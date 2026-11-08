"""Immutable account-name snapshots for jobs and administrative history."""


def actor_username(actor):
    """Return the bounded display name, without granting identity or authority.

    Preserve support for Django users and lightweight actors used by service
    callers. Stored snapshots remain limited to the username fields' 150 chars.
    """
    if actor is None:
        return ""
    getter = getattr(actor, "get_username", None)
    value = getter() if callable(getter) else getattr(actor, "username", "")
    return str(value)[:150]
