"""One strict wire contract for maintenance admission and acknowledgments."""

import json


MAX_MESSAGE_BYTES = 4096


def decode_message(body):
    """Decode one bounded JSON object, refusing ambiguous duplicate fields."""
    if not isinstance(body, bytes) or len(body) > MAX_MESSAGE_BYTES:
        raise ValueError("Invalid maintenance message size")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate maintenance field")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Invalid JSON constant")

    return json.loads(body.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)


def parse_state(payload):
    """Return enabled/generation from an admission state or acknowledgment."""
    if (not isinstance(payload, dict)
        or not {"enabled", "generation"}.issubset(payload)
        or set(payload) - {"enabled", "generation", "quiescent"}
        or type(payload["enabled"]) is not bool
        or type(payload["generation"]) is not int
        or payload["generation"] < 0
        or ("quiescent" in payload and type(payload["quiescent"]) is not bool)):
        raise ValueError("Invalid maintenance state")
    return payload["enabled"], payload["generation"]


def parse_command(payload):
    if not isinstance(payload, dict) or set(payload) != {"enabled", "generation"}:
        raise ValueError("Invalid maintenance command fields")
    return parse_state(payload)


def parse_acknowledgment(payload, *, expected_enabled, expected_generation):
    if not isinstance(payload, dict) or set(payload) != {"enabled", "generation", "quiescent"}:
        raise ValueError("Invalid maintenance acknowledgment fields")
    enabled, generation = parse_state(payload)
    if enabled != expected_enabled or generation != expected_generation:
        raise ValueError("Stale or conflicting maintenance acknowledgment")
    return payload["quiescent"]
