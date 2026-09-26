from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class ReferenceGuideViewTests(TestCase):
    def test_guide_requires_authentication(self):
        response = self.client.get(reverse('reference_guide'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_cashier_sees_guide_without_admin_section(self):
        cashier = User.objects.create_user(username='guide-cashier', password='test-password')
        self.client.force_login(cashier)

        response = self.client.get(reverse('reference_guide'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'User Guide')
        self.assertContains(response, 'A few tips before your first transaction')
        self.assertContains(response, 'Start at the dashboard.')
        self.assertContains(response, 'Receive more stock')
        self.assertNotContains(response, 'Create or update a staff account')

    def test_admin_sees_staff_and_reporting_instructions(self):
        admin = User.objects.create_user(
            username='guide-admin',
            password='test-password',
            role=User.Role.ADMIN,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('reference_guide'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create or update a staff account')
        self.assertContains(response, 'Run and export reports')
