from calendar import month_abbr
import csv
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape

from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from customers.models import Customer
from inventory.models import Product
from sales.models import Document, DocumentItem, Payment


def _date_filters(request):
	start = request.GET.get('from', '').strip()
	end = request.GET.get('to', '').strip()
	try:
		start_date = date.fromisoformat(start) if start else None
	except ValueError:
		start_date = None
	try:
		end_date = date.fromisoformat(end) if end else None
	except ValueError:
		end_date = None
	return start_date, end_date


def _filtered_invoices(request):
	start_date, end_date = _date_filters(request)
	invoices = Document.objects.filter(doc_type=Document.DocType.INVOICE).select_related('customer')
	if start_date:
		invoices = invoices.filter(issue_date__gte=start_date)
	if end_date:
		invoices = invoices.filter(issue_date__lte=end_date)
	return invoices, start_date, end_date


def _sales_rows(invoices):
	return [[
		invoice.doc_number,
		invoice.issue_date.isoformat(),
		invoice.customer.name if invoice.customer else 'Walk-in Customer',
		invoice.get_status_display(),
		str(invoice.total),
		str(invoice.total_paid),
		str(invoice.balance_due),
	] for invoice in invoices.order_by('-issue_date', '-created_at')]


def _xlsx_response(filename, headers, rows):
	def cell(value):
		return f'<c t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
	row_xml = ''.join('<row>' + ''.join(cell(value) for value in row) + '</row>' for row in [headers, *rows])
	files = {
		'[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
		'_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
		'xl/_rels/workbook.xml.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
		'xl/workbook.xml': '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sales" sheetId="1" r:id="rId1"/></sheets></workbook>',
		'xl/worksheets/sheet1.xml': f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{row_xml}</sheetData></worksheet>',
	}
	buffer = BytesIO()
	with ZipFile(buffer, 'w', ZIP_DEFLATED) as workbook:
		for path, content in files.items():
			workbook.writestr(path, content)
	response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
	response['Content-Disposition'] = f'attachment; filename="{filename}"'
	return response


def _month_window(today):
	"""Return six month buckets ending with the current calendar month."""
	months = []
	year, month = today.year, today.month
	for offset in range(5, -1, -1):
		month_index = year * 12 + month - 1 - offset
		bucket_year, bucket_month = divmod(month_index, 12)
		months.append(date(bucket_year, bucket_month + 1, 1))
	return months


def _invoice_gross_profit(invoices):
	zero = Decimal('0.00')
	totals = invoices.aggregate(subtotal=Sum('subtotal'), discounts=Sum('discount'))
	product_cost = DocumentItem.objects.filter(document__in=invoices).aggregate(
		total=Sum(ExpressionWrapper(
			F('quantity') * Coalesce(
				F('product__cost_price'),
				Value(zero, output_field=DecimalField(max_digits=10, decimal_places=2)),
			),
			output_field=DecimalField(max_digits=14, decimal_places=2),
		))
	)['total'] or zero
	return (totals['subtotal'] or zero) - (totals['discounts'] or zero) - product_cost


