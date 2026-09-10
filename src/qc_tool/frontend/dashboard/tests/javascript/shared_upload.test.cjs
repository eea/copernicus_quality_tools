"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM, addPicker} = require("./helpers/dom.cjs");
const source = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared/uploads.js"), "utf8");

function setup(options = {}) {
    const dom = createDOM();
    const root = dom.document.createElement("section");
    dom.document.body.append(root);
    const native = addPicker(dom.document, root, {id: "shared", ...options});
    vm.runInNewContext(source, {window: dom.window, document: dom.document});
    return {...dom, ...native, root, ui: dom.window.qcUpload};
}

test("picker is scoped to its instance and rejects wrong type, count, empty and oversized files", () => {
    const page = setup();
    const other = page.document.createElement("section");
    page.document.body.append(other);
    const second = addPicker(page.document, other, {id: "second"});
    let accepted = 0;
    let invalid = 0;
    page.ui.createPicker(page.root, {extensions: ["zip"], maxBytes: 1024, onSelect: () => accepted++, onInvalid: () => invalid++});
    page.ui.createPicker(other, {extensions: ["zip"]});
    for (const files of [[], [{name: "file.json", size: 1}], [{name: "file.zip", size: 0}], [{name: "file.zip", size: 1025}], [{name: "one.zip", size: 1}, {name: "two.zip", size: 1}]]) {
        page.input.files = files;
        page.input.dispatchEvent({type: "change"});
        assert.ok(page.error.textContent);
        assert.equal(page.input.files.length, 0);
        assert.equal(second.error.textContent, "");
    }
    assert.equal(invalid, 5);
    assert.equal(accepted, 0);
    page.input.files = [{name: "valid.ZIP", size: 1024}];
    page.input.dispatchEvent({type: "change"});
    assert.equal(accepted, 1);
    assert.equal(page.error.textContent, "");
    assert.equal(page.input.getAttribute("aria-invalid"), null);
    assert.equal(page.input.getAttribute("aria-describedby"), "shared-hint shared-error");
});

test("dragging nested elements keeps the drop target highlighted until the final leave", () => {
    const page = setup();
    let selected;
    page.ui.createPicker(page.root, {extensions: ["zip"], onSelect: files => { selected = files; }});
    page.picker.dispatchEvent({type: "dragenter", dataTransfer: {types: ["Files"]}});
    page.picker.dispatchEvent({type: "dragenter", dataTransfer: {types: ["Files"]}});
    page.picker.dispatchEvent({type: "dragleave", dataTransfer: {types: ["Files"]}});
    assert.equal(page.picker.classList.contains("is-dragover"), true);
    const file = {name: "file.zip", size: 10};
    page.picker.dispatchEvent({type: "drop", dataTransfer: {files: [file]}});
    assert.equal(page.picker.classList.contains("is-dragover"), false);
    assert.equal(selected[0], file);
    assert.equal(page.input.files[0], file);
});

test("dropping text preserves the selected file and does not report an invalid upload", () => {
    const page = setup();
    let accepted = 0;
    let invalid = 0;
    page.ui.createPicker(page.root, {
        extensions: ["zip"], onSelect: () => accepted++, onInvalid: () => invalid++,
    });
    const file = {name: "selected.zip", size: 10};
    page.input.files = [file];
    page.input.dispatchEvent({type: "change"});
    const dataTransfer = {files: [], types: ["text/plain"]};
    page.picker.dispatchEvent({type: "dragenter", dataTransfer});
    page.picker.dispatchEvent({type: "dragover", dataTransfer});
    page.picker.dispatchEvent({type: "drop", dataTransfer});

    assert.equal(page.input.files.length, 1);
    assert.equal(page.input.files[0], file);
    assert.equal(accepted, 1);
    assert.equal(invalid, 0);
    assert.equal(page.error.textContent, "");
    assert.equal(page.picker.classList.contains("is-dragover"), false);
});

test("server-rendered validation errors mark the enhanced visible chooser invalid", () => {
    const page = setup();
    page.error.textContent = "The specification contains an unknown check.";
    const picker = page.ui.createPicker(page.root, {extensions: ["json"]});

    assert.equal(page.input.hidden, true);
    assert.equal(page.browse.hidden, false);
    assert.equal(page.input.getAttribute("aria-invalid"), "true");
    assert.equal(page.browse.getAttribute("aria-invalid"), "true");
    picker.showError("");
    assert.equal(page.browse.getAttribute("aria-invalid"), null);
});

