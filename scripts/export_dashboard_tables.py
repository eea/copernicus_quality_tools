"""Export tables from a plain-text pg_dump file to CSV without restoring the database.

Usage:
    python export_dashboard_tables.py [DUMP] [--output-dir DIR] [--tables T1 T2 ...]

DUMP may be a .sql or .sql.gz file. NULL values are written as empty CSV fields.
"""
import argparse
import csv
import gzip
import re
import sys
from pathlib import Path

DEFAULT_DUMP = Path(__file__).with_name("qc_tool_production_20260907.sql")
DEFAULT_TABLES = ["dashboard_delivery", "dashboard_job"]

COPY_RE = re.compile(r"^COPY (?:\"?(\w+)\"?\.)?\"?(\w+)\"? \((.*)\) FROM stdin;$")
ESCAPE_RE = re.compile(r"\\(?:([0-7]{1,3})|x([0-9A-Fa-f]{1,2})|(.))")
SIMPLE_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}


def _replace_escape(match):
    octal, hexa, char = match.groups()
    if octal is not None:
        return chr(int(octal, 8))
    if hexa is not None:
        return chr(int(hexa, 16))
    return SIMPLE_ESCAPES.get(char, char)


def decode_field(value):
    if value == r"\N":
        return None
    if "\\" not in value:
        return value
    return ESCAPE_RE.sub(_replace_escape, value)


def open_dump(path):
    opener = gzip.open if path.suffix == ".gz" else open
    return opener(path, "rt", encoding="utf-8", newline="\n")


def export_tables(dump_path, output_dir, tables):
    output_dir.mkdir(parents=True, exist_ok=True)
    pending = set(tables)
    row_counts = {}

    with open_dump(dump_path) as dump:
        writer = out_file = table = None
        for line in dump:
            if table is None:
                match = COPY_RE.match(line.rstrip("\n"))
                if not match or match.group(2) not in pending:
                    continue
                table = match.group(2)
                columns = [c.strip().strip('"') for c in match.group(3).split(",")]
                out_path = output_dir / f"{table}.csv"
                out_file = open(out_path, "w", encoding="utf-8", newline="")
                writer = csv.writer(out_file)
                writer.writerow(columns)
                row_counts[table] = 0
                print(f"Exporting {table} -> {out_path}")
                continue

            line = line.rstrip("\n")
            if line == r"\.":
                out_file.close()
                print(f"  {row_counts[table]} rows")
                pending.discard(table)
                writer = out_file = table = None
                if not pending:
                    break
                continue

            fields = [decode_field(v) for v in line.split("\t")]
            if len(fields) != len(columns):
                raise ValueError(f"{table}: expected {len(columns)} columns, got {len(fields)} in row: {line!r}")
            writer.writerow(fields)
            row_counts[table] += 1

        if table is not None:
            out_file.close()
            raise ValueError(f"{table}: COPY block is not terminated; the dump may be truncated.")

    if pending:
        raise ValueError(f"Table(s) not found in dump: {', '.join(sorted(pending))}")
    return row_counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", nargs="?", type=Path, default=DEFAULT_DUMP, help="pg_dump .sql or .sql.gz file")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: directory of the dump)")
    parser.add_argument("--tables", nargs="+", default=DEFAULT_TABLES, help="Tables to export")
    args = parser.parse_args()

    try:
        export_tables(args.dump, args.output_dir or args.dump.parent, args.tables)
    except (OSError, ValueError) as error:
        sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
