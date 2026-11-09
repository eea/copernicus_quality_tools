"""Project measured execution facts into the separate run provenance record."""

from qc_tool.jobs import record_job_context
from qc_tool.product_security import normalize_product_ident


def start_provenance(paths, result, *, is_s3, original_zip_sha256=None):
    record_job_context(
        paths, product_ident=normalize_product_ident(result["product_ident"]),
        input_filename=result["filename"], input_source="s3" if is_s3 else "local",
        input_sha256=original_zip_sha256,
        qc_tool_version=result["qc_tool_version"].strip(),
        started_at=result["job_start_date"], status="running",
    )


def boundary_provenance(paths, generation):
    record_job_context(
        paths, boundary_mode="managed" if generation.managed else "legacy",
        boundary_generation_id=generation.generation_id if generation.managed else None,
    )


def downloaded_zip_provenance(paths, status):
    # This observation is set by the shared downloader after hashing the whole
    # original ZIP, before extraction. It is not the QC result's component hash.
    digest = getattr(status, "original_zip_sha256", None)
    if digest is not None:
        record_job_context(paths, input_sha256=digest)


def finish_provenance(paths, result):
    period = result.get("reference_year")
    unit = result.get("product_unit_code") or result.get("aoi_code")
    record_job_context(
        paths, finished_at=result["job_finish_date"], status=result["status"],
        reference_period=str(period) if period is not None and str(period) else None,
        product_unit_code=str(unit) if unit is not None and str(unit) else None,
        reported_input_hash=result.get("hash"),
        input_hash_files=list(result.get("hash_files") or []),
    )
