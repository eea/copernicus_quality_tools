import json
from unittest.mock import Mock
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import TestCase
from django.urls import resolve
from django.urls import reverse

from qc_tool.frontend.accounts.authentication.api_keys import digest_api_key
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.models import ApiUser
from qc_tool.frontend.dashboard import urls as dashboard_urls
from qc_tool.frontend.dashboard.access.routes import PRIVATE_ROUTE_POLICIES
from qc_tool.frontend.dashboard.access.routes import PUBLIC_ROUTE_POLICIES
from qc_tool.frontend.dashboard.access.routes import ROUTE_POLICIES
from qc_tool.frontend.dashboard.access.routes.policies import AuthenticationMode
from qc_tool.frontend.dashboard.access.routes.policies import DenialResponse
from qc_tool.frontend.dashboard.access.routes.policies import RoutePolicy
from qc_tool.frontend.dashboard.access.routes.policies import RouteVisibility
from qc_tool.frontend.dashboard.access.routes.policies import apply_route_policy


VIEW = AccountPermission.VIEW_DELIVERIES
UPLOAD = AccountPermission.UPLOAD_DELIVERY
RUN_QC = AccountPermission.RUN_QC
DELETE = AccountPermission.DELETE_DELIVERY
SUBMIT = AccountPermission.SUBMIT_DELIVERY
MANAGE_CONFIGURATION = AccountPermission.MANAGE_CONFIGURATION

PUBLIC = RouteVisibility.PUBLIC
PRIVATE = RouteVisibility.PRIVATE
NONE = AuthenticationMode.NONE
SESSION = AuthenticationMode.SESSION
API_KEY = AuthenticationMode.API_KEY
WORKER_TOKEN = AuthenticationMode.WORKER_TOKEN
LOGIN_REDIRECT = DenialResponse.LOGIN_REDIRECT
JSON = DenialResponse.JSON
STATUS_ONLY = DenialResponse.STATUS_ONLY


# Independent from the production registry: every URL needs an explicit access
# decision in both implementation and tests.
EXPECTED_POLICIES = {
    "deliveries": (PRIVATE, SESSION, ("GET",), VIEW, LOGIN_REDIRECT),
    "export_deliveries_excel": (
        PRIVATE,
        SESSION,
        ("GET",),
        VIEW,
        LOGIN_REDIRECT,
    ),
    "download_delivery_file": (
        PRIVATE,
        SESSION,
        ("GET",),
        VIEW,
        LOGIN_REDIRECT,
    ),
    "job_report_pdf": (PRIVATE, SESSION, ("GET",), VIEW, LOGIN_REDIRECT),
    "job_combined_log": (PRIVATE, SESSION, ("GET",), VIEW, LOGIN_REDIRECT),
    "file_upload": (PRIVATE, SESSION, ("GET",), UPLOAD, LOGIN_REDIRECT),
    "job_history": (PRIVATE, SESSION, ("GET",), VIEW, LOGIN_REDIRECT),
    "boundaries": (
        PRIVATE,
        SESSION,
        ("GET",),
        MANAGE_CONFIGURATION,
        LOGIN_REDIRECT,
    ),
    "boundaries_upload": (
        PRIVATE,
        SESSION,
        ("GET",),
        MANAGE_CONFIGURATION,
        LOGIN_REDIRECT,
    ),
    "setup_job": (PRIVATE, SESSION, ("GET",), RUN_QC, LOGIN_REDIRECT),
    "show_result": (PRIVATE, SESSION, ("GET",), VIEW, LOGIN_REDIRECT),
    "get_attachment": (PRIVATE, SESSION, ("GET",), VIEW, LOGIN_REDIRECT),
    "announcement": (
        PRIVATE,
        SESSION,
        ("GET", "POST"),
        MANAGE_CONFIGURATION,
        LOGIN_REDIRECT,
    ),
    "deliveries_json": (PRIVATE, SESSION, ("GET",), VIEW, JSON),
    "job_history_json": (PRIVATE, SESSION, ("GET",), VIEW, JSON),
    "delivery_delete": (PRIVATE, SESSION, ("POST",), DELETE, JSON),
    "delivery_submit": (PRIVATE, SESSION, ("POST",), SUBMIT, JSON),
    "delivery_submit_batch": (PRIVATE, SESSION, ("POST",), SUBMIT, JSON),
    "job_info_json": (PRIVATE, SESSION, ("GET",), VIEW, JSON),
    "product_definition_json": (PRIVATE, SESSION, ("GET",), VIEW, JSON),
    "product_list_json": (PRIVATE, SESSION, ("GET",), VIEW, JSON),
    "product_descriptions_dropdown": (
        PRIVATE,
        SESSION,
        ("GET",),
        VIEW,
        JSON,
    ),
    "job_report_json": (PRIVATE, SESSION, ("GET",), VIEW, JSON),
    "resumable_upload": (
        PRIVATE,
        SESSION,
        ("GET", "POST"),
        UPLOAD,
        JSON,
    ),
    "job_delete": (PRIVATE, SESSION, ("POST",), DELETE, JSON),
    "update_job": (PRIVATE, SESSION, ("POST",), VIEW, JSON),
    "boundaries_json": (
        PRIVATE,
        SESSION,
        ("GET",),
        MANAGE_CONFIGURATION,
        JSON,
    ),
    "boundaries_upload_data": (
        PRIVATE,
        SESSION,
        ("POST",),
        MANAGE_CONFIGURATION,
        JSON,
    ),
    "create_job": (PRIVATE, SESSION, ("POST",), RUN_QC, JSON),
    "api_homepage": (PUBLIC, NONE, ("GET",), None, None),
    "api_openapi_json": (PUBLIC, NONE, ("GET",), None, None),
    "api_register_delivery": (PRIVATE, API_KEY, ("POST",), UPLOAD, JSON),
    "api_register_delivery_s3": (PRIVATE, API_KEY, ("POST",), UPLOAD, JSON),
    "api_delivery_list": (PRIVATE, API_KEY, ("GET",), VIEW, JSON),
    "api_product_list": (PRIVATE, API_KEY, ("GET",), VIEW, JSON),
    "api_product_info": (PRIVATE, API_KEY, ("GET",), VIEW, JSON),
    "api_create_job": (PRIVATE, API_KEY, ("POST",), RUN_QC, JSON),
    "api_job_result": (PRIVATE, API_KEY, ("GET",), VIEW, JSON),
    "api_job_result_pdf": (PRIVATE, API_KEY, ("GET",), VIEW, JSON),
    "api_job_history": (PRIVATE, API_KEY, ("GET",), VIEW, JSON),
    "api_submit_delivery_to_eea": (
        PRIVATE,
        API_KEY,
        ("POST",),
        SUBMIT,
        JSON,
    ),
    "pull_job": (PRIVATE, WORKER_TOKEN, ("POST",), None, STATUS_ONLY),
}


