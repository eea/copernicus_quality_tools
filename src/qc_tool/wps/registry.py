#!/usr/bin/env python3


check_function_registry = {}

def register_check_function(ident):
    # Check if the function has already been registered.
    if ident in check_function_registry:
        raise Exception("An attempt to reregister function with ident='%s'.".format(ident))

    # Return decorator.
    def register(func):
        func.ident = ident
        check_function_registry[ident] = func
        return func
    return register

def get_check_function(check_ident):
    func = check_function_registry[check_ident]
    return func

def load_all_check_functions():
    import qc_tool.raster.unzip
    import qc_tool.raster.format
    import qc_tool.raster.naming
    import qc_tool.raster.attribute
    import qc_tool.raster.epsg
    import qc_tool.raster.pixel_size
    import qc_tool.raster.origin
    import qc_tool.raster.bit_depth
    import qc_tool.raster.compress
    import qc_tool.raster.value
    import qc_tool.raster.gap
    import qc_tool.raster.mmu
    import qc_tool.raster.inspire
    import qc_tool.raster.color
    import qc_tool.vector.import2pg
    import qc_tool.vector.unzip
    import qc_tool.vector.naming_clc
    import qc_tool.vector.naming_n2k
    import qc_tool.vector.naming_rpz
    import qc_tool.vector.naming_ua_gdb
    import qc_tool.vector.naming_ua_shp
    import qc_tool.vector.format
    import qc_tool.vector.attribute
    import qc_tool.vector.epsg
    import qc_tool.vector.epsg_clc
    import qc_tool.vector.unique
    import qc_tool.vector.enum
    import qc_tool.vector.singlepart
    import qc_tool.vector.geometry
    import qc_tool.vector.gap
    import qc_tool.vector.gap_unit
    import qc_tool.vector.mmu_clc_change
    import qc_tool.vector.mmu_clc_status
    import qc_tool.vector.mmu_n2k
    import qc_tool.vector.mmu_rpz
    import qc_tool.vector.mmu_ua_change
    import qc_tool.vector.mmu_ua_status
    import qc_tool.vector.mmw
    import qc_tool.vector.mmw_ua
    import qc_tool.vector.overlap
    import qc_tool.vector.neighbour
    import qc_tool.vector.neighbour_rpz
    import qc_tool.vector.inspire

