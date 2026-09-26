from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=200, help_text="Full name or company name")
    account_number = models.CharField(max_length=50, blank=True, default='', help_text="Customer account number shown on quotations and invoices")
    phone = models.CharField(max_length=50, blank=True, default='', help_text="Phone / Mobile contact")
    email = models.EmailField(blank=True, default='', help_text="Email address")
    kra_pin = models.CharField(max_length=20, blank=True, default='', help_text="Customer KRA PIN")
    address = models.TextField(blank=True, default='', help_text="Physical or postal address")
    notes = models.TextField(blank=True, default='', help_text="Optional internal notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        if self.phone:
            return f"{self.name} ({self.phone})"
        return self.name
