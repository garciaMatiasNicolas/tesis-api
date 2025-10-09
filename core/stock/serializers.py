from rest_framework import serializers
from .models import Product, Category, Subcategory


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
    
    def to_representation(self, instance):
        return {
            "id": instance.id,
            "description": instance.description,
            "price": instance.price,
            "category": {"id": instance.category.id, "name": instance.category.name} if instance.category else None,
            "subcategory": {"id": instance.subcategory.id, "name": instance.subcategory.name} if instance.subcategory else None,
            "supplier": {"id": instance.supplier.id, "name": instance.supplier.name} if instance.supplier else None,
            "sku": instance.sku,
            "weight": instance.weight,
            "height": instance.height,
            "depth": instance.depth,
            "width": instance.width,
            "cost_price": instance.cost_price,
            "storage_unit": instance.storage_unit,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


class SubcategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Subcategory
        fields = '__all__'