import pyotp
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from core.store.models import Store, Branch
from django.utils.text import slugify
from django.db import connection

def _upload_to(instance, filename, folder):
    store_name = slugify(instance.store.name) if instance.store and instance.store.name else "default"
    return f'profile/{store_name}/{filename}'

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El email es obligatorio')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'superadmin')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('superadmin', 'Super Admin'),
        ('manager', 'Admin Sucursal'),
        ('employee', 'Empleado'),
        ('client', 'Cliente'),
    )

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_name = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    email_verified = models.BooleanField(default=False)
    first_login = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  
    otp_secret = models.CharField(max_length=32, blank=True, null=True)
    is_2fa_enabled = models.BooleanField(default=False)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'role']

    objects = UserManager()

    def save(self, *args, **kwargs):
        if self.is_2fa_enabled and not self.otp_secret:
            raise ValueError("No se puede habilitar 2FA sin otp_secret.")
        if not self.otp_secret:
            self.otp_secret = pyotp.random_base32()
        super().save(*args, **kwargs)

    def get_totp_uri(self):
        schema = getattr(connection, "schema_name", "public")
        return f"otpauth://totp/MatiasApp:{self.email}?secret={self.otp_secret}&issuer=MatiasApp"

    def verify_otp(self, token):
        totp = pyotp.TOTP(self.otp_secret)
        return totp.verify(token)


class Employee(models.Model):
    profile_photo = models.ImageField(upload_to=_upload_to, null=True, blank=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)
    birth = models.DateField()
    date_joined = models.DateField()
    position = models.CharField(max_length=250)
    dni = models.IntegerField()
    cuil = models.CharField(max_length=20, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    address = models.CharField(max_length=250, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Empleado: {self.user.first_name} {self.user.last_name} de {self.store.name}"


class Supplier(models.Model):
    name = models.CharField(max_length=150, unique=True)
    fantasy_name = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    website = models.URLField(null=True, blank=True)
    cuit = models.CharField(max_length=20, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    address = models.CharField(max_length=250, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name