from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action, api_view, permission_classes
from .models import SalesOrder, PurchaseOrder, SalesItem
from django.db import transaction
from django.db.models import Sum, Count, F, Q, DecimalField
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from datetime import datetime, timedelta
from decimal import Decimal
from .serializer import SalesOrderSerializer, PurchaseOrderSerializer
from core.crm.models import Customer
from core.stock.models import Stock, Product, StockMovement
from django.http import FileResponse, HttpResponse
from .pdf_generator import OrderPDFGenerator
import os
import tempfile


class SalesOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar órdenes de venta (SalesOrder).
    
    Flujo de estados:
    - draft: Presupuesto (no afecta stock)
    - pending: Reserva stock (crea movimiento en TRAN)
    - processing: En preparación (stock ya reservado)
    - completed: Entregado y pagado (movimiento en REC, egreso de stock)
    - cancelled: Cancelado (libera stock si estaba en pending/processing)
    """
    queryset = SalesOrder.objects.all()
    serializer_class = SalesOrderSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Filtrar órdenes por parámetros opcionales en la URL
        """
        queryset = super().get_queryset()
    
        # Filtro por was_delivered
        was_delivered = self.request.query_params.get('was_delivered', None)
        if was_delivered is not None:
            queryset = queryset.filter(was_delivered=was_delivered.lower() == 'true')
        
        # Filtro por canal de venta
        channel = self.request.query_params.get('sales_channel', None)
        if channel:
            queryset = queryset.filter(sales_channel=channel)
        
        # Filtro por cliente
        customer_id = self.request.query_params.get('customer_id', None)
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        
        # Ordenar por fecha de creación (más recientes primero)
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """
        Al crear una orden, asignar el empleado actual si está disponible
        y actualizar información del cliente.
        Si el status es 'pending', crear movimientos de stock.
        """
        from core.stock.models import Stock, StockMovement
        from core.store.models import Branch
        from datetime import datetime, timezone
        from decimal import Decimal
        
        employee = None
        if hasattr(self.request.user, 'employee'):
            employee = self.request.user.employee
        
        # Guardar la orden de venta
        sales_order = serializer.save(employee=employee)
        
        # Actualizar información del cliente
        if sales_order.customer:
            customer = sales_order.customer
            customer.last_purchase_date = sales_order.created_at
            if sales_order.was_payed:
                customer.total_spent += sales_order.total_price
            customer.save()
        
        # Si se crea directamente en estado 'pending', crear movimientos de stock
        if sales_order.status == 'pending':
            self._create_stock_movements_for_pending(sales_order)
    
    def _create_stock_movements_for_pending(self, sales_order):
        """
        Crear movimientos de stock en estado TRAN (reserva) cuando la orden pasa a pending
        """
        from core.stock.models import Stock, StockMovement
        from core.store.models import Branch
        from datetime import datetime, timezone
        from decimal import Decimal
        from rest_framework.exceptions import ValidationError
        
        origin_branch = sales_order.branch_origin
        origin_warehouse = sales_order.warehouse_origin
        
        # Si no hay origen especificado, validar que se proporcione uno
        if not origin_branch and not origin_warehouse:
            employee = sales_order.employee
            
            if employee and employee.branch:
                # Usar sucursal del empleado si está disponible
                origin_branch = employee.branch
            else:
                # Si no hay empleado o no tiene sucursal, requerir origen explícito
                raise ValidationError({
                    'branch_origin': 'Debe especificar una sucursal o depósito de origen para esta orden.',
                    'warehouse_origin': 'Debe especificar una sucursal o depósito de origen para esta orden.',
                    'requires_origin': True
                })

        if origin_branch or origin_warehouse:
            current_time = datetime.now(timezone.utc).isoformat()
            user_info = f'{self.request.user.first_name} {self.request.user.last_name}' if self.request.user else 'Sistema'
            user_id = self.request.user.id if self.request.user else None
            
            # Verificar que no existan movimientos previos
            if not sales_order.stock_movements.exists():
                items = sales_order.sales_items.select_related('product', 'product_unit').all()
                stock_movements_to_create = []
                
                for item in items:
                    product = item.product
                    quantity = item.quantity
                    product_unit = item.product_unit
                    
                    conversion_factor = Decimal('1')
                    if product_unit:
                        conversion_factor = Decimal(str(product_unit.conversion_factor))
                    
                    real_quantity = Decimal(str(quantity)) * conversion_factor
                    
                    # Inicializar stock si no existe
                    if origin_warehouse:
                        Stock.objects.get_or_create(
                            product=product,
                            warehouse=origin_warehouse,
                            branch=None,
                            defaults={'quantity': 0}
                        )
                        location_name = f"depósito: {origin_warehouse.name}"
                        from_location = 'WHA'
                    else:
                        Stock.objects.get_or_create(
                            product=product,
                            branch=origin_branch,
                            warehouse=None,
                            defaults={'quantity': 0}
                        )
                        location_name = f"sucursal: {origin_branch.name}"
                        from_location = 'BRA'
                    
                    comment_data = {
                        'date': current_time,
                        'comment': f'Orden de venta #{sales_order.id} en estado pendiente; reserva de {real_quantity} unidades desde {location_name}.',
                        'status_before': 'draft',
                        'status_after': 'TRAN',
                        'user': user_info,
                        'user_id': user_id
                    }
                    
                    stock_movements_to_create.append(StockMovement(
                        product=product,
                        branch=origin_branch if origin_branch else None,
                        warehouse=origin_warehouse if origin_warehouse else None,
                        status='TRAN',
                        from_location=from_location,
                        to_location='SAL',
                        movement_type='OUT',
                        quantity=real_quantity,
                        unit_used=product_unit,
                        conversion_factor_at_moment=conversion_factor,
                        sale=sales_order,
                        note=f'Reserva para orden de venta #{sales_order.id}',
                        comments=[comment_data]
                    ))
                
                if stock_movements_to_create:
                    StockMovement.objects.bulk_create(stock_movements_to_create)
    
    def _complete_stock_movements(self, sales_order):
        """
        Completar movimientos de stock (egreso real) cuando la orden se completa
        """
        from core.stock.models import Stock
        from django.db.models import F
        from datetime import datetime, timezone
        
        current_time = datetime.now(timezone.utc).isoformat()
        user_info = f'{self.request.user.first_name} {self.request.user.last_name}' if self.request.user else 'Sistema'
        user_id = self.request.user.id if self.request.user else None
        
        stock_movements = sales_order.stock_movements.select_related('product').all()
        
        for stock_movement in stock_movements:
            if stock_movement.status == 'TRAN':
                # Actualizar stock real
                if stock_movement.warehouse:
                    Stock.objects.filter(
                        product=stock_movement.product,
                        warehouse=stock_movement.warehouse,
                        branch=None
                    ).update(quantity=F('quantity') - stock_movement.quantity)
                    location_name = f"depósito: {stock_movement.warehouse.name}"
                else:
                    Stock.objects.filter(
                        product=stock_movement.product,
                        branch=stock_movement.branch,
                        warehouse=None
                    ).update(quantity=F('quantity') - stock_movement.quantity)
                    location_name = f"sucursal: {stock_movement.branch.name}"
                
                # Actualizar estado del movimiento
                comment_data = {
                    'date': current_time,
                    'comment': f'Orden de venta #{sales_order.id} completada; egreso confirmado de {round(stock_movement.quantity)} unidades desde {location_name}.',
                    'status_before': 'TRAN',
                    'status_after': 'REC',
                    'user': user_info,
                    'user_id': user_id
                }
                
                stock_movement.status = 'REC'
                if not stock_movement.comments:
                    stock_movement.comments = []
                stock_movement.comments.append(comment_data)
                stock_movement.save()
    
    def _cancel_stock_movements(self, sales_order):
        """
        Cancelar movimientos de stock cuando la orden se cancela
        """
        from datetime import datetime, timezone
        
        current_time = datetime.now(timezone.utc).isoformat()
        user_info = f'{self.request.user.first_name} {self.request.user.last_name}' if self.request.user else 'Sistema'
        user_id = self.request.user.id if self.request.user else None
        
        stock_movements = sales_order.stock_movements.all()
        
        for stock_movement in stock_movements:
            if stock_movement.status == 'TRAN':
                location_name = f"depósito: {stock_movement.warehouse.name}" if stock_movement.warehouse else f"sucursal: {stock_movement.branch.name}"
                
                comment_data = {
                    'date': current_time,
                    'comment': f'Orden de venta #{sales_order.id} cancelada; liberación de {stock_movement.quantity} unidades reservadas en {location_name}.',
                    'status_before': 'TRAN',
                    'status_after': 'CAN',
                    'user': user_info,
                    'user_id': user_id
                }
                
                stock_movement.status = 'CAN'
                if not stock_movement.comments:
                    stock_movement.comments = []
                stock_movement.comments.append(comment_data)
                stock_movement.save()
    
    def perform_update(self, serializer):
        """
        Al actualizar una orden, gestionar el flujo de estados y stock
        """
        instance = self.get_object()
        old_status = instance.status
        old_was_payed = instance.was_payed
        old_total_price = instance.total_price
        
        # Guardar la orden actualizada
        sales_order = serializer.save()
        new_status = sales_order.status
        
        # Actualizar información del cliente si es necesario
        if sales_order.customer:
            customer = sales_order.customer
            
            # Caso 1: La orden cambió de no pagada a pagada
            if not old_was_payed and sales_order.was_payed:
                customer.total_spent += sales_order.total_price
                customer.save()
            
            # Caso 2: La orden cambió de pagada a no pagada
            elif old_was_payed and not sales_order.was_payed:
                customer.total_spent -= old_total_price
                customer.save()
            
            # Caso 3: La orden ya estaba pagada y cambió el precio
            elif old_was_payed and sales_order.was_payed and old_total_price != sales_order.total_price:
                customer.total_spent = customer.total_spent - old_total_price + sales_order.total_price
                customer.save()
        
        # Gestionar cambios de estado
        # De draft a pending: crear movimientos de stock (reserva)
        if old_status == 'draft' and new_status == 'pending':
            self._create_stock_movements_for_pending(sales_order)
        
        # A completed: confirmar egreso de stock
        elif new_status == 'completed' and old_status != 'completed':
            self._complete_stock_movements(sales_order)
        
        # A cancelled: liberar stock reservado
        elif new_status == 'cancelled' and old_status != 'cancelled':
            self._cancel_stock_movements(sales_order)
    
    def destroy(self, request, *args, **kwargs):
        """
        Eliminar una orden de venta y ajustar el total_spent del cliente
        """
        instance = self.get_object()
        
        # Actualizar el total_spent del cliente antes de eliminar
        if instance.customer and instance.was_payed:
            customer = instance.customer
            customer.total_spent -= instance.total_price
            customer.save()
        
        self.perform_destroy(instance)
        return Response(
            {'message': 'Orden de venta eliminada exitosamente'},
            status=status.HTTP_204_NO_CONTENT
        )
    
    @action(detail=False, methods=['get'], url_path='my-orders')
    def my_orders(self, request):
        """
        Endpoint para que los clientes vean solo sus propias órdenes.
        GET /billing/sales-orders/my-orders/
        """
        try:
            # Verificar que el usuario tenga un Customer asociado
            customer = Customer.objects.get(user=request.user)
        except Customer.DoesNotExist:
            return Response(
                {'error': 'No se encontró un cliente asociado a este usuario'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Filtrar órdenes solo del cliente autenticado
        orders = SalesOrder.objects.filter(customer=customer).order_by('-created_at')
        
        # Serializar y devolver
        serializer = self.get_serializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['get'], url_path='download-pdf')
    def download_pdf(self, request, pk=None):
        """
        Generar y descargar PDF de la orden de venta
        GET /api/sales-orders/{id}/download-pdf/
        """
        order = self.get_object()
        
        try:
            # Crear archivo temporal
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_filename = temp_file.name
            
            # Generar PDF
            generator = OrderPDFGenerator(order, order_type='sales')
            generator.generate(temp_filename)
            
            # Leer archivo y enviarlo como respuesta
            with open(temp_filename, 'rb') as pdf_file:
                response = HttpResponse(pdf_file.read(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="orden_venta_{order.id:08d}.pdf"'
            
            # Eliminar archivo temporal
            os.unlink(temp_filename)
            
            return response
            
        except Exception as e:
            return Response(
                {'error': f'Error al generar PDF: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar órdenes de compra (PurchaseOrder).
    
    Permite:
    - Listar todas las órdenes de compra (GET /api/purchase-orders/)
    - Crear una nueva orden de compra (POST /api/purchase-orders/)
    - Obtener detalle de una orden (GET /api/purchase-orders/{id}/)
    - Actualizar una orden de compra (PUT/PATCH /api/purchase-orders/{id}/)
    - Eliminar una orden de compra (DELETE /api/purchase-orders/{id}/)
    """
    queryset = PurchaseOrder.objects.all()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Filtrar órdenes por parámetros opcionales en la URL
        """
        queryset = super().get_queryset()
    
        # Filtro por status
        status_param = self.request.query_params.get('status', None)
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        # Filtro por proveedor
        supplier_id = self.request.query_params.get('supplier_id', None)
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)
        
        # Filtro por was_payed
        was_payed = self.request.query_params.get('was_payed', None)
        if was_payed is not None:
            queryset = queryset.filter(was_payed=was_payed.lower() == 'true')
        
        # Filtro por received
        received = self.request.query_params.get('received', None)
        if received is not None:
            queryset = queryset.filter(received=received.lower() == 'true')
        
        # Ordenar por fecha de creación (más recientes primero)
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """
        Al crear una orden, asignar el empleado actual si está disponible
        y asignar sucursal por defecto si no hay destino
        """
        from core.store.models import Branch
        from datetime import datetime, timezone
        created_by = None
        
        if (self.request.user.role in ['employee', 'manager', 'superadmin']):
            created_by = self.request.user

        # Si no hay destino especificado, asignar la sucursal casa central (la primera)
        warehouse_destination_id = serializer.validated_data.get('warehouse_destination_id')
        branch_destination_id = serializer.validated_data.get('branch_destination_id')
        
        if not warehouse_destination_id and not branch_destination_id:
            # Buscar la sucursal casa central (la primera o la que tenga nombre "Sucursal Principal")
            default_branch = Branch.objects.filter(name__icontains='Sucursal Principal').first()
            if not default_branch:
                default_branch = Branch.objects.first()
            
            if default_branch:
                purchase_order = serializer.save(created_by=created_by, branch_destination=default_branch)
            else:
                purchase_order = serializer.save(created_by=created_by)
        else:
            purchase_order = serializer.save(created_by=created_by)

        user_info = f'{self.request.user.first_name} {self.request.user.last_name}' if self.request.user else 'Sistema'
        current_time = datetime.now(timezone.utc).isoformat()
        comment_data = {
            'comment': f'Orden de compra creada por {user_info}',
            'created_at': current_time
        }

        if not purchase_order.comments:
            purchase_order.comments = []
        purchase_order.comments.append(comment_data)
        purchase_order.save(update_fields=['comments'])
    
    def perform_update(self, serializer):
        """
        Al actualizar una orden, gestionar el flujo de estados y stock
        """
        from core.stock.models import Stock, StockMovement
        from django.db.models import F
        from datetime import datetime, timezone
        from decimal import Decimal
        
        with transaction.atomic():
            instance = self.get_object()
            old_status = instance.status
            old_was_payed = instance.was_payed
            old_received = instance.received
            user_comment = serializer.validated_data.get('comment')
            updated_from = {}
            fields_updated = []

            for field, new_value in serializer.validated_data.items():
                if field in ['comment', 'items']:
                    continue
                old_value = getattr(instance, field, None)
                if old_value != new_value:
                    fields_updated.append(field)
                    updated_from[field] = {str(old_value): str(new_value)}
        
            # Guardar la orden actualizada
            purchase_order = serializer.save()
            
            # Obtener nuevos valores
            new_status = purchase_order.status
            new_was_payed = purchase_order.was_payed
            new_received = purchase_order.received

            # Determinar el destino
            destination_warehouse = purchase_order.warehouse_destination
            destination_branch = purchase_order.branch_destination
            destination_name = destination_warehouse.name if destination_warehouse else (destination_branch.name if destination_branch else 'Sin destino')
            destination_type = 'depósito' if destination_warehouse else 'sucursal'

            # Preparar datos del usuario para comentarios
            user_info = f'{self.request.user.first_name} {self.request.user.last_name}' if self.request.user else 'Sistema'
            user_id = self.request.user.id if self.request.user else None
            current_time = datetime.now(timezone.utc).isoformat()

            # Usar comentario del usuario si no está vacío, sino usar texto por defecto
            final_comment = user_comment.strip() if user_comment else ''
            comment_data = {
                'fields_updated': fields_updated,
                'updated_from': updated_from,
                'comment': final_comment or f'Orden de compra actualizada por {user_info}',
                'created_at': current_time
            }

            if not purchase_order.comments:
                purchase_order.comments = []
            purchase_order.comments.append(comment_data)
            purchase_order.save(update_fields=['comments'])

            # Gestionar cambios de estado
            # 1) De draft a pending: crear movimientos de stock en TRAN
            if old_status == 'draft' and new_status == 'pending':
                if destination_warehouse or destination_branch:
                    # Evitar duplicados si ya existen movimientos para esta orden
                    if not purchase_order.stock_movements.exists():
                        # Cargar items con relaciones en una sola query
                        items = purchase_order.items.select_related('product', 'product_unit').all()
                        
                        # Preparar lista de movimientos para bulk_create
                        stock_movements_to_create = []
                        stocks_to_initialize = {}
                        
                        for item in items:
                            product = item.product
                            quantity = item.quantity
                            product_unit = item.product_unit
                            
                            # Calcular conversion_factor
                            conversion_factor = Decimal('1')
                            if product_unit:
                                conversion_factor = Decimal(str(product_unit.conversion_factor))
                            
                            # Cantidad real en unidad base
                            real_quantity = Decimal(str(quantity)) * conversion_factor

                            # Acumular para inicializar stock en destino
                            if product.id not in stocks_to_initialize:
                                stocks_to_initialize[product.id] = True

                            # Preparar comentario
                            movement_comment_data = {
                                'date': current_time,
                                'comment': f'Orden de compra #{purchase_order.id} pendiente; en espera de pago y recepción en {destination_type}: {destination_name}.',
                                'status_before': 'draft',
                                'status_after': 'TRAN',
                                'user': user_info,
                                'user_id': user_id
                            }

                            # Crear StockMovement en estado TRAN (en tránsito)
                            stock_movements_to_create.append(StockMovement(
                                product=product,
                                warehouse=destination_warehouse if destination_warehouse else None,
                                branch=destination_branch if destination_branch else None,
                                status='TRAN',
                                from_location='PUR',
                                to_location='WHA' if destination_warehouse else 'BRA',
                                movement_type='IN',
                                quantity=real_quantity,
                                unit_used=product_unit,
                                conversion_factor_at_moment=conversion_factor,
                                purchase=purchase_order,
                                note=f'Orden de compra #{purchase_order.id} pendiente',
                                comments=[movement_comment_data]
                            ))
                        
                        # Crear todos los movimientos en una sola operación
                        if stock_movements_to_create:
                            StockMovement.objects.bulk_create(stock_movements_to_create)

                        # Inicializar stock en destino y eliminar stock cero sin ubicación
                        for product_id in stocks_to_initialize.keys():
                            zero_stocks = Stock.objects.filter(
                                product_id=product_id,
                                warehouse=None,
                                branch=None,
                                quantity=0
                            )
                            if zero_stocks.exists():
                                zero_stocks.delete()

                            if destination_warehouse:
                                Stock.objects.get_or_create(
                                    product_id=product_id,
                                    warehouse=destination_warehouse,
                                    branch=None,
                                    defaults={'quantity': 0}
                                )
                            elif destination_branch:
                                Stock.objects.get_or_create(
                                    product_id=product_id,
                                    branch=destination_branch,
                                    warehouse=None,
                                    defaults={'quantity': 0}
                                )

            # 2) De pending a completed: confirmar ingreso de stock
            elif new_status == 'completed' and old_status != 'completed':
                if destination_warehouse or destination_branch:
                    # Cargar items con relaciones en una sola query
                    items = purchase_order.items.select_related('product', 'product_unit').all()
                    
                    # Preparar datos para actualización bulk
                    stocks_to_update = {}
                    stock_movements_to_update = []
                    
                    for item in items:
                        product = item.product
                        quantity = item.quantity
                        product_unit = item.product_unit
                        
                        # Calcular conversion_factor
                        conversion_factor = Decimal('1')
                        if product_unit:
                            conversion_factor = Decimal(str(product_unit.conversion_factor))
                        
                        # Cantidad real en unidad base
                        real_quantity = Decimal(str(quantity)) * conversion_factor
                        
                        # Acumular cantidades por producto para actualización bulk
                        if product.id not in stocks_to_update:
                            stocks_to_update[product.id] = {
                                'product': product,
                                'quantity': real_quantity
                            }
                        else:
                            stocks_to_update[product.id]['quantity'] += real_quantity
                    
                    # Actualizar stocks usando F() expressions para evitar race conditions
                    for product_id, stock_data in stocks_to_update.items():
                        stocks = Stock.objects.filter(
                            product_id=product_id,
                            warehouse=None,
                            branch=None,
                            quantity=0
                        )  

                        if stocks.exists():
                            stocks.delete()  # Eliminar stock cero sin ubicación

                        if destination_warehouse:
                            updated = Stock.objects.filter(
                                product_id=product_id,
                                warehouse=destination_warehouse,
                                branch=None
                            ).update(quantity=F('quantity') + stock_data['quantity'])

                            if updated == 0:
                                Stock.objects.create(
                                    product_id=product_id,
                                    warehouse=destination_warehouse,
                                    branch=None,
                                    quantity=stock_data['quantity']
                                )
                        
                        elif destination_branch:
                            updated = Stock.objects.filter(
                                product_id=product_id,
                                branch=destination_branch,
                                warehouse=None
                            ).update(quantity=F('quantity') + stock_data['quantity'])

                            if updated == 0:
                                Stock.objects.create(
                                    product_id=product_id,
                                    branch=destination_branch,
                                    warehouse=None,
                                    quantity=stock_data['quantity']
                                )
                    
                    # Actualizar StockMovements a estado REC
                    stock_movements = purchase_order.stock_movements.select_related('product').all()
                    
                    for stock_movement in stock_movements:
                        product_desc = stock_movement.product.description
                        real_qty = stock_movement.quantity
                        
                        movement_comment_data = {
                            'date': current_time,
                            'comment': f'Orden de compra #{purchase_order.id} completada; ingreso de {real_qty} unidades de {product_desc} al {destination_type}: {destination_name}.',
                            'status_before': 'TRAN',
                            'status_after': 'REC',
                            'user': user_info,
                            'user_id': user_id
                        }
                        
                        stock_movement.status = 'REC'
                        if not stock_movement.comments:
                            stock_movement.comments = []
                        stock_movement.comments.append(movement_comment_data)
                        stock_movements_to_update.append(stock_movement)
                    
                    # Bulk update de movimientos
                    if stock_movements_to_update:
                        StockMovement.objects.bulk_update(stock_movements_to_update, ['status', 'comments'])
            
            # 4) A cancelled: cancelar movimientos de stock
            elif new_status == 'cancelled' and old_status != 'cancelled':
                stock_movements = purchase_order.stock_movements.select_for_update().all()
                
                if stock_movements:
                    # Preparar comentario
                    movement_comment_data = {
                        'date': current_time,
                        'comment': f'Orden de compra #{purchase_order.id} cancelada; el ingreso de stock ha sido cancelado.',
                        'status_before': old_status,
                        'status_after': 'CAN',
                        'user': user_info,
                        'user_id': user_id
                    }
                    
                    # Actualizar todos en lote
                    movements_to_update = []
                    for stock_movement in stock_movements:
                        stock_movement.status = 'CAN'
                        if not stock_movement.comments:
                            stock_movement.comments = []
                        stock_movement.comments.append(movement_comment_data)
                        movements_to_update.append(stock_movement)
                    
                    # Bulk update
                    StockMovement.objects.bulk_update(movements_to_update, ['status', 'comments'])

    
    def destroy(self, request, *args, **kwargs):
        """
        Eliminar una orden de compra
        """
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {'message': 'Orden de compra eliminada exitosamente'},
            status=status.HTTP_204_NO_CONTENT
        )
    
    @action(detail=True, methods=['get'], url_path='download-pdf')
    def download_pdf(self, request, pk=None):
        """
        Generar y descargar PDF de la orden de compra
        GET /api/purchase-orders/{id}/download-pdf/
        """
        order = self.get_object()
        
        try:
            # Crear archivo temporal
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_filename = temp_file.name
            
            # Generar PDF
            generator = OrderPDFGenerator(order, order_type='purchase')
            generator.generate(temp_filename)
            
            # Leer archivo y enviarlo como respuesta
            with open(temp_filename, 'rb') as pdf_file:
                response = HttpResponse(pdf_file.read(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="orden_compra_{order.id:08d}.pdf"'
            
            # Eliminar archivo temporal
            os.unlink(temp_filename)
            
            return response
            
        except Exception as e:
            return Response(
                {'error': f'Error al generar PDF: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================================
# ESTADÍSTICAS Y DASHBOARD
# ============================================================================

def _parse_date_range(request):
    """Parse date_from/date_to query params (YYYY-MM-DD). Defaults to current month."""
    from django.utils import timezone as tz
    today = tz.now()
    date_from_str = request.query_params.get('date_from', None)
    date_to_str = request.query_params.get('date_to', None)

    if date_from_str and date_to_str:
        try:
            date_from = tz.make_aware(datetime.strptime(date_from_str, '%Y-%m-%d'))
            date_to = tz.make_aware(
                datetime.strptime(date_to_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            )
            return date_from, date_to
        except ValueError:
            pass

    date_from = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return date_from, today


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stats_overview(request):
    """
    GET /api/billing/stats/overview/
    Params:
      date_from, date_to            – YYYY-MM-DD, defaults to current month
      comparison_mode               – previous_period (default) | same_period_last_year
      category_id, subcategory_id, product_id, supplier_id  – group filter
    """
    date_from, date_to = _parse_date_range(request)

    category_id    = request.query_params.get('category_id')
    subcategory_id = request.query_params.get('subcategory_id')
    product_id     = request.query_params.get('product_id')
    supplier_id    = request.query_params.get('supplier_id')
    has_group      = any([category_id, subcategory_id, product_id, supplier_id])

    # Comparison period
    comparison_mode = request.query_params.get('comparison_mode', 'previous_period')
    if comparison_mode == 'same_period_last_year':
        try:
            prev_date_from = date_from.replace(year=date_from.year - 1)
            prev_date_to   = date_to.replace(year=date_to.year - 1)
        except ValueError:
            prev_date_from = date_from - timedelta(days=365)
            prev_date_to   = date_to - timedelta(days=365)
    else:
        delta          = date_to - date_from
        prev_date_to   = date_from
        prev_date_from = prev_date_to - delta

    # Build SalesItem Q for a given date window + group filter
    def _item_q(df, dt):
        q = Q(
            sales_order__created_at__gte=df,
            sales_order__created_at__lte=dt,
            sales_order__status__in=['pending', 'processing', 'completed'],
        )
        if category_id:    q &= Q(product__category_id=category_id)
        if subcategory_id: q &= Q(product__subcategory_id=subcategory_id)
        if product_id:     q &= Q(product_id=product_id)
        if supplier_id:    q &= Q(product__supplier_id=supplier_id)
        return q

    # Sales aggregation
    if has_group:
        # Item-level revenue (avoids counting non-matching items in the order total)
        sales_cur = SalesItem.objects.filter(_item_q(date_from, date_to)).aggregate(
            total=Sum(F('quantity') * F('unit_price'), output_field=DecimalField()),
            count=Count('sales_order_id', distinct=True),
        )
        sales_prv = SalesItem.objects.filter(_item_q(prev_date_from, prev_date_to)).aggregate(
            total=Sum(F('quantity') * F('unit_price'), output_field=DecimalField()),
            count=Count('sales_order_id', distinct=True),
        )
    else:
        sales_cur = SalesOrder.objects.filter(
            created_at__gte=date_from, created_at__lte=date_to,
            status__in=['pending', 'processing', 'completed'],
        ).aggregate(total=Sum('total_price'), count=Count('id'))
        sales_prv = SalesOrder.objects.filter(
            created_at__gte=prev_date_from, created_at__lt=prev_date_to,
            status__in=['pending', 'processing', 'completed'],
        ).aggregate(total=Sum('total_price'), count=Count('id'))

    current_sales  = sales_cur['total'] or Decimal('0')
    last_sales     = sales_prv['total'] or Decimal('0')
    sales_trend    = float(((current_sales - last_sales) / last_sales) * 100) if last_sales else 0
    current_orders = sales_cur['count'] or 0
    last_orders    = sales_prv['count'] or 0
    orders_trend   = ((current_orders - last_orders) / last_orders) * 100 if last_orders else 0

    # Purchase aggregation
    def _purchase_q(df, dt):
        q = Q(created_at__gte=df, created_at__lte=dt, status__in=['pending', 'completed'])
        if supplier_id:    q &= Q(supplier_id=supplier_id)
        elif category_id:  q &= Q(items__product__category_id=category_id)
        elif subcategory_id: q &= Q(items__product__subcategory_id=subcategory_id)
        elif product_id:   q &= Q(items__product_id=product_id)
        return q

    purchases_cur     = PurchaseOrder.objects.filter(_purchase_q(date_from, date_to)).distinct().aggregate(total=Sum('total_price'))
    purchases_prv     = PurchaseOrder.objects.filter(_purchase_q(prev_date_from, prev_date_to)).distinct().aggregate(total=Sum('total_price'))
    current_purchases = purchases_cur['total'] or Decimal('0')
    last_purchases    = purchases_prv['total'] or Decimal('0')
    purchases_trend   = float(((current_purchases - last_purchases) / last_purchases) * 100) if last_purchases else 0

    # Customers who ordered in period (matching group filter)
    new_customers = Customer.objects.filter(
        created_at__gte=date_from, created_at__lte=date_to
    ).distinct().count()

    # Old customers registered in the period before
    old_customers = Customer.objects.filter(
        created_at__gte=prev_date_from, created_at__lte=prev_date_to
    ).count()

    customers_trend = new_customers - old_customers

    # Inventory — current state, optionally restricted by group filter
    inv_qs = Stock.objects.select_related('product')
    if category_id:    inv_qs = inv_qs.filter(product__category_id=category_id)
    if subcategory_id: inv_qs = inv_qs.filter(product__subcategory_id=subcategory_id)
    if product_id:     inv_qs = inv_qs.filter(product_id=product_id)
    if supplier_id:    inv_qs = inv_qs.filter(product__supplier_id=supplier_id)

    inventory_value = inv_qs.aggregate(
        total=Sum(F('quantity') * F('product__cost_price'), output_field=DecimalField())
    )
    low_stock_count = inv_qs.filter(
        quantity__lt=F('product__safety_stock')
    ).exclude(product__safety_stock=0).count()

    return Response({
        'total_sales': {
            'value': float(current_sales),
            'formatted': f'${current_sales:,.0f}',
            'trend': 'up' if sales_trend > 0 else 'down' if sales_trend < 0 else 'neutral',
            'trend_value': f'{abs(sales_trend):.1f}%',
        },
        'total_orders': {
            'value': current_orders,
            'trend': 'up' if orders_trend > 0 else 'down' if orders_trend < 0 else 'neutral',
            'trend_value': f'{abs(orders_trend):.1f}%',
        },
        'total_purchases': {
            'value': float(current_purchases),
            'formatted': f'${current_purchases:,.0f}',
            'trend': 'up' if purchases_trend > 0 else 'down' if purchases_trend < 0 else 'neutral',
            'trend_value': f'{abs(purchases_trend):.1f}%',
        },
        'total_customers': {
            'value': new_customers,
            'new_in_period': new_customers,
            'trend': 'up' if customers_trend > 0 else 'down' if customers_trend < 0 else 'neutral',
            'trend_value': f"{'+' if customers_trend > 0 else '-'}{customers_trend}",
        },
        'inventory_value': {
            'value': float(inventory_value['total'] or 0),
            'formatted': f"${inventory_value['total'] or 0:,.0f}",
        },
        'low_stock_products': {
            'value': low_stock_count,
            'trend': 'down' if low_stock_count > 0 else 'neutral',
            'trend_value': 'Requieren atención' if low_stock_count > 0 else 'Todo OK',
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_chart(request):
    """
    GET /api/billing/stats/sales-chart/?period=day|week|month&date_from=...&date_to=...

    Uses the same date range as the global dashboard filter.
    period controls grouping granularity:
      day   → one bar per day
      week  → one bar per week
      month → one bar per month (default)
    """
    date_from, date_to = _parse_date_range(request)
    period = request.query_params.get('period', 'week')

    base_qs = SalesOrder.objects.filter(
        created_at__gte=date_from,
        created_at__lte=date_to,
        status__in=['pending', 'processing', 'completed'],
    )

    month_names = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                   'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    day_names   = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

    date_start = date_from.date()
    date_end   = date_to.date()

    if period == 'week':  # daily granularity
        rows = base_qs.annotate(
            bucket=TruncDate('created_at')
        ).values('bucket').annotate(
            sales=Sum('total_price'), orders=Count('id')
        ).order_by('bucket')

        total_days = (date_end - date_start).days + 1
        result = {}
        d = date_start
        for _ in range(total_days):
            label = day_names[d.weekday()] if total_days <= 7 else f'{d.day}/{d.month}'
            result[d] = {'day': label, 'sales': 0, 'orders': 0}
            d += timedelta(days=1)

        for row in rows:
            k = row['bucket']
            if k in result:
                result[k]['sales']  = float(row['sales'] or 0)
                result[k]['orders'] = row['orders']

        data = list(result.values())

    elif period == 'month':  # weekly granularity
        rows = base_qs.annotate(
            bucket=TruncWeek('created_at')
        ).values('bucket').annotate(
            sales=Sum('total_price'), orders=Count('id')
        ).order_by('bucket')

        rows_by_key = {row['bucket'].date(): row for row in rows}

        # Enumerate ISO-weeks that overlap the date range
        monday = date_start - timedelta(days=date_start.weekday())
        weeks  = []
        d, n   = monday, 1
        while d <= date_end:
            weeks.append((d, f'Sem {n}'))
            d += timedelta(weeks=1)
            n += 1

        data = []
        for week_key, label in weeks:
            row = rows_by_key.get(week_key, {})
            data.append({
                'day': label,
                'sales':  float(row.get('sales', 0) or 0),
                'orders': row.get('orders', 0) or 0,
            })

    else:  # monthly granularity
        rows = base_qs.annotate(
            bucket=TruncMonth('created_at')
        ).values('bucket').annotate(
            sales=Sum('total_price'), orders=Count('id')
        ).order_by('bucket')

        rows_by_key = {row['bucket'].date(): row for row in rows}

        # Enumerate months in range
        d = date_start.replace(day=1)
        months = []
        while d <= date_end:
            months.append(d)
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)  # advance one month

        data = []
        for month_start in months:
            row = rows_by_key.get(month_start, {})
            data.append({
                'day': month_names[month_start.month - 1],
                'sales':  float(row.get('sales', 0) or 0),
                'orders': row.get('orders', 0) or 0,
            })

    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def top_products(request):
    """
    GET /api/billing/stats/top-products/?limit=6&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

    Retorna los productos más vendidos por ingresos en el período indicado.
    """
    limit = int(request.query_params.get('limit', 6))
    date_from, date_to = _parse_date_range(request)

    category_id    = request.query_params.get('category_id')
    subcategory_id = request.query_params.get('subcategory_id')
    product_id     = request.query_params.get('product_id')
    supplier_id    = request.query_params.get('supplier_id')

    items_q = Q(
        sales_order__created_at__gte=date_from,
        sales_order__created_at__lte=date_to,
        sales_order__status__in=['pending', 'processing', 'completed'],
    )
    if category_id:    items_q &= Q(product__category_id=category_id)
    if subcategory_id: items_q &= Q(product__subcategory_id=subcategory_id)
    if product_id:     items_q &= Q(product_id=product_id)
    if supplier_id:    items_q &= Q(product__supplier_id=supplier_id)

    top_items = SalesItem.objects.filter(items_q).select_related('product', 'product__category').values(
        'product__id',
        'product__sku',
        'product__description',
        'product__category__name'
    ).annotate(
        units_sold=Sum('quantity'),
        revenue=Sum(F('quantity') * F('unit_price'), output_field=DecimalField())
    ).order_by('-revenue')[:limit]
    
    data = []
    for item in top_items:
        data.append({
            'id': item['product__id'],
            'sku': item['product__sku'],
            'description': item['product__description'],
            'category': item['product__category__name'] or 'Sin categoría',
            'units_sold': item['units_sold'],
            'revenue': float(item['revenue'] or 0),
            'trend': 'up'  # TODO: calcular tendencia comparando con mes anterior
        })
    
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stock_alerts(request):
    """
    GET /api/billing/stats/stock-alerts/?limit=10
    
    Retorna productos con stock por debajo del mínimo de seguridad
    """
    limit = int(request.query_params.get('limit', 10))
    
    # Productos con stock bajo
    low_stock = Stock.objects.filter(
        quantity__lt=F('product__safety_stock')
    ).exclude(
        product__safety_stock=0
    ).select_related(
        'product',
        'warehouse',
        'branch'
    ).order_by('quantity')[:limit]
    
    data = []
    for stock in low_stock:
        # Determinar ubicación
        if stock.warehouse:
            location = stock.warehouse.name
            location_type = 'warehouse'
        elif stock.branch:
            location = stock.branch.name
            location_type = 'branch'
        else:
            location = 'Sin ubicación'
            location_type = 'unknown'
        
        # Determinar nivel de criticidad
        percentage = (float(stock.quantity) / float(stock.product.safety_stock)) * 100 if stock.product.safety_stock > 0 else 0
        
        if percentage < 25:
            status = 'critical'
        elif percentage < 50:
            status = 'warning'
        else:
            status = 'low'
        
        data.append({
            'id': stock.id,
            'sku': stock.product.sku,
            'description': stock.product.description,
            'location': location,
            'location_type': location_type,
            'current_stock': float(stock.quantity),
            'safety_stock': float(stock.product.safety_stock),
            'status': status
        })
    
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_by_channel(request):
    """
    GET /api/billing/stats/sales-by-channel/?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

    Retorna distribución de ventas por canal en el período indicado.
    """
    date_from, date_to = _parse_date_range(request)

    category_id    = request.query_params.get('category_id')
    subcategory_id = request.query_params.get('subcategory_id')
    product_id     = request.query_params.get('product_id')
    supplier_id    = request.query_params.get('supplier_id')
    has_group      = any([category_id, subcategory_id, product_id, supplier_id])

    channel_names = {'ecommerce': 'E-commerce', 'storefront': 'Local físico', 'wholesale': 'Mayorista'}

    if has_group:
        items_q = Q(
            sales_order__created_at__gte=date_from,
            sales_order__created_at__lte=date_to,
            sales_order__status__in=['pending', 'processing', 'completed'],
        )
        if category_id:    items_q &= Q(product__category_id=category_id)
        if subcategory_id: items_q &= Q(product__subcategory_id=subcategory_id)
        if product_id:     items_q &= Q(product_id=product_id)
        if supplier_id:    items_q &= Q(product__supplier_id=supplier_id)

        rows = SalesItem.objects.filter(items_q).values(
            'sales_order__sales_channel'
        ).annotate(
            total=Sum(F('quantity') * F('unit_price'), output_field=DecimalField()),
            count=Count('sales_order_id', distinct=True),
        )
        channel_sales = [
            {'sales_channel': r['sales_order__sales_channel'], 'total': r['total'], 'count': r['count']}
            for r in rows
        ]
    else:
        channel_sales = list(SalesOrder.objects.filter(
            created_at__gte=date_from,
            created_at__lte=date_to,
            status__in=['pending', 'processing', 'completed'],
        ).values('sales_channel').annotate(total=Sum('total_price'), count=Count('id')))

    total_sales = sum(float(item['total'] or 0) for item in channel_sales)

    data = []
    for item in channel_sales:
        percentage = (float(item['total'] or 0) / total_sales * 100) if total_sales > 0 else 0
        ch = item['sales_channel']
        data.append({
            'channel':    channel_names.get(ch, ch),
            'sales':      float(item['total'] or 0),
            'orders':     item['count'],
            'percentage': round(percentage, 1),
        })

    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_status_summary(request):
    """
    GET /api/billing/stats/order-status/?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

    Retorna resumen de órdenes creadas en el período por estado.
    """
    date_from, date_to = _parse_date_range(request)

    category_id    = request.query_params.get('category_id')
    subcategory_id = request.query_params.get('subcategory_id')
    product_id     = request.query_params.get('product_id')
    supplier_id    = request.query_params.get('supplier_id')

    qs = SalesOrder.objects.filter(created_at__gte=date_from, created_at__lte=date_to)

    item_q = Q()
    if category_id:    item_q &= Q(sales_items__product__category_id=category_id)
    if subcategory_id: item_q &= Q(sales_items__product__subcategory_id=subcategory_id)
    if product_id:     item_q &= Q(sales_items__product_id=product_id)
    if supplier_id:    item_q &= Q(sales_items__product__supplier_id=supplier_id)
    if item_q:
        qs = qs.filter(item_q).distinct()

    status_counts = qs.values('status').annotate(
        count=Count('id')
    )
    
    status_names = {
        'draft': 'Presupuestos',
        'pending': 'Pendientes',
        'processing': 'En preparación',
        'completed': 'Completadas',
        'cancelled': 'Canceladas'
    }
    
    data = []
    for item in status_counts:
        data.append({
            'status': item['status'],
            'status_display': status_names.get(item['status'], item['status']),
            'count': item['count']
        })

    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def filter_options(request):
    """
    GET /api/billing/stats/filter-options/
    Params: category_id (filters subcategories + products), subcategory_id (filters products)

    Returns the lists needed to populate the dashboard group-filter dropdowns.
    """
    from core.stock.models import Category, Subcategory
    from users.models import Supplier

    category_id    = request.query_params.get('category_id')
    subcategory_id = request.query_params.get('subcategory_id')

    categories    = list(Category.objects.values('id', 'name').order_by('name'))
    sub_qs        = Subcategory.objects.all()
    if category_id:
        sub_qs = sub_qs.filter(category_id=category_id)
    subcategories = list(sub_qs.values('id', 'name', 'category_id').order_by('name'))

    prod_qs = Product.objects.filter(status='active')
    if category_id:    prod_qs = prod_qs.filter(category_id=category_id)
    if subcategory_id: prod_qs = prod_qs.filter(subcategory_id=subcategory_id)
    products  = list(prod_qs.values('id', 'sku', 'description').order_by('description')[:300])

    suppliers = list(Supplier.objects.values('id', 'name').order_by('name'))

    return Response({
        'categories':    categories,
        'subcategories': subcategories,
        'products':      products,
        'suppliers':     suppliers,
    })
