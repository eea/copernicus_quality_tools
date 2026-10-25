"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");
const source = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared/navigation.js"), "utf8");

function page({mobile = true, navigation = true} = {}) {
    const {document} = createDOM();
    const add = (tag, attributes, parent = document.body) => {
        const node = document.createElement(tag);
        Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
        parent.append(node);
        return node;
    };
    const header = add("header", {class: "site-header"});
    const toggle = navigation ? add("button", {"data-header-toggle": "", "aria-expanded": "false"}, header) : null;
    if (toggle) toggle.getClientRects = () => mobile ? [{}] : [];
    const profile = add("details", {"data-header-menu": ""}, header);
    Object.defineProperty(profile, "open", {
        get() { return this.hasAttribute("open"); },
        set(value) { if (value) this.setAttribute("open", ""); else this.removeAttribute("open"); },
    });
    const summary = add("summary", {}, profile);
    const setting = add("a", {href: "/settings/"}, profile);
    const outside = add("main", {});
    // The small shared DOM double supports one attribute selector at a time.
    const select = document.querySelectorAll.bind(document);
    document.querySelectorAll = selector => selector === "details[data-header-menu][open]"
        ? select("details[data-header-menu]").filter(menu => menu.open) : select(selector);
    vm.runInNewContext(source, {document});
    const event = (type, target, extra = {}) => {
        const event = {type, target, ...extra};
        document.dispatchEvent(event);
        return event;
    };
    return {document, header, toggle, profile, summary, setting, outside, event};
}

test("mobile navigation toggles its announced state and closes on outside click", () => {
    const ui = page();
    assert.equal(ui.header.hasAttribute("data-navigation-ready"), true);
    ui.toggle.click();
    assert.equal(ui.toggle.getAttribute("aria-expanded"), "true");
    ui.event("click", ui.setting);
    assert.equal(ui.toggle.getAttribute("aria-expanded"), "true");
    ui.event("click", ui.outside);
    assert.equal(ui.toggle.getAttribute("aria-expanded"), "false");
    ui.toggle.click();
    ui.toggle.click();
    assert.equal(ui.toggle.getAttribute("aria-expanded"), "false");
});

test("Escape closes Profile first and restores focus before closing mobile navigation", () => {
    const ui = page();
    ui.toggle.click();
    ui.profile.open = true;
    assert.equal(ui.event("keydown", ui.setting, {key: "Escape"}).defaultPrevented, true);
    assert.equal(ui.profile.open, false);
    assert.equal(ui.document.activeElement, ui.summary);
    assert.equal(ui.toggle.getAttribute("aria-expanded"), "true");
    ui.event("keydown", ui.summary, {key: "Escape"});
    assert.equal(ui.toggle.getAttribute("aria-expanded"), "false");
    assert.equal(ui.document.activeElement, ui.toggle);
});

test("outside clicks close Profile and other keys leave it open", () => {
    const ui = page();
    ui.profile.open = true;
    ui.event("keydown", ui.setting, {key: "ArrowDown"});
    ui.event("click", ui.setting);
    assert.equal(ui.profile.open, true);
    ui.event("click", ui.outside);
    assert.equal(ui.profile.open, false);
});

test("Escape never sends desktop focus to a hidden mobile control", () => {
    const ui = page({mobile: false});
    ui.toggle.click(); // A previously expanded menu after a viewport resize.
    ui.setting.focus();
    ui.event("keydown", ui.setting, {key: "Escape"});
    assert.equal(ui.document.activeElement, ui.setting);
    assert.equal(ui.toggle.getAttribute("aria-expanded"), "false");
});

test("sign-in header without navigation needs no toggle enhancement", () => {
    const ui = page({navigation: false});
    assert.equal(ui.header.hasAttribute("data-navigation-ready"), false);
    ui.event("click", ui.outside);
    ui.event("keydown", ui.outside, {key: "Escape"});
});
