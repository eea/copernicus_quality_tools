#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from psycopg2 import DatabaseError
from psycopg2 import sql

from qc_tool.aoi import aoi_codes_equivalent
from qc_tool.aoi import aoi_input_aliases_equivalent
from qc_tool.aoi import invalidate_aoi_code
from qc_tool.aoi import is_aoi_input_alias
from qc_tool.aoi import mark_aoi_medium_not_applicable
from qc_tool.aoi import validate_spatial_aoi_codes


DESCRIPTION = "AOI code matches the vector dataset's spatial location."
IS_SYSTEM = True


def _source_layer_defs(params, contract):
    layer_defs = params.get("layer_defs", {})
    aliases = contract.get("layers") or tuple(
        alias for alias in layer_defs if alias != "boundary"
    )
    return [
        (alias, layer_defs.get(alias))
        for alias in aliases
        if alias != "boundary"
    ]


def _boundary_code_fields(cursor, boundary_table):
    cursor.execute(
        """
        SELECT attribute.attname
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = to_regclass(%s)
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        ORDER BY attribute.attnum
        """,
        (boundary_table,),
    )
    return [name for (name,) in cursor.fetchall() if is_aoi_input_alias(name)]


def _positive_intersection_query(source_table, boundary_table, code_field=None):
    code_selection = sql.SQL("TRUE")
    code_not_null = sql.SQL("")
    code_filter = sql.SQL("")
    if code_field is not None:
        code_selection = sql.SQL("boundary.{code_field}::text").format(
            code_field=sql.Identifier(code_field)
        )
        code_not_null = sql.SQL("AND boundary.{code_field} IS NOT NULL").format(
            code_field=sql.Identifier(code_field)
        )
        code_filter = sql.SQL(
            "AND boundary.{code_field}::text = ANY(%s)"
        ).format(code_field=sql.Identifier(code_field))

    return sql.SQL(
        """
        SELECT DISTINCT {code_selection}
        FROM {source_table} AS source
        INNER JOIN {boundary_table} AS boundary
          ON source.geom IS NOT NULL
         AND boundary.geom IS NOT NULL
        CROSS JOIN LATERAL (
          SELECT ST_MakeValid(boundary.geom) AS geom
        ) AS valid_boundary
        CROSS JOIN LATERAL (
          SELECT ST_MakeValid(
                   CASE
                     WHEN ST_SRID(source.geom) = ST_SRID(valid_boundary.geom)
                       THEN source.geom
                     ELSE ST_Transform(
                       source.geom, ST_SRID(valid_boundary.geom)
                     )
                   END
                 ) AS geom
        ) AS transformed
        CROSS JOIN LATERAL (
          SELECT ST_Intersection(
                   transformed.geom, valid_boundary.geom
                 ) AS geom
          WHERE ST_Intersects(transformed.geom, valid_boundary.geom)
        ) AS overlap
        WHERE NOT ST_IsEmpty(source.geom)
          AND NOT ST_IsEmpty(valid_boundary.geom)
          AND CASE ST_Dimension(transformed.geom)
                WHEN 2 THEN ST_Area(overlap.geom) > 0
                WHEN 1 THEN ST_Length(overlap.geom) > 0
                WHEN 0 THEN NOT ST_IsEmpty(overlap.geom)
                ELSE FALSE
              END
          {code_not_null}
          {code_filter}
        """
    ).format(
        code_selection=code_selection,
        source_table=sql.Identifier(source_table),
        boundary_table=sql.Identifier(boundary_table),
        code_not_null=code_not_null,
        code_filter=code_filter,
    )


def _boundary_code_values(cursor, boundary_table, code_field):
    cursor.execute(
        sql.SQL(
            "SELECT DISTINCT {code_field}::text "
            "FROM {boundary_table} WHERE {code_field} IS NOT NULL"
        ).format(
            code_field=sql.Identifier(code_field),
            boundary_table=sql.Identifier(boundary_table),
        )
    )
    return [value for (value,) in cursor.fetchall()]


def _table_has_geometry(cursor, table_name):
    cursor.execute(
        sql.SQL(
            "SELECT EXISTS (SELECT 1 FROM {table_name} "
            "WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom))"
        ).format(table_name=sql.Identifier(table_name))
    )
    return cursor.fetchone()[0]


