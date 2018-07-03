# Generated by Django 2.0.4 on 2018-07-02 10:17

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('dashboard', '0009_auto_20180702_0825'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='file',
            field=models.ForeignKey(default=None, on_delete=django.db.models.deletion.CASCADE, to='dashboard.UploadedFile'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='job',
            name='user',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]