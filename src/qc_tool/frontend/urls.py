"""qctool URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.11/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""
from django.urls import include
from django.urls import path
from django.contrib import admin
from django.contrib.auth.views import LogoutView

from qc_tool.frontend.accounts.forms.authentication import AccountAdminAuthenticationForm
from qc_tool.frontend.accounts.views.sessions import AdminLoginView

from qc_tool.frontend.dashboard.views.admin_maintenance import maintenance_control
from qc_tool.frontend.dashboard.views.admin_database import database_record, database_records
from qc_tool.frontend.dashboard.views.admin_users import user_management
from qc_tool.frontend.dashboard.views.boundaries import legacy_boundaries_redirect
from qc_tool.frontend.dashboard.views.admin_storage import (
    storage_home, storage_file, storage_download, storage_trash, storage_action, storage_archive, storage_connection_guide,
)
from qc_tool.frontend.dashboard.views.admin_data_transfer import (
    data_transfer, data_transfer_download, data_transfer_status,
)

urlpatterns = [
    path(
        'admin/login/',
        AdminLoginView.as_view(
            template_name='admin/qc_tool_login.html',
            authentication_form=AccountAdminAuthenticationForm,
            next_page='admin:index',
            extra_context={
                'title': 'Sign in',
                'site_header': admin.site.site_header,
                'site_title': admin.site.site_title,
                'has_permission': False,
            },
        ),
        name='admin_login',
    ),
    path(
        'admin/logout/',
        admin.site.admin_view(LogoutView.as_view(next_page='admin_login', redirect_field_name=None)),
        name='admin_logout',
    ),
    path(
        'admin/maintenance/',
        admin.site.admin_view(maintenance_control),
        name='admin_maintenance',
    ),
    path('admin/database/', admin.site.admin_view(data_transfer), name='admin_database'),
    path('admin/maintenance/backups/', admin.site.admin_view(data_transfer), {'default_task': 'backups'}, name='admin_data_transfer'),
    path('admin/maintenance/backups/export/', admin.site.admin_view(data_transfer), {'default_task': 'export', 'workflow': 'export'}, name='admin_backup_export'),
    path('admin/maintenance/backups/import/', admin.site.admin_view(data_transfer), {'default_task': 'import', 'workflow': 'import'}, name='admin_backup_import'),
    path('admin/users/', admin.site.admin_view(user_management), name='admin_user_management'),
    path('admin/storage/', admin.site.admin_view(storage_home), name='admin_storage'),
    path('admin/storage/file/', admin.site.admin_view(storage_file), name='admin_storage_file'),
    path('admin/storage/download/', admin.site.admin_view(storage_download), name='admin_storage_download'),
    path('admin/storage/archive/', admin.site.admin_view(storage_archive), name='admin_storage_archive'),
    path('admin/storage/connection-guide/', admin.site.admin_view(storage_connection_guide), name='admin_storage_connection_guide'),
    path('admin/storage/trash/', admin.site.admin_view(storage_trash), name='admin_storage_trash'),
    path('admin/storage/action/', admin.site.admin_view(storage_action), name='admin_storage_action'),
    path('admin/database/records/<str:table>/', admin.site.admin_view(database_records), name='admin_database_records'),
    path('admin/database/records/<str:table>/<str:pk>/', admin.site.admin_view(database_record), name='admin_database_record'),
    path('admin/maintenance/backups/<str:operation_id>/status/', admin.site.admin_view(data_transfer_status), name='admin_data_transfer_status'),
    path('admin/database/<str:operation_id>/status/', admin.site.admin_view(data_transfer_status), name='admin_data_transfer_status_database_legacy'),
    path('admin/maintenance/backups/<str:operation_id>/download/', admin.site.admin_view(data_transfer_download), name='admin_data_transfer_download'),
    path('admin/database/<str:operation_id>/download/', admin.site.admin_view(data_transfer_download), name='admin_data_transfer_download_database_legacy'),
    path('admin/boundaries/', include('qc_tool.frontend.dashboard.urls.boundaries')),
    path('admin/notifications/', include('qc_tool.frontend.dashboard.urls.notifications')),
    # Direct aliases preserve reviewed POST bodies, query strings and Admin
    # authorization. New navigation always uses the canonical reverse names.
    path('admin/database', admin.site.admin_view(data_transfer), name='admin_data_transfer_no_slash'),
    path('admin/data-transfer/', admin.site.admin_view(data_transfer), name='admin_data_transfer_legacy'),
    path('admin/data-transfer/<str:operation_id>/status/', admin.site.admin_view(data_transfer_status), name='admin_data_transfer_status_legacy'),
    path('admin/data-transfer/<str:operation_id>/download/', admin.site.admin_view(data_transfer_download), name='admin_data_transfer_download_legacy'),
    path('admin/', admin.site.urls),
    path('boundaries/', legacy_boundaries_redirect, {"route_name": "boundaries"}, name='boundaries_legacy'),
    path('boundaries/upload/', legacy_boundaries_redirect, {"route_name": "boundaries_upload"}, name='boundaries_upload_legacy'),
    path('', include('qc_tool.frontend.accounts.urls')),
    path('', include('qc_tool.frontend.dashboard.urls')),
]

handler403 = "qc_tool.frontend.accounts.views.errors.permission_denied"
handler404 = "qc_tool.frontend.accounts.views.errors.page_not_found"
