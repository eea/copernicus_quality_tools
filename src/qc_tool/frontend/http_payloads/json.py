"""Encode legacy database dates as unambiguous JSON timestamps."""

from datetime import datetime

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone


class DatabaseDateTimeJSONEncoder(DjangoJSONEncoder):
    """Label local-naive database dates without changing their stored values.

    With USE_TZ=False, database datetimes use the configured application zone.
    A request's active display timezone must not reinterpret those wall times.
    Aware datetimes and original report strings retain their existing meaning.
    """

    def default(self, value):
        if isinstance(value, datetime) and timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_default_timezone())
        return super().default(value)
