import argparse
import os
import re
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from legacy_db import DB_CONFIG


# Placeholder for the digests that a published submission must carry. It also marks
# the submissions created by this import: their artifact key is not a marker, because
# it is replaced by the real folder below.
LEGACY_DIGEST = "0" * 64

# Legacy submission folders: <product>/<year>/<date>-<name>-<job uuid>.d below this
# directory. The same pattern is in kubectl_files.py, which runs on the local machine.
SUBMISSION_DIR = Path(os.getenv("SUBMISSION_DIR", "/mnt/qc_tool_submission/submission"))
SUBMISSION_FOLDER = re.compile(r"-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.d$")

# Placeholder key of a submission whose folder is not known (yet).
PLACEHOLDER_PREFIX = "legacy-import/"

# The folders found in SUBMISSION_DIR, by the job UUID that ends their name.
FOLDER_STAGING_SQL = """
    CREATE TEMP TABLE legacy_folder (
        job_id uuid PRIMARY KEY,
        artifact_key character varying(1000)
    ) ON COMMIT DROP;
"""

# Replace the placeholder keys by the folders of the submissions (product filter as
# elsewhere in this script). Keys that are not placeholders are left alone.
LINK_FOLDERS_QUERY = """
    UPDATE publication_submission s
    SET artifact_key = f.artifact_key
    FROM legacy_folder f, execution_delivery d
    WHERE f.job_id = s.job_id
      AND d.id = s.delivery_id
      AND s.artifact_digest = %(digest)s
      AND s.artifact_key LIKE 'legacy-import/%%'
      AND (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
"""

PLACEHOLDERS_LEFT_QUERY = """
    SELECT count(*)
    FROM publication_submission s
    JOIN execution_delivery d ON d.id = s.delivery_id
    WHERE s.artifact_digest = %(digest)s
      AND s.artifact_key LIKE 'legacy-import/%%'
      AND (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
"""


def find_submission_folders():
    """{job uuid: '<product>/<year>/<folder>.d'} of the folders in SUBMISSION_DIR.

    If a job has several folders, the last by name (the newest date prefix) wins.
    """
    folders = {}
    if not SUBMISSION_DIR.is_dir():
        return folders
    for product in sorted(SUBMISSION_DIR.iterdir()):
        for year in sorted(product.iterdir()) if product.is_dir() else []:
            for folder in sorted(year.iterdir()) if year.is_dir() else []:
                match = SUBMISSION_FOLDER.search(folder.name)
                if match and folder.is_dir() and not folder.is_symlink():
                    folders[match.group(1)] = f"{product.name}/{year.name}/{folder.name}"
    return folders


def stage_submission_folders(cursor):
    folders = find_submission_folders()
    cursor.execute(FOLDER_STAGING_SQL)
    if folders:
        execute_values(cursor, "INSERT INTO legacy_folder (job_id, artifact_key) VALUES %s", list(folders.items()))
    print(f"Found {len(folders)} submission folders in {SUBMISSION_DIR}.")

# One candidate per submitted delivery that has a product and a unit code.
#  - job: best job of the delivery (ok first, then partial, then the latest).
#  - release: the current release of the product, which is the one coverage
#    is shown for; missing units are added to it.
#  - rn: newest delivery per release and unit is ranked 1.
CANDIDATES_QUERY = """
    CREATE TEMP TABLE legacy_candidate ON COMMIT DROP AS
    SELECT c.*,
           ROW_NUMBER() OVER (
               PARTITION BY c.product_release_id, c.unit_code
               ORDER BY c.date_submitted DESC, c.delivery_id DESC
           ) AS rn
    FROM (
        SELECT d.id AS delivery_id,
               d.date_submitted,
               d.user_id,
               d.filename,
               lower(btrim(d.product_unit_code)) AS unit_code,
               lower(btrim(COALESCE(NULLIF(d.verified_product_unit_code, ''), d.product_unit_code))) AS verified_code,
               j.job_uuid,
               (SELECT cr.id
                FROM catalog_release_revision cr
                WHERE cr.product_id = p.id
                ORDER BY cr.is_current DESC, cr.id
                LIMIT 1) AS product_release_id
        FROM execution_delivery d
        JOIN catalog_product p ON p.ident = d.product_ident
        JOIN LATERAL (
            SELECT job_uuid
            FROM execution_job
            WHERE delivery_id = d.id
            ORDER BY (job_status = 'ok') DESC, (job_status = 'partial') DESC,
                     date_created DESC, job_uuid
            LIMIT 1
        ) j ON TRUE
        WHERE d.date_submitted IS NOT NULL
          AND btrim(COALESCE(d.product_unit_code, '')) <> ''
          AND (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
    ) c
    WHERE c.product_release_id IS NOT NULL
"""