def _dashboard_context():
	today = timezone.localdate()
	current_hour = timezone.localtime().hour
	if current_hour < 12:
		greeting = 'Good morning'
	elif current_hour < 17:
		greeting = 'Good afternoon'
	else:
		greeting = 'Good evening'
	months = _month_window(today)
	invoices = Document.objects.filter(doc_type=Document.DocType.INVOICE)
	month_start = months[0]
	current_month = months[-1]
	previous_month = months[-2]

	monthly_totals = {}
	for row in invoices.filter(issue_date__gte=month_start).annotate(
		month=TruncMonth('issue_date')
	).values('month').annotate(total=Sum('total')):
		month_value = row['month']
		monthly_totals[month_value.date() if hasattr(month_value, 'date') else month_value] = row['total'] or Decimal('0.00')
	current_revenue = monthly_totals.get(current_month, Decimal('0.00'))
	previous_revenue = monthly_totals.get(previous_month, Decimal('0.00'))
	revenue_change = Decimal('0.00')
	if previous_revenue:
		revenue_change = ((current_revenue - previous_revenue) / previous_revenue) * 100
	current_profit = _invoice_gross_profit(invoices.filter(
		issue_date__year=current_month.year, issue_date__month=current_month.month
	))
	previous_profit = _invoice_gross_profit(invoices.filter(
		issue_date__year=previous_month.year, issue_date__month=previous_month.month
	))
	profit_change = Decimal('0.00')
	if previous_profit:
		profit_change = ((current_profit - previous_profit) / previous_profit) * 100
	open_quotations = Document.objects.filter(
		doc_type=Document.DocType.QUOTATION,
		status__in=[Document.Status.DRAFT, Document.Status.SENT],
	)
	open_quotation_total = open_quotations.aggregate(total=Sum('total'))['total'] or Decimal('0.00')

	outstanding = invoices.filter(
		status__in=[Document.Status.UNPAID, Document.Status.PARTIALLY_PAID]
	).annotate(
		paid=Coalesce(Sum('payments__amount'), Value(Decimal('0.00'))),
	).aggregate(
		total=Sum(ExpressionWrapper(F('total') - F('paid'), output_field=DecimalField(max_digits=14, decimal_places=2)))
	)['total'] or Decimal('0.00')
	stock_value = Product.objects.filter(is_active=True).aggregate(
		total=Sum(ExpressionWrapper(
			F('quantity_in_stock') * F('cost_price'),
			output_field=DecimalField(max_digits=14, decimal_places=2),
		))
	)['total'] or Decimal('0.00')
	low_stock = Product.objects.filter(
		is_active=True, quantity_in_stock__lte=F('reorder_level')
	).order_by('quantity_in_stock', 'name')[:6]

	status_rows = invoices.values('status').annotate(total=Count('id'))
	status_data = {status: 0 for status, _ in Document.Status.choices}
	for row in status_rows:
		status_data[row['status']] = row['total']

	category_rows = Product.objects.filter(is_active=True).values(
		'category__name'
	).annotate(total=Sum('quantity_in_stock')).order_by('-total')[:6]
	top_products = DocumentItem.objects.filter(
		document__doc_type=Document.DocType.INVOICE
	).values('product__name').annotate(
		total=Sum('line_total'), quantity=Sum('quantity')
	).order_by('-total')[:5]
	payment_rows = Payment.objects.values('method').annotate(total=Sum('amount')).order_by('-total')

	return {
        'greeting': greeting,
		'total_revenue': invoices.aggregate(total=Sum('total'))['total'] or Decimal('0.00'),
		'current_revenue': current_revenue,
		'revenue_change': revenue_change,
		'current_profit': current_profit,
		'profit_change': profit_change,
		'open_quotation_total': open_quotation_total,
		'open_quotation_count': open_quotations.count(),
		'outstanding': outstanding,
		'invoice_count': invoices.count(),
		'customer_count': Customer.objects.count(),
		'stock_value': stock_value,
		'low_stock': low_stock,
		'recent_invoices': invoices.select_related('customer').order_by('-issue_date', '-created_at')[:7],
		'chart_data': {
			'sales': {
				'labels': [month_abbr[bucket.month] for bucket in months],
				'values': [str(monthly_totals.get(bucket, Decimal('0.00'))) for bucket in months],
			},
			'statuses': {
				'labels': [label for _, label in Document.Status.choices],
				'values': [status_data[key] for key, _ in Document.Status.choices],
			},
			'categories': {
				'labels': [row['category__name'] or 'Uncategorised' for row in category_rows],
				'values': [row['total'] or 0 for row in category_rows],
			},
			'payments': {
				'labels': [dict(Payment.Method.choices).get(row['method'], row['method']) for row in payment_rows],
				'values': [str(row['total'] or Decimal('0.00')) for row in payment_rows],
			},
		},
		'top_products': top_products,
		'report_date': today,
	}


@login_required
def dashboard(request):
	context = _dashboard_context()
	context['is_print_view'] = False
	return render(request, 'home.html', context)


@login_required
def print_report(request):
	context = _dashboard_context()
	context['is_print_view'] = True
	return render(request, 'reports/print_report.html', context)


@login_required
def report_center(request):
	invoices, start_date, end_date = _filtered_invoices(request)
	paid_total = Payment.objects.filter(invoice__in=invoices).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
	metrics = {
		'sales_total': invoices.aggregate(total=Sum('total'))['total'] or Decimal('0.00'),
		'paid_total': paid_total,
		'outstanding': sum((invoice.balance_due for invoice in invoices), Decimal('0.00')),
		'invoice_count': invoices.count(),
		'quotation_count': Document.objects.filter(doc_type=Document.DocType.QUOTATION).count(),
		'average_sale': invoices.aggregate(total=Sum('total'))['total'] or Decimal('0.00'),
	}
	if metrics['invoice_count']:
		metrics['average_sale'] = metrics['sales_total'] / metrics['invoice_count']
	return render(request, 'reports/report_center.html', {
		'metrics': metrics,
		'sales': invoices.order_by('-issue_date', '-created_at')[:20],
		'start_date': start_date,
		'end_date': end_date,
	})


@login_required
def sales_export_csv(request):
	invoices, start_date, end_date = _filtered_invoices(request)
	output = StringIO()
	writer = csv.writer(output)
	writer.writerow(['Invoice', 'Date', 'Customer', 'Status', 'Total', 'Paid', 'Balance'])
	writer.writerows(_sales_rows(invoices))
	response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
	response['Content-Disposition'] = 'attachment; filename="ecohub-sales.csv"'
	return response


@login_required
def sales_export_xlsx(request):
	invoices, start_date, end_date = _filtered_invoices(request)
	headers = ['Invoice', 'Date', 'Customer', 'Status', 'Total', 'Paid', 'Balance']
	return _xlsx_response('ecohub-sales.xlsx', headers, _sales_rows(invoices))
