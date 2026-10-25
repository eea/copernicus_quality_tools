---
title: Storage libraries
parent: Architecture
nav_order: 12
---

# Storage libraries and original files

Admin Storage provides read-only libraries over existing domain records and
immutable files. It does not introduce a version store, alter a specification,
move directories, infer an approval or change the models-only database policy.

## Sources of truth

| Library | Recorded identity and state | Original file access |
| --- | --- | --- |
| Submitted deliveries | `DeliverySubmission` publication and review states; `Delivery.date_submitted` for historical submissions without a receipt | Exact recorded publication `artifact_key`; historical current uploads are explicitly unverified |
| Specifications | Runtime activation markers; existing `QcDefinition` digests and `ProductReleaseDefinition` references | Exact immutable uploaded version or separately identified original deployment file |
| Boundaries | Existing managed generation identities and current pointer; original unmanaged directories when supported | Exact retained generation or the explicit original raster/vector selection |

Publication is independent of approval. Approved filtering requires both a
published receipt and an accepted review. Earlier-plan approvals remain history,
and an old submission timestamp alone provides no approval evidence. The shared
`submission_status` helper owns the existing decision labels and guidance.

A catalog revision and a runtime activation pointer can differ after an
interrupted operation. Present their states separately. A same-named deployment
specification is not proof that it matches a catalog digest. Catalog-only
revisions remain listed with unavailable original bytes; never reconstruct a
download by serializing the stored JSON document.

## One specification collection

Specification source mounts are file locations, not separate kinds of product.
The **Product specifications** task combines their recorded versions into one
collection. **Browse files** instead lists physical roots, using actual folder
names and server paths. Normal locations show persistent data, while the optional
**Installation files** group contains configured `PRODUCT_DIRS` sources. Each
physical root opens its own filesystem hierarchy;
there are no redirects from a physical source folder into a version library.
Existing area keys remain confined locators for file and download links.

The inventory distinguishes saved content versions from installation sources.
Saved identities use the exact product identifier and SHA-256 digest. Multiple
routes to the same observed physical file can be merged while retaining their
locations. Different copies are never merged from their names, sizes or catalog
source paths alone. Inventory discovery does not read original payloads to infer
digests or create another fingerprint index.

Normal library pages show recorded versions and the selected installed fallback.
`include_sources=1` adds other installation files within the same collection;
`library_sources=1` preserves that choice through file inspection and return
navigation. Source counts are separate from saved-version counts. Archived and
missing selection records remain discoverable when extra sources are hidden.
Runtime selection, upload publication and immutable job snapshots continue to
use their existing authorities and precedence, including fail-closed archive
and corrupt-marker behavior.

## Ownership and reuse

- `storage_admin/navigation.py` defines the task navigation and stable URLs.
- `storage_admin/deliveries.py` projects submission records into paginated rows.
- `storage_admin/versions.py` adapts existing reference stores and enriches them
  with scalar catalog metadata.
- `views/admin_storage_shared.py` owns common authorization, page context and
  rendering. Library and folder views share its Admin shell.
- Library templates share filters, pagination and status patterns. Version IDs
  are available on demand rather than requiring traversal of internal folders.
- Existing `files.py` and `downloads.py` remain the only filesystem browsing and
  download policy. Library availability is an observation, not hash verification.

The default `/admin/storage/` opens submitted deliveries. When a guarded
persistent root is configured, it opens that physical tree instead. Explicit
library tabs remain available in both modes. `?tab=files` opens the
folder browser; existing `?area=...&path=...` bookmarks still work. The allowlisted
`library` query parameter and bounded library filter/page values carry a return
destination through folder and file pages, search, sort and checksum navigation.
Known library roots have readable titles and breadcrumbs, with Up returning to
the same library. Raw browsing preserves actual filenames and paths. Return
context cannot redirect outside Admin.

The physical browser carries `browser=files` through file inspection and
downloads. Bounded `browse_query`, `browse_sort`, `browse_direction` and
`browse_page` fields restore the previous folder view from file information.
Entering another folder clears the folder-local search and page while retaining
ordering. Its address form accepts only a path relative to a configured root;
the displayed absolute path is server/container metadata, not arbitrary host
filesystem access. `storage_locations()` projects physical roots separately from
the legacy area metadata, and excludes the filtered `jobs` alias of the work
directory. Libraries continue to carry their own explicit `library` context.

The location inventory removes redundant drive entries, not files. An available
read-only child root can be represented by an available read-only parent only
within the same storage/installation group and when the parent's path policy
permits its exact relative path. Equal roots keep the first compatible location.
Missing or unsafe roots stay discoverable; Trash-capable scopes retain their own
locations. Comparison uses lexical configured paths and existing no-follow
validation, never `resolve()` or filename/content deduplication. All area keys
remain usable for library downloads and old bookmarks. Saved originals therefore
remain under the work tree, while application-provided fallback sources retain
their deployment lifecycle and original runtime precedence.

Retained-original hidden folders are recognized by their exact configured
physical paths, so `.versions` and `.boundary-generations` can also be reached
through an ancestor work or additional mount. Same-named hidden folders elsewhere
are not enabled. Every alias uses the same descriptor confinement and private
control-path policy; browsing never changes activation or original bytes.

## Bounded work and failure behavior

Delivery pagination unions only identifiers and dates in SQL, then hydrates the
visible page. Only those rows have their exact recorded file locations checked;
there is no recursive scan, payload hashing or per-row database lookup.

Version discovery bounds directory entries and small activation-marker reads.
Catalog enrichment uses bounded scalar queries without selecting specification
JSON documents. It reconciles exact product/digest pairs before pagination so
missing originals retain their history. Inventory limits and unavailable sources
produce visible warnings, never silent deletion or automatic fallback activation.

All links resolve through confined file readers, with private path exclusions
and no-follow descriptor traversal. File availability does not certify complete
publication evidence. Folder ZIPs still stream from their explicit selection.
The original-files namespace and archive report explain exclusions separately
from approval and version state.

Validate changes on disposable SQLite and PostgreSQL databases, including ready
maintenance reads. Query shape matters: PostgreSQL can parenthesize UNION
branches, so read-only pagination must remain recognizably SELECT-based without
loosening the maintenance write guard. Preserve the existing model initialization
and recovery policies; never use an occupied database to rehearse schema changes.
