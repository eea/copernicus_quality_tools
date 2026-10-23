"""Follow selection at connection/cursor boundaries without splitting a transaction."""

from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLWrapper


class DatabaseWrapper(PostgreSQLWrapper):
    def _selected_database(self):
        from qc_tool.database import selection

        if (self.alias != "default"
                or self.settings_dict.get("NAME") != selection.configured_connection().get("NAME")):
            return self.settings_dict.get("NAME")
        if self.connection is not None and (self.in_atomic_block or not self.autocommit):
            return getattr(self, "_qc_connected_database", self.settings_dict.get("NAME"))
        return selection.current_database()

    def ensure_connection(self):
        if (self.alias == "default" and self.connection is not None
                and getattr(self, "_qc_connected_database", self.settings_dict.get("NAME")) != self._selected_database()
                and not self.in_atomic_block and self.autocommit):
            self.close()
        return super().ensure_connection()

    def get_connection_params(self):
        params = super().get_connection_params()
        if self.alias == "default":
            params["dbname"] = self._selected_database()
        return params

    def get_new_connection(self, conn_params):
        connection = super().get_new_connection(conn_params)
        self._qc_connected_database = conn_params.get("dbname")
        return connection
