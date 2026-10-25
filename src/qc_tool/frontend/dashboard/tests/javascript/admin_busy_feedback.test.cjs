"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

const source = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/admin/busy-feedback.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));
function response(state = {}, options = {}) {
    return {
        ok: true, status: 200, redirected: false,
        headers: {get: () => "application/json; charset=utf-8"},
        json: async () => ({busy: true, phase: "ready", transfer_active: false, transfer_url: "", ...state}),
        ...options,
    };
}

function page({endpoint = "/admin/maintenance/", fetchResponse = response(), withPanel = true, withFetch = true, withAbort = true, hidden = false} = {}) {
    const dom = createDOM();
    const {document, window} = dom;
    document.hidden = hidden;
    const node = (tag, attributes = {}, parent = document.body) => {
        const result = document.createElement(tag);
        Object.entries(attributes).forEach(([key, value]) => result.setAttribute(key, value));
        parent.append(result);
        return result;
    };
    const panel = node("section", withPanel ? {"data-admin-busy-url": endpoint} : {});
    const heading = node("h2", {"data-admin-busy-heading": ""}, panel);
    heading.textContent = "Another action is finishing";
    const message = node("p", {"data-admin-busy-message": ""}, panel);
    const spinner = node("span", {"data-admin-busy-spinner": ""}, panel);
    const details = node("a", {"data-admin-busy-details": ""}, panel);
    details.href = "https://qc.example.test/admin/maintenance/";
    details.textContent = "View maintenance status";
    const retry = node("button", {"data-admin-busy-retry": "", type: "button", hidden: ""}, panel);
    const requests = [], navigations = [], timers = new Map();
    let nextTimer = 0;
    window.location = {
        href: "https://qc.example.test/admin/database/?tab=backups", origin: "https://qc.example.test",
        replace: url => navigations.push(url), reload: () => navigations.push("reload"),
    };
    window.setTimeout = (callback, delay) => { timers.set(++nextTimer, {callback, delay}); return nextTimer; };
    window.clearTimeout = id => timers.delete(id);
    if (withAbort) window.AbortController = AbortController;
    if (withFetch) window.fetch = (url, options) => {
        requests.push({url, options});
        return typeof fetchResponse === "function" ? fetchResponse(url, options) : Promise.resolve(fetchResponse);
    };
    vm.runInNewContext(source, {window, document, URL});
    return {
        ...dom, panel, heading, message, spinner, details, retry, requests, navigations, timers,
        async tick(delay = 1000) {
            const entry = [...timers].find(([, timer]) => timer.delay === delay);
            assert.ok(entry, `A ${delay}ms timer exists`);
            timers.delete(entry[0]);
            entry[1].callback();
            await flush();
        },
        hide() { document.hidden = true; document.dispatchEvent({type: "visibilitychange"}); },
        show() { document.hidden = false; document.dispatchEvent({type: "visibilitychange"}); },
        leave() { window.dispatchEvent({type: "pagehide"}); },
        restore(persisted = true) { window.dispatchEvent({type: "pageshow", persisted}); },
    };
}

test("busy checks are bounded same-origin GETs without replaying POST or navigating", async () => {
    const ui = page();
    assert.equal(ui.requests.length, 0);
    await ui.tick();
    const request = ui.requests[0];
    assert.equal(request.url, "https://qc.example.test/admin/maintenance/");
    assert.equal(request.options.method, "GET");
    assert.equal(request.options.credentials, "same-origin");
    assert.equal(request.options.mode, "same-origin");
    assert.equal(request.options.redirect, "error");
    assert.equal(request.options.cache, "no-store");
    assert.equal(request.options.headers.Accept, "application/json");
    assert.equal(request.options.body, undefined);
    assert.equal(ui.spinner.hidden, false);
    assert.equal(ui.retry.hidden, true);
    assert.match(ui.message.textContent, /Checking again automatically/);
    assert.deepEqual(ui.navigations, []);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [3000]);
});

