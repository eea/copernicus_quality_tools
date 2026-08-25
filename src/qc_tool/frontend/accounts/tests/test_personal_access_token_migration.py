from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase


class PersonalAccessTokenMigrationTests(TransactionTestCase):
    """Exercise the deployed legacy-token upgrade with historical models."""

    migrate_from = [
        ("accounts", "0001_initial"),
        ("dashboard", "0018_alter_delivery_size_bytes"),
    ]
    migrate_to = [
        ("accounts", "0001_initial"),
        ("dashboard", "0019_personal_access_tokens"),
    ]

    @classmethod
    def tearDownClass(cls):
        # Always leave the schema at the project leaf nodes for subsequent
        # tests, even when an assertion fails part-way through this class.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        # 0019 intentionally cannot recreate deleted secrets on reverse. Build
        # its historical schema directly so this test can exercise the real
        # forward operation without making the production migration reversible.
        old_state = executor.loader.project_state(self.migrate_from)
        new_state = executor.loader.project_state(self.migrate_to)
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(
                new_state.apps.get_model("dashboard", "PersonalAccessToken")
            )
            schema_editor.create_model(
                old_state.apps.get_model("dashboard", "ApiUser")
            )
        MigrationRecorder(connection).record_unapplied(
            "dashboard",
            "0019_personal_access_tokens",
        )
        old_apps = old_state.apps
        self._seed_legacy_state(old_apps)

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def _seed_legacy_state(self, apps):
        user_model = apps.get_model("auth", "User")
        group_model = apps.get_model("auth", "Group")
        permission_model = apps.get_model("auth", "Permission")
        content_type_model = apps.get_model("contenttypes", "ContentType")
        api_user_model = apps.get_model("dashboard", "ApiUser")
        region_grant_model = apps.get_model("accounts", "UserRegionGrant")
        product_grant_model = apps.get_model("accounts", "UserProductGrant")

        self.owner = user_model.objects.create(username="migration-owner")
        invalid_owner = user_model.objects.create(username="invalid-owner")
        duplicate_one = user_model.objects.create(username="duplicate-one")
        duplicate_two = user_model.objects.create(username="duplicate-two")

        default_group, _created = group_model.objects.get_or_create(
            name="default"
        )
        self.owner.groups.add(default_group)

        capability_type, _created = content_type_model.objects.get_or_create(
            app_label="accounts",
            model="accountcapability",
        )
        view_permission, _created = permission_model.objects.get_or_create(
            content_type=capability_type,
            codename="view_deliveries",
            defaults={"name": "Can view deliveries"},
        )
        run_permission, _created = permission_model.objects.get_or_create(
            content_type=capability_type,
            codename="run_qc",
            defaults={"name": "Can run quality control"},
        )
        default_group.permissions.add(view_permission)
        self.owner.user_permissions.add(run_permission)

        region_grant_model.objects.create(
            user_id=self.owner.pk,
            aoi_code="CZ-001",
        )
        product_grant_model.objects.create(
            user_id=self.owner.pk,
            product_ident="general_raster",
        )

        self.valid_digest = "sha256$" + ("a" * 64)
        api_user_model.objects.create(
            user_id=self.owner.pk,
            api_key=self.valid_digest,
        )
        api_user_model.objects.create(
            user_id=invalid_owner.pk,
            api_key="PLAINTEXT-LEGACY",
        )
        duplicate_digest = "sha256$" + ("d" * 64)
        api_user_model.objects.create(
            user_id=duplicate_one.pk,
            api_key=duplicate_digest,
        )
        api_user_model.objects.create(
            user_id=duplicate_two.pk,
            api_key=duplicate_digest,
        )

    def test_migration_preserves_only_unique_supported_digest_with_access_snapshot(self):
        token_model = self.apps.get_model(
            "dashboard",
            "PersonalAccessToken",
        )

        tokens = list(token_model.objects.all())

        self.assertEqual(len(tokens), 1)
        token = tokens[0]
        self.assertEqual(token.user_id, self.owner.pk)
        self.assertEqual(token.name, "Migrated API token")
        self.assertEqual(token.secret_digest, self.valid_digest)
        self.assertEqual(token.token_hint, "")
        self.assertEqual(token.role_snapshot, ["default"])
        self.assertEqual(
            set(token.permission_snapshot),
            {
                "change_password",
                "delete_delivery",
                "manage_api_credential",
                "manage_own_account",
                "run_qc",
                "submit_delivery",
                "upload_delivery",
                "view_deliveries",
            },
        )
        self.assertEqual(token.region_codes_snapshot, ["CZ-001"])
        self.assertEqual(token.product_idents_snapshot, ["general_raster"])
        self.assertFalse(token.is_administrator_snapshot)

    def test_migration_removes_the_legacy_model(self):
        with self.assertRaises(LookupError):
            self.apps.get_model("dashboard", "ApiUser")
