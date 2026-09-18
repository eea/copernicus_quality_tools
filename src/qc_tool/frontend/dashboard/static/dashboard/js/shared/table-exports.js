/* Export filtered rows with the complete data schema, independent of display. */
(function (window, $) {
    "use strict";

    var nextMenuId = 0;

    function exportConfig() {
        var element = window.document.getElementById("qc-table-export-config");
        var config = element ? JSON.parse(element.textContent) : null;
        if (!config || !Array.isArray(config.formats) || !config.formats.length) {
            throw new Error("Export settings are unavailable. Refresh this page and try again.");
        }
        return config;
    }

    function sameOriginUrl(value) {
        var url = new window.URL(value, window.location.href);
        if (url.origin !== new window.URL(window.location.href).origin) {
            throw new Error("The export address must belong to QC Tool.");
        }
        return url;
    }

    function asTable(table) {
        return table && table.jquery ? table : $(table);
    }

    function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, function (character) {
            return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character];
        });
    }

    function htmlText(value) {
        // Template content is inert: extracting display text must not execute
        // scripts or load resources embedded in an HTML-backed table cell.
        var template = window.document.createElement("template");
        template.innerHTML = String(value);
        return template.content.textContent.replace(/\s+/g, " ").trim();
    }

    function columnOption(column, name) {
        var attribute = "data-" + name.replace(/[A-Z]/g, function (letter) {
            return "-" + letter.toLowerCase();
        });
        return column[name] === undefined ? column[attribute] : column[name];
    }

    function allColumns(table) {
        var options = asTable(table).bootstrapTable("getOptions") || {};
        // The table's declared schema retains hidden columns and their order.
        // Flatten header rows, omitting group headings and UI-only controls.
        return (options.columns || []).flat().filter(function (column) {
            var field = column.field;
            var exportable = columnOption(column, "exportable");
            return field !== undefined && field !== null && String(field) !== "" &&
                !(column.colspan > 1) && !column.checkbox && !column.radio && exportable !== false && exportable !== "false" &&
                ["action", "actions", "operate", "operations"].indexOf(String(field)) < 0;
        });
    }

    function columnField(column) {
        var alias = columnOption(column, "exportField");
        return String(alias === undefined ? column.field : alias);
    }

    function rowValue(row, column, settings) {
        var value = row[columnField(column)];
        var exportHtml = columnOption(column, "exportHtml");
        var configuredValue = settings.values && Object.prototype.hasOwnProperty.call(settings.values, column.field)
            ? settings.values[column.field] : null;
        var projected = typeof configuredValue === "function" || typeof column.exportValue === "function";
        if (typeof configuredValue === "function") {
            value = configuredValue(value, row, column);
        } else if (typeof column.exportValue === "function") {
            value = column.exportValue(value, row, column);
        }
        if (value === null || value === undefined) {
            return null;
        }
        // Data is plain by default; a filename such as '<report>.zip' is data,
        // even when other columns in the same table contain rendered HTML.
        if (!projected && typeof value === "string" && (exportHtml === true || exportHtml === "true" ||
                (settings.htmlFields || []).indexOf(String(column.field)) >= 0)) {
            return htmlText(value);
        }
        return value;
    }

    function fileName(settings, format) {
        return String(settings.filename || "table").replace(/\.(csv|json|xlsx|xml)$/i, "") + "." + format;
    }

    function download(blob, filename) {
        var url = window.URL.createObjectURL(blob);
        var link = window.document.createElement("a");
        link.href = url;
        link.download = filename;
        link.hidden = true;
        window.document.body.appendChild(link);
        try {
            link.click();
        } finally {
            link.remove();
            window.setTimeout(function () { window.URL.revokeObjectURL(url); }, 0);
        }
    }

    function serverUrl(format, settings) {
        var server = settings.server;
        var query = typeof server.getQuery === "function" ? server.getQuery() : {};
        var url = sameOriginUrl(server.url);
        Object.keys(query || {}).forEach(function (key) {
            if (query[key] !== undefined && query[key] !== null) {
                url.searchParams.set(key, String(query[key]));
            }
        });
        // The provider owns the full authorized schema and filtered result.
        // Display preferences must never restrict exported rows or columns.
        ["offset", "limit", "pageNumber", "pageSize", "columns"].forEach(function (key) {
            url.searchParams.delete(key);
        });
        url.searchParams.set("format", format);
        return url.href;
    }

    async function responseError(response) {
        var message;
        try {
            var payload = await response.json();
            message = payload.error || payload.message;
        } catch (_error) {
            // HTML error pages and proxies do not provide a JSON message.
        }
        if (typeof message !== "string" || !message.trim()) {
            if (response.status === 401 || response.status === 403) {
                message = "Your session could not be verified. Refresh this page and sign in again if needed.";
            } else if (response.status === 413) {
                message = "This export is too large. Narrow the table filters and try again.";
            } else {
                message = "The server could not create the export. Try again.";
            }
        }
        return new Error(message);
    }

    async function exportFile(table, format, settings) {
        var $table = asTable(table);
        var config = settings || {};
        var shared = exportConfig();
        var columns = allColumns($table);
        var options = $table.bootstrapTable("getOptions") || {};
        var rows;
        var url;
        var token;
        var response;
        if (!shared.formats.some(function (entry) { return entry.value === format; })) {
            throw new Error("This table does not support the selected export format.");
        }
        if (config.server && config.server.url) {
            url = serverUrl(format, config);
            window.location.assign(url);
            return url;
        }
        if (options.sidePagination === "server") {
            throw new Error("A server export is required to download all matching rows.");
        }
        if (!columns.length) {
            throw new Error("This table has no exportable data columns.");
        }
        if (!shared.url) {
            throw new Error("Export settings are unavailable. Refresh this page and try again.");
        }
        url = sameOriginUrl(shared.url);
        token = window.qcCsrf && window.qcCsrf.getToken();
        if (!token) {
            throw new Error("Your session could not be verified. Refresh this page before exporting.");
        }

        rows = $table.bootstrapTable("getData", {useCurrentPage: false}) || [];
        // Every format uses the application serializers. Transport raw typed
        // values here; quoting, formula protection and document structure have
        // one implementation shared with server-paginated exports.
        var body = JSON.stringify({
            format: format,
            filename: fileName(config, format),
            columns: columns.map(function (column) {
                return {field: columnField(column), label: htmlText(column.title || column.field)};
            }),
            rows: rows.map(function (row) {
                var record = Object.create(null);
                columns.forEach(function (column) {
                    record[columnField(column)] = rowValue(row, column, config);
                });
                return record;
            })
        });
        try {
            response = await window.fetch(url.href, {
                method: "POST",
                credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": token},
                body: body
            });
        } catch (_error) {
            throw new Error("The server could not be reached. Check your connection and try again.");
        }
        if (!response.ok) {
            throw await responseError(response);
        }
        if (response.redirected || /text\/html/i.test(response.headers.get("Content-Type") || "")) {
            throw new Error("Your session could not be verified. Refresh this page and sign in again if needed.");
        }
        download(await response.blob(), fileName(config, format));
        return rows.length;
    }

    function exportError(container, error) {
        var message = container.querySelector(".qc-data-table__export-error");
        if (!message && error) {
            message = window.document.createElement("div");
            message.className = "alert alert-danger qc-data-table__export-error";
            message.setAttribute("role", "alert");
            container.appendChild(message);
        }
        if (message) {
            message.textContent = error ? "Export could not be created. " + error.message : "";
            message.hidden = !error;
        }
    }

    function setBusy(container, busy) {
        container.qcTableExportBusy = busy;
        var control = container.querySelector("[data-qc-table-export]");
        if (control) {
            control.disabled = busy;
            control.setAttribute("aria-busy", String(busy));
            var label = control.querySelector(".qc-data-table__export-label");
            if (label) {
                label.textContent = busy ? "Creating export…" : "Export";
            }
        }
    }

    function button(table, settings) {
        var $table = asTable(table);
        var config = settings || {};
        var shared = exportConfig();
        var formats = shared.formats;
        var id = "qc-table-export-" + (++nextMenuId);
        var label = config.label || "Export filtered rows";
        return {
            html: function () {
                var container = $table[0].closest(".bootstrap-table");
                if (container) {
                    // Bootstrap Table rebuilds toolbars on column/options
                    // changes. Replace the one delegated listener each time.
                    if (container.qcTableExportClick) {
                        container.removeEventListener("click", container.qcTableExportClick);
                    }
                    container.qcTableExportClick = async function (event) {
                        var item = event.target.closest("[data-qc-export-format]");
                        var format;
                        if (!item || item.closest(".bootstrap-table") !== container) {
                            return;
                        }
                        event.preventDefault();
                        if (container.qcTableExportBusy) {
                            return;
                        }
                        format = item.getAttribute("data-qc-export-format");
                        if (!formats.some(function (entry) { return entry.value === format; })) {
                            return;
                        }
                        exportError(container, null);
                        setBusy(container, true);
                        try {
                            await exportFile($table, format, config);
                        } catch (error) {
                            exportError(container, error);
                            if (typeof config.onError === "function") {
                                config.onError(error);
                            }
                        } finally {
                            setBusy(container, false);
                            var control = container.querySelector("[data-qc-table-export]");
                            if (control) {
                                control.focus();
                            }
                        }
                    };
                    container.addEventListener("click", container.qcTableExportClick);
                }
                return '<div class="btn-group qc-data-table__export">' +
                    '<button type="button" class="btn btn-default dropdown-toggle qc-data-table__control--icon" data-toggle="dropdown" ' +
                    'data-qc-table-export="true" aria-haspopup="true" aria-expanded="false" ' +
                    (container && container.qcTableExportBusy ? 'disabled aria-busy="true" ' : '') +
                    'id="' + id + '" aria-label="' + escapeHtml(label) + '" title="' + escapeHtml(label) + '">' +
                    '<svg class="ui-icon qc-data-table__export-icon" aria-hidden="true" focusable="false"><use href="' +
                    escapeHtml(shared.iconSprite + "#export") + '"></use></svg> ' +
                    '<span class="sr-only qc-data-table__export-label" aria-live="polite">' +
                    (container && container.qcTableExportBusy ? "Creating export…" : "Export") + '</span> ' +
                    '</button>' +
                    '<ul class="dropdown-menu dropdown-menu-right" role="menu" aria-labelledby="' + id + '">' +
                    formats.map(function (format) {
                        return '<li role="presentation"><a href="#" role="menuitem" data-qc-export-format="' +
                            escapeHtml(format.value) + '">' + escapeHtml(format.label) + '</a></li>';
                    }).join("") + '</ul></div>';
            }
        };
    }

    window.QcTableExports = {
        button: button,
        exportFile: exportFile,
        allColumns: allColumns
    };
}(window, window.jQuery));
