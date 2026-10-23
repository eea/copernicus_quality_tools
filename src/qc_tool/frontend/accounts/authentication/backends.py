from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections

from qc_tool.database import selection


def _reject(request):
    if getattr(request, "maintenance_active", False):
        # Never fall through to a backend that might upgrade a password hash.
        raise PermissionDenied
    return None


class AccountBackend(ModelBackend):
    """Avoid password-hash upgrades while the application database is paused."""

    def lookup_user(self, user_model, username):
        return user_model._default_manager.get_by_natural_key(username)

    def _get_group_permissions(self, user_obj):
        # Maintenance operators may intentionally come from the retained
        # database while inspecting a freshly restored active database.
        return super()._get_group_permissions(user_obj).using(user_obj._state.db or "default")

    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        username = username or kwargs.get(user_model.USERNAME_FIELD)
        if username is None or password is None:
            return _reject(request)

        try:
            user = self.lookup_user(user_model, username)
        except user_model.DoesNotExist:
            # Keep password hashing work similar for existing and missing users.
            user_model().set_password(password)
            return _reject(request)
        except user_model.MultipleObjectsReturned:
            # Existing case-variant duplicates are ambiguous and must fail closed.
            return _reject(request)

        valid_password = (
            check_password(password, user.password)
            if getattr(request, "maintenance_active", False)
            else user.check_password(password)
        )
        if valid_password and self.user_can_authenticate(user):
            return user
        return _reject(request)


class CaseInsensitiveBackend(AccountBackend):
    """Authenticate the configured username field without case sensitivity."""

    def lookup_user(self, user_model, username):
        return user_model._default_manager.get(
            **{f"{user_model.USERNAME_FIELD}__iexact": username},
        )


class MaintenanceBackend(AccountBackend):
    """Handle only paused sign-ins before the normal authentication backend."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not getattr(request, "maintenance_active", False):
            return None
        from qc_tool.frontend.accounts.authorization.access import AccountAccess
        from qc_tool.frontend.dashboard.services.maintenance.reads import _read_query

        user_model = get_user_model()
        username = username or kwargs.get(user_model.USERNAME_FIELD)
        if username is None or password is None:
            return _reject(request)
        active = selection.current_database()
        candidates = [active]
        state = selection.read_state()
        # Rescue credentials remain valid only during the same provisional
        # maintenance window. Reopening never leaves old-database login active.
        generation = getattr(request, "maintenance_status", {}).get("generation")
        if type(generation) is int and state.get("maintenance_generation") == generation:
            candidates.append(state.get("previous"))
        for name in dict.fromkeys(candidate for candidate in candidates if candidate):
            try:
                alias = selection.alias_for_database(name)
                lookup = user_model.USERNAME_FIELD
                if settings.CONFIG["case_insensitive_usernames"]:
                    lookup += "__iexact"
                with connections[alias].execute_wrapper(_read_query):
                    user = user_model._default_manager.using(alias).get(**{lookup: username})
                    valid = check_password(password, user.password)
                    access = AccountAccess.from_user(user)
                if (valid and self.user_can_authenticate(user)
                        and access.can_access_django_admin
                        and (name == active or access.is_administrator)):
                    return user
            except user_model.DoesNotExist:
                user_model().set_password(password)
            except (user_model.MultipleObjectsReturned, DatabaseError):
                continue
        return _reject(request)

    def lookup_user(self, user_model, username):
        if settings.CONFIG["case_insensitive_usernames"]:
            return user_model._default_manager.get(
                **{f"{user_model.USERNAME_FIELD}__iexact": username},
            )
        return super().lookup_user(user_model, username)

    def get_user(self, user_id):
        from qc_tool.frontend.accounts.authentication.maintenance import authentication_origin
        from qc_tool.frontend.accounts.authorization.access import AccountAccess
        from qc_tool.frontend.dashboard.services.maintenance.reads import _read_query

        origin = authentication_origin()
        if origin is None:
            return super().get_user(user_id)
        try:
            alias = selection.alias_for_database(origin)
            with connections[alias].execute_wrapper(_read_query):
                user = get_user_model()._default_manager.using(alias).get(pk=user_id)
                access = AccountAccess.from_user(user)
                if not access.can_access_django_admin:
                    return None
                if origin != selection.current_database() and not access.is_administrator:
                    return None
            return user if self.user_can_authenticate(user) else None
        except (get_user_model().DoesNotExist, selection.DatabaseSelectionError, DatabaseError):
            return None
