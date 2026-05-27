"""
Unit tests for the users module.

Covers:
- UserManager and User model logic
- Employee and Supplier models
- Serializer validations and create/update behavior
- IsNotClientPermission
- Authentication views: LoginView, VerifyOTPView, Enable2FAView
- UserModelViewSet, EmployeeViewSet, SupplierViewSet
- EmailExistsAPIView, VerifyIsClientAPIView
"""
import datetime
import pyotp
from unittest.mock import MagicMock

from django.test import TestCase
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework import status
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User, Employee, Supplier
from users.serializer import (
    EmployeeSerializer,
    EmployeeUpdateSerializer,
    SupplierSerializer,
    UserSerializer,
    UserWithEmployeeSerializer,
)
from users.permissions import IsNotClientPermission
from core.store.models import Store, Branch
from core.crm.models import Customer


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_user(email="test@test.com", role="employee", password="pass123", **kwargs):
    return User.objects.create_user(
        email=email,
        first_name="Test",
        last_name="User",
        role=role,
        password=password,
        **kwargs,
    )


def make_store(owner):
    return Store.objects.create(
        name="Test Store",
        country="Argentina",
        state="Buenos Aires",
        postal_code="1000",
        city="Buenos Aires",
        address="Av. Test 123",
        phone="1111111111",
        owner=owner,
    )


