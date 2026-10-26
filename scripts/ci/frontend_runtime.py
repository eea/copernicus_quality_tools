"""Check the supported packaged frontend, including dependencies needed by probes."""

import re
import subprocess
import sys

import django
import gunicorn  # noqa: F401 -- required by the real-server deployment probe


if sys.version_info[:3] != (3, 12, 14):
    raise SystemExit("Expected the reviewed Python 3.12.14 frontend runtime.")
if django.get_version() != "5.2.17":
    raise SystemExit("Expected the reviewed Django 5.2.17 frontend runtime.")
for executable in ("pg_dump", "pg_restore"):
    version = subprocess.check_output([executable, "--version"], text=True)
    if not re.search(r"\(PostgreSQL\) 14\.", version):
        raise SystemExit(f"Unexpected native backup client: {version}")
subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
