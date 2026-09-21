"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

const source = fs.readFileSync(path.join(__dirname,
    "../../static/dashboard/js/features/submissions/queue.js"), "utf8");

function page({selections = [{}, {}, {disabled: true}], withForm = true} = {}) {
    const {document, window} = createDOM();
    const add = (tag, attributes, parent = document.body) => {
        const node = document.createElement(tag);
        Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, value));
        parent.append(node);
        return node;
    };
    if (!withForm) {
        vm.runInNewContext(source, {document, window});
        return {document, window};
    }

    const form = add("form", {id: "submission-bulk-form"});
    const masterControl = add("label", {"data-submission-select-all-control": "", hidden: ""}, form);
    const master = add("input", {id: "submission-select-all", type: "checkbox"}, masterControl);
    const count = add("span", {id: "submission-selection-count", "aria-live": "polite"}, form);
    const approve = add("button", {id: "submission-approve-selected", type: "submit"}, form);
    const clear = add("button", {id: "submission-clear-selection", type: "button", hidden: ""}, form);
    const inputs = selections.map((selection, index) => {
        const input = add("input", {type: "checkbox", name: "selection", "data-submission-select": ""}, form);
        input.value = "signed-token-" + index;
        input.checked = Boolean(selection.checked);
        input.disabled = Boolean(selection.disabled);
        return input;
    });
    vm.runInNewContext(source, {document, window});

    return {
        document, window, form, masterControl, master, count, approve, clear, inputs,
        check(input, checked) {
            input.checked = checked;
            if (input === master) master.dispatchEvent({type: "change"});
            else form.dispatchEvent({type: "change", target: input});
        },
        submit() {
            const event = {type: "submit"};
            form.dispatchEvent(event);
            return event;
        },
    };
}

test("select all selects only eligible deliveries on this page", () => {
    const p = page();
    assert.equal(p.masterControl.hidden, false);
    assert.equal(p.approve.disabled, true);
    assert.equal(p.count.textContent, "0 selected");
    assert.equal(p.clear.hidden, true);

    p.check(p.master, true);
    assert.deepEqual(p.inputs.map(input => input.checked), [true, true, false]);
    assert.equal(p.count.textContent, "2 selected");
    assert.equal(p.approve.textContent, "Approve selected (2)");
    assert.equal(p.approve.disabled, false);
    assert.equal(p.master.checked, true);
    assert.equal(p.master.indeterminate, false);
    assert.equal(p.clear.hidden, false);

    p.check(p.master, false);
    assert.equal(p.count.textContent, "0 selected");
    assert.equal(p.approve.textContent, "Approve selected");
    assert.equal(p.approve.disabled, true);
});

test("individual selection, mixed state and clearing keep the controls consistent", () => {
    const p = page();
    p.check(p.inputs[0], true);
    assert.equal(p.count.textContent, "1 selected");
    assert.equal(p.master.checked, false);
    assert.equal(p.master.indeterminate, true);

    p.check(p.inputs[1], true);
    assert.equal(p.master.checked, true);
    assert.equal(p.master.indeterminate, false);
    p.check(p.inputs[0], false);
    assert.equal(p.master.indeterminate, true);

    p.clear.click();
    assert.deepEqual(p.inputs.map(input => input.checked), [false, false, false]);
    assert.equal(p.count.textContent, "0 selected");
    assert.equal(p.master.checked, false);
    assert.equal(p.master.indeterminate, false);
    assert.equal(p.clear.hidden, true);
    assert.equal(p.document.activeElement, p.master);
});

test("empty submission is prevented with an actionable message", () => {
    const p = page();
    assert.equal(p.submit().defaultPrevented, true);
    assert.equal(p.count.textContent, "Select at least one delivery.");
    p.check(p.inputs[0], true);
    assert.equal(p.count.textContent, "1 selected");
    assert.equal(p.approve.disabled, false);
});

test("preview submission retains selected tokens and prevents repeated submits", () => {
    const p = page();
    p.check(p.master, true);
    assert.ok(!p.submit().defaultPrevented);
    assert.equal(p.approve.textContent, "Opening review…");
    assert.equal(p.approve.disabled, true);
    assert.deepEqual(p.inputs.filter(input => input.checked && !input.disabled).map(input => input.value),
        ["signed-token-0", "signed-token-1"]);
    assert.equal(p.submit().defaultPrevented, true);
});

test("pageshow restores selection and controls after returning from preview", () => {
    const p = page({selections: [{checked: true}, {}]});
    assert.equal(p.count.textContent, "1 selected");
    assert.equal(p.master.indeterminate, true);
    p.submit();
    p.window.dispatchEvent({type: "pageshow", persisted: true});
    assert.equal(p.approve.disabled, false);
    assert.equal(p.approve.textContent, "Approve selected (1)");
    assert.equal(p.count.textContent, "1 selected");
    assert.equal(p.master.indeterminate, true);
    assert.ok(!p.submit().defaultPrevented);
});

test("disabled selections are never counted, even if already checked", () => {
    const p = page({selections: [{checked: true, disabled: true}]});
    assert.equal(p.count.textContent, "0 selected");
    assert.equal(p.master.disabled, true);
    assert.equal(p.master.checked, false);
    assert.equal(p.approve.disabled, true);
    assert.equal(p.submit().defaultPrevented, true);
});

test("empty pages disable bulk controls and pages without the form need no enhancement", () => {
    const empty = page({selections: []});
    assert.equal(empty.master.disabled, true);
    assert.equal(empty.master.checked, false);
    assert.equal(empty.approve.disabled, true);
    assert.doesNotThrow(() => page({withForm: false}));
});
