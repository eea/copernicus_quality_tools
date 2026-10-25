"""Curated database inspection preserves secrets, permissions and write fences."""

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.db import DatabaseError, connection
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers import service
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.dashboard.access.maintenance import is_maintenance_control_request
from qc_tool.frontend.dashboard.models import Delivery, Job, S3Info
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.database_admin.presentation import record_url
from qc_tool.frontend.dashboard.services.database_admin.resources import resource_for, resources


class DatabaseResourcePolicyTests(SimpleTestCase):
    def test_every_managed_table_has_one_explicit_policy_including_auth_joins(self):
        managed = {model._meta.db_table for model in apps.get_models(include_auto_created=True)
                   if model._meta.managed and not model._meta.proxy}
        policies = resources()
        self.assertEqual(len(policies), 24)
        self.assertEqual(len({resource.table for resource in policies}), len(policies))
        self.assertEqual({resource.table for resource in policies}, managed)
        self.assertEqual({resource.table for resource in policies if resource.model._meta.auto_created},
                         {"auth_user_groups", "auth_user_user_permissions", "auth_group_permissions"})
        self.assertIsNone(resource_for("django_migrations"))
        self.assertIsNone(resource_for("pg_authid"))

    def test_sensitive_fields_have_no_list_detail_or_search_disclosure_policy(self):
        protected = {
            get_user_model(): {"password"}, PersonalAccessToken: {"secret_digest"},
            S3Info: {"credential_ref"}, Session: {"session_key", "session_data"},
            TransferReceipt: {"summary"},
        }
        for model, forbidden in protected.items():
            resource = resource_for(model._meta.db_table)
            with self.subTest(model=model):
                self.assertFalse(forbidden.intersection(resource.fields))
                self.assertFalse(forbidden.intersection(resource.columns))
                self.assertFalse(forbidden.intersection(resource.search))
        self.assertFalse(resource_for(Session._meta.db_table).detail)
        self.assertEqual(record_url(resource_for(Session._meta.db_table), "private-session-key"), "")


