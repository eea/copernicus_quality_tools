import argparse
import os

# Instructions: Run inside the QC Tool frontend container / pod, which has the
# qc_tool package and its database settings (POSTGRES_*).
#
# Creates the missing content types and permissions of all installed apps and
# synchronizes the role groups (default, product_manager, admin) with QC Tool's
# own bootstrap code, as normally done after migrate. Existing permissions and
# unrelated group grants are kept. The result is then checked against the
# expected permissions below.

# (app_label, model, codename): dashboard model permissions.
PERMISSIONS = [
    ("dashboard", model, f"{action}_{model}")
    for model in (
        "delivery", "job", "s3info", "deliverysubmission",
        "submissionconflict", "submissionconflictevent", "submissionreviewevent",
    )
    for action in ("add", "change", "delete", "view")
]

# group name -> (app_label, codename); permission ids of the reference database in comments.
GROUP_PERMISSIONS = {
    "default": [
        ("accounts", "manage_api_credential"),  # 32
        ("accounts", "view_deliveries"),  # 25
        ("accounts", "upload_delivery"),  # 26
        ("accounts", "run_qc"),  # 27
        ("accounts", "delete_delivery"),  # 28
        ("accounts", "submit_delivery"),  # 29
        ("accounts", "change_password"),  # 30
        ("accounts", "manage_own_account"),  # 31
    ],
    "product_manager": [
        ("accounts", "view_product_deliveries"),  # 34
        ("accounts", "view_product_aggregate_report"),  # 35
    ],
    "admin": [
        ("auth", "add_group"),  # 9
        ("auth", "change_group"),  # 10
        ("auth", "delete_group"),  # 11
        ("auth", "view_group"),  # 12
        ("auth", "add_user"),  # 13
        ("auth", "change_user"),  # 14
        ("auth", "view_user"),  # 16
        ("accounts", "manage_api_credential"),  # 32
        ("accounts", "manage_configuration"),  # 33
        ("accounts", "view_product_deliveries"),  # 34
        ("accounts", "view_product_aggregate_report"),  # 35
        ("accounts", "view_deliveries"),  # 25
        ("accounts", "upload_delivery"),  # 26
        ("accounts", "run_qc"),  # 27
        ("accounts", "delete_delivery"),  # 28
        ("accounts", "submit_delivery"),  # 29
        ("accounts", "change_password"),  # 30
        ("accounts", "manage_own_account"),  # 31
        ("accounts", "add_personalaccesstoken"),  # 36
        ("accounts", "change_personalaccesstoken"),  # 37
        ("accounts", "delete_personalaccesstoken"),  # 38
        ("accounts", "view_personalaccesstoken"),  # 39
        ("accounts", "add_userproductgrant"),  # 40
        ("accounts", "change_userproductgrant"),  # 41
        ("accounts", "delete_userproductgrant"),  # 42
        ("accounts", "view_userproductgrant"),  # 43
    ],
}


class DryRun(Exception):
    pass


def setup_django():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qc_tool.frontend.settings")
    import django

    django.setup()


def counts():
    from django.contrib.auth.models import Group
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    return {
        "django_content_type": ContentType.objects.count(),
        "auth_permission": Permission.objects.count(),
        "auth_group_permissions": Group.permissions.through.objects.count(),
    }


def check_expected():
    from django.contrib.auth.models import Group
    from django.contrib.auth.models import Permission

    missing = [
        f"{app}.{codename}"
        for app, _model, codename in PERMISSIONS
        if not Permission.objects.filter(content_type__app_label=app, codename=codename).exists()
    ]
    for group_name, permissions in GROUP_PERMISSIONS.items():
        group = Group.objects.filter(name=group_name).first()
        if group is None:
            missing.append(f"group {group_name}")
            continue
        missing += [
            f"{group_name}: {app}.{codename}"
            for app, codename in permissions
            if not group.permissions.filter(content_type__app_label=app, codename=codename).exists()
        ]
    if missing:
        raise RuntimeError("Expected permissions are still missing: " + ", ".join(missing))


def import_permissions(dry_run):
    setup_django()
    from django.apps import apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes
    from django.db import transaction

    from qc_tool.frontend.accounts.admin.role_permissions import synchronize_admin_role

    print("Importing permissions...")
    try:
        with transaction.atomic():
            before = counts()
            for app_config in apps.get_app_configs():
                create_contenttypes(app_config, verbosity=0)
                create_permissions(app_config, verbosity=0)
            synchronize_admin_role()
            after = counts()
            for table, count in after.items():
                print(f"{table}: {before[table]} -> {count} entries.")
            check_expected()
            print("All expected permissions and group assignments are present.")
            if dry_run:
                raise DryRun()
    except DryRun:
        print("Dry run, rolled back.")
        return
    except Exception as e:
        print(f"Error importing permissions: {e}")
        raise
    print("Permissions imported successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import_permissions(args.dry_run)
