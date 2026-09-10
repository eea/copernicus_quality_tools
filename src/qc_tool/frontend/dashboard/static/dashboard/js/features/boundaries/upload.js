(function (window, document) {
    "use strict";

    var form = document.getElementById("boundary-upload-form");
    if (!form || !window.qcUpload) return;
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
    var picker = window.qcUpload.createPicker(pickerRoot, {
        extensions: ["zip"],
        onSelect: selectFile,
        onInvalid: function () {
            if (!selected) return;
            selected = null;
            row = null;
            list.replaceChildren();
            picker.setSelected(false);
            submit.disabled = true;
        }
    });
    submit.disabled = true;

    function selectFile(files) {
        if (request || redirecting) return;
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
        picker.setBusy(busy || redirecting);
        submit.disabled = busy || !selected || redirecting;
        submit.textContent = busy ? "Uploading and validating…" : "Upload and activate";
    }

    function showResult(tone, message) {
        window.qcUpload.feedback(results, {
            tone: tone, message: message,
            href: tone === "success" ? form.dataset.successUrl : undefined,
            label: "View boundaries"
        });
    }

    function responsePayload(xhr) {
        if (xhr.response && typeof xhr.response === "object") return xhr.response;
        try {
            var payload = JSON.parse(xhr.responseText || "{}");
            return payload && typeof payload === "object" ? payload : {};
        } catch (_error) {
            return {};
        }
    }

    function finishFailure(xhr, message) {
        if (request !== xhr) return;
        request = null;
        setBusy(false);
        row.update({state: "failed", label: "Upload failed", percent: null, error: message});
        showResult("danger", "Activation could not be confirmed. Review the file message before retrying.");
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
            showResult("success", typeof payload.message === "string" ? payload.message : "Boundary package activated.");
            return;
        }
        finishFailure(xhr, typeof payload.message === "string" ? payload.message : "The boundary package could not be uploaded.");
    }

    function upload() {
        if (request || redirecting) return;
        var error = picker.validate(picker.files());
        if (error) {
            picker.showError(error);
            return;
        }
        if (!selected || !row) return;
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
                finishFailure(xhr, "The boundary upload connection failed. Check Boundaries before retrying if the transfer had finished.");
            });
            xhr.addEventListener("timeout", function () {
                finishFailure(xhr, "The upload response timed out. Check Boundaries to see whether activation completed before retrying.");
            });
            xhr.addEventListener("abort", function () {
                finishFailure(xhr, "The upload was interrupted. Check Boundaries if the transfer had finished before trying again.");
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
