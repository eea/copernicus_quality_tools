# from django.conf.urls import url
from django.urls import path
from django.urls import re_path
from qc_tool.frontend.dashboard import views

urlpatterns = [

    path("", views.deliveries, name="deliveries"),

    re_path("data/delivery/list/", views.get_deliveries_json, name="deliveries_json"),

    path("delivery/delete/", views.delivery_delete, name="delivery_delete"),
    path("delivery/submit/", views.submit_delivery_to_eea, name="delivery_submit"),

    path("jobs/<filename>/", views.jobs, name="jobs"),
    path("data/jobs/<filename>/", views.get_jobs, name="jobs_json"),

    path("data/product/<product_ident>/", views.get_product_info, name="product_info_json"),
    path("data/product_config/<product_ident>/", views.get_product_config, name="product_config_json"),
    path("data/product_list/", views.get_product_list, name="product_list_json"),
    path("data/result/<job_uuid>/", views.get_result_json, name="result_json"),
    path("data/wps_status/<job_uuid>/", views.get_wps_status_xml, name="wps_status_xml"),

    path('upload/', views.file_upload, name='file_upload'),

    path("run_wps_execute", views.run_wps_execute, name="run_wps_execute"),

    re_path("save_job/", views.save_job, name="save_job"),

    path("start_job/<int:delivery_id>/", views.start_job, name="start_job"),
    path("result/<job_uuid>/", views.get_result, name="show_result"),
    path("error_table/<job_uuid>/<error_table_filename>/", views.get_error_table, name="get_error_table")
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()

views.startup()