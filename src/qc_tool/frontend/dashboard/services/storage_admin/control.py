"""Shared authority and quiescence guard for reversible storage changes."""

from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.utils.crypto import constant_time_compare

from qc_tool.database.transfers import store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.dashboard.services.maintenance import MaintenanceError
from qc_tool.frontend.dashboard.services.maintenance.barrier import ready_barrier

from .files import StorageError


def authorize_storage_change(actor, *, permission=None):
    """Recheck the actor against the currently selected database."""
    try:
        current = get_user_model().objects.get(pk=actor.pk, username=actor.get_username())
        access = access_for(current)
        if (not current.is_staff or not constant_time_compare(current.password, actor.password)
                or not access.is_administrator or (permission is not None and not access.allows(permission))):
            raise ValueError
        return current
    except (AttributeError, ValueError, get_user_model().DoesNotExist) as error:
        raise StorageError("Sign in as an active administrator on the current database.", status_code=403) from error
    except DatabaseError as error:
        raise StorageError("Administrator access could not be verified. No files were changed.", status_code=503) from error


@contextmanager
def guarded_storage_change(actor, generation, *, permission=None):
    if type(generation) is not int or generation < 0:
        raise StorageError("Maintenance changed. Reload and review this action.")
    try:
        with store.execution_lock(), ready_barrier(generation=generation):
            yield authorize_storage_change(actor, permission=permission)
    except (MaintenanceError, TransferError) as error:
        raise StorageError(str(error)) from error
    except OSError as error:
        raise StorageError("The storage operation could not finish. Its files were retained; review Trash before retrying.",
                           status_code=503) from error
