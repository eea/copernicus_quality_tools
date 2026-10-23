#!/usr/bin/env python3


from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from osgeo import gdal, ogr

from qc_tool.common import CONFIG, TEST_DATA_DIR
from qc_tool.test.helper import ProductTestCase
from qc_tool.worker.dispatch import dispatch


def _fixture_layer(archive_path):
    """Open the first GPKG in a trusted checked-in synthetic delivery."""
    with ZipFile(archive_path) as archive:
        member = next(name for name in archive.namelist() if name.lower().endswith(".gpkg"))
    dataset = ogr.Open("/vsizip/" + str(archive_path) + "/" + member)
    if dataset is None:
        raise AssertionError("The product test fixture cannot be opened")
    return dataset, dataset.GetLayer(0)


def _current_delivery(test, source, *, unit_id=None, layer_name=None, where=None):
    """Construct a separate current-contract input; retain historical bytes."""
    root = Path(test.enterContext(TemporaryDirectory()))
    unpacked = root / "delivery"
    unpacked.mkdir()
    # Only repository-owned fixtures are consumed here, never uploaded input.
    with ZipFile(source) as archive:
        archive.extractall(unpacked)
    path = next(unpacked.rglob("*.gpkg"))
    if layer_name or where:
        replacement = root / "renamed.gpkg"
        dataset = gdal.VectorTranslate(str(replacement), str(path), format="GPKG", layerName=layer_name, where=where)
        if dataset is None:
            raise AssertionError("The current-contract GPKG could not be created")
        dataset = None
        replacement.replace(path)
    if unit_id:
        dataset = ogr.Open(str(path), update=1)
        layer = dataset.GetLayer(0)
        test.assertEqual(layer.CreateField(ogr.FieldDefn("DU_ID", ogr.OFTString)), 0)
        for feature in layer:
            feature.SetField("DU_ID", unit_id)
            test.assertEqual(layer.SetFeature(feature), 0)
        feature = layer = dataset = None
    result = root / source.name
    with ZipFile(result, "w") as archive:
        for item in sorted(unpacked.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(unpacked).as_posix())
    return result


def _matching_boundary(test, delivery, filename, unit_column):
    """Create a small per-unit test boundary from this synthetic delivery."""
    root = Path(test.enterContext(TemporaryDirectory()))
    (root / "vector").mkdir()
    (root / "raster").mkdir()
    source, layer = _fixture_layer(delivery)
    groups = {}
    for feature in layer:
        key = feature.GetField(unit_column)
        test.assertIsNotNone(key)
        geometry = feature.GetGeometryRef().Clone()
        groups[key] = groups[key].Union(geometry) if key in groups else geometry
    path = root / "vector" / filename
    driver = ogr.GetDriverByName("GPKG" if path.suffix == ".gpkg" else "ESRI Shapefile")
    target = driver.CreateDataSource(str(path))
    boundary = target.CreateLayer(path.stem, srs=layer.GetSpatialRef(), geom_type=ogr.wkbMultiPolygon)
    test.assertEqual(boundary.CreateField(ogr.FieldDefn(unit_column, ogr.OFTString)), 0)
    for key, geometry in groups.items():
        feature = ogr.Feature(boundary.GetLayerDefn())
        feature.SetField(unit_column, key)
        feature.SetGeometry(ogr.ForceToMultiPolygon(geometry))
        test.assertEqual(boundary.CreateFeature(feature), 0)
    feature = boundary = target = layer = source = None
    return root


def _dispatch_with_boundary(test, delivery, product, filename, unit_column, skips=(6,)):
    boundary = _matching_boundary(test, delivery, filename, unit_column)
    with patch.dict(CONFIG, boundary_dir=boundary):
        return dispatch(test.job_uuid, "user_name", delivery, product, skips)