test("a filename without a dot is not treated as a matching extension", () => {
    const page = setup();
    let accepted = 0;
    const picker = page.ui.createPicker(page.root, {extensions: ["zip"], onSelect: () => accepted++});
    page.input.files = [{name: "zip", size: 10}];
    page.input.dispatchEvent({type: "change"});

    assert.equal(accepted, 0);
    assert.equal(page.input.files.length, 0);
    assert.match(page.error.textContent, /\.zip/);
    assert.equal(picker.validate([{name: "archive.ZIP", size: 10}]), "");
});

test("busy picker blocks changes without disabling native form file submission", () => {
    const page = setup();
    const cancel = page.document.createElement("a");
    cancel.setAttribute("data-upload-idle", "");
    page.root.append(cancel);
    const pending = page.document.createElement("p");
    pending.setAttribute("data-upload-pending", "");
    pending.hidden = true;
    page.root.append(pending);
    let calls = 0;
    const picker = page.ui.createPicker(page.root, {onSelect: () => calls++});
    const file = {name: "original.zip", size: 10};
    page.input.files = [file];
    picker.setBusy(true);
    assert.equal(page.browse.disabled, true);
    assert.equal(page.input.disabled, false);
    assert.equal(cancel.hidden, true);
    assert.equal(pending.hidden, false);
    page.picker.dispatchEvent({type: "drop", dataTransfer: {files: [{name: "new.zip", size: 10}]}});
    assert.equal(page.input.files[0], file);
    page.input.dispatchEvent({type: "change"});
    assert.equal(calls, 0);
    picker.setBusy(false);
    assert.equal(cancel.hidden, false);
    assert.equal(pending.hidden, true);
    page.input.dispatchEvent({type: "change"});
    assert.equal(calls, 1);
});

test("unsupported file assignment keeps the chooser usable and reports a recoverable error", () => {
    const page = setup();
    let rejected = 0;
    const picker = page.ui.createPicker(page.root, {onInvalid: () => rejected++});
    Object.defineProperty(page.input, "files", {get: () => [], set: value => { if (value.length) throw new Error("unsupported"); }});
    page.picker.dispatchEvent({type: "drop", dataTransfer: {files: [{name: "file.zip", size: 1}]}});
    assert.match(page.error.textContent, /Use the file chooser/);
    assert.equal(rejected, 1);
    assert.equal(page.document.activeElement, picker.browse);
});

test("indeterminate status never advertises invented numeric progress and announcements skip percentage changes", () => {
    const page = setup();
    const list = page.document.createElement("ul");
    const announcement = page.document.createElement("div");
    const row = page.ui.createFile(list, {name: "file.zip", size: 10, announcement});
    row.update({state: "uploading", label: "Uploading · 10%", percent: 10});
    const bar = row.element.querySelector('[role="progressbar"]');
    assert.equal(bar.getAttribute("aria-valuenow"), "10");
    const previous = announcement.textContent;
    row.update({state: "uploading", label: "Uploading · 20%", percent: 20});
    assert.equal(announcement.textContent, previous);
    row.update({state: "saving", label: "Validating package…", percent: null});
    assert.equal(bar.hasAttribute("aria-valuenow"), false);
    assert.match(announcement.textContent, /Validating/);
    row.update({state: "completed", label: "Saved", percent: 100});
    assert.equal(bar.getAttribute("aria-valuenow"), "100");
    assert.equal(bar.hasAttribute("data-indeterminate"), false);
});

test("filenames, details and server errors remain text and retries are explicit", () => {
    const page = setup();
    const list = page.document.createElement("ul");
    let retries = 0;
    const content = '<img src=x onerror="bad()">';
    const row = page.ui.createFile(list, {name: content, size: 10, detail: content, retry: () => retries++});
    row.update({state: "failed", label: "Upload failed", percent: null, error: content});
    assert.equal(list.querySelectorAll("img").length, 0);
    assert.equal(row.element.querySelector(".qc-upload-file__error").textContent, content);
    assert.equal(retries, 0);
    row.element.querySelector("[data-upload-retry]").click();
    assert.equal(retries, 1);
    const result = page.document.createElement("div");
    page.ui.feedback(result, {tone: "danger", message: content});
    assert.equal(result.querySelectorAll("img").length, 0);
    assert.equal(result.children[0].getAttribute("role"), "alert");
});

test("keyboard retry keeps focus on the file when its retry button disappears", () => {
    const page = setup();
    const list = page.document.createElement("ul");
    page.root.append(list);
    const row = page.ui.createFile(list, {
        name: "file.zip", size: 10,
        retry: () => row.update({state: "uploading", label: "Uploading", percent: 0})
    });
    row.update({state: "failed", label: "Upload failed", percent: null, error: "Connection lost"});
    const retry = row.element.querySelector("[data-upload-retry]");
    retry.focus();
    retry.click();
    assert.equal(retry.hidden, true);
    assert.equal(page.document.activeElement, row.element);
    assert.equal(row.element.getAttribute("tabindex"), "-1");
});
