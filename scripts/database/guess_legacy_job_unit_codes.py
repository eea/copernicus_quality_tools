import argparse

import psycopg2

from legacy_db import DB_CONFIG


def guess_job_unit_codes(dry_run, product_idents=None):
    params = {"idents": product_idents}
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # Legacy data carries no verified unit code, so the delivery's guessed
        # product_unit_code is used for the delivery and all of its jobs.
        # Run guess_legacy_delivery_unit_codes.py first.
        cursor.execute(
            """
            UPDATE execution_delivery
            SET verified_product_unit_code = product_unit_code
            WHERE product_unit_code IS NOT NULL
              AND product_unit_code <> ''
              AND verified_product_unit_code IS DISTINCT FROM product_unit_code
              AND (%(idents)s::text[] IS NULL OR lower(product_ident) = ANY(%(idents)s))
        """,
            params,
        )
        print(f"Set verified_product_unit_code on {cursor.rowcount} execution_delivery entries.")

        cursor.execute(
            """
            UPDATE execution_job j
            SET product_unit_code = d.product_unit_code,
                verified_product_unit_code = d.product_unit_code
            FROM execution_delivery d
            WHERE j.delivery_id = d.id
              AND d.product_unit_code IS NOT NULL
              AND d.product_unit_code <> ''
              AND (j.product_unit_code IS DISTINCT FROM d.product_unit_code
                   OR j.verified_product_unit_code IS DISTINCT FROM d.product_unit_code)
              AND (%(idents)s::text[] IS NULL OR lower(d.product_ident) = ANY(%(idents)s))
        """,
            params,
        )
        print(f"Set unit codes on {cursor.rowcount} execution_job entries.")

        if dry_run:
            print("Dry run, rolling back.")
            conn.rollback()
        else:
            conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"Error guessing job unit codes: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--product-ident", action="append", dest="product_idents",
                        help="Only process this product (case-insensitive); repeatable.")
    args = parser.parse_args()
    guess_job_unit_codes(args.dry_run, [ident.lower() for ident in args.product_idents] if args.product_idents else None)
