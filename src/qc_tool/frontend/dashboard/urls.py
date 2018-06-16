# from django.conf.urls import url
from django.urls import path
from dashboard import views

urlpatterns = [
    path('', views.index, name='index'),
    path('data/jobs', views.get_jobs, name='jobs_json'),
    path('data/files', views.get_files_json, name='files_json'),
    path('data/product_type/<product_type_name>/', views.get_product_type_details, name='product_type_details'),
    path('data/product_types/', views.get_product_types, name='product_types'),


    path('files/upload', views.file_upload, name='file_upload'),
    path('files/', views.get_files, name='files'),

    path('run_wps_execute', views.run_wps_execute, name='run_wps_execute'),
    path('new', views.new_job, name='new_job'),
    path('result/<result_uuid>/', views.get_result, name='checking_result'),
    path('status_document/<result_uuid>/', views.get_status_document, name='checking_result'),

]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()