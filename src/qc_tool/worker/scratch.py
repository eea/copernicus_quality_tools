"""Recognizable worker-local scratch with an active-job lease.

The marker lets explicit cleanup distinguish abandoned worker scratch from
unrelated files. A lease and live owner/process-group checks are complementary:
descendants can outlive the validator that owned its advisory file lock.
"""

import fcntl
import json
import os
from pathlib import Path
import stat
import sys
from socket import gethostname

from qc_tool.jobs import compact_job_uuid, normalize_job_uuid


META_FILENAME = ".qc-tool-scratch.json"
LEASE_FILENAME = ".lease"
META_FORMAT = 1


def process_namespace():
    """Identify the PID namespace in which owner PID/group checks are meaningful."""
    if sys.platform == "linux":
        return os.readlink("/proc/self/ns/pid")
    return "host:" + gethostname()


class ScratchLease:
    """Create one new scratch directory and keep its lease until explicitly closed."""

    def __init__(self, directory, job_uuid, *, retain=False):
        self.directory = Path(directory)
        self.job_uuid = normalize_job_uuid(job_uuid)
        if self.directory.name != compact_job_uuid(self.job_uuid):
            raise ValueError("Scratch directory must use the job's compact UUID.")
        self.retain = bool(retain)
        self.descriptor = None

    def __enter__(self):
        # Root provisioning is an explicit deployment responsibility. Never
        # adopt or overwrite an existing child's unknown or retained contents.
        self.directory.mkdir(mode=0o700)
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(self.directory / LEASE_FILENAME, flags, 0o600)
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
                raise ValueError("Scratch lease is not a private regular file.")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            metadata = {
                "format": META_FORMAT,
                "job_uuid": self.job_uuid,
                "retain": self.retain,
                "owner_pid": os.getpid(),
                "process_group": os.getpgrp(),
                "pid_namespace": process_namespace(),
            }
            marker = os.open(self.directory / META_FILENAME,
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600)
            with os.fdopen(marker, "w", encoding="utf-8") as stream:
                json.dump(metadata, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            directory_descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except BaseException:
            os.close(descriptor)
            # An incomplete new directory is intentionally left recognizable
            # as incomplete, never mistaken for a valid cleanup candidate.
            raise
        self.descriptor = descriptor
        return self

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