def make_branch(store, manager):
    return Branch.objects.create(
        store=store,
        manager=manager,
        name="Branch 1",
        country="Argentina",
        state="Buenos Aires",
        postal_code="1000",
        city="Buenos Aires",
        address="Calle Test 1",
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

class UserManagerTests(TenantTestCase):

    def test_create_user_normalizes_email(self):
        user = User.objects.create_user(
            email="TEST@EXAMPLE.COM",
            first_name="A",
            last_name="B",
            role="employee",
            password="pass",
        )
        self.assertEqual(user.email, "test@example.com")

    def test_create_user_without_email_raises(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(
                email="", first_name="A", last_name="B", role="employee", password="p"
            )

    def test_create_superuser_sets_role_and_flags(self):
        user = User.objects.create_superuser(
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            password="admin123",
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.role, "superadmin")

    def test_create_superuser_inherits_role_override(self):
        user = User.objects.create_superuser(
            email="admin2@test.com",
            first_name="A",
            last_name="B",
            password="p",
            role="superadmin",
        )
        self.assertEqual(user.role, "superadmin")


class UserModelTests(TenantTestCase):

    def setUp(self):
        self.user = make_user(email="model@test.com", role="employee")

    def test_otp_secret_auto_generated_on_save(self):
        self.assertIsNotNone(self.user.otp_secret)
        self.assertGreater(len(self.user.otp_secret), 0)

    def test_save_raises_if_2fa_enabled_without_otp_secret(self):
        user = User(
            email="bad2fa@test.com",
            first_name="Test",
            last_name="User",
            role="employee",
            is_2fa_enabled=True,
            otp_secret=None,
        )
        with self.assertRaises(ValueError):
            user.save()

    def test_get_totp_uri_contains_expected_parts(self):
        uri = self.user.get_totp_uri()
        self.assertIn("otpauth://totp/", uri)
        self.assertIn(self.user.email, uri)
        self.assertIn(self.user.otp_secret, uri)

    def test_verify_otp_correct_token_returns_true(self):
        token = pyotp.TOTP(self.user.otp_secret).now()
        self.assertTrue(self.user.verify_otp(token))

    def test_verify_otp_wrong_token_returns_false(self):
        self.assertFalse(self.user.verify_otp("000000"))

    def test_first_login_defaults_to_true(self):
        self.assertTrue(self.user.first_login)

    def test_is_2fa_enabled_defaults_to_false(self):
        self.assertFalse(self.user.is_2fa_enabled)

    def test_email_field_is_username(self):
        self.assertEqual(User.USERNAME_FIELD, "email")


class EmployeeModelTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner@test.com", role="superadmin")
        self.store = make_store(owner=self.owner)
        self.manager = make_user(email="mgr@test.com", role="manager")
        self.branch = make_branch(store=self.store, manager=self.manager)
        self.emp_user = make_user(email="emp@test.com", role="employee")
        self.employee = make_employee(
            user=self.emp_user, store=self.store, branch=self.branch
        )

    def test_str_representation(self):
        expected = (
            f"Empleado: {self.emp_user.first_name} {self.emp_user.last_name}"
            f" de {self.store.name}"
        )
        self.assertEqual(str(self.employee), expected)

    def test_employee_store_relation(self):
        self.assertEqual(self.employee.store, self.store)

    def test_employee_branch_relation(self):
        self.assertEqual(self.employee.branch, self.branch)

    def test_employee_user_relation(self):
        self.assertEqual(self.employee.user, self.emp_user)


class SupplierModelTests(TenantTestCase):

    def test_str_representation(self):
        supplier = Supplier.objects.create(name="Proveedor ABC")
        self.assertEqual(str(supplier), "Proveedor ABC")

    def test_lead_time_days_defaults_to_zero(self):
        supplier = Supplier.objects.create(name="Prov Default")
        self.assertEqual(supplier.lead_time_days, 0)

    def test_name_uniqueness_enforced(self):
        Supplier.objects.create(name="Unique Supplier")
        with self.assertRaises(Exception):
            Supplier.objects.create(name="Unique Supplier")


# ===========================================================================
# Serializer tests
# ===========================================================================

class UserSerializerTests(TenantTestCase):

    def test_valid_employee_data_passes(self):
        s = UserSerializer(
            data={
                "email": "emp@test.com",
                "first_name": "A",
                "last_name": "B",
                "role": "employee",
                "password": "pass123",
            }
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_empty_email_fails_validation(self):
        s = UserSerializer(
            data={
                "email": "",
                "first_name": "A",
                "last_name": "B",
                "role": "employee",
                "password": "pass123",
            }
        )
        self.assertFalse(s.is_valid())
        self.assertIn("email", s.errors)

    def test_invalid_role_fails_validation(self):
        s = UserSerializer(
            data={
                "email": "user@test.com",
                "first_name": "A",
                "last_name": "B",
                "role": "nonexistent_role",
                "password": "pass123",
            }
        )
        self.assertFalse(s.is_valid())
        self.assertIn("role", s.errors)

    def test_create_without_password_raises(self):
        s = UserSerializer(
            data={
                "email": "nopwd@test.com",
                "first_name": "A",
                "last_name": "B",
                "role": "employee",
            }
        )
        self.assertTrue(s.is_valid())
        with self.assertRaises(Exception):
            s.save()

    def test_create_without_role_raises(self):
        s = UserSerializer(
            data={
                "email": "norole@test.com",
                "first_name": "A",
                "last_name": "B",
                "password": "pass123",
            }
        )
        self.assertTrue(s.is_valid())
        with self.assertRaises(Exception):
            s.save()

    def test_create_client_also_creates_customer(self):
        s = UserSerializer(
            data={
                "email": "client@test.com",
                "first_name": "Client",
                "last_name": "One",
                "role": "client",
                "password": "pass123",
            }
        )
        self.assertTrue(s.is_valid(), s.errors)
        user = s.save()
        self.assertTrue(Customer.objects.filter(user=user).exists())

    def test_password_is_write_only(self):
        user = make_user(email="writeonly@test.com", role="employee")
        s = UserSerializer(user)
        self.assertNotIn("password", s.data)

    def test_partial_update_changes_first_name(self):
        user = make_user(email="update@test.com", role="employee")
        s = UserSerializer(user, data={"first_name": "Updated"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        updated = s.save()
        self.assertEqual(updated.first_name, "Updated")

    def test_update_password_hashes_correctly(self):
        user = make_user(email="pwd@test.com", role="employee")
        s = UserSerializer(user, data={"password": "newpassword123"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        user.refresh_from_db()
        self.assertTrue(user.check_password("newpassword123"))

    def test_update_role_when_provided(self):
        user = make_user(email="role_update@test.com", role="employee")
        s = UserSerializer(user, data={"role": "manager"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        updated = s.save()
        self.assertEqual(updated.role, "manager")


class EmployeeSerializerTests(TenantTestCase):

    def test_validate_dni_too_short_raises(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            EmployeeSerializer().validate_dni(123456)  # 6 digits

    def test_validate_dni_too_long_raises(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            EmployeeSerializer().validate_dni(123456789)  # 9 digits

    def test_validate_dni_valid_seven_digits(self):
        result = EmployeeSerializer().validate_dni(1234567)
        self.assertEqual(result, 1234567)

    def test_validate_dni_valid_eight_digits(self):
        result = EmployeeSerializer().validate_dni(12345678)
        self.assertEqual(result, 12345678)

    def test_validate_user_superadmin_role_raises(self):
        from rest_framework.exceptions import ValidationError
        admin = make_user(email="admin_s@test.com", role="superadmin")
        with self.assertRaises(ValidationError):
            EmployeeSerializer().validate_user(admin)

    def test_validate_user_client_role_raises(self):
        from rest_framework.exceptions import ValidationError
        client = make_user(email="client_s@test.com", role="client")
        with self.assertRaises(ValidationError):
            EmployeeSerializer().validate_user(client)

    def test_validate_user_employee_role_passes(self):
        emp = make_user(email="emp_s@test.com", role="employee")
        result = EmployeeSerializer().validate_user(emp)
        self.assertEqual(result, emp)

    def test_validate_user_manager_role_passes(self):
        mgr = make_user(email="mgr_s@test.com", role="manager")
        result = EmployeeSerializer().validate_user(mgr)
        self.assertEqual(result, mgr)


class SupplierSerializerTests(TenantTestCase):

    def test_valid_minimal_supplier(self):
        s = SupplierSerializer(data={"name": "Proveedor Test"})
        self.assertTrue(s.is_valid(), s.errors)

    def test_name_required(self):
        s = SupplierSerializer(data={})
        self.assertFalse(s.is_valid())
        self.assertIn("name", s.errors)

    def test_validate_cuit_invalid_length_raises(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            SupplierSerializer().validate_cuit("123")

    def test_validate_cuit_eleven_digits_passes(self):
        result = SupplierSerializer().validate_cuit("20123456789")
        self.assertEqual(result, "20123456789")

    def test_validate_cuit_thirteen_chars_with_dashes_passes(self):
        result = SupplierSerializer().validate_cuit("20-12345678-9")
        self.assertEqual(result, "20-12345678-9")

    def test_validate_email_invalid_format_raises(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            SupplierSerializer().validate_email("notanemail")

    def test_validate_email_valid_passes(self):
        result = SupplierSerializer().validate_email("valid@supplier.com")
        self.assertEqual(result, "valid@supplier.com")

    def test_validate_email_none_passes(self):
        result = SupplierSerializer().validate_email(None)
        self.assertIsNone(result)

    def test_id_and_timestamps_are_read_only(self):
        s = SupplierSerializer(data={"name": "Prov", "id": 999})
        self.assertTrue(s.is_valid(), s.errors)
        supplier = s.save()
        self.assertNotEqual(supplier.id, 999)


class EmployeeUpdateSerializerTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner2@test.com", role="superadmin")
        self.store = make_store(owner=self.owner)
        self.manager_user = make_user(email="mgr2@test.com", role="manager")
        self.branch = make_branch(store=self.store, manager=self.manager_user)
        self.manager_emp = make_employee(
            user=self.manager_user, store=self.store, branch=self.branch
        )

    def test_cannot_change_manager_role_when_has_assigned_branch(self):
        from rest_framework.exceptions import ValidationError
        s = EmployeeUpdateSerializer(
            self.manager_emp, data={"role": "employee"}, partial=True
        )
        self.assertTrue(s.is_valid(), s.errors)
        with self.assertRaises(ValidationError):
            s.save()

    def test_can_change_employee_role_to_manager(self):
        emp_user = make_user(email="empupdate@test.com", role="employee")
        emp = make_employee(user=emp_user, store=self.store, branch=self.branch)
        s = EmployeeUpdateSerializer(emp, data={"role": "manager"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        s.save()
        emp_user.refresh_from_db()
        self.assertEqual(emp_user.role, "manager")

    def test_update_position_without_role_change(self):
        emp_user = make_user(email="posupdate@test.com", role="employee")
        emp = make_employee(user=emp_user, store=self.store, branch=self.branch)
        s = EmployeeUpdateSerializer(emp, data={"position": "Senior Dev"}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        updated = s.save()
        self.assertEqual(updated.position, "Senior Dev")


class UserWithEmployeeSerializerTests(TenantTestCase):

    def setUp(self):
        self.owner = make_user(email="owner3@test.com", role="superadmin")
        self.store = make_store(owner=self.owner)
        self.mgr_user = make_user(email="mgr3@test.com", role="manager")
        self.branch = make_branch(store=self.store, manager=self.mgr_user)
        self.emp_user = make_user(email="emp3@test.com", role="employee")
        self.employee = make_employee(
            user=self.emp_user, store=self.store, branch=self.branch
        )

    def test_employee_info_included_for_employee(self):
        s = UserWithEmployeeSerializer(self.emp_user)
        self.assertIsNotNone(s.data["employee_info"])
        self.assertEqual(s.data["employee_info"]["id"], self.employee.id)

    def test_employee_info_includes_store_and_branch(self):
        s = UserWithEmployeeSerializer(self.emp_user)
        info = s.data["employee_info"]
        self.assertEqual(info["store_id"], self.store.id)
        self.assertEqual(info["branch_id"], self.branch.id)

    def test_employee_info_null_for_superadmin(self):
        s = UserWithEmployeeSerializer(self.owner)
        self.assertIsNone(s.data["employee_info"])

    def test_employee_info_null_when_no_employee_record(self):
        user_without_emp = make_user(email="no_emp@test.com", role="employee")
        s = UserWithEmployeeSerializer(user_without_emp)
        self.assertIsNone(s.data["employee_info"])


# ===========================================================================
# Permission tests
# ===========================================================================

class IsNotClientPermissionTests(TestCase):

    def _make_request(self, user):
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = user
        return request

    def test_unauthenticated_user_denied(self):
        from django.contrib.auth.models import AnonymousUser
        perm = IsNotClientPermission()
        self.assertFalse(perm.has_permission(self._make_request(AnonymousUser()), None))

    def test_client_role_denied(self):
        user = MagicMock()
        user.is_authenticated = True
        user.role = "client"
        perm = IsNotClientPermission()
        self.assertFalse(perm.has_permission(self._make_request(user), None))

    def test_employee_role_allowed(self):
        user = MagicMock()
        user.is_authenticated = True
        user.role = "employee"
        perm = IsNotClientPermission()
        self.assertTrue(perm.has_permission(self._make_request(user), None))

    def test_manager_role_allowed(self):
        user = MagicMock()
        user.is_authenticated = True
        user.role = "manager"
        perm = IsNotClientPermission()
        self.assertTrue(perm.has_permission(self._make_request(user), None))

    def test_superadmin_role_allowed(self):
        user = MagicMock()
        user.is_authenticated = True
        user.role = "superadmin"
        perm = IsNotClientPermission()
        self.assertTrue(perm.has_permission(self._make_request(user), None))


# ===========================================================================
# Authentication view tests
# ===========================================================================

class LoginViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user(
            email="login@test.com", role="employee", password="correctpass"
        )
        self.user.is_2fa_enabled = True
        self.user.save()

    def test_invalid_credentials_returns_401(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"email": "login@test.com", "password": "wrongpass"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.data["error"], "credentials_invalid")

    def test_valid_credentials_2fa_enabled_returns_2fa_required(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"email": "login@test.com", "password": "correctpass"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["message"], "2fa_required")
        self.assertIn("user_email", resp.data)
        self.assertIn("user_role", resp.data)

    def test_valid_credentials_2fa_not_enabled_returns_qr_code(self):
        no2fa = make_user(email="no2fa@test.com", role="employee", password="pass123")
        resp = self.client.post(
            "/api/auth/login/",
            {"email": "no2fa@test.com", "password": "pass123"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["message"], "2fa_not_enabled")
        self.assertIn("qr_code", resp.data)
        self.assertIn("otp_uri", resp.data)

    def test_client_ecommerce_login_returns_tokens(self):
        client_user = make_user(
            email="client_eco@test.com", role="client", password="pass123"
        )
        Customer.objects.create(
            user=client_user,
            customer_type=Customer.PERSON,
            first_name="Client",
            last_name="Eco",
            email="client_eco@test.com",
        )
        resp = self.client.post(
            "/api/auth/login/",
            {"email": "client_eco@test.com", "password": "pass123", "ecommerce": True},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_client_without_ecommerce_flag_returns_403(self):
        client_user = make_user(
            email="client_noeco@test.com", role="client", password="pass123"
        )
        Customer.objects.create(
            user=client_user,
            customer_type=Customer.PERSON,
            first_name="Client",
            last_name="NoEco",
            email="client_noeco@test.com",
        )
        resp = self.client.post(
            "/api/auth/login/",
            {"email": "client_noeco@test.com", "password": "pass123"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["error"], "not_authorized")


class VerifyOTPViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user(email="otp@test.com", role="employee")
        self.user.is_2fa_enabled = True
        self.user.save()

    def test_nonexistent_user_returns_404(self):
        resp = self.client.post(
            "/api/auth/verify-otp/",
            {"email": "nobody@test.com", "otp": "123456"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["error"], "user_not_found")

    def test_invalid_otp_returns_400(self):
        resp = self.client.post(
            "/api/auth/verify-otp/",
            {"email": "otp@test.com", "otp": "000000"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "otp_invalid")

    def test_valid_otp_returns_access_and_refresh_tokens(self):
        valid_otp = pyotp.TOTP(self.user.otp_secret).now()
        resp = self.client.post(
            "/api/auth/verify-otp/",
            {"email": "otp@test.com", "otp": valid_otp},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_2fa_not_enabled_and_not_first_login_returns_403(self):
        user = make_user(email="no2fa_otp@test.com", role="employee")
        user.is_2fa_enabled = False
        user.first_login = False
        user.save()
        resp = self.client.post(
            "/api/auth/verify-otp/",
            {"email": "no2fa_otp@test.com", "otp": "123456"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)


class Enable2FAViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user(email="enable2fa@test.com", role="employee")

    def test_already_enabled_returns_400(self):
        self.user.is_2fa_enabled = True
        self.user.save()
        resp = self.client.post(
            "/api/auth/enable-2fa/",
            {"email": "enable2fa@test.com", "otp": "000000"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "2fa_enabled")

    def test_valid_otp_enables_2fa_and_clears_first_login(self):
        valid_otp = pyotp.TOTP(self.user.otp_secret).now()
        resp = self.client.post(
            "/api/auth/enable-2fa/",
            {"email": "enable2fa@test.com", "otp": valid_otp},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_2fa_enabled)
        self.assertFalse(self.user.first_login)

    def test_invalid_otp_returns_400_token_invalid(self):
        resp = self.client.post(
            "/api/auth/enable-2fa/",
            {"email": "enable2fa@test.com", "otp": "000000"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "token_invalid")

    def test_nonexistent_user_returns_404(self):
        resp = self.client.post(
            "/api/auth/enable-2fa/",
            {"email": "ghost@test.com", "otp": "000000"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# UserModelViewSet tests
# ===========================================================================

class UserModelViewSetTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.superadmin = make_user(
            email="super@test.com", role="superadmin", password="admin123"
        )
        self.employee = make_user(
            email="emp_view@test.com", role="employee", password="emp123"
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_list_unauthenticated_returns_401(self):
        resp = self.client.get("/api/users/")
        self.assertEqual(resp.status_code, 401)

    def test_list_authenticated_returns_200(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/users/")
        self.assertEqual(resp.status_code, 200)

    def test_create_user_is_public(self):
        resp = self.client.post(
            "/api/users/",
            {
                "email": "newuser@test.com",
                "first_name": "New",
                "last_name": "User",
                "role": "employee",
                "password": "newpass123",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["message"], "user_created")

    def test_create_user_duplicate_email_returns_400(self):
        resp = self.client.post(
            "/api/users/",
            {
                "email": "super@test.com",
                "first_name": "Dup",
                "last_name": "User",
                "role": "employee",
                "password": "pass123",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_me_endpoint_returns_authenticated_user(self):
        self._auth(self.employee)
        resp = self.client.get("/api/users/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["email"], self.employee.email)

    def test_retrieve_user_by_id(self):
        self._auth(self.superadmin)
        resp = self.client.get(f"/api/users/{self.employee.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["email"], self.employee.email)

    def test_partial_update_user(self):
        self._auth(self.superadmin)
        resp = self.client.patch(
            f"/api/users/{self.employee.id}/",
            {"first_name": "Updated"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["message"], "user_updated")

    def test_destroy_user_deletes_record(self):
        self._auth(self.superadmin)
        target = make_user(email="todelete@test.com", role="employee")
        resp = self.client.delete(f"/api/users/{target.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(User.objects.filter(id=target.id).exists())

    def test_me_unauthenticated_returns_401(self):
        resp = self.client.get("/api/users/me/")
        self.assertEqual(resp.status_code, 401)


# ===========================================================================
# EmployeeViewSet tests
# ===========================================================================

class EmployeeViewSetTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.superadmin = make_user(
            email="sa@test.com", role="superadmin", password="pass"
        )
        self.store = make_store(owner=self.superadmin)
        self.manager_user = make_user(
            email="mgr@test.com", role="manager", password="pass"
        )
        self.branch = make_branch(store=self.store, manager=self.manager_user)
        self.manager_emp = make_employee(
            user=self.manager_user, store=self.store, branch=self.branch
        )
        self.emp_user = make_user(
            email="emp@test.com", role="employee", password="pass"
        )
        self.emp = make_employee(
            user=self.emp_user, store=self.store, branch=self.branch
        )
        self.client_user = make_user(
            email="client@test.com", role="client", password="pass"
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_client_cannot_list_employees(self):
        self._auth(self.client_user)
        resp = self.client.get("/api/employees/")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_cannot_list_employees(self):
        resp = self.client.get("/api/employees/")
        self.assertEqual(resp.status_code, 401)

    def test_superadmin_can_list_all_employees(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/employees/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data["count"], 2)

    def test_manager_can_list_branch_employees(self):
        self._auth(self.manager_user)
        resp = self.client.get("/api/employees/")
        self.assertEqual(resp.status_code, 200)
        emails = [e["user_email"] for e in resp.data["results"]]
        self.assertIn(self.emp_user.email, emails)

    def test_superadmin_can_create_employee(self):
        self._auth(self.superadmin)
        resp = self.client.post(
            "/api/employees/",
            {
                "email": "newemp@test.com",
                "first_name": "New",
                "last_name": "Employee",
                "role": "employee",
                "store": self.store.id,
                "branch": self.branch.id,
                "birth": "1995-05-15",
                "date_joined": "2023-01-01",
                "position": "Dev",
                "dni": 30000001,
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("employee", resp.data)

    def test_employee_cannot_create_other_employees(self):
        self._auth(self.emp_user)
        resp = self.client.post(
            "/api/employees/",
            {
                "email": "emp2@test.com",
                "first_name": "Emp2",
                "last_name": "User",
                "role": "employee",
                "store": self.store.id,
                "birth": "1995-01-01",
                "date_joined": "2023-01-01",
                "position": "Dev",
                "dni": 30000002,
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_employee_can_update_own_data(self):
        self._auth(self.emp_user)
        resp = self.client.patch(
            f"/api/employees/{self.emp.id}/",
            {"position": "Senior Dev"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["employee"]["position"], "Senior Dev")

    def test_employee_cannot_update_other_employees(self):
        other = make_user(email="other@test.com", role="employee")
        other_emp = make_employee(user=other, store=self.store, branch=self.branch)
        self._auth(self.emp_user)
        resp = self.client.patch(
            f"/api/employees/{other_emp.id}/",
            {"position": "Hacked"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_superadmin_can_delete_employee(self):
        self._auth(self.superadmin)
        del_user = make_user(email="del@test.com", role="employee")
        del_emp = make_employee(user=del_user, store=self.store, branch=self.branch)
        resp = self.client.delete(f"/api/employees/{del_emp.id}/")
        self.assertEqual(resp.status_code, 204)

    def test_employee_cannot_delete_employees(self):
        self._auth(self.emp_user)
        other = make_user(email="delother@test.com", role="employee")
        other_emp = make_employee(user=other, store=self.store, branch=self.branch)
        resp = self.client.delete(f"/api/employees/{other_emp.id}/")
        self.assertEqual(resp.status_code, 403)

    def test_by_branch_returns_employees_for_superadmin(self):
        self._auth(self.superadmin)
        resp = self.client.get(f"/api/employees/by_branch/?branch_id={self.branch.id}")
        self.assertEqual(resp.status_code, 200)

    def test_by_branch_missing_param_returns_400(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/employees/by_branch/")
        self.assertEqual(resp.status_code, 400)

    def test_by_branch_nonexistent_branch_returns_404(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/employees/by_branch/?branch_id=99999")
        self.assertEqual(resp.status_code, 404)

    def test_manager_cannot_see_employees_of_other_branch(self):
        other_manager = make_user(email="other_mgr@test.com", role="manager")
        other_branch = make_branch(store=self.store, manager=other_manager)
        make_employee(user=other_manager, store=self.store, branch=other_branch)
        self._auth(self.manager_user)
        resp = self.client.get(f"/api/employees/by_branch/?branch_id={other_branch.id}")
        self.assertEqual(resp.status_code, 403)


# ===========================================================================
# SupplierViewSet tests
# ===========================================================================

class SupplierViewSetTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.superadmin = make_user(
            email="sup_sa@test.com", role="superadmin", password="pass"
        )
        self.client_user = make_user(
            email="sup_cli@test.com", role="client", password="pass"
        )
        self.supplier = Supplier.objects.create(
            name="Proveedor Test", lead_time_days=5
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_client_cannot_list_suppliers(self):
        self._auth(self.client_user)
        resp = self.client.get("/api/suppliers/")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_cannot_list_suppliers(self):
        resp = self.client.get("/api/suppliers/")
        self.assertEqual(resp.status_code, 401)

    def test_authenticated_user_can_list_suppliers(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/suppliers/")
        self.assertEqual(resp.status_code, 200)

    def test_create_supplier_returns_201(self):
        self._auth(self.superadmin)
        resp = self.client.post(
            "/api/suppliers/",
            {"name": "Nuevo Proveedor S.A.", "lead_time_days": 7},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["message"], "Proveedor creado exitosamente")

    def test_create_supplier_duplicate_name_returns_400(self):
        self._auth(self.superadmin)
        resp = self.client.post(
            "/api/suppliers/",
            {"name": "Proveedor Test"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_partial_update_supplier(self):
        self._auth(self.superadmin)
        resp = self.client.patch(
            f"/api/suppliers/{self.supplier.id}/",
            {"lead_time_days": 10},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["message"], "Proveedor actualizado exitosamente")

    def test_delete_supplier_returns_204(self):
        self._auth(self.superadmin)
        to_del = Supplier.objects.create(name="Para Borrar")
        resp = self.client.delete(f"/api/suppliers/{to_del.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Supplier.objects.filter(id=to_del.id).exists())

    def test_search_by_name_returns_matching_suppliers(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/suppliers/search/?q=Proveedor")
        self.assertEqual(resp.status_code, 200)
        names = [s["name"] for s in resp.data]
        self.assertIn("Proveedor Test", names)

    def test_search_missing_q_param_returns_400(self):
        self._auth(self.superadmin)
        resp = self.client.get("/api/suppliers/search/")
        self.assertEqual(resp.status_code, 400)

    def test_retrieve_supplier_by_id(self):
        self._auth(self.superadmin)
        resp = self.client.get(f"/api/suppliers/{self.supplier.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["name"], "Proveedor Test")


# ===========================================================================
# EmailExistsAPIView tests
# ===========================================================================

class EmailExistsAPIViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.existing_user = make_user(email="existing@test.com", role="employee")

    def test_missing_email_param_returns_400(self):
        resp = self.client.get("/api/check-email/")
        self.assertEqual(resp.status_code, 400)

    def test_existing_user_email_is_not_available(self):
        resp = self.client.get("/api/check-email/?email=existing@test.com")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["available"])
        self.assertTrue(resp.data["has_user"])

    def test_new_email_is_available(self):
        resp = self.client.get("/api/check-email/?email=brandnew@test.com")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["available"])
        self.assertFalse(resp.data["has_user"])

    def test_orphan_customer_email_returns_available_with_customer_exists_flag(self):
        Customer.objects.create(
            email="orphan@test.com",
            customer_type=Customer.PERSON,
            first_name="Orphan",
            last_name="Customer",
        )
        resp = self.client.get("/api/check-email/?email=orphan@test.com")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["available"])
        self.assertTrue(resp.data["customer_exists"])


# ===========================================================================
# VerifyIsClientAPIView tests
# ===========================================================================

class VerifyIsClientAPIViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.client_user = make_user(
            email="vc_client@test.com", role="client", password="pass"
        )
        Customer.objects.create(
            user=self.client_user,
            customer_type=Customer.PERSON,
            first_name="VC",
            last_name="Client",
            email="vc_client@test.com",
        )
        self.emp_user = make_user(
            email="vc_emp@test.com", role="employee", password="pass"
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_unauthenticated_returns_401(self):
        resp = self.client.get("/api/auth/verify-client/")
        self.assertEqual(resp.status_code, 401)

    def test_client_user_is_client_true(self):
        self._auth(self.client_user)
        resp = self.client.get("/api/auth/verify-client/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["is_client"])

    def test_employee_user_is_client_false(self):
        self._auth(self.emp_user)
        resp = self.client.get("/api/auth/verify-client/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_client"])

    def test_response_includes_user_data(self):
        self._auth(self.client_user)
        resp = self.client.get("/api/auth/verify-client/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("user", resp.data)
        self.assertEqual(resp.data["user"]["email"], self.client_user.email)
