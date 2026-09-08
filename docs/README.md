---
nav_exclude: true
search_exclude: true
---

# QC Tool documentation

This directory contains maintained documentation for the code in this checkout.
Read it locally or in the repository source view at the same revision as the
application. The wiki and separately published pages may describe other versions.

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
└── index.md           # Documentation home
```

When documentation and implementation disagree, treat the implementation as
authoritative and update the documentation in the same pull request.

The [database guide](../src/qc_tool/database/README.md) and its runbooks live
beside their owning code. The [documentation contributor guide](development/documentation.md)
explains how to maintain links and publish files from one verified source revision.
The Jekyll configuration supports site generation; it does not establish the
contents or freshness of an existing published site.
