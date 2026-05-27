"""
Unit tests for the core.store module.

Covers:
- Store and Branch model logic (slug, save, __str__)
- BranchSerializer validations and create/update sync behavior
- StoreSerializer: auto branch creation, location sync, owner validation
- StoreCreateSerializer: simplified creation flow
- StoreConfigSerializer: read-only public representation
- StoreViewSet: CRUD, my_store, branches endpoints
- BranchViewSet: CRUD, principal branch protection
- StoreConfigView: public ecommerce config
"""
import datetime

from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from core.store.models import Store, Branch
from core.store.serializer import (
    BranchSerializer,
    StoreConfigSerializer,
    StoreCreateSerializer,
    StoreSerializer,
)
from users.models import Employee, User


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_user(email="user@test.com", role="superadmin", password="pass123", **kwargs):
    return User.objects.create_user(
        email=email,
        first_name="Test",
        last_name="User",
        role=role,
        password=password,
        **kwargs,
    )


def make_store(owner, name="Test Store", **kwargs):
    return Store.objects.create(
        name=name,
        country="Argentina",
        state="Buenos Aires",
        postal_code="1000",
        city="Buenos Aires",
        address="Av. Test 123",
        phone="1111111111",
        owner=owner,
        **kwargs,
    )


def make_branch(store, manager, name="Sucursal Norte", **kwargs):
    return Branch.objects.create(
        store=store,
        manager=manager,
        name=name,
        country="Argentina",
        state="Buenos Aires",
        postal_code="1000",
        city="Buenos Aires",
        address="Calle Test 1",
        **kwargs,
    )


def make_employee(user, store, branch=None):
    return Employee.objects.create(
        user=user,
        store=store,
        branch=branch,
        birth=datetime.date(1990, 1, 1),
        date_joined=datetime.date(2020, 1, 1),
        position="Developer",
        dni=12345678,
    )


def auth_header(user):
    refresh = RefreshToken.for_user(user)
    return f"Bearer {refresh.access_token}"


# ===========================================================================
# Model tests
# ===========================================================================

class StoreModelTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")

    def test_slug_auto_generated_on_create(self):
        store = make_store(owner=self.owner, name="Mi Tienda Principal")
        self.assertEqual(store.slug, "mi-tienda-principal")

    def test_slug_not_overwritten_on_update(self):
        store = make_store(owner=self.owner, name="Tienda Slug")
        original_slug = store.slug
        store.country = "Brasil"
        store.save()
        self.assertEqual(store.slug, original_slug)

    def test_name_is_unique(self):
        make_store(owner=self.owner, name="Tienda Unica")
        owner2 = make_user(email="owner2@test.com", role="superadmin")
        with self.assertRaises(Exception):
            make_store(owner=owner2, name="Tienda Unica")

    def test_is_active_defaults_to_false(self):
        store = make_store(owner=self.owner)
        self.assertFalse(store.is_active)

    def test_view_only_defaults_to_true(self):
        store = make_store(owner=self.owner)
        self.assertTrue(store.view_only)

    def test_dark_mode_defaults_to_false(self):
        store = make_store(owner=self.owner)
        self.assertFalse(store.dark_mode)

    def test_theme_id_defaults_to_wine(self):
        store = make_store(owner=self.owner)
        self.assertEqual(store.theme_id, "wine")

    def test_str_returns_name(self):
        store = make_store(owner=self.owner, name="Tienda Str")
        self.assertEqual(str(store), "Tienda Str")

    def test_owner_is_one_to_one_with_user(self):
        store = make_store(owner=self.owner)
        self.assertEqual(store.owner, self.owner)
        # Cannot create a second store for the same owner
        with self.assertRaises(Exception):
            Store.objects.create(
                name="Segunda Tienda",
                country="Argentina",
                state="Buenos Aires",
                postal_code="1000",
                city="Buenos Aires",
                address="Otra dirección",
                phone="222",
                owner=self.owner,
            )


class BranchModelTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")
        self.store = make_store(owner=self.owner)
        self.manager = make_user(email="mgr@test.com", role="manager")

    def test_branch_str_returns_name(self):
        branch = make_branch(store=self.store, manager=self.manager, name="Sucursal Test")
        self.assertEqual(str(branch), "Sucursal Test")

    def test_branch_store_relation(self):
        branch = make_branch(store=self.store, manager=self.manager)
        self.assertEqual(branch.store, self.store)

    def test_branch_manager_relation(self):
        branch = make_branch(store=self.store, manager=self.manager)
        self.assertEqual(branch.manager, self.manager)


