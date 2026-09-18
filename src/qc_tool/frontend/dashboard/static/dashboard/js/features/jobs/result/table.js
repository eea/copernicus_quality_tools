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
            labels: {
                subject: "QC check results", region: "QC check results table",
                refresh: "Reload check results", search: "Search checks and messages",
                export: "Export checks in this view"
            },
            exports: {
                filename: $table.attr("data-export-filename"),
                htmlFields: ["check_result"],
                values: {
                    step_nr: function (value) { return Number(value); },
                    check_ident: function (value) { return cellItems(value, ".job-result-check-title, .job-result-check-description, code").join(" · "); },
                    layers: function (value) { return cellItems(value, ".job-result-layer"); },
                    check_attachments: function (value) { return cellItems(value, "a"); },
                    check_message: function (value) { return cellItems(value, "li"); }
                }
            },
            options: {
                pagination: $table.find("tbody tr").length > 10,
                pageSize: 10,
                pageList: [10, 25, 50, 100],
                sidePagination: "client",
                search: true,
                searchHighlight: false,
                showRefresh: true,
                onRefresh: function () { window.location.reload(); },
                formatSearch: function () { return "Search checks and messages"; },
                formatNoMatches: function () { return "No checks match your search."; }
            }
        });
    });
}(window, window.jQuery));
