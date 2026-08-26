/* Compose the focused job-history table and optional destructive workflow. */
(function (window, $) {
    "use strict";

    var history = window.QcJobHistory = window.QcJobHistory || {};
    var config = window.QC_JOB_HISTORY_CONFIG || {};

    $(function () {
        var $table = history.createTable();
        var deletion;
        var selection;

        if (!config.canDeleteJobs) {
            return;
        }
        deletion = history.createDeletionController($table);
        selection = history.createSelectionController(
            $table,
            deletion.open
        );
        deletion.bind();
        selection.bind();
    });
}(window, window.jQuery));
