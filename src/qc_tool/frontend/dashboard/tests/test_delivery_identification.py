"""Parsed filenames select managed specifications without verifying ZIP contents."""

import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.common import QC_TOOL_PRODUCT_DIR
from qc_tool.frontend.accounts.authorization import AccountAccess
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.dashboard.models import Delivery, Job, Product, ProductRelease, QcDefinition, S3Info
from qc_tool.frontend.dashboard.services.catalog.manifest.definitions import parse_definition_snapshot
from qc_tool.frontend.dashboard.services.product_units import create_delivery_job
from qc_tool.frontend.dashboard.services.products.identification import (
    guess_product_ident,
    identify_delivery,
    require_matching_product,
)
from qc_tool.frontend.dashboard.services.products.filename_rules import validate_filename_rules
from qc_tool.frontend.dashboard.services.s3 import S3Delivery
from qc_tool.frontend.dashboard.services.tests.test_resumable_uploads import _parameters
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadError
from qc_tool.frontend.dashboard.services.uploads.access import require_upload_filename
from qc_tool.frontend.dashboard.tests.catalog_fixtures import managed_definition


UA_IDENT = "clms_ua_lcuc_c2021-2024_v010ha"
VERVIERS_FILENAME = "CLMS_UA_LCUC_C2021-2024_V010ha_BE015L1_VERVIERS_03035_V01_R00_20260730.zip"
UA_MAPPING = {
    "family": "copernicus:clms:ua-lcu",
    "schema_version": "0.0.0",
    "match": {
        "variable": "LCUC", "survey": "C2021-2024", "type": "V",
        "resolution": "010ha",
    },
}


def mapped_definition(test_case, ident, *, mapping=None):
    rules = deepcopy(settings.DELIVERY_FILENAME_RULES)
    rules[ident] = deepcopy(UA_MAPPING if mapping is None else mapping)
    test_case.enterContext(override_settings(DELIVERY_FILENAME_RULES=rules))
    return managed_definition(ident, document={
        "description": "Urban Atlas change", "steps": [],
    })


