#!/usr/bin/env python3


import logging
import time
from contextlib import ExitStack
from unittest import TestCase
from uuid import uuid4

from osgeo import gdal
from osgeo import osr

from qc_tool.common import CONFIG
from qc_tool.common import TEST_DATA_DIR
from qc_tool.common import create_job_dir
from qc_tool.worker.dispatch import CheckStatus
from qc_tool.worker.manager import create_connection_manager
from qc_tool.worker.manager import create_jobdir_manager


LOG_FORMAT = "{asctime} {name}:{levelname} {pathname}:{lineno} {message}"
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def init_logging():
    formatter = logging.Formatter(fmt=LOG_FORMAT, style="{", datefmt=LOG_TIME_FORMAT)
    formatter.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_log = logging.getLogger()
    root_log.addHandler(handler)
    root_log.setLevel(logging.DEBUG)


class ProductTestCase(TestCase):
    def setUp(self):
        init_logging()
        super().setUp()
        self.job_uuid = str(uuid4())
        create_job_dir(self.job_uuid)

        # Set up boundary dir to testing sources.
        CONFIG["boundary_dir"] = TEST_DATA_DIR.joinpath("boundaries")


class RasterCheckTestCase(TestCase):
    @staticmethod
    def create_raster(raster_filepath, data, pixel_size, ulx=0, uly=0, epsg=3035):
        """
        Helper method which creates a .TIF raster file with the same pixel values as the data array.
        :param data: 2D NumPy array of integers with the raster data.
        :param pixel_size: Raster resolution in metres.
        :param ulx: X coordinate of upper-left corner of the raster.
        :param uly: Y coordinate of upper-left corner of the raster.
        :param epsg: Integer EPSG code of the raster's coordinate reference system (default: 3035).
        :return: full path of created raster.
        """
        height = data.shape[0]
        width = data.shape[1]
        mem_drv = gdal.GetDriverByName("MEM")
        mem_ds = mem_drv.Create("memory", width, height, 1, gdal.GDT_Byte)
        mem_srs = osr.SpatialReference()
        mem_srs.ImportFromEPSG(epsg)
        mem_ds.SetProjection(mem_srs.ExportToWkt())
        mem_ds.SetGeoTransform((ulx, pixel_size, 0, uly, 0, -pixel_size))
        mem_ds.GetRasterBand(1).WriteArray(data)

        # Store raster dataset.
        raster_filepath.parent.mkdir(parents=True, exist_ok=True)
        dest_driver = gdal.GetDriverByName("GTiff")
        dest_ds = dest_driver.CreateCopy(str(raster_filepath),
                                         mem_ds, False, options=["TILED=YES"])

        # Remove temporary datasource and datasets from memory.
        mem_dsrc = None
        mem_ds = None
        dest_ds = None
        return raster_filepath

    def setUp(self):
        init_logging()
        super().setUp()
        self.status_class = CheckStatus
        job_uuid = str(uuid4())
        create_job_dir(job_uuid)
        self.params = {"skip_inspire_check": True}
        with ExitStack() as stack:
            self.jobdir_manager = stack.enter_context(create_jobdir_manager(job_uuid))
            self.addCleanup(stack.pop_all().close)


class VectorCheckTestCase(TestCase):
    def setUp(self):
        init_logging()
        super().setUp()
        self.status_class = CheckStatus
        job_uuid = str(uuid4())
        create_job_dir(job_uuid)
        self.params = {"skip_inspire_check": True}
        with ExitStack() as stack:
             self.params["connection_manager"] = stack.enter_context(create_connection_manager(job_uuid))
             self.params["jobdir_manager"] = stack.enter_context(create_jobdir_manager(job_uuid))
             self.addCleanup(stack.pop_all().close)
