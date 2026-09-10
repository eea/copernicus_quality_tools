/* Keep the manager's decision distinct from the delivery's QC result. */
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

    if (deliveryStatus === "needs_correction") {
      result.icon = "alert-triangle";
      result.label = "Correction needed";
      result.detail = "Corrections requested. Read the feedback before uploading again.";
    } else if (deliveryStatus === "accepted") {
      result.icon = "check-circle";
      result.label = "Accepted";
      result.detail = "Accepted by the product manager. No further action is needed.";
    } else if (deliveryStatus === "submitted") {
      result.icon = "send";
      result.label = "Submitted";
      result.detail = "Awaiting the product manager's review.";
      if (row.submission_review_state === "conflict") {
        result.detail = "The product manager is reviewing competing submissions.";
      }
    } else if (deliveryStatus === "not_validated") {
      result.icon = "clock";
      result.label = "Not validated";
      result.detail = "Run QC to validate this delivery.";
    } else if (deliveryStatus === "running") {
      result.icon = jobStatus === "waiting" ? "clock" : "refresh";
      result.label = jobStatus === "waiting" ? "In queue" : "In progress";
      result.detail = jobStatus === "waiting"
        ? "QC will start automatically when a worker is available."
        : "QC is running. Results will appear automatically.";
    } else if (deliveryStatus === "passed") {
      result.icon = "check-circle";
      result.label = "Validated";
      result.detail = "QC passed. Ready to submit for review.";
    } else if (deliveryStatus === "failed") {
      result.icon = "x-circle";
      result.label = "Failed";
      result.detail =
        {
          partial: "Some checks failed. Review the QC result before trying again.",
          "worker timeout": "The QC worker timed out. Review the result and run QC again.",
          "worker lost": "The QC worker became unavailable. Run QC again.",
          file_not_found: "The delivery file could not be found. Review the QC result.",
        }[jobStatus] || "Review the QC result to see what needs fixing.";
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
