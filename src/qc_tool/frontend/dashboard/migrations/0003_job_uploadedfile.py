# Generated by Django 2.0.4 on 2018-07-02 06:41

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('dashboard', '0002_auto_20180629_1400'),
    ]

    operations = [
        migrations.CreateModel(
            name='Job',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('product_ident', models.CharField(max_length=64, null=True)),
                ('start', models.DateTimeField(blank=True, null=True)),
                ('end', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(max_length=64)),
                ('status_document_path', models.CharField(max_length=500)),
            ],
        ),
        migrations.CreateModel(
            name='UploadedFile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('filename', models.CharField(max_length=500)),
                ('filepath', models.CharField(max_length=500)),
                ('product_ident', models.CharField(max_length=64)),
                ('date_uploaded', models.DateTimeField(default=django.utils.timezone.now)),
                ('date_last_checked', models.DateTimeField(null=True)),
                ('date_submitted', models.DateTimeField(null=True)),
                ('status', models.CharField(max_length=64)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]