@override_settings(MAINTENANCE_MODE=False)
class AdminDatabaseRecordTests(TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory(prefix="qc-database-browser-")))
        self.enterContext(override_settings(QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
                                           QC_TOOL_TRANSFER_DIR=directory / "transfers"))
        User = get_user_model()
        self.operator = User.objects.create_user("database-browser-admin", "operator@example.test")
        self.operator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.operator.refresh_from_db()
        self.owner = User.objects.create_user("database-browser-owner", "owner@example.test", "test-password")
        self.client.force_login(self.operator)
        self.delivery = Delivery.objects.create(user=self.owner, filename="retained-input.zip", size_bytes=42)
        self.job = Job.objects.create(delivery=self.delivery, requested_by=self.owner, job_status="ok",
                                      product_ident="browser-product", product_description="Browser product")

    def table_url(self, model):
        return reverse("admin_database_records", args=(model._meta.db_table,))

    def detail_url(self, obj):
        return reverse("admin_database_record", args=(obj._meta.db_table, obj.pk))

    def ready(self):
        generation = maintenance.enable(self.operator, 0)["generation"]
        self.assertEqual(maintenance.advance(generation)["phase"], "ready")

    def test_qc_administrator_can_browse_every_allowlisted_table_without_superuser(self):
        self.assertFalse(self.operator.is_superuser)
        for resource in resources():
            with self.subTest(table=resource.table):
                response = self.client.get(reverse("admin_database_records", args=(resource.table,)))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["resource"], resource)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("private", response["Cache-Control"])

    def test_home_checks_schema_once_and_discovers_tables_without_probing_backup_tools(self):
        with (patch.object(service, "schema_readiness", return_value={"ready": True, "message": "Schema matches."}) as schema,
              patch.object(service, "database_availability") as tools):
            response = self.client.get(reverse("admin_data_transfer"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["table_count"], 24)
        for resource in resources():
            self.assertContains(response, f'href="{reverse("admin_database_records", args=(resource.table,))}"')
        schema.assert_called_once_with()
        tools.assert_not_called()

    def test_home_search_and_category_filter_only_classified_tables(self):
        response = self.client.get(reverse("admin_data_transfer"), {"q": "execution_job"})
        grouped = list(response.context["table_groups"])
        self.assertEqual([item["resource"].table for _category, items in grouped for item in items], ["execution_job"])
        response = self.client.get(reverse("admin_data_transfer"), {"category": "Publication & history"})
        self.assertTrue(list(response.context["table_groups"]))
        self.assertTrue(all(category == "Publication & history" for category, _items in response.context["table_groups"]))

    def test_home_prioritizes_records_backups_schema_check_and_maintenance(self):
        response = self.client.get(reverse("admin_data_transfer"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Database status</h1>", html=True)
        for identifier in ("database-transfers-heading",
                           "database-schema-heading", "database-maintenance-heading"):
            with self.subTest(identifier=identifier):
                self.assertContains(response, f'id="{identifier}"')
        for query in ("tab=backups", "tab=databases", "tab=activity"):
            self.assertContains(response, f'href="{reverse("admin_data_transfer")}?{query}"')
        self.assertContains(response, "In-place migrations are not available in v3.0.0.")
        self.assertContains(response, f'href="{reverse("admin_data_transfer")}?schema=check#database-schema-heading"')
        self.assertContains(response, '<details class="database-table-tools">')
        for parameters in ({"q": "execution_job"}, {"category": "Catalog"}, {"tables": "1"}):
            with self.subTest(parameters=parameters):
                opened = self.client.get(reverse("admin_data_transfer"), parameters)
                self.assertContains(opened, "<h1>Browse database records</h1>", html=True)
                self.assertContains(opened, 'id="database-records-heading"')
                self.assertContains(opened, "Back to Database status")
                self.assertNotContains(opened, '<details class="database-table-tools"')
                self.assertNotContains(opened, 'id="database-transfers-heading"')
                self.assertNotContains(opened, 'id="database-schema-heading"')
                self.assertNotContains(opened, 'id="database-maintenance-heading"')

    def test_schema_recheck_is_read_only_and_never_initializes(self):
        from unittest.mock import patch
        from qc_tool.database.deployment import SchemaInitializer
        from qc_tool.database.transfers import service
        with (patch.object(service, "schema_readiness", return_value={"ready": True, "message": "Schema is compatible."}) as check,
              patch.object(SchemaInitializer, "apply") as initialize,
              CaptureQueriesContext(connection) as queries):
            response = self.client.get(reverse("admin_data_transfer"), {"schema": "check"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Schema matches")
        check.assert_called_once_with()
        initialize.assert_not_called()
        self.assertEqual([item["sql"] for item in queries if item["sql"].lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))], [])
        for action in ("apply", "migrate", "repair", "reset"):
            self.assertNotContains(response, f'value="{action}"')

    def test_home_shows_schema_check_time_and_expected_contract_without_extra_action(self):
        checked = "2026-10-23T12:34:56+00:00"
        with patch.object(service, "schema_readiness", return_value={
            "ready": True, "state": "ready", "message": "The database matches current models.",
            "checked_at": checked, "contract_version": "qc-records-v1",
        }) as check:
            response = self.client.get(reverse("admin_data_transfer"))
        check.assert_called_once_with()
        self.assertContains(response, "Schema matches")
        self.assertContains(response, f'<time datetime="{checked}">')
        self.assertContains(response, "Expected contract:")
        self.assertContains(response, "qc-records-v1")
        self.assertIn("no-store", response["Cache-Control"])

    def test_home_displays_actual_schema_drift_and_keeps_backup_navigation_available(self):
        with patch.object(service, "schema_readiness", return_value={
            "ready": False, "state": "drift", "message": "Missing column execution_job.example_field.",
            "checked_at": "2026-10-23T12:34:56+00:00", "contract_version": "qc-records-v1",
        }):
            response = self.client.get(reverse("admin_data_transfer"))
        self.assertContains(response, "Missing column execution_job.example_field.")
        self.assertContains(response, 'role="alert"')
        self.assertNotContains(response, ">Schema matches</p>")
        self.assertContains(response, "qc-records-v1")
        self.assertContains(response, f'href="{reverse("admin_data_transfer")}?tab=backups"')
        self.assertContains(response, "Create a backup")
        self.assertNotContains(response, 'value="repair"')

    def test_schema_inspection_is_limited_to_database_landing(self):
        with patch.object(service, "schema_readiness") as check:
            self.assertEqual(self.client.get(self.table_url(Delivery)).status_code, 200)
            self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
        check.assert_not_called()

    def test_table_browser_keeps_database_tasks_and_returns_to_the_table_directory(self):
        response = self.client.get(self.table_url(Delivery))
        self.assertEqual(response.context["admin_section"], "database")
        self.assertContains(response, 'aria-label="Database tasks"')
        self.assertEqual([item["label"] for item in response.context["database_sections"]],
                         ["Database status", "Back up & restore", "Manage databases", "Progress & history"])
        self.assertEqual([item["key"] for item in response.context["database_sections"] if item["current"]],
                         ["overview"])
        self.assertEqual(response.context["database_breadcrumbs"], [
            {"label": "Database status", "url": reverse("admin_data_transfer")},
            {"label": "Browse records", "url": reverse("admin_data_transfer") + "?tables=1#database-records-heading"},
            {"label": "Deliveries", "url": ""},
        ])
        self.assertContains(response, "Back to tables")
        self.assertContains(response, "<h1>Deliveries</h1>", html=True)

    def test_record_detail_keeps_a_complete_path_back_to_its_table_and_database_status(self):
        response = self.client.get(self.detail_url(self.delivery))
        self.assertContains(response, 'aria-label="Database tasks"')
        self.assertContains(response, "Back to Deliveries")
        self.assertEqual(response.context["database_back_url"], self.table_url(Delivery))
        self.assertEqual(response.context["database_page_title"], self.delivery.filename)
        self.assertEqual(response.context["database_breadcrumbs"][-2:], [
            {"label": "Deliveries", "url": self.table_url(Delivery)},
            {"label": "Record " + str(self.delivery.pk), "url": ""},
        ])
        self.assertContains(response, 'href="' + self.table_url(Delivery) + '"')

    def test_accounts_and_permission_browsers_keep_user_management_ownership(self):
        for model in (get_user_model(), Permission):
            with self.subTest(model=model):
                response = self.client.get(self.table_url(model))
                self.assertEqual(response.context["admin_section"], "users")
                self.assertNotContains(response, 'aria-label="Database tasks"')
                self.assertEqual(response.context["records_home_url"], reverse("admin_user_management"))
                self.assertEqual(response.context["database_breadcrumbs"][0], {
                    "label": "User management", "url": reverse("admin_user_management"),
                })
                self.assertContains(response, "Back to user management")
        response = self.client.get(self.detail_url(self.owner))
        self.assertEqual(response.context["admin_section"], "users")
        self.assertNotContains(response, 'aria-label="Database tasks"')
        self.assertEqual(response.context["database_back_url"], self.table_url(get_user_model()))
        self.assertContains(response, "Back to Users")

    def test_secret_fields_and_session_identifiers_never_reach_html_or_detail_links(self):
        token = PersonalAccessToken.objects.create(user=self.owner, name="Browser token", token_hint="qct_visible",
            secret_digest="sha256$" + "c" * 64, permission_snapshot=["upload_delivery"])
        source = S3Info.objects.create(host="https://objects.example.test", bucketname="deliveries",
                                      key_prefix="retained/", credential_ref="private-credential-reference")
        receipt = TransferReceipt.objects.create(package_id=uuid4(), operation_id=uuid4(),
            package_sha256="a" * 64, plan_sha256="b" * 64, profile="accounts", actor=self.operator,
            actor_name=self.operator.username, summary={"private": "receipt-private-summary"})
        session = Session.objects.create(session_key="browser-private-session-key",
            session_data="browser-private-signed-session-payload", expire_date=timezone.now())
        for obj, secret in ((self.owner, self.owner.password), (token, token.secret_digest),
                            (source, source.credential_ref), (receipt, "receipt-private-summary")):
            for url in (self.table_url(type(obj)), self.detail_url(obj)):
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, secret)
        response = self.client.get(self.table_url(Session))
        self.assertNotContains(response, session.session_key)
        self.assertNotContains(response, session.session_data)
        self.assertContains(response, sha256(session.pk.encode()).hexdigest()[:12])
        self.assertTrue(all(row["url"] == "" for row in response.context["rows"]))
        self.assertTrue(all(not cell["url"] for row in response.context["rows"] for cell in row["cells"]))
        self.assertEqual(self.client.get(self.detail_url(session)).status_code, 404)

    def test_search_and_pagination_preserve_related_filter_and_query(self):
        Delivery.objects.bulk_create([Delivery(user=self.owner, filename=f"paged-delivery-{number:02}.zip", size_bytes=1)
                                      for number in range(27)])
        get_user_model().objects.create_user("unrelated-browser-owner")
        response = self.client.get(self.table_url(Delivery), {"q": "paged-delivery", "page": 2,
            "related_field": "user_id", "related_value": self.owner.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].number, 2)
        self.assertEqual(response.context["page"].paginator.per_page, 25)
        self.assertEqual(response.context["page"].paginator.count, 27)
        self.assertEqual(len(response.context["rows"]), 2)
        self.assertEqual(parse_qs(response.context["pagination_query"]), {
            "q": ["paged-delivery"], "related_field": ["user_id"], "related_value": [str(self.owner.pk)],
        })

    def test_record_filters_can_be_cleared_independently_without_losing_context(self):
        response = self.client.get(self.table_url(Delivery), {"q": "retained", "page": 2,
            "related_field": "user_id", "related_value": self.owner.pk})
        self.assertEqual(parse_qs(urlsplit(response.context["clear_search_url"]).query), {
            "related_field": ["user_id"], "related_value": [str(self.owner.pk)],
        })
        self.assertEqual(parse_qs(urlsplit(response.context["clear_relation_url"]).query), {"q": ["retained"]})
        self.assertContains(response, "1 matching record")
        self.assertContains(response, "Remove relationship filter")
        self.assertContains(response, "Clear search")

    def test_detail_uses_allowed_title_and_keeps_raw_evidence_in_closed_technical_section(self):
        self.delivery.content_sha256 = "d" * 64
        self.delivery.save(update_fields=["content_sha256"])
        response = self.client.get(self.detail_url(self.delivery))
        self.assertEqual(response.context["record_heading"], self.delivery.filename)
        self.assertTrue(any(field["value"] == self.delivery.filename for field in response.context["ordinary_fields"]))
        self.assertTrue(any(field["value"] == self.delivery.content_sha256 for field in response.context["technical_fields"]))
        self.assertFalse(any(field["value"] == self.delivery.content_sha256 for field in response.context["ordinary_fields"]))
        self.assertContains(response, '<details class="database-technical-details">')
        self.assertNotContains(response, '<details class="database-technical-details" open>')
        self.assertContains(response, 'href="#record-connections"')

    def test_empty_search_explains_recovery_and_session_browser_explains_private_fields(self):
        response = self.client.get(self.table_url(Delivery), {"q": "no-such-browser-delivery"})
        self.assertContains(response, "No matching records")
        self.assertContains(response, "Try a different search or remove a filter")
        response = self.client.get(self.table_url(Session))
        self.assertContains(response, "This table is read-only")
        self.assertContains(response, "Session keys and signed session data are kept private.")

    def test_foreign_keys_and_reverse_dependencies_link_to_filtered_admin_records(self):
        response = self.client.get(self.detail_url(self.delivery))
        user_link = next(field["url"] for field in response.context["record_fields"] if field["url"] == self.detail_url(self.owner))
        self.assertEqual(self.client.get(user_link).status_code, 200)
        job_dependency = next(item for item in response.context["record_dependencies"] if item["label"] == "QC jobs")
        self.assertEqual(job_dependency["count"], 1)
        self.assertEqual(urlsplit(job_dependency["url"]).path, self.table_url(Job))
        self.assertEqual(parse_qs(urlsplit(job_dependency["url"]).query), {
            "related_field": ["delivery_id"], "related_value": [str(self.delivery.pk)],
        })
        linked = self.client.get(job_dependency["url"])
        self.assertEqual([row["url"] for row in linked.context["rows"]], [self.detail_url(self.job)])
        user_detail = self.client.get(self.detail_url(self.owner))
        self.assertTrue(any(item["label"] == "User roles" for item in user_detail.context["record_dependencies"]))

    def test_unknown_tables_invalid_pks_and_forged_relation_lookups_are_404(self):
        for table in ("pg_authid", "django_migrations", "missing_table", "auth_user;DROP TABLE auth_user"):
            with self.subTest(table=table):
                self.assertEqual(self.client.get(reverse("admin_database_records", args=(table,))).status_code, 404)
        for pk in ("not-a-number", "9999999999"):
            with self.subTest(pk=pk):
                self.assertEqual(self.client.get(reverse("admin_database_record", args=("execution_delivery", pk))).status_code, 404)
        for parameters in (
            {"related_field": "user__password", "related_value": "secret"},
            {"related_field": "filename", "related_value": self.delivery.filename},
            {"related_field": "user_id", "related_value": "not-an-integer"},
            {"related_field": "user_id"}, {"related_value": str(self.owner.pk)},
        ):
            with self.subTest(parameters=parameters):
                self.assertEqual(self.client.get(self.table_url(Delivery), parameters).status_code, 404)

    def test_database_failures_return_a_safe_503_without_private_connection_details(self):
        for method, url in (("query_records", self.table_url(Delivery)),
                            ("dependencies", self.detail_url(self.delivery))):
            with self.subTest(method=method), patch(
                "qc_tool.frontend.dashboard.views.admin_database." + method,
                side_effect=DatabaseError("private-database-connection-detail"),
            ):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 503)
                self.assertContains(response, "could not be read", status_code=503)
                self.assertNotContains(response, "private-database-connection-detail", status_code=503)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertContains(response, "Back to tables", status_code=503)
                self.assertContains(response, 'aria-label="Database tasks"', status_code=503)

    def test_plain_staff_and_product_managers_cannot_read_global_database_records(self):
        manager = get_user_model().objects.create_user("browser-manager")
        manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        staff = get_user_model().objects.create_user("browser-staff")
        staff.user_permissions.add(*Permission.objects.filter(codename__startswith="view_"))
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        for user in (manager, staff):
            self.client.force_login(user)
            for url in (reverse("admin_data_transfer"), self.table_url(Delivery), self.detail_url(self.delivery)):
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonymous_readers_return_to_the_admin_login_with_the_original_destination(self):
        client = Client()
        for url in (self.table_url(Delivery), self.detail_url(self.delivery)):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(urlsplit(response.url).path, reverse("admin_login"))
                self.assertEqual(parse_qs(urlsplit(response.url).query)["next"], [url])

    def test_editor_actions_respect_actual_object_modeladmin_permissions(self):
        owner = self.client.get(self.detail_url(self.owner))
        self.assertEqual(owner.context["record_actions"][0]["url"], reverse("admin:auth_user_change", args=(self.owner.pk,)))
        superuser = get_user_model().objects.create_superuser("protected-browser-root", "root@example.test", "test-password")
        protected = self.client.get(self.detail_url(superuser))
        self.assertEqual(protected.context["record_actions"], [])
        self.assertNotContains(protected, f'href="{reverse("admin:auth_user_change", args=(superuser.pk,))}"')
        group = Group.objects.get(name=Role.ADMIN.value)
        response = self.client.get(self.detail_url(group))
        self.assertNotContains(response, f'href="{reverse("admin:auth_group_delete", args=(group.pk,))}"')

    def test_maintenance_disables_editor_links_but_preserves_actions_and_reading(self):
        self.ready()
        for url in (self.table_url(get_user_model()), self.detail_url(self.owner)):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["record_actions"])
            for action in response.context["record_actions"]:
                self.assertContains(response, action["label"])
                self.assertNotContains(response, f'href="{action["url"]}"')

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_maintenance_record_gets_never_write_business_or_session_records(self):
        self.ready()
        with CaptureQueriesContext(connection) as queries:
            responses = [self.client.get(url) for url in (
                reverse("admin_data_transfer"), self.table_url(Delivery), self.detail_url(self.owner),
            )]
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual([item["sql"] for item in queries if item["sql"].lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))], [])

    def test_record_posts_are_405_when_open_and_maintenance_fenced_when_paused(self):
        urls = (self.table_url(Delivery), self.detail_url(self.delivery))
        before = list(Delivery.objects.values())
        for enabled in (False, True):
            if enabled:
                self.ready()
            for url in urls:
                with self.subTest(url=url, maintenance=enabled):
                    self.assertFalse(is_maintenance_control_request(RequestFactory().post(url)))
                    response = self.client.post(url, {"filename": "forged.zip", "action": "delete"})
                    self.assertEqual(response.status_code, 503 if enabled else 405)
                    if not enabled:
                        self.assertEqual(response["Allow"], "GET")
        self.assertEqual(list(Delivery.objects.values()), before)
