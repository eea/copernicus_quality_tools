"""The upgrade probe must create historical rows before later schema changes."""

from django.db.migrations.graph import MigrationGraph
from django.test import SimpleTestCase

from qc_tool.database.checks.schema import baseline_targets


class BaselineTargetTests(SimpleTestCase):
    def test_new_app_dependencies_do_not_advance_the_pre_seed_schema(self):
        graph = MigrationGraph()
        framework_head = ("auth", "framework_head")
        accounts_baseline = ("accounts", "release_baseline")
        dashboard_baseline = ("dashboard", "release_baseline")
        dashboard_upgrade = ("dashboard", "later_schema")
        new_app_head = ("future_app", "first_schema")
        for node in (
            framework_head,
            accounts_baseline,
            dashboard_baseline,
            dashboard_upgrade,
            new_app_head,
        ):
            graph.add_node(node, None)
        for child, parent in (
            (accounts_baseline, framework_head),
            (dashboard_baseline, framework_head),
            (dashboard_upgrade, dashboard_baseline),
            (new_app_head, dashboard_upgrade),
        ):
            graph.add_dependency("probe", child, parent)

        targets = baseline_targets(
            graph,
            (accounts_baseline, dashboard_baseline),
            {"accounts", "dashboard", "future_app"},
        )
        applied_before_seed = {
            node for target in targets for node in graph.forwards_plan(target)
        }

        self.assertEqual(
            applied_before_seed,
            {framework_head, accounts_baseline, dashboard_baseline},
        )
        self.assertIn(new_app_head, graph.leaf_nodes())
        self.assertIn(dashboard_upgrade, graph.forwards_plan(new_app_head))