ROUTE_ARGS = {
    "api_product_info": ("fixtureless",),
    "api_job_result": ("00000000-0000-0000-0000-000000000001",),
    "api_job_result_pdf": ("00000000-0000-0000-0000-000000000001",),
    "api_job_history": (1,),
    "job_history_json": (1,),
    "download_delivery_file": (1,),
    "job_info_json": ("fixtureless",),
    "product_definition_json": ("fixtureless",),
    "job_report_json": ("00000000-0000-0000-0000-000000000001",),
    "job_report_pdf": ("00000000-0000-0000-0000-000000000001",),
    "job_combined_log": ("00000000-0000-0000-0000-000000000001",),
    "job_history": (1,),
    "update_job": ("00000000-0000-0000-0000-000000000001",),
    "boundaries_json": ("raster",),
    "show_result": ("00000000-0000-0000-0000-000000000001",),
    "get_attachment": (
        "00000000-0000-0000-0000-000000000001",
        "details.txt",
    ),
}


def route_url(route_name):
    return reverse(route_name, args=ROUTE_ARGS.get(route_name, ()))


def request_route(client, route_name, method, *, query="", headers=None):
    return getattr(client, method.lower())(
        route_url(route_name) + query,
        **(headers or {}),
    )


class RoutePolicyValidationTests(TestCase):
    def make_policy(self, **overrides):
        values = {
            "visibility": PRIVATE,
            "authentication": SESSION,
            "methods": ("GET",),
            "permission": VIEW,
            "denial_response": LOGIN_REDIRECT,
        }
        values.update(overrides)
        return RoutePolicy(**values)

    def test_methods_are_required_uppercase_and_unique(self):
        for methods in ((), ("get",), ("GET", "GET")):
            with self.subTest(methods=methods):
                with self.assertRaises(ValueError):
                    self.make_policy(methods=methods)

    def test_public_routes_cannot_declare_private_access_details(self):
        invalid_overrides = (
            {"authentication": SESSION},
            {"permission": VIEW},
            {"denial_response": JSON},
        )
        for overrides in invalid_overrides:
            values = {
                "visibility": PUBLIC,
                "authentication": NONE,
                "methods": ("GET",),
                "permission": None,
                "denial_response": None,
            }
            values.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    RoutePolicy(**values)

    def test_private_routes_require_authentication_and_denial_contract(self):
        with self.assertRaises(ValueError):
            self.make_policy(authentication=NONE)
        with self.assertRaises(ValueError):
            self.make_policy(denial_response=None)

    def test_account_authentication_requires_an_account_permission(self):
        for authentication in (SESSION, API_KEY):
            with self.subTest(authentication=authentication):
                with self.assertRaises(ValueError):
                    self.make_policy(
                        authentication=authentication,
                        permission=None,
                        denial_response=JSON,
                    )

    def test_worker_authentication_rejects_account_permissions(self):
        with self.assertRaises(ValueError):
            self.make_policy(
                authentication=WORKER_TOKEN,
                permission=VIEW,
                denial_response=STATUS_ONLY,
            )

        policy = self.make_policy(
            authentication=WORKER_TOKEN,
            permission=None,
            denial_response=STATUS_ONLY,
        )
        self.assertIs(policy.authentication, WORKER_TOKEN)

    def test_authentication_modes_reject_incompatible_denial_formats(self):
        for authentication, permission, denial_response in (
            (API_KEY, VIEW, LOGIN_REDIRECT),
            (WORKER_TOKEN, None, JSON),
        ):
            with self.subTest(authentication=authentication):
                with self.assertRaises(ValueError):
                    self.make_policy(
                        authentication=authentication,
                        permission=permission,
                        denial_response=denial_response,
                    )

    def test_global_middleware_denies_an_unclassified_anonymous_view(self):
        request = RequestFactory().get("/future-unclassified-view/")
        request.user = AnonymousUser()
        middleware = LoginRequiredMiddleware(lambda _request: HttpResponse())

        response = middleware.process_view(
            request,
            lambda _request: HttpResponse(),
            (),
            {},
        )

        self.assertEqual(response.status_code, 302)
        location = urlsplit(response["Location"])
        self.assertEqual(location.path, reverse("login"))
        self.assertEqual(
            parse_qs(location.query),
            {"next": ["/future-unclassified-view/"]},
        )


