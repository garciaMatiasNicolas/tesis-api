from django.db import models
from django.utils.text import slugify
from django.conf import settings

def _upload_to(instance, filename, folder):
    store_name = slugify(instance.store.name) if instance.store and instance.store.name else "default"
    return f'storelogos/{store_name}/{filename}'

class Store(models.Model):
    is_active = models.BooleanField(default=False)
    view_only = models.BooleanField(default=True)
    dark_mode = models.BooleanField(default=False)
    theme_id = models.CharField(max_length=100, blank=True, null=True, default='wine')
    logo = models.ImageField(upload_to=_upload_to, blank=True, null=True)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True, max_length=150)
    country = models.CharField(max_length=250)
    state = models.CharField(max_length=250)  
    postal_code = models.CharField(max_length=20)
    city = models.CharField(max_length=250)
    address = models.CharField(max_length=250)
    phone = models.CharField(max_length=250)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    owner = models.OneToOneField("users.User", on_delete=models.CASCADE, related_name='store')

    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Branch(models.Model):
    manager = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name='branches')
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    country = models.CharField(max_length=250)
    state = models.CharField(max_length=250)  
    postal_code = models.CharField(max_length=20)
    city = models.CharField(max_length=250)
    updated_at = models.DateTimeField(auto_now=True)
    address = models.CharField(max_length=250)

    def __str__(self):
        return self.name


    