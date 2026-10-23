"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");
const shared = name => fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared", name), "utf8");

function page({maintenance = false} = {}) {
    const {window, document} = createDOM();
    window.jQuery = undefined;
    const redirects = [];
    const current = new URL("http://localhost:8000/boundaries/upload/?tab=package#upload");
    window.location = {
        href: current.href, protocol: current.protocol, host: current.host,
        pathname: current.pathname, search: current.search, hash: current.hash,
        assign: value => redirects.push(value),
    };
    const create = document.createElement;
    document.createElement = tag => {
        const element = create(tag);
        if (tag === "a") Object.defineProperty(element, "href", {
            set(value) {
                const target = new URL(value, current);
                element.protocol = target.protocol;
                element.host = target.host;
            },
        });
        return element;
    };
    window.CustomEvent = class { constructor(type) { this.type = type; } };
    const context = {window, document, URL};
    vm.runInNewContext(shared("csrf.js"), context);
    if (maintenance) vm.runInNewContext(shared("maintenance.js"), context);
    return {window, redirects};
}

function nativeJson(status, response, headers = {}) {
    return {
        status, response, responseType: "json", getResponseHeader: name => headers[name] || null,
        get responseText() { throw new Error("responseText is unavailable for responseType=json"); },
    };
}

test("native JSON authentication responses redirect without reading responseText", () => {
    const ui = page();
    assert.equal(ui.window.qcAuth.handleUnauthorizedXhr(nativeJson(401, {
        code: "authentication_required", login_url: "/accounts/login/",
    })), true);
    const target = new URL(ui.redirects[0], ui.window.location.href);
    assert.equal(target.pathname, "/accounts/login/");
    assert.equal(target.searchParams.get("next"), "/boundaries/upload/?tab=package#upload");
});

test("empty or malformed native JSON authentication responses remain recoverable", () => {
    const ui = page();
    assert.equal(ui.window.qcAuth.handleUnauthorizedXhr(nativeJson(401, null)), false);
    assert.equal(ui.window.qcAuth.handleUnauthorizedXhr({
        status: 401, responseText: "<html>Login required</html>", getResponseHeader: () => null,
    }), false);
    assert.deepEqual(ui.redirects, []);
});

test("jQuery and text JSON responses preserve the same authentication behavior", () => {
    for (const payload of [
        {responseJSON: {code: "authentication_required", login_url: "/accounts/login/"}},
        {responseType: "text", responseText: JSON.stringify({code: "authentication_required", login_url: "/accounts/login/"})},
    ]) {
        const ui = page();
        assert.equal(ui.window.qcAuth.handleUnauthorizedXhr({status: 401, getResponseHeader: () => null, ...payload}), true);
        assert.equal(ui.redirects.length, 1);
    }
});

test("authentication recovery refuses an external login destination", () => {
    const ui = page();
    assert.equal(ui.window.qcAuth.handleUnauthorizedXhr(nativeJson(401, null, {
        "X-Login-URL": "https://external.invalid/accounts/login/",
    })), false);
    assert.deepEqual(ui.redirects, []);
});

test("non-JSON 503 responses do not throw or incorrectly activate maintenance", () => {
    const ui = page({maintenance: true});
    assert.equal(ui.window.qcAuth.handleUnauthorizedXhr(nativeJson(503, null)), false);
    assert.equal(ui.window.qcMaintenance.isActive(), false);
    ui.window.qcAuth.handleUnauthorizedXhr(nativeJson(503, {code: "maintenance"}));
    assert.equal(ui.window.qcMaintenance.isActive(), true);
});

test("binary responses are not treated as JSON authentication payloads", () => {
    const ui = page();
    assert.equal(ui.window.qcAuth.handleUnauthorizedXhr({
        status: 401, responseType: "arraybuffer", getResponseHeader: () => null,
        get responseText() { throw new Error("Not a text response"); },
    }), false);
});
