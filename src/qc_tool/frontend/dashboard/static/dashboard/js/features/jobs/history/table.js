/* Remote-table lifecycle, feedback, and generated-control accessibility. */
(function (window, $) {
    "use strict";

    var history = window.QcJobHistory = window.QcJobHistory || {};
    var config = window.QC_JOB_HISTORY_CONFIG || {};
    var dataTableUi = window.QcDataTableUi;

    function enhanceTable($table) {
        dataTableUi.enhance($table, {
            subject: "QC job history",
            region: "QC job history table",
            controls: "QC job history display and export controls",
            columns: "Choose visible job columns",
            export: "Export QC job history",
            search: "Search QC job history",
            refresh: "Refresh QC job history",
            toggleAll: "Show or hide all optional job columns"
        });
    }

    function loadSucceeded(rows) {
        var count = Array.isArray(rows) ? rows.length : 0;

        $("#job-history-load-error").attr("hidden", true);
        $("#job-history-live-status").text(
            count === 1 ? "One QC job loaded." : count + " QC jobs loaded."
        );
    }

    function loadFailed() {
        $("#job-history-load-error").removeAttr("hidden");
        $("#job-history-live-status").text(
            "Job history could not be loaded."
        );
    }

    function exportButton($table) {
        return dataTableUi.csvExportButton($table, {
            filename: "qc-job-history.csv",
            label: "Export filtered QC job history as CSV"
        });
    }

    history.createTable = function () {
        var $table = $("#tbl-history");

        $table.on("load-success.bs.table", function (event, rows) {
            loadSucceeded(rows);
        });
        $table.on("load-error.bs.table", loadFailed);
        $table.bootstrapTable(dataTableUi.options({
            cache: false,
            striped: false,
            search: true,
            pagination: true,
            showRefresh: true,
            buttons: function () {
                return {exportView: exportButton($table)};
            },
            buttonsOrder: ["refresh", "columns", "exportView"],
            sortName: "date_created",
            sortOrder: "desc",
            url: config.historyUrl,
            pageSize: 20,
            pageList: [20, 50, 100, 500],
            formatLoadingMessage: function () {
                return "Loading QC job history…";
            },
            formatNoMatches: function () {
                return "No QC jobs have been recorded for this delivery yet.";
            }
        }));
        enhanceTable($table);
        return $table;
    };
}(window, window.jQuery));
