"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

const source = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/admin/action-feedback.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

function page({legacy = false, existingStatus = true, tag = "button", marked = true, valid = true} = {}) {
    const dom = createDOM();
    const {document, window, Element} = dom;
    // The shared DOM double models all original content as child nodes here,
    // allowing node identity/listener restoration to be checked explicitly.
    Object.defineProperty(Element.prototype, "childNodes", {get() { return this.children; }});
    function node(tagName, attrs = {}, parent = document.body) {
        const result = document.createElement(tagName);
        Object.entries(attrs).forEach(([key, value]) => result.setAttribute(key, value));
        parent.append(result);
        return result;
    }
    const prefix = legacy ? "data-transfer-" : "data-admin-";
    const form = node("form", marked ? {
        method: "post", [prefix + "pending-message"]: "Checking the package. Keep this page open.",
        [prefix + "pending-label"]: "Checking…",
    } : {method: "post"});
    form.checkValidity = () => valid;
    const button = node(tag, {type: "submit", name: "action", value: "preview_export"}, form);
    button.name = "action";
    button.value = "preview_export";
    const icon = node("svg", {"aria-hidden": "true"}, button);
    const iconListener = () => {};
    icon.addEventListener("click", iconListener);
    const label = document.createTextNode("Review export");
    button.append(label);
    const status = existingStatus ? node("p", {[prefix + "pending-status"]: "", hidden: ""}, form) : null;
    const statusLabel = status && document.createTextNode("Original feedback");
    if (status) { status.append(statusLabel); }
    vm.runInNewContext(source, {window, document, Promise});
    return {
        ...dom, form, button, icon, iconListener, label, status, statusLabel, node,
        submit(options = {}) {
            const event = {type: "submit", target: form, submitter: button, defaultPrevented: false, ...options};
            document.dispatchEvent(event);
            return event;
        },
        restore(persisted = true) { window.dispatchEvent({type: "pageshow", persisted}); },
    };
}

test("admitted Admin submissions show an accessible spinner and preserve the named POST action", () => {
    const ui = page();
    const event = ui.submit();
    assert.equal(event.defaultPrevented, false);
    assert.equal(ui.form.getAttribute("data-admin-pending"), "true");
    assert.equal(ui.form.getAttribute("aria-busy"), null, "The live announcement remains outside busy subtrees");
    assert.match(ui.button.textContent, /Checking…/);
    assert.equal(ui.button.querySelector(".qc-admin-spinner").getAttribute("aria-hidden"), "true");
    assert.equal(ui.button.getAttribute("aria-busy"), "true");
    assert.equal(ui.button.getAttribute("aria-disabled"), "true");
    assert.equal(ui.button.disabled, false);
    assert.equal(ui.button.name, "action");
    assert.equal(ui.button.value, "preview_export");
    assert.equal(ui.status.hidden, false);
    assert.equal(ui.status.getAttribute("role"), "status");
    assert.equal(ui.status.getAttribute("aria-live"), "polite");
    assert.match(ui.status.textContent, /Checking the package/);
    assert.ok(ui.status.querySelector(".qc-admin-spinner"));
});

test("legacy transfer hooks use the same feedback and do not lose their action value", () => {
    const ui = page({legacy: true});
    ui.submit();
    assert.equal(ui.form.getAttribute("data-transfer-pending"), "true");
    assert.equal(ui.button.value, "preview_export");
    assert.match(ui.status.textContent, /Checking the package/);
    ui.restore();
    assert.equal(ui.form.getAttribute("data-transfer-pending"), null);
    assert.equal(ui.form.getAttribute("data-admin-pending"), null);
});

test("repeated submissions and a different button in the same form cannot submit twice", () => {
    const ui = page();
    const second = ui.node("button", {type: "submit"}, ui.form);
    assert.equal(ui.submit().defaultPrevented, false);
    assert.equal(ui.submit().defaultPrevented, true);
    assert.equal(ui.submit({submitter: second}).defaultPrevented, true);
    assert.equal(second.getAttribute("aria-busy"), null);
});

