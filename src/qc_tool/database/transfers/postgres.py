"""Complete native PostgreSQL copies; restoration never targets the live DB.

The archive is trusted administrator SQL, rather than a portable record graph.
Its independent inventory permits recovery after a lost COMMIT acknowledgement.
Only an explicit preparation action creates a separate operation-owned database.
Nothing drops, clears, repairs or switches an existing database.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from uuid import UUID

from django.conf import settings
from django.db import connection

from .archive import ArchiveLimits, _hash, _sync_directory, open_regular
from .contracts import canonical_bytes, digest
from .errors import TransferError


FORMAT = "qc-tool-postgresql"
VERSION = 1
ARTIFACT_ROOT = "database"
ARTIFACT_KEY = "archive.dump"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DATABASE = re.compile(r"[A-Za-z_][A-Za-z0-9_$-]{0,62}\Z")
_MAX_DIAGNOSTIC_BYTES = 4 * 1024**2
_MAX_SCHEMA_BYTES = 32 * 1024**2
_SYSTEM_NAMESPACE = "n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname !~ '^pg_(toast|temp)'"
_VARCHAR_LITERAL = rb"'(?:''|[^'])*'::character varying(?:\([0-9]+\))?"
_LITERAL_TEXT_ARRAY = re.compile(rb"\(ARRAY\[(?P<items>" + _VARCHAR_LITERAL + rb"(?:,\s*" + _VARCHAR_LITERAL + rb")*)\]\)::text\[\]")


def _timeout():
    value = getattr(settings, "QC_TOOL_POSTGRES_TOOL_TIMEOUT", 3600)
    if type(value) is not int or not 1 <= value <= 86400:
        raise TransferError("QC_TOOL_POSTGRES_TOOL_TIMEOUT must be between 1 and 86400 seconds.")
    return value


def _limits():
    return ArchiveLimits(**getattr(settings, "QC_TOOL_TRANSFER_ARCHIVE_LIMITS", {}))


def _require_space(directory, extra=0):
    reserve = getattr(settings, "QC_TOOL_TRANSFER_MIN_FREE_BYTES", 512 * 1024**2)
    if type(reserve) is not int or reserve < 0:
        raise TransferError("QC_TOOL_TRANSFER_MIN_FREE_BYTES must be a nonnegative integer.")
    if shutil.disk_usage(directory).free < reserve + extra:
        raise TransferError("Private backup storage is low on free space. Free space before retrying.")


def _basic_environment():
    # Do not inherit ambient libpq overrides (especially PGOPTIONS/PGDATABASE).
    result = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    result.update(LC_ALL="C", LANG="C")
    return result


def _run_tool(arguments, *, environment=None, output=None, max_bytes=None, label="PostgreSQL tool"):
    """Drain bounded diagnostics, bound elapsed time/file size, kill children."""
    process = None
    result = bytearray()
    diagnostics = 0
    try:
        from .store import execution_lease_descriptor

        lease = execution_lease_descriptor()
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL,
            stdout=output if output is not None else subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment or _basic_environment(), close_fds=True, start_new_session=True,
            pass_fds=() if lease is None else (lease,))
        started = time.monotonic()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stderr, selectors.EVENT_READ, "error")
            if output is None:
                selector.register(process.stdout, selectors.EVENT_READ, "output")
            while selector.get_map() or process.poll() is None:
                if time.monotonic() - started > _timeout():
                    raise TransferError(f"{label} exceeded the operation timeout. The target was not reset; inspect it before recovery.")
                if output is not None:
                    if max_bytes is not None and os.fstat(output.fileno()).st_size > max_bytes:
                        raise TransferError(f"{label} exceeds the configured file limit.")
                    _require_space(Path(output.name).parent)
                for key, _events in selector.select(0.1):
                    block = os.read(key.fileobj.fileno(), 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                    elif key.data == "output":
                        result.extend(block)
                        if len(result) > _MAX_DIAGNOSTIC_BYTES:
                            raise TransferError(f"{label} produced too much metadata. Use the reviewed operator restore procedure.")
                    else:
                        diagnostics += len(block)
                        if diagnostics > _MAX_DIAGNOSTIC_BYTES:
                            raise TransferError(f"{label} produced too many diagnostics. Inspect database privileges and compatibility.")
            code = process.wait()
        if code:
            # Tool stderr can contain credentials, stored values or malicious SQL.
            # Never include it (or the connection options) in user errors/logs.
            raise TransferError(f"{label} failed. Verify PostgreSQL privileges, compatible client tools and private connection settings. The target was not reset.")
        if output is not None and max_bytes is not None and os.fstat(output.fileno()).st_size > max_bytes:
            raise TransferError(f"{label} exceeds the configured file limit.")
        return bytes(result)
    except (OSError, subprocess.SubprocessError) as error:
        raise TransferError(f"{label} could not run. Install compatible PostgreSQL client tools and verify private storage.") from error
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def _toolchain(major):
    if type(major) is not int or not 14 <= major <= 18:
        raise TransferError("Native UI transfers support PostgreSQL 14 through 18. Use the reviewed operator procedure for another server version.")
    result = {}
    for name in ("pg_dump", "pg_restore"):
        candidates = [f"/usr/lib/postgresql/{major}/bin/{name}", shutil.which(name)]
        selected = None
        for candidate in dict.fromkeys(item for item in candidates if item):
            if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
                continue
            version = _run_tool([candidate, "--version"], label=name).decode("ascii", "replace").strip()
            match = re.search(r"\(PostgreSQL\)\s+(\d+)(?:\.|\s|$)", version)
            if match and int(match[1]) == major:
                selected = (candidate, version)
                break
        if selected is None:
            raise TransferError(f"Install PostgreSQL {major} pg_dump and pg_restore clients. Native UI transfers require the same client/server major version.")
        result[name] = selected[0]
        result[name + "_version"] = selected[1]
    return result


def _params():
    if connection.vendor != "postgresql":
        raise TransferError("Complete native database copies require PostgreSQL. Portable account/data transfers remain available on SQLite.")
    try:
        connection.ensure_connection()
        # Resolved libpq parameters preserve SSL/service/socket configuration.
        resolved = dict(connection.connection.get_dsn_parameters())
        configured = connection.get_connection_params()
        # A bundled psycopg libpq can be newer than pg_dump. Do not export its
        # new default-only parameters into an older client's service parser.
        shared = {"dbname", "user", "host", "hostaddr", "port", "options", "passfile",
            "sslmode", "sslcert", "sslkey", "sslrootcert", "sslcrl", "sslcrldir",
            "sslpassword", "sslsni", "sslcompression", "channel_binding", "gssencmode",
            "krbsrvname", "gsslib", "requirepeer", "target_session_attrs", "connect_timeout"}
        values = {key: value for key, value in resolved.items() if key in shared}
        values.update({key: value for key, value in configured.items()
                       if key not in {"cursor_factory", "connection_factory", "service"}})
        values.pop("service", None)
        values["connect_timeout"] = str(min(int(values.get("connect_timeout", 10) or 10), 10))
        values["application_name"] = "qc-tool-database-transfer"
        return values
    except Exception as error:
        raise TransferError("The application PostgreSQL connection is unavailable. Verify its private connection settings.") from None


@contextmanager
def _database(params, *, snapshot=False):
    import psycopg2

    handle = None
    try:
        handle = psycopg2.connect(**params)
        handle.set_session(isolation_level="REPEATABLE READ", readonly=True)
        with handle.cursor() as cursor:
            for statement in ("SET LOCAL row_security = off", "SET LOCAL TimeZone = 'UTC'",
                              "SET LOCAL DateStyle = 'ISO, YMD'", "SET LOCAL IntervalStyle = 'postgres'",
                              "SET LOCAL extra_float_digits = 3"):
                cursor.execute(statement)
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [str(_timeout() * 1000)])
            cursor.execute("""SELECT d.oid, current_database(), current_setting('server_version'),
                current_setting('server_version_num')::integer, pg_encoding_to_char(d.encoding),
                d.datcollate, d.datctype FROM pg_database d WHERE d.datname = current_database()""")
            oid, name, version, number, encoding, collate, ctype = cursor.fetchone()
            info = {"oid": oid, "database": name, "server_version": version,
                    "server_major": number // 10000, "encoding": encoding,
                    "collation": collate, "ctype": ctype}
            info.update(_locale_metadata(cursor, info["server_major"]))
            if snapshot:
                cursor.execute("SELECT pg_export_snapshot()")
                info["snapshot"] = cursor.fetchone()[0]
        yield handle, info
    except TransferError:
        raise
    except Exception as error:
        raise TransferError("The complete PostgreSQL snapshot could not be inspected. Verify access to every table, sequence and large object; partial or row-filtered backups are not supported.") from None
    finally:
        if handle is not None:
            handle.close()


def _locale_metadata(cursor, major):
    if major < 15:
        return {"locale_provider": "libc", "locale": "", "icu_rules": ""}
    locale_column = "datlocale" if major >= 17 else "daticulocale"
    rules = "COALESCE(daticurules, '')" if major >= 16 else "''"
    cursor.execute(f"SELECT datlocprovider, COALESCE({locale_column}, ''), {rules} FROM pg_database WHERE datname=current_database()")
    provider, locale, icu_rules = cursor.fetchone()
    providers = {"c": "libc", "i": "icu", "b": "builtin"}
    if provider not in providers:
        raise TransferError("This database uses an unsupported PostgreSQL locale provider.")
    return {"locale_provider": providers[provider], "locale": locale, "icu_rules": icu_rules}


def _archive_locale(source):
    if "locale_provider" not in source:
        if source["server_major"] != 14:
            raise TransferError("This older archive does not identify its PostgreSQL locale provider. Export a new complete backup before creating a restore database.")
        return {"locale_provider": "libc", "locale": "", "icu_rules": ""}
    return {key: source[key] for key in ("locale_provider", "locale", "icu_rules")}


@contextmanager
def _tool_environment(params):
    # libpq service files support all connection parameters, including TLS,
    # without exposing any connection strings/passwords in a process listing.
    with tempfile.TemporaryDirectory(prefix="qc-postgres-credentials-") as directory:
        directory = Path(directory)
        service = directory / "service.conf"
        lines = ["[qc_transfer]"]
        for key, value in params.items():
            if key in {"password", "passfile", "service"} or value is None:
                continue
            value = str(value)
            if any(char in value for char in ("\x00", "\r", "\n")):
                raise TransferError("PostgreSQL connection settings contain unsupported line breaks.")
            lines.append(f"{key}={value}")
        with open(service, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
            output.write("\n".join(lines) + "\n")
        environment = _basic_environment()
        environment.update(PGSERVICEFILE=str(service), PGSERVICE="qc_transfer")
        if "password" in params:
            password = str(params["password"])
            if any(char in password for char in ("\x00", "\r", "\n")):
                raise TransferError("The database password cannot be represented by the PostgreSQL password-file format.")
            password_file = directory / "pgpass"
            with open(password_file, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
                output.write("*:*:*:*:" + password.replace("\\", "\\\\").replace(":", "\\:") + "\n")
            environment["PGPASSFILE"] = str(password_file)
        elif params.get("passfile"):
            environment["PGPASSFILE"] = str(params["passfile"])
        yield environment


class _RowDigest:
    def __init__(self):
        self.digest = hashlib.sha256()
        self.rows = 0

    def write(self, block):
        if isinstance(block, str):
            block = block.encode("utf-8")
        self.digest.update(block)
        self.rows += block.count(b"\n")


def _sequences(handle):
    from psycopg2 import sql

    with handle.cursor() as cursor:
        cursor.execute(f"SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='S' AND {_SYSTEM_NAMESPACE} ORDER BY n.nspname, c.relname")
        names = cursor.fetchall()
        result = []
        for schema, name in names:
            cursor.execute(sql.SQL("SELECT last_value, is_called FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(name)))
            value, called = cursor.fetchone()
            result.append({"schema": schema, "name": name, "last_value": value, "is_called": called})
        return result


def _schema_hash(params, tools, snapshot):
    with tempfile.NamedTemporaryFile(prefix="qc-postgres-schema-") as output:
        arguments = [tools["pg_dump"], "--no-password", "--schema-only", "--no-owner", "--no-privileges", "--no-tablespaces", "--snapshot=" + snapshot]
        with _tool_environment(params) as environment:
            _run_tool(arguments, environment=environment, output=output, max_bytes=_MAX_SCHEMA_BYTES, label="PostgreSQL schema verification")
        output.seek(0)
        hasher = hashlib.sha256()
        for line in output:
            # Modern clients randomize a psql safety key; version banners are
            # provenance, not schema. Keep SQL/comments/constraints unchanged.
            if line.startswith((b"\\restrict ", b"\\unrestrict ", b"-- Dumped from database version ", b"-- Dumped by pg_dump version ")):
                continue
            hasher.update(_canonical_constraint_line(line))
        return hasher.hexdigest()


def _canonical_constraint_line(line):
    # Re-parsing a dumped CHECK can distribute a varchar[] -> text[] coercion
    # over its literal elements. Normalize precisely these equivalent forms;
    # never strip arbitrary casts (numeric precision/collation can be semantic).
    if not line.lstrip().startswith(b"CONSTRAINT ") or b" CHECK " not in line:
        return line

    def distribute(match):
        items = re.findall(_VARCHAR_LITERAL, match["items"])
        return b"ARRAY[" + b", ".join(b"(" + item + b")::text" for item in items) + b"]"

    return _LITERAL_TEXT_ARRAY.sub(distribute, line)


def _inventory(handle, params, tools, snapshot):
    from psycopg2 import sql

    tables = []
    with handle.cursor() as cursor:
        cursor.execute("SET LOCAL search_path = pg_catalog")
        cursor.execute(f"SELECT c.oid, n.nspname, c.relname, c.relkind, c.relispopulated FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','m') AND {_SYSTEM_NAMESPACE} ORDER BY n.nspname, c.relname")
        relations = cursor.fetchall()
        for oid, schema, name, kind, populated in relations:
            cursor.execute("""SELECT a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull,
                a.attidentity, a.attgenerated FROM pg_attribute a WHERE a.attrelid=%s AND
                a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum""", [oid])
            columns = [{"name": name, "type": datatype, "nullable": not not_null,
                        "identity": identity, "generated": generated}
                       for name, datatype, not_null, identity, generated in cursor.fetchall()]
            row_digest = _RowDigest()
            # ONLY prevents counting inherited/partitioned rows twice. Sorting
            # complete rows gives stable hashes even without a primary key.
            only = sql.SQL("") if kind == "m" else sql.SQL("ONLY ")
            statement = sql.SQL('COPY (SELECT row_to_json(q)::text FROM {}{}.{} q ORDER BY row_to_json(q)::text COLLATE "C") TO STDOUT').format(only, sql.Identifier(schema), sql.Identifier(name))
            if populated:
                cursor.copy_expert(statement, row_digest)
            tables.append({"schema": schema, "name": name, "kind": kind, "columns": columns,
                           "populated": populated, "rows": row_digest.rows, "sha256": row_digest.digest.hexdigest()})
        cursor.execute("SELECT oid FROM pg_largeobject_metadata ORDER BY oid")
        large_objects = []
        for (oid,) in cursor.fetchall():
            large_object = handle.lobject(oid, "rb")
            try:
                hasher, size = hashlib.sha256(), 0
                for chunk in iter(lambda: large_object.read(1024**2), b""):
                    hasher.update(chunk)
                    size += len(chunk)
                large_objects.append({"oid": oid, "size": size, "sha256": hasher.hexdigest()})
            finally:
                large_object.close()
    return {"tables": tables, "sequences": _sequences(handle), "large_objects": large_objects,
            "schema_sha256": _schema_hash(params, tools, snapshot),
            "total_rows": sum(table["rows"] for table in tables)}


def _review(info, tools, inventory):
    source = {key: value for key, value in info.items() if key != "snapshot"}
    source.update(dump_version=tools["pg_dump_version"], restore_version=tools["pg_restore_version"])
    result = {"format": FORMAT, "version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
              "source": source, "inventory": inventory}
    result["review_hash"] = digest({"source": source, "inventory": inventory})
    result["counts"] = {"tables": len(inventory["tables"]), "rows": inventory["total_rows"]}
    result["source_details"] = {"app_version": str(os.environ.get("VERSION", "unknown")),
        "postgresql_version": info["server_version"], "source_database": info["database"],
        "exported_at": result["created_at"]}
    return result


def availability():
    try:
        params = _params()
        with _database(params) as (handle, info):
            _toolchain(info["server_major"])
            with handle.cursor() as cursor:
                _owner, can_create = _creation_role(cursor)
    except TransferError as error:
        return {"available": False, "reason": str(error), "can_create_restore": False,
                "restore_reason": "PostgreSQL restore preparation is unavailable."}
    return {"available": True, "reason": "Complete PostgreSQL backup is available.",
            "can_create_restore": can_create,
            "restore_reason": ("Administrators can create a fresh restore database here." if can_create else
                "The configured PostgreSQL account needs CREATEDB permission to create a fresh restore database. Ask the database administrator to enable this capability.")}


def preview():
    params = _params()
    with _database(params, snapshot=True) as (handle, info):
        tools = _toolchain(info["server_major"])
        return _review(info, tools, _inventory(handle, params, tools, info["snapshot"]))


def dump_to(path):
    """Write the full custom archive, never a table-filtered ORM projection."""
    path = Path(path)
    params = _params()
    try:
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077:
            raise TransferError("Native backups require a private real directory (0700).")
        with _database(params, snapshot=True) as (handle, info):
            tools = _toolchain(info["server_major"])
            inventory = _inventory(handle, params, tools, info["snapshot"])
            _require_space(path.parent)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as output, _tool_environment(params) as environment:
                # output.name is an fd; give disk-space monitoring a safe path.
                class Output:
                    name = str(path)

                    def fileno(self):
                        return output.fileno()

                _run_tool([tools["pg_dump"], "--no-password", "--format=custom", "--snapshot=" + info["snapshot"]],
                          environment=environment, output=Output(), max_bytes=_limits().max_member_bytes,
                          label="Complete PostgreSQL backup")
                output.flush()
                os.fsync(output.fileno())
            # Sequence state is not MVCC. Concurrent external sequence writes
            # invalidate the reconciliation rather than producing a false proof.
            if inventory["sequences"] != _sequences(handle):
                raise TransferError("Database sequences changed during backup. Isolate external writers and retry.")
            result = _review(info, tools, inventory)
        with open_regular(path) as source:
            sha, size = _hash(source, _limits().max_member_bytes)
        _sync_directory(path.parent)
        result.update(dump_sha256=sha, dump_bytes=size)
        return result
    except FileExistsError as error:
        raise TransferError("The native backup file already exists. Do not overwrite a retained backup.") from error
    except Exception:
        # Never unlink a pre-existing file if exclusive creation failed.
        if 'descriptor' in locals():
            path.unlink(missing_ok=True)
            _sync_directory(path.parent)
        raise


def _native_metadata(verified):
    try:
        return _validate_native_metadata(verified)
    except TransferError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise TransferError("The native PostgreSQL backup metadata is malformed.") from None


def _validate_native_metadata(verified):
    data = verified.records
    required = {"format", "version", "created_at", "source", "inventory", "review_hash", "dump_sha256", "dump_bytes", "counts", "source_details"}
    if not isinstance(data, dict) or set(data) != required or data.get("format") != FORMAT or type(data.get("version")) is not int or data["version"] != VERSION:
        raise TransferError("Unsupported native PostgreSQL backup metadata.")
    created = datetime.fromisoformat(data["created_at"])
    if created.utcoffset() is None:
        raise TransferError("The native PostgreSQL backup timestamp must include a timezone.")
    source, inventory = data["source"], data["inventory"]
    source_required = {"oid", "database", "server_version", "server_major", "encoding", "collation", "ctype", "dump_version", "restore_version"}
    source_locale = {"locale_provider", "locale", "icu_rules"}
    if (not isinstance(source, dict) or set(source) not in (source_required, source_required | source_locale)
            or type(source.get("oid")) is not int or source["oid"] <= 0
            or type(source.get("server_major")) is not int or not 14 <= source["server_major"] <= 18
            or any(not isinstance(source[key], str) or (not source[key] and key not in {"locale", "icu_rules"}) or len(source[key]) > 1000 for key in source if key not in {"oid", "server_major"})):
        raise TransferError("The native PostgreSQL source identity is invalid.")
    if source_locale <= set(source):
        if (source["locale_provider"] not in {"libc", "icu", "builtin"}
                or (source["locale_provider"] != "libc" and not source["locale"])
                or (source["locale_provider"] != "icu" and source["icu_rules"])):
            raise TransferError("The native PostgreSQL locale metadata is invalid.")
    if not isinstance(inventory, dict) or set(inventory) != {"tables", "sequences", "large_objects", "schema_sha256", "total_rows"}:
        raise TransferError("The native PostgreSQL inventory is invalid.")
    if (not isinstance(inventory["tables"], list) or not isinstance(inventory["sequences"], list)
            or not isinstance(inventory["large_objects"], list) or not _SHA256.fullmatch(str(inventory["schema_sha256"]))
            or type(inventory["total_rows"]) is not int or inventory["total_rows"] < 0):
        raise TransferError("The native PostgreSQL inventory is invalid.")
    names = set()
    for table in inventory["tables"]:
        if not isinstance(table, dict) or set(table) != {"schema", "name", "kind", "columns", "populated", "rows", "sha256"}:
            raise TransferError("The native PostgreSQL table inventory is invalid.")
        identity = (table["schema"], table["name"])
        if (any(not isinstance(value, str) or not value or len(value.encode()) > 63 for value in identity)
                or identity in names or not isinstance(table["kind"], str) or table["kind"] not in {"r", "p", "m"}
                or type(table["populated"]) is not bool
                or type(table["rows"]) is not int or table["rows"] < 0
                or not isinstance(table["columns"], list) or not _SHA256.fullmatch(str(table["sha256"]))):
            raise TransferError("The native PostgreSQL table inventory is invalid.")
        names.add(identity)
        columns = set()
        for column in table["columns"]:
            if (not isinstance(column, dict) or set(column) != {"name", "type", "nullable", "identity", "generated"}
                    or not isinstance(column["name"], str) or column["name"] in columns
                    or not isinstance(column["type"], str) or type(column["nullable"]) is not bool
                    or not isinstance(column["identity"], str) or column["identity"] not in {"", "a", "d"}
                    or not isinstance(column["generated"], str) or column["generated"] not in {"", "s", "v"}):
                raise TransferError("The native PostgreSQL column inventory is invalid.")
            columns.add(column["name"])
    if inventory["total_rows"] != sum(table["rows"] for table in inventory["tables"]):
        raise TransferError("The native PostgreSQL row inventory disagrees.")
    if data["counts"] != {"tables": len(inventory["tables"]), "rows": inventory["total_rows"]}:
        raise TransferError("The native PostgreSQL displayed counts disagree with its inventory.")
    details = data["source_details"]
    if (not isinstance(details, dict) or set(details) != {"app_version", "postgresql_version", "source_database", "exported_at"}
            or any(not isinstance(value, str) or len(value) > 1000 for value in details.values())
            or details["source_database"] != source["database"] or details["postgresql_version"] != source["server_version"]
            or details["exported_at"] != data["created_at"]):
        raise TransferError("The native PostgreSQL source details disagree with its inventory.")
    sequence_names, large_ids = set(), set()
    for sequence in inventory["sequences"]:
        if (not isinstance(sequence, dict) or set(sequence) != {"schema", "name", "last_value", "is_called"}
                or not isinstance(sequence["schema"], str) or not isinstance(sequence["name"], str)
                or (sequence["schema"], sequence["name"]) in sequence_names
                or type(sequence["last_value"]) is not int or type(sequence["is_called"]) is not bool):
            raise TransferError("The native PostgreSQL sequence inventory is invalid.")
        sequence_names.add((sequence["schema"], sequence["name"]))
    for item in inventory["large_objects"]:
        if (not isinstance(item, dict) or set(item) != {"oid", "size", "sha256"}
                or type(item["oid"]) is not int or item["oid"] <= 0 or item["oid"] in large_ids
                or type(item["size"]) is not int or item["size"] < 0 or not _SHA256.fullmatch(str(item["sha256"]))):
            raise TransferError("The native PostgreSQL large-object inventory is invalid.")
        large_ids.add(item["oid"])
    if (not isinstance(data["review_hash"], str) or data["review_hash"] != digest({"source": source, "inventory": inventory})
            or not _SHA256.fullmatch(str(data["dump_sha256"])) or type(data["dump_bytes"]) is not int or data["dump_bytes"] < 5):
        raise TransferError("The native PostgreSQL inventory fingerprint is invalid.")
    database_entries = [entry for entry in verified.entries if entry["root"] == ARTIFACT_ROOT]
    if (len(database_entries) != 1 or database_entries[0]["key"] != ARTIFACT_KEY
            or database_entries[0]["sha256"] != data["dump_sha256"] or database_entries[0]["size"] != data["dump_bytes"]):
        raise TransferError("A native PostgreSQL package must contain exactly its complete database archive.")
    from .recovery_files import validate
    validate(verified)
    return data


@contextmanager
def _native_file(verified):
    # Keep large temporary copies on the private persistent transfer filesystem,
    # whose capacity is configured, rather than on the container's /tmp layer.
    directory = verified.path.parent
    entry = next(item for item in verified.entries if item["root"] == ARTIFACT_ROOT and item["key"] == ARTIFACT_KEY)
    _require_space(directory, entry["size"])
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".qc-postgres-archive-", suffix=".dump") as output:
        class CheckedOutput:
            def write(self, block):
                _require_space(directory, len(block))
                return output.write(block)

        verified.copy_artifact(entry, CheckedOutput())
        output.flush()
        output.seek(0)
        if output.read(5) != b"PGDMP":
            raise TransferError("The package does not contain a PostgreSQL custom archive.")
        yield Path(output.name)


def inspect_native(verified):
    data = _native_metadata(verified)
    tools = _toolchain(data["source"]["server_major"])
    with _native_file(verified) as path:
        _run_tool([tools["pg_restore"], "--list", str(path)], label="Native PostgreSQL archive inspection")
    return data


def _creation_role(cursor):
    cursor.execute("SELECT oid, rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user")
    row = cursor.fetchone()
    if row is None:
        raise TransferError("The configured PostgreSQL account could not be identified.")
    return row


def restore_database_name(operation_id):
    """Derive a server-owned name; browsers never supply database identifiers."""
    try:
        value = UUID(str(operation_id))
        if str(value) != str(operation_id):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise TransferError("Choose a valid database restore operation.") from None
    return "qc_restore_" + value.hex


def _created_database(cursor, name):
    cursor.execute("""SELECT d.oid, d.datdba, d.datallowconn,
        shobj_description(d.oid, 'pg_database') FROM pg_database d WHERE d.datname=%s""", [name])
    return cursor.fetchone()


def _create_database(cursor, name, source):
    from psycopg2 import sql

    locale = _archive_locale(source)
    statement = sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING {} LC_COLLATE {} LC_CTYPE {} ALLOW_CONNECTIONS false").format(
        sql.Identifier(name), sql.Literal(source["encoding"]), sql.Literal(source["collation"]), sql.Literal(source["ctype"]))
    if source["server_major"] >= 15:
        statement += sql.SQL(" LOCALE_PROVIDER {}").format(sql.Literal(locale["locale_provider"]))
        if locale["locale_provider"] == "icu":
            statement += sql.SQL(" ICU_LOCALE {}").format(sql.Literal(locale["locale"]))
            if locale["icu_rules"]:
                statement += sql.SQL(" ICU_RULES {}").format(sql.Literal(locale["icu_rules"]))
        elif locale["locale_provider"] == "builtin":
            statement += sql.SQL(" BUILTIN_LOCALE {}").format(sql.Literal(locale["locale"]))
    cursor.execute(statement)


def _validate_creation_journal(value, *, operation_id, name, package_sha256, source_fingerprint, owner):
    if (not isinstance(value, dict) or set(value) != {"version", "operation_id", "database", "package_sha256", "source_fingerprint", "owner_oid", "marker", "status", "target_oid"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["operation_id"] != operation_id or value["database"] != name
            or value["package_sha256"] != package_sha256 or value["source_fingerprint"] != source_fingerprint
            or value["owner_oid"] != owner or value["status"] not in {"creating", "owned", "ready"}
            or not isinstance(value["marker"], str) or not re.fullmatch(r"qc-tool-restore:" + re.escape(operation_id) + r":[0-9a-f]{64}", value["marker"])
            or (value["target_oid"] is not None and (type(value["target_oid"]) is not int or value["target_oid"] <= 0))
            or (value["status"] != "creating" and value["target_oid"] is None)):
        raise TransferError("The restore database ownership journal does not match this operation. Preserve the database and private journal for inspection.")
    return value


def prepare_restore_target(verified, operation_id):
    """Explicitly create one fresh, owned target with durable recovery evidence.

    CREATE DATABASE cannot share a transaction with its ownership marker. A
    crash in that gap leaves an unmarked database, which is retained/refused.
    A marker plus the durable operation intent can finish later preparation;
    a recorded OID prevents adopting a dropped/recreated database with its name.
    The caller owns authorization and the maintenance/control/execution locks.
    """
    from psycopg2 import sql
    import psycopg2
    from . import store

    if store.execution_lease_descriptor() is None:
        raise TransferError("Database preparation must run through the serialized administrator transfer controls.")
    data = inspect_native(verified)
    name = restore_database_name(operation_id)
    operation_id = str(operation_id)
    path = store.operation_dir(operation_id) / "restore-target.json"
    params = _params()
    with _database(params) as (_handle, info):
        if info["server_major"] != data["source"]["server_major"]:
            raise TransferError("Create the restore target on the same PostgreSQL major version as the archive. No database was created.")
    _archive_locale(data["source"])
    source_fingerprint = _target_fingerprint(params, info, {
        "database": name, "oid": 0, "server_major": info["server_major"],
    })
    creator = None
    created = False
    try:
        creator = psycopg2.connect(**params)
        creator.autocommit = True
        with creator.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout', %s, false)", [str(_timeout() * 1000)])
            owner, can_create = _creation_role(cursor)
            existing = _created_database(cursor, name)
            if path.exists() or path.is_symlink():
                journal = _validate_creation_journal(store.read_json(path), operation_id=operation_id,
                    name=name, package_sha256=verified.package_sha256,
                    source_fingerprint=source_fingerprint, owner=owner)
            else:
                if existing is not None:
                    raise TransferError("The generated restore database name already exists without this operation's ownership evidence. It was preserved; start a new import operation.")
                if not can_create:
                    raise TransferError("The configured PostgreSQL account needs CREATEDB permission to create a restore database. Ask the database administrator to enable this capability; no database was created.")
                journal = {"version": 1, "operation_id": operation_id, "database": name,
                    "package_sha256": verified.package_sha256, "source_fingerprint": source_fingerprint,
                    "owner_oid": owner, "marker": "qc-tool-restore:" + operation_id + ":" + secrets.token_hex(32),
                    "status": "creating", "target_oid": None}
                # Commit the intent to private persistent storage before DDL.
                store.write_json(path, journal)
            if existing is None:
                if journal["status"] != "creating" or journal["target_oid"] is not None:
                    raise TransferError("The operation's prepared database is missing. It will not be recreated under the same reviewed identity; start a new import operation.")
                if not can_create:
                    raise TransferError("CREATEDB permission is required to finish preparing this new restore database. No existing database was changed.")
                _create_database(cursor, name, data["source"])
                created = True
                cursor.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(name), sql.Literal(journal["marker"])))
                existing = _created_database(cursor, name)
            if (existing is None or existing[1] != owner or existing[3] != journal["marker"]
                    or (journal["target_oid"] is not None and existing[0] != journal["target_oid"])):
                raise TransferError("Database preparation could not prove ownership of the existing destination. A CREATE acknowledgement may have been lost. The database was preserved; start a new import operation or ask the database administrator to inspect it.")
            if journal["status"] == "ready" and not existing[2]:
                raise TransferError("The prepared database's connection state was changed externally. It was preserved; inspect the destination before recovery.")
            if journal["status"] != "ready":
                journal.update(status="owned", target_oid=existing[0])
                store.write_json(path, journal)
                if not existing[2]:
                    cursor.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(sql.Identifier(name)))
                journal["status"] = "ready"
                store.write_json(path, journal)
    except TransferError:
        raise
    except Exception:
        raise TransferError("The fresh restore database could not be prepared. The operation journal and any created database were preserved. Retry preparation; an unmarked or uncertain database is never replaced.") from None
    finally:
        if creator is not None:
            creator.close()
    # Read-only validation binds the final target OID and rejects other clients.
    with _target(data, name) as (_handle, target, _target_params, fingerprint):
        return {"database": name, "target_database": name, "target_oid": target["oid"],
                "target_label": "postgresql / " + name, "target_fingerprint": fingerprint,
                "created": created, "ready": True}


def _target_name(destination=None):
    value = getattr(settings, "QC_TOOL_RESTORE_DATABASE", "") if destination is None else destination
    if not isinstance(value, str) or not _DATABASE.fullmatch(value):
        raise TransferError("Create a fresh restore database in the administrator panel before reviewing this import. Only server-owned database names are supported; connection strings and browser-selected hosts are refused.")
    return value


def _target_fingerprint(params, source_info, target_info):
    return digest({"host": params.get("host", ""), "hostaddr": params.get("hostaddr", ""),
        "port": params.get("port", ""), "source_oid": source_info["oid"],
        "source_database": source_info["database"], "target_oid": target_info["oid"],
        "target_database": target_info["database"], "server_major": target_info["server_major"]})


def _empty(handle):
    with handle.cursor() as cursor:
        # Check all schemas and object families, not merely Django model tables.
        cursor.execute("""SELECT EXISTS (
            SELECT 1 FROM pg_namespace n WHERE n.nspname NOT IN ('public','pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)'
            UNION ALL SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_conversion c JOIN pg_namespace n ON n.oid=c.connamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_operator o JOIN pg_namespace n ON n.oid=o.oprnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_opclass o JOIN pg_namespace n ON n.oid=o.opcnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_opfamily o JOIN pg_namespace n ON n.oid=o.opfnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_ts_config t JOIN pg_namespace n ON n.oid=t.cfgnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_ts_dict t JOIN pg_namespace n ON n.oid=t.dictnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_ts_parser t JOIN pg_namespace n ON n.oid=t.prsnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_ts_template t JOIN pg_namespace n ON n.oid=t.tmplnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_default_acl
            UNION ALL SELECT 1 FROM pg_cast WHERE oid>=16384
            UNION ALL SELECT 1 FROM pg_cast c JOIN pg_type t ON t.oid=c.castsource JOIN pg_namespace n ON n.oid=t.typnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_cast c JOIN pg_type t ON t.oid=c.casttarget JOIN pg_namespace n ON n.oid=t.typnamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_cast c JOIN pg_proc p ON p.oid=c.castfunc JOIN pg_namespace n ON n.oid=p.pronamespace WHERE """ + _SYSTEM_NAMESPACE + """
            UNION ALL SELECT 1 FROM pg_extension WHERE extname<>'plpgsql'
            UNION ALL SELECT 1 FROM pg_largeobject_metadata
            UNION ALL SELECT 1 FROM pg_event_trigger
            UNION ALL SELECT 1 FROM pg_foreign_server
            UNION ALL SELECT 1 FROM pg_foreign_data_wrapper
            UNION ALL SELECT 1 FROM pg_publication
            UNION ALL SELECT 1 FROM pg_subscription
        )""")
        return not cursor.fetchone()[0]


@contextmanager
def _target(source_metadata, destination=None):
    params = _params()
    with _database(params) as (_handle, source):
        target_params = {**params, "dbname": _target_name(destination)}
        with _database(target_params, snapshot=True) as (handle, target):
            if source["oid"] == target["oid"]:
                raise TransferError("The restore target is the connected application database. Choose a separate empty target; existing databases are never replaced.")
            _require_isolated_target(handle, target)
            if target["server_major"] != source_metadata["source"]["server_major"]:
                raise TransferError("Native UI restore requires the same PostgreSQL major version as the archive. Use the reviewed operator procedure for cross-version upgrades.")
            if any(target[key] != source_metadata["source"][key] for key in ("encoding", "collation", "ctype")):
                raise TransferError("The empty target must use the archive's encoding and locale. Provision a matching fresh database; no target settings were changed.")
            if any(target[key] != value for key, value in _archive_locale(source_metadata["source"]).items()):
                raise TransferError("The restore target's locale provider or rules do not match this archive. Create a matching fresh target; no locale settings were changed.")
            yield handle, target, target_params, _target_fingerprint(params, source, target)


def _require_isolated_target(handle, target):
    with handle.cursor() as cursor:
        cursor.execute("SELECT pg_stat_clear_snapshot()")
        cursor.execute("""SELECT EXISTS (SELECT 1 FROM pg_stat_activity
            WHERE datid=%s AND pid<>pg_backend_pid()
            AND backend_type IN ('client backend', 'parallel worker'))
            OR EXISTS (SELECT 1 FROM pg_prepared_xacts WHERE \"database\"=%s)""",
            [target["oid"], target["database"]])
        if cursor.fetchone()[0]:
            raise TransferError("The restore target has another connected client, parallel worker or prepared transaction. Isolate that database and inspect any interrupted restore before retrying; no target was cleared.")


def plan_restore(verified, destination=None):
    data = inspect_native(verified)
    with _target(data, destination) as (handle, target, _params_value, fingerprint):
        empty = _empty(handle)
    return {"can_apply": empty,
            "blockers": [] if empty else ["The restore target is not entirely empty. Existing schemas, accounts and tables are never cleared or overwritten. Provision another fresh database."],
            "target_label": "postgresql / " + target["database"],
            "confirmation_text": target["database"], "target_fingerprint": fingerprint,
            "counts": {"tables": len(data["inventory"]["tables"]), "rows": data["inventory"]["total_rows"]},
            "source": data["source"], "source_details": data["source_details"]}


def _verify(handle, target_params, target_info, data):
    tools = _toolchain(target_info["server_major"])
    actual = _inventory(handle, target_params, tools, target_info["snapshot"])
    if actual != data["inventory"]:
        raise TransferError("The target does not exactly match this backup's schema, every table/column value, sequences and large objects. Keep maintenance enabled and preserve the target for inspection.")
    return {"verified": True, "target_database": target_info["database"],
            "target_label": "postgresql / " + target_info["database"],
            "counts": {"tables": len(actual["tables"]), "rows": actual["total_rows"]},
            "tables": len(actual["tables"]), "rows": actual["total_rows"],
            "inventory_sha256": digest(actual), "dump_sha256": data["dump_sha256"]}


def verify_restore(verified, expected_target_fingerprint, destination=None):
    data = inspect_native(verified)
    with _target(data, destination) as (handle, target, params, fingerprint):
        if not isinstance(expected_target_fingerprint, str) or fingerprint != expected_target_fingerprint:
            raise TransferError("The reviewed restore target identity changed. Keep maintenance enabled and review the target again.")
        return _verify(handle, params, target, data)


def restore(verified, expected_target_fingerprint, destination=None):
    data = inspect_native(verified)
    with _target(data, destination) as (handle, target, params, fingerprint):
        if not isinstance(expected_target_fingerprint, str) or fingerprint != expected_target_fingerprint:
            raise TransferError("The reviewed restore target identity changed. Review again before restoring.")
        if not _empty(handle):
            # A lost COMMIT acknowledgement may already have completed exactly
            # this reviewed operation. Anything else remains blocked, untouched.
            return _verify(handle, params, target, data)
        tools = _toolchain(target["server_major"])
        with _native_file(verified) as path, _tool_environment(params) as environment:
            _run_tool([tools["pg_restore"], "--no-password", "--single-transaction", "--exit-on-error",
                "--no-owner", "--no-privileges", "--no-tablespaces", "--dbname=service=qc_transfer", str(path)],
                environment=environment, label="Restore into the separate empty PostgreSQL target")
    # Verification needs a new snapshot that sees the restore's commit.
    return verify_restore(verified, expected_target_fingerprint, destination)
