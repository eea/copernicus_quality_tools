/* Safe confirmation and outcome dialogs for delivery mutations. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
    var tableSelector = "#tbl-deliveries";

    function filenameList(rows, introduction) {
        var $message = $("<div>");
        var $list = $("<ul>", {"class": "delivery-dialog-list"});
        $("<p>", {text: introduction}).appendTo($message);
        rows.slice(0, 10).forEach(function (row) {
            $("<li>", {text: String(row.filename || "Unnamed delivery")}).appendTo($list);
        });
        if (rows.length > 10) {
            $("<li>", {text: "...and " + (rows.length - 10) + " more."}).appendTo($list);
        }
        $list.appendTo($message);
        return $message;
    }

    function responseMessage(result) {
        var $message = $("<div>");
        $("<p>", {text: String(result.message || "The request completed.")}).appendTo($message);
        if (Array.isArray(result.failed) && result.failed.length) {
            $("<strong>", {text: "Issues"}).appendTo($message);
            result.failed.slice(0, 20).forEach(function (issue) {
                $("<div>", {text: String(issue)}).appendTo($message);
            });
        }
        return $message;
    }

    function errorText(xhr, fallback) {
        if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
            return String(xhr.responseJSON.message);
        }
        return fallback;
    }

    function showMessage(type, title, message) {
        window.BootstrapDialog.show({
            type: type,
            title: title,
            message: typeof message === "string" ? $("<div>", {text: message}) : message,
            buttons: [{
                label: "Close",
                cssClass: "btn-qc-secondary",
                action: function (dialog) {
                    dialog.close();
                }
            }]
        });
    }

    function completeMutation(message) {
        $(tableSelector).bootstrapTable("uncheckAll");
        window.QcDeliveryTable.refresh();
        window.QcDeliveryTable.announce(message);
    }

    function confirmDelete(rows) {
        var count = rows.length;
        if (!count) {
            return;
        }
        window.BootstrapDialog.show({
            type: window.BootstrapDialog.TYPE_DANGER,
            title: count === 1 ? "Delete this delivery?" : "Delete " + count + " deliveries?",
            message: filenameList(
                rows,
                count === 1
                    ? "The delivery ZIP and its QC history will no longer be available. This cannot be undone."
                    : "The selected delivery ZIP files and their QC histories will no longer be available. This cannot be undone."
            ),
            buttons: [{
                label: count === 1 ? "Delete delivery" : "Delete " + count + " deliveries",
                cssClass: "btn-qc-danger",
                action: function (dialog) {
                    var button = this;
                    button.disable();
                    button.spin();
                    $.ajax({
                        type: "POST",
                        url: config.deleteUrl,
                        dataType: "json",
                        data: {ids: rows.map(function (row) { return row.id; }).join(",")}
                    }).done(function (result) {
                        if (result.status === "error") {
                            dialog.close();
                            showMessage(
                                window.BootstrapDialog.TYPE_WARNING,
                                "Deliveries could not be deleted",
                                String(result.message || "The server rejected the request.")
                            );
                            return;
                        }
                        dialog.close();
                        completeMutation(result.message || "Selected deliveries deleted.");
                    }).fail(function (xhr) {
                        dialog.close();
                        showMessage(
                            window.BootstrapDialog.TYPE_WARNING,
                            "Deliveries could not be deleted",
                            errorText(xhr, "The deletion request failed. Please try again.")
                        );
                    });
                }
            }, {
                label: "Cancel",
                cssClass: "btn-qc-secondary",
                action: function (dialog) {
                    dialog.close();
                }
            }]
        });
    }

    function confirmSubmit(rows) {
        var count = rows.length;
        var useBatch = count > 1;
        if (!count) {
            return;
        }
        window.BootstrapDialog.show({
            type: window.BootstrapDialog.TYPE_PRIMARY,
            title: count === 1 ? "Submit this delivery to EEA?" : "Submit " + count + " deliveries to EEA?",
            message: filenameList(
                rows,
                "The latest successful QC result for each delivery will be used for submission."
            ),
            buttons: [{
                label: count === 1 ? "Submit delivery" : "Submit " + count + " deliveries",
                cssClass: "btn-qc-primary",
                action: function (dialog) {
                    var button = this;
                    var requestData = useBatch ? {
                        ids: rows.map(function (row) { return row.id; }).join(","),
                        filenames: rows.map(function (row) { return row.filename; }).join(",")
                    } : {
                        id: rows[0].id,
                        filename: rows[0].filename
                    };
                    button.disable();
                    button.spin();
                    $.ajax({
                        type: "POST",
                        url: useBatch ? config.submitBatchUrl : config.submitUrl,
                        dataType: "json",
                        data: requestData
                    }).done(function (result) {
                        dialog.close();
                        showMessage(
                            result.status === "ok"
                                ? window.BootstrapDialog.TYPE_SUCCESS
                                : window.BootstrapDialog.TYPE_WARNING,
                            result.status === "ok" ? "Submission complete" : "Submission needs attention",
                            responseMessage(result)
                        );
                        completeMutation(result.message || "Submission request completed.");
                    }).fail(function (xhr) {
                        dialog.close();
                        showMessage(
                            window.BootstrapDialog.TYPE_DANGER,
                            "Submission failed",
                            errorText(xhr, "The submission request failed. Please try again.")
                        );
                    });
                }
            }, {
                label: "Cancel",
                cssClass: "btn-qc-secondary",
                action: function (dialog) {
                    dialog.close();
                }
            }]
        });
    }

    window.QcDeliveryDialogs = {
        confirmDelete: confirmDelete,
        confirmSubmit: confirmSubmit
    };
}(window, window.jQuery));
