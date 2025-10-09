from django.db import models
from users.models import Supplier, Employee
from core.crm.models import Customer
from django.utils.text import slugify


def _upload_to(instance, filename):
    folder = instance.__class__.__name__.lower()
    store_name = slugify(instance.employee.store.name) if instance.employee and instance.employee.store else "default"
    return f'{folder}/{store_name}/{filename}'


class PurchaseOrder(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True)
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
    was_buyed = models.BooleanField(default=False)
    transport = models.CharField(max_length=100, null=True, blank=True)
    driver = models.CharField(max_length=100, null=True, blank=True)
    patent = models.CharField(max_length=20, null=True, blank=True)
    file_path = models.FileField(upload_to=_upload_to, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    currency = models.CharField(max_length=10, default='ARS')
    taxes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)


class PurchaseItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE,related_name='items')
    product = models.ForeignKey('stock.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()


class SalesOrder(models.Model):
    SALES_CHANNEL_CHOICES = [
        ('ecommerce', 'E-commerce'),
        ('storefront', 'Local físico'),
        ('wholesale', 'Mayorista')
    ]
    sales_channel = models.CharField(max_length=20, choices=SALES_CHANNEL_CHOICES, default='ecommerce')
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    payment_method = models.CharField(max_length=150)
    delivery_date = models.DateField(null=False, blank=False)
    deliver_to = models.CharField(max_length=250, null=True, blank=True)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    taxes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(null=True, blank=True)
    currency = models.CharField(max_length=10, default='ARS')
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pendiente'),
        ('approved', 'Aprobado'),
        ('rejected', 'Rechazado')
    ], default='pending')
    was_sold = models.BooleanField(default=False)
    transport = models.CharField(max_length=100, null=True, blank=True)
    driver = models.CharField(max_length=100, null=True, blank=True)
    patent = models.CharField(max_length=20, null=True, blank=True)
    file_path = models.FileField(upload_to=_upload_to, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    

class SalesItem(models.Model):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='sales_items')
    product = models.ForeignKey('stock.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()

