from django.core.exceptions import ObjectDoesNotExist


def legacy_delivery_region_code(delivery):
    """Resolve a delivery region through its owner's legacy profile field.

    This compatibility seam can be replaced when deliveries reference product units
    directly. Region matching intentionally remains exact.
    """

    try:
        owner_profile = delivery.user.userprofile
    except (AttributeError, ObjectDoesNotExist):
        return None
    return getattr(owner_profile, "country", None)