test("stopping QC work retains active feedback even when the control lock is free", async () => {
    const ui = page({fetchResponse: response({busy: false, phase: "stopping"})});
    await ui.tick();
    assert.equal(ui.spinner.hidden, false);
    assert.match(ui.message.textContent, /QC work is stopping/);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [3000]);
});

test("finished actions stop the spinner and ask for an explicit refresh without replay or navigation", async () => {
    for (const phase of ["off", "ready"]) {
        const ui = page({fetchResponse: response({busy: false, phase})});
        await ui.tick();
        assert.equal(ui.heading.textContent, "Ready to check again");
        assert.equal(ui.spinner.hidden, true);
        assert.equal(ui.retry.hidden, true);
        assert.match(ui.message.textContent, /Refresh this page/);
        assert.equal(ui.timers.size, 0);
        assert.deepEqual(ui.navigations, []);
    }
});

test("a transfer still holding maintenance offers its local status for continuation or recovery", async () => {
    const ui = page({fetchResponse: response({busy: false, transfer_active: true, transfer_url: "/admin/database/?operation=abc#transfer-operation"})});
    await ui.tick();
    assert.equal(ui.heading.textContent, "A transfer holds maintenance");
    assert.match(ui.message.textContent, /continue or recover/);
    assert.equal(ui.details.href, "https://qc.example.test/admin/database/?operation=abc#transfer-operation");
    assert.equal(ui.details.textContent, "View current transfer");
    assert.equal(ui.spinner.hidden, true);
    assert.equal(ui.timers.size, 0);
    assert.deepEqual(ui.navigations, []);
});

test("a transfer link is cleared when a later state no longer includes that transfer", async () => {
    let calls = 0;
    const ui = page({fetchResponse: () => Promise.resolve(calls++ ? response({busy: false}) : response({transfer_active: true, transfer_url: "/admin/database/?operation=old"}))});
    await ui.tick();
    assert.match(ui.details.href, /operation=old/);
    await ui.tick(3000);
    assert.equal(ui.details.href, "https://qc.example.test/admin/maintenance/");
    assert.equal(ui.details.textContent, "View maintenance status");
});

test("offline failures retry with backoff, stop after three attempts, and allow a deliberate fresh check", async () => {
    const ui = page({fetchResponse: () => Promise.reject(new Error("offline"))});
    await ui.tick();
    assert.equal(ui.spinner.hidden, true);
    assert.equal(ui.retry.hidden, false);
    assert.match(ui.message.textContent, /request will not be repeated/);
    await ui.tick(6000);
    await ui.tick(12000);
    assert.equal(ui.requests.length, 3);
    assert.equal(ui.timers.size, 0);
    assert.match(ui.message.textContent, /could not connect/);
    ui.retry.click();
    await flush();
    assert.equal(ui.requests.length, 4);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [6000]);
    assert.ok(ui.requests.every(request => request.options.method === "GET"));
    assert.deepEqual(ui.navigations, []);
});

test("HTTP failures and invalid JSON exhaust the same bounded retry budget", async () => {
    for (const fetchResponse of [response({}, {ok: false, status: 503}), response({}, {ok: false, status: 404}),
        response({}, {json: async () => { throw new SyntaxError("truncated JSON"); }})]) {
        const ui = page({fetchResponse});
        await ui.tick();
        await ui.tick(6000);
        await ui.tick(12000);
        assert.equal(ui.requests.length, 3);
        assert.equal(ui.timers.size, 0);
        assert.equal(ui.spinner.hidden, true);
        assert.equal(ui.retry.hidden, false);
    }
});

test("an automatic reconnection shows loading while its status request is pending", async () => {
    let calls = 0, finish;
    const ui = page({fetchResponse: () => ++calls === 1 ? Promise.reject(new Error("offline")) :
        new Promise(resolve => { finish = resolve; })});
    await ui.tick();
    assert.equal(ui.spinner.hidden, true);
    await ui.tick(6000);
    assert.equal(ui.spinner.hidden, false);
    assert.equal(ui.retry.hidden, true);
    assert.match(ui.message.textContent, /Reconnecting/);
    finish(response({busy: false}));
    await flush();
    assert.equal(ui.spinner.hidden, true);
    assert.equal(ui.heading.textContent, "Ready to check again");
});

