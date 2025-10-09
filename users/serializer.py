from rest_framework import serializers
from django.contrib.auth import get_user_model
from core.store.models import Store

User = get_user_model()

# Importar Employee y Supplier usando import relativo para evitar imports circulares
from .models import Employee, Supplier

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'first_name',
            'last_name',
            'role',
            'is_active',
            'is_staff',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_active', 'is_staff', 'role']

    def validate_email(self, value):
        if not value:
            raise serializers.ValidationError("missing_email")
        return value

    def validate_first_name(self, value):
        if not value:
            raise serializers.ValidationError("missing_firstname")
        return value

    def validate_last_name(self, value):
        if not value:
            raise serializers.ValidationError("missing_lastname")
        return value
    
    def validate_role(self, value):
        valid_roles = ['superadmin', 'store_admin', 'manager', 'employee', 'client']
        if value not in valid_roles:
            raise serializers.ValidationError(f"role_not_found")
        return value
    
    def create(self, validated_data):
        request = self.context.get('request', None)
        current_user = request.user if request else None
        user = User.objects.create_user(
            email=validated_data['email'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            role=validated_data['role']
        )

        return user


class EmployeeSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Employee
        fields = [
            'id', 'user', 'user_name', 'user_email', 'store', 'store_name', 'branch', 'branch_name',
            'profile_photo', 'birth', 'date_joined', 'position', 'dni', 'cuil',
            'country', 'state', 'postal_code', 'city', 'address', 'phone',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'user_name', 'user_email', 'store_name', 'branch_name', 'created_at', 'updated_at']

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}" if obj.user else None

    def get_user_email(self, obj):
        return obj.user.email if obj.user else None

    def get_store_name(self, obj):
        return obj.store.name if obj.store else None

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else None

    def validate_dni(self, value):
        if not value:
            raise serializers.ValidationError("El DNI es obligatorio")
        if len(str(value)) < 7 or len(str(value)) > 8:
            raise serializers.ValidationError("El DNI debe tener entre 7 y 8 dígitos")
        return value

    def validate_user(self, value):
        if value.role not in ['employee', 'manager']:
            raise serializers.ValidationError("Solo se pueden asignar usuarios con rol 'employee' o 'manager'")
        return value


class EmployeeCreateSerializer(EmployeeSerializer):
    """Serializer para crear empleados con datos de usuario anidados"""
    # Campos del usuario
    email = serializers.EmailField(write_only=True)
    first_name = serializers.CharField(max_length=100, write_only=True)
    last_name = serializers.CharField(max_length=100, write_only=True)
    password = serializers.CharField(write_only=True, required=False)
    role = serializers.ChoiceField(choices=['manager', 'employee'], default='manager', write_only=True)
    
    class Meta(EmployeeSerializer.Meta):
        fields = EmployeeSerializer.Meta.fields + ['email', 'first_name', 'last_name', 'password', 'role']
        # Hacer el campo user opcional ya que lo crearemos nosotros
        extra_kwargs = {
            'user': {'required': False}
        }
    
    def validate_email(self, value):
        """Validar que el email no exista"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Ya existe un usuario con este email")
        return value
    
    def create(self, validated_data):
        # Extraer datos del usuario
        user_data = {
            'email': validated_data.pop('email'),
            'first_name': validated_data.pop('first_name'),
            'last_name': validated_data.pop('last_name'),
            'role': validated_data.pop('role', 'manager'),  # Por defecto es manager si no se especifica
            'is_active': True
        }
        
        password = validated_data.pop('password', None)
        
        # Crear el usuario primero
        user = User.objects.create_user(
            email=user_data['email'],
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            role=user_data['role'],
            password=password if password else 'defaultpassword123'  # Password temporal
        )
        
        # Asignar el usuario creado al empleado
        validated_data['user'] = user
        
        # Crear el empleado
        return super().create(validated_data)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            'id', 'name', 'fantasy_name', 'email', 'phone', 'website', 'cuit',
            'country', 'state', 'postal_code', 'city', 'address',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_name(self, value):
        if not value:
            raise serializers.ValidationError("El nombre es obligatorio")
        return value

    def validate_email(self, value):
        if value and '@' not in value:
            raise serializers.ValidationError("Formato de email inválido")
        return value

    def validate_cuit(self, value):
        if value and len(value) not in [11, 13]:  # CUIT con o sin guiones
            raise serializers.ValidationError("El CUIT debe tener 11 dígitos")
        return value


class EmployeeUpdateSerializer(EmployeeSerializer):
    """Serializer para actualizar empleados con opción de cambiar el rol del usuario"""
    role = serializers.ChoiceField(choices=['manager', 'employee'], required=False, write_only=True)
    
    class Meta(EmployeeSerializer.Meta):
        fields = EmployeeSerializer.Meta.fields + ['role']
        # Hacer que los campos obligatorios sean opcionales para actualizaciones
        extra_kwargs = {
            'store': {'required': False},
            'position': {'required': False}, 
            'dni': {'required': False},
            'birth': {'required': False},
            'date_joined': {'required': False},
        }
    
    def update(self, instance, validated_data):
        # Si se proporciona un rol, validar el cambio
        if 'role' in validated_data:
            role = validated_data.pop('role')
            current_user = instance.user
            
            # Validar que no se pueda cambiar el rol de un manager que tiene sucursales asignadas
            if current_user.role == 'manager' and role != 'manager':
                from core.store.models import Branch
                # Verificar si el usuario es manager de alguna sucursal
                managed_branches = Branch.objects.filter(manager=current_user)
                if managed_branches.exists():
                    raise serializers.ValidationError({
                        'role': f'No se puede cambiar el rol de este manager porque tiene {managed_branches.count()} sucursal(es) asignada(s). Primero debe reasignar la gestión de las sucursales a otro manager.'
                    })
            
            # Si la validación pasa, actualizar el rol
            if role in ['manager', 'employee']:
                current_user.role = role
                current_user.save()
        
        # Actualizar el resto de datos del empleado
        return super().update(instance, validated_data)


class UserWithEmployeeSerializer(UserSerializer):
    """
    Serializer que incluye información del empleado cuando el usuario es empleado o manager
    """
    employee_info = serializers.SerializerMethodField()
    
    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ['employee_info']
    
    def get_employee_info(self, obj):
        """
        Obtiene la información del empleado si el usuario es empleado o manager
        """
        if obj.role in ['employee', 'manager']:
            try:
                employee = Employee.objects.get(user=obj)
                return {
                    'id': employee.id,
                    'position': employee.position,
                    'dni': employee.dni,
                    'cuil': employee.cuil,
                    'birth': employee.birth,
                    'date_joined': employee.date_joined,
                    'phone': employee.phone,
                    'country': employee.country,
                    'state': employee.state,
                    'city': employee.city,
                    'postal_code': employee.postal_code,
                    'address': employee.address,
                    'store_id': employee.store.id if employee.store else None,
                    'store_name': employee.store.name if employee.store else None,
                    'branch_id': employee.branch.id if employee.branch else None,
                    'branch_name': employee.branch.name if employee.branch else None,
                }
            except Employee.DoesNotExist:
                return None
        return None