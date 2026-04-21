from rest_framework import serializers
from decimal import Decimal
from .models import SalesOrder, SalesItem, PurchaseOrder, PurchaseItem
from core.crm.models import Customer
from core.stock.models import Warehouse, Stock, StockMovement
from core.store.models import Branch
from users.models import Supplier, Employee, User
from django.db.models import Sum, Q


class SalesItemSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source='product.sku', read_only=True)
    product_name = serializers.CharField(source='product.description', read_only=True)
    product_unit_name = serializers.CharField(source='product_unit.name', read_only=True, allow_null=True)
    
    class Meta:
        model = SalesItem
        fields = ['id', 'product', 'product_sku', 'product_name', 'product_unit', 'product_unit_name', 'quantity', 'unit_price']
        read_only_fields = ['id']


class CustomerBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['id', 'customer_type', 'name', 'first_name', 'last_name', 'email', 'phone', 'address']


class WarehouseBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ['id', 'name', 'address']


class BranchBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name', 'address']


class SalesOrderSerializer(serializers.ModelSerializer):
    sales_items = SalesItemSerializer(many=True)
    customer = CustomerBasicSerializer(read_only=True)
    customer_id = serializers.IntegerField(write_only=True)
    warehouse_origin = WarehouseBasicSerializer(read_only=True)
    warehouse_origin_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    branch_origin = BranchBasicSerializer(read_only=True)
    branch_origin_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = SalesOrder
        fields = [
            'id',
            'sales_channel',
            'employee',
            'customer',
            'customer_id',
            'warehouse_origin',
            'warehouse_origin_id',
            'branch_origin',
            'branch_origin_id',
            'status',
            'payment_method',
            'delivery',
            'delivery_date',
            'deliver_to',
            'shipping_cost',
            'total_price',
            'taxes',
            'discount',
            'description',
            'currency',
            'was_payed',
            'was_delivered',
            'delivered_date',
            'transport',
            'driver',
            'patent',
            'file_path',
            'created_at',
            'updated_at',
            'sales_items'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'employee']
    
    def create(self, validated_data):
        sales_items_data = validated_data.pop('sales_items')
        
        # Create the sales order
        sales_order = SalesOrder.objects.create(**validated_data)
        
        # Create the sales items
        for item_data in sales_items_data:
            SalesItem.objects.create(sales_order=sales_order, **item_data)
        
        return sales_order
    
    def update(self, instance, validated_data):
        sales_items_data = validated_data.pop('sales_items', None)
        
        # Update sales order fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update sales items only if provided (for PATCH requests)
        if sales_items_data is not None:
            # Delete existing items
            instance.sales_items.all().delete()
            
            # Create new items
            for item_data in sales_items_data:
                SalesItem.objects.create(sales_order=instance, **item_data)
        
        return instance
    
    def validate(self, data):
        # Solo validar si estamos creando (no hay instancia) o si se envían los campos en actualización
        is_creation = not self.instance
        
        # En creación, asegurar que el estado sea draft y was_payed/was_delivered sean False
        if is_creation:
            data['status'] = 'draft'
            data['was_payed'] = False
            data['was_delivered'] = False
        
        # Validaciones de flujo de estado
        if self.instance:  # Solo en actualización
            old_status = self.instance.status
            new_status = data.get('status', old_status)
            old_was_payed = self.instance.was_payed
            new_was_payed = data.get('was_payed', old_was_payed)
            old_was_delivered = self.instance.was_delivered
            new_was_delivered = data.get('was_delivered', old_was_delivered)
            
            # 1) Solo se puede marcar como pagado si el estado es processing
            if new_was_payed and not old_was_payed:
                if new_status not in ['processing']:
                    raise serializers.ValidationError({
                        'was_payed': 'Solo se puede marcar como pagado una orden en estado de preparación (processing).'
                    })
            
            # 2) Solo se puede marcar como entregado si el estado es processing Y ya está pagado
            if new_was_delivered and not old_was_delivered:
                if new_status not in ['processing']:
                    raise serializers.ValidationError({
                        'was_delivered': 'Solo se puede marcar como entregado una orden en estado de preparación (processing).'
                    })
                # Además, debe estar pagado para poder marcar como entregado
                if not new_was_payed:
                    raise serializers.ValidationError({
                        'was_delivered': 'Solo se puede marcar como entregado una orden que ya ha sido pagada.'
                    })
            
            # 3) Para completar, debe estar pagado y entregado
            if new_status == 'completed' and old_status != 'completed':
                if not new_was_payed or not new_was_delivered:
                    raise serializers.ValidationError({
                        'status': 'Solo se puede marcar como completada una orden que ha sido pagada y entregada.'
                    })
            
            # 4) No se puede cambiar de completed a otros estados
            if old_status == 'completed':
                raise serializers.ValidationError({
                    'status': 'No se puede cambiar el estado de una orden completada.'
                })
            
            # 5) No se puede cambiar de cancelled a otros estados
            if old_status == 'cancelled' and new_status != 'cancelled':
                raise serializers.ValidationError({
                    'status': 'No se puede cambiar el estado de una orden cancelada.'
                })
            
            # 6) Validar transiciones válidas de estado
            valid_transitions = {
                'draft': ['pending', 'cancelled'],
                'pending': ['processing', 'cancelled'],
                'processing': ['completed', 'cancelled'],
                'completed': [],  # No puede cambiar de completed
                'cancelled': []   # No puede cambiar de cancelled
            }
            
            # 7) No se puede actualizar de presupuesto a pendiente si no hay un origen definido (warehouse o branch)
            if old_status == 'draft' and new_status == 'pending':
                warehouse_origin_id = data.get('warehouse_origin_id', self.instance.warehouse_origin_id if self.instance else None)
                branch_origin_id = data.get('branch_origin_id', self.instance.branch_origin_id if self.instance else None)
                
                if not warehouse_origin_id and not branch_origin_id:
                    raise serializers.ValidationError({
                        'requires_origin': True,
                        'status': 'Para cambiar el estado a pendiente, debe especificar un origen de stock.'
                    })
                
            if new_status != old_status:
                if new_status not in valid_transitions.get(old_status, []):
                    raise serializers.ValidationError({
                        'status': f'Transición de estado inválida: {old_status} → {new_status}. '
                                f'Estados válidos desde {old_status}: {", ".join(valid_transitions.get(old_status, []))}'
                    })
        
        # Validate that if delivery is True, deliver_to and shipping_cost are provided
        if 'delivery' in data or is_creation:
            delivery = data.get('delivery', self.instance.delivery if self.instance else False)
            deliver_to = data.get('deliver_to', self.instance.deliver_to if self.instance else None)
            shipping_cost = data.get('shipping_cost', self.instance.shipping_cost if self.instance else 0)
            
            if delivery:
                if not deliver_to or deliver_to.strip() == '':
                    raise serializers.ValidationError({
                        'deliver_to': 'La dirección de entrega es requerida cuando incluye envío.'
                    })
                if shipping_cost <= 0:
                    raise serializers.ValidationError({
                        'shipping_cost': 'El costo de envío debe ser mayor a 0 cuando incluye envío.'
                    })
        
        # Validar que solo haya un origen (warehouse O branch)
        warehouse_origin_id = data.get('warehouse_origin_id', self.instance.warehouse_origin_id if self.instance else None)
        branch_origin_id = data.get('branch_origin_id', self.instance.branch_origin_id if self.instance else None)
        
        if warehouse_origin_id and branch_origin_id:
            raise serializers.ValidationError({
                'origin': 'No puede especificar tanto depósito como sucursal de origen. Elija solo uno.'
            })
        
        # ============ VALIDACIÓN DE STOCK ============
        # Determinar cuándo necesitamos validar stock
        need_stock_validation = False
        
        if is_creation:
            # Siempre validar en creación
            need_stock_validation = True
        elif self.instance:
            # En actualización, validar si:
            old_status = self.instance.status
            new_status = data.get('status', old_status)
            
            # 1. Se cambia de draft a pending (necesita validar stock con el origen)
            if old_status == 'draft' and new_status == 'pending':
                need_stock_validation = True
            
            # 2. Ya está en pending o superior y se cambia el origen
            elif old_status in ['pending', 'processing'] and (
                'warehouse_origin_id' in data or 'branch_origin_id' in data
            ):
                need_stock_validation = True
            
            # 3. Se están modificando los items de la orden
            elif 'sales_items' in data:
                need_stock_validation = True
        
        # Validate sales_items - solo requerido en creación
        if 'sales_items' in data or is_creation:
            sales_items = data.get('sales_items', [])
            if not sales_items and is_creation:
                raise serializers.ValidationError({
                    'sales_items': 'Debe incluir al menos un producto en la orden.'
                })
        
        # EJECUTAR VALIDACIÓN DE STOCK SI ES NECESARIO
        if need_stock_validation:
            # Obtener los items a validar
            if 'sales_items' in data:
                sales_items = data.get('sales_items', [])
            elif self.instance:
                # Usar los items existentes de la instancia
                sales_items = [
                    {
                        'product': item.product,
                        'quantity': item.quantity,
                        'product_unit': item.product_unit
                    }
                    for item in self.instance.sales_items.all()
                ]
            else:
                sales_items = []
            
            if not sales_items:
                raise serializers.ValidationError({
                    'sales_items': 'No se pueden validar items sin productos en la orden.'
                })
            
            # Determinar el origen del stock
            request = self.context.get('request')
            user = User.objects.get(id=self.context.get('request').user.id) if request else None
            
            # Determinar ubicación de origen (warehouse o branch)
            origin_warehouse = None
            origin_branch = None
            origin_specified_manually = False
            
            if warehouse_origin_id:
                # Usuario especificó warehouse manualmente
                origin_warehouse = Warehouse.objects.filter(id=warehouse_origin_id).first()
                if not origin_warehouse:
                    raise serializers.ValidationError({
                        'warehouse_origin_id': 'El depósito de origen especificado no existe.'
                    })
                origin_specified_manually = True
            elif branch_origin_id:
                # Usuario especificó branch manualmente
                origin_branch = Branch.objects.filter(id=branch_origin_id).first()
                if not origin_branch:
                    raise serializers.ValidationError({
                        'branch_origin_id': 'La sucursal de origen especificada no existe.'
                    })
                origin_specified_manually = True
            else:
                # Si no se especifica origen, intentar usar la sucursal del empleado
                if user and user.role != "superadmin":
                    employee = Employee.objects.filter(user=request.user.id).first() if request else None
                    origin_branch = employee.branch if employee else None
                else:
                    origin_branch = Branch.objects.filter(
                        name__icontains='Sucursal Principal'
                    ).first()

                if not origin_branch and employee and employee.store:
                    origin_branch = Branch.objects.filter(
                        store=employee.store,
                        name__icontains='Sucursal Principal'
                    ).first() or Branch.objects.filter(store=employee.store).first()

                # Si encontramos la sucursal del empleado, asignarla automáticamente
                if origin_branch and not self.instance:
                    data['branch_origin_id'] = origin_branch.id

            # Calcular cantidades requeridas por producto
            requested_by_product = {}
            products_by_id = {}

            for item in sales_items:
                product = item.get('product')
                quantity = item.get('quantity', 0)
                product_unit = item.get('product_unit')

                if not product:
                    continue

                # Manejar tanto objetos Product como IDs simples
                product_id = product.id if hasattr(product, 'id') else product
                
                # Guardar referencia al producto para mensajes de error
                if hasattr(product, 'description'):
                    products_by_id[product_id] = product
                else:
                    # Si solo tenemos el ID, obtener el producto de la BD
                    from core.stock.models import Product
                    product_obj = Product.objects.filter(id=product_id).first()
                    if product_obj:
                        products_by_id[product_id] = product_obj

                conversion_factor = Decimal('1')
                if product_unit:
                    if hasattr(product_unit, 'conversion_factor'):
                        conversion_factor = Decimal(str(product_unit.conversion_factor))
                    else:
                        # Si product_unit es un ID, obtenerlo de la BD
                        from core.stock.models import ProductUnit
                        unit_obj = ProductUnit.objects.filter(id=product_unit).first()
                        if unit_obj:
                            conversion_factor = Decimal(str(unit_obj.conversion_factor))

                real_quantity = Decimal(str(quantity)) * conversion_factor

                requested_by_product[product_id] = requested_by_product.get(product_id, Decimal('0')) + real_quantity

            # Solo validar stock si tenemos un origen definido
            if origin_warehouse or origin_branch:
                # Validar stock en la ubicación de origen
                stock_errors = []
                stock_inconsistencies = []  # Para tracking de inconsistencias entre ubicaciones
                
                for product_id, required_qty in requested_by_product.items():

                    # 1. Obtener stock físico
                    if origin_warehouse:
                        stock_obj = Stock.objects.filter(
                            product_id=product_id,
                            warehouse=origin_warehouse,
                            branch=None
                        ).first()
                        origin_location_name = f"Depósito {origin_warehouse.name}"
                        origin_type = 'warehouse'
                        origin_id = origin_warehouse.id
                    else:
                        stock_obj = Stock.objects.filter(
                            product_id=product_id,
                            branch=origin_branch,
                            warehouse=None
                        ).first()
                        origin_location_name = f"Sucursal {origin_branch.name}"
                        origin_type = 'branch'
                        origin_id = origin_branch.id
                    
                    physical_stock = stock_obj.quantity if stock_obj else Decimal('0')
                    
                    # 2. Calcular ventas reservadas (movimientos OUT en TRAN)
                    reserved_sales = StockMovement.objects.filter(
                        product_id=product_id,
                        movement_type='OUT',
                        status='TRAN'
                    )
                    
                    if origin_warehouse:
                        reserved_sales = reserved_sales.filter(warehouse=origin_warehouse, branch=None)
                    else:
                        reserved_sales = reserved_sales.filter(branch=origin_branch, warehouse=None)
                    
                    # Si estamos actualizando una orden, excluir sus propios movimientos
                    if self.instance:
                        reserved_sales = reserved_sales.exclude(sale=self.instance)
                    
                    total_reserved = reserved_sales.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                    
                    # 3. Calcular compras en tránsito (movimientos IN en TRAN)
                    incoming_purchases = StockMovement.objects.filter(
                        product_id=product_id,
                        movement_type='IN',
                        status='TRAN'
                    )
                    if origin_warehouse:
                        incoming_purchases = incoming_purchases.filter(warehouse=origin_warehouse, branch=None)
                    else:
                        incoming_purchases = incoming_purchases.filter(branch=origin_branch, warehouse=None)
                    
                    total_incoming = incoming_purchases.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                    
                    # 4. Calcular stock disponible real
                    available_stock = physical_stock - total_reserved + total_incoming
                    
                    # 5. Validar disponibilidad
                    if available_stock < required_qty:
                        # Buscar stock en otras ubicaciones
                        other_locations = Stock.objects.filter(
                            product_id=product_id,
                            quantity__gt=0
                        ).exclude(
                            Q(warehouse=origin_warehouse, branch=None) if origin_warehouse else Q(branch=origin_branch, warehouse=None)
                        )

                        other_info = []
                        alternative_locations = []  # Para información estructurada
                        
                        for stock in other_locations:
                            # Calcular disponibilidad real en esta ubicación
                            loc_physical = stock.quantity
                            
                            # Reservas en esta ubicación
                            loc_reserved = StockMovement.objects.filter(
                                product_id=product_id,
                                movement_type='OUT',
                                status='TRAN'
                            )
                            if stock.warehouse:
                                loc_reserved = loc_reserved.filter(warehouse=stock.warehouse, branch=None)
                                location_label = f"Depósito '{stock.warehouse.name}' (ID: {stock.warehouse.id})"
                                loc_type = 'warehouse'
                                loc_id = stock.warehouse.id
                                loc_name = stock.warehouse.name
                            else:
                                loc_reserved = loc_reserved.filter(branch=stock.branch, warehouse=None)
                                location_label = f"Sucursal '{stock.branch.name}' (ID: {stock.branch.id})"
                                loc_type = 'branch'
                                loc_id = stock.branch.id
                                loc_name = stock.branch.name
                            
                            loc_total_reserved = loc_reserved.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                            
                            # Compras en tránsito en esta ubicación
                            loc_incoming = StockMovement.objects.filter(
                                product_id=product_id,
                                movement_type='IN',
                                status='TRAN'
                            )
                            if stock.warehouse:
                                loc_incoming = loc_incoming.filter(warehouse=stock.warehouse, branch=None)
                            else:
                                loc_incoming = loc_incoming.filter(branch=stock.branch, warehouse=None)
                            
                            loc_total_incoming = loc_incoming.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                            
                            # Disponibilidad real
                            loc_available = round(loc_physical - loc_total_reserved + loc_total_incoming)
                            
                            # Solo agregar si hay stock disponible real
                            if loc_available > 0:
                                other_info.append(f"{location_label}: {loc_available} unidades disponibles")
                                alternative_locations.append({
                                    'type': loc_type,
                                    'id': loc_id,
                                    'name': loc_name,
                                    'available': float(loc_available)
                                })

                        product_name = getattr(products_by_id.get(product_id), 'description', f"Producto {product_id}")
                        product_sku = getattr(products_by_id.get(product_id), 'sku', '')
                        
                        # Si hay stock en otras ubicaciones, guardar la inconsistencia
                        if alternative_locations and origin_specified_manually:
                            stock_inconsistencies.append({
                                'product_id': product_id,
                                'product_name': product_name,
                                'product_sku': product_sku,
                                'required_qty': float(required_qty),
                                'current_origin': {
                                    'type': origin_type,
                                    'id': origin_id,
                                    'name': origin_warehouse.name if origin_warehouse else origin_branch.name,
                                    'available': float(available_stock)
                                },
                                'alternative_locations': alternative_locations
                            })
                        
                        # Mensaje de error detallado
                        if origin_specified_manually:
                            error_msg = (
                                f"Stock insuficiente en {origin_location_name} para '{product_name}': "
                                f"Requerido: {round(required_qty)}, "
                                f"Físico: {round(physical_stock)}, "
                                f"Reservado en ventas: {round(total_reserved)}, "
                                f"En tránsito (compras): {round(total_incoming)}, "
                                f"Disponible: {round(available_stock)}."
                            )
                            if other_info:
                                error_msg += f" Stock en otras ubicaciones: {'; '.join(other_info)}."
                            else:
                                error_msg += " No hay stock disponible en otras ubicaciones."
                        else:
                            # Origen automático - sugerir alternativas
                            error_msg = (
                                f"Stock insuficiente en {origin_location_name} para '{product_name}': "
                                f"Requerido: {round(required_qty)}, "
                                f"Físico: {round(physical_stock)}, "
                                f"Reservado: {round(total_reserved)}, "
                                f"En tránsito: {round(total_incoming)}, "
                                f"Disponible: {round(available_stock)}."
                            )
                            if other_info:
                                error_msg += (
                                    f" Stock disponible en otras ubicaciones: {'; '.join(other_info)}. "
                                    f"Especifique 'branch_origin_id' o 'warehouse_origin_id' para usar otra ubicación."
                                )
                            else:
                                error_msg += " No hay stock disponible en otras ubicaciones."
                        
                        stock_errors.append(error_msg)

                if stock_errors:
                    # Si hay inconsistencias de ubicación, incluir información estructurada
                    if stock_inconsistencies:
                        raise serializers.ValidationError({
                            'stock_inconsistency': True,
                            'inconsistency_details': stock_inconsistencies,
                            'sales_items': stock_errors
                        })
                    else:
                        raise serializers.ValidationError({
                            'sales_items': stock_errors
                        })
            else:
                # No se pudo determinar origen automáticamente y no fue especificado manualmente
                raise serializers.ValidationError({
                    'sales_items': 'No se pudo determinar la sucursal del empleado. Especifique branch_origin_id o warehouse_origin_id para indicar de dónde tomar el stock.'
                })
        
        return data