test("busy, phase, transfer flag and transfer URL must have their declared types", async () => {
    for (const invalid of [{busy: "false"}, {phase: "unknown"}, {phase: true}, {transfer_active: "false"},
        {transfer_active: undefined}, {transfer_url: {}}, {transfer_url: "x".repeat(2049)}]) {
        const ui = page({fetchResponse: response(invalid)});
        await ui.tick();
        await ui.tick(6000);
        await ui.tick(12000);
        assert.equal(ui.requests.length, 3, JSON.stringify(invalid));
        assert.equal(ui.heading.textContent, "Another action is finishing");
        assert.equal(ui.timers.size, 0);
        assert.equal(ui.spinner.hidden, true);
        assert.deepEqual(ui.navigations, []);
    }
});

test("successful checks reset connection failures while retaining the overall waiting bound", async () => {
    let calls = 0;
    const ui = page({fetchResponse: () => ++calls === 2 ? Promise.resolve(response()) : Promise.reject(new Error("offline"))});
    await ui.tick();
    await ui.tick(6000);
    assert.equal(ui.spinner.hidden, false);
    assert.equal(ui.retry.hidden, true);
    await ui.tick(3000);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [6000]);
});

test("authentication, redirect and non-JSON responses stop checks with a sign-in explanation", async () => {
    for (const options of [{status: 401, ok: false}, {status: 403, ok: false}, {redirected: true},
        {headers: {get: () => "text/html"}}, {headers: {get: () => "text/application/json-fake"}}]) {
        const ui = page({fetchResponse: response({}, options)});
        await ui.tick();
        assert.equal(ui.requests.length, 1);
        assert.equal(ui.timers.size, 0);
        assert.equal(ui.spinner.hidden, true);
        assert.equal(ui.retry.hidden, true);
        assert.match(ui.message.textContent, /sign in/);
        assert.deepEqual(ui.navigations, []);
    }
});

test("slow requests have an abort deadline and cannot overlap another check", async () => {
    const ui = page({fetchResponse: (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("aborted")));
    })});
    await ui.tick();
    ui.retry.click();
    assert.equal(ui.requests.length, 1);
    await ui.tick(10000);
    assert.equal(ui.requests[0].options.signal.aborted, true);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [6000]);
    assert.equal(ui.spinner.hidden, true);
});

test("long waits slow down after twelve checks and stop at forty with a manual next step", async () => {
    const ui = page();
    await ui.tick();
    for (let checks = 2; checks <= 40; checks++) await ui.tick(checks <= 12 ? 3000 : 15000);
    assert.equal(ui.requests.length, 40);
    assert.equal(ui.timers.size, 0);
    assert.equal(ui.spinner.hidden, true);
    assert.equal(ui.retry.hidden, false);
    assert.match(ui.message.textContent, /taking longer than expected/);
    assert.deepEqual(ui.navigations, []);
    ui.retry.click();
    await flush();
    assert.equal(ui.requests.length, 41);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [3000]);
});

test("hidden pages defer work and showing them starts exactly one read", async () => {
    const ui = page({hidden: true});
    assert.equal(ui.timers.size, 0);
    ui.show();
    await ui.tick(0);
    assert.equal(ui.requests.length, 1);
    ui.hide();
    assert.equal(ui.timers.size, 0);
    ui.show();
    await ui.tick(0);
    assert.equal(ui.requests.length, 2);
});

test("hiding invalidates in-flight fetch or JSON results without clearing a resumed request deadline", async () => {
    for (const stage of ["fetch", "json"]) {
        let finishOld, finishCurrent, calls = 0;
        const old = new Promise(resolve => { finishOld = resolve; });
        const current = new Promise(resolve => { finishCurrent = resolve; });
        const ui = page({fetchResponse: () => ++calls === 1 ?
            (stage === "fetch" ? old : Promise.resolve(response({}, {json: () => old}))) : current});
        await ui.tick();
        ui.hide();
        assert.equal(ui.requests[0].options.signal.aborted, true);
        ui.show();
        await ui.tick(0);
        assert.equal(ui.requests.length, 2);
        finishOld(stage === "fetch" ? response({busy: false}) : {busy: false, phase: "ready", transfer_active: false, transfer_url: ""});
        await flush();
        assert.equal(ui.heading.textContent, "Another action is finishing");
        assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [10000]);
        ui.retry.click();
        assert.equal(ui.requests.length, 2, "The resumed request is still marked in flight");
        finishCurrent(response({busy: false}));
        await flush();
        assert.equal(ui.heading.textContent, "Ready to check again");
        assert.equal(ui.timers.size, 0);
        assert.deepEqual(ui.navigations, []);
    }
});

