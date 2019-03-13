FROM ubuntu:bionic

LABEL author=gisat.cz
LABEL description="QC tool environment, postgis service."

# Add repositories and upgrade the system.
RUN apt-get -y update \
    && apt-get -y upgrade

# Install postgresql & postgis.
# During install tzdata package needs timezone already setup.
ENV TZ=UTC
RUN ln -s /usr/share/zoneinfo/UTC /etc/localtime \
    && apt-get -y install postgresql-10-postgis-2.4

USER postgres

# Configure the qc tool database.
#
# We insert qc_job/trust clause just *before* 127.0.0.1/md5 clause in pg_hba.conf,
# so that qc_job is thus allowed to connect to qc_tool_db without password even
# when connecting to 127.0.0.1.
COPY ./init_qc_tool_db.sql /usr/local/src
RUN sed --in-place=.orig --expression='/^# IPv4 local connections/a host  qc_tool_db  qc_job  all  trust' /etc/postgresql/10/main/pg_hba.conf \
    && echo "listen_addresses='*'" >>/etc/postgresql/10/main/postgresql.conf \
    && /etc/init.d/postgresql start \
    && psql --file=/usr/local/src/init_qc_tool_db.sql \
    && /etc/init.d/postgresql stop

VOLUME ["/var/log/postgresql"]

EXPOSE 5432

CMD ["/usr/lib/postgresql/10/bin/postgres", "-D", "/var/lib/postgresql/10/main", "-c", "config_file=/etc/postgresql/10/main/postgresql.conf"]