# At most one published submission per unit may be accepted, and the unique index is
# checked row by row while the upsert below recomputes the states. A submission that an
# earlier run accepted could still be accepted when the newest delivery of its unit
# becomes accepted, so those candidates are reset first. The upsert sets the state of
# every one of them again. Submissions reviewed in QC Tool are not touched.
RESET_ACCEPTED_QUERY = """
    UPDATE publication_submission s
    SET review_state = 'pending'
    FROM legacy_candidate c
    WHERE s.delivery_id = c.delivery_id
      AND s.review_state = 'accepted'
      AND NOT EXISTS (
          SELECT 1 FROM publication_review_event e WHERE e.submission_id = s.submission_uuid
      )
"""

ADD_UNITS_QUERY = """
    INSERT INTO catalog_product_unit (
        product_release_id, product_unit_code, source_value, provenance, created_at
    )
    SELECT DISTINCT product_release_id, unit_code, unit_code, 'legacy-import', now()
    FROM legacy_candidate
    ON CONFLICT (product_release_id, product_unit_code) DO NOTHING
"""

# Units this script added earlier that no submission uses anymore.
CLEANUP_UNITS_QUERY = """
    DELETE FROM catalog_product_unit cu
    USING catalog_release_revision cr, catalog_product p
    WHERE cr.id = cu.product_release_id
      AND p.id = cr.product_id
      AND cu.provenance = 'legacy-import'
      AND (%(idents)s::text[] IS NULL OR lower(p.ident) = ANY(%(idents)s))
      AND NOT EXISTS (
          SELECT 1 FROM publication_submission s WHERE s.product_unit_id = cu.id
      )
"""

# Same accepted count as the Products page.
CURRENT_COVERAGE_QUERY = """
    SELECT count(DISTINCT s.product_unit_id)
    FROM publication_submission s
    JOIN catalog_release_revision cr ON cr.id = s.product_release_id
    WHERE cr.is_current
      AND s.publication_state = 'published'
      AND s.review_state = 'accepted'
"""

