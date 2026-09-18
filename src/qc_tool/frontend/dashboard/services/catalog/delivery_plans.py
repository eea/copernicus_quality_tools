"""Administrator approval of versioned delivery scopes and review assignments."""

from dataclasses import replace
import hashlib

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from qc_tool.product_units import PRODUCT_UNIT_CODE_MAX_LENGTH
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Product, ProductRelease

from .contracts import CatalogSyncResult, DefinitionSnapshot
from .definition_directory import declared_coverage
from .errors import CatalogError
from .manifest.constants import MAX_PRODUCT_UNITS_PER_RELEASE
from .manifest.coverage import extract_coverage_product_units, naming_unit_scopes, extract_definition_product_unit_codes
from .manifest.release_parser import parse_release_document
from .specification_upload import require_specification_administrator
from .sync.locks import lock_catalog_sync
from .sync.service import synchronize_release


def delivery_plan_managers():
    """Only active product managers can be assigned a new review scope."""

    return get_user_model().objects.filter(
        is_active=True, groups__name=Role.PRODUCT_MANAGER.value,
    ).distinct().order_by(get_user_model().USERNAME_FIELD)


def current_product_manager_ids(product_ident):
    return frozenset(UserProductGrant.objects.filter(
        product_ident=product_ident,
        user__groups__name=Role.PRODUCT_MANAGER.value,
    ).values_list("user_id", flat=True))


def manager_assignment_digest(manager_ids):
    payload = ",".join(str(manager_id) for manager_id in sorted(manager_ids))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def validate_delivery_plan_units(product_unit_codes):
    """Apply the shared product unit identity contract to a bounded explicit plan."""

    if not isinstance(product_unit_codes, (list, tuple)) or len(product_unit_codes) > MAX_PRODUCT_UNITS_PER_RELEASE:
        raise CatalogError("invalid_plan", "The delivery plan contains too many product unit codes.")
    values = []
    for value in product_unit_codes:
        if not isinstance(value, str):
            raise CatalogError("invalid_plan", "Enter one product unit code per line.")
        value = value.strip()
        if (
            not value or len(value) > PRODUCT_UNIT_CODE_MAX_LENGTH
            or any(character in value for character in "*?/\\")
            or value in (".", "..")
        ):
            raise CatalogError(
                "invalid_plan", "product unit codes must be explicit identifiers, without wildcards or path separators.",
            )
        values.append(value)
    codes, sources, _provenance = extract_coverage_product_units(
        {"product_unit_codes": values}, (), state="authoritative",
    )
    return tuple(codes), tuple(sources)


def approve_delivery_plan(
    product_ident, release_id, *, expected_release_id, expected_manager_digest, product_unit_codes,
    actor, product_managers=(),
):
    """Publish a reviewed scope without changing existing QC or submission history."""

    require_specification_administrator(actor)
    codes, sources = validate_delivery_plan_units(product_unit_codes)
    selected_ids = {manager.pk for manager in product_managers}
    with transaction.atomic():
        lock_catalog_sync(wait=False)
        release = (
            ProductRelease.objects.select_related("product")
            .filter(pk=release_id, product__ident=product_ident).first()
        )
        if release is None:
            raise CatalogError("unknown_release", "The delivery plan was not found.")
        if not release.product.is_active:
            raise CatalogError("archived_product", "Restore this product before updating its delivery plan.")
        if expected_release_id != release.pk or not release.is_current:
            raise CatalogError(
                "stale_plan", "This delivery plan has changed. Open the current product page and review its latest plan before saving.",
            )
        latest = ProductRelease.objects.filter(release_key=release.release_key).order_by("-revision").first()
        if latest.pk != release.pk:
            raise CatalogError("stale_plan", "A newer revision exists. Review the latest delivery plan before saving.")
        managers = delivery_plan_managers().filter(pk__in=selected_ids)
        if set(managers.values_list("pk", flat=True)) != selected_ids:
            raise CatalogError("invalid_managers", "Choose active users with the product manager role.")
        snapshots, primary_ident = _definition_snapshots(release)
        _validate_specification_scope(codes, snapshots.values())
        existing_manager_ids = current_product_manager_ids(product_ident)
        if expected_manager_digest != manager_assignment_digest(existing_manager_ids):
            raise CatalogError(
                "stale_managers", "The product manager assignments have changed. Refresh the page before saving.",
            )
        same_scope = (
            release.coverage_state == ProductRelease.CoverageState.AUTHORITATIVE
            and set(release.product_units.values_list("product_unit_code", flat=True)) == set(codes)
        )
        if same_scope:
            if existing_manager_ids != selected_ids:
                _assign_managers(product_ident, selected_ids, existing_manager_ids, actor)
                _audit_plan(release, codes, selected_ids, existing_manager_ids, actor, scope_changed=False)
            return release
        snapshot = parse_release_document(
            {
                "release_key": release.release_key,
                "revision": release.revision + 1,
                "description": release.description,
                "definition_idents": list(snapshots),
                "primary_definition": primary_ident,
                "coverage": {"state": "authoritative", "product_unit_codes": list(sources)},
            },
            product_ident=product_ident,
            product_name=release.product.name,
            product_description=release.product.description,
            definition_loader=snapshots.__getitem__,
            source_kind=release.source_kind,
        )
        snapshot = replace(snapshot, product_unit_provenance="administrator")
        synchronize_release(snapshot, CatalogSyncResult())
        approved = ProductRelease.objects.get(
            release_key=release.release_key, revision=snapshot.revision,
        )
        approved.approved_by = actor
        approved.save(update_fields=("approved_by",))
        _assign_managers(product_ident, selected_ids, existing_manager_ids, actor)
        _audit_plan(approved, codes, selected_ids, existing_manager_ids, actor, scope_changed=True)
        return approved


