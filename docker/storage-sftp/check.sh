#!/bin/sh
# Disposable integration check. Invoke only using the documented isolated run.
set -eu

for directory in /run /etc/qc-storage /srv/qc-storage/files; do
    [ -w "$directory" ] || { printf '%s\n' 'This check requires its disposable tmpfs mounts.' >&2; exit 1; }
done

# All keys are test fixtures on disposable tmpfs; no host files are mounted.
ssh-keygen -q -t ed25519 -N '' -f /etc/qc-storage/host_key
ssh-keygen -q -t ed25519 -N '' -f /run/client_key
ssh-keygen -q -t ed25519 -N '' -f /run/unapproved_key
cp /run/client_key.pub /etc/qc-storage/authorized_keys
chmod 0644 /etc/qc-storage/authorized_keys
printf '%s\n' 'QC storage fixture' > /srv/qc-storage/files/sample.txt
chmod 0777 /srv/qc-storage/files
chmod 0666 /srv/qc-storage/files/sample.txt

/usr/local/bin/start-storage-sftp > /run/sshd.log 2>&1 &
daemon_pid=$!
trap 'kill "$daemon_pid" 2>/dev/null || true' EXIT

sftp_fixture() {
    sftp -q -b - -P 2222 -i /run/client_key -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=no -o UserKnownHostsFile=/run/known_hosts \
        -o BatchMode=yes -o ConnectTimeout=2 qcstorage@127.0.0.1
}

attempt=0
until printf 'ls /files\nget /files/sample.txt /run/download.txt\n' | sftp_fixture > /run/client.log 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 20 ]; then
        cat /run/sshd.log /run/client.log >&2
        exit 1
    fi
    sleep 0.1
done
cmp /srv/qc-storage/files/sample.txt /run/download.txt

if printf 'put /run/download.txt /files/upload.txt\n' | sftp_fixture > /run/denied.log 2>&1; then
    printf '%s\n' 'Upload unexpectedly succeeded.' >&2
    exit 1
fi
if printf 'rm /files/sample.txt\n' | sftp_fixture > /run/denied.log 2>&1; then
    printf '%s\n' 'Deletion unexpectedly succeeded.' >&2
    exit 1
fi
if printf 'rename /files/sample.txt /files/renamed.txt\n' | sftp_fixture > /run/denied.log 2>&1; then
    printf '%s\n' 'Rename unexpectedly succeeded.' >&2
    exit 1
fi
if printf 'get /etc/passwd /run/escaped.txt\n' | sftp_fixture > /run/denied.log 2>&1; then
    printf '%s\n' 'The client unexpectedly escaped the share.' >&2
    exit 1
fi
if printf 'ls /files\n' | sftp -q -b - -P 2222 -i /run/unapproved_key \
    -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/run/known_hosts qcstorage@127.0.0.1 > /run/denied.log 2>&1; then
    printf '%s\n' 'An unapproved key unexpectedly authenticated.' >&2
    exit 1
fi

# Command requests are forced into SFTP rather than a shell.
ssh -q -T -p 2222 -i /run/client_key -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/run/known_hosts \
    -o BatchMode=yes qcstorage@127.0.0.1 'touch /files/command-executed' \
    < /dev/null > /run/command.log 2>&1 || true
[ ! -e /srv/qc-storage/files/command-executed ]
forwarding_status=0
timeout 5 ssh -q -N -p 2222 -i /run/client_key -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/run/known_hosts \
    -o BatchMode=yes -o ExitOnForwardFailure=yes -R 0:127.0.0.1:2222 \
    qcstorage@127.0.0.1 > /run/forwarding.log 2>&1 || forwarding_status=$?
if [ "$forwarding_status" -ne 255 ]; then
    printf '%s\n' 'Port forwarding was not promptly rejected.' >&2
    exit 1
fi

/usr/sbin/sshd -T -f /etc/ssh/sshd_config > /run/effective-config
grep -q '^forcecommand internal-sftp -R ' /run/effective-config
grep -q '^disableforwarding yes$' /run/effective-config
grep -q '^passwordauthentication no$' /run/effective-config
grep -q '^permittty no$' /run/effective-config
cmp /srv/qc-storage/files/sample.txt /run/download.txt
[ ! -e /srv/qc-storage/files/upload.txt ]
printf '%s\n' 'SFTP listing/download authentication, read-only operations, chroot and effective restrictions passed.'
