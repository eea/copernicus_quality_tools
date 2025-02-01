#!/bin/bash

# Requires:
# -unzip
# -curl
# -wget

cp /etc/hosts /etc/squid_hosts
echo "127.0.0.1 inspire.ec.europa.eu" >> /etc/squid_hosts

#rm -rf /var/run/apache2/apache2.pid
#service apache2 start
#service apache2 reload

# rm -rf /var/spool/squid3/*
# service squid start
# service squid restart
basicArtifactoryUrl=$REPO_URL
appServerDeplPath=/usr/local/jetty/webapps
appServerUserGroup=root:root


wgetRcFile="/root/.wgetrc"
touch $wgetRcFile
echo "user=$REPO_USER" >> $wgetRcFile
echo "password=$REPO_PWD" >> $wgetRcFile

if [[ -n "$HTTP_PROXY_HOST" && "$HTTP_PROXY_HOST" != "none" ]] || [[ -n "$HTTPS_PROXY_HOST" && "$HTTPS_PROXY_HOST" != "none" ]]; then
 echo "use_proxy=on" >> $wgetRcFile
fi

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

# $1 relative path, $2 egrep regex, $3 destination
getLatestFromII() {
    url=$basicArtifactoryUrl/$1
    eex=$2
    dest=$3
    versionSubPath=$(wget -O- $url | grep -v "maven" | grep -o -E 'href="([^"#]+)"' | cut -d'"' -f2 | sort -V | tail -1)
    latest=$(wget -O- $url/$versionSubPath | egrep -o $eex | sort -V | tail -1)
    echo $latest
    wget -q $url/$versionSubPath/$latest -O $dest
    # TODO verifiy checksum
    md5sum $dest
    chown -R $appServerUserGroup $dest
}

# $1 relative path, $2 egrep regex, $version, $4 destination
getSpecificFromII() {
    url=$basicArtifactoryUrl/$1
    eex=$2
    version=$3
    dest=$4
    versionSubPath=$(wget -O- $url | grep -v "maven" | grep $version | grep -o -E 'href="([^"#]+)"' | cut -d'"' -f2 | sort -V | tail -1)
    latest=$(wget -O- $url/$versionSubPath | egrep -o $eex | sort -V | tail -1)
    wget -q $url/$versionSubPath/$latest -O $dest
    # TODO verifiy checksum
    md5sum $dest
    chown -R $appServerUserGroup $dest
}

# $1 full path with artifact name and version, $2 destination
getFrom() {
    url=$1
    dest=$2
    wget -q $url -O $dest
}

#$1 relative path, $2 egrep, $3 configured value, $4 destination
get() {
    if [ "$3" == "latest" ]; then
        getLatestFromII $1 $2 $4
    else
        getSpecificFromII $1 $2 $3 $4
    fi
}

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

#mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport "$EFS_FILESYSTEM":/ "$ETF_DIR"
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
unzip -o ui.zip -d "$ETF_DIR"

if [ ! -n "$ETF_RELATIVE_URL" ]; then
    ETF_RELATIVE_URL=etf-webapp
fi

# Download Webapp
if [ ! -f "$appServerDeplPath/$ETF_RELATIVE_URL".war ]; then
    echo "Downloading ETF. This may take a while..."
    get de/interactive_instruments/etf/etf-webapp etf-webapp-[0-9\.]+.war "$ETF_WEBAPP_VERSION" "$appServerDeplPath/$ETF_RELATIVE_URL".war
fi

# Download Executable Test Suites
if [[ -n "$ETF_DL_TESTPROJECTS_ZIP" && "$ETF_DL_TESTPROJECTS_ZIP" != "none" ]]; then
  if [ "$ETF_DL_TESTPROJECTS_OVERWRITE_EXISTING" == "true" ]; then
    rm -R "$ETF_DIR"/projects/"$ETF_DL_TESTPROJECTS_DIR_NAME"
  fi
  if [ -d "$ETF_DIR"/projects/"$ETF_DL_TESTPROJECTS_DIR_NAME" ]; then
    echo "Using existing Executable Test Suites, skipping download"
  else
  	echo "Downloading Executable Test Suites"
    wget -q "$ETF_DL_TESTPROJECTS_ZIP" -O projects.zip
    mkdir -p "$ETF_DIR"/projects/"$ETF_DL_TESTPROJECTS_DIR_NAME"
    unzip -o projects.zip -d "$ETF_DIR"/projects/"$ETF_DL_TESTPROJECTS_DIR_NAME"
    rm master.zip
  fi
fi


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

#if ! command -v -- "$1" >/dev/null 2>&1 ; then
#	set -- java -jar "$JETTY_HOME/start.jar" $javaHttpProxyOpts $javaHttpsProxyOpts "$@"
#fi

#if [ "$1" = "java" -a -n "$JAVA_OPTIONS" ] ; then
#	shift
#	set -- java -Djava.io.tmpdir=$TMPDIR $JAVA_OPTIONS "$@"
#fi

#echo "127.0.0.1 inspire.ec.europa.eu" >> /etc/hosts

exec "$@"
