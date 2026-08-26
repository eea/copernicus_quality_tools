"""Bounds for dashboard queries and presentation collections."""


MAX_ITEM_LIMIT = 20


def validate_item_limit(value):
    """Reject values that could accidentally produce unbounded queries."""

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_ITEM_LIMIT
    ):
        raise ValueError(
            "Dashboard item limits must be integers from 1 to 20."
        )
