"""Predicate comparison retains integrity semantics across backend SQL forms."""

from django.test import SimpleTestCase

from qc_tool.database.deployment import _index_signature
from qc_tool.database.predicates import named_sqlite_check, predicate_signature


class SchemaPredicateTests(SimpleTestCase):
    def test_postgres_any_and_casts_match_model_membership(self):
        model = '''"state" IN ('pending', 'accepted')'''
        postgres = "CHECK ((state)::text = ANY ((ARRAY['pending'::varchar, 'accepted'::varchar])::text[]))"
        self.assertEqual(predicate_signature(model), predicate_signature(postgres))

    def test_postgres_double_wrapped_array_matches_current_release_states(self):
        postgres = "CHECK (((coverage_state)::text = ANY ((ARRAY['unknown'::character varying, 'draft'::character varying, 'authoritative'::character varying, 'retired'::character varying])::text[])))"
        model = "coverage_state IN ('unknown', 'draft', 'authoritative', 'retired')"
        self.assertEqual(predicate_signature(model), predicate_signature(postgres))

    def test_reordered_conjunctions_preserve_the_same_predicate(self):
        self.assertEqual(
            predicate_signature('''"size" >= 0 AND ("owner_id" IS NOT NULL AND "state" = 'ready')'''),
            predicate_signature("state = 'ready' AND owner_id IS NOT NULL AND size >= 0"),
        )

    def test_parentheses_preserve_boolean_precedence(self):
        self.assertNotEqual(
            predicate_signature("a = 1 AND (b = 2 OR c = 3)"),
            predicate_signature("(a = 1 AND b = 2) OR c = 3"),
        )

    def test_changed_values_operators_and_null_rules_remain_distinct(self):
        for original, changed in (
            ("size >= 0", "size > 0"),
            ("state = 'accepted'", "state = 'ACCEPTED'"),
            ("submitted IS NOT NULL", "submitted IS NULL"),
            ("state IN ('pending', 'accepted')", "state IN ('pending', 'rejected')"),
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(predicate_signature(original), predicate_signature(changed))

    def test_partial_index_literal_case_changes_its_integrity_contract(self):
        original = "CREATE UNIQUE INDEX accepted ON receipts (unit_id) WHERE review_state = 'accepted'"
        changed = "CREATE UNIQUE INDEX accepted ON receipts (unit_id) WHERE review_state = 'ACCEPTED'"
        self.assertNotEqual(_index_signature(original), _index_signature(changed))

    def test_negated_comparison_matches_backend_not_equal_form(self):
        self.assertEqual(predicate_signature("NOT (notes = '')"), predicate_signature("notes <> ''"))
        self.assertEqual(predicate_signature("NOT (owner_id IS NULL)"), predicate_signature("owner_id IS NOT NULL"))

    def test_unsupported_or_incomplete_syntax_is_refused(self):
        for predicate in ("", "size >=", "length(notes) > 0", "size >= 0 trailing", "size >= 0; SELECT 1"):
            with self.subTest(predicate=predicate), self.assertRaises(ValueError):
                predicate_signature(predicate)

    def test_named_sqlite_checks_preserve_nested_and_escaped_literals(self):
        sql = """CREATE TABLE probe (
            name TEXT,
            CONSTRAINT "other_rule" CHECK (name != 'skip'),
            CONSTRAINT "name_rule" CHECK ((name = 'O''Brien )' OR name = '(ok)') AND name IS NOT NULL)
        )"""
        actual = named_sqlite_check(sql, "name_rule")
        self.assertEqual(
            predicate_signature(actual),
            predicate_signature("(name = 'O''Brien )' OR name = '(ok)') AND name IS NOT NULL"),
        )
        self.assertEqual(named_sqlite_check(sql, "other_rule"), "name != 'skip'")

    def test_missing_or_unclosed_sqlite_check_is_unverifiable(self):
        self.assertIsNone(named_sqlite_check('CREATE TABLE probe (id INTEGER)', "required"))
        self.assertIsNone(named_sqlite_check('CREATE TABLE probe (CONSTRAINT required CHECK ((id > 0)', "required"))
