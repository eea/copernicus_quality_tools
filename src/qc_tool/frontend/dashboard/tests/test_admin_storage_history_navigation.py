"""History links retain their collection and filters below deployment prefixes."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.urls import get_script_prefix, reverse, set_script_prefix

from qc_tool.frontend.dashboard.views.admin_storage_library import _with_library, storage_library


class AdminStorageHistoryNavigationTests(SimpleTestCase):
    def setUp(self):
        previous_prefix = get_script_prefix()
        self.addCleanup(set_script_prefix, previous_prefix)
        set_script_prefix("/quality/")
        self.return_context = {
            "library": "deliveries", "library_query": "needle",
            "library_status": "approved", "library_page": 3,
        }

    def test_prefixed_storage_destinations_keep_the_current_history_filters(self):
        for route in ("admin_storage", "admin_storage_file", "admin_storage_download", "admin_storage_archive"):
            with self.subTest(route=route):
                destination = reverse(route) + "?" + urlencode({
                    "area": "published", "path": "retained/output.d",
                    "library": "boundaries", "library_query": "old filter",
                }) + "#files"

                result = urlsplit(_with_library(destination, self.return_context))

                self.assertEqual(result.path, reverse(route))
                self.assertEqual(result.fragment, "files")
                self.assertEqual(parse_qs(result.query), {
                    "area": ["published"], "path": ["retained/output.d"],
                    "library": ["deliveries"], "library_query": ["needle"],
                    "library_status": ["approved"], "library_page": ["3"],
                })

    def test_foreign_and_parent_paths_do_not_receive_history_return_parameters(self):
        for destination in (
            "https://outside.example/quality/admin/storage/file/?area=published",
            "//outside.example/quality/admin/storage/file/",
            "/admin/storage/file/?area=published",
            "/quality/admin/storage-other/file/",
            "/quality/admin/storage/../users/",
        ):
            with self.subTest(destination=destination):
                self.assertEqual(_with_library(destination, self.return_context), destination)

    def test_canonical_and_legacy_history_entries_preserve_prefixed_delivery_links(self):
        for selection in ({"tab": "history", "collection": "deliveries"}, {"tab": "deliveries"}):
            with self.subTest(selection=selection):
                listing = {
                    "entries": [{
                        "files_url": reverse("admin_storage") + "?area=published&path=retained",
                        "download_url": reverse("admin_storage_archive") + "?area=published&path=retained",
                    }],
                    "status": "approved", "page": 3,
                    "filters": [{"value": "approved", "label": "Approved"}],
                }
                request = RequestFactory().get("/admin/storage/", {
                    **selection, "q": "needle", "status": "approved", "page": "3",
                }, SCRIPT_NAME="/quality")
                with (
                    patch("qc_tool.frontend.dashboard.views.admin_storage_library.authorize"),
                    patch("qc_tool.frontend.dashboard.services.storage_admin.deliveries.inventory", return_value=listing) as inventory,
                    patch("qc_tool.frontend.dashboard.views.admin_storage_library.render_storage", return_value=HttpResponse()) as render,
                ):
                    storage_library(request)

                inventory.assert_called_once_with(query="needle", status="approved", page="3")
                self.assertEqual(render.call_args.kwargs["library_kind"], "deliveries")
                self.assertEqual(parse_qs(urlsplit(render.call_args.kwargs["clear_library_url"]).query), {
                    "tab": ["history"], "collection": ["deliveries"],
                })
                for field in ("files_url", "download_url"):
                    result = urlsplit(listing["entries"][0][field])
                    self.assertTrue(result.path.startswith("/quality/admin/storage/"))
                    parameters = parse_qs(result.query)
                    for key, value in self.return_context.items():
                        self.assertEqual(parameters[key], [str(value)])
