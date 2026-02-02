from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("tenant-info/", views.tenant_info),
]