class DeliveryIdentificationTests(TestCase):
    def test_recognized_name_does_not_create_a_catalog_product(self):
        result = identify_delivery(VERVIERS_FILENAME)

        self.assertEqual(result.status, "unconfigured")
        self.assertEqual(result.candidates, ())
        self.assertIsNone(result.product_ident)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(QcDefinition.objects.exists())

    def test_existing_managed_identifier_matches_valid_ua_without_mapping(self):
        managed_definition(UA_IDENT)

        result = identify_delivery(VERVIERS_FILENAME)

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.candidates, (UA_IDENT,))
        self.assertEqual(result.product_ident, UA_IDENT)
        self.assertEqual(result.parsed.fields["area_code"].upper(), "BE015L1")
        self.assertEqual(result.parsed.fields["city"].upper(), "VERVIERS")
        self.assertEqual(result.parsed.fields["production_date"], "20260730")
        self.assertFalse(Delivery.objects.exists())

    def test_explicit_mapping_matches_an_unrelated_catalog_identifier(self):
        mapped_definition(self, "urban_atlas_change")

        result = identify_delivery(VERVIERS_FILENAME)

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.product_ident, "urban_atlas_change")
        self.assertEqual(guess_product_ident(Path(VERVIERS_FILENAME)), "urban_atlas_change")

    def test_mapping_values_and_filename_are_case_insensitive(self):
        mapping = deepcopy(UA_MAPPING)
        mapping["match"] = {key: value.lower() for key, value in mapping["match"].items()}
        mapped_definition(self, "urban_atlas", mapping=mapping)

        result = identify_delivery(VERVIERS_FILENAME.lower())

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.product_ident, "urban_atlas")

    def test_mapping_requires_matching_period_representation_and_resolution(self):
        mapped_definition(self, "urban_atlas")

        for filename in (
            VERVIERS_FILENAME.replace("C2021-2024", "C2018-2021"),
            VERVIERS_FILENAME.replace("V010ha", "R010ha"),
            VERVIERS_FILENAME.replace("V010ha", "V025ha"),
        ):
            with self.subTest(filename=filename):
                result = identify_delivery(filename)
                self.assertEqual(result.status, "unconfigured")
                self.assertEqual(result.candidates, ())
                self.assertIsNone(result.product_ident)

    def test_explicit_mapping_mismatch_cannot_fall_back_to_identifier_prefix(self):
        mapping = deepcopy(UA_MAPPING)
        mapping["match"]["survey"] = "C2018-2021"
        mapped_definition(self, UA_IDENT, mapping=mapping)

        result = identify_delivery(VERVIERS_FILENAME)

        self.assertEqual(result.status, "unconfigured")
        self.assertIsNone(guess_product_ident(Path(VERVIERS_FILENAME)))

    @override_settings(DELIVERY_FILENAME_RULES={UA_IDENT: None})
    def test_explicit_null_configuration_cannot_fall_back_to_identifier_matching(self):
        managed_definition(UA_IDENT)
        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.products.identification", level="WARNING",
        ):
            result = identify_delivery(VERVIERS_FILENAME)
        self.assertEqual(result.status, "unconfigured")
        self.assertEqual(result.candidates, ())

    @override_settings(DELIVERY_FILENAME_RULES={})
    def test_specification_contents_do_not_supply_routing_configuration(self):
        document = {
            "description": "Original specification", "steps": [],
            "filename_identification": UA_MAPPING,
        }
        definition, _release = managed_definition("arbitrary_name", document=document)
        original_digest = definition.digest
        result = identify_delivery(VERVIERS_FILENAME)
        self.assertEqual(result.status, "unconfigured")
        definition.refresh_from_db()
        self.assertEqual(definition.document, document)
        self.assertEqual(definition.digest, original_digest)

    def test_matching_multiple_specifications_never_silently_selects_one(self):
        mapped_definition(self, "ua_secondary")
        mapped_definition(self, "ua_primary")

        result = identify_delivery(VERVIERS_FILENAME)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(set(result.candidates), {"ua_primary", "ua_secondary"})
        self.assertIsInstance(result.candidates, tuple)
        self.assertIsNone(result.product_ident)
        self.assertIsNone(guess_product_ident(Path(VERVIERS_FILENAME)))

    def test_stopped_and_retired_specifications_are_not_candidates(self):
        _definition, stopped = mapped_definition(self, "ua_stopped")
        Product.objects.filter(pk=stopped.product_id).update(is_active=False)
        _definition, retired = mapped_definition(self, "ua_retired")
        ProductRelease.objects.filter(pk=retired.pk).update(coverage_state="retired")

        result = identify_delivery(VERVIERS_FILENAME)

        self.assertEqual(result.status, "unconfigured")
        self.assertEqual(result.candidates, ())

    def test_malformed_ua_and_impossible_dates_cannot_use_prefix_fallback(self):
        managed_definition(UA_IDENT)

        for filename in (
            VERVIERS_FILENAME.replace("20260730", "20260230"),
            VERVIERS_FILENAME.replace("20260730", "20261301"),
            VERVIERS_FILENAME.replace("BE015L1", "BE015"),
            UA_IDENT + "_arbitrary.zip",
        ):
            with self.subTest(filename=filename):
                result = identify_delivery(filename)
                self.assertEqual(result.status, "invalid")
                self.assertEqual(result.candidates, ())
                self.assertIsNone(result.product_ident)

    def test_legacy_identifiers_require_a_filename_token_boundary(self):
        managed_definition("rpz_2012")

        for filename in ("rpz_2012_delivery.zip", "delivery_rpz_2012.zip", "RPZ_2012.zip"):
            with self.subTest(filename=filename):
                self.assertEqual(identify_delivery(filename).product_ident, "rpz_2012")
        for filename in ("rpz_20120_delivery.zip", "delivery_xrpz_2012.zip", "unrelated.zip"):
            with self.subTest(filename=filename):
                result = identify_delivery(filename)
                self.assertEqual(result.status, "unknown")
                self.assertIsNone(result.product_ident)

    def test_ambiguous_legacy_prefix_and_suffix_are_not_order_dependent(self):
        managed_definition("legacy_a")
        managed_definition("legacy_b")

        result = identify_delivery("legacy_a_delivery_legacy_b.zip")

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(set(result.candidates), {"legacy_a", "legacy_b"})
        self.assertIsNone(result.product_ident)


