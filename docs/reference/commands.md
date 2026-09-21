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
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage makemigrations --check --dry-run

# Users
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage createsuperuser
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage changepassword <username>

# Maintenance
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage clearsessions
```

During draft, `database plan` explains initialization and `database check`
verifies table/column presence. `database apply` creates missing tables from
models, without generating migration files, importing products, or altering
existing columns. Use a fresh development schema after model changes. After
freeze, these commands manage the full migration graph, and
`makemigrations --check --dry-run` detects model drift without writing files.

Use the [local verification procedure](../../src/qc_tool/database/MIGRATIONS.md#local-verification)
to apply and test changes on a disposable database. For a release, follow the
[canonical workflow](../development/database-migrations.md) and run the
application-wide `database apply` once in the documented deployment job before
frontend startup. Never use `migrate <app> zero` to create the baseline; that
command unapplies migrations.

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
