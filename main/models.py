from django.db import models
from django_tenants.models import TenantMixin, DomainMixin
from django.db import models


class Costumer(TenantMixin):
    name = models.CharField(max_length=100, unique=True)
    subscription_start = models.DateField(null=True, blank=True)
    subscription_end = models.DateField(null=True, blank=True)
    paid_until = models.DateField(null=True, blank=True)
    on_trial = models.BooleanField(default=True)
    created_on = models.DateField(auto_now_add=True)
    auto_create_schema = True

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    pass

