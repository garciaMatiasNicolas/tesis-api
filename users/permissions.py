from rest_framework.permissions import BasePermission

class IsNotClientPermission(BasePermission):
    """
    Permission que permite acceso solo a usuarios autenticados que NO sean clientes
    """
    message = "Los clientes no tienen permisos para acceder a esta funcionalidad."
    
    def has_permission(self, request, view):
        # Verificar que esté autenticado
        if not request.user or not request.user.is_authenticated:
            return False
            
        # Verificar que no sea cliente
        return request.user.role != 'client'