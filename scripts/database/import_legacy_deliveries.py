import argparse

import psycopg2

from legacy_db import DB_CONFIG

# ---- delivery plans ----

# A draft release without units of a product whose ident ends with one of these
# suffixes gets a single unit named after the suffix. The provenance must not be
# 'legacy-import': create_legacy_publication_submissions.py deletes unused units
# of that provenance.
DRAFT_SINGLE_UNIT_SQL = """
    INSERT INTO catalog_product_unit (
        product_release_id, product_unit_code, source_value, provenance, created_at
    )
    SELECT cr.id, s.suffix, s.suffix, 'administrator', now()
    FROM catalog_release_revision cr
    JOIN catalog_product p ON p.id = cr.product_id
    CROSS JOIN LATERAL (
        SELECT substring(lower(p.ident) from '(gp|gf|yt|re|mq)$') AS suffix
    ) s
    WHERE cr.is_current
      AND cr.coverage_state = 'draft'
      AND s.suffix IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM catalog_product_unit cu WHERE cu.product_release_id = cr.id
      )
      AND (%(idents)s::text[] IS NULL OR lower(p.ident) = ANY(%(idents)s))
    ON CONFLICT (product_release_id, product_unit_code) DO NOTHING;
"""

# Approve the current draft release of each product (authoritative coverage), so
# its submissions can be reviewed. The units already in the draft become the
# delivery plan. A draft without units is skipped: an approved plan needs units.
DRAFT_PLAN_APPROVAL_SQL = """
    UPDATE catalog_release_revision cr
    SET coverage_state = 'authoritative', approved_at = now()
    FROM catalog_product p
    WHERE p.id = cr.product_id
      AND cr.is_current
      AND cr.coverage_state = 'draft'
      AND EXISTS (
          SELECT 1 FROM catalog_product_unit cu WHERE cu.product_release_id = cr.id
      )
      AND (%(idents)s::text[] IS NULL OR lower(p.ident) = ANY(%(idents)s));
"""

S3INFO_CSV_FILE_PATH = "dashboard_s3info.csv"
DELIVERY_CSV_FILE_PATH = "dashboard_delivery.csv"

# ---- storage_delivery_source ----

# 1. Staging table matching legacy CSV structure
S3INFO_STAGING_SQL = """
    CREATE TEMP TABLE temp_dashboard_s3info (
        id bigint,
        host character varying(200),
        access_key character varying(255),
        secret_key character varying(255),
        bucketname character varying(100),
        key_prefix character varying(500)
    ) ON COMMIT DROP;
"""

# 2. Stream CSV into temporary staging table
S3INFO_COPY_SQL = """
    COPY temp_dashboard_s3info(
        id, host, access_key, secret_key, bucketname, key_prefix
    )
    FROM STDIN
    WITH (FORMAT csv, HEADER true, NULL '')
"""

# 3. Upsert into storage_delivery_source table with empty string '' for credential_ref
S3INFO_UPSERT_SQL = """
    INSERT INTO storage_delivery_source (
        id,
        host,
        credential_ref,
        bucketname,
        key_prefix
    )
    SELECT
        id,
        host,
        '' AS credential_ref,  -- Set to '' per schema spec when credentials are unmapped
        bucketname,
        key_prefix
    FROM temp_dashboard_s3info
    ON CONFLICT (id) DO UPDATE SET
        host = EXCLUDED.host,
        credential_ref = EXCLUDED.credential_ref,
        bucketname = EXCLUDED.bucketname,
        key_prefix = EXCLUDED.key_prefix;
"""

# 4. Reset primary key sequence
S3INFO_SEQUENCE_SQL = """
    SELECT setval(
        pg_get_serial_sequence('storage_delivery_source', 'id'),
        COALESCE(MAX(id), 1)
    ) FROM storage_delivery_source;
"""

# ---- execution_delivery ----

# 1. Create a temporary staging table reflecting CSV structure
DELIVERY_STAGING_SQL = """
    CREATE TEMP TABLE temp_dashboard_delivery (
        id bigint,
        filename character varying(500),
        product_ident character varying(64),
        date_uploaded timestamp with time zone,
        date_submitted timestamp with time zone,
        user_id integer,
        product_description character varying(500),
        size_bytes bigint,
        is_deleted boolean,
        s3_id bigint,
        aoi_code character varying(255)
    ) ON COMMIT DROP;
"""

# 2. Fast CSV copy into staging table
DELIVERY_COPY_SQL = """
    COPY temp_dashboard_delivery(
        id, filename, product_ident, date_uploaded,
        date_submitted, user_id, product_description,
        size_bytes, is_deleted, s3_id, aoi_code
    )
    FROM STDIN
    WITH (FORMAT csv, HEADER true, NULL '')
"""