# The newest delivery per unit (rn = 1) waits for review ('pending'), or with
# --auto-approve is 'accepted' where QC Tool would allow approving it: active
# product, authoritative release. Older deliveries of the same unit, and
# deliveries of a unit already approved outside this import, are 'rejected'.
# Submissions already reviewed in QC Tool keep their state.
INSERT_QUERY = """
    INSERT INTO publication_submission (
        submission_uuid, delivery_id, job_id, product_release_id, product_unit_id,
        product_unit_code, verified_product_unit_code,
        submitted_by_id, submitted_by_username, request_channel,
        publication_state, review_state, review_version,
        requested_at, publication_claimed_at, publication_token, published_at,
        artifact_key, artifact_digest, input_digest, api_token_name,
        failure_code, failure_message
    )
    SELECT gen_random_uuid(), c.delivery_id, c.job_uuid, c.product_release_id, cu.id,
           c.unit_code, COALESCE(NULLIF(c.verified_code, ''), c.unit_code),
           c.user_id, COALESCE(u.username, 'legacy_import'), 'browser',
           'published',
           CASE
               WHEN c.rn <> 1 OR EXISTS (
                   SELECT 1 FROM publication_submission s
                   WHERE s.product_unit_id = cu.id
                     AND s.delivery_id <> c.delivery_id
                     AND s.publication_state = 'published'
                     AND s.review_state = 'accepted'
                     AND (
                         NOT EXISTS (
                             SELECT 1 FROM legacy_candidate o WHERE o.delivery_id = s.delivery_id
                         )
                         OR EXISTS (
                             SELECT 1 FROM publication_review_event e WHERE e.submission_id = s.submission_uuid
                         )
                     )
               ) THEN 'rejected'
               WHEN %(auto_approve)s AND p.is_active AND cr.coverage_state = 'authoritative'
                   THEN 'accepted'
               ELSE 'pending'
           END,
           1,
           c.date_submitted, c.date_submitted, gen_random_uuid(), c.date_submitted,
           COALESCE(lf.artifact_key,
                    'legacy-import/' || c.delivery_id || '/' || COALESCE(c.filename, 'submission.zip')),
           %(digest)s, %(digest)s, '',
           '', ''
    FROM legacy_candidate c
    LEFT JOIN legacy_folder lf ON lf.job_id = c.job_uuid
    JOIN catalog_product_unit cu
      ON cu.product_release_id = c.product_release_id AND cu.product_unit_code = c.unit_code
    JOIN catalog_release_revision cr ON cr.id = c.product_release_id
    JOIN catalog_product p ON p.id = cr.product_id
    LEFT JOIN auth_user u ON u.id = c.user_id
    ON CONFLICT (delivery_id) DO UPDATE SET
        job_id = EXCLUDED.job_id,
        product_release_id = EXCLUDED.product_release_id,
        product_unit_id = EXCLUDED.product_unit_id,
        product_unit_code = EXCLUDED.product_unit_code,
        verified_product_unit_code = EXCLUDED.verified_product_unit_code,
        publication_state = EXCLUDED.publication_state,
        review_state = EXCLUDED.review_state,
        requested_at = EXCLUDED.requested_at,
        published_at = EXCLUDED.published_at
    WHERE NOT EXISTS (
        SELECT 1 FROM publication_review_event e
        WHERE e.submission_id = publication_submission.submission_uuid
    )
"""

# Imported deliveries that were rejected only because another delivery of the same
# unit is accepted are superseded: mark them deleted instead of "Correction needed".
# Submissions reviewed in QC Tool are left alone.
DELETE_SUPERSEDED_QUERY = """
    UPDATE execution_delivery d
    SET is_deleted = TRUE
    FROM publication_submission s
    WHERE s.delivery_id = d.id
      AND NOT d.is_deleted
      AND s.artifact_digest = %(digest)s
      AND s.publication_state = 'published'
      AND s.review_state = 'rejected'
      AND NOT EXISTS (
          SELECT 1 FROM publication_review_event e WHERE e.submission_id = s.submission_uuid
      )
      AND EXISTS (
          SELECT 1 FROM publication_submission a
          WHERE a.product_unit_id = s.product_unit_id
            AND a.delivery_id <> s.delivery_id
            AND a.publication_state = 'published'
            AND a.review_state = 'accepted'
      )
      AND (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
"""


