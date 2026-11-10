---
title: Checks
has_children: true
nav_order: 2
---
# Checks

This section covers various checks:

- [Vector Checks](checks/vector-checks.md)
- (add more later)

## AOI result metadata

The worker publishes a normalized AOI code in the job result once all required
spatial media have completed AOI validation or been marked not applicable. The
frontend persists this value on the job and its delivery.

AOIs explicitly excluded by every boundary check's `skip_aoi_codes` are trusted
from the naming rules and can be published without spatial validation. For
example, CLC+ 2025 publishes `gf` and `mq` even though their boundary checks are
skipped. A merely empty medium or an incomplete boundary exemption does not,
on its own, make an AOI eligible for publication.
