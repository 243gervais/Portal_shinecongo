from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def get_profile_role(user):
    if not user.is_authenticated:
        return ""
    if user.is_superuser:
        return "ADMIN"
    profile = getattr(user, "userprofile", None)
    return profile.role if profile else ""


def is_mobile_admin(user):
    return user.is_authenticated and (user.is_superuser or get_profile_role(user) == "ADMIN")


def is_mobile_manager(user):
    return user.is_authenticated and get_profile_role(user) in {"ADMIN", "MANAGER"}


def is_field_associate(user):
    return user.is_authenticated and get_profile_role(user) == "EMPLOYE"


def manager_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not is_mobile_manager(request.user):
            messages.error(request, "Acces reserve aux managers et administrateurs.")
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


def mobile_login_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        return view_func(request, *args, **kwargs)

    return wrapped

