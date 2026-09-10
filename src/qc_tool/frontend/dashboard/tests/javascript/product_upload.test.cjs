"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const {queuePage, tick} = require("./helpers/queue-page.cjs");
const file = (name = "example.json", size = 100) => ({name, size});
const added = (created = true) => ({status: "ok", created, product_ident: "example", url: "/products/example/", message: created ? "Added to catalog." : "Already added."});

test("multiple specifications are staged with per-file Add and Add all, without sending requests", () => {
    const page = queuePage("products");
    assert.equal(page.container.hidden, true);
    assert.equal(page.native.hidden, true);
    assert.equal(page.picker.input.multiple, true);
    page.choose([file(), file("second.json")]);
    assert.equal(page.requests.length, 0);
    assert.equal(page.queue.entries.length, 2);
    assert.equal(page.all.hidden, false);
    assert.equal(page.all.textContent, "Add all (2)");
    for (const entry of page.queue.entries) {
        assert.equal(entry.state, "selected");
        assert.equal(entry.row.element.querySelector("[data-upload-add]").hidden, false);
        assert.equal(entry.row.element.querySelector('[role="progressbar"]').hidden, true);
    }
});

test("Add sends only the selected specification and marks success only after the response", async () => {
    const page = queuePage("products");
    const first = file();
    page.choose([first, file("later.json")]);
    page.click(page.queue.entries[0], "add");
    await tick();
    assert.equal(page.requests.length, 1);
    const request = page.requests[0];
    assert.equal(request.body.entries[0][0], "definition_file");
    assert.equal(request.body.entries[0][1], first);
    assert.equal(request.headers["X-CSRFToken"], "csrf-fixture");
    assert.equal(request.headers.Accept, "application/json");
    request.upload.fire("progress", {lengthComputable: true, loaded: 100, total: 100});
    assert.equal(page.queue.entries[0].state, "saving");
    assert.equal(page.queue.entries[0].percent, null);
    request.respond(200, added());
    await tick();
    assert.equal(page.queue.entries[0].state, "completed");
    assert.equal(page.queue.entries[1].state, "selected");
    assert.equal(page.requests.length, 1);
});

test("Add all runs sequentially and a failed file never erases another success", async () => {
    const page = queuePage("products");
    page.choose([file(), file("second.json"), file("third.json")]);
    page.all.click();
    page.all.click();
    await tick();
    assert.equal(page.requests.length, 1);
    page.requests[0].respond(200, added());
    await tick();
    assert.equal(page.requests.length, 2);
    page.requests[1].respond(400, {status: "error", message: "Invalid specification"});
    await tick();
    assert.equal(page.requests.length, 3);
    page.requests[2].respond(200, added(false));
    await tick();
    assert.deepEqual(Array.from(page.queue.entries, entry => entry.state), ["completed", "failed", "completed"]);
    assert.equal(page.queue.entries[2].label, "Already added");
    page.click(page.queue.entries[1], "retry");
    await tick();
    assert.equal(page.requests.length, 4);
    page.requests[3].respond(200, added());
    await tick();
    assert.ok(page.queue.entries.every(entry => entry.state === "completed"));
});

test("invalid or duplicate selections are visible and excluded from Add all", async () => {
    const page = queuePage("products");
    page.choose([file(), file("bad.zip"), file("empty.json", 0), file("large.json", 1048577), file("EXAMPLE.JSON")]);
    assert.equal(page.queue.entries[0].state, "selected");
    assert.ok(page.queue.entries.slice(1).every(entry => entry.state === "blocked"));
    assert.equal(page.all.hidden, true);
    page.click(page.queue.entries[0], "add");
    await tick();
    assert.equal(page.requests.length, 1);
    page.requests[0].respond(200, added());
    await tick();
    assert.equal(page.requests.length, 1);
});

test("removing a staged file preserves other selections and keyboard focus", () => {
    const page = queuePage("products");
    page.choose([file(), file("keep.json")]);
    page.click(page.queue.entries[0], "remove");
    assert.equal(page.queue.entries.length, 1);
    assert.equal(page.queue.entries[0].file.name, "keep.json");
    assert.equal(page.document.activeElement, page.picker.browse);
    assert.equal(page.requests.length, 0);
});

test("network interruptions remain retryable and authentication stops remaining batch work", async () => {
    const page = queuePage("products");
    page.choose([file()]); page.click(page.queue.entries[0], "add"); await tick();
    page.requests[0].fire("timeout"); await tick();
    assert.equal(page.queue.entries[0].state, "failed");
    assert.match(page.queue.entries[0].message, /Retry to confirm/);
    const auth = queuePage("products", {authExpired: true});
    auth.choose([file(), file("second.json")]); auth.all.click(); await tick();
    auth.requests[0].respond(401, {}); await tick();
    assert.equal(auth.requests.length, 1);
    assert.equal(auth.picker.browse.disabled, true);
    assert.ok(auth.queue.entries.every(entry => entry.state !== "completed"));
});

test("a malformed success response never marks a specification as added", async () => {
    const page = queuePage("products");
    page.choose([file()]); page.click(page.queue.entries[0], "add"); await tick();
    page.requests[0].respond(200, {status: "ok"}); await tick();
    assert.equal(page.queue.entries[0].state, "failed");
});
