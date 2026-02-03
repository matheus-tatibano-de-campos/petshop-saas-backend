from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("customers", views.CustomerViewSet, basename="customer")
router.register("pets", views.PetViewSet, basename="pet")
router.register("services", views.ServiceViewSet, basename="service")

urlpatterns = [
    path("health/", views.health),
    path("appointments/pre-book/", views.PreBookAppointmentView.as_view(), name="pre_book_appointment"),
    path("tenant-info/", views.tenant_info),
    path("auth/login/", views.LoginView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", views.RefreshTokenView.as_view(), name="token_refresh"),
    path("tenants/", views.TenantCreateView.as_view(), name="tenant_create"),
    path("", include(router.urls)),
]