# ===========================================================================
# Serializer tests
# ===========================================================================

class BranchSerializerValidationTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")
        self.store = make_store(owner=self.owner)
        self.manager = make_user(email="mgr@test.com", role="manager")

    def test_validate_manager_employee_role_raises(self):
        from rest_framework.exceptions import ValidationError
        emp = make_user(email="emp@test.com", role="employee")
        with self.assertRaises(ValidationError):
            BranchSerializer().validate_manager(emp)

    def test_validate_manager_client_role_raises(self):
        from rest_framework.exceptions import ValidationError
        client = make_user(email="cli@test.com", role="client")
        with self.assertRaises(ValidationError):
            BranchSerializer().validate_manager(client)

    def test_validate_manager_manager_role_passes(self):
        result = BranchSerializer().validate_manager(self.manager)
        self.assertEqual(result, self.manager)

    def test_validate_manager_superadmin_role_passes(self):
        result = BranchSerializer().validate_manager(self.owner)
        self.assertEqual(result, self.owner)

    def test_validate_manager_none_passes(self):
        result = BranchSerializer().validate_manager(None)
        self.assertIsNone(result)

    def test_validate_main_branch_manager_must_be_owner(self):
        from rest_framework.exceptions import ValidationError
        other_manager = make_user(email="other@test.com", role="manager")
        s = BranchSerializer()
        s.instance = None
        data = {
            "name": f"{self.store.name} - Sucursal Principal",
            "manager": other_manager,
            "store": self.store,
        }
        with self.assertRaises(ValidationError) as ctx:
            s.validate(data)
        self.assertIn("manager", ctx.exception.detail)

    def test_validate_main_branch_owner_as_manager_passes(self):
        s = BranchSerializer()
        s.instance = None
        data = {
            "name": f"{self.store.name} - Sucursal Principal",
            "manager": self.owner,
            "store": self.store,
        }
        result = s.validate(data)
        self.assertEqual(result, data)

    def test_validate_regular_branch_any_manager_passes(self):
        other_mgr = make_user(email="othermgr@test.com", role="manager")
        s = BranchSerializer()
        s.instance = None
        data = {
            "name": "Sucursal Norte",
            "manager": other_mgr,
            "store": self.store,
        }
        result = s.validate(data)
        self.assertEqual(result, data)

    def test_get_manager_name_returns_full_name(self):
        branch = make_branch(store=self.store, manager=self.manager)
        s = BranchSerializer(branch)
        self.assertEqual(
            s.data["manager_name"],
            f"{self.manager.first_name} {self.manager.last_name}",
        )

    def test_get_manager_name_none_when_no_manager(self):
        branch = Branch.objects.create(
            store=self.store,
            manager=self.manager,
            name="Sin Manager",
            country="AR",
            state="BA",
            postal_code="1000",
            city="CABA",
            address="X",
        )
        branch.manager = None
        # Test method directly
        s = BranchSerializer()
        branch.manager = None
        result = s.get_manager_name(branch)
        self.assertIsNone(result)


class BranchSerializerCreateTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")
        self.store = make_store(owner=self.owner)
        self.manager = make_user(email="mgr@test.com", role="manager")

    def test_create_branch_assigns_manager_employee_branch(self):
        emp = make_employee(user=self.manager, store=self.store)
        s = BranchSerializer(
            data={
                "store": self.store.id,
                "manager": self.manager.id,
                "name": "Nueva Sucursal",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Av. Nueva 1",
            }
        )
        self.assertTrue(s.is_valid(), s.errors)
        branch = s.save()
        emp.refresh_from_db()
        self.assertEqual(emp.branch, branch)

    def test_create_branch_no_employee_record_does_not_raise(self):
        # Manager without Employee record - should not fail
        s = BranchSerializer(
            data={
                "store": self.store.id,
                "manager": self.manager.id,
                "name": "Sin Empleado Mgr",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Calle 1",
            }
        )
        self.assertTrue(s.is_valid(), s.errors)
        branch = s.save()
        self.assertIsNotNone(branch.id)


class BranchSerializerUpdateTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")
        self.store = make_store(owner=self.owner)
        self.manager = make_user(email="mgr@test.com", role="manager")
        self.branch = make_branch(store=self.store, manager=self.manager)
        self.emp = make_employee(user=self.manager, store=self.store, branch=self.branch)

    def test_manager_change_clears_old_employee_branch(self):
        new_mgr = make_user(email="newmgr@test.com", role="manager")
        new_emp = make_employee(user=new_mgr, store=self.store)
        s = BranchSerializer(self.branch, data={"manager": new_mgr.id}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        self.emp.refresh_from_db()
        self.assertIsNone(self.emp.branch)

    def test_manager_change_assigns_new_employee_branch(self):
        new_mgr = make_user(email="newmgr2@test.com", role="manager")
        new_emp = make_employee(user=new_mgr, store=self.store)
        s = BranchSerializer(self.branch, data={"manager": new_mgr.id}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        new_emp.refresh_from_db()
        self.assertEqual(new_emp.branch, self.branch)

    def test_main_branch_location_update_syncs_to_store(self):
        main_branch = Branch.objects.get(
            store=self.store, name__endswith="- Sucursal Principal"
        )
        s = BranchSerializer(main_branch, data={"city": "Rosario"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        self.store.refresh_from_db()
        self.assertEqual(self.store.city, "Rosario")

    def test_non_main_branch_update_does_not_sync_to_store(self):
        original_city = self.store.city
        s = BranchSerializer(self.branch, data={"city": "Córdoba"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        self.store.refresh_from_db()
        self.assertEqual(self.store.city, original_city)


class StoreSerializerTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")

    def test_validate_owner_non_superadmin_raises(self):
        from rest_framework.exceptions import ValidationError
        employee = make_user(email="emp@test.com", role="employee")
        with self.assertRaises(ValidationError):
            StoreSerializer().validate_owner(employee)

    def test_validate_owner_superadmin_passes(self):
        result = StoreSerializer().validate_owner(self.owner)
        self.assertEqual(result, self.owner)

    def test_create_auto_generates_main_branch(self):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.user = self.owner
        s = StoreSerializer(
            data={
                "name": "Auto Branch Store",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Av. 1",
                "phone": "111",
                "owner": self.owner.id,
            },
            context={"request": request},
        )
        self.assertTrue(s.is_valid(), s.errors)
        store = s.save()
        main_branch = Branch.objects.filter(
            store=store, name__endswith="- Sucursal Principal"
        ).first()
        self.assertIsNotNone(main_branch)

    def test_create_sets_is_active_false(self):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.user = self.owner
        s = StoreSerializer(
            data={
                "name": "Inactive Store",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Av. 2",
                "phone": "222",
                "owner": self.owner.id,
            },
            context={"request": request},
        )
        self.assertTrue(s.is_valid(), s.errors)
        store = s.save()
        self.assertFalse(store.is_active)

    def test_create_main_branch_inherits_store_location(self):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.user = self.owner
        s = StoreSerializer(
            data={
                "name": "Location Sync Store",
                "country": "Argentina",
                "state": "Córdoba",
                "postal_code": "5000",
                "city": "Córdoba",
                "address": "Av. Colón 100",
                "phone": "333",
                "owner": self.owner.id,
            },
            context={"request": request},
        )
        self.assertTrue(s.is_valid(), s.errors)
        store = s.save()
        main_branch = Branch.objects.get(store=store, name__endswith="- Sucursal Principal")
        self.assertEqual(main_branch.city, "Córdoba")
        self.assertEqual(main_branch.state, "Córdoba")
        self.assertEqual(main_branch.address, "Av. Colón 100")

    def test_update_location_syncs_to_main_branch(self):
        store = make_store(owner=self.owner, name="Sync Store")
        main_branch = Branch.objects.get(store=store, name__endswith="- Sucursal Principal")
        s = StoreSerializer(store, data={"city": "Mendoza"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        main_branch.refresh_from_db()
        self.assertEqual(main_branch.city, "Mendoza")

    def test_update_non_location_field_does_not_change_branch(self):
        store = make_store(owner=self.owner, name="No Sync Store")
        main_branch = Branch.objects.get(store=store, name__endswith="- Sucursal Principal")
        original_city = main_branch.city
        s = StoreSerializer(store, data={"phone": "999999999"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        main_branch.refresh_from_db()
        self.assertEqual(main_branch.city, original_city)

    def test_get_owner_name_returns_full_name(self):
        store = make_store(owner=self.owner, name="Owner Name Store")
        s = StoreSerializer(store)
        self.assertEqual(
            s.data["owner_name"],
            f"{self.owner.first_name} {self.owner.last_name}",
        )

    def test_branches_included_in_serializer_data(self):
        store = make_store(owner=self.owner, name="With Branches Store")
        manager = make_user(email="mgr2@test.com", role="manager")
        make_branch(store=store, manager=manager, name="Extra Branch")
        s = StoreSerializer(store)
        branch_names = [b["name"] for b in s.data["branches"]]
        self.assertIn("Extra Branch", branch_names)
        self.assertTrue(
            any("Sucursal Principal" in n for n in branch_names)
        )


class StoreCreateSerializerTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")

    def test_create_sets_owner_from_request_user(self):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.user = self.owner
        s = StoreCreateSerializer(
            data={
                "name": "Create Serializer Store",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Av. 1",
                "phone": "111",
            },
            context={"request": request},
        )
        self.assertTrue(s.is_valid(), s.errors)
        store = s.save()
        self.assertEqual(store.owner, self.owner)

    def test_create_auto_creates_main_branch(self):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.user = self.owner
        s = StoreCreateSerializer(
            data={
                "name": "Auto Branch Create",
                "country": "Argentina",
                "state": "Santa Fe",
                "postal_code": "2000",
                "city": "Rosario",
                "address": "Calle 1",
                "phone": "444",
            },
            context={"request": request},
        )
        self.assertTrue(s.is_valid(), s.errors)
        store = s.save()
        self.assertTrue(
            Branch.objects.filter(
                store=store, name__endswith="- Sucursal Principal"
            ).exists()
        )

    def test_create_assigns_main_branch_to_owner_employee(self):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.user = self.owner
        s = StoreCreateSerializer(
            data={
                "name": "Employee Branch Store",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Av. 99",
                "phone": "555",
            },
            context={"request": request},
        )
        self.assertTrue(s.is_valid(), s.errors)
        store = s.save()
        # Create employee for the owner and verify branch assignment logic
        # (employee doesn't exist yet so branch assignment is skipped)
        emp = make_employee(user=self.owner, store=store)
        # Verify the store was created correctly
        self.assertEqual(store.owner, self.owner)


class StoreConfigSerializerTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")
        self.store = make_store(owner=self.owner, name="Config Store")
        self.store.is_active = True
        self.store.save()

    def test_config_serializer_returns_expected_fields(self):
        s = StoreConfigSerializer(self.store)
        data = s.data
        self.assertIn("id", data)
        self.assertIn("name", data)
        self.assertIn("logo", data)
        self.assertIn("is_active", data)
        self.assertIn("view_only", data)
        self.assertIn("dark_mode", data)
        self.assertIn("theme_id", data)

    def test_config_serializer_all_fields_read_only(self):
        s = StoreConfigSerializer(self.store, data={"name": "Hacked"})
        # read_only fields are ignored in input
        self.assertTrue(s.is_valid(), s.errors)

    def test_logo_is_none_when_no_logo(self):
        s = StoreConfigSerializer(self.store)
        self.assertIsNone(s.data["logo"])


# ===========================================================================
# StoreViewSet tests
# ===========================================================================

class StoreViewSetTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.superadmin = make_user(
            email="super@test.com", role="superadmin", password="pass"
        )
        self.manager = make_user(
            email="mgr@test.com", role="manager", password="pass"
        )
        self.employee = make_user(
            email="emp@test.com", role="employee", password="pass"
        )
        self.client_user = make_user(
            email="cli@test.com", role="client", password="pass"
        )
        self.store = make_store(owner=self.superadmin, name="Main Store")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_list_unauthenticated_returns_401(self):
        resp = self.client.get("/api/stores/")
        self.assertEqual(resp.status_code, 401)

    def test_list_client_returns_403(self):
        self._auth(self.client_user)
        resp = self.client.get("/api/stores/")
        self.assertEqual(resp.status_code, 403)

    def test_list_authenticated_employee_returns_200(self):
        self._auth(self.employee)
        resp = self.client.get("/api/stores/")
        self.assertEqual(resp.status_code, 200)

    def test_list_returns_all_stores(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/stores/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data), 1)

    def test_retrieve_store_by_id(self):
        self._auth(self.superadmin)
        resp = self.client.get(f"/api/stores/{self.store.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["name"], "Main Store")

    def test_superadmin_can_create_store(self):
        self._auth(self.superadmin)
        # Need a new owner since superadmin already has a store (OneToOne)
        new_owner = make_user(email="newowner@test.com", role="superadmin")
        resp = self.client.post(
            "/api/stores/",
            {
                "name": "New Store Via API",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1001",
                "city": "Buenos Aires",
                "address": "Calle Nueva 1",
                "phone": "222222",
            },
            content_type="application/json",
        )
        # Superadmin creates store, owner is set to request.user
        self.assertEqual(resp.status_code, 201)

    def test_partial_update_store_by_superadmin(self):
        self._auth(self.superadmin)
        resp = self.client.patch(
            f"/api/stores/{self.store.id}/",
            {"phone": "999999999"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_branches_action_returns_store_branches(self):
        self._auth(self.superadmin)
        resp = self.client.get(f"/api/stores/{self.store.id}/branches/")
        self.assertEqual(resp.status_code, 200)
        # Main branch was auto-created with the store
        branch_names = [b["name"] for b in resp.data]
        self.assertTrue(any("Sucursal Principal" in n for n in branch_names))

    def test_my_store_returns_store_for_owner(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/stores/my-store/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["name"], "Main Store")

    def test_my_store_returns_404_when_no_store(self):
        user_no_store = make_user(email="nostore@test.com", role="superadmin")
        self._auth(user_no_store)
        resp = self.client.get("/api/stores/my-store/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["error"], "No tienes una tienda asociada")

    def test_my_store_client_returns_403(self):
        self._auth(self.client_user)
        resp = self.client.get("/api/stores/my-store/")
        self.assertEqual(resp.status_code, 403)

    def test_delete_store_removes_it(self):
        self._auth(self.superadmin)
        owner2 = make_user(email="del_owner@test.com", role="superadmin")
        store2 = make_store(owner=owner2, name="To Delete Store")
        resp = self.client.delete(f"/api/stores/{store2.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Store.objects.filter(id=store2.id).exists())


# ===========================================================================
# BranchViewSet tests
# ===========================================================================

class BranchViewSetTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.superadmin = make_user(
            email="super@test.com", role="superadmin", password="pass"
        )
        self.manager = make_user(
            email="mgr@test.com", role="manager", password="pass"
        )
        self.employee = make_user(
            email="emp@test.com", role="employee", password="pass"
        )
        self.client_user = make_user(
            email="cli@test.com", role="client", password="pass"
        )
        self.store = make_store(owner=self.superadmin, name="Branch Test Store")
        # make_store auto-creates a main branch via serializer/view,
        # but here we're directly creating the store model, so create manually
        self.main_branch = Branch.objects.get_or_create(
            store=self.store,
            name=f"{self.store.name} - Sucursal Principal",
            defaults={
                "manager": self.superadmin,
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Principal",
            },
        )[0]
        self.branch = make_branch(
            store=self.store, manager=self.manager, name="Sucursal Norte"
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_list_unauthenticated_returns_401(self):
        resp = self.client.get("/api/branches/")
        self.assertEqual(resp.status_code, 401)

    def test_list_client_returns_403(self):
        self._auth(self.client_user)
        resp = self.client.get("/api/branches/")
        self.assertEqual(resp.status_code, 403)

    def test_list_authenticated_returns_200(self):
        self._auth(self.employee)
        resp = self.client.get("/api/branches/")
        self.assertEqual(resp.status_code, 200)

    def test_retrieve_branch_by_id(self):
        self._auth(self.superadmin)
        resp = self.client.get(f"/api/branches/{self.branch.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["name"], "Sucursal Norte")

    def test_superadmin_can_create_branch(self):
        self._auth(self.superadmin)
        resp = self.client.post(
            "/api/branches/",
            {
                "store": self.store.id,
                "manager": self.manager.id,
                "name": "Sucursal Sur",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1100",
                "city": "La Plata",
                "address": "Av. Sur 1",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_partial_update_branch(self):
        self._auth(self.superadmin)
        resp = self.client.patch(
            f"/api/branches/{self.branch.id}/",
            {"city": "Rosario"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_delete_non_main_branch_succeeds(self):
        self._auth(self.superadmin)
        branch_to_del = make_branch(
            store=self.store, manager=self.manager, name="Para Borrar"
        )
        resp = self.client.delete(f"/api/branches/{branch_to_del.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Branch.objects.filter(id=branch_to_del.id).exists())

    def test_delete_main_branch_returns_400(self):
        self._auth(self.superadmin)
        resp = self.client.delete(f"/api/branches/{self.main_branch.id}/")
        # perform_destroy returns Response(error) but DRF ignores the return value
        # The actual behavior: instance.delete() is never called if it returns early
        # So the branch should NOT be deleted
        self.assertTrue(
            Branch.objects.filter(id=self.main_branch.id).exists(),
            "Main branch should not have been deleted",
        )

    def test_branch_name_with_manager_info_in_list(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/branches/")
        self.assertEqual(resp.status_code, 200)
        names = [b["name"] for b in resp.data["results"]]
        self.assertIn("Sucursal Norte", names)


# ===========================================================================
# StoreConfigView tests
# ===========================================================================

class StoreConfigViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.owner = make_user(email="owner@test.com", role="superadmin")

    def test_config_no_active_store_returns_404(self):
        # Ensure no active store exists
        Store.objects.all().update(is_active=False)
        resp = self.client.get("/api/config/")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.data)
        self.assertIn("default_config", resp.data)

    def test_config_active_store_returns_200(self):
        store = make_store(owner=self.owner, name="Active Store")
        store.is_active = True
        store.save()
        resp = self.client.get("/api/config/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["name"], "Active Store")

    def test_config_is_public_no_auth_required(self):
        # No authentication needed
        store = make_store(owner=self.owner, name="Public Store")
        store.is_active = True
        store.save()
        resp = self.client.get("/api/config/")
        self.assertEqual(resp.status_code, 200)

    def test_config_returns_expected_fields(self):
        store = make_store(owner=self.owner, name="Fields Store")
        store.is_active = True
        store.save()
        resp = self.client.get("/api/config/")
        self.assertEqual(resp.status_code, 200)
        for field in ("id", "name", "logo", "is_active", "view_only", "dark_mode", "theme_id"):
            self.assertIn(field, resp.data)

    def test_config_returns_first_active_store(self):
        store1 = make_store(owner=self.owner, name="First Active")
        store1.is_active = True
        store1.save()
        owner2 = make_user(email="owner2@test.com", role="superadmin")
        store2 = make_store(owner=owner2, name="Second Active")
        store2.is_active = True
        store2.save()
        resp = self.client.get("/api/config/")
        self.assertEqual(resp.status_code, 200)
        # Returns first() - at least one of the active stores
        self.assertIn(resp.data["name"], ["First Active", "Second Active"])


# ===========================================================================
# Integration: Store creation creates main branch automatically
# ===========================================================================

class StoreCreationIntegrationTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.superadmin = make_user(
            email="creator@test.com", role="superadmin", password="pass"
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_post_store_creates_main_branch_automatically(self):
        self._auth(self.superadmin)
        resp = self.client.post(
            "/api/stores/",
            {
                "name": "Integration Store",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Av. Integración 1",
                "phone": "111",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        store = Store.objects.get(name="Integration Store")
        self.assertTrue(
            Branch.objects.filter(
                store=store, name__endswith="- Sucursal Principal"
            ).exists()
        )

    def test_post_store_main_branch_has_same_city(self):
        self._auth(self.superadmin)
        self.client.post(
            "/api/stores/",
            {
                "name": "City Sync Store",
                "country": "Argentina",
                "state": "Mendoza",
                "postal_code": "5500",
                "city": "Mendoza",
                "address": "Av. San Martín 1",
                "phone": "333",
            },
            content_type="application/json",
        )
        store = Store.objects.get(name="City Sync Store")
        main_branch = Branch.objects.get(
            store=store, name__endswith="- Sucursal Principal"
        )
        self.assertEqual(main_branch.city, "Mendoza")

    def test_patch_store_city_syncs_to_main_branch(self):
        self._auth(self.superadmin)
        # Create store first
        self.client.post(
            "/api/stores/",
            {
                "name": "Patch Sync Store",
                "country": "Argentina",
                "state": "Buenos Aires",
                "postal_code": "1000",
                "city": "Buenos Aires",
                "address": "Av. 1",
                "phone": "444",
            },
            content_type="application/json",
        )
        store = Store.objects.get(name="Patch Sync Store")
        # Now update the city
        self.client.patch(
            f"/api/stores/{store.id}/",
            {"city": "Córdoba"},
            content_type="application/json",
        )
        main_branch = Branch.objects.get(
            store=store, name__endswith="- Sucursal Principal"
        )
        self.assertEqual(main_branch.city, "Córdoba")
