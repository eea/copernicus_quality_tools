# from django.conf.urls import url
from django.urls import path
from django.urls import re_path
from qc_tool.frontend.dashboard import views

urlpatterns = [

    path("", views.deliveries, name="deliveries"),

    re_path("data/delivery/list/", views.get_deliveries_json, name="deliveries_json"),

    path("delivery/delete/", views.delivery_delete, name="delivery_delete"),
    path("delivery/submit/", views.submit_delivery_to_eea, name="delivery_submit"),
    path("delivery/refresh_status/<job_uuid>/", views.refresh_job_status, name="delivery_refresh_status"),

    path("data/job_info/<product_ident>/", views.get_job_info, name="job_info_json"),
    path("data/product_definition/<product_ident>/", views.get_product_definition, name="product_definition_json"),
    path("data/product_list/", views.get_product_list, name="product_list_json"),
    path("data/report/<job_uuid>/report.json", views.get_job_report, name="job_report_json"),
    path("data/report/<job_uuid>/report.pdf", views.get_pdf_report, name="job_report_pdf"),
    path("data/wps_status/<job_uuid>/", views.get_wps_status_xml, name="wps_status_xml"),

    path('upload/', views.file_upload, name='file_upload'),

    path("data/boundaries/<boundary_type>/", views.get_boundaries_json, name="boundaries_json"),
    path('boundaries/', views.boundaries, name='boundaries'),
    path('boundaries_upload/', views.boundaries_upload, name='boundaries_upload'),

    path("run_wps_execute", views.run_wps_execute, name="run_wps_execute"),

    path("start_job/<int:delivery_id>/", views.start_job, name="start_job"),
    path("result/<job_uuid>/", views.get_result, name="show_result"),
    path("attachment/<job_uuid>/<attachment_filename>/", views.get_attachment, name="get_attachment")
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()
