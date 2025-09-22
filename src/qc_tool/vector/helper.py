#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import logging
import re
import time
from datetime import datetime
from math import ceil
from math import floor
from zipfile import ZipFile
import boto3
from pathlib import Path

import psycopg2
import psycopg2.errorcodes
import requests
from checksumdir import dirhash

from qc_tool.common import HASH_ALGORITHM
from qc_tool.common import FAILED_ITEMS_LIMIT

from qc_tool.common import CONFIG


INSPIRE_TEST_SUITE_NAME = "INSPIRE data sets and data set series interoperability metadata"
INSPIRE_SERVER_TIMEOUT = 60
INSPIRE_TEST_RUN_TIMEOUT = 360
INSPIRE_POLL_INTERVAL = 40
INSPIRE_MAX_RETRIES = 3
INSPIRE_SERVICE_STATUS_MAX_RETRIES = 10
INSPIRE_SERVICE_STATUS_RETRY_INTERVAL = 60
INSPIRE_SERVICE_LOCAL_PORT = 8080

PARTITION_MAX_VERTICES = 50000

NEIGHBOUR_LENGTH_TOLERANCE = 0.001  # tolerance for neighbour when two points are considered as the same point.


log = logging.getLogger(__name__)


def do_unzip(zip_filepath, unzip_dir, status):
    # The source zip file must have .zip extension.
    if not zip_filepath.name.lower().endswith(".zip"):
        status.aborted("Uploaded delivery {:s} has incorrect file format. Delivery must be a .zip file."
                       .format(zip_filepath.name))

    status.set_status_property("hash_files", [zip_filepath.name])
    unzip_dir.mkdir()

    # The source zip file must be a zip archive.
    try:
        with ZipFile(str(zip_filepath)) as zip_file:
            zip_file.extractall(path=str(unzip_dir))
    except Exception as ex:
        status.aborted("Error unzipping file {:s}, reason: {:s}".format(zip_filepath.name, str(ex)))
        return

    status.add_params({"unzip_dir": unzip_dir})

def do_s3_download(host, access_key, secret_key, bucketname, pattern, s3_local_dir, status):

    if not s3_local_dir.exists():
        s3_local_dir.mkdir()

    # Check the S3 storage connection, filter objects by naming pattern, download to s3_local_dir
    downloaded_filenames = []
    try:
        s3 = boto3.resource('s3', aws_access_key_id=access_key, aws_secret_access_key=secret_key, endpoint_url=host)
        bucket = s3.Bucket(bucketname)
        objects_filtered = list(bucket.objects.filter(Prefix=pattern))
        if len(objects_filtered) == 0:
            status.aborted("Error S3 download, the {:s} pattern doesn't match any object on the S3 storage.".format(pattern)) # jaky typ vyjimky??
            return
        for obj in objects_filtered:
            obj_name = Path(obj.key).name
            local_filepath = s3_local_dir.joinpath(obj_name)
            s3.Bucket(bucketname).download_file(obj.key, local_filepath)
            downloaded_filenames.append(obj_name)

        if downloaded_filenames:
            if not status.params.get("hash"):
                downloaded_files_hash = dirhash(s3_local_dir, HASH_ALGORITHM)
                status.set_status_property("hash", downloaded_files_hash)
                status.set_status_property("hash_files", downloaded_filenames)
    except Exception as ex:
        status.aborted("Error S3 download, reason: {:s}".format(str(ex)))
        return
    if not status.params.get("unzip_dir"):
        status.add_params({"unzip_dir": s3_local_dir})


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
def extract_aoi_code(layer_defs, layer_regexes, expected_aoi_codes, status, preserve_aoicode_case=False, compare_aoi_codes=True):
    layer_aoi_codes = []
    for layer_alias, layer_def in layer_defs.items():
        layer_name = layer_def["src_layer_name"]
        layer_regex = layer_regexes[layer_alias]
        if preserve_aoicode_case:
            mobj = re.match(layer_regex, layer_name, re.IGNORECASE)
        else:
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
        if compare_aoi_codes and aoi_code not in expected_aoi_codes:
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

# Extract EPSG code and compare it to pre-defined list.
def extract_epsg_code(layer_defs, layer_regexes, expected_epsg_codes, status, compare_epsg_codes=True):
    layer_epsg_codes = []
    for layer_alias, layer_def in layer_defs.items():
        layer_name = layer_def["src_layer_name"]
        layer_regex = layer_regexes[layer_alias]
        mobj = re.match(layer_regex, layer_name.lower())
        if mobj is None:
            status.aborted("Layer {:s} has illegal name: {:s}.".format(layer_alias, layer_name))
            continue
        try:
            epsg_code = mobj.group("epsg_code")
        except IndexError:
            status.aborted("Layer {:s} does not contain EPSG code.".format(layer_name))
            continue
        layer_epsg_codes.append(epsg_code)

        # Compare detected AOI code to pre-defined list.
        if compare_epsg_codes and epsg_code not in expected_epsg_codes:
            status.aborted("Layer {:s} has illegal EPSG code {:s}.".format(layer_name, epsg_code))
            continue

    # Check that AOI code could be detected.
    if len(set(layer_epsg_codes)) == 0:
        status.aborted("EPSG code could not be detected from any layer name.")
        return

    # If there are multiple layers, check that all layers have the same EPSG code.
    if len(set(layer_epsg_codes)) > 1:
        status.aborted("Layers do not have the same EPSG code. Detected EPSG codes: {:s}"
                       .format(",".join(list(layer_epsg_codes))))

    # Set aoi_code as a global parameter.
    return epsg_code


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
        for layer_info in self.layer_infos:
            layer_index += 1
            layer_alias = "layer_{:d}".format(layer_index)
            layer_info["layer_alias"] = layer_alias
            self.layer_defs[layer_alias] = layer_info

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
        layer_info["layer_alias"] = layer_alias

        # Add regex groups to layer info.
        layer_info["groups"] = regex.search(layer_info["src_layer_name"]).groupdict()

        # Add layer info to layer_defs.
        self.layer_defs[layer_alias] = layer_info

    def check_excessive_layers(self):
        if len(self.layer_infos) > 0:
            desc = ", ".join(info["src_layer_name"] for info in self.layer_infos)
            self.status.failed("There are excessive layers: {:s}.".format(desc))


