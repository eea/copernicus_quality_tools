# Obsolete wiki documentation tools

These files are retained together for a deletion decision. They have no callers
in the current repository's CI, Docker setup or documentation workflow.

| File | Historical purpose | Removal reason |
| --- | --- | --- |
| `crawl_sitemap.py` | Crawl the GitHub wiki and write a sitemap in the current directory | The current documentation source is `docs/`, not the wiki. |
| `generate_sitemap.py` | Fetch one wiki page and write a sitemap relative to the script's parent | Overlapping implementation of the same obsolete workflow. |
| `sitemap.xml` | Generated historical wiki URLs | Generated output rather than maintained source. |
| `sidebar.md` | Empty wiki sidebar artifact | No content or callers. |

The current [`docs/_config.yml`](../../../docs/_config.yml) already enables
`jekyll-sitemap`; neither Python tool builds that documentation. The retained
tools use requests/BeautifulSoup and perform network/file operations. They are
not CLI help targets or automated tests.

Propose removing all four files together after confirming that no external
operator still relies on the historical wiki workflow. They remain byte-for-byte
historical implementations apart from their lifecycle docstrings; moving them
does not maintain their old output locations as a public API.
