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
        parser.add_argument(
            '--email', dest='email', required=False,
            help='the email of the new user',
        )
        parser.add_argument(
            '--country', dest='country', required=False,
            help='the country of the new user',
        )

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        is_superuser = options['superuser']
        email = options.get('email', "{:s}@{:s}.com".format(username, username))
        country = options.get('country')

        # create the user
        if User.objects.filter(username=username).exists():
            print("The user with username {:s} already exists.".format(username))
            return

        if is_superuser:
            # Creating a superuser (admin YES)
            User.objects.create_superuser(username=username,
                                            email=email,
                                            password=password)
        else:
            # Creating a regular user (admin NO)
            User.objects.create_user(username=username,
                                            email=email,
                                            password=password)
            if country is not None:
                user = User.objects.get(username=username)
                try:
                    user.userprofile.country = country
                    user.userprofile.save()
                    print("User {:s} created successfully with country set to {:s}.".format(username, country))
                except Exception as e:
                    print("User {:s} created, but failed to set country.".format(username))   
