#!/bin/bash

# Requires:
# -unzip
# -curl
# -wget

cp /etc/hosts /etc/squid_hosts
echo "127.0.0.1 inspire.ec.europa.eu" >> /etc/squid_hosts

rm -f /var/run/squid.pid
rm -rf /var/run/apache2/apache2.pid

#service apache2 start
#service apache2 reload

# rm -rf /var/spool/squid3/*
# service squid start
# service squid restart


javaHttpProxyOpts=""
if [[ -n "$HTTP_PROXY_HOST" && "$HTTP_PROXY_HOST" != "none" ]]; then
  if [[ -n "$HTTP_PROXY_USERNAME" && "$HTTP_PROXY_USERNAME" != "none" ]]; then
    echo "Using HTTP proxy server $HTTP_PROXY_HOST on port $HTTP_PROXY_PORT as user $HTTP_PROXY_USERNAME"
    javaHttpProxyOpts="-Dhttp.proxyHost=$HTTP_PROXY_HOST -Dhttp.proxyPort=$HTTP_PROXY_PORT -Dhttp.proxyUser=$HTTP_PROXY_USERNAME -Dhttp.proxyPassword=$HTTP_PROXY_PASSWORD"
    echo "http_proxy=http://$HTTP_PROXY_USERNAME:$HTTP_PROXY_PASSWORD@$HTTP_PROXY_HOST:$HTTP_PROXY_PORT" >> $wgetRcFile
  else
    echo "Using HTTP proxy server $HTTP_PROXY_HOST on port $HTTP_PROXY_PORT"
    javaHttpProxyOpts="-Dhttp.proxyHost=$HTTP_PROXY_HOST -Dhttp.proxyPort=$HTTP_PROXY_PORT"
    echo "http_proxy=http://$HTTP_PROXY_HOST:$HTTP_PROXY_PORT" >> $wgetRcFile
  fi
fi

javaHttpsProxyOpts=""
if [[ -n "$HTTPS_PROXY_HOST" && "$HTTPS_PROXY_HOST" != "none" ]]; then
  if [[ -n "$HTTPS_PROXY_USERNAME" && "$HTTPS_PROXY_USERNAME" != "none" ]]; then
    echo "Using HTTP Secure proxy server $HTTPS_PROXY_HOST on port $HTTPS_PROXY_PORT as user $HTTPS_PROXY_USERNAME"
    javaHttpsProxyOpts="-Dhttps.proxyHost=$HTTPS_PROXY_HOST -Dhttps.proxyPort=$HTTPS_PROXY_PORT -Dhttps.proxyUser=$HTTPS_PROXY_USERNAME -Dhttps.proxyPassword=$HTTPS_PROXY_PASSWORD"
    echo "https_proxy=https://$HTTPS_PROXY_USERNAME:$HTTPS_PROXY_PASSWORD@$HTTPS_PROXY_HOST:$HTTPS_PROXY_PORT" >> $wgetRcFile
  else
    echo "Using HTTP Secure proxy server $HTTPS_PROXY_HOST on port $HTTPS_PROXY_PORT"
    javaHttpsProxyOpts="-Dhttps.proxyHost=$HTTPS_PROXY_HOST -Dhttps.proxyPort=$HTTPS_PROXY_PORT"
    echo "https_proxy=https://$HTTPS_PROXY_HOST:$HTTPS_PROXY_PORT" >> $wgetRcFile
  fi
fi

set -x

max_mem_kb=0
xms_xmx=""
if [[ -n "$MAX_MEM" && "$MAX_MEM" != "max" && "$MAX_MEM" != "0" ]]; then
  re='^[0-9]+$'
  if ! [[ $MAX_MEM =~ $re ]] ; then
     echo "MAX_MEM: Not a number" >&2; exit 1
  fi
  max_mem_kb=$(($MAX_MEM*1024))
  xms_xmx="-Xms1g -Xmx${max_mem_kb}k"
else
  # in KB
  max_mem_kb=$(cat /proc/meminfo | grep MemTotal | awk '{ print $2 }')

  # 4 GB in kb
  if [[ $max_mem_kb -lt 4194304 ]]; then
    xms_xmx="-Xms1g"
  else
    # 2 GB for system
    xmx_kb=$(($max_mem_kb-2097152))
    xms_xmx="-Xms2g -Xmx${xmx_kb}k"
  fi
fi

if [[ $max_mem_kb -lt 1048576 ]]; then
  echo "At least 1GB ram is required"
  exit 1;
fi

JAVA_OPTIONS="-server $xms_xmx $javaHttpProxyOpts $javaHttpsProxyOpts -Xdebug -Xrunjdwp:transport=dt_socket,server=y,suspend=n,address=1044"
export JAVA_OPTIONS
echo "Using JAVA_OPTIONS: ${JAVA_OPTIONS}"

mkdir -p "$ETF_DIR"/bak
mkdir -p "$ETF_DIR"/td
mkdir -p "$ETF_DIR"/logs
mkdir -p "$ETF_DIR"/http_uploads
mkdir -p "$ETF_DIR"/testdata
mkdir -p "$ETF_DIR"/ds/obj
mkdir -p "$ETF_DIR"/ds/appendices
mkdir -p "$ETF_DIR"/ds/attachments
mkdir -p "$ETF_DIR"/ds/db/repo
mkdir -p "$ETF_DIR"/ds/db/data
mkdir -p "$ETF_DIR"/projects
mkdir -p "$ETF_DIR"/config

#unzip -o ui.zip -d "$ETF_DIR"

chmod 770 -R "$ETF_DIR"/td

chmod 775 -R "$ETF_DIR"/ds/obj
chmod 770 -R "$ETF_DIR"/ds/db/repo
chmod 770 -R "$ETF_DIR"/ds/db/data
chmod 770 -R "$ETF_DIR"/ds/appendices
chmod 775 -R "$ETF_DIR"/ds/attachments

chmod 777 -R "$ETF_DIR"/projects
chmod 777 -R "$ETF_DIR"/config

chmod 775 -R "$ETF_DIR"/http_uploads
chmod 775 -R "$ETF_DIR"/bak
chmod 775 -R "$ETF_DIR"/testdata

touch "$ETF_DIR"/logs/etf.log
chmod 775 "$ETF_DIR"/logs/etf.log

chown -fR $appServerUserGroup $ETF_DIR


exec "$@"
