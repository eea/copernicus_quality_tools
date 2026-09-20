"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function jobFailure(responseJSON) {
    const dialogs = [];
    const document = {};
    const $ = value => ({
        ready() {},
        val() { return value === "#select_product" ? "product" : "1"; },
        modal() {}, each() {},
        attr() { return "/deliveries/jobs/create/"; },
        text(text) { return {textContent: text}; }
    });
    $.ajax = options => options.error({responseJSON});
    const context = {$, document, BootstrapDialog: {show: dialog => dialogs.push(dialog)}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/features/jobs/setup.js"), "utf8"), context);
    context.create_job();
    return dialogs[0];
}

test("job creation explains backend filename errors as plain text", () => {
    const message = 'The filename <img src=x onerror="alert(1)"> does not match the selected specification.';
    const dialog = jobFailure({code: "delivery_name_invalid", message});
    assert.equal(dialog.message.textContent, message);
});

test("job creation retains a safe fallback for missing or malformed error messages", () => {
    for (const payload of [undefined, {}, {message: {html: "untrusted"}}]) {
        assert.equal(jobFailure(payload).message.textContent, "Error running job. Please try later.");
    }
});
