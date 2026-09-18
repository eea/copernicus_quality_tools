"""Administrator-managed specification revisions and archival."""

import ast
from dataclasses import dataclass
from functools import lru_cache
import logging
from pathlib import Path

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q

import qc_tool.common as common
from qc_tool.product_security import normalize_product_ident
from qc_tool.frontend.dashboard.models import Product, ProductRelease, QcDefinition, Job
from qc_tool.frontend.accounts.authorization import access_for

from .contracts import CatalogSyncResult, DefinitionSnapshot
from .definition_directory import declared_coverage
from .definition_import import definition_release_snapshot
from .errors import CatalogError
from .manifest.definitions import MAX_DEFINITION_BYTES, parse_definition_snapshot
from .revisions import store_definition
from .sync.locks import lock_catalog_sync
from .sync.service import synchronize_release
from .upload_storage import publish_specification, publish_specification_state, staged_specification


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpecificationUpload:
    definition: DefinitionSnapshot
    payload: bytes


@dataclass(frozen=True)
class SpecificationUploadResult:
    product_ident: str
    created: bool


def read_specification_upload(uploaded_file):
    name = uploaded_file.name
    if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".json"):
        raise CatalogError("invalid_filename", "Choose a product specification with a .json filename.")
    ident = normalize_product_ident(name[:-5])
    if ident is None:
        raise CatalogError(
            "invalid_product_ident",
            "Use a filename of up to 64 ASCII letters, digits, dots, underscores or hyphens before .json, starting with a letter or digit. The names list, upload and submissions are reserved.",
        )
    if uploaded_file.size > MAX_DEFINITION_BYTES:
        raise CatalogError("definition_too_large", "The JSON file must be 1 MiB or smaller.")
    payload = uploaded_file.read(MAX_DEFINITION_BYTES + 1)
    if len(payload) > MAX_DEFINITION_BYTES:
        raise CatalogError("definition_too_large", "The JSON file must be 1 MiB or smaller.")
    definition = parse_definition_snapshot(ident, payload, source_path="upload:" + ident + ".json")
    steps = definition.document["steps"]
    if not steps:
        raise CatalogError("invalid_checks", "The specification must include at least one QC check.")
    supported = _supported_checks()
    for number, step in enumerate(steps, start=1):
        if step["check_ident"] not in supported or "required" not in step:
            raise CatalogError(
                "invalid_checks",
                "Step {} must reference an installed raster/vector QC check and declare required as true or false.".format(number),
            )
    declared_coverage(definition)
    return SpecificationUpload(definition=definition, payload=payload)


@lru_cache(maxsize=1)
def _supported_checks():
    """Discover packaged checks without importing or executing uploaded names."""

    root = Path(common.__file__).parent
    checks = set()
    for family in ("raster", "vector"):
        for path in (root / family).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if any(isinstance(node, ast.FunctionDef) and node.name == "run_check" for node in tree.body):
                checks.add("qc_tool.{}.{}".format(family, path.stem))
    return frozenset(checks)


def require_specification_administrator(actor):
    if not access_for(actor).is_administrator:
        raise PermissionDenied("Only administrators can manage product specifications.")


def add_product_specification(upload, *, actor):
    require_specification_administrator(actor)
    definition = upload.definition
    ident = definition.product_ident
    coverage = declared_coverage(definition)
    try:
        with staged_specification(common.CONFIG["work_dir"], upload.payload) as (directory, staged):
            with transaction.atomic(durable=True):
                lock_catalog_sync(wait=False)
                latest = _editable_release(ident)
                product = Product.objects.filter(ident=ident).first()
                was_inactive = product is not None and not product.is_active
                matching_current = bool(
                    latest and latest.is_current
                    and latest.source_kind == ProductRelease.SourceKind.UPLOAD
                    and latest.definition_links.filter(qc_definition__digest=definition.digest).exists()
                )
                created = not matching_current or was_inactive
                if created:
                    _require_no_active_jobs(ident)
                    snapshot = definition_release_snapshot(
                        definition, coverage,
                        latest.release_key if latest else "definition:" + ident,
                        latest.revision + 1 if latest else 1,
                        source_kind="upload",
                    )
                    synchronize_release(snapshot, CatalogSyncResult())
                    product = Product.objects.get(ident=ident)
                    if not product.is_active:
                        product.is_active = True
                        product.save(update_fields=("is_active", "updated_at"))
                    _audit(actor, product, CHANGE if latest else ADDITION,
                           "Uploaded specification SHA-256 " + definition.digest)
                else:
                    store_definition(definition)
            # Until this atomic pointer is switched, new jobs check that the
            # runtime digest agrees with the committed upload release.
            publish_specification(staged, directory, ident, definition.digest, upload.payload)
    except OSError as exc:
        logger.exception("Product specification storage failed for %s", ident)
        raise CatalogError(
            "specification_storage_unavailable",
            "The specification could not be made available to QC workers. Check shared storage and upload the same file again to complete it.",
        ) from exc
    return SpecificationUploadResult(product_ident=ident, created=created)


def remove_product_specification(ident, *, actor):
    require_specification_administrator(actor)
    ident = normalize_product_ident(ident)
    if ident is None:
        raise CatalogError("unknown_product", "Product not found.")
    try:
        with staged_specification(common.CONFIG["work_dir"]) as (directory, _staged):
            with transaction.atomic(durable=True):
                lock_catalog_sync(wait=False)
                _editable_release(ident)
                _require_no_active_jobs(ident)
                product = Product.objects.filter(ident=ident).first()
                if product is None:
                    raise CatalogError("unknown_product", "Product not found.")
                if product.is_active:
                    from .readiness import invalidate_product_readiness

                    product.is_active = False
                    product.save(update_fields=("is_active", "updated_at"))
                    invalidate_product_readiness(product.pk)
                    _audit(actor, product, DELETION, "Stopped product from active QC use; revision history retained.")
            publish_specification_state(directory, ident, {"active": False})
    except OSError as exc:
        logger.exception("Product specification removal storage failed for %s", ident)
        raise CatalogError(
            "specification_storage_unavailable",
            "The product was stopped in the catalog, but shared storage could not be updated. Retry stopping to finish it.",
        ) from exc


def _editable_release(ident):
    releases = ProductRelease.objects.filter(
        Q(product__ident=ident) | Q(definition_links__qc_definition__product_ident=ident)
    ).select_related("product").distinct()
    keys = list(releases.order_by("release_key").values_list("release_key", flat=True).distinct()[:2])
    latest = releases.order_by("-revision").first()
    if len(keys) > 1 or (latest and (
        latest.product.ident != ident
        or latest.definition_links.count() != 1
        or not latest.definition_links.filter(qc_definition__product_ident=ident).exists()
    )):
        raise CatalogError(
            "grouped_product",
            "This specification belongs to a grouped release. Manage its versions through the reviewed catalog manifest.",
        )
    return latest


def _require_no_active_jobs(ident):
    if Job.objects.filter(
        product_ident__iexact=ident,
        job_status__in=(common.JOB_WAITING, common.JOB_RUNNING),
    ).exists():
        raise CatalogError(
            "specification_in_use",
            "This specification has queued or running QC jobs. Finish those jobs before replacing or removing it.",
        )


def _audit(actor, product, action, message):
    LogEntry.objects.create(
        user=actor,
        content_type=ContentType.objects.get_for_model(Product),
        object_id=str(product.pk),
        object_repr=str(product)[:200],
        action_flag=action,
        change_message=message,
    )
