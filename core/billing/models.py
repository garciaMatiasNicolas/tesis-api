from django.db import models
from core.stock.models import Warehouse
from core.store.models import Branch
from users.models import Supplier, Employee, User
from core.crm.models import Customer
from django.utils.text import slugify


def _upload_to(instance, filename):
    folder = instance.__class__.__name__.lower()
    store_name = slugify(instance.employee.store.name) if instance.employee and instance.employee.store else "default"
    return f'{folder}/{store_name}/{filename}'


class PurchaseOrder(models.Model):
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    payment_method = models.CharField(max_length=150)
    delivery_date = models.DateField(null=False, blank=False)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pendiente'),
        ('approved', 'Aprobado'),
        ('rejected', 'Rechazado')
    ], default='pending')
    was_payed = models.BooleanField(default=False)
    received = models.BooleanField(default=False)
    received_date = models.DateField(null=True, blank=True)
    transport = models.CharField(max_length=100, null=True, blank=True)
    warehouse_destination = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_orders')
    branch_destination = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_orders')
    driver = models.CharField(max_length=100, null=True, blank=True)
    patent = models.CharField(max_length=20, null=True, blank=True)
    file_path = models.FileField(upload_to=_upload_to, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    currency = models.CharField(max_length=10, default='ARS')
    taxes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    comments = models.JSONField(null=True, blank=True, default=list)


class PurchaseItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE,related_name='items')
    product = models.ForeignKey('stock.Product', on_delete=models.CASCADE)
    product_unit = models.ForeignKey('stock.ProductUnit', on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)


class SalesOrder(models.Model):
    SALES_CHANNEL_CHOICES = [
        ('ecommerce', 'E-commerce'),
        ('storefront', 'Local físico'),
        ('wholesale', 'Mayorista')
    ]

    # Estados sugeridos para tus 3 flujos
    STATUS_CHOICES = [
        ('draft', 'Presupuesto'),
        ('pending', 'Pendiente (Reserva Stock)'),
        ('processing', 'En Preparación'),
        ('completed', 'Completada'),
        ('cancelled', 'Cancelada'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    # Origen de la venta vs Origen de la mercadería
    branch_origin = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='sales_orders', null=True, blank=True)
    warehouse_origin = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='sales_orders', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    sales_channel = models.CharField(max_length=20, choices=SALES_CHANNEL_CHOICES, default='ecommerce')
    # Precios totales (Calculados)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0) # Aumenté max_digits por inflación ARS
    # Logística
    delivery = models.BooleanField(default=False)
    # Cambiado a null=True para ventas de mostrador (1a)
    delivery_date = models.DateField(null=True, blank=True) 
    was_payed = models.BooleanField(default=False)
    was_delivered = models.BooleanField(default=False)
    payment_method = models.CharField(max_length=150)
    deliver_to = models.CharField(max_length=250, null=True, blank=True)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    taxes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(null=True, blank=True)
    currency = models.CharField(max_length=10, default='ARS')
    was_payed = models.BooleanField(default=False)
    was_delivered = models.BooleanField(default=False)
    delivered_date = models.DateField(null=True, blank=True)
    transport = models.CharField(max_length=100, null=True, blank=True)
    driver = models.CharField(max_length=100, null=True, blank=True)
    patent = models.CharField(max_length=20, null=True, blank=True)
    file_path = models.FileField(upload_to=_upload_to, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    comments = models.JSONField(null=True, blank=True, default=list)
    sales_channel = models.CharField(max_length=20, choices=SALES_CHANNEL_CHOICES, default='ecommerce')

class SalesItem(models.Model):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='sales_items')
    product = models.ForeignKey('stock.Product', on_delete=models.CASCADE)
    product_unit = models.ForeignKey('stock.ProductUnit', on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)


    