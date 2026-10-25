"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");
const {queuePage, tick} = require("./helpers/queue-page.cjs");
const source = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared/maintenance.js"), "utf8");

function page({active = true, admin = false, phase = "ready"} = {}) {
    const dom = createDOM();
    const {window, document} = dom;
    const node = (tag, attributes = {}, parent = document.body) => {
        const result = document.createElement(tag);
        Object.entries(attributes).forEach(([key, value]) => result.setAttribute(key, value));
        parent.append(result);
        return result;
    };
    const notice = admin ? "Creating users, editing records and other changes are paused. Browsing and downloads remain available." :
        "Maintenance: browsing and downloads remain available.";
    node("meta", {name: "qc-maintenance", content: active ? "on" : "off", "data-notice": notice});
    if (admin) node("meta", {name: "qc-admin", content: "true"});
    const banner = node("div", {"data-maintenance-banner": "", ...(admin ? {"data-maintenance-admin": ""} : {})});
    banner.hidden = !active;
    const title = admin ? node("strong", {"data-maintenance-title": ""}, banner) : null;
    if (title) title.textContent = phase === "stopping" ? "Turning on maintenance" : "Maintenance is on";
    const message = node("span", {"data-maintenance-message": ""}, banner);
    message.textContent = notice;
    const write = node("form", {method: "post", "data-maintenance-write": ""});
    const mutate = node("button", {type: "submit"}, write);
    const detail = node("a", {href: "/deliveries/1/"}, write);
    const filter = node("form", {method: "get"});
    const applyFilter = node("button", {type: "submit"}, filter);
    const exportForm = node("form", {method: "post"});
    const exportButton = node("button", {type: "submit"}, exportForm);
    const controls = node("form", {method: "post", "data-maintenance-exempt": "",
        ...(admin ? {"data-maintenance-disable-form": "", action: "/admin/maintenance/"} : {})}, admin ? banner : document.body);
    const generation = node("input", {type: "hidden", name: "generation", value: "7"}, controls);
    const maintenanceAction = node("button", {type: "submit"}, controls);
    if (admin) maintenanceAction.disabled = !active || phase !== "ready";
    const controlNote = admin ? node("span", {"data-maintenance-control-note": "", hidden: ""}, banner) : null;
    const refresh = admin ? node("a", {"data-maintenance-refresh": "", href: "", hidden: ""}, banner) : null;
    window.CustomEvent = class { constructor(type) { this.type = type; } };
    vm.runInNewContext(source, {window, document});
    return {...dom, banner, title, message, write, mutate, detail, filter, applyFilter, exportForm, exportButton,
        controls, generation, maintenanceAction, controlNote, refresh,
        dispatch(type, target) {
            const event = {type, target, stopImmediatePropagation() { this.stopped = true; }};
            document.dispatchEvent(event);
            return event;
        }};
}

test("maintenance disables explicit writes and keeps filtering, exports and detail navigation", () => {
    const ui = page();
    assert.equal(ui.banner.hidden, false);
    assert.equal(ui.mutate.disabled, true);
    assert.equal(ui.applyFilter.disabled, false);
    assert.equal(ui.exportButton.disabled, false);
    assert.equal(ui.dispatch("submit", ui.write).defaultPrevented, true);
    assert.equal(ui.dispatch("submit", ui.filter).defaultPrevented, undefined);
    assert.equal(ui.dispatch("submit", ui.exportForm).defaultPrevented, undefined);
    assert.equal(ui.dispatch("click", ui.detail).defaultPrevented, undefined);
    assert.equal(ui.detail.getAttribute("href"), "/deliveries/1/");
});

test("native admin mutations are disabled while maintenance controls stay usable", () => {
    const ui = page({admin: true});
    assert.equal(ui.exportButton.disabled, true); // Ordinary native admin POST.
    assert.equal(ui.maintenanceAction.disabled, false);
    assert.equal(ui.dispatch("click", ui.maintenanceAction).defaultPrevented, undefined);
    assert.equal(ui.dispatch("submit", ui.controls).defaultPrevented, undefined);
    assert.equal(ui.applyFilter.disabled, false);
});

