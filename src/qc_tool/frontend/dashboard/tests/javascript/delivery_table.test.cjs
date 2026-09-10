"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

const actionGroups = [
    {value: "needs_correction", label: "Review changes"}, {value: "failed", label: "Resolve QC issues"},
    {value: "not_validated", label: "Run QC"}, {value: "passed", label: "Submit"}
];
const workflows = {
    action_required: {label: "Action required", statuses: actionGroups.map(g => g.value)},
    running: {label: "Running now", statuses: ["running"]},
    in_review: {label: "In review", statuses: ["submitted"]},
    completed: {label: "Completed", statuses: ["accepted"]},
    all: {label: "All deliveries", statuses: [...actionGroups.map(g => g.value), "running", "submitted", "accepted"]}
};

function page(url = "http://localhost/deliveries/") {
    const {document} = createDOM();
    const nodes = new Map(), timers = new Map(), refreshes = [];
    let tableOptions, timerId = 0, data = [];
    const tabs = ["action_required", "running", "in_review", "completed", "all"].map(value => ({attributes: {"data-delivery-view": value}, events: {}}));
    const select = {value: "", options: ["", "needs_correction", "failed", "running", "not_validated", "passed", "submitted", "accepted"].map(value => ({value, dataset: {statusLabel: value}}))};
    function node(selector) {
        if (!nodes.has(selector)) {
            const element = document.createElement("div");
            element.addEventListener = function (name, handler) { this.events[name] = handler; };
            element.removeEventListener = function (name) { delete this.events[name]; };
            nodes.set(selector, element);
        }
        return nodes.get(selector);
    }
    const field = node("#delivery-status-field");
    function $(selector) {
        const list = typeof selector !== "string" ? [selector] : selector === "[data-delivery-view]" ? tabs : selector.includes("btSelectItem") ? [] : [node(selector)];
        return {
            attr(name, value) { if (typeof name === "object") list.forEach(n => Object.assign(n.attributes, name)); else if (value === undefined) return list[0]?.attributes[name]; else list.forEach(n => n.attributes[name] = value); return this; },
            prop(name, value) { list.forEach(n => n[name] = value); return this; },
            text(value) { if (value === undefined) return list[0]?.text; list.forEach(n => n.text = value); return this; },
            val(value) { if (value === undefined) return list[0]?.value; list.forEach(n => n.value = value); return this; },
            toggleClass() { return this; }, first() { return this; },
            each(callback) { list.forEach((n, i) => callback.call(n, i)); return this; },
            on(events, selectorOrHandler, handler) { events.split(" ").forEach(event => list.forEach(n => n.events[event] = handler || selectorOrHandler)); return this; },
            bootstrapTable(command, options) {
                if (typeof command === "object") { tableOptions = command; return this; }
                if (command === "getOptions") return tableOptions;
                if (command === "getData") return data;
                if (command === "getSelections") return [];
                if (command === "refreshOptions") Object.assign(tableOptions, options);
                if (command === "refresh") refreshes.push(options);
                return this;
            }
        };
    }
    $.extend = (target, ...values) => Object.assign(target, ...values);
    const table = document.createElement("table"); table.id = "tbl-deliveries";
    const body = document.createElement("tbody"); table.appendChild(body); table.tBodies = [body]; document.body.appendChild(table);
    body.insertBefore = function(child, before) { child.parentNode = this; this.children.splice(this.children.indexOf(before), 0, child); };
    document.getElementById = id => id === "delivery-status-select" ? select : id === "delivery-status-field" ? field :
        id === "delivery-workflow-config" ? {textContent: JSON.stringify(workflows)} :
        id === "delivery-action-groups" ? {textContent: JSON.stringify(actionGroups)} : node("#" + id);
    const toolbar = node("#delivery-table-toolbar");
    for (const [id, hook] of [["delivery-filter-toggle", "toggle"], ["delivery-advanced-filters", "panel"], ["delivery-advanced-summary", "summary"], ["btn-clear-filters", "clear"], ["delivery-filter-search", "search"]]) {
        const element = node("#" + id); element.setAttribute("data-table-filter-" + hook, ""); toolbar.appendChild(element);
    }
    node("#delivery-advanced-filters").appendChild(node("#delivery-filter-aoi"));
    const window = {document, QcDataTableUi: {create(table, config) { table.bootstrapTable(config.options); }, enhance() {}}, jQuery: $, location: {href: url}, history: {replaceState(_a, _b, value) { window.location.href = new URL(value, url).href; }},
        QC_DELIVERIES_CONFIG: {}, setTimeout(callback) { timers.set(++timerId, callback); return timerId; }, clearTimeout(id) { timers.delete(id); }};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared/table-filters.js"), "utf8"), {window});
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/features/deliveries/table.js"), "utf8"), {window, document, URL, URLSearchParams});
    window.QcDeliveryTable.init();
    function change(selector, value) { const n = node(selector); n.value = value; n.events.change.call(n); }
    function tab(value) { const n = tabs.find(n => n.attributes["data-delivery-view"] === value); n.events.click.call(n); }
    function loaded(counts, workflowCounts = {}, rows = [], total = rows.length) {
        data = rows;
        body.replaceChildren();
        rows.forEach((row, index) => {
            const tr = document.createElement("tr"); tr.setAttribute("data-index", index);
            tr.cells = [document.createElement("td"), document.createElement("td")]; tr.cells.forEach(cell => tr.appendChild(cell));
            body.appendChild(tr);
        });
        node("#tbl-deliveries").events["load-success.bs.table"]({}, {total, status_counts: counts, workflow_counts: workflowCounts});
    }
    return {window, document, node, select, field, tabs, change, tab, loaded, timers, body, refreshes, options: () => tableOptions, query: () => window.QcDeliveryTable.exportQuery()};
}

