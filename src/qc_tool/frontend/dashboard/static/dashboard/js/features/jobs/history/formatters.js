/* Safe, accessible Bootstrap Table formatters for QC job records. */
(function (window, $) {
    "use strict";

    var history = window.QcJobHistory = window.QcJobHistory || {};
    var config = window.QC_JOB_HISTORY_CONFIG || {};

    function icon(symbol) {
        var namespace = "http://www.w3.org/2000/svg";
        var svg = document.createElementNS(namespace, "svg");
        var use = document.createElementNS(namespace, "use");

        svg.setAttribute("class", "ui-icon");
        svg.setAttribute("aria-hidden", "true");
        svg.setAttribute("focusable", "false");
        use.setAttribute(
            "href",
            String(config.iconSprite || "") + "#" + symbol
        );
        svg.appendChild(use);
        return svg;
    }

    function outerHtml($element) {
        return $element.prop("outerHTML");
    }

    function emptyValue() {
        return outerHtml($("<span>", {
            "class": "job-history-value--empty",
            text: "Not available"
        }));
    }

    function dateFormatter(value) {
        if (!value) {
            return emptyValue();
        }
        return outerHtml($("<time>", {
            "class": "job-history-date",
            datetime: String(value),
            text: window.moment
                ? window.moment.utc(value).local().format("D MMM YYYY, HH:mm")
                : String(value)
        }));
    }

    function stepsFormatter(value) {
        var label = Array.isArray(value)
            ? (value.length ? value.join(", ") : "None")
            : (value ? String(value) : "None");

        return outerHtml($("<span>", {
            "class": value ? "job-history-steps" : "job-history-value--empty",
            text: label
        }));
    }

    function productUnitFormatter(value, row) {
        var reported = value ? String(value) : "";
        var submitted = row.verified_product_unit_code
            ? String(row.verified_product_unit_code)
            : "";
        var $unit;

        if (!reported && !submitted) {
            return emptyValue();
        }
        $unit = $("<span>", {"class": "job-history-product-unit"});
        $("<strong>", {
            text: reported
                ? "Reported: " + reported
                : "Reported: Not available"
        }).appendTo($unit);
        if (submitted) {
            $("<small>", {text: "Verified ZIP unit: " + submitted}).appendTo($unit);
        }
        return outerHtml($unit);
    }

    function statusPresentation(value) {
        var status = String(value || "").toLowerCase();
        var statuses = {
            ok: ["passed", "check-circle", "Passed"],
            waiting: ["queued", "clock", "Queued"],
            running: ["running", "refresh", "Running"],
            partial: ["failed", "alert-triangle", "Partially passed"],
            failed: ["failed", "x-circle", "Failed"],
            error: ["failed", "x-circle", "System error"],
            "worker timeout": ["failed", "clock", "Worker timeout"],
            "worker lost": ["failed", "x-circle", "Worker unavailable"]
        };
        var presentation = statuses[status] || [
            "unknown",
            "help-circle",
            status || "Unknown"
        ];

        return {
            modifier: presentation[0],
            icon: presentation[1],
            label: presentation[2]
        };
    }

    function statusFormatter(value, row) {
        var presentation = statusPresentation(value);
        var resultUrl = String(config.resultUrlTemplate || "#").replace(
            String(config.resultUrlPlaceholder || ""),
            encodeURIComponent(String(row.job_uuid))
        );
        var $link = $("<a>", {
            "class": "job-history-status job-history-status--" +
                presentation.modifier,
            href: resultUrl,
            "aria-label": "Open result for job " + String(row.job_uuid) +
                ": " + presentation.label
        });

        $link.append(icon(presentation.icon));
        $("<span>", {text: presentation.label}).appendTo($link);
        return outerHtml($link);
    }

    history.icon = icon;
    window.dateFormatter = dateFormatter;
    window.stepsFormatter = stepsFormatter;
    window.productUnitFormatter = productUnitFormatter;
    window.statusFormatter = statusFormatter;
}(window, window.jQuery));
