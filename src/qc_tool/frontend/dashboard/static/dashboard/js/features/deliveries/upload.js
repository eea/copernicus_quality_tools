/* Explicit delivery additions, checked against this user's existing filenames. */
(function(window, document) {
    "use strict";
    var root = document.getElementById("resumable-upload");
    var ui = window.qcUpload;
    if (!root || !window.Resumable || !ui || !ui.createQueue) return;

    function check(entry) {
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
                    reject(new Error(payload && payload.message || "Could not check your existing deliveries. Retry before adding this file."));
                    return;
                }
                var existing = payload.files[0];
                var canOverwrite = existing.exists && existing.can_overwrite === true && Number.isSafeInteger(existing.delivery_id) && existing.delivery_id > 0;
                resolve({blocked: existing.exists,
                    overwriteKey: canOverwrite ? existing.delivery_id : null,
                    message: canOverwrite ? "You already uploaded this filename. Overwrite replaces its ZIP with this file and requires new quality checks. Previous QC history is retained." :
                        existing.overwrite_reason || "You already uploaded a delivery with this filename. View that delivery or rename this ZIP before adding it.",
                    url: existing.url, linkLabel: "View existing delivery"});
            });
            ["error", "timeout", "abort"].forEach(function(event) {
                xhr.addEventListener(event, function() { reject(new Error("Could not check your existing deliveries. Retry before adding this file.")); });
            });
            xhr.send(JSON.stringify({filenames: [entry.file.name]}));
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
            var resumable = new window.Resumable({
                target: root.dataset.uploadUrl,
                headers: {"X-CSRFToken": window.qcCsrf.getToken()},
                query: overwriting ? {overwrite_delivery_id: entry.overwriteKey} : {},
                chunkSize: 5 * 1024 * 1024,
                simultaneousUploads: Number(root.dataset.simultaneousUploads) || 1,
                testChunks: true, throttleProgressCallbacks: 1,
                generateUniqueIdentifier: function() { return entry.meta.uploadIdentifier; }
            });
            function update() {
                if (settled || canceling) return;
                report({state: paused ? "paused" : percent === 100 ? "saving" : "uploading",
                    label: paused ? "Paused" : percent === 100 ? "Saving delivery…" : (overwriting ? "Uploading replacement · " : "Adding delivery · ") + percent + "%",
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
                // HTML error page must never appear as an added delivery.
                if (message && (!payload || payload.status !== "ok")) {
                    fail(new Error("The server did not confirm this delivery. Retry the upload to confirm it."));
                    return;
                }
                payload = payload || {};
                settled = true;
                resolve({label: overwriting ? "Overwritten" : "Added", message: "Ready for quality checks.", url: payload.delivery_id ? root.dataset.deliveriesUrl + "jobs/" + payload.delivery_id + "/" : root.dataset.deliveriesUrl, linkLabel: "View delivery"});
            });
            resumable.on("fileError", function(_file, message) {
                if (settled || canceling) return;
                var error = new Error("The delivery could not be added. Retry the upload.");
                if (window.qcAuth.redirectFromPayload(message)) error.redirecting = true;
                else {
                    var payload;
                    try { payload = JSON.parse(message); } catch (_error) { payload = {}; }
                    if (typeof payload.message === "string") error.message = payload.message;
                    if (["delivery_exists", "overwrite_target_changed", "overwrite_not_allowed"].indexOf(payload.code) !== -1) {
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
    window.qcDeliveryUpload = ui.createQueue(root, {extensions: ["zip"], check: check, send: send});
})(window, document);
