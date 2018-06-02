CREATE FUNCTION __f_count_rows(_tbl regclass, OUT _ct bigint)
RETURNS bigint
LANGUAGE plpgsql
AS $$
BEGIN
   EXECUTE 'SELECT count(*) FROM ' ||  _tbl INTO _ct;
END
$$;


-- FUNCTION: __v6_validcodes(text, text)
-- DROP FUNCTION __v6_validcodes(text, text);

CREATE OR REPLACE FUNCTION __v6_validcodes(
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
  code_from text;
  code_to text;
  code text;

BEGIN
	EXECUTE format('DROP TABLE IF EXISTS %1$s_ValidCodes_error', product_name);

	CASE product_type
		when 'clc' then
			CASE substring(product_name,4,2)
				when '06' then code='code_06';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when '12' then code='code_12';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when '18' then code='code_18';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				else
					SELECT 999999 INTO _ct;
			END CASE;

		when 'cha' then
			CASE substring(product_name,4,2)
				when '06' then
					code_from='code_00';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code_from);
					code_to='code_06';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when '12' then
					code_from='code_06';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code_from);
					code_to='code_12';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when '18' then
					code_from='code_12';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code_from);
					code_to='code_18';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM clc_code)',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				else
					SELECT 999999 INTO _ct;
			END CASE;

  		when 'ua' then
			CASE right(product_name,6)
				when 'ua2006' then code='code2006';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM ua_code)',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when 'ua2012' then code='code2012';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM ua_code)',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when 'ua2018' then code='code2018';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM ua_code)',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				else
					SELECT 999999 INTO _ct;
			END CASE;

		when 'uacha' then
			CASE right(product_name,16)
				when 'change_2006_2012' then
					code_from='code2006';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM ua_code)',product_name,code_from);
					code_to='code2012';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM ua_code)',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when 'change_2012_2018' then
					code_from='code2012';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM ua_code)',product_name,code_from);
					code_to='code2018';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM ua_code)',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				else
					SELECT 999999 INTO _ct;
			END CASE;
		else
			SELECT 999999 INTO _ct;
	END CASE;

END

$BODY$;


-- FUNCTION: public.__v11_mmu_change_clc(integer, text)
-- DROP FUNCTION public.__v11_mmu_change_clc(integer, text);

CREATE OR REPLACE FUNCTION __v11_mmu_change_clc(
	mmu integer,
	product_name text,
	OUT _ct bigint)
    RETURNS bigint
    LANGUAGE 'plpgsql'

    COST 100
    VOLATILE
AS $BODY$

DECLARE
  _tbl regclass;
  product_name_status_to text;
  code_from text;
  code_to text;

BEGIN
  EXECUTE format('DROP TABLE IF EXISTS cha_diss_from CASCADE');
  EXECUTE format('DROP TABLE IF EXISTS cha_diss_to CASCADE');

  EXECUTE format('DROP TABLE IF EXISTS %1$s_lessMMU_error', product_name);
  EXECUTE format('DROP TABLE IF EXISTS %1$s_lessMMU_except', product_name);

  EXECUTE format('DROP TABLE IF EXISTS cha_within_from CASCADE');
  EXECUTE format('DROP TABLE IF EXISTS cha_within_to CASCADE');

  IF position('cha' IN product_name)>0 THEN

		product_name_status_to = overlay(product_name placing 'clc' from position('cha' IN product_name));

		IF position('06' IN product_name)>0 THEN
			code_from = 'code_00';
			code_to = 'code_06';
		END IF;

		IF position('12' IN product_name)>0 THEN
			code_from = 'code_06';
			code_to = 'code_12';
		END IF;

		IF position('18' IN product_name)>0 THEN
			code_from = 'code_12';
			code_to = 'code_18';
		END IF;


