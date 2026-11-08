"""Read backend catalogs for schema inspection; never create objects."""

import re
from django.db import models
from qc_tool.database.predicates import named_sqlite_check

def column_types(connection, cursor, table, columns):
    if connection.vendor == "postgresql":
        cursor.execute(
            "SELECT attname, format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped", [table],
        )
        return dict(cursor.fetchall())
    return {column.name: str(column.type_code) for column in columns}

def index_sql(connection, cursor, table, name):
    if connection.vendor == "postgresql":
        cursor.execute(
            "SELECT pg_get_indexdef(i.indexrelid) FROM pg_index i "
            "JOIN pg_class c ON c.oid=i.indexrelid "
            "WHERE i.indrelid=%s::regclass AND c.relname=%s", [table, name],
        )
    else:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=%s", [name])
    row = cursor.fetchone()
    return row[0] if row else None

def table_sql(cursor, table):
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=%s", [table])
    row = cursor.fetchone()
    return row[0] if row else ""

def check_sql(connection, cursor, table, name):
    if connection.vendor == "postgresql":
        cursor.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                       "WHERE conrelid=%s::regclass AND conname=%s AND contype='c'", [table, name])
        row = cursor.fetchone()
        return row[0] if row else None
    return named_sqlite_check(table_sql(cursor, table), name)

def automatic_primary_key(connection, cursor, model):
    field = model._meta.pk
    if not isinstance(field, (models.AutoField, models.BigAutoField, models.SmallAutoField)):
        return True
    table = model._meta.db_table
    if connection.vendor == "postgresql":
        cursor.execute("SELECT a.attidentity, pg_get_expr(d.adbin,d.adrelid), "
                       "pg_get_serial_sequence(%s,%s) FROM pg_attribute a "
                       "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
                       "WHERE a.attrelid=%s::regclass AND a.attname=%s",
                       [table, field.column, table, field.column])
        row = cursor.fetchone()
        if not row or not row[2]:
            return False
        if row[0] == "d":
            return True
        match = re.fullmatch(r"nextval\('((?:''|[^'])+)'::regclass\)", row[1] or "")
        if row[0] or not match:
            return False
        cursor.execute("SELECT %s::regclass = %s::regclass", [match[1].replace("''", "'"), row[2]])
        return bool(cursor.fetchone()[0])
    return bool(re.search(r"\bAUTOINCREMENT\b", table_sql(cursor, table), re.I))

def objects(connection, cursor, declared_models, *, allow_history):
    if connection.vendor != "postgresql":
        tables = {table.name: table.type for table in connection.introspection.get_table_list(cursor)}
        return tables, []
    cursor.execute("SELECT current_schema()")
    schema = cursor.fetchone()[0]
    namespace_filter = ("n.nspname NOT IN ('pg_catalog','information_schema') "
                        "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%'")
    cursor.execute("SELECT n.nspname,c.relname,c.relkind FROM pg_class c "
                   "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE " + namespace_filter +
                   " AND c.relkind IN ('r','p','v','m','f','c')")
    tables = {(name if namespace == schema else f"{namespace}.{name}"):
              ("t" if kind in {"r", "p"} else "v") for namespace, name, kind in cursor.fetchall()}
    expected = {(schema, model._meta.db_table) for model in declared_models}
    if allow_history:
        expected.add((schema, "django_migrations"))
    cursor.execute("SELECT n.nspname,s.relname,tn.nspname,t.relname FROM pg_class s "
                   "JOIN pg_namespace n ON n.oid=s.relnamespace "
                   "LEFT JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=s.oid "
                   "AND d.deptype IN ('a','i') LEFT JOIN pg_class t ON t.oid=d.refobjid "
                   "LEFT JOIN pg_namespace tn ON tn.oid=t.relnamespace "
                   "WHERE s.relkind='S' AND " + namespace_filter)
    problems = [f"unexpected sequence {namespace}.{name}" for namespace, name, owner_schema, owner in cursor.fetchall()
                if (owner_schema, owner) not in expected]
    # A relation-free database with a foreign function/type is not an empty
    # initialization target. Do not silently add application tables to it.
    if not tables:
        cursor.execute("SELECT n.nspname,p.proname FROM pg_proc p "
                       "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE " + namespace_filter)
        problems += [f"unexpected function {namespace}.{name}" for namespace, name in cursor.fetchall()]
        cursor.execute("SELECT n.nspname,t.typname FROM pg_type t "
                       "JOIN pg_namespace n ON n.oid=t.typnamespace WHERE " + namespace_filter +
                       " AND t.typtype IN ('d','e','r','m')")
        problems += [f"unexpected type {namespace}.{name}" for namespace, name in cursor.fetchall()]
    return tables, problems

