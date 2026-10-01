from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('quotations/', views.quotation_list, name='quotation_list'),
    path('document/<int:pk>/delete-quotation/', views.quotation_delete, name='quotation_delete'),
    path('document/<int:pk>/edit-quotation/', views.quotation_edit, name='quotation_edit'),
    path('create/', views.document_create, name='document_create'),
    path('document/<int:pk>/', views.document_detail, name='document_detail'),
    path('document/<int:pk>/print/', views.document_print, name='document_print'),
    path('document/<int:pk>/receipt/print/', views.receipt_print, name='receipt_print'),
    path('document/<int:pk>/convert/', views.quotation_convert_to_invoice, name='quotation_convert'),
    path('document/<int:pk>/pay/', views.record_payment, name='record_payment'),
    path('api/products/', views.product_search_api, name='product_search_api'),
]
