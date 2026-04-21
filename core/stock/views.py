from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
import os
from decimal import Decimal
from django.conf import settings
from .models import Product, Category, Subcategory, Warehouse, ProductUnit, Stock, StockMovement
from .serializers import ProductSerializer, CategorySerializer, SubcategorySerializer, WarehouseSerializer, ProductUnitSerializer, StockSerializer, StockMovementSerializer
from users.permissions import IsNotClientPermission
from core.store.models import Store, Branch
from django.db import transaction


class StockMovementPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 100


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsNotClientPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def perform_create(self, serializer):
        # Create the product
        product = serializer.save()
        
        # Create a base stock record with quantity 0 and no warehouse/branch
        Stock.objects.create(
            product=product,
            quantity=0.0000,
            warehouse=None,
            branch=None
        )
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def destroy(self, request, *args, **kwargs):
        """Eliminación lógica: marca el producto como descontinuado"""
        instance = self.get_object()
        instance.status = 'discontinued'
        instance.save()
        return Response({
            'message': 'Producto descontinuado exitosamente',
            'status': 'discontinued'
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['delete'])
    def permanent_delete(self, request, pk=None):
        """Eliminación física permanente del producto"""
        product = self.get_object()
        product.delete()
        return Response({
            'message': 'Producto eliminado permanentemente'
        }, status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        """Reactivar un producto descontinuado"""
        product = self.get_object()
        if product.status != 'discontinued':
            return Response(
                {'error': 'El producto ya está activo'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        product.status = 'active'
        product.save()
        return Response({
            'message': 'Producto reactivado exitosamente',
            'status': 'active'
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload_image(self, request, pk=None):
        """
        Endpoint para subir imágenes de producto al servidor local.
        Soporta hasta 3 imágenes por producto.
        Estructura: media/images/{store}/{sku}/image_1.jpg
        """
        product = self.get_object()
        
        # Determinar qué imagen se está subiendo (image_1, image_2, o image_3)
        image_slot = request.data.get('slot', 'image_1')  # Por defecto image_1
        if image_slot not in ['image_1', 'image_2', 'image_3']:
            return Response(
                {'error': 'Slot de imagen inválido. Use: image_1, image_2, o image_3'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if 'image' not in request.FILES:
            return Response(
                {'error': 'No se encontró archivo de imagen'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            image_file = request.FILES['image']
            
            # Validar tamaño (máximo 5MB)
            if image_file.size > 5 * 1024 * 1024:
                return Response(
                    {'error': 'El archivo de imagen no puede ser mayor a 5MB'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validar tipo
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
            if image_file.content_type not in allowed_types:
                return Response(
                    {'error': 'Solo se permiten archivos JPEG, PNG, GIF y WebP'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Eliminar imagen anterior si existe
            current_image = getattr(product, image_slot)
            if current_image:
                try:
                    # Construir ruta completa del archivo
                    old_image_path = os.path.join(settings.MEDIA_ROOT, str(current_image))
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                except Exception as e:
                    print(f"Error al eliminar imagen anterior: {e}")
            
            # Guardar nueva imagen usando el ImageField
            setattr(product, image_slot, image_file)
            product.save()
            
            # Obtener URL completa de la imagen
            image_url = request.build_absolute_uri(getattr(product, image_slot).url)
            
            return Response({
                'message': f'Imagen {image_slot} subida exitosamente',
                'slot': image_slot,
                'image_url': image_url,
                'all_images': {
                    'image_1': request.build_absolute_uri(product.image_1.url) if product.image_1 else None,
                    'image_2': request.build_absolute_uri(product.image_2.url) if product.image_2 else None,
                    'image_3': request.build_absolute_uri(product.image_3.url) if product.image_3 else None,
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': f'Error al subir imagen: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['delete'])
    def delete_image(self, request, pk=None):
        """
        Endpoint para eliminar imagen de producto del servidor local.
        Puede eliminar una imagen específica o todas.
        """
        product = self.get_object()
        
        # Determinar qué imagen eliminar
        image_slot = request.query_params.get('slot', 'all')  # Por defecto elimina todas
        
        if image_slot not in ['image_1', 'image_2', 'image_3', 'all']:
            return Response(
                {'error': 'Slot de imagen inválido. Use: image_1, image_2, image_3, o all'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            deleted_images = []
            
            # Eliminar imagen específica o todas
            slots_to_delete = ['image_1', 'image_2', 'image_3'] if image_slot == 'all' else [image_slot]
            
            for slot in slots_to_delete:
                current_image = getattr(product, slot)
                
                if current_image:
                    try:
                        # Construir ruta completa del archivo
                        image_path = os.path.join(settings.MEDIA_ROOT, str(current_image))
                        # Eliminar archivo físico si existe
                        if os.path.exists(image_path):
                            os.remove(image_path)
                            deleted_images.append(slot)
                        
                        # Limpiar campo en base de datos
                        setattr(product, slot, None)
                    except Exception as e:
                        print(f"Error al eliminar {slot}: {e}")
            
            if not deleted_images:
                return Response(
                    {'error': 'No hay imágenes para eliminar'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            product.save()
            
            return Response({
                'message': f'Imagen(es) eliminada(s) exitosamente: {", ".join(deleted_images)}',
                'deleted_slots': deleted_images,
                'remaining_images': {
                    'image_1': request.build_absolute_uri(product.image_1.url) if product.image_1 else None,
                    'image_2': request.build_absolute_uri(product.image_2.url) if product.image_2 else None,
                    'image_3': request.build_absolute_uri(product.image_3.url) if product.image_3 else None,
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': f'Error al eliminar imagen: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsNotClientPermission]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs): 
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SubcategoryViewSet(viewsets.ModelViewSet):
    queryset = Subcategory.objects.all()
    serializer_class = SubcategorySerializer
    permission_classes = [IsNotClientPermission]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_classes = [IsNotClientPermission]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        if request.user.role == 'superadmin':
            request.data['store'] = Store.objects.first().id  # Asignar al primer store disponible
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        else:
            return Response(
                {'error': 'Solo superadministradores pueden crear depósitos'},
                status=status.HTTP_403_FORBIDDEN
            )
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Verificar si el depósito tiene stock antes de eliminar
        if instance.stocks.exists():
            return Response(
                {'error': 'No se puede eliminar el depósito porque tiene stock asociado'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        self.perform_destroy(instance)
        return Response({
            'message': 'Depósito eliminado exitosamente'
        }, status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['get'])
    def stock(self, request, pk=None):
        """Obtener el stock del depósito"""
        warehouse = self.get_object()
        stocks = warehouse.stocks.select_related('product').all()
        
        stock_data = [{
            'product_id': stock.product.id,
            'product_sku': stock.product.sku,
            'product_description': stock.product.description,
            'quantity': stock.quantity,
            'updated_at': stock.updated_at
        } for stock in stocks]
        
        return Response({
            'warehouse': WarehouseSerializer(warehouse).data,
            'stock': stock_data,
            'total_items': len(stock_data)
        }, status=status.HTTP_200_OK)


class ProductUnitViewSet(viewsets.ModelViewSet):
    queryset = ProductUnit.objects.all()
    serializer_class = ProductUnitSerializer
    permission_classes = [IsNotClientPermission]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        
        # Filtrar por producto si se proporciona el parámetro 'product'
        product_id = request.query_params.get('product', None)
        
        if product_id is not None:
            prod = Product.objects.get(id=product_id)  # Verificar que el producto exista
            queryset = queryset.filter(product=prod)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StockViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de solo lectura para Stock.
    El stock no puede ser creado, actualizado o eliminado directamente.
    Todas las modificaciones de stock deben realizarse a través de:
    - Órdenes de compra (PurchaseOrder)
    - Órdenes de venta (SalesOrder)
    - Movimientos de stock (StockMovement)
    """
    queryset = Stock.objects.select_related('product', 'warehouse', 'branch').all()
    serializer_class = StockSerializer
    permission_classes = [IsNotClientPermission]
    
    def list(self, request, *args, **kwargs):
        """
        Listar todos los stocks con filtros opcionales.
        Query params:
        - product: ID del producto
        - warehouse: ID del depósito
        - branch: ID de la sucursal
        - low_stock: 'true' para mostrar solo productos con stock bajo
        """
        queryset = self.get_queryset()
        
        # Filtros opcionales
        product_id = request.query_params.get('product', None)
        warehouse_id = request.query_params.get('warehouse', None)
        branch_id = request.query_params.get('branch', None)
        low_stock = request.query_params.get('low_stock', None)
        
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        
        # Filtrar por stock bajo si se solicitó
        if low_stock == 'true':
            filtered_queryset = []
            for stock in queryset:
                if stock.product.safety_stock and stock.quantity < stock.product.safety_stock:
                    filtered_queryset.append(stock)
            queryset = filtered_queryset
        
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'count': len(serializer.data),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
    
    def retrieve(self, request, *args, **kwargs):
        """Obtener un registro de stock específico por ID"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def low_stock_alert(self, request):
        """
        Endpoint para obtener todos los productos con stock por debajo del nivel de seguridad.
        Útil para alertas y notificaciones.
        """
        queryset = self.get_queryset()
        
        low_stock_items = []
        for stock in queryset:
            if stock.product.safety_stock and stock.quantity < stock.product.safety_stock:
                low_stock_items.append({
                    'id': stock.id,
                    'product': {
                        'id': stock.product.id,
                        'sku': stock.product.sku,
                        'description': stock.product.description,
                        'safety_stock': float(stock.product.safety_stock),
                    },
                    'location_name': stock.warehouse.name if stock.warehouse else (stock.branch.name if stock.branch else 'Sin ubicación'),
                    'warehouse': stock.warehouse.name if stock.warehouse else None,
                    'branch': stock.branch.name if stock.branch else None,
                    'current_quantity': float(stock.quantity),
                    'difference': float(stock.product.safety_stock - stock.quantity),
                    'updated_at': stock.updated_at
                })
        
        return Response({
            'count': len(low_stock_items),
            'results': low_stock_items
        }, status=status.HTTP_200_OK)


class StockMovementViewSet(viewsets.ModelViewSet):
    """
    ViewSet para StockMovement.
    Los movimientos de stock pueden ser:
    - Consultados (GET)
    - Creados manualmente para transferencias internas (POST)
    Los movimientos de compras y ventas se crean automáticamente.
    """
    queryset = StockMovement.objects.select_related(
        'product', 
        'warehouse', 
        'branch', 
        'unit_used',
        'sale',
        'purchase'
    ).all().order_by('-date')
    serializer_class = StockMovementSerializer
    permission_classes = [IsNotClientPermission]
    pagination_class = StockMovementPagination
    http_method_names = ['get', 'post', 'head', 'options']  # Solo permitir GET y POST
    
    def create(self, request, *args, **kwargs):
        """
        Crear un movimiento interno de stock.
        Valida que haya stock suficiente y actualiza las ubicaciones.
        """
        data = request.data
        
        # Validar campos requeridos
        required_fields = ['product', 'fromLocationType', 'fromLocation', 'toLocationType', 'toLocation', 'quantity']
        for field in required_fields:
            if field not in data or not data[field]:
                return Response(
                    {'error': f'El campo {field} es requerido'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        try:
            product = Product.objects.get(id=data['product'])
        except Product.DoesNotExist:
            return Response(
                {'error': 'Producto no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        from_type = data['fromLocationType']  # WHA o BRA
        from_id = data['fromLocation']
        to_type = data['toLocationType']  # WHA o BRA
        to_id = data['toLocation']
        quantity = Decimal(str(data['quantity']))
        note = data.get('note', '')
        
        # Validar que origen y destino sean diferentes
        if from_type == to_type and from_id == to_id:
            return Response(
                {'error': 'El origen y destino deben ser diferentes'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validar cantidad
        if quantity <= 0:
            return Response(
                {'error': 'La cantidad debe ser mayor a 0'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener ubicaciones
        from_warehouse = None
        from_branch = None
        to_warehouse = None
        to_branch = None
        
        try:
            if from_type == 'WHA':
                from_warehouse = Warehouse.objects.get(id=from_id)
            else:
                from_branch = Branch.objects.get(id=from_id)
                
            if to_type == 'WHA':
                to_warehouse = Warehouse.objects.get(id=to_id)
            else:
                to_branch = Branch.objects.get(id=to_id)
        except (Warehouse.DoesNotExist, Branch.DoesNotExist):
            return Response(
                {'error': 'Ubicación no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Validar stock en origen
        try:
            if from_type == 'WHA':
                stock_origin = Stock.objects.get(product=product, warehouse=from_warehouse)
            else:
                stock_origin = Stock.objects.get(product=product, branch=from_branch)
                
            if stock_origin.quantity < quantity:
                location_name = from_warehouse.name if from_warehouse else from_branch.name
                return Response(
                    {
                        'error': f'Stock insuficiente en {location_name}',
                        'detail': f'Stock disponible: {stock_origin.quantity} {product.base_unit_name}, solicitado: {quantity} {product.base_unit_name}'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Stock.DoesNotExist:
            location_name = from_warehouse.name if from_warehouse else from_branch.name
            return Response(
                {'error': f'No hay stock de {product.description} en {location_name}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            # Crear o actualizar stock en destino
            if to_type == 'WHA':
                stock_dest, created = Stock.objects.get_or_create(
                    product=product,
                    warehouse=to_warehouse,
                    defaults={'quantity': 0}
                )
            else:
                stock_dest, created = Stock.objects.get_or_create(
                    product=product,
                    branch=to_branch,
                    defaults={'quantity': 0}
                )
        
            # Actualizar cantidades
            stock_origin.quantity -= quantity
            stock_origin.save()
            
            stock_dest.quantity += quantity
            stock_dest.save()
            
            # Determinar qué ubicación usar para el movimiento (usamos la que sea warehouse o branch)
            movement_warehouse = from_warehouse or to_warehouse
            movement_branch = from_branch or to_branch
            
            # Crear el movimiento de stock
            movement = StockMovement.objects.create(
                product=product,
                warehouse=movement_warehouse,
                branch=movement_branch,
                from_location=from_type,
                to_location=to_type,
                movement_type='OUT' if from_type in ['WHA', 'BRA'] else 'IN',
                quantity=quantity,
                status='REC',  # Movimientos internos se marcan como recibidos inmediatamente
                note=note,
                conversion_factor_at_moment=Decimal('1.0')
            )
            
            # Agregar comentario al movimiento
            from_name = from_warehouse.name if from_warehouse else from_branch.name
            to_name = to_warehouse.name if to_warehouse else to_branch.name
            movement.add_comment(
                f'Movimiento interno: {quantity} {product.base_unit_name} de {from_name} a {to_name}',
                status_before=None,
                user=request.user
            )
            
            serializer = self.get_serializer(movement)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def list(self, request, *args, **kwargs):
        """
        Listar todos los movimientos de stock con filtros opcionales y paginación.
        Query params:
        - product: ID del producto
        - warehouse: ID del depósito
        - branch: ID de la sucursal
        - movement_type: Tipo de movimiento ('IN' o 'OUT')
        - status: Estado del movimiento ('PEN', 'TRAN', 'REC', 'CAN')
        - from_location: Origen del movimiento ('PUR', 'SAL', 'WHA', 'BRA', 'MOV')
        - to_location: Destino del movimiento ('PUR', 'SAL', 'WHA', 'BRA', 'MOV')
        - sale: ID de la orden de venta
        - purchase: ID de la orden de compra
        - date_from: Fecha desde (formato: YYYY-MM-DD)
        - date_to: Fecha hasta (formato: YYYY-MM-DD)
        - page: Número de página (default: 1)
        - page_size: Tamaño de página (default: 5, max: 100)
        """
        queryset = self.get_queryset()
        
        # Filtros opcionales
        product_id = request.query_params.get('product', None)
        warehouse_id = request.query_params.get('warehouse', None)
        branch_id = request.query_params.get('branch', None)
        movement_type = request.query_params.get('movement_type', None)
        status_filter = request.query_params.get('status', None)
        from_location = request.query_params.get('from_location', None)
        to_location = request.query_params.get('to_location', None)
        sale_id = request.query_params.get('sale', None)
        purchase_id = request.query_params.get('purchase', None)
        date_from = request.query_params.get('date_from', None)
        date_to = request.query_params.get('date_to', None)
        
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        
        if movement_type and movement_type in ['IN', 'OUT']:
            queryset = queryset.filter(movement_type=movement_type)
        
        if status_filter and status_filter in ['PEN', 'TRAN', 'REC', 'CAN']:
            queryset = queryset.filter(status=status_filter)
        
        if from_location and from_location in ['PUR', 'SAL', 'WHA', 'BRA', 'MOV']:
            queryset = queryset.filter(from_location=from_location)
        
        if to_location and to_location in ['PUR', 'SAL', 'WHA', 'BRA', 'MOV']:
            queryset = queryset.filter(to_location=to_location)
        
        if sale_id:
            queryset = queryset.filter(sale_id=sale_id)
        
        if purchase_id:
            queryset = queryset.filter(purchase_id=purchase_id)
        
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        
        # Aplicar paginación
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'count': len(serializer.data),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
    
    def retrieve(self, request, *args, **kwargs):
        """Obtener un movimiento de stock específico por ID"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def by_product(self, request):
        """
        Obtener todos los movimientos de un producto específico.
        Query param requerido: product_id
        """
        product_id = request.query_params.get('product_id', None)
        
        if not product_id:
            return Response(
                {'error': 'Se requiere el parámetro product_id'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = self.get_queryset().filter(product_id=product_id)
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'product_id': product_id,
            'count': len(serializer.data),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def by_location(self, request):
        """
        Obtener todos los movimientos de una ubicación específica (warehouse o branch).
        Query params: warehouse_id o branch_id (uno de los dos requerido)
        """
        warehouse_id = request.query_params.get('warehouse_id', None)
        branch_id = request.query_params.get('branch_id', None)
        
        if not warehouse_id and not branch_id:
            return Response(
                {'error': 'Se requiere warehouse_id o branch_id'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = self.get_queryset()
        
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        elif branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'warehouse_id': warehouse_id,
            'branch_id': branch_id,
            'count': len(serializer.data),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def recent(self, request):
        """
        Obtener los movimientos más recientes.
        Query param: limit (default: 50, max: 100)
        """
        limit = int(request.query_params.get('limit', 50))
        limit = min(limit, 100)  # Máximo 100 registros
        
        queryset = self.get_queryset()[:limit]
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'limit': limit,
            'count': len(serializer.data),
            'results': serializer.data
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def pending(self, request):
        """
        Obtener todos los movimientos pendientes (status='PEN' o 'TRAN').
        """
        queryset = self.get_queryset().filter(status__in=['PEN', 'TRAN'])
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'count': len(serializer.data),
            'results': serializer.data
        }, status=status.HTTP_200_OK)