test("pagehide aborts work, and BFCache restoration resumes once without replaying actions", async () => {
    let finish;
    const ui = page({fetchResponse: () => new Promise(resolve => { finish = resolve; })});
    await ui.tick();
    ui.leave();
    assert.equal(ui.requests[0].options.signal.aborted, true);
    assert.equal(ui.timers.size, 0);
    finish(response({busy: false}));
    await flush();
    assert.equal(ui.heading.textContent, "Another action is finishing");
    ui.restore(false);
    assert.equal(ui.timers.size, 0);
    ui.restore();
    await ui.tick(0);
    assert.equal(ui.requests.length, 2);
    assert.equal(ui.requests[1].options.method, "GET");
    assert.deepEqual(ui.navigations, []);
});

test("terminal or exhausted checks stay stopped across visibility changes and BFCache", async () => {
    for (const outcome of ["finished", "failed", "bound"]) {
        const ui = page({fetchResponse: outcome === "finished" ? response({busy: false}) : outcome === "failed" ?
            () => Promise.reject(new Error("offline")) : response()});
        await ui.tick();
        if (outcome === "failed") { await ui.tick(6000); await ui.tick(12000); }
        if (outcome === "bound") for (let checks = 2; checks <= 40; checks++) await ui.tick(checks <= 12 ? 3000 : 15000);
        const count = ui.requests.length;
        ui.hide(); ui.show(); ui.leave(); ui.restore();
        assert.equal(ui.timers.size, 0, outcome);
        assert.equal(ui.requests.length, count, outcome);
    }
});

test("unsafe status endpoints never fetch and explain how to check manually", () => {
    for (const endpoint of ["https://other.example.test/admin/maintenance/", "//other.example.test/admin/maintenance/",
        "https://user:secret@qc.example.test/admin/maintenance/", "javascript:alert(1)", "http://["]) {
        const ui = page({endpoint});
        assert.equal(ui.requests.length, 0, endpoint);
        assert.equal(ui.timers.size, 0, endpoint);
        assert.equal(ui.spinner.hidden, true, endpoint);
        assert.match(ui.message.textContent, /Open maintenance status/);
        assert.deepEqual(ui.navigations, []);
    }
});

test("unsafe or malformed transfer URLs keep the local maintenance link", async () => {
    for (const transfer_url of ["https://other.example.test/admin/database/", "//other.example.test/admin/database/",
        "https://user:secret@qc.example.test/admin/database/", "javascript:alert(1)", "http://["]) {
        const ui = page({fetchResponse: response({busy: false, transfer_active: true, transfer_url})});
        await ui.tick();
        assert.equal(ui.details.href, "https://qc.example.test/admin/maintenance/", transfer_url);
        assert.equal(ui.details.textContent, "View maintenance status");
        assert.deepEqual(ui.navigations, []);
        assert.equal(ui.requests.length, 1);
    }
});

test("missing polling support shows a usable manual fallback and ordinary pages remain untouched", () => {
    for (const options of [{withFetch: false}, {withAbort: false}]) {
        const ui = page(options);
        assert.equal(ui.timers.size, 0);
        assert.equal(ui.spinner.hidden, true);
        assert.equal(ui.retry.hidden, true);
        assert.match(ui.message.textContent, /Automatic status checks are unavailable/);
    }
    const ordinary = page({withPanel: false});
    assert.equal(ordinary.timers.size, 0);
    assert.equal(ordinary.requests.length, 0);
});
