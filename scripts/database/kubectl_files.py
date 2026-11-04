"""Copy files between the local disk and a Kubernetes pod with kubectl (runs locally).

Shared by export_legacy_tables.py and import_legacy_tables_kubernetes.py. Named
without "legacy" on purpose: the pod only receives the *legacy*.py scripts.
"""
import os
import re
import subprocess
import tarfile
import threading
from pathlib import Path

# <date>-<name>-<job uuid>.d: the job UUID that ends the name of a submission folder.
SUBMISSION_FOLDER = re.compile(r"-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.d$")

# One kubectl exec stream per batch: a single long stream tends to break
# ("error reading from error stream"), so batches are small and retried.
BATCH_BYTES = 128 * 1024 * 1024
BATCH_FILES = 200
ATTEMPTS = 3


def find_pod(namespace, name, prefix):
    """The pod called name, or else the first running pod starting with prefix."""
    if name:
        return name
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", namespace,
         "--field-selector=status.phase=Running",
         "-o", "jsonpath={.items[*].metadata.name}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
    )
    pods = [pod for pod in result.stdout.split() if pod.startswith(prefix)]
    if not pods:
        raise SystemExit(f"Error: no running pod starting with '{prefix}' in namespace '{namespace}'.")
    return pods[0]


def plain_name(name):
    """A single path component; database values must not escape the storage root."""
    return bool(name) and name not in (".", "..") and not any(char in name for char in "/\\\0\r\n")


def _exec(namespace, pod, shell_command):
    return ["kubectl", "exec", "-i", "-n", namespace, pod, "--", "sh", "-c", shell_command]


