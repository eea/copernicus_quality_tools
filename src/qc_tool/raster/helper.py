#!/usr/bin/env python3

from zipfile import ZipFile


def do_raster_layers(params):
    return [params["raster_layer_defs"][layer_alias] for layer_alias in params["layers"]]


def zip_shapefile(shp_filepath):
    # Gather all files to be zipped.
    shp_without_extension = shp_filepath.stem
    output_dir = shp_filepath.parent
    filepaths_to_zip = [f for f in output_dir.iterdir() if f.stem == shp_without_extension]

    required_extensions = [".shp", ".dbf", ".shx", ".prj"]
    for ext in required_extensions:
        ext_filepath = output_dir.joinpath("{:s}{:s}".format(shp_without_extension, ext))
        if ext_filepath not in filepaths_to_zip:
            raise FileNotFoundError("Dumped {:s} file {:s} is missing.".format(ext, ext_filepath))

    # Zip the files.
    zip_filepath = output_dir.joinpath("{:s}.zip".format(shp_without_extension))
    with ZipFile(str(zip_filepath), "w") as zf:
        for filepath in filepaths_to_zip:
            zf.write(str(filepath), filepath.name)

    # Remove zipped files.
    for filepath in filepaths_to_zip:
        filepath.unlink()
    return zip_filepath.name
