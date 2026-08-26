from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from qc_tool.frontend.dashboard.access import delivery_action_capabilities
from qc_tool.frontend.dashboard.access import can_view_delivery
from qc_tool.frontend.dashboard.views import query_deliveries


class DeliveryAccessTests(TestCase):
    def test_actions_require_both_account_capability_and_owner_access(self):
        access = SimpleNamespace(
            can_run_qc=True,
            can_delete=True,
            can_submit=False,
            can_manage_user=lambda owner_id: owner_id == 7,
        )

        self.assertEqual(
            delivery_action_capabilities(access, 7),
            {
                "can_run_qc": True,
                "can_delete": True,
                "can_submit": False,
            },
        )
        self.assertEqual(
            delivery_action_capabilities(access, 8),
            {
                "can_run_qc": False,
                "can_delete": False,
                "can_submit": False,
            },
        )

    def test_delivery_query_includes_server_derived_ui_flags(self):
        access = SimpleNamespace(
            is_administrator=True,
            can_run_qc=True,
            can_delete=True,
            can_submit=True,
            can_manage_user=lambda owner_id: owner_id == 7,
        )
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor.description = [
            ("id",),
            ("action_owner_id",),
            ("s3_id",),
        ]
        cursor.fetchall.return_value = [(11, 7, None)]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor

        with patch(
            "qc_tool.frontend.dashboard.services.deliveries.listing.query."
            "access_for",
            return_value=access,
        ), patch(
            "qc_tool.frontend.dashboard.services.deliveries.listing.query."
            "connection.cursor",
            return_value=cursor_context,
        ):
            total, rows = query_deliveries(
                SimpleNamespace(id=7),
                include_capabilities=True,
            )

        self.assertEqual(total, 1)
        self.assertEqual(
            rows,
            [
                {
                    "id": 11,
                    "s3_id": None,
                    "type": "local",
                    "can_run_qc": True,
                    "can_delete": True,
                    "can_submit": True,
                }
            ],
        )

    def test_region_and_product_scopes_are_additive(self):
        access = SimpleNamespace(
            allows=lambda permission: True,
            is_administrator=False,
            user_id=99,
            can_view_region_deliveries=True,
            region_codes=frozenset({"CZ", "DE"}),
            can_view_product_deliveries=True,
            product_idents=frozenset({"clc", "water"}),
        )
        first_region_delivery = SimpleNamespace(
            user_id=1,
            user=SimpleNamespace(
                userprofile=SimpleNamespace(country="CZ"),
            ),
            product_ident="urban",
        )
        second_region_delivery = SimpleNamespace(
            user_id=4,
            user=SimpleNamespace(
                userprofile=SimpleNamespace(country="DE"),
            ),
            product_ident="urban",
        )
        product_delivery = SimpleNamespace(
            user_id=2,
            user=SimpleNamespace(
                userprofile=SimpleNamespace(country="SK"),
            ),
            product_ident="clc",
        )
        differently_cased_product_delivery = SimpleNamespace(
            user_id=5,
            user=SimpleNamespace(
                userprofile=SimpleNamespace(country="SK"),
            ),
            product_ident="WATER",
        )
        outside_delivery = SimpleNamespace(
            user_id=3,
            user=SimpleNamespace(
                userprofile=SimpleNamespace(country="SK"),
            ),
            product_ident="urban",
        )

        self.assertTrue(can_view_delivery(access, first_region_delivery))
        self.assertTrue(can_view_delivery(access, second_region_delivery))
        self.assertTrue(can_view_delivery(access, product_delivery))
        self.assertTrue(
            can_view_delivery(access, differently_cased_product_delivery)
        )
        self.assertFalse(can_view_delivery(access, outside_delivery))

    def test_product_scope_requires_both_capability_and_grant(self):
        delivery = SimpleNamespace(
            user_id=1,
            user=SimpleNamespace(
                userprofile=SimpleNamespace(country="SK"),
            ),
            product_ident="CLC",
        )
        base_access = {
            "allows": lambda permission: True,
            "is_administrator": False,
            "user_id": 99,
            "can_view_region_deliveries": False,
            "region_codes": frozenset(),
        }
        grant_without_capability = SimpleNamespace(
            **base_access,
            can_view_product_deliveries=False,
            product_idents=frozenset({"clc"}),
        )
        capability_without_grant = SimpleNamespace(
            **base_access,
            can_view_product_deliveries=True,
            product_idents=frozenset(),
        )

        self.assertFalse(
            can_view_delivery(grant_without_capability, delivery)
        )
        self.assertFalse(
            can_view_delivery(capability_without_grant, delivery)
        )

    def test_legacy_region_matching_is_exact(self):
        access = SimpleNamespace(
            allows=lambda permission: True,
            is_administrator=False,
            user_id=99,
            can_view_region_deliveries=True,
            region_codes=frozenset({"CZ"}),
            can_view_product_deliveries=False,
            product_idents=frozenset(),
        )
        differently_cased_delivery = SimpleNamespace(
            user_id=1,
            user=SimpleNamespace(
                userprofile=SimpleNamespace(country="cz"),
            ),
            product_ident="urban",
        )

        self.assertFalse(
            can_view_delivery(access, differently_cased_delivery)
        )

    def test_delivery_query_uses_additive_bound_scope_parameters(self):
        access = SimpleNamespace(
            is_administrator=False,
            can_view_region_deliveries=True,
            region_codes=frozenset({"DE", "CZ"}),
            can_view_product_deliveries=True,
            product_idents=frozenset({"water", "clc"}),
            can_manage_user=lambda owner_id: False,
        )
        cursor = MagicMock()
        cursor.fetchone.return_value = (0,)
        cursor.description = [("id",), ("action_owner_id",), ("s3_id",)]
        cursor.fetchall.return_value = []
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor

        with patch(
            "qc_tool.frontend.dashboard.services.deliveries.listing.query."
            "access_for",
            return_value=access,
        ), patch(
            "qc_tool.frontend.dashboard.services.deliveries.listing.query."
            "connection.cursor",
            return_value=cursor_context,
        ):
            query_deliveries(
                SimpleNamespace(id=7),
                filter='{"product_description": "CLC"}',
                search="sample",
            )

        total_call, rows_call = cursor.execute.call_args_list
        for call in (total_call, rows_call):
            sql, params = call.args
            self.assertIn(
                "d.user_id = %s OR up.country IN (%s, %s) "
                "OR LOWER(d.product_ident) IN (%s, %s)",
                sql,
            )
            self.assertEqual(
                params,
                [
                    7,
                    "CZ",
                    "DE",
                    "clc",
                    "water",
                    "CLC",
                    "%sample%",
                ],
            )
