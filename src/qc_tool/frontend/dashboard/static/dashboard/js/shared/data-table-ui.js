/* Shared Bootstrap Table options and generated-control accessibility. */
(function (window, $) {
    "use strict";

    var commonOptions = {
        showColumns: true,
        showButtonText: true,
        showColumnsToggleAll: true,
        minimumCountColumns: 0,
        buttonsAlign: "right",
        formatColumns: function () {
            return "Columns";
        },
        formatColumnsToggleAll: function () {
            return "All optional columns";
        }
    };

    function options(overrides) {
        return $.extend(true, {}, commonOptions, overrides || {});
    }

    function exportButton(settings) {
        var config = settings || {};
        var text = config.text || "Export";
        var label = config.label || text;
        var attributes = $.extend({}, {
            "aria-label": label,
            title: config.title || label,
            "data-qc-table-export": "true"
        }, config.attributes || {});
        var button = {
            text: text,
            icon: config.icon === undefined ? "glyphicon-export icon-share" : config.icon,
            event: config.event || function () {},
            attributes: attributes
        };

        if (config.className) {
            button.attributes.class = config.className;
        }
        if (config.render !== undefined) {
            button.render = config.render;
        }
        return button;
    }

    function exportText(value) {
        var text;

        if (value === undefined || value === null) {
            return "";
        }
        if (typeof value === "object") {
            try {
                value = JSON.stringify(value);
            } catch (error) {
                value = String(value);
            }
        }
        text = $("<div>").html(String(value)).text();
        return $.trim(text).replace(/\s+/g, " ");
    }

    function csvCell(value) {
        var text = exportText(value);

        if (/^[\t\r\n ]*[=+\-@]/.test(text)) {
            text = "'" + text;
        }
        return '"' + text.replace(/"/g, '""') + '"';
    }

    function exportCsv(table, settings) {
        var $table = table && table.jquery ? table : $(table);
        var config = settings || {};
        var columns = ($table.bootstrapTable("getVisibleColumns") || [])
            .filter(function (column) {
                return Boolean(column.field);
            });
        var rows = $table.bootstrapTable("getData", {formatted: true}) || [];
        var lines = [columns.map(function (column) {
            return csvCell(column.title);
        }).join(",")];
        var blob;
        var downloadUrl;
        var link;

        rows.forEach(function (row) {
            lines.push(columns.map(function (column) {
                return csvCell(row[column.field]);
            }).join(","));
        });
        blob = new window.Blob(
            ["\ufeff", lines.join("\r\n")],
            {type: "text/csv;charset=utf-8"}
        );
        downloadUrl = window.URL.createObjectURL(blob);
        link = window.document.createElement("a");
        link.href = downloadUrl;
        link.download = config.filename || "table.csv";
        link.hidden = true;
        window.document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(function () {
            window.URL.revokeObjectURL(downloadUrl);
        }, 0);
        return rows.length;
    }

    function csvExportButton(table, settings) {
        var config = settings || {};

        return exportButton({
            text: config.text || "Export",
            label: config.label || "Export table as CSV",
            title: config.title || config.label || "Export table as CSV",
            event: function () {
                exportCsv(table, config);
            }
        });
    }

    function labelValue(labels, name, fallback) {
        var value = labels && labels[name];
        return typeof value === "string" && $.trim(value) ? value : fallback;
    }

    function controlAttributes($controls, label, tableId) {
        var attributes = {
            "aria-label": label,
            title: label
        };

        if (tableId) {
            attributes["aria-controls"] = tableId;
        }
        $controls.attr(attributes).addClass("qc-data-table__control");
        $controls.find(".glyphicon, .fa, .bi").attr("aria-hidden", "true");
    }

    function enhanceControls($table, labels) {
        var $container = $table.closest(".bootstrap-table");
        var $toolbar;
        var $columnButton;
        var $exportButtons;
        var $refreshButton;
        var $searchInput;
        var subject;
        var tableId;

        if (!$container.length) {
            return;
        }

        subject = labelValue(labels, "subject", "table");
        tableId = $table.attr("id") || "";
        $container.addClass("qc-data-table");
        $toolbar = $container.find(".fixed-table-toolbar").first();
        if (!$toolbar.length) {
            return;
        }

        $toolbar.children(".columns").attr({
            role: "group",
            "aria-label": labelValue(
                labels,
                "controls",
                subject + " display and export controls"
            )
        });

        $columnButton = $toolbar.find(
            ".keep-open > button.dropdown-toggle, button[name='columns']"
        ).first();
        controlAttributes(
            $columnButton,
            labelValue(labels, "columns", "Choose visible " + subject + " columns"),
            tableId
        );
        $columnButton.attr("aria-haspopup", "true");
        if ($columnButton.attr("aria-expanded") === undefined) {
            $columnButton.attr("aria-expanded", "false");
        }

        $exportButtons = $toolbar.find(
            ".export > button, button[data-qc-table-export='true']"
        );
        controlAttributes(
            $exportButtons,
            labelValue(labels, "export", "Export " + subject),
            tableId
        );

        $refreshButton = $toolbar.find("button[name='refresh']");
        controlAttributes(
            $refreshButton,
            labelValue(labels, "refresh", "Refresh " + subject),
            tableId
        );

        $searchInput = $toolbar.find(".search input").first();
        if ($searchInput.length) {
            $searchInput.attr(
                "aria-label",
                labelValue(labels, "search", "Search " + subject)
            );
            if (!$searchInput.attr("placeholder")) {
                $searchInput.attr(
                    "placeholder",
                    labelValue(labels, "search", "Search " + subject)
                );
            }
        }

        $toolbar.find(".keep-open input.toggle-all").attr(
            "aria-label",
            labelValue(
                labels,
                "toggleAll",
                "Show or hide all optional " + subject + " columns"
            )
        );
        $toolbar.find(".keep-open input[data-field]").each(function () {
            var $input = $(this);
            var columnName = $.trim($input.siblings("span").first().text()) ||
                String($input.attr("data-field") || "table");
            $input.attr("aria-label", "Show or hide the " + columnName + " column");
        });
    }

    function enhanceSortControls($table) {
        var tableOptions = $table.bootstrapTable("getOptions") || {};

        $table.find("thead th").removeAttr("aria-sort");
        $table.find("thead .th-inner.sortable").each(function () {
            var $control = $(this);
            var $header = $control.closest("th");
            var field = $header.attr("data-field");
            var label = $.trim(
                $control.clone().children().remove().end().text()
            ) || field;

            $control.attr({
                role: "button",
                tabindex: "0",
                "aria-label": "Sort by " + label
            }).off("keydown.qcDataTableSort").on(
                "keydown.qcDataTableSort",
                function (event) {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        $(this).trigger("click");
                    }
                }
            );
            if (field === tableOptions.sortName) {
                $header.attr(
                    "aria-sort",
                    tableOptions.sortOrder === "asc"
                        ? "ascending"
                        : "descending"
                );
            }
        });
    }

    function enhanceScrollRegion($table, labels) {
        var $container = $table.closest(".bootstrap-table");
        var $scrollRegion = $container.find(".fixed-table-body").first();
        var labelledBy = labels && labels.regionLabelledBy;

        if (!$scrollRegion.length) {
            return;
        }
        $scrollRegion.attr({
            role: "region",
            tabindex: "0"
        });
        if (labelledBy) {
            $scrollRegion
                .attr("aria-labelledby", labelledBy)
                .removeAttr("aria-label");
        } else {
            $scrollRegion
                .attr(
                    "aria-label",
                    labelValue(
                        labels,
                        "region",
                        labelValue(labels, "subject", "Data") + " table"
                    )
                )
                .removeAttr("aria-labelledby");
        }
    }

    function enhance(table, labels) {
        var $tables = table && table.jquery ? table : $(table);
        var resolvedLabels = $.extend({}, labels || {});

        $tables.each(function () {
            var $table = $(this);

            $table.addClass("qc-data-table__table");
            $table.off(".qcDataTableUi").on(
                "post-header.bs.table.qcDataTableUi " +
                "reset-view.bs.table.qcDataTableUi " +
                "column-switch.bs.table.qcDataTableUi " +
                "column-switch-all.bs.table.qcDataTableUi " +
                "sort.bs.table.qcDataTableUi " +
                "refresh-options.bs.table.qcDataTableUi",
                function () {
                    enhanceControls($table, resolvedLabels);
                    enhanceSortControls($table);
                    enhanceScrollRegion($table, resolvedLabels);
                }
            );
            enhanceControls($table, resolvedLabels);
            enhanceSortControls($table);
            enhanceScrollRegion($table, resolvedLabels);
        });
        return $tables;
    }

    window.QcDataTableUi = {
        options: options,
        exportButton: exportButton,
        exportCsv: exportCsv,
        csvExportButton: csvExportButton,
        enhance: enhance
    };
}(window, window.jQuery));
