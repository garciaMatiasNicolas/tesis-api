from django.shortcuts import render
from django.db.models import Q, Sum, Count
from django.utils import timezone
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Customer
from .serializer import (
    CustomerListSerializer,
    CustomerDetailSerializer,
    CustomerCreateSerializer,
    CustomerUpdateSerializer,
    CustomerContactSerializer,
    CustomerContactHistorySerializer,
    CustomerContactUpdateSerializer
)


class CustomerViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar clientes del CRM.
    Proporciona operaciones CRUD completas con filtros y búsqueda.
    """
    queryset = Customer.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['first_name', 'last_name', 'name', 'fantasy_name', 'email', 'cuit', 'phone']
    ordering_fields = ['created_at', 'updated_at', 'last_purchase_date', 'total_spent']
    ordering = ['-created_at']

    def get_queryset(self):
        """Obtener queryset base con optimizaciones"""
        return Customer.objects.select_related('user', 'supplier').all()

    def get_serializer_class(self):
        """Seleccionar serializer según la acción"""
        if self.action == 'list':
            return CustomerListSerializer
        elif self.action == 'create':
            return CustomerCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return CustomerUpdateSerializer
        elif self.action == 'contact':
            return CustomerContactSerializer
        elif self.action == 'update_contact':
            return CustomerContactUpdateSerializer
        return CustomerDetailSerializer

    def list(self, request, *args, **kwargs):
        """Listar clientes con filtros y paginación"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Filtros adicionales por parámetros
        customer_type = request.query_params.get('type', None)
        has_purchases = request.query_params.get('has_purchases', None)
        min_spent = request.query_params.get('min_spent', None)
        max_spent = request.query_params.get('max_spent', None)
        
        if customer_type:
            queryset = queryset.filter(customer_type=customer_type)
        
        if has_purchases == 'true':
            queryset = queryset.filter(total_spent__gt=0)
        elif has_purchases == 'false':
            queryset = queryset.filter(total_spent=0)
            
        if min_spent:
            try:
                queryset = queryset.filter(total_spent__gte=float(min_spent))
            except ValueError:
                pass
                
        if max_spent:
            try:
                queryset = queryset.filter(total_spent__lte=float(max_spent))
            except ValueError:
                pass

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })

    def retrieve(self, request, *args, **kwargs):
        """Obtener detalles de un cliente específico"""
        return super().retrieve(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Crear un nuevo cliente"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Verificar permisos (solo usuarios con role específico pueden crear)
        if not hasattr(request.user, 'role') or request.user.role not in ['superadmin', 'manager', 'employee']:
            return Response(
                {"error": "No tienes permisos para crear clientes"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        customer = serializer.save()
        
        # Respuesta con serializer de detalle
        detail_serializer = CustomerDetailSerializer(customer)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """Actualizar cliente completo"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # Verificar permisos
        if not hasattr(request.user, 'role') or request.user.role not in ['superadmin', 'manager', 'employee']:
            return Response(
                {"error": "No tienes permisos para actualizar clientes"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save()
        
        # Respuesta con serializer de detalle
        detail_serializer = CustomerDetailSerializer(customer)
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        """Eliminar cliente"""
        instance = self.get_object()
        
        # Verificar permisos (solo superadmin y manager pueden eliminar)
        if not hasattr(request.user, 'role') or request.user.role not in ['superadmin', 'manager']:
            return Response(
                {"error": "No tienes permisos para eliminar clientes"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verificar que no tenga compras asociadas (ejemplo de regla de negocio)
        if instance.total_spent > 0:
            return Response(
                {"error": "No se puede eliminar un cliente que tiene compras registradas"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        customer_name = str(instance)
        instance.delete()
        
        return Response(
            {"message": f"Cliente '{customer_name}' eliminado exitosamente"}, 
            status=status.HTTP_204_NO_CONTENT
        )

    @action(detail=True, methods=['post'])
    def contact(self, request, pk=None):
        """Agregar un nuevo contacto al historial del cliente"""
        customer = self.get_object()
        serializer = CustomerContactSerializer(customer, data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response(
            {
                "message": f"Contacto agregado para {customer}",
                "contact_added": customer.contact_history[-1] if customer.contact_history else None,
                "total_contacts": customer.get_contacts_count()
            }, 
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['get'])
    def contact_history(self, request, pk=None):
        """Obtener el historial completo de contactos del cliente"""
        customer = self.get_object()
        
        return Response(
            {
                "customer_id": customer.id,
                "customer_name": str(customer),
                "contact_history": customer.contact_history or [],
                "total_contacts": customer.get_contacts_count(),
                "last_contact_date": customer.get_last_contact_date()
            }
        )
    
    @action(detail=True, methods=['patch'])
    def update_contact(self, request, pk=None):
        """Actualizar un contacto específico del historial"""
        customer = self.get_object()
        serializer = CustomerContactUpdateSerializer(
            data=request.data, 
            context={'customer': customer, 'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.update_contact(customer, serializer.validated_data)
        
        return Response(
            {
                "message": f"Contacto actualizado para {customer}",
                "contact_history": customer.contact_history,
                "total_contacts": customer.get_contacts_count()
            }
        )
    
    @action(detail=True, methods=['delete'])
    def delete_contact(self, request, pk=None):
        """Eliminar un contacto específico del historial"""
        customer = self.get_object()
        contact_index = request.data.get('contact_index')
        
        if contact_index is None:
            return Response(
                {"error": "contact_index es requerido"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            contact_index = int(contact_index)
        except ValueError:
            return Response(
                {"error": "contact_index debe ser un número"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not customer.contact_history or contact_index >= len(customer.contact_history) or contact_index < 0:
            return Response(
                {"error": "Índice de contacto inválido"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Eliminar el contacto
        deleted_contact = customer.contact_history.pop(contact_index)
        customer.save()
        
        return Response(
            {
                "message": f"Contacto eliminado para {customer}",
                "deleted_contact": deleted_contact,
                "remaining_contacts": customer.get_contacts_count()
            }
        )

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Obtener estadísticas de clientes"""
        queryset = self.get_queryset()
        
        # Calcular clientes contactados (que tienen historial de contactos)
        customers_with_contacts = queryset.exclude(contact_history=[]).exclude(contact_history__isnull=True)
        customers_without_contacts = queryset.filter(contact_history=[])
        
        stats = {
            'total_customers': queryset.count(),
            'total_persons': queryset.filter(customer_type=Customer.PERSON).count(),
            'total_companies': queryset.filter(customer_type=Customer.COMPANY).count(),
            'customers_with_purchases': queryset.filter(total_spent__gt=0).count(),
            'customers_without_purchases': queryset.filter(total_spent=0).count(),
            'customers_with_contacts': customers_with_contacts.count(),
            'customers_without_contacts': customers_without_contacts.count(),
            'total_revenue': queryset.aggregate(
                total=Sum('total_spent')
            )['total'] or 0,
            'average_spent_per_customer': 0,
            'recent_customers': queryset.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=30)
            ).count(),
            'top_countries': list(
                queryset.values('country')
                .annotate(count=Count('id'))
                .order_by('-count')[:5]
            ),
            'top_cities': list(
                queryset.values('city', 'state')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            )
        }
        
        # Calcular promedio real
        if stats['total_customers'] > 0:
            stats['average_spent_per_customer'] = stats['total_revenue'] / stats['total_customers']
        
        # Estadísticas adicionales de contactos
        total_contacts = 0
        for customer in customers_with_contacts:
            total_contacts += customer.get_contacts_count()
        
        stats['total_contacts'] = total_contacts
        stats['average_contacts_per_customer'] = (
            total_contacts / customers_with_contacts.count() 
            if customers_with_contacts.count() > 0 else 0
        )
        
        return Response(stats)

    @action(detail=False, methods=['get'])
    def search(self, request):
        """Búsqueda avanzada de clientes"""
        query = request.query_params.get('q', '')
        customer_type = request.query_params.get('type', '')
        country = request.query_params.get('country', '')
        
        if not query:
            return Response(
                {"error": "Parámetro 'q' requerido para la búsqueda"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Búsqueda en múltiples campos
        queryset = self.get_queryset().filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(name__icontains=query) |
            Q(fantasy_name__icontains=query) |
            Q(email__icontains=query) |
            Q(cuit__icontains=query) |
            Q(phone__icontains=query)
        )
        
        # Filtros adicionales
        if customer_type:
            queryset = queryset.filter(customer_type=customer_type)
        if country:
            queryset = queryset.filter(country__icontains=country)
        
        # Limitar resultados
        queryset = queryset[:20]
        
        serializer = CustomerListSerializer(queryset, many=True)
        return Response({
            'query': query,
            'count': queryset.count(),
            'results': serializer.data
        })

    @action(detail=True, methods=['patch'])
    def update_purchase_info(self, request, pk=None):
        """Actualizar información de compras del cliente"""
        customer = self.get_object()
        
        # Solo permitir actualización de campos relacionados con compras
        allowed_fields = ['last_purchase_date', 'total_spent']
        update_data = {
            key: value for key, value in request.data.items() 
            if key in allowed_fields
        }
        
        if not update_data:
            return Response(
                {"error": "No se proporcionaron campos válidos para actualizar"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = CustomerUpdateSerializer(customer, data=update_data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response(
            {
                "message": f"Información de compras actualizada para {customer}",
                "last_purchase_date": customer.last_purchase_date,
                "total_spent": customer.total_spent
            }, 
            status=status.HTTP_200_OK
        )
