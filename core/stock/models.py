import datetime
import os
from django.db import models
from core.store.models import Store, Branch
from users.models import Supplier


def product_image_upload_path(instance, filename, slot='image_1'):
    """
    Retorna la ruta donde se guardará la imagen del producto.
    Formato: images/{store}/{sku}/image_1.jpg
    """
    # Obtener extensión del archivo
    ext = os.path.splitext(filename)[1]
    # Por defecto usar 'default_store' si no hay store asociado
    store_name = Store.objects.filter(is_active=True).first().slug if Store.objects.filter(is_active=True).exists() else "default_store"
    # Construir nombre de archivo basado en el slot
    filename = f"{slot}{ext}"
    return f'assets/{store_name}/{instance.sku}/{filename}'


def product_image_1_path(instance, filename):
    """Ruta para image_1"""
    return product_image_upload_path(instance, filename, 'image_1')


def product_image_2_path(instance, filename):
    """Ruta para image_2"""
    return product_image_upload_path(instance, filename, 'image_2')


def product_image_3_path(instance, filename):
    """Ruta para image_3"""
    return product_image_upload_path(instance, filename, 'image_3')


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Subcategory(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    STATUS_CHOICES = [
        ('active', 'Activo'),   
        ('discontinued', 'Descontinuado')
    ]

    UNIT_TYPE_CHOICES = [
        ('count', 'Recuento (Unidades)'),
        ('weight', 'Peso (Kilos/Gramos)'),
        ('volume', 'Volumen (Litros/Mililitros)'),
    ]

    BASE_UNIT_CHOICES = [
        ('unit', 'Unidad'),
        ('kg', 'Kilogramo'),
        ('g', 'Gramo'),
        ('l', 'Litro'),
        ('ml', 'Mililitro'),
    ]

    unit_type = models.CharField(max_length=10, choices=UNIT_TYPE_CHOICES, default='count')
    base_unit_name = models.CharField(max_length=20, choices=BASE_UNIT_CHOICES, default='unit')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    subcategory = models.ForeignKey(Subcategory, on_delete=models.SET_NULL, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    sku = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    depth = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    safety_stock = models.DecimalField(max_digits=15, decimal_places=4, default=0.0000)
    width = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Imágenes del producto (hasta 3)
    image_1 = models.ImageField(upload_to=product_image_1_path, blank=True, null=True)
    image_2 = models.ImageField(upload_to=product_image_2_path, blank=True, null=True)
    image_3 = models.ImageField(upload_to=product_image_3_path, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='active')

    def __str__(self):
        return f"{self.sku} - {self.description}"
    
    def get_image_folder(self, store_name="default_store"):
        """
        Retorna la ruta de carpeta local para las imágenes de este producto.
        Formato: images/{store}/{sku}/
        """
        return f"images/{store_name}/{self.sku}"
    
    @property
    def images(self):
        """Retorna lista de URLs de imágenes disponibles"""
        images = []
        if self.image_1:
            images.append(self.image_1.url)
        if self.image_2:
            images.append(self.image_2.url)
        if self.image_3:
            images.append(self.image_3.url)
        return images


class ProductUnit(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='units')
    name = models.CharField(max_length=50)  
    conversion_factor = models.DecimalField(max_digits=12, decimal_places=4)
    
    def __str__(self):
        return f"{self.name} de {self.product.description} (x{self.conversion_factor})"


class Warehouse(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='warehouses')
    name = models.CharField(max_length=100, unique=True)
    country = models.CharField(max_length=250)
    state = models.CharField(max_length=250, null=True, blank=True)
    city = models.CharField(max_length=250)
    address = models.CharField(max_length=250)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Stock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stocks')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='stocks')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='stocks')
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0.0000)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'warehouse'],
                condition=models.Q(warehouse__isnull=False),
                name='unique_product_warehouse'
            ),
            models.UniqueConstraint(
                fields=['product', 'branch'],
                condition=models.Q(branch__isnull=False),
                name='unique_product_branch'
            ),
        ]

    def __str__(self):
        location = self.warehouse.name if self.warehouse else (self.branch.name if self.branch else 'Sin ubicación')
        return f"{self.product} - {location}: {self.quantity}"


class StockMovement(models.Model):
    MOVEMENT_TYPE_CHOICES = [
        ('IN', 'Ingreso'),
        ('OUT', 'Egreso'),
    ]

    FROM_TO_CHOICES = [
        ('PUR', 'Compra'),
        ('SAL', 'Venta'),
        ('WHA', 'Deposito'),
        ('BRA', 'Sucursal'),
        ('MOV', 'Movimiento'),
    ]

    STATUS_CHOICES = [
        ('PEN', 'Pendiente de pago'),
        ('TRAN', 'En transito'),
        ('REC', 'Recibido'),
        ('CAN', 'Cancelado'),
    ]

    status = models.CharField(max_length=4, choices=STATUS_CHOICES, default='TRAN')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, null=True, blank=True)
    from_location = models.CharField(max_length=3, choices=FROM_TO_CHOICES)
    to_location = models.CharField(max_length=3, choices=FROM_TO_CHOICES)
    movement_type = models.CharField(max_length=3, choices=MOVEMENT_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0.0000)
    unit_used = models.ForeignKey(ProductUnit, on_delete=models.SET_NULL, null=True, blank=True)
    conversion_factor_at_moment = models.DecimalField(max_digits=10, decimal_places=4, default=1.0)
    sale = models.ForeignKey('billing.SalesOrder', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_movements')
    purchase = models.ForeignKey('billing.PurchaseOrder', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_movements')
    date = models.DateTimeField(auto_now_add=True)
    note = models.TextField(null=True, blank=True)
    comments = models.JSONField(null=True, blank=True, default=list)

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity} {self.product} en {self.warehouse}"
    
    def add_comment(self, comment, status_before=None, user=None):
        """Agregar un nuevo contacto al historial"""
        comment = {
            'date': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'comment': comment,
            'status_before': status_before,
            'status_after': self.status,
            'user': f'{user.first_name} {user.last_name}' if user else 'Sistema',
            'user_id': user.id if user else None
        }
        
        if not self.comments:
            self.comments = []
        
        self.comments.append(comment)
        self.save()
        
        return comment