--		## create polyline border using status destination layer
		PERFORM __V11_MMU_polyline_border(product_name_status_to);

		--EXECUTE format('DROP TABLE IF EXISTS cha_le50_nb CASCADE);
		--EXECUTE format('CREATE TABLE cha_le50_nb AS SELECT c.* from %1$s c, %2$s_polyline_border b where (NOT (ST_INTERSECTS(c.wkb_geometry, b.geometry1)) AND c.shape_area < %3$s)', product_name, product_name_status_to, mmu::text);

--		## preparation of table for _error
		EXECUTE format('CREATE TABLE %1$s_lessMMU_error AS SELECT c.* from %1$s c, %2$s_polyline_border b where (NOT (ST_INTERSECTS(c.wkb_geometry, b.geometry1)) AND c.shape_area < %3$s)', product_name, product_name_status_to, mmu::text);

--		FROM:
--		##dissolve by code_from
		EXECUTE format('CREATE OR REPLACE VIEW cha_diss_from_multi AS select %2$s, st_union(wkb_geometry) AS geometry1 from %1$s group by %2$s', product_name, code_from);
		EXECUTE format('CREATE OR REPLACE VIEW cha_diss_from_view AS select ''%1$s'' ::text as cntr, %2$s, ST_Area((st_dump(geometry1)).geom)::numeric as area_from, (st_dump(geometry1)).geom as geometry2 FROM cha_diss_from_multi', product_name, code_from);
		EXECUTE format('CREATE TABLE cha_diss_from AS select cha_diss_from_view.* from cha_diss_from_view where cha_diss_from_view.area_from > %1$s',mmu::text);

--		##create table where potential error polygons are within complex change dissolve_from
		EXECUTE format('CREATE TABLE cha_within_from AS select c.* from %1$s_lessMMU_error c, cha_diss_from b where (st_within(c.wkb_geometry,b.geometry2))',product_name);

--		##delete polygons which are within complex change dissolve_from    from error layer
		EXECUTE format('DELETE from %1$s_lessMMU_error using cha_within_from where %1$s_lessMMU_error.id=cha_within_from.id',product_name);


--		TO:
--		##dissolve by code_to
		EXECUTE format('CREATE OR REPLACE VIEW cha_diss_to_multi AS select %2$s, st_union(wkb_geometry) AS geometry1 FROM %1$s group by %2$s', product_name, code_to);
		EXECUTE format('CREATE OR REPLACE VIEW cha_diss_to_view AS select ''%1$s'' ::text as cntr, %2$s, ST_Area((st_dump(geometry1)).geom)::numeric as area_to, (st_dump(geometry1)).geom as geometry2 FROM cha_diss_to_multi', product_name, code_to);
		EXECUTE format('CREATE TABLE cha_diss_to AS select cha_diss_to_view.* FROM cha_diss_to_view where cha_diss_to_view.area_to > %1$s',mmu::text);
		-- EXECUTE format('DROP VIEW IF EXISTS cha_diss_to_multi');

--		##create table where potential error polygons are within complex change dissolve_to
		EXECUTE format('CREATE TABLE cha_within_to AS select c.* FROM %1$s_lessMMU_error c, cha_diss_to b where (st_within(c.wkb_geometry,b.geometry2))',product_name);

--		##delete polygons which are within complex change dissolve_to    from error layer
		EXECUTE format('DELETE FROM %1$s_lessMMU_error using cha_within_to where %1$s_lessMMU_error.id=cha_within_to.id',product_name);

--		##% cha12_lessMMU_error is ready!


--		## now exceptions:
--		## preparation of table for _exceptions
		EXECUTE format('CREATE TABLE %1$s_lessMMU_except AS SELECT c.* from %1$s c, %2$s_polyline_border b where (ST_INTERSECTS(c.wkb_geometry, b.geometry1) AND c.shape_area < %3$s)', product_name, product_name_status_to, mmu::text);
		EXECUTE format('INSERT INTO %1$s_lessMMU_except SELECT * FROM cha_within_from',product_name);
		EXECUTE format('INSERT INTO %1$s_lessMMU_except SELECT * FROM cha_within_to',product_name);

--		## RETURNS:
		EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_lessMMU_error' INTO _ct;
  ELSE
		SELECT 999999 INTO _ct;
  END IF;

 -- RETURN product_name_status_to;
 -- RETURN 'OK';

END

$BODY$;



-- FUNCTION: __v11_mmu_polyline_border(text)
-- DROP FUNCTION __v11_mmu_polyline_border(text);

CREATE OR REPLACE FUNCTION __v11_mmu_polyline_border(
	product_name text)
    RETURNS text
    LANGUAGE 'plpgsql'

    COST 100
    VOLATILE
AS $BODY$

DECLARE
  tmp boolean;
BEGIN

  EXECUTE format('CREATE TABLE IF NOT EXISTS %1$s_polyline_border AS SELECT ''%1$s'' ::text AS cntr, st_boundary(st_union(wkb_geometry)) AS geometry1 from %1$s', product_name);

	RETURN 'OK';
END

$BODY$;


-- FUNCTION: public.__v11_mmu_status(integer, text, boolean)
-- DROP FUNCTION public.__v11_mmu_status(integer, text, boolean);

CREATE OR REPLACE FUNCTION public.__v11_mmu_status(
	mmu integer,
	product_name text,
	product_border boolean,
	OUT _ct bigint)
    RETURNS bigint
    LANGUAGE 'plpgsql'

    COST 100
    VOLATILE
AS $BODY$

DECLARE
  _tbl regclass;
BEGIN
  EXECUTE format('DROP TABLE IF EXISTS %1$s_lessMMU_error', product_name);
  EXECUTE format('DROP TABLE IF EXISTS %1$s_lessMMU_except', product_name);

  CASE product_border
     WHEN true then
		PERFORM __V11_MMU_polyline_border(product_name);
		EXECUTE format('CREATE TABLE %1$s_lessMMU_error AS SELECT c.* from %1$s c, %1$s_polyline_border b where (NOT (ST_INTERSECTS(c.wkb_geometry, b.geometry1))) AND c.shape_area < %2$s',product_name, mmu::text);
		EXECUTE format('CREATE TABLE %1$s_lessMMU_except AS SELECT c.* from %1$s c, %1$s_polyline_border b where ((ST_INTERSECTS(c.wkb_geometry, b.geometry1))) AND c.shape_area < %2$s',product_name, mmu::text);
		EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_lessMMU_error' INTO _ct;

	 ELSE
		EXECUTE format('CREATE TABLE %1$s_lessMMU_error AS SELECT c.* from %1$s c where c.shape_area < %2$s',product_name, mmu::text);
		EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_lessMMU_error' INTO _ct;
  END CASE;

  -- RETURN 'OK';
END

$BODY$;


CREATE FUNCTION __v11_mmu_change(mmu integer, product_name text, product_type text, product_border boolean, code_from text, code_to text)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
  _tbl regclass;
  product_name_status_to text;


BEGIN
  EXECUTE format('DROP TABLE IF EXISTS cha_diss_from');
  EXECUTE format('DROP TABLE IF EXISTS cha_diss_to');

  EXECUTE format('DROP TABLE IF EXISTS %1$s_lessMMU_error', product_name);
  EXECUTE format('DROP TABLE IF EXISTS %1$s_lessMMU_except', product_name);

  CASE product_border
     WHEN true then
		IF position('cha' IN product_name)>0 THEN
			product_name_status_to = overlay(product_name placing 'clc' from position('cha' IN product_name));
		END IF;

		PERFORM __V11_MMU_polyline_border(product_name_status_to);

--		FROM:
--		##dissolve by code_from
		EXECUTE format('CREATE OR REPLACE VIEW cha_diss_from_multi AS select %2$s, st_union(wkb_geometry) AS geometry1 from %1$s group by %2$s', product_name, code_from);
		EXECUTE format('CREATE TABLE cha_diss_from AS select ''%1$s'' ::text as cntr, %2$s, ST_Area((st_dump(geometry1)).geom)::numeric as area_from, (st_dump(geometry1)).geom as geometry2 from cha_diss_from_multi', product_name, code_from);
		EXECUTE format('DROP VIEW IF EXISTS cha_diss_from_multi');

--		##selection where cha_diss_from  not intersect border and area_from < MMU
		EXECUTE format('CREATE TABLE cha_diss_from_error AS SELECT c.* from cha_diss_from c, %1$s_polyline_border b where (NOT (ST_INTERSECTS(c.geometry2, b.geometry1)) AND c.area_from < %2$s)', product_name_status_to, mmu::text);
--		CREATE TABLE cha_diss_from_error_test AS SELECT c.* from cha_diss_from c, clc12_cz_polyline_border b where (NOT (ST_INTERSECTS(c.geometry2, b.geometry1)) AND c.area_from < 60000)

--		TO:
--		##dissolve by code_to
		EXECUTE format('CREATE OR REPLACE VIEW clc_cha_diss_to_multi AS select %2$s, st_union(wkb_geometry) AS geometry1 from %1$s group by %2$s', product_name, code_to);
		EXECUTE format('CREATE TABLE cha_diss_to AS select ''%1$s'' ::text as cntr, %2$s, ST_Area((st_dump(geometry1)).geom)::numeric as area_to, (st_dump(geometry1)).geom as geometry2 from clc_cha_diss_to_multi', product_name, code_to);
		EXECUTE format('DROP VIEW IF EXISTS clc_cha_diss_to_multi');

--		##selection where cha_diss_to  not intersect border and area_to < MMU
		EXECUTE format('CREATE TABLE cha_diss_to_error AS SELECT c.* from cha_diss_to c, %1$s_polyline_border b where (NOT (ST_INTERSECTS(c.geometry2, b.geometry1)) AND c.area_to < %2$s)', product_name_status_to, mmu::text);

--		EXECUTE format('CREATE TABLE %1$s_lessMMU_error AS SELECT c.* from %1$s c, %1$s_polyline_border b where (NOT (ST_INTERSECTS(c.wkb_geometry, b.geometry1))) AND c.shape_area < %2$s',product_name, mmu::text);
--		EXECUTE format('CREATE TABLE %1$s_lessMMU_except AS SELECT c.* from %1$s c, %1$s_polyline_border b where ((ST_INTERSECTS(c.wkb_geometry, b.geometry1))) AND c.shape_area < %2$s',product_name, mmu::text);
--		EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_lessMMU_error' INTO _ct;

	 ELSE
--		EXECUTE format('CREATE TABLE %1$s_lessMMU_error AS SELECT c.* from %1$s c where c.shape_area < %2$s',product_name, mmu::text);
--		EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_lessMMU_error' INTO _ct;
  END CASE;

  RETURN product_name_status_to;
  -- RETURN 'OK';

END
$$;
