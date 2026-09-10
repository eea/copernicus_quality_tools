"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

const formats = ["json", "csv", "xlsx", "xml"];
const settled = () => new Promise(resolve => setImmediate(resolve));
const success = value => new Response(value || "serialized export", {headers: {"Content-Type": "application/octet-stream"}});

function fixture({columns, rows = [], options = {sidePagination: "client"}, config, token = "test-csrf", fetch} = {}) {
    options.columns = options.columns || [columns || [{field: "filename", title: "Filename"}]];
    const {document} = createDOM();
    const configuration = document.createElement("script");
    configuration.id = "qc-table-export-config";
    configuration.textContent = JSON.stringify(config || {
        url: "/data/tables/export/", iconSprite: "/static/dashboard/icons/ui.svg",
        formats: formats.map(value => ({value, label: value.toUpperCase()}))
    });
    document.body.appendChild(configuration);
    const container = document.createElement("div");
    container.className = "bootstrap-table";
    const table = document.createElement("table");
    container.appendChild(table);
    document.body.appendChild(container);
    const blobs = [], revoked = [], links = [], requests = [], fetchRequests = [], dataRequests = [];
    const createElement = document.createElement;
    document.createElement = tag => {
        const element = createElement(tag);
        if (tag === "template") {
            element.content = {textContent: ""};
            Object.defineProperty(element, "innerHTML", {set(value) {
                // The fixture needs only known markup; browser parsing is tested separately.
                element.content.textContent = value.replace(/<[^>]*>/g, "")
                    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
            }});
        }
        if (tag === "a") element.click = () => links.push({href: element.href, download: element.download});
        return element;
    };
    const $table = {
        jquery: "test", 0: table,
        bootstrapTable(command, params) {
            if (command === "getVisibleColumns") return options.columns.flat().filter(column => column.visible !== false);
            if (command === "getOptions") return options;
            if (command === "getData") { dataRequests.push(params); return rows; }
            throw new Error("Unexpected table operation: " + command);
        }
    };
    class BrowserURL extends URL {}
    BrowserURL.createObjectURL = blob => { blobs.push(blob); return "blob:test-" + blobs.length; };
    BrowserURL.revokeObjectURL = url => revoked.push(url);
    const window = {
        document, URL: BrowserURL, jQuery: () => $table,
        qcCsrf: {getToken() { return token; }},
        location: {href: "https://qc.example/deliveries/", assign(url) { requests.push(url); }},
        setTimeout(callback) { callback(); },
        async fetch(url, settings) {
            fetchRequests.push({url, ...settings});
            return fetch ? fetch(url, settings) : success();
        }
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/shared/table-exports.js"), "utf8"), {window});
    return {
        exports: window.QcTableExports, $table, container, document, blobs, revoked, links, requests, dataRequests,
        fetchRequests, configuration,
        payload(index = 0) { return JSON.parse(fetchRequests[index].body); },
        addControl() {
            container.querySelector("[data-qc-table-export]")?.remove();
            const control = document.createElement("button");
            control.setAttribute("data-qc-table-export", "true");
            const label = document.createElement("span");
            label.className = "qc-data-table__export-label";
            label.textContent = "Export";
            control.appendChild(label);
            container.appendChild(control);
            return control;
        },
        click(format) {
            const link = document.createElement("a");
            link.setAttribute("data-qc-export-format", format);
            container.appendChild(link);
            container.dispatchEvent({type: "click", target: link});
        }
    };
}

for (const format of formats) {
    test(format.toUpperCase() + " uses the shared serializer with a CSRF-protected same-origin request", async () => {
        const p = fixture({rows: [{filename: "report.zip"}]});
        assert.equal(await p.exports.exportFile(p.$table, format, {filename: "deliveries.xml"}), 1);
        assert.equal(p.fetchRequests[0].url, "https://qc.example/data/tables/export/");
        assert.equal(p.fetchRequests[0].method, "POST");
        assert.equal(p.fetchRequests[0].credentials, "same-origin");
        assert.equal(p.fetchRequests[0].headers["X-CSRFToken"], "test-csrf");
        assert.equal(p.fetchRequests[0].headers["Content-Type"], "application/json");
        assert.deepEqual(p.payload(), {format, filename: "deliveries." + format,
            columns: [{field: "filename", label: "Filename"}], rows: [{filename: "report.zip"}]});
        assert.equal(await p.blobs[0].text(), "serialized export");
        assert.deepEqual(p.links, [{href: "blob:test-1", download: "deliveries." + format}]);
        assert.deepEqual(p.revoked, ["blob:test-1"]);
        assert.equal(p.requests.length, 0);
        assert.equal(p.document.querySelectorAll("a").length, 0);
    });
}

test("every format exports all data columns in schema order, regardless of visibility", async () => {
    const columns = [
        {field: "selected", checkbox: true}, {field: "radio", radio: true},
        {field: "filename", title: "File"}, {field: "size", title: "Size", visible: false},
        {field: "status", title: "Status", exportField: "delivery_status", visible: false},
        {field: "actions", title: "Actions"}, {field: "internal", exportable: false},
        {field: "secret", "data-exportable": "false"}
    ];
    const p = fixture({
        columns,
        rows: [{filename: "second.zip", size: 2, delivery_status: "passed", internal: "private"},
            {filename: "first.zip", size: 1, delivery_status: "failed"}]
    });
    for (const [index, format] of formats.entries()) {
        assert.equal(await p.exports.exportFile(p.$table, format), 2);
        assert.equal(p.dataRequests[index].useCurrentPage, false);
        assert.deepEqual(p.payload(index).columns, [{field: "filename", label: "File"}, {field: "size", label: "Size"}, {field: "delivery_status", label: "Status"}]);
        assert.deepEqual(p.payload(index).rows, [{filename: "second.zip", size: 2, delivery_status: "passed"},
            {filename: "first.zip", size: 1, delivery_status: "failed"}]);
        // Simulate display changes, including hiding every data column.
        columns.forEach(column => { column.visible = index % 2 === 1; });
    }
});

test("grouped table headers do not become export columns or disturb hidden field order", async () => {
    const p = fixture({options: {sidePagination: "client", columns: [
        [{field: "id", title: "ID", rowspan: 2}, {title: "Details", colspan: 2}],
        [{field: "name", title: "Name", visible: false}, {field: "size", title: "Size"}]
    ]}, rows: [{id: 1, name: "file.zip", size: 42}]});
    await p.exports.exportFile(p.$table, "json");
    assert.deepEqual(p.payload().columns.map(column => column.field), ["id", "name", "size"]);
    assert.deepEqual(p.payload().rows, [{id: 1, name: "file.zip", size: 42}]);
});

test("raw strings, formulas and numeric types are preserved for the central serializers", async () => {
    const row = {filename: "<report> České.zip", note: 'one, "two"\r\nthree', formula: " \t=1+1", negative: -5, empty: null};
    const p = fixture({columns: Object.keys(row).map(field => ({field})), rows: [row]});
    for (const format of formats) await p.exports.exportFile(p.$table, format);
    p.fetchRequests.forEach((request, index) => assert.deepEqual(p.payload(index).rows, [row]));
});

test("HTML-backed cells opt in to text extraction while aliases and callbacks retain typed data", async () => {
    const p = fixture({
        columns: [
            {field: "description", title: "<strong>Product</strong>", exportHtml: true},
            {field: "display", title: "ID", exportField: "id"},
            {field: "progress", title: "Progress", exportValue: (_value, row) => row.count / row.total},
            {field: "meta", title: "Metadata"}, {field: "date", title: "Date"}
        ],
        rows: [{description: '<a href="/products/1">Land &amp; cover</a>', display: "#12", id: 12, count: 2, total: 4,
            meta: {regions: ["CZ", "BE"]}, date: new Date("2026-09-10T12:00:00Z")}]
    });
    await p.exports.exportFile(p.$table, "json");
    assert.deepEqual(p.payload().rows, [{description: "Land & cover", id: 12, progress: 0.5,
        meta: {regions: ["CZ", "BE"]}, date: "2026-09-10T12:00:00.000Z"}]);
    assert.equal(p.payload().columns[0].label, "Product");
    assert.equal(p.payload().columns[1].field, "id");
});

test("projection handles nulls and prototype-like fields without changing plain text", async () => {
    const p = fixture({columns: [
        {field: "filename"}, {field: "status"}, {field: "unset"}, {field: "__proto__"}
    ], rows: [{filename: "<keep>.zip", status: "<span>Passed</span>", ["__proto__"]: "literal field"}]});
    await p.exports.exportFile(p.$table, "xml", {htmlFields: ["status"]});
    assert.deepEqual(p.payload().rows, [{filename: "<keep>.zip", status: "Passed", unset: null, ["__proto__"]: "literal field"}]);
});

test("page adapters project typed metrics without changing column metadata", async () => {
    const p = fixture({columns: [{field: "completion", title: "Completion"}], rows: [{completion: "<strong>25%</strong> 1 accepted of 4", accepted: 1, expected: 4}]});
    await p.exports.exportFile(p.$table, "xlsx", {values: {completion: (_value, row, column) => {
        assert.equal(column.field, "completion");
        return row.accepted / row.expected * 100;
    }}});
    assert.deepEqual(p.payload().rows, [{completion: 25}]);
    await p.exports.exportFile(p.$table, "json", {values: {completion: () => "<literal>"}, htmlFields: ["completion"]});
    assert.deepEqual(p.payload(1).rows, [{completion: "<literal>"}]);
});

test("empty filtered tables still send column headers for every format", async () => {
    const p = fixture();
    for (const format of formats) {
        assert.equal(await p.exports.exportFile(p.$table, format), 0);
    }
    p.fetchRequests.forEach((_request, index) => {
        assert.deepEqual(p.payload(index).rows, []);
        assert.deepEqual(p.payload(index).columns, [{field: "filename", label: "Filename"}]);
    });
});

test("server exports support the same formats and preserve current filtering and sorting without page limits", async () => {
    let workflow = "completed";
    const p = fixture({columns: [{field: "filename"}, {field: "status", exportField: "delivery_status"}], options: {sidePagination: "server"}});
    const settings = {server: {
        url: '/deliveries/export/?limit=20&other=keep&columns=%5B%22filename%22%5D',
        getQuery: () => ({delivery_view: workflow, search: "a & b", sort: "filename", order: "desc", limit: 20, offset: 40,
            pageNumber: 3, pageSize: 20, columns: '["filename"]'})
    }};
    for (const format of formats) {
        await p.exports.exportFile(p.$table, format, settings);
        const url = new URL(p.requests.at(-1));
        assert.equal(url.pathname, "/deliveries/export/");
        assert.equal(url.searchParams.get("delivery_view"), workflow);
        assert.equal(url.searchParams.get("format"), format);
        assert.equal(url.searchParams.has("columns"), false);
        assert.equal(url.searchParams.get("search"), "a & b");
        assert.equal(url.searchParams.get("sort"), "filename");
        assert.equal(url.searchParams.get("order"), "desc");
        assert.equal(url.searchParams.get("other"), "keep");
        for (const key of ["limit", "offset", "pageNumber", "pageSize"]) assert.equal(url.searchParams.has(key), false);
        workflow = "action_required";
    }
    assert.equal(p.dataRequests.length, 0);
    assert.equal(p.fetchRequests.length, 0);
});

test("invalid formats, unloaded server pages and tables without data columns fail without a request", async () => {
    const server = fixture({options: {sidePagination: "server"}});
    await assert.rejects(server.exports.exportFile(server.$table, "csv"), /server export is required/);
    await assert.rejects(server.exports.exportFile(server.$table, "unknown", {server: {url: "/export/"}}), /does not support/);
    assert.equal(server.requests.length, 0);
    const empty = fixture({columns: [{field: "actions"}]});
    await assert.rejects(empty.exports.exportFile(empty.$table, "json"), /no exportable data columns/);
    const ordinary = fixture();
    await assert.rejects(ordinary.exports.exportFile(ordinary.$table, "unknown"), /does not support/);
    assert.equal(ordinary.fetchRequests.length, 0);
});

test("CSRF tokens never leave the application origin and missing tokens produce a useful error", async () => {
    const external = fixture({config: {url: "https://other.example/export/", formats: [{value: "csv", label: "CSV"}]}});
    await assert.rejects(external.exports.exportFile(external.$table, "csv"), /must belong to QC Tool/);
    assert.equal(external.fetchRequests.length, 0);
    const missing = fixture({token: ""});
    await assert.rejects(missing.exports.exportFile(missing.$table, "csv"), /Refresh this page before exporting/);
    assert.equal(missing.fetchRequests.length, 0);
    await assert.rejects(missing.exports.exportFile(missing.$table, "csv", {server: {url: "https://other.example/export/"}}), /must belong to QC Tool/);
    assert.equal(missing.requests.length, 0);
});

test("the canonical menu always shows JSON, CSV, XLSX and XML and replaces its delegated listener", async () => {
    const p = fixture({rows: [{filename: "sample.zip"}]});
    const button = p.exports.button(p.$table, {label: 'Export "products"', formats: [{value: "csv", label: "Legacy"}]});
    const html = button.html();
    assert.match(html, /data-toggle="dropdown"/);
    assert.match(html, /aria-haspopup="true" aria-expanded="false"/);
    assert.deepEqual([...html.matchAll(/role="menuitem" data-qc-export-format="([^"]+)">([^<]+)</g)]
        .map(match => [match[1], match[2]]), formats.map(format => [format, format.toUpperCase()]));
    assert.ok(html.includes("Export &quot;products&quot;"));
    button.html();
    p.click("csv");
    await settled();
    assert.equal(p.blobs.length, 1);
    assert.equal(p.container.events.click.length, 1);
    p.click("unknown");
    await settled();
    assert.equal(p.fetchRequests.length, 1);
});

test("busy exports block duplicate downloads and survive toolbar rebuilds before restoring focus", async () => {
    let finish;
    const pending = new Promise(resolve => { finish = resolve; });
    const p = fixture({fetch: () => pending});
    const button = p.exports.button(p.$table);
    button.html();
    const first = p.addControl();
    p.click("xlsx");
    assert.equal(first.disabled, true);
    assert.equal(first.getAttribute("aria-busy"), "true");
    assert.equal(first.textContent, "Creating export…");
    assert.match(button.html(), /disabled aria-busy="true"/);
    const rebuilt = p.addControl();
    p.click("json");
    assert.equal(p.fetchRequests.length, 1);
    finish(success());
    await settled();
    assert.equal(rebuilt.disabled, false);
    assert.equal(rebuilt.getAttribute("aria-busy"), "false");
    assert.equal(rebuilt.textContent, "Export");
    assert.equal(p.document.activeElement, rebuilt);
    assert.equal(p.blobs.length, 1);
});

test("HTTP failures appear inline and successful retries clear the error", async () => {
    let fail = true;
    const reported = [];
    const p = fixture({fetch: () => fail ? new Response(JSON.stringify({error: "Reduce the export size."}), {status: 413}) : success()});
    p.exports.button(p.$table, {onError: error => reported.push(error.message)}).html();
    const control = p.addControl();
    p.click("xml");
    await settled();
    const alert = p.container.querySelector(".qc-data-table__export-error");
    assert.equal(alert.getAttribute("role"), "alert");
    assert.equal(alert.hidden, false);
    assert.match(alert.textContent, /Reduce the export size/);
    assert.equal(reported.length, 1);
    assert.equal(control.disabled, false);
    assert.equal(p.blobs.length, 0);
    fail = false;
    p.click("xml");
    await settled();
    assert.equal(alert.hidden, true);
    assert.equal(p.blobs.length, 1);
});

test("network and session errors never become misleading downloads", async () => {
    const network = fixture({fetch: () => { throw new Error("network down"); }});
    await assert.rejects(network.exports.exportFile(network.$table, "json"), /Check your connection/);
    const forbidden = fixture({fetch: () => new Response("Forbidden", {status: 403})});
    await assert.rejects(forbidden.exports.exportFile(forbidden.$table, "xlsx"), /session could not be verified/);
    const login = fixture({fetch: () => new Response("<html>Login</html>", {headers: {"Content-Type": "text/html"}})});
    await assert.rejects(login.exports.exportFile(login.$table, "csv"), /sign in again/);
    for (const p of [network, forbidden, login]) assert.equal(p.blobs.length, 0);
});
