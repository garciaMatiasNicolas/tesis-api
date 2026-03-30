from .views import ProductViewSet, CategoryViewSet, SubcategoryViewSet, WarehouseViewSet, ProductUnitViewSet, StockViewSet, StockMovementViewSet
from rest_framework.routers import DefaultRouter
from django.urls import path, include

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'subcategories', SubcategoryViewSet, basename='subcategory')
router.register(r'warehouses', WarehouseViewSet, basename='warehouse')
router.register(r'productunits', ProductUnitViewSet, basename='productunit')
router.register(r'stock', StockViewSet, basename='stock')
router.register(r'stock-movements', StockMovementViewSet, basename='stock-movement')

urlpatterns = [
    path('', include(router.urls)),
]