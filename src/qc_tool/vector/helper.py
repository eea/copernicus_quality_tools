#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import re
import time
from zipfile import ZipFile


import requests

from qc_tool.common import FAILED_ITEMS_LIMIT

INSPIRE_VALIDATOR_URL = "http://inspire.ec.europa.eu/validator/"
INSPIRE_SERVICE_URL = INSPIRE_VALIDATOR_URL + "v2/"
INSPIRE_TEST_SUITE_NAME = "INSPIRE data sets and data set series interoperability metadata"
INSPIRE_SERVER_TIMEOUT = 60
INSPIRE_TEST_RUN_TIMEOUT = 300
INSPIRE_POLL_INTERVAL = 20
INSPIRE_MAX_RETRIES = 3


def do_unzip(zip_filepath, unzip_dir, status):
    # The source zip file must have .zip extension.
    if not zip_filepath.name.lower().endswith(".zip"):
        status.aborted("Uploaded delivery {:s} has incorrect file format. Delivery must be a .zip file."
                       .format(zip_filepath.name))
    unzip_dir.mkdir()

    # The source zip file must be a zip archive.
    try:
        with ZipFile(str(zip_filepath)) as zip_file:
            zip_file.extractall(path=str(unzip_dir))
    except Exception as ex:
        status.aborted("Error unzipping file {:s}.".format(zip_filepath.name))
        return

    status.add_params({"unzip_dir": unzip_dir})


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

    # Find all gdb directories.
    gdb_dirs = [path for path in unzip_dir.glob("**") if path.suffix.lower() == ".gdb"]
    gdb_layer_infos = []

    for gdb_dir in gdb_dirs:
        # Open geodatabase.
        ds = ogr.Open(str(gdb_dir))
        if ds is None:
            status.aborted("Can not open geodatabase {:s}.".format(str(gdb_dir.relative_to(unzip_dir))))
            continue
        for layer_index in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(layer_index)
            layer_name = layer.GetName()
            gdb_layer_infos.append({"src_layer_name": layer_name, "src_filepath": gdb_dir})
        ds = None
    return gdb_layer_infos


def find_gpkg_layers(unzip_dir, status):
    from osgeo import ogr

    # Find .gpkg files.
    gpkg_filepaths = [path for path in unzip_dir.glob("**/*")
                     if path.is_file() and path.suffix.lower() == ".gpkg"]
    gpkg_layer_infos = []

    for gpkg_filepath in gpkg_filepaths:
        # Open geopackage.
        ds = ogr.Open(str(gpkg_filepath))
        if ds is None:
            status.aborted("Can not open geopackage {:s}.".format(gpkg_filepath.name))
            return []

        for layer_index in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(layer_index)
            layer_name = layer.GetName()
            gpkg_layer_infos.append({"src_layer_name": layer_name, "src_filepath": gpkg_filepath})
        ds = None
    return gpkg_layer_infos


def find_documents(unzip_dir, regex):
    document_filepaths = [path for path in unzip_dir.glob("**/*") if path.is_file()]
    regex = re.compile(regex, re.IGNORECASE)
    matched_document_filepaths = [doc for doc in document_filepaths if regex.search(doc.name)]
    if len(matched_document_filepaths) == 0:
        return False
    return matched_document_filepaths


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
            self.status.aborted("The {:s} layer name does not match naming convention.".format(layer_alias))
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


