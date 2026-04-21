from django.urls import path
from . import views

urlpatterns = [
    # Vistas de productos
    path('products/', views.ProductList.as_view(), name='product-list'),
    path('products/<int:pk>/', views.ProductDetail.as_view(), name='product-detail'),
    
    # Vistas de categorías y subcategorías
    path('categories/', views.CategoryList.as_view(), name='category-list'),
    path('subcategories/', views.SubcategoryList.as_view(), name='subcategory-list'),
    path('suppliers/', views.SupplierList.as_view(), name='supplier-list'),
    
    # Registro de clientes
    path('register/', views.CustomerRegistration.as_view(), name='customer-registration'),
    
    # Vistas de carritos
    path('carts/', views.CartManagement.as_view(), name='cart-management'),
    path('carts/<int:cart_id>/items/', views.CartItemManagement.as_view(), name='cart-item-list'),
    path('carts/<int:cart_id>/items/<int:item_id>/', views.CartItemManagement.as_view(), name='cart-item-detail'),

    # Vista para obtener datos del cliente
    path('customers/me/', views.CustomerData.as_view(), name='customer-data'),

    # Checkout
    path('carts/<int:cart_id>/checkout/', views.CheckoutCart.as_view(), name='cart-checkout'),
]