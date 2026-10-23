"""Reusable application code must not depend on QC check implementations."""

import ast
from importlib.util import resolve_name
from pathlib import Path
from unittest import TestCase


QC_TOOL_SOURCE = Path(__file__).resolve().parents[1]
SHARED_PACKAGES = ("worker", "frontend", "database", "maintenance")
CHECK_PACKAGES = ("qc_tool.vector", "qc_tool.raster")


def static_imports(path):
    """Resolve ordinary and relative imports without importing application code."""
    relative = path.relative_to(QC_TOOL_SOURCE)
    package = ".".join(("qc_tool", *relative.parts[:-1]))
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            yield node.lineno, module
            for alias in node.names:
                yield node.lineno, ".".join((module, alias.name))


class WorkerModuleBoundaryTests(TestCase):
    def test_shared_application_packages_do_not_import_qc_check_packages(self):
        violations = []
        for owner in SHARED_PACKAGES:
            for path in sorted((QC_TOOL_SOURCE / owner).rglob("*.py")):
                relative = path.relative_to(QC_TOOL_SOURCE)
                # Retained backup/research snapshots are not application modules.
                if "tests" in relative.parts or not all(
                    (QC_TOOL_SOURCE / parent / "__init__.py").is_file()
                    for parent in relative.parents
                ):
                    continue
                for line, imported in static_imports(path):
                    if any(imported == check or imported.startswith(check + ".") for check in CHECK_PACKAGES):
                        violations.append(f"{relative}:{line}: {imported}")
        self.assertEqual(
            violations,
            [],
            "Move reusable infrastructure out of raster/vector checks:\n" + "\n".join(violations),
        )
