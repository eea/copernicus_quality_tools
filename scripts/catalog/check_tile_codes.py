"""Read-only tile allowlist diagnostic for selected raster catalog families.

This historical utility checks six-character lengths in the second recipe step.
It is a manual diagnostic, not an automated QC check or a complete tile validator.
Product specification bytes are only read.
"""
import argparse
import json
from pathlib import Path
import os


PRODUCT_DEFINITION_DIR = Path(__file__).resolve().parents[2] / "product_definitions"


def main(products_dir=PRODUCT_DEFINITION_DIR):
    all_product_definitions = os.listdir(products_dir)

    # restrict the checking to clcplus, hrlvlcc, hrlnvlcc definitions with aoi_codes sections in naming check.

    for product_definition in all_product_definitions:
        product_definition_path = os.path.join(products_dir, product_definition)
        if "clcplus" in product_definition or "hrlvlcc" in product_definition or "hrlnvlcc" in product_definition:
            with open(product_definition_path, "r") as fp:
                prod_def = json.load(fp)
                naming_check = prod_def["steps"][1]
                if "aoi_codes" in naming_check["parameters"]:
                    aoi_codes = naming_check["parameters"]["aoi_codes"]
                    invalid_aoi_codes = []
                    #print(f"aoi codes found! ({len(aoi_codes)})")
                    for aoi_code in aoi_codes:
                        if len(aoi_code) != 6:
                            invalid_aoi_codes.append(aoi_code)
                    if invalid_aoi_codes:
                        print(f"{product_definition} has invalid aoi codes {invalid_aoi_codes}")
                else:
                    pass
                    #print("no aoi codes to check.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products-dir", type=Path, default=PRODUCT_DEFINITION_DIR,
                        help="Product definition directory (default: repository product_definitions)")
    main(parser.parse_args().products_dir)
