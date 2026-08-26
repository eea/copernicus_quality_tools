/* Remote-table lifecycle, feedback, and generated-control accessibility. */
(function (window, $) {
    "use strict";

    var history = window.QcJobHistory = window.QcJobHistory || {};
    var config = window.QC_JOB_HISTORY_CONFIG || {};

    function labelControls($table) {
        var $container = $table.closest(".bootstrap-table");

        $container.find(".search input").attr({
            "aria-label": "Search QC job history",
            placeholder: "Search jobs"
        });
        $container.find("button[name='refresh']").attr(
            "aria-label",
            "Refresh QC job history"
        );
        $container.find("button[name='columns']").attr(
            "aria-label",
            "Choose visible job columns"
        );
        $container.find("button[data-type='json']").attr(
            "aria-label",
            "Export QC job history"
        );
    }

    function loadSucceeded($table, rows) {
        var count = Array.isArray(rows) ? rows.length : 0;

        $("#job-history-load-error").attr("hidden", true);
        $("#job-history-live-status").text(
            count === 1 ? "One QC job loaded." : count + " QC jobs loaded."
        );
        labelControls($table);
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
            loadSucceeded($table, rows);
        });
        $table.on("load-error.bs.table", loadFailed);
        $table.on("post-header.bs.table", function () {
            labelControls($table);
        });
        $table.bootstrapTable({
            cache: false,
            striped: false,
            search: true,
            pagination: true,
            showColumns: true,
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
        });
        return $table;
    };
}(window, window.jQuery));
