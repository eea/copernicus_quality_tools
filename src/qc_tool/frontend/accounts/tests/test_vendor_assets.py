import hashlib
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.test import TestCase
from django.urls import reverse


STATIC_ROOT = (
    Path(__file__).resolve().parents[2]
    / "dashboard"
    / "static"
    / "dashboard"
)


class ReviewedVendorAssetTests(SimpleTestCase):
    """Detect an unreviewed or partial replacement of security-sensitive JS."""

    EXPECTED = {
        "js/jquery.min.js": (
            b"jQuery v3.7.1",
            "fc9a93dd241f6b045cbff0481cf4e1901becd0e12fb45166a8f17f95823f0b1a",
        ),
        "js/bootstrap.min.js": (
            b"Bootstrap v3.4.1",
            "9ee2fcff6709e4d0d24b09ca0fc56aade12b4961ed9c43fd13b03248bfb57afe",
        ),
        "css/bootstrap.min.css": (
            b"Bootstrap v3.4.1",
            "6d92dfc1700fd38cd130ad818e23bc8aef697f815b2ea5face2b5dfad22f2e11",
        ),
    }

    def test_reviewed_vendor_assets_match_the_documented_release_bytes(self):
        for relative_path, (version_marker, expected_digest) in self.EXPECTED.items():
            with self.subTest(relative_path=relative_path):
                payload = STATIC_ROOT.joinpath(relative_path).read_bytes()
                self.assertIn(version_marker, payload[:256])
                self.assertEqual(
                    hashlib.sha256(payload).hexdigest(),
                    expected_digest,
                )


class BoundaryUploadClientTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="boundary-upload-ui-admin",
            email="admin@example.test",
            password="unused",
        )

    def test_page_uses_one_small_same_origin_upload_client(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("boundaries_upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="fileupload"')
        self.assertContains(response, 'id="upload-result"')
        self.assertContains(response, "dashboard/js/boundaries_upload.js")
        self.assertNotContains(response, "jquery-file-upload")
        self.assertNotContains(response, "data-form-data")
        self.assertNotContains(response, " multiple")
