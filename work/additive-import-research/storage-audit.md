# Retained delivery ZIPs and additive record import: storage audit

Research date: 21 October 2026. This records the repository findings before the
additive-import implementation and distinguishes that snapshot from its proposed
design. Subsequent implementation is documented in the main architecture guide.
This appendix itself makes no schema, database or retained-file changes. Source
links identify the inspected implementation; line numbers can move as development
continues.

## Finding and claim boundary

An imported QC job must identify the exact ZIP that the historical run checked.
The presence of a same-named ZIP on a shared volume is insufficient evidence.
SQL foreign keys prove record associations; they do not prove that filesystem
bytes still correspond to those records.

The current download path has no checksum comparison. An imported or otherwise
desynchronized active delivery can therefore return HTTP 200 with different ZIP
bytes at the expected path. This is a risk identified by code inspection, not a
claim that this happened in the serving installation.

Normal upload replacement already has a useful protection: it marks the old
delivery deleted before publishing replacement bytes, and the old job page hides
the ZIP link. Do not describe the normal replacement flow as automatically
serving new bytes for an old job. The identified gap concerns imported or
desynchronized records, direct endpoint use with an inconsistent active record,
and the absence of a verified historical download contract.

## Current persisted and filesystem identities

| Resource | Current identity | Storage consequence |
| --- | --- | --- |
| Delivery | Integer primary key; user FK; filename; byte size; optional content SHA-256; deleted flag | Canonical ZIP location is derived from the current related user's username and the delivery filename. There is no immutable per-delivery upload key. |
| Job | UUID primary key; delivery FK; optional input SHA-256; product/release/definition associations | Reports and results use `WORK_DIR/job_<compact job UUID>/`. The worker reads the local delivery at its original incoming path. |
| Published submission | Submission UUID; one-to-one delivery and job; release and unit FKs; artifact key, manifest digest and input digest | The immutable publication includes a separate input ZIP copy and a checksummed manifest. |
| Transfer artifact | Named configured storage root plus canonical relative key, size and SHA-256 | Existing files can be reused only when their bytes match the package inventory. |

Evidence:

