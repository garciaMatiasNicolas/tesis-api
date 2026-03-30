from rest_framework import serializers
from decimal import Decimal
from .models import SalesOrder, SalesItem, PurchaseOrder, PurchaseItem
from core.crm.models import Customer
from core.stock.models import Warehouse, Stock
from core.store.models import Branch
from users.models import Supplier, Employee, User


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
        
        # Validate sales_items - solo requerido en creación
        if 'sales_items' in data or is_creation:
            sales_items = data.get('sales_items', [])
            if not sales_items and is_creation:
                raise serializers.ValidationError({
                    'sales_items': 'Debe incluir al menos un producto en la orden.'
                })

            # Determinar el origen del stock
            request = self.context.get('request')
            user = User.objects.get(id=self.context.get('request').user.id) if request else None
            print(request.data)
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
                if user.role != "superadmin":
                    employee = Employee.objects.get(user=request.user.id) if request else None
                    origin_branch = employee.branch
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
                if origin_branch:
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

                product_id = product.id if hasattr(product, 'id') else product
                products_by_id[product_id] = product

                conversion_factor = Decimal('1')
                if product_unit and hasattr(product_unit, 'conversion_factor'):
                    conversion_factor = Decimal(str(product_unit.conversion_factor))

                real_quantity = Decimal(str(quantity)) * conversion_factor

                requested_by_product[product_id] = requested_by_product.get(product_id, Decimal('0')) + real_quantity

            # Solo validar stock si tenemos un origen definido
            if origin_warehouse or origin_branch:
                # Validar stock en la ubicación de origen
                stock_errors = []
                for product_id, required_qty in requested_by_product.items():
                    # Obtener stock en la ubicación de origen
                    if origin_warehouse:
                        origin_qty = Stock.objects.filter(
                            product_id=product_id,
                            warehouse=origin_warehouse,
                            branch=None
                        ).values_list('quantity', flat=True).first() or Decimal('0')
                        origin_location_name = f"Depósito {origin_warehouse.name}"
                    else:
                        origin_qty = Stock.objects.filter(
                            product_id=product_id,
                            branch=origin_branch,
                            warehouse=None
                        ).values_list('quantity', flat=True).first() or Decimal('0')
                        origin_location_name = f"Sucursal {origin_branch.name}"

                    if Decimal(str(origin_qty)) < required_qty:
                        # Buscar stock en otras ubicaciones
                        other_locations = Stock.objects.filter(
                            product_id=product_id,
                            quantity__gt=0
                        )
                        
                        if origin_warehouse:
                            other_locations = other_locations.exclude(warehouse=origin_warehouse)
                        else:
                            other_locations = other_locations.exclude(branch=origin_branch, warehouse=None)

                        other_info = []
                        for stock in other_locations:
                            if stock.branch:
                                location_name = f"Sucursal '{stock.branch.name}' (ID: {stock.branch.id})"
                                other_info.append(f"{location_name}: {stock.quantity} unidades")
                            elif stock.warehouse:
                                location_name = f"Depósito '{stock.warehouse.name}' (ID: {stock.warehouse.id})"
                                other_info.append(f"{location_name}: {stock.quantity} unidades")

                        product_name = getattr(products_by_id.get(product_id), 'description', f"Producto {product_id}")
                        
                        # Si el origen fue especificado manualmente, error más directo
                        if origin_specified_manually:
                            if other_info:
                                stock_errors.append(
                                    f"Stock insuficiente en {origin_location_name} para '{product_name}' "
                                    f"(requerido: {required_qty}, disponible: {origin_qty}). "
                                    f"Stock en otras ubicaciones: {'; '.join(other_info)}."
                                )
                            else:
                                stock_errors.append(
                                    f"Stock insuficiente en {origin_location_name} para '{product_name}' "
                                    f"(requerido: {required_qty}, disponible: {origin_qty}). "
                                    f"No hay stock disponible en otras ubicaciones."
                                )
                        else:
                            # Origen automático (sucursal del empleado) - sugerir alternativas
                            if other_info:
                                stock_errors.append(
                                    f"Stock insuficiente en {origin_location_name} para '{product_name}' "
                                    f"(requerido: {required_qty}, disponible: {origin_qty}). "
                                    f"Stock disponible en otras ubicaciones: {'; '.join(other_info)}. "
                                    f"Especifique 'branch_origin_id' o 'warehouse_origin_id' para tomar stock de otra ubicación."
                                )
                            else:
                                stock_errors.append(
                                    f"Stock insuficiente en {origin_location_name} para '{product_name}' "
                                    f"(requerido: {required_qty}, disponible: {origin_qty}). "
                                    f"No hay stock disponible en otras ubicaciones."
                                )

                if stock_errors:
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
    comment = serializers.CharField(write_only=True, required=False, allow_blank=False)
    
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
        # Solo validar items si están siendo actualizados
        # Esto permite PATCH sin items (ej: solo cambiar status)

        if 'items' in data:
            items = data.get('items', [])
            if not items:
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
            comment = data.get('comment')
            if not comment or not str(comment).strip():
                raise serializers.ValidationError({
                    'comment': 'Debe incluir un comentario de actualización.'
                })
            old_status = self.instance.status
            new_status = data.get('status', old_status)
            
            # 1) El estado no puede volver de aprobado o rechazado a pendiente
            if old_status in ['approved', 'rejected'] and new_status == 'pending':
                raise serializers.ValidationError({
                    'status': 'No se puede cambiar el estado de aprobado o rechazado a pendiente.'
                })
            
            # 2) No se puede marcar como pagado si no está aprobado
            new_was_payed = data.get('was_payed', self.instance.was_payed)
            if new_was_payed and new_status != 'approved':
                raise serializers.ValidationError({
                    'was_payed': 'No se puede marcar como pagado una orden que no está aprobada.'
                })
            
            # 3) No se puede marcar como recibido si no está pagado
            new_received = data.get('received', self.instance.received)
            if new_received and not new_was_payed:
                raise serializers.ValidationError({
                    'received': 'No se puede marcar como recibido una orden que no está pagada.'
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
