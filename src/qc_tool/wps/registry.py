#!/usr/bin/env python3


check_function_registry = {}

def register_check_function(ident, description=None):
    # If name is supplied with dots, take the last part.
    ident = ident.split(".")[-1]

    # Check if the function has already been registered.
    if ident in check_function_registry:
        raise Exception("An attempt to reregister function with ident='%s'.".format(ident))

    # Return decorator.
    def register(func):
        func.ident = ident
        func.description = description
        check_function_registry[ident] = func
        return func
    return register

def get_check_function(ident):
    return check_function_registry[ident]

def load_all_check_functions():
    import qc_tool.wps.common_check.dummy
    import qc_tool.wps.raster_check.r1
    import qc_tool.wps.raster_check.r2
    import qc_tool.wps.raster_check.r3
    import qc_tool.wps.raster_check.r4
    import qc_tool.wps.raster_check.r5
    import qc_tool.wps.raster_check.r6
    import qc_tool.wps.raster_check.r7
    import qc_tool.wps.raster_check.r8
    import qc_tool.wps.raster_check.r9
    import qc_tool.wps.raster_check.r11
    import qc_tool.wps.raster_check.r14
    import qc_tool.wps.raster_check.r15
    import qc_tool.wps.vector_check.import2pg
    import qc_tool.wps.vector_check.v1
    import qc_tool.wps.vector_check.v2
    import qc_tool.wps.vector_check.v3
    import qc_tool.wps.vector_check.v4
    import qc_tool.wps.vector_check.v5
    import qc_tool.wps.vector_check.v6
    import qc_tool.wps.vector_check.v8
    import qc_tool.wps.vector_check.v11
    import qc_tool.wps.vector_check.v13
    import qc_tool.wps.vector_check.v14
