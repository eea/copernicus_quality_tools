"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const {File} = require("node:buffer");
const {queuePage, tick} = require("./helpers/queue-page.cjs");
const {nativeFileInput} = require("./helpers/native-file-input.cjs");

function uploadPage(feature) {
    const page = queuePage(feature);
    return {...page, chooser: nativeFileInput(page.picker.input)};
}

async function finishChecks(page, start = 0) {
    for (let index = start; index < page.requests.length; index++) page.checked(index);
    await tick();
}

for (const feature of ["products", "deliveries"]) {
    const extension = feature === "products" ? "json" : "zip";
    const first = () => new File(["first original bytes"], "first." + extension, {lastModified: 1});

    for (const count of [1, 2]) {
        test(feature + ": stages " + count + " native files chosen before upload scripts initialize", async () => {
            const selected = [first(), new File(["second original bytes"], "second." + extension)].slice(0, count);
            let chooser;
            const page = queuePage(feature, {
                beforeInitialize({picker}) {
                    picker.input.multiple = count > 1;
                    chooser = nativeFileInput(picker.input);
                    picker.input.click();
                    chooser.choose(selected);
                    assert.equal(chooser.files.length, count);
                },
            });
            await finishChecks(page);

            assert.deepEqual(Array.from(page.queue.entries, entry => entry.file), selected);
            assert.deepEqual(Array.from(page.queue.entries, entry => entry.state), selected.map(() => "selected"));
            assert.equal(page.container.hidden, false);
            assert.equal(chooser.files.length, 0);
            assert.equal(page.picker.input.value, "");
            assert.equal(page.transports.length, 0, "Enhancement must stage files without starting an upload");
            assert.equal(page.requests.length, feature === "products" ? 0 : count);
        });
    }

    test(feature + ": Browse stages every native selection before the live FileList is reset", async () => {
        const page = uploadPage(feature);
        const selected = [first(), new File(["second original bytes"], "second." + extension, {lastModified: 2})];

        page.picker.browse.click();
        assert.equal(page.chooser.opens, 1);
        assert.equal(Array.isArray(page.chooser.files), false);
        page.chooser.choose(selected);
        await finishChecks(page);

        assert.equal(page.chooser.files.length, 0);
        assert.equal(page.picker.input.value, "");
        assert.deepEqual(Array.from(page.queue.entries, entry => entry.file), selected);
        assert.deepEqual(Array.from(page.queue.entries, entry => entry.state), ["selected", "selected"]);
        assert.equal(page.all.hidden, false);
        assert.equal(page.container.hidden, false);
        assert.equal(await page.queue.entries[0].file.text(), "first original bytes");
        assert.equal(await page.queue.entries[1].file.text(), "second original bytes");
        assert.equal(page.transports.length, 0, "Choosing files must not start an upload");
        assert.equal(page.requests.length, feature === "products" ? 0 : 2);
    });

    test(feature + ": cancelling a reopened chooser preserves its staged files and controls", async () => {
        const page = uploadPage(feature);
        const selected = first();
        page.picker.browse.click();
        page.chooser.choose([selected]);
        await finishChecks(page);
        const requests = page.requests.length;

        page.picker.browse.click();
        page.chooser.cancel();

        assert.equal(page.chooser.opens, 2);
        assert.equal(page.queue.entries.length, 1);
        assert.equal(page.queue.entries[0].file, selected);
        assert.equal(page.queue.entries[0].state, "selected");
        assert.equal(page.picker.error.textContent, "");
        assert.equal(page.requests.length, requests);
        assert.equal(page.transports.length, 0);
    });

    test(feature + ": removing a file permits choosing the same native file again", async () => {
        const page = uploadPage(feature);
        const selected = first();
        page.picker.browse.click();
        page.chooser.choose([selected]);
        await finishChecks(page);
        page.click(page.queue.entries[0], "remove");
        assert.equal(page.queue.entries.length, 0);
        const requests = page.requests.length;

        page.picker.browse.click();
        page.chooser.choose([selected]);
        await finishChecks(page, requests);

        assert.equal(page.queue.entries.length, 1);
        assert.equal(page.queue.entries[0].file, selected);
        assert.equal(page.queue.entries[0].state, "selected");
        assert.equal(page.chooser.files.length, 0);
        assert.equal(page.transports.length, 0);
    });
}
