/* Progress belongs to the explicit maintenance operation, never a GET probe. */
(function(window, document) {
    "use strict";
    var root = document.querySelector("[data-maintenance-control]");
    var form = root && root.querySelector("[data-maintenance-progress]");
    if (!form) return;

    var phase = root.getAttribute("data-phase");
    var generation = Number(root.getAttribute("data-generation"));
    var progress = root.querySelector("[data-progress-status]");
    var indicator = root.querySelector("[data-progress-indicator]");
    var message = root.querySelector("[data-progress-message]");
    var checked = root.querySelector("[data-progress-checked]");
    var problem = root.querySelector("[data-progress-problem]");
    var errorMessage = root.querySelector("[data-progress-error]");
    var retry = root.querySelector("[data-progress-retry]");
    var blockers = root.querySelector("[data-progress-blockers]");
    var timer, controller, deadline, running = false, stopped = false, suspended = false;
    var failures = 0, passes = 0, sequence = 0;

    function showProgress(text, active) {
        if (message) message.textContent = text;
        if (indicator) indicator.hidden = !active;
        if (progress) progress.setAttribute("data-progress-active", active ? "true" : "false");
    }
    function showProblem(text, canRetry) {
        problem.hidden = false;
        errorMessage.textContent = text;
        retry.hidden = !canRetry;
        if (stopped) showProgress("Automatic progress checks are paused.", false);
    }
    function schedule(delay) {
        window.clearTimeout(timer);
        if (!stopped && !suspended) timer = window.setTimeout(checkProgress, delay);
    }
    function connectionFailed() {
        failures += 1;
        if (failures >= 3) stopped = true;
        if (!stopped) showProgress("Reconnecting to check progress…", true);
        showProblem(stopped
            ? "Progress checks could not connect. Maintenance stays on. Try again or reload this page."
            : "The connection was interrupted. Maintenance stays on; retrying automatically…", stopped);
        schedule(10000);
    }
    function pause() {
        sequence += 1;
        window.clearTimeout(timer);
        window.clearTimeout(deadline);
        if (controller) controller.abort();
        controller = null;
        running = false;
    }
    async function checkProgress() {
        if (stopped || suspended || running) return;
        if (document.hidden) { schedule(5000); return; }
        running = true;
        var current = ++sequence;
        controller = new window.AbortController();
        var requestController = controller;
        var requestDeadline = window.setTimeout(function() { requestController.abort(); }, 20000);
        deadline = requestDeadline;
        showProgress(passes >= 3
            ? "Stopping work is taking longer than usual. Checks continue automatically; technical details are available below."
            : "Checking that application requests and QC jobs have stopped…", true);
        try {
            var response = await window.fetch(form.action || window.location.href, {
                method: "POST", body: new window.FormData(form),
                headers: {Accept: "application/json"}, credentials: "same-origin",
                cache: "no-store", signal: requestController.signal
            });
            if (current !== sequence || stopped || suspended) return;
            if (response.redirected || !(response.headers.get("Content-Type") || "").includes("application/json")) {
                stopped = true;
                showProblem("Your session may have expired. Reload this page to sign in and continue. Maintenance stays on.", false);
                return;
            }
            var state = await response.json();
            if (current !== sequence || stopped || suspended) return;
            if (!state || !["off", "stopping", "ready"].includes(state.phase)
                    || !Number.isInteger(state.generation) || state.generation < 0) {
                connectionFailed();
                return;
            }
            if (state.phase !== phase || state.generation !== generation || state.transfer_active) {
                stopped = true;
                showProgress("Status updated. Refreshing this page…", true);
                // A previous control action may have rendered this page from
                // POST. Navigate with GET instead of resubmitting that action.
                window.location.replace(window.location.href.split("#")[0]);
                return;
            }
            if (state.busy) {
                // Lock contention is an expected wait, not a lost connection.
                failures = 0;
                problem.hidden = true;
                showProgress("Another maintenance action is finishing. Checking again shortly…", true);
                schedule(3000);
                return;
            }
            if (!state.poll || (!response.ok && response.status < 500)) {
                stopped = true;
                showProblem(state.error || "Progress checks are paused. Reload this page to see the current status.", false);
                return;
            }
            if (!response.ok) {
                connectionFailed();
                return;
            }
            failures = 0;
            passes += 1;
            problem.hidden = true;
            blockers.replaceChildren();
            (Array.isArray(state.blockers) ? state.blockers : []).forEach(function(text) {
                if (typeof text !== "string") return;
                var item = document.createElement("li");
                item.textContent = text;
                blockers.appendChild(item);
            });
            blockers.hidden = !blockers.children.length;
            if (checked) {
                checked.hidden = false;
                checked.textContent = "Last checked at " + new Date().toLocaleTimeString([], {
                    hour: "2-digit", minute: "2-digit", second: "2-digit"
                }) + ".";
            }
            showProgress(passes >= 3
                ? "Stopping work is taking longer than usual. Checks continue automatically; technical details are available below."
                : "Waiting for work to stop. Progress checks continue automatically…", true);
            schedule(passes >= 12 ? 15000 : 5000);
        } catch (_error) {
            if (current === sequence && !stopped && !suspended) connectionFailed();
        } finally {
            window.clearTimeout(requestDeadline);
            if (current === sequence) {
                controller = null;
                running = false;
            }
        }
    }
    retry.addEventListener("click", function() {
        if (running) return;
        window.clearTimeout(timer);
        stopped = false;
        failures = 0;
        problem.hidden = true;
        checkProgress();
    });
    document.addEventListener("visibilitychange", function() {
        if (document.hidden) {
            pause();
        } else if (!stopped && !suspended) {
            checkProgress();
        }
    });
    window.addEventListener("pagehide", function() {
        suspended = true;
        pause();
    });
    window.addEventListener("pageshow", function(event) {
        if (!event.persisted) return;
        suspended = false;
        if (!stopped) schedule(0);
    });
    showProgress("Stopping work automatically. This page will update when it is finished.", true);
    schedule(1000);
})(window, document);
