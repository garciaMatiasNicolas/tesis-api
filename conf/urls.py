from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('api/', include('core.store.urls')),
    path('api/', include('core.stock.urls')),
    path('api/crm/', include('core.crm.urls')),
]
