# Database and storage transfers — implementation verification

23 October 2026. Implemented in the existing central transfer service and Admin
forms. No model/table/schema, first-party migration, baseline, QC specification,
vector check or raster check was changed by this work. Existing unrelated working
tree edits were retained.

## Supported behavior

- Portable connected-record import/export explicitly selects records only or
  records with available files. User-only transfer remains separate and bounded.
- New format 3 includes a reviewed semantic schema descriptor and contract
  version. Formats 1/2 keep strict legacy readers. Release labels alone neither
  grant nor deny compatibility.
- Schema comparison identifies table/model/field/type/nullability/relation,
  declaration and validation-policy differences. Database Admin checks actual
  model readiness on every authorized landing visit and before record transfers.
- Unsupported portable contracts remain private, inspectable and downloadable;
  their records cannot be applied. No fields are silently defaulted or discarded.
- Expected artifact identities, original origins, role/path associations,
  expected versus observed hashes, availability and payload inclusion persist in
  existing atomic transfer receipts and survive re-export after integer rekeying.
- Missing/unverified files do not erase history. Included members still require
  strict payload, namespace, specification and publication integrity validation.
- Records-only bulk files use safe descriptor metadata checks; only bounded
  publication/specification metadata is read. No new historical input hash is
  invented from a present candidate.
- Native PostgreSQL archives retain every database table/column value, stored
  credential fields, sessions, sequences and large objects, including content
  outside ORM/portable contracts. Optional local files use an ORM-independent,
  bounded retained-business-storage inventory, including unlinked old ZIPs.
- Native restore targets a separate empty database. Files are created exclusively
  or verified/reused, never overwritten. Specification bytes and legacy boundary
  trees restore into inert immutable version/generation namespaces.
- Private durable storage pins prevent Storage Admin quarantine of files needed
  by inactive/unavailable restored databases. Pin uncertainty blocks cleanup;
  no pin is released automatically.
- Database switch preserves the current-model schema gate and explicit Admin
  access review. Missing historical files are shown as availability warnings;
  present bytes participate in the reviewed fingerprint. Dependent operations
  must still verify their required inputs.
- Export review detects known file-size/free-space blockers before a long export
  is queued. Packaging checks the reviewed bytes again before publication.

## Verification evidence

All SQL writes and backup/restoration tests used disposable databases. Test
PostgreSQL 14 containers used tmpfs, no host ports and no application volumes;
their servers and test-created restore databases were removed afterward.

| Check | Result |
| --- | --- |
| Broad PostgreSQL integration, Admin, downloads and storage suites | 592 tests passed; zero skips/failures/errors |
| Final PostgreSQL compatibility, optional-file round trips, original artifacts, native restore, control and pin checks | 135 tests passed; zero skips/failures/errors |
| Final capacity/service/recovery checks plus actual native SQL-and-ZIP restoration and retained pin | 50 tests passed; zero skips/failures/errors |
| SQLite integration, Admin, downloads and storage suites | 594 tests; zero failures/errors; 38 PostgreSQL/backend-specific skips |
| Dashboard JavaScript | 162 tests passed; zero skips/failures |
| Python compilation and whitespace checks | Passed |
| Relative links in changed architecture/user/database documentation | 38 targets checked; all exist |

The counts overlap and are not a unique total. The final focused PostgreSQL run
rechecks the last capacity-preflight change after the broad suites. Expected
injected failures exercise rollback, lost acknowledgement and recovery paths;
they are not unhandled suite failures.

Critical real round trips include records-only into a different disposable
namespace; original expected identities retained after re-export; missing source
ZIP/manifest preservation; exact historical download after a later file copy;
wrong late ZIP refusal; inspectable future-schema drift with original package
download; complete native PostgreSQL restoration with an unlinked ZIP; unchanged
active source SQL; and retained-database cleanup protection.

## Boundaries

There is no automatic conversion for hypothetical future schemas. A changed
record contract needs a reviewed typed reader and preservation fixtures in its
release. v3.0.0 remains draft/models-only; target adoption and first migration
history are a separate reviewed 3.0.1-or-later transition.

General legacy-file search/attachment, indexed artifact tables, selected-job
graph export, remote-object copying, automatic pin retirement, scheduled off-host
backup/PITR and independent storage-pointer switching remain future work.
Configured package/capacity limits apply. Deployment secrets, PostgreSQL globals,
remote objects and excluded temporary/log/private-control files require their
own recovery procedures. This is not an EEA deployment or a Docker Hub release
validation. No live user database was reset or migrated, and no user data was
exported/imported as part of testing.