class RoutePolicyRegistryTests(TestCase):
    def test_registry_is_an_explicit_policy_for_all_42_dashboard_routes(self):
        self.assertEqual(len(EXPECTED_POLICIES), 42)
        self.assertEqual(set(ROUTE_POLICIES), set(EXPECTED_POLICIES))

        for route_name, expected in EXPECTED_POLICIES.items():
            with self.subTest(route_name=route_name):
                policy = ROUTE_POLICIES[route_name]
                actual = (
                    policy.visibility,
                    policy.authentication,
                    policy.methods,
                    policy.permission,
                    policy.denial_response,
                )
                self.assertEqual(actual, expected)

    def test_public_and_private_registries_are_disjoint_and_complete(self):
        self.assertFalse(set(PUBLIC_ROUTE_POLICIES) & set(PRIVATE_ROUTE_POLICIES))
        self.assertEqual(
            set(ROUTE_POLICIES),
            set(PUBLIC_ROUTE_POLICIES) | set(PRIVATE_ROUTE_POLICIES),
        )
        self.assertEqual(
            set(PUBLIC_ROUTE_POLICIES),
            {"api_homepage", "api_openapi_json"},
        )
        self.assertEqual(
            set(PRIVATE_ROUTE_POLICIES),
            set(EXPECTED_POLICIES) - set(PUBLIC_ROUTE_POLICIES),
        )

    def test_every_named_dashboard_url_is_wired_through_its_policy(self):
        named_patterns = {
            pattern.name: pattern
            for pattern in dashboard_urls.urlpatterns
            if getattr(pattern, "name", None) is not None
        }
        self.assertEqual(set(named_patterns), set(EXPECTED_POLICIES))

        for route_name in EXPECTED_POLICIES:
            with self.subTest(route_name=route_name):
                policy = ROUTE_POLICIES[route_name]
                pattern_callback = named_patterns[route_name].callback
                self.assertEqual(
                    getattr(pattern_callback, "_qc_tool_route_policy", None),
                    policy,
                )
                self.assertIs(
                    getattr(pattern_callback, "login_required", None),
                    False,
                    "The route registry must own authentication before the "
                    "global session-only middleware runs.",
                )

                resolved = resolve(route_url(route_name))
                self.assertEqual(resolved.url_name, route_name)
                self.assertEqual(
                    getattr(resolved.func, "_qc_tool_route_policy", None),
                    policy,
                )
                self.assertIs(
                    getattr(resolved.func, "login_required", None),
                    False,
                )


class RoutePolicyAuthorizationOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.unprivileged = get_user_model().objects.create_user(
            username="policy-order-unprivileged",
        )
        cls.unprivileged.groups.through.objects.filter(
            user_id=cls.unprivileged.pk
        ).delete()

    def setUp(self):
        self.factory = RequestFactory()

    def test_session_permission_is_checked_before_html_view_runs(self):
        request = self.factory.get("/private/")
        request.user = self.unprivileged
        view = Mock(return_value=HttpResponse())
        policy = RoutePolicy(
            visibility=PRIVATE,
            authentication=SESSION,
            methods=("GET",),
            permission=VIEW,
            denial_response=LOGIN_REDIRECT,
        )

        with self.assertRaises(PermissionDenied):
            apply_route_policy(policy, view)(request)
        view.assert_not_called()

    def test_session_authentication_is_checked_before_data_view_runs(self):
        request = self.factory.get("/private/data/")
        request.user = AnonymousUser()
        view = Mock(return_value=HttpResponse())
        policy = RoutePolicy(
            visibility=PRIVATE,
            authentication=SESSION,
            methods=("GET",),
            permission=VIEW,
            denial_response=JSON,
        )

        response = apply_route_policy(policy, view)(request)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            json.loads(response.content)["code"],
            "authentication_required",
        )
        view.assert_not_called()

    def test_api_key_authentication_is_checked_before_view_runs(self):
        request = self.factory.get("/private/api/")
        request.user = AnonymousUser()
        view = Mock(return_value=HttpResponse())
        policy = RoutePolicy(
            visibility=PRIVATE,
            authentication=API_KEY,
            methods=("GET",),
            permission=VIEW,
            denial_response=JSON,
        )

        response = apply_route_policy(policy, view)(request)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'Bearer realm="QC Tool API"',
        )
        view.assert_not_called()

    def test_worker_authentication_is_checked_before_view_runs(self):
        request = self.factory.post("/private/worker/")
        request.user = AnonymousUser()
        view = Mock(return_value=HttpResponse())
        policy = RoutePolicy(
            visibility=PRIVATE,
            authentication=WORKER_TOKEN,
            methods=("POST",),
            permission=None,
            denial_response=STATUS_ONLY,
        )

        response = apply_route_policy(policy, view)(request)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'WorkerToken realm="QC Tool Worker"',
        )
        view.assert_not_called()


class AnonymousRoutePolicyTests(TestCase):
    def route_names_for(self, *, authentication=None, denial_response=None):
        return [
            name
            for name, policy in ROUTE_POLICIES.items()
            if (
                (authentication is None or policy.authentication is authentication)
                and (
                    denial_response is None
                    or policy.denial_response is denial_response
                )
            )
        ]

    def test_private_session_pages_redirect_with_the_exact_return_path(self):
        login_path = reverse("login")
        route_names = self.route_names_for(
            authentication=SESSION,
            denial_response=LOGIN_REDIRECT,
        )

        for route_name in route_names:
            with self.subTest(route_name=route_name):
                target = route_url(route_name)
                response = request_route(self.client, route_name, "GET")
                location = urlsplit(response["Location"])

                self.assertEqual(response.status_code, 302)
                self.assertEqual(location.path, login_path)
                self.assertEqual(parse_qs(location.query), {"next": [target]})

    def test_private_session_data_routes_return_a_structured_401(self):
        login_path = reverse("login")
        route_names = self.route_names_for(
            authentication=SESSION,
            denial_response=JSON,
        )

        for route_name in route_names:
            policy = ROUTE_POLICIES[route_name]
            method = policy.methods[0]
            with self.subTest(route_name=route_name, method=method):
                response = request_route(self.client, route_name, method)

                self.assertEqual(response.status_code, 401)
                self.assertEqual(response["X-Login-URL"], login_path)
                self.assertEqual(
                    response.json(),
                    {
                        "status": "error",
                        "code": "authentication_required",
                        "message": (
                            "Your session has expired. Please sign in again."
                        ),
                        "login_url": login_path,
                    },
                )

    def test_api_key_routes_challenge_missing_credentials(self):
        for route_name in self.route_names_for(authentication=API_KEY):
            policy = ROUTE_POLICIES[route_name]
            method = policy.methods[0]
            with self.subTest(route_name=route_name, method=method):
                response = request_route(self.client, route_name, method)

                self.assertEqual(response.status_code, 401)
                self.assertEqual(
                    response["WWW-Authenticate"],
                    'Bearer realm="QC Tool API"',
                )
                self.assertEqual(response.json()["status"], "error")

    def test_only_the_two_documentation_routes_are_public(self):
        public_routes = [
            name
            for name, policy in ROUTE_POLICIES.items()
            if policy.visibility is PUBLIC
        ]

        self.assertEqual(
            set(public_routes),
            {"api_homepage", "api_openapi_json"},
        )
        for route_name in public_routes:
            with self.subTest(route_name=route_name):
                response = request_route(self.client, route_name, "GET")
                self.assertEqual(response.status_code, 200)

    def test_worker_route_challenges_a_missing_worker_token(self):
        response = request_route(self.client, "pull_job", "POST")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'WorkerToken realm="QC Tool Worker"',
        )
        self.assertEqual(response.content, b"")


class AuthenticatedRoutePolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.unprivileged = get_user_model().objects.create_user(
            username="route-policy-unprivileged",
        )
        # Required-role signals restore the default group after normal M2M
        # removal. Delete through the join table to exercise fail-closed
        # behavior for legacy or corrupt rows.
        cls.unprivileged.groups.through.objects.filter(
            user_id=cls.unprivileged.pk
        ).delete()
        cls.unprivileged_api_key = "qct_" + ("U" * 43)
        ApiUser.objects.create(
            user=cls.unprivileged,
            api_key=digest_api_key(cls.unprivileged_api_key),
        )

        cls.superuser = get_user_model().objects.create_superuser(
            username="route-policy-superuser",
            email="superuser@example.com",
            password="unused",
        )
        cls.superuser_api_key = "qct_" + ("S" * 43)
        ApiUser.objects.create(
            user=cls.superuser,
            api_key=digest_api_key(cls.superuser_api_key),
        )

    def route_names_for(self, *, authentication=None, denial_response=None):
        return [
            name
            for name, policy in ROUTE_POLICIES.items()
            if (
                (authentication is None or policy.authentication is authentication)
                and (
                    denial_response is None
                    or policy.denial_response is denial_response
                )
            )
        ]

    def test_unprivileged_session_user_gets_denial_appropriate_403(self):
        self.client.force_login(self.unprivileged)
        # force_login updates last_login and restores the required default
        # group through the user post-save invariant.
        self.unprivileged.groups.through.objects.filter(
            user_id=self.unprivileged.pk
        ).delete()

        for denial_response in (LOGIN_REDIRECT, JSON):
            route_names = self.route_names_for(
                authentication=SESSION,
                denial_response=denial_response,
            )
            for route_name in route_names:
                policy = ROUTE_POLICIES[route_name]
                method = policy.methods[0]
                with self.subTest(
                    route_name=route_name,
                    denial_response=denial_response,
                    method=method,
                ):
                    response = request_route(self.client, route_name, method)
                    self.assertEqual(response.status_code, 403)
                    if denial_response is JSON:
                        self.assertEqual(
                            response.json()["code"],
                            "permission_denied",
                        )

    def test_unprivileged_api_principal_gets_json_403(self):
        for route_name in self.route_names_for(authentication=API_KEY):
            policy = ROUTE_POLICIES[route_name]
            method = policy.methods[0]
            with self.subTest(route_name=route_name, method=method):
                response = request_route(
                    self.client,
                    route_name,
                    method,
                    headers={
                        "HTTP_AUTHORIZATION": (
                            f"Bearer {self.unprivileged_api_key}"
                        )
                    },
                )

                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["status"], "error")

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=True,
    )
    def test_every_route_rejects_an_unsupported_method(self, _auth_worker):
        self.client.force_login(self.superuser)
        for route_name, policy in ROUTE_POLICIES.items():
            method = "PATCH"
            self.assertNotIn(method, policy.methods)
            if policy.authentication is API_KEY:
                headers = {
                    "HTTP_AUTHORIZATION": f"Bearer {self.superuser_api_key}"
                }
            elif policy.authentication is WORKER_TOKEN:
                headers = {
                    "HTTP_AUTHORIZATION": "WorkerToken valid-worker-token"
                }
            else:
                headers = {}

            with self.subTest(route_name=route_name):
                response = request_route(
                    self.client,
                    route_name,
                    method,
                    headers=headers,
                )
                self.assertEqual(response.status_code, 405)