test("default workflow and exports focus on required actions; history remains secondary", () => {
    const p = page();
    assert.equal(p.query().delivery_view, "action_required");
    assert.equal(p.query().delivery_status, "all");
    assert.equal(p.query().sort, "priority");
    assert.equal(p.tabs.find(t => t.attributes["aria-pressed"] === "true").attributes["data-delivery-view"], "action_required");
    p.tab("in_review");
    assert.equal(p.query().delivery_view, "in_review");
    assert.equal(p.field.hidden, true);
    p.tab("completed");
    assert.equal(p.query().delivery_view, "completed");
    assert.equal(p.field.hidden, true);
    assert.match(p.window.location.href, /delivery_view=completed/);
    p.tab("all");
    assert.equal(p.query().delivery_view, "all");
    assert.equal(p.field.hidden, false);
});

test("workflow filters exclude irrelevant statuses and retain a selected empty result", () => {
    const p = page();
    p.loaded({all: 5, submitted: 2, failed: 2, running: 1, passed: 0, not_validated: 0, needs_correction: 0});
    assert.deepEqual(p.select.options.filter(o => !o.hidden).map(o => o.value), ["", "failed"]);
    p.change("#delivery-status-select", "failed");
    assert.equal(p.query().delivery_status, "failed");
    p.loaded({all: 2, submitted: 2, failed: 0});
    assert.equal(p.select.options.find(o => o.value === "failed").hidden, false);
    assert.equal(p.select.value, "failed");
    p.tab("all");
    assert.equal(p.select.options.find(o => o.value === "submitted").hidden, false);
    p.change("#delivery-status-select", "submitted");
    assert.equal(p.select.value, "submitted");
    p.tab("in_review");
    assert.equal(p.query().delivery_status, "all");
});

test("clear filters preserves the workflow and cancels pending search", () => {
    const p = page();
    p.tab("completed");
    p.change("#delivery-filter-product", "Land cover");
    const search = p.node("#delivery-filter-search"); search.value = "old search"; search.events.input.call(search);
    p.node("#btn-clear-filters").events.click();
    assert.equal(p.query().delivery_view, "completed");
    assert.equal(p.query().filter, "");
    assert.equal(p.query().search, "");
    assert.equal(p.timers.size, 0);
});

