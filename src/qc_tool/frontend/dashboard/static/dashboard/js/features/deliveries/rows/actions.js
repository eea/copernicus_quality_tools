/* Lifecycle-ordered, permission-aware controls for one delivery row. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
    var formatters = window.QcDeliveryFormatters;

    function actionClasses(primary, cssClass) {
        return (primary
            ? "btn-qc-primary delivery-row-action--primary "
            : "btn-qc-quiet delivery-row-action--secondary ") +
            "btn-qc--compact " + cssClass;
    }

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
            actionClasses(primary, "delivery-job-link"),
            "history",
            label,
            String(row.job_result_url),
            label + " for " + filename
        ).appendTo($container);
    }

    function appendRun($container, row, filename, primary) {
        var label = row.last_job_uuid ? "Run QC again" : "Run QC";
        actionLink(
            actionClasses(primary, "delivery-row-qc"),
            "play",
            label,
            String(config.setupJobUrl || "") + "?deliveries=" +
                encodeURIComponent(String(row.id)),
            "Run quality controls for " + filename
        ).appendTo($container);
    }

    function appendSubmit($container, row, filename, primary) {
        actionButton(
            row,
            actionClasses(primary, "submit-delivery-button"),
            "send",
            "Submit to EEA",
            "Submit " + filename + " to EEA"
        ).appendTo($container);
    }

    function appendDelete($container, row, filename) {
        actionButton(
            row,
            "btn-qc-quiet btn-qc--compact delivery-row-action--secondary " +
                "delivery-row-action--danger delete-button",
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
        var $primary = $("<div>", {
            "class": "delivery-row-actions__primary"
        });
        var $secondary = $("<div>", {
            "class": "delivery-row-actions__secondary"
        });
        var $destructive = $("<div>", {
            "class": "delivery-row-actions__destructive"
        });
        var actions = plan(row);
        var primaryAssigned = false;

        actions.forEach(function (action) {
            var isPrimary = action !== "delete" && !primaryAssigned;
            var $container = isPrimary ? $primary : $secondary;

            if (action === "submit") {
                appendSubmit($container, row, filename, isPrimary);
            } else if (action === "result") {
                appendResult($container, row, filename, isPrimary);
            } else if (action === "run") {
                appendRun($container, row, filename, isPrimary);
            } else if (action === "delete") {
                appendDelete($destructive, row, filename);
            }
            if (isPrimary && $primary.children().length) {
                primaryAssigned = true;
            }
        });
        if ($primary.children().length) {
            $primary.appendTo($actions);
        }
        if ($secondary.children().length) {
            $secondary.appendTo($actions);
        }
        if ($destructive.children().length) {
            $destructive.appendTo($actions);
        }
        return actions.length;
    }

    formatters.actionPlan = plan;
    window.QcDeliveryRowActions = {populate: populate};
}(window, window.jQuery));
