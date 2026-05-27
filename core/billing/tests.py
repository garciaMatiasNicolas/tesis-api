import datetime
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User, Employee, Supplier
from core.billing.models import SalesOrder, PurchaseOrder, SalesItem, PurchaseItem
from core.crm.models import Customer
from core.stock.models import Product, Category, Subcategory, Stock, StockMovement, Warehouse
from core.store.models import Store, Branch

SALES_URL = '/api/billing/sales-orders/'
PURCHASE_URL = '/api/billing/purchase-orders/'
STATS_URL = '/api/billing/stats/'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(email, role='manager', password='pass123', **kwargs):
    return User.objects.create_user(
        email=email, first_name='Test', last_name='User',
        role=role, password=password, **kwargs,
    )


def auth_header(user):
    return f"Bearer {RefreshToken.for_user(user).access_token}"


def make_store(suffix=''):
    owner = make_user(f'owner{suffix}@test.com', role='superadmin')
    store = Store.objects.create(name=f'Test Store{suffix}', owner=owner)
    branch = Branch.objects.create(
        store=store, name=f'Test Store{suffix} - Sucursal Principal',
        manager=owner, country='AR', state='BA', city='CABA',
        address='Calle 1', postal_code='1000',
    )
    return store, branch, owner


def make_category():
    return Category.objects.create(name='Cat')


def make_subcategory(category):
    return Subcategory.objects.create(name='Sub', category=category)


def make_supplier():
    return Supplier.objects.create(name='Supplier', email='sup@test.com', cuit='20123456781')


def make_product(category, subcategory, sku='SKU001', price=100, cost=50, safety_stock=10):
    return Product.objects.create(
        description='Product', sku=sku,
        sale_price=price, cost_price=cost,
        category=category, subcategory=subcategory,
        safety_stock=safety_stock, status='active',
    )


def make_customer(email='cust@test.com', user=None):
    return Customer.objects.create(
        customer_type='person', first_name='John', last_name='Doe',
        email=email, user=user,
    )


def set_stock(product, branch=None, warehouse=None, quantity=100):
    stock, created = Stock.objects.get_or_create(
        product=product, branch=branch, warehouse=warehouse,
        defaults={'quantity': quantity},
    )
    if not created:
        stock.quantity = quantity
        stock.save()
    return stock


def make_sales_order(customer, branch, product, quantity=1, status='draft'):
    """Direct DB create, bypassing serializer validation."""
    order = SalesOrder.objects.create(
        customer=customer,
        branch_origin=branch,
        status=status,
        payment_method='cash',
        total_price=Decimal(str(product.sale_price)) * quantity,
    )
    SalesItem.objects.create(
        sales_order=order, product=product,
        quantity=quantity, unit_price=product.sale_price,
    )
    return order


def make_purchase_order(supplier, branch, product, quantity=2, status='draft'):
    """Direct DB create, bypassing serializer validation."""
    order = PurchaseOrder.objects.create(
        supplier=supplier,
        branch_destination=branch,
        status=status,
        payment_method='transfer',
        delivery_date=datetime.date.today() + datetime.timedelta(days=7),
        total_price=Decimal(str(product.cost_price)) * quantity,
        comments=[],
    )
    PurchaseItem.objects.create(
        purchase_order=order, product=product,
        quantity=quantity, unit_price=product.cost_price,
    )
    return order


# ---------------------------------------------------------------------------
# SalesOrder – LIST
# ---------------------------------------------------------------------------

class SalesOrderListViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.customer = make_customer()

    def test_list_returns_200(self):
        resp = self.client.get(SALES_URL)
        self.assertEqual(resp.status_code, 200)

    def test_list_unauthenticated_returns_401(self):
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        resp = self.client.get(SALES_URL)
        self.assertEqual(resp.status_code, 401)

    def test_list_shows_all_orders(self):
        make_sales_order(self.customer, self.branch, self.product)
        make_sales_order(self.customer, self.branch, self.product)
        resp = self.client.get(SALES_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data), 2)

    def test_filter_by_was_delivered(self):
        o1 = make_sales_order(self.customer, self.branch, self.product)
        o1.was_delivered = True
        o1.save()
        make_sales_order(self.customer, self.branch, self.product)

        resp = self.client.get(SALES_URL + '?was_delivered=true')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data]
        self.assertIn(o1.id, ids)

    def test_filter_by_sales_channel(self):
        o1 = make_sales_order(self.customer, self.branch, self.product)
        o1.sales_channel = 'wholesale'
        o1.save()

        resp = self.client.get(SALES_URL + '?sales_channel=wholesale')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data]
        self.assertIn(o1.id, ids)

    def test_filter_by_customer_id(self):
        cust2 = make_customer('other@test.com')
        make_sales_order(self.customer, self.branch, self.product)
        o2 = make_sales_order(cust2, self.branch, self.product)

        resp = self.client.get(SALES_URL + f'?customer_id={cust2.id}')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data]
        self.assertIn(o2.id, ids)
        for o in resp.data:
            self.assertEqual(o['customer']['id'], cust2.id)


