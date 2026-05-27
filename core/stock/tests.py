import json
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User, Supplier
from core.store.models import Store, Branch
from core.stock.models import (
    Category, Subcategory, Product, ProductUnit,
    Warehouse, Stock, StockMovement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(email, role="employee", password="pass123", **kwargs):
    return User.objects.create_user(
        email=email, first_name="Test", last_name="User",
        role=role, password=password, **kwargs,
    )


def auth_header(user):
    return f"Bearer {RefreshToken.for_user(user).access_token}"


def make_product(sku="P001", description="Producto Test", price="100.00", cost_price="50.00", **kwargs):
    return Product.objects.create(
        sku=sku, description=description,
        price=Decimal(price), cost_price=Decimal(cost_price),
        **kwargs,
    )


def make_store(name="Test Store"):
    owner = make_user(f"owner_{name.replace(' ', '')}@test.com", role="superadmin")
    store = Store.objects.create(name=name, owner=owner)
    branch = Branch.objects.create(
        store=store, name=f"{name} - Sucursal Principal",
        manager=owner, country="AR", state="BA", city="CABA",
        address="Calle 1", postal_code="1000",
    )
    return store, branch


def make_warehouse(store, name="Depósito Central"):
    return Warehouse.objects.create(
        store=store, name=name,
        country="AR", state="BA", city="CABA", address="Av. Test 1",
    )


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------

class StockMovementModelTests(TenantTestCase):
    def setUp(self):
        self.product = make_product()
        self.user = make_user("mv@test.com")
        self.movement = StockMovement.objects.create(
            product=self.product,
            movement_type="IN",
            from_location="PUR",
            to_location="WHA",
            quantity=Decimal("10.0000"),
            status="TRAN",
        )

    def test_add_comment_appends_to_comments(self):
        self.movement.add_comment("Recibido en depósito", status_before="TRAN", user=self.user)
        self.movement.refresh_from_db()
        self.assertEqual(len(self.movement.comments), 1)

    def test_add_comment_records_user(self):
        self.movement.add_comment("Test", user=self.user)
        self.movement.refresh_from_db()
        self.assertEqual(self.movement.comments[0]["user_id"], self.user.id)

    def test_add_comment_records_sistema_when_no_user(self):
        self.movement.add_comment("Automático")
        self.movement.refresh_from_db()
        self.assertEqual(self.movement.comments[0]["user"], "Sistema")

    def test_add_comment_records_status_transition(self):
        self.movement.add_comment("Transición", status_before="TRAN")
        self.movement.refresh_from_db()
        entry = self.movement.comments[0]
        self.assertEqual(entry["status_before"], "TRAN")
        self.assertEqual(entry["status_after"], "TRAN")  # current status unchanged


class ProductModelTests(TenantTestCase):
    def test_product_images_property_empty_when_no_images(self):
        product = make_product(sku="IMG001")
        self.assertEqual(product.images, [])

    def test_product_str_includes_sku_and_description(self):
        product = make_product(sku="SKU-X", description="Artículo X")
        self.assertIn("SKU-X", str(product))
        self.assertIn("Artículo X", str(product))


# ---------------------------------------------------------------------------
# ProductViewSet Tests
# ---------------------------------------------------------------------------

class ProductListViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("plv@test.com", role="employee")
        self._auth(self.employee)
        self.cat = Category.objects.create(name="Electrónica")
        self.p1 = make_product(sku="E001", description="Laptop", price="1200.00", category=self.cat)
        self.p2 = make_product(sku="E002", description="Mouse", price="50.00", category=self.cat)
        self.p3 = make_product(sku="R001", description="Remera", price="200.00")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_returns_200(self):
        resp = self.client.get("/api/products/")
        self.assertEqual(resp.status_code, 200)

    def test_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get("/api/products/")
        self.assertEqual(resp.status_code, 401)

    def test_client_role_is_blocked(self):
        client_user = make_user("client@test.com", role="client")
        self._auth(client_user)
        resp = self.client.get("/api/products/")
        self.assertEqual(resp.status_code, 403)

    def test_paginated_5_per_page(self):
        for i in range(6):
            make_product(sku=f"PAGED{i}", description=f"Paged {i}", price="10.00")
        resp = self.client.get("/api/products/")
        data = resp.json()
        self.assertIn("results", data)
        self.assertLessEqual(len(data["results"]), 5)

    def test_all_param_disables_pagination(self):
        resp = self.client.get("/api/products/?all=1")
        data = resp.json()
        # all=1 bypasses paginator → returns plain list
        self.assertIsInstance(data, list)

    def test_filter_by_category(self):
        resp = self.client.get(f"/api/products/?category={self.cat.id}")
        data = resp.json()
        results = data.get("results", data)
        skus = [r["sku"] for r in results]
        self.assertIn("E001", skus)
        self.assertIn("E002", skus)
        self.assertNotIn("R001", skus)

    def test_filter_by_status(self):
        self.p3.status = "discontinued"
        self.p3.save()
        resp = self.client.get("/api/products/?status=discontinued")
        data = resp.json()
        results = data.get("results", data)
        skus = [r["sku"] for r in results]
        self.assertIn("R001", skus)
        self.assertNotIn("E001", skus)

    def test_search_by_sku(self):
        resp = self.client.get("/api/products/?search=E001")
        data = resp.json()
        results = data.get("results", data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["sku"], "E001")

    def test_search_by_description(self):
        resp = self.client.get("/api/products/?search=laptop")
        data = resp.json()
        results = data.get("results", data)
        skus = [r["sku"] for r in results]
        self.assertIn("E001", skus)

    def test_search_by_category_name(self):
        resp = self.client.get("/api/products/?search=Electrónica")
        data = resp.json()
        results = data.get("results", data)
        skus = [r["sku"] for r in results]
        self.assertIn("E001", skus)


class ProductCreateViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("pcreate@test.com", role="employee")
        self._auth(self.employee)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def _payload(self, sku="NEW001"):
        return {"sku": sku, "description": "Nuevo Producto", "price": "150.00", "cost_price": "80.00"}

    def test_create_returns_201(self):
        resp = self.client.post(
            "/api/products/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_create_auto_creates_stock_record(self):
        resp = self.client.post(
            "/api/products/",
            data=json.dumps(self._payload("AUTOSTOCK")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        product = Product.objects.get(sku="AUTOSTOCK")
        self.assertTrue(Stock.objects.filter(product=product).exists())
        stock = Stock.objects.get(product=product)
        self.assertEqual(stock.quantity, Decimal("0.0000"))
        self.assertIsNone(stock.warehouse)
        self.assertIsNone(stock.branch)

    def test_create_duplicate_sku_returns_400(self):
        make_product(sku="DUP001")
        resp = self.client.post(
            "/api/products/",
            data=json.dumps(self._payload("DUP001")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_client_cannot_create(self):
        client_user = make_user("client_prod@test.com", role="client")
        self._auth(client_user)
        resp = self.client.post(
            "/api/products/",
            data=json.dumps(self._payload("CLIENT001")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)


class ProductRetrieveUpdateViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("pret@test.com", role="employee")
        self._auth(self.employee)
        self.product = make_product(sku="RET001", description="Producto Retrieve")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_retrieve_returns_200(self):
        resp = self.client.get(f"/api/products/{self.product.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["sku"], "RET001")

    def test_retrieve_404_nonexistent(self):
        resp = self.client.get("/api/products/99999/")
        self.assertEqual(resp.status_code, 404)

    def test_patch_updates_description(self):
        resp = self.client.patch(
            f"/api/products/{self.product.id}/",
            data=json.dumps({"description": "Descripción actualizada"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.description, "Descripción actualizada")


class ProductSoftDeleteViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("pdel@test.com", role="employee")
        self._auth(self.employee)
        self.product = make_product(sku="DEL001")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_delete_sets_status_discontinued(self):
        resp = self.client.delete(f"/api/products/{self.product.id}/")
        self.assertEqual(resp.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, "discontinued")

    def test_delete_does_not_remove_db_record(self):
        self.client.delete(f"/api/products/{self.product.id}/")
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())

    def test_permanent_delete_removes_record(self):
        resp = self.client.delete(f"/api/products/{self.product.id}/permanent_delete/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Product.objects.filter(id=self.product.id).exists())


class ProductReactivateViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("preact@test.com", role="employee")
        self._auth(self.employee)
        self.product = make_product(sku="REACT001")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_reactivate_discontinued_product(self):
        self.product.status = "discontinued"
        self.product.save()
        resp = self.client.post(f"/api/products/{self.product.id}/reactivate/")
        self.assertEqual(resp.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, "active")

    def test_reactivate_already_active_returns_400(self):
        resp = self.client.post(f"/api/products/{self.product.id}/reactivate/")
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# CategoryViewSet Tests
# ---------------------------------------------------------------------------

class CategoryViewSetTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("catv@test.com", role="employee")
        self._auth(self.employee)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_list_returns_200(self):
        Category.objects.create(name="Alimentos")
        resp = self.client.get("/api/categories/")
        self.assertEqual(resp.status_code, 200)

    def test_create_category(self):
        resp = self.client.post(
            "/api/categories/",
            data=json.dumps({"name": "Herramientas"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Category.objects.filter(name="Herramientas").exists())

    def test_delete_category(self):
        cat = Category.objects.create(name="Temporal")
        resp = self.client.delete(f"/api/categories/{cat.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Category.objects.filter(id=cat.id).exists())

    def test_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get("/api/categories/")
        self.assertEqual(resp.status_code, 401)

    def test_client_blocked(self):
        client_user = make_user("cat_client@test.com", role="client")
        self._auth(client_user)
        resp = self.client.get("/api/categories/")
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# SubcategoryViewSet Tests
# ---------------------------------------------------------------------------

class SubcategoryViewSetTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("subcat@test.com", role="employee")
        self._auth(self.employee)
        self.category = Category.objects.create(name="Bebidas")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_list_returns_200(self):
        Subcategory.objects.create(name="Gaseosas", category=self.category)
        resp = self.client.get("/api/subcategories/")
        self.assertEqual(resp.status_code, 200)

    def test_create_subcategory(self):
        resp = self.client.post(
            "/api/subcategories/",
            data=json.dumps({"name": "Jugos", "category": self.category.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_delete_subcategory(self):
        sub = Subcategory.objects.create(name="Aguas", category=self.category)
        resp = self.client.delete(f"/api/subcategories/{sub.id}/")
        self.assertEqual(resp.status_code, 204)


# ---------------------------------------------------------------------------
# WarehouseViewSet Tests
# ---------------------------------------------------------------------------

class WarehouseViewSetTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.superadmin = make_user("wsa@test.com", role="superadmin")
        self.employee = make_user("wemp@test.com", role="employee")
        self.store, self.branch = make_store("Warehouse Store")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_superadmin_can_create_warehouse(self):
        self._auth(self.superadmin)
        resp = self.client.post(
            "/api/warehouses/",
            data=json.dumps({
                "name": "Depósito Norte",
                "country": "AR", "state": "BA", "city": "CABA", "address": "Av. Norte 1",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_employee_cannot_create_warehouse(self):
        self._auth(self.employee)
        resp = self.client.post(
            "/api/warehouses/",
            data=json.dumps({
                "store": self.store.id,
                "name": "Depósito Bloqueado",
                "country": "AR", "state": "BA", "city": "CABA", "address": "Av. 1",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_list_returns_200(self):
        self._auth(self.employee)
        make_warehouse(self.store)
        resp = self.client.get("/api/warehouses/")
        self.assertEqual(resp.status_code, 200)

    def test_delete_warehouse_without_stock(self):
        self._auth(self.employee)
        wh = make_warehouse(self.store, "Depósito Vacío")
        resp = self.client.delete(f"/api/warehouses/{wh.id}/")
        self.assertEqual(resp.status_code, 204)

    def test_delete_warehouse_with_stock_returns_400(self):
        self._auth(self.employee)
        wh = make_warehouse(self.store, "Depósito Con Stock")
        product = make_product(sku="WHSTOCK")
        Stock.objects.create(product=product, warehouse=wh, quantity=Decimal("5.0000"))
        resp = self.client.delete(f"/api/warehouses/{wh.id}/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Warehouse.objects.filter(id=wh.id).exists())

    def test_warehouse_stock_action_returns_200(self):
        self._auth(self.employee)
        wh = make_warehouse(self.store, "Depósito Stock Action")
        resp = self.client.get(f"/api/warehouses/{wh.id}/stock/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("stock", resp.json())


# ---------------------------------------------------------------------------
# ProductUnitViewSet Tests
# ---------------------------------------------------------------------------

class ProductUnitViewSetTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("punit@test.com", role="employee")
        self._auth(self.employee)
        self.product = make_product(sku="UNIT001")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_create_product_unit(self):
        resp = self.client.post(
            "/api/productunits/",
            data=json.dumps({
                "product": self.product.id,
                "name": "Caja x12",
                "conversion_factor": "12.0000",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(ProductUnit.objects.filter(product=self.product, name="Caja x12").exists())

    def test_list_filter_by_product(self):
        ProductUnit.objects.create(product=self.product, name="Pack x6", conversion_factor=Decimal("6.0000"))
        resp = self.client.get(f"/api/productunits/?product={self.product.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)

    def test_delete_product_unit(self):
        unit = ProductUnit.objects.create(
            product=self.product, name="Bolsa x25", conversion_factor=Decimal("25.0000")
        )
        resp = self.client.delete(f"/api/productunits/{unit.id}/")
        self.assertEqual(resp.status_code, 204)


# ---------------------------------------------------------------------------
# StockViewSet Tests (Read-Only)
# ---------------------------------------------------------------------------

class StockViewSetTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("stock@test.com", role="employee")
        self._auth(self.employee)
        self.store, self.branch = make_store("Stock Store")
        self.warehouse = make_warehouse(self.store, "Depósito Stock Test")
        self.product = make_product(sku="STCK001", safety_stock=Decimal("10.0000"))
        self.stock_record = Stock.objects.create(
            product=self.product, warehouse=self.warehouse, quantity=Decimal("5.0000")
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_list_returns_200(self):
        resp = self.client.get("/api/stock/")
        self.assertEqual(resp.status_code, 200)

    def test_post_is_not_allowed(self):
        resp = self.client.post(
            "/api/stock/",
            data=json.dumps({"product": self.product.id, "quantity": "10.0"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 405)

    def test_retrieve_returns_200(self):
        resp = self.client.get(f"/api/stock/{self.stock_record.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_filter_by_product(self):
        resp = self.client.get(f"/api/stock/?product={self.product.id}")
        data = resp.json()
        results = data.get("results", data)
        self.assertTrue(all(r["product_detail"]["sku"] == "STCK001" for r in results))

    def test_filter_by_warehouse(self):
        resp = self.client.get(f"/api/stock/?warehouse={self.warehouse.id}")
        self.assertEqual(resp.status_code, 200)

    def test_filter_low_stock_true(self):
        # product has safety_stock=10, quantity=5 → should appear
        resp = self.client.get("/api/stock/?low_stock=true")
        data = resp.json()
        results = data.get("results", data)
        ids = [r["id"] for r in results]
        self.assertIn(self.stock_record.id, ids)

    def test_search_by_sku(self):
        resp = self.client.get("/api/stock/?search=STCK001")
        data = resp.json()
        results = data.get("results", data)
        self.assertTrue(len(results) >= 1)

    def test_low_stock_alert_action_returns_200(self):
        resp = self.client.get("/api/stock/low_stock_alert/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("count", data)
        self.assertIn("results", data)

    def test_low_stock_alert_identifies_below_safety_stock(self):
        # stock_record has quantity=5, safety_stock=10 → low stock
        resp = self.client.get("/api/stock/low_stock_alert/")
        product_ids = [r["product"]["id"] for r in resp.json()["results"]]
        self.assertIn(self.product.id, product_ids)

    def test_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get("/api/stock/")
        self.assertEqual(resp.status_code, 401)

    def test_client_blocked(self):
        client_user = make_user("stock_client@test.com", role="client")
        self._auth(client_user)
        resp = self.client.get("/api/stock/")
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# StockMovementViewSet Tests
# ---------------------------------------------------------------------------

class StockMovementListViewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("smlist@test.com", role="employee")
        self._auth(self.employee)
        self.product = make_product(sku="MVLIST")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_list_returns_200(self):
        resp = self.client.get("/api/stock-movements/")
        self.assertEqual(resp.status_code, 200)

    def test_filter_by_movement_type(self):
        StockMovement.objects.create(
            product=self.product, movement_type="IN",
            from_location="PUR", to_location="WHA",
            quantity=Decimal("10"), status="TRAN",
        )
        StockMovement.objects.create(
            product=self.product, movement_type="OUT",
            from_location="WHA", to_location="SAL",
            quantity=Decimal("5"), status="TRAN",
        )
        resp = self.client.get("/api/stock-movements/?movement_type=IN")
        data = resp.json()
        results = data.get("results", data)
        self.assertTrue(all(r["movement_type"] == "IN" for r in results))

    def test_filter_by_status(self):
        StockMovement.objects.create(
            product=self.product, movement_type="IN",
            from_location="PUR", to_location="WHA",
            quantity=Decimal("10"), status="REC",
        )
        resp = self.client.get("/api/stock-movements/?status=REC")
        data = resp.json()
        results = data.get("results", data)
        self.assertTrue(all(r["status"] == "REC" for r in results))

    def test_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get("/api/stock-movements/")
        self.assertEqual(resp.status_code, 401)

    def test_client_blocked(self):
        client_user = make_user("mvlist_client@test.com", role="client")
        self._auth(client_user)
        resp = self.client.get("/api/stock-movements/")
        self.assertEqual(resp.status_code, 403)

    def test_delete_not_allowed(self):
        mv = StockMovement.objects.create(
            product=self.product, movement_type="IN",
            from_location="PUR", to_location="WHA",
            quantity=Decimal("1"), status="TRAN",
        )
        resp = self.client.delete(f"/api/stock-movements/{mv.id}/")
        self.assertEqual(resp.status_code, 405)


class StockMovementInternalTransferTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("smtransfer@test.com", role="employee")
        self._auth(self.employee)
        self.store, self.branch = make_store("Transfer Store")
        self.wh_origin = make_warehouse(self.store, "Origen")
        self.wh_dest = make_warehouse(self.store, "Destino")
        self.product = make_product(sku="TRANSFER001")
        # Stock en origen
        self.stock_origin = Stock.objects.create(
            product=self.product, warehouse=self.wh_origin, quantity=Decimal("100.0000")
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def _payload(self, quantity=20, from_id=None, to_id=None):
        return {
            "product": self.product.id,
            "fromLocationType": "WHA",
            "fromLocation": from_id or self.wh_origin.id,
            "toLocationType": "WHA",
            "toLocation": to_id or self.wh_dest.id,
            "quantity": quantity,
            "note": "Test transfer",
        }

    def test_successful_transfer_returns_201(self):
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_transfer_deducts_from_origin(self):
        self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload(quantity=30)),
            content_type="application/json",
        )
        self.stock_origin.refresh_from_db()
        self.assertEqual(self.stock_origin.quantity, Decimal("70.0000"))

    def test_transfer_adds_to_destination(self):
        self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload(quantity=25)),
            content_type="application/json",
        )
        stock_dest = Stock.objects.get(product=self.product, warehouse=self.wh_dest)
        self.assertEqual(stock_dest.quantity, Decimal("25.0000"))

    def test_transfer_creates_movement_in_tran_status(self):
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.json()["status"], "TRAN")

    def test_transfer_creates_destination_stock_if_not_exists(self):
        self.assertFalse(Stock.objects.filter(product=self.product, warehouse=self.wh_dest).exists())
        self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertTrue(Stock.objects.filter(product=self.product, warehouse=self.wh_dest).exists())

    def test_missing_required_field_returns_400(self):
        payload = self._payload()
        del payload["quantity"]
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_same_origin_and_destination_returns_400(self):
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload(from_id=self.wh_origin.id, to_id=self.wh_origin.id)),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_zero_quantity_returns_400(self):
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload(quantity=0)),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_insufficient_stock_returns_400(self):
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload(quantity=999)),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_nonexistent_product_returns_404(self):
        payload = self._payload()
        payload["product"] = 99999
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_nonexistent_location_returns_404(self):
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps(self._payload(to_id=99999)),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)


class StockMovementPatchTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("smpatch@test.com", role="employee")
        self._auth(self.employee)
        self.store, self.branch = make_store("Patch Store")
        self.wh_origin = make_warehouse(self.store, "Patch Origen")
        self.wh_dest = make_warehouse(self.store, "Patch Destino")
        self.product = make_product(sku="PATCH001")
        self.stock_origin = Stock.objects.create(
            product=self.product, warehouse=self.wh_origin, quantity=Decimal("50.0000")
        )
        # Crear una transferencia interna via API para que el note tenga metadata correcta
        resp = self.client.post(
            "/api/stock-movements/",
            data=json.dumps({
                "product": self.product.id,
                "fromLocationType": "WHA",
                "fromLocation": self.wh_origin.id,
                "toLocationType": "WHA",
                "toLocation": self.wh_dest.id,
                "quantity": 20,
            }),
            content_type="application/json",
        )
        self.movement_id = resp.json()["id"]
        # Refrescar stock_origin después del transfer
        self.stock_origin.refresh_from_db()

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_patch_to_rec_updates_status(self):
        resp = self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"status": "REC"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "REC")

    def test_patch_rec_is_terminal_cannot_be_changed(self):
        self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"status": "REC"}),
            content_type="application/json",
        )
        resp = self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"status": "TRAN"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_can_reverts_stock(self):
        origin_qty_before = self.stock_origin.quantity
        self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"status": "CAN"}),
            content_type="application/json",
        )
        self.stock_origin.refresh_from_db()
        # After cancel, origin should have 20 units restored
        self.assertEqual(self.stock_origin.quantity, origin_qty_before + Decimal("20.0000"))

    def test_patch_can_clears_destination_stock(self):
        self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"status": "CAN"}),
            content_type="application/json",
        )
        stock_dest = Stock.objects.get(product=self.product, warehouse=self.wh_dest)
        self.assertEqual(stock_dest.quantity, Decimal("0.0000"))

    def test_patch_can_is_terminal_cannot_be_changed(self):
        self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"status": "CAN"}),
            content_type="application/json",
        )
        resp = self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"status": "TRAN"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_without_status_field_returns_400(self):
        resp = self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"note": "nuevo"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_invalid_status_returns_400(self):
        resp = self.client.patch(
            f"/api/stock-movements/{self.movement_id}/",
            data=json.dumps({"status": "INVALID"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_sale_linked_movement_returns_400(self):
        from core.crm.models import Customer
        from core.billing.models import SalesOrder
        customer = Customer.objects.create(customer_type="person", first_name="T", last_name="T")
        order = SalesOrder.objects.create(
            customer=customer, sales_channel="storefront",
            payment_method="efectivo", delivery_date="2026-06-01",
            total_price=Decimal("0"), status="draft",
        )
        movement = StockMovement.objects.create(
            product=self.product,
            movement_type="OUT",
            from_location="WHA",
            to_location="SAL",
            quantity=Decimal("5"),
            status="TRAN",
            sale=order,
        )
        resp = self.client.patch(
            f"/api/stock-movements/{movement.id}/",
            data=json.dumps({"status": "REC"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# StockMovement Custom Actions Tests
# ---------------------------------------------------------------------------

class StockMovementActionsTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("smaction@test.com", role="employee")
        self._auth(self.employee)
        self.product = make_product(sku="ACTION001")
        StockMovement.objects.create(
            product=self.product, movement_type="IN",
            from_location="PUR", to_location="WHA",
            quantity=Decimal("10"), status="TRAN",
        )
        StockMovement.objects.create(
            product=self.product, movement_type="OUT",
            from_location="WHA", to_location="SAL",
            quantity=Decimal("5"), status="REC",
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_by_product_without_param_returns_400(self):
        resp = self.client.get("/api/stock-movements/by_product/")
        self.assertEqual(resp.status_code, 400)

    def test_by_product_with_param_returns_results(self):
        resp = self.client.get(f"/api/stock-movements/by_product/?product_id={self.product.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)

    def test_by_location_without_params_returns_400(self):
        resp = self.client.get("/api/stock-movements/by_location/")
        self.assertEqual(resp.status_code, 400)

    def test_recent_returns_200(self):
        resp = self.client.get("/api/stock-movements/recent/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
        self.assertLessEqual(data["count"], 50)

    def test_recent_respects_limit_param(self):
        resp = self.client.get("/api/stock-movements/recent/?limit=1")
        data = resp.json()
        self.assertLessEqual(len(data["results"]), 1)

    def test_pending_returns_only_pen_and_tran(self):
        resp = self.client.get("/api/stock-movements/pending/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        statuses = [r["status"] for r in data["results"]]
        self.assertTrue(all(s in ["PEN", "TRAN"] for s in statuses))
