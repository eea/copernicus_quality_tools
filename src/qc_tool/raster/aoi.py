#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from math import ceil
from math import floor

from osgeo import gdal
from osgeo import ogr
from osgeo import osr

from qc_tool.aoi import aoi_codes_equivalent
from qc_tool.aoi import aoi_input_aliases_equivalent
from qc_tool.aoi import invalidate_aoi_code
from qc_tool.aoi import is_aoi_input_alias
from qc_tool.aoi import normalize_aoi_code
from qc_tool.aoi import validate_spatial_aoi_codes
from qc_tool.raster.helper import get_aoi_mask_filepath


DESCRIPTION = "AOI code matches the raster dataset's spatial location."
IS_SYSTEM = True


def dataset_footprint(dataset):
    """Return the exact raster grid footprint as an OGR polygon."""
    geotransform = dataset.GetGeoTransform()
    corners = [
        gdal.ApplyGeoTransform(geotransform, 0, 0),
        gdal.ApplyGeoTransform(geotransform, dataset.RasterXSize, 0),
        gdal.ApplyGeoTransform(
            geotransform, dataset.RasterXSize, dataset.RasterYSize
        ),
        gdal.ApplyGeoTransform(geotransform, 0, dataset.RasterYSize),
    ]
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x_coordinate, y_coordinate in corners + [corners[0]]:
        ring.AddPoint_2D(x_coordinate, y_coordinate)
    footprint = ogr.Geometry(ogr.wkbPolygon)
    footprint.AddGeometry(ring)

    projection = dataset.GetProjectionRef()
    if not projection:
        raise ValueError("raster has no coordinate reference system")
    spatial_reference = osr.SpatialReference()
    spatial_reference.ImportFromWkt(projection)
    spatial_reference.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    footprint.AssignSpatialReference(spatial_reference)
    return footprint


def _transform_geometry(geometry, target_spatial_reference):
    transformed = geometry.Clone()
    source_spatial_reference = transformed.GetSpatialReference()
    if source_spatial_reference is None or target_spatial_reference is None:
        raise ValueError("AOI geometry has no coordinate reference system")
    source_spatial_reference = source_spatial_reference.Clone()
    target_spatial_reference = target_spatial_reference.Clone()
    source_spatial_reference.SetAxisMappingStrategy(
        osr.OAMS_TRADITIONAL_GIS_ORDER
    )
    target_spatial_reference.SetAxisMappingStrategy(
        osr.OAMS_TRADITIONAL_GIS_ORDER
    )
    transformed.AssignSpatialReference(source_spatial_reference)
    if not source_spatial_reference.IsSame(target_spatial_reference):
        transformed.Transform(
            osr.CoordinateTransformation(
                source_spatial_reference, target_spatial_reference
            )
        )
    return transformed


def _positive_area_overlap(first_geometry, second_geometry):
    if not first_geometry.Intersects(second_geometry):
        return False
    intersection = first_geometry.Intersection(second_geometry)
    return intersection is not None and not intersection.IsEmpty() and intersection.GetArea() > 0


def _geometry_pixel_window(dataset, geometry):
    inverse_geotransform = gdal.InvGeoTransform(dataset.GetGeoTransform())
    min_x, max_x, min_y, max_y = geometry.GetEnvelope()
    pixel_corners = [
        gdal.ApplyGeoTransform(inverse_geotransform, x_coordinate, y_coordinate)
        for x_coordinate, y_coordinate in (
            (min_x, min_y), (min_x, max_y),
            (max_x, min_y), (max_x, max_y),
        )
    ]
    x_start = max(0, floor(min(pixel[0] for pixel in pixel_corners)))
    y_start = max(0, floor(min(pixel[1] for pixel in pixel_corners)))
    x_stop = min(
        dataset.RasterXSize,
        ceil(max(pixel[0] for pixel in pixel_corners)),
    )
    y_stop = min(
        dataset.RasterYSize,
        ceil(max(pixel[1] for pixel in pixel_corners)),
    )
    if x_start >= x_stop or y_start >= y_stop:
        return None
    return x_start, y_start, x_stop, y_stop


