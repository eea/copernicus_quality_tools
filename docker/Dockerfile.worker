FROM ubuntu:disco

LABEL author=gisat.cz
LABEL description="QC tool environment, worker service."

ARG VERSION

ENV PYTHONPATH=/usr/local/src/copernicus_quality_tools/src
ENV VERSION=${VERSION:-${DOCKER_TAG:-master}}

# Build the initial environment.
RUN echo "$VERSION" >/etc/qc_tool_version.txt \
    && apt-get -y update \
    && apt-get -y upgrade \
    && apt-get -y install wget unzip time

# Install python and bootstrap pip.
RUN cd /usr/local/src \
    && apt-get -y install python3 python3-distutils \
    && wget --no-verbose https://bootstrap.pypa.io/get-pip.py \
    && python3 get-pip.py

# Install environment.
RUN apt-get -y install gdal-bin python3-gdal \
    && apt-get -y install python3-psycopg2 \
    && pip3 install numpy \
    && pip3 install scikit-image reportlab requests \
    && pip3 install bottle \
    && pip3 install supervisor

# Copy supervisor config file.
COPY ./supervisord.conf /etc

# Expose the port of supervisor.
EXPOSE 9001

# Install postgresql & postgis.
# During install tzdata package needs timezone having been set already.
ENV TZ=UTC
RUN ln -s /usr/share/zoneinfo/UTC /etc/localtime \
    && apt-get -y install postgresql-11-postgis-2.5

# Configure the qc tool database.
#
# We insert qc_job/trust clause just *before* 127.0.0.1/md5 clause in pg_hba.conf,
# so that qc_job is thus allowed to connect to qc_tool_db without password even
# when connecting to 127.0.0.1.
USER postgres
COPY ./init_qc_tool_db.sql /usr/local/src
RUN sed --in-place=.orig --expression='/^# IPv4 local connections/a host  qc_tool_db  qc_job  all  trust' /etc/postgresql/11/main/pg_hba.conf \
    && echo "listen_addresses='*'" >>/etc/postgresql/11/main/postgresql.conf \
    && /etc/init.d/postgresql start \
    && psql --file=/usr/local/src/init_qc_tool_db.sql \
    && /etc/init.d/postgresql stop
USER root

# Install qc tool.
RUN cd /usr/local/src \
    && wget --no-verbose https://github.com/eea/copernicus_quality_tools/archive/${VERSION}.zip \
    && unzip -q ./${VERSION}.zip \
    && rm ./${VERSION}.zip \
    && mv ./copernicus_quality_tools-${VERSION} ./copernicus_quality_tools \
    && echo ${VERSION} >./copernicus_quality_tools/VERSION

# Expose the port of job scheduler.
EXPOSE 8000

CMD ["supervisord", "-c", "/etc/supervisord.conf"]