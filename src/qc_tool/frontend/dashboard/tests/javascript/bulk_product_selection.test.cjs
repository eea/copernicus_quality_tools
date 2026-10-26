"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

function page({selected = [], secondSelector = false, additionalDefinitions = [], headLoad = false} = {}) {
    const {window, document} = createDOM();
    document.readyState = headLoad ? "loading" : "complete";
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,
        "../../static/dashboard/js/shared/checkbox-selection.js"), "utf8"), {window});
    const add = (parent, tag, hook, text = "") => {
        const node = document.createElement(tag);
        node.setAttribute("data-bulk-product-" + hook, "");
        node.textContent = text;
        parent.append(node);
        return node;
    };
    function selector(selection) {
        const root = add(document.body, "div", "selector");
        const value = add(root, "input", "value");
        value.value = JSON.stringify(selection);
        const controls = add(root, "div", "controls");
        controls.hidden = true;
        const search = add(controls, "input", "search");
        const family = add(controls, "select", "family");
        family.value = "";
        const matching = add(controls, "button", "select-matching");
        const all = add(controls, "button", "select-all");
        const clear = add(controls, "button", "clear");
        const status = add(root, "p", "status");
        const empty = add(root, "p", "empty");
        empty.hidden = true;
        const optionList = add(root, "div", "options");
        optionList.hidden = true;
        const definitions = [
            ["clms_euhydro_rivers", "River network"],
            ["clms_euhydro_lakes", "Standing water"],
            ["clms_hrlvlcc_cover", "Land cover"],
            ["other_water", "Water quality"],
            ["clms_euhydro_assigned", "Already assigned", true],
        ].concat(additionalDefinitions);
        const rows = definitions.map(([ident, label, assigned]) => {
            const row = add(optionList, "label", "option");
            const choice = add(row, "input", "choice");
            choice.value = ident;
            choice.checked = Boolean(assigned || selection.includes(ident));
            choice.disabled = Boolean(assigned);
            if (assigned) choice.setAttribute("data-already-assigned", "true");
            const description = document.createElement("span");
            description.textContent = ident + " — " + label;
            row.append(description);
            return {ident, row, choice};
        });
        return {root, value, controls, search, family, matching, all, clear, status, empty, optionList, rows};
    }
    const runScript = () => vm.runInNewContext(fs.readFileSync(path.join(__dirname,
        "../../../accounts/static/accounts/js/admin/bulk-product-select.js"), "utf8"), {window, document});
    if (headLoad) runScript();
    const first = selector(selected);
    const second = secondSelector ? selector([]) : null;
    if (!headLoad) runScript();
    return {
        ...first, second,
        ready() {
            document.readyState = "interactive";
            document.dispatchEvent({type: "DOMContentLoaded"});
        },
        selected: () => JSON.parse(first.value.value),
        filter(query, family = "") {
            first.search.value = query;
            first.search.dispatchEvent({type: "input"});
            first.family.value = family;
            first.root.dispatchEvent({type: "change", target: first.family});
        },
        visible: () => first.rows.filter(item => !item.row.hidden).map(item => item.ident),
    };
}

test("prefix matching and family filtering add only visible unassigned specifications", () => {
    const p = page();
    assert.equal(p.controls.hidden, false);
    p.filter("CLMS_EUHYDRO*");
    assert.deepEqual(p.visible(), ["clms_euhydro_rivers", "clms_euhydro_lakes", "clms_euhydro_assigned"]);

    p.matching.click();

    assert.deepEqual(p.selected(), ["clms_euhydro_rivers", "clms_euhydro_lakes"]);
    assert.equal(p.rows.at(-1).choice.checked, true);
    assert.equal(p.rows.at(-1).choice.disabled, true);
    p.filter("water", "clms_hrlvlcc");
    assert.deepEqual(p.visible(), []);
    assert.equal(p.empty.hidden, false);
    assert.deepEqual(p.selected(), ["clms_euhydro_rivers", "clms_euhydro_lakes"]);
});

test("description search intersects the selected family without clearing earlier choices", () => {
    const p = page();
    p.filter("WATER", "clms_euhydro");
    assert.deepEqual(p.visible(), ["clms_euhydro_lakes"]);
    p.matching.click();
    p.filter("cover", "clms_hrlvlcc");
    p.matching.click();

    assert.deepEqual(p.selected(), ["clms_euhydro_lakes", "clms_hrlvlcc_cover"]);
    p.rows.find(item => item.ident === "clms_hrlvlcc_cover").choice.checked = false;
    p.root.dispatchEvent({type: "change", target: p.rows.find(item => item.ident === "clms_hrlvlcc_cover").choice});
    assert.deepEqual(p.selected(), ["clms_euhydro_lakes"]);
});

test("select all includes filtered-out eligible choices and clear preserves existing assignments", () => {
    const p = page();
    p.filter("nothing matches");
    p.all.click();
    assert.deepEqual(p.selected(), ["clms_euhydro_rivers", "clms_euhydro_lakes", "clms_hrlvlcc_cover", "other_water"]);
    p.clear.click();
    assert.deepEqual(p.selected(), []);
    assert.equal(p.rows.at(-1).choice.checked, true);
    assert.equal(p.rows.at(-1).choice.disabled, true);
    assert.equal(p.rows.slice(0, -1).every(item => !item.choice.checked), true);
});

test("server-rendered choices survive enhancement and selectors keep independent state", () => {
    const p = page({selected: ["clms_hrlvlcc_cover"], secondSelector: true});
    assert.deepEqual(p.selected(), ["clms_hrlvlcc_cover"]);
    p.filter("clms_euhydro*");
    p.matching.click();

    assert.deepEqual(JSON.parse(p.second.value.value), []);
    assert.equal(p.second.rows.slice(0, -1).every(item => !item.choice.checked), true);
    assert.match(p.status.textContent, /3/);
});

test("family choices respect identifier boundaries while typed wildcard prefixes remain explicit", () => {
    const p = page({additionalDefinitions: [["clms_euhydrology_other", "Another water family"]]});
    p.filter("", "clms_euhydro");
    assert.deepEqual(p.visible(), ["clms_euhydro_rivers", "clms_euhydro_lakes", "clms_euhydro_assigned"]);
    p.filter("clms_euhydro*");
    assert.equal(p.visible().includes("clms_euhydrology_other"), true);
    p.filter("CLMS_HRLVLCC*");
    assert.deepEqual(p.visible(), ["clms_hrlvlcc_cover"]);
});

test("head-loaded Admin media initializes after its selector markup arrives", () => {
    const p = page({headLoad: true});
    assert.equal(p.controls.hidden, true);
    assert.equal(p.optionList.hidden, true);
    p.ready();

    assert.equal(p.controls.hidden, false);
    assert.equal(p.optionList.hidden, false);
    p.filter("clms_euhydro*");
    p.matching.click();
    assert.deepEqual(p.selected(), ["clms_euhydro_rivers", "clms_euhydro_lakes"]);

    p.ready();
    assert.equal(p.matching.events.click.length, 1, "Readiness must not bind a second click handler");
    p.clear.click();
    assert.deepEqual(p.selected(), []);
});