def _polygonize_mask_block(mask_dataset, x_offset, y_offset, width, height):
    mask_values = mask_dataset.GetRasterBand(1).ReadAsArray(
        x_offset, y_offset, width, height
    )
    if mask_values is None:
        raise ValueError("AOI boundary mask pixels cannot be read")
    aoi_values = (mask_values == 1).astype("uint8")
    if not aoi_values.any():
        return ()

    memory_raster = gdal.GetDriverByName("MEM").Create(
        "", width, height, 1, gdal.GDT_Byte
    )
    geotransform = mask_dataset.GetGeoTransform()
    block_origin = gdal.ApplyGeoTransform(
        geotransform, x_offset, y_offset
    )
    memory_raster.SetGeoTransform((
        block_origin[0], geotransform[1], geotransform[2],
        block_origin[1], geotransform[4], geotransform[5],
    ))
    memory_raster.SetProjection(mask_dataset.GetProjectionRef())
    memory_band = memory_raster.GetRasterBand(1)
    memory_band.WriteArray(aoi_values)

    memory_vector = ogr.GetDriverByName("Memory").CreateDataSource("")
    spatial_reference = osr.SpatialReference()
    spatial_reference.ImportFromWkt(mask_dataset.GetProjectionRef())
    spatial_reference.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    layer = memory_vector.CreateLayer(
        "aoi", spatial_reference, geom_type=ogr.wkbPolygon
    )
    layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
    gdal.Polygonize(memory_band, memory_band, layer, 0, [])
    geometries = tuple(
        feature.GetGeometryRef().Clone()
        for feature in layer
        if feature.GetField("value") == 1
    )
    memory_vector = None
    memory_raster = None
    return geometries


def iter_aoi_mask_geometries(mask_dataset, limit_geometry):
    """Yield mask-value-one polygons intersecting a geometry's pixel window."""
    window = _geometry_pixel_window(mask_dataset, limit_geometry)
    if window is None:
        return
    x_start, y_start, x_stop, y_stop = window
    block_width = min(512, x_stop - x_start)
    block_height = min(512, y_stop - y_start)
    for y_offset in range(y_start, y_stop, block_height):
        height = min(block_height, y_stop - y_offset)
        for x_offset in range(x_start, x_stop, block_width):
            width = min(block_width, x_stop - x_offset)
            for geometry in _polygonize_mask_block(
                mask_dataset, x_offset, y_offset, width, height
            ):
                yield geometry


def geometry_overlaps_aoi_mask(mask_dataset, geometry):
    """Return whether geometry has positive-area overlap with AOI mask pixels."""
    mask_spatial_reference = osr.SpatialReference()
    mask_spatial_reference.ImportFromWkt(mask_dataset.GetProjectionRef())
    transformed_geometry = _transform_geometry(
        geometry, mask_spatial_reference
    )
    return any(
        _positive_area_overlap(transformed_geometry, mask_geometry)
        for mask_geometry in iter_aoi_mask_geometries(
            mask_dataset, transformed_geometry
        )
    )


def _find_code_field(layer, requested_field=None):
    field_names = [
        layer.GetLayerDefn().GetFieldDefn(index).GetName()
        for index in range(layer.GetLayerDefn().GetFieldCount())
    ]
    if requested_field is not None:
        matches = [
            name for name in field_names
            if aoi_input_aliases_equivalent(name, requested_field)
        ]
    else:
        matches = [name for name in field_names if is_aoi_input_alias(name)]
    if len(matches) != 1:
        raise ValueError(
            "AOI boundary must contain exactly one selected code field; found {:d}"
            .format(len(matches))
        )
    return matches[0]


