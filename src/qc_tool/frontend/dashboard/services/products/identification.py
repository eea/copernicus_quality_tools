"""Product-identification helpers shared by delivery entry points."""

from qc_tool.frontend.accounts.services.products import available_product_descriptions


def find_product_description(product_ident):
    """Return the configured description for one identifier."""

    description = "Unknown"
    product_descriptions = available_product_descriptions()
    normalized = product_ident.lower() if product_ident else None
    if normalized in product_descriptions:
        description = product_descriptions[normalized]
    return description


def guess_product_ident(delivery_filepath):
    """Guess a product identifier from the uploaded ZIP filename."""

    filename_stem = delivery_filepath.stem.lower()
    for product_ident in available_product_descriptions():
        if (
            filename_stem.startswith(product_ident)
            or filename_stem.endswith(product_ident)
        ):
            return product_ident
    return None
