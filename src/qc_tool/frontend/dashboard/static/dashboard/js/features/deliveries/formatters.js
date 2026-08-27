/* Safe delivery row formatting and capability-aware action presentation. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};

    function icon(symbol) {
        var namespace = "http://www.w3.org/2000/svg";
        var svg = document.createElementNS(namespace, "svg");
        var use = document.createElementNS(namespace, "use");
        svg.setAttribute("class", "ui-icon");
        svg.setAttribute("aria-hidden", "true");
        svg.setAttribute("focusable", "false");
        use.setAttribute("href", String(config.iconSprite || "") + "#" + symbol);
        svg.appendChild(use);
        return svg;
    }

    function appendIconText($element, symbol, text) {
        $element.append(icon(symbol));
        $element.append($("<span>", {
            "class": "delivery-row-action-label",
            text: text
        }));
        return $element;
    }

    function outerHtml($element) {
        return $element.prop("outerHTML");
    }

    function formatBytes(value) {
        var bytes = Number(value);
        var sizes = ["Bytes", "KB", "MB", "GB", "TB"];
        var sizeIndex;
        if (!Number.isFinite(bytes) || bytes < 0) {
            return "Size unavailable";
        }
        if (bytes === 0) {
            return "0 Bytes";
        }
        sizeIndex = Math.min(
            Math.floor(Math.log(bytes) / Math.log(1024)),
            sizes.length - 1
        );
        return (bytes / Math.pow(1024, sizeIndex)).toFixed(sizeIndex ? 2 : 0) +
            " " + sizes[sizeIndex];
    }

    function formatDate(value) {
        if (!value) {
            return null;
        }
        if (window.moment) {
            return window.moment.utc(value).local().format("D MMM YYYY, HH:mm");
        }
        return String(value);
    }

    function isBusy(row) {
        return row.last_job_status === "waiting" || row.last_job_status === "running";
    }

    function canRunQc(row) {
        return Boolean(
            config.canRunQc && row.can_run_qc && !isBusy(row) && !row.date_submitted
        );
    }

    function canDelete(row) {
        return Boolean(
            config.canDelete && row.can_delete && !isBusy(row) && !row.date_submitted
        );
    }

    function canSubmit(row) {
        return Boolean(
            config.submissionEnabled && config.canSubmit && row.can_submit &&
            row.last_job_status === "ok" && !row.date_submitted
        );
    }

    function checkboxFormatter(value, row) {
        return {
            disabled: !canRunQc(row) && !canDelete(row) && !canSubmit(row),
            checked: false
        };
    }

    function metadataSeparator($container) {
        $("<span>", {"class": "delivery-meta__separator", text: "\u2022"})
            .attr("aria-hidden", "true")
            .appendTo($container);
    }

    function deliveryFormatter(value, row) {
        var filename = String(row.filename || "Unnamed delivery");
        var historyUrl = String(row.job_history_url || "#");
        var $delivery = $("<div>", {"class": "delivery-cell"});
        var $link = $("<a>", {
            "class": "delivery-history-link",
            href: historyUrl,
            "aria-label": "View QC job history for " + filename
        });
        var $meta = $("<div>", {"class": "delivery-meta"});

        $("<span>", {"class": "delivery-history-link__filename", text: filename})
            .appendTo($link);
        $link.append(icon("chevron-right")).appendTo($delivery);
        $("<span>", {text: "ID #" + String(row.id || "\u2014")}).appendTo($meta);
        metadataSeparator($meta);
        $("<span>", {text: row.type === "s3" ? "S3" : "Local"}).appendTo($meta);
        metadataSeparator($meta);
        $("<span>", {text: formatBytes(row.size_bytes)}).appendTo($meta);
        if (row.username) {
            metadataSeparator($meta);
            $("<span>", {text: String(row.username)}).appendTo($meta);
        }
        $meta.appendTo($delivery);
        $("<div>", {
            "class": "delivery-cell__date",
            text: formatDate(row.date_uploaded) || "Upload date unavailable"
        }).appendTo($delivery);
        appendIconText($("<a>", {
            "class": "delivery-history-shortcut",
            href: historyUrl,
            "aria-label": "Open complete QC job history for " + filename
        }).appendTo($delivery), "history", "QC job history");
        return outerHtml($delivery);
    }

    function productFormatter(value, row) {
        var description = String(row.product_description || "Product not identified");
        var $product = $("<div>", {"class": "delivery-product"});
        var $link = $("<a>", {
            "class": "delivery-product__link",
            href: String(config.productsUrl || "#"),
            text: description,
            "aria-label": "View products; current delivery product is " + description
        });

        $link.append(icon("chevron-right")).appendTo($product);
        if (row.product_ident) {
            $("<span>", {
                "class": "delivery-product__ident",
                text: String(row.product_ident)
            }).appendTo($product);
        }
        $("<span>", {
            "class": "delivery-aoi" + (row.aoi_code ? "" : " delivery-aoi--empty"),
            text: row.aoi_code ? "AOI: " + String(row.aoi_code) : "AOI not available"
        }).appendTo($product);
        return outerHtml($product);
    }

    function statusPresentation(row) {
        var deliveryStatus = String(row.delivery_status || "failed");
        var jobStatus = String(row.last_job_status || "");
        var presentation = {
            modifier: deliveryStatus,
            icon: "alert-triangle",
            label: "Needs attention",
            detail: "The latest QC state needs review."
        };

        if (deliveryStatus === "submitted") {
            presentation.icon = "send";
            presentation.label = "Submitted";
            presentation.detail = row.date_submitted
                ? "Submitted " + formatDate(row.date_submitted)
                : "Submitted to EEA";
        } else if (deliveryStatus === "not_validated") {
            presentation.icon = "clock";
            presentation.label = "Not validated";
            presentation.detail = "Run QC to validate this delivery.";
        } else if (deliveryStatus === "running") {
            presentation.icon = "refresh";
            presentation.label = jobStatus === "waiting" ? "Queued" : "Running";
            presentation.detail = row.date_started
                ? "Started " + formatDate(row.date_started)
                : "Waiting for a QC worker.";
        } else if (deliveryStatus === "passed") {
            presentation.icon = "check-circle";
            presentation.label = "Passed";
            presentation.detail = row.date_finished
                ? "QC completed " + formatDate(row.date_finished)
                : "The latest QC job passed.";
        } else if (deliveryStatus === "failed") {
            presentation.icon = "x-circle";
            presentation.label = {
                partial: "Partially passed",
                error: "QC error",
                "worker timeout": "Worker timeout",
                "worker lost": "Worker unavailable",
                file_not_found: "File not found"
            }[jobStatus] || "Failed";
            presentation.detail = row.date_finished
                ? "QC completed " + formatDate(row.date_finished)
                : "The latest QC job needs review.";
        }
        return presentation;
    }

    function actionLink(cssClass, symbol, text, href, ariaLabel) {
        return appendIconText($("<a>", {
            "class": "btn delivery-row-action " + cssClass,
            href: href,
            "aria-label": ariaLabel
        }), symbol, text);
    }

    function actionButton(row, cssClass, symbol, text, ariaLabel) {
        return appendIconText($("<button>", {
            "class": "btn delivery-row-action " + cssClass,
            type: "button",
            "aria-label": ariaLabel
        }).attr({
            "data-delivery-id": String(row.id),
            "data-delivery-filename": String(row.filename || "")
        }), symbol, text);
    }

    function statusFormatter(value, row) {
        var filename = String(row.filename || "delivery");
        var presentation = statusPresentation(row);
        var $statusCell = $("<div>", {"class": "delivery-status-block"});
        var $heading = $("<div>", {
            "class": "delivery-status delivery-status--" + presentation.modifier
        });
        var $actions = $("<div>", {
            "class": "delivery-row-actions",
            "aria-label": "Actions for " + filename
        });
        var actionCount = 0;

        $heading.append(icon(presentation.icon));
        $("<strong>", {text: presentation.label}).appendTo($heading);
        $heading.appendTo($statusCell);
        $("<p>", {"class": "delivery-status-block__detail", text: presentation.detail})
            .appendTo($statusCell);

        if (row.job_result_url) {
            actionLink(
                "btn-qc-quiet btn-qc--compact delivery-job-link",
                "history",
                "View latest QC job",
                String(row.job_result_url),
                "View latest QC job for " + filename
            ).appendTo($actions);
            actionCount += 1;
        }
        if (canRunQc(row)) {
            actionLink(
                "btn-qc-success btn-qc--compact delivery-row-qc",
                "play",
                row.last_job_uuid ? "Run QC again" : "Run QC",
                String(config.setupJobUrl || "") + "?deliveries=" + encodeURIComponent(String(row.id)),
                "Run quality controls for " + filename
            ).appendTo($actions);
            actionCount += 1;
        }
        if (canSubmit(row)) {
            actionButton(
                row,
                "btn-qc-primary btn-qc--compact submit-delivery-button",
                "send",
                "Submit to EEA",
                "Submit " + filename + " to EEA"
            ).appendTo($actions);
            actionCount += 1;
        }
        if (canDelete(row)) {
            actionButton(
                row,
                "btn-qc-danger-outline btn-qc--compact delete-button",
                "trash",
                "Delete",
                "Delete " + filename
            ).appendTo($actions);
            actionCount += 1;
        }

        if (actionCount) {
            $actions.appendTo($statusCell);
        } else {
            $("<span>", {
                "class": "delivery-row-actions-empty",
                text: "No actions currently available"
            }).appendTo($statusCell);
        }
        return outerHtml($statusCell);
    }

    function statusCellStyle() {
        return {classes: "delivery-status-cell"};
    }

    window.checkboxFormatter = checkboxFormatter;
    window.deliveryFormatter = deliveryFormatter;
    window.productFormatter = productFormatter;
    window.statusFormatter = statusFormatter;
    window.statusCellStyle = statusCellStyle;
    window.QcDeliveryFormatters = {
        canRunQc: canRunQc,
        canDelete: canDelete,
        canSubmit: canSubmit
    };
}(window, window.jQuery));
