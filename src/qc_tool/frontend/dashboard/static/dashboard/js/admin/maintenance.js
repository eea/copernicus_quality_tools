/* Progress belongs to the explicit maintenance operation, never a GET probe. */
(function(window, document) {
    "use strict";
    var root = document.querySelector("[data-maintenance-control]");
    var form = root && root.querySelector("[data-maintenance-progress]");
    if (!form) return;

    var phase = root.getAttribute("data-phase");
    var generation = Number(root.getAttribute("data-generation"));
    var message = root.querySelector("[data-progress-message]");
    var problem = root.querySelector("[data-progress-problem]");
    var errorMessage = root.querySelector("[data-progress-error]");
    var retry = root.querySelector("[data-progress-retry]");
    var blockers = root.querySelector("[data-progress-blockers]");
    var timer, controller, deadline, running = false, stopped = false, failures = 0, passes = 0;

    function showProblem(text, canRetry) {
        problem.hidden = false;
        errorMessage.textContent = text;
        retry.hidden = !canRetry;
    }
    function schedule(delay) {
        if (!stopped) timer = window.setTimeout(checkProgress, delay);
    }
    function connectionFailed() {
        failures += 1;
        if (failures >= 3) stopped = true;
        showProblem(stopped
            ? "Progress checks could not connect. Maintenance stays on. Try again or reload this page."
            : "The connection was interrupted. Maintenance stays on; retrying automatically…", stopped);
        schedule(10000);
    }
    async function checkProgress() {
        if (stopped || running) return;
        if (document.hidden) { schedule(5000); return; }
        running = true;
        controller = new window.AbortController();
        deadline = window.setTimeout(function() { controller.abort(); }, 20000);
        try {
            var response = await window.fetch(form.action || window.location.href, {
                method: "POST", body: new window.FormData(form),
                headers: {Accept: "application/json"}, credentials: "same-origin",
                cache: "no-store", signal: controller.signal
            });
            if (stopped) return;
            if (response.redirected || !(response.headers.get("Content-Type") || "").includes("application/json")) {
                stopped = true;
                showProblem("Your session may have expired. Reload this page to sign in and continue. Maintenance stays on.", false);
                return;
            }
            var state = await response.json();
            if (stopped) return;
            if (!state || !["off", "stopping", "ready"].includes(state.phase)) {
                connectionFailed();
                return;
            }
            if (state.phase !== phase || state.generation !== generation || state.transfer_active) {
                stopped = true;
                // A previous control action may have rendered this page from
                // POST. Navigate with GET instead of resubmitting that action.
                window.location.replace(window.location.href.split("#")[0]);
                return;
            }
            if (!state.poll) {
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
            (state.blockers || []).forEach(function(text) {
                var item = document.createElement("li");
                item.textContent = text;
                blockers.appendChild(item);
            });
            blockers.hidden = !blockers.children.length;
            if (passes >= 3) message.textContent = "Stopping work is taking longer than usual. Checks continue automatically; technical details are available below.";
            schedule(passes >= 12 ? 15000 : 5000);
        } catch (_error) {
            if (!stopped) connectionFailed();
        } finally {
            window.clearTimeout(deadline);
            controller = null;
            running = false;
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
    window.addEventListener("pagehide", function() {
        stopped = true;
        window.clearTimeout(timer);
        window.clearTimeout(deadline);
        if (controller) controller.abort();
    });
    schedule(1000);
})(window, document);
