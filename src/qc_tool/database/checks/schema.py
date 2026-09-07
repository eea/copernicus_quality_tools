"""Build draft models or exercise released upgrades on an EMPTY test database.

Run inside the supported frontend runtime with QC_TOOL_ENVIRONMENT=test and
explicit disposable DB settings. This command never resets an existing database.
"""

import os
import sys


def seed_baseline(apps):
    """Keep historical input fixed; evolve successor assertions for schema changes."""
    snapshots = []

    def create(app, model, **values):
        instance = apps.get_model(app, model).objects.create(**values)
        snapshots.append((
            instance._meta.label_lower,
            instance.pk,
            type(instance).objects.filter(pk=instance.pk).values(*values).get(),
        ))
        return instance

    # Deliberately synthetic, unusable credentials; no shared files or services.
    user = create("auth", "User", username="migration-probe", password="!")
    product = create(
        "dashboard", "Product", ident="migration_probe", name="Migration probe",
    )
    release = create(
        "dashboard", "ProductRelease", product_id=product.pk,
        release_key="migration_probe_2026", revision=1,
        description="Migration probe", catalog_digest="c" * 64,
        coverage_state="authoritative", is_current=True,
    )
    aoi_code = "AOI-" + "x" * 251
    aoi = create(
        "dashboard", "ProductAOI", product_release_id=release.pk,
        aoi_code=aoi_code, provenance="migration-test",
    )
    definition = create(
        "dashboard", "QcDefinition", product_ident=product.ident,
        digest="d" * 64, description="Migration probe",
        document={"probe": True}, source_path="migration-probe.json",
    )
    create(
        "dashboard", "ProductReleaseDefinition", product_release_id=release.pk,
        qc_definition_id=definition.pk, is_primary=True,
    )
    create(
        "accounts", "UserRegionGrant", user_id=user.pk, aoi_code="CZ-001",
    )
    create(
        "accounts", "UserProductGrant", user_id=user.pk,
        product_ident=product.ident,
    )
    token = create(
        "dashboard", "PersonalAccessToken", user_id=user.pk, name="Migration probe",
        secret_digest="sha256:" + "e" * 64,
        permission_snapshot=["view_deliveries"], role_snapshot=["default"],
        region_codes_snapshot=["CZ-001"], product_idents_snapshot=[product.ident],
    )
    delivery = create(
        "dashboard", "Delivery", user_id=user.pk, filename="migration-probe.zip",
        size_bytes=2 ** 33, product_ident=product.ident,
        aoi_code=aoi_code, aoi_code_submitted=aoi_code, content_sha256="a" * 64,
    )
    job = create(
        "dashboard", "Job", delivery_id=delivery.pk, product_ident=product.ident,
        product_description="Migration probe", job_status="ok",
        aoi_code=aoi_code, aoi_code_submitted=aoi_code,
        requested_by_id=user.pk, requested_by_username=user.username,
        request_source="api", requested_api_token_id=token.pk,
        requested_api_token_name=token.name,
        product_release_id=release.pk, qc_definition_id=definition.pk,
        input_sha256="a" * 64, result_metadata={"aoi_code": aoi_code},
    )
    create(
        "dashboard", "DeliverySubmission", delivery_id=delivery.pk, job_id=job.pk,
        product_release_id=release.pk, product_aoi_id=aoi.pk,
        aoi_code=aoi_code, aoi_code_submitted=aoi_code,
        submitted_by_id=user.pk, submitted_by_username=user.username,
        request_channel="api", api_token_id=token.pk, api_token_name=token.name,
        publication_state="pending",
    )
    return snapshots


def verify_rows(snapshots):
    from django.apps import apps

    for label, pk, expected in snapshots:
        actual = apps.get_model(label).objects.filter(pk=pk).values(*expected).get()
        if actual != expected:
            raise RuntimeError(f"Migration changed the probe's {label} record.")


def verify_account_bootstrap():
    from django.contrib.auth.models import Group

    from qc_tool.frontend.accounts.authorization.permissions import (
        ROLE_PERMISSION_GRANTS,
    )
    from qc_tool.frontend.accounts.authorization.roles import Role
    from qc_tool.frontend.accounts.services.role_permissions import (
        capability_content_type,
    )

    for role, permissions in ROLE_PERMISSION_GRANTS.items():
        actual = set(Group.objects.get(name=role.value).permissions.filter(
            content_type=capability_content_type(),
        ).values_list("codename", flat=True))
        if actual != {permission.value for permission in permissions}:
            raise RuntimeError(f"Role {role.value} was not bootstrapped correctly.")
    if Group.objects.get(name=Role.ADMIN.value).permissions.filter(
        content_type__app_label="auth", codename="delete_user",
    ).exists():
        raise RuntimeError("Account bootstrap unexpectedly granted hard user deletion.")


def baseline_targets(graph, baselines, first_party_apps):
    """Seed before all later first-party work, including newly introduced apps."""
    return list(baselines) + [
        node for node in graph.leaf_nodes() if node[0] not in first_party_apps
    ]


def main():
    if os.environ.get("QC_TOOL_ENVIRONMENT", "").strip().casefold() != "test":
        raise RuntimeError("This check requires QC_TOOL_ENVIRONMENT=test.")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qc_tool.frontend.settings")
    import django
    django.setup()

    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from qc_tool.database.deployment import release_policy
    from qc_tool.database.policy import MIGRATION_MODULES

    if connection.introspection.table_names(include_views=True):
        raise RuntimeError("Refusing to modify a nonempty database. Use a new test database.")

    policy = release_policy()
    if policy["phase"] == "draft":
        from django.apps import apps

        call_command("database", "apply", verbosity=0)
        if apps.get_model("dashboard", "Product").objects.exists():
            raise RuntimeError("Draft schema initialization must not seed products.")
        snapshots = seed_baseline(apps)
        call_command("database", "apply", verbosity=0)
        call_command("database", "check", verbosity=0)
        verify_rows(snapshots)
        verify_account_bootstrap()
        print(f"{connection.vendor}: draft model schema, synthetic data, repeat initialization and roles passed.")
        return

    executor = MigrationExecutor(connection)
    baselines = tuple(policy["baselines"].items())
    for baseline in baselines:
        if baseline not in executor.loader.graph.nodes:
            raise RuntimeError(f"Missing committed release baseline: {baseline}.")
    conflicts = executor.loader.detect_conflicts()
    if conflicts:
        raise RuntimeError(f"Resolve migration conflicts before release: {conflicts}.")

    # Keep Django's own apps at their supported heads; pin only QC Tool's apps
    # to the first release. Never reverse an installed or production database.
    targets = baseline_targets(executor.loader.graph, baselines, MIGRATION_MODULES)
    executor.migrate(targets)
    baseline_apps = executor.loader.project_state(targets).apps
    snapshots = seed_baseline(baseline_apps)

    # The management command also runs post_migrate permission/role bootstrap.
    call_command("database", "apply", verbosity=0)
    verify_rows(snapshots)
    verify_account_bootstrap()
    call_command("database", "apply", verbosity=0)
    call_command("database", "check", verbosity=0)
    call_command(
        "makemigrations", *MIGRATION_MODULES,
        check_changes=True, dry_run=True, interactive=False, verbosity=0,
    )
    verify_rows(snapshots)
    verify_account_bootstrap()
    print(f"{connection.vendor}: baseline, seeded upgrade, repeat migrate, and model drift checks passed.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
