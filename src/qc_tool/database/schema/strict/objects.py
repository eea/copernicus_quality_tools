"""Reject database objects outside the supported application schema."""

def problems(connection, cursor):
    if connection.vendor == "sqlite":
        cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        return [f"unexpected trigger {name}" for (name,) in cursor.fetchall()]
    if connection.vendor != "postgresql":
        return ["baseline adoption supports PostgreSQL and SQLite only"]
    problems = []
    namespace = "n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)'"
    queries = (
        ("function", "SELECT n.nspname||'.'||p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE " + namespace),
        ("type", "SELECT n.nspname||'.'||t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE " + namespace + " AND t.typtype IN ('d','e','r','m')"),
        ("trigger", "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND " + namespace),
        ("rule", "SELECT r.rulename FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class JOIN pg_namespace n ON n.oid=c.relnamespace WHERE " + namespace),
        ("extension", "SELECT extname FROM pg_extension WHERE extname<>'plpgsql'"),
        ("schema", "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public','pg_catalog','information_schema') AND nspname !~ '^pg_(toast|temp)'"),
        ("event trigger", "SELECT evtname FROM pg_event_trigger"),
        ("collation", "SELECT n.nspname||'.'||c.collname FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace WHERE " + namespace),
        ("operator", "SELECT n.nspname||'.'||o.oprname FROM pg_operator o JOIN pg_namespace n ON n.oid=o.oprnamespace WHERE " + namespace),
    )
    for kind, query in queries:
        cursor.execute(query)
        problems += [f"unexpected {kind} {name}" for (name,) in cursor.fetchall()]
    return problems
