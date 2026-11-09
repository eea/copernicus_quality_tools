"""Ask the verified worker's shared resolver for its retained artifact roles."""

import json
from pathlib import Path
import subprocess


_RESOLVE = """
import json,sys
from qc_tool.common import CONFIG
from qc_tool.jobs import read_job_context,resolve_job_paths
paths=resolve_job_paths(CONFIG['work_dir'],sys.argv[1])
context=read_job_context(paths) if paths.directory.exists() else None
filename=(context or {}).get('specification',{}).get('filename')
filename=filename or (sys.argv[2]+'.json' if paths.legacy else sys.argv[3])
roles={'directory':paths.directory,'result':paths.result_path,
       'specification':paths.specification_path(filename),'outputs':paths.output_dir}
print(json.dumps({name:path.relative_to(paths.jobs_root).as_posix() for name,path in roles.items()}))
"""


def retained_worker_paths(container, job_uuid, work_root, product_ident, source_filename):
    """Translate worker-relative roles into the isolated host evidence mount."""

    document = json.loads(subprocess.check_output([
        "docker", "exec", container, "python3", "-c", _RESOLVE,
        str(job_uuid), product_ident.lower(), source_filename,
    ], text=True))
    if not isinstance(document, dict) or set(document) != {"directory", "result", "specification", "outputs"}:
        raise ValueError("Worker artifact roles are invalid")
    root = Path(work_root)
    resolved_root = root.resolve()
    roles = {}
    for role, value in document.items():
        if not isinstance(value, str):
            raise ValueError("Worker artifact role is invalid")
        key = Path(value)
        target = root / key
        if key.is_absolute() or ".." in key.parts or not target.resolve().is_relative_to(resolved_root):
            raise ValueError("Worker artifact role escapes the evidence mount")
        roles[role] = target
    return roles
