/* Check-result exports share the table menu while retaining structured lists. */
(function (window, $) {
    "use strict";

    function cellItems(value, selector) {
        var template = window.document.createElement("template");
        template.innerHTML = value || "";
        return Array.prototype.map.call(template.content.querySelectorAll(selector), function (element) {
            return element.textContent.trim();
        });
    }

    $(function () {
        var $table = $("#tbl-results");
        if (!$table.length) return;
        window.QcDataTableUi.create($table, {
            labels: {subject: "QC check results", region: "QC check results table"},
            exports: {
                filename: $table.attr("data-export-filename"),
                htmlFields: ["check_result"],
                values: {
                    step_nr: function (value) { return Number(value); },
                    check_ident: function (value) { return cellItems(value, "code, span").join(" · "); },
                    layers: function (value) { return cellItems(value, ".job-result-layer"); },
                    check_attachments: function (value) { return cellItems(value, "a"); },
                    check_message: function (value) { return cellItems(value, "li"); }
                }
            },
            options: {
                pagination: false,
                sidePagination: "client",
                search: false,
                showRefresh: false
            }
        });
    });
}(window, window.jQuery));
