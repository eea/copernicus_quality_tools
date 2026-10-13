"""Verify current models on an entirely empty disposable test database.

Run in the pinned frontend runtime with QC_TOOL_ENVIRONMENT=test and explicit
isolated DB settings. This command never resets or upgrades an existing target.
"""

import os
import sys

from django.utils import timezone


def seed_records(apps):
    """Create synthetic current-model rows and retain their exact selected values."""
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
    user = create("auth", "User", username="schema-probe", password="!")
    product = create(
        "dashboard", "Product", ident="schema_probe", name="Schema probe",
    )
    release = create(
        "dashboard", "ProductRelease", product_id=product.pk,
        release_key="schema_probe_2026", revision=1,
        description="Schema probe", catalog_digest="c" * 64,
        coverage_state="authoritative", is_current=True,
        approved_at=timezone.now(),
    )
    product_unit_code = "unit-" + "x" * 250
    product_unit = create(
        "dashboard", "ProductUnit", product_release_id=release.pk,
        product_unit_code=product_unit_code, provenance="schema-test",
    )
    definition = create(
        "dashboard", "QcDefinition", product_ident=product.ident,
        digest="d" * 64, description="Schema probe",
        document={"probe": True}, source_path="schema-probe.json",
    )
    create(
        "dashboard", "ProductReleaseDefinition", product_release_id=release.pk,
        qc_definition_id=definition.pk, is_primary=True,
    )
    create(
        "accounts", "UserProductGrant", user_id=user.pk,
        product_ident=product.ident,
    )
    token = create(
        "accounts", "PersonalAccessToken", user_id=user.pk, name="Schema probe",
        secret_digest="sha256:" + "e" * 64,
        permission_snapshot=["view_deliveries"], role_snapshot=["default"],
        product_idents_snapshot=[product.ident],
    )
    delivery = create(
        "dashboard", "Delivery", user_id=user.pk, filename="schema-probe.zip",
        size_bytes=2 ** 33, product_ident=product.ident,
        product_unit_code=product_unit_code, verified_product_unit_code=product_unit_code, content_sha256="a" * 64,
    )
    job = create(
        "dashboard", "Job", delivery_id=delivery.pk, product_ident=product.ident,
        product_description="Schema probe", job_status="ok",
        product_unit_code=product_unit_code, verified_product_unit_code=product_unit_code,
        requested_by_id=user.pk, requested_by_username=user.username,
        request_source="api", requested_api_token_id=token.pk,
        requested_api_token_name=token.name,
        product_release_id=release.pk, qc_definition_id=definition.pk,
        input_sha256="a" * 64, reference_period="2024",
    )
    create(
        "dashboard", "DeliverySubmission", delivery_id=delivery.pk, job_id=job.pk,
        product_release_id=release.pk, product_unit_id=product_unit.pk,
        product_unit_code=product_unit_code, verified_product_unit_code=product_unit_code,
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
            raise RuntimeError(f"Repeated initialization changed the probe's {label} record.")


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


def verify_declared_constraints_and_indexes():
    """Validate the required managed schema contract and named integrity rules."""
    from django.db import connection
    from qc_tool.database.deployment import SchemaInitializer

    SchemaInitializer(connection).check()


def main():
    if os.environ.get("QC_TOOL_ENVIRONMENT", "").strip().casefold() != "test":
        raise RuntimeError("This check requires QC_TOOL_ENVIRONMENT=test.")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qc_tool.frontend.settings")
    import django
    django.setup()

    from django.apps import apps
    from django.contrib.auth.models import Group
    from django.core.management import call_command
    from django.db import connection
    from unittest.mock import patch
    from qc_tool.database.checks.source import check_source
    from qc_tool.database.deployment import SchemaInitializer

    check_source()
    initializer = SchemaInitializer(connection)
    if initializer.inspect()["state"] != "empty":
        raise RuntimeError("Refusing to modify a nonempty database. Use a new test database.")

    call_command("database", "apply", verbosity=0)
    verify_declared_constraints_and_indexes()
    verify_account_bootstrap()
    if (apps.get_model("auth", "User").objects.exists()
            or apps.get_model("dashboard", "Product").objects.exists()):
        raise RuntimeError("Schema initialization must not create users or seed products.")

    snapshots = seed_records(apps)
    roles = list(Group.objects.order_by("pk").values_list("pk", "name"))
    grants = list(Group.permissions.through.objects.order_by("pk").values_list(
        "pk", "group_id", "permission_id",
    ))
    # A matching target must never run native initialization or bootstrap again.
    with patch("qc_tool.database.deployment.call_command",
               side_effect=RuntimeError("Repeated apply attempted initialization/bootstrap.")):
        call_command("database", "apply", verbosity=0)
        call_command("database", "check", verbosity=0)
    verify_rows(snapshots)
    verify_account_bootstrap()
    if (roles != list(Group.objects.order_by("pk").values_list("pk", "name"))
            or grants != list(Group.permissions.through.objects.order_by("pk").values_list(
                "pk", "group_id", "permission_id",
            ))):
        raise RuntimeError("Repeated initialization changed role or permission records.")
    verify_declared_constraints_and_indexes()
    print(f"{connection.vendor}: current-model schema, synthetic records, read-only repeat apply and roles passed.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
