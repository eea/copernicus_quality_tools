/* One specification per request; the shared queue owns individual/batch actions. */
(function(window, document) {
    "use strict";
    var root = document.getElementById("product-definition-upload-card");
    var form = document.getElementById("product-definition-upload");
    if (!root || !form || !window.qcUpload || !window.qcUpload.createQueue || !window.XMLHttpRequest) return;

    function send(entry, report) {
        return new Promise(function(resolve, reject) {
            var xhr = new window.XMLHttpRequest();
            var data = new window.FormData();
            data.append("definition_file", entry.file);
            xhr.open("POST", form.action);
            xhr.responseType = "json";
            xhr.timeout = 120000;
            xhr.setRequestHeader("Accept", "application/json");
            xhr.setRequestHeader("X-CSRFToken", window.qcCsrf.getToken());
            xhr.upload.addEventListener("progress", function(event) {
                var percent = event.lengthComputable && event.total ? Math.floor(event.loaded / event.total * 100) : null;
                report({state: percent === 100 ? "saving" : "uploading", label: percent === 100 ? "Validating specification…" : "Adding specification…", percent: percent === 100 ? null : percent});
            });
            xhr.addEventListener("load", function() {
                if (window.qcAuth.handleUnauthorizedXhr(xhr) || (xhr.responseURL && xhr.responseURL.indexOf("/accounts/login/") !== -1 &&
                        window.qcAuth.redirectFromPayload({code: "authentication_required", login_url: xhr.responseURL}))) {
                    var authError = new Error("Sign in to continue.");
                    authError.redirecting = true;
                    reject(authError);
                    return;
                }
                var payload = xhr.response;
                if (xhr.status >= 200 && xhr.status < 300 && payload && payload.status === "ok" &&
                        typeof payload.created === "boolean" && typeof payload.product_ident === "string" && typeof payload.url === "string") {
                    resolve({label: payload.created ? "Added" : "Already added", message: payload.message, url: payload.url, linkLabel: "View product"});
                } else reject(new Error(payload && typeof payload.message === "string" ? payload.message : "The specification could not be added. Try again."));
            });
            ["error", "timeout", "abort"].forEach(function(event) {
                xhr.addEventListener(event, function() { reject(new Error("The response was interrupted. Retry to confirm whether this specification was added.")); });
            });
            xhr.send(data);
        });
    }
    form.noValidate = true;
    form.addEventListener("submit", function(event) { event.preventDefault(); });
    window.qcProductUpload = window.qcUpload.createQueue(root, {
        extensions: ["json"], maxBytes: Number(form.dataset.maxFileBytes) || 1048576,
        key: function(file) { return file.name.replace(/\.json$/i, "").toLowerCase(); },
        send: send
    });
})(window, document);
