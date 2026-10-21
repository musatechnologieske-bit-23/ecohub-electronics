from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0003_document_vat_enabled'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='documentitem',
            options={'ordering': ['id']},
        ),
    ]
