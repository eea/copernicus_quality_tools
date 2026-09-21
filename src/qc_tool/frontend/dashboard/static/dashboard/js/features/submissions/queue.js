(function () {
    "use strict";

    var form = document.getElementById("submission-bulk-form");
    if (!form) return;

    var selectAll = document.getElementById("submission-select-all");
    var selectAllControl = document.querySelector("[data-submission-select-all-control]");
    var approve = document.getElementById("submission-approve-selected");
    var count = document.getElementById("submission-selection-count");
    var clear = document.getElementById("submission-clear-selection");
    var openingReview = false;

    if (!selectAll || !approve || !count || !clear) return;

    function eligibleSelections() {
        return Array.prototype.slice.call(form.querySelectorAll("[data-submission-select]"))
            .filter(function (input) { return !input.disabled; });
    }

    function update() {
        var eligible = eligibleSelections();
        var selected = eligible.filter(function (input) { return input.checked; }).length;
        count.textContent = selected + " selected";
        approve.disabled = openingReview || selected === 0;
        approve.textContent = openingReview ? "Opening review…" :
            "Approve selected" + (selected ? " (" + selected + ")" : "");
        selectAll.checked = eligible.length > 0 && selected === eligible.length;
        selectAll.indeterminate = selected > 0 && selected < eligible.length;
        selectAll.disabled = eligible.length === 0;
        clear.hidden = selected === 0;
        return selected;
    }

    selectAll.addEventListener("change", function () {
        eligibleSelections().forEach(function (input) { input.checked = selectAll.checked; });
        update();
    });

    form.addEventListener("change", function (event) {
        if (event.target.hasAttribute("data-submission-select")) update();
    });

    clear.addEventListener("click", function () {
        eligibleSelections().forEach(function (input) { input.checked = false; });
        update();
        selectAll.focus();
    });

    form.addEventListener("submit", function (event) {
        if (openingReview) {
            event.preventDefault();
            return;
        }
        if (!update()) {
            event.preventDefault();
            count.textContent = "Select at least one delivery.";
            return;
        }
        openingReview = true;
        update();
    });

    window.addEventListener("pageshow", function () {
        openingReview = false;
        update();
    });

    if (selectAllControl) selectAllControl.hidden = false;
    update();
}());
