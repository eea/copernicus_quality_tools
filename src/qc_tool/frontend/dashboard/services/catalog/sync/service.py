"""Transactional orchestration for idempotent catalog publication."""

from django.db import transaction

from ..contracts import CatalogSyncResult
from .current_pointer import synchronize_current_pointer
from .locks import lock_catalog_sync
from .product_records import synchronize_definitions
from .product_records import synchronize_product
from .release_records import create_release
from .release_records import find_existing_release
from .release_validation import validate_existing_release


def synchronize_product_catalog(snapshot, *, dry_run=False):
    """Publish complete immutable release revisions in one transaction."""

    result = CatalogSyncResult(releases_scanned=len(snapshot.releases))
    with transaction.atomic():
        lock_catalog_sync()
        for release_snapshot in snapshot.releases:
            result = synchronize_release(release_snapshot, result)
        if dry_run:
            transaction.set_rollback(True)
    return result


def synchronize_release(snapshot, result):
    product, result = synchronize_product(snapshot, result)
    definitions, result = synchronize_definitions(snapshot, result)
    release = find_existing_release(snapshot)
    if release is None:
        release, result = create_release(
            snapshot,
            product=product,
            definitions=definitions,
            result=result,
        )
    else:
        validate_existing_release(release, snapshot, product=product)
    return synchronize_current_pointer(release, snapshot, result)
