"""Database connection of the legacy import scripts, which run in the frontend pod.

import_legacy_tables_kubernetes.py owns the configuration and passes it as QC_DB_*
variables. Anything it leaves empty comes from the POSTGRES_* variables of the
pod. (Not DB_*: Kubernetes sets DB_PORT etc. for a Service named "db".)
"""
import os

_VARIABLES = {
    "dbname": ("QC_DB_NAME", "POSTGRES_DB"),
    "user": ("QC_DB_USER", "POSTGRES_USER"),
    "password": ("QC_DB_PASSWORD", "POSTGRES_PASSWORD"),
    "host": ("QC_DB_HOST", "POSTGRES_HOST"),
    "port": ("QC_DB_PORT", "POSTGRES_PORT"),
}

DB_CONFIG = {
    key: value
    for key, names in _VARIABLES.items()
    for value in [next((os.environ[name] for name in names if os.environ.get(name)), None)]
    if value
}
