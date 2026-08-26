import re
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.shortcuts import render
from django.test import Client
from django.test import SimpleTestCase
from django.test import TestCase
from django.test import override_settings
from django.urls import path
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect

from qc_tool.frontend.dashboard.models import Delivery


def empty_view(_request):
    return HttpResponse()


@login_not_required
def csrf_page(request):
    return render(request, "dashboard/layouts/base.html")


@login_not_required
@csrf_protect
def csrf_mutation(_request):
    return HttpResponse("ok")


urlpatterns = [
    path("login/", empty_view, name="login"),
    path("csrf-page/", csrf_page),
    path("csrf-mutation/", csrf_mutation),
]


@override_settings(ROOT_URLCONF=__name__)
class BrowserCsrfContractTests(SimpleTestCase):
    def test_base_page_token_can_authorize_a_browser_mutation(self):
        client = Client(enforce_csrf_checks=True)

        page = client.get("/csrf-page/")
        body = page.content.decode()
        token = re.search(
            r'<meta name="csrf-token" content="([^\"]+)">',
            body,
        ).group(1)

        self.assertIn("csrftoken", page.cookies)
        self.assertIn('/static/dashboard/js/shared/csrf.js', body)
        self.assertEqual(client.post("/csrf-mutation/").status_code, 403)
        self.assertEqual(
            client.post(
                "/csrf-mutation/",
                HTTP_X_CSRFTOKEN=token,
            ).status_code,
            200,
        )


class ProductionMutationCsrfTests(TestCase):
    def test_delivery_delete_requires_token_from_deliveries_page(self):
        client = Client(enforce_csrf_checks=True)
        user = get_user_model().objects.create_user(username="delivery-owner")
        delivery = Delivery.objects.create(
            user=user,
            filename="file-that-does-not-exist.zip",
            size_bytes=1,
        )
        client.force_login(user)

        with TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root,
        ):
            tokenless_response = client.post(
                reverse("delivery_delete"),
                {"ids": delivery.pk},
            )
            delivery.refresh_from_db()
            self.assertEqual(tokenless_response.status_code, 403)
            self.assertFalse(delivery.is_deleted)

            deliveries_page = client.get(reverse("deliveries"))
            body = deliveries_page.content.decode()
            token = re.search(
                r'<meta name="csrf-token" content="([^\"]+)">',
                body,
            ).group(1)

            self.assertEqual(deliveries_page.status_code, 200)
            self.assertIn("csrftoken", deliveries_page.cookies)
            authorized_response = client.post(
                reverse("delivery_delete"),
                {"ids": delivery.pk},
                HTTP_X_CSRFTOKEN=token,
            )

        delivery.refresh_from_db()
        self.assertEqual(authorized_response.status_code, 200)
        self.assertTrue(delivery.is_deleted)
