import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import TestCase

from qc_tool.frontend.accounts.authentication.api_keys import digest_api_key
from qc_tool.frontend.accounts.authentication.decorators import api_key_required
from qc_tool.frontend.accounts.authorization.decorators import (
    account_json_permission_required,
    account_permission_required,
)
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.permissions import DEFAULT_PERMISSIONS
from qc_tool.frontend.accounts.authorization.permissions import permissions_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import ApiUser
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


def ok_view(_request):
    return HttpResponse("ok")


def api_key(character):
    return "qct_" + (character * 43)


class PermissionResolutionTests(TestCase):
    def test_default_group_resolves_through_django_permission_backend(self):
        user = get_user_model().objects.create_user(username="default-policy")

        self.assertEqual(
            permissions_for(user),
            DEFAULT_PERMISSIONS,
        )

    def test_direct_user_permission_is_additive(self):
        user = get_user_model().objects.create_user(username="direct-policy")
        permission = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.MANAGE_CONFIGURATION.value,
        )
        user.user_permissions.add(permission)

        self.assertEqual(
            permissions_for(user),
            DEFAULT_PERMISSIONS | {AccountPermission.MANAGE_CONFIGURATION},
        )

    def test_ungrouped_user_has_no_grants(self):
        user = get_user_model().objects.create_user(username="ungrouped-policy")
        user.groups.through.objects.filter(user_id=user.pk).delete()

        self.assertEqual(
            permissions_for(user),
            frozenset(),
        )

    def test_anonymous_and_inactive_users_have_no_grants(self):
        inactive = get_user_model().objects.create_user(
            username="inactive-policy",
            is_active=False,
        )

        self.assertEqual(permissions_for(AnonymousUser()), frozenset())
        self.assertEqual(permissions_for(inactive), frozenset())


class PermissionDecoratorTests(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def create_user(self, username, *, role=None, is_superuser=False):
        user = get_user_model().objects.create_user(
            username=username,
            is_staff=is_superuser,
            is_superuser=is_superuser,
        )
        if role is not None:
            group, _created = Group.objects.get_or_create(name=role.value)
            user.groups.add(group)
        return user

    def remove_canonical_roles(self, user):
        user.groups.through.objects.filter(
            user_id=user.pk,
            group__name__in=Role.values(),
        ).delete()

    def test_browser_permission_decorator_fails_closed_without_role(self):
        view = account_permission_required(
            AccountPermission.UPLOAD_DELIVERY
        )(ok_view)
        request = self.request_factory.get("/upload/")
        request.user = self.create_user("ungrouped-browser")
        self.remove_canonical_roles(request.user)

        with self.assertRaises(PermissionDenied):
            view(request)

    def test_session_responses_are_private_for_success_and_login_redirects(self):
        view = account_permission_required(
            AccountPermission.UPLOAD_DELIVERY
        )(ok_view)
        authorized_request = self.request_factory.get("/upload/")
        authorized_request.user = self.create_user("private-browser")
        authorized = view(authorized_request)

        anonymous_request = self.request_factory.get("/upload/")
        anonymous_request.user = AnonymousUser()
        anonymous = view(anonymous_request)

        for response in (authorized, anonymous):
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["Pragma"], "no-cache")
            self.assertIn("Cookie", response["Vary"])

    def test_session_json_denial_is_private_and_varies_on_cookie(self):
        view = account_json_permission_required(
            AccountPermission.UPLOAD_DELIVERY
        )(ok_view)
        request = self.request_factory.get("/data/upload/")
        request.user = AnonymousUser()

        response = view(request)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("Cookie", response["Vary"])

    def test_api_permission_allows_default_and_admin_roles(self):
        view = api_key_required(permission=AccountPermission.RUN_QC)(ok_view)
        default_user = self.create_user("default-api")
        administrator = self.create_user("admin-api", role=Role.ADMIN)
        default_key = api_key("D")
        admin_key = api_key("A")
        ApiUser.objects.create(
            user=default_user,
            api_key=digest_api_key(default_key),
        )
        ApiUser.objects.create(
            user=administrator,
            api_key=digest_api_key(admin_key),
        )

        default_response = view(
            self.request_factory.get(
                "/api/job",
                HTTP_AUTHORIZATION=f"Bearer {default_key}",
            )
        )
        admin_response = view(
            self.request_factory.get(
                "/api/job",
                HTTP_AUTHORIZATION=f"Bearer {admin_key}",
            )
        )

        self.assertEqual(default_response.status_code, 200)
        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual(default_response["Cache-Control"], "private, no-store")
        self.assertEqual(default_response["Pragma"], "no-cache")
        self.assertIn("Authorization", default_response["Vary"])

    def test_api_permission_fails_closed_without_role(self):
        view = api_key_required(permission=AccountPermission.RUN_QC)(ok_view)
        user = self.create_user("ungrouped-api")
        self.remove_canonical_roles(user)
        raw_key = api_key("U")
        ApiUser.objects.create(user=user, api_key=digest_api_key(raw_key))

        response = view(
            self.request_factory.get(
                "/api/job",
                HTTP_AUTHORIZATION=f"Bearer {raw_key}",
            )
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            json.loads(response.content)["code"],
            "permission_denied",
        )
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("Authorization", response["Vary"])

    def test_api_missing_and_invalid_credentials_use_bearer_challenges(self):
        view = api_key_required(permission=AccountPermission.RUN_QC)(ok_view)

        missing = view(self.request_factory.get("/api/job"))
        invalid = view(
            self.request_factory.get(
                "/api/job",
                HTTP_AUTHORIZATION=f"Bearer {api_key('X')}",
            )
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(
            missing["WWW-Authenticate"],
            'Bearer realm="QC Tool API"',
        )
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(
            json.loads(invalid.content)["code"],
            "invalid_token",
        )
        self.assertIn('error="invalid_token"', invalid["WWW-Authenticate"])
        for response in (missing, invalid):
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["Pragma"], "no-cache")
            self.assertIn("Authorization", response["Vary"])

    def test_api_query_credentials_are_rejected_even_with_valid_header(self):
        view = api_key_required(permission=AccountPermission.RUN_QC)(ok_view)
        user = self.create_user("query-api")
        raw_key = api_key("Q")
        ApiUser.objects.create(user=user, api_key=digest_api_key(raw_key))

        response = view(
            self.request_factory.get(
                "/api/job",
                {"apikey": raw_key},
                HTTP_AUTHORIZATION=f"Bearer {raw_key}",
            )
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            json.loads(response.content)["code"],
            "query_parameter_not_allowed",
        )
