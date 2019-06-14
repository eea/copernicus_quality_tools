#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.common import FAILED_ITEMS_LIMIT


LINEAR_CODE = "1"
PATCHY_CODE = "2"


def do_layers(params):
    if "layers" in params:
        return [params["layer_defs"][layer_alias] for layer_alias in params["layers"]]
    else:
        return params["layer_defs"].values()

def get_failed_items_message(cursor, error_table_name, pg_fid_name, limit=FAILED_ITEMS_LIMIT):
    # Get failed items.
    sql = "SELECT {0:s} FROM {1:s} ORDER BY {0:s};".format(pg_fid_name, error_table_name)
    cursor.execute(sql)
    items = [row[0] for row in cursor.fetchmany(limit)]
    if len(items) == 0:
        return None

    # Prepare and shorten the message.
    message = ", ".join(map(str, items))
    if cursor.rowcount > len(items):
        message += " and {:d} others".format(cursor.rowcount - len(items))

    return message


def find_shp_layers(unzip_dir, status):
    """
    Finds all .shp layers anywhere in the directory hierarchy under unzip_dir.
    """
    from osgeo import ogr

    shp_filepaths = [path for path in unzip_dir.glob("**/*")
                     if path.is_file() and path.suffix.lower() == ".shp"]

    shp_layer_infos = []
    for shp_filepath in shp_filepaths:
        try:
            ds = ogr.Open(str(shp_filepath))
        except:
            status.aborted("Can not open shapefile {:s}".format(shp_filepath.name))
            continue
        if ds is None:
            status.aborted("Can not open shapefile {:s}".format(shp_filepath.name))
            continue
        shp_layer = ds.GetLayer()
        if shp_layer is None:
            status.aborted("Shapefile {:s} does not contain any layer.".format(shp_filepath.name))
            continue
        shp_layer_infos.append({"src_filepath": shp_filepath, "src_layer_name": shp_layer.GetName()})
    return shp_layer_infos


def find_gdb_layers(unzip_dir, status):
    from osgeo import ogr

    # Find gdb folder.
    gdb_dirs = [path for path in unzip_dir.glob("**") if path.suffix.lower() == ".gdb"]
    gdb_layer_infos = []

    for gdb_dir in gdb_dirs:
        # Open geodatabase.
        ds = ogr.Open(str(gdb_dir))
        if ds is None:
            status.aborted("Can not open geodatabase {:s}.".format(gdb_dir.name))
            return

        for layer_index in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(layer_index)
            layer_name = layer.GetName()
            gdb_layer_infos.append({"src_layer_name": layer_name, "src_filepath": gdb_dir})
        ds = None
    return gdb_layer_infos


def check_gdb_filename(gdb_filepath, gdb_filename_regex, aoi_code, status):
    mobj = re.compile(gdb_filename_regex, re.IGNORECASE).search(gdb_filepath.name)
    if mobj is None:
        status.aborted("Geodatabase filename {:s} is not in accord with specification: '{:s}'."
                       .format(gdb_filepath.name, gdb_filename_regex))
        return

    if "?<P>aoi_code" in gdb_filename_regex and aoi_code is not None:
        try:
            detected_aoi_code = mobj.group("aoi_code")
        except IndexError:
            status.aborted("Geodatabase filename {:s} does not contain AOI code.".format(gdb_filepath.name))
            return

        if detected_aoi_code != aoi_code:
            status.aborted("Geodatabase filename AOI code '{:s}' does not match AOI code of the layers: '{:s}'"
                           .format(detected_aoi_code, aoi_code))
            return


# Extract AOI code and compare it to pre-defined list.
def extract_aoi_code(layer_defs, layer_regexes, expected_aoi_codes, status):
    layer_aoi_codes = []
    for layer_alias, layer_def in layer_defs.items():
        layer_name = layer_def["src_layer_name"]
        layer_regex = layer_regexes[layer_alias]
        mobj = re.match(layer_regex, layer_name.lower())
        if mobj is None:
            status.aborted("Layer {:s} has illegal name: {:s}.".format(layer_alias, layer_name))
            continue
        try:
            aoi_code = mobj.group("aoi_code")
        except IndexError:
            status.aborted("Layer {:s} does not contain AOI code.".format(layer_name))
            continue
        layer_aoi_codes.append(aoi_code)

        # Compare detected AOI code to pre-defined list.
        if aoi_code not in expected_aoi_codes:
            status.aborted("Layer {:s} has illegal AOI code {:s}.".format(layer_name, aoi_code))
            continue

    # Check that AOI code could be detected.
    if len(set(layer_aoi_codes)) == 0:
        status.aborted("AOI code could not be detected from any layer name.")
        return

    # If there are multiple layers, check that all layers have the same AOI code.
    if len(set(layer_aoi_codes)) > 1:
        status.aborted("Layers do not have the same AOI code. Detected AOI codes: {:s}"
                       .format(",".join(list(layer_aoi_codes))))

    # Set aoi_code as a global parameter.
    return aoi_code


