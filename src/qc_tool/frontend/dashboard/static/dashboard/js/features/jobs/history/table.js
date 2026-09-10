/* Remote-table lifecycle, feedback, and generated-control accessibility. */
(function (window, $) {
    "use strict";

    var history = window.QcJobHistory = window.QcJobHistory || {};
    var config = window.QC_JOB_HISTORY_CONFIG || {};
    var dataTableUi = window.QcDataTableUi;

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

    history.createTable = function () {
        var $table = $("#tbl-history");

        $table.on("load-success.bs.table", function (event, rows) {
            loadSucceeded(rows);
        });
        $table.on("load-error.bs.table", loadFailed);
        dataTableUi.create($table, {
            labels: {subject: "QC job history", region: "QC job history table"},
            exports: {filename: "qc-job-history"},
            options: {
                cache: false,
                striped: false,
                search: true,
                pagination: true,
                showRefresh: true,
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
            }
        });
        return $table;
    };
}(window, window.jQuery));
