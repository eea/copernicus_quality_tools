(function(window, document, $) {
    "use strict";

    var root = document.getElementById("resumable-upload");
    if (!root || !window.Resumable || !$) {
        return;
    }

    var $root = $(root);
    var $progress = $root.find(".resumable-progress");
    var $list = $root.find(".resumable-list");
    var $overallProgress = $root.find(".delivery-upload-overall-progress");
    var $overallBar = $root.find(".delivery-upload-overall-progress .progress-bar");
    var $feedback = $root.find(".delivery-upload-feedback");
    var resumable = new window.Resumable({
        target: root.getAttribute("data-upload-url"),
        headers: {"X-CSRFToken": window.qcCsrf.getToken()},
        chunkSize: 5 * 1024 * 1024,
        simultaneousUploads: Number(root.getAttribute("data-simultaneous-uploads")) || 1,
        testChunks: true,
        throttleProgressCallbacks: 1,
        fileType: ["zip"]
    });

    function progressElement(file) {
        return file.qcListItem.find(".resumable-file-progress");
    }

    function uploadErrorMessage(rawMessage) {
        try {
            var payload = JSON.parse(rawMessage);
            if (payload && typeof payload.message === "string") {
                return payload.message;
            }
        } catch (_error) {
            // Proxy and protocol errors need not contain JSON.
        }
        return "The file could not be uploaded.";
    }

    function setProgress(percent) {
        var bounded = Math.max(0, Math.min(100, percent));
        $overallBar
            .css({width: bounded + "%"})
            .attr("aria-valuenow", bounded)
            .find(".sr-only")
            .text(bounded + "% uploaded");
        $progress.find(".progress-bar").css({width: bounded + "%"});
        $progress.find(".progress-text").text(bounded + "% complete");
    }

    function showFeedback(tone, message) {
        var $notice = $("<div>", {
            "class": "workspace-notice workspace-notice--" + tone,
            "role": tone === "danger" ? "alert" : "status"
        });
        $("<div>").append($("<strong>").text(message)).appendTo($notice);
        $("<a>", {
            "class": "btn btn-default btn-qc-secondary",
            "href": root.getAttribute("data-deliveries-url"),
            "text": "Back to deliveries"
        }).appendTo($notice);
        $feedback.empty().append($notice);
    }

    if (!resumable.support) {
        $root.find(".resumable-error").prop("hidden", false).show();
        $root.find(".resumable-drop").prop("hidden", true).hide();
        return;
    }

    resumable.assignDrop($root.find(".resumable-drop")[0]);
    resumable.assignBrowse($root.find(".resumable-browse")[0]);

    $root.find(".progress-resume-link").on("click", function() {
        resumable.upload();
    });
    $root.find(".progress-pause-link").on("click", function() {
        resumable.pause();
    });
    $root.find(".progress-cancel-link").on("click", function() {
        resumable.cancel();
    });

    resumable.on("fileAdded", function(file) {
        $progress.add($list).add($overallProgress).prop("hidden", false).show();
        $progress.find(".progress-resume-link").hide();
        $progress.find(".progress-pause-link, .progress-cancel-link").show();
        file.qcListItem = $("<li>");
        $("<span>", {"class": "resumable-file-name"})
            .text(file.fileName)
            .appendTo(file.qcListItem);
        $("<span>", {"class": "resumable-file-progress"})
            .text("Queued")
            .appendTo(file.qcListItem);
        $list.append(file.qcListItem);
        resumable.upload();
    });

    resumable.on("pause", function() {
        $progress.find(".progress-resume-link").show();
        $progress.find(".progress-pause-link").hide();
    });

    resumable.on("uploadStart", function() {
        $progress.find(".progress-resume-link").hide();
        $progress.find(".progress-pause-link").show();
    });

    resumable.on("complete", function() {
        $progress.find(".progress-resume-link, .progress-pause-link, .progress-cancel-link").hide();
        setProgress(100);
        showFeedback("success", "Delivery files uploaded successfully.");
    });

    resumable.on("fileSuccess", function(file) {
        progressElement(file).text("Completed");
    });

    resumable.on("fileError", function(file, message) {
        if (window.qcAuth.redirectFromPayload(message)) {
            return;
        }
        var safeMessage = uploadErrorMessage(message);
        progressElement(file).text("Failed: " + safeMessage);
        showFeedback("danger", safeMessage);
    });

    resumable.on("fileProgress", function(file) {
        progressElement(file).text(Math.floor(file.progress() * 100) + "%");
        setProgress(Math.floor(resumable.progress() * 100));
    });

    resumable.on("cancel", function() {
        $root.find(".resumable-file-progress").text("Canceled");
        $progress.find(".progress-resume-link, .progress-pause-link").hide();
    });

    window.qcDeliveryUpload = resumable;
})(window, document, window.jQuery);
