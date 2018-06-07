-- FUNCTION: public.__v5_uniqueid(text, text)

-- DROP FUNCTION public.__v5_uniqueid(text, text);

CREATE OR REPLACE FUNCTION __v5_uniqueid(
	product_name text,
	product_type text,
	OUT _ct bigint)
    RETURNS bigint
    LANGUAGE 'plpgsql'

    COST 100
    VOLATILE
AS $BODY$

DECLARE
  _tbl regclass;

BEGIN
	EXECUTE format('DROP TABLE IF EXISTS %1$s_UniqueID_error', product_name);
	DROP TABLE IF EXISTS V5temp;

	CASE
		when product_type='clc' OR product_type='cha' then
			EXECUTE format('CREATE TABLE V5temp AS select id as UID, count(id) as UIDcount from %1$s group by id having count(id) > 1',product_name);
			EXECUTE format('CREATE TABLE %1$s_uniqueID_error AS SELECT * from %1$s, V5temp where %1$s.id = V5temp.uid',product_name);
			EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_uniqueID_error' INTO _ct;

  		when product_type='ua' OR product_type='uacha' then
			EXECUTE format('CREATE TABLE V5temp AS select ident as UID, count(ident) as UIDcount from %1$s group by ident having count(ident) > 1',product_name);
			EXECUTE format('CREATE TABLE %1$s_uniqueID_error AS SELECT * from %1$s, V5temp where %1$s.ident = V5temp.uid',product_name);
			EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_uniqueID_error' INTO _ct;
		else
			SELECT 999999 INTO _ct;
	END CASE;

	DROP TABLE IF EXISTS V5temp;
END

$BODY$;
--TEST1
