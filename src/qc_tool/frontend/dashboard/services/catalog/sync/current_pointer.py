"""Mutable current-release pointer management."""

from dataclasses import replace

from qc_tool.frontend.dashboard.models import ProductRelease


def synchronize_current_pointer(release, snapshot, result):
    if snapshot.is_current and not release.is_current:
        ProductRelease.objects.filter(
            release_key=snapshot.release_key,
            is_current=True,
        ).exclude(pk=release.pk).update(is_current=False)
        release.is_current = True
        release.save(update_fields=("is_current",))
    elif not snapshot.is_current and release.is_current:
        release.is_current = False
        release.save(update_fields=("is_current",))
    else:
        return result
    from ..readiness import invalidate_product_readiness

    invalidate_product_readiness(release.product_id)
    return replace(
        result,
        current_pointers_changed=result.current_pointers_changed + 1,
    )
