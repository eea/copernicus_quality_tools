#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from psycopg2 import DatabaseError
from psycopg2 import sql


DESCRIPTION = "AOI code matches the dataset's spatial location."
IS_SYSTEM = False


_KNOWN_BOUNDARY_CODE_FIELDS = ("aoi_code", "fua_code", "du_id", "du", "codecity")
_STANDARD_AOI_PATTERNS = (
    re.compile(r"^(?P<aoi_code>[a-z]{2}[0-9]{3}l)(?:[0-9])?$", re.IGNORECASE),
    re.compile(r"^(?P<aoi_code>du[0-9]{3})(?:[a-z])?$", re.IGNORECASE),
)


def _clear_aoi(status, message):
    status.aborted(message)
    status.add_params({"aoi_code": None, "_aoi_spatially_validated": False})
    status.set_status_property("aoi_code", None)


def _compile_aoi_pattern(pattern_text):
    if not pattern_text:
        return None

    pattern = re.compile(pattern_text, re.IGNORECASE)
    if "aoi_code" not in pattern.groupindex and pattern.groups > 1:
        raise ValueError(
            "aoi_code_pattern must define an 'aoi_code' named group or at most one capture group."
        )
    return pattern


def _normalize_aoi_code(raw_code, pattern):
    if raw_code is None:
        return None

    raw_code = str(raw_code).strip()
    if not raw_code:
        return None

    if pattern is None:
        for standard_pattern in _STANDARD_AOI_PATTERNS:
            match = standard_pattern.fullmatch(raw_code)
            if match is not None:
                return match.group("aoi_code").casefold()
        return raw_code.casefold()

    match = pattern.match(raw_code)
    if match is None:
        return None
    if "aoi_code" in pattern.groupindex:
        normalized = match.group("aoi_code")
    elif pattern.groups == 1:
        normalized = match.group(1)
    else:
        normalized = match.group(0)

    if normalized is None or not normalized.strip():
        return None
    return normalized.strip().casefold()


def _source_layer_defs(params):
    layer_defs = params["layer_defs"]
    if "layers" in params:
        aliases = [alias for alias in params["layers"] if alias != "boundary"]
    else:
        aliases = [alias for alias in layer_defs if alias != "boundary"]
    return [(alias, layer_defs.get(alias)) for alias in aliases]


def _positive_intersection_query(source_table, boundary_table, code_field=None):
    code_selection = sql.SQL("TRUE")
    if code_field is not None:
        code_selection = sql.SQL("boundary.{code_field}::text").format(
            code_field=sql.Identifier(code_field)
        )

    return sql.SQL(
        """
        SELECT DISTINCT {code_selection}
        FROM {source_table} AS source
        INNER JOIN {boundary_table} AS boundary
          ON source.geom IS NOT NULL
         AND boundary.geom IS NOT NULL
        CROSS JOIN LATERAL (
          SELECT CASE
                   WHEN ST_SRID(source.geom) = ST_SRID(boundary.geom)
                     THEN source.geom
                   ELSE ST_Transform(source.geom, ST_SRID(boundary.geom))
                 END AS geom
        ) AS transformed
        CROSS JOIN LATERAL (
          SELECT ST_Intersection(transformed.geom, boundary.geom) AS geom
          WHERE ST_Intersects(transformed.geom, boundary.geom)
        ) AS overlap
        WHERE NOT ST_IsEmpty(source.geom)
          AND NOT ST_IsEmpty(boundary.geom)
          AND CASE ST_Dimension(transformed.geom)
                WHEN 2 THEN ST_Area(overlap.geom) > 0
                WHEN 1 THEN ST_Length(overlap.geom) > 0
                WHEN 0 THEN NOT ST_IsEmpty(overlap.geom)
                ELSE FALSE
              END
          {code_not_null}
        """
    ).format(
        code_selection=code_selection,
        source_table=sql.Identifier(source_table),
        boundary_table=sql.Identifier(boundary_table),
        code_not_null=(
            sql.SQL("AND boundary.{code_field} IS NOT NULL").format(
                code_field=sql.Identifier(code_field)
            )
            if code_field is not None
            else sql.SQL("")
        ),
    )


def _discover_boundary_code_field(cursor, boundary_table):
    cursor.execute(
        """
        SELECT attribute.attname
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = to_regclass(%s)
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
          AND lower(attribute.attname) = ANY(%s)
        ORDER BY lower(attribute.attname)
        """,
        (boundary_table, list(_KNOWN_BOUNDARY_CODE_FIELDS)),
    )
    return [row[0] for row in cursor.fetchall()]


