# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.apps import AppConfig


class QualityControlWorkspaceConfig(AppConfig):
    """Stable Django app label for the QC workspace application."""

    name = "qc_tool.frontend.dashboard"
    label = "dashboard"
    verbose_name = "QC workspace"