test("shared script preserves the Admin stopping status and reviewed ready controls", () => {
    const stopping = page({admin: true, phase: "stopping"});
    assert.equal(stopping.title.textContent, "Turning on maintenance");
    assert.match(stopping.message.textContent, /Creating users, editing records/);
    assert.equal(stopping.maintenanceAction.disabled, true);

    const ready = page({admin: true});
    ready.window.qcMaintenance.observeXhr({status: 200, getResponseHeader: () => "on"});
    assert.equal(ready.controls.hidden, false);
    assert.equal(ready.maintenanceAction.disabled, false);
    assert.equal(ready.generation.getAttribute("value"), "7");
});

test("maintenance ending retires the Admin off form until a fresh page supplies its state", () => {
    const ui = page({admin: true});

    ui.window.qcMaintenance.observeResponse({status: 200, headers: {get: () => "off"}});

    assert.equal(ui.title.textContent, "Maintenance has ended");
    assert.match(ui.message.textContent, /ended.*Reload/);
    assert.equal(ui.controls.hidden, true);
    assert.equal(ui.maintenanceAction.disabled, true);
    assert.equal(ui.refresh.hidden, false);
    assert.equal(ui.controlNote.hidden, false);
    assert.equal(ui.mutate.disabled, true);
    assert.equal(ui.dispatch("submit", ui.write).defaultPrevented, true);
    assert.match(ui.message.textContent, /ended.*Reload/);

    ui.window.qcMaintenance.observeResponse({status: 200, headers: {get: () => "on"}});

    assert.equal(ui.title.textContent, "Maintenance is on");
    assert.equal(ui.controls.hidden, true);
    assert.equal(ui.maintenanceAction.disabled, true);
    assert.match(ui.controlNote.textContent, /Reload/);
});

test("Admin tabs learning about maintenance show its impact without offering a stale off form", () => {
    const ui = page({active: false, admin: true});

    ui.window.qcMaintenance.observeXhr({status: 503, responseJSON: {error: "maintenance"}});

    assert.equal(ui.banner.hidden, false);
    assert.equal(ui.title.textContent, "Maintenance is on");
    assert.match(ui.message.textContent, /Creating users, editing records/);
    assert.equal(ui.controls.hidden, true);
    assert.equal(ui.maintenanceAction.disabled, true);
    assert.equal(ui.generation.getAttribute("value"), "7");
    assert.equal(ui.refresh.hidden, false);
    assert.equal(ui.mutate.disabled, true);
});

test("an existing tab learns maintenance from the next AJAX response and waits for reload after it ends", () => {
    const ui = page({active: false});
    let transitions = 0;
    ui.document.addEventListener("qc:maintenance", () => transitions++);
    assert.equal(ui.mutate.disabled, false);
    ui.window.qcMaintenance.observeXhr({status: 200, getResponseHeader: () => "on"});
    assert.equal(ui.window.qcMaintenance.isActive(), true);
    assert.equal(ui.mutate.disabled, true);
    assert.equal(transitions, 1);
    ui.window.qcMaintenance.observeXhr({status: 503, responseJSON: {error: "maintenance"}});
    assert.equal(transitions, 1);
    ui.window.qcMaintenance.observeXhr({status: 200, getResponseHeader: () => "off"});
    assert.match(ui.message.textContent, /ended.*Reload/);
    assert.equal(ui.mutate.disabled, true);
});

test("fetch responses from browsing exports also update an existing tab", () => {
    const ui = page({active: false});
    ui.window.qcMaintenance.observeResponse({status: 200, headers: {get: () => "on"}});
    assert.equal(ui.mutate.disabled, true);
    assert.equal(ui.exportButton.disabled, false);
});

test("upload queues do not attach or create transports when rendered during maintenance", () => {
    for (const feature of ["products", "deliveries"]) {
        const ui = queuePage(feature, {maintenance: true});
        assert.equal(ui.queue, null);
        ui.choose([{name: feature === "products" ? "one.json" : "one.zip", size: 4}]);
        assert.equal(ui.requests.length, 0);
        assert.equal(ui.transports.length, 0);
    }
});

test("a queued selection cannot start after maintenance begins in an existing tab", async () => {
    const ui = queuePage("products");
    ui.choose([{name: "one.json", size: 4}, {name: "two.json", size: 4}]);
    await tick();
    ui.window.qcMaintenance = {isActive: () => true};
    ui.queue.addAll();
    ui.queue.add(ui.queue.entries[0]);
    assert.equal(ui.requests.length, 0);
    assert.equal(ui.transports.length, 0);
});
