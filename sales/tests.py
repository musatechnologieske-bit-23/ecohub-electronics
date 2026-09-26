from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from decimal import Decimal
import json

from sales.models import Document, DocumentItem, Payment, Receipt
from sales.views import _document_print_context
from inventory.models import Product, StockMovement
from customers.models import Customer

User = get_user_model()


class SalesFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.cashier = User.objects.create_user(
            username='cashier_sales',
            password='password123',
            role=User.Role.CASHIER
        )
        self.customer = Customer.objects.create(name='Acme Corp', phone='0711000111', kra_pin='A123456789Z')

        # Product with 50 units initial stock
        self.product = Product.objects.create(
            name='Fast Charger 30W',
            sku='CHG-001',
            cost_price=10.00,
            selling_price=25.00,
            reorder_level=5
        )
        StockMovement.objects.create(
            product=self.product,
            movement_type=StockMovement.MovementType.STOCK_IN,
            quantity=50,
            reference='Initial Restock',
            created_by=self.cashier
        )

    def test_print_terms_are_optional_and_signature_is_not_repeated_below_line(self):
        invoice = Document.objects.create(
            doc_type=Document.DocType.INVOICE,
            doc_number='INV-PRINT-1',
            customer=self.customer,
            total=Decimal('100.00'),
            created_by=self.cashier,
        )
        request = RequestFactory().get('/')
        request.user = self.cashier

        context = _document_print_context(request, invoice)
        self.assertNotIn('85%', context['print_notes'])
        self.assertNotIn('15%', context['print_notes'])
        self.assertIn('Payment schedule to be agreed', context['print_notes'])
        self.assertEqual(context['company_kra_pin'], 'P052109923A')

        invoice.notes = '30% deposit, remaining 70% on completion.'
        invoice.save(update_fields=['notes'])
        context = _document_print_context(request, invoice)
        self.assertEqual(context['print_notes'], invoice.notes)

        printed_document = render_to_string('sales/document_print.html', context)
        self.assertEqual(printed_document.count(self.cashier.username), 1)
        self.assertIn('Authorized signature', printed_document)
        self.assertIn('KRA PIN: P052109923A', printed_document)
        self.assertIn('KRA PIN:</strong> A123456789Z', printed_document)
        self.assertIn('Warranty is provided', printed_document)
        self.assertNotIn('Bank Code: 07000', printed_document)
        self.assertNotIn('GREENSPAN MALL', printed_document)
        self.assertNotIn('signature-name', printed_document)

        receipt = Receipt.objects.create(invoice=invoice, receipt_number='RCP-PRINT-1')
        printed_receipt = render_to_string('sales/receipt_print.html', {
            'invoice': invoice,
            'receipt': receipt,
            'payments': [],
            'print_user': self.cashier.username,
        })
        self.assertEqual(printed_receipt.count(self.cashier.username), 1)
        self.assertIn('Authorized signature', printed_receipt)
        self.assertNotIn('Bank Code: 07000', printed_receipt)
        self.assertNotIn('GREENSPAN MALL', printed_receipt)
        self.assertNotIn('signature-name', printed_receipt)

    def test_doc_number_generation(self):
        doc_num1 = Document.generate_next_number(Document.DocType.INVOICE)
        self.assertEqual(doc_num1, 'INV-0001')
        doc_qt1 = Document.generate_next_number(Document.DocType.QUOTATION)
        self.assertEqual(doc_qt1, 'QT-0001')

    def test_sale_with_catalog_and_adhoc_items(self):
        self.client.login(username='cashier_sales', password='password123')

        items_payload = [
            # Catalog item: 2 units of Charger @ 25.00 = 50.00
            {
                'product_id': self.product.pk,
                'description': self.product.name,
                'quantity': 2,
                'unit_price': '25.00',
                'is_adhoc': False,
            },
            # Ad-hoc custom item: Screen protector installation @ 15.00
            {
                'product_id': None,  # Ad-hoc
                'description': 'Tempered Glass Screen Protector Fitment',
                'quantity': 1,
                'unit_price': '15.00',
                'is_adhoc': True,
            }
        ]

        response = self.client.post(
            reverse('sales:document_create') + '?type=invoice',
            {
                'customer_id': self.customer.pk,
                'issue_date': '2026-09-22',
                'discount': '5.00',
                'tax': '0.00',
                'action_type': 'issue',
                'items_payload': json.dumps(items_payload),
            }
        )
        self.assertEqual(response.status_code, 302)

        invoice = Document.objects.get(doc_number='INV-0001')
        self.assertEqual(invoice.status, Document.Status.UNPAID)
        self.assertEqual(invoice.subtotal, Decimal('65.00'))  # 50 + 15
        self.assertEqual(invoice.discount, Decimal('5.00'))
        self.assertEqual(invoice.total, Decimal('60.00'))     # 65 - 5

        # Verify items
        self.assertEqual(invoice.items.count(), 2)
        catalog_item = invoice.items.get(product=self.product)
        self.assertEqual(catalog_item.quantity, 2)
        adhoc_item = invoice.items.get(product__isnull=True)
        self.assertEqual(adhoc_item.description, 'Tempered Glass Screen Protector Fitment')
        self.assertTrue(adhoc_item.is_adhoc)

        # CRITICAL TEST: Stock deduction for catalog product ONLY
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 48)  # 50 - 2

        # Verify StockMovement record exists
        movement = StockMovement.objects.filter(product=self.product, movement_type='sale').first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, 2)
        self.assertEqual(movement.reference, 'Sale #INV-0001')

    def test_quotation_does_not_deduct_stock_until_converted(self):
        self.client.login(username='cashier_sales', password='password123')

        items_payload = [{
            'product_id': self.product.pk,
            'description': self.product.name,
            'quantity': 5,
            'unit_price': '25.00',
        }]

        # Create quotation
        self.client.post(
            reverse('sales:document_create') + '?type=quotation',
            {
                'customer_id': self.customer.pk,
                'issue_date': '2026-09-22',
                'quotation_payment_term': 'credit',
                'action_type': 'issue',
                'items_payload': json.dumps(items_payload),
            }
        )
        quote = Document.objects.get(doc_number='QT-0001')
        self.assertEqual(quote.status, Document.Status.SENT)
        self.assertEqual(quote.quotation_payment_term, Document.QuotationPaymentTerm.CREDIT)
        self.assertEqual(quote.tax, Decimal('20.00'))
        self.assertEqual(quote.total, Decimal('145.00'))

        # Product stock should NOT change
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 50)

        # Now convert quotation to invoice
        convert_response = self.client.post(reverse('sales:quotation_convert', args=[quote.pk]))
        self.assertEqual(convert_response.status_code, 302)

        quote.refresh_from_db()
        self.assertEqual(quote.status, Document.Status.CONVERTED)

        invoice = Document.objects.get(doc_type=Document.DocType.INVOICE)
        self.assertEqual(invoice.converted_from, quote)
        self.assertEqual(invoice.total, quote.total)
        self.assertEqual(invoice.quotation_payment_term, Document.QuotationPaymentTerm.CREDIT)

        # Stock is now deducted
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 45)  # 50 - 5

    def test_quotation_can_create_and_capture_new_customer(self):
        self.client.login(username='cashier_sales', password='password123')
        items_payload = [{
            'product_id': self.product.pk,
            'description': self.product.name,
            'quantity': 1,
            'unit_price': '25.00',
        }]

        response = self.client.post(
            reverse('sales:document_create') + '?type=quotation',
            {
                'customer_id': 'new',
                'new_customer_name': 'Green Future Ltd',
                'new_customer_account_number': 'ACC-0099',
                'new_customer_phone': '+254700000001',
                'new_customer_email': 'accounts@greenfuture.example',
                'new_customer_kra_pin': 'p123456789a',
                'new_customer_address': 'Nairobi, Kenya',
                'issue_date': '2026-09-22',
                'action_type': 'issue',
                'items_payload': json.dumps(items_payload),
            }
        )

        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(name='Green Future Ltd')
        quote = Document.objects.get(doc_number='QT-0001')
        self.assertEqual(quote.customer, customer)
        self.assertEqual(customer.account_number, 'ACC-0099')
        self.assertEqual(customer.phone, '+254700000001')
        self.assertEqual(customer.kra_pin, 'P123456789A')

    def test_quotation_print_shows_customer_pin_company_pin_and_payment_term(self):
        quote = Document.objects.create(
            doc_type=Document.DocType.QUOTATION,
            doc_number='QT-PRINT-1',
            customer=self.customer,
            quotation_payment_term=Document.QuotationPaymentTerm.APPROVED,
            created_by=self.cashier,
        )
        request = RequestFactory().get('/')
        request.user = self.cashier

        printed_document = render_to_string(
            'sales/document_print.html',
            _document_print_context(request, quote),
        )

        self.assertIn('A123456789Z', printed_document)
        self.assertIn('P052109923A', printed_document)
        self.assertIn('Payment terms:</strong> Approved', printed_document)

    def test_payments_and_auto_receipt_generation(self):
        self.client.login(username='cashier_sales', password='password123')

        invoice = Document.objects.create(
            doc_type=Document.DocType.INVOICE,
            doc_number='INV-0010',
            customer=self.customer,
            status=Document.Status.UNPAID,
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            created_by=self.cashier
        )

        # 1. Partial payment: $40
        resp1 = self.client.post(reverse('sales:record_payment', args=[invoice.pk]), {
            'amount': '40.00',
            'method': Payment.Method.MPESA,
            'reference': 'QWE123MPESA',
        })
        self.assertEqual(resp1.status_code, 302)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PARTIALLY_PAID)
        self.assertEqual(invoice.total_paid, Decimal('40.00'))
        self.assertEqual(invoice.balance_due, Decimal('60.00'))
        self.assertFalse(hasattr(invoice, 'receipt'))

        # 2. Overpayment attempt should fail
        resp2 = self.client.post(reverse('sales:record_payment', args=[invoice.pk]), {
            'amount': '80.00',  # Exceeds $60
            'method': Payment.Method.CASH,
        })
        self.assertEqual(resp2.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.balance_due, Decimal('60.00'))  # Unchanged

        # 3. Final payment of remaining $60
        resp3 = self.client.post(reverse('sales:record_payment', args=[invoice.pk]), {
            'amount': '60.00',
            'method': Payment.Method.CASH,
        })
        self.assertEqual(resp3.status_code, 302)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)
        self.assertEqual(invoice.balance_due, Decimal('0.00'))

        # Auto-receipt generated
        self.assertTrue(hasattr(invoice, 'receipt'))
        receipt = invoice.receipt
        self.assertEqual(receipt.receipt_number, 'RCP-0001')
        self.assertEqual(receipt.issued_by, self.cashier)

    def test_print_requires_custom_signature_name(self):
        self.client.login(username='cashier_sales', password='password123')
        invoice = Document.objects.create(
            doc_type=Document.DocType.INVOICE,
            doc_number='INV-0020',
            customer=self.customer,
            status=Document.Status.UNPAID,
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            created_by=self.cashier,
        )

        response = self.client.get(
            reverse('sales:document_print', args=[invoice.pk]),
            {'signature_type': 'custom'},
        )

        self.assertEqual(response.status_code, 400)
