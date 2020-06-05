#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.test.helper import VectorCheckTestCase


class Test_table_exists(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.helper import table_exists
        cursor = self.params["connection_manager"].get_connection().cursor()
        self.assertFalse(table_exists(cursor.connection, "mylayer"))
        cursor.execute("CREATE TABLE mylayer ();")
        self.assertTrue(table_exists(cursor.connection, "mylayer"))


class Test_column_exists(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.helper import column_exists
        cursor = self.params["connection_manager"].get_connection().cursor()
        self.assertFalse(column_exists(cursor.connection, "mylayer", "mycolumn"))
        cursor.execute("CREATE TABLE mylayer (fid integer);")
        self.assertFalse(column_exists(cursor.connection, "mylayer", "mycolumn"))
        cursor.execute("ALTER TABLE mylayer ADD COLUMN mycolumn integer;")
        self.assertTrue(column_exists(cursor.connection, "mylayer", "mycolumn"))


class Test_extract_srid(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.helper import extract_srid
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mylayer (geom geometry(Polygon, 4326));")
        srid = extract_srid(cursor.connection, "mylayer")
        self.assertEqual(4326, srid)


class Test_PartitionedLayer(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.params["connection_manager"].get_connection()
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE mylayer (xfid integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mylayer VALUES (1, ST_MakeEnvelope(-1.1, -2.2, 1, 1, 4326)),"
                                                 " (2, ST_MakeEnvelope(10, 10, 11.3, 11.4, 4326));")

    def test_setup_srid(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        self.assertEqual(4326, partitioned_layer.srid)

    def test_extract_extent(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        xmin, ymin, xmax, ymax = partitioned_layer.extract_extent()
        self.assertListEqual([-1.1, -2.2, 11.3, 11.4], [xmin, ymin, xmax, ymax])

    def test_expand_box(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid", grid_size=2)
        xmin, ymin, xmax, ymax = partitioned_layer.expand_box(-1.1, -2.2, 11.3, 11.4)
        self.assertListEqual([-4, -6, 14, 14], [xmin, ymin, xmax, ymax])

    def test_fill_initial_partition(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid", srid=4326)
        partitioned_layer._create_partition_table()
        initial_partition_id = partitioned_layer._fill_initial_partition(-4, -6, 14, 14)
        cursor = self.connection.cursor()
        cursor.execute("SELECT partition_id, superpartition_id, num_vertices, ST_AsText(geom) FROM partition_mylayer;")
        self.assertListEqual([(1, None, None, "POLYGON((-4 -6,-4 14,14 14,14 -6,-4 -6))")],
                             cursor.fetchall())
        
    def test_fill_initial_features(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid", srid=4326)
        partitioned_layer._create_polygon_dump()
        partitioned_layer._create_feature_table()
        partitioned_layer._fill_initial_features(1)
        cursor = self.connection.cursor()
        cursor.execute("SELECT fid, partition_id, ST_AsText(geom) FROM feature_mylayer ORDER BY fid;")
        self.assertListEqual([(1, 1, "POLYGON((-1.1 -2.2,-1.1 1,1 1,1 -2.2,-1.1 -2.2))"),
                              (2, 1, "POLYGON((10 10,10 11.4,11.3 11.4,11.3 10,10 10))")],
                             cursor.fetchall())
        
    def test_update_npoints(self):
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer,"
                                                      " num_vertices integer,"
                                                      " geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (1, 1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (2, NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (3, NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        cursor.execute("CREATE TABLE feature_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO feature_mylayer VALUES (2, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                         " (3, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                         " (3, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        partitioned_layer._update_npoints()
        cursor.execute("SELECT partition_id, num_vertices FROM partition_mylayer ORDER BY partition_id;")
        self.assertListEqual([(1, 1), (2, 5), (3, 10)],
                             cursor.fetchall())

    def test_split_partitions(self):
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer,"
                                                      " superpartition_id integer,"
                                                      " num_vertices integer,"
                                                      " geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (2, 1, 4, ST_MakeEnvelope(0, 0, 4, 1, 4326)),"
                                                           " (3, 1, 5, ST_MakeEnvelope(0, 0, 6, 1, 4326));")
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid", srid=4326, max_vertices=4)
        split_count = partitioned_layer._split_partitions()
        self.assertEqual(1, split_count)
        cursor = self.connection.cursor()
        cursor.execute("SELECT partition_id, superpartition_id, num_vertices, ST_AsText(geom) FROM partition_mylayer ORDER BY partition_id;")
        self.assertListEqual([(2, 1, 4, "POLYGON((0 0,0 1,4 1,4 0,0 0))"),
                              (3, 1, 5, "POLYGON((0 0,0 1,6 1,6 0,0 0))"),
                              (None, 3, None, "POLYGON((0 0,0 1,3 1,3 0,0 0))"),
                              (None, 3, None, "POLYGON((3 0,3 1,6 1,6 0,3 0))")],
                             cursor.fetchall())

    def test_fill_subpartitions(self):
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer,"
                                                      " superpartition_id integer,"
                                                      " num_vertices integer,"
                                                      " geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (2, 1, NULL, ST_MakeEnvelope(-10, 0, 0, 3, 4326)),"
                                                           " (3, 1, NULL, ST_MakeEnvelope(0, 0, 10, 3, 4326)),"
                                                           " (4, 3, NULL, ST_MakeEnvelope(0, 0, 5, 3, 4326)),"
                                                           " (5, 3, NULL, ST_MakeEnvelope(5, 0, 10, 3, 4326));")
        cursor.execute("CREATE TABLE feature_mylayer (fid integer, partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO feature_mylayer VALUES (1, 2, ST_MakeEnvelope(-5, 1, -3, 2, 4326)),"
                                                         " (2, 3, ST_MakeEnvelope(4, 1, 7, 2, 4326)),"
                                                         " (3, 3, ST_MakeEnvelope(5, 1, 6, 2, 4326));")
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        partitioned_layer._create_polygon_dump()
        partitioned_layer._fill_subpartitions()
        cursor.execute("SELECT fid, partition_id, ST_AsText(geom) FROM feature_mylayer ORDER BY fid, partition_id;")
        self.assertListEqual([(1, 2, "POLYGON((-5 1,-5 2,-3 2,-3 1,-5 1))"),
                              (2, 3, "POLYGON((4 1,4 2,7 2,7 1,4 1))"),
                              (2, 4, "POLYGON((4 1,4 2,5 2,5 1,4 1))"),
                              (2, 5, "POLYGON((5 2,7 2,7 1,5 1,5 2))"),
                              (3, 5, "POLYGON((5 1,5 2,6 2,6 1,5 1))")],
                             cursor.fetchall())

    def test_delete_superitems(self):
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer, superpartition_id integer);")
        cursor.execute("INSERT INTO partition_mylayer VALUES (2, 1),"
                                                           " (3, 1),"
                                                           " (4, 3),"
                                                           " (5, 3);")
        cursor.execute("CREATE TABLE feature_mylayer (fid integer, partition_id integer);")
        cursor.execute("INSERT INTO feature_mylayer VALUES (1, 2),"
                                                         " (2, 3),"
                                                         " (3, 3),"
                                                         " (4, 4),"
                                                         " (5, 5),"
                                                         " (6, 5);")
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        partitioned_layer._delete_superitems()
        cursor.execute("SELECT partition_id, superpartition_id FROM partition_mylayer ORDER BY partition_id;")
        self.assertListEqual([(2, 1),
                              (4, 3),
                              (5, 3)],
                             cursor.fetchall())
        cursor.execute("SELECT fid, partition_id FROM feature_mylayer ORDER BY fid;")
        self.assertListEqual([(1, 2),
                              (4, 4),
                              (5, 5),
                              (6, 5)],
                             cursor.fetchall())


class Test_NeighbourTable(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.params["connection_manager"].get_connection()
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE feature_mylayer (fid integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO feature_mylayer VALUES (1, ST_MakeEnvelope(0, 0, 1.1, 1, 4326)),"
                                                         " (2, ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (3, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                         " (4, ST_MakeEnvelope(4, 0, 5, 1, 4326)),"
                                                         " (5, ST_MakeEnvelope(5, 0, 6, 1, 4326));")

    def test_fill(self):
        from qc_tool.vector.helper import PartitionedLayer
        from qc_tool.vector.helper import NeighbourTable
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid", srid=4326)
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table._create_neighbour_table()
        neighbour_table._fill()
        cursor = self.connection.cursor()
        cursor.execute("SELECT fida, fidb, dim FROM neighbour_mylayer ORDER BY fida, fidb;")
        self.assertListEqual([(1, 2, 2),
                              (2, 1, 2),
                              (2, 3, 1),
                              (3, 2, 1),
                              (4, 5, 1),
                              (5, 4, 1)],
                             cursor.fetchall())


class Test_MetaTable(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.params["connection_manager"].get_connection()
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE mylayer (xfid integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mylayer VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                 " (2, ST_MakeEnvelope(1, 0, 2, 1, 4326));")

    def test_init_meta_table(self):
        from qc_tool.vector.helper import _MetaTable
        meta_table = _MetaTable(self.connection, "mylayer", "xfid")
        meta_table._create_meta_table()
        cursor = self.connection.cursor()
        cursor.execute("SELECT fid FROM meta_mylayer ORDER BY fid;")
        self.assertListEqual([(1,), (2,)], cursor.fetchall())


class Test_InteriorTable(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.helper import _InteriorTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (2, ST_MakeEnvelope(-10, -10, 1, 10, 4326)),"
                                                           " (5, ST_MakeEnvelope(10, 1, 20, 2, 4326));")
        cursor.execute("CREATE TABLE feature_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO feature_mylayer VALUES (2, ST_MakeEnvelope(-10, -10, 1, 9, 4326)),"
                                                         " (5, ST_MakeEnvelope(10, 1, 11, 2, 4326)),"
                                                         " (5, ST_MakeEnvelope(19, 1, 20, 2, 4326));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        interior_table = _InteriorTable(partitioned_layer)
        interior_table._create_interior_table()
        interior_table._fill()
        cursor.execute("SELECT partition_id, ST_AsText(geom) FROM interior_mylayer ORDER BY partition_id;")
        self.assertListEqual([(2, 'MULTIPOLYGON(((-10 -10,-10 9,1 9,1 -10,-10 -10)))'),
                              (5, 'MULTIPOLYGON(((10 1,10 2,11 2,11 1,10 1)),((19 1,19 2,20 2,20 1,19 1)))')],
                             cursor.fetchall())

    def test_empty_interior(self):
        from qc_tool.vector.helper import _InteriorTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        cursor.execute("CREATE TABLE feature_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        interior_table = _InteriorTable(partitioned_layer)
        interior_table._create_interior_table()
        interior_table._fill()
        cursor.execute("SELECT partition_id, ST_AsText(geom) FROM interior_mylayer ORDER BY partition_id;")
        self.assertListEqual([], cursor.fetchall())


class Test_ExteriorTable(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.helper import _ExteriorTable
        from qc_tool.vector.helper import _InteriorTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (2, ST_MakeEnvelope(-10, -10, 1, 10, 4326)),"
                                                           " (5, ST_MakeEnvelope(10, 1, 20, 2, 4326));")
        cursor.execute("CREATE TABLE interior_mylayer (partition_id integer, geom geometry(MultiPolygon, 4326));")
        cursor.execute("INSERT INTO interior_mylayer VALUES (2, ST_Multi(ST_MakeEnvelope(-10, -10, 1, 9, 4326))),"
                                                          " (5, ST_Union(ST_MakeEnvelope(10, 1, 11, 2, 4326),"
                                                                       " ST_MakeEnvelope(19, 1, 20, 2, 4326)));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        interior_table = _InteriorTable(partitioned_layer)
        exterior_table = _ExteriorTable(interior_table)
        exterior_table._create_exterior_table()
        exterior_table._fill()
        cursor.execute("SELECT partition_id, ST_AsText(geom) FROM exterior_mylayer ORDER BY partition_id;")
        self.assertListEqual([(2, 'MULTIPOLYGON(((-10 9,-10 10,1 10,1 9,-10 9)))'),
                              (5, 'MULTIPOLYGON(((11 2,19 2,19 1,11 1,11 2)))')],
                             cursor.fetchall())

    def test_empty_interior(self):
        from qc_tool.vector.helper import _ExteriorTable
        from qc_tool.vector.helper import _InteriorTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        cursor.execute("CREATE TABLE interior_mylayer (partition_id integer, geom geometry(MultiPolygon, 4326));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        interior_table = _InteriorTable(partitioned_layer)
        exterior_table = _ExteriorTable(interior_table)
        exterior_table._create_exterior_table()
        exterior_table._fill()
        cursor.execute("SELECT partition_id, ST_AsText(geom) FROM exterior_mylayer ORDER BY partition_id;")
        self.assertListEqual([(1, 'MULTIPOLYGON(((0 0,0 1,1 1,1 0,0 0)))')], cursor.fetchall())

    def test_empty_exterior(self):
        from qc_tool.vector.helper import _ExteriorTable
        from qc_tool.vector.helper import _InteriorTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        cursor.execute("CREATE TABLE interior_mylayer (partition_id integer, geom geometry(MultiPolygon, 4326));")
        cursor.execute("INSERT INTO interior_mylayer VALUES (1, ST_Multi(ST_MakeEnvelope(0, 0, 1, 1, 4326)));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        interior_table = _InteriorTable(partitioned_layer)
        exterior_table = _ExteriorTable(interior_table)
        exterior_table._create_exterior_table()
        exterior_table._fill()
        cursor.execute("SELECT partition_id, ST_AsText(geom) FROM exterior_mylayer ORDER BY partition_id;")
        self.assertListEqual([], cursor.fetchall())


class Test_MarginalProperty(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.helper import MarginalProperty
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE meta_mylayer (fid integer);")
        cursor.execute("CREATE TABLE feature_mylayer (fid integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO feature_mylayer VALUES (2, ST_MakeEnvelope(1, 1, 2, 2, 4326)),"
                                                         " (2, ST_MakeEnvelope(3, 1, 4, 2, 4326)),"
                                                         " (3, ST_MakeEnvelope(5, 1, 6, 2, 4326)),"
                                                         " (4, ST_MakeEnvelope(7, 1, 8, 2, 4326));")
        cursor.execute("CREATE TABLE exterior_mylayer (geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO exterior_mylayer VALUES (ST_MakeEnvelope(3, 2, 4, 3, 4326)),"
                                                          " (ST_MakeEnvelope(5, 2, 6, 3, 4326));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        marginal_property = MarginalProperty(partitioned_layer)
        marginal_property._prepare_meta_table()
        cursor.execute("INSERT INTO meta_mylayer (fid) VALUES (2), (3), (4);")
        marginal_property._fill()
        cursor.execute("SELECT fid, is_marginal FROM meta_mylayer ORDER BY fid;")
        self.assertListEqual([(2, True), (3, True), (4, False)],
                             cursor.fetchall())


class Test_ComplexChangeProperty(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.params["connection_manager"].get_connection()
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE mylayer (xfid integer, code1 char, code2 char, area real, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mylayer VALUES (1, 'A', 'A',   1, NULL),"
                                                 " (2, 'A', 'B',   2, NULL),"
                                                 " (3, 'A', 'C',   4, NULL),"
                                                 " (4, 'A', 'D',   8, NULL),"
                                                 " (5, 'B', 'D',  16, NULL),"
                                                 " (6, 'C', 'D',  32, NULL),"
                                                 " (7, 'D', 'D',  64, NULL),"
                                                 " (8, 'A', 'D', 128, NULL);")

    def test_fill_cluster(self):
        from qc_tool.vector.helper import PartitionedLayer
        from qc_tool.vector.helper import NeighbourTable
        from qc_tool.vector.helper import _MetaTable
        from qc_tool.vector.helper import ComplexChangeProperty
        cursor = self.connection.cursor()
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table._create_neighbour_table()
        cursor.execute("INSERT INTO neighbour_mylayer VALUES (1, 2, 1), (2, 1, 1),"
                                                           " (2, 3, 1), (3, 2, 1),"
                                                           " (3, 4, 1), (4, 3, 1),"
                                                           " (4, 5, 1), (5, 4, 1),"
                                                           " (5, 6, 1), (6, 5, 1),"
                                                           " (6, 7, 1), (7, 6, 1);")
        meta_table = _MetaTable(self.connection, "mylayer", "xfid")
        meta_table._create_meta_table()
        complex_change_property = ComplexChangeProperty(neighbour_table, "code1", "code2", "area")
        complex_change_property._prepare_meta_table()
        complex_change_property._fill_cluster("cc_id_initial", "code1")
        complex_change_property._fill_cluster("cc_id_final", "code2")
        cursor.execute("SELECT fid, cc_id_initial, cc_id_final FROM meta_mylayer ORDER BY fid;")
        self.assertListEqual([(1, None, None),
                              (2, 2, None),
                              (3, 2, None),
                              (4, 2, 4),
                              (5, None, 4),
                              (6, None, 4),
                              (7, None, None),
                              (8, None, None)],
                             cursor.fetchall())

    def test_fill_area(self):
        from qc_tool.vector.helper import PartitionedLayer
        from qc_tool.vector.helper import NeighbourTable
        from qc_tool.vector.helper import _MetaTable
        from qc_tool.vector.helper import ComplexChangeProperty
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        neighbour_table = NeighbourTable(partitioned_layer)
        meta_table = _MetaTable(self.connection, "mylayer", "xfid")
        meta_table._create_meta_table()
        complex_change_property = ComplexChangeProperty(neighbour_table, "code1", "code2", "area")
        complex_change_property._prepare_meta_table()
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM meta_mylayer;")
        cursor.execute("INSERT INTO meta_mylayer VALUES (1, NULL, NULL),"
                                                      " (2, 2, NULL),"
                                                      " (3, 2, NULL),"
                                                      " (4, 2, 4),"
                                                      " (5, NULL, 4),"
                                                      " (6, NULL, 4),"
                                                      " (7, NULL, NULL),"
                                                      " (8, NULL, NULL);")
        complex_change_property._fill_area("cc_id_initial")
        complex_change_property._fill_area("cc_id_final")
        cursor.execute("SELECT fid, cc_area FROM meta_mylayer ORDER BY fid;")
        self.assertListEqual([(1, None),
                              (2, 14.), (3, 14.),
                              (4, 56.), (5, 56.), (6, 56.),
                              (7, None),
                              (8, None)],
                             cursor.fetchall())

class Test_GapTable(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.params["connection_manager"].get_connection()

    def test_split_geom(self):
        from qc_tool.vector.helper import GapTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        partitioned_layer._create_polygon_dump()
        gap_table = GapTable(partitioned_layer, "myboundary", None)
        gap_table._create_split_geom()
        cursor.execute("SELECT ST_AsText(split_geom(ST_MakeEnvelope(0.6, -1.1, 9.2, 6, 4326), 1.0));")
        self.assertListEqual([('POLYGON((0.6 6,5 6,5 -1.1,0.6 -1.1,0.6 6))',),
                              ('POLYGON((5 -1.1,5 6,9.2 6,9.2 -1.1,5 -1.1))',)],
                             cursor.fetchall())
        cursor.execute("SELECT ST_AsText(split_geom(ST_MakeEnvelope(0.2, 0.1, 0.6, 0.9, 4326), 1.0));")
        self.assertListEqual([], cursor.fetchall())

    def test_fill_initial_features(self):
        from qc_tool.vector.helper import GapTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE myboundary (geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO myboundary VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                    " (ST_MakeEnvelope(2, 2, 3, 3, 4326));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        partitioned_layer._create_polygon_dump()
        gap_table = GapTable(partitioned_layer, "myboundary", None)
        gap_table._create_gap_table()
        gap_table._fill_initial_features()
        cursor.execute("SELECT fid, ST_AsText(geom) FROM gap_mylayer ORDER BY fid;")
        self.assertListEqual([(1, 'POLYGON((0 0,0 1,1 1,1 0,0 0))'),
                              (2, 'POLYGON((2 2,2 3,3 3,3 2,2 2))')],
                             cursor.fetchall())

    def test_fill_initial_features_du(self):
        from qc_tool.vector.helper import GapTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mylayer (du integer);")
        cursor.execute("INSERT INTO mylayer VALUES (3);")
        cursor.execute("CREATE TABLE myboundary (du integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO myboundary VALUES (2, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                    " (3, ST_MakeEnvelope(2, 2, 3, 3, 4326));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        partitioned_layer._create_polygon_dump()
        gap_table = GapTable(partitioned_layer, "myboundary", "du")
        gap_table._create_gap_table()
        gap_table._fill_initial_features()
        cursor.execute("SELECT fid, ST_AsText(geom) FROM gap_mylayer ORDER BY fid;")
        self.assertListEqual([(1, 'POLYGON((2 2,2 3,3 3,3 2,2 2))')],
                             cursor.fetchall())

    def test_split_features(self):
        from qc_tool.vector.helper import GapTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE gap_mylayer (fid SERIAL PRIMARY KEY, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO gap_mylayer (geom) VALUES (ST_MakeEnvelope(-6.8, -1.6, -1.2, -1.1, 4326)),"
                                                            " (ST_Union(ST_Union(ST_MakeEnvelope(0.2, 0.2, 8, 1.8, 4326),"
                                                                               " ST_MakeEnvelope(0.2, 3.2, 9.2, 4.2, 4326)),"
                                                                      " ST_MakeEnvelope(0.1, 0.2, 5, 4.2, 4326)));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326, max_vertices=5)
        partitioned_layer._create_polygon_dump()
        gap_table = GapTable(partitioned_layer, "myboundary", None)
        gap_table._create_split_geom()
        count = gap_table._split_features()
        self.assertEqual(1, count)
        cursor.execute("SELECT fid, ST_AsText(geom) FROM gap_mylayer ORDER BY fid;")
        self.assertListEqual([(1, 'POLYGON((-6.8 -1.6,-6.8 -1.1,-1.2 -1.1,-1.2 -1.6,-6.8 -1.6))'),
                              (3, 'POLYGON((5 4.2,5 3.2,5 1.8,5 0.2,0.2 0.2,0.1 0.2,0.1 4.2,0.2 4.2,5 4.2))'),
                              (4, 'POLYGON((5 0.2,5 1.8,8 1.8,8 0.2,5 0.2))'),
                              (5, 'POLYGON((5 3.2,5 4.2,9.2 4.2,9.2 3.2,5 3.2))')],
                             cursor.fetchall())

    def test_subtract_partition(self):
        from qc_tool.vector.helper import GapTable
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE gap_mylayer (fid SERIAL PRIMARY KEY, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO gap_mylayer (geom) VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                            " (ST_MakeEnvelope(0, 2, 2, 3, 4326)),"
                                                            " (ST_MakeEnvelope(0, 3, 2, 4, 4326));")
        cursor.execute("CREATE TABLE interior_mylayer (partition_id integer, geom geometry(MultiPolygon, 4326));")
        cursor.execute("INSERT INTO interior_mylayer VALUES (1, ST_Multi(ST_MakeEnvelope(-1, -1, 10, 10, 4326))),"
                                                          " (3, ST_Multi(ST_Union(ST_MakeEnvelope(0, 2, 1, 4, 4326),"
                                                                                " ST_MakeEnvelope(1, 3, 2, 4, 4326))));")
        partitioned_layer = PartitionedLayer(cursor.connection, "mylayer", "xfid", srid=4326)
        partitioned_layer._create_polygon_dump()
        gap_table = GapTable(partitioned_layer, "myboundary", None)
        gap_table._subtract_partition(3)
        cursor.execute("SELECT fid, ST_AsText(geom) FROM gap_mylayer ORDER BY fid;")
        self.assertListEqual([(1, 'POLYGON((0 0,0 1,1 1,1 0,0 0))'),
                              (4, 'POLYGON((1 3,2 3,2 2,1 2,1 3))')],
                             cursor.fetchall())


orig_polygon = ("""POLYGON(
(4185553.87870000116527080535888671875 2421242.403499999083578586578369140625,
 4184000 2421242.403499999083578586578369140625,
 4184000 2422537.6,
4185863.8933000001125037670135498046875 2421369.047499998472630977630615234375,
4185884.244300005026161670684814453125 2421352.4066999997012317180633544921875,
4186315.22270000167191028594970703125 2421000,
4185874.643699995242059230804443359375 2420583.701399997808039188385009765625,
4185703.87870000116527080535888671875 2421047.4035000004805624485015869140625,
4185738.0089999996125698089599609375 2421159.557199998758733272552490234375,
4185735.044400003738701343536376953125 2421162.3692000010050833225250244140625,4185553.87870000116527080535888671875 2421242.403499999083578586578369140625),
(4185703.87870000116527080535888671875 2421047.4035000004805624485015869140625,4186052.387999995611608028411865234375 2420992.5710999988950788974761962890625,4185704.7221000022254884243011474609375 2421047.3133000009693205356597900390625,4185703.87870000116527080535888671875 2421047.4035000004805624485015869140625)
)""")


partition = ("POLYGON(("
              "4185868 2417711,"
              "4185868 2425417,"
              "4189787 2425417,"
              "4189787 2417711,"
              "4185868 2417711"
             "))")

x_cut = 4185868

import re
class Test_drift2(VectorCheckTestCase):
    def test_intersection(self):
        cursor = self.params["connection_manager"].get_connection().cursor()

        sql = ("SELECT ST_AsText((geom).geom, 50) FROM"
               "(SELECT ST_DumpPoints(ST_GeomFromText(%s)) AS geom"
               ") AS sq"
               " WHERE ST_X((geom).geom) > %s"
               " ORDER BY ST_X((geom).geom), ST_Y((geom).geom);")
        cursor.execute(sql, [orig_polygon, x_cut])
        orig_points = cursor.fetchall()

        sql = ("SELECT ST_AsText((geom).geom, 50) FROM"
               "(SELECT ST_DumpPoints("
               "  ST_Intersection("
               "   ST_GeomFromText(%s), "
               "   ST_GeomFromText(%s)"
               "  )"
               " ) AS geom"
               ") AS sq"
               " WHERE ST_X((geom).geom) > %s"
               " ORDER BY ST_X((geom).geom), ST_Y((geom).geom);")
        cursor.execute(sql, [orig_polygon, partition, x_cut])
        part_points = cursor.fetchall()

        regex_x = "POINT\(([0-9\.]+)\s"
        n_drifted_points = 0
        for (orig_point, part_point) in zip(orig_points, part_points):
            if orig_point != part_point:
                print(orig_point)
                print(part_point)
                orig_point_x = re.search(regex_x, str(orig_point)).group(1)
                part_point_x = re.search(regex_x, str(part_point)).group(1)
                print("difference: {}".format(float(orig_point_x) - float(part_point_x)))
                print("------------------")
                n_drifted_points += 1
        print("number of drifted points: {}".format(n_drifted_points))

        sql = "SELECT ST_NPoints(ST_GeomFromText(%s));"
        cursor.execute(sql, [orig_polygon])
        n_orig_points = cursor.fetchone()
        print(n_orig_points)


class Test_snap(VectorCheckTestCase):
    def test_snap(self):
        cursor = self.params["connection_manager"].get_connection().cursor()

        sql = ("SELECT ST_AsText((geom).geom, 50) FROM"
               "(SELECT ST_DumpPoints(ST_GeomFromText(%s)) AS geom"
               ") AS sq"
               " WHERE ST_X((geom).geom) > %s"
               " ORDER BY ST_X((geom).geom), ST_Y((geom).geom);")
        cursor.execute(sql, [orig_polygon, x_cut])
        orig_points = cursor.fetchall()

        sql = ("SELECT ST_AsText((geom).geom, 50) FROM"
               "(SELECT ST_DumpPoints("
               "  ST_Snap("
               "   ST_Intersection("
               "    ST_GeomFromText(%s), "
               "    ST_GeomFromText(%s)"
               "   ),"
               "   ST_GeomFromText(%s), 1e-3"
               "  )) AS geom"
               ") AS sq"
               " WHERE ST_X((geom).geom) > %s"
               " ORDER BY ST_X((geom).geom), ST_Y((geom).geom);")
        cursor.execute(sql, [orig_polygon, partition, orig_polygon, x_cut])
        part_points = cursor.fetchall()

        regex_x = "POINT\(([0-9\.]+)\s"
        n_drifted_points = 0
        for (orig_point, part_point) in zip(orig_points, part_points):
            if orig_point != part_point:
                print(orig_point)
                print(part_point)
                orig_point_x = re.search(regex_x, str(orig_point)).group(1)
                part_point_x = re.search(regex_x, str(part_point)).group(1)
                print("difference: {}".format(float(orig_point_x) - float(part_point_x)))
                print("------------------")
                n_drifted_points += 1
        print("number of drifted points: {}".format(n_drifted_points))



class Test_drift(VectorCheckTestCase):
    def test_intersection(self):
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE original_polygon (fid SERIAL PRIMARY KEY,"
                       "GEOM geometry(Polygon, 3035));")
        cursor.execute("INSERT INTO original_polygon (geom) VALUES ("
                       "ST_Difference("
                       "ST_MakeEnvelope(4185000,"
                       "                2420000,"
                       "                4187000, "
                       "                2421000,"
                       "                3035),"
                       "ST_MakeEnvelope(4186003.6767000020481646060943603515625, "
                       "                2420953.49070000089704990386962890625,"
                       "                4186004.0712999999523162841796875,"
                       "                2420955.9968999992124736309051513671875,"
                       "                3035))"
                       ");")

        cursor.execute("SELECT ST_AsText(ST_Intersection(geom, "
                       "ST_MakeEnvelope(4186001, 2419000, 4188000, 2422000, 3035)), 50)"
                       "FROM original_polygon;")
        row = cursor.fetchone()
        print(row)


    def test_intersection2(self):
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE original_polygon (fid SERIAL PRIMARY KEY,"
                       "GEOM geometry(Polygon, 3035));")
        cursor.execute("INSERT INTO original_polygon (geom) VALUES ("
                       "ST_Difference("
                       "ST_MakeEnvelope(4185000,"
                       "                2420000,"
                       "                4187000, "
                       "                2421000,"
                       "                3035),"
                       "ST_MakeEnvelope(4186000,"
                       "                2420953,"
                       "                4186003.6767000020481646060943603515625, "
                       "                2420953.49070000089704990386962890625,"
                       "                3035))"
                       ");")

        cursor.execute("SELECT ST_AsText(geom, 50)"
                       "FROM original_polygon;")
        row = cursor.fetchone()
        print(row)
