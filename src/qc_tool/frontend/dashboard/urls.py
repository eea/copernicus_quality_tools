from django.urls import path
from qc_tool.frontend.dashboard import views

urlpatterns = [

    path("", views.deliveries, name="deliveries"),

    path("api/", views.api_homepage, name="api_homepage"),
    path("api/register-delivery", views.api_register_delivery, name="api_register_delivery"),
    path("api/register-delivery-s3", views.api_register_delivery_s3, name="api_register_delivery_s3"),
    path("api/delivery-list", views.api_delivery_list, name="api_delivery_list"),
    path("api/product-list", views.api_product_list, name="api_product_list"),
    path("api/product-info/<product_ident>", views.api_product_info, name="api_product_info"),
    path("api/create-job", views.api_create_job, name="api_create_job"),
    path("api/job-result/<job_uuid>", views.api_job_result, name="api_job_result"),
    path("api/job-result-pdf/<job_uuid>", views.api_job_result_pdf, name="api_job_result_pdf"),
    path("api/job-history/<delivery_id>", views.api_job_history, name="api_job_history"),
    path("api/submit-delivery-to-eea", views.api_submit_delivery_to_eea, name="api_submit_delivery_to_eea"),

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

    path("upload/", views.resumable_upload_page, name="file_upload"),
    path("resumable_upload/", views.resumable_upload, name="resumable_upload"),

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
    path("attachment/<job_uuid>/<attachment_filename>/", views.get_attachment, name="get_attachment"),

    path("announcement/", views.announcement, name="announcement")
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()

# On initial startup: create token for worker authentication.
from qc_tool.common import create_worker_token
create_worker_token()
