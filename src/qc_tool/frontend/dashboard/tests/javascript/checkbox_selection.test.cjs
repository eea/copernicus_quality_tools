"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function selection(inputs, all = {}) {
    const window = {};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,
        "../../static/dashboard/js/shared/checkbox-selection.js"), "utf8"), {window});
    return {all, state: window.QcCheckboxSelection.create({items: () => inputs, all})};
}

test("selection state excludes disabled inputs and keeps select-all's mixed state accurate", () => {
    const inputs = [{checked: true}, {checked: false}, {checked: true, disabled: true}];
    const {all, state} = selection(inputs);
    assert.equal(state.update().count, 1);
    assert.equal(all.checked, false);
    assert.equal(all.indeterminate, true);
    assert.equal(state.setAll(true).count, 2);
    assert.equal(all.checked, true);
    assert.equal(all.indeterminate, false);
    assert.equal(state.clear().count, 0);
    assert.equal(inputs[2].checked, true, "Disabled stored choices are preserved");
});

test("selection refresh reads current page inputs instead of caching old eligibility", () => {
    const inputs = [{checked: true}];
    const {all, state} = selection(inputs);
    assert.equal(state.update().count, 1);
    inputs.push({checked: false});
    assert.equal(state.update().total, 2);
    assert.equal(all.indeterminate, true);
    inputs[0].disabled = true;
    assert.equal(state.update().count, 0);
    inputs.pop();
    assert.equal(state.update().total, 0);
    assert.equal(all.disabled, true);
    assert.equal(all.checked, false);
});

test("independent selections preserve values and never carry choices into another page", () => {
    const first = [{checked: false, value: "signed-token"}];
    const second = [{checked: false, value: "folder/file.zip"}];
    const a = selection(first), b = selection(second);
    a.state.setAll(true);
    assert.equal(b.state.update().count, 0);
    assert.equal(first[0].value, "signed-token");
    assert.equal(second[0].value, "folder/file.zip");
});