def _source_extent(cursor, table_name, target_srid):
    cursor.execute(
        sql.SQL(
            "WITH extent AS ("
            "  SELECT ST_Extent("
            "    CASE WHEN ST_SRID(geom) = %s THEN geom "
            "         ELSE ST_Transform(geom, %s) END"
            "  ) AS bounds FROM {table_name} "
            "  WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)"
            ") "
            "SELECT ST_XMin(bounds), ST_XMax(bounds), "
            "       ST_YMin(bounds), ST_YMax(bounds) FROM extent"
        ).format(table_name=sql.Identifier(table_name)),
        (target_srid, target_srid),
    )
    return cursor.fetchone()


def _extent_geometry(extent, spatial_reference):
    from osgeo import ogr

    min_x, max_x, min_y, max_y = extent
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x_coordinate, y_coordinate in (
        (min_x, min_y), (max_x, min_y), (max_x, max_y),
        (min_x, max_y), (min_x, min_y),
    ):
        ring.AddPoint_2D(x_coordinate, y_coordinate)
    geometry = ogr.Geometry(ogr.wkbPolygon)
    geometry.AddGeometry(ring)
    geometry.AssignSpatialReference(spatial_reference)
    return geometry


def _positive_mask_intersection_query(source_table):
    return sql.SQL(
        """
        WITH mask AS (
          SELECT ST_GeomFromWKB(%s, %s) AS geom
        )
        SELECT EXISTS (
          SELECT 1
          FROM {source_table} AS source
          CROSS JOIN mask
          CROSS JOIN LATERAL (
            SELECT ST_MakeValid(
                     CASE
                       WHEN ST_SRID(source.geom) = ST_SRID(mask.geom)
                         THEN source.geom
                       ELSE ST_Transform(source.geom, ST_SRID(mask.geom))
                     END
                   ) AS geom
          ) AS transformed
          CROSS JOIN LATERAL (
            SELECT ST_Intersection(transformed.geom, mask.geom) AS geom
            WHERE ST_Intersects(transformed.geom, mask.geom)
          ) AS overlap
          WHERE source.geom IS NOT NULL
            AND NOT ST_IsEmpty(source.geom)
            AND CASE ST_Dimension(transformed.geom)
                  WHEN 2 THEN ST_Area(overlap.geom) > 0
                  WHEN 1 THEN ST_Length(overlap.geom) > 0
                  WHEN 0 THEN NOT ST_IsEmpty(overlap.geom)
                  ELSE FALSE
                END
        )
        """
    ).format(source_table=sql.Identifier(source_table))


def _contract_raster_mask(params, contract):
    from osgeo import gdal
    from qc_tool.raster.helper import get_aoi_mask_filepath

    raster_layer_defs = params.get("raster_layer_defs", {})
    for check in contract.get("checks", ()):
        for raster_alias in check.get("layers") or tuple(raster_layer_defs):
            raster_layer_def = raster_layer_defs.get(raster_alias)
            if not raster_layer_def or not raster_layer_def.get("src_filepath"):
                continue
            raster_dataset = gdal.Open(str(raster_layer_def["src_filepath"]))
            if raster_dataset is None:
                continue
            mask_filepath = get_aoi_mask_filepath(
                params["boundary_dir"].joinpath("raster"),
                check.get("mask", "default"),
                raster_dataset.GetGeoTransform()[1],
                params["aoi_code"],
            )
            mask_dataset = gdal.Open(str(mask_filepath))
            if mask_dataset is not None:
                return mask_dataset
    raise ValueError("AOI boundary raster mask is not available")


def _detect_against_raster_mask(params, contract):
    from osgeo import osr
    from qc_tool.raster.aoi import iter_aoi_mask_geometries

    mask_dataset = _contract_raster_mask(params, contract)
    spatial_reference = osr.SpatialReference()
    spatial_reference.ImportFromWkt(mask_dataset.GetProjectionRef())
    spatial_reference.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    spatial_reference.AutoIdentifyEPSG()
    authority_code = spatial_reference.GetAuthorityCode(None)
    if authority_code is None:
        raise ValueError("AOI boundary mask has no identifiable EPSG code")
    target_srid = int(authority_code)

    detected_codes = []
    nonempty_layer_count = 0
    with params["connection_manager"].get_connection().cursor() as cursor:
        for alias, layer_def in _source_layer_defs(params, contract):
            if not layer_def or not layer_def.get("pg_layer_name"):
                raise ValueError(
                    "vector layer '{:s}' has not been imported".format(alias)
                )
            table_name = layer_def["pg_layer_name"]
            if not _table_has_geometry(cursor, table_name):
                continue
            nonempty_layer_count += 1
            extent = _source_extent(cursor, table_name, target_srid)
            limit_geometry = _extent_geometry(extent, spatial_reference)
            query = _positive_mask_intersection_query(table_name)
            overlaps = False
            for mask_geometry in iter_aoi_mask_geometries(
                mask_dataset, limit_geometry
            ):
                cursor.execute(
                    query,
                    (bytes(mask_geometry.ExportToWkb()), target_srid),
                )
                if cursor.fetchone()[0]:
                    overlaps = True
                    break
            if not overlaps:
                raise ValueError(
                    "vector layer '{:s}' does not overlap its claimed AOI mask"
                    .format(alias)
                )
            detected_codes.append(params["aoi_code"])
    if nonempty_layer_count == 0:
        raise ValueError(
            "no non-empty vector dataset layer is available for AOI validation"
        )
    return detected_codes


