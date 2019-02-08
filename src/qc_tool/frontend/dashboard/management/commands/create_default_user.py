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
            '--superuser', dest='superuser', action='store_true',
            help='if set then the new user will have superuser privileges.'
        )

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        is_superuser = options['superuser']

        # create the user
        if User.objects.filter(username=username).exists():
            print("The user with username {:s} already exists.".format(username))
            return

        if is_superuser:
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
