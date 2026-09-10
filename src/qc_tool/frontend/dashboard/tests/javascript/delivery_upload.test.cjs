"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const {queuePage, tick} = require("./helpers/queue-page.cjs");
const file = (name = "delivery.zip") => ({name, size: 100});
async function staged(page, files = [file()]) {
    page.choose(files);
    page.requests.slice().forEach((_request, index) => page.checked(index));
    await tick();
}
async function start(page, entry = page.queue.entries[0]) {
    page.click(entry, "add");
    page.checked();
    await tick();
    return page.transports.at(-1);
}

test("delivery selection checks own filenames without uploading until Add", async () => {
    const page = queuePage("deliveries");
    page.choose([file()]);
    assert.equal(page.transports.length, 0);
    assert.equal(page.queue.entries[0].state, "checking");
    assert.deepEqual(JSON.parse(page.requests[0].body), {filenames: ["delivery.zip"]});
    page.checked(); await tick();
    assert.equal(page.queue.entries[0].state, "selected");
    const upload = await start(page);
    assert.equal(page.requests.length, 2, "Check again immediately before adding.");
    assert.equal(upload.uploadCalls, 1);
});

test("existing filename offers explicit Overwrite with a warning and link", async () => {
    const page = queuePage("deliveries");
    page.choose([file()]); page.checked(0, true); await tick();
    const entry = page.queue.entries[0];
    assert.equal(entry.state, "replaceable");
    assert.match(entry.message, /delivery with this name/);
    assert.equal(entry.url, "/deliveries/jobs/7/");
    assert.equal(entry.row.element.querySelector("[data-upload-add]").hidden, true);
    assert.equal(entry.row.element.querySelector("[data-upload-overwrite]").hidden, false);
    assert.equal(page.transports.length, 0);
});

test("a filename that becomes occupied before Add is blocked without a transfer", async () => {
    const page = queuePage("deliveries"); await staged(page);
    page.click(page.queue.entries[0], "add"); page.checked(1, true); await tick();
    assert.equal(page.queue.entries[0].state, "replaceable");
    assert.equal(page.transports.length, 0);
});

test("100 percent and vendor complete do not report success before server registration", async () => {
    const page = queuePage("deliveries"); await staged(page);
    const upload = await start(page);
    upload.progress(1); upload.fire("complete"); await tick();
    assert.equal(page.queue.entries[0].state, "saving");
    upload.fail({message: "Registration failed"}); await tick();
    upload.success(); upload.progress(1); await tick();
    assert.equal(page.queue.entries[0].state, "failed");
    assert.equal(page.queue.entries[0].message, "Registration failed");
});

test("delivery retry retains its receipt identity; selecting another file uses a fresh identity", async () => {
    const page = queuePage("deliveries"); await staged(page);
    const first = await start(page);
    const identifier = first.options.generateUniqueIdentifier();
    assert.match(identifier, /^upload-[a-f0-9]{32}$/);
    first.fail({message: "Confirmation lost"}); await tick();
    page.click(page.queue.entries[0], "retry"); await tick();
    const retry = page.transports[1];
    assert.equal(retry.options.generateUniqueIdentifier(), identifier);
    assert.equal(page.requests.length, 2, "Receipt recovery must not be blocked by its own newly registered row.");
    retry.success(); await tick();
    assert.equal(page.queue.entries[0].state, "completed");
    await staged(page, [file("second.zip")]);
    const second = await start(page, page.queue.entries[1]);
    assert.notEqual(second.options.generateUniqueIdentifier(), identifier);
});

test("pause, resume and cancellation affect only the active file", async () => {
    const page = queuePage("deliveries"); await staged(page, [file(), file("second.zip")]);
    const upload = await start(page);
    upload.progress(0.4);
    page.click(page.queue.entries[0], "pause");
    assert.equal(page.queue.entries[0].state, "paused");
    page.click(page.queue.entries[0], "resume");
    assert.equal(page.queue.entries[0].state, "uploading");
    page.click(page.queue.entries[0], "cancel"); await tick();
    upload.success(); await tick();
    assert.equal(page.queue.entries[0].state, "canceled");
    assert.equal(page.queue.entries[1].state, "selected");
    assert.equal(page.transports.length, 1);
});

test("an unavailable filename check requires retry rather than blindly sending the file", async () => {
    const page = queuePage("deliveries"); page.choose([file()]);
    page.requests[0].fire("error"); await tick();
    assert.equal(page.queue.entries[0].state, "failed");
    assert.equal(page.transports.length, 0);
    page.click(page.queue.entries[0], "retry"); page.checked(1); await tick();
    assert.equal(page.transports.length, 1);
});

