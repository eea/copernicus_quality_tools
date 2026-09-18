"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function page({withPlanFilter = false} = {}) {
    const nodes = new Map([
        ["#tbl-products", {}], ["#products-toolbar", {}],
        ["#products-search", {value: ""}], ["#products-live-status", {}]
    ]);
    if (withPlanFilter) nodes.set("#products-plan-filter", {value: ""});
    const operations = [], timers = new Map(), states = [];
    let configuration, filterSettings, rows = [], timerId = 0;
    const text = value => String(value || "").replace(/<[^>]*>/g, "")
        .replace(/&amp;/g, "&").replace(/&quot;/g, '"');

    class Query {
        constructor(items) { this.items = items; this.length = items.length; }
        html(value) { this.items.forEach(item => { item.html = value; }); return this; }
        text(value) {
            if (value === undefined) return this.items.map(item => item.text ?? text(item.html)).join("");
            this.items.forEach(item => { item.text = value; }); return this;
        }
        attr(name) { return this.items[0]?.attrs?.[name]; }
        val(value) {
            if (value === undefined) return this.items[0]?.value;
            this.items.forEach(item => { item.value = value; }); return this;
        }
        prop(name, value) { this.items.forEach(item => { item[name] = value; }); return this; }
        on(name, callback) { this.items.forEach(item => { (item.events ||= {})[name] = callback; }); return this; }
        map(callback) { return {get: () => this.items.map((item, index) => callback.call(item, index))}; }
        find(selector) {
            // Known fixture markup only: the real browser parses server-rendered cells.
            const html = this.items[0]?.html || "";
            const items = [];
            for (const match of html.matchAll(/<(\w+)\b([^>]*)>/g)) {
                const attrs = Object.fromEntries([...match[2].matchAll(/([\w-]+)="([^"]*)"/g)]
                    .map(value => [value[1], text(value[2])]));
                const matches = selector.split(",").some(part => part.trim().startsWith(".")
                    ? (attrs.class || "").split(" ").includes(part.trim().slice(1))
                    : part.trim() === match[1]);
                if (matches) {
                    const start = match.index + match[0].length;
                    const end = html.indexOf("</" + match[1] + ">", start);
                    items.push({attrs, text: text(html.slice(start, end < 0 ? start : end))});
                }
            }
            return new Query(items);
        }
        bootstrapTable(command, value) {
            if (command === "getData") return rows;
            if (command === "getOptions") return configuration.options;
            operations.push([command, value]);
            return this;
        }
    }
    function $(value) {
        if (typeof value === "function") { value(); return; }
        if (value === "<div>") return new Query([{}]);
        return new Query(typeof value === "string" ? (nodes.has(value) ? [nodes.get(value)] : []) : [value]);
    }
    $.trim = value => value.trim();
    $.fn = {bootstrapTable() {}};
    const document = {getElementById: id => nodes.get("#" + id)};
    const window = {
        jQuery: $, document,
        location: {reload() { operations.push(["reload"]); }},
        QcDataTableUi: {create(_table, settings) { configuration = settings; }},
        QcTableFilters: {create(_root, settings) { filterSettings = settings; return {update(state) { states.push(state); }}; }},
        setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
        clearTimeout(id) { timers.delete(id); }
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/features/products/index.js"), "utf8"), {window, document});
    return {
        window, configuration, operations, nodes, states,
        clear: () => filterSettings.onClear(),
        show(nextRows) { rows = nextRows; for (const callback of timers.values()) callback(); timers.clear(); }
    };
}

function row(name, ident, plan) {
    return {description: '<div class="product-table__identity" data-plan-label="' + plan + '">' +
        '<a class="product-table__title">' + name + '</a><code class="product-table__ident">' + ident + '</code>' +
        '<span>Review delivery plan</span></div>'};
}

test("search and plan filters use product identity after removing redundant status columns", () => {
    const p = page({withPlanFilter: true});
    const land = row("Land &amp; cover", "clc2024", "Draft");
    const water = row("Water", "water-2024", "Not defined");
    const search = p.configuration.options.customSearch;
    assert.deepEqual([...search([land, water], "CLC2024", {plan: "Draft"})], [land]);
    assert.equal(search([land, water], "", {plan: "Not defined"})[0], water);
    assert.equal(search([land, water], "land & cover", {plan: "Not defined"}).length, 0);
    assert.equal(search([land, water], "delivery plan", {}).length, 0);
});

test("single-plan catalogs work without a filter control and retain accessible results feedback", () => {
    const p = page();
    p.show([row("Land", "clc2024", "Draft")]);
    assert.equal(p.configuration.options.showColumns, true);
    assert.equal(p.configuration.options.showRefresh, true);
    assert.equal(p.nodes.get("#products-toolbar").hidden, false);
    assert.equal(p.nodes.get("#products-live-status").text, "One product shown.");
    p.nodes.get("#products-search").value = "missing";
    p.clear();
    assert.deepEqual(p.operations.map(operation => operation[0]), ["filterBy", "resetSearch"]);
    p.show([]);
    assert.match(p.nodes.get("#products-live-status").text, /No products match/);
    p.configuration.options.onRefresh();
    assert.equal(p.operations.at(-1)[0], "reload");
});

test("exports project product identity and typed coverage instead of rendered cells", () => {
    const p = page();
    const values = p.configuration.exports.values;
    assert.equal(values.description(row("Land &amp; cover", "clc2024", "Draft").description), "Land & cover · clc2024");
    assert.equal(values.declared_expected('<span class="product-table__metric">55</span><span>Provisional scope</span>'), 55);
    assert.equal(values.declared_expected('<span>Not defined</span>'), null);
    assert.equal(values.completion_percentage('<strong>3 / 4</strong><progress value="75" max="100"></progress>'), 75);
    assert.equal(values.completion_percentage('<span>Awaiting approval</span>'), null);
    assert.equal(values.actions, undefined);
});

test("metric sorting ranks accepted coverage by percentage and handles missing scope", () => {
    const p = page();
    assert.ok(p.window.productMetricSorter('<progress max="100" value="75"></progress>', '<progress max="100" value="25"></progress>') > 0);
    assert.ok(p.window.productMetricSorter('<span>Not defined</span>', '<span class="product-table__metric">0</span>') < 0);
});
