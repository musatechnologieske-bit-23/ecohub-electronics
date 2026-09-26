from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
from inventory.models import Product
from customers.models import Customer


class Document(models.Model):
    class DocType(models.TextChoices):
        QUOTATION = 'quotation', 'Quotation'
        INVOICE = 'invoice', 'Invoice'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SENT = 'sent', 'Sent'
        CONVERTED = 'converted', 'Converted to Invoice'
        UNPAID = 'unpaid', 'Unpaid'
        PARTIALLY_PAID = 'partially_paid', 'Partially Paid'
        PAID = 'paid', 'Paid'
        CANCELLED = 'cancelled', 'Cancelled'

    class QuotationPaymentTerm(models.TextChoices):
        CASH = 'cash', 'Cash'
        CREDIT = 'credit', 'Credit'
        APPROVED = 'approved', 'Approved'

    doc_type = models.CharField(max_length=20, choices=DocType.choices, default=DocType.INVOICE)
    doc_number = models.CharField(max_length=50, unique=True, help_text="e.g. QT-0001 or INV-0001")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    quotation_payment_term = models.CharField(
        max_length=20,
        choices=QuotationPaymentTerm.choices,
        default=QuotationPaymentTerm.CASH,
    )

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True, default='')

    converted_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='converted_invoices'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issue_date', '-created_at']

    def __str__(self):
        return f"{self.get_doc_type_display()} {self.doc_number}"

    @property
    def is_quotation(self) -> bool:
        return self.doc_type == self.DocType.QUOTATION

    @property
    def is_invoice(self) -> bool:
        return self.doc_type == self.DocType.INVOICE

    @property
    def total_paid(self) -> Decimal:
        """Sum of all recorded payments."""
        total_p = self.payments.aggregate(models.Sum('amount'))['amount__sum']
        return total_p or Decimal('0.00')

    @property
    def balance_due(self) -> Decimal:
        """Outstanding balance on this document."""
        return max(Decimal('0.00'), self.total - self.total_paid)

    @classmethod
    def generate_next_number(cls, doc_type: str) -> str:
        """
        Generates consecutive document numbers like QT-0001 or INV-0001.
        """
        prefix = "QT-" if doc_type == cls.DocType.QUOTATION else "INV-"
        last_doc = cls.objects.filter(
            doc_type=doc_type,
            doc_number__startswith=prefix
        ).order_by('-id').first()

        if last_doc and last_doc.doc_number:
            try:
                numeric_part = int(last_doc.doc_number.replace(prefix, ''))
                next_number = numeric_part + 1
            except ValueError:
                next_number = cls.objects.filter(doc_type=doc_type).count() + 1
        else:
            next_number = 1

        return f"{prefix}{next_number:04d}"


class DocumentItem(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='document_items',
        help_text="Null designates an ad-hoc custom item not linked to inventory catalog"
    )
    description = models.CharField(max_length=255)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.description} ({self.quantity} x {self.unit_price})"

    @property
    def is_adhoc(self) -> bool:
        """True if this is an ad-hoc custom item, not linked to a Product."""
        return self.product is None

    def save(self, *args, **kwargs):
        self.line_total = Decimal(self.quantity) * Decimal(self.unit_price)
        super().save(*args, **kwargs)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        MPESA = 'mpesa', 'M-Pesa'
        CARD = 'card', 'Card / Credit Card'
        BANK_TRANSFER = 'bank_transfer', 'Bank Transfer'

    invoice = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(max_length=100, blank=True, default='', help_text="e.g. M-Pesa transaction ID, check number")
    paid_at = models.DateTimeField(default=timezone.now)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments_received'
    )

    class Meta:
        ordering = ['-paid_at']

    def __str__(self):
        return f"Payment of {self.amount} for {self.invoice.doc_number} ({self.get_method_display()})"


class Receipt(models.Model):
    invoice = models.OneToOneField(Document, on_delete=models.CASCADE, related_name='receipt')
    receipt_number = models.CharField(max_length=50, unique=True, help_text="e.g. RCP-0001")
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='receipts_issued'
    )

    class Meta:
        ordering = ['-issued_at']

    def __str__(self):
        return f"Receipt {self.receipt_number} ({self.invoice.doc_number})"

    @classmethod
    def generate_next_number(cls) -> str:
        prefix = "RCP-"
        last_receipt = cls.objects.filter(receipt_number__startswith=prefix).order_by('-id').first()
        if last_receipt:
            try:
                num = int(last_receipt.receipt_number.replace(prefix, ''))
                next_num = num + 1
            except ValueError:
                next_num = cls.objects.count() + 1
        else:
            next_num = 1
        return f"{prefix}{next_num:04d}"