class InspireServiceClient():
    """This class contains methods for communicating with the INSPIRE validator service API.
    """

    @staticmethod
    def retrieve_test_suite_id():
        """
        Retrieves the INSPIRE executable test suite ID from the INSPIRE service
        :return: (suite ID, "ok") if the suite ID is correctly returned or (None, ERROR_MESSAGE) in case of failure.
        """
        try:
            r = requests.get(INSPIRE_SERVICE_URL + "ExecutableTestSuites.json", timeout=INSPIRE_SERVER_TIMEOUT)
            r.raise_for_status()
            # The service should return a json object with a list of test suites.
            test_suites = r.json()["EtfItemCollection"]["executableTestSuites"]["ExecutableTestSuite"]
            inspire_test_suites = [t for t in test_suites if INSPIRE_TEST_SUITE_NAME in t["label"]]
            # The test suites should contain exactly one suite with label equal to INSPIRE_TEST_SUITE_NAME.
            if len(inspire_test_suites) == 0:
                raise ValueError("The validator service {:s} does not have any test suites named '{:s}'".format(
                    INSPIRE_VALIDATOR_URL, INSPIRE_TEST_SUITE_NAME))
            if len(inspire_test_suites) > 1:
                raise ValueError("The validator service {:s} has more than one test suite named '{:s}'".format(
                    INSPIRE_VALIDATOR_URL, INSPIRE_TEST_SUITE_NAME))

            return inspire_test_suites[0]["id"], "ok"
        except requests.exceptions.HTTPError as ex:
            return None, str(ex)
        except requests.exceptions.ConnectionError:
            return None, "Service not available."
        except requests.exceptions.Timeout:
            return None, "Connection timeout."
        except requests.exceptions.RequestException as ex:
            return None, repr(ex)
        except KeyError:
            return None, "Service API returned unexpected response."
        except Exception as ex:
            return None, repr(ex)

    @staticmethod
    def create_test_object(xml_filepath):
        """
        Uploads a xml file to INSPIRE service and receives a temporary test object ID.
        :return: (status_code, test object ID, "ok") if the xml file was correctly uploaded or (None, ERROR_MESSAGE) if upload failed.
        """
        xml_upload_url = INSPIRE_SERVICE_URL + "TestObjects?action=upload"

        try:
            with open(str(xml_filepath), "rb") as filehandle:
                xml_file_data = {"file": (xml_filepath.name, filehandle)}

                r = requests.post(xml_upload_url, files=xml_file_data, timeout=INSPIRE_SERVER_TIMEOUT)
                if r.status_code == 400:
                    return (r.status_code,
                            r.json(),
                            "The xml file {:s} does not contain a <gmd:MD_Metadata> top-level element."
                            .format(xml_filepath.name))
                r.raise_for_status()

                # The service should return a json object with the test object ID.
                test_object = r.json()
                object_id = test_object["testObject"]["id"]
                # The test_object_id must be used without the "EID" prefix.
                if object_id.startswith("EID"):
                    return r.status_code, object_id[3:], "ok"
                else:
                    return r.status_code, object_id, "ok"

        except requests.exceptions.HTTPError as ex:
            return None, None, str(ex)
        except requests.exceptions.ConnectionError:
            return None, None, "Service not available."
        except requests.exceptions.Timeout:
            return None, None, "Connection timeout."
        except requests.exceptions.RequestException as ex:
            return None, None, repr(ex)
        except KeyError:
            return None, None, "Service API returned unexpected response."
        except Exception as ex:
            return None, None, repr(ex)

    @staticmethod
    def start_test_run(test_suite_id, test_object_id):
        """
        Instructs the service to start a new test run.
        The created test run is executed asynchronously on the service.
        :param test_suite_id: The test suite ID, obtained with retrieve_test_suite_id() function.
        :param test_object_id: The test object ID, obtained with create_test_object() function.
        :return: The ID of the started test run.
        """
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        test_run_label = "INSPIRE test run on {:s} with Conformance class {:s}".format(timestamp,
                                                                                       INSPIRE_TEST_SUITE_NAME)
        test_run_data = {
            "label": test_run_label,
            "executableTestSuiteIds": [test_suite_id],
            "arguments": {
                "files_to_test": ".*",
                "tests_to_execute": ".*"
            },
            "testObject": {
                "id": test_object_id
            }
        }
        start_run_url = INSPIRE_SERVICE_URL + "TestRuns"
        try:
            r = requests.post(start_run_url, json=test_run_data, timeout=INSPIRE_SERVER_TIMEOUT)
            r.raise_for_status()
            test_run = r.json()["EtfItemCollection"]["testRuns"]["TestRun"]
            return test_run["id"], "ok"
        except requests.exceptions.HTTPError as ex:
            return None, str(ex)
        except requests.exceptions.ConnectionError:
            return None, "Service not available."
        except requests.exceptions.Timeout:
            return None, "Connection timeout."
        except requests.exceptions.RequestException as ex:
            return None, repr(ex)
        except KeyError:
            return None, "Service API returned unexpected response."
        except Exception as ex:
            return None, repr(ex)

    @staticmethod
    def retrieve_test_result(test_run_id):
        """
        Polls the test run for a result.
        :param test_run_id: The test run ID, obtained with start_test_run
        :param test_object_id: The test object ID, obtained with create_test_object() function.
        :return: A tuple with test result status [PASSED, PASSED_MANUAL, FAILED or None] and message ["ok" or "error"]
        """

        run_url = INSPIRE_SERVICE_URL + "TestRuns/" + test_run_id
        progress_url = run_url + "/progress"
        json_report_url = run_url + ".json"

        total_seconds = 0
        try:
            # polling the service every 10 seconds for progress
            while True:
                time.sleep(INSPIRE_POLL_INTERVAL)
                total_seconds = total_seconds + INSPIRE_POLL_INTERVAL
                r = requests.get(progress_url, timeout=INSPIRE_SERVER_TIMEOUT)
                r.raise_for_status()
                progress = r.json()
                print("{0}/{1}".format(progress["val"], progress["max"]))
                if progress["val"] == progress["max"]:
                    break
                if total_seconds > INSPIRE_TEST_RUN_TIMEOUT:
                    return None, "Validation run has timed out after {:d} seconds.".format(total_seconds)

            # retrieving the status from the result json document
            time.sleep(INSPIRE_POLL_INTERVAL)
            r = requests.get(json_report_url, timeout=INSPIRE_SERVER_TIMEOUT)
            r.raise_for_status()
            test_result = r.json()["EtfItemCollection"]["testRuns"]["TestRun"]
            test_status = test_result["status"]
            return test_status, "ok"

        except requests.exceptions.HTTPError as ex:
            return None, str(ex)
        except requests.exceptions.ConnectionError:
            return None, "Service not available."
        except requests.exceptions.Timeout:
            return None, "Connection timeout."
        except requests.exceptions.RequestException as ex:
            return None, repr(ex)
        except KeyError:
            return None, "Service API returned unexpected response."
        except Exception as ex:
            return None, repr(ex)

    @staticmethod
    def download_test_result(test_run_id, attachment_filepath):
        """
        Downloads the html report, json report or log file of the test run.
        :param test_run_id: The test run ID, obtained with start_test_run
        :param test_object_id: The test object ID, obtained with create_test_object() function.
        :return: message ["ok" or "error"]
        """
        result_url = INSPIRE_SERVICE_URL + "TestRuns/" + test_run_id

        if attachment_filepath.name.endswith(".html"):
            attachment_url = result_url + ".html"
        elif attachment_filepath.name.endswith("txt"):
            attachment_url = result_url + "/log"
        elif attachment_filepath.name.endswith(".json"):
            attachment_url = result_url + ".json"
        else:
            raise ValueError("Attachment file must have .html, .txt or .json extension.")

        # Download and attach html report.
        try:
            r = requests.get(attachment_url, timeout=INSPIRE_SERVER_TIMEOUT)
            with open(str(attachment_filepath), "wb") as f:
                f.write(r.content)
            return "ok"
        except Exception as ex:
            return repr(ex)


