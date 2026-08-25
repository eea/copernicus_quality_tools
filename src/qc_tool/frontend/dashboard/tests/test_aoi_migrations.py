from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db import models
from django.test import TransactionTestCase


class AoiSchemaMigrationTests(TransactionTestCase):
    """Verify the AOI schema extends the current personal-token migration."""

    migrate_from = [
        ("accounts", "0001_initial"),
        ("dashboard", "0019_personal_access_tokens"),
    ]
    migrate_to = [
        ("accounts", "0001_initial"),
        ("dashboard", "0023_reconcile_aoi_metadata"),
    ]

    @classmethod
    def tearDownClass(cls):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        User = old_apps.get_model("auth", "User")
        Delivery = old_apps.get_model("dashboard", "Delivery")
        Job = old_apps.get_model("dashboard", "Job")
        user = User.objects.create(username="aoi-migration-owner")
        delivery = Delivery.objects.create(
            user_id=user.pk,
            filename="historic.zip",
            size_bytes=1,
        )
        self.delivery_id = delivery.pk
        self.job_id = Job.objects.create(
            delivery_id=delivery.pk,
            product_ident="historic-product",
            product_description="Historic product",
        ).pk
        unknown_delivery = Delivery.objects.create(
            user_id=user.pk,
            filename="unknown.zip",
            size_bytes=1,
        )
        self.unknown_delivery_id = unknown_delivery.pk
        self.unknown_job_id = Job.objects.create(
            delivery_id=unknown_delivery.pk,
            product_ident="unknown-product",
            product_description="Unknown product",
        ).pk

        self._prepare_dev_job_schema(Job)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE dashboard_job SET aoi_code = %s "
                "WHERE product_ident = %s",
                ("EE003L1", "historic-product"),
            )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def test_adopted_job_values_are_canonicalized_and_projected(self):
        Delivery = self.apps.get_model("dashboard", "Delivery")
        Job = self.apps.get_model("dashboard", "Job")

        self.assertEqual(Job.objects.get(pk=self.job_id).aoi_code, "ee003l")
        self.assertEqual(
            Delivery.objects.get(pk=self.delivery_id).aoi_code,
            "ee003l",
        )

    def test_unknown_values_remain_null_without_filesystem_side_effects(self):
        Delivery = self.apps.get_model("dashboard", "Delivery")
        Job = self.apps.get_model("dashboard", "Job")

        self.assertIsNone(Job.objects.get(pk=self.unknown_job_id).aoi_code)
        self.assertIsNone(
            Delivery.objects.get(pk=self.unknown_delivery_id).aoi_code
        )

    def test_personal_token_model_remains_in_the_migration_state(self):
        token_model = self.apps.get_model("dashboard", "PersonalAccessToken")

        self.assertEqual(token_model._meta.model_name, "personalaccesstoken")

    def test_stable_aoi_indexes_exist_after_schema_adoption(self):
        expected = {
            "dashboard_job": "dash_job_aoi_idx",
            "dashboard_delivery": "dash_delivery_aoi_idx",
        }
        with connection.cursor() as cursor:
            for table_name, index_name in expected.items():
                constraints = connection.introspection.get_constraints(
                    cursor,
                    table_name,
                )
                self.assertIn(index_name, constraints)
                aoi_indexes = sorted(
                    name
                    for name, constraint in constraints.items()
                    if constraint.get("index")
                    and tuple(constraint.get("columns") or ())
                    == ("aoi_code",)
                )
                self.assertEqual(aoi_indexes, [index_name])

    @staticmethod
    def _prepare_dev_job_schema(Job):
        with connection.cursor() as cursor:
            columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor,
                    Job._meta.db_table,
                )
            }
        if "aoi_code" not in columns:
            field = models.CharField(
                blank=True,
                default=None,
                editable=False,
                max_length=255,
                null=True,
            )
            field.set_attributes_from_name("aoi_code")
            field.model = Job
            with connection.schema_editor() as schema_editor:
                schema_editor.add_field(Job, field)

        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor,
                Job._meta.db_table,
            )
            if "dev_job_aoi_idx" not in constraints:
                quote = connection.ops.quote_name
                cursor.execute(
                    "CREATE INDEX {} ON {} ({})".format(
                        quote("dev_job_aoi_idx"),
                        quote(Job._meta.db_table),
                        quote("aoi_code"),
                    )
                )
