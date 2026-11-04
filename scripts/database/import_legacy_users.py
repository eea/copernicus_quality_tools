import argparse

import psycopg2

from legacy_db import DB_CONFIG

# Database connection details — update these or use environment variables
CSV_FILE_PATH = "auth_user.csv"

# 1. Create a temporary staging table matching the structure of auth_user
STAGING_SQL = """
    CREATE TEMP TABLE temp_auth_user (
        LIKE auth_user INCLUDING DEFAULTS
    ) ON COMMIT DROP;
"""

# 2. Fast CSV copy into the temporary table
COPY_SQL = """
    COPY temp_auth_user(
        id, password, last_login, is_superuser,
        username, first_name, last_name, email,
        is_staff, is_active, date_joined
    )
    FROM STDIN
    WITH (FORMAT csv, HEADER true)
"""

# 3. Upsert into auth_user table
UPSERT_SQL = """
    INSERT INTO auth_user (
        id, password, last_login, is_superuser,
        username, first_name, last_name, email,
        is_staff, is_active, date_joined
    )
    SELECT
        id, password, last_login, is_superuser,
        username, first_name, last_name, email,
        is_staff, is_active, date_joined
    FROM temp_auth_user
    ON CONFLICT (id) DO UPDATE SET
        password = EXCLUDED.password,
        last_login = EXCLUDED.last_login,
        is_superuser = EXCLUDED.is_superuser,
        username = EXCLUDED.username,
        first_name = EXCLUDED.first_name,
        last_name = EXCLUDED.last_name,
        email = EXCLUDED.email,
        is_staff = EXCLUDED.is_staff,
        is_active = EXCLUDED.is_active,
        date_joined = EXCLUDED.date_joined;
"""

# 4. Give every imported non-admin user the default role (the "default" group).
# Admins are users that are superusers, staff, or already in the "admin" group.
# The group is created when missing; existing memberships are kept.
DEFAULT_GROUP_SQL = """
    INSERT INTO auth_group (name) VALUES ('default') ON CONFLICT (name) DO NOTHING;
"""

DEFAULT_ROLE_SQL = """
    INSERT INTO auth_user_groups (user_id, group_id)
    SELECT t.id, g.id
    FROM temp_auth_user t
    JOIN auth_user u ON u.id = t.id
    CROSS JOIN auth_group g
    WHERE g.name = 'default'
      AND NOT u.is_superuser
      AND NOT u.is_staff
      AND NOT EXISTS (
          SELECT 1
          FROM auth_user_groups ug
          JOIN auth_group ag ON ag.id = ug.group_id
          WHERE ug.user_id = u.id AND ag.name = 'admin'
      )
    ON CONFLICT (user_id, group_id) DO NOTHING;
"""

# 5. Reset sequence ID to max(id) so future Django creates don't hit duplicate key errors
SEQUENCE_SQL = """
    SELECT setval(
        pg_get_serial_sequence('auth_user', 'id'),
        COALESCE(MAX(id), 1)
    ) FROM auth_user;
"""


def import_users_copy(dry_run=False):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        print("Starting batch import...")

        cursor.execute(STAGING_SQL)

        with open(CSV_FILE_PATH, "r", encoding="utf-8") as f:
            cursor.copy_expert(sql=COPY_SQL, file=f)

        print("CSV data copied to temporary staging table.")

        cursor.execute(UPSERT_SQL)
        imported_count = cursor.rowcount
        print(f"Upserted {imported_count} rows into auth_user.")

        cursor.execute(DEFAULT_GROUP_SQL)
        cursor.execute(DEFAULT_ROLE_SQL)
        print(f"Assigned the default role to {cursor.rowcount} non-admin users.")

        cursor.execute(SEQUENCE_SQL)

        # Commit everything in a single atomic transaction
        if dry_run:
            conn.rollback()
            print("Dry run, rolled back.")
            return
        conn.commit()
        print("Import completed and auto-increment sequence updated successfully!")

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
    args = parser.parse_args()
    import_users_copy(args.dry_run)