- [Delivery fields](../../src/qc_tool/frontend/dashboard/domain/deliveries/delivery.py#L11),
  including [optional digest and deletion state](../../src/qc_tool/frontend/dashboard/domain/deliveries/delivery.py#L52).
- [Job relationships](../../src/qc_tool/frontend/dashboard/domain/jobs/job.py#L14)
  and [optional input checksum](../../src/qc_tool/frontend/dashboard/domain/jobs/job.py#L99).
- [Submission identity and retained provenance](../../src/qc_tool/frontend/dashboard/domain/submissions/delivery_submission.py#L19).
- [Job directory derivation](../../src/qc_tool/common.py#L468).
- [MEDIA_ROOT uses incoming storage](../../src/qc_tool/frontend/settings.py#L313).
- [Archive root/key contract](../../src/qc_tool/database/transfers/archive.py#L60).

The local Compose frontend and worker use the same incoming and work paths:
[frontend environment](../../docker/compose.local.yaml#L52) and
[worker environment](../../docker/compose.local.yaml#L136). A fresh SQL database
does not establish that these mounted directories are empty, synchronized or
owned by the newly imported records. Shared volumes are an independent resource
that the import plan must inspect.

## Current job-to-ZIP download behavior

The [job result template](../../src/qc_tool/frontend/dashboard/templates/dashboard/jobs/result.html#L123)
shows the historical job identifier and input SHA-256, but its ZIP link is
`download_delivery_file(delivery.id)`. It suppresses the link when
`delivery.is_deleted` is true.

The [delivery endpoint](../../src/qc_tool/frontend/dashboard/views/deliveries/files.py#L16):

1. Loads a delivery by its local integer primary key.
2. Applies delivery-level view authorization.
3. Rejects deleted deliveries.
4. Resolves `MEDIA_ROOT/<delivery.user.username>/<delivery.filename>`.
5. Opens the regular file and returns it.

It does not compare the opened bytes to `delivery.content_sha256`,
`delivery.size_bytes` or the historical job's `input_sha256`. A checksum shown on
the page is not currently a checksum guarantee on that response.

The [upload path resolver](../../src/qc_tool/frontend/dashboard/services/uploads/paths.py#L20)
already rejects another user's path, subdirectories, unsafe owner names,
symlinked owner directories/files and nonregular/non-ZIP files. Reuse this path
policy. The [artifact opener](../../src/qc_tool/frontend/dashboard/services/artifacts/files.py#L41)
returns an open descriptor and refuses symlinks and special files. Hash and then
return that same descriptor rather than validating one path and reopening it.

Historical downloads should use the existing
[job authorization](../../src/qc_tool/frontend/dashboard/access/jobs.py#L6),
which checks the selected job's recorded product/release scope. It deliberately
does not grant access to an older run solely because the delivery was rerun
under a different product.

### Existing replacement protection

The [replacement workflow](../../src/qc_tool/frontend/dashboard/services/uploads/overwrite.py#L170)
retains old bytes as a private `.previous` recovery hard link, creates a hidden
successor delivery and marks the original deleted in a durable transaction. It
then publishes replacement bytes. The old result page consequently shows
`(deleted)` rather than a download link, and the delivery endpoint rejects that
old record.

The private overwrite journal and `.previous` file are recovery state. They are
not a public historical ZIP resolver, not a portable artifact contract and not
an appropriate namespace for an arbitrary import UI to browse.

### What job history itself retains

The [worker](../../src/qc_tool/worker/dispatch.py#L123) copies the original
product specification into the job directory, hashes the original local ZIP and
passes its path into checks. It does not copy every local input ZIP into an
immutable per-job input archive. [Terminal metadata projection](../../src/qc_tool/frontend/dashboard/services/product_units/jobs/metadata.py#L9)
copies the worker result hash into `Job.input_sha256` when available.

The delivery digest can be populated from publication evidence in
[submission finalization](../../src/qc_tool/frontend/dashboard/services/submissions/state/finalization.py#L79).
Its existence must not be assumed for every old delivery or failed job. An
absent historical job checksum cannot be reconstructed as an historical fact
simply by hashing whatever now exists at the same filename.

## Current published-input contract and its limits

[Publication](../../src/qc_tool/frontend/dashboard/services/submissions/publication/delivery_input.py#L17)
copies the original local ZIP into `input.d/<filename>`, computes size and digest,
and compares the digest with the expected QC input. It records this file in the
publication inventory. S3 inputs are explicitly not archived by this workflow;
publication currently refuses them rather than inventing a retained copy.

The [manifest builder](../../src/qc_tool/frontend/dashboard/services/submissions/publication/manifest.py#L25)
binds:

- Submission UUID and job UUID.
- Delivery integer ID, product-release integer ID and product-unit integer ID.
- Expected and verified product-unit codes.
- Historical input SHA-256, request timestamp and local/remote storage kind.
- Every retained file's relative path, byte size and SHA-256.

The [submission reader](../../src/qc_tool/frontend/dashboard/services/submissions/artifacts.py#L14)
verifies the manifest body's SHA-256 against both the document's stated digest
and `submission.artifact_digest`, and checks its submission UUID against the
local submission. [File opening](../../src/qc_tool/frontend/dashboard/services/submissions/artifacts.py#L40)
then verifies the selected member's digest and size before returning the open
descriptor. These are strong reusable primitives.

That reader does **not** by itself compare every manifest relation to the current
job/release/unit graph. The current [transfer receipt verifier](../../src/qc_tool/database/transfers/artifacts.py#L247)
does compare that broader context. A new job-bound input resolver must verify the
manifest's job identity, input digest and relevant local/source identity mapping;
checking only manifest SHA-256 plus submission UUID is insufficient after
additive integer-ID remapping.

Original product specifications and uploaded snapshots must remain byte-for-byte
unchanged. Published manifests and retained publication bytes should likewise
remain immutable. An importer must not rewrite IDs inside a manifest and
recompute its checksum to make it appear native to the destination.

## Current transfer behavior that can be reused

### Source inventory

[Delivery collection](../../src/qc_tool/database/transfers/artifacts.py#L126)
uses the source account username and filename. It requires a regular file,
checks size and the delivery checksum when recorded, and rejects mismatches.
Remote delivery objects and credentials are external requirements. Missing
retired uploads can become warnings; a missing active local upload fails the
portable artifact contract.

[Job collection](../../src/qc_tool/database/transfers/artifacts.py#L149)
preserves job-root report/result/specification files and `output.d` artifacts.
Missing job directories are warnings so SQL history can remain available. Worker
input and scratch directories are deliberately excluded, as are top-level
`.log`, `.stdout` and `.pre` files. Copying all worker state would expose secrets,
temporary database exports or materialized remote data.

[Published collection](../../src/qc_tool/database/transfers/artifacts.py#L170)
requires its original manifest and complete immutable inventory.
[Package validation](../../src/qc_tool/database/transfers/artifacts.py#L314)
binds allowed filesystem destinations to the imported business graph, original
specification digests and published-input inventories. Uploaded archive paths
are not arbitrary destinations.

### Destination inventory and safe publication

[Restore preflight](../../src/qc_tool/database/transfers/artifacts.py#L804)
classifies a package member as create or reuse. Existing bytes must pass
[exact digest and size matching](../../src/qc_tool/database/transfers/artifacts.py#L769).
A mismatch raises a conflict; nothing may be overwritten.

[File publication](../../src/qc_tool/database/transfers/artifacts.py#L616)
stages complete bytes on the destination filesystem, fsyncs them, journals inode
ownership before publication, revalidates parent directories and uses exclusive
hard-link creation. The filesystem is durable before SQL commit.
[Rollback](../../src/qc_tool/database/transfers/artifacts.py#L716) removes only
unchanged objects whose inode ownership was recorded by this operation. Reused
files are never its rollback property.

This mechanism depends on staging and final files being on the same device.
[Nested-mount detection](../../src/qc_tool/database/transfers/artifacts.py#L635)
currently fails safely. An import UI should identify the affected configured
root and explain the storage prerequisite rather than provide a destructive
fallback or silently use a nonatomic cross-device move.

### Current intentional record limitations

[Account planning](../../src/qc_tool/database/transfers/records.py#L394)
requires explicit mapping when a username exists, and application restoration
requires preserving usernames because paths depend on them. Application import
requires all business tables to be empty. [Record insertion](../../src/qc_tool/database/transfers/records.py#L449)
preserves source business IDs and remaps user FKs only.

Those checks are an intentional boundary, not a UI-only inconvenience. Removing
the empty-table check without remapping all dependencies, verifying reuse and
preserving immutable artifact context would make the current code unsafe.

## Shared-storage and retained-file failure cases

| Scenario | Current consequence | Required additive behavior |
| --- | --- | --- |
| Fresh SQL database with matching `incoming/alice/file.zip` already on volume | Artifact planner can reuse exact bytes. | Verify SHA-256 and size; bind imported job to the verified input; leave existing file untouched. |
| Same path and size, different bytes | Artifact planner rejects a package conflict; delivery download itself would not detect a desynchronized record. | Show a file conflict before applying records; never attach those bytes to historical QC. |
| Source `alice` mapped to target `bob` | Current application planner blocks it. | Require explicit owner/storage mapping evidence or keep the restriction; do not silently rename/move retained files. |
| Job UUID already has a retained directory and matching package files plus `job.log` | Current strict retained-tree preflight rejects the unlisted log. | Preserve runtime extras without weakening immutable publication inventories. |
| Job directory contains `tmp.d` or excluded worker input | Current strict preflight rejects these directories although export omitted them. | Treat reviewed runtime namespaces separately; never sweep them into exports or delete them. |
| Published submission directory has an additional unlisted file | Current strict preflight rejects it. | Retain strict rejection: its complete immutable inventory is an integrity boundary. |
| Different deployments share one incoming/work volume | Same username/filename or job UUID can refer to another deployment's bytes. | Bind provenance and expected digests; do not assume matching path implies matching deployment. |
| Correct ZIP exists only in a published receipt | Current delivery link cannot locate it if canonical upload is missing/deleted. | Authorized job resolver can use the manifest-bound verified input for that exact job. |
| Correct ZIP exists only at an unknown arbitrary server path | Current maintained import does not scan arbitrary storage. | Restrict any linking UI to configured, authorized roots; show safe candidates and require cryptographic proof. |
| S3 delivery has no retained local input | Remote requirement is reported; native local download cannot supply the object. | Show remote/unavailable state, never synthesize a local ZIP or import credentials implicitly. |
| Frontend sees ZIP mount but worker does not, or permissions differ | Import can appear successful while rerun fails. | Distinguish historical download readiness from worker/storage readiness; verify deployment mounts separately. |
| File changes after review while maintenance is on | Application writers are excluded; external filesystem writers may still exist. | Rehash/revalidate at apply, verification and download as appropriate; stale plan must fail safely. |
| SQL transaction fails after new files are published | Existing inode journal can remove operation-created files. | Preserve reused files and unrelated directories; keep uncertain operations in maintenance until receipt reconciliation. |
| Destination path is a nested mount with another device | Current exclusive publication cannot link its staged file. | Clear storage blocker; no overwrite/delete/cross-device fallback. |

### Strict job-tree inventory mismatch

The current [_preflight_retained_trees](../../src/qc_tool/database/transfers/artifacts.py#L776)
includes both immutable submissions and ordinary job working directories. It
requires every existing directory and file to occur in the package inventory.
This conflicts with the deliberate omissions in the source job collector.

Proposed correction: separate the two policies. Submission trees must remain an
exact immutable inventory. Job trees should verify all imported included members,
reject conflicting included bytes and unsafe objects, and retain explicitly
reviewed runtime extras. Unknown extras require a visible review/blocker policy;
they must never be deleted automatically. Do not interpret existing logs as
reusable publication evidence.

## Proposed long-term artifact provenance requirements

This section describes future architecture, not current implemented behavior.

An additive importer needs a durable, exportable association between source
identity and destination identity. At minimum it must retain:

| Evidence | Purpose |
| --- | --- |
| Source deployment/package identity and package digest | Distinguish an idempotent repeated import from unrelated identical-looking local IDs. |
| Resource kind, source key and target key | Remap integer FKs without claiming that a source integer is globally unique. |
| Stable job and submission UUIDs | Preserve report paths and immutable publication identities; conflicting UUIDs must block or be skipped as a connected graph. |
| Original manifest identity context | Verify delivery/release/unit IDs in original manifest bytes through an explicit source-to-local mapping. |
| Artifact root/key, size and SHA-256 | Locate and verify existing or newly copied bytes without arbitrary absolute paths. |
| Binding basis and verification time | Distinguish a historical QC checksum, original publication proof, package checksum and merely discovered current file. |
| Import receipt and actor | Audit which reviewed operation created each association and reconcile interruptions. |

A package checksum proves which file was in the package. It does not alone prove
that an old hashless QC job checked those bytes. Retain this distinction in the
model and UI. Do not silently backfill `Job.input_sha256` with the hash of an
arbitrary discovered ZIP and present it as historical QC evidence.

Any future provenance model change in draft v3.0.0 must follow the current
models-only policy and be tested on fresh disposable databases. This appendix
does not propose changing or repairing a populated developer/production schema,
adding first-party migrations, or importing legacy data converters.

## Proposed job-bound resolver

Add a named endpoint accepting a job UUID and reuse `require_job_view` before
opening any artifact. Its result must be the checked ZIP or an explicit
unavailable result, never a best-effort same-name file.

Resolution order:

1. Establish a valid expected input digest from the persisted historical job or
   trusted, validated original publication evidence. Report disagreements as
   conflicts. A blank historical digest alone does not establish proof.
2. If a published submission belongs to this exact job, verify its original
   manifest digest, submission UUID, job UUID, input SHA-256 and source/local
   graph context. Select its single inventoried input ZIP and reuse the existing
   checksummed submission-file opener.
3. Otherwise resolve the configured canonical owner upload or a separately
   reviewed immutable artifact binding. Open without following links; stream
   size and SHA-256; compare with the established historical evidence.
4. Rewind and return the same descriptor. Fail closed on mismatch, missing proof,
   wrong owner, unsafe storage or ambiguous candidates.

The job result UI should link **Download checked ZIP** to this endpoint. The
ordinary delivery endpoint can remain a current-upload action with a distinct
label, or share the low-level verified-file helper once its contract is explicit.
Do not apply a current delivery's changed product scope in place of historical
job authorization.

## Proposed Admin UX states and decisions

The import review should group records with the artifacts they require. Avoid
asking an administrator to interpret foreign-key IDs or fix server paths in code.

| State | UI explanation | Safe action |
| --- | --- | --- |
| Verified on server | Original ZIP is already available and matches size/SHA-256. | Reuse automatically; show owner, filename, size and digest. |
| Included in package | Verified package contains the required original. | Create the missing destination exclusively; never replace existing bytes. |
| Existing record matches | Same stable identity and equivalent mapped relationships/content. | Reuse without modifying that record. |
| Different file | Destination filename is occupied by different bytes. | Keep existing data; skip the dependent graph or choose a reviewed separate binding. |
| Missing original | Neither package nor approved storage provides verified bytes. | Upload/link the original, or explicitly import history without claiming downloadable input where that profile supports it. |
| Historical input unverified | Record has no trustworthy historical hash/binding. | Preserve the audit gap; show why download cannot be guaranteed. |
| Remote input | Input is not retained locally and depends on external access. | Show separate remote-storage requirement. |
| Mapping required | Source account or business identity collides locally. | Compare source/local summaries; choose reuse, distinct supported identity or skip connected graph. |
| Unsafe/unavailable storage | Permissions, mount, symlink or root policy prevents safe access. | Explain affected configured root and block applying affected graph. |

Before confirmation show counts for created/reused/skipped records and files,
unresolved conflicts and historical jobs lacking verified input. Conflict choices
must propagate to dependent records; skipping a delivery must not leave imported
jobs pointing at an unrelated local integer ID. Revalidate the plan and file
evidence at execution time. After import, provide links to actual imported jobs
and their verified ZIP availability.

## Acceptance cases

These are proposed tests, not tests executed by this read-only audit.

1. Import into fresh disposable SQL with pre-existing matching incoming/work
   files. Verify the historical job page downloads exactly the original ZIP;
   reused file bytes and inode are unchanged.
2. Import into occupied SQL with unrelated users, deliveries and jobs whose
   integer IDs collide. Existing rows and artifacts remain unchanged; imported
   relations point to their allocated/reused local targets.
3. Reimport the same package and repeat after an interrupted/lost acknowledgment.
   No duplicate graph, detached FK or duplicate artifact binding appears.
4. Provide a same-name, same-size but different-hash ZIP. Preview reports conflict,
   execution cannot bind it, and historical download cannot return HTTP 200 with
   those wrong bytes.
5. Import a job whose canonical ZIP disappeared but exact input remains in its
   published receipt. Verify authorized download through the job endpoint, exact
   bytes and the original manifest identity context.
6. Substitute a valid manifest from another job while keeping internally valid
   checksums. New resolver rejects job/submission/context mismatch.
7. Remap a published graph's integer IDs. Verify original manifest bytes and
   digest remain unchanged and explicit provenance reconciles every embedded ID.
8. Attempt conflicting job/submission UUID reuse. Block rather than generate a
   new UUID or overwrite retained directories.
9. Map an account to another username. Require explicit supported storage
   resolution or a blocker; do not rename/move either owner's retained ZIPs.
10. Exercise normal upload replacement. Old delivery remains deleted, its current
    upload endpoint stays unavailable and old page does not show the old current
    file link. A manifest-backed historical input may remain separately available
    under its verified historical contract.
11. Import a hashless old job. Preserve its missing-evidence status; do not infer
    a historical SHA from filename, byte size, another job or current upload.
12. Preserve existing job logs, stdout, scratch/input directories and unrelated
    work trees during matching artifact reuse. Unexpected files in immutable
    submission trees still fail strict verification.
13. Replace an artifact or parent with a symlink; test traversal, special files,
    wrong owner, Unicode path ambiguity, nested mount and permission denial. Fail
    without opening outside configured authorized storage or modifying records.
14. Change bytes after preview, including same-size replacement. Execution and
    downloads detect stale/conflicting evidence. Hash then serve the same open
    descriptor.
15. Verify owner/product-grant, unrelated owner, scoped product-manager and admin
    authorization using the selected historical job. Denied access precedes
    filesystem access and does not disclose private storage paths.
16. Fail SQL before the atomic receipt after file publication. Reused bytes remain;
    only unchanged operation-owned new files may be removed. Retry reconciles
    records and artifacts without silent changes.
17. Verify remote/S3-only and missing-storage cases remain explicit unavailable
    states. No credentials, private overwrite recovery files or worker scratch
    secrets enter the package or become publicly downloadable.

## Audit limitations

This appendix is based on repository reads. It does not certify the contents,
permissions or mount consistency of production storage; it does not claim that
any live job currently downloads incorrect bytes. It proposes acceptance tests
but does not run them or deliver an additive-import implementation. The existing
fresh-target transfer integration test is useful evidence of intended
[publication and original-byte preservation](../../src/qc_tool/database/tests/integration/test_transfer_application.py#L1),
not evidence that occupied-target merging or arbitrary retained-storage reuse
already works.
