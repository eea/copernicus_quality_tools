from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^run_wps_execute', views.run_wps_execute, name='run_wps_execute'),
    url(r'^new$', views.new_check, name='new_check'),
    url(r'^checking_tasks\.json$', views.tasks_json, name='tasks_json'),
    url(r'^$', views.job_list, name='job_list'),
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()