#!/usr/bin/env python3


from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

from qc_tool.worker.manager import create_jobdir_manager


class TestCommon(TestCase):
    def test_load_product_definition(self):
        from qc_tool.common import load_product_definition
        product_definition = load_product_definition("clc2012")
        self.assertIn("steps", product_definition)
        self.assertLess(1, len(product_definition["steps"]))
        self.assertDictEqual({"check_ident": "qc_tool.vector.import2pg",
                              "required": True},
                             product_definition["steps"][6])

    def test_get_product_descriptions(self):
        from qc_tool.common import get_product_descriptions
        product_descriptions = get_product_descriptions()
        self.assertIn("clc2012", product_descriptions)
        self.assertEqual("CORINE Land Cover 2012", product_descriptions["clc2012"])

    def test_prepare_job_blueprint(self):
        from qc_tool.common import load_product_definition
        from qc_tool.common import prepare_job_blueprint
        product_definition = load_product_definition("clc2012")
        job_result = prepare_job_blueprint(product_definition)
        self.assertEqual("clc2012", job_result["product_ident"])
        self.assertEqual("CORINE Land Cover 2012", job_result["description"])
        self.assertEqual("qc_tool.vector.attribute", job_result["steps"][2]["check_ident"])
        self.assertEqual("Attribute table is composed of prescribed attributes.", job_result["steps"][2]["description"])
        self.assertTrue(job_result["steps"][1]["required"])
        self.assertFalse(job_result["steps"][1]["system"])
        self.assertIsNone(job_result["steps"][1]["status"])
        self.assertIsNone(job_result["steps"][1]["messages"])
        self.assertEqual("qc_tool.vector.import2pg", job_result["steps"][6]["check_ident"])
        self.assertTrue(job_result["steps"][6]["system"])


