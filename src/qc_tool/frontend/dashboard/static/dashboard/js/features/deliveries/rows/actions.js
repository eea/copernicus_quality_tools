/* Lifecycle-ordered, permission-aware controls for one delivery row. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
    var formatters = window.QcDeliveryFormatters;

    function actionLink(cssClass, symbol, text, href, ariaLabel) {
        return formatters.appendIconText($("<a>", {
            "class": "btn delivery-row-action " + cssClass,
            href: href,
            "aria-label": ariaLabel
        }), symbol, text);
    }

    function actionButton(row, cssClass, symbol, text, ariaLabel) {
        return formatters.appendIconText($("<button>", {
            "class": "btn delivery-row-action " + cssClass,
            type: "button",
            "aria-label": ariaLabel
        }).attr({
            "data-delivery-id": String(row.id),
            "data-delivery-filename": String(row.filename || "")
        }), symbol, text);
    }

    function appendResult($container, row, filename, primary) {
        var status = String(row.delivery_status || "failed");
        var label = "View QC result";

        if (status === "failed") {
            label = "Review QC result";
        } else if (status === "running") {
            label = "View current QC job";
        }
        actionLink(
            (primary ? "btn-qc-primary" : "btn-qc-secondary") +
                " btn-qc--compact delivery-job-link",
            "history",
            label,
            String(row.job_result_url),
            label + " for " + filename
        ).appendTo($container);
    }

    function appendRun($container, row, filename) {
        var label = row.last_job_uuid ? "Run QC again" : "Run QC";
        actionLink(
            "btn-qc-success btn-qc--compact delivery-row-qc",
            "play",
            label,
            String(config.setupJobUrl || "") + "?deliveries=" +
                encodeURIComponent(String(row.id)),
            "Run quality controls for " + filename
        ).appendTo($container);
    }

    function appendSubmit($container, row, filename) {
        actionButton(
            row,
            "btn-qc-primary btn-qc--compact submit-delivery-button",
            "send",
            "Submit to EEA",
            "Submit " + filename + " to EEA"
        ).appendTo($container);
    }

    function appendDelete($container, row, filename) {
        actionButton(
            row,
            "btn-qc-danger-outline btn-qc--compact delete-button",
            "trash",
            "Delete",
            "Delete " + filename
        ).appendTo($container);
    }

    function plan(row) {
        var status = String(row.delivery_status || "failed");
        var actions = [];

        if (status === "passed" && formatters.canSubmit(row)) {
            actions.push("submit");
        }
        if (row.job_result_url && status !== "not_validated") {
            actions.push("result");
        }
        if (
            formatters.canRunQc(row) &&
            ["not_validated", "passed", "failed"].indexOf(status) >= 0
        ) {
            actions.push("run");
        }
        if (formatters.canDelete(row)) {
            actions.push("delete");
        }
        return actions;
    }

    function populate($actions, row, filename) {
        var $workflow = $("<div>", {
            "class": "delivery-row-actions__workflow"
        });
        var $destructive = $("<div>", {
            "class": "delivery-row-actions--destructive"
        });
        var actions = plan(row);

        actions.forEach(function (action, index) {
            if (action === "submit") {
                appendSubmit($workflow, row, filename);
            } else if (action === "result") {
                appendResult($workflow, row, filename, index === 0);
            } else if (action === "run") {
                appendRun($workflow, row, filename);
            } else if (action === "delete") {
                appendDelete($destructive, row, filename);
            }
        });
        if ($workflow.children().length) {
            $workflow.appendTo($actions);
        }
        if ($destructive.children().length) {
            $destructive.appendTo($actions);
        }
        return actions.length;
    }

    formatters.actionPlan = plan;
    window.QcDeliveryRowActions = {populate: populate};
}(window, window.jQuery));
