from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet

# Crear el router para las APIs REST
router = DefaultRouter()
router.register(r'customers', CustomerViewSet, basename='customer')

urlpatterns = [
    path('', include(router.urls)),
]
