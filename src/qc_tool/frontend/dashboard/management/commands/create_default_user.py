from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create a custom user'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username', dest='username', required=True,
            help='the username of the new user',
        )
        parser.add_argument(
            '--password', dest='password', required=True,
            help='the password of the new user',
        )
        parser.add_argument(
            '--admin', dest='admin', required=False,
            help='YES if the user should be admin, NO otherwise.'
        )

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']

        if "admin" in options:
            is_admin = options["admin"]
        else:
            is_admin = "NO"

        print("username: {:s}".format(username))
        print("password: {:s}".format(password))
        print("is_admin: {:s}".format(is_admin))

        # create the user
        if User.objects.filter(username=username).exists():
            print("User not created. The user with username {:s} already exists.")
            return

        if is_admin == "YES":
            # Creating a superuser (admin YES)
            User.objects.create_superuser(username=username,
                                            email="{:s}@{:s}.com".format(username, username),
                                            password=password)
        else:
            # Creating a regular user (admin NO)
            User.objects.create_user(username=username,
                                            email="{:s}@{:s}.com".format(username, username),
                                            password=password)
            print("Default user {:s} created successfully.".format(username))