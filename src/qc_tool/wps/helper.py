#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import os
import re
import subprocess
import zipfile

from qc_tool.common import FAILED_ITEMS_LIMIT


def dir_recursive_search(in_dir, regexp=".*", target="file", deep=9999, full_path=True):
    results = []
    level = 0
    for root, dirs, files in os.walk(in_dir):
        res = [f for f in os.listdir(root) if re.search(r"{:s}".format(regexp), f)]
        for f in res:
            path = os.path.join(root, f)
            if ((target == "file" and os.path.isfile(path)) or (target == "dir" and os.path.isdir(path))) and (level <= deep):
                if full_path:
                    results.append(path)
                else:
                    results.append(f)
        level += 1
    return results

def do_layers(params):
    return [params["layer_defs"][layer_alias] for layer_alias in params["layers"]]


def dump_failed_items(connection_manager, error_table_name, pg_fid_name, src_table_name, output_dir):
    cursor = connection_manager.get_connection().cursor()
    export_table_name = ("features_{:s}".format(error_table_name))
    SQL = ("CREATE TABLE {export_table_name:s} AS "
           "(SELECT * FROM {src_table_name:s}"
           " WHERE {pg_fid_name:s} IN ("
           "  SELECT {pg_fid_name:s} FROM {error_table_name:s}))")
    SQL = SQL.format(export_table_name=export_table_name,
                     src_table_name=src_table_name,
                     error_table_name=error_table_name,
                     pg_fid_name=pg_fid_name)
    cursor.execute(SQL)
    dst_file = dump_features(connection_manager, output_dir, export_table_name)
    return dst_file

def dump_failed_pairs(connection_manager, error_table_name, pg_fid_name, src_table_name, output_dir):
    cursor = connection_manager.get_connection().cursor()
    export_table_name = ("pairs_{:s}".format(error_table_name))
    SQL = ("CREATE TABLE {export_table_name:s} AS "
           "SELECT * FROM {src_table_name:s} WHERE {pg_fid_name:s} IN "
           "(SELECT a_{pg_fid_name:s} "
           " FROM {error_table_name:s} "
           " UNION"
           " SELECT b_{pg_fid_name:s} "
           " FROM {error_table_name:s})")
    SQL = SQL.format(pg_fid_name=pg_fid_name,
                     error_table_name=error_table_name,
                     export_table_name=export_table_name,
                     src_table_name=src_table_name)
    cursor.execute(SQL)
    dst_file = dump_csv(connection_manager, output_dir, export_table_name)
    return dst_file

def dump_features(connection_manager, dst_dirpath, export_table_name):
    (dsn, schema) = connection_manager.get_dsn_schema()
    dst_filepath = dst_dirpath.joinpath("{:s}.shp".format(export_table_name))
    args = [
        "ogr2ogr",
        "-f",
        "ESRI Shapefile",
        str(dst_filepath),
        "PG:{:s} active_schema={:s}".format(dsn, schema),
        export_table_name
    ]
    subprocess.run(args)
    if not dst_filepath.exists():
        raise FileNotFoundError("exported error shapefile {:s} does not exist!".format(str(dst_filepath)))
    return zip_features(dst_filepath, dst_dirpath)

def dump_csv(connection_manager, dst_dirpath, export_table_name):
    (dsn, schema) = connection_manager.get_dsn_schema()
    dst_filepath = dst_dirpath.joinpath(export_table_name + ".csv")
    args = [
        "ogr2ogr",
        "-f",
        "CSV",
        str(dst_filepath),
        "PG:{:s} active_schema={:s}".format(dsn, schema),
        export_table_name
    ]
    subprocess.run(args)
    if not dst_filepath.exists():
        raise FileNotFoundError("exported error csv file {:s} does not exist!".format(str(dst_filepath)))
    return zip_features(dst_filepath, dst_dirpath)


def zip_features(filepath, output_dir):
    # one shapefile layer is composed of multiple files (shp, shx, dbf, prj)
    # all required files <error_table_name>.shp, <error_table_name>.dbf, <error_table_name>.shx
    # are added into one zip archive.
    src_stem = filepath.stem
    zip_filepath = output_dir.joinpath(src_stem + ".zip")
    src_dir = filepath.parent
    files_to_zip = [f for f in src_dir.iterdir() if f.stem == src_stem]
    with zipfile.ZipFile(str(zip_filepath), "w") as zf:
        for f in files_to_zip:
            zf.write(str(f), src_stem + "/" + f.name)
    return zip_filepath.name


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
            self.status.aborted()
            self.status.add_message("Can not find {:s} layer.".format(layer_alias))
            return
        if len(matched_infos) > 1:
            layer_names = [item["src_layer_name"] for item in matched_infos]
            self.status.aborted()
            self.status.add_message("Found {:d} {:s} layers: {:s}.".format(len(matched_infos),
                                                                           layer_alias,
                                                                           ", ".join(layer_names)))
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
            self.status.failed()
            self.status.add_message("There are excessive layers: {:s}.".format(desc))
