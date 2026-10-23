/* Progressive enhancement for the server-reviewed Admin transfer workflow. */
(function () {
    "use strict";

    var exportForm = document.querySelector("[data-transfer-export-form]");
    if (exportForm) {
        var accounts = exportForm.querySelector("[data-account-selection]");
        var review = exportForm.querySelector("[data-transfer-review]");
        function updateScope() {
            var scope = exportForm.querySelector('input[name="scope"]:checked');
            if (accounts && scope) {
                accounts.hidden = scope.value !== "selected_accounts";
                // Keep the selection when switching scopes, but do not submit
                // it as part of a complete or all-account export.
                accounts.querySelectorAll("select, input").forEach(function (field) {
                    field.disabled = accounts.hidden;
                });
            }
            if (scope && review) {
                var nativeBackup = scope.value === "database";
                review.disabled = (nativeBackup ? exportForm.dataset.databaseReady : exportForm.dataset.recordsReady) !== "true";
                review.textContent = nativeBackup ? "Review database backup" : "Review export";
                document.querySelectorAll("[data-transfer-profile-warning]").forEach(function (warning) {
                    warning.hidden = (warning.dataset.transferProfileWarning === "database") !== nativeBackup;
                });
            }
        }
        exportForm.addEventListener("change", updateScope);
        updateScope();
    }

    var importForm = document.querySelector("[data-transfer-import-form]");
    if (importForm) {
        var apply = importForm.querySelector("[data-transfer-apply]");
        var dirtyMessage = importForm.querySelector("[data-mapping-dirty]");
        var updateReview = importForm.querySelector("[data-transfer-update-review]");
        var confirmation = importForm.querySelector("[data-transfer-confirmation]");
        importForm.addEventListener("change", function (event) {
            if ((event.target.tagName === "SELECT" || event.target.tagName === "INPUT") &&
                    /^(account(?:_action|_target)?|resolution)_\d+$/.test(event.target.name)) {
                if (apply) { apply.disabled = true; }
                if (dirtyMessage) { dirtyMessage.hidden = false; }
                if (updateReview) { updateReview.hidden = false; }
                if (confirmation) { confirmation.hidden = true; }
            }
        });
    }

    var operation = document.querySelector("[data-transfer-status-url]");
    if (!operation || !window.fetch) { return; }
    var stopped = false;
    var leaving = false;
    var inFlight = false;
    var timer, controller, timeout;
    var message = operation.querySelector("[data-transfer-poll-message]");
    var statuses = ["staged", "planned", "queued", "running", "completed", "cancelled", "failed", "recovery_required"];
    function localUrl(value) {
        var url = new URL(value, window.location.href);
        if (url.origin !== window.location.origin || url.username || url.password) {
            throw new Error("Transfer URLs must stay on this site.");
        }
        return url.href;
    }
    function schedule() {
        if (!stopped) { timer = window.setTimeout(poll, 3000); }
    }
    function poll() {
        if (stopped || inFlight) { return; }
        if (document.hidden) { schedule(); return; }
        inFlight = true;
        controller = window.AbortController ? new window.AbortController() : null;
        timeout = window.setTimeout(function () {
            if (controller) { controller.abort(); }
        }, 15000);
        var options = {method: "GET", credentials: "same-origin", mode: "same-origin", redirect: "error", cache: "no-store", headers: {"Accept": "application/json"}};
        if (controller) { options.signal = controller.signal; }
        Promise.resolve().then(function () {
            if (stopped) { return; }
            return window.fetch(localUrl(operation.dataset.transferStatusUrl), options);
        }).then(function (response) {
            if (stopped) { return; }
            var contentType = response.headers.get("Content-Type") || "";
            if (!response.ok || response.redirected || contentType.split(";")[0].trim().toLowerCase() !== "application/json") {
                throw new Error("Transfer status is unavailable.");
            }
            return response.json();
        }).then(function (current) {
            if (stopped) { return; }
            if (!current || current.id !== operation.dataset.operationId || statuses.indexOf(current.status) < 0 ||
                    typeof current.runner_active !== "boolean" || typeof current.recoverable !== "boolean" ||
                    typeof current.cancellable !== "boolean") {
                throw new Error("The transfer status response is invalid.");
            }
            var runnerChanged = String(current.runner_active) !== operation.dataset.runnerActive;
            var recoveryChanged = String(current.recoverable) !== operation.dataset.recoverable;
            var cancellationChanged = String(current.cancellable) !== operation.dataset.cancellable;
            if (current.status !== operation.dataset.transferStatus || runnerChanged || recoveryChanged || cancellationChanged) {
                stopped = true;
                // A canonical GET avoids resubmitting a rendered POST response.
                var refresh = operation.querySelector("[data-transfer-refresh]");
                if (refresh) { window.location.replace(localUrl(refresh.href)); }
            }
        }).catch(function () {
            if (leaving) { return; }
            stopped = true;
            if (message) { message.textContent = "Automatic updates paused. Refresh status to check progress."; }
        }).finally(function () {
            window.clearTimeout(timeout);
            controller = null;
            inFlight = false;
            schedule();
        });
    }
    window.addEventListener("pagehide", function () {
        leaving = true;
        stopped = true;
        window.clearTimeout(timer);
        window.clearTimeout(timeout);
        if (controller) { controller.abort(); }
    });
    schedule();
}());
