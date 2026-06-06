from django.core.paginator import Paginator


def paginate_queryset(request, queryset, *, per_page=20, page_param="page"):
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get(page_param) or 1
    return paginator.get_page(page_number)
