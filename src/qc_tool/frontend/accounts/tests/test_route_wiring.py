from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job


class ProtectedMutationRouteTests(TestCase):
    mutation_routes = (
        "delivery_delete",
        "create_job",
        "resumable_upload",
        "delivery_submit",
    )

    def remove_canonical_roles(self, user):
        user.groups.through.objects.filter(
            user_id=user.pk,
            group__name__in=Role.values(),
        ).delete()

    def assert_no_delivery_or_job_mutation(self):
        self.assertEqual(Delivery.objects.count(), 0)
        self.assertEqual(Job.objects.count(), 0)

    def test_anonymous_users_are_redirected_before_mutation_handlers_run(self):
        for route_name in self.mutation_routes:
            with self.subTest(route_name=route_name):
                response = self.client.post(reverse(route_name))
                self.assertEqual(response.status_code, 302)
                self.assertIn("/accounts/login/", response.url)

        self.assert_no_delivery_or_job_mutation()

    def test_ungrouped_users_are_denied_by_wired_route_permissions(self):
        for index, route_name in enumerate(self.mutation_routes):
            with self.subTest(route_name=route_name):
                user = get_user_model().objects.create_user(
                    username=f"ungrouped-{index}",
                )
                self.client.force_login(user)
                self.remove_canonical_roles(user)
                response = self.client.post(reverse(route_name))
                self.assertEqual(response.status_code, 403)
                self.client.logout()

        self.assert_no_delivery_or_job_mutation()