test("ordering and exports preserve workflow and status filtering", () => {
    const p = page("http://localhost/deliveries/?delivery_status=failed&delivery_view=all");
    p.change("#delivery-sort", "newest");
    assert.equal(p.query().sort, "id");
    assert.equal(p.query().order, "desc");
    assert.equal(p.query().delivery_status, "failed");
    assert.equal(p.query().delivery_view, "all");
    p.change("#delivery-sort", "priority");
    assert.equal(p.query().sort, "priority");
    p.node("#tbl-deliveries").events["sort.bs.table"]({}, "filename", "asc");
    assert.equal(p.node("#delivery-sort").value, "custom");
});

test("inconsistent and legacy links map to usable workflow filters", () => {
    const p = page("http://localhost/deliveries/?delivery_status=attention");
    assert.equal(p.query().delivery_view, "action_required");
    assert.equal(p.query().delivery_status, "all");
    const mismatch = page("http://localhost/deliveries/?delivery_status=failed&delivery_view=completed");
    assert.equal(mismatch.query().delivery_view, "completed");
    assert.equal(mismatch.query().delivery_status, "all");
    assert.equal(page("http://localhost/deliveries/?delivery_status=submitted").query().delivery_view, "in_review");
});

test("action groups mark page boundaries, retain totals and are removed outside the action view", () => {
    const p = page();
    const rows = [{delivery_status:"failed"}, {delivery_status:"failed"}, {delivery_status:"not_validated"}, {delivery_status:"passed"}];
    p.loaded({failed: 21, not_validated: 1, passed: 1}, {action_required: 23, running: 2}, rows);
    const headings = () => p.body.querySelectorAll(".delivery-action-group");
    assert.deepEqual(headings().map(h => h.textContent), ["Resolve QC issues21", "Run QC1", "Submit1"]);
    assert.equal(headings()[0].children[0].colSpan, 2);
    p.node("#tbl-deliveries").events["post-body.bs.table"]();
    assert.equal(headings().length, 3);
    assert.equal(p.node("[data-delivery-view-count='running']").text, 2);
    p.tab("running");
    p.loaded({running: 1}, {running: 1}, [{delivery_status:"running"}]);
    assert.equal(headings().length, 0);
});

test("a workflow transition empties a later page without hiding remaining deliveries or causing retry loops", () => {
    const p = page();
    p.loaded({running: 20}, {running: 20}, [], 20);
    assert.equal(p.refreshes.length, 1);
    assert.equal(p.refreshes[0].pageNumber, 1);
    p.loaded({running: 20}, {running: 20}, [], 20);
    assert.equal(p.refreshes.length, 1);
    p.loaded({running: 0}, {running: 0});
    assert.equal(p.refreshes.length, 1);
});

test("optional filters preserve applied values when collapsed and clear returns focus to search", () => {
    const p = page();
    const toggle = p.node("#delivery-filter-toggle"), panel = p.node("#delivery-advanced-filters");
    const clear = p.node("#btn-clear-filters");
    assert.equal(toggle.attributes["aria-expanded"], "false");
    assert.equal(panel.hidden, true);
    assert.equal(clear.hidden, true);
    toggle.events.click.call(toggle);
    assert.equal(toggle.attributes["aria-expanded"], "true");
    assert.equal(panel.hidden, false);
    p.change("#delivery-filter-product", "Land cover");
    assert.equal(clear.hidden, false);
    assert.equal(p.node("#delivery-advanced-summary").textContent, "Filters (1)");
    p.node("#delivery-filter-aoi").focus();
    panel.events.keydown({key: "Escape", preventDefault() {}});
    assert.equal(p.document.activeElement, toggle);
    assert.equal(panel.hidden, true);
    assert.equal(JSON.parse(p.query().filter).product_description, "Land cover");
    clear.focus(); clear.events.click();
    assert.equal(p.document.activeElement, p.node("#delivery-filter-search"));
    assert.equal(clear.hidden, true);
    assert.equal(p.query().delivery_view, "action_required");
});

test("a linked status filter is visible immediately and sort alone does not expose Clear filters", () => {
    const p = page("http://localhost/deliveries/?delivery_status=failed");
    assert.equal(p.node("#delivery-advanced-filters").hidden, false);
    assert.equal(p.node("#delivery-filter-toggle").attributes["aria-expanded"], "true");
    const unfiltered = page();
    unfiltered.change("#delivery-sort", "newest");
    assert.equal(unfiltered.node("#btn-clear-filters").hidden, true);
});
