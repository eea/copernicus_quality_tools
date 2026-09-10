"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

function load(window, document, file) {
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/features/deliveries/", file), "utf8"), {window, document});
}

function page() {
    const dom = createDOM();
    const {window, document, $} = dom;
    window.QC_DELIVERIES_CONFIG = {canSubmit: true, canRunQc: true, canDelete: true, submissionEnabled: true};
    const queryPrototype = Object.getPrototypeOf($(document.body));
    const append = queryPrototype.append;
    const attr = queryPrototype.attr;
    queryPrototype.append = function(child) { return append.call(this, $(child)); };
    queryPrototype.attr = function(name, value) {
        if (name && typeof name === "object") {
            Object.entries(name).forEach(([key, entry]) => attr.call(this, key, entry));
            return this;
        }
        return attr.call(this, name, value);
    };
    queryPrototype.children = function() { return {length: this[0].children.length}; };
    load(window, document, "formatters.js");
    window.QcDeliveryFormatters.outerHtml = element => element[0];
    ["rows/status.js", "rows/actions.js", "rows/overview.js"].forEach(file => load(window, document, file));
    return dom;
}

const rejected = {
    id: 4, filename: "delivery.zip", delivery_status: "needs_correction",
    last_job_status: "ok", date_submitted: "2026-09-10T10:00:00Z",
    submission_review_state: "rejected", submission_url: "/submissions/receipt/",
    can_upload_correction: true, correction_upload_url: "/deliveries/upload/?correction_for=receipt",
    job_result_url: "/jobs/result/", can_delete: true, can_run_qc: true, can_submit: true,
};

test("review outcomes stay distinct from the QC result", () => {
    const {window} = page();
    const status = window.QcDeliveryRowStatus.presentation;
    assert.equal(status(rejected).label, "Correction needed");
    assert.match(status(rejected).detail, /Corrections requested/);
    assert.equal(status({...rejected, delivery_status: "accepted", submission_review_state: "accepted"}).label, "Accepted");
    assert.match(status({...rejected, delivery_status: "submitted", submission_review_state: "pending"}).detail, /Awaiting/);
    assert.equal(status({delivery_status: "passed", last_job_status: "ok"}).label, "Validated");
    assert.equal(status({delivery_status: "running", last_job_status: "waiting"}).label, "In queue");
    assert.equal(status({delivery_status: "running", last_job_status: "running"}).label, "In progress");
    assert.equal(status({delivery_status: "failed", last_job_status: "partial"}).label, "Failed");
    assert.match(status({delivery_status: "failed", last_job_status: "partial"}).detail, /Some checks failed/);
});

test("rejected rows prioritize feedback and owner correction, keeping the original protected", () => {
    const {window} = page();
    const plan = row => Array.from(window.QcDeliveryFormatters.actionPlan(row));
    assert.deepEqual(plan(rejected), ["review", "correction", "result"]);
    assert.deepEqual(plan({...rejected, can_upload_correction: false}), ["review", "result"]);
    assert.deepEqual(plan({...rejected, correction_upload_url: ""}), ["review", "result"]);
    const actions = window.actionsFormatter(null, rejected);
    assert.match(actions.textContent, /View feedbackUpload correctionView QC result/);
    assert.equal(actions.querySelector(".delivery-correction-link").getAttribute("href"), rejected.correction_upload_url);
});

test("running, in-review and accepted rows expose a quiet route to details", () => {
    const {window} = page();
    const plan = row => Array.from(window.QcDeliveryFormatters.actionPlan(row));
    for (const status of ["submitted", "accepted"]) {
        const row = {...rejected, delivery_status: status};
        assert.deepEqual(plan(row), ["review"]);
        const actions = window.actionsFormatter(null, row);
        assert.equal(actions.querySelector(".delivery-row-action--primary"), null);
        assert.equal(actions.querySelectorAll("a").length, 1);
        assert.equal(actions.querySelector(".delivery-review-link").getAttribute("href"), row.submission_url);
    }
    const running = {...rejected, delivery_status: "running", last_job_status: "running", date_submitted: null};
    assert.deepEqual(plan(running), ["result"]);
    const actions = window.actionsFormatter(null, running);
    assert.equal(actions.querySelector(".delivery-row-action--primary"), null);
    assert.equal(actions.textContent, "View QC progress");
    assert.deepEqual(plan({...running, job_result_url: ""}), []);
});

test("actionable deliveries retain one prominent next step", () => {
    const {window} = page();
    const row = {...rejected, date_submitted: null, submission_url: ""};
    const expected = {
        not_validated: ["", "Run QC"],
        failed: ["error", "Review QC result"],
        passed: ["ok", "Submit for review"],
    };
    for (const [status, [jobStatus, label]] of Object.entries(expected)) {
        const actions = window.actionsFormatter(null, {...row, delivery_status: status, last_job_status: jobStatus});
        assert.equal(actions.querySelectorAll(".delivery-row-action--primary").length, 1);
        assert.equal(actions.querySelector(".delivery-row-action--primary").textContent, label);
    }
});

test("feedback and reviewer names are literal text, with no disclosure without a review link", () => {
    const {window} = page();
    const notes = '<img src=x onerror="alert(1)">Please fix the geometry.';
    const row = {...rejected, review_notes: notes, review_actor_username: "<script>manager</script>"};
    const status = window.statusFormatter(null, row);
    assert.equal(status.querySelector(".delivery-review-feedback__comment").textContent, notes);
    assert.equal(status.querySelectorAll("img").length, 0);
    assert.equal(status.querySelectorAll("script").length, 0);
    assert.equal(window.statusFormatter(null, {...row, submission_url: ""}).querySelector(".delivery-review-feedback"), null);
});

test("review updates reach empty attention views and respect selection, focus and visibility", () => {
    const document = {hidden: false, activeElement: null};
    let selected = [], refreshed = [], rows = [{submission_url: "/receipt/", submission_review_state: "pending"}];
    const window = {
        QC_DELIVERIES_CONFIG: {submissionEnabled: true, updateJobStatuses: false},
        QcDeliveryTable: {rows: () => rows, selectedRows: () => selected, refresh: options => refreshed.push(options)},
        jQuery: () => ({bootstrapTable: () => ({pageNumber: 3})}),
    };
    load(window, document, "polling.js");
    window.QcDeliveryPolling.poll();
    assert.equal(refreshed.length, 1);
    assert.equal(refreshed[0].pageNumber, 3);
    assert.equal(refreshed[0].silent, true);
    selected = [{}]; window.QcDeliveryPolling.poll();
    selected = []; document.hidden = true; window.QcDeliveryPolling.poll();
    document.hidden = false; document.activeElement = {closest: () => ({})}; window.QcDeliveryPolling.poll();
    assert.equal(refreshed.length, 1);
    // Submitted rows are absent from the attention view, but a new rejection
    // must still appear without requiring the uploader to reload the page.
    document.activeElement = null; rows = []; window.QcDeliveryPolling.poll();
    assert.equal(refreshed.length, 2);
    window.QC_DELIVERIES_CONFIG.submissionEnabled = false;
    window.QcDeliveryPolling.poll();
    assert.equal(refreshed.length, 2);
});
