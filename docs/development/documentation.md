---
title: Writing documentation
parent: Development
nav_order: 2
---

# Writing documentation

Documentation is maintained alongside the code in this repository. General
guides live under `docs/`; component-owned runbooks may live beside their code.
Read the files from the same checkout or source revision as the application.
The wiki and any separately published site are not authoritative for that revision.

## Put information in the owning section

| Topic | Directory |
| --- | --- |
| First clone and local startup | `getting-started/` |
| Browser/API/Admin workflows | `user-guide/` |
| Component and code design | `architecture/` |
| Contributor workflow and tests | `development/` |
| Production rollout and maintenance | `deployment/` |
| Settings and command lookup | `reference/` |
| QC check behavior | `checks/` |

Use lowercase, descriptive, hyphen-separated filenames. Each navigation page
has YAML front matter with `title`, `parent` where applicable, and `nav_order`.

## Style

- Start with the outcome or task.
- Use one term consistently: **frontend**, **worker**, **delivery**, **job**.
- Copy commands from tested repository entrypoints, not historical wiki pages.
- Mark destructive commands before the code block.
- Never publish credentials, tokens, delivery data, or production host secrets.
- Use tables for comparisons and Mermaid for component or sequence diagrams.
- Use repository-relative Markdown links for files in this repository, and
  verify that every target and heading exists in the same checkout.
- State important limitations instead of presenting a template as universally
  production-ready.

## Keep docs synchronized

Update documentation when changing:

- Compose services or startup commands;
- environment variables or defaults;
- roles, permissions, or scope behavior;
- public/private endpoints or authentication;
- volume layout and persistence;
- deployment/runtime versions;
- API request/response contracts;
- operator procedures.

## Link to the same source revision

Link to another repository file relative to the Markdown file containing the
link. For example, the database procedure is
[`../../src/qc_tool/database/MIGRATIONS.md`](../../src/qc_tool/database/MIGRATIONS.md)
from this directory. Do not use hard-coded GitHub `blob/dev` or `blob/master`
URLs for same-repository references: they can point to different code than the
version the reader is using. External documentation should link to the actual
upstream source.

Verify file paths and heading fragments locally before adding a link. Do not
substitute a wiki page or an assumed published URL for a missing target; find
the owning file or document the missing procedure in the repository.

## Publishing

[`docs/_config.yml`](../_config.yml) provides a Jekyll / Just the Docs
configuration. Its presence does not establish that a published site matches
the checkout. Repository-relative links work in the checkout and GitHub source
view, including links to files outside `docs/`. A Jekyll build rooted only in
`docs/` does not bundle those outside files.

A publishing process must include those files or rewrite their links to
verified source URLs pinned to the exact commit being published. It must
validate the rendered links before publishing and identify that source revision.
Do not replace source-relative links with guessed site URLs to accommodate a
docs-only build.

## Validate

At minimum:

```bash
git diff --check -- docs
rg -n '\[\[' docs
rg -n '`docker-compose([[:space:]]|$)' docs
```

The first command catches whitespace errors. The second catches unconverted wiki
links. The third catches the legacy Compose v1 command; Compose filenames may
still contain `docker-compose` for compatibility.

Review every relative link, heading fragment, and Mermaid block in the diff.
Check same-repository targets in the checkout rather than relying on the wiki.
If a local Jekyll environment is available, build the site as an additional check,
but do not make local Jekyll installation a prerequisite for ordinary code
changes.
