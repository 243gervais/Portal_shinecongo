from comptes.admin_inbox import get_admin_inbox_counts


def admin_inbox_badge(request):
    return get_admin_inbox_counts(request.user)
