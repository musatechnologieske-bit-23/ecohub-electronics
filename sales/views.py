from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
import json
from weasyprint import HTML

VAT_RATE = Decimal('0.16')


def _document_print_context(request, document):
    """Build shared printable details, including optional customer terms."""
    default_notes = (
        f"Delivery:\n"
        f"- Delivery and installation schedule to be agreed.\n"
        f"Payment:\n"
        f"- Payment schedule to be agreed with the customer."
    )
    default_signature = request.user.get_full_name() or request.user.get_username()
    signature_name = request.GET.get('signature_name', '').strip()
    return {
        'document': document,
        'company_kra_pin': 'P052109923A',
        'items': document.items.select_related('product').all(),
        'payments': document.payments.select_related('received_by').all(),
        'print_user': signature_name or default_signature,
        'print_notes': document.notes or default_notes,
    }

from .models import Document, DocumentItem, Payment, Receipt
from inventory.models import Product, StockMovement
from customers.models import Customer


@login_required
def invoice_list(request):
    """List of all sales invoices with search and status filtering."""
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    invoices = Document.objects.filter(doc_type=Document.DocType.INVOICE).select_related('customer', 'created_by')

    if query:
        invoices = invoices.filter(
            Q(doc_number__icontains=query) |
            Q(customer__name__icontains=query) |
            Q(items__description__icontains=query)
        ).distinct()

    if status_filter:
        invoices = invoices.filter(status=status_filter)

    paginator = Paginator(invoices, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'sales/invoice_list.html', {
        'invoices': page_obj,
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'status_choices': Document.Status.choices,
    })


@login_required
def quotation_list(request):
    """List of all quotations."""
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    quotations = Document.objects.filter(doc_type=Document.DocType.QUOTATION).select_related('customer', 'created_by')

    if query:
        quotations = quotations.filter(
            Q(doc_number__icontains=query) |
            Q(customer__name__icontains=query) |
            Q(items__description__icontains=query)
        ).distinct()

    if status_filter:
        quotations = quotations.filter(status=status_filter)

    paginator = Paginator(quotations, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'sales/quotation_list.html', {
        'quotations': page_obj,
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
    })


@login_required
def document_detail(request, pk):
    """View invoice or quotation details, items, payments, and receipt."""
    document = get_object_or_404(
        Document.objects.select_related('customer', 'created_by', 'converted_from'),
        pk=pk
    )
    items = document.items.select_related('product').all()
    payments = document.payments.select_related('received_by').all()
    receipt = getattr(document, 'receipt', None)

    return render(request, 'sales/document_detail.html', {
        'document': document,
        'items': items,
        'payments': payments,
        'receipt': receipt,
        'payment_methods': Payment.Method.choices,
    })


@login_required
def document_print(request, pk):
    """Return a clean PDF without browser-generated URL or title headers."""
    document = get_object_or_404(
        Document.objects.select_related('customer', 'created_by', 'converted_from'), pk=pk
    )
    if request.GET.get('signature_type') == 'custom' and not request.GET.get('signature_name', '').strip():
        return HttpResponse('Please provide a signature name or select the logged-in user.', status=400)
    html = render_to_string(
        'sales/document_print.html',
        _document_print_context(request, document),
        request=request,
    )
    pdf = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{document.doc_number}.pdf"'
    return response


@login_required
def receipt_print(request, pk):
    """Render the official receipt as a standalone printable document."""
    invoice = get_object_or_404(
        Document.objects.select_related('customer', 'created_by').filter(
            doc_type=Document.DocType.INVOICE
        ), pk=pk
    )
    receipt = getattr(invoice, 'receipt', None)
    if receipt is None:
        return HttpResponse('This invoice does not have an official receipt yet.', status=404)
    signature_name = request.GET.get('signature_name', '').strip()
    if request.GET.get('signature_type') == 'custom' and not signature_name:
        return HttpResponse('Please provide a signature name or select the logged-in user.', status=400)
    return render(request, 'sales/receipt_print.html', {
        'invoice': invoice,
        'receipt': receipt,
        'payments': invoice.payments.select_related('received_by').all(),
        'print_user': signature_name or request.user.get_full_name() or request.user.get_username(),
    })


