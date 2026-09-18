/* Shared Bootstrap Table options and generated-control accessibility. */
(function (window, $) {
    "use strict";

    var commonOptions = {
        showColumns: true,
        showButtonText: false,
        showColumnsToggleAll: true,
        minimumCountColumns: 1,
        buttonsAlign: "right",
        formatColumns: function () {
            return "Columns";
        },
        formatColumnsToggleAll: function () {
            return "All columns";
        }
    };

    function options(overrides) {
        return $.extend(true, {}, commonOptions, overrides || {});
    }

    function exportMenu(table, settings) {
        return window.QcTableExports.button(table, settings);
    }

    // Programmatic CSV compatibility; all menu callers share the full registry.
    function exportCsv(table, settings) {
        return window.QcTableExports.exportFile(table, "csv", settings);
    }

    function csvExportButton(table, settings) {
        return exportMenu(table, settings);
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

    function controlContent($control, symbol, text, dropdown) {
        if (!$control.length || $control.attr("data-qc-control-icon") === symbol) return;
        var configuration = window.document.getElementById("qc-table-export-config");
        var sprite = configuration ? JSON.parse(configuration.textContent).iconSprite : "";
        // Keep the original button and its plugin event handlers in place.
        function icon(name, className) {
            var svg = window.document.createElementNS("http://www.w3.org/2000/svg", "svg");
            var use = window.document.createElementNS("http://www.w3.org/2000/svg", "use");
            svg.setAttribute("class", "ui-icon" + (className ? " " + className : ""));
            svg.setAttribute("aria-hidden", "true");
            svg.setAttribute("focusable", "false");
            use.setAttribute("href", String(sprite || "") + "#" + name);
            svg.appendChild(use);
            return svg;
        }
        $control.empty().append(icon(symbol)).attr("data-qc-control-icon", symbol);
        if (text) $control.append($("<span>", {text: text}));
        if (dropdown) $control.append(icon("chevron-down", "qc-data-table__control-chevron"));
        $control.addClass(text ? "qc-data-table__control--columns" : "qc-data-table__control--icon");
    }

    function syncColumnSelection($toolbar) {
        var $columns = $toolbar.find(".keep-open input[data-field]");
        var checked = $columns.filter(":checked").length;
        // Fixed action columns are absent from the chooser and must not skew
        // the native plugin's calculation of the select-all checkbox state.
        $toolbar.find(".keep-open input.toggle-all")
            .prop("checked", $columns.length > 0 && checked === $columns.length)
            .prop("indeterminate", checked > 0 && checked < $columns.length);
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
        // Menus belong outside the scrolling table body. Mark enclosing cards
        // too, so their rounded surfaces cannot clip the native dropdowns.
        $container.parents(".workspace-card").addClass("qc-data-table-card");
        $toolbar = $container.find(".fixed-table-toolbar").first();
        if (!$toolbar.length) {
            return;
        }
        $toolbar.toggleClass(
            "qc-data-table__toolbar--custom",
            $toolbar.find("[data-table-filter-toolbar]").length > 0
        );

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
        controlContent($columnButton, "columns", "Columns", true);
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
        controlContent($refreshButton, "refresh");
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
                "Show or hide all " + subject + " columns"
            )
        );
        $toolbar.find(".keep-open input[data-field]").each(function () {
            var $input = $(this);
            var columnName = $.trim($input.siblings("span").first().text()) ||
                String($input.attr("data-field") || "table");
            $input.attr("aria-label", "Show or hide the " + columnName + " column");
        });
        $toolbar.off("change.qcDataTableColumns").on(
            "change.qcDataTableColumns",
            ".keep-open input[type='checkbox']",
            function () { syncColumnSelection($toolbar); }
        );
        syncColumnSelection($toolbar);
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

    function create(table, settings) {
        var $table = table && table.jquery ? table : $(table);
        var config = settings || {};
        var resolved = options(config.options);
        var originalButtons = resolved.buttons;

        if (config.exports) {
            resolved.buttons = function () {
                var buttons = typeof originalButtons === "function"
                    ? originalButtons.apply(this, arguments) : originalButtons;
                return $.extend({}, buttons || {}, {exportView: exportMenu($table, config.exports)});
            };
            resolved.buttonsOrder = (resolved.buttonsOrder || ["refresh", "columns"]).slice();
            if (resolved.buttonsOrder.indexOf("exportView") < 0) resolved.buttonsOrder.push("exportView");
        }
        $table.bootstrapTable(resolved);
        enhance($table, config.labels);
        return $table;
    }

    window.QcDataTableUi = {
        create: create,
        options: options,
        exportMenu: exportMenu,
        exportCsv: exportCsv,
        csvExportButton: csvExportButton,
        enhance: enhance
    };
}(window, window.jQuery));
