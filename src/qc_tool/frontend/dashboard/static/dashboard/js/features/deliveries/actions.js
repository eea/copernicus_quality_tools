/* Single-row and current-page bulk delivery action coordination. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
    var dialogs = window.QcDeliveryDialogs || {};
    var tableSelector = "#tbl-deliveries";

    function selectedState() {
        var table = window.QcDeliveryTable;
        var rows = table.selectedRows();
        return {
            rows: rows,
            total: rows.length,
            qc: rows.filter(table.canRunQc),
            removable: rows.filter(table.canDelete),
            submittable: rows.filter(table.canSubmit)
        };
    }

    function updateButton(selector, label, eligible, total, reason) {
        var $button = $(selector);
        var allEligible = total > 0 && eligible === total;
        var displayLabel = total ? label + " (" + total + ")" : label;
        if (!$button.length) {
            return;
        }
        $button
            .prop("disabled", !allEligible)
            .attr("title", total > 0 && !allEligible ? reason : "")
            .attr(
                "aria-label",
                displayLabel + (total > 0 && !allEligible ? ". " + reason : "")
            )
            .find(".delivery-action-label")
            .text(displayLabel);
    }

    function updateSelection() {
        var state = selectedState();
        var unavailable = [];
        var guidance;

        $("#delivery-selection-toolbar").prop("hidden", state.total === 0);
        $("#delivery-selection-summary").text(
            state.total === 0
                ? "No deliveries selected"
                : state.total + (state.total === 1 ? " delivery" : " deliveries") +
                    " selected on this page"
        );

        if ($("#btn-qc-multi").length && state.qc.length !== state.total) {
            unavailable.push("Run QC");
        }
        if ($("#btn-submit-multi").length && state.submittable.length !== state.total) {
            unavailable.push("Submit to EEA");
        }
        if ($("#btn-delete-multi").length && state.removable.length !== state.total) {
            unavailable.push("Delete");
        }

        guidance = "Every selected delivery is eligible for the available actions.";
        if (!state.total) {
            guidance = "Select eligible deliveries on this page to apply a bulk action.";
        } else if (unavailable.length) {
            guidance = "Adjust the selection: not every delivery is eligible for " +
                unavailable.join(", ") + ".";
        }
        $("#delivery-selection-guidance").text(guidance);

        updateButton(
            "#btn-qc-multi",
            "Run QC",
            state.qc.length,
            state.total,
            "Run QC requires every selected delivery to be eligible."
        );
        updateButton(
            "#btn-submit-multi",
            "Submit to EEA",
            state.submittable.length,
            state.total,
            "Submission requires every selected delivery to have passed QC."
        );
        updateButton(
            "#btn-delete-multi",
            "Delete",
            state.removable.length,
            state.total,
            "Delete requires every selected delivery to be eligible."
        );
    }

    function blocked(message) {
        $("#delivery-selection-guidance").text(message);
        window.QcDeliveryTable.announce(message);
    }

    function rowFromButton(button) {
        return {
            id: $(button).attr("data-delivery-id"),
            filename: $(button).attr("data-delivery-filename")
        };
    }

    function bindRowActions() {
        $(tableSelector).on("click", ".delete-button", function () {
            dialogs.confirmDelete([rowFromButton(this)]);
        });
        $(tableSelector).on("click", ".submit-delivery-button", function () {
            dialogs.confirmSubmit([rowFromButton(this)]);
        });
    }

    function bindBulkActions() {
        $("#btn-clear-selection").on("click", function () {
            $(tableSelector).bootstrapTable("uncheckAll");
            updateSelection();
            window.QcDeliveryTable.announce("Delivery selection cleared.");
        });
        $("#btn-qc-multi").on("click", function () {
            var state = selectedState();
            if (!state.total || state.qc.length !== state.total) {
                blocked("Run QC requires every selected delivery to be eligible.");
                return;
            }
            window.location.assign(
                String(config.setupJobUrl || "") + "?deliveries=" +
                encodeURIComponent(state.rows.map(function (row) { return row.id; }).join(","))
            );
        });
        $("#btn-delete-multi").on("click", function () {
            var state = selectedState();
            if (!state.total || state.removable.length !== state.total) {
                blocked("Delete requires every selected delivery to be eligible.");
                return;
            }
            dialogs.confirmDelete(state.rows);
        });
        $("#btn-submit-multi").on("click", function () {
            var state = selectedState();
            if (!state.total || state.submittable.length !== state.total) {
                blocked("Submission requires every selected delivery to have passed QC.");
                return;
            }
            dialogs.confirmSubmit(state.rows);
        });
    }

    function bindSelectionEvents() {
        $(tableSelector).on(
            "check.bs.table check-all.bs.table uncheck.bs.table uncheck-all.bs.table " +
            "load-success.bs.table page-change.bs.table",
            updateSelection
        );
    }

    function init() {
        bindRowActions();
        bindBulkActions();
        bindSelectionEvents();
        updateSelection();
    }

    window.QcDeliveryActions = {
        init: init,
        updateSelection: updateSelection
    };
}(window, window.jQuery));
