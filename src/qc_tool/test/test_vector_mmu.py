#!/usr/bin/env python3


from qc_tool.test.helper import VectorCheckTestCase


class Test_mmu(VectorCheckTestCase):
    """Tests former vector.mmu used by swf_2015_vec_ras and ua_2018_stl."""
    def test(self):
        from qc_tool.vector.mmu import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, code varchar, shape_area real, geom geometry(Polygon, 4326));")

        # General features, class 1.
        cursor.execute("INSERT INTO reference VALUES (10, 'code1', 250001, ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (12, 'code1', 250000, ST_MakeEnvelope(12, 0, 13, 2, 4326));")

        # General features, class 2.
        cursor.execute("INSERT INTO reference VALUES (14, 'code2', 500001, ST_MakeEnvelope(14, 1, 15, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (16, 'code2', 500000, ST_MakeEnvelope(16, 0, 17, 2, 4326));")

        # Excluded feature.
        cursor.execute("INSERT INTO reference VALUES (30, 'code1', 249999, ST_MakeEnvelope(10.1, 1.1, 10.9, 1.9, 4326));")

        # Error feature.
        cursor.execute("INSERT INTO reference VALUES (31, 'code2', 499999, ST_MakeEnvelope(14.1, 1.1, 14.9, 1.9, 4326));")

        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "fid",
                                                         "fid_display_name": "row number"}},
                            "layers": ["reference"],
                            "complex_change": None,
                            "general_where": ["layer.shape_area >= 500000 OR layer.code <> 'code2'"],
                            "exception_where": ["FALSE"],
                            "warning_where": ["FALSE"],
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_reference_error ORDER BY fid;")
        self.assertListEqual([(31,)], cursor.fetchall())


