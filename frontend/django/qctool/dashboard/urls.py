from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^wps_execute_test', views.wps_execute_test, name='wps_execute_test'),
    url(r'^jobs\.json$', views.jobs_json, name='jobs_json'),
    url(r'^$', views.job_list, name='job_list'),
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()