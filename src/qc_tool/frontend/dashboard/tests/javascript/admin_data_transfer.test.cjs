"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/admin/data-transfer.js"), "utf8");
const operationId = "812d54c5-f69b-4f51-9e25-d4cbbd9a35da";
const canonicalUrl = "https://qc.example.test/admin/database/?operation=" + operationId + "#transfer-operation";
const flush = () => new Promise(resolve => setImmediate(resolve));

function response(values = {}, options = {}) {
    return {
        ok: true, redirected: false,
        headers: {get: () => "application/json; charset=utf-8"},
        json: async () => ({id: operationId, status: "queued", runner_active: false, recoverable: false, cancellable: true, ...values}),
        ...options,
    };
}

function page({withOperation = true, withExport = false, withImport = false, reviewBlocked = false, databaseReady = true, recordsReady = true, statusUrl = "/admin/database/" + operationId + "/status/", refreshUrl = canonicalUrl, fetchResponse = response()} = {}) {
    const scope = {value: "database"};
    const chosenUsers = [{disabled: false, value: "12"}, {disabled: false, value: "kept search"}];
    const picker = {hidden: false, querySelectorAll: () => chosenUsers};
    const exportEvents = {}, importEvents = {}, windowEvents = {};
    const review = {disabled: false, textContent: "Review export"};
    const warnings = ["database", "records"].map(kind => ({dataset: {transferProfileWarning: kind}, hidden: false}));
    const exportForm = {
        dataset: {databaseReady: String(databaseReady), recordsReady: String(recordsReady)},
        querySelector: selector => selector === "[data-account-selection]" ? picker : selector === "[data-transfer-review]" ? review : scope,
        addEventListener: (name, callback) => { exportEvents[name] = callback; },
    };
    const apply = {disabled: reviewBlocked}, dirtyMessage = {hidden: true};
    const updateReview = {hidden: !reviewBlocked}, confirmation = {hidden: reviewBlocked};
    const importForm = {
        querySelector: selector => ({
            "[data-transfer-apply]": apply,
            "[data-mapping-dirty]": dirtyMessage,
            "[data-transfer-update-review]": updateReview,
            "[data-transfer-confirmation]": confirmation,
        })[selector],
        addEventListener: (name, callback) => { importEvents[name] = callback; },
    };
    const message = {textContent: "Progress updates automatically."};
    const operation = {
        dataset: {transferStatusUrl: statusUrl, operationId, transferStatus: "queued", runnerActive: "false", recoverable: "false", cancellable: "true"},
        querySelector: selector => selector === "[data-transfer-poll-message]" ? message : {href: refreshUrl},
    };
    const requests = [], navigations = [], timers = new Map();
    let timerId = 0;
    const document = {
        hidden: false,
        querySelectorAll: () => warnings,
        querySelector: selector => ({
            "[data-transfer-export-form]": withExport ? exportForm : null,
            "[data-transfer-import-form]": withImport ? importForm : null,
            "[data-transfer-status-url]": withOperation ? operation : null,
        })[selector],
    };
    const window = {
        location: {href: canonicalUrl, origin: "https://qc.example.test", replace: url => navigations.push(url)},
        fetch: (url, options) => {
            requests.push({url, options});
            return typeof fetchResponse === "function" ? fetchResponse(url, options) : Promise.resolve(fetchResponse);
        },
        AbortController,
        setTimeout(callback, delay) { timers.set(++timerId, {callback, delay}); return timerId; },
        clearTimeout(id) { timers.delete(id); },
        addEventListener: (name, callback) => { windowEvents[name] = callback; },
    };
    vm.runInNewContext(script, {window, document, URL});
    return {
        window, document, operation, requests, navigations, timers, message, scope, picker, chosenUsers,
        apply, dirtyMessage, updateReview, confirmation, review, warnings, exportEvents, importEvents, windowEvents,
        async tick(delay = 3000) {
            const entry = [...timers].find(([, value]) => value.delay === delay);
            assert.ok(entry, "A timer with the requested delay exists");
            timers.delete(entry[0]);
            entry[1].callback();
            await flush();
        },
    };
}

