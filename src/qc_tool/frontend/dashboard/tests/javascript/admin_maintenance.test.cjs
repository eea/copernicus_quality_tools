"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

const source = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/admin/maintenance.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

function response(state = {}, options = {}) {
    return {
        ok: true, redirected: false,
        headers: {get: () => "application/json; charset=utf-8"},
        json: async () => ({phase: "stopping", generation: 5, poll: true, blockers: [], ...state}),
        ...options,
    };
}

function page({phase = "stopping", withForm = phase === "stopping", withBlockers = true, fetchResponse = response()} = {}) {
    const dom = createDOM();
    const {window, document} = dom;
    const node = (tag, attributes = {}, parent = document.body) => {
        const result = document.createElement(tag);
        Object.entries(attributes).forEach(([key, value]) => result.setAttribute(key, value));
        parent.append(result);
        return result;
    };
    const root = node("section", {"data-maintenance-control": "", "data-phase": phase, "data-generation": "5"});
    const progress = node("p", {"data-progress-status": ""}, root);
    const indicator = node("span", {"data-progress-indicator": ""}, progress);
    const message = node("span", {"data-progress-message": ""}, progress);
    const checked = node("p", {"data-progress-checked": ""}, root);
    const problem = node("div", {"data-progress-problem": "", hidden: ""}, root);
    const error = node("p", {"data-progress-error": ""}, problem);
    const retry = node("button", {"data-progress-retry": "", type: "button", hidden: ""}, problem);
    const blockers = withBlockers ? node("ul", {"data-progress-blockers": "", hidden: ""}, root) : null;
    let form;
    if (withForm) {
        form = node("form", {"data-maintenance-progress": "", method: "post"}, root);
        form.action = "https://qc.example.test/admin/maintenance/";
        for (const [name, value] of Object.entries({csrfmiddlewaretoken: "csrf-test-token", generation: "5", action: "progress"})) {
            node("input", {type: "hidden", name}, form).value = value;
        }
    }
    const requests = [], navigations = [], timers = new Map();
    let nextTimer = 0, reloads = 0;
    window.location = {
        href: "https://qc.example.test/admin/maintenance/#content-start",
        replace(url) { navigations.push(url); },
        reload() { reloads++; },
    };
    window.AbortController = AbortController;
    window.FormData = class {
        constructor(element) {
            this.values = new Map(element.querySelectorAll("input").map(input => [input.getAttribute("name"), input.value]));
        }
        get(name) { return this.values.get(name); }
    };
    window.setTimeout = (callback, delay) => { timers.set(++nextTimer, {callback, delay}); return nextTimer; };
    window.clearTimeout = id => timers.delete(id);
    window.fetch = (url, options) => {
        requests.push({url, options});
        return typeof fetchResponse === "function" ? fetchResponse(url, options) : Promise.resolve(fetchResponse);
    };
    vm.runInNewContext(source, {window, document});
    return {
        ...dom, requests, navigations, timers, message, indicator, progress, checked, problem, error, retry, blockers,
        get reloads() { return reloads; },
        async tick(delay = 1000) {
            const entry = [...timers].find(([, value]) => value.delay === delay);
            assert.ok(entry, `A ${delay}ms timer exists`);
            timers.delete(entry[0]);
            entry[1].callback();
            await flush();
        },
    };
}

test("ready and off pages never start automatic progress work", () => {
    for (const phase of ["ready", "off"]) {
        const ui = page({phase});
        assert.equal(ui.requests.length, 0);
        assert.equal(ui.timers.size, 0);
    }
});

test("progress POST includes CSRF and generation and waits before scheduling the next pass", async () => {
    let finish;
    const ui = page({fetchResponse: () => new Promise(resolve => { finish = resolve; })});
    await ui.tick();
    const {url, options} = ui.requests[0];
    assert.equal(url, "https://qc.example.test/admin/maintenance/");
    assert.equal(options.method, "POST");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    assert.equal(options.headers.Accept, "application/json");
    assert.equal(options.body.get("csrfmiddlewaretoken"), "csrf-test-token");
    assert.equal(options.body.get("generation"), "5");
    assert.equal(options.body.get("action"), "progress");
    assert.equal(options.signal.aborted, false);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [20000]);
    ui.retry.click();
    assert.equal(ui.requests.length, 1);
    finish(response());
    await flush();
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [5000]);
    await ui.tick(5000);
    assert.equal(ui.requests.length, 2);
});

