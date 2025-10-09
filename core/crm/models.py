from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import User, Supplier


class Customer(models.Model):
    PERSON = 'person'
    COMPANY = 'company'
    CUSTOMER_TYPE_CHOICES = [
        (PERSON, 'Persona Física'),
        (COMPANY, 'Empresa'),
    ]

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)  # solo ecommerce
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)  # si también es proveedor
    customer_type = models.CharField(max_length=10, choices=CUSTOMER_TYPE_CHOICES, default=PERSON)

    # Comunes
    email = models.EmailField(max_length=254, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    address = models.CharField(max_length=250, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Persona
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)

    # Empresa
    name = models.CharField(max_length=150, unique=True, null=True, blank=True)
    fantasy_name = models.CharField(max_length=100, null=True, blank=True)
    cuit = models.CharField(max_length=20, null=True, blank=True)

    # Historial de actividad
    comments = models.TextField(null=True, blank=True)  # Comentario principal
    contact_history = models.JSONField(default=list, blank=True)  # Array de contactos
    last_purchase_date = models.DateTimeField(null=True, blank=True)
    total_spent = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        if self.customer_type == self.PERSON:
            return f"{self.first_name} {self.last_name}"
        return self.name or "Cliente sin nombre"

    def add_contact(self, comment, user=None):
        """Agregar un nuevo contacto al historial"""
        contact = {
            'date': timezone.now().isoformat(),
            'comment': comment,
            'user': user.username if user else 'Sistema',
            'user_id': user.id if user else None
        }
        
        if not self.contact_history:
            self.contact_history = []
        
        self.contact_history.append(contact)
        self.save()
        
        return contact
    
    def get_last_contact_date(self):
        """Obtener la fecha del último contacto"""
        if self.contact_history:
            return self.contact_history[-1]['date']
        return None
    
    def get_contacts_count(self):
        """Obtener el número total de contactos"""
        return len(self.contact_history) if self.contact_history else 0
