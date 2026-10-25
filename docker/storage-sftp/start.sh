#!/bin/sh
set -eu

if [ ! -f /etc/qc-storage/authorized_keys ] || [ ! -s /etc/qc-storage/authorized_keys ]; then
    printf '%s\n' 'Provide a nonempty maintainer public authorized_keys file.' >&2
    exit 1
fi
if [ ! -f /etc/qc-storage/host_key ] || [ ! -s /etc/qc-storage/host_key ]; then
    printf '%s\n' 'Provide the persistent private SSH host key; it is never generated at startup.' >&2
    exit 1
fi
if [ ! -d /srv/qc-storage/files ]; then
    printf '%s\n' 'The reviewed export directory is unavailable.' >&2
    exit 1
fi

mkdir -p /run/sshd
/usr/sbin/sshd -t -f /etc/ssh/sshd_config
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config
