from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user_model
from django.db.models import Q
from .serializer import UserSerializer, EmployeeSerializer, SupplierSerializer, EmployeeCreateSerializer, EmployeeUpdateSerializer, UserWithEmployeeSerializer
from .models import Employee, Supplier
from rest_framework.permissions import IsAuthenticated
from core.store.models import Branch
from .permissions import IsNotClientPermission

User = get_user_model()


class UserModelViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [AllowAny()]
        elif self.action in ['list', 'retrieve', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated()]
        
        return super().get_permissions()
    
    ## Lista todos los usuarios
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    ## Lista un usuario por su ID
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Obtener información del usuario actual incluyendo datos del empleado si corresponde"""
        # Usar el serializer extendido que incluye información del empleado
        serializer = UserWithEmployeeSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    ## Crea un nuevo usuario
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        if serializer.is_valid():
            user = serializer.save()
            return Response({"message": "user_created", "user": self.get_serializer(user).data}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    ## Actualiza un usuario por su ID
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "user_updated", "user": serializer.data}, 
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    ## Elimina un usuario por su ID
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response({"message": "user_deleted"}, status=status.HTTP_204_NO_CONTENT)


class EmailExistsAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        email = request.GET.get('email')
        
        if not email:
            return Response(
                data={'error': 'Email parameter is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            User.objects.get(email=email)
            # Email existe, no está disponible
            return Response(data={'available': False, 'exists': True}, status=status.HTTP_200_OK)
        except ObjectDoesNotExist:
            # Email no existe, está disponible
            return Response(data={'available': True, 'exists': False}, status=status.HTTP_200_OK)


class VerifyIsClientAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        user_data = {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role
        }
        
        if user.role == 'client':
            return Response(data={'is_client': True, 'user': user_data}, status=status.HTTP_200_OK)
        else:
            return Response(data={'is_client': False, 'user': user_data}, status=status.HTTP_200_OK)


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsNotClientPermission]

    def get_serializer_class(self):
        if self.action == 'create':
            return EmployeeCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return EmployeeUpdateSerializer
        return EmployeeSerializer

    def get_queryset(self):
        user = self.request.user
        
        if user.role == 'superadmin':
            # Superadmin puede ver todos los empleados
            return Employee.objects.all()
        elif user.role == 'manager':
            # Manager solo puede ver empleados de su sucursal
            try:
                manager_employee = Employee.objects.get(user=user)
                if manager_employee.branch:
                    return Employee.objects.filter(branch=manager_employee.branch)
                else:
                    # Si el manager no tiene sucursal asignada, no puede ver empleados
                    return Employee.objects.none()
            except Employee.DoesNotExist:
                # Si el manager no tiene registro de empleado, no puede ver empleados
                return Employee.objects.none()
        else:
            # Otros roles no pueden ver empleados
            return Employee.objects.none()

    def create(self, request, *args, **kwargs):
        user = request.user
        
        if user.role not in ['superadmin', 'manager']:
            return Response(
                {"error": "No tienes permisos para crear empleados"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Si es manager, verificar que solo pueda crear empleados en su sucursal
        if user.role == 'manager':
            # Obtener la sucursal del manager
            try:
                manager_employee = Employee.objects.get(user=user)
                manager_branch = manager_employee.branch
                
                if not manager_branch:
                    return Response(
                        {"error": "No tienes una sucursal asignada para crear empleados"}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Verificar que la sucursal especificada sea la del manager
                branch_id = request.data.get('branch')
                if branch_id and int(branch_id) != manager_branch.id:
                    return Response(
                        {"error": "Solo puedes crear empleados en tu propia sucursal"}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Si no se especifica sucursal, asignar automáticamente la del manager
                if not branch_id:
                    request.data['branch'] = manager_branch.id
                    
            except Employee.DoesNotExist:
                return Response(
                    {"error": "No tienes registro de empleado para crear otros empleados"}, 
                    status=status.HTTP_403_FORBIDDEN
                )

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Empleado creado exitosamente", "employee": serializer.data}, 
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        user = request.user

        # Verificar permisos de edición
        if user.role == 'superadmin':
            # Superadmin puede editar cualquier empleado
            pass
        elif user.role == 'manager':
            # Manager solo puede editar empleados de su propia sucursal
            try:
                manager_employee = Employee.objects.get(user=user)
                manager_branch = manager_employee.branch
                
                if not manager_branch:
                    return Response(
                        {"error": "No tienes una sucursal asignada"}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Verificar que el empleado pertenezca a la sucursal del manager
                if not instance.branch or instance.branch.id != manager_branch.id:
                    return Response(
                        {"error": "Solo puedes editar empleados de tu propia sucursal"}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
                    
            except Employee.DoesNotExist:
                return Response(
                    {"error": "No tienes registro de empleado"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
        elif user.role == 'employee':
            # Employee solo puede editar su propio registro
            if instance.user != user:
                return Response(
                    {"error": "Solo puedes editar tus propios datos"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            return Response(
                {"error": "No tienes permisos para editar empleados"}, 
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Empleado actualizado exitosamente", "employee": serializer.data}, 
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        user = request.user

        # Solo superadmin y manager pueden eliminar empleados
        if user.role == 'superadmin':
            # Superadmin puede eliminar cualquier empleado
            pass
        elif user.role == 'manager':
            # Manager solo puede eliminar empleados de su propia sucursal
            try:
                manager_employee = Employee.objects.get(user=user)
                manager_branch = manager_employee.branch
                
                if not manager_branch:
                    return Response(
                        {"error": "No tienes una sucursal asignada"}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Verificar que el empleado pertenezca a la sucursal del manager
                if not instance.branch or instance.branch.id != manager_branch.id:
                    return Response(
                        {"error": "Solo puedes eliminar empleados de tu propia sucursal"}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
                    
            except Employee.DoesNotExist:
                return Response(
                    {"error": "No tienes registro de empleado"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            return Response(
                {"error": "No tienes permisos para eliminar empleados"}, 
                status=status.HTTP_403_FORBIDDEN
            )

        User.objects.get(id=instance.user.id).delete()
        instance.delete()
        return Response(
            {"message": "Empleado eliminado exitosamente"}, 
            status=status.HTTP_204_NO_CONTENT
        )

    @action(detail=False, methods=['get'])
    def by_branch(self, request):
        """Obtener empleados por sucursal"""
        branch_id = request.query_params.get('branch_id')
        if not branch_id:
            return Response(
                {"error": "El parámetro branch_id es requerido"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user
        try:
            branch = Branch.objects.get(id=branch_id)
        except Branch.DoesNotExist:
            return Response(
                {"error": "La sucursal no existe"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        # Verificar permisos
        if user.role == 'superadmin':
            # Superadmin puede ver empleados de cualquier sucursal
            pass
        elif user.role == 'manager':
            # Manager solo puede ver empleados de sus sucursales
            if branch.manager != user:
                return Response(
                    {"error": "No tienes permisos para ver empleados de esta sucursal"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            return Response(
                {"error": "No tienes permisos para esta operación"}, 
                status=status.HTTP_403_FORBIDDEN
            )

        employees = Employee.objects.filter(branch=branch)
        serializer = self.get_serializer(employees, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsNotClientPermission]

    def list(self, request, *args, **kwargs):
        # Todos los usuarios autenticados pueden ver proveedores
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        # Todos los usuarios autenticados pueden ver un proveedor específico
        return super().retrieve(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        # Por ahora no hay restricciones para crear proveedores
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            supplier = serializer.save()
            return Response(
                {"message": "Proveedor creado exitosamente", "supplier": serializer.data}, 
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        # Por ahora no hay restricciones para actualizar proveedores
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Proveedor actualizado exitosamente", "supplier": serializer.data}, 
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        # Por ahora no hay restricciones para eliminar proveedores
        instance = self.get_object()
        instance.delete()
        return Response(
            {"message": "Proveedor eliminado exitosamente"}, 
            status=status.HTTP_204_NO_CONTENT
        )

    @action(detail=False, methods=['get'])
    def search(self, request):
        """Buscar proveedores por nombre o CUIT"""
        query = request.query_params.get('q', '')
        if not query:
            return Response(
                {"error": "El parámetro 'q' es requerido para la búsqueda"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        suppliers = Supplier.objects.filter(
            Q(name__icontains=query) |
            Q(fantasy_name__icontains=query) |
            Q(cuit__icontains=query)
        )
        
        serializer = self.get_serializer(suppliers, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)