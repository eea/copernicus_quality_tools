# Editing product definitions

Use the [local development workflow](../docs/getting-started/local-development.md)
and [local Compose configuration](compose.local.yaml) to work with product
recipes from the checkout. The local frontend and worker mount the repository,
including [`product_definitions/`](../product_definitions/).

Executable check recipes and relational product catalog records have separate
ownership. Follow [catalog ownership](../docs/architecture/product-catalog-and-submissions.md#catalog-ownership)
and [deployment order](../docs/architecture/product-catalog-and-submissions.md#deployment-order)
when changing the catalog. Editing a recipe does not register a catalog release.

The [legacy editable-product Compose example](docker_compose_examples/docker-compose.editable_product.yml)
is available for reference. Use the maintained local workflow above for startup
commands and service names.