def run_check(params, status):
    """Validate one named AOI against the imported dataset and boundary.

    ``aoi_code_pattern`` is an optional prefix regular expression applied to
    both the named and spatial codes. A named ``aoi_code`` capture group is
    preferred; a single unnamed capture group is also accepted. Prefix
    matching lets product-specific revision or sub-unit suffixes be ignored.
    """
    raw_claimed_code = params.get("aoi_code")
    if not isinstance(raw_claimed_code, str) or not raw_claimed_code.strip():
        _clear_aoi(status, "AOI code is missing; spatial AOI validation cannot be performed.")
        return

    try:
        pattern = _compile_aoi_pattern(params.get("aoi_code_pattern"))
    except (re.error, TypeError, ValueError) as exc:
        _clear_aoi(status, "Invalid AOI code normalization pattern: {:s}".format(str(exc)))
        return

    claimed_code = _normalize_aoi_code(raw_claimed_code, pattern)
    if claimed_code is None:
        _clear_aoi(
            status,
            "AOI code '{:s}' does not match the configured AOI code pattern."
            .format(raw_claimed_code),
        )
        return

    layer_defs = params.get("layer_defs")
    boundary_def = layer_defs.get("boundary") if isinstance(layer_defs, dict) else None
    if not boundary_def or not boundary_def.get("pg_layer_name"):
        _clear_aoi(status, "Spatial AOI validation requires an imported boundary layer.")
        return

    source_layer_defs = _source_layer_defs(params)
    if not source_layer_defs:
        _clear_aoi(status, "Spatial AOI validation requires at least one imported dataset layer.")
        return
    for alias, layer_def in source_layer_defs:
        if not layer_def or not layer_def.get("pg_layer_name"):
            _clear_aoi(
                status,
                "Dataset layer '{:s}' has not been imported for spatial AOI validation."
                .format(alias),
            )
            return

    boundary_table = boundary_def["pg_layer_name"]
    explicit_code_field = params.get("aoi_boundary_code_field")
    code_field = explicit_code_field
    if code_field is not None and (not isinstance(code_field, str) or not code_field):
        _clear_aoi(status, "AOI boundary code field must be a non-empty string.")
        return
    boundary_source = params.get("aoi_boundary_source", params.get("boundary_source"))
    selected_boundary_mode = (
        explicit_code_field is None
        and isinstance(boundary_source, str)
        and "{aoi_code}" in boundary_source
    )
    spatial_codes = set()

    try:
        with params["connection_manager"].get_connection().cursor() as cursor:
            if code_field is None and not selected_boundary_mode:
                discovered_fields = _discover_boundary_code_field(cursor, boundary_table)
                if len(discovered_fields) == 0:
                    _clear_aoi(
                        status,
                        "Boundary layer '{:s}' has no recognized AOI code field."
                        .format(boundary_table),
                    )
                    return
                if len(discovered_fields) > 1:
                    _clear_aoi(
                        status,
                        "Boundary layer '{:s}' has multiple recognized AOI code fields: {:s}."
                        .format(boundary_table, ", ".join(discovered_fields)),
                    )
                    return
                code_field = discovered_fields[0]

            for alias, layer_def in source_layer_defs:
                query = _positive_intersection_query(
                    layer_def["pg_layer_name"], boundary_table, code_field
                )
                cursor.execute(query)
                raw_spatial_codes = [row[0] for row in cursor.fetchall()]
                if not raw_spatial_codes:
                    _clear_aoi(
                        status,
                        "Dataset layer '{:s}' does not overlap any AOI boundary with positive measure."
                        .format(alias),
                    )
                    return

                if code_field is None:
                    spatial_codes.add(claimed_code)
                    continue

                for raw_spatial_code in raw_spatial_codes:
                    normalized = _normalize_aoi_code(raw_spatial_code, pattern)
                    if normalized is None:
                        _clear_aoi(
                            status,
                            "Boundary AOI code '{:s}' does not match the configured AOI code pattern."
                            .format(str(raw_spatial_code)),
                        )
                        return
                    spatial_codes.add(normalized)
    except (DatabaseError, KeyError) as exc:
        _clear_aoi(status, "Spatial AOI validation could not be completed: {:s}".format(str(exc)))
        return

    if not spatial_codes:
        _clear_aoi(status, "No AOI code could be detected from spatial analysis.")
        return
    if len(spatial_codes) > 1:
        _clear_aoi(
            status,
            "Spatial analysis detected multiple AOI codes: {:s}."
            .format(", ".join(sorted(spatial_codes))),
        )
        return

    spatial_code = next(iter(spatial_codes))
    if spatial_code != claimed_code:
        _clear_aoi(
            status,
            "AOI code '{:s}' does not match the spatially detected AOI code '{:s}'."
            .format(claimed_code, spatial_code),
        )
        return

    status.add_params({"aoi_code": spatial_code, "_aoi_spatially_validated": True})
    status.set_status_property("aoi_code", spatial_code)