class Test_mmu_clc_status(VectorCheckTestCase):
    """Tests former vector.mmu_clc_status used by clc_2012, clc_2018."""
    def test(self):
        from qc_tool.vector.mmu import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, shape_area real, geom geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO reference VALUES (10, 250001, ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (12, 250000, ST_MakeEnvelope(12, 0, 13, 2, 4326));")
        # Exception feature being at the boundary.
        cursor.execute("INSERT INTO reference VALUES (20, 249999, ST_MakeEnvelope(20, 0, 21, 2, 4326));")
        # Error feature.
        cursor.execute("INSERT INTO reference VALUES (30, 249999, ST_MakeEnvelope(10.1, 1.1, 10.9, 1.9, 4326));")

        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "fid",
                                                         "fid_display_name": "row number"}},
                            "layers": ["reference"],
                            "complex_change": None,
                            "general_where": ["layer.shape_area >= 250000"],
                            "exception_where": ["meta.is_marginal"],
                            "warning_where": ["FALSE"],
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_reference_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_exception ORDER BY fid;")
        self.assertListEqual([(20,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_error ORDER BY fid;")
        self.assertListEqual([(30,)], cursor.fetchall())

class Test_mmu_clc_change(VectorCheckTestCase):
    """Tests former vector.mmu_clc_change used by clc_2012, clc_2018."""
    def test(self):
        from qc_tool.vector.mmu import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()

        # Artificial margin.
        cursor.execute("CREATE TABLE margin (geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO margin VALUES (ST_MakeEnvelope(-1, -1, 100, 100, 4326));")

        # Add layer to be checked.
        cursor.execute("CREATE TABLE change (fid integer, shape_area real, code1 char(1), code2 char(1), geom geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO change VALUES (10, 50001, 'X', 'X', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        cursor.execute("INSERT INTO change VALUES (12, 50000, 'X', 'X', ST_MakeEnvelope(0, 2, 1, 3, 4326));")
        # Exception pair of features taking part in complex change with the same code in initial year.
        cursor.execute("INSERT INTO change VALUES (22, 40000, 'A', '1', ST_MakeEnvelope(0, 10, 1, 11, 4326));")
        cursor.execute("INSERT INTO change VALUES (23, 10000, 'A', '2', ST_MakeEnvelope(1, 10, 2, 11, 4326));")
        # Exception pair of features taking part in complex change with the same code in final year.
        cursor.execute("INSERT INTO change VALUES (25, 40000, '1', 'B', ST_MakeEnvelope(0, 12, 1, 13, 4326));")
        cursor.execute("INSERT INTO change VALUES (26, 10000, '2', 'B', ST_MakeEnvelope(1, 12, 2, 13, 4326));")
        # Error feature.
        cursor.execute("INSERT INTO change VALUES (30, 49999, 'C', 'C', ST_MakeEnvelope(0, 14, 1, 15, 4326));")
        # Error feature, complex change with total area below limit.
        cursor.execute("INSERT INTO change VALUES (32, 40000, '1', 'D', ST_MakeEnvelope(0, 16, 1, 17, 4326));")
        cursor.execute("INSERT INTO change VALUES (33,  9999, '2', 'D', ST_MakeEnvelope(1, 16, 2, 17, 4326));")

        self.params.update({"layer_defs": {"change": {"pg_layer_name": "change",
                                                      "pg_fid_name": "fid",
                                                      "fid_display_name": "row number"},
                                           "reference": {"pg_layer_name": "margin"}},
                            "layers": ["change"],
                            "complex_change": {"initial_code_column_name": "code1",
                                               "final_code_column_name": "code2",
                                               "area_column_name": "shape_area"},
                            "general_where": ["layer.shape_area >= 50000"],
                            "exception_where": ["meta.cc_area IS NOT NULL AND meta.cc_area >= 50000"],
                            "warning_where": ["FALSE"],
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT * FROM s01_change_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,)], cursor.fetchall())
        cursor.execute("SELECT * FROM s01_change_exception ORDER BY fid;")
        self.assertListEqual([(22,), (23,), (25,), (26,)], cursor.fetchall())
        cursor.execute("SELECT * FROM s01_change_error ORDER BY fid;")
        self.assertListEqual([(30,), (32,), (33,)], cursor.fetchall())


class Test_mmu_ua_status(VectorCheckTestCase):
    """Tests former vector.mmu_ua_status used by ua_2012, ua_2018."""
    def test(self):
        from qc_tool.vector.mmu import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, area real, code char(5), comment varchar(10), geom geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO reference VALUES (10, 1, '122', NULL, ST_MakeEnvelope(10, 1, 11, 8, 4326));")
        cursor.execute("INSERT INTO reference VALUES (12, 1, '1228', NULL, ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (14, 1, '12288', NULL, ST_MakeEnvelope(14, 1, 15, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (16, 1, '1228', NULL, ST_MakeEnvelope(16, 1, 17, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (18, 2501, '1', NULL, ST_MakeEnvelope(10, 8, 19, 10, 4326));")
        cursor.execute("INSERT INTO reference VALUES (20, 2500, '1', NULL, ST_MakeEnvelope(20, 1, 21, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (22, 10000, '2', NULL, ST_MakeEnvelope(59, 0, 80, 3, 4326));")
        cursor.execute("INSERT INTO reference VALUES (24, 10000, '3', NULL, ST_MakeEnvelope(24, 1, 25, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (26, 10000, '4', NULL, ST_MakeEnvelope(26, 1, 27, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (28, 10000, '5', NULL, ST_MakeEnvelope(28, 1, 29, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (30, 1, '9', NULL, ST_MakeEnvelope(30, 1, 31, 4, 4326));")

        # Exception features, touches fid=30.
        cursor.execute("INSERT INTO reference VALUES (40, 1, '2', NULL, ST_MakeEnvelope(31, 3, 41, 4, 4326));")

        # Exception feature at margin.
        cursor.execute("INSERT INTO reference VALUES (42, 100, '2', NULL, ST_MakeEnvelope(42, 0, 43, 4, 4326));")

        # Exception feature with comment.
        cursor.execute("INSERT INTO reference VALUES (43, 1, '1', 'comment01', ST_MakeEnvelope(60, 1, 61, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (44, 2499, '1', 'comment02', ST_MakeEnvelope(63, 1, 63, 2, 4326));")

        # Warning feature, touches fid=10.
        cursor.execute("INSERT INTO reference VALUES (50, 500, '2', NULL, ST_MakeEnvelope(10.1, 8, 11, 9, 4326));")

        # Error features breaking general requirements.
        cursor.execute("INSERT INTO reference VALUES (60, 1, '123', NULL, ST_MakeEnvelope(60, 1, 61, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (62, 2499, '1', NULL, ST_MakeEnvelope(63, 1, 63, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (64, 2499, '13', NULL, ST_MakeEnvelope(65, 1, 65, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (66, 9999, '2', NULL, ST_MakeEnvelope(67, 1, 67, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (68, 9999, '3', NULL, ST_MakeEnvelope(69, 1, 69, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (70, 9999, '4', NULL, ST_MakeEnvelope(71, 1, 71, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (72, 9999, '5', NULL, ST_MakeEnvelope(73, 1, 73, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (74, 20000, '6', NULL, ST_MakeEnvelope(75, 1, 75, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (76, 20000, '7', NULL, ST_MakeEnvelope(77, 1, 77, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (78, 20000, '8', NULL, ST_MakeEnvelope(79, 1, 79, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (79, 2499, '1', 'comment03', ST_MakeEnvelope(63, 1, 63, 2, 4326));")

        # Error feature breaking exception requirements.
        cursor.execute("INSERT INTO reference VALUES (80, 99, '4', NULL, ST_MakeEnvelope(80, 0, 81, 2, 4326));")

        # Error feature breaking warning requirements, touches fid=10.
        cursor.execute("INSERT INTO reference VALUES (82, 499, '2', NULL, ST_MakeEnvelope(10.1, 8, 11, 9, 4326));")

        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "fid",
                                                         "fid_display_name": "row number"}},
                            "layers": ["reference"],
                            "complex_change": None,
                            "general_where": [" layer.code LIKE '122%'",
                                              "OR",
                                              " (layer.code LIKE '1%'",
                                              "  AND layer.area >= 2500)",
                                              "OR",
                                              " (layer.code SIMILAR TO '[2-5]%'",
                                              "  AND layer.area >= 10000)",
                                              "OR",
                                              " layer.code LIKE '9%'"],
                            "exception_where": [" (meta.is_marginal",
                                                "  AND layer.area >= 100)",
                                                "OR",
                                                " EXISTS (SELECT FROM neighbours(meta.fid) WHERE code LIKE '9%')",
                                                "OR",
                                                " (layer.comment IS NOT NULL",
                                                "  AND has_comment(layer.comment, ARRAY['comment01',",
                                                "                                       'comment02']))"],
                            "warning_where": ["(layer.code NOT LIKE '122%'",
                                              " AND EXISTS (SELECT FROM neighbours(meta.fid) WHERE code LIKE '122%')",
                                              " AND layer.area >= 500)"],
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_reference_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (14,), (16,), (18,), (20,), (22,), (24,), (26,), (28,), (30,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_exception ORDER BY fid;")
        self.assertListEqual([(40,), (42,), (43,), (44,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_warning ORDER BY fid;")
        self.assertListEqual([(50,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_error ORDER BY fid;")
        self.assertListEqual([(60,), (62,), (64,), (66,), (68,), (70,), (72,), (74,), (76,), (78,), (79,), (80,), (82,)], cursor.fetchall())


class Test_mmu_ua_change(VectorCheckTestCase):
    """Tests former vector.mmu_ua_change used by ua_2018_change."""
    def test(self):
        from qc_tool.vector.mmu import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE change (fid integer, area real, code1 char(5), code2 char(5), comment varchar(10), geom geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO change VALUES (10, 1001, 'X', '1', NULL, ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (12, 1000, 'X', '1', NULL, ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (14, 1000, 'X', '12', NULL, ST_MakeEnvelope(14, 1, 15, 2, 4326));")

        cursor.execute("INSERT INTO change VALUES (16, 2500, 'X', '2', NULL, ST_MakeEnvelope(16, 1, 17, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (18, 2500, 'X', '3', NULL, ST_MakeEnvelope(18, 1, 19, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (20, 2500, 'X', '4', NULL, ST_MakeEnvelope(20, 1, 21, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (22, 2500, 'X', '5', NULL, ST_MakeEnvelope(22, 1, 23, 2, 4326));")

        # Exception features.
        cursor.execute("INSERT INTO change VALUES (30, 1, '122', 'X', NULL, ST_MakeEnvelope(30, 1, 31, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (32, 1, 'X', '122', NULL, ST_MakeEnvelope(32, 1, 33, 2, 4326));")

        # Exception features with comments.
        cursor.execute("INSERT INTO change VALUES (33, 999, 'X', '1', 'comment01', ST_MakeEnvelope(40, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (34, 999, 'X', '12', 'comment02', ST_MakeEnvelope(42, 1, 11, 2, 4326));")

        # Error features breaking general requirements.
        cursor.execute("INSERT INTO change VALUES (40, 999, 'X', '1', NULL, ST_MakeEnvelope(40, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (42, 999, 'X', '12', NULL, ST_MakeEnvelope(42, 1, 11, 2, 4326));")

        cursor.execute("INSERT INTO change VALUES (44, 2499, 'X', '2', NULL, ST_MakeEnvelope(44, 1, 45, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (46, 2499, 'X', '3', NULL, ST_MakeEnvelope(46, 1, 46, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (48, 2499, 'X', '4', NULL, ST_MakeEnvelope(48, 1, 48, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (50, 2499, 'X', '5', NULL, ST_MakeEnvelope(50, 1, 50, 2, 4326));")

        cursor.execute("INSERT INTO change VALUES (52, 20000, 'X', '6', NULL, ST_MakeEnvelope(52, 1, 53, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (54, 20000, 'X', '7', NULL, ST_MakeEnvelope(54, 1, 55, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (56, 20000, 'X', '8', NULL, ST_MakeEnvelope(56, 1, 57, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (58, 20000, 'X', '9', NULL, ST_MakeEnvelope(58, 1, 59, 2, 4326));")

        cursor.execute("INSERT INTO change VALUES (59, 999, 'X', '12', 'comment03', ST_MakeEnvelope(42, 1, 11, 2, 4326));")

        # Error features breaking exception requirements.
        cursor.execute("INSERT INTO change VALUES (60, 1, '123', 'X', NULL, ST_MakeEnvelope(12, 1, 13, 2, 4326));")

        self.params.update({"layer_defs": {"change": {"pg_layer_name": "change",
                                                      "pg_fid_name": "fid",
                                                      "fid_display_name": "row number"}},
                            "layers": ["change"],
                            "complex_change": None,
                            "general_where": [" (code2 LIKE '1%' AND area >= 1000)",
                                              "OR",
                                              " (code2 SIMILAR TO '[2-5]%' AND area >= 2500)"],
                            "exception_where": [" code1 LIKE '122%'",
                                                "OR",
                                                " code2 LIKE '122%'",
                                                "OR",
                                                " (comment IS NOT NULL",
                                                "  AND has_comment(comment, ARRAY['comment01',",
                                                "                                 'comment02']))"],
                            "warning_where": ["FALSE"],
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_change_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (14,), (16,), (18,), (20,), (22,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_change_exception ORDER BY fid;")
        self.assertListEqual([(30,), (32,), (33,), (34,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_change_error ORDER BY fid;")
        self.assertListEqual([(40,), (42,), (44,), (46,), (48,), (50,), (52,), (54,), (56,), (58,), (59,), (60,)], cursor.fetchall())


class Test_mmu_n2k(VectorCheckTestCase):
    """Tests former vector.mmu_n2k used by n2k_2012."""
    def test(self):
        from qc_tool.vector.mmu import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE n2k (fid integer,"
                                        " area_ha real,"
                                        " maes_4_1 integer,"
                                        " maes_1_2 integer,"
                                        " maes_3_2 integer,"
                                        " maes_4_2 integer,"
                                        " comment2 varchar(40),"
                                        " geom geometry(Polygon, 4326));")

        # Artificial margin as a general feature.
        cursor.execute("INSERT INTO n2k VALUES (0, 0.5, NULL, 1, 100, 1000, NULL, ST_MakeEnvelope(-1, -1, 100, 100, 4326));")

        # Marginal features.
        cursor.execute("INSERT INTO n2k VALUES (10, 0.1, NULL, 8, 800, 8000, NULL, ST_MakeEnvelope(-1, 0, 1, 1, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (11, 0.0999, NULL, 8, 800, 8000, NULL, ST_MakeEnvelope(-1, 2, 1, 3, 4326));")

        # Linear features.
        cursor.execute("INSERT INTO n2k VALUES (20, 0.1, NULL, 1, 121, 1210, NULL, ST_MakeEnvelope(0, 4, 1, 5, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (21, 0.1, NULL, 1, 121, 1211, NULL, ST_MakeEnvelope(0, 6, 1, 7, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (22, 0.1, NULL, 1, 122, 1220, NULL, ST_MakeEnvelope(0, 8, 1, 9, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (23, 0.1, NULL, 9, 911, 9110, NULL, ST_MakeEnvelope(0, 10, 1, 11, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (24, 0.1, NULL, 9, 912, 9120, NULL, ST_MakeEnvelope(0, 12, 1, 13, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (25, 0.0999, NULL, 1, 121, 1210, NULL, ST_MakeEnvelope(0, 14, 1, 15, 4326));")

        # Urban feature touching road or railway.
        cursor.execute("INSERT INTO n2k VALUES (30, 0.25, NULL, 1, 100, 1000, NULL, ST_MakeEnvelope(1, 14, 2, 15, 4326));")

        # Complex change features.
        cursor.execute("INSERT INTO n2k VALUES (40, 0.2, 9002, 9, 900, 9001, NULL, ST_MakeEnvelope(0, 16, 1, 17, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (41, 0.2, 9003, 9, 900, 9001, NULL, ST_MakeEnvelope(1, 16, 2, 17, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (42, 0.2, 9004, 9, 900, 9001, NULL, ST_MakeEnvelope(2, 16, 3, 17, 4326));")

        # Features with specific comment.
        cursor.execute("INSERT INTO n2k VALUES (50, 0, NULL, 8, 800, 8000, 'comment1', ST_MakeEnvelope(60, 0, 61, 1, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (51, 0, NULL, 8, 800, 8000, 'comment2; xxx', ST_MakeEnvelope(60, 0, 61, 1, 4326));")

        cursor.execute("INSERT INTO n2k VALUES (52, 0, NULL, 8, 800, 8000, NULL, ST_MakeEnvelope(60, 0, 61, 1, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (53, 0, NULL, 8, 800, 8000, 'comment_nok', ST_MakeEnvelope(60, 0, 61, 1, 4326));")

        self.params.update({"layer_defs": {"n2k": {"pg_layer_name": "n2k",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["n2k"],
                            "complex_change": {"initial_code_column_name": "maes_4_1",
                                               "final_code_column_name": "maes_4_2",
                                               "area_column_name": "area_ha"},
                            "general_where": ["layer.area_ha >= 0.5"],
                            "exception_where": [" (meta.is_marginal",
                                                "  AND layer.area_ha >= 0.1)",
                                                "OR",
                                                " (layer.maes_1_2 = 1",
                                                "  AND layer.maes_3_2 NOT IN (121, 122)",
                                                "  AND EXISTS (SELECT FROM neighbours(meta.fid) WHERE maes_3_2 IN (121, 122))",
                                                "  AND layer.area_ha >= 0.25)",
                                                "OR",
                                                " (layer.maes_3_2 IN (121, 122, 911, 912)",
                                                "  AND layer.area_ha >= 0.1)",
                                                "OR",
                                                " (meta.cc_area IS NOT NULL",
                                                "  AND meta.cc_area >= 0.5)",
                                                "OR",
                                                " (layer.comment2 IS NOT NULL",
                                                "  AND has_comment(layer.comment2, ARRAY['comment1',",
                                                "                                        'comment2']))"],
                            "warning_where": ["FALSE"],
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_n2k_general ORDER BY fid;")
        self.assertListEqual([(0,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_n2k_exception ORDER BY fid;")
        self.assertListEqual([(10,), (20,), (21,), (22,), (23,), (24,), (30,), (40,), (41,), (42,), (50,), (51,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_n2k_error ORDER BY fid;")
        self.assertListEqual([(11,), (25,), (52,), (53,)], cursor.fetchall())


class Test_mmu_rpz(VectorCheckTestCase):
    """Tests former vector.mmu_rpz used by rpz_2012, rpz_2018."""
    def test(self):
        from qc_tool.vector.mmu import run_check

        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE rpz (fid integer, area_ha real, code integer, ua char(1), comment varchar(40), geom geometry(Polygon, 4326));")

        # Artificial margin as a general feature.
        self.cursor.execute("INSERT INTO rpz VALUES (0, 0.5, 10, NULL, NULL, ST_MakeEnvelope(-1, -1, 50, 50, 4326));")

        # Feature being part of Urban Atlas Core Region.
        self.cursor.execute("INSERT INTO rpz VALUES (1, 0.01, 1, 'U', NULL, ST_MakeEnvelope(50, -1, 51, 50, 4326));")

        # Marginal features.
        self.cursor.execute("INSERT INTO rpz VALUES (10, 0.2, 8, NULL, NULL, ST_MakeEnvelope(-1, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (11, 0.19, 8, NULL, NULL, ST_MakeEnvelope(-1, 2, 1, 3, 4326));")

        # Marginal features touching Urban Atlas Core Region.
        self.cursor.execute("INSERT INTO rpz VALUES (12, 0.2, 8, NULL, NULL, ST_MakeEnvelope(49, 0, 50, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (13, 0.19, 8, NULL, NULL, ST_MakeEnvelope(49, 2, 50, 3, 4326))")

        # Urban features.
        self.cursor.execute("INSERT INTO rpz VALUES (20, 0.25, 1111, NULL, NULL, ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (21, 0.24, 1111, NULL, NULL, ST_MakeEnvelope(2, 1, 3, 2, 4326))")
        self.cursor.execute("INSERT INTO rpz VALUES (22, 0.25, 1112, NULL, NULL, ST_MakeEnvelope(2, 2, 3, 3, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (23, 0.24, 1112, NULL, NULL, ST_MakeEnvelope(2, 3, 3, 4, 4326))")
        self.cursor.execute("INSERT INTO rpz VALUES (24, 0.25, 1113, NULL, NULL, ST_MakeEnvelope(2, 4, 3, 5, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (25, 0.24, 1113, NULL, NULL, ST_MakeEnvelope(2, 5, 3, 6, 4326))")

        # Linear features.
        self.cursor.execute("INSERT INTO rpz VALUES (30, 0.1,  1210, NULL, NULL, ST_MakeEnvelope(4, 0, 5, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (31, 0.09, 1210, NULL, NULL, ST_MakeEnvelope(4, 1, 5, 2, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (32, 0.1,  1220, NULL, NULL, ST_MakeEnvelope(4, 2, 5, 3, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (33, 0.09, 1220, NULL, NULL, ST_MakeEnvelope(4, 3, 5, 4, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (34, 0.1,  1230, NULL, NULL, ST_MakeEnvelope(4, 4, 5, 5, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (35, 0.09, 1230, NULL, NULL, ST_MakeEnvelope(4, 5, 5, 6, 4326));")

        # Features with specific comment.
        self.cursor.execute("INSERT INTO rpz VALUES (40, 0, 8, NULL, 'comment1', ST_MakeEnvelope(6, 0, 7, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (41, 0, 8, NULL, 'comment2 nok', ST_MakeEnvelope(6, 0, 7, 1, 4326));")

        self.params.update({"layer_defs": {"rpz": {"pg_layer_name": "rpz",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["rpz"],
                            "complex_change": None,
                            "general_where": [" layer.ua IS NOT NULL",
                                              "OR",
                                              " layer.area_ha >= 0.5"],
                            "exception_where": [" ((meta.is_marginal",
                                                "   OR EXISTS (SELECT FROM neighbours(meta.fid) WHERE ua IS NOT NULL))",
                                                "  AND layer.area_ha >= 0.2)",
                                                "OR",
                                                " (layer.code IN (1111, 1112)",
                                                "  AND layer.area_ha >= 0.25)",
                                                "OR",
                                                " (layer.code IN (1210, 1220)",
                                                "  AND layer.area_ha >= 0.1)",
                                                "OR",
                                                " (layer.comment IS NOT NULL",
                                                "  AND has_comment(layer.comment, ARRAY['comment1']))"],
                            "warning_where": ["FALSE"],
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        self.cursor.execute("SELECT fid FROM s01_rpz_general ORDER BY fid;")
        self.assertListEqual([(0,), (1,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_rpz_exception ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (20,), (22,), (30,), (32,), (40,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_rpz_error ORDER BY fid;")
        self.assertListEqual([(11,), (13,), (21,), (23,), (24,), (25,), (31,), (33,), (34,), (35,), (41,)], self.cursor.fetchall())

class Test_mmu_cz(VectorCheckTestCase):
    """Tests former vector.mmu_cz used by cz_2012, cz_2018, cz_2018_change."""
    def test(self):
        from qc_tool.vector.mmu import run_check

        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE mytable (fid integer, code1 char, code2 char, geom geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO mytable VALUES (1, 'C', 'D', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                      " (2, 'C', 'D', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                      " (3, 'C', 'D', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                      " (4, 'C', 'D', ST_MakeEnvelope(3, 0, 4, 1, 4326));")

        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "code_column_names": ["code1", "code2"],
                            "complex_change": None,
                            "general_where": ["layer.fid = 1"],
                            "exception_where": ["layer.fid IN (2, 3)"],
                            "warning_where": ["FALSE"],
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        self.cursor.execute("SELECT fid FROM s01_mytable_general;")
        self.assertListEqual([(1,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_mytable_exception ORDER BY fid;")
        self.assertListEqual([(2,), (3,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_mytable_warning;")
        self.assertListEqual([], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_mytable_error;")
        self.assertListEqual([(4,)], self.cursor.fetchall())
