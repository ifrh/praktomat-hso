# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2022-08-18 14:02
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0009_Task_dynamic_upload_waiting_time_Python3_Python2'),
    ]

    operations = [
        migrations.AlterField(
            model_name='task',
            name='submission_date',
            field=models.DateTimeField(help_text='The time up until the user has time to complete the task. This time will be extended by the duration configured with the deadline tolerance setting for those who just missed the deadline.'),
        ),
    ]