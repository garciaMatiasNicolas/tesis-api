from rest_framework import serializers
from django.db.models import Sum, F, Value, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from .models import Product, Category, Subcategory, Warehouse, ProductUnit, Stock, StockMovement
from core.store.models import Branch
from core.billing.models import PurchaseItem, SalesItem


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
    
    def validate_image(self, value):
        """Validar el archivo de imagen"""
        if value:
            # Validar tamaño del archivo (máximo 5MB)
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError("El archivo de imagen no puede ser mayor a 5MB.")
            
            # Validar tipo de archivo
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
            if value.content_type not in allowed_types:
                raise serializers.ValidationError("Solo se permiten archivos JPEG, PNG y GIF.")
        
        return value
    
    def to_representation(self, instance):
        return {
            "id": instance.id,
            "description": instance.description,
            "price": instance.price,
            "category": {"id": instance.category.id, "name": instance.category.name} if instance.category else None,
            "subcategory": {"id": instance.subcategory.id, "name": instance.subcategory.name} if instance.subcategory else None,
            "supplier": {"id": instance.supplier.id, "name": instance.supplier.name} if instance.supplier else None,
            "sku": instance.sku,
            "weight": instance.weight,
            "height": instance.height,
            "depth": instance.depth,
            "width": instance.width,
            "cost_price": instance.cost_price,
            "safety_stock": float(instance.safety_stock.normalize()) if instance.safety_stock else 0.0,
            "base_unit_name": instance.get_base_unit_name_display(),
            "unit_type": instance.get_unit_type_display(),
            "image": instance.image.url if instance.image else None,
            "status": instance.status,  
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }


class ProductUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductUnit
        exclude = ('created_at', 'updated_at')
    
    def to_representation(self, instance):
        return {
            "id": instance.id,
            "product": instance.product.id if instance.product else None,
            "name": instance.name,
            "conversion_factor": float(instance.conversion_factor.normalize()),
        }



class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


class SubcategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Subcategory
        fields = '__all__'


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = '__all__'
    
    def to_representation(self, instance):
        return {
            "id": instance.id,
            "store": {"id": instance.store.id, "name": instance.store.name} if instance.store else None,
            "name": instance.name,
            "country": instance.country,
            "state": instance.state,
            "city": instance.city,
            "address": instance.address,
            "created_at": instance.created_at,
        }


