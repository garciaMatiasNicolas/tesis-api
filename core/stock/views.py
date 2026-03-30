from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.decorators import action
from .models import Product, Category, Subcategory, Warehouse, ProductUnit, Stock, StockMovement
from .serializers import ProductSerializer, CategorySerializer, SubcategorySerializer, WarehouseSerializer, ProductUnitSerializer, StockSerializer, StockMovementSerializer
from users.permissions import IsNotClientPermission
from core.store.models import Store


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
        """Endpoint específico para subir imagen de producto"""
        product = self.get_object()
        
        if 'image' not in request.FILES:
            return Response(
                {'error': 'No se encontró archivo de imagen'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Eliminar imagen anterior si existe
        if product.image:
            product.image.delete(save=False)
        
        # Asignar nueva imagen
        product.image = request.FILES['image']
        
        # Validar usando el serializer
        serializer = self.get_serializer(product, data={'image': request.FILES['image']}, partial=True)
        serializer.is_valid(raise_exception=True)
        product.save()
        
        return Response({
            'message': 'Imagen subida exitosamente',
            'image_url': product.image.url
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['delete'])
    def delete_image(self, request, pk=None):
        """Endpoint para eliminar imagen de producto"""
        product = self.get_object()
        
        if not product.image:
            return Response(
                {'error': 'El producto no tiene imagen'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Eliminar archivo físico
        product.image.delete(save=False)
        product.image = None
        product.save()
        
        return Response({
            'message': 'Imagen eliminada exitosamente'
        }, status=status.HTTP_200_OK)


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


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de solo lectura para StockMovement.
    Los movimientos de stock no pueden ser creados, actualizados o eliminados directamente desde aquí.
    Se crean automáticamente a través de:
    - Órdenes de compra (PurchaseOrder)
    - Órdenes de venta (SalesOrder)
    - Transferencias entre ubicaciones
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
    
    def list(self, request, *args, **kwargs):
        """
        Listar todos los movimientos de stock con filtros opcionales.
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