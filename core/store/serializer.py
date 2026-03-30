from rest_framework import serializers
from .models import Store, Branch
from users.models import User


class StoreConfigSerializer(serializers.ModelSerializer):
    """
    Serializer para la configuración pública de la tienda (ecommerce)
    """
    class Meta:
        model = Store
        fields = ['id', 'name', 'logo', 'view_only', 'is_active', 'dark_mode', 'theme_id', 'phone']
        read_only_fields = ['id', 'name', 'logo', 'view_only', 'is_active', 'dark_mode', 'theme_id', 'phone']


class StoreThemeConfigSerializer(serializers.ModelSerializer):
    """
    Serializer para actualizar la configuración visual de la tienda (logo y paleta de colores)
    """
    class Meta:
        model = Store
        fields = ['logo', 'theme_id', 'dark_mode']
        
    # Las validaciones de los colores han sido eliminadas ya que ahora se usa theme_id


class BranchSerializer(serializers.ModelSerializer):
    manager_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Branch
        fields = [
            'id', 'name', 'manager', 'manager_name', 'store', 
            'country', 'state', 'postal_code', 'city', 'address', 
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'manager_name']

    def get_manager_name(self, obj):
        return f"{obj.manager.first_name} {obj.manager.last_name}" if obj.manager else None

    def validate_manager(self, value):
        if value is None:
            return value  # Permitir manager nulo
        
        if value.role not in ['manager', 'superadmin']:
            raise serializers.ValidationError("El gerente de la sucursal debe tener el rol de manager o superadmin. Para cambiar los roles de sus empleados, vaya a la sección de usuarios.")
        return value

    def validate(self, data):
        """Validación personalizada para la sucursal"""
        # Si se está actualizando una instancia existente
        if self.instance:
            branch_name = data.get('name', self.instance.name)
            manager = data.get('manager', self.instance.manager)
            store = data.get('store', self.instance.store)
        else:
            # Si se está creando una nueva instancia
            branch_name = data.get('name', '')
            manager = data.get('manager')
            store = data.get('store')
        
        # Validar que solo el owner de la store pueda ser manager de la sucursal principal
        if branch_name and branch_name.endswith("- Sucursal Principal"):
            if manager and store:
                if manager != store.owner:
                    raise serializers.ValidationError({
                        'manager': 'Solo el propietario de la tienda puede ser manager de la sucursal principal.'
                    })
        
        return data

    def create(self, validated_data):
        # Crear la sucursal
        new_branch = super().create(validated_data)
        
        # Si tiene un manager asignado, actualizar su Employee model
        if new_branch.manager:
            from users.models import Employee
            try:
                manager_employee = Employee.objects.get(user=new_branch.manager, store=new_branch.store)
                manager_employee.branch = new_branch
                manager_employee.save(update_fields=['branch'])
            except Employee.DoesNotExist:
                pass  # El manager no tiene registro de empleado
        
        return new_branch

    def update(self, instance, validated_data):
        # Campos que deben sincronizarse con la tienda si es sucursal principal
        sync_fields = ['country', 'state', 'postal_code', 'city', 'address']
        
        # Verificar si es la sucursal principal
        is_main_branch = instance.name.endswith("- Sucursal Principal")
        
        # Guardar los valores anteriores para comparar (solo si es sucursal principal)
        old_values = {}
        if is_main_branch:
            old_values = {field: getattr(instance, field) for field in sync_fields}
        
        # Guardar el manager anterior para comparar
        old_manager = instance.manager
        new_manager = validated_data.get('manager', instance.manager)
        
        # Actualizar la sucursal
        updated_branch = super().update(instance, validated_data)
        
        # Si cambió el manager, actualizar el Employee model
        if old_manager != new_manager:
            from users.models import Employee
            
            # Si había un manager anterior, limpiar su asignación de sucursal
            if old_manager:
                try:
                    old_employee = Employee.objects.get(user=old_manager, store=updated_branch.store)
                    old_employee.branch = None
                    old_employee.save(update_fields=['branch'])
                except Employee.DoesNotExist:
                    pass  # El manager anterior no tiene registro de empleado
            
            # Si hay un nuevo manager, asignarle esta sucursal
            if new_manager:
                try:
                    new_employee = Employee.objects.get(user=new_manager, store=updated_branch.store)
                    new_employee.branch = updated_branch
                    new_employee.save(update_fields=['branch'])
                except Employee.DoesNotExist:
                    pass  # El nuevo manager no tiene registro de empleado
        
        # Si es la sucursal principal, sincronizar con la tienda
        if is_main_branch:
            fields_changed = []
            for field in sync_fields:
                if field in validated_data and old_values[field] != getattr(updated_branch, field):
                    fields_changed.append(field)
            
            if fields_changed:
                store = updated_branch.store
                # Actualizar solo los campos que cambiaron en la tienda
                for field in fields_changed:
                    setattr(store, field, getattr(updated_branch, field))
                
                store.save(update_fields=fields_changed)
        
        return updated_branch