class PurchaseItemSerializer(serializers.ModelSerializer):
    product_description = serializers.CharField(source='product.description', read_only=True)
    product_sku = serializers.CharField(source='product.sku', read_only=True)
    product_unit_name = serializers.CharField(source='product_unit.name', read_only=True, allow_null=True)
    product_unit_conversion_factor = serializers.DecimalField(source='product_unit.conversion_factor', max_digits=10, decimal_places=4, read_only=True, allow_null=True)
    product_cost_price = serializers.DecimalField(source='product.cost_price', max_digits=10, decimal_places=2, read_only=True)
    product_base_unit_name = serializers.CharField(source='product.base_unit_name', read_only=True)
    
    class Meta:
        model = PurchaseItem
        fields = ['id', 'product', 'product_description', 'product_sku', 'product_unit', 'product_unit_name', 'product_unit_conversion_factor', 'product_cost_price', 'quantity', 'product_base_unit_name']
        read_only_fields = ['id']
    
    def to_representation(self, instance):
        representation = super().to_representation(instance)
        
        # Normalizar conversion_factor para eliminar ceros trailing
        if instance.product_unit and instance.product_unit.conversion_factor:
            representation['product_unit_conversion_factor'] = float(instance.product_unit.conversion_factor.normalize())
        
        return representation


class SupplierBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ['id', 'name', 'email', 'phone', 'address']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseItemSerializer(many=True)
    supplier = SupplierBasicSerializer(read_only=True)
    warehouse_destination = WarehouseBasicSerializer(read_only=True)
    branch_destination = BranchBasicSerializer(read_only=True)
    supplier_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    warehouse_destination_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    branch_destination_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    comment = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = PurchaseOrder
        fields = [
            'id',
            'created_by',
            'supplier',
            'supplier_id',
            'comment',
            'payment_method',
            'delivery_date',
            'total_price',
            'description',
            'status',
            'was_payed',
            'received',
            'received_date',
            'transport',
            'driver',
            'patent',
            'currency',
            'taxes',
            'discount',
            'shipping_cost',
            'comments',
            'file_path',
            'warehouse_destination',
            'warehouse_destination_id',
            'branch_destination',
            'branch_destination_id',
            'created_at',
            'updated_at',
            'items'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'comments']
    
    def create(self, validated_data):
        validated_data.pop('comment', None)
        items_data = validated_data.pop('items')
        

        # Create the purchase order
        purchase_order = PurchaseOrder.objects.create(**validated_data)
        
        # Create the purchase items
        for item_data in items_data:
            PurchaseItem.objects.create(purchase_order=purchase_order, **item_data)
        
        return purchase_order
    
    def update(self, instance, validated_data):
        validated_data.pop('comment', None)
        validated_data.pop('comments', None)
        items_data = validated_data.pop('items', None)
        
        # Update purchase order fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update purchase items if provided
        if items_data is not None:
            # Delete existing items
            instance.items.all().delete()
            
            # Create new items
            for item_data in items_data:
                PurchaseItem.objects.create(purchase_order=instance, **item_data)
        
        return instance
    
    def validate(self, data):
        # Solo validar si estamos creando (no hay instancia) o si se envían los campos en actualización
        is_creation = not self.instance
        
        # En creación, asegurar que el estado sea draft y was_payed/received sean False
        if is_creation:
            data['status'] = 'draft'
            data['was_payed'] = False
            data['received'] = False
        
        # Solo validar items si están siendo actualizados o en creación
        if 'items' in data or is_creation:
            items = data.get('items', [])
            if not items and is_creation:
                raise serializers.ValidationError({
                    'items': 'Debe incluir al menos un producto en la orden de compra.'
                })
            
            # Validate that each item has quantity > 0
            for item in items:
                if item.get('quantity', 0) <= 0:
                    raise serializers.ValidationError({
                        'items': 'La cantidad de cada producto debe ser mayor a 0.'
                    })
        
        # Validaciones de flujo de estado
        if self.instance:  # Solo en actualización
            # Los comentarios son opcionales
            old_status = self.instance.status
            new_status = data.get('status', old_status)
            old_was_payed = self.instance.was_payed
            new_was_payed = data.get('was_payed', old_was_payed)
            old_received = self.instance.received
            new_received = data.get('received', old_received)
            
            # 1) Solo se puede marcar como pagado si el estado es pending
            if new_was_payed and not old_was_payed:
                if new_status not in ['pending']:
                    raise serializers.ValidationError({
                        'was_payed': 'Solo se puede marcar como pagado una orden pendiente (pending).'
                    })
            
            # 2) Solo se puede marcar como recibido si el estado es pending Y ya está pagado
            if new_received and not old_received:
                if new_status not in ['pending']:
                    raise serializers.ValidationError({
                        'received': 'Solo se puede marcar como recibido una orden pendiente (pending).'
                    })
                # Además, debe estar pagado para poder marcar como recibido
                if not new_was_payed:
                    raise serializers.ValidationError({
                        'received': 'No se puede marcar como recibido una orden que no está pagada.'
                    })
            
            # 3) Para completar, debe estar pagado y recibido
            if new_status == 'completed' and old_status != 'completed':
                if not new_was_payed or not new_received:
                    raise serializers.ValidationError({
                        'status': 'Para completar la orden, debe estar pagada y recibida.'
                    })
            
            # 4) No se puede cambiar de completed a otros estados
            if old_status == 'completed':
                raise serializers.ValidationError({
                    'status': 'No se puede cambiar el estado de una orden completada.'
                })
            
            # 5) No se puede cambiar de cancelled a otros estados
            if old_status == 'cancelled' and new_status != 'cancelled':
                raise serializers.ValidationError({
                    'status': 'No se puede cambiar el estado de una orden cancelada.'
                })
            
            # 6) Validar transiciones válidas de estado
            valid_transitions = {
                'draft': ['pending', 'cancelled'],
                'pending': ['completed', 'cancelled'],
                'completed': [],  # No puede cambiar de completed
                'cancelled': []   # No puede cambiar de cancelled
            }
            
            # 7) No se puede actualizar de presupuesto a pendiente si no hay un destino definido (warehouse o branch)
            if old_status == 'draft' and new_status == 'pending':
                warehouse_destination_id = data.get('warehouse_destination_id', self.instance.warehouse_destination_id if self.instance else None)
                branch_destination_id = data.get('branch_destination_id', self.instance.branch_destination_id if self.instance else None)
                
                if not warehouse_destination_id and not branch_destination_id:
                    raise serializers.ValidationError({
                        'status': 'Debe especificar un destino (warehouse o branch) antes de pasar a pendiente.'
                    })
                
            if new_status != old_status:
                if new_status not in valid_transitions.get(old_status, []):
                    raise serializers.ValidationError({
                        'status': f'No se puede cambiar de {old_status} a {new_status}. Transiciones válidas: {", ".join(valid_transitions.get(old_status, []))}'
                    })
        
        # Validar que solo haya un destino (warehouse O branch)
        warehouse_destination_id = data.get('warehouse_destination_id', self.instance.warehouse_destination_id if self.instance else None)
        branch_destination_id = data.get('branch_destination_id', self.instance.branch_destination_id if self.instance else None)
        
        if warehouse_destination_id and branch_destination_id:
            raise serializers.ValidationError({
                'destination': 'No puede especificar tanto depósito como sucursal de destino. Elija solo uno.'
            })
        
        # Si no hay destino, debe haber al menos uno (se manejará en el view con la sucursal por defecto)
        if not warehouse_destination_id and not branch_destination_id and not self.instance:
            # En creación, si no se especifica destino, se asignará la sucursal por defecto
            pass
        
        return data