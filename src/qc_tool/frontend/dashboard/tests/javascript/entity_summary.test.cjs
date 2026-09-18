"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

const ready = {
    status_label: "Delivery status",
    status: {value: "not_validated", label: "Not validated", tone: "neutral"},
    action: {label: "Run QC", url: "/job/setup/?deliveries=14", icon: "play"},
};

function fixture() {
    const {document, window} = createDOM();
    window.URL = URL;
    window.location = new URL("https://qc.example/deliveries/jobs/14/");
    const root = document.createElement("section");
    root.id = "history-summary";
    root.setAttribute("data-icon-sprite", "/static/dashboard/icons/ui.svg");
    document.body.appendChild(root);
    function element(tag, hook, parent = root) {
        const node = document.createElement(tag);
        node.setAttribute(hook, "");
        parent.appendChild(node);
        return node;
    }
    const title = element("h2", "data-entity-summary-title");
    const state = element("div", "data-entity-summary-state");
    const statusRow = element("dl", "data-entity-summary-status-row", state);
    const label = element("dt", "data-entity-summary-status-label", statusRow);
    const badge = element("span", "data-entity-summary-status", statusRow);
    const action = element("div", "data-entity-summary-action", state);
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared/entity-summary.js"), "utf8"), {window});
    return {document, window, root, title, state, label, badge, action,
        update(summary) { window.QcEntitySummary.updateState(root, summary); }};
}

test("an unvalidated delivery offers the server-authorized first QC action", () => {
    const p = fixture();
    p.update(ready);
    assert.equal(p.label.textContent, "Delivery status");
    assert.equal(p.badge.textContent, "Not validated");
    assert.equal(p.badge.getAttribute("data-tone"), "neutral");
    const link = p.action.querySelector("a");
    assert.equal(link.getAttribute("href"), "https://qc.example/job/setup/?deliveries=14");
    assert.equal(link.textContent, "Run QC");
    assert.equal(link.querySelector("use").getAttribute("href"), "/static/dashboard/icons/ui.svg#play");
    assert.equal(p.action.hidden, false);
});

test("a fresh running state removes a stale action and preserves keyboard focus", () => {
    const p = fixture();
    p.update(ready);
    p.action.querySelector("a").focus();
    p.update({status_label: "Delivery status", status: {value: "running", label: "In queue", tone: "warning"}, action: null});
    assert.equal(p.badge.textContent, "In queue");
    assert.equal(p.badge.getAttribute("data-state"), "running");
    assert.equal(p.action.querySelector("a"), null);
    assert.equal(p.action.hidden, true);
    assert.equal(p.document.activeElement, p.title);
});

test("unchanged refreshes retain the action link and focus", () => {
    const p = fixture();
    p.update(ready);
    const link = p.action.querySelector("a");
    link.focus();
    p.update(ready);
    assert.equal(p.action.querySelector("a"), link);
    assert.equal(p.document.activeElement, link);
});

test("state labels stay literal and unsafe action links are omitted", () => {
    const p = fixture();
    const text = '<img src=x onerror="alert(1)">';
    for (const url of ["javascript:alert(1)", "https://untrusted.example/qc", "//untrusted.example/qc"]) {
        p.update({...ready, status: {...ready.status, label: text}, action: {...ready.action, url}});
        assert.equal(p.badge.textContent, text);
        assert.equal(p.badge.querySelector("img"), null);
        assert.equal(p.action.hidden, true);
        assert.equal(p.action.querySelector("a"), null);
    }
});

test("summaries without state remain quiet and incomplete responses preserve known state", () => {
    const p = fixture();
    p.update({});
    assert.equal(p.state.hidden, true);
    p.update(ready);
    p.update(null);
    assert.equal(p.badge.textContent, "Not validated");
    assert.equal(p.action.hidden, false);
});

test("history refresh takes delivery state from the server, independent of table rows", () => {
    const p = fixture();
    let settings;
    const table = {on() { return this; }};
    p.window.jQuery = () => table;
    p.window.QC_JOB_HISTORY_CONFIG = {summaryId: p.root.id, historyUrl: "/history/?include_delivery=1"};
    p.window.QcDataTableUi = {create(_table, config) { settings = config; }};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/features/jobs/history/table.js"), "utf8"), {window: p.window});
    p.window.QcJobHistory.createTable();
    const rows = [];
    const response = {rows, delivery_summary: ready};
    assert.equal(settings.options.responseHandler(response), rows);
    assert.equal(p.action.hidden, false);
    settings.options.responseHandler({rows, delivery_summary: {
        status_label: "Delivery status", status: {value: "submitted", label: "Submitted", tone: "primary"}, action: null,
    }});
    assert.equal(p.badge.textContent, "Submitted");
    assert.equal(p.action.hidden, true);
});