class FilenameIdentificationConfigurationTests(TestCase):
    def test_valid_application_rules_are_normalized_without_mutating_the_input(self):
        original = deepcopy(UA_MAPPING)
        self.assertEqual(validate_filename_rules(UA_MAPPING), original)
        self.assertEqual(UA_MAPPING, original)

    def test_invalid_application_rules_are_rejected(self):
        invalid_mappings = (
            "copernicus:clms:ua-lcu",
            {},
            {**UA_MAPPING, "family": "unknown:family"},
            {**UA_MAPPING, "schema_version": "99.0.0"},
            {**UA_MAPPING, "match": "LCUC"},
            {**UA_MAPPING, "match": {"unknown_field": "LCUC"}},
            {**UA_MAPPING, "match": {"variable": ["LCUC"]}},
            {**UA_MAPPING, "match": {"variable": "INVALID"}},
            {**UA_MAPPING, "match": {"resolution": "ten-hectares"}},
        )
        for mapping in invalid_mappings:
            with self.subTest(mapping=mapping):
                with self.assertRaises(ValueError):
                    validate_filename_rules(mapping)
        self.assertFalse(QcDefinition.objects.exists())

    def test_product_import_does_not_validate_application_routing(self):
        document = {
            "description": "Unmodified source", "steps": [],
            "filename_identification": "source metadata unrelated to QC Tool routing",
        }
        snapshot = parse_definition_snapshot(
            "urban_atlas", json.dumps(document).encode(), source_path="upload:urban_atlas.json",
        )
        self.assertEqual(snapshot.document, document)


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DeliveryIdentificationUploadTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="identified-uploader")

    def access(self, *idents):
        for ident in idents:
            UserProductGrant.objects.get_or_create(user=self.user, product_ident=ident)
        return AccountAccess.from_user(self.user)

    def assert_rejected(self, access, filename, code, status):
        with self.assertRaises(ResumableUploadError) as raised:
            require_upload_filename(access, filename)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.status_code, status)

    def test_known_name_requires_access_to_its_matching_product(self):
        mapped_definition(self, "urban_atlas")
        managed_definition("unrelated")

        self.assert_rejected(self.access("unrelated"), VERVIERS_FILENAME, "product_permission_denied", 403)
        result = require_upload_filename(self.access("urban_atlas"), VERVIERS_FILENAME)

        self.assertEqual(result.product_ident, "urban_atlas")

    def test_unconfigured_name_cannot_use_an_unrelated_assignment(self):
        managed_definition("unrelated")

        self.assert_rejected(self.access("unrelated"), VERVIERS_FILENAME, "product_not_configured", 400)

    def test_invalid_name_cannot_use_a_matching_prefix_assignment(self):
        managed_definition(UA_IDENT)

        self.assert_rejected(
            self.access(UA_IDENT), VERVIERS_FILENAME.replace("20260730", "20260230"),
            "delivery_name_invalid", 400,
        )

    def test_ambiguous_name_allows_an_assigned_candidate_without_selecting_it(self):
        mapped_definition(self, "ua_a")
        mapped_definition(self, "ua_b")
        managed_definition("unrelated")
        self.assert_rejected(self.access("unrelated"), VERVIERS_FILENAME, "product_permission_denied", 403)

        result = require_upload_filename(self.access("ua_b"), VERVIERS_FILENAME)

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.product_ident)

    def test_unknown_legacy_filename_can_be_uploaded_for_later_manual_selection(self):
        managed_definition("legacy_product")

        result = require_upload_filename(self.access("legacy_product"), "delivery.zip")

        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.product_ident)

    def upload(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=Path(temporary)))
        self.client.force_login(self.user)
        parameters = {**_parameters(), "resumableFilename": VERVIERS_FILENAME}
        return self.client.post(reverse("resumable_upload"), {
            **parameters, "file": SimpleUploadedFile("chunk", b"abcd"),
        })

    def test_registration_stores_product_but_never_a_verified_unit_from_filename(self):
        mapped_definition(self, "urban_atlas")
        self.access("urban_atlas")

        response = self.upload()

        self.assertEqual(response.status_code, 200, response.content)
        delivery = Delivery.objects.get()
        self.assertEqual(delivery.filename, VERVIERS_FILENAME)
        self.assertEqual(delivery.product_ident, "urban_atlas")
        self.assertIsNone(delivery.product_unit_code)
        self.assertIsNone(delivery.submitted_product_unit_code)
        self.assertFalse(Job.objects.exists())

    def test_ambiguous_registration_waits_for_manual_qc_product_selection(self):
        mapped_definition(self, "ua_a")
        mapped_definition(self, "ua_b")
        self.access("ua_b")

        response = self.upload()

        self.assertEqual(response.status_code, 200, response.content)
        delivery = Delivery.objects.get()
        self.assertIsNone(delivery.product_ident)
        self.assertIsNone(delivery.product_unit_code)
        self.assertIsNone(delivery.submitted_product_unit_code)


class DeliveryIdentificationJobTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="identified-job-owner")
        self.definition, self.release = mapped_definition(self, "urban_atlas")
        self.other_definition, self.other_release = managed_definition("unrelated")
        for ident in ("urban_atlas", "unrelated"):
            UserProductGrant.objects.create(user=self.user, product_ident=ident)
        self.access = AccountAccess.from_user(self.user)
        self.delivery = Delivery.objects.create(
            user=self.user, filename=VERVIERS_FILENAME, size_bytes=4,
        )
        self.snapshots = {
            "urban_atlas": (self.definition, self.release),
            "unrelated": (self.other_definition, self.other_release),
        }
        self.enterContext(patch(
            "qc_tool.frontend.dashboard.services.product_units.jobs.creation._catalog_snapshot",
            side_effect=lambda ident, **_kwargs: self.snapshots[ident],
        ))

    def create_job(self, product_ident):
        return create_delivery_job(
            self.delivery, product_ident=product_ident,
            product_description="Selected product", skip_steps="",
            requested_by=self.user, account_access=self.access,
        )

    def test_known_filename_rejects_an_unrelated_selected_specification(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.create_job("unrelated")

        self.assertFalse(Job.objects.exists())
        self.delivery.refresh_from_db()
        self.assertIsNone(self.delivery.product_ident)
        self.assertIsNone(self.delivery.product_unit_code)
        self.assertIsNone(self.delivery.submitted_product_unit_code)

    def test_matching_job_keeps_parsed_unit_separate_from_verified_metadata(self):
        job = self.create_job("urban_atlas")

        self.assertEqual(job.qc_definition_id, self.definition.pk)
        self.assertEqual(job.product_ident, "urban_atlas")
        self.assertIsNone(job.product_unit_code)
        self.assertIsNone(job.submitted_product_unit_code)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.product_ident, "urban_atlas")
        self.assertIsNone(self.delivery.product_unit_code)
        self.assertIsNone(self.delivery.submitted_product_unit_code)

    def test_invalid_and_unconfigured_names_cannot_create_jobs_or_change_rows(self):
        for filename in (
            VERVIERS_FILENAME.replace("20260730", "20260230"),
            VERVIERS_FILENAME.replace("C2021-2024", "C2018-2021"),
        ):
            with self.subTest(filename=filename):
                self.delivery.filename = filename
                self.delivery.save(update_fields=("filename",))
                with self.assertRaises(ValueError):
                    self.create_job("urban_atlas")
                self.assertFalse(Job.objects.exists())
                self.delivery.refresh_from_db()
                self.assertIsNone(self.delivery.product_ident)

    def test_unknown_legacy_filename_preserves_manual_product_selection(self):
        self.delivery.filename = "delivery.zip"
        self.delivery.save(update_fields=("filename",))

        job = self.create_job("unrelated")

        self.assertEqual(job.qc_definition_id, self.other_definition.pk)
        self.assertEqual(job.product_ident, "unrelated")

    def test_ambiguous_filename_allows_an_assigned_matching_qc_selection(self):
        definition, release = mapped_definition(self, "urban_atlas_alternative")
        self.snapshots["urban_atlas_alternative"] = (definition, release)
        UserProductGrant.objects.create(user=self.user, product_ident="urban_atlas_alternative")
        self.access = AccountAccess.from_user(self.user)
        self.assertEqual(identify_delivery(VERVIERS_FILENAME).status, "ambiguous")

        job = self.create_job("urban_atlas_alternative")

        self.assertEqual(job.qc_definition_id, definition.pk)
        self.assertEqual(job.product_ident, "urban_atlas_alternative")
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.product_ident, "urban_atlas_alternative")
        self.assertIsNone(self.delivery.submitted_product_unit_code)


