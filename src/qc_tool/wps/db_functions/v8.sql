-- FUNCTION: public.__v8_multipartpolyg(text)

-- DROP FUNCTION public.__v8_multipartpolyg(text);

CREATE OR REPLACE FUNCTION __v8_multipartpolyg(
	product_name text,
	OUT _ct bigint)
    RETURNS bigint
    LANGUAGE 'plpgsql'

    COST 100
    VOLATILE
AS $BODY$

DECLARE
  _tbl regclass;


BEGIN
	EXECUTE format('DROP TABLE IF EXISTS %1$s_MultipartPolyg_error', product_name);
	EXECUTE format('CREATE TABLE %1$s_MultipartPolyg_error AS SELECT * from (SELECT *, ST_NumGeometries(wkb_geometry) as Ngeom from %1$s order by Ngeom desc) as AAA where Ngeom>1', product_name);
	EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_MultipartPolyg_error' INTO _ct;
END

$BODY$;