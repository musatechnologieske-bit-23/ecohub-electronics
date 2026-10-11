from django.db import migrations, models


def preserve_existing_quotation_vat(apps, schema_editor):
    Document = apps.get_model('sales', 'Document')
    Document.objects.filter(doc_type='quotation').update(vat_enabled=True)


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0002_document_quotation_payment_term'),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='vat_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            preserve_existing_quotation_vat,
            migrations.RunPython.noop,
        ),
    ]
