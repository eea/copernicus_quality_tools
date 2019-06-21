# Dockerfile for building web console.
# It utilizes django.

FROM ubuntu:disco

LABEL author=gisat.cz
LABEL description="QC tool environment, frontend service."

ARG VERSION

ENV PYTHONPATH=/usr/local/src/copernicus_quality_tools/src
ENV VERSION=${VERSION:-${DOCKER_TAG:-master}}

# Build the initial environment.
RUN echo "$VERSION" >/etc/qc_tool_version.txt \
    && apt-get -y update \
    && apt-get -y upgrade \
    && apt-get -y install wget unzip

# Install python and bootstrap pip
RUN cd /usr/local/src \
    && apt-get -y install python3 python3-distutils \
    && wget --no-verbose https://bootstrap.pypa.io/get-pip.py \
    && python3 get-pip.py

# Install qc tool, frontend application.
RUN cd /usr/local/src \
    && wget --no-verbose https://github.com/eea/copernicus_quality_tools/archive/${VERSION}.zip \
    && unzip ./${VERSION}.zip \
    && rm ./${VERSION}.zip \
    && mv ./copernicus_quality_tools-${VERSION} ./copernicus_quality_tools \
    && cd copernicus_quality_tools/src/qc_tool/frontend \
    && pip3 install -r ./requirements.txt \
    && mkdir /var/lib/qc_tool
EXPOSE 8000

# Run frontend application.
COPY ./run_frontend.sh /
RUN chmod +x /run_frontend.sh
CMD /run_frontend.sh