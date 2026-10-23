"""ZIP materialization adapter shared by configured QC worker checks.

Check modules own their validation pipelines. Keep extraction behavior stable
here; changing admission limits requires a separate geospatial fixture review.
Ordinary FileGDB index members in supported fixtures exceed archive_security's
default compression ratio cap, so that extractor is not a drop-in replacement.
"""

from zipfile import ZipFile


def do_unzip(zip_filepath, unzip_dir, status):
    # The source zip file must have .zip extension.
    if not zip_filepath.name.lower().endswith(".zip"):
        status.aborted("Uploaded delivery {:s} has incorrect file format. Delivery must be a .zip file."
                       .format(zip_filepath.name))
        return

    status.set_status_property("hash_files", [zip_filepath.name])
    # The source zip file must be a zip archive.
    try:
        unzip_dir.mkdir()
        with ZipFile(str(zip_filepath)) as zip_file:
            zip_file.extractall(path=str(unzip_dir))
    except Exception as ex:
        status.aborted("Error unzipping file {:s}, reason: {:s}".format(zip_filepath.name, str(ex)))
        return

    status.add_params({"unzip_dir": unzip_dir})