class Test_clc(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        expected_step_results = ["ok"] * 24
        # vector.inspire check is skipped
        expected_step_results[7] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "clc2012", (8,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_clc_status(ProductTestCase):
    def test_status_json(self):
        from qc_tool.common import load_job_result
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        # This regression verifies serialization, independently of an external
        # INSPIRE installation, like the CLC product fixture above.
        job_result = dispatch(self.job_uuid, "user_name", filepath, "clc2012", (8,))
        self.assertEqual(job_result["steps"][7]["check_ident"], "qc_tool.vector.inspire")
        self.assertEqual(job_result["steps"][7]["status"], "skipped")
        job_result_from_file = load_job_result(self.job_uuid)
        self.assertEqual(job_result, job_result_from_file,
                         "Job result returned by dispatch() must be the same as job result stored in json file.")


class Test_n2k_2006(ProductTestCase):
    year = 2006

    def fixture(self):
        return TEST_DATA_DIR.joinpath("vector", "n2k", "gpkg", f"N2K_DU001A_Status{self.year}_LCLU_v1_20200915.gpkg.zip")

    def test_historical_input_without_required_unit_is_rejected(self):
        job_result = dispatch(self.job_uuid, "user_name", self.fixture(), f"n2k_{self.year}", (6,))
        self.assertEqual([step["status"] for step in job_result["steps"]], ["ok", "ok", "aborted"])
        self.assertIn("missing attributes: du_id(string)", job_result["steps"][-1]["messages"][0])

    def test_current_required_unit_and_matching_boundary(self):
        filepath = _current_delivery(self, self.fixture(), unit_id="DU001A")
        expected_step_results = ["ok"] * 17
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = _dispatch_with_boundary(self, filepath, f"n2k_{self.year}", "boundary_n2k.gpkg", "du_id")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_n2k_2012(Test_n2k_2006):
    year = 2012


class Test_n2k_2018(Test_n2k_2006):
    year = 2018


class Test_n2k_2012_change(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "gpkg", "N2K_DU001A_Change2006_2012_LCLU_v1_20200915.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "n2k_2012_change", (6,))
        print(job_result)
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_n2k_2018_change(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "gpkg", "N2K_DU001A_Change2012_2018_LCLU_v1_20200915.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "n2k_2018_change", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_rpz_2012(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_LCLU2012_DU007T.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "rpz_2012", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_rpz_2018(ProductTestCase):
    def test_reversed_historical_year_order_is_rejected(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_DU001B_lclu_2018_2012_v03.gpkg.zip")
        result = dispatch(self.job_uuid, "user_name", filepath, "rpz_2018", (6,))
        self.assertEqual([step["status"] for step in result["steps"]], ["ok", "aborted"])
        self.assertIn("The rpz layer name does not match naming convention.", result["steps"][-1]["messages"])

    def test_historical_codes_remain_rejected_after_correcting_year_order(self):
        source = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_DU001B_lclu_2018_2012_v03.gpkg.zip")
        filepath = _current_delivery(self, source, layer_name="rpz_DU001B_lclu_2012_2018_v03")
        result = _dispatch_with_boundary(self, filepath, "rpz_2018", "boundary_rpz.shp", "du_id")
        invalid = result["steps"][7]
        self.assertEqual(invalid["check_ident"], "qc_tool.vector.enum")
        self.assertEqual(invalid["status"], "failed")
        self.assertEqual(len(invalid["messages"]), 4)
        self.assertTrue(all("invalid codes in features with row number: 31, 32" in message
                            for message in invalid["messages"]))

    def test_current_year_order_and_supported_class_subset(self):
        source = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_DU001B_lclu_2018_2012_v03.gpkg.zip")
        # Retain the original unsupported 9110/9210 features in the rejection
        # regression above. This independent smoke delivery contains only
        # current supported classes, without relabelling those original rows.
        filepath = _current_delivery(self, source, layer_name="rpz_DU001B_lclu_2012_2018_v03",
                                     where="CODE_1_12 <> 9")
        expected_step_results = ["ok"] * 18
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = _dispatch_with_boundary(self, filepath, "rpz_2018", "boundary_rpz.shp", "du_id")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_swf_vec_ras(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector_raster", "swf_2015_vec_ras", "swf_2015_vec_ras_FR_3035_123_pt01.zip")
        expected_step_results = ["ok"] * 30
        # vector.inspire check is skipped
        expected_step_results[16] = "skipped"
        # vector.area in the testing data does not match
        expected_step_results[20] = "failed"

        boundary = Path(self.enterContext(TemporaryDirectory()))
        (boundary / "raster").mkdir()
        (boundary / "vector").mkdir()
        shutil.copyfile(TEST_DATA_DIR / "boundaries/raster/mask_swf_005m_123.tif",
                        boundary / "raster/mask_swf_2015_005m_123.tif")
        with patch.dict(CONFIG, boundary_dir=boundary):
            job_result = dispatch(self.job_uuid, "user_name", filepath, "swf_2015_vec_ras", (17,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)
        self.assertListEqual(['Layer vector has error features with row number: 10.'],
                             job_result["steps"][20]["messages"])


class Test_ua2012(ProductTestCase):
    def test_gpkg(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2012.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = _dispatch_with_boundary(self, filepath, "ua2012", "boundary_ua.gpkg", "fua_code")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)


class Test_ua2018(ProductTestCase):
    def test_gpkg(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2018.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = _dispatch_with_boundary(self, filepath, "ua2018", "boundary_ua.gpkg", "fua_code")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)


class Test_ua_change_2012_2018(ProductTestCase):
    def test_gpkg(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_change_2012_2018.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua_change_2012_2018", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

    def test_very_long_layer_name(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "UK568L1_CHESHIRE_WEST_AND_CHESTER_change_2012_2018.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"
        expected_step_results[13] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua_change_2012_2018", (6, 14))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)


class Test_ua2018_stl(ProductTestCase):
    def test_gpkg(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2018_stl.gpkg.zip")
        expected_step_results = ["ok"] * 14
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua2018_stl", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

class Test_cz_2012(ProductTestCase):
    def test_gdb(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "cz", "gpkg", "CZ_2012_DU001_3035_V1_2.gpkg.zip")
        expected_step_results = ["ok"] * 17
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = _dispatch_with_boundary(self, filepath, "cz_2012", "boundary_cz.shp", "du")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

class Test_cz_2018(ProductTestCase):
    def test_gdb(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "cz", "gpkg", "CZ_2018_DU001_3035_V1_2.gpkg.zip")
        expected_step_results = ["ok"] * 17
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = _dispatch_with_boundary(self, filepath, "cz_2018", "boundary_cz.shp", "du")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

class Test_cz_change_2012_2018(ProductTestCase):
    def test_gdb(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "cz", "gpkg", "CZ_change_2012_2018_DU001_3035_V1_2.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "cz_change_2012_2018", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

