# Application schema

QC Tool uses one application database. Django models are the executable schema
specification; this reference explains their ownership and persistence rules.
The [database runbook](MIGRATIONS.md) owns initialization and release changes.

## Naming and ownership

Each managed QC Tool model declares an explicit `Meta.db_table`. Table names use
singular, lowercase words separated by underscores and a business-domain prefix.
Named indexes and constraints follow the same domain vocabulary. Names describe
the stored fact independently of the Python package or UI that displays it.

These prefixes group tables within one database. They do not create separate
PostgreSQL schemas, services or release procedures. Django app labels remain
framework identities for model discovery, content types and permissions;
`accounts` and `dashboard` participate in one centrally managed migration graph.

### Accounts

Models are owned and exported by [`accounts.models`](../frontend/accounts/models/__init__.py).
They do not import dashboard models.

| Table | Model | Stored facts |
| --- | --- | --- |
| `account_profile` | [UserProfile](../frontend/accounts/models/user_profile.py) | Account profile metadata |
| `account_api_token` | [PersonalAccessToken](../frontend/accounts/models/api_tokens.py) | Named token digests and issuance-time access snapshots |
| `account_product_grant` | [UserProductGrant](../frontend/accounts/models/product_grants.py) | Explicit user scope for a canonical QC-definition identifier |
| `account_region_grant` | [UserRegionGrant](../frontend/accounts/models/region_grants.py) | Explicit user scope for an exact region code |

Django owns users, groups, permissions, content types, sessions, admin history
and the migration recorder. Their standard `auth_*` and `django_*` tables remain
framework-managed. `AccountCapability` is an unmanaged permission anchor, so it
has a content type and permissions but creates no application table.

### Catalog

These models belong to the [catalog domain](../frontend/dashboard/domain/catalog/__init__.py)
and are discovered by the `dashboard` app.

| Table | Model | Stored facts |
| --- | --- | --- |
| `catalog_product` | [Product](../frontend/dashboard/domain/catalog/product.py) | Business product identity and display metadata |
| `catalog_release_revision` | [ProductRelease](../frontend/dashboard/domain/catalog/product_release.py) | A versioned release scope, coverage state and current-revision selection |
| `catalog_definition_revision` | [QcDefinition](../frontend/dashboard/domain/catalog/qc_definition.py) | An immutable executable definition document and digest |
| `catalog_release_definition` | [ProductReleaseDefinition](../frontend/dashboard/domain/catalog/product_release_definition.py) | Explicit release-to-definition revision mapping |
| `catalog_release_aoi` | [ProductAOI](../frontend/dashboard/domain/catalog/product_aoi.py) | One expected AOI within a specific release revision |

Business products, executable definitions and expected AOIs are distinct facts.
An expected AOI is release-specific; a worker observation cannot add one to the
catalog. Catalog synchronization is an explicit operation, separate from schema
initialization.

### Execution and storage

| Table | Model | Stored facts |
| --- | --- | --- |
| `execution_delivery` | [Delivery](../frontend/dashboard/domain/deliveries/delivery.py) | Upload ownership, input identity and current workflow projections |
| `execution_job` | [Job](../frontend/dashboard/domain/jobs/job.py) | A QC execution, queue state, definition provenance and verified result snapshot |
| `storage_delivery_source` | [S3Info](../frontend/dashboard/domain/storage/s3_info.py) | Remote input coordinates and credentials used to obtain a delivery |

These models are discovered by `dashboard.models`. File bytes live in configured
storage, not in PostgreSQL. Remote-source credentials are operational secrets;
they do not constitute a retained copy of the input.

### Publication

| Table | Model | Stored facts |
| --- | --- | --- |
| `publication_submission` | [DeliverySubmission](../frontend/dashboard/domain/submissions/delivery_submission.py) | Authorizing job, expected and verified AOIs, actor snapshots and final storage receipt |
| `publication_conflict` | [SubmissionConflict](../frontend/dashboard/domain/submissions/submission_conflict.py) | Current review state for competing candidates |
| `publication_conflict_event` | [SubmissionConflictEvent](../frontend/dashboard/domain/submissions/submission_conflict_event.py) | Retained history of conflict opening and resolution |

Publication is separate from execution. A successful QC job is not yet a final
submission. The publication service must preserve its verified input and outputs
before recording a published receipt. Review decisions can select a different
candidate without replacing or deleting any candidate's archived files.

## Retaining verified deliverables

The [submission service](../frontend/dashboard/services/submissions/lifecycle.py)
uses this sequence:

1. Reserve the exact latest successful job and its input digest, release and AOI.
2. Copy the uploaded ZIP and QC artifacts into private staging under
   `SUBMISSION_DIR`. Verify the ZIP against the reserved QC checksum.
3. Write a manifest containing file paths, sizes and SHA-256 checksums. Flush
   files and synchronize directory entries before exposing the complete tree
   through a same-filesystem rename. Synchronize the containing directory too.
4. Record the final path, checksums and publication time in the database. A
   storage failure cannot mark the delivery submitted. A retry after rename
   verifies the existing manifest and inventory before completing the receipt.
5. On a retry of an already finalized submission, verify the files against the
   manifest and the recorded database digest. Missing or changed files produce
   an integrity error; the service does not replace them from mutable inputs.

Final submission records cannot be deleted through ordinary model/queryset
operations. Their receipt and identity fields cannot be rewritten through those
operations, including bulk updates and conflict-updating inserts. Conflict events
are append-only. Foreign keys protect the authorizing job, delivery and catalog
references. A detached account reference does not erase the stored actor name or
credential snapshot. Review-state changes remain supported.

S3 registration and QC execution are supported, but the publication workflow does
not archive remote source objects. It therefore rejects S3 final submission with
`s3_input_not_archived`. To publish a retained deliverable, upload the ZIP, run QC
on that upload and submit it. A source-object checksum alone is insufficient for
final publication; adding S3 publication requires verified input archiving first.

`SUBMISSION_DIR` must be persistent storage outside worker scratch and upload
cleanup. Back up the database and publication storage as a consistent set, and
rehearse restoration with manifest verification. Model guards and checksums do
not prevent privileged SQL/filesystem changes or replace backups. The deployment
operator owns storage redundancy, access permissions and the retention policy;
see [operations](../../../docs/deployment/operations.md).

## Maintaining this structure

Define each table once in its owning model, and update this inventory when its
responsibility changes. Raw SQL must obtain and quote table identifiers from
model metadata, as the [delivery query](../frontend/dashboard/services/deliveries/listing/query/sql.py)
does. Do not duplicate a table-name registry in another configuration file.

Follow the phase-specific [database workflow](MIGRATIONS.md#choose-the-workflow).
Use fresh disposable databases for draft schema changes. Once migration history
is frozen, preserve table and model identities through reviewed migrations and
explicit application compatibility checks.
