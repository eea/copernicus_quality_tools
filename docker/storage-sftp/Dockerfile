ARG DEBIAN_IMAGE=debian:trixie-slim
FROM ${DEBIAN_IMAGE}

RUN apt-get update \
    && apt-get install --yes --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && useradd --uid 10001 --user-group --home-dir /files \
        --shell /usr/sbin/nologin --password '*' qcstorage \
    && install -d -m 0755 -o root -g root /srv/qc-storage /srv/qc-storage/files /etc/qc-storage

COPY sshd_config /etc/ssh/sshd_config
COPY start.sh /usr/local/bin/start-storage-sftp
RUN chmod 0755 /usr/local/bin/start-storage-sftp

EXPOSE 2222
ENTRYPOINT ["/usr/local/bin/start-storage-sftp"]