test("export scope hides and excludes the user picker while preserving its selection", () => {
    const p = page({withOperation: false, withExport: true});
    assert.equal(p.picker.hidden, true);
    assert.ok(p.chosenUsers.every(field => field.disabled));
    p.scope.value = "selected_accounts";
    p.exportEvents.change();
    assert.equal(p.picker.hidden, false);
    assert.ok(p.chosenUsers.every(field => !field.disabled));
    p.scope.value = "all_accounts";
    p.exportEvents.change();
    assert.equal(p.picker.hidden, true);
    assert.equal(p.chosenUsers[0].value, "12");
});

test("an edited mapping requires saving before the reviewed import can be confirmed", () => {
    const p = page({withOperation: false, withImport: true});
    p.importEvents.change({target: {tagName: "INPUT", name: "destination_confirmation"}});
    assert.equal(p.apply.disabled, false);
    assert.equal(p.updateReview.hidden, true);
    assert.equal(p.confirmation.hidden, false);
    p.importEvents.change({target: {tagName: "SELECT", name: "account_0"}});
    assert.equal(p.apply.disabled, true);
    assert.equal(p.dirtyMessage.hidden, false);
    assert.equal(p.updateReview.hidden, false);
    assert.equal(p.confirmation.hidden, true);
});

test("record resolution selections require revalidation before importing", () => {
    for (const tagName of ["SELECT", "INPUT"]) {
        const p = page({withOperation: false, withImport: true});
        p.importEvents.change({target: {tagName, name: "resolution_3"}});
        assert.equal(p.apply.disabled, true);
        assert.equal(p.dirtyMessage.hidden, false);
        assert.equal(p.updateReview.hidden, false);
        assert.equal(p.confirmation.hidden, true);
    }
});

test("user selection and target changes require a fresh reviewed plan", () => {
    for (const name of ["account_action_0", "account_target_0"]) {
        const p = page({withOperation: false, withImport: true});
        p.importEvents.change({target: {tagName: "SELECT", name}});
        assert.equal(p.apply.disabled, true);
        assert.equal(p.dirtyMessage.hidden, false);
        assert.equal(p.updateReview.hidden, false);
        assert.equal(p.confirmation.hidden, true);
    }
});

test("a blocked review keeps its update action available until the server validates it", () => {
    const p = page({withOperation: false, withImport: true, reviewBlocked: true});
    assert.equal(p.updateReview.hidden, false);
    assert.equal(p.confirmation.hidden, true);
    p.importEvents.change({target: {tagName: "SELECT", name: "account_0"}});
    assert.equal(p.updateReview.hidden, false);
    assert.equal(p.confirmation.hidden, true);
    assert.equal(p.apply.disabled, true);
});

test("native default and selective scopes each use their own availability", () => {
    const p = page({withOperation: false, withExport: true, databaseReady: true, recordsReady: false});
    assert.equal(p.scope.value, "database");
    assert.equal(p.review.disabled, false);
    assert.equal(p.review.textContent, "Review database backup");
    assert.deepEqual(p.warnings.map(item => item.hidden), [false, true]);
    p.scope.value = "application";
    p.exportEvents.change();
    assert.equal(p.review.disabled, true);
    assert.deepEqual(p.warnings.map(item => item.hidden), [true, false]);
    const q = page({withOperation: false, withExport: true, databaseReady: false, recordsReady: true});
    assert.equal(q.review.disabled, true);
    q.scope.value = "selected_accounts";
    q.exportEvents.change();
    assert.equal(q.review.disabled, false);
    assert.equal(q.picker.hidden, false);
});

test("polling only reads same-origin JSON with bounded requests and no POST resubmission", async () => {
    const p = page();
    await p.tick();
    assert.equal(p.requests.length, 1);
    assert.equal(p.requests[0].options.method, "GET");
    assert.equal(p.requests[0].options.mode, "same-origin");
    assert.equal(p.requests[0].options.redirect, "error");
    assert.equal(p.requests[0].options.cache, "no-store");
    assert.equal(p.requests[0].options.credentials, "same-origin");
    assert.equal(p.navigations.length, 0);
    assert.equal(p.timers.size, 1);
});

