"""Fail the image build/startup when the worker cannot run supported QC jobs."""

import sys
from importlib.util import find_spec


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("QC Tool workers require Python 3.11 or newer; rebuild the matching worker image.")

    from osgeo import gdal, ogr
    import numpy
    import psycopg2
    import pypdf
    import reportlab
    import saxonche
    import skimage

    if find_spec("PyPDF2") is not None:
        raise SystemExit("The obsolete PyPDF2 parser must not remain in the final worker runtime.")

    if gdal.VersionInfo("RELEASE_NAME") != "3.8.4":
        raise SystemExit("This worker build requires the reviewed GDAL 3.8.4 runtime.")
    missing = [name for name in ("GPKG", "ESRI Shapefile", "PostgreSQL", "OpenFileGDB", "Parquet")
               if ogr.GetDriverByName(name) is None]
    if missing or gdal.GetDriverByName("GTiff") is None:
        raise SystemExit("Worker GDAL drivers are incomplete: " + ", ".join(missing or ["GTiff"]))

    # Importing the scheduler/report exercises application syntax and adapters,
    # without starting services or touching application databases.
    import qc_tool.worker.scheduler
    import qc_tool.worker.report

    print("Worker runtime ready: Python %s; GDAL %s; required QC drivers and adapters available."
          % (sys.version.split()[0], gdal.VersionInfo("RELEASE_NAME")))


if __name__ == "__main__":
    main()
