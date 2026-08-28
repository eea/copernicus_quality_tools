/* Shared formatting helpers and capability checks for delivery rows. */
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
        return row.last_job_status === "waiting" ||
            row.last_job_status === "running";
    }

    function canRunQc(row) {
        return Boolean(
            config.canRunQc && row.can_run_qc &&
            !isBusy(row) && !row.date_submitted
        );
    }

    function canDelete(row) {
        return Boolean(
            config.canDelete && row.can_delete &&
            !isBusy(row) && !row.date_submitted
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

    window.checkboxFormatter = checkboxFormatter;
    window.QcDeliveryFormatters = {
        appendIconText: appendIconText,
        canDelete: canDelete,
        canRunQc: canRunQc,
        canSubmit: canSubmit,
        formatBytes: formatBytes,
        formatDate: formatDate,
        icon: icon,
        outerHtml: outerHtml
    };
}(window, window.jQuery));
