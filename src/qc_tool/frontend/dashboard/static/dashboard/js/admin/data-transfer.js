/* Progressive enhancement for the server-reviewed Admin transfer workflow. */
(function () {
    "use strict";

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
    var timer, controller, activeTimeout;
    var activeRequest = 0;
    var failures = 0;
    var offline = false;
    var message = operation.querySelector("[data-transfer-poll-message]");
    var resume = operation.querySelector("[data-transfer-resume]");
    var lastChecked = operation.querySelector("[data-transfer-last-checked]");
    var runningIndicator = operation.querySelector("[data-transfer-running-indicator]");
    var checkingIndicator = operation.querySelector("[data-transfer-checking-indicator]");
    var progressLabel = operation.querySelector("[data-transfer-progress-label]");
    var progressItems = operation.querySelector("[data-transfer-progress-items]");
    var progressBytes = operation.querySelector("[data-transfer-progress-bytes]");
    var statuses = ["staged", "planned", "queued", "running", "completed", "cancelled", "failed", "recovery_required"];
    function invalidStatus(message) {
        var error = new Error(message);
        error.invalidStatus = true;
        return error;
    }
    function localUrl(value) {
        var url;
        try { url = new URL(value, window.location.href); }
        catch (_) { throw invalidStatus("Transfer URLs must be valid local URLs."); }
        if (url.origin !== window.location.origin || url.username || url.password) {
            throw invalidStatus("Transfer URLs must stay on this site.");
        }
        return url.href;
    }
    function feedback(state, text) {
        operation.dataset.transferPollingState = state;
        if (message && message.textContent !== text) { message.textContent = text; }
        if (runningIndicator) { runningIndicator.hidden = state !== "active"; }
        if (checkingIndicator) { checkingIndicator.hidden = state !== "checking"; }
        if (resume) {
            resume.hidden = state === "active" || state === "checking";
            resume.disabled = inFlight;
        }
    }
    function isOffline() { return window.navigator && window.navigator.onLine === false; }
    function schedule(delay) {
        window.clearTimeout(timer);
        if (!stopped && !leaving && !offline) { timer = window.setTimeout(poll, delay || 3000); }
    }
    function counter(value) {
        return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
    }
    function bytes(value) {
        var units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
        var unit = 0;
        while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
        return (unit ? value.toFixed(1) : String(value)) + " " + units[unit];
    }
    function updateProgress(progress) {
        if (!progress || typeof progress !== "object") { return; }
        if (progressLabel && typeof progress.label === "string" && progress.label.length <= 240 &&
                progressLabel.textContent !== progress.label) {
            progressLabel.textContent = progress.label;
        }
        [[progressItems, "processed_items", "total_items", function (value) { return String(value); }, " items"],
         [progressBytes, "processed_bytes", "total_bytes", bytes, ""]].forEach(function (field) {
            if (!field[0]) { return; }
            var processed = progress[field[1]], total = progress[field[2]];
            var hasProcessed = counter(processed), hasTotal = counter(total) && total > 0;
            field[0].hidden = !hasProcessed && !hasTotal;
            field[0].textContent = (hasProcessed || hasTotal ? field[3](hasProcessed ? processed : 0) : "") +
                (hasTotal ? " / " + field[3](total) : "") + field[4];
        });
    }
    function poll() {
        if (stopped || leaving || inFlight) { return; }
        if (document.hidden) { schedule(); return; }
        if (offline || isOffline()) {
            offline = true;
            feedback("offline", "You are offline. Showing the last reported progress. Updates resume when you reconnect; the server-side transfer is independent of this page.");
            return;
        }
        inFlight = true;
        if (resume) { resume.disabled = true; }
        var requestId = ++activeRequest;
        var requestController = window.AbortController ? new window.AbortController() : null;
        controller = requestController;
        var retryDelay = 3000;
        var timeout;
        var deadline = new Promise(function (_resolve, reject) {
            timeout = window.setTimeout(function () {
                if (requestController) { requestController.abort(); }
                reject(new Error("Transfer status check timed out."));
            }, 15000);
        });
        activeTimeout = timeout;
        var options = {method: "GET", credentials: "same-origin", mode: "same-origin", redirect: "error", cache: "no-store", headers: {"Accept": "application/json"}};
        if (requestController) { options.signal = requestController.signal; }
        function currentRequest() { return !stopped && !leaving && requestId === activeRequest; }
        var request = Promise.resolve().then(function () {
            if (!currentRequest()) { return; }
            return window.fetch(localUrl(operation.dataset.transferStatusUrl), options);
        }).then(function (response) {
            if (!currentRequest()) { return; }
            var contentType = response.headers.get("Content-Type") || "";
            if (!response.redirected && !response.ok && response.status >= 500) {
                throw new Error("Transfer status is temporarily unavailable.");
            }
            if (!response.ok || response.redirected || contentType.split(";")[0].trim().toLowerCase() !== "application/json") {
                throw invalidStatus("Transfer status is unavailable.");
            }
            return Promise.resolve().then(function () { return response.json(); }).catch(function () {
                throw invalidStatus("The transfer status response is invalid.");
            });
        });
        Promise.race([request, deadline]).then(function (current) {
            if (!currentRequest()) { return; }
            if (!current || current.id !== operation.dataset.operationId || statuses.indexOf(current.status) < 0 ||
                    typeof current.runner_active !== "boolean" || typeof current.recoverable !== "boolean" ||
                    typeof current.cancellable !== "boolean") {
                throw invalidStatus("The transfer status response is invalid.");
            }
            failures = 0;
            feedback("active", "Progress updates automatically.");
            if (lastChecked) {
                lastChecked.hidden = false;
                lastChecked.textContent = "Last checked at " + new Date().toLocaleTimeString() + ".";
            }
            updateProgress(current.progress);
            var runnerChanged = String(current.runner_active) !== operation.dataset.runnerActive;
            var recoveryChanged = String(current.recoverable) !== operation.dataset.recoverable;
            var cancellationChanged = String(current.cancellable) !== operation.dataset.cancellable;
            if (current.status !== operation.dataset.transferStatus || runnerChanged || recoveryChanged || cancellationChanged) {
                // A canonical GET avoids resubmitting a rendered POST response.
                var refresh = operation.querySelector("[data-transfer-refresh]");
                if (refresh) {
                    var destination = localUrl(refresh.href);
                    stopped = true;
                    feedback("checking", "The transfer status changed. Opening the latest result…");
                    window.location.replace(destination);
                }
            }
        }).catch(function (error) {
            if (leaving || requestId !== activeRequest) { return; }
            failures += 1;
            stopped = !!error.invalidStatus || failures >= 3;
            retryDelay = Math.min(30000, 3000 * Math.pow(2, failures));
            feedback(stopped ? "paused" : "retrying", stopped ?
                "Automatic updates paused. Showing the last reported progress. Try automatic updates again or refresh status to check the transfer." :
                "Status is temporarily unavailable. Retrying automatically; showing the last reported progress. This does not interrupt the transfer.");
        }).finally(function () {
            window.clearTimeout(timeout);
            if (requestId !== activeRequest) { return; }
            controller = null;
            activeTimeout = null;
            inFlight = false;
            if (resume) { resume.disabled = false; }
            schedule(retryDelay);
        });
    }
    function resumePolling() {
        if (leaving || inFlight) { return; }
        stopped = false;
        failures = 0;
        offline = isOffline();
        window.clearTimeout(timer);
        feedback("checking", "Checking the latest transfer status…");
        poll();
    }
    if (resume) { resume.addEventListener("click", resumePolling); }
    window.addEventListener("offline", function () {
        offline = true;
        activeRequest += 1;
        inFlight = false;
        window.clearTimeout(timer);
        window.clearTimeout(activeTimeout);
        if (controller) { controller.abort(); }
        controller = null;
        feedback("offline", "You are offline. Showing the last reported progress. Updates resume when you reconnect; the server-side transfer is independent of this page.");
    });
    window.addEventListener("online", function () {
        if (!offline || leaving) { return; }
        offline = false;
        resumePolling();
    });
    window.addEventListener("pagehide", function () {
        leaving = true;
        activeRequest += 1;
        inFlight = false;
        window.clearTimeout(timer);
        window.clearTimeout(activeTimeout);
        if (controller) { controller.abort(); }
        controller = null;
    });
    window.addEventListener("pageshow", function (event) {
        if (!event.persisted) { return; }
        // Back/forward cache restores this same JS state. Resume status reads
        // without enqueuing, retrying or cancelling the server-side transfer.
        leaving = false;
        stopped = false;
        failures = 0;
        offline = isOffline();
        poll();
    });
    document.addEventListener("visibilitychange", function () {
        if (!document.hidden && !stopped && !leaving && !inFlight) {
            window.clearTimeout(timer);
            poll();
        }
    });
    schedule();
}());