@login_required
def document_create(request):
    """
    Create a new Quotation or Invoice.
    Supports catalog product search AND on-the-fly ad-hoc custom line items.
    """
    doc_type = request.GET.get('type', Document.DocType.INVOICE)
    if doc_type not in [Document.DocType.INVOICE, Document.DocType.QUOTATION]:
        doc_type = Document.DocType.INVOICE

    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        issue_date = request.POST.get('issue_date')
        due_date = request.POST.get('due_date') or None
        notes = request.POST.get('notes', '').strip()
        quotation_payment_term = request.POST.get(
            'quotation_payment_term', Document.QuotationPaymentTerm.CASH
        )
        if quotation_payment_term not in Document.QuotationPaymentTerm.values:
            quotation_payment_term = Document.QuotationPaymentTerm.CASH
        discount_val = Decimal(request.POST.get('discount') or '0.00')
        tax_val = Decimal(request.POST.get('tax') or '0.00')
        action_type = request.POST.get('action_type', 'issue')  # 'draft' or 'issue'

        # Parse items JSON payload
        items_json = request.POST.get('items_payload', '[]')
        try:
            items_data = json.loads(items_json)
        except json.JSONDecodeError:
            items_data = []

        if not items_data:
            messages.error(request, "Please add at least one line item to the document.")
            customers = Customer.objects.all().order_by('name')
            return render(request, 'sales/document_form.html', {
                'doc_type': doc_type,
                'customers': customers,
            })

        customer = None
        if customer_id == 'new':
            customer_name = request.POST.get('new_customer_name', '').strip()
            if not customer_name:
                messages.error(request, 'Please enter the new customer name.')
                customers = Customer.objects.all().order_by('name')
                return render(request, 'sales/document_form.html', {
                    'doc_type': doc_type,
                    'customers': customers,
                })
            customer = Customer.objects.create(
                name=customer_name,
                account_number=request.POST.get('new_customer_account_number', '').strip(),
                phone=request.POST.get('new_customer_phone', '').strip(),
                email=request.POST.get('new_customer_email', '').strip(),
                kra_pin=request.POST.get('new_customer_kra_pin', '').strip().upper(),
                address=request.POST.get('new_customer_address', '').strip(),
            )
        elif customer_id:
            try:
                customer = Customer.objects.get(pk=customer_id)
            except Customer.DoesNotExist:
                pass

        with transaction.atomic():
            doc_number = Document.generate_next_number(doc_type)

            # Determine initial status
            if action_type == 'draft':
                initial_status = Document.Status.DRAFT
            else:
                initial_status = Document.Status.SENT if doc_type == Document.DocType.QUOTATION else Document.Status.UNPAID

            doc = Document.objects.create(
                doc_type=doc_type,
                doc_number=doc_number,
                customer=customer,
                status=initial_status,
                issue_date=issue_date or timezone.now().date(),
                due_date=due_date,
                quotation_payment_term=(
                    quotation_payment_term
                    if doc_type == Document.DocType.QUOTATION
                    else Document.QuotationPaymentTerm.CASH
                ),
                discount=discount_val,
                tax=tax_val,
                notes=notes,
                created_by=request.user,
            )

            subtotal = Decimal('0.00')

            for item in items_data:
                product_id = item.get('product_id')
                description = item.get('description', '').strip()
                quantity = int(item.get('quantity', 1))
                unit_price = Decimal(str(item.get('unit_price', '0.00')))
                line_total = Decimal(quantity) * unit_price

                product = None
                if product_id:
                    try:
                        product = Product.objects.select_for_update().get(pk=product_id)
                    except Product.DoesNotExist:
                        product = None

                DocumentItem.objects.create(
                    document=doc,
                    product=product,
                    description=description or (product.name if product else "Custom Item"),
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                )

                subtotal += line_total

                # Deduct stock ONLY for confirmed/issued INVOICES and ONLY for CATALOG products
                if doc.is_invoice and doc.status != Document.Status.DRAFT and product:
                    StockMovement.objects.create(
                        product=product,
                        movement_type=StockMovement.MovementType.SALE,
                        quantity=quantity,
                        reference=f"Sale #{doc.doc_number}",
                        created_by=request.user
                    )

            doc.subtotal = subtotal
            if doc.is_quotation:
                taxable_amount = max(Decimal('0.00'), subtotal - discount_val)
                tax_val = (taxable_amount * VAT_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                doc.tax = tax_val
            doc.total = max(Decimal('0.00'), subtotal - discount_val + tax_val)
            doc.save()

            messages.success(request, f"{doc.get_doc_type_display()} '{doc.doc_number}' has been created successfully.")
            return redirect('sales:document_detail', pk=doc.pk)

    customers = Customer.objects.all().order_by('name')
    products = Product.objects.filter(is_active=True).order_by('name')

    return render(request, 'sales/document_form.html', {
        'doc_type': doc_type,
        'customers': customers,
        'products': products,
    })


@login_required
@require_POST
def quotation_convert_to_invoice(request, pk):
    """
    Convert an existing quotation into a fresh invoice.
    Updates the quotation status to 'converted' and logs stock deductions for catalog items.
    """
    quotation = get_object_or_404(Document, pk=pk, doc_type=Document.DocType.QUOTATION)

    with transaction.atomic():
        invoice_number = Document.generate_next_number(Document.DocType.INVOICE)

        invoice = Document.objects.create(
            doc_type=Document.DocType.INVOICE,
            doc_number=invoice_number,
            customer=quotation.customer,
            status=Document.Status.UNPAID,
            issue_date=timezone.now().date(),
            subtotal=quotation.subtotal,
            discount=quotation.discount,
            tax=quotation.tax,
            total=quotation.total,
            quotation_payment_term=quotation.quotation_payment_term,
            notes=quotation.notes,
            converted_from=quotation,
            created_by=request.user,
        )

        for q_item in quotation.items.all():
            DocumentItem.objects.create(
                document=invoice,
                product=q_item.product,
                description=q_item.description,
                quantity=q_item.quantity,
                unit_price=q_item.unit_price,
                line_total=q_item.line_total,
            )

            # Deduct inventory for catalog items
            if q_item.product:
                StockMovement.objects.create(
                    product=q_item.product,
                    movement_type=StockMovement.MovementType.SALE,
                    quantity=q_item.quantity,
                    reference=f"Sale #{invoice.doc_number} (from {quotation.doc_number})",
                    created_by=request.user
                )

        quotation.status = Document.Status.CONVERTED
        quotation.save(update_fields=['status', 'updated_at'])

        messages.success(request, f"Quotation '{quotation.doc_number}' was successfully converted to Invoice '{invoice.doc_number}'.")
        return redirect('sales:document_detail', pk=invoice.pk)


@login_required
@require_POST
def record_payment(request, pk):
    """
    Record a partial or full payment on an invoice.
    Automatically generates a formal Receipt when invoice is fully paid.
    """
    invoice = get_object_or_404(Document, pk=pk, doc_type=Document.DocType.INVOICE)

    amount_str = request.POST.get('amount', '').strip()
    method = request.POST.get('method', Payment.Method.CASH)
    reference = request.POST.get('reference', '').strip()

    try:
        amount = Decimal(amount_str)
        if amount <= Decimal('0.00'):
            raise ValueError
    except (ValueError, ArithmeticError):
        messages.error(request, "Please enter a valid positive payment amount.")
        return redirect('sales:document_detail', pk=invoice.pk)

    balance = invoice.balance_due
    if amount > balance:
        messages.error(request, f"Payment amount (KSh {amount:.2f}) cannot exceed the balance due (KSh {balance:.2f}).")
        return redirect('sales:document_detail', pk=invoice.pk)

    with transaction.atomic():
        payment = Payment.objects.create(
            invoice=invoice,
            amount=amount,
            method=method,
            reference=reference,
            received_by=request.user
        )

        new_balance = invoice.balance_due
        if new_balance <= Decimal('0.00'):
            invoice.status = Document.Status.PAID
            # Auto-generate Receipt
            if not hasattr(invoice, 'receipt'):
                rcp_num = Receipt.generate_next_number()
                Receipt.objects.create(
                    invoice=invoice,
                    receipt_number=rcp_num,
                    issued_by=request.user
                )
                messages.success(request, f"Payment of ${amount:.2f} received. Invoice fully paid! Receipt #{rcp_num} generated.")
            else:
                messages.success(request, f"Payment of ${amount:.2f} received. Invoice fully paid!")
        else:
            invoice.status = Document.Status.PARTIALLY_PAID
            messages.success(request, f"Partial payment of ${amount:.2f} recorded. Remaining balance: ${new_balance:.2f}.")

        invoice.save(update_fields=['status', 'updated_at'])

    return redirect('sales:document_detail', pk=invoice.pk)


@login_required
def product_search_api(request):
    """
    JSON search API returning catalog items for checkout.
    """
    query = request.GET.get('q', '').strip()
    products = Product.objects.filter(is_active=True)
    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(sku__icontains=query)
        )[:15]
    else:
        products = products[:15]

    data = [
        {
            'id': p.id,
            'name': p.name,
            'sku': p.sku,
            'price': str(p.selling_price),
            'stock': p.quantity_in_stock,
            'is_low_stock': p.is_low_stock,
            'is_out_of_stock': p.is_out_of_stock,
        }
        for p in products
    ]
    return JsonResponse({'products': data})
