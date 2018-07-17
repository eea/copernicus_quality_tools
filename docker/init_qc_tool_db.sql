CREATE ROLE qc_job WITH LOGIN PASSWORD NULL;

CREATE DATABASE qc_tool_db WITH OWNER qc_job;

GRANT ALL PRIVILEGES ON DATABASE qc_tool_db TO qc_job;

\c qc_tool_db

ALTER SCHEMA public OWNER TO qc_job;

CREATE EXTENSION postgis;

GRANT ALL ON TABLE public.spatial_ref_sys TO qc_job;

SET ROLE TO qc_job;

CREATE SCHEMA qc_function;

ALTER ROLE qc_job SET search_path TO qc_function, public;
