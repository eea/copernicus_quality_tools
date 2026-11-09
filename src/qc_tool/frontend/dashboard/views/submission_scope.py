"""Permission-intersected queue filters shared by listing and bulk preview."""


def scoped_submission_queue(queryset, query):
    """Apply only explicit identities to an already permission-scoped query."""

    product = query.get("product", "")
    if product:
        queryset = queryset.filter(product_release__product__ident=product)
    for parameter, field in (("release", "product_release_id"), ("delivery", "delivery_id")):
        value = query.get(parameter, "")
        if value:
            if not (value.isascii() and value.isdecimal() and len(value) < 19 and int(value) > 0):
                return queryset.none()
            queryset = queryset.filter(**{field: int(value)})
    return queryset
