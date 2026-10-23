# Admin navigation and retained-storage verification

Verified 23 October 2026 against the current working tree.

## Implemented structure

| Section | Entry point | Scope |
| --- | --- | --- |
| Overview | `/admin/` | Permission-aware entry cards and maintenance status |
| User management | `/admin/users/` | Existing user/group/access editors and user-profile import/export |
| Database | `/admin/database/` | Connected-record transfers, native backups/recovery, maintenance, read-only schema checks and supported table inspection |
| Storage | `/admin/storage/` | Configured local uploads, recognized job files and immutable publications; listings independent of Delivery/Job rows |

All task links stay within Admin. The existing header arrow is the explicit
way back to the QC workspace. Model editors, account-table views and loaded
user transfer operations retain the owning navigation section.

## Data and file safeguards

- Historical record details link to exact local paths and stable job UUIDs.
  Incoming ZIP and explicit job-input verification require recorded SHA-256 and
  size. Output, temporary and nested ZIPs never gain an input-verification label,
  even when their bytes happen to match an input.
- Browsing and downloads work without delivery/job records. They neither import
  data nor infer ownership from a similar filename. Missing files and missing
  historical evidence remain visible as unavailable/unverified.
- File opens are descriptor-relative and reject traversal, symbolic links,
  hard-linked files, special files, protected configuration overlaps and hidden
  application control storage. Checksum evidence is bound to the reviewed inode
  before and after reading, including the final pathname check.
- File removal is an individual, reviewed move into same-filesystem private
  trash. Linked files, original specifications and published evidence are
  protected. Eligible orphan job reports use the known report filename patterns.
- File changes require current-database administrator authority, CSRF, the
  reviewed maintenance generation, ready maintenance, the transfer execution
  lease and the shared exclusive application-activity barrier. They write no
  application SQL rows.
- Durable filesystem intents retain interrupted operations. Restore never
  overwrites an existing destination. A ZIP linked by records imported after
  quarantine must match their recorded checksum and size before restoration.
  No permanent-purge action exists.
- No model or schema changes were introduced. Draft v3.0.0 policy remains
  models-only: schema inspection is read-only, with no in-place migrations.

## Validation

- Broad isolated PostgreSQL 14 run: **682 tests passed**, zero failures, errors
  or skips, 148.683 seconds.
- Follow-up PostgreSQL 14 run after final storage hardening: **121 tests passed**,
  zero failures, errors or skips, 27.556 seconds. This overlaps the broad run;
  the counts are not a unique-test total.
- Follow-up suites: storage filesystem/trash (26), storage references (22),
  actual Storage HTTP requests (24), existing historical input downloads (21),
  database transfer service (28).
- Covered CSRF and permissions, ready-state/generation checks, active transfers,
  zero SQL writes during maintenance file actions, protected specifications,
  empty delivery/job tables, quarantine followed by matching record import and
  restore, no overwrite, interrupted recovery and directory/file-change races.
- Django system check: zero issues. `git diff --check`: clean.
- PostgreSQL used unique temporary containers, synthetic credentials, no host
  ports or persistent volumes and disposable databases. Both containers were
  removed. Existing database volumes and retained server files were untouched.

## UI review

Rendered 22 real Django pages using temporary synthetic records/files and the
current static assets. All rendered successfully. Reviewed the Overview, User
management, Database, Storage and retained-ZIP confirmation states in Chrome.
The temporary preview server and browser tab were closed afterward.

- [Overview](overview.png)
- [Verified retained ZIP](verified-zip.png)
- [Recoverable trash confirmation](recoverable-trash.png)

These screenshots contain synthetic preview data, not the live installation.

The Storage browser covers configured local storage rather than arbitrary
server paths or S3. Database backups remain separate from server-file backups.
