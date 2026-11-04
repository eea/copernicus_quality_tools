import argparse

import psycopg2

from legacy_db import DB_CONFIG

CSV_FILE_PATH = "dashboard_job.csv"

# 1. Staging table matching legacy dashboard_job CSV structure
STAGING_SQL = """
    CREATE TEMP TABLE temp_dashboard_job (
        job_uuid uuid,
        date_created timestamp with time zone,
        date_started timestamp with time zone,
        date_finished timestamp with time zone,
        job_status character varying(64),
        product_ident character varying(64),
        skip_steps character varying(100),
        worker_url character varying(500),
        delivery_id bigint,
        product_description character varying(500),
        aoi_code character varying(255)
    ) ON COMMIT DROP;
"""

# 2. Stream CSV into temporary staging table
COPY_SQL = """
    COPY temp_dashboard_job(
        job_uuid, date_created, date_started, date_finished,
        job_status, product_ident, skip_steps, worker_url,
        delivery_id, product_description, aoi_code
    )
    FROM STDIN
    WITH (FORMAT csv, HEADER true, NULL '')
"""

# 3. Insert/Upsert into execution_job table
# Filters against execution_delivery to respect foreign key constraint
UPSERT_SQL = """
    INSERT INTO execution_job (
        job_uuid,
        delivery_id,
        date_created,
        date_started,
        date_finished,
        job_status,
        product_ident,
        product_description,
        product_unit_code,
        skip_steps,
        worker_url,
        requested_by_username,
        requested_api_token_name,
        input_sha256,
        reference_period
    )
    SELECT
        t.job_uuid,
        t.delivery_id,
        t.date_created,
        t.date_started,
        t.date_finished,
        t.job_status,
        t.product_ident,
        t.product_description,
        t.aoi_code AS product_unit_code,
        t.skip_steps,
        t.worker_url,
        'legacy_import' AS requested_by_username,
        '' AS requested_api_token_name,
        '' AS input_sha256,
        '' AS reference_period
    FROM temp_dashboard_job t
    JOIN execution_delivery d ON t.delivery_id = d.id
    -- Optional --product-ident and --months filters; NULL imports everything.
    WHERE (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
      AND (%(months)s::int IS NULL
           OR t.date_created >= now() - make_interval(months => %(months)s::int))
    ON CONFLICT (job_uuid) DO UPDATE SET
        delivery_id = EXCLUDED.delivery_id,
        date_created = EXCLUDED.date_created,
        date_started = EXCLUDED.date_started,
        date_finished = EXCLUDED.date_finished,
        job_status = EXCLUDED.job_status,
        product_ident = EXCLUDED.product_ident,
        product_description = EXCLUDED.product_description,
        product_unit_code = EXCLUDED.product_unit_code,
        skip_steps = EXCLUDED.skip_steps,
        worker_url = EXCLUDED.worker_url;
"""


def import_jobs_copy(dry_run=False, product_idents=None, months=None):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        print("Starting batch import for execution_job...")

        cursor.execute(STAGING_SQL)

        with open(CSV_FILE_PATH, "r", encoding="utf-8") as f:
            cursor.copy_expert(sql=COPY_SQL, file=f)

        print("CSV streamed to temporary staging table.")

        cursor.execute(UPSERT_SQL, {"idents": product_idents, "months": months})
        print(f"Upserted {cursor.rowcount} records into execution_job.")

        if dry_run:
            conn.rollback()
            print("Dry run, rolled back.")
            return
        conn.commit()
        print("Jobs imported successfully!")

    except Exception as e:
        conn.rollback()
        print(f"Error during import: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--product-ident", action="append", dest="product_idents",
                        help="Only process this product (case-insensitive); repeatable.")
    parser.add_argument("--months", type=int, metavar="N",
                        help="Only import jobs created within the last N months.")
    args = parser.parse_args()
    import_jobs_copy(args.dry_run, [ident.lower() for ident in args.product_idents] if args.product_idents else None,
                     args.months)
