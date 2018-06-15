CREATE OR REPLACE FUNCTION __v13_overlapping_polygons(IN table_name varchar, IN ident_colname varchar, OUT error_count integer)
LANGUAGE plpgsql
AS $$
DECLARE
  sql text;
BEGIN
  CREATE TABLE IF NOT EXISTS v13_overlapping_polygons_error (
    table_name varchar,
    ident_a varchar,
    ident_b varchar);
  sql := format(
    'INSERT INTO v13_overlapping_polygons_error
       SELECT %1$L, ta.%2$I::text, tb.%2$I::text
       FROM %1$I ta INNER JOIN %1$I tb ON ta.%2$I < tb.%2$I
       WHERE ST_Relate(ta.wkb_geometry, tb.wkb_geometry, %3$L)
       ORDER BY ta.%2$I, tb.%2$I;',
    table_name, ident_colname, 'T********');
  EXECUTE sql;
  sql := 'SELECT count(*) FROM v13_overlapping_polygons_error WHERE table_name=$1;';
  EXECUTE sql INTO error_count USING table_name;
END;
$$;