test("pre-cancelled, invalid, disabled and unmarked submissions never claim work started", () => {
    for (const scenario of ["cancelled", "invalid", "disabled", "unmarked"]) {
        const ui = page({valid: scenario !== "invalid", marked: scenario !== "unmarked"});
        if (scenario === "disabled") { ui.button.disabled = true; }
        ui.submit({defaultPrevented: scenario === "cancelled"});
        assert.equal(ui.form.getAttribute("data-admin-pending"), null, scenario);
        assert.equal(ui.button.querySelector(".qc-admin-spinner"), null, scenario);
        assert.equal(ui.status.hidden, true, scenario);
    }
});

test("a guard cancelling later in event propagation clears pending feedback", async () => {
    const ui = page({existingStatus: false});
    ui.document.addEventListener("submit", event => event.preventDefault());
    assert.equal(ui.submit().defaultPrevented, true);
    await flush();
    assert.equal(ui.form.getAttribute("data-admin-pending"), null);
    assert.equal(ui.button.querySelector("svg"), ui.icon);
    assert.equal(ui.form.querySelector(".qc-admin-pending-status"), null);
});

test("native formnovalidate and novalidate submissions can show their pending feedback", () => {
    for (const bypass of ["form", "button"]) {
        const ui = page({valid: false});
        if (bypass === "form") { ui.form.noValidate = true; }
        else { ui.button.formNoValidate = true; }
        ui.submit();
        assert.equal(ui.form.getAttribute("data-admin-pending"), "true");
    }
});

test("Back and ordinary pageshow restore original icons, node handlers, ARIA and live status", () => {
    for (const persisted of [false, true]) {
        const ui = page();
        ui.button.setAttribute("aria-busy", "false");
        ui.button.setAttribute("aria-disabled", "false");
        ui.status.setAttribute("role", "note");
        ui.status.setAttribute("aria-live", "off");
        ui.submit();
        ui.restore(persisted);
        assert.deepEqual(ui.button.childNodes, [ui.icon, ui.label]);
        assert.deepEqual(ui.icon.events.click, [ui.iconListener]);
        assert.equal(ui.button.getAttribute("aria-busy"), "false");
        assert.equal(ui.button.getAttribute("aria-disabled"), "false");
        assert.equal(ui.button.classList.contains("qc-admin-action-pending"), false);
        assert.equal(ui.status.hidden, true);
        assert.deepEqual(ui.status.childNodes, [ui.statusLabel]);
        assert.equal(ui.status.getAttribute("role"), "note");
        assert.equal(ui.status.getAttribute("aria-live"), "off");
        assert.equal(ui.form.getAttribute("data-admin-pending"), null);
        assert.equal(ui.submit().defaultPrevented, false, "Back leaves the next legitimate submission available");
    }
});

test("input submitters retain their value and use a visible live status for feedback", () => {
    const ui = page({tag: "input", existingStatus: false});
    ui.submit();
    assert.equal(ui.button.value, "preview_export");
    assert.equal(ui.button.getAttribute("value"), "preview_export");
    assert.equal(ui.button.disabled, false);
    const status = ui.form.querySelector(".qc-admin-pending-status");
    assert.ok(status.querySelector(".qc-admin-spinner"));
    assert.equal(status.hidden, false);
    ui.restore();
    assert.equal(ui.form.querySelector(".qc-admin-pending-status"), null);
    assert.equal(ui.button.getAttribute("aria-disabled"), null);
});

test("keyboard submission without a submitter still uses feedback and preserves the default action", () => {
    const ui = page();
    ui.submit({submitter: null});
    assert.equal(ui.button.getAttribute("aria-busy"), "true");
    assert.equal(ui.button.value, "preview_export");
});

test("delegation supports newly added forms and resets all pending forms without replaying actions", () => {
    const ui = page({existingStatus: false});
    const added = ui.node("form", {"data-admin-pending-message": "Saving another setting…"});
    const save = ui.node("button", {type: "submit"}, added);
    save.append(ui.document.createTextNode("Save"));
    ui.submit();
    ui.document.dispatchEvent({type: "submit", target: added, submitter: save});
    assert.equal(added.getAttribute("data-admin-pending"), "true");
    ui.restore();
    assert.equal(ui.form.getAttribute("data-admin-pending"), null);
    assert.equal(added.getAttribute("data-admin-pending"), null);
    assert.equal(save.textContent, "Save");
    assert.equal(added.querySelector(".qc-admin-pending-status"), null);
});
