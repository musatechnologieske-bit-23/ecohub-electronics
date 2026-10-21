from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponse, JsonResponse
from django.contrib.staticfiles import finders
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from django.utils.text import slugify
from io import BytesIO
import json

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

VAT_RATE = Decimal('0.16')


def _format_kenyan_phone(phone):
    phone = (phone or '').strip()
    digits = ''.join(character for character in phone if character.isdigit())
    if digits.startswith('254'):
        return f'+{digits}'
    if digits.startswith('0'):
        return f'+254{digits[1:]}'
    if len(digits) == 9:
        return f'+254{digits}'
    return phone


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
        'customer_phone': _format_kenyan_phone(document.customer.phone if document.customer else ''),
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
@require_POST
def quotation_delete(request, pk):
    quotation = get_object_or_404(Document, pk=pk, doc_type=Document.DocType.QUOTATION)
    if quotation.status == Document.Status.CONVERTED or quotation.converted_invoices.exists():
        messages.error(request, 'Converted quotations cannot be deleted because they are linked to invoices.')
        return redirect('sales:quotation_list')

    quotation_number = quotation.doc_number
    quotation.delete()
    messages.success(request, f"Quotation '{quotation_number}' was deleted.")
    return redirect('sales:quotation_list')


@login_required
def quotation_edit(request, pk):
    quotation = get_object_or_404(
        Document.objects.select_related('customer'),
        pk=pk,
        doc_type=Document.DocType.QUOTATION,
    )
    if quotation.status in [Document.Status.CONVERTED, Document.Status.CANCELLED] or quotation.converted_invoices.exists():
        messages.error(request, 'Converted or cancelled quotations cannot be edited.')
        return redirect('sales:document_detail', pk=quotation.pk)

    customers = Customer.objects.all().order_by('name')
    products = Product.objects.filter(is_active=True).order_by('name')
    initial_items = [
        {
            'product_id': item.product_id,
            'description': item.description,
            'sku': item.product.sku if item.product else None,
            'quantity': item.quantity,
            'unit_price': str(item.unit_price),
            'is_adhoc': item.product_id is None,
        }
        for item in quotation.items.select_related('product').all()
    ]

    if request.method == 'POST':
        try:
            items_data = json.loads(request.POST.get('items_payload', '[]'))
            if not isinstance(items_data, list) or not items_data:
                raise ValueError
            parsed_items = []
            for item in items_data:
                quantity = int(item.get('quantity', 0))
                unit_price = Decimal(str(item.get('unit_price', '0')))
                description = item.get('description', '').strip()
                if quantity < 1 or unit_price < 0 or not description:
                    raise ValueError
                parsed_items.append((item.get('product_id'), description, quantity, unit_price))
            discount = Decimal(request.POST.get('discount') or '0')
            if discount < 0:
                raise ValueError
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError, ArithmeticError):
            messages.error(request, 'Please provide valid quotation details and at least one item.')
            return redirect('sales:quotation_edit', pk=quotation.pk)

        customer_id = request.POST.get('customer_id')
        if customer_id == 'new':
            customer_name = request.POST.get('new_customer_name', '').strip()
            if not customer_name:
                messages.error(request, 'Please enter the new customer name.')
                return redirect('sales:quotation_edit', pk=quotation.pk)
            customer = Customer.objects.create(
                name=customer_name,
                account_number=request.POST.get('new_customer_account_number', '').strip(),
                phone=request.POST.get('new_customer_phone', '').strip(),
                email=request.POST.get('new_customer_email', '').strip(),
                kra_pin=request.POST.get('new_customer_kra_pin', '').strip().upper(),
                address=request.POST.get('new_customer_address', '').strip(),
            )
        else:
            customer = Customer.objects.filter(pk=customer_id).first() if customer_id else None

        payment_term = request.POST.get('quotation_payment_term', Document.QuotationPaymentTerm.CASH)
        if payment_term not in Document.QuotationPaymentTerm.values:
            payment_term = Document.QuotationPaymentTerm.CASH

        with transaction.atomic():
            quotation.customer = customer
            quotation.issue_date = request.POST.get('issue_date') or quotation.issue_date
            quotation.due_date = request.POST.get('due_date') or None
            quotation.quotation_payment_term = payment_term
            quotation.discount = discount
            quotation.vat_enabled = request.POST.get('vat_enabled') == '1'
            quotation.notes = request.POST.get('notes', '').strip()
            quotation.items.all().delete()

            subtotal = Decimal('0.00')
            for product_id, description, quantity, unit_price in parsed_items:
                product = Product.objects.filter(pk=product_id).first() if product_id else None
                line_total = Decimal(quantity) * unit_price
                DocumentItem.objects.create(
                    document=quotation,
                    product=product,
                    description=description,
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                )
                subtotal += line_total

            quotation.subtotal = subtotal
            taxable_amount = max(Decimal('0.00'), subtotal - discount)
            quotation.tax = (
                (taxable_amount * VAT_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                if quotation.vat_enabled else Decimal('0.00')
            )
            quotation.total = max(Decimal('0.00'), subtotal - discount + quotation.tax)
            quotation.save()

        messages.success(request, f"Quotation '{quotation.doc_number}' has been updated.")
        return redirect('sales:document_detail', pk=quotation.pk)

    return render(request, 'sales/document_form.html', {
        'doc_type': Document.DocType.QUOTATION,
        'customers': customers,
        'products': products,
        'document': quotation,
        'initial_items': initial_items,
        'is_edit': True,
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
    """Render a browser-printable document that can be saved as a PDF."""
    document = get_object_or_404(
        Document.objects.select_related('customer', 'created_by', 'converted_from'), pk=pk
    )
    if request.GET.get('signature_type') == 'custom' and not request.GET.get('signature_name', '').strip():
        return HttpResponse('Please provide a signature name or select the logged-in user.', status=400)
    return render(
        request,
        'sales/document_print.html',
        _document_print_context(request, document),
    )


@login_required
def document_download(request, pk):
    """Generate and directly download an invoice or quotation as a PDF."""
    document = get_object_or_404(
        Document.objects.select_related('customer', 'created_by', 'converted_from'), pk=pk
    )
    if request.GET.get('signature_type') == 'custom' and not request.GET.get('signature_name', '').strip():
        return HttpResponse('Please provide a signature name or select the logged-in user.', status=400)

    context = _document_print_context(request, document)
    output = BytesIO()
    pdf = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=13 * mm,
        leftMargin=13 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f'{document.get_doc_type_display()} {document.doc_number}',
    )

    navy = colors.HexColor('#073b8f')
    green = colors.HexColor('#087f5b')
    gray = colors.HexColor('#4b5563')
    light_gray = colors.HexColor('#f1f3f5')
    styles = {
        'brand': ParagraphStyle('Brand', fontName='Helvetica-Bold', fontSize=15, leading=17, textColor=navy),
        'subtitle': ParagraphStyle('Subtitle', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=green),
        'company': ParagraphStyle('Company', fontSize=8, leading=11, textColor=gray),
        'title': ParagraphStyle('Title', fontName='Helvetica-Bold', fontSize=17, leading=20, alignment=TA_RIGHT, textColor=gray),
        'right': ParagraphStyle('Right', fontSize=8, leading=11, alignment=TA_RIGHT, textColor=gray),
        'customer': ParagraphStyle('Customer', fontName='Helvetica-Bold', fontSize=11, leading=14),
        'body': ParagraphStyle('Body', fontSize=8, leading=11, textColor=gray),
        'table_header': ParagraphStyle('TableHeader', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.white),
        'table_body': ParagraphStyle('TableBody', fontSize=8, leading=10),
        'table_right': ParagraphStyle('TableRight', fontSize=8, leading=10, alignment=TA_RIGHT),
        'small': ParagraphStyle('Small', fontSize=7.5, leading=10, textColor=gray),
    }

    def paragraph(value, style='body'):
        return Paragraph(escape(str(value)).replace('\n', '<br/>'), styles[style])

    def formatted_paragraph(value, style='body'):
        return Paragraph(value, styles[style])

    company = [
        paragraph('Ecohub Energy Africa Limited', 'brand'),
        paragraph('Reliable energy & technology solutions', 'subtitle'),
        paragraph(
            'P.O. Box 20504, Nairobi, Kenya\nTel: +254 748 891 464\n'
            f'Email: info@ecohubenergyafrica.com\n{context["company_kra_pin"]}',
            'company',
        ),
    ]
    logo_path = finders.find('logo.jpeg')
    if logo_path:
        company_header = Table(
            [[Image(logo_path, width=12 * mm, height=12 * mm), company]],
            colWidths=[14 * mm, 76 * mm],
        )
        company_header.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
    else:
        company_header = company

    story = [
        Table(
            [[company_header, [
                paragraph(document.get_doc_type_display().upper(), 'title'),
                paragraph(f'# {document.doc_number}', 'right'),
            ]]],
            colWidths=[91 * mm, 93 * mm],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('LINEBELOW', (0, 0), (-1, -1), 0.6, colors.HexColor('#cbd5e1')),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
            ]),
        ),
        Spacer(1, 4 * mm),
    ]

    customer = document.customer
    customer_lines = [paragraph(customer.name if customer else 'Walk-in Customer', 'customer')]
    if customer and customer.account_number:
        customer_lines.append(paragraph(f'Account: {customer.account_number}'))
    if customer and customer.address:
        customer_lines.append(paragraph(customer.address))
    if context['customer_phone']:
        customer_lines.append(paragraph(context['customer_phone']))
    if customer and customer.email:
        customer_lines.append(paragraph(customer.email))
    if customer and customer.kra_pin:
        customer_lines.append(paragraph(customer.kra_pin))

    metadata = [formatted_paragraph(f'<b>Date:</b> {document.issue_date:%d %b, %Y}')]
    if document.due_date:
        metadata.append(formatted_paragraph(f'<b>Due date:</b> {document.due_date:%d %b, %Y}'))
    if document.is_quotation:
        metadata.append(formatted_paragraph(
            f'<b>Payment terms:</b> {escape(document.get_quotation_payment_term_display())}'
        ))
    metadata.append(formatted_paragraph(f'<b>Total Amount: KES {document.total:,.2f}</b>'))
    story.extend([
        Table(
            [[customer_lines, metadata]],
            colWidths=[110 * mm, 74 * mm],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('BACKGROUND', (1, -1), (1, -1), light_gray),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]),
        ),
        Spacer(1, 4 * mm),
    ])

    item_rows = [[
        paragraph('Item', 'table_header'),
        paragraph('Quantity', 'table_header'),
        paragraph('Rate', 'table_header'),
        paragraph('Amount', 'table_header'),
    ]]
    for item in context['items']:
        description = [paragraph(item.description, 'table_body')]
        if item.product:
            description.append(paragraph(f'SKU: {item.product.sku}', 'small'))
        item_rows.append([
            description,
            paragraph(str(item.quantity), 'table_body'),
            paragraph(f'KES {item.unit_price:,.2f}', 'table_right'),
            paragraph(f'KES {item.line_total:,.2f}', 'table_right'),
        ])
    if not context['items']:
        item_rows.append([paragraph('No items added.', 'table_body'), '', '', ''])
    items_table = Table(item_rows, colWidths=[84 * mm, 24 * mm, 35 * mm, 41 * mm], repeatRows=1)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('LINEBELOW', (0, 1), (-1, -1), 0.4, colors.HexColor('#e5e7eb')),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.extend([items_table, Spacer(1, 4 * mm)])

    total_rows = [[paragraph('Subtotal', 'table_body'), paragraph(f'KES {document.subtotal:,.2f}', 'table_right')]]
    if document.discount:
        total_rows.append([paragraph('Discount', 'table_body'), paragraph(f'- KES {document.discount:,.2f}', 'table_right')])
    if document.tax:
        tax_label = 'VAT (16%)' if document.vat_enabled else 'Tax'
        total_rows.append([paragraph(tax_label, 'table_body'), paragraph(f'KES {document.tax:,.2f}', 'table_right')])
    total_index = len(total_rows)
    total_rows.append([
        formatted_paragraph('<b>Total</b>', 'table_body'),
        formatted_paragraph(f'<b>KES {document.total:,.2f}</b>', 'table_right'),
    ])
    if document.is_invoice:
        total_rows.append([paragraph('Balance due', 'table_body'), paragraph(f'KES {document.balance_due:,.2f}', 'table_right')])
    totals_table = Table(total_rows, colWidths=[34 * mm, 43 * mm])
    totals_table.setStyle(TableStyle([
        ('LINEABOVE', (0, total_index), (-1, total_index), 0.5, gray),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    notes = [formatted_paragraph('<b>Please Note</b>')] + [paragraph(line) for line in context['print_notes'].splitlines()]
    story.extend([
        Table(
            [[notes, totals_table]],
            colWidths=[107 * mm, 77 * mm],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]),
        ),
        Spacer(1, 4 * mm),
        formatted_paragraph(
            '<b>Terms &amp; Conditions:</b><br/>'
            '1. Goods and services are not returnable and remain property of Ecohub Energy Africa Limited until fully paid for.<br/>'
            '2. This quotation is valid for 30 days and prices are subject to change.<br/>'
            "3. Warranty is provided in accordance with the manufacturer's warranty and Ecohub warranty terms.",
            'small',
        ),
        Spacer(1, 3 * mm),
    ])

    bank_table = Table(
        [[
            formatted_paragraph('<b>Payable To</b><br/>Ecohub Energy Africa Limited<br/>P.O. Box 20504 - 00100 Nairobi', 'small'),
            formatted_paragraph('<b>Banking Details</b><br/>NCBA BANK<br/>SWIFT/IBAN: CBAFKENX<br/>Account No: 5444810016', 'small'),
            formatted_paragraph(
                f'<b>Other Details</b><br/>Beneficiary: ECOHUB ENERGY AFRICA LTD<br/>'
                f'Currency: Kenya Shillings<br/>Quotation: {escape(document.doc_number)}',
                'small',
            ),
        ]],
        colWidths=[61 * mm, 61 * mm, 62 * mm],
    )
    bank_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, gray),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, gray),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    signature_table = Table(
        [[paragraph('Authorized signature', 'small'), formatted_paragraph(
            f'Prepared by {escape(context["print_user"])}<br/>{document.issue_date:%d %b %Y}', 'right'
        )]],
        colWidths=[92 * mm, 92 * mm],
        style=TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('LINEABOVE', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]),
    )
    story.extend([
        KeepTogether([
            bank_table,
            Spacer(1, 5 * mm),
            signature_table,
            Spacer(1, 4 * mm),
            paragraph('Thank you for your business.', 'small'),
        ]),
    ])
    pdf.build(story)

    filename = f'{slugify(document.doc_number) or document.pk}.pdf'
    output.seek(0)
    return FileResponse(
        output,
        as_attachment=True,
        filename=filename,
        content_type='application/pdf',
    )


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
        'customer_phone': _format_kenyan_phone(invoice.customer.phone if invoice.customer else ''),
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
        vat_enabled = request.POST.get('vat_enabled') == '1'
        if 'vat_enabled' not in request.POST:
            vat_enabled = doc_type == Document.DocType.QUOTATION
        tax_val = Decimal('0.00')
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
                vat_enabled=vat_enabled,
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
            if doc.vat_enabled:
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
            vat_enabled=quotation.vat_enabled,
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
