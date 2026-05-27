import json
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User
from core.crm.models import Customer
from core.crm.serializer import (
    CustomerCreateSerializer,
    CustomerUpdateSerializer,
    CustomerListSerializer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(email, role="employee", password="pass123", **kwargs):
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


def make_person(email="person@test.com", first_name="Juan", last_name="García", **kwargs):
    return Customer.objects.create(
        customer_type="person",
        email=email,
        first_name=first_name,
        last_name=last_name,
        **kwargs,
    )


def make_company(email="company@test.com", name="Empresa SA", **kwargs):
    return Customer.objects.create(
        customer_type="company",
        email=email,
        name=name,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------

class CustomerModelTests(TenantTestCase):

    def setUp(self):
        self.customer = make_person()
        self.staff_user = make_user("staff@test.com")

    def test_add_contact_appends_to_history(self):
        self.customer.add_contact("Primera llamada", medium="telefono", user=self.staff_user)
        self.assertEqual(self.customer.get_contacts_count(), 1)

    def test_add_contact_records_user_name(self):
        self.customer.add_contact("Reunión", medium="presencial", user=self.staff_user)
        entry = self.customer.contact_history[0]
        self.assertEqual(entry["user"], "Test User")
        self.assertEqual(entry["user_id"], self.staff_user.id)

    def test_add_contact_without_user_records_sistema(self):
        self.customer.add_contact("Contacto automático")
        entry = self.customer.contact_history[0]
        self.assertEqual(entry["user"], "Sistema")
        self.assertIsNone(entry["user_id"])

    def test_add_contact_returns_dict(self):
        result = self.customer.add_contact("Test", medium="email")
        self.assertIsInstance(result, dict)
        self.assertIn("date", result)
        self.assertIn("comment", result)

    def test_get_last_contact_date_returns_none_when_empty(self):
        self.assertIsNone(self.customer.get_last_contact_date())

    def test_get_last_contact_date_returns_last_entry(self):
        self.customer.add_contact("Primero")
        self.customer.add_contact("Segundo")
        date = self.customer.get_last_contact_date()
        self.assertIsNotNone(date)
        # Debe coincidir con el segundo contacto
        self.assertEqual(date, self.customer.contact_history[-1]["date"])

    def test_get_contacts_count_zero_when_empty(self):
        self.assertEqual(self.customer.get_contacts_count(), 0)

    def test_get_contacts_count_reflects_all_entries(self):
        self.customer.add_contact("Uno")
        self.customer.add_contact("Dos")
        self.customer.add_contact("Tres")
        self.assertEqual(self.customer.get_contacts_count(), 3)

    def test_str_for_person(self):
        result = str(self.customer)
        self.assertIn("Juan", result)
        self.assertIn("García", result)

    def test_str_for_company(self):
        company = make_company(email="str@test.com", name="XYZ SA")
        self.assertEqual(str(company), "XYZ SA")


# ---------------------------------------------------------------------------
# Serializer Tests
# ---------------------------------------------------------------------------

class CustomerCreateSerializerTests(TenantTestCase):

    def _person_data(self, **overrides):
        base = {
            "customer_type": "person",
            "first_name": "María",
            "last_name": "López",
            "email": "maria@test.com",
        }
        base.update(overrides)
        return base

    def _company_data(self, **overrides):
        base = {
            "customer_type": "company",
            "name": "Distribuidora SA",
            "email": "dist@test.com",
        }
        base.update(overrides)
        return base

    def test_person_requires_first_name(self):
        s = CustomerCreateSerializer(data=self._person_data(first_name=""))
        self.assertFalse(s.is_valid())

    def test_person_requires_last_name(self):
        s = CustomerCreateSerializer(data=self._person_data(last_name=""))
        self.assertFalse(s.is_valid())

    def test_person_creation_nullifies_company_fields(self):
        s = CustomerCreateSerializer(data=self._person_data(name="Empresa", cuit="30-123"))
        self.assertTrue(s.is_valid(), s.errors)
        customer = s.save()
        self.assertIsNone(customer.name)
        self.assertIsNone(customer.cuit)

    def test_company_requires_name(self):
        s = CustomerCreateSerializer(data={"customer_type": "company", "email": "no@test.com"})
        self.assertFalse(s.is_valid())

    def test_company_creation_nullifies_person_fields(self):
        s = CustomerCreateSerializer(data=self._company_data(first_name="Juan", last_name="Pérez"))
        self.assertTrue(s.is_valid(), s.errors)
        customer = s.save()
        self.assertIsNone(customer.first_name)
        self.assertIsNone(customer.last_name)

    def test_duplicate_email_raises_error(self):
        make_person(email="dup@test.com")
        s = CustomerCreateSerializer(data=self._person_data(email="dup@test.com"))
        self.assertFalse(s.is_valid())

    def test_duplicate_cuit_raises_error(self):
        make_company(email="cuit1@test.com", name="Empresa A", cuit="30-111")
        s = CustomerCreateSerializer(data=self._company_data(email="cuit2@test.com", name="Empresa B", cuit="30-111"))
        self.assertFalse(s.is_valid())

    def test_valid_person_creates_customer(self):
        s = CustomerCreateSerializer(data=self._person_data())
        self.assertTrue(s.is_valid(), s.errors)
        customer = s.save()
        self.assertIsNotNone(customer.id)
        self.assertEqual(customer.customer_type, "person")

    def test_valid_company_creates_customer(self):
        s = CustomerCreateSerializer(data=self._company_data())
        self.assertTrue(s.is_valid(), s.errors)
        customer = s.save()
        self.assertIsNotNone(customer.id)
        self.assertEqual(customer.customer_type, "company")


class CustomerUpdateSerializerTests(TenantTestCase):

    def setUp(self):
        self.customer = make_person(email="update@test.com")

    def test_same_email_passes_uniqueness_check(self):
        s = CustomerUpdateSerializer(
            instance=self.customer,
            data={"email": "update@test.com"},
            partial=True,
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_new_duplicate_email_raises_error(self):
        make_person(email="other@test.com", first_name="Otro", last_name="Cliente")
        s = CustomerUpdateSerializer(
            instance=self.customer,
            data={"email": "other@test.com"},
            partial=True,
        )
        self.assertFalse(s.is_valid())

    def test_cuit_uniqueness_excludes_self(self):
        self.customer.cuit = "30-999"
        self.customer.save()
        s = CustomerUpdateSerializer(
            instance=self.customer,
            data={"cuit": "30-999"},
            partial=True,
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_partial_update_preserves_other_fields(self):
        s = CustomerUpdateSerializer(
            instance=self.customer,
            data={"phone": "+54 11 1234-5678"},
            partial=True,
        )
        self.assertTrue(s.is_valid(), s.errors)
        customer = s.save()
        self.assertEqual(customer.first_name, "Juan")


class CustomerListSerializerTests(TenantTestCase):

    def test_full_name_for_person(self):
        customer = make_person(first_name="Ana", last_name="Torres")
        s = CustomerListSerializer(customer)
        self.assertEqual(s.data["full_name"], "Ana Torres")

    def test_full_name_for_company(self):
        company = make_company(email="cname@test.com", name="Acme Corp")
        s = CustomerListSerializer(company)
        self.assertEqual(s.data["full_name"], "Acme Corp")

    def test_display_name_fallback_sin_nombre(self):
        customer = Customer.objects.create(customer_type="company")
        s = CustomerListSerializer(customer)
        self.assertEqual(s.data["display_name"], "Sin nombre")

    def test_contacts_count_delegates_to_model(self):
        customer = make_person(email="cnt@test.com")
        customer.add_contact("Uno")
        customer.add_contact("Dos")
        s = CustomerListSerializer(customer)
        self.assertEqual(s.data["contacts_count"], 2)

    def test_last_contact_date_none_when_empty(self):
        customer = make_person(email="nocontact@test.com")
        s = CustomerListSerializer(customer)
        self.assertIsNone(s.data["last_contact_date"])

    def test_last_contact_date_matches_model_method(self):
        customer = make_person(email="wcontact@test.com")
        customer.add_contact("Contacto")
        s = CustomerListSerializer(customer)
        self.assertEqual(s.data["last_contact_date"], customer.get_last_contact_date())


# ---------------------------------------------------------------------------
# ViewSet Tests — List & Filters
# ---------------------------------------------------------------------------

class CustomerListViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("emp@test.com", role="employee")
        self._auth(self.employee)
        self.p1 = make_person(email="p1@test.com", total_spent=Decimal("1000.00"))
        self.p2 = make_person(email="p2@test.com", first_name="Carlos", last_name="Ruiz", total_spent=Decimal("0.00"))
        self.c1 = make_company(email="c1@test.com", name="Empresa Test")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get("/api/crm/customers/")
        self.assertEqual(resp.status_code, 401)

    def test_returns_200_for_employee(self):
        resp = self.client.get("/api/crm/customers/")
        self.assertEqual(resp.status_code, 200)

    def test_filter_by_type_person(self):
        resp = self.client.get("/api/crm/customers/?type=person")
        data = resp.json()
        results = data.get("results", data)
        types = [r["customer_type"] for r in results]
        self.assertTrue(all(t == "person" for t in types))

    def test_filter_by_type_company(self):
        resp = self.client.get("/api/crm/customers/?type=company")
        data = resp.json()
        results = data.get("results", data)
        types = [r["customer_type"] for r in results]
        self.assertTrue(all(t == "company" for t in types))

    def test_filter_has_purchases_true(self):
        resp = self.client.get("/api/crm/customers/?has_purchases=true")
        data = resp.json()
        results = data.get("results", data)
        emails = [r["email"] for r in results]
        self.assertIn("p1@test.com", emails)
        self.assertNotIn("p2@test.com", emails)

    def test_filter_has_purchases_false(self):
        resp = self.client.get("/api/crm/customers/?has_purchases=false")
        data = resp.json()
        results = data.get("results", data)
        emails = [r["email"] for r in results]
        self.assertIn("p2@test.com", emails)
        self.assertNotIn("p1@test.com", emails)

    def test_filter_min_spent(self):
        resp = self.client.get("/api/crm/customers/?min_spent=500")
        data = resp.json()
        results = data.get("results", data)
        emails = [r["email"] for r in results]
        self.assertIn("p1@test.com", emails)
        self.assertNotIn("p2@test.com", emails)

    def test_filter_max_spent(self):
        resp = self.client.get("/api/crm/customers/?max_spent=500")
        data = resp.json()
        results = data.get("results", data)
        emails = [r["email"] for r in results]
        self.assertIn("p2@test.com", emails)
        self.assertNotIn("p1@test.com", emails)

    def test_search_by_first_name(self):
        resp = self.client.get("/api/crm/customers/?search=Carlos")
        data = resp.json()
        results = data.get("results", data)
        emails = [r["email"] for r in results]
        self.assertIn("p2@test.com", emails)
        self.assertNotIn("p1@test.com", emails)

    def test_ordering_by_total_spent_desc(self):
        resp = self.client.get("/api/crm/customers/?ordering=-total_spent&type=person")
        data = resp.json()
        results = data.get("results", data)
        spents = [float(r["total_spent"]) for r in results]
        self.assertEqual(spents, sorted(spents, reverse=True))


# ---------------------------------------------------------------------------
# ViewSet Tests — Create
# ---------------------------------------------------------------------------

class CustomerCreateViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("creator@test.com", role="employee")
        self.client_user = make_user("client@test.com", role="client")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def _payload_person(self, email="new@test.com"):
        return {
            "customer_type": "person",
            "first_name": "Ana",
            "last_name": "López",
            "email": email,
        }

    def test_employee_can_create(self):
        self._auth(self.employee)
        resp = self.client.post(
            "/api/crm/customers/",
            data=json.dumps(self._payload_person()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_client_cannot_create(self):
        self._auth(self.client_user)
        resp = self.client.post(
            "/api/crm/customers/",
            data=json.dumps(self._payload_person("client_try@test.com")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_cannot_create(self):
        resp = self.client.post(
            "/api/crm/customers/",
            data=json.dumps(self._payload_person()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_missing_last_name_returns_400(self):
        self._auth(self.employee)
        data = {"customer_type": "person", "first_name": "Ana", "email": "nolast@test.com"}
        resp = self.client.post(
            "/api/crm/customers/",
            data=json.dumps(data),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_returns_detail_serializer(self):
        self._auth(self.employee)
        resp = self.client.post(
            "/api/crm/customers/",
            data=json.dumps(self._payload_person()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        # contact_history is only in detail serializer, not list serializer
        self.assertIn("contact_history", resp.json())

    def test_superadmin_can_create(self):
        superadmin = make_user("sadmin@test.com", role="superadmin")
        self._auth(superadmin)
        resp = self.client.post(
            "/api/crm/customers/",
            data=json.dumps(self._payload_person("sadmin_c@test.com")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_manager_can_create(self):
        manager = make_user("mgr@test.com", role="manager")
        self._auth(manager)
        resp = self.client.post(
            "/api/crm/customers/",
            data=json.dumps(self._payload_person("mgr_c@test.com")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)


# ---------------------------------------------------------------------------
# ViewSet Tests — Retrieve
# ---------------------------------------------------------------------------

class CustomerRetrieveViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user("ret@test.com")
        self.customer = make_person(email="retcust@test.com")
        self._auth(self.user)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_retrieve_returns_200(self):
        resp = self.client.get(f"/api/crm/customers/{self.customer.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], "retcust@test.com")

    def test_retrieve_includes_contact_history(self):
        resp = self.client.get(f"/api/crm/customers/{self.customer.id}/")
        self.assertIn("contact_history", resp.json())

    def test_retrieve_404_for_nonexistent(self):
        resp = self.client.get("/api/crm/customers/99999/")
        self.assertEqual(resp.status_code, 404)

    def test_retrieve_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get(f"/api/crm/customers/{self.customer.id}/")
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# ViewSet Tests — Update
# ---------------------------------------------------------------------------

class CustomerUpdateViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("upd_emp@test.com", role="employee")
        self.client_user = make_user("upd_client@test.com", role="client")
        self.customer = make_person(email="upd_cust@test.com")
        # Customer linked to client_user
        self.own_customer = make_person(
            email="own_cust@test.com",
            first_name="Propio",
            last_name="Cliente",
            user=self.client_user,
        )

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_employee_can_update(self):
        self._auth(self.employee)
        resp = self.client.patch(
            f"/api/crm/customers/{self.customer.id}/",
            data=json.dumps({"phone": "+54 11 0000-0000"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_update_returns_detail_serializer(self):
        self._auth(self.employee)
        resp = self.client.patch(
            f"/api/crm/customers/{self.customer.id}/",
            data=json.dumps({"phone": "+54 11 0000-0000"}),
            content_type="application/json",
        )
        self.assertIn("contact_history", resp.json())

    def test_client_can_update_own_record(self):
        self._auth(self.client_user)
        resp = self.client.patch(
            f"/api/crm/customers/{self.own_customer.id}/",
            data=json.dumps({"phone": "+54 11 1111-1111"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_client_cannot_update_other_record(self):
        self._auth(self.client_user)
        resp = self.client.patch(
            f"/api/crm/customers/{self.customer.id}/",
            data=json.dumps({"phone": "+54 11 9999-0000"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# ViewSet Tests — Destroy
# ---------------------------------------------------------------------------

class CustomerDestroyViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.manager = make_user("mgr_del@test.com", role="manager")
        self.employee = make_user("emp_del@test.com", role="employee")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_employee_cannot_delete(self):
        customer = make_person(email="emp_nodelete@test.com")
        self._auth(self.employee)
        resp = self.client.delete(f"/api/crm/customers/{customer.id}/")
        self.assertEqual(resp.status_code, 403)

    def test_manager_can_delete_customer_without_purchases(self):
        customer = make_person(email="del_ok@test.com")
        self._auth(self.manager)
        resp = self.client.delete(f"/api/crm/customers/{customer.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Customer.objects.filter(id=customer.id).exists())

    def test_cannot_delete_customer_with_purchases(self):
        customer = make_person(email="del_spent@test.com", total_spent=Decimal("5000.00"))
        self._auth(self.manager)
        resp = self.client.delete(f"/api/crm/customers/{customer.id}/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Customer.objects.filter(id=customer.id).exists())

    def test_delete_also_removes_linked_user(self):
        linked_user = make_user("linked_del@test.com", role="client")
        customer = make_person(email="del_linked@test.com", user=linked_user)
        self._auth(self.manager)
        self.client.delete(f"/api/crm/customers/{customer.id}/")
        self.assertFalse(User.objects.filter(id=linked_user.id).exists())

    def test_superadmin_can_delete(self):
        superadmin = make_user("sadmin_del@test.com", role="superadmin")
        customer = make_person(email="sa_del@test.com")
        self._auth(superadmin)
        resp = self.client.delete(f"/api/crm/customers/{customer.id}/")
        self.assertEqual(resp.status_code, 204)


# ---------------------------------------------------------------------------
# ViewSet Tests — Contact Actions
# ---------------------------------------------------------------------------

class CustomerContactActionTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("contact_emp@test.com", role="employee")
        self.customer = make_person(email="contact_cust@test.com")
        self._auth(self.employee)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def _url(self, action):
        return f"/api/crm/customers/{self.customer.id}/{action}/"

    def test_post_contact_returns_201(self):
        resp = self.client.post(
            self._url("contact"),
            data=json.dumps({"comment": "Primera llamada", "medium": "telefono"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_post_contact_adds_to_history(self):
        self.client.post(
            self._url("contact"),
            data=json.dumps({"comment": "Consulta email", "medium": "email"}),
            content_type="application/json",
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.get_contacts_count(), 1)
        self.assertEqual(self.customer.contact_history[0]["comment"], "Consulta email")

    def test_post_contact_response_includes_contact_added(self):
        resp = self.client.post(
            self._url("contact"),
            data=json.dumps({"comment": "Reunión"}),
            content_type="application/json",
        )
        data = resp.json()
        self.assertIn("contact_added", data)
        self.assertEqual(data["contact_added"]["comment"], "Reunión")

    def test_post_contact_records_authenticated_user(self):
        self.client.post(
            self._url("contact"),
            data=json.dumps({"comment": "Test user recording"}),
            content_type="application/json",
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.contact_history[0]["user_id"], self.employee.id)

    def test_get_contact_history_returns_200(self):
        self.customer.add_contact("Historial 1")
        resp = self.client.get(self._url("contact_history"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["customer_id"], self.customer.id)
        self.assertEqual(data["total_contacts"], 1)

    def test_get_contact_history_empty_returns_empty_array(self):
        resp = self.client.get(self._url("contact_history"))
        data = resp.json()
        self.assertEqual(data["contact_history"], [])
        self.assertEqual(data["total_contacts"], 0)
        self.assertIsNone(data["last_contact_date"])

    def test_patch_update_contact_modifies_comment(self):
        self.customer.add_contact("Comentario original")
        resp = self.client.patch(
            self._url("update_contact"),
            data=json.dumps({"contact_index": 0, "comment": "Comentario corregido"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.contact_history[0]["comment"], "Comentario corregido")

    def test_patch_update_contact_adds_edited_fields(self):
        self.customer.add_contact("Original")
        self.client.patch(
            self._url("update_contact"),
            data=json.dumps({"contact_index": 0, "comment": "Editado"}),
            content_type="application/json",
        )
        self.customer.refresh_from_db()
        entry = self.customer.contact_history[0]
        self.assertIn("edited_date", entry)
        self.assertIn("edited_by", entry)

    def test_patch_update_contact_invalid_index_returns_400(self):
        resp = self.client.patch(
            self._url("update_contact"),
            data=json.dumps({"contact_index": 99, "comment": "X"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_delete_contact_removes_entry(self):
        self.customer.add_contact("Uno")
        self.customer.add_contact("Dos")
        resp = self.client.delete(
            self._url("delete_contact"),
            data=json.dumps({"contact_index": 0}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.get_contacts_count(), 1)
        self.assertEqual(self.customer.contact_history[0]["comment"], "Dos")

    def test_delete_contact_response_includes_deleted_contact(self):
        self.customer.add_contact("A eliminar")
        resp = self.client.delete(
            self._url("delete_contact"),
            data=json.dumps({"contact_index": 0}),
            content_type="application/json",
        )
        data = resp.json()
        self.assertIn("deleted_contact", data)
        self.assertEqual(data["deleted_contact"]["comment"], "A eliminar")

    def test_delete_contact_without_index_returns_400(self):
        resp = self.client.delete(
            self._url("delete_contact"),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_delete_contact_invalid_index_returns_400(self):
        resp = self.client.delete(
            self._url("delete_contact"),
            data=json.dumps({"contact_index": 99}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# ViewSet Tests — Stats
# ---------------------------------------------------------------------------

class CustomerStatsViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("stats@test.com", role="employee")
        self._auth(self.employee)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_stats_returns_200(self):
        resp = self.client.get("/api/crm/customers/stats/")
        self.assertEqual(resp.status_code, 200)

    def test_stats_total_customers_is_accurate(self):
        make_person(email="s1@test.com")
        make_person(email="s2@test.com")
        make_company(email="s3@test.com", name="Corp Stats")
        resp = self.client.get("/api/crm/customers/stats/")
        data = resp.json()
        self.assertEqual(data["total_customers"], 3)

    def test_stats_separates_persons_and_companies(self):
        make_person(email="sp1@test.com")
        make_company(email="sc1@test.com", name="Stat Corp")
        resp = self.client.get("/api/crm/customers/stats/")
        data = resp.json()
        self.assertEqual(data["total_persons"], 1)
        self.assertEqual(data["total_companies"], 1)

    def test_stats_counts_customers_with_purchases(self):
        make_person(email="bought@test.com", total_spent=Decimal("500.00"))
        make_person(email="notbought@test.com", total_spent=Decimal("0.00"))
        resp = self.client.get("/api/crm/customers/stats/")
        data = resp.json()
        self.assertEqual(data["customers_with_purchases"], 1)
        self.assertEqual(data["customers_without_purchases"], 1)

    def test_stats_total_revenue_sums_all_spent(self):
        make_person(email="rev1@test.com", total_spent=Decimal("1000.00"))
        make_person(email="rev2@test.com", total_spent=Decimal("500.00"))
        resp = self.client.get("/api/crm/customers/stats/")
        data = resp.json()
        self.assertEqual(float(data["total_revenue"]), 1500.0)

    def test_stats_recent_customers_counts_last_30_days(self):
        make_person(email="recent@test.com")
        resp = self.client.get("/api/crm/customers/stats/")
        data = resp.json()
        self.assertGreaterEqual(data["recent_customers"], 1)

    def test_stats_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get("/api/crm/customers/stats/")
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# ViewSet Tests — Search
# ---------------------------------------------------------------------------

class CustomerSearchViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("search@test.com", role="employee")
        self._auth(self.employee)
        make_person(email="pedro@test.com", first_name="Pedro", last_name="Sánchez", country="Argentina")
        make_person(email="ana@test.com", first_name="Ana", last_name="Martínez", country="Chile")
        make_company(email="xyz@test.com", name="XYZ Corp", country="Argentina")

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_without_q_returns_400(self):
        resp = self.client.get("/api/crm/customers/search/")
        self.assertEqual(resp.status_code, 400)

    def test_search_by_first_name(self):
        resp = self.client.get("/api/crm/customers/search/?q=Pedro")
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["email"], "pedro@test.com")

    def test_search_by_email(self):
        resp = self.client.get("/api/crm/customers/search/?q=xyz@test.com")
        data = resp.json()
        self.assertEqual(data["count"], 1)

    def test_search_by_company_name(self):
        resp = self.client.get("/api/crm/customers/search/?q=XYZ")
        data = resp.json()
        emails = [r["email"] for r in data["results"]]
        self.assertIn("xyz@test.com", emails)

    def test_search_filter_by_type(self):
        resp = self.client.get("/api/crm/customers/search/?q=test.com&type=company")
        data = resp.json()
        types = [r["customer_type"] for r in data["results"]]
        self.assertTrue(all(t == "company" for t in types))

    def test_search_filter_by_country(self):
        resp = self.client.get("/api/crm/customers/search/?q=test.com&country=Argentina")
        data = resp.json()
        results = data["results"]
        emails = [r["email"] for r in results]
        self.assertIn("pedro@test.com", emails)
        self.assertNotIn("ana@test.com", emails)

    def test_search_limited_to_20_results(self):
        for i in range(25):
            make_person(email=f"bulk{i}@test.com", first_name="Bulk", last_name=f"User{i}")
        resp = self.client.get("/api/crm/customers/search/?q=bulk")
        data = resp.json()
        self.assertLessEqual(len(data["results"]), 20)

    def test_search_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.get("/api/crm/customers/search/?q=test")
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# ViewSet Tests — Update Purchase Info
# ---------------------------------------------------------------------------

class CustomerUpdatePurchaseInfoViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.employee = make_user("purc_emp@test.com", role="employee")
        self.customer = make_person(email="purc_cust@test.com")
        self._auth(self.employee)

    def _auth(self, user):
        self.client.defaults["HTTP_AUTHORIZATION"] = auth_header(user)

    def test_update_purchase_info_returns_200(self):
        resp = self.client.patch(
            f"/api/crm/customers/{self.customer.id}/update_purchase_info/",
            data=json.dumps({"total_spent": "25000.00"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_update_purchase_info_persists_total_spent(self):
        self.client.patch(
            f"/api/crm/customers/{self.customer.id}/update_purchase_info/",
            data=json.dumps({"total_spent": "12500.00"}),
            content_type="application/json",
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.total_spent, Decimal("12500.00"))

    def test_update_purchase_info_persists_last_purchase_date(self):
        self.client.patch(
            f"/api/crm/customers/{self.customer.id}/update_purchase_info/",
            data=json.dumps({"last_purchase_date": "2026-05-21T15:00:00Z"}),
            content_type="application/json",
        )
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.last_purchase_date)

    def test_update_purchase_info_no_valid_fields_returns_400(self):
        resp = self.client.patch(
            f"/api/crm/customers/{self.customer.id}/update_purchase_info/",
            data=json.dumps({"email": "hack@test.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_purchase_info_requires_auth(self):
        del self.client.defaults["HTTP_AUTHORIZATION"]
        resp = self.client.patch(
            f"/api/crm/customers/{self.customer.id}/update_purchase_info/",
            data=json.dumps({"total_spent": "100.00"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)