test("readiness, another administrator's change and a transfer each navigate once with GET", async () => {
    for (const state of [{phase: "ready"}, {phase: "off"}, {generation: 6}, {transfer_active: true}]) {
        const ui = page({fetchResponse: response(state)});
        await ui.tick();
        assert.deepEqual(ui.navigations, ["https://qc.example.test/admin/maintenance/"]);
        assert.equal(ui.reloads, 0);
        assert.equal(ui.timers.size, 0);
    }
});

test("three failed connections stop automatic retries and offer a working retry button", async () => {
    const ui = page({fetchResponse: () => Promise.reject(new Error("offline"))});
    await ui.tick();
    await ui.tick(10000);
    await ui.tick(10000);
    assert.equal(ui.requests.length, 3);
    assert.equal(ui.timers.size, 0);
    assert.equal(ui.problem.hidden, false);
    assert.equal(ui.retry.hidden, false);
    assert.equal(ui.indicator.hidden, true);
    assert.equal(ui.progress.getAttribute("data-progress-active"), "false");
    assert.match(ui.error.textContent, /Maintenance stays on/);
    ui.retry.click();
    await flush();
    assert.equal(ui.requests.length, 4);
    assert.equal(ui.retry.hidden, true);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [10000]);
});

test("login redirects and HTML stop checks with a sign-in explanation", async () => {
    for (const fetchResponse of [response({}, {redirected: true}), response({}, {headers: {get: () => "text/html"}})]) {
        const ui = page({fetchResponse});
        await ui.tick();
        assert.equal(ui.timers.size, 0);
        assert.equal(ui.reloads, 0);
        assert.deepEqual(ui.navigations, []);
        assert.equal(ui.retry.hidden, true);
        assert.match(ui.error.textContent, /sign in/);
        assert.match(ui.error.textContent, /Maintenance stays on/);
    }
});

test("hidden tabs defer requests and leaving the page cancels the next check", async () => {
    const ui = page();
    ui.document.hidden = true;
    await ui.tick();
    assert.equal(ui.requests.length, 0);
    ui.document.hidden = false;
    await ui.tick(5000);
    assert.equal(ui.requests.length, 1);
    ui.window.dispatchEvent({type: "pagehide"});
    assert.equal(ui.timers.size, 0);
});

test("leaving the page aborts a pending request without showing connection failures", async () => {
    const ui = page({fetchResponse: (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("aborted")));
    })});
    await ui.tick();
    const signal = ui.requests[0].options.signal;
    ui.window.dispatchEvent({type: "pagehide"});
    assert.equal(signal.aborted, true);
    assert.equal(ui.timers.size, 0);
    await flush();
    assert.equal(ui.reloads, 0);
    assert.deepEqual(ui.navigations, []);
    assert.equal(ui.problem.hidden, true);
    assert.equal(ui.timers.size, 0);
});

test("late fetch and JSON responses after leaving cannot reload or restart checks", async () => {
    for (const pendingStage of ["fetch", "json"]) {
        let finish;
        const pending = () => new Promise(resolve => { finish = resolve; });
        const ui = page({fetchResponse: pendingStage === "fetch" ? pending : response({}, {json: pending})});
        await ui.tick();
        ui.window.dispatchEvent({type: "pagehide"});
        assert.equal(ui.requests[0].options.signal.aborted, true);
        finish(pendingStage === "fetch" ? response({phase: "ready"}) : {phase: "ready", generation: 5});
        await flush();
        assert.equal(ui.reloads, 0);
        assert.deepEqual(ui.navigations, []);
        assert.equal(ui.timers.size, 0);
        assert.equal(ui.problem.hidden, true);
    }
});

