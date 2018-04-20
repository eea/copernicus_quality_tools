# Dockerfile for building environment for COP15m WPS checking processes.
# Currently, it utilizes flask as wsgi server.

FROM alpine

ENV TESTING_REPO=http://dl-3.alpinelinux.org/alpine/edge/testing

# Upgrade the base system.
RUN apk update \
    && apk upgrade \
    && mkdir /usr/local/src

# Install python.
RUN apk add python3 \
    && pip3 install --upgrade pip

# Install postgresql and postgis.
# Postgis installs gdal too.
RUN apk add postgresql \
    && apk add --repository $TESTING_REPO postgis \
    && apk add py3-psycopg2

# Install python gdal.
RUN apk add g++ python3-dev \
    && apk add --repository $TESTING_REPO gdal-dev \
    && pip3 install GDAL numpy \
    && apk del g++ python3-dev gdal-dev

# Install flask & pywps.
RUN apk add git gcc musl-dev python3-dev py3-lxml \
    && pip3 install Flask \
    && cd /usr/local \
    && pip3 install -e git+https://github.com/geopython/pywps.git@4.0.0#egg=pywps-dev \
    && apk del git gcc musl-dev python3-dev
