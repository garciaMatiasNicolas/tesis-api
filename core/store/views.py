from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import Store, Branch
from .serializer import (
    StoreSerializer, 
    StoreCreateSerializer, 
    StoreActivationSerializer,
    BranchSerializer
)


class StoreViewSet(viewsets.ModelViewSet):
    queryset = Store.objects.all()
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Store.objects.all()
 
    def get_serializer_class(self):
        if self.action == 'create':
            return StoreCreateSerializer
        elif self.action in ['activate', 'deactivate']:
            return StoreActivationSerializer
        return StoreSerializer

    def perform_create(self, serializer):
        # Solo store_admin y admin pueden crear tiendas
        if self.request.user.role not in ['superadmin']:
            return Response(
                {"error": "No tienes permisos para crear tiendas"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        serializer.save()

    def perform_update(self, serializer):
        # Solo el owner, manager o superadmin pueden actualizar
        store = self.get_object()
        if (self.request.user != store.owner and 
            self.request.user.role not in ['superadmin', 'manager']):
            return Response(
                {"error": "No tienes permisos para actualizar esta tienda"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # La sincronización ahora se maneja en el serializer
        serializer.save()

    def perform_destroy(self, instance):
        # Solo el owner o admin pueden eliminar
        if self.request.user != instance.owner and self.request.user.role != 'superadmin':
            return Response(
                {"error": "No tienes permisos para eliminar esta tienda"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        instance.delete()
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['patch'])
    def activate(self, request, pk=None):
        """Activar una tienda"""
        store = self.get_object()
        
        # Solo el owner o admin pueden activar
        if request.user != store.owner and request.user.role != 'admin':
            return Response(
                {"error": "No tienes permisos para activar esta tienda"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        store.is_active = True
        store.save()
        
        return Response(
            {"message": f"Tienda {store.name} activada exitosamente"}, 
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['patch'])
    def deactivate(self, request, pk=None):
        """Desactivar una tienda"""
        store = self.get_object()
        
        # Solo el owner o admin pueden desactivar
        if request.user != store.owner and request.user.role != 'admin':
            return Response(
                {"error": "No tienes permisos para desactivar esta tienda"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        store.is_active = False
        store.save()
        
        return Response(
            {"message": f"Tienda {store.name} desactivada exitosamente"}, 
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['get'])
    def branches(self, request, pk=None):
        """Obtener todas las sucursales de una tienda"""
        store = self.get_object()
        branches = store.branch_set.all()
        serializer = BranchSerializer(branches, many=True)
        return Response(serializer.data)


class BranchViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Branch.objects.all()

    def perform_create(self, serializer):
        # Solo superadmin puede crear sucursales
        if self.request.user.role not in ['superadmin']:
            return Response(
                {"error": "No tienes permisos para crear sucursales"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verificar que la tienda pertenezca al usuario (si no es superadmin)
        store = serializer.validated_data['store']
        if (self.request.user.role == 'store_admin' and 
            store.owner != self.request.user):
            return Response(
                {"error": "No puedes crear sucursales en tiendas que no te pertenecen"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer.save()

    def perform_update(self, serializer):
        # Solo el owner de la tienda, manager o superadmin pueden actualizar
        branch = self.get_object()
        if (self.request.user != branch.store.owner and 
            self.request.user.role not in ['superadmin', 'manager']):
            return Response(
                {"error": "No tienes permisos para actualizar esta sucursal"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # La sincronización ahora se maneja en el serializer
        serializer.save()

    def perform_destroy(self, instance):
        # Verificar que no sea la sucursal principal
        if instance.name.endswith("- Sucursal Principal"):
            return Response(
                {"error": "No puedes eliminar la sucursal principal"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Solo el owner de la tienda o superadmin pueden eliminar
        if (self.request.user != instance.store.owner and 
            self.request.user.role != 'superadmin'):
            return Response(
                {"error": "No tienes permisos para eliminar esta sucursal"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        instance.delete()
