"""Product assignment checks shared by delivery registration endpoints."""

from qc_tool.frontend.accounts.services.products import available_product_idents
from qc_tool.frontend.dashboard.access.deliveries import delivery_product_scope_matches
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.delivery_names import DeliveryNameParserUnavailable
from qc_tool.frontend.dashboard.services.products import identify_delivery

from ._resumable.errors import ResumableUploadError


def require_upload_product(access, product_ident):
    """Require an accessible managed product before accepting a delivery."""

    available = available_product_idents()
    allowed = (
        any(access.can_access_product(ident) for ident in available)
        if not product_ident
        else product_ident in available and access.can_access_product(product_ident)
    )
    if not allowed:
        raise _product_denied()


def require_upload_filename(access, filename, *, overwrite_delivery_id=None):
    try:
        identification = identify_delivery(filename)
    except DeliveryNameParserUnavailable as exc:
        raise ResumableUploadError("filename_recognition_unavailable", str(exc), 503) from exc
    if identification.status == "invalid":
        raise ResumableUploadError("delivery_name_invalid", identification.message, 400)
    if identification.status == "unconfigured":
        raise ResumableUploadError("product_not_configured", identification.message, 400)
    if identification.candidates:
        if not any(access.can_access_product(ident) for ident in identification.candidates):
            raise _product_denied()
    else:
        require_upload_product(access, None)
    if overwrite_delivery_id is not None:
        # Include a retired original so interrupted overwrite recovery cannot
        # bypass a product assignment revoked since its initial request.
        original = Delivery.objects.filter(
            pk=overwrite_delivery_id, user_id=access.user_id,
        ).first()
        if original is not None:
            require_upload_delivery(access, original)
    return identification


def require_upload_delivery(access, delivery):
    if not delivery_product_scope_matches(access, delivery):
        raise _product_denied()


def _product_denied():
    return ResumableUploadError(
        "product_permission_denied",
        "You can upload deliveries only for products assigned to your account. "
        "Contact an administrator to update your product assignments.",
        403,
    )
