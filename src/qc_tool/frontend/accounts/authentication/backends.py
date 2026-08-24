from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveBackend(ModelBackend):
    """Authenticate the configured username field without case sensitivity."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        username = username or kwargs.get(user_model.USERNAME_FIELD)
        if username is None or password is None:
            return None

        lookup = {f"{user_model.USERNAME_FIELD}__iexact": username}
        try:
            user = user_model._default_manager.get(**lookup)
        except user_model.DoesNotExist:
            # Keep password hashing work similar for existing and missing users.
            user_model().set_password(password)
            return None
        except user_model.MultipleObjectsReturned:
            # Existing case-variant duplicates are ambiguous and must fail closed.
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
