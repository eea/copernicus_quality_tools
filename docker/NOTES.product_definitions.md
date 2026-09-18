# Editing product definitions

Use the [local development workflow](../docs/getting-started/local-development.md)
and [local Compose configuration](compose.local.yaml) to work with product
recipes from the checkout. The local frontend and worker mount the repository,
including [`product_definitions/`](../product_definitions/).

The product catalog starts empty. Bundled JSON files are reference recipes;
mounting them or restarting the stack does not add products. An administrator
adds the selected specifications and then assigns their products to users.

To manage specifications without editing the checkout, sign in as an
administrator and use **Products → Upload specification**, or **Upload revision**
on a product, then **Add**. Upload one reviewed JSON file,
up to 1 MiB. A new filename adds a product; changed bytes under an existing
filename create its next dated immutable revision. The first upload of an imported
recipe creates an upload-managed release; repeating its current uploaded file
does not duplicate that revision. The product and draft or unknown product unit scope are
stored in PostgreSQL, while original bytes are retained under
`WORK_DIR/product_definitions/.versions/<ident>/<digest>.json`. The active version
is selected by `.state/<ident>.json`. The maintained local Compose setup shares
this persistent work volume between frontend and worker, so activation needs no
service restart.

Only administrators can upload or remove specifications. **Remove specification**
archives a product from active use while preserving version history and submitted
deliverables. Find it under **Removed products** and choose **Restore product**
to upload the same filename and reactivate it. Uploads and removal are
blocked while the specification has queued or running jobs. Products grouping
several specifications or release streams use the reviewed catalog manifest.

Follow [product definition import and reporting](../docs/development/product-definitions.md)
for the complete workflow and local Compose commands. `sync_product_definitions`
is an optional, explicit bulk import that stores immutable JSON documents in
PostgreSQL and derives draft product unit scopes for `/products`;
`sync_product_catalog` applies a reviewed expected-delivery plan.
Editing a recipe alone does not update either database record.

Frontend and worker execution resolve active uploaded versions before configured
recipe files. Product lists and new QC requests require an active catalog entry.
Inactive state prevents archived products from falling back to a
bundled recipe. Drain jobs before directly replacing deployed files, deploy
matching recipes to both runtimes, and perform the explicit import. A database
snapshot does not automatically become the worker's execution source. Back up
the database and the whole `WORK_DIR/product_definitions/` directory together,
including hidden `.versions` and `.state`, and exclude it from scratch cleanup.
If activation fails after the database commit, restore storage access and retry
the same original JSON. If removal cannot publish its inactive marker, restore
storage access and repeat removal; the database product remains inactive.

The [legacy editable-product Compose example](docker_compose_examples/docker-compose.editable_product.yml)
is available for reference. Use the maintained local workflow above for startup
commands and service names.
