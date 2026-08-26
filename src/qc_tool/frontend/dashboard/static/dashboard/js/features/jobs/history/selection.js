/* Selection summary and bulk-action state for deletable QC jobs. */
(function (window, $) {
    "use strict";

    var history = window.QcJobHistory = window.QcJobHistory || {};

    history.createSelectionController = function ($table, openDeletion) {
        function selectedJobs() {
            return $table.bootstrapTable("getSelections");
        }

        function update() {
            var count = selectedJobs().length;
            var summary = count === 0
                ? "No jobs selected"
                : count + (count === 1
                    ? " job selected"
                    : " jobs selected");
            var actionLabel = count === 0
                ? "Delete selected"
                : "Delete selected (" + count + ")";

            $("#job-selection-summary").text(summary);
            $("[data-job-delete-label]").text(actionLabel);
            $("#btn-delete-multi").prop("disabled", count === 0);
        }

        function openSelected() {
            var jobUuids = selectedJobs().map(function (row) {
                return row.job_uuid;
            });

            if (!jobUuids.length) {
                update();
                return;
            }
            openDeletion(jobUuids);
        }

        function bind() {
            $table.on(
                "check.bs.table check-all.bs.table " +
                "uncheck.bs.table uncheck-all.bs.table load-success.bs.table",
                update
            );
            $("#btn-delete-multi").on("click", openSelected);
            update();
        }

        return {bind: bind, update: update};
    };
}(window, window.jQuery));
