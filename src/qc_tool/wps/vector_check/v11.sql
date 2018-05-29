CREATE FUNCTION __f_count_rows(_tbl regclass, OUT _ct bigint)
RETURNS bigint
LANGUAGE plpgsql
AS $$
BEGIN
   EXECUTE 'SELECT count(*) FROM ' ||  _tbl INTO _ct;
END
$$;


CREATE FUNCTION __v11_mmu_polyline_border(product_name text)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
  tmp boolean;
BEGIN

  EXECUTE format('CREATE TABLE IF NOT EXISTS %1$s_polyline_border AS SELECT ''%1$s'' ::text AS cntr, st_boundary(st_union(wkb_geometry)) AS geometry1 from %1$s', product_name);

	RETURN 'OK';
END
$$;


CREATE FUNCTION __v11_mmu_status(mmu integer, product_name text, product_border boolean, OUT _ct bigint)
RETURNS bigint
LANGUAGE plpgsql
AS $$
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
$$;


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
