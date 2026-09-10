/* Disclosure and clear-filter feedback shared by table page controllers. */
(function (window) {
    "use strict";

    var instances = new WeakMap();

    function create(root, settings) {
        if (instances.has(root)) return instances.get(root);
        var config = settings || {};
        var toggle = root.querySelector("[data-table-filter-toggle]");
        var panel = root.querySelector("[data-table-filter-panel]");
        var summary = root.querySelector("[data-table-filter-summary]");
        var clear = root.querySelector("[data-table-filter-clear]");
        var search = root.querySelector("[data-table-filter-search]");

        function setExpanded(expanded) {
            if (!toggle || !panel) return;
            if (!expanded && panel.contains(window.document.activeElement)) toggle.focus();
            toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
            panel.hidden = !expanded;
        }

        function togglePanel() {
            setExpanded(toggle.getAttribute("aria-expanded") !== "true");
        }

        function closePanel(event) {
            if (event.key === "Escape") {
                setExpanded(false);
                event.preventDefault();
            }
        }

        function clearFilters() {
            // Move focus before the controller hides the clear button.
            if (search) search.focus();
            if (config.onClear) config.onClear();
        }

        function update(state) {
            var count = Number(state.count) || 0;
            if (clear) {
                if (!state.active && window.document.activeElement === clear && search) search.focus();
                clear.hidden = !state.active;
            }
            if (summary) summary.textContent = count ? "Filters (" + count + ")" : "Filters";
            if (toggle) toggle.classList.toggle("has-filters", count > 0);
        }

        if (toggle) toggle.addEventListener("click", togglePanel);
        if (panel) panel.addEventListener("keydown", closePanel);
        if (clear) clear.addEventListener("click", clearFilters);

        var controller = {
            update: update,
            setExpanded: setExpanded,
            destroy: function () {
                if (toggle) toggle.removeEventListener("click", togglePanel);
                if (panel) panel.removeEventListener("keydown", closePanel);
                if (clear) clear.removeEventListener("click", clearFilters);
                instances.delete(root);
            }
        };
        instances.set(root, controller);
        return controller;
    }

    window.QcTableFilters = {create: create};
}(window));
