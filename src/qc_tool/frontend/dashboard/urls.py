# from django.conf.urls import url
from django.urls import path
from dashboard import views

urlpatterns = [
    path('', views.index, name='index'),
    path('files', views.get_files, name='files'),
    path('product_types', views.get_product_types, name='product_types'),
    path('product_type_details/<product_type>/', views.get_product_type_details, name='product_type_details'),
    path('product_type_table/<product_type>/', views.get_product_type_table, name='product_type_table'),
    path('run_wps_execute', views.run_wps_execute, name='run_wps_execute'),
    path('new', views.new_check, name='new_check'),
    path('checking_sessions', views.get_checking_sessions, name='checking_sessions_json')
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()