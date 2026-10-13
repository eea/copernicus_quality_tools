---
title: Commands
parent: Reference
nav_order: 2
---

# Command reference

Examples use the local stack. Substitute the deployment's Compose files,
project name, and env file in production.

## Compose lifecycle

```bash
docker compose -f docker/compose.local.yaml config --quiet
docker compose -f docker/compose.local.yaml up --build --detach
docker compose -f docker/compose.local.yaml ps
docker compose -f docker/compose.local.yaml logs --follow frontend worker
docker compose -f docker/compose.local.yaml down
```

Destructive local reset:

```bash
docker compose -f docker/compose.local.yaml down --volumes
```

## Django

```bash
# Configuration and whole-application schema
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage check
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage database plan
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage database check

# Users
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage createsuperuser
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage changepassword <username>

# Maintenance
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage clearsessions
```

`database plan` and `database check` inspect the schema read-only. The explicit
`database apply` command initializes an entirely empty database from models,
including in production; it is a read-only no-op for a complete matching schema.
It refuses partial or foreign schemas and detected model drift. It never imports
products, converts records, resets a database or upgrades existing tables.

For a new empty target, run:

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database apply
```

Use a fresh disposable target after model changes. Follow the
[database guide](../development/database-migrations.md) before selecting persistent
storage and the [manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md)
for a prepared current-schema copy. The application ships no migration or legacy
conversion command.

## QC Tool user provisioning

For trusted automation, `create_default_user` supports canonical roles and
scope grants:

```bash
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage create_default_user \
    --username <username> \
    --password <temporary-password> \
    --group product_manager \
    --product <canonical-product-ident>
```

Repeat `--group` or `--product` for multiple values. Prefer Django
Admin or an interactive command when exposing a password on the process command
line or shell history is unacceptable.

Upload the product specification as an administrator before assigning it with
`--product`. Files in the bundled recipe directory are not available assignments
until explicitly added to the database catalog.

The command is idempotent: it does not update an existing user's password,
roles, or scopes. Use Admin or the appropriate password command for changes.

## Database shell

```bash
docker compose -f docker/compose.local.yaml exec userdb \
  psql --username qc_user --dbname qc_tool
```

Do not change users/groups through raw SQL. Django signals and services assign
the default role and synchronize staff status; raw inserts bypass them.

## Tests

See the full [testing guide](../development/testing.md).
