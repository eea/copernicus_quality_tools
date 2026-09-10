"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

function page() {
    const {window, document} = createDOM();
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared/table-filters.js"), "utf8"), {window});
    function toolbar() {
        const root = document.createElement("div"), nodes = {};
        for (const name of ["search", "toggle", "panel", "summary", "clear"]) {
            const node = document.createElement(name === "toggle" || name === "clear" ? "button" : "div");
            node.setAttribute("data-table-filter-" + name, "");
            root.appendChild(node); nodes[name] = node;
        }
        const input = document.createElement("input"); nodes.panel.appendChild(input);
        document.body.appendChild(root);
        return {root, input, ...nodes};
    }
    return {window, document, toolbar};
}

test("independent toolbars preserve filters, announce active count, and return keyboard focus", () => {
    const p = page(), first = p.toolbar(), second = p.toolbar();
    let cleared = 0;
    const controls = p.window.QcTableFilters.create(first.root, {onClear() { cleared++; controls.update({active: false}); }});
    const other = p.window.QcTableFilters.create(second.root);
    controls.setExpanded(false); other.setExpanded(false);
    controls.update({active: true, count: 2}); other.update({active: false, count: 0});
    assert.equal(first.summary.textContent, "Filters (2)");
    assert.equal(second.summary.textContent, "Filters");
    first.toggle.click();
    assert.equal(first.panel.hidden, false);
    assert.equal(second.panel.hidden, true);
    first.input.value = "AT"; first.input.focus();
    first.panel.dispatchEvent({type: "keydown", key: "Escape"});
    assert.equal(first.panel.hidden, true);
    assert.equal(first.input.value, "AT");
    assert.equal(p.document.activeElement, first.toggle);
    first.clear.focus(); first.clear.click();
    assert.equal(cleared, 1);
    assert.equal(p.document.activeElement, first.search);
    assert.equal(first.clear.hidden, true);
    assert.equal(second.clear.hidden, true);
});

test("initializing twice does not double-bind controls and destroy permits a clean replacement", () => {
    const p = page(), ui = p.toolbar();
    let count = 0;
    const settings = {onClear() { count++; }};
    const controls = p.window.QcTableFilters.create(ui.root, settings);
    assert.equal(p.window.QcTableFilters.create(ui.root, settings), controls);
    ui.clear.click(); assert.equal(count, 1);
    controls.destroy(); ui.clear.click(); assert.equal(count, 1);
    p.window.QcTableFilters.create(ui.root, settings);
    ui.clear.click(); assert.equal(count, 2);
});