class StoreSerializer(serializers.ModelSerializer):
    branches = BranchSerializer(many=True, read_only=True, source='branch_set')
    owner_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Store
        fields = [
            'id', 'name', 'slug', 'logo', 'is_active', 'view_only',
            'country', 'state', 'postal_code', 'city', 'address', 'phone',
            'owner', 'owner_name', 'branches', 'created_at', 'updated_at', 
            'dark_mode', 'theme_id'
        ]
        read_only_fields = ['id', 'slug', 'owner_name', 'branches', 'created_at', 'updated_at']

    def get_owner_name(self, obj):
        return f"{obj.owner.first_name} {obj.owner.last_name}" if obj.owner else None

    def create(self, validated_data):
        # El owner será el usuario actual
        request = self.context.get('request')
        if request and request.user:
            validated_data['owner'] = request.user
        
        # Por defecto la tienda no está activa
        validated_data['is_active'] = False
        
        store = Store.objects.create(**validated_data)
        
        # Crear la branch principal automáticamente con los mismos datos de dirección
        main_branch = Branch.objects.create(
            store=store,
            manager=store.owner,
            name=f"{store.name} - Sucursal Principal",
            country=store.country,
            state=store.state,
            postal_code=store.postal_code,
            city=store.city,
            address=store.address
        )
        
        # Actualizar el Employee del owner para asignarle la sucursal principal
        from users.models import Employee
        try:
            owner_employee = Employee.objects.get(user=store.owner, store=store)
            owner_employee.branch = main_branch
            owner_employee.save(update_fields=['branch'])
        except Employee.DoesNotExist:
            pass  # El owner no tiene registro de empleado
        
        return store

    def update(self, instance, validated_data):
        # Campos que deben sincronizarse con la sucursal principal
        sync_fields = ['country', 'state', 'postal_code', 'city', 'address']

        # Guardar los valores anteriores para comparar
        old_values = {field: getattr(instance, field) for field in sync_fields}
        
        # Actualizar la tienda
        updated_store = super().update(instance, validated_data)
        
        # Sincronizar con la sucursal principal si algún campo cambió
        fields_changed = []
        for field in sync_fields:
            if field in validated_data and old_values[field] != getattr(updated_store, field):
                fields_changed.append(field)
        
        if fields_changed:
            try:
                # Buscar la sucursal principal
                from .models import Branch
                main_branch = Branch.objects.get(
                    store=updated_store, 
                    name__endswith="- Sucursal Principal"
                )
                
                # Actualizar solo los campos que cambiaron
                for field in fields_changed:
                    setattr(main_branch, field, getattr(updated_store, field))
                
                main_branch.save(update_fields=fields_changed)
                
            except Branch.DoesNotExist:
                # Si no existe la sucursal principal, crearla
                Branch.objects.create(
                    store=updated_store,
                    manager=updated_store.owner,
                    name=f"{updated_store.name} - Sucursal Principal",
                    country=updated_store.country,
                    state=updated_store.state,
                    postal_code=updated_store.postal_code,
                    city=updated_store.city,
                    address=updated_store.address
                )
        
        return updated_store

    def validate_owner(self, value):
        if value.role not in ['superadmin']:
            raise serializers.ValidationError("El propietario debe ser superadmin.")
        return value


class StoreCreateSerializer(serializers.ModelSerializer):
    """Serializer simplificado para crear tiendas"""
    
    class Meta:
        model = Store
        fields = [
            'name', 'logo', 'country', 'state', 'postal_code', 
            'city', 'address', 'phone', 'theme_id', 'dark_mode'
        ]

    def create(self, validated_data):
        # El owner será el usuario actual
        request = self.context.get('request')
        if request and request.user:
            validated_data['owner'] = request.user
        
        # Por defecto la tienda no está activa
        validated_data['is_active'] = False
        
        store = Store.objects.create(**validated_data)
        
        # Crear la branch principal automáticamente con los mismos datos de dirección
        main_branch = Branch.objects.create(
            store=store,
            manager=store.owner,
            name=f"{store.name} - Sucursal Principal",
            country=store.country,
            state=store.state,
            postal_code=store.postal_code,
            city=store.city,
            address=store.address
        )
        
        # Actualizar el Employee del owner para asignarle la sucursal principal
        from users.models import Employee
        try:
            owner_employee = Employee.objects.get(user=store.owner, store=store)
            owner_employee.branch = main_branch
            owner_employee.save(update_fields=['branch'])
        except Employee.DoesNotExist:
            pass  # El owner no tiene registro de empleado
        
        return store

    def update(self, instance, validated_data):
        # Campos que deben sincronizarse con la sucursal principal
        sync_fields = ['country', 'state', 'postal_code', 'city', 'address']
        
        # Guardar los valores anteriores para comparar
        old_values = {field: getattr(instance, field) for field in sync_fields}
        
        # Actualizar la tienda
        updated_store = super().update(instance, validated_data)
        
        # Sincronizar con la sucursal principal si algún campo cambió
        fields_changed = []
        for field in sync_fields:
            if field in validated_data and old_values[field] != getattr(updated_store, field):
                fields_changed.append(field)
        
        if fields_changed:
            try:
                # Buscar la sucursal principal
                from .models import Branch
                main_branch = Branch.objects.get(
                    store=updated_store, 
                    name__endswith="- Sucursal Principal"
                )
                
                # Actualizar solo los campos que cambiaron
                for field in fields_changed:
                    setattr(main_branch, field, getattr(updated_store, field))
                
                main_branch.save(update_fields=fields_changed)
                
            except Branch.DoesNotExist:
                # Si no existe la sucursal principal, crearla
                Branch.objects.create(
                    store=updated_store,
                    manager=updated_store.owner,
                    name=f"{updated_store.name} - Sucursal Principal",
                    country=updated_store.country,
                    state=updated_store.state,
                    postal_code=updated_store.postal_code,
                    city=updated_store.city,
                    address=updated_store.address
                )
        
        return updated_store