@override_settings(
    DEBUG=False, MAINTENANCE_MODE=False,
    S3_ALLOWED_ENDPOINTS=("https://objects.example.com",),
)
class DeliveryIdentificationApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="identified-api-owner")
        mapped_definition(self, "urban_atlas")
        managed_definition("unrelated")
        for ident in ("urban_atlas", "unrelated"):
            UserProductGrant.objects.create(user=self.user, product_ident=ident)
        self.authorization = "Bearer " + issue_personal_access_token(self.user, "Identification").raw_token
        self.media_root = Path(self.enterContext(TemporaryDirectory()))
        self.user_root = self.media_root / self.user.username
        self.user_root.mkdir()
        self.enterContext(override_settings(MEDIA_ROOT=self.media_root))

    def register(self, source, filename):
        if source == "local":
            (self.user_root / filename).write_bytes(b"archive")
            return self.client.post(
                reverse("api_register_delivery"), {"uploaded_file": filename},
                content_type="application/json", HTTP_AUTHORIZATION=self.authorization,
            )
        with patch(
            "qc_tool.frontend.dashboard.views.api_access.deliveries.inspect_s3_delivery",
            return_value=S3Delivery(filename="incoming/" + filename, size_bytes=7),
        ):
            return self.client.post(reverse("api_register_delivery_s3"), {
                "host": "https://objects.example.com", "access_key": "key", "secret_key": "secret",
                "bucketname": "deliveries", "key_prefix": "incoming/" + filename,
            }, content_type="application/json", HTTP_AUTHORIZATION=self.authorization)

    def test_local_and_s3_registration_share_real_filename_identification(self):
        for source in ("local", "s3"):
            with self.subTest(source=source):
                response = self.register(source, VERVIERS_FILENAME)
                self.assertEqual(response.status_code, 200, response.content)
                delivery = Delivery.objects.get(pk=response.json()["delivery_id"])
                self.assertEqual(delivery.filename, VERVIERS_FILENAME)
                self.assertEqual(delivery.product_ident, "urban_atlas")
                self.assertIsNone(delivery.product_unit_code)
                self.assertIsNone(delivery.submitted_product_unit_code)

    def test_recognized_invalid_and_unconfigured_names_are_rejected_before_persistence(self):
        for source in ("local", "s3"):
            for filename, code in (
                (VERVIERS_FILENAME.replace("20260730", "20260230"), "delivery_name_invalid"),
                (VERVIERS_FILENAME.replace("C2021-2024", "C2018-2021"), "product_not_configured"),
            ):
                with self.subTest(source=source, filename=filename):
                    response = self.register(source, filename)
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertEqual(response.json()["code"], code)
                    self.assertFalse(Delivery.objects.exists())
                    self.assertFalse(S3Info.objects.exists())

    def test_unrelated_product_access_cannot_authorize_known_names(self):
        self.user.product_grants.filter(product_ident="urban_atlas").delete()

        for source in ("local", "s3"):
            with self.subTest(source=source):
                response = self.register(source, VERVIERS_FILENAME)
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(response.json()["code"], "product_permission_denied")
                self.assertFalse(Delivery.objects.exists())
                self.assertFalse(S3Info.objects.exists())

    def test_ambiguous_registration_retains_no_silently_chosen_product(self):
        mapped_definition(self, "urban_atlas_alternative")

        for source in ("local", "s3"):
            with self.subTest(source=source):
                response = self.register(source, VERVIERS_FILENAME)
                self.assertEqual(response.status_code, 200, response.content)
                delivery = Delivery.objects.get(pk=response.json()["delivery_id"])
                self.assertIsNone(delivery.product_ident)
                self.assertIsNone(delivery.product_unit_code)
                self.assertIsNone(delivery.submitted_product_unit_code)


