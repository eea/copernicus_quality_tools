"""The shared audit snapshot accepts service actors without changing semantics."""

from types import SimpleNamespace
import unittest

from qc_tool.frontend.accounts.services.actors import actor_username


class ActorUsernameTests(unittest.TestCase):
    def test_absent_actor_or_name_has_an_empty_snapshot(self):
        self.assertEqual(actor_username(None), "")
        self.assertEqual(actor_username(object()), "")

    def test_callable_user_getter_takes_precedence(self):
        actor = SimpleNamespace(username="fallback", get_username=lambda: "canonical")
        self.assertEqual(actor_username(actor), "canonical")

    def test_non_callable_getter_falls_back_to_username(self):
        self.assertEqual(actor_username(SimpleNamespace(get_username="ignored", username="actor")), "actor")

    def test_non_string_names_keep_the_existing_string_conversion(self):
        self.assertEqual(actor_username(SimpleNamespace(get_username=lambda: 42)), "42")
        self.assertEqual(actor_username(SimpleNamespace(username=None)), "None")

    def test_snapshots_are_limited_by_characters_not_encoded_bytes(self):
        value = "ž" * 151
        self.assertEqual(actor_username(SimpleNamespace(username=value)), value[:150])
        self.assertEqual(actor_username(SimpleNamespace(get_username=lambda: value)), value[:150])

    def test_getter_failures_are_not_silently_changed_to_anonymous_names(self):
        def broken_getter():
            raise RuntimeError("actor lookup failed")

        with self.assertRaisesRegex(RuntimeError, "actor lookup failed"):
            actor_username(SimpleNamespace(get_username=broken_getter))
