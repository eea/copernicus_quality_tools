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
  python3 -m qc_tool.frontend.manage maintenance status
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage maintenance on
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage maintenance check --generation <current-generation>
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage maintenance off --generation <current-generation>

# Session cleanup (an operator DB writer; do not run during a backup)
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage clearsessions
```

Normal maintenance is controlled through **Admin → Maintenance mode**.
The commands provide operator recovery when the signed-in session expires.
Both control the same persistent state without a Docker environment setting or
container restart.
`on` and `check` return nonzero while stopping is incomplete; check their exit
status before starting a backup. `status` reports state, and `off` requires
confirmed readiness. First use can initialize private maintenance storage;
`status` never performs a readiness transition or writes the application DB.
Follow the [maintenance runbook](../deployment/maintenance.md)
for generation checks, worker retirement and backup/schema boundaries.

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

## Record transfer operations

The administrator UI creates reviewed operations and launches the dedicated
runner. These commands inspect or recover an existing operation; they do not
accept SQL, create a schema or bypass package/maintenance validation.

```bash
python3 -m qc_tool.frontend.manage data_transfer status <operation-uuid>
python3 -m qc_tool.frontend.manage data_transfer run <operation-uuid>
python3 -m qc_tool.frontend.manage data_transfer retry <operation-uuid>
python3 -m qc_tool.frontend.manage data_transfer cancel <operation-uuid>
```

Run inside the frontend container with its normal database, storage and control
configuration. `run` is also the dedicated subprocess invoked by the UI.
`retry` retains the original operation identity and verifies the durable outcome;
an active process-owned lock prevents a second runner. `cancel` refuses committed
or unsafe interrupted imports. A transfer pins maintenance until it completes or
safe cancellation is recorded. No command automatically disables maintenance.

Follow the [record transfer guide](../user-guide/record-transfers.md) for scope,
account mapping, compatibility and interrupted-operation recovery.

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

Optional `--email` must be a valid address; omitting it leaves the field blank.
Invalid addresses are rejected before creating an account.

Upload the product specification as an administrator before assigning it with
`--product`. Files in the bundled recipe directory are not available assignments
until explicitly added to the database catalog.

The command is idempotent: it does not update an existing user's password,
email, roles, or scopes. Use Admin or the appropriate password command for changes.

## Database shell

```bash
docker compose -f docker/compose.local.yaml exec userdb \
  psql --username qc_user --dbname qc_tool
```

Do not change users/groups through raw SQL. Django signals and services assign
the default role and synchronize staff status; raw inserts bypass them.

## Tests

See the full [testing guide](../development/testing.md).