class BundledUrbanAtlasVariantIdentificationTests(TestCase):
    """Supplied alternate recipes remain selectable for the same valid archive."""

    filename = "CLMS_UA_LCU_S2021_V025ha_BE015L1_VERVIERS_03035_V01_R00_20260730.zip"
    base_ident = "clms_ua_lcu_s2021_v025ha"
    variant_idents = (
        "clms_ua_lcu_s2021_v025ha_fgb_parquet",
        "clms_ua_lcu_s2021_v025ha_boundary2018",
    )

    def load_bundled_definition(self, ident):
        path = QC_TOOL_PRODUCT_DIR / (ident + ".json")
        original_bytes = path.read_bytes()
        snapshot = parse_definition_snapshot(ident, original_bytes, source_path=str(path))
        self.assertNotIn("filename_identification", snapshot.document)
        self.assertEqual(path.read_bytes(), original_bytes)
        return managed_definition(ident, document=snapshot.document)[0]

    def assert_unique_variant(self, ident):
        definition = self.load_bundled_definition(ident)
        result = identify_delivery(self.filename)

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.candidates, (ident,))
        self.assertEqual(result.product_ident, ident)
        require_matching_product(self.filename, ident, definition=definition)
        self.assertFalse(Delivery.objects.exists())
        self.assertFalse(Job.objects.exists())

    def test_fgb_parquet_recipe_matches_without_a_base_catalog_product(self):
        self.assert_unique_variant(self.variant_idents[0])

    def test_boundary2018_recipe_matches_without_a_base_catalog_product(self):
        self.assert_unique_variant(self.variant_idents[1])

    def test_dhm_recipe_keeps_its_complete_product_year_identity(self):
        definition = self.load_bundled_definition("ua2012_dhm")
        filename = "BE015L1_VERVIERS_UA2012_DHM.zip"

        result = identify_delivery(filename)

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.product_ident, "ua2012_dhm")
        self.assertEqual(result.parsed.family, "copernicus:clms:ua-dhm")
        require_matching_product(filename, "ua2012_dhm", definition=definition)

    def test_base_and_variant_recipes_require_explicit_selection(self):
        definitions = {
            ident: self.load_bundled_definition(ident)
            for ident in (self.base_ident, *self.variant_idents)
        }
        result = identify_delivery(self.filename)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(set(result.candidates), set(definitions))
        self.assertIsNone(result.product_ident)
        for ident, definition in definitions.items():
            with self.subTest(ident=ident):
                require_matching_product(self.filename, ident, definition=definition)

    def test_variant_recipe_does_not_match_another_reference_year(self):
        self.load_bundled_definition(self.variant_idents[0])

        result = identify_delivery(self.filename.replace("S2021", "S2024"))

        self.assertEqual(result.status, "unconfigured")
        self.assertEqual(result.candidates, ())

    def test_recognized_product_does_not_match_a_partial_prefix_or_date_identifier(self):
        for ident in ("clms", "clms_ua", "clms_ua_lcu", "20260730"):
            managed_definition(ident)

        result = identify_delivery(self.filename)

        self.assertEqual(result.status, "unconfigured")
        self.assertEqual(result.candidates, ())

    def test_complete_product_identity_is_not_made_ambiguous_by_unrelated_edges(self):
        self.load_bundled_definition(self.base_ident)
        for ident in ("clms", "clms_ua", "20260730"):
            managed_definition(ident)

        result = identify_delivery(self.filename)

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.candidates, (self.base_ident,))
