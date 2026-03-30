from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal
from ..stock.models import Product, Category, Subcategory
from .models import Cart, CartItem
from core.billing.models import SalesOrder, SalesItem
from core.crm.models import Customer
from .serializer import (
    ProductSerializer, CategorySerializer, SubcategorySerializer,
    CartSerializer, CartItemSerializer, SalesOrderSerializer, SalesItemSerializer,
    CustomerSerializer
)
from users.models import Supplier
from users.serializer import SupplierSerializer
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import NotFound, ValidationError
from django.db import transaction
from users.permissions import IsNotClientPermission


class ProductPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 100


class ProductList(APIView):
    """
    Vista pública para listar productos con filtros y paginación
    """
    permission_classes = [AllowAny]

    def get(self, request):
        products = Product.objects.all()
        
        # Filtros
        category_id = request.query_params.get('category', None)
        subcategory_id = request.query_params.get('subcategory', None)
        search = request.query_params.get('search', None)
        min_price = request.query_params.get('min_price', None)
        max_price = request.query_params.get('max_price', None)
        sort_by = request.query_params.get('sort_by', None)
        
        # Aplicar filtros
        if category_id:
            products = products.filter(category_id=category_id)
            
        if subcategory_id:
            products = products.filter(subcategory_id=subcategory_id)
            
        if search:
            products = products.filter(
                Q(description__icontains=search) |
                Q(sku__icontains=search)
            )
            
        if min_price:
            try:
                products = products.filter(price__gte=float(min_price))
            except ValueError:
                pass
                
        if max_price:
            try:
                products = products.filter(price__lte=float(max_price))
            except ValueError:
                pass
        
        # Ordenamiento
        if sort_by == 'price_asc':
            products = products.order_by('price')
        elif sort_by == 'price_desc':
            products = products.order_by('-price')
        elif sort_by == 'name_asc':
            products = products.order_by('description')
        elif sort_by == 'name_desc':
            products = products.order_by('-description')
        elif sort_by == 'newest':
            products = products.order_by('-created_at')
        else:
            products = products.order_by('-created_at')  # Por defecto más nuevos primero
        
        # Paginación
        paginator = ProductPagination()
        page = paginator.paginate_queryset(products, request)
        
        if page is not None:
            serializer = ProductSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = ProductSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)


class CategoryList(APIView):
    """
    Vista pública para listar todas las categorías
    """
    permission_classes = [AllowAny]

    def get(self, request):
        categories = Category.objects.all().order_by('name')
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)


class SubcategoryList(APIView):
    """
    Vista pública para listar subcategorías, opcionalmente filtradas por categoría
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        subcategories = Subcategory.objects.all()
        
        category_id = request.query_params.get('category', None)
        if category_id:
            subcategories = subcategories.filter(category_id=category_id)
            
        subcategories = subcategories.order_by('name')
        serializer = SubcategorySerializer(subcategories, many=True)
        return Response(serializer.data)


class SupplierList(APIView):
    """
    Vista pública para listar proveedores
    """
    permission_classes = [AllowAny]

    def get(self, request):
        suppliers = Supplier.objects.all()
        serializer = SupplierSerializer(suppliers, many=True)
        return Response(serializer.data)


class ProductDetail(APIView):
    """
    Vista pública para obtener detalles de un producto específico
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            product = Product.objects.get(pk=pk)
            serializer = ProductSerializer(product)
            return Response(serializer.data)
        except Product.DoesNotExist:
            return Response(
                {"error": "Producto no encontrado"}, 
                status=status.HTTP_404_NOT_FOUND
            )


