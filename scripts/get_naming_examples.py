

import json
from pathlib import Path
from typing import Any, Dict


TARGET_KEYS = [
    "layer_names",
    "aoi_codes",
    "epsg_codes",
    "extensions",
    "reference_year",
    "formats",
]


def extract_values(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: data[key] for key in TARGET_KEYS if key in data}

def find_keys(obj, target_keys, found=None):
    if found is None:
        found = {}

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in target_keys and key not in found:
                found[key] = value
            find_keys(value, target_keys, found)

    elif isinstance(obj, list):
        for item in obj:
            find_keys(item, target_keys, found)

    return found


def main(products_dir) -> None:
    folder = Path(products_dir)

    c = 0
    results = dict()
    for json_file in sorted(folder.glob("clms_*.json")):
        c += 1
        try:
            with json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            print("{}: error reading file: {}".format(json_file.name, exc))
            continue

        values = find_keys(data, TARGET_KEYS)
        values_new = dict()
        version = "v02"
        revision = "r02"
        release_date = None
        for key, value in values.items():
            # print(key, value)
            if type(value) == str:
                values_new[key] = value
            elif type(value) == dict:
                values_new[key] = list(value.values())[0]
            elif type(value) == list:
                values_new[key] =value[0]
        # print(values)
        # print(values_new)
        # print("json_file", json_file.name)
        product_layer_prefix = "_".join(json_file.name.split("_")[0:3])
        if product_layer_prefix not in results:
            results[product_layer_prefix] = []

        if "layer_names" in values_new:
            sample_product_name = values_new["layer_names"].lstrip("^").rstrip("$")

        # print("sample_product_name orig", sample_product_name)

        # replace aoi code
        if "aoi_codes" in values_new:
            sample_product_name = sample_product_name.replace('(?P<aoi_code>[0-9a-zA-Z]{6})', values_new["aoi_codes"])
            sample_product_name = sample_product_name.replace('(?P<aoi_code>[a-zA-Z]{2})', values_new["aoi_codes"])
            sample_product_name = sample_product_name.replace('(?P<aoi_code>[0-9a-z]{6})[0-9]{1}', values_new["aoi_codes"])
            sample_product_name = sample_product_name.replace('(?P<aoi_code>[0-9a-zA-Z]{2})', values_new["aoi_codes"])
            sample_product_name = sample_product_name.replace('(?P<fua_name>[a-z\-]+)', values_new["aoi_codes"])
            sample_product_name = sample_product_name.replace('(?P<fua_name>[a-z_]+)', values_new["aoi_codes"])

        # replace AOI code for FUA regions
        sample_product_name = sample_product_name.replace('(?P<aoi_code>gf)', "gf")
        sample_product_name = sample_product_name.replace('(?P<aoi_code>gp)', "gp")
        sample_product_name = sample_product_name.replace('(?P<aoi_code>mq)', "mq")
        sample_product_name = sample_product_name.replace('(?P<aoi_code>re)', "re")
        sample_product_name = sample_product_name.replace('(?P<aoi_code>yt)', "yt")

        sample_product_name = sample_product_name.replace('(gf|GF)', "gf")
        sample_product_name = sample_product_name.replace('(gp|GP)', "gp")
        sample_product_name = sample_product_name.replace('(mq|MQ', "mq")
        sample_product_name = sample_product_name.replace('(re|RE)', "re")
        sample_product_name = sample_product_name.replace('(yt|YT)', "yt")

        # replace epsg code
        if "epsg_codes" in values_new:
            sample_product_name = sample_product_name.replace('(?P<epsg_code>[0-9]{5})', values_new["epsg_codes"])

        # replace version
        sample_product_name = sample_product_name.replace('v[0-9]{2}', version)

        # replace revision
        sample_product_name = sample_product_name.replace('r[0-9]{2}', revision)

        # replace release date
        sample_product_name = sample_product_name.replace('_[0-9]{8}', "20250101")

        # add extension
        if "extensions" in values_new:
            sample_product_name += values_new["extensions"]
        if "formats" in values_new:
            sample_product_name += values_new["formats"]

        results[product_layer_prefix].append(sample_product_name)

    for prod, sample_names in results.items():
        # filter sample names
        sample_names_aoi_fixed = list()
        sample_names_aoi_year_fixed = list()
        for sample_name in sample_names:
            if "_gp" in sample_name:
                pass
            elif "_mq" in sample_name:
                pass
            elif "_re" in sample_name:
                pass
            elif "_yt" in sample_name:
                pass
            else:
                sample_names_aoi_fixed.append(sample_name)

        is2021 = list(set([1 for i in sample_names_aoi_fixed if "2021" in i]))
        is2024 = list(set([1 for i in sample_names_aoi_fixed if "2024" in i]))

        if len(is2021) != 0 and len(is2024) != 0:
            for sample_name in sample_names_aoi_fixed:
                if "2021" not in sample_name:
                    pass
                else:
                    sample_names_aoi_year_fixed.append(sample_name)
        elif len(is2021) != 0:
            for sample_name in sample_names_aoi_fixed:
                if "2021" not in sample_name:
                    pass
                else:
                    sample_names_aoi_year_fixed.append(sample_name)
        elif len(is2024) != 0:
            for sample_name in sample_names_aoi_fixed:
                if "2024" not in sample_name:
                    pass
                else:
                    sample_names_aoi_year_fixed.append(sample_name)
        else:
            sample_names_aoi_year_fixed.append(sample_name)






        print(prod, sample_names_aoi_year_fixed)

        # print("sample_product_name new", sample_product_name)

if __name__ == "__main__":
    products_dir = "/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/product_definitions/"
    main(products_dir)


