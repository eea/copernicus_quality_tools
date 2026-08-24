---
title: Writing documentation
parent: Development
nav_order: 2
---

# Writing documentation

Documentation lives under `docs/`, uses Markdown, and is published with GitHub
Pages and Just the Docs. It must also remain readable directly on GitHub.

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
- Prefer repository-relative Markdown links so source is useful on GitHub.
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

Review every relative link and Mermaid block in the GitHub diff. If a local
Jekyll environment is available, build the Pages site as an additional check,
but do not make local Jekyll installation a prerequisite for ordinary code
changes.
