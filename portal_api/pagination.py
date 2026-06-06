from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class PortalPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 50

    def get_paginated_response(self, data, extra=None):
        payload = OrderedDict(
            [
                ("count", self.page.paginator.count),
                ("num_pages", self.page.paginator.num_pages),
                ("page", self.page.number),
                ("page_size", self.get_page_size(self.request)),
                ("has_next", self.page.has_next()),
                ("has_previous", self.page.has_previous()),
                ("next", self.get_next_link()),
                ("previous", self.get_previous_link()),
                ("results", data),
            ]
        )
        if extra:
            payload.update(extra)
        return Response(payload)
