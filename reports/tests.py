from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from inventory.models import Product
from reports.views import _dashboard_context
from sales.models import Document, DocumentItem


class DashboardMetricTests(TestCase):
	def test_open_quotation_total_and_monthly_gross_profit(self):
		product = Product.objects.create(
			name='Solar lamp',
			sku='SOLAR-001',
			cost_price=Decimal('20.00'),
		)
		invoice = Document.objects.create(
			doc_type=Document.DocType.INVOICE,
			doc_number='INV-DASHBOARD-1',
			issue_date=timezone.localdate(),
			subtotal=Decimal('200.00'),
			discount=Decimal('10.00'),
			tax=Decimal('30.40'),
			total=Decimal('220.40'),
		)
		DocumentItem.objects.create(
			document=invoice,
			product=product,
			description=product.name,
			quantity=2,
			unit_price=Decimal('100.00'),
			line_total=Decimal('200.00'),
		)
		Document.objects.create(
			doc_type=Document.DocType.QUOTATION,
			doc_number='QT-DASHBOARD-1',
			status=Document.Status.DRAFT,
			total=Decimal('75.00'),
		)
		Document.objects.create(
			doc_type=Document.DocType.QUOTATION,
			doc_number='QT-DASHBOARD-2',
			status=Document.Status.SENT,
			total=Decimal('125.00'),
		)
		Document.objects.create(
			doc_type=Document.DocType.QUOTATION,
			doc_number='QT-DASHBOARD-3',
			status=Document.Status.CONVERTED,
			total=Decimal('300.00'),
		)

		context = _dashboard_context()

		self.assertEqual(context['open_quotation_count'], 2)
		self.assertEqual(context['open_quotation_total'], Decimal('200.00'))
		self.assertEqual(context['current_profit'], Decimal('150.00'))