test("Add all skips protected deliveries and confirms each new delivery independently", async () => {
    const page = queuePage("deliveries");
    page.choose([file("existing.zip"), file("one.zip"), file("two.zip")]);
    page.checked(0, true, {can_overwrite: false, overwrite_reason: "This delivery has a submission."}); page.checked(1); page.checked(2); await tick();
    assert.equal(page.all.hidden, false);
    assert.equal(page.all.textContent, "Upload all (2)");
    page.all.click(); page.checked(3); await tick();
    assert.equal(page.all.hidden, false);
    assert.equal(page.all.disabled, true);
    assert.match(page.all.textContent, /Uploading.*2 remaining/);
    assert.equal(page.transports.length, 1);
    page.transports[0].success(8); await tick();
    page.checked(4); await tick();
    assert.equal(page.transports.length, 2);
    page.transports[1].success(9); await tick();
    assert.deepEqual(Array.from(page.queue.entries, entry => entry.state), ["blocked", "completed", "completed"]);
});

test("the registration conflict guard remains visible if a race beats the preflight", async () => {
    const page = queuePage("deliveries"); await staged(page);
    const upload = await start(page);
    upload.fail({code: "delivery_exists", message: "You already have a delivery with this filename."}); await tick();
    assert.equal(page.queue.entries[0].state, "failed");
    assert.equal(page.queue.entries[0].row.element.querySelector("[data-upload-retry]").hidden, false);
    assert.equal(page.queue.entries[0].url, "/deliveries/");
});

test("an unexpected successful HTTP body cannot report an added delivery", async () => {
    const page = queuePage("deliveries"); await staged(page);
    const upload = await start(page);
    upload.fire("fileSuccess", upload.file, "<html>Service unavailable</html>"); await tick();
    assert.equal(page.queue.entries[0].state, "failed");
    assert.match(page.queue.entries[0].message, /did not confirm/);
});

test("a receipt recovered through empty successful chunk probes is accepted", async () => {
    const page = queuePage("deliveries"); await staged(page);
    const upload = await start(page);
    upload.fire("fileSuccess", upload.file, ""); await tick();
    assert.equal(page.queue.entries[0].state, "completed");
    assert.equal(page.queue.entries[0].url, "/deliveries/");
});

test("Overwrite explicitly pins the inspected delivery and requires fresh QC", async () => {
    const page = queuePage("deliveries");
    page.choose([file()]); page.checked(0, true); await tick();
    page.click(page.queue.entries[0], "overwrite"); page.checked(1, true); await tick();
    assert.equal(page.transports.length, 1);
    const upload = page.transports[0];
    assert.equal(upload.options.query.overwrite_delivery_id, 7);
    upload.fail({message: "Response lost"}); await tick();
    page.click(page.queue.entries[0], "retry"); await tick();
    assert.equal(page.transports[1].options.query.overwrite_delivery_id, 7);
    assert.equal(page.transports[1].options.generateUniqueIdentifier(), upload.options.generateUniqueIdentifier());
    page.transports[1].success(8); await tick();
    assert.equal(page.queue.entries[0].label, "Replaced");
    assert.equal(page.queue.entries[0].url, "/deliveries/jobs/8/");
});

test("mixed batch clearly adds new files and overwrites eligible duplicates", async () => {
    const page = queuePage("deliveries");
    page.choose([file("new.zip"), file("existing.zip"), file("protected.zip")]);
    page.checked(0); page.checked(1, true); page.checked(2, true, {can_overwrite: false}); await tick();
    assert.equal(page.all.textContent, "Replace and upload all (2)");
    assert.match(page.batchDescription.textContent, /1 new file · 1 replacement/);
    page.all.click(); page.checked(3); await tick();
    assert.equal(page.transports[0].options.query.overwrite_delivery_id, undefined);
    page.transports[0].success(10); await tick();
    page.checked(4, true); await tick();
    assert.equal(page.transports[1].options.query.overwrite_delivery_id, 7);
    page.transports[1].success(11); await tick();
    assert.deepEqual(Array.from(page.queue.entries, entry => entry.state), ["completed", "completed", "blocked"]);
});

test("a batch of only duplicates also offers an overwrite batch action", async () => {
    const page = queuePage("deliveries");
    page.choose([file("one.zip"), file("two.zip")]); page.checked(0, true); page.checked(1, true); await tick();
    assert.equal(page.all.hidden, false);
    assert.equal(page.all.textContent, "Replace and upload all (2)");
    assert.match(page.batchDescription.textContent, /^2 replacements/);
});

