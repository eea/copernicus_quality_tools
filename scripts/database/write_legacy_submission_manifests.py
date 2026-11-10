import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

import psycopg2

from create_legacy_publication_submissions import LEGACY_DIGEST, PLACEHOLDER_PREFIX, SUBMISSION_DIR
from legacy_db import DB_CONFIG


# Writes the submission-manifest.json that QC Tool requires in every published
# submission folder, and replaces the placeholder artifact digest of the legacy
# submission by the digest of that manifest. Without it the submission page shows
# "Submission files are unavailable". Run it after the submission folders are in
# SUBMISSION_DIR and linked (create_legacy_publication_submissions.py --link-folders).
#
# The manifest has the format of qc_tool ... publication/manifest.py (schema 2):
# canonical JSON with the SHA-256 of the same body without 'artifact_sha256' in
# it. The files of the folder are listed as they are now; downloads verify each
# file against that listing. A folder written by this script is not changed
# again unless the submission is imported anew (its digest is the placeholder
# again). Re-running the script is safe: submissions with a real digest are skipped.
#
# Note: other scripts of this import identify imported submissions by the
# placeholder digest. Run this one last.

MANIFEST_FILENAME = "submission-manifest.json"
MANIFEST_SCHEMA_VERSION = 2

SUBMISSIONS_QUERY = """
    SELECT s.submission_uuid, s.delivery_id, s.job_id, s.product_release_id, s.product_unit_id,
           s.product_unit_code, s.verified_product_unit_code, s.requested_at, s.input_digest,
           s.artifact_key
    FROM publication_submission s
    JOIN execution_delivery d ON d.id = s.delivery_id
    WHERE s.artifact_digest = %(digest)s
      AND s.publication_state = 'published'
      AND s.artifact_key NOT LIKE %(placeholder)s
      AND (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
    ORDER BY s.requested_at
"""

UPDATE_QUERY = """
    UPDATE publication_submission
    SET artifact_digest = %(manifest_digest)s
    WHERE submission_uuid = %(uuid)s AND artifact_digest = %(digest)s
"""


class FolderError(Exception):
    """The folder cannot be described by a manifest."""


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def folder_of(artifact_key):
    """The folder below SUBMISSION_DIR named by the key, which must be a real directory."""
    path = PurePosixPath(artifact_key)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise FolderError("unsafe artifact key")
    folder = SUBMISSION_DIR.joinpath(*path.parts)
    for parent in [folder, *folder.parents]:
        if parent == SUBMISSION_DIR:
            break
        if parent.is_symlink():
            raise FolderError("a path component is a symbolic link")
    if not folder.is_dir():
        raise FolderError("folder not found")
    return folder


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory_of(folder):
    """[{path, sha256, size}] of all regular files; links and special files are refused."""
    files = []
    for directory, names, filenames in os.walk(folder):
        for name in names + filenames:
            if os.path.islink(os.path.join(directory, name)):
                raise FolderError(f"symbolic link {name}")
        for name in filenames:
            path = Path(directory, name)
            relative = path.relative_to(folder).as_posix()
            if relative == MANIFEST_FILENAME:
                continue  # Replaced below; the manifest never lists itself.
            if not path.is_file():
                raise FolderError(f"unsupported file {relative}")
            files.append({"path": relative, "sha256": file_digest(path), "size": path.stat().st_size})
    if not files:
        raise FolderError("folder has no files")
    return sorted(files, key=lambda item: item["path"])


def build_manifest(row, files):
    """Manifest bytes and the digest of its body, as publication/manifest.py builds them."""
    (uuid, delivery_id, job_id, release_id, unit_id, unit_code, verified_code, requested_at,
     input_digest, _key) = row
    body = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "submission_id": str(uuid),
        "delivery_id": delivery_id,
        "job_id": str(job_id),
        "product_release_id": release_id,
        "product_unit_id": unit_id,
        "product_unit_code": unit_code,
        "submitted_product_unit_code": verified_code,
        "input_sha256": input_digest,
        "storage": "local",
        "requested_at": requested_at.isoformat(),
        "files": files,
    }
    digest = hashlib.sha256(canonical_json(body)).hexdigest()
    return canonical_json({**body, "artifact_sha256": digest}), digest


def write_manifest(folder, payload):
    """Replace the manifest atomically; a failure leaves the old state."""
    temporary = folder / (".tmp-" + MANIFEST_FILENAME)
    try:
        with open(temporary, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, folder / MANIFEST_FILENAME)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_legacy_submission_manifests(dry_run, product_idents=None):
    params = {"digest": LEGACY_DIGEST, "placeholder": PLACEHOLDER_PREFIX + "%", "idents": product_idents}
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    done, failed = 0, []
    try:
        print("Writing manifests of legacy submissions...")
        cursor.execute(SUBMISSIONS_QUERY, params)
        rows = cursor.fetchall()
        print(f"{len(rows)} legacy submissions with a linked folder in {SUBMISSION_DIR}.")
        for row in rows:
            try:
                folder = folder_of(row[9])
                payload, digest = build_manifest(row, inventory_of(folder))
                if not dry_run:
                    write_manifest(folder, payload)
                    cursor.execute(UPDATE_QUERY, {**params, "manifest_digest": digest, "uuid": row[0]})
                    # One commit per submission: the file is written before it, so an
                    # interrupted run leaves a manifest that the next run replaces.
                    conn.commit()
                done += 1
            except (FolderError, OSError) as error:
                conn.rollback()
                failed.append((row[9], str(error)))
        print(f"{'Would write' if dry_run else 'Wrote'} {done} manifests, {len(failed)} failed.")
        for key, reason in failed:
            print(f"  {key}: {reason}")
    finally:
        cursor.close()
        conn.close()
    return not failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Check the folders and count the manifests; write nothing.")
    parser.add_argument("--product-ident", action="append", dest="product_idents",
                        help="Only process this product (case-insensitive); repeatable.")
    args = parser.parse_args()
    idents = [ident.lower() for ident in args.product_idents] if args.product_idents else None
    if not write_legacy_submission_manifests(args.dry_run, idents):
        raise SystemExit(1)