class CartManagement(APIView):
    """
    API para gestionar carritos de compra
    """
    permission_classes = [IsAuthenticated]  # Cambiar a IsAuthenticated cuando se implemente autenticación
    
    def get(self, request):
        """Obtener el carrito del cliente"""
        customer_id = request.query_params.get('customer_id')
        
        if customer_id:
            try:
                customer = Customer.objects.get(id=customer_id)
            except Customer.DoesNotExist:
                return Response({"error": "Cliente no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({"error": "Se requiere customer_id"}, status=status.HTTP_400_BAD_REQUEST)
            
        # Obtener el carrito actual o crear uno nuevo
        cart, created = Cart.objects.get_or_create(
            customer=customer,
            sales_order__isnull=True,  # Solo carritos que no estén asociados a una orden
            defaults={"customer": customer}
        )
        
        serializer = CartSerializer(cart)
        return Response(serializer.data)
    
    @transaction.atomic
    def post(self, request):
        """Crear un nuevo carrito para el cliente"""
        user_id = request.user.id
        customer_id = request.data.get('customer_id')
        
        if not customer_id:
            return Response({"error": "Se requiere customer_id"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({"error": "Cliente no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        
        if customer.user.id != user_id:
            return Response({"error": "No autorizado para este cliente"}, status=status.HTTP_403_FORBIDDEN)
        
        # Verificar si ya existe un carrito activo para este cliente
        existing_cart = Cart.objects.filter(customer=customer, sales_order__isnull=True).order_by('-created_at').first()
        
        if existing_cart:
            serializer = CartSerializer(existing_cart)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        # Crear nuevo carrito
        cart = Cart.objects.create(customer=customer)
        serializer = CartSerializer(cart)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CustomerData(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        try:
            customer = Customer.objects.get(user=user)
        except Customer.DoesNotExist:
            return Response({"error": "customer_not_found"}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = CustomerSerializer(customer)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def patch(self, request):
        """Actualizar datos del perfil del cliente"""
        user = request.user

        try:
            customer = Customer.objects.get(user=user)
        except Customer.DoesNotExist:
            return Response({"error": "customer_not_found"}, status=status.HTTP_404_NOT_FOUND)
        
        # Crear diccionario con solo los campos que se pueden actualizar
        allowed_fields = [
            'first_name', 'last_name', 'name', 'fantasy_name', 'email', 
            'phone', 'address', 'city', 'state', 'country', 'postal_code', 
            'document_type', 'document_number', 'cuit', 'birth_date',
            'customer_type', 'description'
        ]
        
        update_data = {}
        for field in allowed_fields:
            if field in request.data:
                update_data[field] = request.data[field]
        
        if not update_data:
            return Response(
                {"error": "No se proporcionaron campos válidos para actualizar"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Si se actualiza el email, también actualizar el usuario
        if 'email' in update_data:
            user.email = update_data['email']
            user.save()
        
        # Si se actualizan first_name o last_name, también actualizar el usuario
        if 'first_name' in update_data:
            user.first_name = update_data['first_name']
            user.save()
        
        if 'last_name' in update_data:
            user.last_name = update_data['last_name']
            user.save()
        
        # Actualizar el customer con validación
        serializer = CustomerSerializer(customer, data=update_data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        """Actualización completa del perfil del cliente"""
        user = request.user

        try:
            customer = Customer.objects.get(user=user)
        except Customer.DoesNotExist:
            return Response({"error": "customer_not_found"}, status=status.HTTP_404_NOT_FOUND)
        
        # Actualizar también el usuario si se proporcionan los campos correspondientes
        if 'email' in request.data:
            user.email = request.data['email']
            user.save()
        
        if 'first_name' in request.data:
            user.first_name = request.data['first_name']
            user.save()
        
        if 'last_name' in request.data:
            user.last_name = request.data['last_name']
            user.save()
        
        # Actualizar el customer
        serializer = CustomerSerializer(customer, data=request.data, partial=False)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CartItemManagement(APIView):
    """
    API para gestionar los items de un carrito
    """
    permission_classes = [IsAuthenticated]  # Cambiar a IsAuthenticated cuando se implemente autenticación
    
    def get_cart(self, cart_id):
        try:
            return Cart.objects.get(id=cart_id)
        except Cart.DoesNotExist:
            raise NotFound("Carrito no encontrado")
    
    def get(self, request, cart_id):
        """Obtener todos los items de un carrito"""
        cart = self.get_cart(cart_id)
        items = cart.cart_items.all()
        serializer = CartItemSerializer(items, many=True)
        return Response(serializer.data)
    
    def post(self, request, cart_id):
        """Agregar un producto al carrito"""
        cart = self.get_cart(cart_id)
        
        # Verificar si el carrito ya está asociado a una orden
        if cart.sales_order:
            return Response(
                {"error": "Este carrito ya ha sido procesado como una orden"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        product_id = request.data.get('product_id')
        quantity = request.data.get('quantity', 1)
        
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            return Response({"error": "Producto no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        
        # Verificar si el producto ya está en el carrito
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={"quantity": quantity}
        )
        
        # Si ya existía, actualizar la cantidad
        if not created:
            cart_item.quantity += int(quantity)
            cart_item.save()
        
        serializer = CartItemSerializer(cart_item)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
    def put(self, request, cart_id, item_id=None):
        """Actualizar la cantidad de un producto en el carrito"""
        cart = self.get_cart(cart_id)
        
        # Verificar si el carrito ya está asociado a una orden
        if cart.sales_order:
            return Response(
                {"error": "Este carrito ya ha sido procesado como una orden"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not item_id:
            return Response({"error": "Se requiere item_id"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            item = CartItem.objects.get(id=item_id, cart=cart)
        except CartItem.DoesNotExist:
            return Response({"error": "Item no encontrado en el carrito"}, status=status.HTTP_404_NOT_FOUND)
        
        quantity = request.data.get('quantity')
        
        if quantity is None:
            return Response({"error": "Se requiere quantity"}, status=status.HTTP_400_BAD_REQUEST)
        
        quantity = int(quantity)
        
        if quantity <= 0:
            item.delete()
            return Response({"message": "Item eliminado del carrito"}, status=status.HTTP_204_NO_CONTENT)
        
        item.quantity = quantity
        item.save()
        
        serializer = CartItemSerializer(item)
        return Response(serializer.data)
    
    def delete(self, request, cart_id, item_id=None):
        """Eliminar un producto del carrito"""
        cart = self.get_cart(cart_id)
        
        # Verificar si el carrito ya está asociado a una orden
        if cart.sales_order:
            return Response(
                {"error": "Este carrito ya ha sido procesado como una orden"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if item_id:
            try:
                item = CartItem.objects.get(id=item_id, cart=cart)
                item.delete()
                return Response({"message": "Item eliminado del carrito"}, status=status.HTTP_204_NO_CONTENT)
            except CartItem.DoesNotExist:
                return Response({"error": "Item no encontrado en el carrito"}, status=status.HTTP_404_NOT_FOUND)
        else:
            # Si no se proporciona item_id, eliminar todos los items del carrito
            cart.cart_items.all().delete()
            return Response({"message": "Todos los items fueron eliminados del carrito"}, status=status.HTTP_204_NO_CONTENT)


class CheckoutCart(APIView):
    """
    API para convertir un carrito en una orden de venta (checkout)
    """
    permission_classes = [IsAuthenticated]  # Cambiar a IsAuthenticated cuando se implemente autenticación
    
    @transaction.atomic
    def post(self, request, cart_id):
        """Convertir un carrito en una orden de venta"""
        try:
            cart = Cart.objects.get(id=cart_id)
        except Cart.DoesNotExist:
            return Response({"error": "Carrito no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        
        # Verificar si el carrito ya está asociado a una orden
        if cart.sales_order:
            return Response(
                {"error": "Este carrito ya ha sido procesado como una orden"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verificar si el carrito tiene items
        if not cart.cart_items.exists():
            return Response(
                {"error": "El carrito está vacío, no se puede crear una orden"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener datos del request para la orden
        payment_method = request.data.get('payment_method', 'efectivo')
        delivery_date = request.data.get('delivery_date', timezone.now().date())
        deliver_to = request.data.get('deliver_to', cart.customer.address if cart.customer.address else '')
        shipping_cost = Decimal(str(request.data.get('shipping_cost', 0)))
        taxes = Decimal(str(request.data.get('taxes', 0)))
        discount = Decimal(str(request.data.get('discount', 0)))
        description = request.data.get('notes', '')
        
        # Calcular total de los productos
        subtotal = Decimal('0')
        for item in cart.cart_items.all():
            subtotal += item.product.price * item.quantity
        
        # Calcular total final
        total_price = subtotal + shipping_cost + taxes - discount
        
        # Crear orden de venta
        sales_order = SalesOrder.objects.create(
            customer=cart.customer,
            sales_channel='ecommerce',
            payment_method=payment_method,
            delivery_date=delivery_date,
            deliver_to=deliver_to,
            shipping_cost=shipping_cost,
            total_price=total_price,
            taxes=taxes,
            discount=discount,
            description=description,
            status='pending'
        )
        
        # Transferir items del carrito a la orden
        for cart_item in cart.cart_items.all():
            SalesItem.objects.create(
                sales_order=sales_order,
                product=cart_item.product,
                quantity=cart_item.quantity
            )
        
        # Actualizar relación del carrito con la orden
        cart.sales_order = sales_order
        cart.save()
        
        serializer = SalesOrderSerializer(sales_order)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    