# from django.conf.urls import url
from django.urls import path
from dashboard import views

urlpatterns = [
    path('', views.index, name='index'),
    path('run_wps_execute', views.run_wps_execute, name='run_wps_execute'),
    path('new', views.new_check, name='new_check'),
    path('checking_tasks.json', views.tasks_json, name='tasks_json')
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()