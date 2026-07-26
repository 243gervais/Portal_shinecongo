from rest_framework.permissions import BasePermission


def _get_profile(user):
    return getattr(user, "userprofile", None)


class IsPortalEmployee(BasePermission):
    message = "Accès réservé aux employés."

    def has_permission(self, request, view):
        user = request.user
        profile = _get_profile(user)
        return bool(
            user
            and user.is_authenticated
            and profile
            and profile.is_employe()
            and profile.site_id
        )


class IsPortalSelfAttendanceUser(BasePermission):
    message = "Accès réservé aux employés et managers rattachés à un site."

    def has_permission(self, request, view):
        user = request.user
        profile = _get_profile(user)
        return bool(
            user
            and user.is_authenticated
            and profile
            and (profile.is_employe() or profile.is_manager())
            and profile.site_id
        )


class IsManagerOrAdmin(BasePermission):
    message = "Accès réservé aux managers et administrateurs."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        profile = _get_profile(user)
        return bool(profile and (profile.is_manager() or profile.is_admin()))