class LayerDefsBuilder():
    """
    Helper class for naming checks doing regex lookup for layers.
    """
    def __init__(self, status):
        self.status = status
        self.layer_infos = []
        self.tpl_params = {}
        self.layer_defs = {}

    def add_layer_info(self, layer_filepath, layer_name):
        self.layer_infos.append({"src_filepath": layer_filepath, "src_layer_name": layer_name})

    def set_tpl_params(self, **kwargs):
        for k, v in kwargs.items():
            self.tpl_params[k] = v

    def extract_all_layers(self):
        layer_index = 0
        for info in self.layer_infos:
            layer_index += 1
            layer_alias = "layer_{:d}".format(layer_index)
            self.layer_defs[layer_alias] = info


    def extract_layer_def(self, regex, layer_alias):
        if self.tpl_params:
            regex = regex.format(**self.tpl_params)
        regex = re.compile(regex, re.IGNORECASE)
        matched_infos = [info for info in self.layer_infos if regex.search(info["src_layer_name"])]
        if len(matched_infos) == 0:
            self.status.aborted("Can not find {:s} layer.".format(layer_alias))
            return
        if len(matched_infos) > 1:
            layer_names = [item["src_layer_name"] for item in matched_infos]
            self.status.aborted("Found {:d} {:s} layers: {:s}."
                                .format(len(matched_infos), layer_alias, ", ".join(layer_names)))
            return

        # Pop the layer info from the source list.
        layer_info = self.layer_infos.pop(self.layer_infos.index(matched_infos[0]))

        # Add regex groups to layer info.
        layer_info["groups"] = regex.search(layer_info["src_layer_name"]).groupdict()

        # Add layer info to layer_defs.
        self.layer_defs[layer_alias] = layer_info

    def check_excessive_layers(self):
        if len(self.layer_infos) > 0:
            desc = ", ".join(info["src_layer_name"] for info in self.layer_infos)
            self.status.failed("There are excessive layers: {:s}.".format(desc))


class ComplexChangeCollector():
    """Collects members of complex changes across the layer.

    The set of features participating in one complex change is called cluster here.
    Clusters are built so that every fid passed to collect_clusters() becomes member of just one cluster.

    The class presumes that the type of fid column is always integer.
    """
    def __init__(self, cursor, cluster_table, layer_name, fid_name, code_column_name):
        self.cursor = cursor
        self.sql_params = {"cluster_table": cluster_table,
                           "layer_name": layer_name,
                           "fid_name": fid_name,
                           "code_column_name": code_column_name}

    def create_cluster_table(self):
        self.cursor.execute("DROP TABLE IF EXISTS {cluster_table};".format(**self.sql_params))
        self.cursor.execute("CREATE TABLE {cluster_table} (cluster_id integer, cycle_nr integer, fid integer);".format(**self.sql_params))

    def build_clusters(self, fids):
        for fid in fids:
            self.collect_cluster_members(fid)

    def collect_cluster_members(self, fid):
        # Check the feature is not a member of any already built cluster.
        sql = "SELECT fid FROM {cluster_table} WHERE fid = %s;".format(**self.sql_params)
        self.cursor.execute(sql, [fid])
        if self.cursor.rowcount >= 1:
            return

        # Init cycle counter.
        cycle_nr = 0

        # Insert initial member.
        sql = "INSERT INTO {cluster_table} VALUES (%s, %s, %s);"
        sql = sql.format(**self.sql_params)
        self.cursor.execute(sql, [fid, cycle_nr, fid])

        # Collect all remaining members.
        # Every cycle extends the cluster by members which are neighbours of the members
        # added in the previous cycle.
        while True:
            cycle_nr += 1
            sql = ("INSERT INTO {cluster_table}"
                   " SELECT DISTINCT {cluster_id}, {cycle_nr}, other.{fid_name}"
                   " FROM"
                   "  (SELECT *"
                   "   FROM {layer_name}"
                   "   WHERE {fid_name} IN"
                   "    (SELECT fid"
                   "     FROM {cluster_table}"
                   "     WHERE cluster_id = {cluster_id} AND cycle_nr = {cycle_nr} - 1)"
                   "  ) AS last_members,"
                   "  (SELECT *"
                   "   FROM {layer_name}"
                   "   WHERE {fid_name} NOT IN"
                   "    (SELECT fid FROM {cluster_table})"
                   "  ) AS other"
                   " WHERE"
                   "  last_members.{code_column_name} = other.{code_column_name}"
                   "  AND last_members.geom && other.geom"
                   "  AND ST_Dimension(ST_Intersection(last_members.geom, other.geom)) >= 1;")
            sql = sql.format(**self.sql_params, cluster_id=fid, cycle_nr=cycle_nr)
            self.cursor.execute(sql)
            if self.cursor.rowcount <= 0:
                break
