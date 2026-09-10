"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM, addPicker} = require("./helpers/dom.cjs");

const source = fs.readFileSync(path.join(
    __dirname, "../../static/dashboard/js/features/boundaries/upload.js"
), "utf8");

function boundaryPage({unauthorized = false, openingFails = false} = {}) {
    const {document, window} = createDOM();
    function element(tag, attributes, parent = document.body) {
        const node = document.createElement(tag);
        for (const [name, value] of Object.entries(attributes || {})) node.setAttribute(name, value);
        parent.appendChild(node);
        return node;
    }
    const form = element("form", {id: "boundary-upload-form", "data-success-url": "/boundaries/"});
    form.action = "/boundaries/upload/data/";
    const nativePicker = addPicker(document, form, {id: "boundary-upload"});
    const {input, error} = nativePicker;
    element("ul", {"data-upload-list": ""}, form);
    const submit = element("button", {"data-boundary-submit": ""}, form);
    const cancel = element("a", {"data-upload-idle": "", href: "/boundaries/"}, form);
    const pending = element("p", {"data-upload-pending": "", "data-boundary-hint": "", hidden: ""}, form);
    const result = element("div", {id: "upload-result"}, form);
    element("div", {"data-upload-announcement": ""});
    const rows = [];
    let picker;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared/uploads.js"), "utf8"), {window, document});
    const shared = window.qcUpload;
    window.qcUpload = {
        ...shared,
        createPicker(root, options) {
            picker = shared.createPicker(root, options);
            const setBusy = picker.setBusy;
            picker.setBusy = busy => { picker.busy = busy; setBusy(busy); };
            return picker;
        },
        createFile(list, options) {
            const row = shared.createFile(list, options);
            const update = row.update;
            row.options = options;
            row.updates = [];
            row.update = state => { row.state = {...state}; row.updates.push({...state}); update(state); };
            rows.push(row);
            return row;
        },
    };
    class Events {
        constructor() { this.listeners = {}; }
        addEventListener(name, listener) { this.listeners[name] = listener; }
        fire(name, event = {}) { this.listeners[name]?.(event); }
    }
    const requests = [];
    class Xhr extends Events {
        constructor() {
            super();
            this.upload = new Events();
            this.headers = {};
            this.status = 0;
            requests.push(this);
        }
        open(method, url) {
            if (openingFails) throw new Error("Cannot open request");
            this.method = method;
            this.url = url;
        }
        setRequestHeader(name, value) { this.headers[name] = value; }
        send(data) { this.data = data; }
        respond(status, payload) { this.status = status; this.response = payload; this.fire("load"); }
    }
    window.XMLHttpRequest = Xhr;
    window.FormData = class {
        constructor() { this.entries = []; }
        append(name, value) { this.entries.push([name, value]); }
    };
    window.qcCsrf = {getToken: () => "csrf-fixture"};
    window.qcAuth = {handleUnauthorizedXhr: () => unauthorized};
    vm.runInNewContext(source, {window, document});
    return {
        picker, requests, submit, rows, error, input, cancel, pending,
        list: form.querySelector("[data-upload-list]"),
        select(file = {name: "boundaries.zip", size: 1024}) {
            input.files = [file];
            input.dispatchEvent({type: "change"});
            return file;
        },
        upload() { form.dispatchEvent({type: "submit", preventDefault() {}}); },
        row: () => rows.at(-1),
        feedback: () => result.textContent,
        tone: () => result.children[0]?.className.replace("workspace-notice workspace-notice--", ""),
    };
}

test("selection waits for explicit activation and sends one CSRF-protected multipart request", () => {
    const page = boundaryPage();
    assert.equal(page.submit.disabled, true);
    const file = page.select();
    assert.equal(page.requests.length, 0);
    assert.equal(page.row().state.state, "selected");
    assert.equal(page.submit.disabled, false);
    page.upload();
    page.upload();
    assert.equal(page.requests.length, 1);
    const xhr = page.requests[0];
    assert.equal(xhr.method, "POST");
    assert.equal(xhr.url, "/boundaries/upload/data/");
    assert.equal(xhr.headers["X-CSRFToken"], "csrf-fixture");
    assert.equal(xhr.headers.Accept, "application/json");
    assert.equal(xhr.data.entries[0][0], "file");
    assert.equal(xhr.data.entries[0][1], file);
    assert.equal(page.picker.busy, true);
    assert.equal(page.row().state.percent, null);
    assert.equal(page.cancel.hidden, true);
    assert.equal(page.pending.hidden, false);
});

