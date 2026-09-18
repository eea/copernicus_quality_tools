"""Product assignment checks shared by delivery registration endpoints."""

from pathlib import Path

from qc_tool.frontend.dashboard.access.deliveries import delivery_product_scope_matches
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.services.products import guess_product_ident

from ._resumable.errors import ResumableUploadError


def require_upload_product(access, product_ident):
    """Allow unclassified ZIPs only while the account has an assigned product."""

    allowed = (
        access.has_product_assignments
        if not product_ident
        else access.can_access_product(product_ident)
    )
    if not allowed:
        raise _product_denied()


def require_upload_filename(access, filename, *, overwrite_delivery_id=None):
    require_upload_product(access, guess_product_ident(Path(filename)))
    if overwrite_delivery_id is not None:
        # Include a retired original so interrupted overwrite recovery cannot
        # bypass a product assignment revoked since its initial request.
        original = Delivery.objects.filter(
            pk=overwrite_delivery_id, user_id=access.user_id,
        ).first()
        if original is not None:
            require_upload_delivery(access, original)


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
