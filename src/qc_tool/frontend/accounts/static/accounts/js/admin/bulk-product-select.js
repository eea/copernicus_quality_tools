/* Explicit selections only: filtering never submits or creates product grants. */
(function (window, document) {
    "use strict";
    function enhance() {
        document.querySelectorAll("[data-bulk-product-selector]").forEach(function (root) {
            if (root.hasAttribute("data-bulk-product-enhanced")) return;
            var value = root.querySelector("[data-bulk-product-value]");
            var search = root.querySelector("[data-bulk-product-search]");
            var family = root.querySelector("[data-bulk-product-family]");
            var matching = root.querySelector("[data-bulk-product-select-matching]");
            var all = root.querySelector("[data-bulk-product-select-all]");
            var clear = root.querySelector("[data-bulk-product-clear]");
            var status = root.querySelector("[data-bulk-product-status]");
            var empty = root.querySelector("[data-bulk-product-empty]");
            var options = Array.prototype.slice.call(root.querySelectorAll("[data-bulk-product-option]")).map(function (row) {
                return {row: row, input: row.querySelector("[data-bulk-product-choice]")};
            }).filter(function (option) { return option.input; });
            if (!value || !search || !matching || !all || !clear || !status) return;
            root.setAttribute("data-bulk-product-enhanced", "true");
            var selection = window.QcCheckboxSelection.create({
                items: function() { return options.map(function(option) { return option.input; }); }
            });

            function update() {
                var state = selection.update();
                var visible = state.items.filter(function(input) { return !input.closest("[data-bulk-product-option]").hidden; });
                var assigned = options.filter(function (option) { return option.input.hasAttribute("data-already-assigned"); });
                value.value = JSON.stringify(state.selected.map(function(input) { return input.value; }));
                status.textContent = state.count + " selected · " + visible.length + " matching available · " + assigned.length + " already assigned";
                matching.disabled = visible.length === 0;
                all.disabled = state.total === 0;
                clear.disabled = state.count === 0;
                if (empty) {
                    empty.hidden = options.some(function (option) { return !option.row.hidden; });
                    empty.textContent = options.length ? "No matching specifications." : "No existing specifications are available.";
                }
            }
            function filter() {
                var query = search.value.trim().toLowerCase();
                var prefix = query.endsWith("*");
                if (prefix) query = query.slice(0, -1);
                var group = family ? family.value.toLowerCase() : "";
                options.forEach(function (option) {
                    var ident = option.input.value.toLowerCase();
                    var familyMatches = !group || ident === group || ident.startsWith(group + "_");
                    var queryMatches = !query || (prefix ? ident.startsWith(query) : option.row.textContent.toLowerCase().includes(query));
                    option.row.hidden = !(familyMatches && queryMatches);
                });
                update();
            }
            matching.addEventListener("click", function () {
                selection.items().forEach(function(input) { if (!input.closest("[data-bulk-product-option]").hidden) input.checked = true; });
                update();
            });
            all.addEventListener("click", function () {
                selection.setAll(true);
                update();
            });
            clear.addEventListener("click", function () {
                selection.clear();
                update();
            });
            root.addEventListener("change", function (event) {
                if (event.target === family) filter();
                else if (event.target.matches("[data-bulk-product-choice]")) update();
            });
            search.addEventListener("input", filter);
            window.addEventListener("pageshow", filter);
            var controls = root.querySelector("[data-bulk-product-controls]");
            if (controls) controls.hidden = false;
            var optionList = root.querySelector("[data-bulk-product-options]");
            if (optionList) optionList.hidden = false;
            filter();
        });
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", enhance, {once: true});
    } else {
        enhance();
    }
    document.addEventListener("formset:added", enhance);
}(window, document));
