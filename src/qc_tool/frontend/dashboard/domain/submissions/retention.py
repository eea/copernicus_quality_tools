"""Ordinary ORM bulk operations must preserve publication audit records."""

from django.core.exceptions import ValidationError
from django.db import models

from .artifact_keys import validate_artifact_key


class RetainedPublicationQuerySet(models.QuerySet):
    """Keep history while allowing explicitly mutable review projections."""

    bulk_mutable_fields = frozenset()
    clearable_actor_fields = frozenset()

    def delete(self):
        raise ValidationError("Publication records are retained as audit history.")

    def update(self, **kwargs):
        forbidden = {
            field for field, value in kwargs.items()
            if field not in self.bulk_mutable_fields
            and not (field in self.clearable_actor_fields and value is None)
        }
        if forbidden:
            raise ValidationError(
                "Publication history cannot be rewritten by a bulk update."
            )
        return super().update(**kwargs)

    def bulk_create(self, objs, *args, **kwargs):
        # Upserts bypass Model.save(), including its identity/receipt checks.
        if kwargs.get("update_conflicts") or (len(args) > 2 and args[2]):
            raise ValidationError("Publication history cannot be overwritten.")
        return super().bulk_create(objs, *args, **kwargs)


class SubmissionQuerySet(RetainedPublicationQuerySet):
    bulk_mutable_fields = frozenset({"review_state", "review_version"})
    # Django's SET_NULL collector may detach a removed account; its immutable
    # username and credential snapshots remain the historical evidence.
    clearable_actor_fields = frozenset({"submitted_by", "submitted_by_id"})

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        for submission in objs:
            if submission.artifact_key:
                try:
                    validate_artifact_key(submission.artifact_key)
                except ValueError as exc:
                    raise ValidationError({"artifact_key": str(exc)}) from exc
        return super().bulk_create(objs, *args, **kwargs)


class ConflictEventQuerySet(RetainedPublicationQuerySet):
    clearable_actor_fields = frozenset({"actor", "actor_id"})
