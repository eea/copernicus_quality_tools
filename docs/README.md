---
nav_exclude: true
search_exclude: true
---

# QC Tool documentation

This directory contains the documentation published through GitHub Pages. It
is also designed to be read directly on GitHub.

Start here:

- [Documentation home](index.md)
- [Getting started](getting-started/index.md)
- [Architecture](architecture/index.md)
- [Local development](development/index.md)
- [Production deployment](deployment/index.md)
- [Configuration reference](reference/environment-variables.md)

## Documentation source layout

```text
docs/
├── getting-started/   # First local run and common startup problems
├── user-guide/        # Browser, API, and Django Admin workflows
├── architecture/      # Components, code boundaries, data, and security
├── development/       # Contributor workflow and tests
├── deployment/        # Production rollout and operations
├── reference/         # Environment variables and commands
├── checks/            # Quality-check reference material
├── _config.yml        # GitHub Pages / Just the Docs configuration
└── index.md           # Published documentation home
```

When documentation and implementation disagree, treat the implementation as
authoritative and update the documentation in the same pull request.
