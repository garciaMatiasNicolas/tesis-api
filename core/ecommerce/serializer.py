from rest_framework import serializers
from django.db import transaction
from django.db.models import Sum
from ..stock.models import Product, Category, Subcategory, Stock
from .models import Cart, CartItem
from core.billing.models import PurchaseItem, SalesOrder, SalesItem, PurchaseOrder
from core.crm.models import Customer
from users.models import User


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
    
    def to_representation(self, instance):
        # Obtener la solicitud actual para construir la URL absoluta
        request = self.context.get('request')
        
        # Construir las URLs de las imágenes
        def get_image_url(image_field):
            if not image_field:
                return None
            try:
                # Obtener la URL
                if hasattr(image_field, 'url'):
                    url = image_field.url
                else:
                    url = str(image_field).strip()
                
                # Validar que no sea vacío o 'None'
                if not url or url == 'None' or url == '':
                    return None
                    
                # Si tenemos request, construir URL absoluta
                if request:
                    return request.build_absolute_uri(url)
                return url
            except Exception as e:
                print(f"Error getting image URL: {e}")
                return None
        
        # Obtener todas las imágenes disponibles
        images = []
        if instance.image_1:
            images.append(get_image_url(instance.image_1))
        if instance.image_2:
            images.append(get_image_url(instance.image_2))
        if instance.image_3:
            images.append(get_image_url(instance.image_3))
        
        # Primera imagen para compatibilidad hacia atrás
        image_url = images[0] if images else None
        
        # Validar stock 
        stock = Stock.objects.filter(product=instance).aggregate(total_quantity=Sum('quantity'))['total_quantity'] or 0
        
        sales_orders = SalesItem.objects.filter(sales_order__status__in=['pending', 'processing'], product=instance).aggregate(total_quantity=Sum('quantity'))['total_quantity'] or 0
        
        purchase_orders = PurchaseItem.objects.filter(purchase_order__status__in=['pending', 'processing'], product=instance).aggregate(total_quantity=Sum('quantity'))['total_quantity'] or 0
        available_stock = stock - sales_orders + purchase_orders

        if available_stock <= 0:
            stock = False
        else:
            stock = True

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
            "image": image_url,  # Primera imagen para compatibilidad
            "images": images,  # Array de todas las imágenes
            "image_1": get_image_url(instance.image_1),
            "image_2": get_image_url(instance.image_2),
            "image_3": get_image_url(instance.image_3),
            "stock": stock
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


class CustomerRegistrationSerializer(serializers.Serializer):
    """
    Serializer para registro de clientes del ecommerce.
    Maneja la lógica de vinculación con clientes existentes creados desde CRM.
    """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True, required=True)
    first_name = serializers.CharField(required=True, max_length=100)
    last_name = serializers.CharField(required=True, max_length=100)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)
    address = serializers.CharField(required=False, allow_blank=True, max_length=250)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    state = serializers.CharField(required=False, allow_blank=True, max_length=100)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=20)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100, default='Argentina')
    
    def validate(self, data):
        # Validar que las contraseñas coincidan
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"password": "Las contraseñas no coinciden"})
        
        # Validar que no exista un usuario con ese email
        email = data['email']
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError({
                "email": "Ya existe una cuenta con este email. Por favor, inicia sesión."
            })
        
        return data
    
    @transaction.atomic
    def create(self, validated_data):
        # Remover confirm_password ya que no se guarda
        validated_data.pop('confirm_password')
        
        email = validated_data['email']
        password = validated_data.pop('password')
        
        # Buscar si existe un Customer sin usuario con este email
        existing_customer = Customer.objects.filter(
            email=email, 
            user__isnull=True
        ).first()
        
        # Crear el usuario
        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            role='client'
        )
        
        if existing_customer:
            # CASO A: Cliente existe desde CRM, vincular con el nuevo usuario
            existing_customer.user = user
            
            # Actualizar campos solo si están vacíos en el customer existente
            if not existing_customer.first_name:
                existing_customer.first_name = validated_data['first_name']
            if not existing_customer.last_name:
                existing_customer.last_name = validated_data['last_name']
            if not existing_customer.phone and validated_data.get('phone'):
                existing_customer.phone = validated_data.get('phone')
            if not existing_customer.address and validated_data.get('address'):
                existing_customer.address = validated_data.get('address')
            if not existing_customer.city and validated_data.get('city'):
                existing_customer.city = validated_data.get('city')
            if not existing_customer.state and validated_data.get('state'):
                existing_customer.state = validated_data.get('state')
            if not existing_customer.postal_code and validated_data.get('postal_code'):
                existing_customer.postal_code = validated_data.get('postal_code')
            if not existing_customer.country and validated_data.get('country'):
                existing_customer.country = validated_data.get('country')
                
            existing_customer.save()
            
            return {
                'user': user,
                'customer': existing_customer,
                'linked_to_existing': True,
                'message': 'Cuenta creada y vinculada exitosamente. Se mantiene tu historial de compras previo.'
            }
        else:
            # CASO B: Cliente nuevo, crear desde cero
            customer = Customer.objects.create(
                user=user,
                email=email,
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
                phone=validated_data.get('phone', ''),
                address=validated_data.get('address', ''),
                city=validated_data.get('city', ''),
                state=validated_data.get('state', ''),
                postal_code=validated_data.get('postal_code', ''),
                country=validated_data.get('country', 'Argentina'),
                customer_type='person'
            )
            
            return {
                'user': user,
                'customer': customer,
                'linked_to_existing': False,
                'message': 'Cuenta creada exitosamente'
            }