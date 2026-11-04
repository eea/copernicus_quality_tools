"""List the deliveries and jobs of the imported legacy rows.

Runs in the QC Tool frontend pod. Prints one item per line (stdout): for
deliveries the relative path <username>/<filename> of the ZIP file, for jobs the
job UUID, for submissions the job UUID of the legacy submission records (see
create_legacy_publication_submissions.py). Read-only; it does not look at the storage.
"""
import argparse
import sys
import uuid

import psycopg2

from legacy_db import DB_CONFIG

DELIVERY_FILES_SQL = """
    SELECT u.username, d.filename
    FROM execution_delivery d
    JOIN auth_user u ON u.id = d.user_id
    WHERE (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
      AND (%(months)s::int IS NULL
           OR d.date_uploaded >= now() - make_interval(months => %(months)s::int))
    ORDER BY d.id
"""

JOB_IDS_SQL = """
    SELECT j.job_uuid
    FROM execution_job j
    JOIN execution_delivery d ON d.id = j.delivery_id
    WHERE (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
      AND (%(months)s::int IS NULL
           OR j.date_created >= now() - make_interval(months => %(months)s::int))
    ORDER BY j.date_created
"""

# The submissions of the legacy import carry the placeholder digest (all zeros); their
# folders are found by the job UUID. Submissions made in QC Tool are not listed.
SUBMISSION_KEYS_SQL = """
    SELECT s.job_id
    FROM publication_submission s
    JOIN execution_delivery d ON d.id = s.delivery_id
    WHERE s.artifact_digest = repeat('0', 64)
      AND (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
      AND (%(months)s::int IS NULL
           OR s.requested_at >= now() - make_interval(months => %(months)s::int))
    ORDER BY s.requested_at
"""


def plain_name(name):
    """A single path component; database values must not escape the storage root."""
    return bool(name) and name not in (".", "..") and not any(char in name for char in "/\\\0\r\n")


def delivery_items(cursor, idents, months):
    cursor.execute(DELIVERY_FILES_SQL, {"idents": idents, "months": months})
    items = []
    for username, filename in cursor.fetchall():
        if plain_name(username) and plain_name(filename):
            items.append(f"{username}/{filename}")
        else:
            print(f"  skipped (unsafe name): {username}/{filename}", file=sys.stderr)
    return items


def job_items(cursor, idents, months):
    cursor.execute(JOB_IDS_SQL, {"idents": idents, "months": months})
    return [str(uuid.UUID(str(job_uuid))) for (job_uuid,) in cursor.fetchall()]


def submission_items(cursor, idents, months):
    cursor.execute(SUBMISSION_KEYS_SQL, {"idents": idents, "months": months})
    return [str(uuid.UUID(str(job_id))) for (job_id,) in cursor.fetchall() if job_id]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("deliveries", "jobs", "submissions"))
    parser.add_argument("--product-ident", action="append", dest="product_idents")
    parser.add_argument("--months", type=int, metavar="N")
    args = parser.parse_args()
    idents = [ident.lower() for ident in args.product_idents] if args.product_idents else None

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            collect = {"deliveries": delivery_items, "jobs": job_items, "submissions": submission_items}[args.kind]
            items = collect(cursor, idents, args.months)
    finally:
        conn.close()

    print(f"{args.kind}: {len(items)} in the database.", file=sys.stderr)
    sys.stdout.write("".join(f"{item}\n" for item in items))