def existing_files(namespace, pod, root, names, *, job_directories=False):
    """Names (relative to root) of the files that exist in the pod; reports the missing.

    With job_directories each name is a directory, and its regular files directly
    inside (not the subdirectories) are listed.
    """
    if job_directories:
        script = ('while IFS= read -r d; do n=0; for f in "$d"/*; do '
                  'if [ -f "$f" ]; then echo "$f"; n=1; fi; done; '
                  '[ "$n" = 1 ] || echo "  missing: $d" >&2; done')
    else:
        script = 'while IFS= read -r f; do if [ -f "$f" ]; then echo "$f"; else echo "  missing: $f" >&2; fi; done'
    # Bytes, not text: on Windows text mode would add \r to every line.
    result = subprocess.run(
        _exec(namespace, pod, f'cd "{root}" && {script}'),
        input="".join(f"{name}\n" for name in names).encode(), stdout=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SystemExit(f"Error: checking the files in the pod failed with exit code {result.returncode}.")
    return result.stdout.decode("utf-8").splitlines()


def remote_sizes(namespace, pod, root, names):
    """File sizes in the pod, in the order of names (-1 when a file cannot be read)."""
    result = subprocess.run(
        _exec(namespace, pod, f'cd "{root}" && while IFS= read -r f; do stat -c %s "$f" 2>/dev/null || echo -1; done'),
        input="".join(f"{name}\n" for name in names).encode(), stdout=subprocess.PIPE,
    )
    sizes = [int(line) for line in result.stdout.decode("ascii").split()]
    if result.returncode != 0 or len(sizes) != len(names):
        raise SystemExit("Error: could not read the file sizes in the pod.")
    return sizes


def _complete(target, name, size):
    path = target / name
    return path.is_file() and path.stat().st_size == size


def _batches(names, sizes):
    batch, total = [], 0
    for name, size in zip(names, sizes):
        if batch and (total + size > BATCH_BYTES or len(batch) >= BATCH_FILES):
            yield batch
            batch, total = [], 0
        batch.append(name)
        total += size
    if batch:
        yield batch


def long_path(path):
    """Absolute path; on Windows with the extended-length prefix, which lifts the 260 character limit."""
    prefix = "\\\\?\\"
    path = os.path.abspath(path)
    if os.name == "nt" and not path.startswith(prefix):
        path = prefix + path
    return Path(path)


def _stream(namespace, pod, root, names, target):
    """One kubectl exec tar stream of names into target; raises when it breaks.

    Returns {name: error} for the files that could not be written locally. Those
    do not break the stream and are not worth retrying.
    """
    process = subprocess.Popen(
        _exec(namespace, pod, f'tar -cf - -C "{root}" -T -'),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )

    # Feed the list from a thread: tar writes output while it still reads names.
    def feed():
        try:
            process.stdin.write("".join(f"{name}\n" for name in names).encode())
        except OSError:
            pass  # The stream broke; the reader reports it.
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    unwritable = {}
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                try:
                    archive.extract(member, target, filter="data")
                except (tarfile.FilterError, OSError) as error:
                    # The file is opened before any data is read, so the stream stays valid.
                    unwritable[member.name] = error
    except BaseException:
        process.kill()
        raise
    finally:
        process.stdout.close()
        writer.join()
        returncode = process.wait()
    if returncode != 0:
        raise OSError(f"kubectl exited with code {returncode}")
    return unwritable


def copy_files(namespace, pod, root, names, target):
    """Copy the files (relative to root in the pod) into the local target directory.

    Files already complete locally (same size) are skipped, so an interrupted run
    can be repeated. Returns the number of files that are complete afterwards.
    """
    shown = Path(target)
    target = long_path(target)
    target.mkdir(parents=True, exist_ok=True)
    sizes = remote_sizes(namespace, pod, root, names)
    wanted = {name: size for name, size in zip(names, sizes)}
    todo = [name for name in names if not _complete(target, name, wanted[name])]
    print(f"{len(names) - len(todo)} files already copied, {len(todo)} to copy "
          f"({sum(wanted[name] for name in todo) / 1e6:.0f} MB).", flush=True)

    failed, unwritable = [], {}
    for number, batch in enumerate(_batches(todo, [wanted[name] for name in todo]), 1):
        for attempt in range(1, ATTEMPTS + 1):
            pending = [name for name in batch if not _complete(target, name, wanted[name]) and name not in unwritable]
            if not pending:
                break
            try:
                unwritable.update(_stream(namespace, pod, root, pending, target))
            except (tarfile.TarError, OSError, EOFError) as error:
                print(f"  batch {number}, attempt {attempt} of {ATTEMPTS} failed: {error}", flush=True)
        missing = [name for name in batch if not _complete(target, name, wanted[name])]
        failed += missing
        print(f"  batch {number}: {len(batch) - len(missing)} of {len(batch)} copied", flush=True)

    copied = len(names) - len(failed)
    print(f"Copied {copied} of {len(names)} files to {shown}.", flush=True)
    if failed:
        for name in failed:
            print(f"  not copied: {name}" + (f" ({unwritable[name]})" if name in unwritable else ""))
        raise SystemExit(f"Error: {len(failed)} files could not be copied. Run the command again to retry them.")
    return copied


def remote_exists(namespace, pod, root, names):
    """The names (files or directories, relative to root) that exist in the pod."""
    result = subprocess.run(
        _exec(namespace, pod, f'cd "{root}" && while IFS= read -r f; do if [ -e "$f" ]; then echo "$f"; fi; done'),
        input="".join(f"{name}\n" for name in names).encode(), stdout=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SystemExit(f"Error: checking the files in the pod failed with exit code {result.returncode}.")
    return set(result.stdout.decode("utf-8").splitlines())


# Extract into a staging directory beside the target and move the files into place
# only after the whole archive arrived: a broken stream never leaves a truncated
# file that would later look like an existing one. Existing files are not replaced.
_UPLOAD_SCRIPT = (
    'set -e; umask 027; R="ROOT"; S="$R/.legacy_upload_$$"; mkdir -p "$S"; '
    "trap 'rm -rf \"$S\"' EXIT; "
    'tar -xf - --no-same-owner -C "$S"; cd "$S"; '
    'find . -type f | while IFS= read -r f; do f="${f#./}"; '
    'mkdir -p "$(dirname "$R/$f")"; mv -n "$f" "$R/$f"; done'
)


def _upload_member(info):
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o640
    return info


def _upload_stream(namespace, pod, root, local_root, pairs):
    """One kubectl exec tar stream of the local files into root in the pod; raises when it breaks."""
    process = subprocess.Popen(
        _exec(namespace, pod, _UPLOAD_SCRIPT.replace("ROOT", root)), stdin=subprocess.PIPE,
    )
    errors = []

    def feed():
        try:
            with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
                for local_name, remote_name in pairs:
                    archive.add(local_root / local_name, arcname=remote_name, recursive=False, filter=_upload_member)
        except OSError as error:  # A broken stream, or a local file that cannot be read.
            errors.append(error)
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    returncode = process.wait()
    writer.join()
    if returncode != 0 or errors:
        raise OSError(errors[0] if errors else f"kubectl exited with code {returncode}")


def upload_groups(namespace, pod, root, local_root, groups):
    """Upload local files (relative to local_root) to root in the pod.

    groups are lists of files that must arrive together, such as all files of a
    job: a group is never split over batches. A file is its name, or a pair
    (name relative to local_root, name relative to root) when they differ.
    Returns the number of uploaded files.
    """
    local_root = long_path(local_root)
    groups = [[(item, item) if isinstance(item, str) else tuple(item) for item in group] for group in groups]
    batches, batch, total, count = [], [], 0, 0
    for group in groups:
        size = sum((local_root / local_name).stat().st_size for local_name, _ in group)
        if batch and (total + size > BATCH_BYTES or count + len(group) > BATCH_FILES):
            batches.append(batch)
            batch, total, count = [], 0, 0
        batch.append(group)
        total += size
        count += len(group)
    if batch:
        batches.append(batch)

    def incomplete(batch):
        present = remote_exists(namespace, pod, root, [remote for group in batch for _, remote in group])
        return [group for group in batch if not all(remote in present for _, remote in group)]

    failed = []
    for number, batch in enumerate(batches, 1):
        for attempt in range(1, ATTEMPTS + 1):
            pending = incomplete(batch)
            if not pending:
                break
            try:
                _upload_stream(namespace, pod, root, local_root, [pair for group in pending for pair in group])
            except (OSError, tarfile.TarError) as error:
                print(f"  batch {number}, attempt {attempt} of {ATTEMPTS} failed: {error}", flush=True)
        missing = incomplete(batch)
        failed += missing
        print(f"  batch {number}: {len(batch) - len(missing)} of {len(batch)} uploaded", flush=True)

    uploaded = sum(len(group) for group in groups) - sum(len(group) for group in failed)
    print(f"Uploaded {uploaded} files.", flush=True)
    if failed:
        for group in failed:
            print(f"  not uploaded: {group[0][1]}" + (f" (+{len(group) - 1} more)" if len(group) > 1 else ""))
        raise SystemExit(f"Error: {len(failed)} items could not be uploaded. Run the command again to retry them.")
    return uploaded


def remote_lines(namespace, pod, root, script, names=()):
    """Run a shell script in root in the pod; names go to its stdin, one per line.

    Returns the lines of its output, for example the result of a find.
    """
    result = subprocess.run(
        _exec(namespace, pod, f'cd "{root}" && {script}'),
        input="".join(f"{name}\n" for name in names).encode(), stdout=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SystemExit(f"Error: listing the files in the pod failed with exit code {result.returncode}.")
    return result.stdout.decode("utf-8").splitlines()
