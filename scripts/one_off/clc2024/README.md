# Historical CLC2024 preparation and investigation

These files preserve product-specific work. They are not application entrypoints
or automated QC tests. A manual diagnostic can be run more than once without
making it part of release regression testing.

## Metadata generator

[`generate_metadata.py`](generate_metadata.py) contains the historical CLC2024 XML
templates. It executes immediately when imported or run, selects the first GPKG/
GDB beside the file and its first `clc24_*` layer, prompts for a contact email,
then replaces four XML outputs beside the file. It requires Fiona and pyproj and
does not validate the resulting metadata.

Keep it for historical reference. If reproduction is necessary, copy the script
and an intended delivery into a separate working directory and review the output
there. Do not import it into test discovery or run it against preserved original
delivery/specification snapshots. A maintained general metadata generator needs
explicit inputs, an owning template workflow and validation before promotion.

## Gap analysis

[`gap_analysis.py`](gap_analysis.py) is a repeatable manual investigation tool.
It logs in, downloads gap attachments from historical QC reports, filters by
area and writes GeoPackages. It does not run QC, change recorded QC outcomes, or
submit deliveries. Dependencies are requests, GeoPandas and its vector drivers.

Run from the repository root, supplying a private delivery list and output path:

```bash
python3 -m scripts.one_off.clc2024.gap_analysis \
  --username your-account \
  --delivery-list /private/clc-deliveries.json \
  --output-dir /private/gap-analysis-output \
  --land-polygons /path/to/osm-land-polygons-europe.gpkg \
  --area-threshold 100000
```

The command prompts for the password when `--password` is omitted. The default
threshold is **100,000 m² (10 hectares)**; source geometry must use a suitable
projected CRS for area measurements. Only rows with a submission date are
processed. If the land layer is absent, ocean filtering is disabled. Server
attachment names are treated as trusted historical inputs; this diagnostic is
not the application's confined artifact-download API.

The required `--delivery-list` and `--output-dir` explicitly select the private
captured input and generated output directory. Production captures are not
synthetic test data or a maintained catalog and are kept outside the checkout.
Only rows with a submission date are processed.

The metadata generator is a
[conditional removal candidate](../../README.md#proposed-deletions). Keep gap
analysis only while its investigation remains useful, with reviewed sources and
outputs outside Git.
