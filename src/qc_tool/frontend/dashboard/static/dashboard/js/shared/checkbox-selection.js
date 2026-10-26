/* Page-local checkbox state. Domain actions and announcements stay with callers. */
(function(window) {
    "use strict";

    function create(options) {
        function items() {
            return Array.prototype.slice.call(options.items()).filter(function(input) { return !input.disabled; });
        }
        function snapshot() {
            var available = items();
            var selected = available.filter(function(input) { return input.checked; });
            return {items: available, selected: selected, count: selected.length, total: available.length};
        }
        function update() {
            var state = snapshot();
            if (options.all) {
                options.all.checked = state.total > 0 && state.count === state.total;
                options.all.indeterminate = state.count > 0 && state.count < state.total;
                options.all.disabled = state.total === 0;
            }
            return state;
        }
        function setAll(checked) {
            items().forEach(function(input) { input.checked = checked; });
            return update();
        }
        return {items: items, update: update, setAll: setAll, clear: function() { return setAll(false); }};
    }

    window.QcCheckboxSelection = {create: create};
})(window);