test("blockers are rendered as text and stale blockers disappear after a successful pass", async () => {
    let pass = 0;
    const unsafeText = '<img src=x onerror="alert(1)">';
    const ui = page({fetchResponse: () => Promise.resolve(response({blockers: pass++ ? [] : [unsafeText]}))});
    await ui.tick();
    assert.equal(ui.blockers.hidden, false);
    assert.equal(ui.blockers.children.length, 1);
    assert.equal(ui.blockers.children[0].tagName, "LI");
    assert.equal(ui.blockers.children[0].textContent, unsafeText);
    assert.equal(ui.blockers.children[0].children.length, 0);
    await ui.tick(5000);
    assert.equal(ui.blockers.children.length, 0);
    assert.equal(ui.blockers.hidden, true);
});

test("the simple maintenance page checks progress without a technical blocker list", async () => {
    const ui = page({withBlockers: false, fetchResponse: response({blockers: ["Waiting for workers."]})});

    await ui.tick();

    assert.equal(ui.problem.hidden, true);
    assert.equal(ui.indicator.hidden, false);
    assert.match(ui.message.textContent, /Waiting for work to stop/);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [5000]);
    await ui.tick(5000);
    assert.equal(ui.requests.length, 2);
    assert.equal(ui.problem.hidden, true);
});

test("a stalled request is aborted before bounded retrying", async () => {
    let signal;
    const ui = page({fetchResponse: (_url, options) => new Promise((_resolve, reject) => {
        signal = options.signal;
        signal.addEventListener("abort", () => reject(new Error("aborted")));
    })});
    await ui.tick();
    await ui.tick(20000);
    assert.equal(signal.aborted, true);
    assert.equal(ui.problem.hidden, false);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [10000]);
});

test("busy contention keeps waiting without consuming the connection failure budget", async () => {
    const ui = page({fetchResponse: response({busy: true}, {ok: false, status: 409})});
    await ui.tick();
    for (let pass = 0; pass < 4; pass++) await ui.tick(3000);
    assert.equal(ui.requests.length, 5);
    assert.equal(ui.problem.hidden, true);
    assert.equal(ui.indicator.hidden, false);
    assert.match(ui.message.textContent, /Another maintenance action is finishing/);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [3000]);
});

test("a non-busy rejected check stops with an actionable explanation and no spinner", async () => {
    const ui = page({fetchResponse: response({error: "Reload and review maintenance."}, {ok: false, status: 409})});
    await ui.tick();
    assert.equal(ui.timers.size, 0);
    assert.equal(ui.indicator.hidden, true);
    assert.equal(ui.retry.hidden, true);
    assert.equal(ui.error.textContent, "Reload and review maintenance.");
});

test("returning to a visible tab checks immediately without counting its aborted request as a failure", async () => {
    const ui = page({fetchResponse: (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("aborted")));
    })});
    await ui.tick();
    ui.document.hidden = true;
    ui.document.dispatchEvent({type: "visibilitychange"});
    assert.equal(ui.requests[0].options.signal.aborted, true);
    await flush();
    assert.equal(ui.problem.hidden, true);
    assert.equal(ui.timers.size, 0);
    ui.document.hidden = false;
    ui.document.dispatchEvent({type: "visibilitychange"});
    assert.equal(ui.requests.length, 2);
});

test("back navigation restarts progress while an old response remains harmless", async () => {
    let finish;
    let pass = 0;
    const ui = page({fetchResponse: () => ++pass === 1
        ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(response())});
    await ui.tick();
    ui.window.dispatchEvent({type: "pagehide"});
    ui.window.dispatchEvent({type: "pageshow", persisted: true});
    await ui.tick(0);
    assert.equal(ui.requests.length, 2);
    finish(response({phase: "ready"}));
    await flush();
    assert.deepEqual(ui.navigations, []);
    assert.equal(ui.problem.hidden, true);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [5000]);
});

test("an incomplete status response retries without navigating to an unverified state", async () => {
    const ui = page({fetchResponse: response({generation: null})});
    await ui.tick();
    assert.deepEqual(ui.navigations, []);
    assert.equal(ui.problem.hidden, false);
    assert.deepEqual([...ui.timers.values()].map(timer => timer.delay), [10000]);
});
