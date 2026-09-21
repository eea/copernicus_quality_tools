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
                "Assign an exact canonical product or QC definition ID; "
                "may be supplied more than once. Each ID is validated against "
                "the active managed product catalog."
            ),
        )

    def handle(self, *args, **options):
        result = provision_user(
            username=options["username"],
            password=options["password"],
            email=options.get("email"),
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
