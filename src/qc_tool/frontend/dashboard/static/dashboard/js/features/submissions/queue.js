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

    var selection = window.QcCheckboxSelection.create({
        all: selectAll,
        items: function() { return form.querySelectorAll("[data-submission-select]"); }
    });

    function update() {
        var selected = selection.update().count;
        count.textContent = selected + " selected";
        approve.disabled = openingReview || selected === 0 || Boolean(window.qcMaintenance && window.qcMaintenance.isActive());
        approve.textContent = openingReview ? "Opening review…" :
            "Approve selected" + (selected ? " (" + selected + ")" : "");
        clear.hidden = selected === 0;
        return selected;
    }

    selectAll.addEventListener("change", function () {
        selection.setAll(selectAll.checked);
        update();
    });

    form.addEventListener("change", function (event) {
        if (event.target.hasAttribute("data-submission-select")) update();
    });

    clear.addEventListener("click", function () {
        selection.clear();
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
