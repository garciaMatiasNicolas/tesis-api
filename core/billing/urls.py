from django.urls import path
from rest_framework.routers import DefaultRouter
from core.billing.views import (
    SalesOrderViewSet, 
    PurchaseOrderViewSet,
    stats_overview,
    sales_chart,
    top_products,
    stock_alerts,
    sales_by_channel,
    order_status_summary
)

router = DefaultRouter()
router.register(r'billing/sales-orders', SalesOrderViewSet, basename='sales-order')
router.register(r'billing/purchase-orders', PurchaseOrderViewSet, basename='purchase-order')

# URLs adicionales para estadísticas
stats_urls = [
    path('billing/stats/overview/', stats_overview, name='stats-overview'),
    path('billing/stats/sales-chart/', sales_chart, name='sales-chart'),
    path('billing/stats/top-products/', top_products, name='top-products'),
    path('billing/stats/stock-alerts/', stock_alerts, name='stock-alerts'),
    path('billing/stats/sales-by-channel/', sales_by_channel, name='sales-by-channel'),
    path('billing/stats/order-status/', order_status_summary, name='order-status-summary'),
]

urlpatterns = router.urls + stats_urls