class StockSerializer(serializers.ModelSerializer):
    """
    Serializador de solo lectura para Stock.
    Incluye información completa del producto, warehouse/branch y alertas de stock bajo.
    """
    product_detail = serializers.SerializerMethodField()
    warehouse_detail = serializers.SerializerMethodField()
    branch_detail = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()
    purchase_order_pending = serializers.SerializerMethodField()
    sale_order_pending = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = [
            'id',
            'product',
            'product_detail',
            'purchase_order_pending',
            'sale_order_pending',
            'warehouse',
            'warehouse_detail',
            'branch',
            'branch_detail',
            'location_name',
            'quantity',
            'is_low_stock',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['__all__']  # Todos los campos son de solo lectura
    
    def get_product_detail(self, obj):
        """Información detallada del producto"""
        if obj.product:
            return {
                'id': obj.product.id,
                'sku': obj.product.sku,
                'description': obj.product.description,
                'safety_stock': float(obj.product.safety_stock) if obj.product.safety_stock else 0.0,
                'base_unit_name': obj.product.get_base_unit_name_display(),
                'unit_type': obj.product.get_unit_type_display(),
                'status': obj.product.status,
                'supplier': obj.product.supplier.name if obj.product.supplier else None
            }
        return None
    
    def get_warehouse_detail(self, obj):
        """Información detallada del depósito"""
        if obj.warehouse:
            return {
                'id': obj.warehouse.id,
                'name': obj.warehouse.name,
                'address': obj.warehouse.address,
                'city': obj.warehouse.city,
                'state': obj.warehouse.state,
                'country': obj.warehouse.country
            }
        return None
    
    def get_branch_detail(self, obj):
        """Información detallada de la sucursal"""
        if obj.branch:
            return {
                'id': obj.branch.id,
                'name': obj.branch.name,
                'address': obj.branch.address,
                'city': obj.branch.city,
                'state': obj.branch.state,
                'country': obj.branch.country
            }
        return None
    
    def get_is_low_stock(self, obj):
        """Verificar si el stock está por debajo del nivel de seguridad"""
        if obj.product and obj.product.safety_stock:
            return obj.quantity < obj.product.safety_stock
        return False
    
    def get_location_name(self, obj):
        """Nombre de la ubicación (warehouse o branch)"""
        if obj.warehouse:
            return obj.warehouse.name
        elif obj.branch:
            return obj.branch.name
        return "Sin ubicación asignada"
    
    def get_purchase_order_pending(self, obj):
        """Cantidad pendiente en órdenes de compra"""
        total_expr = Sum(
            ExpressionWrapper(
                F('quantity') * Coalesce(F('product_unit__conversion_factor'), Value(1)),
                output_field=DecimalField(max_digits=15, decimal_places=4)
            )
        )
        if obj.warehouse:
            return PurchaseItem.objects.filter(
                product=obj.product,
                purchase_order__status='approved',
                purchase_order__received=False,
                purchase_order__warehouse_destination=obj.warehouse
            ).aggregate(total_pending=total_expr)['total_pending'] or 0
        
        elif obj.branch:
            return PurchaseItem.objects.filter(
                product=obj.product,
                purchase_order__status='approved',
                purchase_order__received=False,
                purchase_order__branch_destination=obj.branch
            ).aggregate(total_pending=total_expr)['total_pending'] or 0
        
        else:
            return 0    
        
    def get_sale_order_pending(self, obj):
        """Cantidad pendiente en órdenes de venta"""
        total_expr = Sum(
            ExpressionWrapper(
                F('quantity') * Coalesce(F('product_unit__conversion_factor'), Value(1)),
                output_field=DecimalField(max_digits=15, decimal_places=4)
            )
        )
        
        return SalesItem.objects.filter(
            product=obj.product,
            sales_order__was_delivered=False
        ).aggregate(total_pending=total_expr)['total_pending'] or 0
    
    def to_representation(self, instance):
        """Sobrescribir para normalizar valores decimales"""
        representation = super().to_representation(instance)
        representation['quantity'] = float(instance.quantity.normalize()) if instance.quantity else 0.0
        return representation


class StockMovementSerializer(serializers.ModelSerializer):
    """
    Serializador de solo lectura para StockMovement.
    Incluye información completa del producto, ubicaciones, y referencias a órdenes.
    """
    product_detail = serializers.SerializerMethodField()
    warehouse_detail = serializers.SerializerMethodField()
    branch_detail = serializers.SerializerMethodField()
    unit_detail = serializers.SerializerMethodField()
    sale_detail = serializers.SerializerMethodField()
    purchase_detail = serializers.SerializerMethodField()
    from_location_name = serializers.SerializerMethodField()
    to_location_name = serializers.SerializerMethodField()
    movement_type_display = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    
    class Meta:
        model = StockMovement
        fields = [
            'id',
            'product',
            'product_detail',
            'warehouse',
            'warehouse_detail',
            'branch',
            'branch_detail',
            'from_location',
            'from_location_name',
            'to_location',
            'to_location_name',
            'movement_type',
            'movement_type_display',
            'quantity',
            'unit_used',
            'unit_detail',
            'conversion_factor_at_moment',
            'status',
            'status_display',
            'sale',
            'sale_detail',
            'purchase',
            'purchase_detail',
            'date',
            'note',
            'comments'
        ]
        read_only_fields = ['__all__']
    
    def get_product_detail(self, obj):
        """Información detallada del producto"""
        if obj.product:
            return {
                'id': obj.product.id,
                'sku': obj.product.sku,
                'description': obj.product.description,
                'base_unit_name': obj.product.get_base_unit_name_display(),
                'unit_type': obj.product.get_unit_type_display()
            }
        return None
    
    def get_warehouse_detail(self, obj):
        """Información detallada del depósito"""
        if obj.warehouse:
            return {
                'id': obj.warehouse.id,
                'name': obj.warehouse.name,
                'address': obj.warehouse.address,
                'city': obj.warehouse.city
            }
        return None
    
    def get_branch_detail(self, obj):
        """Información detallada de la sucursal"""
        if obj.branch:
            return {
                'id': obj.branch.id,
                'name': obj.branch.name,
                'address': obj.branch.address,
                'city': obj.branch.city
            }
        return None
    
    def get_unit_detail(self, obj):
        """Información de la unidad utilizada"""
        if obj.unit_used:
            return {
                'id': obj.unit_used.id,
                'name': obj.unit_used.name,
                'conversion_factor': float(obj.unit_used.conversion_factor)
            }
        return None
    
    def get_sale_detail(self, obj):
        """Información de la orden de venta asociada"""
        if obj.sale:
            return {
                'id': obj.sale.id,
                'order_number': f"V-{obj.sale.id:04d}"
            }
        return None
    
    def get_purchase_detail(self, obj):
        """Información de la orden de compra asociada"""
        if obj.purchase:
            return {
                'id': obj.purchase.id,
                'order_number': f"OC-{obj.purchase.id:04d}"
            }
        return None
    
    def get_from_location_name(self, obj):
        """Nombre legible del origen"""
        return obj.get_from_location_display()
    
    def get_to_location_name(self, obj):
        """Nombre legible del destino"""
        return obj.get_to_location_display()
    
    def get_movement_type_display(self, obj):
        """Tipo de movimiento legible"""
        return obj.get_movement_type_display()
    
    def get_status_display(self, obj):
        """Estado legible"""
        return obj.get_status_display()
    
    def to_representation(self, instance):
        """Sobrescribir para normalizar valores decimales"""
        representation = super().to_representation(instance)
        representation['quantity'] = float(instance.quantity.normalize()) if instance.quantity else 0.0
        representation['conversion_factor_at_moment'] = float(instance.conversion_factor_at_moment.normalize()) if instance.conversion_factor_at_moment else 1.0
        return representation