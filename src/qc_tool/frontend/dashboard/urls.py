# from django.conf.urls import url
from django.urls import path
from django.urls import re_path
from qc_tool.frontend.dashboard import views

urlpatterns = [

    path("", views.deliveries, name="deliveries"),

    path("data/delivery/list/", views.get_deliveries_json, name="deliveries_json"),
    path("data/job_history/<delivery_id>/", views.get_job_history_json, name="job_history_json"),
    path("data/delivery/file/<delivery_id>/", views.download_delivery_file, name="download_delivery_file"),

    path("delivery/delete/", views.delivery_delete, name="delivery_delete"),
    path("delivery/submit/", views.submit_delivery_to_eea, name="delivery_submit"),

    path("data/job_info/<product_ident>/", views.get_job_info, name="job_info_json"),
    path("data/product_definition/<product_ident>/", views.get_product_definition, name="product_definition_json"),
    path("data/product_list/", views.get_product_list, name="product_list_json"),
    path("data/report/<job_uuid>/report.json", views.get_job_report, name="job_report_json"),
    path("data/report/<job_uuid>/report.pdf", views.get_pdf_report, name="job_report_pdf"),

    path("upload/", views.file_upload, name="file_upload"),

    path("job_history/<delivery_id>/", views.job_history_page, name="job_history"),
    path("job/delete/", views.job_delete, name="job_delete"),
    path("job/update/<job_uuid>/", views.update_job, name="update_job"),

    path("data/boundaries/<boundary_type>/", views.get_boundaries_json, name="boundaries_json"),
    path("boundaries/", views.boundaries, name="boundaries"),
    path("boundaries_upload/", views.boundaries_upload, name="boundaries_upload"),

    path("create_job", views.create_job, name="create_job"),
    path("pull_job", views.pull_job, name="pull_job"),

    # path("setup_job/<int:delivery_id>", views.setup_job, name="setup_job"),
    path("setup_job", views.setup_job, name="setup_job"),
    path("result/<job_uuid>", views.get_result, name="show_result"),
    path("attachment/<job_uuid>/<attachment_filename>/", views.get_attachment, name="get_attachment")
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()

# On initial startup: create token for worker authentication.
from qc_tool.common import create_worker_token
create_worker_token()
