"""QC Tool routing configuration, separate from immutable product specifications.

Keys are managed specification identifiers. These mappings never register a
product: a matching current catalog entry and the user's grant are still required.
"""


_URBAN_ATLAS_STATUS_2021 = {
    "family": "copernicus:clms:ua-lcu",
    "schema_version": "0.0.0",
    "match": {
        "variable": "LCU",
        "survey": "S2021",
        "type": "V",
        "resolution": "025ha",
    },
}

DEFAULT_DELIVERY_FILENAME_RULES = {
    "clms_ua_lcu_s2021_v025ha_fgb_parquet": _URBAN_ATLAS_STATUS_2021,
    "clms_ua_lcu_s2021_v025ha_boundary2018": _URBAN_ATLAS_STATUS_2021,
}
