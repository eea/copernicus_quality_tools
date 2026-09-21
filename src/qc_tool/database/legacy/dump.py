"""Read legacy PostgreSQL COPY data without executing any dump SQL.

The major-release converter deliberately accepts a narrow format: a complete,
UTF-8 plain pg_dump with public-schema, text-format COPY blocks. Schema,
functions and psql commands are never executed. Parsed rows can contain secrets;
do not log ``tables`` or include their contents in conversion reports.
"""

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re


class LegacyDumpError(ValueError):
    """Invalid or unsupported dump; messages contain locations, never values."""


@dataclass(frozen=True)
class LegacyDump:
    tables: dict[str, list[dict[str, str | None]]] = field(repr=False)
    columns: dict[str, tuple[str, ...]] = field(repr=False)
    source_sha256: str
    source_size_bytes: int

    @property
    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.tables.items()}


_IDENTIFIER = r'(?:[A-Za-z_][A-Za-z_0-9]*|"[A-Za-z_][A-Za-z_0-9]*")'
_COPY = re.compile(
    rf'COPY\s+(?P<schema>{_IDENTIFIER})\.(?P<table>{_IDENTIFIER})\s*'
    rf'\((?P<columns>{_IDENTIFIER}(?:\s*,\s*{_IDENTIFIER})*)\)'
    r'\s+FROM\s+stdin\s*;',
    re.IGNORECASE,
)
_ENCODING = re.compile(r"SET\s+client_encoding\s*=\s*'UTF-?8'\s*;", re.IGNORECASE)
_ESCAPES = {
    ord("b"): b"\b", ord("f"): b"\f", ord("n"): b"\n",
    ord("r"): b"\r", ord("t"): b"\t", ord("v"): b"\v",
    ord("\\"): b"\\",
}
_OCTAL = b"01234567"
_HEX = b"0123456789abcdefABCDEF"


def _identifier(value: str) -> str:
    return value[1:-1] if value.startswith('"') else value.lower()


def _decode_field(raw: bytes, *, line: int, column: int) -> str | None:
    location = f"line {line}, column {column}"
    if raw == b"\\N":
        return None
    result = bytearray()
    position = 0
    while position < len(raw):
        value = raw[position]
        position += 1
        if value != 92:  # PostgreSQL COPY escapes use a backslash.
            if value < 32:
                raise LegacyDumpError(f"Unescaped control character at {location}.")
            result.append(value)
            continue
        if position == len(raw):
            raise LegacyDumpError(f"Incomplete COPY escape at {location}.")
        escape = raw[position]
        position += 1
        if escape in _ESCAPES:
            result.extend(_ESCAPES[escape])
        elif escape in _OCTAL:
            digits = bytearray([escape])
            while position < len(raw) and len(digits) < 3 and raw[position] in _OCTAL:
                digits.append(raw[position])
                position += 1
            number = int(digits, 8)
            if number > 255:
                raise LegacyDumpError(f"Out-of-range COPY byte escape at {location}.")
            result.append(number)
        elif escape == ord("x"):
            digits = bytearray()
            while position < len(raw) and len(digits) < 2 and raw[position] in _HEX:
                digits.append(raw[position])
                position += 1
            if not digits:
                raise LegacyDumpError(f"Incomplete COPY hex escape at {location}.")
            result.append(int(digits, 16))
        else:
            raise LegacyDumpError(f"Unsupported COPY escape at {location}.")
    if b"\x00" in result:
        raise LegacyDumpError(f"NUL byte in COPY text at {location}.")
    try:
        return result.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise LegacyDumpError(f"Invalid UTF-8 COPY text at {location}.") from None


def read_legacy_dump(path: str | Path) -> LegacyDump:
    """Parse a complete UTF-8 plain pg_dump, retaining original field strings.

    Numeric IDs, dates, booleans and JSON are intentionally not interpreted here;
    the converter validates them against each destination model. The SHA-256 is
    calculated over the source bytes in the same pass as parsing. Only aggregate
    ``counts`` and source metadata are safe for ordinary operator output.
    """
    tables: dict[str, list[dict[str, str | None]]] = {}
    columns: dict[str, tuple[str, ...]] = {}
    digest = sha256()
    size = 0
    active_table = None
    declared_utf8 = False
    completed = False
    with Path(path).open("rb") as source:
        for line_number, raw_line in enumerate(source, start=1):
            digest.update(raw_line)
            size += len(raw_line)
            line = raw_line.removesuffix(b"\n").removesuffix(b"\r")
            if active_table is not None:
                if line == b"\\.":
                    active_table = None
                    continue
                raw_fields = line.split(b"\t")
                names = columns[active_table]
                if len(raw_fields) != len(names):
                    raise LegacyDumpError(f"COPY column count mismatch at line {line_number}.")
                tables[active_table].append({
                    name: _decode_field(raw, line=line_number, column=index)
                    for index, (name, raw) in enumerate(zip(names, raw_fields), start=1)
                })
                continue
            try:
                statement = line.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError:
                raise LegacyDumpError(f"Invalid UTF-8 SQL text at line {line_number}.") from None
            if re.match(r"SET\s+client_encoding\b", statement, re.IGNORECASE):
                if not _ENCODING.fullmatch(statement):
                    raise LegacyDumpError("Only UTF-8 PostgreSQL dumps are supported.")
                declared_utf8 = True
            elif re.match(r"COPY\b", statement, re.IGNORECASE):
                if completed or not declared_utf8:
                    raise LegacyDumpError(f"Unexpected COPY block at line {line_number}.")
                match = _COPY.fullmatch(statement)
                if match is None or _identifier(match["schema"]) != "public":
                    raise LegacyDumpError(f"Unsupported COPY statement at line {line_number}.")
                table = _identifier(match["table"])
                names = tuple(_identifier(name.strip()) for name in match["columns"].split(","))
                if table in tables:
                    raise LegacyDumpError(f"Duplicate COPY table at line {line_number}.")
                if len(set(names)) != len(names):
                    raise LegacyDumpError(f"Duplicate COPY column at line {line_number}.")
                tables[table] = []
                columns[table] = names
                active_table = table
            elif re.match(r"INSERT\b", statement, re.IGNORECASE):
                raise LegacyDumpError(f"INSERT dumps are unsupported; use COPY text (line {line_number}).")
            elif statement == "-- PostgreSQL database dump complete":
                completed = True
    if active_table is not None:
        raise LegacyDumpError("Truncated COPY block: its end marker is missing.")
    if not completed:
        raise LegacyDumpError("Incomplete pg_dump: its completion marker is missing.")
    if not declared_utf8 or not tables:
        raise LegacyDumpError("No UTF-8 public-schema COPY data found.")
    return LegacyDump(tables, columns, digest.hexdigest(), size)
