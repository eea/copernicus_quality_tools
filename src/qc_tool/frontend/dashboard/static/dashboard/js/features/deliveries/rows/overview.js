/* Safe composite delivery overview rendering for Bootstrap Table. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
    var formatters = window.QcDeliveryFormatters;
    var rowActions = window.QcDeliveryRowActions;
    var rowStatus = window.QcDeliveryRowStatus;

    function metadataSeparator($container) {
        $("<span>", {"class": "delivery-meta__separator", text: "\u2022"})
            .attr("aria-hidden", "true")
            .appendTo($container);
    }

    function identity(row) {
        var filename = String(row.filename || "Unnamed delivery");
        var $identity = $("<div>", {"class": "delivery-overview__identity"});
        var $headline = $("<div>", {"class": "delivery-overview__headline"});
        var $link = $("<a>", {
            "class": "delivery-history-link",
            href: String(row.job_history_url || "#"),
            "aria-label": "View QC job history for " + filename
        });
        var $meta = $("<div>", {"class": "delivery-meta"});
        var uploadedAt = formatters.formatDate(row.date_uploaded);

        $("<span>", {"class": "delivery-history-link__filename", text: filename})
            .appendTo($link);
        $link.append(formatters.icon("chevron-right")).appendTo($headline);
        rowStatus.badge(rowStatus.presentation(row)).appendTo($headline);
        $headline.appendTo($identity);

        $("<span>", {
            text: uploadedAt ? "Uploaded " + uploadedAt : "Upload date unavailable"
        }).appendTo($meta);
        metadataSeparator($meta);
        $("<span>", {text: formatters.formatBytes(row.size_bytes)}).appendTo($meta);
        metadataSeparator($meta);
        $("<span>", {text: row.type === "s3" ? "S3" : "Local"}).appendTo($meta);
        if (row.username) {
            metadataSeparator($meta);
            $("<span>", {text: String(row.username)}).appendTo($meta);
        }
        metadataSeparator($meta);
        $("<span>", {text: "ID #" + String(row.id || "\u2014")}).appendTo($meta);
        $meta.appendTo($identity);
        return $identity;
    }

    function productContext(row) {
        var description = String(row.product_description || "Product not identified");
        var productUrl = String(config.productsUrl || "#");
        var $product = $("<div>", {"class": "delivery-overview__product"});

        if (row.product_ident && config.productDetailUrlTemplate) {
            productUrl = String(config.productDetailUrlTemplate).replace(
                "product-ident-placeholder",
                encodeURIComponent(String(row.product_ident))
            );
        }
        var $link = $("<a>", {
            "class": "delivery-product__link",
            href: productUrl,
            text: description,
            "aria-label": "View product details for " + description
        });

        $("<span>", {
            "class": "delivery-overview__label",
            text: "Product / AOI"
        }).appendTo($product);
        $link.append(formatters.icon("chevron-right")).appendTo($product);
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
        return $product;
    }

    function deliveryOverviewFormatter(value, row) {
        var filename = String(row.filename || "delivery");
        var status = rowStatus.presentation(row);
        var $overview = $("<article>", {
            "class": "delivery-overview",
            "data-delivery-status": status.modifier
        });
        var $footer = $("<div>", {"class": "delivery-overview__footer"});
        var $actions = $("<div>", {
            "class": "delivery-row-actions",
            "role": "group",
            "aria-label": "Actions for " + filename
        });

        identity(row).appendTo($overview);
        productContext(row).appendTo($overview);
        $("<p>", {
            "class": "delivery-overview__status-detail",
            text: status.detail
        }).appendTo($footer);
        if (rowActions.populate($actions, row, filename)) {
            $actions.appendTo($footer);
        } else {
            $("<span>", {
                "class": "delivery-row-actions-empty",
                text: "No additional actions available"
            }).appendTo($footer);
        }
        $footer.appendTo($overview);
        return formatters.outerHtml($overview);
    }

    window.deliveryOverviewFormatter = deliveryOverviewFormatter;
}(window, window.jQuery));
