"""A full package records every optional section decision explicitly."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from qc_tool.database.transfers import components
from qc_tool.database.transfers.archive import ArtifactSource, canonical_json, inspect_archive, write_archive
from qc_tool.database.transfers.errors import TransferError


class BackupSelectionEvidenceTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))

    def document(self, selected=()):
        rows = [{"key": key, "label": components.COMPONENT_LABELS[key], "selected": key in selected,
                 "status": "empty" if key in selected else "omitted", "files_count": 0, "byte_count": 0}
                for key in components.EXPORT_COMPONENTS]
        return {"format": "qc-tool-backup-selection", "version": 1,
                "selected_components": list(selected),
                "omitted_components": [key for key in components.EXPORT_COMPONENTS if key not in selected],
                "components": rows}

    def package(self, document, extra=(), storage=None):
        source = self.root / "selection.json"
        source.write_bytes(canonical_json(document))
        sources = [ArtifactSource("database", "metadata/selection.json", source)]
        for index, key in enumerate(extra):
            path = self.root / ("extra-" + str(index))
            path.write_bytes(b"retained metadata")
            sources.append(ArtifactSource("database", key, path))
        archive = self.root / "package.zip"
        write_archive(archive, {}, {}, sources, storage=storage)
        return inspect_archive(archive)

    def test_explicit_empty_selection_roundtrips(self):
        components.validate(self.package(self.document()))

    def test_omitted_and_selected_components_must_partition_all_choices(self):
        document = self.document()
        document["omitted_components"].pop()
        with self.assertRaisesMessage(TransferError, "inconsistent"):
            components.validate(self.package(document))

    def test_selected_globals_must_have_the_sql_section(self):
        with self.assertRaisesMessage(TransferError, "disagree"):
            components.validate(self.package(self.document(["postgresql_globals"])))

    def test_omitted_globals_cannot_be_included_silently(self):
        with self.assertRaisesMessage(TransferError, "disagree"):
            components.validate(self.package(self.document(), extra=["metadata/globals.sql"]))

    def test_file_component_decisions_must_match_storage_inventory(self):
        with self.assertRaisesMessage(TransferError, "selected backup files"):
            components.validate(self.package(self.document(["boundaries"]), storage={
                "recovery_files": {"version": 2, "selected_components": []}}))