test("a changed overwrite target requires a new explicit choice", async () => {
    const page = queuePage("deliveries");
    page.choose([file()]); page.checked(0, true); await tick();
    page.click(page.queue.entries[0], "overwrite"); page.checked(1, true, {delivery_id: 8}); await tick();
    assert.equal(page.transports.length, 0);
    assert.equal(page.queue.entries[0].state, "replaceable");
    page.click(page.queue.entries[0], "overwrite"); page.checked(2, true, {delivery_id: 8}); await tick();
    assert.equal(page.transports[0].options.query.overwrite_delivery_id, 8);
});

test("a file becoming protected before batch overwrite is skipped", async () => {
    const page = queuePage("deliveries");
    page.choose([file(), file("next.zip")]); page.checked(0, true); page.checked(1); await tick();
    page.all.click(); page.checked(2, true, {can_overwrite: false, overwrite_reason: "Submitted deliveries are retained."}); await tick();
    page.checked(3); await tick();
    assert.equal(page.queue.entries[0].state, "blocked");
    assert.match(page.queue.entries[0].message, /retained/);
    assert.equal(page.transports.length, 1);
    assert.equal(page.transports[0].file.name, "next.zip");
});

const correction = {id: "c31729bc-f62d-4dcc-8636-0520b510a52e", filename: "delivery.zip", deliveryId: 7};

test("corrections reject a changed filename locally, including letter case", async () => {
    const page = queuePage("deliveries", {correction});
    assert.equal(page.picker.input.multiple, false);
    page.choose([file("different.zip"), file("Delivery.zip")]);
    await tick();
    assert.equal(page.requests.length, 0);
    assert.equal(page.transports.length, 0);
    page.queue.entries.forEach(entry => {
        assert.equal(entry.state, "blocked");
        assert.equal(entry.label, "Filename must match");
        assert.match(entry.message, /Keep the original filename: "delivery.zip"/);
        assert.equal(entry.row.element.querySelector("[data-upload-overwrite]").hidden, true);
    });
});

test("correction upload pins the rejected submission and opens fresh QC", async () => {
    const page = queuePage("deliveries", {correction});
    page.choose([file()]);
    assert.deepEqual(JSON.parse(page.requests[0].body), {filenames: ["delivery.zip"], correction_submission_id: correction.id});
    page.checked(0, true); await tick();
    const entry = page.queue.entries[0];
    assert.equal(entry.label, "Ready for correction");
    assert.equal(entry.row.element.querySelector("[data-upload-overwrite]").textContent, "Upload correction");
    assert.match(entry.message, /rejected submission and its files will stay/);
    page.click(entry, "overwrite"); page.checked(1, true); await tick();
    assert.deepEqual({...page.transports[0].options.query}, {overwrite_delivery_id: 7, correction_submission_id: correction.id});
    page.transports[0].success(8); await tick();
    assert.equal(entry.label, "Correction uploaded");
    assert.equal(entry.url, "/deliveries/jobs/new/?deliveries=8");
    assert.equal(entry.linkLabel, "Run quality checks");
    assert.match(entry.message, /then submit this correction for review/);
});

test("a correction cannot silently switch to a different delivery or a new upload", async () => {
    for (const extra of [{delivery_id: 8}, {exists: false}, {can_overwrite: false}]) {
        const page = queuePage("deliveries", {correction});
        page.choose([file()]); page.checked(0, true); await tick();
        page.click(page.queue.entries[0], "overwrite"); page.checked(1, true, extra); await tick();
        assert.equal(page.transports.length, 0);
        assert.equal(page.queue.entries[0].state, "blocked");
        assert.match(page.queue.entries[0].message, /can no longer receive a correction/);
    }
});

test("only one same-named corrected ZIP can be eligible in the queue", async () => {
    const page = queuePage("deliveries", {correction});
    page.choose([file(), file()]); page.checked(0, true); await tick();
    assert.deepEqual(Array.from(page.queue.entries, entry => entry.state), ["replaceable", "blocked"]);
    assert.equal(page.all.hidden, true);
    page.click(page.queue.entries[0], "overwrite"); page.checked(1, true); await tick();
    page.transports[0].fail({message: "Response lost"}); await tick();
    page.click(page.queue.entries[0], "retry"); await tick();
    assert.equal(page.transports[1].options.query.correction_submission_id, correction.id);
    assert.equal(page.transports[1].options.generateUniqueIdentifier(), page.transports[0].options.generateUniqueIdentifier());
});
