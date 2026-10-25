/* Read-only waiting feedback. A failed administrative POST is never replayed. */
(function(window, document) {
    "use strict";
    var panel = document.querySelector("[data-admin-busy-url]");
    if (!panel) return;
    var heading = panel.querySelector("[data-admin-busy-heading]");
    var message = panel.querySelector("[data-admin-busy-message]");
    var spinner = panel.querySelector("[data-admin-busy-spinner]");
    var details = panel.querySelector("[data-admin-busy-details]");
    var retry = panel.querySelector("[data-admin-busy-retry]");
    if (!heading || !message || !spinner || !details || !retry) return;
    var defaultDetailsUrl = details.href, defaultDetailsLabel = details.textContent;
    var timer, deadline, controller, running = false, stopped = false, suspended = false;
    var failures = 0, checks = 0, sequence = 0;
    var endpoint;
    try {
        endpoint = new URL(panel.getAttribute("data-admin-busy-url"), window.location.href);
        if (endpoint.origin !== window.location.origin || endpoint.username || endpoint.password) throw new Error("Invalid status URL");
    } catch (_error) {
        show("Automatic status checks are unavailable. Open maintenance status to check the current action.", false, false);
        return;
    }
    if (!window.fetch || !window.AbortController) {
        show("Automatic status checks are unavailable. Open maintenance status to check the current action.", false, false);
        return;
    }

    function show(text, active, canRetry) {
        message.textContent = text;
        spinner.hidden = !active;
        retry.hidden = !canRetry;
    }
    function schedule(delay) {
        window.clearTimeout(timer);
        if (!stopped && !suspended && !document.hidden) timer = window.setTimeout(check, delay);
    }
    function failed() {
        failures += 1;
        stopped = failures >= 3;
        show(stopped
            ? "Status checks could not connect. Open maintenance status or check again when your connection returns."
            : "Could not check the current action. Retrying automatically; your request will not be repeated.", false, true);
        schedule(Math.min(30000, 3000 * Math.pow(2, failures)));
    }
    async function check() {
        if (stopped || suspended || running || document.hidden) return;
        running = true;
        var current = ++sequence;
        controller = new window.AbortController();
        var requestController = controller;
        var requestDeadline = window.setTimeout(function() { requestController.abort(); }, 10000);
        deadline = requestDeadline;
        function isCurrent() { return current === sequence && !stopped && !suspended && !document.hidden; }
        if (failures) show("Reconnecting to check the current action…", true, false);
        try {
            var response = await window.fetch(endpoint.href, {
                method: "GET", headers: {Accept: "application/json"}, credentials: "same-origin",
                mode: "same-origin", redirect: "error", cache: "no-store", signal: requestController.signal
            });
            if (!isCurrent()) return;
            if (response.redirected || response.status === 401 || response.status === 403 ||
                    (response.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase() !== "application/json") {
                stopped = true;
                show("Your session may have expired. Refresh this page to sign in and check the current action.", false, false);
                return;
            }
            if (!response.ok) { failed(); return; }
            var state = await response.json();
            if (!isCurrent()) return;
            if (!state || typeof state.busy !== "boolean" || !["off", "stopping", "ready"].includes(state.phase) ||
                    typeof state.transfer_active !== "boolean" || typeof state.transfer_url !== "string" || state.transfer_url.length > 2048) {
                failed(); return;
            }
            failures = 0;
            checks += 1;
            details.href = defaultDetailsUrl;
            details.textContent = defaultDetailsLabel;
            if (state.transfer_url) {
                try {
                    var transfer = new URL(state.transfer_url, window.location.href);
                    if (transfer.origin === window.location.origin && !transfer.username && !transfer.password) {
                        details.href = transfer.href;
                        details.textContent = "View current transfer";
                    }
                } catch (_invalidTransferUrl) { /* Keep the reviewed maintenance link. */ }
            }
            if (state.busy || state.phase === "stopping") {
                if (checks >= 40) {
                    stopped = true;
                    show("This is taking longer than expected. Open maintenance status for details, or check again.", false, true);
                    return;
                }
                show(state.busy ? "Another maintenance or database action is running. Checking again automatically."
                    : "QC work is stopping. Open maintenance status to follow progress.", true, false);
                schedule(checks >= 12 ? 15000 : 3000);
            } else {
                stopped = true;
                if (state.transfer_active) {
                    heading.textContent = "A transfer holds maintenance";
                    show("A transfer still holds maintenance. Open its status to continue or recover it before trying another action.", false, false);
                } else {
                    heading.textContent = "Ready to check again";
                    show("The other action has finished. Refresh this page to review the current state before trying again.", false, false);
                }
            }
        } catch (_error) {
            if (isCurrent()) failed();
        } finally {
            window.clearTimeout(requestDeadline);
            if (current === sequence) {
                controller = null;
                deadline = null;
                running = false;
            }
        }
    }
    function pause() {
        sequence += 1;
        window.clearTimeout(timer);
        window.clearTimeout(deadline);
        if (controller) controller.abort();
        controller = null;
        running = false;
    }
    function resume() {
        if (running || suspended || document.hidden) return;
        window.clearTimeout(timer);
        stopped = false;
        failures = 0;
        checks = 0;
        show("Checking the current action…", true, false);
        check();
    }
    retry.addEventListener("click", resume);
    document.addEventListener("visibilitychange", function() {
        if (document.hidden) pause();
        else if (!stopped && !suspended) schedule(0);
    });
    window.addEventListener("pagehide", function() { suspended = true; pause(); });
    window.addEventListener("pageshow", function(event) {
        if (!event.persisted) return;
        suspended = false;
        if (!stopped) schedule(0);
    });
    schedule(1000);
})(window, document);
