"""
URL configuration for Ecohub project.
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from . import views

urlpatterns = [
    path('health/', views.health, name='health'),
    path('guide/', views.reference_guide, name='reference_guide'),
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('customers/', include('customers.urls')),
    path('sales/', include('sales.urls')),
    path('reports/', include('reports.urls')),
    path('login/', lambda request: redirect('accounts:login'), name='login'),
]
