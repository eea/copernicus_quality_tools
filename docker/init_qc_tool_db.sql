CREATE ROLE qc_job WITH LOGIN PASSWORD NULL;

CREATE DATABASE qc_tool_db WITH OWNER qc_job;

GRANT ALL PRIVILEGES ON DATABASE qc_tool_db TO qc_job;

\c qc_tool_db

ALTER SCHEMA public OWNER TO qc_job;

CREATE EXTENSION postgis;
CREATE EXTENSION postgis_topology;

GRANT USAGE ON SCHEMA topology to qc_job;
GRANT ALL ON ALL tables IN SCHEMA topology to qc_job;
GRANT USAGE, SELECT ON ALL sequences IN SCHEMA topology TO qc_job;

GRANT ALL ON TABLE public.spatial_ref_sys TO qc_job;