# 3. Upsert from staging table into execution_delivery
# Maps `aoi_code` -> `product_unit_code`
DELIVERY_UPSERT_SQL = """
    INSERT INTO execution_delivery (
        id,
        user_id,
        filename,
        size_bytes,
        date_uploaded,
        date_submitted,
        product_ident,
        product_description,
        product_unit_code,
        is_deleted,
        s3_id
    )
    SELECT
        id,
        user_id,
        filename,
        size_bytes,
        date_uploaded,
        date_submitted,
        product_ident,
        product_description,
        aoi_code AS product_unit_code,
        is_deleted,
        s3_id
    FROM temp_dashboard_delivery
    -- Optional --product-ident and --months filters; NULL imports everything.
    WHERE (%(idents)s::text[] IS NULL OR lower(product_ident) = ANY(%(idents)s))
      AND (%(months)s::int IS NULL
           OR date_uploaded >= now() - make_interval(months => %(months)s::int))
    ON CONFLICT (id) DO UPDATE SET
        user_id = EXCLUDED.user_id,
        filename = EXCLUDED.filename,
        size_bytes = EXCLUDED.size_bytes,
        date_uploaded = EXCLUDED.date_uploaded,
        date_submitted = EXCLUDED.date_submitted,
        product_ident = EXCLUDED.product_ident,
        product_description = EXCLUDED.product_description,
        product_unit_code = EXCLUDED.product_unit_code,
        is_deleted = EXCLUDED.is_deleted,
        s3_id = EXCLUDED.s3_id;
"""

# 4. Give each delivery's user access to the delivery's product. Only users that
# exist are granted; existing grants are kept (and so is their creator audit).
DELIVERY_GRANT_SQL = """
    INSERT INTO account_product_grant (user_id, product_ident, created_at, created_by_id)
    SELECT DISTINCT d.user_id, d.product_ident, now(), NULL::integer
    FROM temp_dashboard_delivery d
    JOIN execution_delivery e ON e.id = d.id
    JOIN auth_user u ON u.id = d.user_id
    WHERE d.product_ident IS NOT NULL AND d.product_ident <> ''
      AND (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
      AND (%(months)s::int IS NULL
           OR d.date_uploaded >= now() - make_interval(months => %(months)s::int))
    ON CONFLICT (user_id, product_ident) DO NOTHING;
"""

# 5. Reset sequence for IDENTITY primary key column
DELIVERY_SEQUENCE_SQL = """
    SELECT setval(
        pg_get_serial_sequence('execution_delivery', 'id'),
        COALESCE(MAX(id), 1)
    ) FROM execution_delivery;
"""


def approve_draft_delivery_plans(dry_run=False, product_idents=None):
    """Approve draft plans; product_idents=None means all products."""
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        print("Approving delivery plans of draft products...")
        cursor.execute(DRAFT_SINGLE_UNIT_SQL, {"idents": product_idents})
        print(f"Added {cursor.rowcount} single product units to draft plans.")

        cursor.execute(DRAFT_PLAN_APPROVAL_SQL, {"idents": product_idents})
        print(f"Approved {cursor.rowcount} draft delivery plans.")

        if dry_run:
            conn.rollback()
            print("Dry run, rolled back.")
            return
        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"Error during plan approval: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


def import_s3_sources_copy(dry_run=False):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        print("Starting batch import for storage_delivery_source...")

        cursor.execute(S3INFO_STAGING_SQL)

        with open(S3INFO_CSV_FILE_PATH, "r", encoding="utf-8") as f:
            cursor.copy_expert(sql=S3INFO_COPY_SQL, file=f)

        print("CSV streamed to temporary staging table.")

        cursor.execute(S3INFO_UPSERT_SQL)
        print(f"Upserted {cursor.rowcount} records into storage_delivery_source.")

        cursor.execute(S3INFO_SEQUENCE_SQL)

        if dry_run:
            conn.rollback()
            print("Dry run, rolled back.")
            return
        conn.commit()
        print("Storage delivery sources imported successfully!")

    except Exception as e:
        conn.rollback()
        print(f"Error during import: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


def import_deliveries_copy(dry_run=False, product_idents=None, months=None):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        print("Starting batch import for execution_delivery...")

        cursor.execute(DELIVERY_STAGING_SQL)

        with open(DELIVERY_CSV_FILE_PATH, "r", encoding="utf-8") as f:
            cursor.copy_expert(sql=DELIVERY_COPY_SQL, file=f)

        print("CSV streamed to temporary staging table.")

        cursor.execute(DELIVERY_UPSERT_SQL, {"idents": product_idents, "months": months})
        print(f"Upserted {cursor.rowcount} records into execution_delivery.")

        cursor.execute(DELIVERY_GRANT_SQL, {"idents": product_idents, "months": months})
        print(f"Added {cursor.rowcount} product grants for delivery users.")

        cursor.execute(DELIVERY_SEQUENCE_SQL)

        if dry_run:
            conn.rollback()
            print("Dry run, rolled back.")
            return
        conn.commit()
        print("Import completed and identity sequence updated successfully!")

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
                        help="Only import deliveries uploaded within the last N months.")
    args = parser.parse_args()
    idents = [ident.lower() for ident in args.product_idents] if args.product_idents else None
    # Plans of all draft products are approved, whatever --product-ident says.
    approve_draft_delivery_plans(args.dry_run)
    import_s3_sources_copy(args.dry_run)
    import_deliveries_copy(args.dry_run, idents, args.months)
