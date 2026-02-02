from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("tenant-info/", views.tenant_info),
    path("auth/login/", views.LoginView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", views.RefreshTokenView.as_view(), name="token_refresh"),
]
