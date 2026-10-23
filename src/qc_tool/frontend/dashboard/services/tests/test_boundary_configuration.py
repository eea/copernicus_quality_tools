"""Boundary upload deployment limits use one validated domain contract."""

from dataclasses import asdict
import json
import os
import subprocess
import sys
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from qc_tool.frontend.dashboard.services.boundaries.configuration import (
    boundary_package_limits_from_environment,
    get_boundary_package_limits,
)
from qc_tool.frontend.dashboard.services.boundaries.contracts import (
    BoundaryPackageLimits,
)
from qc_tool.frontend.dashboard.services.boundaries.errors import (
    BoundaryPackageConfigurationError,
)


class BoundaryPackageConfigurationTests(SimpleTestCase):
    def test_defaults_support_reviewed_geospatial_package_without_relaxing_guards(self):
        defaults = BoundaryPackageLimits()

        self.assertEqual(defaults.max_archive_bytes, 4 * 1024**3)
        self.assertEqual(defaults.max_member_bytes, 4 * 1024**3)
        self.assertEqual(defaults.max_uncompressed_bytes, 32 * 1024**3)
        self.assertEqual(defaults.max_members, 10_000)
        self.assertEqual(defaults.max_compression_ratio, 100)
        self.assertEqual(defaults.max_path_length, 1024)
        self.assertEqual(defaults.max_path_component_bytes, 255)
        self.assertEqual(defaults.max_path_depth, 32)
        self.assertEqual(boundary_package_limits_from_environment({}), asdict(defaults))

    def test_every_limit_has_a_validated_environment_override(self):
        expected = {
            "max_archive_bytes": 5 * 1024**3,
            "max_members": 1200,
            "max_member_bytes": 3 * 1024**3,
            "max_uncompressed_bytes": 40 * 1024**3,
            "max_compression_ratio": 125.5,
            "max_path_length": 800,
            "max_path_component_bytes": 200,
            "max_path_depth": 24,
        }
        environment = {
            f"QC_TOOL_BOUNDARY_{key.upper()}": str(value)
            for key, value in expected.items()
        }

        self.assertEqual(boundary_package_limits_from_environment(environment), expected)

    def test_invalid_integer_environment_values_name_the_setting_and_fail_closed(self):
        for field_name in asdict(BoundaryPackageLimits()):
            if field_name == "max_compression_ratio":
                continue
            variable = f"QC_TOOL_BOUNDARY_{field_name.upper()}"
            for value in ("", "no", "0", "-1", "1.5", "nan", "inf", True):
                with self.subTest(variable=variable, value=value):
                    with self.assertRaisesMessage(ImproperlyConfigured, variable):
                        boundary_package_limits_from_environment({variable: value})

    def test_invalid_ratio_environment_values_fail_closed(self):
        variable = "QC_TOOL_BOUNDARY_MAX_COMPRESSION_RATIO"
        for value in ("", "no", "0", "-1", "0.99", "nan", "inf", "-inf", True):
            with self.subTest(value=value):
                with self.assertRaisesMessage(ImproperlyConfigured, variable):
                    boundary_package_limits_from_environment({variable: value})

    def test_partial_setting_uses_domain_defaults_for_unspecified_limits(self):
        with override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_members": 12}):
            limits = get_boundary_package_limits()

        self.assertEqual(limits, BoundaryPackageLimits(max_members=12))

    def test_setting_changes_are_not_cached(self):
        with override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_members": 12}):
            first = get_boundary_package_limits()
        with override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_members": 24}):
            second = get_boundary_package_limits()

        self.assertEqual(first.max_members, 12)
        self.assertEqual(second.max_members, 24)

    def test_adapter_uses_the_contract_mapping_validation(self):
        configured = {"max_members": 17}
        with override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS=configured):
            with patch.object(
                BoundaryPackageLimits,
                "from_mapping",
                wraps=BoundaryPackageLimits.from_mapping,
            ) as from_mapping:
                limits = get_boundary_package_limits()

        from_mapping.assert_called_once_with(configured)
        self.assertEqual(limits.max_members, 17)

    def test_malformed_django_settings_fail_as_typed_configuration_errors(self):
        invalid = (
            None,
            [],
            "defaults",
            {"max_archives_bytes": 10},
            {"max_archive_bytes": "4294967296"},
            {"max_members": True},
            {"max_member_bytes": 0},
            {"max_uncompressed_bytes": -1},
            {"max_compression_ratio": float("nan")},
            {"max_compression_ratio": float("inf")},
            {"max_compression_ratio": 0.5},
        )
        for values in invalid:
            with self.subTest(values=values):
                with override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS=values):
                    with self.assertRaises(BoundaryPackageConfigurationError) as error:
                        get_boundary_package_limits()
                self.assertIn("QC_TOOL_BOUNDARY_PACKAGE_LIMITS", error.exception.detail)

    def _settings_process(self, overrides):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("QC_TOOL_BOUNDARY_")
        }
        environment.update({"QC_TOOL_ENVIRONMENT": "test", "DB_ENGINE": "sqlite"})
        environment.update(overrides)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; "
                "from qc_tool.frontend.settings import QC_TOOL_BOUNDARY_PACKAGE_LIMITS; "
                "print(json.dumps(QC_TOOL_BOUNDARY_PACKAGE_LIMITS))",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_settings_loads_environment_limits_without_duplicate_defaults(self):
        result = self._settings_process({"QC_TOOL_BOUNDARY_MAX_ARCHIVE_BYTES": "1024"})

        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values["max_archive_bytes"], 1024)
        self.assertEqual(values["max_member_bytes"], BoundaryPackageLimits().max_member_bytes)
        self.assertEqual(values["max_uncompressed_bytes"], BoundaryPackageLimits().max_uncompressed_bytes)

    def test_bad_environment_configuration_refuses_settings_loading(self):
        result = self._settings_process({"QC_TOOL_BOUNDARY_MAX_MEMBERS": "typo"})

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("QC_TOOL_BOUNDARY_MAX_MEMBERS must be a positive integer", result.stderr)
