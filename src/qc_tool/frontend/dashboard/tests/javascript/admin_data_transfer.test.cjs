"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/admin/data-transfer.js"), "utf8");
const operationId = "812d54c5-f69b-4f51-9e25-d4cbbd9a35da";
const canonicalUrl = "https://qc.example.test/admin/maintenance/backups/export/?operation=" + operationId + "#transfer-operation";
const flush = () => new Promise(resolve => setImmediate(resolve));

function response(values = {}, options = {}) {
    return {
        ok: true, redirected: false,
        headers: {get: () => "application/json; charset=utf-8"},
        json: async () => ({id: operationId, status: "queued", runner_active: false, recoverable: false, cancellable: true, ...values}),
        ...options,
    };
}

function page({withOperation = true, withImport = false, reviewBlocked = false, statusUrl = "/admin/maintenance/backups/" + operationId + "/status/", refreshUrl = canonicalUrl, fetchResponse = response()} = {}) {
    const importEvents = {}, resumeEvents = {}, windowEvents = {}, documentEvents = {};
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
    const lastChecked = {hidden: true, textContent: ""};
    const runningIndicator = {hidden: false};
    const resume = {hidden: true, disabled: false, addEventListener: (name, callback) => { resumeEvents[name] = callback; }};
    const progressLabel = {textContent: "Preparing and checking your package."};
    const progressItems = {textContent: "", hidden: true};
    const progressBytes = {textContent: "", hidden: true};
    const operation = {
        dataset: {transferStatusUrl: statusUrl, operationId, transferStatus: "queued", runnerActive: "false", recoverable: "false", cancellable: "true"},
        querySelector: selector => ({
            "[data-transfer-poll-message]": message,
            "[data-transfer-resume]": resume,
            "[data-transfer-last-checked]": lastChecked,
            "[data-transfer-running-indicator]": runningIndicator,
            "[data-transfer-progress-label]": progressLabel,
            "[data-transfer-progress-items]": progressItems,
            "[data-transfer-progress-bytes]": progressBytes,
            "[data-transfer-refresh]": {href: refreshUrl},
        })[selector],
    };
    const requests = [], navigations = [], timers = new Map();
    let timerId = 0;
    const document = {
        hidden: false,
        addEventListener: (name, callback) => { documentEvents[name] = callback; },
        querySelector: selector => ({
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
        navigator: {onLine: true},
        setTimeout(callback, delay) { timers.set(++timerId, {callback, delay}); return timerId; },
        clearTimeout(id) { timers.delete(id); },
        addEventListener: (name, callback) => {
            const previous = windowEvents[name];
            windowEvents[name] = previous ? event => { previous(event); callback(event); } : callback;
        },
    };
    vm.runInNewContext(script, {window, document, URL});
    return {
        window, document, operation, requests, navigations, timers, message,
        apply, dirtyMessage, updateReview, confirmation, importEvents, windowEvents, documentEvents,
        resume, resumeEvents, lastChecked, runningIndicator,
        progressLabel, progressItems, progressBytes,
        async tick(delay = 3000) {
            const entry = [...timers].find(([, value]) => value.delay === delay);
            assert.ok(entry, "A timer with the requested delay exists");
            timers.delete(entry[0]);
            entry[1].callback();
            await flush();
        },
    };
}

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

test("persisted phase and chunk counters update in place without reloading or submitting", async () => {
    const p = page({fetchResponse: response({progress: {
        phase: "packaging_files", label: "Adding selected files to your package.",
        processed_items: 2, total_items: 10, processed_bytes: 1048576, total_bytes: 2097152,
    }})});
    await p.tick();
    assert.equal(p.progressLabel.textContent, "Adding selected files to your package.");
    assert.equal(p.progressItems.textContent, "2 / 10 items");
    assert.equal(p.progressItems.hidden, false);
    assert.equal(p.progressBytes.textContent, "1.0 MiB / 2.0 MiB");
    assert.equal(p.progressBytes.hidden, false);
    assert.deepEqual(p.navigations, []);
    assert.equal(p.requests[0].options.method, "GET");
});

test("unknown byte totals show only processed bytes rather than an invented percentage", async () => {
    const p = page({fetchResponse: response({progress: {
        label: "Reading the database.", processed_bytes: 4096,
    }})});
    await p.tick();
    assert.equal(p.progressBytes.textContent, "4.0 KiB");
    assert.equal(p.progressItems.hidden, true);
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
        response({}, {ok: false, status: 401}),
        response({}, {json: async () => { throw new SyntaxError("Bad JSON"); }}),
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

test("returning to a visible tab checks status immediately without overlapping requests", async () => {
    const p = page();
    p.document.hidden = true;
    await p.tick();
    p.document.hidden = false;
    p.documentEvents.visibilitychange();
    p.documentEvents.visibilitychange();
    await flush();
    assert.equal(p.requests.length, 1);
    assert.equal(p.timers.size, 1);
});

test("back and forward cache restoration resumes polling and reveals an already prepared ZIP", async () => {
    const p = page({fetchResponse: response({status: "completed", cancellable: false})});
    p.windowEvents.pagehide();
    assert.equal(p.timers.size, 0);
    p.windowEvents.pageshow({persisted: true});
    await flush();
    assert.equal(p.requests.length, 1);
    assert.equal(p.requests[0].options.method, "GET");
    assert.deepEqual(p.navigations, [canonicalUrl]);
});

test("BFCache restoration ignores late old responses while a fresh status read is active", async () => {
    let finishOld;
    let requests = 0;
    const p = page({fetchResponse: () => {
        requests += 1;
        return requests === 1 ? new Promise(resolve => { finishOld = resolve; }) : Promise.resolve(response());
    }});
    await p.tick();
    p.windowEvents.pagehide();
    p.windowEvents.pageshow({persisted: true});
    await flush();
    finishOld(response({status: "completed", cancellable: false}));
    await flush();
    assert.equal(p.requests.length, 2);
    assert.deepEqual(p.navigations, []);
    assert.equal(p.timers.size, 1);
});

test("leaving aborts only the status read without cancelling the backup or restarting polling", async () => {
    const p = page({fetchResponse: (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("Aborted")));
    })});
    await p.tick();
    const signal = p.requests[0].options.signal;
    p.windowEvents.pagehide();
    assert.equal(signal.aborted, true);
    assert.equal(p.timers.size, 0);
    await flush();
    assert.equal(p.requests.length, 1, "Leaving must never send a cancellation request");
    assert.equal(p.requests[0].options.method, "GET");
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

test("a timed-out status read retries with bounded backoff and retains a manual refresh fallback", async () => {
    let signal;
    const p = page({fetchResponse: (_url, options) => new Promise((_resolve, reject) => {
        signal = options.signal;
        signal.addEventListener("abort", () => reject(new Error("Aborted")));
    })});
    await p.tick();
    assert.equal(signal.aborted, false);
    await p.tick(15000);
    assert.equal(signal.aborted, true);
    assert.match(p.message.textContent, /Retrying automatically/);
    await p.tick(6000);
    await p.tick(15000);
    await p.tick(12000);
    await p.tick(15000);
    assert.equal(p.requests.length, 3);
    assert.equal(p.timers.size, 0);
    assert.match(p.message.textContent, /refresh status/i);
});

test("transient network and server errors retry status reads then resume normal polling", async () => {
    for (const failure of [() => Promise.reject(new Error("Offline")), () => Promise.resolve(response({}, {ok: false, status: 503}))]) {
        let requests = 0;
        const p = page({fetchResponse: () => ++requests === 1 ? failure() : Promise.resolve(response())});
        await p.tick();
        assert.match(p.message.textContent, /Retrying automatically/);
        await p.tick(6000);
        assert.equal(p.requests.length, 2);
        assert.equal(p.message.textContent, "Progress updates automatically.");
        assert.equal(p.timers.size, 1);
        await p.tick();
        assert.equal(p.requests.length, 3);
    }
});


test("polling reports the last successful check and clears stale feedback after recovery", async () => {
    let requests = 0;
    const p = page({fetchResponse: () => ++requests === 1 ? Promise.reject(new Error("Network unavailable")) : Promise.resolve(response())});
    await p.tick();
    assert.equal(p.operation.dataset.transferPollingState, "retrying");
    assert.equal(p.runningIndicator.hidden, true, "Do not animate a stale report as current work");
    assert.equal(p.resume.hidden, false);
    assert.equal(p.lastChecked.hidden, true);
    await p.tick(6000);
    assert.equal(p.operation.dataset.transferPollingState, "active");
    assert.equal(p.runningIndicator.hidden, false);
    assert.equal(p.resume.hidden, true);
    assert.equal(p.lastChecked.hidden, false);
    assert.match(p.lastChecked.textContent, /^Last checked at /);
});

test("manual status retry resumes reads without rerunning or cancelling a transfer", async () => {
    let requests = 0;
    const p = page({fetchResponse: () => ++requests === 1 ? Promise.resolve(response({}, {headers: {get: () => "text/html"}})) : Promise.resolve(response())});
    await p.tick();
    assert.equal(p.operation.dataset.transferPollingState, "paused");
    assert.equal(p.resume.hidden, false);
    p.resumeEvents.click();
    await flush();
    assert.equal(p.requests.length, 2);
    assert.ok(p.requests.every(request => request.options.method === "GET"));
    assert.equal(p.operation.dataset.transferPollingState, "active");
    assert.equal(p.resume.hidden, true);
    assert.deepEqual(p.navigations, []);
});

test("offline pages pause reads and reconnect with a fresh status check", async () => {
    const p = page();
    p.window.navigator.onLine = false;
    p.windowEvents.offline();
    assert.equal(p.timers.size, 0);
    assert.equal(p.requests.length, 0);
    assert.equal(p.runningIndicator.hidden, true);
    assert.equal(p.operation.dataset.transferPollingState, "offline");
    assert.match(p.message.textContent, /Showing the last reported progress/);
    p.resumeEvents.click();
    await flush();
    assert.equal(p.requests.length, 0, "A retry cannot turn an offline snapshot into current progress");
    p.window.navigator.onLine = true;
    p.windowEvents.online();
    await flush();
    assert.equal(p.requests.length, 1);
    assert.equal(p.operation.dataset.transferPollingState, "active");
    assert.equal(p.runningIndicator.hidden, false);
});

test("a response arriving after going offline cannot navigate or overwrite stale feedback", async () => {
    let finish;
    const p = page({fetchResponse: () => new Promise(resolve => { finish = resolve; })});
    await p.tick();
    p.windowEvents.offline();
    assert.equal(p.requests[0].options.signal.aborted, true);
    finish(response({status: "completed", cancellable: false}));
    await flush();
    assert.deepEqual(p.navigations, []);
    assert.equal(p.operation.dataset.transferPollingState, "offline");
    assert.equal(p.timers.size, 0);
});

test("a stalled JSON body has the same bounded deadline as its status request", async () => {
    const p = page({fetchResponse: response({}, {json: () => new Promise(() => {})})});
    await p.tick();
    await p.tick(15000);
    assert.equal(p.operation.dataset.transferPollingState, "retrying");
    assert.equal(p.resume.disabled, false);
    await p.tick(6000);
    assert.equal(p.requests.length, 2);
});


test("status checks still time out when the browser has no AbortController", async () => {
    const p = page({fetchResponse: () => new Promise(() => {})});
    p.window.AbortController = undefined;
    await p.tick();
    assert.equal(p.requests[0].options.signal, undefined);
    await p.tick(15000);
    assert.equal(p.operation.dataset.transferPollingState, "retrying");
    assert.equal(p.resume.disabled, false);
    await p.tick(6000);
    assert.equal(p.requests.length, 2);
});
