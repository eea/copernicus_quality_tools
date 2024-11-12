import json
import os


PRODUCT_DEFINITION_DIR = "../product_definitions"


def main():
    all_product_definitions = os.listdir(PRODUCT_DEFINITION_DIR)

    # restrict the checking to clcplus, hrlvlcc, hrlnvlcc definitions with aoi_codes sections in naming check.

    for product_definition in all_product_definitions:
        product_definition_path = os.path.join(PRODUCT_DEFINITION_DIR, product_definition)
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
    main()
