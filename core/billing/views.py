from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import SalesOrder, PurchaseOrder
from django.db import transaction
from .serializer import SalesOrderSerializer, PurchaseOrderSerializer


class SalesOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar órdenes de venta (SalesOrder).
    
    Permite:
    - Listar todas las órdenes de venta (GET /api/sales-orders/)
    - Crear una nueva orden de venta (POST /api/sales-orders/)
    - Obtener detalle de una orden (GET /api/sales-orders/{id}/)
    - Actualizar una orden de venta (PUT/PATCH /api/sales-orders/{id}/)
    - Eliminar una orden de venta (DELETE /api/sales-orders/{id}/)
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
        y actualizar información del cliente
        """
        employee = None
        if hasattr(self.request.user, 'employee'):
            employee = self.request.user.employee
        
        # Guardar la orden de venta
        sales_order = serializer.save(employee=employee)
        
        # Actualizar información del cliente
        if sales_order.customer:
            customer = sales_order.customer
            # Actualizar fecha de última compra
            customer.last_purchase_date = sales_order.created_at
            # Actualizar total gastado solo si la orden fue pagada
            if sales_order.was_payed:
                customer.total_spent += sales_order.total_price
            customer.save()
    
    def perform_update(self, serializer):
        """
        Al actualizar una orden, ajustar el total_spent del cliente si cambia
        el estado de pago o el precio total
        """
        from core.stock.models import Stock, StockMovement
        from core.store.models import Branch
        from django.db.models import F
        from datetime import datetime, timezone
        from decimal import Decimal

        instance = self.get_object()
        old_was_payed = instance.was_payed
        old_total_price = instance.total_price
        old_was_delivered = instance.was_delivered
        
        # Guardar la orden actualizada
        sales_order = serializer.save()
        
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
                # Restar el precio viejo y sumar el nuevo
                customer.total_spent = customer.total_spent - old_total_price + sales_order.total_price
                customer.save()

        # Impactar stock cuando se marca como entregada
        if not old_was_delivered and sales_order.was_delivered:
            
            # Usar el origen especificado en la orden (branch_origin o warehouse_origin)
            origin_branch = sales_order.branch_origin
            origin_warehouse = sales_order.warehouse_origin
            
            # Si no hay origen especificado, usar la sucursal del empleado
            if not origin_branch and not origin_warehouse:
                employee = sales_order.employee
                origin_branch = employee.branch if employee else None

                if not origin_branch and employee and employee.store:
                    origin_branch = Branch.objects.filter(
                        store=employee.store,
                        name__icontains='Sucursal Principal'
                    ).first() or Branch.objects.filter(store=employee.store).first()

            if origin_branch or origin_warehouse:
                current_time = datetime.now(timezone.utc).isoformat()
                user_info = f'{self.request.user.first_name} {self.request.user.last_name}' if self.request.user else 'Sistema'
                user_id = self.request.user.id if self.request.user else None

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

                        # Crear o actualizar stock según el origen
                        if origin_warehouse:
                            Stock.objects.get_or_create(
                                product=product,
                                warehouse=origin_warehouse,
                                branch=None,
                                defaults={'quantity': 0}
                            )

                            Stock.objects.filter(
                                product=product,
                                warehouse=origin_warehouse,
                                branch=None
                            ).update(quantity=F('quantity') - real_quantity)
                            
                            location_name = f"depósito: {origin_warehouse.name}"
                            from_location = 'WAR'
                        else:
                            Stock.objects.get_or_create(
                                product=product,
                                branch=origin_branch,
                                warehouse=None,
                                defaults={'quantity': 0}
                            )

                            Stock.objects.filter(
                                product=product,
                                branch=origin_branch,
                                warehouse=None
                            ).update(quantity=F('quantity') - real_quantity)
                            
                            location_name = f"sucursal: {origin_branch.name}"
                            from_location = 'BRA'

                        comment_data = {
                            'date': current_time,
                            'comment': f'Orden de venta #{sales_order.id} entregada; egreso de {real_quantity} unidades desde {location_name}.',
                            'status_before': 'TRAN',
                            'status_after': 'REC',
                            'user': user_info,
                            'user_id': user_id
                        }

                        stock_movements_to_create.append(StockMovement(
                            product=product,
                            branch=origin_branch if origin_branch else None,
                            warehouse=origin_warehouse if origin_warehouse else None,
                            status='REC',
                            from_location=from_location,
                            to_location='SAL',
                            movement_type='OUT',
                            quantity=real_quantity,
                            unit_used=product_unit,
                            conversion_factor_at_moment=conversion_factor,
                            sale=sales_order,
                            note=f'Orden de venta #{sales_order.id} entregada',
                            comments=[comment_data]
                        ))

                    if stock_movements_to_create:
                        StockMovement.objects.bulk_create(stock_movements_to_create)
    
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
        Al actualizar una orden, gestionar el flujo de estados y stock (OPTIMIZADO)
        """
        from core.stock.models import Stock, StockMovement
        from django.db.models import F
        from datetime import datetime, timezone
        from decimal import Decimal
        
        with transaction.atomic():
            instance = self.get_object()
            old_status = instance.status
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

            comment_data = {
                'fields_updated': fields_updated,
                'updated_from': updated_from,
                'comment': user_comment or f'Orden de compra actualizada por {user_info}',
                'created_at': current_time
            }

            if not purchase_order.comments:
                purchase_order.comments = []
            purchase_order.comments.append(comment_data)
            purchase_order.save(update_fields=['comments'])

            # 1) Si cambia el estado de pendiente a aprobado, crear StockMovement
            if old_status == 'pending' and new_status == 'approved':
                
                if destination_warehouse or destination_branch:
                    # Evitar duplicados si ya existen movimientos para esta orden
                    if purchase_order.stock_movements.exists():
                        pass
                    else:
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
                            comment_data = {
                                'date': current_time,
                                'comment': f'Orden de compra #{purchase_order.id} aprobada; en espera de recepción en {destination_type}: {destination_name}.',
                                'status_before': old_status,
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
                                note=f'Orden de compra #{purchase_order.id} aprobada',
                                comments=[comment_data]
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

            # 2) Si cambia a rechazado, cancelar movimientos de stock
            elif new_status == 'rejected' and old_status != 'rejected':
                stock_movements = purchase_order.stock_movements.select_for_update().all()
                
                if stock_movements:

                    # Preparar comentario
                    comment_data = {
                        'date': current_time,
                        'comment': f'Orden de compra #{purchase_order.id} rechazada; el ingreso de stock ha sido cancelado.',
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
                        stock_movement.comments.append(comment_data)
                        movements_to_update.append(stock_movement)
                    
                    # Bulk update
                    StockMovement.objects.bulk_update(movements_to_update, ['status', 'comments'])

            # 3) Si se marca como recibido, actualizar stock y StockMovement
            if not old_received and new_received:
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
                        
                        comment_data = {
                            'date': current_time,
                            'comment': f'Orden de compra #{purchase_order.id} recibida; ingreso de {real_qty} unidades de {product_desc} al {destination_type}: {destination_name}.',
                            'status_before': 'TRAN',
                            'status_after': 'REC',
                            'user': user_info,
                            'user_id': user_id
                        }
                        
                        stock_movement.status = 'REC'
                        if not stock_movement.comments:
                            stock_movement.comments = []
                        stock_movement.comments.append(comment_data)
                        stock_movements_to_update.append(stock_movement)
                    
                    # Bulk update de movimientos
                    if stock_movements_to_update:
                        StockMovement.objects.bulk_update(stock_movements_to_update, ['status', 'comments'])
    
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
