"""Lightweight result contract shared by QC checks and the dispatcher."""

from qc_tool.worker.aoi import set_aoi_status_property
from qc_tool.worker.product_units import set_product_unit_status_property


class CheckStatus:
    """Mutable outcome collected while one configured QC step executes."""

    def __init__(self):
        self.status = "ok"
        self.messages = []
        self.error_table_infos = []
        self.full_table_names = []
        self.attachment_filenames = []
        self.params = {}
        self.status_properties = {}

    def aborted(self, message):
        self.messages.append(message)
        self.status = "aborted"

    def failed(self, message):
        self.messages.append(message)
        if self.status != "aborted":
            self.status = "failed"

    def cancelled(self, message):
        self.messages.append(message)
        if self.status not in ("aborted", "failed"):
            self.status = "cancelled"

    def info(self, message):
        self.messages.append(message)

    def is_aborted(self):
        return self.status == "aborted"

    def add_error_table(self, error_table_name, src_table_name, pg_fid_name):
        self.error_table_infos.append(
            (error_table_name, src_table_name, pg_fid_name)
        )

    def add_full_table(self, table_name):
        self.full_table_names.append(table_name)

    def add_attachment(self, filename):
        self.attachment_filenames.append(filename)

    def add_params(self, params_dict):
        self.params.update(params_dict)

    def set_status_property(self, key, value):
        if not set_product_unit_status_property(self, key, value) and not set_aoi_status_property(self, key, value):
            self.status_properties[key] = value

    def __repr__(self):
        members = (
            "status={:s}, messages={:s}, error_table_infos={:s}, "
            "attachment_filenames={:s}, params={:s}, status_properties={:s}"
        ).format(
            repr(self.status),
            repr(self.messages),
            repr(self.error_table_infos),
            repr(self.attachment_filenames),
            repr(self.params),
            repr(self.status_properties),
        )
        return "{:s}({:s})".format(self.__class__.__name__, members)
