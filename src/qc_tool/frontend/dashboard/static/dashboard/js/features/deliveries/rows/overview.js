/* Safe, semantic delivery table cell rendering for Bootstrap Table. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
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
        var $history = $("<a>", {
            "class": "delivery-history-link",
            href: String(row.job_history_url || "#"),
            "aria-label": "View job history for " + filename
        });

        $("<strong>", {
            "class": "delivery-cell__filename",
            text: filename
        }).appendTo($delivery);
        $history.append(formatters.icon("history"));
        $("<span>", {
            "class": "delivery-history-link__label",
            text: "Job history"
        }).appendTo($history);
        $history.appendTo($delivery);
        return html($delivery);
    }

    function productFormatter(value, row) {
        row = row || {};
        var description = String(
            row.product_description || value || "Product not identified"
        );
        var aoiCode = "";
        var productUrl = String(config.productsUrl || "#");
        var $product = $("<div>", {"class": "delivery-product"});
        var $link;

        if (String(row.last_job_status || "").toLowerCase() === "ok") {
            aoiCode = String(
                row.aoi_code_submitted || row.aoi_code || ""
            );
        }

        if (row.product_ident && config.productDetailUrlTemplate) {
            productUrl = String(config.productDetailUrlTemplate).replace(
                "product-ident-placeholder",
                encodeURIComponent(String(row.product_ident))
            );
        }
        $link = $("<a>", {
            "class": "delivery-product__link",
            href: productUrl,
            text: description,
            "aria-label": "View product details for " + description
        });
        $link.append(formatters.icon("chevron-right")).appendTo($product);
        if (row.product_ident) {
            $("<span>", {
                "class": "delivery-product__ident",
                text: String(row.product_ident)
            }).appendTo($product);
        }
        if (aoiCode) {
            $("<span>", {
                "class": "delivery-aoi",
                text: "AOI: " + aoiCode
            }).appendTo($product);
        }
        return html($product);
    }

    function uploadedFormatter(value, row) {
        var uploadedAt = formatters.formatDate((row || {}).date_uploaded || value);
        return html($("<span>", {
            "class": "delivery-date" + (uploadedAt ? "" : " delivery-value--empty"),
            text: uploadedAt || "Not available"
        }));
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
        var status = rowStatus.presentation(row || {});
        var $status = $("<div>", {"class": "delivery-status-block"});

        rowStatus.badge(status).appendTo($status);
        $("<p>", {
            "class": "delivery-status-block__detail",
            text: status.detail
        }).appendTo($status);
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
                text: "No additional actions available"
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
