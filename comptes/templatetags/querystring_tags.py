from django import template


register = template.Library()


@register.simple_tag(takes_context=True)
def page_querystring(context, page_param, page_number):
    request = context.get("request")
    if request is None:
        return ""

    params = request.GET.copy()
    params[page_param] = page_number
    return params.urlencode()
