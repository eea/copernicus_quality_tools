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
  Tcount integer :=0;
	
BEGIN
	EXECUTE format('DROP TABLE IF EXISTS %1$s_ValidCodes_error', product_name);

	CASE product_type
		when 'clc' then
			CASE substring(product_name,4,2)
				when '06' then code='code_06';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when '12' then code='code_12';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;					
				when '18' then code='code_18';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;			
				else 
					SELECT 999999 INTO _ct;
			END CASE;

		when 'cha' then	
			CASE substring(product_name,4,2)
				when '06' then
					code_from='code_00';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code_from);		
					code_to='code_06';				
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;	
				when '12' then
					code_from='code_06';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code_from);						
					code_to='code_12';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code_to);
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s=%3$s and chtype <>''T''',product_name,code_from,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;	
				when '18' then
					code_from='code_12';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code_from);						
					code_to='code_18';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''CLC'')',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;	
				else 
					SELECT 999999 INTO _ct;
			END CASE;

  		when 'ua' then
			CASE right(product_name,6)
				when 'ua2006' then code='code2006';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''UA'')',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;
				when 'ua2012' then code='code2012';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''UA'')',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;					
				when 'ua2018' then code='code2018';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''UA'')',product_name,code);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;			
				else 
					SELECT 999999 INTO _ct;
			END CASE;

		when 'uacha' then
			CASE right(product_name,16)
				when 'change_2006_2012' then
					code_from='code2006';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''UA'')',product_name,code_from);						
					code_to='code2012';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''UA'')',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;	
				when 'change_2012_2018' then
					code_from='code2012';
					EXECUTE format('CREATE TABLE %1$s_ValidCodes_error AS SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''UA'')',product_name,code_from);						
					code_to='code2018';
					EXECUTE format('INSERT INTO %1$s_ValidCodes_error SELECT * FROM %1$s WHERE %2$s NOT IN (SELECT code FROM V6_code WHERE data_type=''UA'')',product_name,code_to);
					EXECUTE 'SELECT count(*) FROM ' ||  product_name || '_ValidCodes_error' INTO _ct;	
				else 
					SELECT 999999 INTO _ct;
			END CASE;
		else 
			SELECT 999999 INTO _ct;	
	END CASE;	

END  

$BODY$;