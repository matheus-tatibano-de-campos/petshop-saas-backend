from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """Allows access only to users with role OWNER or superuser."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or getattr(user, "role", None) == "OWNER")
        )


class IsOwnerOrAttendant(BasePermission):
    """Allows access to OWNER or ATTENDANT roles (and superusers)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or getattr(user, "role", None) in ("OWNER", "ATTENDANT")
            )
        )