def populate_publication_submissions(dry_run, product_idents=None, auto_approve=False):
    params = {"idents": product_idents, "digest": LEGACY_DIGEST, "auto_approve": auto_approve}
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        print("Generating publication_submission records for submitted legacy deliveries...")
        print("Auto-approve: " + ("yes" if auto_approve else "no, newest submissions await review"))

        cursor.execute(
            """
            SELECT count(*) FROM execution_delivery
            WHERE date_submitted IS NOT NULL
              AND (%(idents)s::text[] IS NULL OR lower(product_ident) = ANY(%(idents)s))
        """,
            params,
        )
        submitted = cursor.fetchone()[0]

        cursor.execute(CANDIDATES_QUERY, params)
        cursor.execute("SELECT count(*) FROM legacy_candidate")
        candidates = cursor.fetchone()[0]
        print(f"{candidates} of {submitted} submitted deliveries have a product, job and unit code.")

        cursor.execute(ADD_UNITS_QUERY)
        print(f"Added {cursor.rowcount} missing catalog_product_unit entries.")

        stage_submission_folders(cursor)
        cursor.execute(RESET_ACCEPTED_QUERY)
        print(f"Reset {cursor.rowcount} accepted submissions before recomputing their review state.")
        cursor.execute(INSERT_QUERY, params)
        print(f"Inserted/Updated {cursor.rowcount} publication_submission entries.")

        cursor.execute(LINK_FOLDERS_QUERY, params)
        print(f"Replaced {cursor.rowcount} placeholder keys of earlier entries by their submission folder.")
        cursor.execute(PLACEHOLDERS_LEFT_QUERY, params)
        print(f"{cursor.fetchone()[0]} legacy submissions have no folder in {SUBMISSION_DIR}.")

        cursor.execute(DELETE_SUPERSEDED_QUERY, params)
        print(f"Marked {cursor.rowcount} deliveries superseded by an accepted delivery as deleted.")

        cursor.execute(CLEANUP_UNITS_QUERY, params)
        print(f"Removed {cursor.rowcount} unused legacy-import units.")

        cursor.execute(CURRENT_COVERAGE_QUERY)
        print(f"Accepted product units on current releases: {cursor.fetchone()[0]}")

        cursor.execute(
            """
            SELECT review_state, count(*) FROM publication_submission GROUP BY 1 ORDER BY 1
        """
        )
        print("Submissions by review_state:", dict(cursor.fetchall()))

        if dry_run:
            conn.rollback()
            print("Dry run, rolled back.")
        else:
            conn.commit()
            print("Publication submissions created successfully!")

    except Exception as e:
        conn.rollback()
        print(f"Error creating publication submissions: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


def link_submission_folders(dry_run, product_idents=None):
    """Replace the placeholder keys by the folders found now, e.g. after uploading them."""
    params = {"idents": product_idents, "digest": LEGACY_DIGEST}
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    try:
        print("Linking legacy submissions to their submission folders...")
        stage_submission_folders(cursor)
        cursor.execute(LINK_FOLDERS_QUERY, params)
        print(f"Replaced {cursor.rowcount} placeholder keys by their submission folder.")
        cursor.execute(PLACEHOLDERS_LEFT_QUERY, params)
        print(f"{cursor.fetchone()[0]} legacy submissions have no folder in {SUBMISSION_DIR}.")
        if dry_run:
            conn.rollback()
            print("Dry run, rolled back.")
        else:
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error linking submission folders: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def yes_no(value):
    value = value.strip().lower()
    if value in ("yes", "y", "true", "1"):
        return True
    if value in ("no", "n", "false", "0"):
        return False
    raise argparse.ArgumentTypeError("expected yes or no")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--product-ident", action="append", dest="product_idents",
                        help="Only process this product (case-insensitive); repeatable.")
    parser.add_argument("--auto-approve", nargs="?", const="yes", default="no", type=yes_no,
                        metavar="yes|no",
                        help="Approve the newest submission per unit where possible (default: no, "
                             "submissions await approval review).")
    parser.add_argument("--link-folders", action="store_true",
                        help="Only replace the placeholder keys of the legacy submissions by their "
                             "<product>/<year>/<folder>.d in the submission directory; create nothing.")
    args = parser.parse_args()
    idents = [ident.lower() for ident in args.product_idents] if args.product_idents else None
    if args.link_folders:
        link_submission_folders(args.dry_run, idents)
    else:
        populate_publication_submissions(args.dry_run, idents, args.auto_approve)