def _audit_plan(release, codes, selected_ids, previous_ids, actor, *, scope_changed):
    LogEntry.objects.create(
        user=actor,
        content_type=ContentType.objects.get_for_model(Product),
        object_id=str(release.product_id),
        object_repr=str(release.product)[:200],
        action_flag=CHANGE,
        change_message=(
            "{} delivery plan {} revision {} with {} expected product units. "
            "Product manager account IDs: {}; previously: {}."
        ).format(
            "Approved" if scope_changed else "Updated manager assignments for",
            release.release_key, release.revision, len(codes),
            ", ".join(map(str, sorted(selected_ids))) or "none",
            ", ".join(map(str, sorted(previous_ids))) or "none",
        ),
    )


def _definition_snapshots(release):
    links = list(release.definition_links.select_related("qc_definition").order_by("qc_definition__product_ident"))
    primary = [link for link in links if link.is_primary]
    if not links or len(primary) != 1:
        raise CatalogError(
            "missing_specification", "Upload a product specification before approving a delivery plan.",
        )
    snapshots = {
        link.qc_definition.product_ident: DefinitionSnapshot(
            product_ident=link.qc_definition.product_ident,
            description=link.qc_definition.description,
            digest=link.qc_definition.digest,
            document=link.qc_definition.document,
            source_path=link.qc_definition.source_path,
        )
        for link in links
    }
    if len(snapshots) != len(links):
        raise CatalogError("ambiguous_specification", "The product has conflicting specification versions. Review its catalog before approving a plan.")
    return snapshots, primary[0].qc_definition.product_ident


def _assign_managers(product_ident, selected_ids, existing_ids, actor):
    UserProductGrant.objects.filter(
        product_ident=product_ident, user_id__in=existing_ids - selected_ids,
    ).delete()
    for manager_id in selected_ids - existing_ids:
        UserProductGrant.objects.get_or_create(
            product_ident=product_ident, user_id=manager_id,
            defaults={"created_by": actor},
        )


def _validate_specification_scope(codes, definitions):
    """Avoid activating product units that every linked QC specification rejects."""

    supported = set()
    for definition in definitions:
        declared_coverage(definition)
        scopes, _declared, _unbounded = naming_unit_scopes(definition.document)
        finite_scopes = [set(scope) for scope in scopes]
        if any(key in definition.document for key in ("product_units", "product_unit_codes", "aoi_codes")):
            finite_scopes.append(set(extract_definition_product_unit_codes(definition.document)))
        if not finite_scopes:
            # No finite naming check places a known bound on the explicit plan.
            return
        supported.update(set.intersection(*finite_scopes))
    missing = set(codes) - supported
    if missing:
        preview = ", ".join(sorted(missing)[:5])
        raise CatalogError(
            "unsupported_product_units",
            "These product units are outside the specification's naming rules: {}. Upload a specification that supports them before approving this plan.".format(preview),
        )