class InspireServiceClient():
    """This class contains methods for communicating with the INSPIRE validator service API.
    """
    @staticmethod
    def is_local_validator_url(validator_url):
        # return s true if the url is e.g localhost:8080/validator/v2
        return str(INSPIRE_SERVICE_LOCAL_PORT) in validator_url

    @staticmethod
    def get_github_validator_version():
        github_url = "https://api.github.com/repos/INSPIRE-MIF/helpdesk-validator/releases/latest"
        try:
            resp_json = requests.get(github_url).json()
            git_tag = resp_json["tag_name"]
            # Remove the initial "v as in v2024.3 from the tag name"
            if git_tag.startswith("v"):
                git_tag = git_tag[1:]
            return git_tag.strip()
        except BaseException as e:
            return None

    def get_local_validator_version():
        version_textfile_path = Path("/etc/inspire-validator-version.txt")
        local_version = ""
        if version_textfile_path.exists():
            local_version = version_textfile_path.read_text()
            if local_version.startswith("v"):
                local_version = local_version[1:]
        return local_version.strip()

    @staticmethod
    def get_service_status():
        """
        Verifies that the INSPIRE service API is up and running by calling /validator/v2/status endpoint.
        :return: 200 (ok) if OK and up, 502 (service unavailable) if not up.
        """
        try:
            r = requests.get(CONFIG["inspire_service_url"] + "status", timeout=1)
            r.raise_for_status()
            return r.status_code
        except Exception as ex:
            return 502 # SERVICE UNAVAILABLE

    @staticmethod
    def retrieve_test_suite_id():
        """
        Retrieves the INSPIRE executable test suite ID from the INSPIRE service
        :return: (suite ID, "ok") if the suite ID is correctly returned or (None, ERROR_MESSAGE) in case of failure.
        """
        try:
            r = requests.get(CONFIG["inspire_service_url"] + "ExecutableTestSuites.json", timeout=INSPIRE_SERVER_TIMEOUT)
            r.raise_for_status()
            # The service should return a json object with a list of test suites.
            test_suites = r.json()["EtfItemCollection"]["executableTestSuites"]["ExecutableTestSuite"]

            inspire_test_suites = [t for t in test_suites if INSPIRE_TEST_SUITE_NAME in t["label"]]
            # The test suites should contain exactly one suite with label equal to INSPIRE_TEST_SUITE_NAME.
            if len(inspire_test_suites) == 0:
                raise ValueError("The validator service {:s} does not have any test suites named '{:s}'".format(
                    CONFIG["inspire_service_url"], INSPIRE_TEST_SUITE_NAME))
            if len(inspire_test_suites) > 1:
                raise ValueError("The validator service {:s} has more than one test suite named '{:s}'".format(
                    CONFIG["inspire_service_url"], INSPIRE_TEST_SUITE_NAME))

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
        xml_upload_url = CONFIG["inspire_service_url"] + "TestObjects?action=upload"

        try:
            with open(str(xml_filepath), "rb") as filehandle:
                xml_file_data = {"fileupload": (xml_filepath.name, filehandle)}

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
            return None, None, "Service not available (url: {:s}).".format(xml_upload_url)
        except requests.exceptions.Timeout:
            return None, None, "Connection timeout (url: {:s}).".format(xml_upload_url)
        except requests.exceptions.RequestException as ex:
            return None, None, repr(ex)
        except KeyError:
            return None, None, "Service API returned unexpected response (url: {:s}).".format(xml_upload_url)
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
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        start_run_url = CONFIG["inspire_service_url"] + "TestRuns"
        try:
            r = requests.post(start_run_url, json=test_run_data, timeout=INSPIRE_SERVER_TIMEOUT)
            r.raise_for_status()

            test_run = r.json()["EtfItemCollection"]["testRuns"]["TestRun"]
            return test_run["id"], "ok"
        except requests.exceptions.HTTPError as ex:
            return None, str(ex)
        except requests.exceptions.ConnectionError:
            return None, "Service not available (url: {:s}).".format(start_run_url)
        except requests.exceptions.Timeout:
            return None, "Connection timeout (url: {:s}).".format(start_run_url)
        except requests.exceptions.RequestException as ex:
            return None, repr(ex)
        except KeyError:
            return None, "Service API returned unexpected response (url: {:s}).".format(start_run_url)
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

        run_url = CONFIG["inspire_service_url"] + "TestRuns/" + test_run_id
        progress_url = run_url + "/progress"
        json_report_url = run_url + ".json"

        total_seconds = 0
        try:
            # polling the service every POLL_INTERVAL seconds for progress
            while True:
                time.sleep(INSPIRE_POLL_INTERVAL)
                total_seconds = total_seconds + INSPIRE_POLL_INTERVAL
                r = requests.get(progress_url, timeout=INSPIRE_SERVER_TIMEOUT)
                r.raise_for_status()
                progress = r.json()
                log.debug("{0}/{1}".format(progress["val"], progress["max"]))
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
            return None, "Service not available (url: {:s}).".format(run_url)
        except requests.exceptions.Timeout:
            return None, "Connection timeout (url: {:s}).".format(run_url)
        except requests.exceptions.RequestException as ex:
            return None, repr(ex)
        except KeyError:
            return None, "Service API returned unexpected response (url: {:s}).".format(run_url)
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
        result_url = CONFIG["inspire_service_url"] + "TestRuns/" + test_run_id

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
    # Step 0, check the service version and status. only proceed if the service is up.
    

    if InspireServiceClient.is_local_validator_url(CONFIG["inspire_service_url"]):
        status.info("Using built-in validator at {:s}.".format(CONFIG["inspire_service_url"]))
        local_validator_version = InspireServiceClient.get_local_validator_version()
        github_validator_version = InspireServiceClient.get_github_validator_version()
        if github_validator_version is None:
            status.info("Installed validator version: {:s}.".format(local_validator_version))
            status.info("QC TOOL was unable to check if installed version of INSPIRE validator is up-to-date!")
        elif str(local_validator_version) == str(github_validator_version):
            status.info("Installed validator version: {:s}.".format(local_validator_version))
        else:
            status.info("Installed validator version {:s} is not up-to date, Latest online version is {:s}.".format(
                local_validator_version, github_validator_version
            ))
    else:
         status.info("Using online validator service {:s}.".format(CONFIG["inspire_service_url"]))

    for status_check_retry_no in range(0, INSPIRE_SERVICE_STATUS_MAX_RETRIES):
        service_status = InspireServiceClient.get_service_status()
        if service_status == 200:
            break
        else:
            print(f"inspire service_status, retry {status_check_retry_no}, status={service_status}")
            time.sleep(INSPIRE_SERVICE_STATUS_RETRY_INTERVAL) # wait for 60 seconds until next retry.

    if service_status != 200:
        error_message = f'Service {CONFIG["inspire_service_url"]} has not responded after {status_check_retry_no} retries.'
        status.failed("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, error_message))
        return

    # Step 1, Retrieve the predefined test suite from the service. The predefined test suite has a unique test suite ID.
    test_suite_id, test_suite_message = InspireServiceClient.retrieve_test_suite_id()

    if test_suite_id is None:
        status.failed("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, test_suite_message))
        # if the test_suite_id is unavailable, then the inspire service is probably not working as expected.
        return

    # Does the file contain GMD:MD_Metadata element?

    # Step 2, Upload xml file to the service. The service creates a temporary test object with a unique test object ID.
    status_code, test_object_id, test_object_message = InspireServiceClient.create_test_object(xml_filepath)
    if status_code == 400:
        status.failed("Metadata file {:s} is not in INSPIRE XML format and cannot be validated:. ".format(test_object_message))
        return
    if test_object_id is None:
        status.failed("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, test_object_message))
        return

    # Step 3, Create a new test run using the selected test suite and previously created test object.
    time.sleep(INSPIRE_POLL_INTERVAL)
    test_run_id, test_run_message = InspireServiceClient.start_test_run(test_suite_id, test_object_id)

    if test_run_id is None:
        status.failed("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, test_run_message))
        return

    # Step 4, Retrieve result of the test run.
    result_status, result_message = InspireServiceClient.retrieve_test_result(test_run_id)
    if result_status is None:
        status.failed("Unable to validate metadata of {:s}: {:s}.".format(xml_filepath.name, result_message))
        return

    # Step 5, Evaluate INSPIRE validation status.
    if result_status in ["PASSED", "PASSED_MANUAL"]:
        pass
    elif result_status == "FAILED":
        status.failed(
            "Metadata of {:s} did not pass INSPIRE validation. See report for details.".format(xml_filepath.name))
    elif result_status in ["UNDEFINED"]:
        # Ocassionally the test run ends with undefined status when executed for the first time.
        # In case of undefined status, retry uploading the xml file to the service and starting a new test run.
        if retry_no < INSPIRE_MAX_RETRIES:
            do_inspire_check(xml_filepath, export_prefix, output_dir, status, retry_no+1)
        else:
            status.failed(
                "Metadata of {:s} could not be validated, validation service is busy.".format(xml_filepath.name))

    # Step 6, Download and add html report and log file attachments.
    html_filepath = output_dir.joinpath(export_prefix + "_report.html")
    html_status = InspireServiceClient.download_test_result(test_run_id, html_filepath)
    if html_filepath.is_file():
        status.add_attachment(html_filepath.name)
    else:
        status.failed("Report {:s} is not available: {:s}".format(html_filepath.name, html_status))

    log_filepath = output_dir.joinpath(export_prefix + "_log.txt")
    log_status = InspireServiceClient.download_test_result(test_run_id, log_filepath)
    if log_filepath.is_file():
        status.add_attachment(log_filepath.name)
    else:
        status.failed("Log file {:s} is not available: {:s}".format(log_filepath.name, log_status))


def table_exists(connection, table_name):
    sql = ("SELECT\n"
           "FROM information_schema.tables\n"
           "WHERE\n"
           " table_schema = current_schema()\n"
           " AND table_name = %s;")
    with connection.cursor() as cursor:
        cursor.execute(sql, [table_name])
        if cursor.rowcount == 0:
            return False
        if cursor.rowcount == 1:
            return True
        else:
            raise Exception("Found {:d} tables named {:s}.".format(cursor.rowcount, table_name))


def column_exists(connection, table_name, column_name):
    sql = ("SELECT\n"
           "FROM information_schema.columns\n"
           "WHERE\n"
           " table_schema = current_schema()\n"
           " AND table_name = %s\n"
           " AND column_name = %s;")
    with connection.cursor() as cursor:
        cursor.execute(sql, [table_name, column_name])
        if cursor.rowcount == 0:
            return False
        if cursor.rowcount == 1:
            return True
        else:
            raise Exception("Found {:d} columns named {:s} in table {:s}.".format(cursor.rowcount, column_name, table_name))


def extract_srid(connection, table):
    GEOM_COLUMN = "geom"
    with connection.cursor() as cursor:
        sql = ("SELECT Find_SRID(current_schema()::varchar, %s, %s);")
        cursor.execute(sql, [table, GEOM_COLUMN])
        srid, = cursor.fetchone()
    return srid


def create_pg_neighbours(connection, neighbour_table_name, pg_layer_name, pg_fid_name):
    sql_params = {"neighbour_table_name": neighbour_table_name,
                  "pg_layer_name": pg_layer_name,
                  "pg_fid_name": pg_fid_name}
    with connection.cursor() as cursor:
        sql = "DROP FUNCTION IF EXISTS neighbours;"
        cursor.execute(sql)
        sql = ("CREATE FUNCTION neighbours(ifid integer)\n"
               "RETURNS SETOF {pg_layer_name}\n"
               "PARALLEL SAFE\n"
               "STABLE\n"
               "LANGUAGE sql\n"
               "AS $$\n"
               " SELECT f.*\n"
               " FROM\n"
               "  {neighbour_table_name} AS n\n"
               "  INNER JOIN {pg_layer_name} AS f ON n.fidb = f.{pg_fid_name}\n"
               " WHERE n.fida = ifid;\n"
               "$$;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)


def create_pg_has_comment(connection):
    with connection.cursor() as cursor:
        sql = "DROP FUNCTION IF EXISTS has_comment;"
        cursor.execute(sql)
        sql = ("CREATE FUNCTION has_comment(comment varchar, allowed_comments varchar[])\n"
               "RETURNS boolean\n"
               "PARALLEL SAFE\n"
               "IMMUTABLE\n"
               "LANGUAGE sql\n"
               "AS $$\n"
               " SELECT\n"
               "  ARRAY(SELECT regexp_replace(regexp_split_to_table(comment, ';'),\n"
               "                              '^\\s*(\\S*)\\s*$',\n"
               "                              '\\1')::varchar)\n"
               "  && allowed_comments;\n"
               "$$;")
        cursor.execute(sql)


class PartitionedLayer():
    """The class generates partitioned layer.

    The whole area of the layer is partitioned into tiles where every tile has no more than maximum allowed vertices.
    If some feature crosses partition boundary, it gets splitted."""
    def __init__(self, connection, pg_layer_name, pg_fid_name, srid=None, max_vertices=PARTITION_MAX_VERTICES, grid_size=1.):
        self.connection = connection
        self.pg_layer_name = pg_layer_name
        self.pg_fid_name = pg_fid_name
        self.partition_table_name = "partition_{:s}".format(pg_layer_name)
        self.feature_table_name = "feature_{:s}".format(pg_layer_name)
        self.max_vertices = max_vertices
        self.grid_size = grid_size
        if srid is None:
            self.srid = extract_srid(connection, pg_layer_name)
        else:
            self.srid = srid

    def extract_extent(self):
        with self.connection.cursor() as cursor:
            sql_params = {"pg_layer_name": self.pg_layer_name}
            sql = ("SELECT\n"
                   " ST_XMin(ex), ST_YMin(ex), ST_XMax(ex), ST_YMax(ex)\n"
                   "FROM\n"
                   " (SELECT ST_Extent(geom) AS ex FROM {pg_layer_name}) sq;")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            xmin, ymin, xmax, ymax = cursor.fetchone()
        if xmin > xmax:
            xmin, xmax = xmax, xmin
        if ymin > ymax:
            ymin, ymax = ymax, ymin
        return xmin, ymin, xmax, ymax

    def expand_box(self, xmin, ymin, xmax, ymax):
        xmin = floor((xmin - self.grid_size) / self.grid_size) * self.grid_size
        ymin = floor((ymin - self.grid_size) / self.grid_size) * self.grid_size
        xmax = ceil((xmax + self.grid_size) / self.grid_size) * self.grid_size
        ymax = ceil((ymax + self.grid_size) / self.grid_size) * self.grid_size
        return xmin, ymin, xmax, ymax

    def _create_polygon_dump(self):
        with self.connection.cursor() as cursor:
            sql = "DROP FUNCTION IF EXISTS polygon_dump;"
            cursor.execute(sql)
            sql = ("CREATE FUNCTION polygon_dump(geom geometry)\n"
                   "RETURNS SETOF geometry\n"
                   "PARALLEL SAFE\n"
                   "IMMUTABLE\n"
                   "LANGUAGE sql\n"
                   "AS $$\n"
                   " SELECT geom\n"
                   " FROM (SELECT (ST_Dump(geom)).geom) AS tg\n"
                   " WHERE ST_Dimension(geom) >= 2;\n"
                   "$$;")
            cursor.execute(sql)

    def _create_partition_table(self):
        sql_params = {"partition_table_name": self.partition_table_name}
        with self.connection.cursor() as cursor:
            sql = ("CREATE TABLE {partition_table_name}\n"
                   " (partition_id SERIAL PRIMARY KEY,\n"
                   "  superpartition_id integer NULL DEFAULT NULL,\n"
                   "  num_vertices integer NULL DEFAULT NULL,\n"
                   "  geom geometry(Polygon, %s));")
            sql = sql.format(**sql_params)
            cursor.execute(sql, [self.srid])
            sql = ("CREATE INDEX {partition_table_name}_superpartition_id_idx ON {partition_table_name} (superpartition_id ASC NULLS LAST);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("CREATE INDEX {partition_table_name}_num_vertices_idx ON {partition_table_name} (num_vertices ASC NULLS FIRST);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("CREATE INDEX {partition_table_name}_geom_idx ON {partition_table_name} USING GIST (geom);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def _fill_initial_partition(self, xmin, ymin, xmax, ymax):
        sql_params = {"partition_table_name": self.partition_table_name}
        with self.connection.cursor() as cursor:
            sql = ("INSERT INTO {partition_table_name} (geom)\n"
                   "VALUES (ST_MakeEnvelope(%s, %s, %s, %s, %s))\n"
                   "RETURNING partition_id;")
            sql = sql.format(**sql_params)
            cursor.execute(sql, [xmin, ymin, xmax, ymax, self.srid])
            initial_partition_id, = cursor.fetchone()
        return initial_partition_id

    def _create_feature_table(self):
        sql_params = {"pg_layer_name": self.pg_layer_name,
                      "pg_fid_name": self.pg_fid_name,
                      "feature_table_name": self.feature_table_name}
        with self.connection.cursor() as cursor:
            # Create support table holding partitioned features.
            sql = ("CREATE TABLE {feature_table_name}\n"
                   " (fid integer NOT NULL,"
                   "  partition_id integer NOT NULL,"
                   "  geom geometry(Polygon, %s));")
            sql = sql.format(**sql_params)
            cursor.execute(sql, [self.srid])
            sql = ("CREATE INDEX {feature_table_name}_fid_idx ON {feature_table_name} (fid);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("CREATE INDEX {feature_table_name}_partition_id_idx ON {feature_table_name} (partition_id);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("CREATE INDEX {feature_table_name}_geom_idx ON {feature_table_name} USING GIST (geom);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def _fill_initial_features(self, initial_partition_id):
        sql_params = {"pg_layer_name": self.pg_layer_name,
                      "pg_fid_name": self.pg_fid_name,
                      "feature_table_name": self.feature_table_name}
        with self.connection.cursor() as cursor:
            # Copy original features from the layer.
            sql = ("INSERT INTO {feature_table_name} (fid, partition_id, geom)\n"
                   "SELECT {pg_fid_name}, %s, polygon_dump(geom)\n"
                   "FROM {pg_layer_name};")
            sql = sql.format(**sql_params)
            cursor.execute(sql, [initial_partition_id])

    def _update_npoints(self):
        sql_params = {"feature_table_name": self.feature_table_name,
                      "partition_table_name": self.partition_table_name}
        with self.connection.cursor() as cursor:
            # Update num_vertices in partitions.
            sql = ("UPDATE {partition_table_name} AS p\n"
                   "SET num_vertices = (SELECT sum(ST_NPoints(geom))\n"
                   "                    FROM {feature_table_name} AS f\n"
                   "                    WHERE f.partition_id = p.partition_id)\n"
                   "WHERE num_vertices IS NULL;")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            log.debug("{:d} subpartitions have got updated npoints.".format(cursor.rowcount))

    def _split_partitions(self):
        """Split partitions into subpartitions."""
        sql_params = {"partition_table_name": self.partition_table_name}
        with self.connection.cursor() as superpartition_cursor:
            # Select all partitions having high num_vertices.
            sql = ("SELECT\n"
                   " partition_id,\n"
                   " ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom)\n"
                   "FROM {partition_table_name}\n"
                   "WHERE num_vertices > %s;")
            sql = sql.format(**sql_params)
            superpartition_cursor.execute(sql, [self.max_vertices])
            if superpartition_cursor.rowcount == 0:
                return 0

            split_count = 0
            with self.connection.cursor() as subpartition_cursor:
                for superpartition_id, xmin, ymin, xmax, ymax in superpartition_cursor.fetchall():
                    # Prepare query template for creating subpartition.
                    sql = ("INSERT INTO {partition_table_name} (superpartition_id, geom)\n"
                           "VALUES (%s, ST_MakeEnvelope(%s, %s, %s, %s, %s));")
                    sql = sql.format(**sql_params)

                    # Compute centerlines for splitting superpartition.
                    xcenter = (xmin + xmax) / 2 // self.grid_size * self.grid_size
                    ycenter = (ymin + ymax) / 2 // self.grid_size * self.grid_size

                    # Split the superpartition by dividing the longer side.
                    if xcenter - xmin > ycenter - ymin:
                        # Reject splitting superpartition if the xsize gets smaller then grid size.
                        # Due to current splitting calculation, the xsize becomes zero in such case.
                        # Due to rounding, the left part of the split is always smaller then right part.
                        xsize = xcenter - xmin
                        if xsize < self.grid_size:
                            log.debug("Partitioning superpartition {:d} has been rejected, while the xsize {:f} of subpartition gets smaller then grid size {:f}.".format(superpartition_id, xsize, self.grid_size))
                            continue

                        # Split superpartition by vertical line.
                        subpartition_cursor.execute(sql, [superpartition_id, xmin, ymin, xcenter, ymax, self.srid])
                        subpartition_cursor.execute(sql, [superpartition_id, xcenter, ymin, xmax, ymax, self.srid])
                    else:
                        # Reject splitting superpartition if the ysize gets smaller then grid size.
                        # Due to current splitting calculation, the ysize becomes zero in such case.
                        # Due to rounding, the lower part of the split is always smaller then upper part.
                        ysize = ycenter - ymin
                        if ysize < self.grid_size:
                            log.debug("Partitioning superpartition {:d} has been rejected, while the ysize {:f} of subpartition gets smaller then grid size {:f}.".format(superpartition_id, ysize, self.grid_size))
                            continue

                        # Split superpartition by horizontal line.
                        subpartition_cursor.execute(sql, [superpartition_id, xmin, ymin, xmax, ycenter, self.srid])
                        subpartition_cursor.execute(sql, [superpartition_id, xmin, ycenter, xmax, ymax, self.srid])
                    split_count += 1
            log.debug("{:d} superpartitions have been splitted into subpartitions.".format(split_count))
            return split_count

    def _fill_subpartitions(self):
        """Insert features into subpartitions."""
        with self.connection.cursor() as cursor:
            sql_params = {"feature_table_name": self.feature_table_name,
                          "partition_table_name": self.partition_table_name}
            # Move features from superpartition into covering subpartition.
            sql = ("UPDATE {feature_table_name} AS f\n"
                   "SET partition_id = p.partition_id\n"
                   "FROM {partition_table_name} AS p\n"
                   "WHERE\n"
                   " p.num_vertices IS NULL\n"
                   " AND f.partition_id = p.superpartition_id\n"
                   " AND f.geom @ p.geom;")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            log.debug("{:d} features have been moved into subpartitions.".format(cursor.rowcount))

            # Split remaining features into both subpartitions.
            sql = ("INSERT INTO {feature_table_name} (fid, partition_id, geom)\n"
                   "SELECT\n"
                   " f.fid,\n"
                   " p.partition_id,\n"
                   " polygon_dump(ST_Intersection(f.geom, p.geom))\n"
                   "FROM\n"
                   " {feature_table_name} AS f\n"
                   " INNER JOIN {partition_table_name} AS p ON f.partition_id = p.superpartition_id\n"
                   "WHERE p.num_vertices IS NULL;")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            log.debug("{:d} features have been splitted into subpartitions.".format(cursor.rowcount))

    def _delete_superitems(self):
        sql_params = {"feature_table_name": self.feature_table_name,
                      "partition_table_name": self.partition_table_name}
        with self.connection.cursor() as cursor:
            # Delete features of superpartitions.
            sql = ("DELETE FROM {feature_table_name} AS ft\n"
                   "WHERE\n"
                   " EXISTS (SELECT\n"
                   "         FROM {partition_table_name} AS pt\n"
                   "         WHERE ft.partition_id = pt.superpartition_id);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            log.debug("{:d} features have been deleted from superpartitions.".format(cursor.rowcount))

            # Vacuum the feature table.
            #
            # It is needed to vacuum analyze the table periodically.
            # Otherwise the consecutive queries fall extremely slow,
            # e.g. updating npoints takes 20 minutes without vacuum and 5 seconds with.
            sql = "VACUUM ANALYZE {feature_table_name};"
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            log.debug("Feature table {:s} has been vacuumed.".format(self.feature_table_name))

            # Delete all superpartitions.
            sql = ("DELETE FROM {partition_table_name} AS superpt\n"
                   "WHERE\n"
                   " EXISTS (SELECT\n"
                   "         FROM {partition_table_name} AS subpt\n"
                   "         WHERE superpt.partition_id = subpt.superpartition_id);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            log.debug("{:d} superpartitions have been deleted.".format(cursor.rowcount))

            # Vacuum the partition table.
            #
            # See the comment above about vacuuming the feature table.
            sql = "VACUUM ANALYZE {partition_table_name};"
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            log.debug("Partition table {:s} has been vacuumed.".format(self.partition_table_name))

    def make(self):
        if self.is_made():
            log.info("Layer {:s} has already been partitioned.".format(self.pg_layer_name))
        else:
            log.debug("Started partitioning layer {:s}.".format(self.pg_layer_name))
            self._create_polygon_dump()
            xmin, ymin, xmax, ymax = self.extract_extent()
            xmin, ymin, xmax, ymax = self.expand_box(xmin, ymin, xmax, ymax)
            self._create_partition_table()
            initial_partition_id = self._fill_initial_partition(xmin, ymin, xmax, ymax)
            self._create_feature_table()
            self._fill_initial_features(initial_partition_id)
            self._update_npoints()
            while True:
                split_count = self._split_partitions()
                if split_count == 0:
                    break
                self._fill_subpartitions()
                self._delete_superitems()
                self._update_npoints()
            log.info("Layer {:s} has just been partitioned.".format(self.pg_layer_name))

    def is_made(self):
        return table_exists(self.connection, self.partition_table_name)


class NeighbourTable():
    def __init__(self, partitioned_layer):
        self.partitioned_layer = partitioned_layer
        self.neighbour_table_name = "neighbour_{:s}".format(partitioned_layer.pg_layer_name)
        self.neighbour_length_tolerance = NEIGHBOUR_LENGTH_TOLERANCE

    @property
    def connection(self):
        return self.partitioned_layer.connection

    def _create_neighbour_table(self):
        sql_params = {"neighbour_table_name": self.neighbour_table_name}
        with self.connection.cursor() as cursor:
            sql = ("CREATE TABLE {neighbour_table_name}\n"
                   " (fida integer NOT NULL,\n"
                   "  fidb integer NOT NULL,\n"
                   "  dim smallint NOT NULL,\n"
                   " PRIMARY KEY (fida, fidb));")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("CREATE INDEX {neighbour_table_name}_fida_idx ON {neighbour_table_name} (fida);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("CREATE INDEX {neighbour_table_name}_fidb_idx ON {neighbour_table_name} (fidb);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def _fill(self):
        sql_params = {"feature_table_name": self.partitioned_layer.feature_table_name,
                      "neighbour_table_name": self.neighbour_table_name,
                      "neighbour_length_tolerance": self.neighbour_length_tolerance}
        with self.connection.cursor() as cursor:
            # Insert neighbouring pairs.
            sql = ("WITH\n"
                   " intersections AS\n"
                   "  (SELECT\n"
                   "    ta.fid AS fida,\n"
                   "    tb.fid AS fidb,\n"
                   "    ST_Intersection(ta.geom, tb.geom) AS geom\n"
                   "   FROM {feature_table_name} AS ta\n"
                   "   INNER JOIN {feature_table_name} AS tb ON ta.geom && tb.geom\n"
                   "   WHERE\n"
                   "    ta.fid < tb.fid)\n"
                   "INSERT INTO {neighbour_table_name} (fida, fidb, dim)\n"
                   "SELECT fida, fidb, max(ST_Dimension(geom)) AS dim\n"
                   "FROM intersections\n"
                   "WHERE NOT ST_IsEmpty(geom)\n"
                   "GROUP BY fida, fidb\n"
                   "HAVING max(ST_Dimension(geom)) >= 1 AND max(ST_Length(geom)) > {neighbour_length_tolerance};")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # Insert inverted pairs.
            sql = ("INSERT INTO {neighbour_table_name} (fida, fidb, dim)\n"
                   "SELECT fidb, fida, dim\n"
                   "FROM {neighbour_table_name};")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def make(self):
        if self.is_made():
            log.info("Suport table of neighbours {:s} has already been created.".format(self.neighbour_table_name))
        else:
            log.debug("Starting creating support table of neighbours {:s}.".format(self.neighbour_table_name))
            self.partitioned_layer.make()
            self._create_neighbour_table()
            self._fill()
            log.info("Support table of neighbours {:s} has just been created.".format(self.neighbour_table_name))

    def is_made(self):
        return table_exists(self.connection, self.neighbour_table_name)


class _MetaTable():
    """Meta table is support table giving additional properties to features.

    Meta table is created and filled by other classes, e.g. MarginalProperty.
    Meta table is used by joining layer table with with 1:1."""
    def __init__(self, connection, pg_layer_name, pg_fid_name):
        self.connection = connection
        self.pg_layer_name = pg_layer_name
        self.pg_fid_name = pg_fid_name
        self.meta_table_name = "meta_{:s}".format(pg_layer_name)

    def _create_meta_table(self):
        sql_params = {"meta_table_name": self.meta_table_name,
                      "pg_layer_name": self.pg_layer_name,
                      "pg_fid_name": self.pg_fid_name}
        with self.connection.cursor() as cursor:
            sql = ("CREATE TABLE {meta_table_name}\n"
                   " (fid integer PRIMARY KEY);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("INSERT INTO {meta_table_name} (fid)\n"
                   "SELECT {pg_fid_name} FROM {pg_layer_name} ORDER BY {pg_fid_name};")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def make(self):
        if self.is_made():
            log.info("Support meta table {:s} has already been created.".format(self.meta_table_name))
        else:
            self._create_meta_table()
            log.info("Support meta table {:s} has just been created.".format(self.meta_table_name))

    def is_made(self):
        return table_exists(self.connection, self.meta_table_name)


class _InteriorTable():
    def __init__(self, partitioned_layer):
        self.partitioned_layer = partitioned_layer
        self.interior_table_name = "interior_{:s}".format(self.partitioned_layer.pg_layer_name)

    @property
    def connection(self):
        return self.partitioned_layer.connection

    def _create_interior_table(self):
        sql_params = {"srid": self.partitioned_layer.srid,
                      "interior_table": self.interior_table_name}
        with self.connection.cursor() as cursor:
            sql = ("CREATE TABLE {interior_table}\n"
                   " (partition_id integer PRIMARY KEY,\n"
                   "  geom geometry(MultiPolygon, {srid}));")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("CREATE INDEX {interior_table}_geom_idx ON {interior_table} USING GIST (geom);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def _fill(self):
        sql_params = {"partition_table": self.partitioned_layer.partition_table_name,
                      "feature_table": self.partitioned_layer.feature_table_name,
                      "interior_table": self.interior_table_name}
        with self.connection.cursor() as cursor:
            sql = ("INSERT INTO {interior_table}\n"
                   "SELECT pt.partition_id, ST_Multi(ST_Union(ft.geom))\n"
                   "FROM\n"
                   " {partition_table} AS pt\n"
                   " INNER JOIN {feature_table} AS ft ON pt.partition_id = ft.partition_id\n"
                   "GROUP BY pt.partition_id;")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def make(self):
        if self.is_made():
            log.info("Interior table for the layer {:s} has already been created.".format(self.partitioned_layer.pg_layer_name))
        else:
            log.info("Started creating interior table for the layer {:s}.".format(self.partitioned_layer.pg_layer_name))
            self.partitioned_layer.make()
            self._create_interior_table()
            self._fill()
            log.info("Interior table for the layer {:s} has just been created.".format(self.partitioned_layer.pg_layer_name))

    def is_made(self):
        return table_exists(self.connection, self.interior_table_name)


class _ExteriorTable():
    def __init__(self, interior_table):
        self.interior_table = interior_table
        self.exterior_table_name = "exterior_{:s}".format(self.partitioned_layer.pg_layer_name)

    @property
    def partitioned_layer(self):
        return self.interior_table.partitioned_layer

    @property
    def connection(self):
        return self.partitioned_layer.connection

    def _create_exterior_table(self):
        sql_params = {"srid": self.partitioned_layer.srid,
                      "exterior_table": self.exterior_table_name}
        with self.connection.cursor() as cursor:
            sql = ("CREATE TABLE {exterior_table} (partition_id integer PRIMARY KEY,\n"
                                                 " geom geometry(MultiPolygon, {srid}));")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            sql = ("CREATE INDEX {exterior_table}_geom_idx ON {exterior_table} USING GIST (geom);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def _fill(self):
        sql_params = {"partition_table": self.partitioned_layer.partition_table_name,
                      "interior_table": self.interior_table.interior_table_name,
                      "exterior_table": self.exterior_table_name}
        with self.connection.cursor() as cursor:
            sql = ("INSERT INTO {exterior_table} (partition_id, geom)\n"
                   "SELECT\n"
                   " partition_id,\n"
                   " ST_Multi(geom)\n"
                   "FROM\n"
                   " (SELECT\n"
                   "   pt.partition_id AS partition_id,\n"
                   "   COALESCE(ST_Difference(pt.geom, it.geom), pt.geom) AS geom\n"
                   "  FROM\n"
                   "   {partition_table} AS pt\n"
                   "   LEFT JOIN {interior_table} AS it ON pt.partition_id = it.partition_id\n"
                   " ) AS dt\n"
                   "WHERE\n"
                   " NOT ST_IsEmpty(geom);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def make(self):
        if self.is_made():
            log.info("Exterior table for the layer {:s} has already been created.".format(self.partitioned_layer.pg_layer_name))
        else:
            log.info("Started creating exterior table for the layer {:s}.".format(self.partitioned_layer.pg_layer_name))
            self.interior_table.make()
            self._create_exterior_table()
            self._fill()
            log.info("Exterior table for the layer {:s} has just been created.".format(self.partitioned_layer.pg_layer_name))

    def is_made(self):
        return table_exists(self.connection, self.exterior_table_name)


class MarginalProperty():
    def __init__(self, partitioned_layer):
        self.partitioned_layer = partitioned_layer
        interior_table = _InteriorTable(partitioned_layer)
        self.exterior_table = _ExteriorTable(interior_table)
        self.meta_table = _MetaTable(partitioned_layer.connection,
                                     partitioned_layer.pg_layer_name,
                                     partitioned_layer.pg_fid_name)

    @property
    def connection(self):
        return self.partitioned_layer.connection

    def _prepare_meta_table(self):
        sql_params = {"meta_table": self.meta_table.meta_table_name}
        sql = ("ALTER TABLE {meta_table}\n"
               "ADD COLUMN is_marginal boolean DEFAULT NULL;")
        sql = sql.format(**sql_params)
        with self.connection.cursor() as cursor:
            cursor.execute(sql)

    def _fill(self):
        sql_params = {"meta_table": self.meta_table.meta_table_name,
                      "feature_table": self.partitioned_layer.feature_table_name,
                      "exterior_table": self.exterior_table.exterior_table_name}
        with self.connection.cursor() as cursor:
            sql = ("UPDATE {meta_table} AS meta\n"
                "SET is_marginal = EXISTS (\n"
                "    SELECT 1\n"
                "    FROM {feature_table} AS f\n"
                "    INNER JOIN {exterior_table} AS e ON f.geom && e.geom\n"
                "    WHERE f.fid = meta.fid\n"
                "    AND ST_Dimension(ST_Intersection(f.geom, e.geom)) >= 1);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def make(self):
        if self.is_made():
            log.info("Marginal property for the layer {:s} has already been created.".format(self.partitioned_layer.pg_layer_name))
        else:
            log.info("Started creating marginal property for the layer {:s}.".format(self.partitioned_layer.pg_layer_name))
            self.exterior_table.make()
            self.meta_table.make()
            self._prepare_meta_table()
            self._fill()
            log.info("Marginal property for the layer {:s} has just been created.".format(self.partitioned_layer.pg_layer_name))

    def is_made(self):
        return column_exists(self.connection, self.meta_table.meta_table_name, "is_marginal")


class ComplexChangeProperty():
    def __init__(self, neighbour_table, initial_code_column_name, final_code_column_name, area_column_name):
        self.neighbour_table = neighbour_table
        self.initial_code_column_name = initial_code_column_name
        self.final_code_column_name = final_code_column_name
        self.area_column_name = area_column_name
        self.meta_table = _MetaTable(neighbour_table.connection,
                                     self.partitioned_layer.pg_layer_name,
                                     self.partitioned_layer.pg_fid_name)

    @property
    def partitioned_layer(self):
        return self.neighbour_table.partitioned_layer

    @property
    def connection(self):
        return self.neighbour_table.connection

    def _prepare_meta_table(self):
        sql_params = {"meta_table_name": self.meta_table.meta_table_name}
        sql = ("ALTER TABLE {meta_table_name}\n"
               "  ADD COLUMN cc_id_initial integer DEFAULT NULL,\n"
               "  ADD COLUMN cc_id_final integer DEFAULT NULL,\n"
               "  ADD COLUMN cc_area real DEFAULT NULL;")
        sql = sql.format(**sql_params)
        with self.connection.cursor() as cursor:
            cursor.execute(sql)

    def _fill_cluster(self, cc_id_column_name, code_column_name):
        # Complex change is a cluster consisting of neighbouring features having the same code.
        # For the purpose of related algorithms every cluster is identified by the smallest fid
        # of its member feature.

        # Prepare sql params.
        sql_params = {"neighbour_table_name": self.neighbour_table.neighbour_table_name,
                      "meta_table_name": self.meta_table.meta_table_name,
                      "pg_layer_name": self.partitioned_layer.pg_layer_name,
                      "pg_fid_name": self.partitioned_layer.pg_fid_name,
                      "initial_code_column_name": self.initial_code_column_name,
                      "final_code_column_name": self.final_code_column_name,
                      "cc_id_column_name": cc_id_column_name,
                      "code_column_name": code_column_name}

        # Pair every feature with the smallest fid of its neighbours.
        # Apply filter to members of complex change.
        # Order the result by fid which is important for the next step.
        sql = ("SELECT layer.{pg_fid_name}, min(other.{pg_fid_name}) AS nfid\n"
               " FROM\n"
               "  {pg_layer_name} AS layer\n"
               "  INNER JOIN {neighbour_table_name} AS nb ON layer.{pg_fid_name} = nb.fida\n"
               "  INNER JOIN {pg_layer_name} AS other ON nb.fidb = other.{pg_fid_name}\n"
               " WHERE\n"
               "  layer.{code_column_name} = other.{code_column_name}\n"
               "  AND layer.{initial_code_column_name} != layer.{final_code_column_name}"
               "  AND other.{initial_code_column_name} != other.{final_code_column_name}"
               " GROUP BY layer.{pg_fid_name}\n"
               " ORDER BY layer.{pg_fid_name};")
        sql = sql.format(**sql_params)
        with self.connection.cursor() as cursor:
            cursor.execute(sql)

            # Assign cluster ids to features.
            # For every feature find the root feature.
            # Root feature is cluster member with the smallest fid.
            # As the features are sorted by fid,
            # and the features are registered sequentially,
            # it is enough for every feature being just registered
            # to take cluster fid from its already registered neighbour.
            fid_cc_idx = {}
            for (fid, nfid) in cursor.fetchall():
                if fid <= nfid:
                    fid_cc_idx[fid] = fid
                else:
                    fid_cc_idx[fid] = fid_cc_idx[nfid]

        # Dump clusters.
        with self.connection.cursor() as cursor:
            for fid, cc_id in fid_cc_idx.items():
                sql = "UPDATE {meta_table_name} SET {cc_id_column_name} = %s WHERE fid = %s;"
                sql = sql.format(**sql_params)
                cursor.execute(sql, [cc_id, fid])

    def _fill_area(self, cc_id_column_name):
        sql_params = {"meta_table_name": self.meta_table.meta_table_name,
                      "pg_layer_name": self.partitioned_layer.pg_layer_name,
                      "pg_fid_name": self.partitioned_layer.pg_fid_name,
                      "cc_id_column_name": cc_id_column_name,
                      "area_column_name": self.area_column_name}
        sql = ("UPDATE {meta_table_name} AS meta\n"
               " SET cc_area = cca.cc_area\n"
               " FROM\n"
               "  (SELECT meta.{cc_id_column_name} AS cc_id, sum(layer.{area_column_name}) AS cc_area\n"
               "    FROM {meta_table_name} as meta\n"
               "     INNER JOIN {pg_layer_name} AS layer ON meta.fid = layer.{pg_fid_name}\n"
               "    WHERE meta.{cc_id_column_name} IS NOT NULL\n"
               "    GROUP BY meta.{cc_id_column_name}) AS cca\n"
               " WHERE\n"
               "  meta.{cc_id_column_name} = cca.cc_id\n"
               "  AND (meta.cc_area IS NULL OR meta.cc_area < cca.cc_area);")
        sql = sql.format(**sql_params)
        with self.connection.cursor() as cursor:
            cursor.execute(sql)

    def make(self):
        if self.is_made():
            log.info("Complex change properties for the layer {:s} have already been created.".format(self.partitioned_layer.pg_layer_name))
        else:
            log.info("Started creating complex change properties for the layer {:s}.".format(self.partitioned_layer.pg_layer_name))
            self.neighbour_table.make()
            self.meta_table.make()
            self._prepare_meta_table()

            # Fill clusters for initial year and for final year.
            self._fill_cluster("cc_id_initial", self.initial_code_column_name)
            self._fill_cluster("cc_id_final", self.final_code_column_name)

            # Fill complex change area by greater of initial year and final year.
            self._fill_area("cc_id_initial")
            self._fill_area("cc_id_final")
            log.info("Complex change properties for the layer {:s} has just been created.".format(self.partitioned_layer.pg_layer_name))

    def is_made(self):
        return column_exists(self.connection, self.meta_table.meta_table_name, "cc_area")


class GapTable():
    def __init__(self, partitioned_layer, boundary_layer_name, du_column_name):
        self.partitioned_layer = partitioned_layer
        self.interior_table = _InteriorTable(partitioned_layer)
        self.boundary_layer_name = boundary_layer_name
        self.du_column_name = du_column_name
        self.gap_table_name = "gap_{:s}".format(partitioned_layer.pg_layer_name)

    @property
    def connection(self):
        return self.interior_table.partitioned_layer.connection

    def _create_split_geom(self):
        with self.connection.cursor() as cursor:
            sql = "DROP FUNCTION IF EXISTS split_geom;"
            cursor.execute(sql)
            sql = ("CREATE FUNCTION split_geom(geom geometry, grid_size float)\n"
                   "RETURNS SETOF geometry\n"
                   "PARALLEL SAFE\n"
                   "IMMUTABLE\n"
                   "LANGUAGE plpgsql\n"
                   "AS $$\n"
                   "DECLARE\n"
                   " xmin float;\n"
                   " xmax float;\n"
                   " ymin float;\n"
                   " ymax float;\n"
                   " xcenter float;\n"
                   " ycenter float;\n"
                   "BEGIN\n"
                   " xmin := least(ST_XMin(geom), ST_XMax(geom));\n"
                   " xmax := greatest(ST_XMin(geom), ST_XMax(geom));\n"
                   " ymin := least(ST_YMin(geom), ST_YMax(geom));\n"
                   " ymax := greatest(ST_YMin(geom), ST_YMax(geom));\n"
                   " xmin := floor(xmin / grid_size) * grid_size;\n"
                   " xmax := ceil(xmax / grid_size) * grid_size;\n"
                   " ymin := floor(ymin / grid_size) * grid_size;\n"
                   " ymax := ceil(ymax / grid_size) * grid_size;\n"
                   " IF xmax - xmin >= ymax - ymin\n"
                   " THEN\n"
                   "  xcenter := floor((xmin + xmax) / 2 / grid_size) * grid_size;\n"
                   "  IF xcenter - xmin >= grid_size\n"
                   "  THEN\n"
                   "   RETURN QUERY SELECT polygon_dump(ST_Intersection(ST_MakeEnvelope(xmin, ymin, xcenter, ymax, ST_SRID(geom)), geom));\n"
                   "   RETURN QUERY SELECT polygon_dump(ST_Intersection(ST_MakeEnvelope(xcenter, ymin, xmax, ymax, ST_SRID(geom)), geom));\n"
                   "  END IF;\n"
                   " ELSE\n"
                   "  ycenter := floor((ymin + ymax) / 2 / grid_size) * grid_size;\n"
                   "  IF ycenter - ymin >= grid_size\n"
                   "  THEN\n"
                   "   RETURN QUERY SELECT polygon_dump(ST_Intersection(ST_MakeEnvelope(xmin, ymin, xmax, ycenter, ST_SRID(geom)), geom));\n"
                   "   RETURN QUERY SELECT polygon_dump(ST_Intersection(ST_MakeEnvelope(xmin, ycenter, xmax, ymax, ST_SRID(geom)), geom));\n"
                   "  END IF;\n"
                   " END IF;\n"
                   " RETURN;\n"
                   "END;\n"
                   "$$;")
            cursor.execute(sql)

    def _create_gap_table(self):
        sql_params = {"gap_table": self.gap_table_name,
                      "srid": self.interior_table.partitioned_layer.srid}
        with self.connection.cursor() as cursor:
            sql = ("CREATE TABLE {gap_table}\n"
                   " (fid SERIAL PRIMARY KEY,\n"
                   "  geom geometry(Polygon, {srid}));")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def _fill_initial_features(self):
        sql_params = {"gap_table": self.gap_table_name,
                      "boundary_table": self.boundary_layer_name}
        if self.du_column_name is None:
            sql = ("INSERT INTO {gap_table} (geom)\n"
                   "SELECT polygon_dump(geom)\n"
                   "FROM {boundary_table};")
        else:
            sql_params.update({"du_column": self.du_column_name,
                               "layer_table": self.partitioned_layer.pg_layer_name})
            sql = ("INSERT INTO {gap_table} (geom)\n"
                   "SELECT polygon_dump(bt.geom)\n"
                   "FROM {boundary_table} AS bt\n"
                   "INNER JOIN (SELECT DISTINCT {du_column} FROM {layer_table}) AS dut ON bt.{du_column} = dut.{du_column};")
        with self.connection.cursor() as cursor:
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def _split_features(self):
        """Splits gap features having too many vertices."""
        sql_params = {"gap_table": self.gap_table_name}
        sql_execute_params = {"grid_size": self.partitioned_layer.grid_size,
                              "max_vertices": self.partitioned_layer.max_vertices}
        with self.connection.cursor() as cursor:
            sql = ("WITH\n"
                   " sel AS (SELECT fid AS orig_fid, split_geom(geom, %(grid_size)s) AS new_geom\n"
                   "         FROM {gap_table}\n"
                   "         WHERE ST_NPoints(geom) > %(max_vertices)s),\n"
                   " ins AS (INSERT INTO {gap_table} (geom)\n"
                   "         SELECT new_geom\n"
                   "         FROM sel)\n"
                   "DELETE FROM {gap_table}\n"
                   "WHERE fid IN (SELECT orig_fid FROM sel);")
            sql = sql.format(**sql_params)
            cursor.execute(sql, sql_execute_params)
            return cursor.rowcount

    def _subtract_partition(self, partition_id):
        """Subtracts interior of the partition from the gap table."""
        sql_params = {"gap_table": self.gap_table_name,
                      "interior_table": self.interior_table.interior_table_name}
        sql_execute_params = {"partition_id": partition_id}
        with self.connection.cursor() as cursor:

            sql = ("WITH\n"
                   " par AS (SELECT geom\n"
                   "         FROM {interior_table}\n"
                   "         WHERE partition_id = %(partition_id)s),\n"
                   " sub AS (SELECT\n"
                   "          gt.fid AS orig_fid,\n"
                   "          ST_Difference(ST_Buffer(gt.geom, 0), ST_Buffer(par.geom, 0)) AS sgeom\n"
                   "         FROM\n"
                   "          {gap_table} AS gt\n"
                   "          INNER JOIN par ON gt.geom && par.geom),\n"
                   " ins AS (INSERT INTO {gap_table} (geom)\n"
                   "         SELECT polygon_dump(sgeom)\n"
                   "         FROM sub)\n"
                   "DELETE FROM {gap_table}\n"
                   "WHERE fid IN (SELECT orig_fid FROM sub);")

            # more complex sql, to handle exceptional cases of invalid geometries introduced by partitioning.
            sql = """
WITH
 par AS (
   SELECT ST_MakeValid(ST_SnapToGrid(geom, 0.000001)) AS geom
   FROM {interior_table}
   WHERE partition_id = %(partition_id)s
 ),
 gt_valid AS (
   SELECT fid, ST_MakeValid(ST_SnapToGrid(geom, 0.000001)) AS geom
   FROM {gap_table}
   WHERE ST_IsValid(geom) OR geom IS NOT NULL
 ),
 sub AS (
   SELECT
     gt_valid.fid AS orig_fid,
     ST_CollectionExtract(
       ST_MakeValid(
         ST_Difference(gt_valid.geom, par.geom)
       ),
       3
     ) AS sgeom
   FROM gt_valid
   INNER JOIN par ON gt_valid.geom && par.geom
   WHERE NOT ST_IsEmpty(gt_valid.geom)
 ),
 ins AS (
   INSERT INTO {gap_table} (geom)
   SELECT polygon_dump(sgeom)
   FROM sub
   WHERE NOT ST_IsEmpty(sgeom)
 )
DELETE FROM {gap_table}
WHERE fid IN (SELECT orig_fid FROM sub);
"""
            
            sql = sql.format(**sql_params)
            cursor.execute(sql, sql_execute_params)
            return cursor.rowcount

    def _subtract_all_partitions(self):
        sql_params = {"partition_table": self.partitioned_layer.partition_table_name,
                      "gap_table": self.gap_table_name}
        with self.connection.cursor() as cursor:
            sql = "SELECT partition_id FROM {partition_table} ORDER BY partition_id;"
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            for partition_id in cursor.fetchall():
                while True:
                    split_count = self._split_features()
                    print("splitcount", split_count)
                    if split_count <= 0:
                        break
                self._subtract_partition(partition_id)
            sql = "VACUUM ANALYZE {gap_table};"
            sql = sql.format(**sql_params)
            cursor.execute(sql)

    def make(self):
        if self.is_made():
            log.info("Gap table for the layer {:s} have already been created.".format(self.partitioned_layer.pg_layer_name))
        else:
            log.info("Started creating gap table for the layer {:s}.".format(self.partitioned_layer.pg_layer_name))
            self.partitioned_layer.make()
            self.interior_table.make()
            self._create_split_geom()
            self._create_gap_table()
            self._fill_initial_features()
            self._subtract_all_partitions()
            log.info("Gap table for the layer {:s} has just been created.".format(self.partitioned_layer.pg_layer_name))

    def is_made(self):
        return table_exists(self.connection, self.gap_table_name)
