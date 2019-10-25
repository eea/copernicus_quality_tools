from django.urls import path

from . import views

urlpatterns = [
    path('', views.resumable_upload, name='resumable-upload'),
]
