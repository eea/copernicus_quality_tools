"""Shared INSPIRE metadata validation integration for QC worker checks.

Keep transport concerns independent of vector/raster algorithms and frontend
models. Compatibility exports remain available from vector.helper.
"""

import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests

from qc_tool.common import CONFIG


INSPIRE_TEST_SUITE_NAME = "INSPIRE data sets and data set series interoperability metadata"
INSPIRE_SERVER_TIMEOUT = 60
INSPIRE_VERSION_TIMEOUT = 5
INSPIRE_TEST_RUN_TIMEOUT = 360
INSPIRE_POLL_INTERVAL = 5
INSPIRE_MAX_RETRIES = 3
INSPIRE_SERVICE_STATUS_MAX_RETRIES = 10
INSPIRE_SERVICE_STATUS_RETRY_INTERVAL = 60
INSPIRE_SERVICE_LOCAL_PORT = 8080


class _InspireDeadlineExceeded(Exception):
    pass


log = logging.getLogger(__name__)


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
            resp_json = requests.get(github_url, timeout=INSPIRE_VERSION_TIMEOUT).json()
            git_tag = resp_json["tag_name"]
            # Remove the initial "v as in v2024.3 from the tag name"
            if git_tag.startswith("v"):
                git_tag = git_tag[1:]
            return git_tag.strip()
        except Exception:
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
    def _poll_response(url, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _InspireDeadlineExceeded
        time.sleep(min(INSPIRE_POLL_INTERVAL, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _InspireDeadlineExceeded
        response = requests.get(url, timeout=min(INSPIRE_SERVER_TIMEOUT, remaining))
        if time.monotonic() >= deadline:
            raise _InspireDeadlineExceeded
        response.raise_for_status()
        return response

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

        deadline = time.monotonic() + INSPIRE_TEST_RUN_TIMEOUT
        try:
            # polling the service every POLL_INTERVAL seconds for progress
            while True:
                r = InspireServiceClient._poll_response(progress_url, deadline)
                progress = r.json()
                log.debug("{0}/{1}".format(progress["val"], progress["max"]))
                if progress["val"] == progress["max"]:
                    break
            # retrieving the status from the result json document
            r = InspireServiceClient._poll_response(json_report_url, deadline)
            test_result = r.json()["EtfItemCollection"]["testRuns"]["TestRun"]
            test_status = test_result["status"]
            return test_status, "ok"

        except _InspireDeadlineExceeded:
            return None, "Validation run has timed out after {:d} seconds.".format(INSPIRE_TEST_RUN_TIMEOUT)
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



def do_inspire_check(xml_filepath, export_prefix, output_dir, status, retry_no=0, lightweight_validator=False):
    if lightweight_validator:
        report_filepath = output_dir.joinpath(export_prefix + "_report.txt")
        result = subprocess.run(
            ["geonetwork-validate", "--xml", str(xml_filepath)],
            capture_output=True,
            text=True,
        )
        report_content = result.stdout + result.stderr
        report_filepath.write_text(report_content, encoding="utf-8")
        status.add_attachment(report_filepath.name)
        if "[INVALID]" in report_content:
            status.failed("Metadata of {:s} did not pass INSPIRE validation using the lightweight geonetwork-validator. See report for details.".format(xml_filepath.name))
        else:
            status.info("Metadata of {:s} is valid.".format(xml_filepath.name))
        return
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
            do_inspire_check(
                xml_filepath,
                export_prefix,
                output_dir,
                status,
                retry_no + 1,
                lightweight_validator=lightweight_validator,
            )
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