# ---------------------------------------------------------------------------
# SalesOrder – CREATE
# ---------------------------------------------------------------------------

class SalesOrderCreateViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.customer = make_customer()
        set_stock(self.product, branch=self.branch, quantity=50)

    def _payload(self, **overrides):
        data = {
            'customer_id': self.customer.id,
            'payment_method': 'cash',
            'branch_origin_id': self.branch.id,
            'sales_items': [
                {'product': self.product.id, 'quantity': 1, 'unit_price': '100.00'},
            ],
        }
        data.update(overrides)
        return data

    def test_create_returns_201(self):
        resp = self.client.post(SALES_URL, self._payload(), content_type='application/json')
        self.assertEqual(resp.status_code, 201)

    def test_create_forces_draft_status(self):
        payload = self._payload()
        payload['status'] = 'pending'
        resp = self.client.post(SALES_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], 'draft')

    def test_create_forces_was_payed_false(self):
        payload = self._payload()
        payload['was_payed'] = True
        resp = self.client.post(SALES_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.data['was_payed'])

    def test_create_forces_was_delivered_false(self):
        payload = self._payload()
        payload['was_delivered'] = True
        resp = self.client.post(SALES_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.data['was_delivered'])

    def test_create_requires_sales_items(self):
        payload = self._payload()
        payload['sales_items'] = []
        resp = self.client.post(SALES_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_create_unauthenticated_returns_401(self):
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        resp = self.client.post(SALES_URL, self._payload(), content_type='application/json')
        self.assertEqual(resp.status_code, 401)

    def test_create_updates_customer_last_purchase_date(self):
        resp = self.client.post(SALES_URL, self._payload(), content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.last_purchase_date)

    def test_create_both_origins_returns_400(self):
        store2, wh_branch, _ = make_store('2')
        wh = Warehouse.objects.create(name='WH1', branch=wh_branch)
        payload = self._payload()
        payload['warehouse_origin_id'] = wh.id
        resp = self.client.post(SALES_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_create_with_delivery_requires_deliver_to(self):
        payload = self._payload()
        payload['delivery'] = True
        payload['shipping_cost'] = '500.00'
        resp = self.client.post(SALES_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_create_with_delivery_requires_shipping_cost(self):
        payload = self._payload()
        payload['delivery'] = True
        payload['deliver_to'] = 'Calle Falsa 123'
        resp = self.client.post(SALES_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_create_insufficient_stock_returns_400(self):
        set_stock(self.product, branch=self.branch, quantity=0)
        payload = self._payload()
        payload['sales_items'] = [
            {'product': self.product.id, 'quantity': 10, 'unit_price': '100.00'},
        ]
        resp = self.client.post(SALES_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# SalesOrder – RETRIEVE / UPDATE
# ---------------------------------------------------------------------------

class SalesOrderRetrieveUpdateViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.customer = make_customer()
        set_stock(self.product, branch=self.branch, quantity=100)
        self.order = make_sales_order(self.customer, self.branch, self.product)

    def test_retrieve_returns_200(self):
        resp = self.client.get(f'{SALES_URL}{self.order.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['id'], self.order.id)

    def test_retrieve_nonexistent_returns_404(self):
        resp = self.client.get(f'{SALES_URL}99999/')
        self.assertEqual(resp.status_code, 404)

    def test_patch_description(self):
        resp = self.client.patch(
            f'{SALES_URL}{self.order.id}/',
            {'description': 'Updated'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.description, 'Updated')


# ---------------------------------------------------------------------------
# SalesOrder – STATE MACHINE
# ---------------------------------------------------------------------------

class SalesOrderStateMachineTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.customer = make_customer()
        set_stock(self.product, branch=self.branch, quantity=100)

    def _new_order(self):
        return make_sales_order(self.customer, self.branch, self.product)

    # draft → pending
    def test_draft_to_pending_creates_stock_movement(self):
        order = self._new_order()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'pending', 'branch_origin_id': self.branch.id},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(order.stock_movements.filter(status='TRAN', movement_type='OUT').exists())

    def test_draft_to_pending_without_origin_returns_400(self):
        order = SalesOrder.objects.create(
            customer=self.customer, status='draft',
            payment_method='cash', total_price=100,
        )
        SalesItem.objects.create(
            sales_order=order, product=self.product,
            quantity=1, unit_price=100,
        )
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'pending'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_transition_draft_to_processing_returns_400(self):
        order = self._new_order()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'processing'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # pending → processing
    def test_pending_to_processing(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'processing'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'processing')

    # was_payed only in processing
    def test_was_payed_only_allowed_in_processing(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'was_payed': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_was_payed_allowed_in_processing(self):
        order = self._new_order()
        order.status = 'processing'
        order.save()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'processing', 'was_payed': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    # was_delivered requires was_payed
    def test_was_delivered_without_was_payed_returns_400(self):
        order = self._new_order()
        order.status = 'processing'
        order.save()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'processing', 'was_delivered': True, 'was_payed': False},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # processing → completed
    def test_processing_to_completed_requires_payed_and_delivered(self):
        order = self._new_order()
        order.status = 'processing'
        order.save()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'completed'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_processing_to_completed_completes_stock_movements(self):
        order = self._new_order()
        order.status = 'processing'
        order.save()
        StockMovement.objects.create(
            product=self.product, branch=self.branch,
            status='TRAN', movement_type='OUT',
            from_location='BRA', to_location='SAL',
            quantity=1, sale=order,
        )
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'completed', 'was_payed': True, 'was_delivered': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(order.stock_movements.filter(status='REC').exists())

    def test_completed_updates_customer_total_spent(self):
        order = self._new_order()
        order.status = 'processing'
        order.total_price = Decimal('200.00')
        order.save()
        before = self.customer.total_spent
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'completed', 'was_payed': True, 'was_delivered': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.total_spent, before + Decimal('200.00'))

    # cancellation
    def test_cancel_from_draft(self):
        order = self._new_order()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'cancelled'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')

    def test_cancel_from_pending_cancels_stock_movements(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        mv = StockMovement.objects.create(
            product=self.product, branch=self.branch,
            status='TRAN', movement_type='OUT',
            from_location='BRA', to_location='SAL',
            quantity=1, sale=order,
        )
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'cancelled'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        mv.refresh_from_db()
        self.assertEqual(mv.status, 'CAN')

    # terminal states
    def test_completed_is_terminal(self):
        order = self._new_order()
        order.status = 'completed'
        order.was_payed = True
        order.was_delivered = True
        order.save()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'cancelled'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_cancelled_is_terminal(self):
        order = self._new_order()
        order.status = 'cancelled'
        order.save()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'draft'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_transition_pending_to_draft_returns_400(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        resp = self.client.patch(
            f'{SALES_URL}{order.id}/',
            {'status': 'draft'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# SalesOrder – DESTROY
# ---------------------------------------------------------------------------

class SalesOrderDestroyViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.customer = make_customer()

    def test_delete_returns_204(self):
        order = make_sales_order(self.customer, self.branch, self.product)
        resp = self.client.delete(f'{SALES_URL}{order.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(SalesOrder.objects.filter(id=order.id).exists())

    def test_delete_adjusts_total_spent_if_payed(self):
        order = make_sales_order(self.customer, self.branch, self.product)
        order.was_payed = True
        order.total_price = Decimal('300.00')
        order.save()
        self.customer.total_spent = Decimal('300.00')
        self.customer.save()

        resp = self.client.delete(f'{SALES_URL}{order.id}/')
        self.assertEqual(resp.status_code, 204)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.total_spent, Decimal('0.00'))

    def test_delete_unauthenticated_returns_401(self):
        order = make_sales_order(self.customer, self.branch, self.product)
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        resp = self.client.delete(f'{SALES_URL}{order.id}/')
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# SalesOrder – MY-ORDERS
# ---------------------------------------------------------------------------

class SalesOrderMyOrdersTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.client_user = make_user('client@test.com', role='client')
        self.customer = make_customer('client@test.com', user=self.client_user)
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.client_user)

    def test_my_orders_returns_own_orders_only(self):
        order = make_sales_order(self.customer, self.branch, self.product)
        other_customer = make_customer('other@test.com')
        make_sales_order(other_customer, self.branch, self.product)

        resp = self.client.get(f'{SALES_URL}my-orders/')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data]
        self.assertIn(order.id, ids)
        self.assertEqual(len(ids), 1)

    def test_my_orders_no_customer_returns_404(self):
        user_no_customer = make_user('nocust@test.com', role='client')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(user_no_customer)
        resp = self.client.get(f'{SALES_URL}my-orders/')
        self.assertEqual(resp.status_code, 404)

    def test_my_orders_unauthenticated_returns_401(self):
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        resp = self.client.get(f'{SALES_URL}my-orders/')
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# PurchaseOrder – LIST
# ---------------------------------------------------------------------------

class PurchaseOrderListViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.supplier = make_supplier()

    def test_list_returns_200(self):
        resp = self.client.get(PURCHASE_URL)
        self.assertEqual(resp.status_code, 200)

    def test_list_unauthenticated_returns_401(self):
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        resp = self.client.get(PURCHASE_URL)
        self.assertEqual(resp.status_code, 401)

    def test_filter_by_status(self):
        order = make_purchase_order(self.supplier, self.branch, self.product)
        order.status = 'pending'
        order.save()
        make_purchase_order(self.supplier, self.branch, self.product)

        resp = self.client.get(PURCHASE_URL + '?status=pending')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data]
        self.assertIn(order.id, ids)

    def test_filter_by_supplier_id(self):
        sup2 = Supplier.objects.create(name='Sup2', email='s2@test.com', cuit='20999999991')
        make_purchase_order(self.supplier, self.branch, self.product)
        o2 = make_purchase_order(sup2, self.branch, self.product)

        resp = self.client.get(PURCHASE_URL + f'?supplier_id={sup2.id}')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data]
        self.assertIn(o2.id, ids)

    def test_filter_by_was_payed(self):
        order = make_purchase_order(self.supplier, self.branch, self.product)
        order.was_payed = True
        order.save()
        make_purchase_order(self.supplier, self.branch, self.product)

        resp = self.client.get(PURCHASE_URL + '?was_payed=true')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data]
        self.assertIn(order.id, ids)

    def test_filter_by_received(self):
        order = make_purchase_order(self.supplier, self.branch, self.product)
        order.received = True
        order.save()

        resp = self.client.get(PURCHASE_URL + '?received=true')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data]
        self.assertIn(order.id, ids)


# ---------------------------------------------------------------------------
# PurchaseOrder – CREATE
# ---------------------------------------------------------------------------

class PurchaseOrderCreateViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.supplier = make_supplier()

    def _payload(self, **overrides):
        data = {
            'supplier': self.supplier.id,
            'payment_method': 'transfer',
            'delivery_date': str(datetime.date.today() + datetime.timedelta(days=7)),
            'branch_destination_id': self.branch.id,
            'items': [
                {'product': self.product.id, 'quantity': 5, 'unit_price': '50.00'},
            ],
        }
        data.update(overrides)
        return data

    def test_create_returns_201(self):
        resp = self.client.post(PURCHASE_URL, self._payload(), content_type='application/json')
        self.assertEqual(resp.status_code, 201)

    def test_create_forces_draft_status(self):
        payload = self._payload()
        payload['status'] = 'pending'
        resp = self.client.post(PURCHASE_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], 'draft')

    def test_create_forces_was_payed_false(self):
        payload = self._payload()
        payload['was_payed'] = True
        resp = self.client.post(PURCHASE_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.data['was_payed'])

    def test_create_adds_comment_to_audit_trail(self):
        resp = self.client.post(PURCHASE_URL, self._payload(), content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        order = PurchaseOrder.objects.get(id=resp.data['id'])
        self.assertIsNotNone(order.comments)
        self.assertGreater(len(order.comments), 0)

    def test_create_assigns_created_by_for_manager(self):
        resp = self.client.post(PURCHASE_URL, self._payload(), content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        order = PurchaseOrder.objects.get(id=resp.data['id'])
        self.assertEqual(order.created_by, self.user)

    def test_create_requires_items(self):
        payload = self._payload()
        payload['items'] = []
        resp = self.client.post(PURCHASE_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_create_unauthenticated_returns_401(self):
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        resp = self.client.post(PURCHASE_URL, self._payload(), content_type='application/json')
        self.assertEqual(resp.status_code, 401)

    def test_create_both_destinations_returns_400(self):
        store2, wh_branch, _ = make_store('2')
        wh = Warehouse.objects.create(name='WH', branch=wh_branch)
        payload = self._payload()
        payload['warehouse_destination_id'] = wh.id
        resp = self.client.post(PURCHASE_URL, payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# PurchaseOrder – RETRIEVE / UPDATE
# ---------------------------------------------------------------------------

class PurchaseOrderRetrieveUpdateViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.supplier = make_supplier()
        self.order = make_purchase_order(self.supplier, self.branch, self.product)

    def test_retrieve_returns_200(self):
        resp = self.client.get(f'{PURCHASE_URL}{self.order.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['id'], self.order.id)

    def test_retrieve_nonexistent_returns_404(self):
        resp = self.client.get(f'{PURCHASE_URL}99999/')
        self.assertEqual(resp.status_code, 404)

    def test_patch_description_appends_audit_comment(self):
        resp = self.client.patch(
            f'{PURCHASE_URL}{self.order.id}/',
            {'description': 'Updated description'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertGreater(len(self.order.comments), 0)


# ---------------------------------------------------------------------------
# PurchaseOrder – STATE MACHINE
# ---------------------------------------------------------------------------

class PurchaseOrderStateMachineTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.supplier = make_supplier()
        set_stock(self.product, branch=self.branch, quantity=0)

    def _new_order(self):
        return make_purchase_order(self.supplier, self.branch, self.product, quantity=5)

    # draft → pending
    def test_draft_to_pending_creates_stock_movement(self):
        order = self._new_order()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'pending', 'branch_destination_id': self.branch.id},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(order.stock_movements.filter(status='TRAN', movement_type='IN').exists())

    def test_draft_to_pending_without_destination_returns_400(self):
        order = PurchaseOrder.objects.create(
            supplier=self.supplier, status='draft',
            payment_method='cash',
            delivery_date=datetime.date.today() + datetime.timedelta(days=7),
            total_price=100, comments=[],
        )
        PurchaseItem.objects.create(
            purchase_order=order, product=self.product,
            quantity=2, unit_price=50,
        )
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'pending'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_transition_draft_to_completed_returns_400(self):
        order = self._new_order()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'completed'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # was_payed only in pending
    def test_was_payed_only_allowed_in_pending(self):
        order = self._new_order()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'was_payed': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_was_payed_allowed_in_pending(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'was_payed': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    # received requires was_payed
    def test_received_without_was_payed_returns_400(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'received': True, 'was_payed': False},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # pending → completed
    def test_pending_to_completed_requires_payed_and_received(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'completed'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_pending_to_completed_updates_stock(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        stock_before = Stock.objects.filter(
            product=self.product, branch=self.branch, warehouse=None,
        ).first()
        qty_before = stock_before.quantity if stock_before else Decimal('0')

        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'completed', 'was_payed': True, 'received': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

        stock_after = Stock.objects.filter(
            product=self.product, branch=self.branch, warehouse=None,
        ).first()
        qty_after = stock_after.quantity if stock_after else Decimal('0')
        self.assertGreater(qty_after, qty_before)

    def test_pending_to_completed_marks_movements_rec(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        StockMovement.objects.create(
            product=self.product, branch=self.branch,
            status='TRAN', movement_type='IN',
            from_location='PUR', to_location='BRA',
            quantity=5, purchase=order,
        )
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'completed', 'was_payed': True, 'received': True},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(order.stock_movements.filter(status='REC').exists())

    # cancellation
    def test_cancel_from_draft(self):
        order = self._new_order()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'cancelled'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')

    def test_cancel_from_pending_cancels_movements(self):
        order = self._new_order()
        order.status = 'pending'
        order.save()
        mv = StockMovement.objects.create(
            product=self.product, branch=self.branch,
            status='TRAN', movement_type='IN',
            from_location='PUR', to_location='BRA',
            quantity=5, purchase=order,
        )
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'cancelled'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        mv.refresh_from_db()
        self.assertEqual(mv.status, 'CAN')

    # terminal states
    def test_completed_is_terminal(self):
        order = self._new_order()
        order.status = 'completed'
        order.was_payed = True
        order.received = True
        order.save()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'cancelled'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_cancelled_is_terminal(self):
        order = self._new_order()
        order.status = 'cancelled'
        order.save()
        resp = self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'status': 'draft'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # audit trail on every update
    def test_update_appends_comment(self):
        order = self._new_order()
        initial_count = len(order.comments or [])
        self.client.patch(
            f'{PURCHASE_URL}{order.id}/',
            {'description': 'Test update', 'comment': 'User note'},
            content_type='application/json',
        )
        order.refresh_from_db()
        self.assertGreater(len(order.comments), initial_count)


# ---------------------------------------------------------------------------
# PurchaseOrder – DESTROY
# ---------------------------------------------------------------------------

class PurchaseOrderDestroyViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)
        store, self.branch, _ = make_store()
        cat = make_category()
        sub = make_subcategory(cat)
        self.product = make_product(cat, sub)
        self.supplier = make_supplier()

    def test_delete_returns_204(self):
        order = make_purchase_order(self.supplier, self.branch, self.product)
        resp = self.client.delete(f'{PURCHASE_URL}{order.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(PurchaseOrder.objects.filter(id=order.id).exists())

    def test_delete_unauthenticated_returns_401(self):
        order = make_purchase_order(self.supplier, self.branch, self.product)
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        resp = self.client.delete(f'{PURCHASE_URL}{order.id}/')
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# Billing Stats
# ---------------------------------------------------------------------------

class BillingStatsViewTests(TenantTestCase):

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.user = make_user('mgr@test.com')
        self.client.defaults['HTTP_AUTHORIZATION'] = auth_header(self.user)

    def test_stats_overview_returns_200(self):
        resp = self.client.get(f'{STATS_URL}overview/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('total_sales', resp.data)
        self.assertIn('total_orders', resp.data)
        self.assertIn('total_purchases', resp.data)
        self.assertIn('inventory_value', resp.data)

    def test_stats_overview_unauthenticated_returns_401(self):
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        resp = self.client.get(f'{STATS_URL}overview/')
        self.assertEqual(resp.status_code, 401)

    def test_sales_chart_returns_200(self):
        resp = self.client.get(f'{STATS_URL}sales-chart/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_sales_chart_with_period_month(self):
        resp = self.client.get(f'{STATS_URL}sales-chart/?period=month')
        self.assertEqual(resp.status_code, 200)

    def test_sales_chart_with_period_day(self):
        resp = self.client.get(f'{STATS_URL}sales-chart/?period=day')
        self.assertEqual(resp.status_code, 200)

    def test_top_products_returns_200(self):
        resp = self.client.get(f'{STATS_URL}top-products/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_stock_alerts_returns_200(self):
        resp = self.client.get(f'{STATS_URL}stock-alerts/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_stock_alerts_shows_low_stock_products(self):
        store, branch, _ = make_store('stats')
        cat = make_category()
        sub = make_subcategory(cat)
        product = make_product(cat, sub, sku='LOW001', safety_stock=20)
        set_stock(product, branch=branch, quantity=3)

        resp = self.client.get(f'{STATS_URL}stock-alerts/')
        self.assertEqual(resp.status_code, 200)
        skus = [item['sku'] for item in resp.data]
        self.assertIn('LOW001', skus)

    def test_sales_by_channel_returns_200(self):
        resp = self.client.get(f'{STATS_URL}sales-by-channel/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_order_status_returns_200(self):
        resp = self.client.get(f'{STATS_URL}order-status/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_filter_options_returns_200(self):
        resp = self.client.get(f'{STATS_URL}filter-options/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('categories', resp.data)
        self.assertIn('subcategories', resp.data)
        self.assertIn('products', resp.data)
        self.assertIn('suppliers', resp.data)

    def test_all_stat_endpoints_require_auth(self):
        self.client.defaults.pop('HTTP_AUTHORIZATION', None)
        endpoints = [
            'sales-chart/', 'top-products/', 'stock-alerts/',
            'sales-by-channel/', 'order-status/', 'filter-options/',
        ]
        for endpoint in endpoints:
            resp = self.client.get(f'{STATS_URL}{endpoint}')
            self.assertEqual(resp.status_code, 401, msg=f'{endpoint} should require auth')

    def test_stats_overview_with_date_range(self):
        resp = self.client.get(
            f'{STATS_URL}overview/?date_from=2025-01-01&date_to=2025-12-31'
        )
        self.assertEqual(resp.status_code, 200)

    def test_stats_overview_comparison_mode_last_year(self):
        resp = self.client.get(
            f'{STATS_URL}overview/?comparison_mode=same_period_last_year'
        )
        self.assertEqual(resp.status_code, 200)
