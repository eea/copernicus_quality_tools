/* Text-first lifecycle presentation for a delivery's latest QC state. */
(function (window, $) {
  "use strict";

  var formatters = window.QcDeliveryFormatters;

  function presentation(row) {
    var deliveryStatus = String(row.delivery_status || "failed");
    var jobStatus = String(row.last_job_status || "");
    var result = {
      modifier: deliveryStatus,
      icon: "alert-triangle",
      label: "Needs attention",
      detail: "The latest QC state needs review.",
    };

    if (deliveryStatus === "submitted") {
      result.icon = "send";
      result.label = "Submitted";
      result.detail = row.date_submitted
        ? "Submitted " + formatters.formatDate(row.date_submitted)
        : "Submitted to EEA";
    } else if (deliveryStatus === "not_validated") {
      result.icon = "clock";
      result.label = "Not validated";
      result.detail = "Run QC to validate this delivery.";
    } else if (deliveryStatus === "running") {
      result.icon = "refresh";
      result.label = jobStatus === "waiting" ? "Queued" : "Running";
      result.detail = row.date_started
        ? "Started " + formatters.formatDate(row.date_started)
        : "Waiting for a QC worker.";
    } else if (deliveryStatus === "passed") {
      result.icon = "check-circle";
      result.label = "Passed";
      result.detail = "The latest QC job passed.";
    } else if (deliveryStatus === "failed") {
      result.icon = "x-circle";
      result.label =
        {
          partial: "Partially passed",
          error: "Failed",
          "worker timeout": "Worker timeout",
          "worker lost": "Worker unavailable",
          file_not_found: "File not found",
        }[jobStatus] || "Failed";
      result.detail = "The latest QC job needs review.";
    }
    return result;
  }

  function badge(status) {
    var $status = $("<span>", {
      class: "delivery-status delivery-status--" + status.modifier,
    });

    $status.append(formatters.icon(status.icon));
    $("<strong>", { text: status.label }).appendTo($status);
    return $status;
  }

  window.QcDeliveryRowStatus = {
    badge: badge,
    presentation: presentation,
  };
})(window, window.jQuery);
