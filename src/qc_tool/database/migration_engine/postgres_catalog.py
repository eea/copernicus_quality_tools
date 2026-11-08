"""Ordered PostgreSQL catalog reads for immutable schema fingerprints."""

NAMESPACE = "n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)'"


def schema_queries():
    """Keep result order/columns stable: persisted review fingerprints use them."""
    return tuple(query.format(namespace=NAMESPACE) for query in (
        """SELECT n.nspname,c.relname,c.relkind,c.relpersistence,
                  c.relrowsecurity,c.relforcerowsecurity,c.reloptions
             FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE {namespace} ORDER BY 1,2""",
        """SELECT n.nspname,c.relname,a.attname,format_type(a.atttypid,a.atttypmod),
                  a.attnotnull,a.attidentity,a.attgenerated,
                  pg_get_expr(d.adbin,d.adrelid),a.attcollation::regcollation::text
             FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
             JOIN pg_namespace n ON n.oid=c.relnamespace
             LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            WHERE a.attnum>0 AND NOT a.attisdropped AND {namespace}
            ORDER BY 1,2,a.attnum""",
        """SELECT n.nspname,c.relname,k.conname,
                  pg_get_constraintdef(k.oid),k.convalidated
             FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
             JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE {namespace} ORDER BY 1,2,3""",
        """SELECT n.nspname,c.relname,pg_get_indexdef(i.indexrelid),
                  i.indisvalid,i.indisready
             FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
             JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE {namespace} ORDER BY 1,2,3""",
        """SELECT n.nspname,c.relname,t.tgname,pg_get_triggerdef(t.oid)
             FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
             JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE NOT t.tgisinternal AND {namespace} ORDER BY 1,2,3""",
        """SELECT n.nspname,p.proname,pg_get_functiondef(p.oid)
             FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE p.prokind IN ('f','p') AND {namespace} ORDER BY 1,2,3""",
    ))
