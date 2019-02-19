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
    import qc_tool.raster.r_unzip
    import qc_tool.raster.r1
    import qc_tool.raster.r2
    import qc_tool.raster.r3
    import qc_tool.raster.r4
    import qc_tool.raster.r5
    import qc_tool.raster.r6
    import qc_tool.raster.r7
    import qc_tool.raster.r8
    import qc_tool.raster.r9
    import qc_tool.raster.r10
    import qc_tool.raster.r11
    import qc_tool.raster.r12
    import qc_tool.raster.r13
    import qc_tool.vector.v_import2pg
    import qc_tool.vector.v_unzip
    import qc_tool.vector.v1_clc
    import qc_tool.vector.v1_n2k
    import qc_tool.vector.v1_rpz
    import qc_tool.vector.v1_ua_gdb
    import qc_tool.vector.v1_ua_shp
    import qc_tool.vector.v2
    import qc_tool.vector.v3
    import qc_tool.vector.v4
    import qc_tool.vector.v4_clc
    import qc_tool.vector.v5
    import qc_tool.vector.v6
    import qc_tool.vector.v8
    import qc_tool.vector.v9
    import qc_tool.vector.v10
    import qc_tool.vector.v10_unit
    import qc_tool.vector.v11_clc_change
    import qc_tool.vector.v11_clc_status
    import qc_tool.vector.v11_n2k
    import qc_tool.vector.v11_rpz
    import qc_tool.vector.v11_ua_change
    import qc_tool.vector.v11_ua_status
    import qc_tool.vector.v12
    import qc_tool.vector.v12_ua
    import qc_tool.vector.v13
    import qc_tool.vector.v14
    import qc_tool.vector.v14_rpz
    import qc_tool.vector.v15

