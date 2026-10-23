"""Frontend and worker reject the same ambiguous/stale maintenance messages."""

from unittest import TestCase

from qc_tool.maintenance.protocol import decode_message, parse_acknowledgment, parse_command


class MaintenanceProtocolTests(TestCase):
    def test_command_uses_strict_boolean_and_generation_types(self):
        self.assertEqual(parse_command(decode_message(b'{"enabled":true,"generation":2}')), (True, 2))
        for payload in ({"enabled": "true", "generation": 2}, {"enabled": True, "generation": False}, {"enabled": True, "generation": -1}, {"enabled": True, "generation": 1, "extra": 1}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_command(payload)

    def test_duplicate_fields_and_oversized_body_are_rejected(self):
        for raw in (b'{"enabled":true,"enabled":false,"generation":2}', b" " * 4097, b'{"generation":NaN}'):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                decode_message(raw)

    def test_acknowledgment_requires_matching_generation_mode_and_explicit_quiescence(self):
        payload = {"enabled": True, "generation": 2, "quiescent": True}
        self.assertTrue(parse_acknowledgment(payload, expected_enabled=True, expected_generation=2))
        for update in ({"generation": 1}, {"enabled": False}, {"quiescent": "true"}, {"extra": True}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                parse_acknowledgment({**payload, **update}, expected_enabled=True, expected_generation=2)
