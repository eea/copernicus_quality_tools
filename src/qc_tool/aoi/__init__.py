"""Public AOI identifier and metadata contract.

External names such as ``fua_code`` and ``delivery_unit_id`` are accepted only
at input boundaries. All persisted and public representations use
``aoi_code``. Spatial validation remains the responsibility of product QC and
is intentionally outside this reusable package.
"""

from .constants import AOI_CODE_KEY
from .constants import AOI_CODE_MAX_LENGTH
from .constants import AOI_INPUT_ALIASES
from .identifiers import aoi_codes_equivalent
from .identifiers import aoi_input_aliases_equivalent
from .identifiers import canonicalize_aoi_capture_groups
from .identifiers import extract_aoi_code_from_groups
from .identifiers import has_aoi_code_capture
from .identifiers import is_aoi_input_alias
from .identifiers import normalize_aoi_code
from .identifiers import with_canonical_aoi_capture
from .metadata import AoiMetadata
from .metadata import merge_aoi_metadata


__all__ = (
    "AOI_CODE_KEY",
    "AOI_CODE_MAX_LENGTH",
    "AOI_INPUT_ALIASES",
    "AoiMetadata",
    "aoi_codes_equivalent",
    "aoi_input_aliases_equivalent",
    "canonicalize_aoi_capture_groups",
    "extract_aoi_code_from_groups",
    "has_aoi_code_capture",
    "is_aoi_input_alias",
    "merge_aoi_metadata",
    "normalize_aoi_code",
    "with_canonical_aoi_capture",
)
