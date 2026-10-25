/* Feedback for admitted native Admin form submissions. The server owns actions. */
(function (window, document) {
    "use strict";

    var pendingForms = new Map();

    function restoreAttribute(node, name, value) {
        if (value === null) { node.removeAttribute(name); }
        else { node.setAttribute(name, value); }
    }
    function spinner() {
        var node = document.createElement("span");
        node.className = "qc-admin-spinner";
        node.setAttribute("aria-hidden", "true");
        return node;
    }
    function reset(form, state) {
        if (pendingForms.get(form) !== state) { return; }
        pendingForms.delete(form);
        restoreAttribute(form, "data-admin-pending", state.adminPending);
        restoreAttribute(form, "data-transfer-pending", state.transferPending);
        if (state.action) {
            if (state.content) { state.action.replaceChildren.apply(state.action, state.content); }
            restoreAttribute(state.action, "aria-disabled", state.disabled);
            restoreAttribute(state.action, "aria-busy", state.busy);
            state.action.classList.toggle("qc-admin-action-pending", state.pendingClass);
        }
        if (state.createdStatus) { state.status.remove(); }
        else {
            state.status.replaceChildren.apply(state.status, state.statusContent);
            state.status.hidden = state.statusHidden;
            restoreAttribute(state.status, "role", state.statusRole);
            restoreAttribute(state.status, "aria-live", state.statusLive);
            state.status.classList.toggle("qc-admin-pending-status", state.statusClass);
        }
    }

    // A delegated bubble listener runs after form-specific validation and the
    // shared maintenance capture guard, including on forms added dynamically.
    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (!form || form.tagName !== "FORM" ||
                (!form.hasAttribute("data-admin-pending-message") && !form.hasAttribute("data-transfer-pending-message"))) { return; }
        if (event.defaultPrevented) { return; }
        if (pendingForms.has(form)) { event.preventDefault(); return; }
        var action = event.submitter || form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
        if (action && action.disabled) { return; }
        // Native submissions are already validated. This also leaves synthetic
        // submit events alone when they would fail the same browser validation.
        if (!form.noValidate && !(action && action.formNoValidate) &&
                typeof form.checkValidity === "function" && !form.checkValidity()) { return; }
        var status = form.querySelector("[data-admin-pending-status], [data-transfer-pending-status]");
        var state = {
            action: action,
            adminPending: form.getAttribute("data-admin-pending"),
            transferPending: form.getAttribute("data-transfer-pending"),
            createdStatus: !status
        };
        if (!status) { status = document.createElement("p"); form.appendChild(status); }
        state.status = status;
        state.statusContent = Array.prototype.slice.call(status.childNodes);
        state.statusHidden = status.hidden;
        state.statusRole = status.getAttribute("role");
        state.statusLive = status.getAttribute("aria-live");
        state.statusClass = status.classList.contains("qc-admin-pending-status");
        pendingForms.set(form, state);
        form.setAttribute("data-admin-pending", "true");
        if (form.hasAttribute("data-transfer-pending-message")) { form.setAttribute("data-transfer-pending", "true"); }
        if (action) {
            state.disabled = action.getAttribute("aria-disabled");
            state.busy = action.getAttribute("aria-busy");
            state.pendingClass = action.classList.contains("qc-admin-action-pending");
            if (action.tagName === "BUTTON") {
                // Preserve the actual nodes, including icons and their handlers,
                // so Back restores the complete control rather than plain text.
                state.content = Array.prototype.slice.call(action.childNodes);
                action.replaceChildren(spinner(), document.createTextNode(" " +
                    (form.dataset.adminPendingLabel || form.dataset.transferPendingLabel || "Please wait…")));
            }
            // Disabling a submitter, or changing an input's value, would remove
            // or alter its action=value in the native POST. Keep both intact.
            action.setAttribute("aria-disabled", "true");
            action.setAttribute("aria-busy", "true");
            action.classList.add("qc-admin-action-pending");
        }
        status.classList.add("qc-admin-pending-status");
        status.setAttribute("role", "status");
        status.setAttribute("aria-live", "polite");
        status.replaceChildren(spinner(), document.createTextNode(" " +
            (form.dataset.adminPendingMessage || form.dataset.transferPendingMessage || "Working. Please wait for the next step.")));
        // Keep the live announcement outside the busy button subtree.
        status.hidden = false;
        // A later document/window guard can still cancel this event. Do not
        // leave its rejected action looking as though work has started.
        Promise.resolve().then(function () {
            if (event.defaultPrevented) { reset(form, state); }
        });
    });

    window.addEventListener("pageshow", function () {
        pendingForms.forEach(function (state, form) { reset(form, state); });
    });
}(window, document));
