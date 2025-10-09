from django.contrib import admin
from django.utils.html import format_html
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = [
        'get_display_name', 'customer_type', 'email', 'phone', 
        'city', 'country', 'total_spent', 'last_purchase_date', 
        'created_at', 'get_status'
    ]
    list_filter = [
        'customer_type', 'country', 'state', 'city', 
        'created_at', 'last_purchase_date'
    ]
    search_fields = [
        'first_name', 'last_name', 'name', 'fantasy_name', 
        'email', 'cuit', 'phone'
    ]
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('customer_type', 'user', 'supplier')
        }),
        ('Datos de Persona Física', {
            'fields': ('first_name', 'last_name', 'date_of_birth'),
            'classes': ('collapse',),
        }),
        ('Datos de Empresa', {
            'fields': ('name', 'fantasy_name', 'cuit'),
            'classes': ('collapse',),
        }),
        ('Información de Contacto', {
            'fields': ('email', 'phone', 'address', 'city', 'state', 'country', 'postal_code')
        }),
        ('Actividad Comercial', {
            'fields': ('total_spent', 'last_purchase_date', 'last_date_contacted', 'comments')
        }),
        ('Metadatos', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def get_display_name(self, obj):
        """Obtener nombre para mostrar"""
        if obj.customer_type == Customer.PERSON:
            return f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return obj.name or obj.fantasy_name or 'Sin nombre'
    get_display_name.short_description = 'Nombre'
    get_display_name.admin_order_field = 'first_name'
    
    def get_status(self, obj):
        """Estado del cliente basado en actividad"""
        if obj.total_spent > 0:
            if obj.last_purchase_date:
                # Cliente activo
                return format_html(
                    '<span style="color: green;">●</span> Activo'
                )
            else:
                # Cliente con compras pero sin fecha
                return format_html(
                    '<span style="color: orange;">●</span> Con Compras'
                )
        else:
            # Cliente sin compras
            return format_html(
                '<span style="color: red;">●</span> Sin Compras'
            )
    get_status.short_description = 'Estado'
    
    def get_queryset(self, request):
        """Optimizar consultas"""
        return super().get_queryset(request).select_related('user', 'supplier')
    
    # Acciones personalizadas
    actions = ['mark_as_contacted', 'export_to_csv']
    
    def mark_as_contacted(self, request, queryset):
        """Marcar clientes como contactados hoy"""
        from django.utils import timezone
        updated = queryset.update(last_date_contacted=timezone.now())
        self.message_user(
            request, 
            f'{updated} cliente(s) marcado(s) como contactado(s) hoy.'
        )
    mark_as_contacted.short_description = "Marcar como contactados hoy"
    
    def export_to_csv(self, request, queryset):
        """Exportar clientes seleccionados a CSV"""
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="clientes.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Tipo', 'Nombre', 'Email', 'Teléfono', 'Ciudad', 
            'País', 'Total Gastado', 'Última Compra', 'Creado'
        ])
        
        for customer in queryset:
            writer.writerow([
                customer.id,
                customer.get_customer_type_display(),
                self.get_display_name(customer),
                customer.email or '',
                customer.phone or '',
                customer.city or '',
                customer.country or '',
                customer.total_spent,
                customer.last_purchase_date.strftime('%Y-%m-%d') if customer.last_purchase_date else '',
                customer.created_at.strftime('%Y-%m-%d')
            ])
        
        return response
    export_to_csv.short_description = "Exportar a CSV"
