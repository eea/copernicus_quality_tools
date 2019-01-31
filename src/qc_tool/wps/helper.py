#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import os
import re
import subprocess
from zipfile import ZipFile

from qc_tool.common import FAILED_ITEMS_LIMIT


def do_layers(params):
    return [params["layer_defs"][layer_alias] for layer_alias in params["layers"]]

def shorten_failed_items_message(items, count):
    if len(items) == 0:
        return None
    message = ", ".join(map(str, items))
    if count > len(items):
        message += " and {:d} others".format(count - len(items))
    return message

def get_failed_items_message(cursor, error_table_name, pg_fid_name, limit=FAILED_ITEMS_LIMIT):
    sql = "SELECT {0:s} FROM {1:s} ORDER BY {0:s};".format(pg_fid_name, error_table_name)
    cursor.execute(sql)
    failed_items = [row[0] for row in cursor.fetchmany(limit)]
    failed_items_message = shorten_failed_items_message(failed_items, cursor.rowcount)
    return failed_items_message

def get_failed_pairs_message(cursor, error_table_name, pg_fid_name, limit=FAILED_ITEMS_LIMIT):
    sql = "SELECT a_{0:s}, b_{0:s} FROM {1:s} ORDER BY a_{0:s}, b_{0:s};".format(pg_fid_name, error_table_name)
    cursor.execute(sql)
    failed_pairs = ["{:s}-{:s}".format(str(row[0]), str(row[1])) for row in cursor.fetchmany(limit)]
    failed_pairs_message = shorten_failed_items_message(failed_pairs, cursor.rowcount)
    return failed_pairs_message

def zip_shapefile(shp_filepath):
    # Gather all files to be zipped.
    shp_without_extension = shp_filepath.stem
    output_dir = shp_filepath.parent
    filepaths_to_zip = [f for f in output_dir.iterdir() if f.stem == shp_without_extension]

    required_extensions = [".shp", ".dbf", ".shx", ".prj"]
    for ext in required_extensions:
        ext_filepath = output_dir.joinpath("{:s}{:s}".format(shp_without_extension, ext))
        if ext_filepath not in filepaths_to_zip:
            raise FileNotFoundError("Dumped {:s} file {:s} is missing.".format(ext, ext_filepath))

    # Zip the files.
    zip_filepath = output_dir.joinpath("{:s}.zip".format(shp_without_extension))
    with ZipFile(str(zip_filepath), "w") as zf:
        for filepath in filepaths_to_zip:
            zf.write(str(filepath), filepath.name)

    # Remove zipped files.
    for filepath in filepaths_to_zip:
        filepath.unlink()
    return zip_filepath.name


class LayerDefsBuilder():
    """
    Helper class for v1 checks doing regex lookup for layers.
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

    def extract_layer_def(self, regex, layer_alias):
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
            sql = ("WITH"
                   " last_members AS ("
                   "  SELECT *"
                   "  FROM {layer_name}"
                   "  WHERE {fid_name} IN ("
                   "   SELECT fid"
                   "   FROM {cluster_table}"
                   "   WHERE cluster_id = {cluster_id} AND cycle_nr = {cycle_nr} - 1)),"
                   " other AS ("
                   "  SELECT *"
                   "  FROM {layer_name}"
                   "  WHERE {fid_name} NOT IN (SELECT fid FROM {cluster_table})) "
                   "INSERT INTO {cluster_table}"
                   " SELECT DISTINCT {cluster_id}, {cycle_nr}, other.{fid_name}"
                   " FROM last_members, other"
                   " WHERE"
                   "  last_members.{code_column_name} = other.{code_column_name}"
                   "  AND ST_Dimension(ST_Intersection(last_members.wkb_geometry, other.wkb_geometry)) >= 1;")
            sql = sql.format(**self.sql_params, cluster_id=fid, cycle_nr=cycle_nr)
            self.cursor.execute(sql)
            if self.cursor.rowcount <= 0:
                break
