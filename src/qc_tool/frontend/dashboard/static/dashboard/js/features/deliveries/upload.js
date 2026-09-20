/* Explicit delivery uploads, checked against this user's existing filenames. */
(function(window, document) {
    "use strict";
    var root = document.getElementById("resumable-upload");
    var ui = window.qcUpload;
    if (!root || !window.Resumable || !ui || !ui.createQueue) return;
    var correctionId = root.dataset.correctionSubmission;
    var correctionFilename = root.dataset.correctionFilename;
    var correctionDeliveryId = Number(root.dataset.correctionDeliveryId);

    function identificationDetail(identification) {
        if (!identification || typeof identification.summary !== "string" || !identification.summary) return "";
        var recognized = identification.parsed_status === "recognized";
        var detail = (recognized ? "Filename details: " : "Detected product: ") + identification.summary;
        if (recognized) detail += " · Unverified until QC";
        if (identification.status === "ambiguous") detail += " · Choose the product when starting QC.";
        return detail;
    }

    function check(entry) {
        if (correctionId && entry.file.name !== correctionFilename) {
            return Promise.resolve({blocked: true,
                label: "Filename must match",
                message: 'Keep the original filename: "' + correctionFilename + '". Choose the corrected ZIP with this exact name.'});
        }
        return new Promise(function(resolve, reject) {
            var xhr = new window.XMLHttpRequest();
            xhr.open("POST", root.dataset.checkUrl);
            xhr.responseType = "json";
            xhr.timeout = 30000;
            xhr.setRequestHeader("Accept", "application/json");
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.setRequestHeader("X-CSRFToken", window.qcCsrf.getToken());
            xhr.addEventListener("load", function() {
                if (window.qcAuth.handleUnauthorizedXhr(xhr)) {
                    var error = new Error("Sign in to check your deliveries.");
                    error.redirecting = true;
                    reject(error);
                    return;
                }
                var payload = xhr.response;
                if (xhr.status !== 200 || !payload || payload.status !== "ok" || !Array.isArray(payload.files) || payload.files.length !== 1 || !payload.files[0] ||
                        payload.files[0].filename !== entry.file.name || typeof payload.files[0].exists !== "boolean") {
                    var error = new Error(payload && payload.message || "Could not check for an existing delivery. Retry to continue.");
                    var blockedLabels = {
                        delivery_name_invalid: "Check the filename",
                        product_not_configured: "Product unavailable",
                        product_permission_denied: "Product access required"
                    };
                    if (payload && Object.prototype.hasOwnProperty.call(blockedLabels, payload.code)) {
                        error.blocked = true;
                        error.label = blockedLabels[payload.code];
                    }
                    reject(error);
                    return;
                }
                var existing = payload.files[0];
                var detail = identificationDetail(existing.identification);
                var canOverwrite = existing.exists && existing.can_overwrite === true && Number.isSafeInteger(existing.delivery_id) && existing.delivery_id > 0;
                if (correctionId && (!canOverwrite || existing.delivery_id !== correctionDeliveryId)) {
                    resolve({blocked: true, detail: detail, message: existing.overwrite_reason || "This submission can no longer receive a correction. Open the original submission to check its current status.",
                        url: existing.url, linkLabel: "View existing delivery"});
                    return;
                }
                resolve({blocked: existing.exists, detail: detail,
                    label: correctionId ? "Ready for correction" : undefined,
                    overwriteKey: canOverwrite ? existing.delivery_id : null,
                    message: canOverwrite ? (correctionId ? "Ready to upload your correction. The rejected submission and its files will stay in your history." : "You have a delivery with this name. Replacing it keeps its history and requires new quality checks.") :
                        existing.overwrite_reason || "You have a delivery with this name. View it or rename this ZIP before uploading.",
                    url: existing.url, linkLabel: "View existing delivery"});
            });
            ["error", "timeout", "abort"].forEach(function(event) {
                xhr.addEventListener(event, function() { reject(new Error("Could not check for an existing delivery. Retry to continue.")); });
            });
            var request = {filenames: [entry.file.name]};
            if (correctionId) request.correction_submission_id = correctionId;
            xhr.send(JSON.stringify(request));
        });
    }

    function send(entry, report) {
        return new Promise(function(resolve, reject) {
            if (!entry.meta.uploadIdentifier || entry.meta.uploadTarget !== entry.overwriteKey) {
                var random = new Uint8Array(16);
                window.crypto.getRandomValues(random);
                entry.meta.uploadIdentifier = "upload-" + Array.from(random, function(value) { return value.toString(16).padStart(2, "0"); }).join("");
                entry.meta.uploadTarget = entry.overwriteKey;
            }
            var overwriting = entry.overwriteKey !== null;
            var settled = false;
            var paused = false;
            var canceling = false;
            var percent = 0;
            var query = overwriting ? {overwrite_delivery_id: entry.overwriteKey} : {};
            if (correctionId) query.correction_submission_id = correctionId;
            var resumable = new window.Resumable({
                target: root.dataset.uploadUrl,
                headers: {"X-CSRFToken": window.qcCsrf.getToken()},
                query: query,
                chunkSize: 5 * 1024 * 1024,
                simultaneousUploads: Number(root.dataset.simultaneousUploads) || 1,
                testChunks: true, throttleProgressCallbacks: 1,
                generateUniqueIdentifier: function() { return entry.meta.uploadIdentifier; }
            });
            function update() {
                if (settled || canceling) return;
                report({state: paused ? "paused" : percent === 100 ? "saving" : "uploading",
                    label: paused ? "Paused" : percent === 100 ? "Saving delivery…" : (correctionId ? "Uploading correction · " : overwriting ? "Uploading replacement · " : "Uploading delivery · ") + percent + "%",
                    percent: percent, controls: controls});
            }
            function fail(error) {
                if (settled) return;
                settled = true;
                reject(error);
            }
            var controls = {
                pause: function() { if (!settled) { paused = true; resumable.pause(); update(); } },
                resume: function() { if (!settled) { paused = false; resumable.upload(); update(); } },
                cancel: function() {
                    if (settled) return;
                    canceling = true;
                    resumable.cancel();
                    var error = new Error("Upload canceled. Use Retry upload to resume this file.");
                    error.canceled = true;
                    fail(error);
                }
            };
            if (!resumable.support) { fail(new Error("This browser cannot upload delivery files.")); return; }
            resumable.on("fileAdded", function() { if (!settled) resumable.upload(); });
            resumable.on("fileProgress", function(file) { if (!settled) { percent = Math.max(0, Math.min(100, Math.floor(file.progress() * 100))); update(); } });
            resumable.on("fileSuccess", function(_file, message) {
                if (settled || canceling) return;
                var payload;
                try { payload = JSON.parse(message); } catch (_error) { payload = null; }
                // Successful resume probes return an empty body. Nonempty
                // responses must carry the endpoint's acknowledgement; an
                // HTML error page must never appear as an uploaded delivery.
                if (message && (!payload || payload.status !== "ok")) {
                    fail(new Error("The server did not confirm this delivery. Retry the upload to confirm it."));
                    return;
                }
                payload = payload || {};
                settled = true;
                if (correctionId) {
                    resolve({label: "Correction uploaded", message: "Run quality checks, then submit this correction for review.",
                        url: payload.delivery_id && root.dataset.setupJobUrl ? root.dataset.setupJobUrl + "?deliveries=" + payload.delivery_id : root.dataset.deliveriesUrl,
                        linkLabel: payload.delivery_id && root.dataset.setupJobUrl ? "Run quality checks" : "Open deliveries to run quality checks"});
                    return;
                }
                resolve({label: overwriting ? "Replaced" : "Uploaded", message: "Ready for quality checks.", url: payload.delivery_id ? root.dataset.deliveriesUrl + "jobs/" + payload.delivery_id + "/" : root.dataset.deliveriesUrl, linkLabel: "View delivery"});
            });
            resumable.on("fileError", function(_file, message) {
                if (settled || canceling) return;
                var error = new Error("The delivery could not be uploaded. Retry the upload.");
                if (window.qcAuth.redirectFromPayload(message)) error.redirecting = true;
                else {
                    var payload;
                    try { payload = JSON.parse(message); } catch (_error) { payload = {}; }
                    if (typeof payload.message === "string") error.message = payload.message;
                    if (["delivery_exists", "overwrite_target_changed", "overwrite_not_allowed", "correction_not_available"].indexOf(payload.code) !== -1) {
                        error.recheck = true;
                        error.url = root.dataset.deliveriesUrl;
                        error.linkLabel = "View your deliveries";
                    }
                }
                fail(error);
            });
            // Vendor complete also fires after errors/cancel; it cannot confirm
            // registration. Only fileSuccess resolves this attempt.
            update();
            resumable.addFile(entry.file);
        });
    }
    window.qcDeliveryUpload = ui.createQueue(root, {
        extensions: ["zip"], check: check, send: send,
        labels: correctionId ? {
            add: "Upload correction", overwrite: "Upload correction", ready: "Ready to upload correction",
            pending: "Uploading correction…", failed: "Correction upload failed", completed: "uploaded", running: "Uploading correction…"
        } : {
            add: "Upload", overwrite: "Replace and upload", addAll: "Upload all", overwriteAll: "Replace and upload all",
            ready: "Ready to upload", pending: "Uploading…", failed: "Upload failed", completed: "uploaded", running: "Uploading…"
        }
    });
    if (correctionId) window.qcDeliveryUpload.picker.input.multiple = false;
})(window, document);
