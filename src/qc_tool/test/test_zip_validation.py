#!/usr/bin/env python3


from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZIP_STORED, ZipFile

from qc_tool.common import QCException
from qc_tool.common import TEST_DATA_DIR
from qc_tool.raster.unzip import ZIP_VALIDATORS as RASTER_ZIP_VALIDATORS
from qc_tool.vector.unzip import ZIP_VALIDATORS as VECTOR_ZIP_VALIDATORS


VALIDATOR_PIPELINES = {
    "raster": RASTER_ZIP_VALIDATORS,
    "vector": VECTOR_ZIP_VALIDATORS,
}


class TestZipValidation(TestCase):
    def setUp(self):
        super().setUp()
        self.temp_dir_context = TemporaryDirectory()
        self.addCleanup(self.temp_dir_context.cleanup)
        self.temp_dir = Path(self.temp_dir_context.name)

        self.valid_zip = self.temp_dir.joinpath("valid.zip")
        with ZipFile(str(self.valid_zip), "w", compression=ZIP_STORED) as zip_file:
            zip_file.writestr("payload.txt", "portable zip payload")

    def test_valid_archive(self):
        for pipeline_name, validators in VALIDATOR_PIPELINES.items():
            with self.subTest(pipeline=pipeline_name):
                for validator in validators:
                    validator(self.valid_zip)

    def test_archive_with_prefixed_copy_is_rejected(self):
        valid_data = self.valid_zip.read_bytes()
        damaged_zip = self.temp_dir.joinpath("damaged.zip")
        damaged_zip.write_bytes(valid_data + valid_data)

        for pipeline_name, validators in VALIDATOR_PIPELINES.items():
            with self.subTest(pipeline=pipeline_name):
                with self.assertRaises(QCException) as raised:
                    for validator in validators:
                        validator(damaged_zip)

                message = str(raised.exception)
                self.assertIn("{:d} extra bytes".format(len(valid_data)), message)
                self.assertIn("Windows built-in ZIP extractor", message)

    def test_undamaged_hrl_fixture_is_accepted(self):
        undamaged_zip = TEST_DATA_DIR.joinpath(
            "vector", "hrl", "undamaged_zip", "CLMS_HRLSLF_S2018_E73N22_R01.zip"
        )

        # Run the real control fixture through both product specific pipelines
        # so later validators cannot accidentally reject a portable ZIP.
        for pipeline_name, validators in VALIDATOR_PIPELINES.items():
            with self.subTest(pipeline=pipeline_name):
                for validator in validators:
                    validator(undamaged_zip)

    def test_damaged_hrl_fixture_is_rejected(self):
        damaged_zip = TEST_DATA_DIR.joinpath(
            "vector", "hrl", "damaged_zip", "CLMS_HRLSLF_S2018_E50N22_jktest.zip"
        )

        for pipeline_name, validators in VALIDATOR_PIPELINES.items():
            with self.subTest(pipeline=pipeline_name):
                with self.assertRaisesRegex(QCException, "5242880 extra bytes"):
                    for validator in validators:
                        validator(damaged_zip)
