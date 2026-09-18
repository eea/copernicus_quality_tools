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
      result.detail = "";
    } else if (deliveryStatus === "accepted") {
      result.icon = "check-circle";
      result.label = "Accepted";
      result.detail = "";
    } else if (deliveryStatus === "submitted") {
      result.icon = "send";
      result.label = "Submitted";
      result.detail = "Awaiting product manager review.";
      if (row.submission_review_state === "conflict") {
        result.detail = "The product manager is reviewing competing submissions.";
      }
    } else if (deliveryStatus === "not_validated") {
      result.icon = "clock";
      result.label = "Not validated";
      result.detail = "";
    } else if (deliveryStatus === "running") {
      result.icon = jobStatus === "waiting" ? "clock" : "refresh";
      result.label = jobStatus === "waiting" ? "In queue" : "In progress";
      result.detail = jobStatus === "waiting"
        ? "Starts automatically when a worker is available."
        : "Results update automatically.";
    } else if (deliveryStatus === "passed") {
      result.icon = "check-circle";
      result.label = "Validated";
      result.detail = "";
    } else if (deliveryStatus === "failed") {
      result.icon = "x-circle";
      result.label = "Failed";
      result.detail =
        {
          partial: "Some checks failed.",
          "worker timeout": "QC timed out. Run QC again.",
          "worker lost": "QC was interrupted. Run QC again.",
          file_not_found: "The delivery file could not be found.",
        }[jobStatus] || "";
    }
    return result;
  }

  function badge(status) {
    var $status = $("<span>", {
      class: "delivery-status delivery-status--" + status.modifier,
    });

    $status.append(formatters.icon(status.icon));
    $("<span>", { text: status.label }).appendTo($status);
    return $status;
  }

  window.QcDeliveryRowStatus = {
    badge: badge,
    presentation: presentation,
  };
})(window, window.jQuery);