test("completed transfer means validating until the server confirms activation", () => {
    const page = boundaryPage();
    page.select();
    page.upload();
    const xhr = page.requests[0];
    xhr.upload.fire("progress", {lengthComputable: true, loaded: 1024, total: 1024});
    assert.equal(page.row().state.state, "saving");
    assert.match(page.row().state.label, /Validating boundary package/);
    assert.equal(page.feedback(), "");
    assert.equal(page.submit.disabled, true);
    assert.equal(page.cancel.hidden, true);
    assert.equal(page.pending.hidden, false);
    xhr.respond(200, {is_valid: true, message: "Boundary generation activated."});
    assert.equal(page.row().state.state, "completed");
    assert.equal(page.tone(), "success");
    assert.equal(page.picker.busy, false);
    assert.equal(page.submit.disabled, true);
    assert.equal(page.picker.files().length, 0);
    assert.equal(page.cancel.hidden, false);
    assert.equal(page.pending.hidden, true);
});

test("unknown transfer length stays indeterminate instead of inventing a percentage", () => {
    const page = boundaryPage();
    page.select();
    page.upload();
    page.requests[0].upload.fire("progress", {lengthComputable: false, loaded: 5, total: 0});
    assert.equal(page.row().state.state, "uploading");
    assert.equal(page.row().state.percent, null);
});

test("HTTP failure or rejected package cannot activate the success state", () => {
    for (const [status, payload] of [[200, {is_valid: false}], [500, {is_valid: true}], [200, {is_valid: "true"}], [200, null]]) {
        const page = boundaryPage();
        page.select();
        page.upload();
        page.requests[0].respond(status, payload);
        assert.equal(page.row().state.state, "failed");
        assert.equal(page.tone(), "danger");
        assert.equal(page.picker.busy, false);
        assert.equal(page.submit.disabled, false);
        assert.equal(page.cancel.hidden, false);
        assert.equal(page.pending.hidden, true);
    }
});

test("failed selection remains retryable and late events cannot overwrite the retry", () => {
    const page = boundaryPage();
    page.select();
    page.upload();
    const first = page.requests[0];
    first.respond(400, {is_valid: false, message: "Missing raster directory."});
    assert.equal(page.row().state.error, "Missing raster directory.");
    page.row().options.retry();
    assert.equal(page.requests.length, 2);
    assert.equal(page.row().state.state, "uploading");
    first.respond(200, {is_valid: true});
    first.fire("error");
    assert.equal(page.row().state.state, "uploading");
    assert.equal(page.feedback(), "");
    page.requests[1].respond(200, {is_valid: true});
    assert.equal(page.row().state.state, "completed");
});

test("network error, timeout and abort recover controls without claiming server rollback", () => {
    for (const event of ["error", "timeout", "abort"]) {
        const page = boundaryPage();
        page.select();
        page.upload();
        page.requests[0].upload.fire("progress", {lengthComputable: true, loaded: 1024, total: 1024});
        assert.equal(page.row().state.state, "saving");
        page.requests[0].fire(event);
        assert.equal(page.row().state.state, "failed");
        assert.equal(page.picker.busy, false);
        assert.equal(page.submit.disabled, false);
        assert.match(page.row().state.error, /Check Boundaries/);
        assert.equal(page.tone(), "danger");
        assert.equal(page.feedback(), "Activation could not be confirmed. Review the file message before retrying.");
        assert.equal(page.cancel.hidden, false);
        assert.equal(page.pending.hidden, true);
    }
});

test("authentication redirects cannot produce a late success notice", () => {
    const page = boundaryPage({unauthorized: true});
    page.select();
    page.upload();
    page.requests[0].respond(401, {is_valid: false});
    page.requests[0].respond(200, {is_valid: true});
    page.upload();
    assert.equal(page.feedback(), "");
    assert.equal(page.requests.length, 1);
    assert.equal(page.submit.disabled, true);
});

test("removing a selection prevents submission and clears its file row", () => {
    const page = boundaryPage();
    page.select();
    page.row().options.remove();
    page.upload();
    assert.equal(page.picker.files().length, 0);
    assert.equal(page.submit.disabled, true);
    assert.equal(page.requests.length, 0);
    assert.match(page.error.textContent, /Choose a file/);
});

test("request setup failures recover the picker and allow another attempt", () => {
    const page = boundaryPage({openingFails: true});
    page.select();
    page.upload();
    assert.equal(page.row().state.state, "failed");
    assert.equal(page.picker.busy, false);
    assert.equal(page.submit.disabled, false);
    assert.match(page.row().state.error, /could not start/);
});

test("invalid replacement clears a selected package so it cannot accidentally activate", () => {
    const page = boundaryPage();
    page.select();
    assert.equal(page.list.children.length, 1);
    page.select({name: "wrong.json", size: 10});
    assert.equal(page.list.children.length, 0);
    assert.equal(page.input.files.length, 0);
    assert.equal(page.submit.disabled, true);
    assert.match(page.error.textContent, /Choose .zip files only/);
    page.upload();
    assert.equal(page.requests.length, 0);
});

test("selecting an invalid new file preserves an already confirmed activation", () => {
    const page = boundaryPage();
    page.select();
    page.upload();
    page.requests[0].respond(200, {is_valid: true, message: "Activated"});
    page.select({name: "wrong.json", size: 10});
    assert.equal(page.tone(), "success");
    assert.equal(page.row().state.state, "completed");
    assert.equal(page.requests.length, 1);
});
