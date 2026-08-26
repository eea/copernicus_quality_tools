"""Product identification helpers shared by delivery entry points."""

from qc_tool.common import get_product_descriptions


def find_product_description(product_ident):
    """
    given a product ident, retrieve the product description.
    :param product_ident: the product identifier, for example clc, rpz, ua.
    :return: the product description string.
    """
    description = "Unknown"
    product_descriptions = get_product_descriptions()
    if product_ident:
        case_insensitive_product_ident = product_ident.lower()
    else:
        case_insensitive_product_ident = None
    if case_insensitive_product_ident in product_descriptions:
        description = product_descriptions[case_insensitive_product_ident]
    return description


def guess_product_ident(delivery_filepath):
    """
    Tries to guess the product ident from the uploaded zip file name.
    """
    fn = delivery_filepath.stem.lower()

    product_descriptions = get_product_descriptions()
    for product_ident, product_description in product_descriptions.items():
        if fn.startswith(product_ident) or fn.endswith(product_ident):
            return product_ident
    return None