test("a completed operation navigates to the canonical GET page", async () => {
    const p = page({fetchResponse: response({status: "completed", cancellable: false})});
    await p.tick();
    assert.deepEqual(p.navigations, [canonicalUrl]);
    assert.equal(p.timers.size, 0);
});

test("expiry of runner startup grace reveals recovery even when status is unchanged", async () => {
    const p = page({fetchResponse: response({recoverable: true})});
    await p.tick();
    assert.deepEqual(p.navigations, [canonicalUrl]);
});

test("a changed cancellation permission refreshes the available controls", async () => {
    const p = page({fetchResponse: response({cancellable: false})});
    await p.tick();
    assert.deepEqual(p.navigations, [canonicalUrl]);
    assert.equal(p.timers.size, 0);
});

test("HTML, redirects and invalid operation responses pause updates without navigation", async () => {
    const badResponses = [
        response({}, {headers: {get: () => "text/html"}}),
        response({}, {redirected: true}),
        response({id: "another-operation"}),
        response({status: "unknown"}),
        response({recoverable: "yes"}),
        response({}, {ok: false}),
    ];
    for (const fetchResponse of badResponses) {
        const p = page({fetchResponse});
        await p.tick();
        assert.equal(p.navigations.length, 0);
        assert.equal(p.timers.size, 0);
        assert.match(p.message.textContent, /Automatic updates paused/);
    }
});

test("external status and refresh URLs cannot redirect administrator polling", async () => {
    const status = page({statusUrl: "https://other.example.test/status"});
    await status.tick();
    assert.equal(status.requests.length, 0);
    assert.match(status.message.textContent, /paused/);
    const refresh = page({refreshUrl: "https://other.example.test/", fetchResponse: response({status: "completed"})});
    await refresh.tick();
    assert.equal(refresh.navigations.length, 0);
    assert.match(refresh.message.textContent, /paused/);
});

test("hidden pages pause requests and leaving the page clears polling", async () => {
    const p = page();
    p.document.hidden = true;
    await p.tick();
    assert.equal(p.requests.length, 0);
    p.document.hidden = false;
    await p.tick();
    assert.equal(p.requests.length, 1);
    p.windowEvents.pagehide();
    assert.equal(p.timers.size, 0);
});

test("leaving aborts an in-flight status read without showing an error or restarting polling", async () => {
    const p = page({fetchResponse: (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("Aborted")));
    })});
    await p.tick();
    const signal = p.requests[0].options.signal;
    p.windowEvents.pagehide();
    assert.equal(signal.aborted, true);
    assert.equal(p.timers.size, 0);
    await flush();
    assert.equal(p.timers.size, 0);
    assert.deepEqual(p.navigations, []);
    assert.equal(p.message.textContent, "Progress updates automatically.");
});

test("late fetch and JSON payloads after leaving cannot navigate or restart polling", async () => {
    for (const pendingStage of ["fetch", "json"]) {
        let finish;
        const pending = () => new Promise(resolve => { finish = resolve; });
        const p = page({fetchResponse: pendingStage === "fetch" ? pending : response({}, {json: pending})});
        await p.tick();
        p.windowEvents.pagehide();
        assert.equal(p.requests[0].options.signal.aborted, true);
        finish(pendingStage === "fetch" ? response({status: "completed"}) : {
            id: operationId, status: "completed", runner_active: false, recoverable: false, cancellable: false,
        });
        await flush();
        assert.deepEqual(p.navigations, []);
        assert.equal(p.timers.size, 0);
        assert.equal(p.message.textContent, "Progress updates automatically.");
    }
});

test("a timed-out status read is aborted and leaves a manual refresh fallback", async () => {
    let signal;
    const p = page({fetchResponse: (_url, options) => new Promise((_resolve, reject) => {
        signal = options.signal;
        signal.addEventListener("abort", () => reject(new Error("Aborted")));
    })});
    await p.tick();
    assert.equal(signal.aborted, false);
    await p.tick(15000);
    assert.equal(signal.aborted, true);
    assert.equal(p.timers.size, 0);
    assert.match(p.message.textContent, /Refresh status/);
});
