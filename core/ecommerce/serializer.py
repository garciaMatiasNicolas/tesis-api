from rest_framework import serializers
from ..stock.models import Product, Category, Subcategory
from .models import Cart, CartItem
from core.billing.models import SalesOrder, SalesItem
from core.crm.models import Customer


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
    
    def to_representation(self, instance):
        # Obtener la solicitud actual para construir la URL absoluta
        request = self.context.get('request')
        
        # Construir la URL de la imagen
        image_url = None
        if instance.image:
            if request:
                # Si tenemos la solicitud, usamos build_absolute_uri para obtener la URL completa
                image_url = request.build_absolute_uri(instance.image.url)
            else:
                # De lo contrario, usamos una URL relativa o fija
                image_url = instance.image.url
        
        return {
            "id": instance.id,
            "description": instance.description,
            "price": instance.price,
            "category": {"id": instance.category.id, "name": instance.category.name} if instance.category else None,
            "subcategory": {"id": instance.subcategory.id, "name": instance.subcategory.name} if instance.subcategory else None,
            "supplier": {"id": instance.supplier.id, "name": instance.supplier.name} if instance.supplier else None,
            "sku": instance.sku,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
            "image": image_url,
        }


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


class SubcategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Subcategory
        fields = '__all__'


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'city', 'postal_code', 'state', 'country']


class CartItemSerializer(serializers.ModelSerializer):
    product_details = ProductSerializer(source='product', read_only=True)
    
    class Meta:
        model = CartItem
        fields = ['id', 'product', 'product_details', 'quantity', 'added_at', 'updated_at']
        extra_kwargs = {
            'product': {'write_only': True}
        }


class CartSerializer(serializers.ModelSerializer):
    cart_items = CartItemSerializer(many=True, read_only=True)
    customer_details = CustomerSerializer(source='customer', read_only=True)
    total = serializers.SerializerMethodField()
    
    class Meta:
        model = Cart
        fields = ['id', 'customer', 'customer_details', 'created_at', 'updated_at', 'cart_items', 'total']
        extra_kwargs = {
            'customer': {'write_only': True}
        }
    
    def get_total(self, obj):
        total = 0
        for item in obj.cart_items.all():
            total += item.product.price * item.quantity
        return total


class SalesItemSerializer(serializers.ModelSerializer):
    product_details = ProductSerializer(source='product', read_only=True)
    
    class Meta:
        model = SalesItem
        fields = ['id', 'product', 'product_details', 'quantity']
        extra_kwargs = {
            'product': {'write_only': True}
        }


class SalesOrderSerializer(serializers.ModelSerializer):
    sales_items = SalesItemSerializer(many=True, read_only=True)
    customer_details = CustomerSerializer(source='customer', read_only=True)
    
    class Meta:
        model = SalesOrder
        fields = ['id', 'customer', 'customer_details', 'sales_channel', 'payment_method', 
                  'delivery_date', 'deliver_to', 'shipping_cost', 'total_price', 
                  'taxes', 'discount', 'status', 'was_payed', 'created_at', 
                  'updated_at', 'sales_items']
        read_only_fields = ['status', 'was_payed', 'created_at', 'updated_at']