class TestProductDirs(TestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.common import CONFIG
        self.orig_product_dirs = CONFIG["product_dirs"]
        job_uuid = str(uuid4())
        with ExitStack() as stack:
            self.jobdir_manager = stack.enter_context(create_jobdir_manager(job_uuid))
            self.addCleanup(stack.pop_all().close)

        self.product_dir_1 = self.jobdir_manager.tmp_dir.joinpath("products_1")
        self.product_dir_1.mkdir()
        self.product_dir_1.joinpath("p1.json").write_text('{"description": "p1desc"}')
        self.product_dir_1.joinpath("pX.json").write_text('{"description": "pXdesc from 1"}')

        self.product_dir_2 = self.jobdir_manager.tmp_dir.joinpath("products_2")
        self.product_dir_2.mkdir()
        self.product_dir_2.joinpath("p2.json").write_text('{"description": "p2desc"}')
        self.product_dir_2.joinpath("pX.json").write_text('{"description": "pXdesc from 2"}')
        self.product_dir_2.joinpath("P3.json").write_text('{"description": "p3desc"}')

    def tearDown(self):
        from qc_tool.common import CONFIG
        CONFIG["product_dirs"] = self.orig_product_dirs
        super().tearDown()

    def test_locate_product_definition(self):
        from qc_tool.common import CONFIG
        from qc_tool.common import locate_product_definition

        CONFIG["product_dirs"] = [self.product_dir_1, self.product_dir_2]
        self.assertEqual(self.product_dir_1.joinpath("p1.json"), locate_product_definition("p1"))
        self.assertEqual(self.product_dir_2.joinpath("p2.json"), locate_product_definition("p2"))
        self.assertEqual(self.product_dir_1.joinpath("pX.json"), locate_product_definition("pX"))
        self.assertEqual(self.product_dir_2.joinpath("P3.json"), locate_product_definition("p3"))

        CONFIG["product_dirs"] = [self.product_dir_2, self.product_dir_1]
        self.assertEqual(self.product_dir_1.joinpath("p1.json"), locate_product_definition("p1"))
        self.assertEqual(self.product_dir_2.joinpath("p2.json"), locate_product_definition("p2"))
        self.assertEqual(self.product_dir_2.joinpath("pX.json"), locate_product_definition("pX"))

    def test_locate_product_definition_rejects_unroutable_identifiers(self):
        from qc_tool.common import CONFIG
        from qc_tool.common import locate_product_definition
        from qc_tool.common import QCException

        self.product_dir_1.joinpath("paß.json").write_text(
            '{"description": "confusable"}'
        )
        CONFIG["product_dirs"] = [self.product_dir_1]

        for product_ident in ("list", "with/slash", "paß", None):
            with self.subTest(product_ident=product_ident):
                with self.assertRaises(QCException):
                    locate_product_definition(product_ident)

        with self.assertRaises(QCException):
            locate_product_definition("pass")

    def test_get_product_descriptions(self):
        from qc_tool.common import CONFIG
        from qc_tool.common import get_product_descriptions

        CONFIG["product_dirs"] = [self.product_dir_1, self.product_dir_2]
        self.assertDictEqual(
            {
                "p1": "p1desc",
                "p2": "p2desc",
                "p3": "p3desc",
                "px": "pXdesc from 1",
            },
            get_product_descriptions(),
        )

        CONFIG["product_dirs"] = [self.product_dir_2, self.product_dir_1]
        self.assertDictEqual(
            {
                "p1": "p1desc",
                "p2": "p2desc",
                "p3": "p3desc",
                "px": "pXdesc from 2",
            },
            get_product_descriptions(),
        )

    def test_invalid_definition_does_not_hide_the_healthy_catalog(self):
        from qc_tool.common import CONFIG
        from qc_tool.common import get_product_descriptions
        from qc_tool.common import INVALID_PRODUCT_DESCRIPTION

        self.product_dir_1.joinpath("broken.json").write_text("<<<<<<< HEAD")
        CONFIG["product_dirs"] = [self.product_dir_1]

        with self.assertLogs("qc_tool.common", level="WARNING"):
            descriptions = get_product_descriptions()

        self.assertEqual(descriptions["p1"], "p1desc")
        self.assertEqual(descriptions["broken"], INVALID_PRODUCT_DESCRIPTION)


class TestCommonWithConfig(TestCase):
    def setUp(self):
        from qc_tool.common import CONFIG
        from qc_tool.common import setup_config
        setup_config()
        self.work_dir = CONFIG["work_dir"]
        self.work_dir.mkdir(exist_ok=True, parents=True)

    def test_compose_job_dir(self):
        from qc_tool.common import compose_job_dir

        job_uuid = UUID("045f9089-5921-4416-b689-6ba9e6c87f10")
        expected = Path(
            self.work_dir,
            "job_045f908959214416b6896ba9e6c87f10",
        )

        representations = (
            job_uuid,
            str(job_uuid),
            job_uuid.hex,
            str(job_uuid).upper(),
        )
        for value in representations:
            with self.subTest(value=value):
                self.assertEqual(compose_job_dir(value), expected)

    def test_compose_job_paths_reject_invalid_identifiers(self):
        from qc_tool.common import compose_job_dir
        from qc_tool.common import compose_job_stdout_filepath

        invalid_values = (
            None,
            "",
            "not-a-uuid",
            "../outside",
            "00000000-0000-0000-0000-000000000001/../../outside",
            "\N{SNOWMAN}",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    compose_job_dir(value)
                with self.assertRaises(ValueError):
                    compose_job_stdout_filepath(value)

    def test_compose_job_stdout_filepath_accepts_uuid_objects(self):
        from qc_tool.common import compose_job_stdout_filepath

        job_uuid = UUID("045f9089-5921-4416-b689-6ba9e6c87f10")

        self.assertEqual(
            compose_job_stdout_filepath(job_uuid),
            Path(self.work_dir, "job.{}.stdout".format(job_uuid)),
        )

    def test_store_load_job_result(self):
        from qc_tool.common import compose_job_dir
        from qc_tool.common import load_job_result
        from qc_tool.common import store_job_result

        job_uuid = uuid4()
        job_dir = compose_job_dir(job_uuid)
        job_dir.mkdir(exist_ok=True)
        result = {"job_uuid": str(job_uuid)}
        store_job_result(result)
        self.assertDictEqual(result, load_job_result(job_uuid))


class TestWorkerToken(TestCase):
    def setUp(self):
        from qc_tool.common import CONFIG

        self.original_work_dir = CONFIG["work_dir"]
        self.temporary_directory = TemporaryDirectory()
        CONFIG["work_dir"] = Path(self.temporary_directory.name)

    def tearDown(self):
        from qc_tool.common import CONFIG

        CONFIG["work_dir"] = self.original_work_dir
        self.temporary_directory.cleanup()

    def test_token_is_created_once_with_private_permissions(self):
        from qc_tool.common import WORKER_TOKEN_FILENAME
        from qc_tool.common import get_worker_token

        first = get_worker_token()
        second = get_worker_token()
        token_path = Path(self.temporary_directory.name, WORKER_TOKEN_FILENAME)

        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

    def test_existing_token_permissions_are_repaired(self):
        from qc_tool.common import WORKER_TOKEN_FILENAME
        from qc_tool.common import get_worker_token

        token_path = Path(self.temporary_directory.name, WORKER_TOKEN_FILENAME)
        token_path.write_text("existing-token", encoding="utf-8")
        token_path.chmod(0o644)

        self.assertEqual(get_worker_token(), "existing-token")
        self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

    def test_symbolic_link_token_path_is_rejected(self):
        from qc_tool.common import QCException
        from qc_tool.common import WORKER_TOKEN_FILENAME
        from qc_tool.common import get_worker_token

        outside = Path(self.temporary_directory.name, "outside-token")
        outside.write_text("outside", encoding="utf-8")
        Path(self.temporary_directory.name, WORKER_TOKEN_FILENAME).symlink_to(outside)

        with self.assertRaises(QCException):
            get_worker_token()

    @patch("qc_tool.common.compare_digest", return_value=True)
    def test_authentication_uses_constant_time_comparison(self, compare):
        from qc_tool.common import auth_worker
        from qc_tool.common import get_worker_token

        stored = get_worker_token()

        self.assertTrue(auth_worker("presented-token"))
        compare.assert_called_once_with("presented-token", stored)
        self.assertFalse(auth_worker(None))
