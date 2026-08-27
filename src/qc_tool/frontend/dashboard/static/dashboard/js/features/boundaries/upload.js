(function (window, document) {
    "use strict";

    var input = document.getElementById("fileupload");
    var trigger = document.querySelector(".js-upload-files");
    var progress = document.querySelector("#modal-progress .progress-bar");
    var resultContainer = document.getElementById("upload-result");

    if (!input || !trigger || !progress || !resultContainer) {
        return;
    }

    function showProgress(visible) {
        trigger.disabled = visible;
        input.disabled = visible;
        if (window.jQuery && window.jQuery.fn.modal) {
            window.jQuery("#modal-progress").modal(visible ? "show" : "hide");
        }
    }

    function updateProgress(loaded, total) {
        var percentage = total > 0 ? Math.round((loaded / total) * 100) : 0;
        var label = percentage + "%";
        progress.style.width = label;
        progress.textContent = label;
        progress.setAttribute("aria-valuenow", String(percentage));
    }

    function showResult(kind, message) {
        var alert = document.createElement("div");
        var icon = document.createElement("span");

        resultContainer.replaceChildren();
        alert.className = "alert alert-" + kind;
        icon.className = "glyphicon " + (
            kind === "success" ? "glyphicon-ok" : "glyphicon-remove"
        );
        alert.appendChild(icon);
        alert.appendChild(document.createTextNode(" " + message));

        if (kind === "success") {
            var link = document.createElement("a");
            link.className = "btn btn-qc-secondary";
            link.href = input.dataset.successUrl;
            link.textContent = "Go Back to Boundaries";
            alert.appendChild(document.createTextNode(" "));
            alert.appendChild(link);
        }

        resultContainer.appendChild(alert);
    }

    function responsePayload(xhr) {
        if (xhr.response && typeof xhr.response === "object") {
            return xhr.response;
        }
        try {
            return JSON.parse(xhr.responseText || "{}");
        } catch (_error) {
            return {};
        }
    }

    function completeUpload(xhr) {
        showProgress(false);
        input.value = "";

        if (
            window.qcAuth &&
            window.qcAuth.handleUnauthorizedXhr &&
            window.qcAuth.handleUnauthorizedXhr(xhr)
        ) {
            return;
        }

        var payload = responsePayload(xhr);
        if (xhr.status >= 200 && xhr.status < 300 && payload.is_valid) {
            updateProgress(1, 1);
            showResult("success", payload.message || "Boundary package activated.");
            return;
        }
        showResult(
            "danger",
            payload.message || "The boundary package could not be uploaded."
        );
    }

    trigger.addEventListener("click", function () {
        input.click();
    });

    input.addEventListener("change", function () {
        if (input.files.length !== 1) {
            showResult("danger", "Select exactly one boundary package ZIP file.");
            input.value = "";
            return;
        }

        var request = new XMLHttpRequest();
        var form = new FormData();
        form.append("file", input.files[0]);

        request.open("POST", input.dataset.url);
        request.responseType = "json";
        request.setRequestHeader("Accept", "application/json");
        if (window.qcCsrf) {
            request.setRequestHeader("X-CSRFToken", window.qcCsrf.getToken());
        }
        request.upload.addEventListener("progress", function (event) {
            if (event.lengthComputable) {
                updateProgress(event.loaded, event.total);
            }
        });
        request.addEventListener("load", function () {
            completeUpload(request);
        });
        request.addEventListener("error", function () {
            showProgress(false);
            input.value = "";
            showResult("danger", "The boundary upload connection failed.");
        });

        resultContainer.replaceChildren();
        updateProgress(0, 1);
        showProgress(true);
        request.send(form);
    });
})(window, document);
