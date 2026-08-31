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
        },
        formatExport: function () {
            return "Export";
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
                "refresh-options.bs.table.qcDataTableUi",
                function () {
                    enhanceControls($table, resolvedLabels);
                }
            );
            enhanceControls($table, resolvedLabels);
        });
        return $tables;
    }

    window.QcDataTableUi = {
        options: options,
        exportButton: exportButton,
        enhance: enhance
    };
}(window, window.jQuery));
