/* Accessible confirmation and server-backed deletion of selected QC jobs. */
(function (window, $) {
    "use strict";

    var history = window.QcJobHistory = window.QcJobHistory || {};
    var config = window.QC_JOB_HISTORY_CONFIG || {};

    history.createDeletionController = function ($table) {
        var pendingJobUuids = [];

        function showError(message) {
            $("#job-history-delete-error")
                .text(String(message))
                .removeAttr("hidden");
        }

        function errorMessage(xhr) {
            if (xhr.responseJSON && xhr.responseJSON.message) {
                return String(xhr.responseJSON.message);
            }
            return "The selected job history could not be deleted. " +
                "Please try again.";
        }

        function populateJobList(jobUuids) {
            var visibleJobs = jobUuids.slice(0, 10);
            var omittedCount = jobUuids.length - visibleJobs.length;
            var $list = $("#confirm-delete-jobs").empty();

            visibleJobs.forEach(function (jobUuid) {
                $("<li>", {text: String(jobUuid)}).appendTo($list);
            });
            if (omittedCount > 0) {
                $("<li>", {
                    text: "and " + omittedCount + " more " +
                        (omittedCount === 1 ? "job" : "jobs")
                }).appendTo($list);
            }
        }

        function open(jobUuids) {
            var title;

            pendingJobUuids = jobUuids.slice();
            title = pendingJobUuids.length === 1
                ? "Delete selected QC job?"
                : "Delete " + pendingJobUuids.length +
                    " selected QC jobs?";
            $("#confirm-delete-title").text(title);
            $("#job-history-delete-error").attr("hidden", true).empty();
            populateJobList(pendingJobUuids);
            $("#confirm-delete").modal("show");
        }

        function deletePendingJobs() {
            var $button = $("#confirm-delete-button");
            var $label = $button.find("span");
            var deletedCount = pendingJobUuids.length;

            if (!deletedCount) {
                showError("Select at least one QC job to delete.");
                return;
            }
            $button.prop("disabled", true);
            $label.text("Deleting…");
            $("#job-history-delete-error").attr("hidden", true).empty();

            $.ajax({
                type: "POST",
                url: config.deleteUrl,
                data: {uuids: pendingJobUuids.join(",")},
                dataType: "json"
            }).done(function (result) {
                if (result.status === "error") {
                    showError(
                        result.message ||
                        "The selected jobs could not be deleted."
                    );
                    return;
                }
                $("#confirm-delete").modal("hide");
                $("#job-history-live-status").text(
                    deletedCount === 1
                        ? "One QC job was deleted."
                        : deletedCount + " QC jobs were deleted."
                );
                pendingJobUuids = [];
                $table.bootstrapTable("refresh");
            }).fail(function (xhr) {
                showError(errorMessage(xhr));
            }).always(function () {
                $button.prop("disabled", false);
                $label.text("Delete jobs");
            });
        }

        function bind() {
            $("#confirm-delete-button").on("click", deletePendingJobs);
            $("#confirm-delete").on("hidden.bs.modal", function () {
                pendingJobUuids = [];
                $("#job-history-delete-error").attr("hidden", true).empty();
            });
        }

        return {bind: bind, open: open};
    };
}(window, window.jQuery));
