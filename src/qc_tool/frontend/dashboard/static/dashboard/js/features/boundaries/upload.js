(function (window, document) {
    "use strict";

    var form = document.getElementById("boundary-upload-form");
    if (!form || !window.qcUpload) return;
    if (window.qcMaintenance && window.qcMaintenance.isActive()) return;
    if (!window.XMLHttpRequest || !window.FormData) {
        form.querySelector("[data-boundary-unsupported]").hidden = false;
        return;
    }

    var pickerRoot = form;
    var list = form.querySelector("[data-upload-list]");
    var submit = form.querySelector("[data-boundary-submit]");
    var results = document.getElementById("upload-result");
    var announcement = document.querySelector("[data-upload-announcement]");
    if (!pickerRoot || !list || !submit || !results) return;

    var selected = null;
    var row = null;
    var request = null;
    var redirecting = false;
    var limitValue = form.dataset.maxArchiveBytes || "";
    var archiveLimit = /^[0-9]+$/.test(limitValue) ? Number(limitValue) : 0;
    if (!Number.isSafeInteger(archiveLimit) || archiveLimit <= 0) archiveLimit = 0;
    var picker = window.qcUpload.createPicker(pickerRoot, {
        extensions: ["zip"],
        maxBytes: archiveLimit || undefined,
        onSelect: selectFile,
        onInvalid: invalidSelection
    });
    submit.disabled = true;

    function invalidSelection(message) {
        if (!selected) {
            if (!row) showResult("danger", message);
            return;
        }
        selected = null;
        row = null;
        list.replaceChildren();
        picker.setSelected(false);
        submit.disabled = true;
        showResult("danger", message);
    }

    function storageError(file) {
        var value = form.dataset.availableUploadBytes;
        var available = typeof value === "string" && /^[0-9]+$/.test(value) ? Number(value) : null;
        if (!Number.isSafeInteger(available) || available < 0 || file.size <= available) return "";
        return "Not enough server storage to receive this ZIP. " +
            "Space available for receiving uploads: " + window.qcUpload.formatSize(available) + ". " +
            "Free space on the server, then reload this page before retrying.";
    }

    function rejectStorage(message) {
        picker.clear();
        picker.showError(message);
        invalidSelection(message);
    }

    function selectFile(files) {
        if (window.qcMaintenance && window.qcMaintenance.isActive()) return;
        if (request || redirecting) return;
        var capacityError = storageError(files[0]);
        if (capacityError) {
            rejectStorage(capacityError);
            return;
        }
        selected = files[0];
        picker.setSelected(true);
        list.replaceChildren();
        results.replaceChildren();
        row = window.qcUpload.createFile(list, {
            name: selected.name,
            size: selected.size,
            announcement: announcement,
            retry: upload,
            remove: clearSelection
        });
        row.update({state: "selected", label: "Ready to upload", percent: null, error: ""});
        submit.disabled = false;
    }

    function clearSelection() {
        if (request || redirecting) return;
        selected = null;
        row = null;
        picker.clear();
        picker.setSelected(false);
        list.replaceChildren();
        results.replaceChildren();
        submit.disabled = true;
        announcement.textContent = "File removed. Choose a boundary package.";
        picker.browse.focus();
    }

    function setBusy(busy) {
        busy = busy || Boolean(window.qcMaintenance && window.qcMaintenance.isActive());
        picker.setBusy(busy || redirecting);
        submit.disabled = busy || !selected || redirecting;
        submit.textContent = busy ? "Uploading and validating…" : "Upload and activate";
    }

    function showResult(tone, message, reviewCurrent) {
        window.qcUpload.feedback(results, {
            tone: tone, message: message,
            href: tone === "success" || reviewCurrent ? form.dataset.successUrl : undefined,
            label: "View boundaries"
        });
    }

    function payloadMessage(payload) {
        return typeof payload.message === "string" && payload.message.trim()
            ? payload.message.trim().slice(0, 2000) : "";
    }

    function responsePayload(xhr) {
        if (window.qcAuth && window.qcAuth.responsePayload) {
            var decoded = window.qcAuth.responsePayload(xhr);
            return decoded && typeof decoded === "object" ? decoded : {};
        }
        if (xhr.response && typeof xhr.response === "object") return xhr.response;
        try {
            var payload = JSON.parse(xhr.responseText || "{}");
            return payload && typeof payload === "object" ? payload : {};
        } catch (_error) {
            return {};
        }
    }

    function finishFailure(xhr, message, reviewCurrent) {
        if (request !== xhr) return;
        request = null;
        setBusy(false);
        row.update({state: "failed", label: reviewCurrent ? "Activation not confirmed" : "Upload failed", percent: null, error: message});
        showResult("danger", message, reviewCurrent);
    }

    function failureResponse(xhr, payload) {
        var status = xhr.status;
        var message = payloadMessage(payload);
        var knownRejection = message && payload.is_valid === false && [
            "boundary_package_insufficient_space", "boundary_upload_insufficient_space",
            "boundary_package_configuration_error", "boundary_upload_unavailable"
        ].indexOf(payload.code) !== -1;
        var reviewCurrent = !knownRejection && (status === 0 || status === 408 || status >= 500);
        if (message && (payload.is_valid === false || (status >= 400 && payload.is_valid !== true))) {
            if (reviewCurrent) message += " Check Boundaries before retrying.";
            return {message: message, reviewCurrent: reviewCurrent};
        }
        if (status === 413) {
            message = "The server or proxy rejected the upload as too large (HTTP 413). " +
                "Check the displayed ZIP size limit and the server or proxy upload limit before retrying.";
        } else if (status === 401) {
            message = "Your sign-in could not be confirmed (HTTP 401). Reload this page and sign in before retrying.";
        } else if (status === 403) {
            message = "The upload was refused (HTTP 403). Reload this page to refresh your sign-in and security token before retrying.";
        } else if (status === 408) {
            message = "The server timed out receiving the boundary package (HTTP 408). Check Boundaries before retrying.";
        } else if (status === 502 || status === 504) {
            message = "The server or proxy did not return an activation confirmation (HTTP " + status + "). " +
                "Check Boundaries before retrying; activation may still have completed.";
        } else if (status === 503) {
            message = "The service is temporarily unavailable (HTTP 503). Check Boundaries and maintenance status before retrying.";
        } else if (status >= 500) {
            message = "The server could not confirm boundary activation (HTTP " + status + "). Check Boundaries before retrying.";
        } else if (status === 0) {
            message = "The boundary upload connection ended without a server response. Check Boundaries before retrying.";
        } else if (status >= 200 && status < 300 && payload.is_valid !== false) {
            message = "The server returned an unexpected response instead of an activation confirmation. Check Boundaries before retrying.";
            reviewCurrent = true;
        } else {
            message = "The server rejected the boundary package (HTTP " + status + "). Check the ZIP package requirements before retrying.";
        }
        return {message: message, reviewCurrent: reviewCurrent};
    }

    function completeUpload(xhr) {
        if (request !== xhr) return;
        if (window.qcAuth && window.qcAuth.handleUnauthorizedXhr &&
                window.qcAuth.handleUnauthorizedXhr(xhr)) {
            redirecting = true;
            request = null;
            setBusy(false);
            return;
        }
        var payload = responsePayload(xhr);
        if (xhr.status >= 200 && xhr.status < 300 && payload.is_valid === true) {
            request = null;
            selected = null;
            picker.clear();
            setBusy(false);
            row.update({state: "completed", label: "Boundary package activated", percent: 100, error: ""});
            showResult("success", payloadMessage(payload) || "Boundary package activated.");
            return;
        }
        var failure = failureResponse(xhr, payload);
        finishFailure(xhr, failure.message, failure.reviewCurrent);
    }

    function upload() {
        if (window.qcMaintenance && window.qcMaintenance.isActive()) return;
        if (request || redirecting) return;
        var error = picker.validate(picker.files());
        if (error) {
            picker.showError(error);
            return;
        }
        if (!selected || !row) return;
        var capacityError = storageError(selected);
        if (capacityError) {
            rejectStorage(capacityError);
            return;
        }
        var xhr = new window.XMLHttpRequest();
        var data = new window.FormData();
        data.append("file", selected);
        request = xhr;
        results.replaceChildren();
        setBusy(true);
        row.update({state: "uploading", label: "Uploading boundary package…", percent: null, error: ""});
        try {
            xhr.open("POST", form.action);
            xhr.responseType = "json";
            // Large packages need time for transfer and server-side validation.
            xhr.timeout = 30 * 60 * 1000;
            xhr.setRequestHeader("Accept", "application/json");
            if (window.qcCsrf) xhr.setRequestHeader("X-CSRFToken", window.qcCsrf.getToken());
            xhr.upload.addEventListener("progress", function (event) {
                if (request !== xhr) return;
                var percent = event.lengthComputable && event.total > 0
                    ? Math.max(0, Math.min(100, Math.floor(event.loaded / event.total * 100))) : null;
                row.update({
                    state: percent === 100 ? "saving" : "uploading",
                    label: percent === 100 ? "Validating boundary package…" : "Uploading boundary package…",
                    percent: percent,
                    error: ""
                });
            });
            xhr.addEventListener("load", function () { completeUpload(xhr); });
            xhr.addEventListener("error", function () {
                finishFailure(xhr, "The boundary upload connection failed. Check Boundaries before retrying; activation may still have completed.", true);
            });
            xhr.addEventListener("timeout", function () {
                finishFailure(xhr, "The upload response timed out. Check Boundaries to see whether activation completed before retrying.", true);
            });
            xhr.addEventListener("abort", function () {
                finishFailure(xhr, "The upload was interrupted. Check Boundaries before retrying if the transfer had finished.", true);
            });
            xhr.send(data);
        } catch (_error) {
            finishFailure(xhr, "The boundary upload could not start. Try again or choose another package.");
        }
    }

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        upload();
    });
})(window, document);
