CREATE OR REPLACE FUNCTION __v14_neighbcodes(
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
  id text;
	
BEGIN
	EXECUTE format('DROP TABLE IF EXISTS %1$s_NeighbCodes_error', product_name);

	CASE product_type
		when 'clc' then
			CASE upper(substring(product_name,1,5))
				when 'CLC06' then code='code_06';
				when 'CLC12' then code='code_12';				
				when 'CLC18' then code='code_18';				
				else 
					SELECT 999999 INTO _ct;
					RETURN;
			END CASE; 
			id = 'id';
		when 'cha' then	
			code='change';
			id = 'id';
			IF upper(substring(product_name,1,5)) not in ('CHA06','CHA12','CHA18')
			then 
				SELECT 999999 INTO _ct;
				RETURN;				
			END IF;
		when 'ua' then	
			CASE upper(right(product_name,6))
				when 'UA2006' then code='code2006';
				when 'UA2012' then code='code2012';				
				when 'UA2018' then code='code2018';				
				else 
					SELECT 999999 INTO _ct;
					RETURN;
			END CASE; 
			id = 'ident';
		when 'uacha' then
			CASE upper(right(product_name,16))
				when 'CHANGE_2006_2012' then
					code = 'code2006,code2012';
				when 'CHANGE_2012_2018' then
					code = 'code2012,code2018';		
				else 
					SELECT 999999 INTO _ct;
					RETURN;
			END CASE; 	
			id = 'ident';

		else 
			SELECT 999999 INTO _ct;	
			RETURN;
	END CASE;	
		
					--create layer: singlepart dissolve by code 
		    EXECUTE format('DROP TABLE IF EXISTS %1$s_DISScode12SP', product_name);
		    EXECUTE format('CREATE TABLE %1$s_DISScode12SP AS select %2$s, (st_dump(st_union(wkb_geometry))).geom as geometry1 from %1$s group by %2$s',product_name,code);
					-- add field id_diss (primary key)
		    EXECUTE format('ALTER TABLE %1$s_DISScode12SP ADD COLUMN id_diss serial PRIMARY KEY',product_name);
					--create layer: Point layer of source polygon
		    EXECUTE format('DROP TABLE IF EXISTS %1$s_P',product_name);
		    EXECUTE format('CREATE TABLE %1$s_P AS SELECT %2$s, ST_PointOnSurface(wkb_geometry) AS geometry1 from %1$s',product_name,id);

					-- create indexex
		     EXECUTE format('CREATE INDEX  %1$s_p_index1 ON %1$s_p USING GIST (geometry1)',product_name);
		     EXECUTE format('CREATE INDEX %1$s_disscode12sp_index2 ON %1$s_disscode12sp USING GIST (geometry1)',product_name);

					-- id_diss update
		     EXECUTE format('ALTER TABLE %1$s_p ADD COLUMN id_diss integer',product_name);
		     EXECUTE format('UPDATE %1$s_p SET id_diss = %1$s_disscode12sp.id_diss FROM %1$s_disscode12sp WHERE ST_Within(%1$s_p.geometry1, %1$s_disscode12sp.geometry1)',product_name);

		     EXECUTE format('DROP TABLE IF EXISTS CCC',product_name);
		     EXECUTE format('CREATE TABLE CCC AS SELECT id_diss, count(%2$s)  from %1$s_P group by id_diss having count(id_diss) > 1',product_name,id);
		     EXECUTE format('DROP TABLE IF EXISTS DDD',product_name);
		     EXECUTE format('CREATE TABLE DDD  AS SELECT %1$s_p.%2$s from %1$s_P JOIN CCC ON %1$s_P.id_diss=CCC.id_diss',product_name,id);

			 EXECUTE format('DROP TABLE IF EXISTS %1$s_NeighbCode_error',product_name);
			 EXECUTE format('CREATE TABLE %1$s_NeighbCode_error AS select %1$s.* from %1$s JOIN DDD ON %1$s.%2$s=DDD.%2$s',product_name,id);
			 EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_NeighbCode_error' INTO _ct;
	
END

$BODY$;

