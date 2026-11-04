import argparse
import json
import os
import re
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from legacy_db import DB_CONFIG

# Location in the QC Tool frontend container / pod.
POD_DEFINITIONS_DIR = Path("/usr/local/src/copernicus_quality_tools/product_definitions")


def default_definitions_dirs():
    """PRODUCT_DIRS (":"-separated), else the pod location, else the repository."""
    if os.getenv("PRODUCT_DIRS"):
        return [Path(d) for d in os.environ["PRODUCT_DIRS"].split(":") if d]
    if POD_DEFINITIONS_DIR.is_dir():
        return [POD_DEFINITIONS_DIR]
    return [Path(__file__).resolve().parents[2] / "product_definitions"]

# Named groups that identify a product unit, in order of preference.
UNIT_GROUPS = ("aoi_code", "fua_code", "du_id")

# Legacy deliveries only keep the archive name, while some regexes target
# the inner dataset name, so extensions are tried as well.
CANDIDATE_SUFFIXES = ("", ".gdb", ".gpkg", ".shp", ".tif")


def iter_regexes(node):
    """Yield all strings of a definition that are regexes with a unit group."""
    if isinstance(node, dict):
        for value in node.values():
            yield from iter_regexes(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_regexes(value)
    elif isinstance(node, str) and any(f"(?P<{g}>" in node for g in UNIT_GROUPS):
        yield node


def iter_aoi_codes(node):
    """Yield every list of unit codes declared in a definition."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "aoi_codes" and isinstance(value, list):
                yield value
            else:
                yield from iter_aoi_codes(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_aoi_codes(value)


# Products whose unit is the leading filename part, e.g.
# ES059Lx_ZAMORA_UA2012_DHM.zip -> es059lx. Not checked against a code list.
LEADING_PART_PRODUCTS = {"ua2012", "ua2012_dhm", "ua2018", "ua2018_stl"}
LEADING_PART_REGEX = re.compile(r"^([a-z]{2}[0-9]{3}[a-z0-9]*)_", re.IGNORECASE)


# Products whose rows are recomputed even if already filled, to undo the
# earlier 7-character codes (e.g. uk033l1). Catalog units of all clms_ua_*
# products use the 6-character definition codes (e.g. uk033l).
RECOMPUTE_PRODUCTS = {"clms_ua_bbh_s2021_r10m"}


def guess_leading_part(filename):
    match = LEADING_PART_REGEX.match(Path(filename).name.strip())
    return match.group(1).lower() if match else None


class Definition:
    def __init__(self, path):
        document = json.loads(path.read_text(encoding="utf-8"))
        self.regexes = []
        for pattern in dict.fromkeys(iter_regexes(document)):
            try:
                self.regexes.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                continue
        # Lower-cased code -> code as declared in the definition.
        self.codes = {}
        for codes in iter_aoi_codes(document):
            for code in codes:
                if isinstance(code, str) and code != "*":
                    self.codes.setdefault(code.lower(), code)

    def guess_unit_code(self, filename):
        stem = Path(filename).stem
        for regex in self.regexes:
            for suffix in CANDIDATE_SUFFIXES:
                match = regex.search(stem + suffix)
                if match is None:
                    continue
                groups = match.groupdict()
                for group in UNIT_GROUPS:
                    value = groups.get(group)
                    if value and value.lower() in self.codes:
                        return self.codes[value.lower()]
        return None


def load_definitions(directories):
    # Product idents of legacy deliveries differ in case from file names.
    # The first directory wins, as in QC Tool.
    paths = {}
    for directory in directories:
        for path in directory.glob("*.json"):
            paths.setdefault(path.stem.lower(), path)
    return paths


def guess_delivery_unit_codes(definitions_dirs, dry_run, product_idents=None):
    paths = load_definitions(definitions_dirs)
    if not paths:
        raise SystemExit(f"No product definitions found in {', '.join(map(str, definitions_dirs))}.")
    cache = {}

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id, product_ident, filename, product_unit_code
            FROM execution_delivery
            WHERE (product_unit_code IS NULL OR product_unit_code = ''
                   OR lower(product_ident) = ANY(%(recompute)s))
              AND filename IS NOT NULL
              AND (%(idents)s::text[] IS NULL OR lower(product_ident) = ANY(%(idents)s))
        """,
            {"recompute": list(RECOMPUTE_PRODUCTS), "idents": product_idents},
        )
        rows = cursor.fetchall()
        print(f"Found {len(rows)} deliveries to process.")

        updates = []
        no_definition = set()
        for delivery_id, product_ident, filename, current_code in rows:
            key = (product_ident or "").lower()
            if key in LEADING_PART_PRODUCTS:
                code = guess_leading_part(filename)
                if code is not None:
                    updates.append((delivery_id, code))
                continue
            if key not in cache:
                path = paths.get(key)
                cache[key] = Definition(path) if path else None
                if path is None:
                    no_definition.add(product_ident)
            definition = cache[key]
            if definition is None:
                continue
            code = definition.guess_unit_code(filename)
            if code is None and key in RECOMPUTE_PRODUCTS and current_code:
                # The regex fails e.g. on non-ASCII FUA names; shorten the
                # earlier 7-character code instead.
                code = definition.codes.get(current_code[:6].lower())
            if code is not None:
                updates.append((delivery_id, code))

        print(f"Guessed product_unit_code for {len(updates)} of {len(rows)} deliveries.")
        if no_definition:
            print(f"No product definition for: {', '.join(sorted(map(str, no_definition)))}")

        if dry_run:
            print("Dry run, nothing written.")
            conn.rollback()
            return

        execute_values(
            cursor,
            """
            UPDATE execution_delivery AS d
            SET product_unit_code = v.code
            FROM (VALUES %s) AS v(id, code)
            WHERE d.id = v.id
        """,
            updates,
        )
        print(f"Updated {cursor.rowcount} execution_delivery entries.")
        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"Error guessing delivery unit codes: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--definitions-dir", type=Path, action="append", dest="definitions_dirs",
                        help="Product definitions directory; repeatable (default: PRODUCT_DIRS, else /usr/local/src/copernicus_quality_tools/product_definitions, else ../../product_definitions).")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--product-ident", action="append", dest="product_idents",
                        help="Only process this product (case-insensitive); repeatable.")
    args = parser.parse_args()
    guess_delivery_unit_codes(args.definitions_dirs or default_definitions_dirs(), args.dry_run,
                              [ident.lower() for ident in args.product_idents] if args.product_idents else None)