def detect_spatial_aoi_codes(params, contract):
    """Return boundary AOI codes having positive-measure dataset overlap."""
    if contract.get("source_type") == "raster":
        return _detect_against_raster_mask(params, contract)

    layer_defs = params.get("layer_defs", {})
    boundary_def = layer_defs.get("boundary")
    if not boundary_def or not boundary_def.get("pg_layer_name"):
        raise ValueError("AOI boundary has not been imported")

    source_layers = _source_layer_defs(params, contract)
    if not source_layers:
        raise ValueError("no vector dataset layer is available for AOI validation")
    missing_layers = [
        alias for alias, layer_def in source_layers
        if not layer_def or not layer_def.get("pg_layer_name")
    ]
    if missing_layers:
        raise ValueError(
            "vector layer(s) have not been imported: {:s}"
            .format(", ".join(missing_layers))
        )

    boundary_table = boundary_def["pg_layer_name"]
    code_field = contract.get("code_field")
    selected_boundary = (
        contract.get("selected_boundary", False)
        or "{aoi_code}" in contract.get("source", "")
    )
    detected_codes = []
    with params["connection_manager"].get_connection().cursor() as cursor:
        matching_boundary_codes = None
        if not selected_boundary:
            code_fields = _boundary_code_fields(cursor, boundary_table)
            if code_field is not None:
                code_fields = [
                    field for field in code_fields
                    if aoi_input_aliases_equivalent(field, code_field)
                ]
            if len(code_fields) != 1:
                raise ValueError(
                    "AOI boundary must contain exactly one recognized code field; found {:d}"
                    .format(len(code_fields))
                )
            code_field = code_fields[0]
            matching_boundary_codes = [
                boundary_code
                for boundary_code in _boundary_code_values(
                    cursor, boundary_table, code_field
                )
                if aoi_codes_equivalent(
                    params["aoi_code"], boundary_code
                )
            ]
            if not matching_boundary_codes:
                raise ValueError(
                    "AOI code '{:s}' is not present in the selected boundary"
                    .format(params["aoi_code"])
                )

        nonempty_layer_count = 0
        for alias, layer_def in source_layers:
            if not _table_has_geometry(cursor, layer_def["pg_layer_name"]):
                continue
            nonempty_layer_count += 1
            query = _positive_intersection_query(
                layer_def["pg_layer_name"], boundary_table, code_field
            )
            if matching_boundary_codes is None:
                cursor.execute(query)
            else:
                cursor.execute(query, (matching_boundary_codes,))
            layer_codes = [value for (value,) in cursor.fetchall()]
            if not layer_codes:
                raise ValueError(
                    "vector layer '{:s}' does not overlap an AOI boundary with positive measure"
                    .format(alias)
                )
            if code_field is None:
                detected_codes.append(params["aoi_code"])
            else:
                detected_codes.extend(layer_codes)
        if nonempty_layer_count == 0:
            raise ValueError(
                "no non-empty vector dataset layer is available for AOI validation"
            )
    return detected_codes


def validate_aoi(params, status, contract):
    """Validate the job's one claimed AOI using imported vector geometry."""
    if params.get("aoi_code") is None:
        return None
    if params.get("skip_vector_checks"):
        status.info("Vector AOI validation is not applicable to this empty vector delivery.")
        return mark_aoi_medium_not_applicable(
            params, status, medium="vector"
        )

    try:
        detected_codes = detect_spatial_aoi_codes(params, contract)
    except (DatabaseError, KeyError, OSError, RuntimeError, ValueError) as exc:
        invalidate_aoi_code(
            status,
            "Vector AOI validation could not be completed: {:s}.".format(str(exc)),
        )
        return None
    return validate_spatial_aoi_codes(
        params, status, detected_codes, medium="vector"
    )
