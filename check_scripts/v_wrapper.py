import json
import os
import ogr
from import_file import import_file

# import check scripts
dir_this = os.path.dirname(os.path.realpath(__file__))  # parent directory of this file


def run(conig_file, filename, layer):

    dir_this = os.path.dirname(os.path.realpath(__file__))

    # directory with config files
    general_config_dir = os.path.join(dir_this, 'helpers/config_files/general')

    # import helper
    helper = import_file(os.path.join(dir_this, 'helpers/helper.py'))

    # import check modules
    v1 = import_file(os.path.join(dir_this, 'common_checks/VR1.py'))
    # v2 = ...
    # v3 = ...

    # -------------------------------
    # basic check of input parameters
    # -------------------------------

    # enable ogr to use exceptions
    ogr.UseExceptions()

    # check of input data source existence
    if not os.path.exists(filename):
        return {"STATUS": "FAILED",
                "MESSAGE": "INPUT DATA SOURCE DOES NOT EXIST IN THE FILESYSTEM"}

    # check of input data source
    try:
        fgdbopen = ogr.Open(filename)
        if fgdbopen is None:
            return {"STATUS": "FAILED",
                    "MESSAGE": "INVALID DATA SOURCE"}
    except:
        return {"STATUS": "FAILED",
                "MESSAGE": "INVALID DATA SOURCE"}

    # checking the existence of the layer in the data source
    fcs_in_fgdb = list()
    for lyr in fgdbopen:
        fcs_in_fgdb.append(lyr.GetName())
    if layer not in fcs_in_fgdb:
        return {"STATUS": "FAILED",
                "MESSAGE": "NO SUCH LAYER IN DATA SOURCE"}
    lyr = None
    fgdbopen = None

    # check for appropriate config file existence
    if not os.path.exists(conig_file):
        return {"STATUS": "FAILED",
                "MESSAGE": "APPROPRIATED CONFIG FILE DOES NOT EXIST"}

    # --------------------------------
    # load data from check config file
    # --------------------------------

    with open(conig_file) as cf:
        config_data = json.load(cf)

    # get list of required checks
    list_of_checks = [check_id["check_id"] for check_id in config_data["checks"][:]]

    # ======
    # CHECKS
    # ======

    # --------------------
    # request for 1. check
    # --------------------

    if "V1" in list_of_checks:

        # get config parameters for V1 check
        v1_config = [d for d in config_data["checks"] if d["check_id"] == "V1"][0]

        # load FileExtension: driver pairs from config file
        config_drivers = os.path.join(general_config_dir, 'gdal_ogr_drivers.json')
        with open(config_drivers) as drivers_data:
            drivers_load = json.load(drivers_data)
        print v1.run_check(v1_config, filename, drivers_load)


#     # request for 2. check
#     if "V2" in list_of_checks:
#         v2_params = [d for d in json_data["checks"] if d["check_id"] == "V2"]
#         v2.run_check(v2_params, gdb, fc)

print run("/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/check_scripts/helpers/config_files/vector/clc_chaYY.json",
          "/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/testing_data/clc2012_mt.gdb",
          "cha12_MT")