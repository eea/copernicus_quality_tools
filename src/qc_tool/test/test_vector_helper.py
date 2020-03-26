#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.test.helper import VectorCheckTestCase


class Test_PartitionedLayer(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.params["connection_manager"].get_connection()
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE mylayer (xfid integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mylayer VALUES (1, ST_MakeEnvelope(-1.1, -2.2, 1, 1, 4326)),"
                                                 " (2, ST_MakeEnvelope(10, 10, 11.3, 11.4, 4326));")

    def test_extract_layer_info(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        srid, xmin, ymin, xmax, ymax = partitioned_layer.extract_layer_info()
        self.assertEqual(4326, srid)
        self.assertListEqual([-1.1, -2.2, 11.3, 11.4], [xmin, ymin, xmax, ymax])

    def test_expand_box(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(None, "mylayer", "xfid", grid_size=2)
        xmin, ymin, xmax, ymax = partitioned_layer.expand_box(-1.1, -2.2, 11.3, 11.4)
        self.assertListEqual([-4, -6, 14, 14], [xmin, ymin, xmax, ymax])

    def test_init_partition_table(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        partitioned_layer.srid = 4326
        initial_partition_id = partitioned_layer._init_partition_table(-4, -6, 14, 14)
        cursor = self.connection.cursor()
        cursor.execute("SELECT partition_id, superpartition_id, num_vertices, ST_AsText(geom) FROM partition_mylayer;")
        self.assertListEqual([(1, None, None, "POLYGON((-4 -6,-4 14,14 14,14 -6,-4 -6))")], cursor.fetchall())
        
    def test_init_feature_table(self):
        from qc_tool.vector.helper import PartitionedLayer
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        partitioned_layer.srid = 4326
        partitioned_layer._init_feature_table(1)
        cursor = self.connection.cursor()
        cursor.execute("SELECT fid, partition_id, ST_AsText(geom) FROM feature_mylayer ORDER BY fid;")
        self.assertListEqual([(1, 1, "POLYGON((-1.1 -2.2,-1.1 1,1 1,1 -2.2,-1.1 -2.2))"),
                              (2, 1, "POLYGON((10 10,10 11.4,11.3 11.4,11.3 10,10 10))")], cursor.fetchall())
        
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
        self.assertListEqual([(1, 1), (2, 5), (3, 10)], cursor.fetchall())

    def test_split_partitions(self):
        from qc_tool.vector.helper import PartitionedLayer
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer,"
                                                      " superpartition_id integer,"
                                                      " num_vertices integer,"
                                                      " geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (2, 1, 4, ST_MakeEnvelope(0, 0, 4, 1, 4326)),"
                                                           " (3, 1, 5, ST_MakeEnvelope(0, 0, 6, 1, 4326));")
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid", max_vertices=4)
        partitioned_layer.srid = 4326
        split_count = partitioned_layer._split_partitions()
        self.assertEqual(1, split_count)
        cursor = self.connection.cursor()
        cursor.execute("SELECT partition_id, superpartition_id, num_vertices, ST_AsText(geom) FROM partition_mylayer ORDER BY partition_id;")
        self.assertListEqual([(2, 1, 4, "POLYGON((0 0,0 1,4 1,4 0,0 0))"),
                              (3, 1, 5, "POLYGON((0 0,0 1,6 1,6 0,0 0))"),
                              (None, 3, None, "POLYGON((0 0,0 1,3 1,3 0,0 0))"),
                              (None, 3, None, "POLYGON((3 0,3 1,6 1,6 0,3 0))")], cursor.fetchall())

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
        partitioned_layer._fill_subpartitions()
        cursor.execute("SELECT fid, partition_id, ST_AsText(geom) FROM feature_mylayer ORDER BY fid, partition_id;")
        self.assertListEqual([(1, 2, "POLYGON((-5 1,-5 2,-3 2,-3 1,-5 1))"),
                              (2, 3, "POLYGON((4 1,4 2,7 2,7 1,4 1))"),
                              (2, 4, "POLYGON((4 1,4 2,5 2,5 1,4 1))"),
                              (2, 5, "POLYGON((5 2,7 2,7 1,5 1,5 2))"),
                              (3, 5, "POLYGON((5 1,5 2,6 2,6 1,5 1))")], cursor.fetchall())

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
                              (5, 3)], cursor.fetchall())
        cursor.execute("SELECT fid, partition_id FROM feature_mylayer ORDER BY fid;")
        self.assertListEqual([(1, 2),
                              (4, 4),
                              (5, 5),
                              (6, 5)], cursor.fetchall())


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
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table._init_neighbour_table()
        neighbour_table._fill()
        cursor = self.connection.cursor()
        cursor.execute("SELECT fida, fidb, dim FROM neighbour_mylayer ORDER BY fida, fidb;")
        self.assertListEqual([(1, 2, 2),
                              (2, 1, 2),
                              (2, 3, 1),
                              (3, 2, 1),
                              (4, 5, 1),
                              (5, 4, 1)], cursor.fetchall())


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
        meta_table._init_meta_table()
        cursor = self.connection.cursor()
        cursor.execute("SELECT fid FROM meta_mylayer ORDER BY fid;")
        self.assertListEqual([(1,), (2,)], cursor.fetchall())


class Test_MarginalProperty(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.params["connection_manager"].get_connection()

    def test_init_exterior_table(self):
        from qc_tool.vector.helper import PartitionedLayer
        from qc_tool.vector.helper import MarginalProperty
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE partition_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO partition_mylayer VALUES (2, ST_MakeEnvelope(-10, -10, 1, 10, 4326)),"
                                                           " (5, ST_MakeEnvelope(10, 1, 20, 2, 4326));")
        cursor.execute("CREATE TABLE feature_mylayer (partition_id integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO feature_mylayer VALUES (2, ST_MakeEnvelope(-10, -10, 1, 9, 4326)),"
                                                         " (5, ST_MakeEnvelope(10, 1, 11, 2, 4326)),"
                                                         " (5, ST_MakeEnvelope(19, 1, 20, 2, 4326));")
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        marginal_property = MarginalProperty(partitioned_layer)
        marginal_property._init_exterior_table()
        cursor.execute("SELECT partition_id, ST_AsText(geom) FROM exterior_mylayer ORDER BY partition_id;")
        self.assertListEqual([(2, 'POLYGON((-10 9,-10 10,1 10,1 9,-10 9))'),
                              (5, 'POLYGON((11 2,19 2,19 1,11 1,11 2))')], cursor.fetchall())

    def test_fill(self):
        from qc_tool.vector.helper import PartitionedLayer
        from qc_tool.vector.helper import MarginalProperty
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE meta_mylayer (fid integer, is_marginal boolean DEFAULT NULL);")
        cursor.execute("INSERT INTO meta_mylayer (fid) VALUES (2), (3), (4);")
        cursor.execute("CREATE TABLE feature_mylayer (fid integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO feature_mylayer VALUES (2, ST_MakeEnvelope(1, 1, 2, 2, 4326)),"
                                                         " (2, ST_MakeEnvelope(3, 1, 4, 2, 4326)),"
                                                         " (3, ST_MakeEnvelope(5, 1, 6, 2, 4326)),"
                                                         " (4, ST_MakeEnvelope(7, 1, 8, 2, 4326));")
        cursor.execute("CREATE TABLE exterior_mylayer (geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO exterior_mylayer VALUES (ST_MakeEnvelope(3, 2, 4, 3, 4326)),"
                                                          " (ST_MakeEnvelope(5, 2, 6, 3, 4326));")
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        marginal_property = MarginalProperty(partitioned_layer)
        marginal_property._fill()
        cursor.execute("SELECT fid, is_marginal FROM meta_mylayer ORDER BY fid;")
        self.assertListEqual([(2, True), (3, True), (4, False)], cursor.fetchall())


class Test_ComplexChangeProperty(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self.params["connection_manager"].get_connection()
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE mylayer (xfid integer, code1 char, code2 char, area real);")
        cursor.execute("INSERT INTO mylayer VALUES (1, 'A', 'A',   1),"
                                                 " (2, 'A', 'B',   2),"
                                                 " (3, 'A', 'C',   4),"
                                                 " (4, 'A', 'D',   8),"
                                                 " (5, 'B', 'D',  16),"
                                                 " (6, 'C', 'D',  32),"
                                                 " (7, 'D', 'D',  64),"
                                                 " (8, 'A', 'D', 128);\n")

    def test_fill_cluster(self):
        from qc_tool.vector.helper import PartitionedLayer
        from qc_tool.vector.helper import NeighbourTable
        from qc_tool.vector.helper import _MetaTable
        from qc_tool.vector.helper import ComplexChangeProperty
        cursor = self.connection.cursor()
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table._init_neighbour_table()
        cursor.execute("INSERT INTO neighbour_mylayer VALUES (1, 2, 1), (2, 1, 1),\n"
                                                           " (2, 3, 1), (3, 2, 1),\n"
                                                           " (3, 4, 1), (4, 3, 1),\n"
                                                           " (4, 5, 1), (5, 4, 1),\n"
                                                           " (5, 6, 1), (6, 5, 1),\n"
                                                           " (6, 7, 1), (7, 6, 1);")
        meta_table = _MetaTable(self.connection, "mylayer", "xfid")
        meta_table._init_meta_table()
        complex_change_property = ComplexChangeProperty(neighbour_table, "code1", "code2", "area")
        complex_change_property._init_meta_table()
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
                              (8, None, None)], cursor.fetchall())

    def test_fill_area(self):
        from qc_tool.vector.helper import PartitionedLayer
        from qc_tool.vector.helper import NeighbourTable
        from qc_tool.vector.helper import _MetaTable
        from qc_tool.vector.helper import ComplexChangeProperty
        partitioned_layer = PartitionedLayer(self.connection, "mylayer", "xfid")
        neighbour_table = NeighbourTable(partitioned_layer)
        meta_table = _MetaTable(self.connection, "mylayer", "xfid")
        meta_table._init_meta_table()
        complex_change_property = ComplexChangeProperty(neighbour_table, "code1", "code2", "area")
        complex_change_property._init_meta_table()
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM meta_mylayer;")
        cursor.execute("INSERT INTO meta_mylayer VALUES (1, NULL, NULL),\n"
                                                      " (2, 2, NULL),\n"
                                                      " (3, 2, NULL),\n"
                                                      " (4, 2, 4),\n"
                                                      " (5, NULL, 4),\n"
                                                      " (6, NULL, 4),\n"
                                                      " (7, NULL, NULL),\n"
                                                      " (8, NULL, NULL);")
        complex_change_property._fill_area("cc_id_initial")
        complex_change_property._fill_area("cc_id_final")
        cursor.execute("SELECT fid, cc_area FROM meta_mylayer ORDER BY fid;")
        self.assertListEqual([(1, None),
                              (2, 14.), (3, 14.),
                              (4, 56.), (5, 56.), (6, 56.),
                              (7, None),
                              (8, None)], cursor.fetchall())
