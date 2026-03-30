from rest_framework import serializers
from django.utils import timezone
from .models import Customer
from users.models import User, Supplier


class CustomerListSerializer(serializers.ModelSerializer):
    """Serializer para listar clientes (campos básicos)"""
    full_name = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    last_contact_date = serializers.SerializerMethodField()
    contacts_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = [
            'id', 'customer_type', 'full_name', 'display_name', 'first_name', 'last_name', 'date_of_birth', 'name', 'fantasy_name', 'email', 'phone', 'city', 'state', 'country', 'postal_code', 'address', 'cuit', 'comments', 'total_spent', 'last_purchase_date', 'last_contact_date', 'contacts_count', 'created_at', 'updated_at'
        ]
        
    def get_full_name(self, obj):
        if obj.customer_type == Customer.PERSON:
            return f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return obj.name or obj.fantasy_name
        
    def get_display_name(self, obj):
        if obj.customer_type == Customer.PERSON:
            return f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return obj.name or obj.fantasy_name or 'Sin nombre'
    
    def get_last_contact_date(self, obj):
        return obj.get_last_contact_date()
    
    def get_contacts_count(self, obj):
        return obj.get_contacts_count()


class CustomerDetailSerializer(serializers.ModelSerializer):
    """Serializer para detalles completos del cliente"""
    full_name = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    user_username = serializers.CharField(source='user.username', read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    last_contact_date = serializers.SerializerMethodField()
    contacts_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = [
            'id', 'customer_type', 'full_name', 'display_name',
            'user', 'user_username', 'supplier', 'supplier_name',
            'email', 'phone', 'address', 'country', 'state', 'city', 'postal_code',
            'first_name', 'last_name', 'date_of_birth',
            'name', 'fantasy_name', 'cuit',
            'comments', 'contact_history', 'last_contact_date', 'contacts_count',
            'last_purchase_date', 'total_spent',
            'created_at', 'updated_at'
        ]
        
    def get_full_name(self, obj):
        if obj.customer_type == Customer.PERSON:
            return f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return obj.name or obj.fantasy_name
        
    def get_display_name(self, obj):
        if obj.customer_type == Customer.PERSON:
            return f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return obj.name or obj.fantasy_name or 'Sin nombre'
    
    def get_last_contact_date(self, obj):
        return obj.get_last_contact_date()
    
    def get_contacts_count(self, obj):
        return obj.get_contacts_count()


class CustomerCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear clientes"""
    
    class Meta:
        model = Customer
        fields = [
            'customer_type', 'user', 'supplier',
            'email', 'phone', 'address', 'country', 'state', 'city', 'postal_code',
            'first_name', 'last_name', 'date_of_birth',
            'name', 'fantasy_name', 'cuit',
            'comments'
        ]
        
    def validate(self, data):
        customer_type = data.get('customer_type')
        
        # Validaciones para persona física
        if customer_type == Customer.PERSON:
            if not data.get('first_name') or not data.get('last_name'):
                raise serializers.ValidationError(
                    "Para personas físicas, nombre y apellido son obligatorios."
                )
            # Limpiar campos de empresa
            data['name'] = None
            data['fantasy_name'] = None
            data['cuit'] = None
            
        # Validaciones para empresa
        elif customer_type == Customer.COMPANY:
            if not data.get('name'):
                raise serializers.ValidationError(
                    "Para empresas, el nombre de la empresa es obligatorio."
                )
            # Limpiar campos de persona
            data['first_name'] = None
            data['last_name'] = None
            data['date_of_birth'] = None
            
        # Validar email único si se proporciona
        email = data.get('email')
        if email and Customer.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                "Ya existe un cliente con este email."
            )
            
        # Validar CUIT único si se proporciona
        cuit = data.get('cuit')
        if cuit and Customer.objects.filter(cuit=cuit).exists():
            raise serializers.ValidationError(
                "Ya existe un cliente con este CUIT."
            )
            
        return data


class CustomerUpdateSerializer(serializers.ModelSerializer):
    """Serializer para actualizar clientes"""
    
    class Meta:
        model = Customer
        fields = [
            'customer_type', 'user', 'supplier',
            'email', 'phone', 'address', 'country', 'state', 'city', 'postal_code',
            'first_name', 'last_name', 'date_of_birth',
            'name', 'fantasy_name', 'cuit',
            'comments', 'contact_history', 'last_purchase_date', 'total_spent'
        ]
        
    def validate(self, data):
        customer_type = data.get('customer_type', self.instance.customer_type)
        
        # Validaciones para persona física
        if customer_type == Customer.PERSON:
            if 'first_name' in data and 'last_name' in data:
                if not data.get('first_name') or not data.get('last_name'):
                    raise serializers.ValidationError(
                        "Para personas físicas, nombre y apellido son obligatorios."
                    )
            # Si cambiamos a persona, limpiar campos de empresa
            if data.get('customer_type') == Customer.PERSON:
                data['name'] = None
                data['fantasy_name'] = None
                data['cuit'] = None
                
        # Validaciones para empresa
        elif customer_type == Customer.COMPANY:
            if 'name' in data and not data.get('name'):
                raise serializers.ValidationError(
                    "Para empresas, el nombre de la empresa es obligatorio."
                )
            # Si cambiamos a empresa, limpiar campos de persona
            if data.get('customer_type') == Customer.COMPANY:
                data['first_name'] = None
                data['last_name'] = None
                data['date_of_birth'] = None
                
        # Validar email único si se proporciona y cambió
        email = data.get('email')
        if email and email != self.instance.email:
            if Customer.objects.filter(email=email).exists():
                raise serializers.ValidationError(
                    "Ya existe un cliente con este email."
                )
                
        # Validar CUIT único si se proporciona y cambió
        cuit = data.get('cuit')
        if cuit and cuit != self.instance.cuit:
            if Customer.objects.filter(cuit=cuit).exists():
                raise serializers.ValidationError(
                    "Ya existe un cliente con este CUIT."
                )
                
        return data


class CustomerContactSerializer(serializers.ModelSerializer):
    """Serializer para agregar contactos al historial"""
    comment = serializers.CharField(write_only=True, required=True)
    medium = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = Customer
        fields = ['comment', 'medium', 'contact_history']
        read_only_fields = ['contact_history']
        
    def update(self, instance, validated_data):
        comment = validated_data.pop('comment')
        medium = validated_data.pop('medium', None)
        # Usar el método add_contact del modelo
        user = User.objects.get(id=self.context['request'].user.id)
        instance.add_contact(comment, medium=medium, user=user)
        return instance


class CustomerContactHistorySerializer(serializers.Serializer):
    """Serializer para manejar el historial de contactos completo"""
    date = serializers.DateTimeField(read_only=True)
    comment = serializers.CharField(read_only=True)
    user = serializers.CharField(read_only=True)
    user_id = serializers.IntegerField(read_only=True, allow_null=True)


class CustomerContactUpdateSerializer(serializers.Serializer):
    """Serializer para actualizar un contacto específico del historial"""
    contact_index = serializers.IntegerField(required=True)
    comment = serializers.CharField(required=True)
    
    def validate_contact_index(self, value):
        customer = self.context['customer']
        if not customer.contact_history or value >= len(customer.contact_history) or value < 0:
            raise serializers.ValidationError("Índice de contacto inválido")
        return value
    
    def update_contact(self, customer, validated_data):
        index = validated_data['contact_index']
        new_comment = validated_data['comment']
        
        # Actualizar el comentario en el historial
        customer.contact_history[index]['comment'] = new_comment
        customer.contact_history[index]['edited_date'] = timezone.now().isoformat()
        customer.contact_history[index]['edited_by'] = self.context['request'].user.username
        
        customer.save()
        return customer
