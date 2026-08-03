#!/usr/bin/env python3
"""
Download _gap_ attachments from QC job results and extract polygons
with area > 1 km² (1 000 000 m²) into per-delivery GeoPackage files.

Usage:
    python clc_gap_undetected.py \
        --username <qc_user> \
        --password <qc_pass> \
        [--base-url https://qc-copernicus.eea.europa.eu] \
        [--delivery-list clc_delivery_list.json] \
        [--output-dir ./gap_results] \
        [--area-threshold 1000000] \
        [--land-polygons osm-land-polygons-europe.gpkg]
"""

import argparse
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import requests


BASE_URL = "https://qc-copernicus.eea.europa.eu"
LOGIN_URL = "/accounts/login/"
REPORT_URL = "/data/report/{job_uuid}/report.json"
ATTACHMENT_URL = "/attachment/{job_uuid}/{filename}/"

AREA_THRESHOLD_DEFAULT = 100_000  # 1 ha


def login(session: requests.Session, base_url: str, username: str, password: str) -> None:
    login_url = base_url + LOGIN_URL
    # Fetch CSRF token.
    resp = session.get(login_url, timeout=30)
    resp.raise_for_status()
    csrf_token = session.cookies.get("csrftoken")
    if not csrf_token:
        raise RuntimeError("Could not obtain CSRF token from login page.")
    payload = {
        "username": username,
        "password": password,
        "csrfmiddlewaretoken": csrf_token,
    }
    headers = {"Referer": login_url}
    resp = session.post(login_url, data=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    # Django redirects on success; if we're still on /accounts/login/ it failed.
    if "/accounts/login/" in resp.url:
        raise RuntimeError("Login failed – check username and password.")
    print(f"Logged in as '{username}'.")


def fetch_gap_attachment_names(session: requests.Session, base_url: str, job_uuid: str) -> list[str]:
    url = base_url + REPORT_URL.format(job_uuid=job_uuid)
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    try:
        report = resp.json()
    except ValueError:
        return []
    gap_filenames = []
    for step in report.get("steps", []):
        for fname in step.get("attachment_filenames") or []:
            if "_gap_" in fname:
                gap_filenames.append(fname)
    return gap_filenames


def download_attachment(
    session: requests.Session,
    base_url: str,
    job_uuid: str,
    attachment_filename: str,
    dest_path: Path,
) -> None:
    url = base_url + ATTACHMENT_URL.format(job_uuid=job_uuid, filename=attachment_filename)
    with session.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)


def load_land_polygons(path: Path) -> gpd.GeoDataFrame:
    """Load the OSM land polygons reference layer."""
    print(f"Loading land polygons from '{path}' ...", end=" ", flush=True)
    gdf = gpd.read_file(path)
    print(f"{len(gdf)} features, CRS={gdf.crs.to_string()}")
    return gdf


