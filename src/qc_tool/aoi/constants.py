"""Stable AOI constants shared by identifier and persistence layers."""


AOI_CODE_KEY = "aoi_code"
AOI_CODE_MAX_LENGTH = 255

# Order is significant: an explicit ``aoi_code`` capture is preferred when
# several equivalent aliases are populated by one external naming contract.
AOI_INPUT_ALIASES = (
    AOI_CODE_KEY,
    "delivery_unit_id",
    "fua_code",
    "fua",
    "du_id",
    "du",
    "code_city",
    "codecity",
)
