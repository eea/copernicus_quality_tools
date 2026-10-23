"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const {queuePage, tick} = require("./helpers/queue-page.cjs");
const chunkPosts = page => page.requests.filter(request => request.method === "POST" &&
    new URL(request.url, "http://qc.test").pathname === "/resumable_upload/");

async function waitFor(predicate) {
    for (let attempt = 0; attempt < 20; attempt++) {
        if (predicate()) return;
        await new Promise(resolve => setTimeout(resolve, 1));
    }
    assert.ok(predicate(), "Expected vendor transport activity did not occur.");
}

async function startRealUpload(page) {
    page.choose([new File(["delivery ZIP bytes"], "delivery.zip", {type: "application/zip"})]);
    page.checked(); await tick();
    page.click(page.queue.entries[0], "add");
    page.checked();
    await waitFor(() => page.requests.some(request => request.method === "GET"));
    return page.requests.find(request => request.method === "GET");
}

test("real resumable transport sends at most one POST after an unavailable probe and retries only on request", async () => {
    const page = queuePage("deliveries", {realResumable: true});
    const probe = await startRealUpload(page);
    const originalIdentity = new URL(probe.url, "http://qc.test").searchParams.get("resumableIdentifier");
    assert.match(originalIdentity, /^upload-[a-f0-9]{32}$/);
    probe.respond(503, {status: "error", code: "upload_storage_unavailable", message: "Upload storage is unavailable."});
    const posts = chunkPosts(page);
    assert.equal(posts.length, 1);
    posts[0].respond(503, {status: "error", code: "upload_storage_unavailable", message: "Upload storage is unavailable."});
    await tick(); await tick();
    assert.equal(chunkPosts(page).length, 1);
    assert.equal(page.queue.entries[0].state, "failed");
    assert.match(page.queue.entries[0].message, /Upload storage is unavailable/);
    assert.equal(page.queue.entries[0].row.element.querySelector("[data-upload-retry]").hidden, false);

    page.click(page.queue.entries[0], "retry");
    await waitFor(() => page.requests.filter(request => request.method === "GET").length === 2);
    const resumed = page.requests.filter(request => request.method === "GET")[1];
    assert.equal(new URL(resumed.url, "http://qc.test").searchParams.get("resumableIdentifier"), originalIdentity);
    resumed.respond(200, null);
    await tick();
    assert.equal(page.queue.entries[0].state, "completed", "A committed receipt can be recovered by a successful probe.");
    assert.equal(chunkPosts(page).length, 1);
});

test("a real network failure stops without retry timers and manual Retry resumes the same chunks", async () => {
    const page = queuePage("deliveries", {realResumable: true});
    const probe = await startRealUpload(page);
    probe.respond(404, null);
    const post = chunkPosts(page)[0];
    post.status = 0;
    post.readyState = 4;
    post.responseText = "";
    post.fire("error");
    await tick(); await tick();
    assert.equal(page.queue.entries[0].state, "failed");
    assert.equal(page.transports.length, 1);
    assert.equal(chunkPosts(page).length, 1);
    page.click(page.queue.entries[0], "retry");
    await waitFor(() => page.requests.filter(request => request.method === "GET").length === 2);
    const resumed = page.requests.filter(request => request.method === "GET")[1];
    assert.equal(new URL(resumed.url, "http://qc.test").searchParams.get("resumableIdentifier"),
        new URL(probe.url, "http://qc.test").searchParams.get("resumableIdentifier"));
    resumed.respond(404, null);
    const retried = chunkPosts(page);
    assert.equal(retried.length, 2);
    retried[1].respond(200, {status: "ok", delivery_id: 17});
    await tick();
    assert.equal(page.queue.entries[0].state, "completed");
    assert.equal(page.queue.entries[0].url, "/deliveries/jobs/17/");
});
