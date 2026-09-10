"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function page() {
    const document = {hidden: false, activeElement: null};
    const state = {rows: [], selected: [], requests: [], refreshes: [], announcements: []};
    const $ = () => ({bootstrapTable: () => ({pageNumber: 2})});
    $.ajax = options => {
        const request = {options};
        state.requests.push(request);
        return {done(handler) { request.done = handler; return this; }, always(handler) { request.always = handler; return this; }};
    };
    const window = {
        jQuery: $, QC_DELIVERIES_CONFIG: {submissionEnabled: false, updateJobStatuses: true, updateJobUrlTemplate: "/jobs/00000000-0000-0000-0000-000000000000/"},
        QcDeliveryTable: {rows: () => state.rows, selectedRows: () => state.selected, refresh: options => state.refreshes.push(options), announce: message => state.announcements.push(message)}
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/features/deliveries/polling.js"), "utf8"), {window, document});
    const poll = () => window.QcDeliveryPolling.poll();
    const finish = (request, status) => { request.done({last_job_status: status}); request.always(); };
    return {state, document, window, poll, finish};
}

test("an empty action view refreshes when QC finishes in a different stage, even without submissions", () => {
    const p = page();
    p.poll();
    assert.equal(p.state.refreshes.length, 1);
    assert.equal(p.state.refreshes[0].pageNumber, 2);
});

test("finished QC refreshes stage membership once and preserves an active selection", () => {
    const p = page();
    p.state.rows = [{last_job_uuid: "a", last_job_status: "running"}, {last_job_uuid: "b", last_job_status: "waiting"}];
    p.poll();
    p.finish(p.state.requests[0], "ok");
    assert.equal(p.state.refreshes.length, 0);
    p.finish(p.state.requests[1], "running");
    assert.equal(p.state.refreshes.length, 1);
    assert.equal(p.state.announcements.length, 1);
    p.poll();
    p.state.selected = [{}];
    p.finish(p.state.requests[2], "ok");
    p.finish(p.state.requests[3], "running");
    assert.equal(p.state.refreshes.length, 1);
});
