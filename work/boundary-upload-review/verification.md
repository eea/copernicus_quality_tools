# Boundary package upload correction — 23 October 2026

## Reproduced blockers

The supplied `boundary_package_20260617.zip` is valid and unchanged:

- Archive: 2,573,177,623 bytes (about 2.4 GiB).
- 8,489 ZIP entries, including 8,485 regular files and four directories.
- Expanded bytes: 23,878,305,384 (about 22.2 GiB).
- Largest file: 3,515,866,983 bytes (about 3.3 GiB).
- Compression ratio: 9.29 overall, 81.91 maximum per member, below the existing
  100-times bound.
- All 8,485 regular files passed a full streamed CRC check.

The old policy independently rejected compressed size, largest expanded member
and total expansion (512 MiB / 512 MiB / 2 GiB). The browser replaced every error
with a generic activation banner. Docker also had only about 1.1 GiB free, which
could prevent Django from receiving the multipart upload before the view ran.

## Changes

- One authoritative default policy now permits a 4 GiB ZIP, 4 GiB per expanded
  file and 32 GiB total. Member count, path, entry-type, encryption and compression
  protections remain. All limits support validated deployment configuration.
- The HTTP view passes configured limits explicitly. Catalog reads use the same
  configured member bound. Upload pages display limits and read-only capacity;
  the picker rejects impossible uploads before transmission.
- The service rejects known excessive file sizes before staging, retains streamed
  bounds, and checks compressed-copy/extraction capacity with headroom. First
  activation includes required legacy snapshot copies in the space estimate.
- The existing Django CSRF enforcement is retained through a subclass that
  translates boundary multipart I/O failures before the view. Receiving or
  pre-activation disk exhaustion returns safe, actionable HTTP 507 JSON.
- Known rejections show the actual safe backend reason prominently. Proxy,
  authentication, timeout and connection failures have specific guidance. Unknown
  completion never triggers automatic retries or a claim that activation failed.
- Errors after pointer selection, including fsync or cleanup space failures,
  remain neutral HTTP 500 confirmation failures; they do not claim the previous
  generation is still selected. Earlier failures retain the existing package.
- Shared raw-XHR decoding handles native JSON without accessing its unavailable
  `responseText`. Authentication and maintenance handling use that safe decoder.
- Production startup retains one Gunicorn process and one background refresh
  owner, with four explicit `gthread` request threads so browsing continues during
  long uploads. The existing 120-second worker heartbeat setting is retained;
  ingress/browser deadlines are separate.

## Local environment

The user approved increasing Docker's disk limit to 100 GiB. Docker Desktop's
slider exposes 8 GiB increments, so 96 GiB was selected as the nearest value below
that approval. Existing containers/data were retained. The four previously
running services were resumed; the original stopped frontend/worker remained
stopped. After validation cleanup, boundary storage had about 35 GiB free.

The actual source ZIP was mounted read-only into a disposable, network-isolated
container. Its complete extraction, publication and activation succeeded in
80.524 seconds using the new default policy. The result had all 8,485 files and
23,878,305,384 expanded bytes. The active pointer resolved to the published
generation. Archive SHA-256:

`bbbe512ee7708ccb5c48a4ad7c7c14a3ce3d249ca28024c05e822c7fd36db863`

That container and its extracted test files were removed. The live boundary
package was not activated or replaced. No specification, database schema or
existing database records were changed by the correction.

## Verification

- Broad PostgreSQL 14 regression run: **799 passed**, zero failures/errors/skips,
  162.770 seconds.
- Final PostgreSQL follow-up after the last hardening changes: **145 passed**,
  zero failures/errors/skips, 3.208 seconds. This overlaps the broad suite.
- Final dashboard Node event tests: **159 passed**, zero failures/skips, including
  21 boundary tests and native-XHR authentication recovery.
- Entrypoint tests: **four passed** in the frontend runtime, including a real
  Gunicorn slow-request/concurrent-health probe. The slow request remained active
  while health returned within one second.
- Django system checks, shell syntax and `git diff --check` passed.
- PostgreSQL used fresh tmpfs-only disposable containers/databases, isolated
  control/file paths and synthetic credentials. Validation containers were removed.
- The local frontend collected updated static files and restarted successfully.

The live upload page was inspected in Chrome. Automated file selection was
blocked by the extension's file-URL access setting; no browser upload or live
activation was submitted. Manual selection remains available.

- [Corrected live upload page](upload-page.png)
- [Applied Docker disk setting](docker-capacity.png)
