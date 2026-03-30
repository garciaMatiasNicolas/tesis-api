from rest_framework.routers import DefaultRouter
from core.billing.views import SalesOrderViewSet, PurchaseOrderViewSet

router = DefaultRouter()
router.register(r'billing/sales-orders', SalesOrderViewSet, basename='sales-order')
router.register(r'billing/purchase-orders', PurchaseOrderViewSet, basename='purchase-order')

urlpatterns = router.urls