from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError
from qc_tool.frontend.dashboard.services.uploads import remove_user_delivery_upload
from qc_tool.frontend.dashboard.services.uploads import resolve_user_delivery_upload


class DeliveryUploadPathTests(SimpleTestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.media_root = Path(self.temp_dir.name)
        self.user_root = self.media_root / "alice"
        self.user_root.mkdir()
        self.delivery = self.user_root / "delivery.zip"
        self.delivery.write_bytes(b"zip-placeholder")

    def resolve(self, supplied_path):
        return resolve_user_delivery_upload(
            supplied_path,
            media_root=self.media_root,
            username="alice",
        )

    def test_accepts_filename_or_full_path_below_the_authenticated_user_root(self):
        self.assertEqual(self.resolve("delivery.zip"), self.delivery.resolve())
        self.assertEqual(self.resolve(str(self.delivery)), self.delivery.resolve())

    def test_rejects_another_users_file(self):
        other_root = self.media_root / "bob"
        other_root.mkdir()
        other_file = other_root / "delivery.zip"
        other_file.write_bytes(b"other")

        with self.assertRaises(DeliveryUploadPathError) as caught:
            self.resolve(str(other_file))

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(
            caught.exception.code,
            "uploaded_file_outside_user_storage",
        )

    def test_rejects_nested_and_traversal_paths(self):
        nested = self.user_root / "nested"
        nested.mkdir()
        nested_file = nested / "delivery.zip"
        nested_file.write_bytes(b"nested")

        for supplied_path in ("nested/delivery.zip", "../alice/nested/delivery.zip"):
            with self.subTest(supplied_path=supplied_path):
                with self.assertRaises(DeliveryUploadPathError) as caught:
                    self.resolve(supplied_path)
                self.assertEqual(caught.exception.status_code, 403)

    def test_rejects_symbolic_links_even_when_the_target_is_inside_the_root(self):
        link = self.user_root / "link.zip"
        link.symlink_to(self.delivery)

        with self.assertRaises(DeliveryUploadPathError) as caught:
            self.resolve(str(link))

        self.assertEqual(caught.exception.code, "unsafe_uploaded_file")

    def test_rejects_a_symbolic_link_used_as_the_user_storage_root(self):
        real_root = self.media_root / "real-alice"
        real_root.mkdir()
        (real_root / "delivery.zip").write_bytes(b"outside")
        self.delivery.unlink()
        self.user_root.rmdir()
        self.user_root.symlink_to(real_root, target_is_directory=True)

        with self.assertRaises(DeliveryUploadPathError) as caught:
            self.resolve("delivery.zip")

        self.assertEqual(caught.exception.code, "unsafe_upload_storage")

    def test_rejects_missing_non_zip_and_non_string_values(self):
        text_file = self.user_root / "delivery.txt"
        text_file.write_text("not a delivery", encoding="utf-8")

        cases = (
            (None, "missing_uploaded_file"),
            ("missing.zip", "uploaded_file_not_found"),
            ("delivery.txt", "invalid_delivery_file_type"),
        )
        for supplied_path, expected_code in cases:
            with self.subTest(supplied_path=supplied_path):
                with self.assertRaises(DeliveryUploadPathError) as caught:
                    self.resolve(supplied_path)
                self.assertEqual(caught.exception.code, expected_code)

    def test_removes_only_the_users_regular_delivery_file(self):
        removed = remove_user_delivery_upload(
            media_root=self.media_root,
            username="alice",
            filename="delivery.zip",
        )

        self.assertTrue(removed)
        self.assertFalse(self.delivery.exists())
        self.assertFalse(
            remove_user_delivery_upload(
                media_root=self.media_root,
                username="alice",
                filename="delivery.zip",
            )
        )

    def test_delete_rejects_traversal_and_symbolic_links(self):
        outside = self.media_root / "outside.zip"
        outside.write_bytes(b"outside")
        link = self.user_root / "link.zip"
        link.symlink_to(outside)

        for filename in ("../outside.zip", "link.zip"):
            with self.subTest(filename=filename):
                with self.assertRaises(DeliveryUploadPathError):
                    remove_user_delivery_upload(
                        media_root=self.media_root,
                        username="alice",
                        filename=filename,
                    )
        self.assertEqual(outside.read_bytes(), b"outside")
