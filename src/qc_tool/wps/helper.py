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
