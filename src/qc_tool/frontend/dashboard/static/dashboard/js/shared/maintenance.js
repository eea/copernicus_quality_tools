/* Shared read-only presentation; the server owns admission and authorization. */
(function(window, document) {
    "use strict";
    var config = document.querySelector('meta[name="qc-maintenance"]');
    var active = Boolean(config && config.getAttribute("content") === "on");
    var notice = config && config.getAttribute("data-notice") || "Maintenance in progress. You can browse and download existing data. Changes are temporarily paused.";
    var admin = Boolean(document.querySelector('meta[name="qc-admin"]'));

    function exempt(node) { return node.closest && node.closest("[data-maintenance-exempt]"); }
    function marked(node) { return node.closest && node.closest("[data-maintenance-write]"); }
    function disable(node) {
        if (exempt(node)) return;
        if (node.tagName === "FORM") {
            node.querySelectorAll("button, input, select, textarea").forEach(disable);
            return;
        }
        node.setAttribute("data-maintenance-disabled", "true");
        if ("disabled" in node) node.disabled = true;
        else if (node.tagName === "A") {
            node.setAttribute("aria-disabled", "true");
            node.setAttribute("tabindex", "-1");
        }
    }
    function apply() {
        if (!active) return;
        document.querySelectorAll("[data-maintenance-write]").forEach(disable);
        if (admin) document.querySelectorAll('form[method="post"]').forEach(disable);
    }
    function show(message) {
        document.querySelectorAll("[data-maintenance-banner]").forEach(function(node) { node.hidden = false; });
        document.querySelectorAll("[data-maintenance-message]").forEach(function(node) { node.textContent = message || notice; });
    }
    function activate() {
        var changed = !active;
        active = true;
        show();
        apply();
        if (changed) document.dispatchEvent(new window.CustomEvent("qc:maintenance"));
    }
    function observePayload(payload) {
        if (typeof payload === "string") {
            try { payload = JSON.parse(payload); } catch (_error) { return false; }
        }
        if (payload && (payload.error === "maintenance" || payload.code === "maintenance")) {
            activate();
            return true;
        }
        return false;
    }
    function observeXhr(xhr) {
        if (!xhr) return;
        var header = xhr.getResponseHeader ? xhr.getResponseHeader("X-QC-Maintenance") :
            xhr.headers && xhr.headers.get("X-QC-Maintenance");
        if (header === "on") activate();
        else if (header === "off" && active) show("Maintenance has ended. Reload this page to enable changes.");
        else if (xhr.status === 503) {
            if (window.qcAuth && window.qcAuth.responsePayload) {
                observePayload(window.qcAuth.responsePayload(xhr));
            } else {
                var payload = xhr.responseJSON || xhr.response;
                if (!payload && (!xhr.responseType || xhr.responseType === "text")) {
                    try { payload = xhr.responseText; } catch (_error) { payload = null; }
                }
                observePayload(payload);
            }
        }
    }
    function guard(event) {
        if (!active) return;
        var node = event.target;
        var link = node.closest && node.closest("a");
        if (event.type === "click" && link && !link.hasAttribute("data-maintenance-write")) return;
        var isWrite = marked(node) || (admin && node.closest && node.closest('form[method="post"]'));
        if (!isWrite || exempt(node)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        show();
    }
    document.addEventListener("click", guard, true);
    document.addEventListener("submit", guard, true);
    window.qcMaintenance = {
        isActive: function() { return active; }, apply: apply,
        activate: activate, observeXhr: observeXhr, observeResponse: observeXhr, observePayload: observePayload
    };
    if (active) { show(); apply(); }
    if (window.MutationObserver) {
        new window.MutationObserver(function() { apply(); }).observe(document.body, {childList: true, subtree: true});
    }
})(window, document);
