"""Create synthetic browser fixtures inside the harness's disposable container."""

import json
import os
from pathlib import Path
from zipfile import ZipFile

import django


ROOT = Path("/tmp/qc-tool-browser")


def main():
    # This script is deliberately unsuitable for an operator's existing target.
    if (
        os.environ.get("QC_TOOL_ENVIRONMENT") != "test"
        or os.environ.get("DB_ENGINE") != "sqlite"
        or os.environ.get("FRONTEND_DB_PATH") != str(ROOT / "frontend.sqlite3")
    ):
        raise SystemExit("Browser fixtures require the isolated harness database.")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qc_tool.frontend.settings")
    django.setup()

    from django.contrib.auth import get_user_model

    get_user_model().objects.create_superuser(
        username="browser-admin", email="browser@example.test",
        password="disposable-browser-test-password",
    )
    fixtures = ROOT / "fixtures"
    fixtures.mkdir()
    (ROOT / "empty-product-definitions").mkdir()
    for browser in ("chromium", "firefox"):
        for selection in ("chooser", "drop"):
            ident = f"ci_smoke_{browser}_{selection}"
            document = {
                "description": f"Synthetic browser smoke {browser} {selection}",
                "steps": [{
                    "check_ident": "qc_tool.vector.naming", "required": True,
                    "parameters": {"reference_year": "2026", "aoi_codes": ["CZ"]},
                }],
            }
            (fixtures / f"{ident}.json").write_text(json.dumps(document), encoding="utf-8")
            with ZipFile(fixtures / f"{ident}_CZ.zip", "w") as archive:
                archive.writestr("synthetic.txt", "Synthetic upload bytes; no QC is executed.\n")

    # The upload service validates archive structure, paths and retention. Real
    # geospatial content is covered by worker tests, not this transport smoke.
    with ZipFile(fixtures / "boundaries.zip", "w") as archive:
        archive.writestr("raster/smoke.tif", b"synthetic-raster-placeholder")
        archive.writestr("vector/smoke.gpkg", b"synthetic-vector-placeholder")


if __name__ == "__main__":
    main()
