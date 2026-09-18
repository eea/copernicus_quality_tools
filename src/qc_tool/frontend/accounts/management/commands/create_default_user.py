from django.core.management.base import BaseCommand

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.users import provision_user


class Command(BaseCommand):
    help = "Create a QC Tool user"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Create a Django superuser.",
        )
        parser.add_argument("--email")
        parser.add_argument(
            "--country",
            help="Profile country used for legacy region access.",
        )
        parser.add_argument(
            "--region",
            "--region-code",
            "--aoi-code",
            dest="region_codes",
            action="append",
            default=[],
            help=(
                "Assign one exact, opaque region code; may be supplied more than "
                "once. No catalog validation or normalization is performed. "
                "This scopes region access but does not grant region "
                "permissions."
            ),
        )
        parser.add_argument(
            "--group",
            action="append",
            choices=Role.values(),
            default=[],
            help="Assign a canonical group; may be supplied more than once.",
        )
        parser.add_argument(
            "--product",
            dest="product_idents",
            action="append",
            default=[],
            help=(
                "Assign an exact canonical lowercase product definition ID; "
                "may be supplied more than once. Each ID is validated against "
                "the configured product definitions."
            ),
        )

    def handle(self, *args, **options):
        result = provision_user(
            username=options["username"],
            password=options["password"],
            email=options.get("email"),
            country=options.get("country"),
            region_codes=options["region_codes"],
            product_idents=options["product_idents"],
            groups=options["group"],
            is_superuser=options["superuser"],
        )

        if not result.created:
            self.stdout.write(
                self.style.WARNING(
                    f"The user with username {options['username']} already exists."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"User {options['username']} created successfully.")
        )
