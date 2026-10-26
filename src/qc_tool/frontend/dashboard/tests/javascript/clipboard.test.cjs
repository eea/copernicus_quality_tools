"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");
const flush = () => new Promise(resolve => setImmediate(resolve));

function page({clipboard = null, secure = true, exec = () => true} = {}) {
    const {window, document} = createDOM();
    const nativeWrites = [], legacyWrites = [], timers = [];
    let selected;
    const createElement = document.createElement;
    document.createElement = function(tag) {
        const node = createElement(tag);
        node.select = function() { selected = node; };
        node.setSelectionRange = function(start, end) { node.selection = [start, end]; };
        return node;
    };
    document.execCommand = function(command) {
        assert.equal(command, "copy");
        legacyWrites.push(selected.value);
        return exec();
    };
    window.navigator = clipboard ? {clipboard: {writeText(text) { nativeWrites.push(text); return clipboard(text); }}} : {};
    window.isSecureContext = secure;
    window.location = {hash: ""};
    window.setTimeout = callback => { timers.push(callback); };
    const context = {window, document, Promise};
    function load(file) {
        vm.runInNewContext(fs.readFileSync(path.join(__dirname, file), "utf8"), context);
    }
    load("../../static/dashboard/js/shared/clipboard.js");
    function node(tag, id, parent = document.body) {
        const result = document.createElement(tag);
        result.id = id;
        parent.append(result);
        return result;
    }
    return {window, document, node, load, nativeWrites, legacyWrites, timers, copy: window.QcClipboard.copy};
}

test("native clipboard writes run in the user gesture without touching fallback controls", async () => {
    const p = page({clipboard: () => Promise.resolve()});
    const before = p.document.body.children.length;
    const result = p.copy('<exact text & "bytes">');
    assert.deepEqual(p.nativeWrites, ['<exact text & "bytes">']);
    await result;
    assert.deepEqual(p.legacyWrites, []);
    assert.equal(p.document.body.children.length, before);
});

test("API-style copy falls back after denied native access and cleans up temporary inputs", async () => {
    for (const clipboard of [null, () => Promise.reject(new Error("denied")), () => { throw new Error("denied"); }]) {
        const p = page({clipboard});
        const button = p.node("button", "copy");
        button.focus();
        await p.copy("curl --data 'original text'");
        assert.deepEqual(p.legacyWrites, ["curl --data 'original text'"]);
        assert.deepEqual(p.document.body.children, [button]);
        assert.equal(p.document.activeElement, button);
    }
});

test("account-style copy uses the original input outside secure contexts", async () => {
    const p = page({clipboard: () => Promise.resolve(), secure: false});
    const input = p.node("input", "token");
    input.value = "private-token";
    await p.copy(input.value, {fallbackInput: input, secureOnly: true, fallbackOnError: false});
    assert.deepEqual(p.nativeWrites, []);
    assert.deepEqual(p.legacyWrites, ["private-token"]);
    assert.deepEqual(input.selection, [0, 13]);
    assert.equal(p.document.activeElement, input);
});

test("account native rejection and Storage native-only policy never invoke legacy commands", async () => {
    const account = page({clipboard: () => Promise.reject(new Error("denied"))});
    await assert.rejects(account.copy("token", {fallbackOnError: false}));
    assert.deepEqual(account.legacyWrites, []);
    for (const clipboard of [null, () => Promise.reject(new Error("denied")), () => { throw new Error("denied"); }]) {
        const p = page({clipboard});
        await assert.rejects(p.copy("sftp://example.test", {legacyFallback: false}));
        assert.deepEqual(p.legacyWrites, []);
        assert.equal(p.document.body.children.length, 0);
    }
});

test("failed legacy commands remove their temporary control and reject without claiming success", async () => {
    for (const exec of [() => false, () => { throw new Error("blocked"); }]) {
        const p = page({exec});
        const button = p.node("button", "copy");
        button.focus();
        await assert.rejects(p.copy("example"));
        assert.deepEqual(p.document.body.children, [button]);
        assert.equal(p.document.activeElement, button);
    }
});

test("restricted browser clipboard getters obey the caller's fallback policy", async () => {
    const p = page();
    Object.defineProperty(p.window.navigator, "clipboard", {get() { throw new Error("restricted"); }});
    await assert.rejects(p.copy("private", {legacyFallback: false}));
    assert.deepEqual(p.legacyWrites, []);
    await p.copy("public example");
    assert.deepEqual(p.legacyWrites, ["public example"]);
});

test("account token feedback preserves manual selection after a denied native copy", async () => {
    const p = page({clipboard: () => Promise.reject(new Error("denied"))});
    const input = p.node("input", "token");
    input.value = "private-token";
    const button = p.node("button", "copy");
    button.setAttribute("data-copy-target", "#token");
    const status = p.node("p", "credential-copy-status");
    p.load("../../../accounts/static/accounts/js/account-settings.js");
    assert.deepEqual(p.nativeWrites, []);
    p.document.dispatchEvent({type: "click", target: button});
    await flush();
    assert.match(status.textContent, /Copy the selected token manually/);
    assert.equal(p.document.activeElement, input);
    assert.deepEqual(p.legacyWrites, []);
});

test("account token copy keeps its secure-context policy and success announcement", async () => {
    for (const secure of [true, false]) {
        const p = page({clipboard: () => Promise.resolve(), secure});
        const input = p.node("input", "token");
        input.value = "private-token";
        const button = p.node("button", "copy");
        button.setAttribute("data-copy-target", "#token");
        const status = p.node("p", "credential-copy-status");
        p.load("../../../accounts/static/accounts/js/account-settings.js");
        p.document.dispatchEvent({type: "click", target: button});
        await flush();
        assert.equal(button.textContent, "Copied");
        assert.match(status.textContent, /Store it securely before leaving/);
        assert.equal(p.nativeWrites.length, secure ? 1 : 0);
        assert.equal(p.legacyWrites.length, secure ? 0 : 1);
    }
});

test("API examples confirm only successful copy and restore their original button label", async () => {
    const p = page({clipboard: () => Promise.reject(new Error("denied"))});
    const example = p.node("code", "example");
    example.textContent = "curl --header 'Authorization: TOKEN'";
    const button = p.node("button", "copy");
    button.textContent = "Copy example";
    button.setAttribute("data-copy-target", example.id);
    p.load("../../static/dashboard/js/features/api_access/index.js");
    p.document.dispatchEvent({type: "click", target: button});
    await flush();
    assert.deepEqual(p.legacyWrites, [example.textContent]);
    assert.equal(button.textContent, "Copied");
    p.timers[0]();
    assert.equal(button.textContent, "Copy example");
});

test("API copy failures keep example text available without a false confirmation", async () => {
    const p = page({exec: () => false});
    const example = p.node("code", "example");
    example.textContent = "original example";
    const button = p.node("button", "copy");
    button.textContent = "Copy example";
    button.setAttribute("data-copy-target", example.id);
    p.load("../../static/dashboard/js/features/api_access/index.js");
    p.document.dispatchEvent({type: "click", target: button});
    await flush();
    assert.equal(button.textContent, "Copy example");
    assert.equal(example.textContent, "original example");
    assert.deepEqual(p.timers, []);
});
