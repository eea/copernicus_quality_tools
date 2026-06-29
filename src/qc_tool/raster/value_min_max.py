def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.raster.helper import do_raster_layers

    
    # Pass the parameters as min_allowed and max_allowed.
    min_allowed = params.get("min_allowed")
    max_allowed = params.get("max_allowed")

    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))
        ds_band = ds.GetRasterBand(1)

        # Compute exact min/max values (ignoring NoData)
        min_val, max_val = ds_band.ComputeRasterMinMax(False)
        
        errors = []

        # Check against min_allowed if it is set
        if min_allowed is not None and min_val < min_allowed:
            errors.append("values smaller than {:s} (found min: {:.4f})".format(str(min_allowed), min_val))

        # Check against max_allowed if it is set
        if max_allowed is not None and max_val > max_allowed:
            errors.append("values greater than {:s} (found max: {:.4f})".format(str(max_allowed), max_val))

        # If any boundary was violated, report it
        if errors:
            error_msg = " and ".join(errors)
            status.failed("Layer {:s} has pixels with {:s}."
                          .format(layer_def["src_layer_name"], error_msg))