/* Bounded QC polling and review updates for the visible delivery page. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
    var placeholderUuid = "00000000-0000-0000-0000-000000000000";
    var maxJobsPerPoll = 20;
    var pollInProgress = false;
    var pollCursor = 0;
    var timer = null;

    function isActive(row) {
        return Boolean(
            row.last_job_uuid &&
            (row.last_job_status === "waiting" || row.last_job_status === "running")
        );
    }

    function updateUrl(jobUuid) {
        return String(config.updateJobUrlTemplate || "").replace(
            placeholderUuid,
            encodeURIComponent(String(jobUuid))
        );
    }

    function refreshWorkflow() {
        var table = window.QcDeliveryTable;
        // QC and reviews can move deliveries in from another workflow stage.
        // Refresh even when the current view has no running or pending rows.
        // Preserve selections and keyboard focus while a user acts on a row.
        if (document.hidden || (!config.submissionEnabled && !config.updateJobStatuses) || table.selectedRows().length ||
            (document.activeElement && document.activeElement.closest("#tbl-deliveries"))) {
            return;
        }
        table.refresh({
            silent: true,
            pageNumber: $("#tbl-deliveries").bootstrapTable("getOptions").pageNumber
        });
        return true;
    }

    function poll() {
        var activeRows;
        var batch;
        var remaining;
        var statusChanged = false;

        if (pollInProgress || document.hidden || !window.QcDeliveryTable) {
            return;
        }
        activeRows = config.updateJobStatuses ? window.QcDeliveryTable.rows().filter(isActive) : [];
        if (!activeRows.length) {
            pollCursor = 0;
            refreshWorkflow();
            return;
        }

        pollCursor %= activeRows.length;
        batch = activeRows.slice(pollCursor, pollCursor + maxJobsPerPoll);
        if (batch.length < Math.min(maxJobsPerPoll, activeRows.length)) {
            batch = batch.concat(
                activeRows.slice(0, Math.min(maxJobsPerPoll - batch.length, activeRows.length))
            );
        }
        pollCursor = (pollCursor + batch.length) % activeRows.length;

        pollInProgress = true;
        remaining = batch.length;
        batch.forEach(function (row) {
            $.ajax({
                type: "POST",
                url: updateUrl(row.last_job_uuid),
                dataType: "json"
            }).done(function (updated) {
                if (updated && updated.last_job_status !== row.last_job_status) {
                    statusChanged = true;
                }
            }).always(function () {
                remaining -= 1;
                if (remaining !== 0) {
                    return;
                }
                pollInProgress = false;
                if (refreshWorkflow() && statusChanged) {
                    window.QcDeliveryTable.announce(
                        "A QC job status changed. Deliveries refreshed."
                    );
                }
            });
        });
    }

    function init() {
        if (!config.updateJobStatuses && !config.submissionEnabled) {
            return;
        }
        $("#tbl-deliveries").one("load-success.bs.table", poll);
        timer = window.setInterval(poll, Math.max(Number(config.updateInterval) || 30000, 5000));
        $(window).on("beforeunload.qcDeliveryPolling", function () {
            window.clearInterval(timer);
        });
    }

    window.QcDeliveryPolling = {init: init, poll: poll};
}(window, window.jQuery));
