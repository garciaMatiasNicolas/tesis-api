import json
from decimal import Decimal

from django.test import TestCase
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework_simplejwt.tokens import RefreshToken
from unittest.mock import MagicMock, patch

from users.models import User, Supplier
from core.crm.models import Customer
from core.stock.models import Product, Category, Subcategory
from core.billing.models import SalesOrder, SalesItem
from core.ecommerce.models import Cart, CartItem
from core.ecommerce.serializer import (
    CustomerRegistrationSerializer,
    CartSerializer,
    ProductSerializer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(email, role="client", password="pass123", **kwargs):
    return User.objects.create_user(
        email=email,
        first_name="Test",
        last_name="User",
        role=role,
        password=password,
        **kwargs,
    )


def auth_header(user):
    return f"Bearer {RefreshToken.for_user(user).access_token}"


def make_product(sku="P001", description="Test Product", price="100.00", cost_price="50.00", category=None):
    return Product.objects.create(
        sku=sku,
        description=description,
        price=Decimal(price),
        cost_price=Decimal(cost_price),
        category=category,
    )


def make_customer(email="customer@test.com", user=None, **kwargs):
    return Customer.objects.create(
        email=email,
        first_name="Juan",
        last_name="García",
        customer_type="person",
        user=user,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------

class CartModelTests(TenantTestCase):
    def setUp(self):
        self.user = make_user("cmodel@test.com")
        self.customer = make_customer("cmodel_c@test.com", user=self.user)

    def test_cart_created_with_null_sales_order(self):
        cart = Cart.objects.create(customer=self.customer)
        self.assertIsNone(cart.sales_order)

    def test_cart_is_active_while_sales_order_is_null(self):
        cart = Cart.objects.create(customer=self.customer)
        active_carts = Cart.objects.filter(customer=self.customer, sales_order__isnull=True)
        self.assertIn(cart, active_carts)

    def test_cart_frozen_after_sales_order_assigned(self):
        cart = Cart.objects.create(customer=self.customer)
        sales_order = SalesOrder.objects.create(
            customer=self.customer,
            sales_channel="ecommerce",
            payment_method="efectivo",
            delivery_date="2026-06-01",
            total_price=Decimal("0.00"),
        )
        cart.sales_order = sales_order
        cart.save()
        active_carts = Cart.objects.filter(customer=self.customer, sales_order__isnull=True)
        self.assertNotIn(cart, active_carts)


class CartItemModelTests(TenantTestCase):
    def setUp(self):
        self.user = make_user("itemmodel@test.com")
        self.customer = make_customer("itemmodel_c@test.com", user=self.user)
        self.product = make_product()
        self.cart = Cart.objects.create(customer=self.customer)

    def test_cart_item_links_to_cart_and_product(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=3)
        self.assertEqual(item.cart, self.cart)
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.quantity, 3)

    def test_cart_item_accessible_via_related_name(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        self.assertEqual(self.cart.cart_items.count(), 1)


# ---------------------------------------------------------------------------
# Serializer Tests
# ---------------------------------------------------------------------------

class CustomerRegistrationSerializerTests(TenantTestCase):

    def _data(self, **overrides):
        base = {
            "email": "nuevo@test.com",
            "password": "pass123",
            "confirm_password": "pass123",
            "first_name": "Juan",
            "last_name": "García",
        }
        base.update(overrides)
        return base

    def test_passwords_mismatch_raises_error(self):
        s = CustomerRegistrationSerializer(data=self._data(confirm_password="diferente"))
        self.assertFalse(s.is_valid())
        self.assertIn("password", s.errors)

    def test_duplicate_email_raises_error(self):
        make_user("nuevo@test.com")
        s = CustomerRegistrationSerializer(data=self._data(email="nuevo@test.com"))
        self.assertFalse(s.is_valid())
        self.assertIn("email", s.errors)

    def test_password_too_short_raises_error(self):
        s = CustomerRegistrationSerializer(data=self._data(password="abc", confirm_password="abc"))
        self.assertFalse(s.is_valid())
        self.assertIn("password", s.errors)

    def test_case_b_creates_new_user_and_customer(self):
        s = CustomerRegistrationSerializer(data=self._data())
        self.assertTrue(s.is_valid(), s.errors)
        result = s.save()
        self.assertFalse(result["linked_to_existing"])
        self.assertIsNotNone(result["user"].id)
        self.assertIsNotNone(result["customer"].id)
        self.assertEqual(result["user"].role, "client")

    def test_case_a_links_existing_crm_customer(self):
        # Customer exists from CRM (no user linked)
        Customer.objects.create(
            email="nuevo@test.com",
            first_name="",
            last_name="",
            customer_type="person",
            user=None,
        )
        s = CustomerRegistrationSerializer(data=self._data())
        self.assertTrue(s.is_valid(), s.errors)
        result = s.save()
        self.assertTrue(result["linked_to_existing"])
        self.assertIsNotNone(result["customer"].user)

    def test_case_a_fills_empty_fields_on_existing_customer(self):
        existing = Customer.objects.create(
            email="nuevo@test.com",
            first_name="",
            last_name="",
            customer_type="person",
            user=None,
        )
        data = self._data(first_name="Juan", last_name="García")
        s = CustomerRegistrationSerializer(data=data)
        self.assertTrue(s.is_valid(), s.errors)
        result = s.save()
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Juan")

    def test_case_a_preserves_existing_non_empty_fields(self):
        existing = Customer.objects.create(
            email="nuevo@test.com",
            first_name="Nombre Original",
            last_name="Apellido Original",
            customer_type="person",
            user=None,
        )
        s = CustomerRegistrationSerializer(data=self._data())
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Nombre Original")


class CartSerializerTotalTests(TenantTestCase):
    def setUp(self):
        self.user = make_user("cartser@test.com")
        self.customer = make_customer("cartser_c@test.com", user=self.user)
        self.product1 = make_product(sku="C001", price="200.00")
        self.product2 = make_product(sku="C002", price="150.00")
        self.cart = Cart.objects.create(customer=self.customer)

    def test_total_is_zero_for_empty_cart(self):
        s = CartSerializer(self.cart)
        self.assertEqual(s.data["total"], 0)

    def test_total_sums_price_times_quantity(self):
        CartItem.objects.create(cart=self.cart, product=self.product1, quantity=2)
        CartItem.objects.create(cart=self.cart, product=self.product2, quantity=3)
        s = CartSerializer(self.cart)
        expected = Decimal("200.00") * 2 + Decimal("150.00") * 3
        self.assertEqual(Decimal(str(s.data["total"])), expected)


class ProductSerializerStockTests(TenantTestCase):
    def setUp(self):
        self.product = make_product(sku="STOCK001", price="100.00")

    def test_stock_false_when_no_physical_stock(self):
        s = ProductSerializer(self.product)
        self.assertFalse(s.data["stock"])

    def test_stock_true_when_physical_stock_exists(self):
        from core.stock.models import Stock
        Stock.objects.create(product=self.product, quantity=Decimal("10.0000"))
        s = ProductSerializer(self.product)
        self.assertTrue(s.data["stock"])

    def test_stock_false_when_all_reserved_in_pending_sales(self):
        from core.stock.models import Stock
        Stock.objects.create(product=self.product, quantity=Decimal("5.0000"))
        customer = make_customer("stocktest@test.com")
        order = SalesOrder.objects.create(
            customer=customer,
            sales_channel="ecommerce",
            payment_method="efectivo",
            delivery_date="2026-06-01",
            total_price=Decimal("500.00"),
            status="pending",
        )
        SalesItem.objects.create(
            sales_order=order, product=self.product, quantity=5, unit_price=Decimal("100.00")
        )
        s = ProductSerializer(self.product)
        self.assertFalse(s.data["stock"])


# ---------------------------------------------------------------------------
# Public View Tests
# ---------------------------------------------------------------------------

class ProductListViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.category = Category.objects.create(name="Electrónica")
        self.subcategory = Subcategory.objects.create(name="Teléfonos", category=self.category)
        self.p1 = make_product(sku="E001", description="Samsung Galaxy", price="500.00", category=self.category)
        self.p2 = make_product(sku="E002", description="iPhone 15", price="1200.00", category=self.category)
        self.p3 = make_product(sku="F001", description="Zapatos deportivos", price="200.00")

    def test_list_returns_200(self):
        resp = self.client.get("/api/ecommerce/products/")
        self.assertEqual(resp.status_code, 200)

    def test_list_is_paginated_with_default_page_size_4(self):
        # Create additional products to exceed page size
        for i in range(4):
            make_product(sku=f"EXTRA{i}", description=f"Extra {i}", price="50.00")
        resp = self.client.get("/api/ecommerce/products/")
        data = resp.json()
        self.assertIn("results", data)
        self.assertLessEqual(len(data["results"]), 4)

    def test_filter_by_category(self):
        resp = self.client.get(f"/api/ecommerce/products/?category={self.category.id}")
        data = resp.json()
        results = data.get("results", data)
        skus = [r["sku"] for r in results]
        self.assertIn("E001", skus)
        self.assertIn("E002", skus)
        self.assertNotIn("F001", skus)

    def test_filter_by_search_description(self):
        resp = self.client.get("/api/ecommerce/products/?search=samsung")
        data = resp.json()
        results = data.get("results", data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["sku"], "E001")

    def test_filter_by_min_price(self):
        resp = self.client.get("/api/ecommerce/products/?min_price=600")
        data = resp.json()
        results = data.get("results", data)
        skus = [r["sku"] for r in results]
        self.assertIn("E002", skus)
        self.assertNotIn("E001", skus)

    def test_filter_by_max_price(self):
        resp = self.client.get("/api/ecommerce/products/?max_price=300")
        data = resp.json()
        results = data.get("results", data)
        skus = [r["sku"] for r in results]
        self.assertIn("F001", skus)
        self.assertNotIn("E002", skus)

    def test_sort_by_price_asc(self):
        resp = self.client.get("/api/ecommerce/products/?sort_by=price_asc")
        data = resp.json()
        results = data.get("results", data)
        prices = [float(r["price"]) for r in results]
        self.assertEqual(prices, sorted(prices))

    def test_sort_by_price_desc(self):
        resp = self.client.get("/api/ecommerce/products/?sort_by=price_desc")
        data = resp.json()
        results = data.get("results", data)
        prices = [float(r["price"]) for r in results]
        self.assertEqual(prices, sorted(prices, reverse=True))


class ProductDetailViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.product = make_product(sku="DET001")

    def test_detail_returns_200(self):
        resp = self.client.get(f"/api/ecommerce/products/{self.product.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["sku"], "DET001")

    def test_detail_returns_404_for_nonexistent_product(self):
        resp = self.client.get("/api/ecommerce/products/99999/")
        self.assertEqual(resp.status_code, 404)


class CategoryListViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)

    def test_returns_200(self):
        Category.objects.create(name="Ropa")
        Category.objects.create(name="Accesorios")
        resp = self.client.get("/api/ecommerce/categories/")
        self.assertEqual(resp.status_code, 200)

    def test_ordered_by_name(self):
        Category.objects.create(name="Zapatos")
        Category.objects.create(name="Accesorios")
        resp = self.client.get("/api/ecommerce/categories/")
        names = [c["name"] for c in resp.json()]
        self.assertEqual(names, sorted(names))


class SubcategoryListViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.cat_a = Category.objects.create(name="CatA")
        self.cat_b = Category.objects.create(name="CatB")
        Subcategory.objects.create(name="Sub A1", category=self.cat_a)
        Subcategory.objects.create(name="Sub A2", category=self.cat_a)
        Subcategory.objects.create(name="Sub B1", category=self.cat_b)

    def test_returns_all_subcategories(self):
        resp = self.client.get("/api/ecommerce/subcategories/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 3)

    def test_filters_by_category(self):
        resp = self.client.get(f"/api/ecommerce/subcategories/?category={self.cat_a.id}")
        self.assertEqual(resp.status_code, 200)
        names = [s["name"] for s in resp.json()]
        self.assertIn("Sub A1", names)
        self.assertIn("Sub A2", names)
        self.assertNotIn("Sub B1", names)


class SupplierListViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)

    def test_returns_200(self):
        Supplier.objects.create(name="Proveedor Test")
        resp = self.client.get("/api/ecommerce/suppliers/")
        self.assertEqual(resp.status_code, 200)

    def test_no_auth_required(self):
        resp = self.client.get("/api/ecommerce/suppliers/")
        self.assertNotEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# Customer Registration View Tests
# ---------------------------------------------------------------------------

class CustomerRegistrationViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)

    def _payload(self, **overrides):
        base = {
            "email": "nuevo@test.com",
            "password": "pass123",
            "confirm_password": "pass123",
            "first_name": "Juan",
            "last_name": "García",
        }
        base.update(overrides)
        return base

    def test_case_b_creates_new_user_and_customer(self):
        resp = self.client.post(
            "/api/ecommerce/register/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertFalse(data["linked_to_existing"])
        self.assertEqual(data["user"]["email"], "nuevo@test.com")

    def test_case_a_links_existing_crm_customer(self):
        Customer.objects.create(
            email="nuevo@test.com",
            first_name="Cargado Desde CRM",
            last_name="Apellido",
            customer_type="person",
            user=None,
        )
        resp = self.client.post(
            "/api/ecommerce/register/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["linked_to_existing"])

    def test_passwords_mismatch_returns_400(self):
        resp = self.client.post(
            "/api/ecommerce/register/",
            data=json.dumps(self._payload(confirm_password="diferente")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_email_returns_400(self):
        make_user("nuevo@test.com")
        resp = self.client.post(
            "/api/ecommerce/register/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_password_too_short_returns_400(self):
        resp = self.client.post(
            "/api/ecommerce/register/",
            data=json.dumps(self._payload(password="abc", confirm_password="abc")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_no_auth_required_for_registration(self):
        resp = self.client.post(
            "/api/ecommerce/register/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertNotEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# Cart Management View Tests
# ---------------------------------------------------------------------------

class CartManagementViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user("cart@test.com")
        self.customer = make_customer("cart_c@test.com", user=self.user)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_get_requires_auth(self):
        resp = self.client.get("/api/ecommerce/carts/")
        self.assertEqual(resp.status_code, 401)

    def test_get_without_customer_id_returns_400(self):
        self._auth(self.user)
        resp = self.client.get("/api/ecommerce/carts/")
        self.assertEqual(resp.status_code, 400)

    def test_get_with_invalid_customer_id_returns_404(self):
        self._auth(self.user)
        resp = self.client.get("/api/ecommerce/carts/?customer_id=99999")
        self.assertEqual(resp.status_code, 404)

    def test_get_returns_existing_active_cart(self):
        self._auth(self.user)
        cart = Cart.objects.create(customer=self.customer)
        resp = self.client.get(f"/api/ecommerce/carts/?customer_id={self.customer.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], cart.id)

    def test_get_creates_cart_if_none_exists(self):
        self._auth(self.user)
        resp = self.client.get(f"/api/ecommerce/carts/?customer_id={self.customer.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Cart.objects.filter(customer=self.customer).exists())

    def test_post_requires_auth(self):
        resp = self.client.post(
            "/api/ecommerce/carts/",
            data=json.dumps({"customer_id": self.customer.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_post_without_customer_id_returns_400(self):
        self._auth(self.user)
        resp = self.client.post("/api/ecommerce/carts/", data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_post_with_wrong_customer_returns_403(self):
        other_user = make_user("other@test.com")
        other_customer = make_customer("other_c@test.com", user=other_user)
        self._auth(self.user)
        resp = self.client.post(
            "/api/ecommerce/carts/",
            data=json.dumps({"customer_id": other_customer.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_post_creates_new_cart(self):
        self._auth(self.user)
        resp = self.client.post(
            "/api/ecommerce/carts/",
            data=json.dumps({"customer_id": self.customer.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Cart.objects.filter(customer=self.customer).count(), 1)

    def test_post_returns_existing_cart_instead_of_creating_new(self):
        existing = Cart.objects.create(customer=self.customer)
        self._auth(self.user)
        resp = self.client.post(
            "/api/ecommerce/carts/",
            data=json.dumps({"customer_id": self.customer.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], existing.id)
        self.assertEqual(Cart.objects.filter(customer=self.customer).count(), 1)


# ---------------------------------------------------------------------------
# Cart Item Management View Tests
# ---------------------------------------------------------------------------

class CartItemManagementViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user("items@test.com")
        self.customer = make_customer("items_c@test.com", user=self.user)
        self.product = make_product(sku="ITEM001", price="100.00")
        self.cart = Cart.objects.create(customer=self.customer)
        self._auth(self.user)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_get_items_returns_200(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        resp = self.client.get(f"/api/ecommerce/carts/{self.cart.id}/items/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_post_adds_new_item(self):
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/items/",
            data=json.dumps({"product_id": self.product.id, "quantity": 2}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(CartItem.objects.filter(cart=self.cart).count(), 1)

    def test_post_merges_quantity_for_existing_item(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/items/",
            data=json.dumps({"product_id": self.product.id, "quantity": 3}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        item = CartItem.objects.get(cart=self.cart, product=self.product)
        self.assertEqual(item.quantity, 5)

    def test_post_to_frozen_cart_returns_400(self):
        sales_order = SalesOrder.objects.create(
            customer=self.customer,
            sales_channel="ecommerce",
            payment_method="efectivo",
            delivery_date="2026-06-01",
            total_price=Decimal("0.00"),
        )
        self.cart.sales_order = sales_order
        self.cart.save()
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/items/",
            data=json.dumps({"product_id": self.product.id, "quantity": 1}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_post_with_invalid_product_returns_404(self):
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/items/",
            data=json.dumps({"product_id": 99999, "quantity": 1}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_put_updates_quantity(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        resp = self.client.put(
            f"/api/ecommerce/carts/{self.cart.id}/items/{item.id}/",
            data=json.dumps({"quantity": 7}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 7)

    def test_put_zero_quantity_deletes_item(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        resp = self.client.put(
            f"/api/ecommerce/carts/{self.cart.id}/items/{item.id}/",
            data=json.dumps({"quantity": 0}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(CartItem.objects.filter(id=item.id).exists())

    def test_put_negative_quantity_deletes_item(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        resp = self.client.put(
            f"/api/ecommerce/carts/{self.cart.id}/items/{item.id}/",
            data=json.dumps({"quantity": -1}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(CartItem.objects.filter(id=item.id).exists())

    def test_put_to_frozen_cart_returns_400(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        sales_order = SalesOrder.objects.create(
            customer=self.customer,
            sales_channel="ecommerce",
            payment_method="efectivo",
            delivery_date="2026-06-01",
            total_price=Decimal("0.00"),
        )
        self.cart.sales_order = sales_order
        self.cart.save()
        resp = self.client.put(
            f"/api/ecommerce/carts/{self.cart.id}/items/{item.id}/",
            data=json.dumps({"quantity": 5}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_delete_specific_item(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        resp = self.client.delete(f"/api/ecommerce/carts/{self.cart.id}/items/{item.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(CartItem.objects.filter(id=item.id).exists())

    def test_delete_all_items(self):
        p2 = make_product(sku="ITEM002", price="50.00")
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        CartItem.objects.create(cart=self.cart, product=p2, quantity=2)
        resp = self.client.delete(f"/api/ecommerce/carts/{self.cart.id}/items/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self.cart.cart_items.count(), 0)

    def test_delete_from_frozen_cart_returns_400(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        sales_order = SalesOrder.objects.create(
            customer=self.customer,
            sales_channel="ecommerce",
            payment_method="efectivo",
            delivery_date="2026-06-01",
            total_price=Decimal("0.00"),
        )
        self.cart.sales_order = sales_order
        self.cart.save()
        resp = self.client.delete(f"/api/ecommerce/carts/{self.cart.id}/items/{item.id}/")
        self.assertEqual(resp.status_code, 400)

    def test_get_items_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get(f"/api/ecommerce/carts/{self.cart.id}/items/")
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# Customer Data View Tests
# ---------------------------------------------------------------------------

class CustomerDataViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user("custdata@test.com")
        self.customer = make_customer("custdata_c@test.com", user=self.user)
        self._auth(self.user)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_get_returns_customer_data(self):
        resp = self.client.get("/api/ecommerce/customers/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], "custdata_c@test.com")

    def test_get_returns_404_when_no_customer(self):
        user_no_customer = make_user("nolink@test.com")
        self._auth(user_no_customer)
        resp = self.client.get("/api/ecommerce/customers/me/")
        self.assertEqual(resp.status_code, 404)

    def test_get_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get("/api/ecommerce/customers/me/")
        self.assertEqual(resp.status_code, 401)

    def test_patch_updates_customer_field(self):
        resp = self.client.patch(
            "/api/ecommerce/customers/me/",
            data=json.dumps({"phone": "+54 11 1234-5678"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone, "+54 11 1234-5678")

    def test_patch_propagates_email_to_user(self):
        new_email = "updated@test.com"
        # Need a unique email for the Customer too
        Customer.objects.filter(id=self.customer.id).update(email=new_email)
        resp = self.client.patch(
            "/api/ecommerce/customers/me/",
            data=json.dumps({"email": new_email}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, new_email)

    def test_patch_propagates_first_name_to_user(self):
        resp = self.client.patch(
            "/api/ecommerce/customers/me/",
            data=json.dumps({"first_name": "NuevoNombre"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "NuevoNombre")

    def test_patch_propagates_last_name_to_user(self):
        resp = self.client.patch(
            "/api/ecommerce/customers/me/",
            data=json.dumps({"last_name": "NuevoApellido"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, "NuevoApellido")

    def test_patch_with_no_valid_fields_returns_400(self):
        resp = self.client.patch(
            "/api/ecommerce/customers/me/",
            data=json.dumps({"campo_inexistente": "valor"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_updates_customer_fully(self):
        resp = self.client.put(
            "/api/ecommerce/customers/me/",
            data=json.dumps({
                "first_name": "Ana",
                "last_name": "Lopez",
                "email": "custdata_c@test.com",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, "Ana")


# ---------------------------------------------------------------------------
# Checkout View Tests
# ---------------------------------------------------------------------------

class CheckoutCartViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user("checkout@test.com")
        self.customer = make_customer("checkout_c@test.com", user=self.user)
        self.product = make_product(sku="CHK001", price="250.00")
        self.cart = Cart.objects.create(customer=self.customer)
        self._auth(self.user)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_checkout_empty_cart_returns_400(self):
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/checkout/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_checkout_already_processed_cart_returns_400(self):
        sales_order = SalesOrder.objects.create(
            customer=self.customer,
            sales_channel="ecommerce",
            payment_method="efectivo",
            delivery_date="2026-06-01",
            total_price=Decimal("0.00"),
        )
        self.cart.sales_order = sales_order
        self.cart.save()
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/checkout/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_checkout_nonexistent_cart_returns_404(self):
        resp = self.client.post(
            "/api/ecommerce/carts/99999/checkout/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_checkout_creates_sales_order_with_draft_status(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/checkout/",
            data=json.dumps({
                "payment_method": "transferencia",
                "delivery_date": "2026-06-15",
                "shipping_cost": "100.00",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["status"], "draft")
        self.assertTrue(SalesOrder.objects.filter(id=data["id"]).exists())

    def test_checkout_freezes_cart(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/checkout/",
            data="{}",
            content_type="application/json",
        )
        self.cart.refresh_from_db()
        self.assertIsNotNone(self.cart.sales_order)

    def test_checkout_creates_sales_items_from_cart_items(self):
        p2 = make_product(sku="CHK002", price="50.00")
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        CartItem.objects.create(cart=self.cart, product=p2, quantity=3)
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/checkout/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        order = SalesOrder.objects.get(id=resp.json()["id"])
        self.assertEqual(order.salesitem_set.count(), 2)

    def test_checkout_calculates_total_correctly(self):
        # 2 x 250 + shipping 100 = 600
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/checkout/",
            data=json.dumps({"shipping_cost": "100.00", "taxes": "0", "discount": "0"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        order = SalesOrder.objects.get(id=resp.json()["id"])
        self.assertEqual(order.total_price, Decimal("600.00"))

    def test_checkout_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/checkout/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_checkout_sales_channel_is_ecommerce(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        resp = self.client.post(
            f"/api/ecommerce/carts/{self.cart.id}/checkout/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        order = SalesOrder.objects.get(id=resp.json()["id"])
        self.assertEqual(order.sales_channel, "ecommerce")