def split_by_land(
    gaps: gpd.GeoDataFrame,
    land: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Split *gaps* into two GeoDataFrames:
      - land_gaps  : intersect at least one land polygon
      - ocean_gaps : fully outside all land polygons
    """
    # Reproject land to match the gaps CRS if needed.
    if land.crs != gaps.crs:
        land_reproj = land.to_crs(gaps.crs)
    else:
        land_reproj = land

    joined = gpd.sjoin(gaps, land_reproj[["geometry"]], how="left", predicate="intersects")
    intersects_land = joined.index[joined["index_right"].notna()].unique()

    land_gaps = gaps.loc[gaps.index.isin(intersects_land)].copy()
    ocean_gaps = gaps.loc[~gaps.index.isin(intersects_land)].copy()
    return land_gaps, ocean_gaps


def filter_large_gaps(gpkg_path: Path, area_threshold: float) -> gpd.GeoDataFrame | None:
    """
    Read all layers from a GPKG, combine features whose 'area' attribute
    (or computed geometry area when the column is absent) exceeds the threshold.
    Returns a GeoDataFrame or None if nothing qualifies.
    """
    import fiona

    layers = fiona.listlayers(str(gpkg_path))
    frames = []
    for layer in layers:
        gdf = gpd.read_file(gpkg_path, layer=layer)
        if gdf.empty:
            continue
        if "area" in gdf.columns:
            large = gdf[gdf["area"] > area_threshold].copy()
        else:
            # Fall back to computing area from geometry (assumes projected CRS).
            large = gdf[gdf.geometry.area > area_threshold].copy()
        if not large.empty:
            large["_source_layer"] = layer
            frames.append(large)

    if not frames:
        return None
    combined = gpd.pd.concat(frames, ignore_index=True)
    return combined


def process_delivery(
    session: requests.Session,
    base_url: str,
    row: dict,
    output_dir: Path,
    area_threshold: float,
    land: gpd.GeoDataFrame | None = None,
) -> None:
    job_uuid = row["last_job_uuid"]
    delivery_filename = row["filename"]
    # Build the output stem: strip double extension like .gdb.zip or just .zip
    stem = delivery_filename
    for ext in (".gdb.zip", ".zip"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break

    output_gpkg = output_dir / f"{stem}_suspect_gaps.gpkg"
    ocean_dir = output_dir / "ocean_gaps"
    output_ocean_gpkg = ocean_dir / f"{stem}_ocean_gaps.gpkg"
    if output_gpkg.exists() and (land is None or output_ocean_gpkg.exists()):
        print(f"  Skipping '{delivery_filename}' – output already exists.")
        return

    gap_names = fetch_gap_attachment_names(session, base_url, job_uuid)
    if not gap_names:
        print(f"  No _gap_ attachments found for '{delivery_filename}' (job {job_uuid}).")
        return

    print(f"  Found {len(gap_names)} gap attachment(s): {gap_names}")

    all_frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for att_name in gap_names:
            dest = Path(tmp) / att_name
            print(f"    Downloading '{att_name}' ...", end=" ", flush=True)
            try:
                download_attachment(session, base_url, job_uuid, att_name, dest)
            except requests.HTTPError as exc:
                print(f"FAILED ({exc})")
                continue
            print("OK")

            if not att_name.lower().endswith(".gpkg"):
                print(f"    Skipping '{att_name}' – not a GeoPackage (unsupported format).")
                continue

            try:
                gdf = filter_large_gaps(dest, area_threshold)
            except Exception as exc:
                print(f"    ERROR reading '{att_name}': {exc}")
                continue

            if gdf is not None:
                gdf["_attachment"] = att_name
                all_frames.append(gdf)

    if not all_frames:
        print(f"  No gaps > {area_threshold} m² found for '{delivery_filename}'.")
        return

    import pandas as pd
    combined = pd.concat(all_frames, ignore_index=True)
    combined_gdf = gpd.GeoDataFrame(combined, geometry="geometry")

    if land is not None:
        land_gaps, ocean_gaps = split_by_land(combined_gdf, land)
        if not land_gaps.empty:
            land_gaps.to_file(output_gpkg, driver="GPKG")
            print(f"  Saved {len(land_gaps)} suspect (land) gap(s) to '{output_gpkg}'.")
        else:
            print(f"  No land-intersecting gaps for '{delivery_filename}'.")
        if not ocean_gaps.empty:
            ocean_dir.mkdir(parents=True, exist_ok=True)
            ocean_gaps.to_file(output_ocean_gpkg, driver="GPKG")
            print(f"  Saved {len(ocean_gaps)} ocean gap(s) to '{output_ocean_gpkg}'.")
        else:
            print(f"  No ocean-only gaps for '{delivery_filename}'.")
    else:
        combined_gdf.to_file(output_gpkg, driver="GPKG")
        print(f"  Saved {len(combined_gdf)} feature(s) to '{output_gpkg}'.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", help="QC Tool username")
    parser.add_argument("--password", help="QC Tool password (prompted if omitted)")
    parser.add_argument("--base-url", default=BASE_URL, help=f"Base URL of the QC Tool (default: {BASE_URL})")
    parser.add_argument(
        "--delivery-list",
        default=Path(__file__).parent / "clc_delivery_list.json",
        type=Path,
        help="Path to clc_delivery_list.json",
    )
    parser.add_argument(
        "--output-dir",
        default=Path(__file__).parent / "gap_results",
        type=Path,
        help="Directory to write output GeoPackages (created if needed)",
    )
    parser.add_argument(
        "--area-threshold",
        type=float,
        default=AREA_THRESHOLD_DEFAULT,
        help=f"Minimum gap area in m² to include (default: {AREA_THRESHOLD_DEFAULT} = 1 ha)",
    )
    parser.add_argument(
        "--land-polygons",
        default=Path(__file__).parent / "osm-land-polygons-europe.gpkg",
        type=Path,
        help="Path to OSM land polygons GeoPackage used to separate ocean gaps",
    )
    args = parser.parse_args()

    username = args.username or input("QC Tool username: ").strip()
    password = args.password or getpass.getpass("QC Tool password: ")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.delivery_list, encoding="utf-8") as fh:
        data = json.load(fh)

    rows = data.get("rows", data) if isinstance(data, dict) else data
    submitted = [r for r in rows if r.get("date_submitted")]
    print(f"Found {len(submitted)} submitted deliveries (out of {len(rows)} total).")

    land = None
    if args.land_polygons.exists():
        land = load_land_polygons(args.land_polygons)
    else:
        print(f"WARNING: land polygons file '{args.land_polygons}' not found – ocean filtering disabled.")

    session = requests.Session()
    login(session, args.base_url, username, password)

    for i, row in enumerate(submitted, 1):
        print(f"[{i}/{len(submitted)}] {row['filename']} (job {row['last_job_uuid']})")
        try:
            process_delivery(session, args.base_url, row, args.output_dir, args.area_threshold, land)
        except Exception as exc:
            print(f"  ERROR processing delivery: {exc}")


if __name__ == "__main__":
    main()
