/* Refresh an entity summary's server-provided state and permitted next action. */
(function (window) {
    "use strict";

    function actionUrl(action) {
        if (!action || !action.url || !action.label) return null;
        try {
            var url = new window.URL(action.url, window.location.href);
            return url.origin === window.location.origin &&
                ["http:", "https:"].indexOf(url.protocol) >= 0 ? url.href : null;
        } catch (_error) {
            return null;
        }
    }

    function updateAction(root, action) {
        var container = root.querySelector("[data-entity-summary-action]");
        var url = actionUrl(action);
        if (!container) return;
        if (!url) {
            if (container.contains(window.document.activeElement)) {
                var heading = root.querySelector("[data-entity-summary-title]");
                if (heading) heading.focus();
            }
            container.replaceChildren();
            container.hidden = true;
            return;
        }
        var link = container.querySelector("a");
        if (!link) {
            link = window.document.createElement("a");
            link.className = "btn btn-primary btn-qc-primary";
            container.appendChild(link);
        }
        link.setAttribute("href", url);
        link.replaceChildren();
        if (action.icon && /^[a-z0-9-]+$/.test(action.icon)) {
            var namespace = "http://www.w3.org/2000/svg";
            var svg = window.document.createElementNS(namespace, "svg");
            var use = window.document.createElementNS(namespace, "use");
            svg.setAttribute("class", "ui-icon");
            svg.setAttribute("aria-hidden", "true");
            svg.setAttribute("focusable", "false");
            use.setAttribute("href", (root.getAttribute("data-icon-sprite") || "") + "#" + action.icon);
            svg.appendChild(use);
            link.appendChild(svg);
        }
        var label = window.document.createElement("span");
        label.textContent = action.label;
        link.appendChild(label);
        container.hidden = false;
    }

    function updateState(root, summary) {
        if (!root || !summary) return;
        var state = root.querySelector("[data-entity-summary-state]");
        var row = root.querySelector("[data-entity-summary-status-row]");
        var label = root.querySelector("[data-entity-summary-status-label]");
        var badge = root.querySelector("[data-entity-summary-status]");
        var status = summary.status;
        if (label) label.textContent = summary.status_label || "Status";
        if (row) row.hidden = !status;
        if (badge && status) {
            // Only update changed text to keep repeated refreshes quiet for
            // screen readers. Labels are text, never rendered HTML.
            if (badge.textContent !== status.label) badge.textContent = status.label;
            badge.setAttribute("data-state", status.value || "");
            badge.setAttribute("data-tone", status.tone || "neutral");
        }
        updateAction(root, summary.action);
        if (state) state.hidden = !status && !actionUrl(summary.action);
    }

    window.QcEntitySummary = {updateState: updateState};
}(window));