def locate_metadata_file(layer_filepath):
    # XML metadata file can be LAYER.xml or LAYER.shp.xml or metadata/LAYER.xml or metadata/LAYER.shp.xml
    for xml_filepath in [layer_filepath.parent.joinpath("Metadata", layer_filepath.stem + ".xml"),
                         layer_filepath.parent.joinpath("metadata", layer_filepath.stem + ".xml"),
                         layer_filepath.parent.joinpath(layer_filepath.stem + ".xml")]:
        if xml_filepath.exists():
            return xml_filepath
    return None


def do_inspire_check(xml_filepath, export_prefix, output_dir, status, retry_no=0):

    # Step 1, Retrieve the predefined test suite from the service. The predefined test suite has a unique test suite ID.
    status.info("Using validator service {:s}.".format(INSPIRE_VALIDATOR_URL))
    test_suite_id, test_suite_message = InspireServiceClient.retrieve_test_suite_id()
    if test_suite_id is None:
        status.info("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, test_suite_message))
        # if the test_suite_id is unavailable, then the inspire service is probably not working as expected.
        return

    # Does the file contain GMD:MD_Metadata element?


    # Step 2, Upload xml file to the service. The service creates a temporary test object with a unique test object ID.
    status_code, test_object_id, test_object_message = InspireServiceClient.create_test_object(xml_filepath)
    if status_code == 400:
        status.info("Metadata file {:s} is not in INSPIRE XML format and cannot be validated:. ".format(test_object_message))
        return
    if test_object_id is None:
        status.info("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, test_object_message))
        return

    # Step 3, Create a new test run using the selected test suite and previously created test object.
    time.sleep(INSPIRE_POLL_INTERVAL)
    test_run_id, test_run_message = InspireServiceClient.start_test_run(test_suite_id, test_object_id)

    if test_run_id is None:
        status.info("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, test_run_message))
        return

    # Step 4, Retrieve result of the test run.
    result_status, result_message = InspireServiceClient.retrieve_test_result(test_run_id)
    if result_status is None:
        status.info("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, result_message))
        return


    # Step 5, Evaluate INSPIRE validation status.
    if result_status in ["PASSED", "PASSED_MANUAL"]:
        pass
    elif result_status == "FAILED":
        status.info(
            "Metadata of {:s} did not pass INSPIRE validation. See report for details.".format(xml_filepath.name))
    elif result_status == "UNDEFINED":
        # Ocassionally the test run ends with undefined status when executed for the first time.
        # In case of undefined status, retry uploading the xml file to the service and starting a new test run.
        if retry_no < INSPIRE_MAX_RETRIES:
            do_inspire_check(xml_filepath, export_prefix, output_dir, status, retry_no+1)
        else:
            status.info(
                "Metadata of {:s} could not be validated, validation service is busy.".format(xml_filepath.name))

    # Step 6, Download and add html report and log file attachments.
    html_filepath = output_dir.joinpath(export_prefix + "_report.html")
    html_status = InspireServiceClient.download_test_result(test_run_id, html_filepath)
    if html_filepath.is_file():
        status.add_attachment(html_filepath.name)
    else:
        status.info("NOTE: report {:s} is not available: {:s}".format(html_filepath.name, html_status))

    log_filepath = output_dir.joinpath(export_prefix + "_log.txt")
    log_status = InspireServiceClient.download_test_result(test_run_id, log_filepath)
    if log_filepath.is_file():
        status.add_attachment(log_filepath.name)
    else:
        status.info("NOTE: log file {:s} is not available: {:s}".format(log_filepath.name, log_status))
