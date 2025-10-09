from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StoreViewSet, BranchViewSet

router = DefaultRouter()
router.register(r'stores', StoreViewSet, basename='store')
router.register(r'branches', BranchViewSet, basename='branch')

urlpatterns = [
    path('', include(router.urls)),
]