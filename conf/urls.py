from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('api/', include('core.store.urls')),
    path('api/', include('core.stock.urls')),
    path('api/', include('core.billing.urls')),
    path('api/crm/', include('core.crm.urls')),
    path('api/ecommerce/', include('core.ecommerce.urls')),
]

# Servir archivos media en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