def _vector_boundary_overlaps(filepath, claimed_code, raster_footprint,
                              requested_field=None):
    datasource = ogr.Open(str(filepath), 0)
    if datasource is None:
        raise ValueError("AOI boundary file {:s} cannot be opened".format(filepath.name))
    layer = datasource.GetLayer(0)
    if layer is None:
        raise ValueError("AOI boundary file {:s} has no layer".format(filepath.name))
    code_field = _find_code_field(layer, requested_field)
    transformed_footprint = _transform_geometry(
        raster_footprint, layer.GetSpatialRef()
    )

    found_code = False
    found_overlap = False
    layer.ResetReading()
    for feature in layer:
        boundary_code = feature.GetField(code_field)
        if not aoi_codes_equivalent(claimed_code, boundary_code):
            continue
        found_code = True
        boundary_geometry = feature.GetGeometryRef()
        if boundary_geometry is not None and not boundary_geometry.IsValid():
            boundary_geometry = boundary_geometry.MakeValid()
        if boundary_geometry is not None and _positive_area_overlap(
            transformed_footprint, boundary_geometry
        ):
            found_overlap = True
            break
    datasource = None
    if not found_code:
        raise ValueError(
            "AOI code '{:s}' is not present in boundary {:s}"
            .format(normalize_aoi_code(claimed_code), filepath.name)
        )
    return found_overlap


def _raster_mask_filepath(params, check, raster_dataset):
    return get_aoi_mask_filepath(
        params["boundary_dir"].joinpath("raster"),
        check.get("mask", "default"),
        raster_dataset.GetGeoTransform()[1],
        params["aoi_code"],
    )


def _raster_mask_overlaps(params, check, raster_footprint, raster_dataset):
    mask_filepath = _raster_mask_filepath(params, check, raster_dataset)
    mask_dataset = gdal.Open(str(mask_filepath))
    if mask_dataset is None:
        raise ValueError(
            "AOI boundary mask {:s} is not available".format(mask_filepath.name)
        )
    return geometry_overlaps_aoi_mask(mask_dataset, raster_footprint)


def _layer_defs_for_check(params, check):
    layer_defs = params.get("raster_layer_defs", {})
    aliases = check.get("layers") or tuple(layer_defs)
    return [
        (alias, layer_defs.get(alias))
        for alias in aliases
    ]


def detect_spatial_aoi_codes(params, contract):
    """Return the claimed code once for every raster that overlaps its boundary."""
    claimed_code = params["aoi_code"]
    detected_codes = []
    for check in contract.get("checks", ()):
        layer_defs = _layer_defs_for_check(params, check)
        if not layer_defs:
            raise ValueError("no raster dataset layer is available for AOI validation")
        for alias, layer_def in layer_defs:
            if not layer_def or not layer_def.get("src_filepath"):
                raise ValueError(
                    "raster layer '{:s}' is not available for AOI validation"
                    .format(alias)
                )
            raster_dataset = gdal.Open(str(layer_def["src_filepath"]))
            if raster_dataset is None:
                raise ValueError(
                    "raster layer '{:s}' cannot be opened for AOI validation"
                    .format(alias)
                )
            raster_footprint = dataset_footprint(raster_dataset)
            if check["source_type"] == "vector":
                boundary_filepath = params["boundary_dir"].joinpath(
                    "vector", check["source"]
                )
                if not boundary_filepath.is_file():
                    raise ValueError(
                        "AOI boundary {:s} is not available"
                        .format(check["source"])
                    )
                overlaps = _vector_boundary_overlaps(
                    boundary_filepath,
                    claimed_code,
                    raster_footprint,
                    check.get("code_field"),
                )
            else:
                overlaps = _raster_mask_overlaps(
                    params, check, raster_footprint, raster_dataset
                )
            if not overlaps:
                raise ValueError(
                    "raster layer '{:s}' does not overlap its claimed AOI boundary"
                    .format(alias)
                )
            detected_codes.append(claimed_code)
    return detected_codes


def validate_aoi(params, status, contract):
    """Validate the job's one claimed AOI using raster footprints."""
    if params.get("aoi_code") is None:
        return None
    try:
        detected_codes = detect_spatial_aoi_codes(params, contract)
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        invalidate_aoi_code(
            status,
            "Raster AOI validation could not be completed: {:s}.".format(str(exc)),
        )
        return None
    return validate_spatial_aoi_codes(
        params, status, detected_codes, medium="raster"
    )
