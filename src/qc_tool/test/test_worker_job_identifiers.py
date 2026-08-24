from unittest import TestCase
from unittest.mock import MagicMock

from qc_tool.worker.jobs import JobIdentifierError
from qc_tool.worker.jobs import job_schema_name
from qc_tool.worker.jobs import normalize_job_uuid
from qc_tool.worker.jobs import validate_path_component
from qc_tool.worker.manager import ConnectionManager


VALID_UUID = "00000000-0000-0000-0000-000000000001"


class WorkerJobIdentifierTests(TestCase):
    def test_normalizes_uuid_and_builds_a_fixed_alphabet_schema(self):
        self.assertEqual(
            normalize_job_uuid("00000000000000000000000000000001"),
            VALID_UUID,
        )
        self.assertEqual(
            job_schema_name(VALID_UUID),
            "job_00000000000000000000000000000001",
        )

    def test_rejects_uuid_values_that_could_be_paths_or_sql(self):
        for value in ("../job", "x; DROP SCHEMA public", "job_uuid", None):
            with self.subTest(value=value):
                with self.assertRaises(JobIdentifierError):
                    normalize_job_uuid(value)

    def test_rejects_unsafe_storage_components_without_rewriting_them(self):
        for value in (
            "../alice",
            "nested/delivery.zip",
            "..",
            "a\\b",
            "x\x00",
            "\N{SNOWMAN}" * 86,
        ):
            with self.subTest(value=value):
                with self.assertRaises(JobIdentifierError):
                    validate_path_component(value, 500, "filename")
        self.assertEqual(
            validate_path_component("delivery.zip", 500, "filename"),
            "delivery.zip",
        )

    def test_connection_manager_rejects_invalid_uuid_before_connecting(self):
        with self.assertRaises(JobIdentifierError):
            ConnectionManager(
                "bad; DROP SCHEMA public",
                "localhost",
                5432,
                "worker",
                "worker",
                False,
            )

    def test_connection_manager_quotes_the_derived_schema_identifier(self):
        manager = ConnectionManager(
            VALID_UUID,
            "localhost",
            5432,
            "worker",
            "worker",
            False,
        )
        connection = MagicMock(closed=0)
        cursor = connection.cursor.return_value
        manager.connection = connection

        manager._create_job_schema()

        statements = [str(call.args[0]) for call in cursor.execute.call_args_list]
        self.assertEqual(len(statements), 2)
        self.assertTrue(all("Identifier('job_" in item for item in statements))
        self.assertEqual(
            manager.job_schema_name,
            "job_00000000000000000000000000000001",
        )
