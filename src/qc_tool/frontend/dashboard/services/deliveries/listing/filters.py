"""Bounded delivery-list filter and pagination parsing."""

import logging
import json
from qc_tool.product_units import PRODUCT_UNIT_CODE_MAX_LENGTH

logger = logging.getLogger(__name__)

MAX_DELIVERY_PAGE_SIZE = 1_000
MAX_DELIVERY_OFFSET = 10_000_000

DELIVERY_FILTER_VALUE_LIMITS = {
    "product_description": 500,
    "product_unit_code": PRODUCT_UNIT_CODE_MAX_LENGTH,
}


def parse_filter(filter_str, column_lookup):
    filter_sql = ""
    filter_params = []
    filter_dict = decode_filter_mapping(filter_str)
    for key, val in filter_dict.items():
        filter_column = column_lookup.get(key)
        if not filter_column:
            # ignore any undefined filter columns
            continue
        if key == "product_description":
            filter_sql += f" AND {filter_column} = %s"
            filter_params.append(val)
        elif key == "last_job_status":
            if val == "Not checked":
                filter_sql += f" AND {filter_column} IS NULL"
            else:
                filter_sql += f" AND {filter_column} = %s"
                filter_params.append(val)
        else:
            filter_sql += f" AND {filter_column} LIKE %s"
            filter_params.append(f"%{val}%")
    return filter_sql, filter_params


def decode_filter_mapping(filter_str):
    """Return bounded string filters supported by the delivery workspace."""

    try:
        filter_dict = json.loads(filter_str)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Unable to decode filter expression %r", filter_str)
        return {}

    if not isinstance(filter_dict, dict):
        logger.warning("Filter expression must be a JSON object: %r", filter_str)
        return {}

    supported = {}
    for key, value in filter_dict.items():
        maximum = DELIVERY_FILTER_VALUE_LIMITS.get(key)
        if maximum is None:
            continue
        if not isinstance(value, str) or len(value) > maximum:
            logger.warning("Ignoring invalid delivery filter field %r", key)
            continue
        supported[key] = value
    return supported


def bounded_query_integer(value, *, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)
