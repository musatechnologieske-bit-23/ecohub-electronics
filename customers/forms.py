from django import forms
from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'account_number', 'phone', 'email', 'kra_pin', 'address', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'block w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm',
                'placeholder': 'Customer or company name',
            }),
            'account_number': forms.TextInput(attrs={
                'class': 'block w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm',
                'placeholder': 'e.g. ACC-0012',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'block w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm',
                'placeholder': 'e.g. +254 712 345 678',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'block w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm',
                'placeholder': 'customer@example.com',
            }),
            'kra_pin': forms.TextInput(attrs={
                'class': 'block w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm uppercase',
                'placeholder': 'e.g. A000000000A',
                'autocomplete': 'off',
            }),
            'address': forms.Textarea(attrs={
                'class': 'block w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm',
                'rows': 3,
                'placeholder': 'Shop location, street, city...',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'block w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm',
                'rows': 2,
                'placeholder': 'Customer preferences, tax PIN, or delivery instructions...',
            }),
        }
