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

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        print("username: {:s}".format(username))
        print("password: {:s}".format(password))
        # create the user
        user = User.objects.create_user(username=username,
                                        email="{:s}@{:s}.com".format(username, username),
                                        password=password)
        print("Default user {:s} created successfully.".format(username))