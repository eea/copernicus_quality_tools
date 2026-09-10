"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");
const {createDOM, addPicker} = require("./dom.cjs");
const tick = () => new Promise(resolve => setImmediate(resolve));

function queuePage(feature, {authExpired = false} = {}) {
    const {window, document} = createDOM();
    function node(tag, attrs, parent) {
        const result = document.createElement(tag);
        Object.entries(attrs || {}).forEach(([key, value]) => result.setAttribute(key, value));
        parent?.append(result);
        return result;
    }
    const root = node("section", {id: feature === "products" ? "product-definition-upload-card" : "resumable-upload", "data-upload-url": "/resumable_upload/", "data-check-url": "/deliveries/upload/check/", "data-deliveries-url": "/deliveries/"}, document.body);
    const form = node("form", {id: "product-definition-upload", "data-max-file-bytes": "1048576"}, root);
    form.action = "/products/upload/";
    const picker = addPicker(document, form, {id: "queued", accept: feature === "products" ? ".json" : ".zip"});
    const native = node("button", {"data-upload-native": ""}, form);
    const container = node("div", {"data-upload-queue": "", hidden: ""}, form);
    const summary = node("p", {"data-upload-queue-summary": ""}, container);
    const all = node("button", {"data-upload-add-all": ""}, container);
    const batchDescription = node("p", {"data-upload-batch-description": ""}, container);
    const list = node("ul", {"data-upload-list": ""}, container);
    const hint = node("p", {"data-upload-queue-hint": "", hidden: ""}, container);
    node("div", {"data-upload-announcement": ""}, root);
    node("div", {"data-upload-feedback": ""}, root);
    window.crypto = webcrypto;
    window.qcCsrf = {getToken: () => "csrf-fixture"};
    window.qcAuth = {handleUnauthorizedXhr: () => authExpired, redirectFromPayload: () => authExpired};
    class Events {
        constructor() { this.events = {}; }
        addEventListener(name, handler) { (this.events[name] ||= []).push(handler); }
        fire(name, event = {}) { (this.events[name] || []).forEach(handler => handler(event)); }
    }
    const requests = [];
    window.XMLHttpRequest = class extends Events {
        constructor() { super(); this.upload = new Events(); this.headers = {}; requests.push(this); }
        open(method, url) { this.method = method; this.url = url; }
        setRequestHeader(name, value) { this.headers[name] = value; }
        send(body) { this.body = body; }
        respond(status, payload) { this.status = status; this.response = payload; this.fire("load"); }
    };
    window.FormData = class { constructor() { this.entries = []; } append(key, value) { this.entries.push([key, value]); } };
    const transports = [];
    window.Resumable = class {
        constructor(options) { this.options = options; this.events = {}; this.support = true; this.uploadCalls = 0; transports.push(this); }
        on(name, callback) { this.events[name] = callback; }
        fire(name, ...args) { this.events[name]?.(...args); }
        addFile(file) { this.file = file; this.fire("fileAdded", file); }
        upload() { this.uploadCalls++; }
        pause() { this.paused = true; }
        cancel() { this.fire("complete"); }
        progress(fraction) { this.fire("fileProgress", {progress: () => fraction}); }
        success(id = 1) { this.fire("fileSuccess", this.file, JSON.stringify({status: "ok", delivery_id: id})); }
        fail(payload) { this.fire("fileError", this.file, typeof payload === "string" ? payload : JSON.stringify(payload)); }
    };
    for (const file of ["shared/uploads.js", "shared/upload-queue.js", "features/" + feature + "/upload.js"]) {
        vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../../static/dashboard/js/", file), "utf8"), {window, document});
    }
    const queue = feature === "products" ? window.qcProductUpload : window.qcDeliveryUpload;
    return {
        window, document, root, form, picker, native, container, summary, all, batchDescription, list, hint, queue, requests, transports,
        choose(files) { picker.input.files = files; picker.input.dispatchEvent({type: "change"}); },
        click(entry, hook) { const button = entry.row.element.querySelector("[data-upload-" + hook + "]"); if (button.hidden) throw new Error("Hidden button " + hook); button.click(); },
        checked(index = requests.length - 1, exists = false, extra = {}) {
            const filename = JSON.parse(requests[index].body).filenames[0];
            requests[index].respond(200, {status: "ok", files: [{filename, exists, delivery_id: exists ? 7 : null, can_overwrite: exists, url: exists ? "/deliveries/jobs/7/" : null, ...extra}]});
        }
    };
}
module.exports = {queuePage, tick};
