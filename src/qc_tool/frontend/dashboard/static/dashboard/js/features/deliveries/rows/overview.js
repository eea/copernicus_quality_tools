/* Safe, semantic delivery table cell rendering for Bootstrap Table. */
(function (window, $) {
    "use strict";

    var formatters = window.QcDeliveryFormatters;
    var rowActions = window.QcDeliveryRowActions;
    var rowStatus = window.QcDeliveryRowStatus;

    function html($element) {
        return formatters.outerHtml($element);
    }

    function deliveryFormatter(value, row) {
        row = row || {};
        var filename = String(row.filename || value || "Unnamed delivery");
        var $delivery = $("<div>", {"class": "delivery-cell"});
        var $name = $(row.job_history_url ? "<a>" : "<span>", {
            "class": "delivery-cell__filename",
            text: filename
        });
        if (row.job_history_url) {
            $name.attr({
                href: String(row.job_history_url),
                title: "Open delivery and QC history",
                "aria-label": "Open delivery and QC history for " + filename
            });
        }
        $name.appendTo($delivery);
        if (row.size_bytes !== undefined && row.size_bytes !== null) {
            $("<span>", {"class": "delivery-cell__metadata", text: formatters.formatBytes(row.size_bytes)}).appendTo($delivery);
        }
        return html($delivery);
    }

    function productFormatter(value, row) {
        row = row || {};
        var description = String(
            row.product_display_name || row.product_description || value || "Product not identified"
        );
        var productUnitCode = "";
        var $product = $("<div>", {"class": "delivery-product"});
        var $link;

        if (String(row.last_job_status || "").toLowerCase() === "ok") {
            productUnitCode = String(
                row.verified_product_unit_code || row.product_unit_code || ""
            );
        }

        $link = $(row.product_url ? "<a>" : "<span>", {
            "class": "delivery-product__link",
            text: description
        });
        if (row.product_url) {
            $link.attr({href: String(row.product_url), "aria-label": "View product details for " + description});
        }
        $link.appendTo($product);
        if (productUnitCode) {
            $("<span>", {
                "class": "delivery-product-unit",
                text: "Product unit: " + productUnitCode
            }).appendTo($product);
        }
        return html($product);
    }

    function uploadedFormatter(value, row) {
        var rawDate = (row || {}).date_uploaded || value;
        var uploadedAt = formatters.formatDate(rawDate);
        var $date = $("<time>", {
            "class": "delivery-date" + (uploadedAt ? "" : " delivery-value--empty"),
            text: window.moment && rawDate ? window.moment.utc(rawDate).local().format("D MMM YYYY") : uploadedAt || "Not available"
        });
        if (rawDate) $date.attr({datetime: String(rawDate), title: uploadedAt});
        if (window.moment && rawDate) {
            $("<span>", {"class": "delivery-date__time", text: window.moment.utc(rawDate).local().format("HH:mm")}).appendTo($date);
        }
        return html($date);
    }

    function sizeFormatter(value, row) {
        var size = (row || {}).size_bytes;
        if (size === undefined || size === null || size === "") {
            size = value;
        }
        return html($("<span>", {
            "class": "delivery-size",
            text: formatters.formatBytes(size)
        }));
    }

    function sourceFormatter(value, row) {
        var source = String((row || {}).type || value || "").toLowerCase();
        var label = source === "s3" ? "S3" : source === "local" ? "Local" : "Not available";
        return html($("<span>", {
            "class": "delivery-source" + (source ? "" : " delivery-value--empty"),
            text: label
        }));
    }

    function ownerFormatter(value, row) {
        var owner = (row || {}).username || value;
        return html($("<span>", {
            "class": "delivery-owner" + (owner ? "" : " delivery-value--empty"),
            text: owner ? String(owner) : "Not available"
        }));
    }

    function idFormatter(value, row) {
        var id = (row || {}).id;
        if (id === undefined || id === null || id === "") {
            id = value;
        }
        return html($("<span>", {
            "class": "delivery-id" + (
                id === undefined || id === null || id === ""
                    ? " delivery-value--empty"
                    : ""
            ),
            text: id === undefined || id === null || id === ""
                ? "Not available"
                : "#" + String(id)
        }));
    }

    function statusFormatter(value, row) {
        row = row || {};
        var status = rowStatus.presentation(row);
        var $status = $("<div>", {"class": "delivery-status-block"});

        rowStatus.badge(status).appendTo($status);
        if (status.detail) {
            $("<p>", {"class": "delivery-status-block__detail", text: status.detail}).appendTo($status);
        }
        if (row.delivery_status === "needs_correction" && row.submission_url) {
            var $feedback = $("<div>", {"class": "delivery-review-feedback"});
            $("<p>", {
                "class": "delivery-review-feedback__byline",
                text: "Feedback" + (row.review_actor_username ? " from " + row.review_actor_username : "")
            }).appendTo($feedback);
            $("<p>", {
                "class": "delivery-review-feedback__comment",
                text: row.review_notes || "No written feedback was recorded. Contact your product manager."
            }).appendTo($feedback);
            if (row.review_created_at) {
                $("<time>", {
                    datetime: String(row.review_created_at),
                    text: formatters.formatDate(row.review_created_at)
                }).appendTo($feedback);
            }
            $feedback.appendTo($status);
        }
        var $links = $("<div>", {"class": "delivery-status-block__links"});
        if (row.job_result_url && row.delivery_status !== "failed") {
            var resultLabel = row.delivery_status === "running" ? "QC progress" : "QC result";
            var $result = $("<a>", {"class": "delivery-qc-link", href: String(row.job_result_url),
                "aria-label": resultLabel + " for " + String(row.filename || "delivery")});
            formatters.appendIconText($result, "file", resultLabel).appendTo($links);
        }
        if (row.job_history_url && row.last_job_uuid) {
            var $history = $("<a>", {"class": "delivery-history-link", href: String(row.job_history_url),
                "aria-label": "View QC history for " + String(row.filename || "delivery")});
            $history.append(formatters.icon("history"));
            $("<span>", {"class": "delivery-history-link__label", text: "QC history"}).appendTo($history);
            $history.appendTo($links);
        }
        if ($links.children().length) $links.appendTo($status);
        return html($status);
    }

    function actionsFormatter(value, row) {
        row = row || {};
        var filename = String(row.filename || "delivery");
        var $actions = $("<div>", {
            "class": "delivery-row-actions",
            "role": "group",
            "aria-label": "Actions for " + filename
        });

        if (!rowActions.populate($actions, row, filename)) {
            $("<span>", {
                "class": "delivery-row-actions-empty",
                text: "—",
                "aria-label": "No action required"
            }).appendTo($actions);
        }
        return html($actions);
    }

    window.deliveryFormatter = deliveryFormatter;
    window.productFormatter = productFormatter;
    window.uploadedFormatter = uploadedFormatter;
    window.sizeFormatter = sizeFormatter;
    window.sourceFormatter = sourceFormatter;
    window.ownerFormatter = ownerFormatter;
    window.idFormatter = idFormatter;
    window.statusFormatter = statusFormatter;
    window.actionsFormatter = actionsFormatter;
}(window, window.jQuery));
