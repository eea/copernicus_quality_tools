---
title: Frontend vendor assets
parent: Development
nav_order: 4
---

# Frontend vendor assets

QC Tool serves browser dependencies from its own static-files deployment. This
avoids runtime trust in a third-party CDN, but it also means maintainers must
review and update vendored files deliberately.

## Reviewed compatibility baseline

| Local file | Version | Upstream source | SHA-256 |
| --- | --- | --- | --- |
| `dashboard/js/jquery.min.js` | jQuery 3.7.1 | `https://code.jquery.com/jquery-3.7.1.min.js` | `fc9a93dd241f6b045cbff0481cf4e1901becd0e12fb45166a8f17f95823f0b1a` |
| `dashboard/js/bootstrap.min.js` | Bootstrap 3.4.1 | `https://cdn.jsdelivr.net/npm/bootstrap@3.4.1/dist/js/bootstrap.min.js` | `9ee2fcff6709e4d0d24b09ca0fc56aade12b4961ed9c43fd13b03248bfb57afe` |
| `dashboard/css/bootstrap.min.css` | Bootstrap 3.4.1 | `https://cdn.jsdelivr.net/npm/bootstrap@3.4.1/dist/css/bootstrap.min.css` | `6d92dfc1700fd38cd130ad818e23bc8aef697f815b2ea5face2b5dfad22f2e11` |

The Bootstrap hashes also reproduce the SHA-384 integrity values published in
the official Bootstrap 3.4 documentation. Never replace these files from an
unversioned URL.

## Update procedure

1. Read the upstream release and security notes.
2. Download a versioned release from the project's official distribution.
3. Verify the published integrity value when one is available and record a
   SHA-256 digest here.
4. Replace the local asset; do not add a runtime CDN dependency.
5. Update the exact-hash regression test.
6. Run JavaScript syntax checks, Django `collectstatic`, the frontend suite, and
   a browser smoke test of login, navigation, dialogs, tables, and uploads.

Bootstrap 3 is end-of-life. Version 3.4.1 is the final compatible security
patch, not a long-term supported dependency. Moving templates and plugins to a
supported Bootstrap major version should be a dedicated UI migration with
browser regression coverage.
