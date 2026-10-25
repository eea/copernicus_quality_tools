"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {createDOM} = require("./helpers/dom.cjs");

const source = fs.readFileSync(path.join(__dirname, "../../static/dashboard/js/admin/storage.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

function page({count = 3, checked = [], disabled = [], stored = null, storageThrows = false, withExplorer = true,
    withSelection = true, withConnection = true, clipboard = text => Promise.resolve(text)} = {}) {
    const dom = createDOM();
    const {document, window} = dom;
    const node = (tag, attributes = {}, parent = document.body) => {
        const result = document.createElement(tag);
        Object.entries(attributes).forEach(([key, value]) => result.setAttribute(key, value));
        parent.append(result);
        return result;
    };
    const storageReads = [], storageWrites = [], clipboardWrites = [], network = [], timers = [];
    let storedValue = stored;
    const localStorage = {
        getItem(key) { storageReads.push(key); if (storageThrows) throw new Error("storage denied"); return storedValue; },
        setItem(key, value) { storageWrites.push([key, value]); if (storageThrows) throw new Error("storage full"); storedValue = value; },
    };
    window.localStorage = localStorage;
    window.fetch = (...args) => { network.push(args); throw new Error("Downloads must stay native"); };
    window.setTimeout = (...args) => { timers.push(args); throw new Error("Storage controls need no timers"); };
    window.navigator = clipboard === null ? {} : {clipboard: {writeText(text) { clipboardWrites.push(text); return clipboard(text); }}};
    let explorer, controls, listView, gridView, form, selectAll, selectionStatus, selectedDownload, clear, keyboardHint;
    const items = [], rows = [];
    if (withExplorer) {
        explorer = node("section", {"data-storage-explorer": "", "data-storage-view": "list"});
        controls = node("div", {"data-storage-view-controls": "", hidden: ""}, explorer);
        listView = node("button", {type: "button", "data-storage-view-choice": "list", "aria-pressed": "true"}, controls);
        gridView = node("button", {type: "button", "data-storage-view-choice": "grid", "aria-pressed": "false"}, controls);
        keyboardHint = node("span", {"data-storage-keyboard-hint": "", hidden: ""}, explorer);
    }
    if (withSelection) {
        form = node("form", {method: "get", action: "/admin/storage/archive/", "data-storage-selection-form": ""}, explorer || document.body);
        selectAll = node("input", {type: "checkbox", "data-storage-select-all": "", hidden: ""}, form);
        selectionStatus = node("span", {"data-storage-selection-status": "", role: "status", "aria-live": "polite"}, form);
        selectedDownload = node("button", {type: "submit", "data-storage-selected-download": ""}, form);
        clear = node("button", {type: "button", "data-storage-clear": "", hidden: ""}, form);
        for (let index = 0; index < count; index++) {
            const row = node("tr", {"data-storage-row": ""}, form);
            rows.push(row);
            const item = node("input", {type: "checkbox", name: "paths", value: `folder/file ${index}.tif`, "data-storage-item": ""}, row);
            item.value = `folder/file ${index}.tif`;
            item.checked = checked.includes(index);
            item.disabled = disabled.includes(index);
            items.push(item);
        }
    }
    const folderDownload = node("a", {href: "/admin/storage/archive/?area=work", "data-storage-download": ""});
    const downloadStatus = node("p", {"data-storage-download-status": "", role: "status", "aria-live": "polite", hidden: ""});
    let address, command, copyAddress, copyCommand, copyStatus;
    if (withConnection) {
        address = node("code", {id: "storage-sftp-address"});
        address.textContent = "sftp://example.test:2222";
        command = node("code", {id: "storage-sftp-command"});
        command.textContent = "sftp -P 2222 user@example.test";
        copyAddress = node("button", {type: "button", "data-storage-copy": "", "data-storage-copy-target": address.id});
        copyCommand = node("button", {type: "button", "data-storage-copy": "", "data-storage-copy-target": command.id});
        copyStatus = node("p", {"data-storage-copy-status": "", hidden: ""});
    }
    vm.runInNewContext(source, {window, document, Promise});
    return {
        ...dom, node, explorer, controls, listView, gridView, form, selectAll, selectionStatus, selectedDownload, clear, items, rows, keyboardHint,
        folderDownload, downloadStatus, address, command, copyAddress, copyCommand, copyStatus,
        storageReads, storageWrites, clipboardWrites, network, timers,
        stored(value) { storedValue = value; },
        change(item, value) { item.checked = value; form.dispatchEvent({type: "change", target: item}); },
        submit(prevented = false) {
            const event = {type: "submit", defaultPrevented: prevented};
            form.dispatchEvent(event);
            return event;
        },
        restore(persisted = true) { window.dispatchEvent({type: "pageshow", persisted}); },
        key(key, options = {}) {
            const event = {type: "keydown", key, target: explorer, ...options};
            explorer.dispatchEvent(event);
            return event;
        },
    };
}

test("empty selection has clear instructions, an available select-all and a disabled download", () => {
    const ui = page();
    assert.equal(ui.selectAll.hidden, false);
    assert.equal(ui.selectAll.checked, false);
    assert.equal(ui.selectAll.indeterminate, false);
    assert.equal(ui.selectedDownload.disabled, true);
    assert.equal(ui.clear.hidden, true);
    assert.equal(ui.selectionStatus.textContent, "Select files or folders to download together.");
    assert.deepEqual(ui.network, []);
    assert.deepEqual(ui.timers, []);
});

test("individual changes announce this page's selection and set the all-items checkbox state", () => {
    const ui = page();
    ui.change(ui.items[0], true);
    assert.equal(ui.selectionStatus.textContent, "1 item selected on this page.");
    assert.equal(ui.selectAll.checked, false);
    assert.equal(ui.selectAll.indeterminate, true);
    assert.equal(ui.selectedDownload.disabled, false);
    assert.equal(ui.clear.hidden, false);
    ui.change(ui.items[1], true);
    ui.change(ui.items[2], true);
    assert.equal(ui.selectionStatus.textContent, "3 items selected on this page.");
    assert.equal(ui.selectAll.checked, true);
    assert.equal(ui.selectAll.indeterminate, false);
    ui.change(ui.items[1], false);
    assert.equal(ui.selectAll.checked, false);
    assert.equal(ui.selectAll.indeterminate, true);
});

test("select-all and Clear affect exactly the enabled items on the current page", () => {
    const ui = page({disabled: [2]});
    ui.change(ui.selectAll, true);
    assert.deepEqual(ui.items.map(item => Boolean(item.checked)), [true, true, false]);
    assert.equal(ui.selectionStatus.textContent, "2 items selected on this page.");
    assert.equal(ui.selectAll.checked, true);
    assert.equal(ui.selectAll.indeterminate, false);
    ui.clear.click();
    assert.deepEqual(ui.items.map(item => Boolean(item.checked)), [false, false, false]);
    assert.equal(ui.selectAll.checked, false);
    assert.equal(ui.selectAll.indeterminate, false);
    assert.equal(ui.selectedDownload.disabled, true);
    assert.equal(ui.clear.hidden, true);
    ui.change(ui.selectAll, true);
    ui.change(ui.selectAll, false);
    assert.deepEqual(ui.items.map(item => Boolean(item.checked)), [false, false, false]);
});

test("Ctrl and Command A select only this explorer page's enabled items", () => {
    for (const modifier of ["ctrlKey", "metaKey"]) {
        const ui = page({disabled: [2]});
        const unrelated = ui.node("input", {type: "checkbox", "data-storage-item": "", name: "paths"});
        assert.equal(ui.keyboardHint.hidden, false);
        const event = ui.key("a", {[modifier]: true, target: ui.listView});
        assert.equal(event.defaultPrevented, true);
        assert.deepEqual(ui.items.map(item => Boolean(item.checked)), [true, true, false]);
        assert.equal(Boolean(unrelated.checked), false);
        assert.equal(ui.selectionStatus.textContent, "2 items selected on this page.");
        assert.equal(ui.selectedDownload.disabled, false);
        assert.deepEqual(ui.rows.map(row => row.classList.contains("storage-row--selected")), [true, true, false]);
        assert.deepEqual(ui.network, []);
        assert.deepEqual(ui.storageWrites, []);
    }
});

test("Escape clears selected rows and download guidance, then leaves native Escape alone", () => {
    const ui = page({checked: [0, 1]});
    ui.submit();
    assert.equal(ui.downloadStatus.hidden, false);
    assert.equal(ui.key("Escape").defaultPrevented, true);
    assert.ok(ui.items.every(item => !item.checked));
    assert.ok(ui.rows.every(row => !row.classList.contains("storage-row--selected")));
    assert.equal(ui.clear.hidden, true);
    assert.equal(ui.selectedDownload.disabled, true);
    assert.equal(ui.downloadStatus.hidden, true);
    assert.notEqual(ui.key("Escape").defaultPrevented, true);
});

test("select-all and Escape work while a file checkbox or radio has focus", () => {
    for (const modifier of ["ctrlKey", "metaKey"]) {
        const ui = page({checked: [0], disabled: [2]});
        const radio = ui.node("input", {type: "radio"}, ui.explorer);
        for (const target of [ui.items[0], ui.selectAll, radio]) {
            target.focus();
            assert.equal(ui.key("a", {[modifier]: true, target: ui.document.activeElement}).defaultPrevented, true);
            assert.deepEqual(ui.items.map(item => Boolean(item.checked)), [true, true, false]);
            assert.equal(ui.selectedDownload.disabled, false);
            assert.equal(ui.key("Escape", {target: ui.document.activeElement}).defaultPrevented, true);
            assert.deepEqual(ui.items.map(item => Boolean(item.checked)), [false, false, false]);
            assert.equal(ui.selectedDownload.disabled, true);
            assert.equal(ui.clear.hidden, true);
        }
        assert.deepEqual(ui.network, []);
    }
});

test("selection shortcuts preserve text editing, form fields and editable ancestors", () => {
    const ui = page({checked: [0]});
    const editable = ui.node("div", {contenteditable: "true"}, ui.explorer);
    const targets = [
        ui.node("input", {type: "search"}, ui.explorer),
        ui.node("input", {type: "text"}, ui.explorer),
        ui.node("textarea", {}, ui.explorer),
        ui.node("select", {}, ui.explorer),
        editable,
        ui.node("span", {}, editable),
    ];
    for (const target of targets) {
        assert.notEqual(ui.key("a", {ctrlKey: true, target}).defaultPrevented, true);
        assert.notEqual(ui.key("A", {metaKey: true, target}).defaultPrevented, true);
        assert.notEqual(ui.key("Escape", {target}).defaultPrevented, true);
        assert.deepEqual(ui.items.map(item => Boolean(item.checked)), [true, false, false]);
    }
});

test("shortcuts never affect another area, cancelled events or unrelated key combinations", () => {
    const ui = page({checked: [0]});
    const outside = ui.node("button");
    const events = [
        ["a", {ctrlKey: true, target: outside}],
        ["Escape", {target: outside}],
        ["a", {}],
        ["b", {ctrlKey: true}],
        ["a", {ctrlKey: true, shiftKey: true}],
        ["a", {ctrlKey: true, altKey: true}],
        ["Escape", {ctrlKey: true}],
        ["Escape", {shiftKey: true}],
        ["Escape", {altKey: true}],
    ];
    for (const [key, options] of events) assert.notEqual(ui.key(key, options).defaultPrevented, true);
    ui.key("a", {ctrlKey: true, defaultPrevented: true});
    ui.key("Escape", {defaultPrevented: true});
    assert.deepEqual(ui.items.map(item => Boolean(item.checked)), [true, false, false]);
    for (const options of [{count: 0}, {withSelection: false}, {disabled: [0, 1, 2]}]) {
        const empty = page(options);
        assert.notEqual(empty.key("a", {ctrlKey: true}).defaultPrevented, true);
        assert.notEqual(empty.key("Escape").defaultPrevented, true);
    }
});

test("an empty folder or entirely disabled list cannot create an empty selected ZIP request", () => {
    for (const options of [{count: 0}, {count: 2, checked: [0, 1], disabled: [0, 1]}]) {
        const ui = page(options);
        assert.equal(ui.selectAll.disabled, true);
        assert.equal(ui.selectedDownload.disabled, true);
        assert.equal(ui.clear.hidden, true);
        assert.equal(ui.submit().defaultPrevented, true);
        assert.equal(ui.selectionStatus.textContent, "Select at least one file or folder to download.");
        assert.equal(ui.downloadStatus.hidden, true);
        assert.deepEqual(ui.network, []);
    }
});

test("selected ZIP submits stay native GETs with unchanged values and no permanent pending state", () => {
    const ui = page({checked: [0, 2]});
    const values = ui.items.map(item => item.value);
    assert.equal(ui.submit().defaultPrevented, false);
    assert.equal(ui.form.getAttribute("method"), "get");
    assert.equal(ui.form.getAttribute("action"), "/admin/storage/archive/");
    assert.deepEqual(ui.items.map(item => item.value), values);
    assert.deepEqual(ui.items.map(item => item.checked), [true, false, true]);
    assert.equal(ui.selectedDownload.disabled, false);
    assert.equal(ui.form.getAttribute("aria-busy"), null);
    assert.equal(ui.form.getAttribute("data-admin-pending"), null);
    assert.equal(ui.downloadStatus.hidden, false);
    assert.match(ui.downloadStatus.textContent, /browser will start the ZIP after checking/);
    assert.match(ui.downloadStatus.textContent, /Keep the download connection open/);
    assert.doesNotMatch(ui.downloadStatus.textContent, /complete|ready|success/i);
    assert.equal(ui.submit().defaultPrevented, false, "A later explicit download remains available on this page");
    assert.equal(ui.selectedDownload.disabled, false);
    assert.deepEqual(ui.network, []);
    assert.deepEqual(ui.timers, []);
});

test("folder links leave the native download untouched and show guidance without claiming completion", () => {
    const ui = page();
    const event = {type: "click", defaultPrevented: false};
    ui.folderDownload.dispatchEvent(event);
    assert.equal(event.defaultPrevented, false);
    assert.equal(ui.folderDownload.getAttribute("href"), "/admin/storage/archive/?area=work");
    assert.equal(ui.downloadStatus.hidden, false);
    assert.match(ui.downloadStatus.textContent, /until your browser finishes/);
    ui.folderDownload.click();
    assert.deepEqual(ui.network, []);
    assert.deepEqual(ui.timers, []);
});

test("a cancelled download does not imply that a request started", () => {
    const ui = page({checked: [0]});
    ui.folderDownload.dispatchEvent({type: "click", defaultPrevented: true});
    assert.equal(ui.downloadStatus.hidden, true);
    assert.equal(ui.submit(true).defaultPrevented, true);
    assert.equal(ui.downloadStatus.hidden, true);
});

test("new selection clears stale download guidance and a new page never inherits selected paths", () => {
    const ui = page({checked: [0]});
    ui.submit();
    assert.equal(ui.downloadStatus.hidden, false);
    ui.change(ui.items[1], true);
    assert.equal(ui.downloadStatus.hidden, true);
    const nextPage = page({stored: "grid"});
    assert.equal(nextPage.selectedDownload.disabled, true);
    assert.ok(nextPage.items.every(item => !item.checked));
    assert.deepEqual(ui.storageWrites, [], "Selection is never persisted into another folder or page");
});

test("Back restoration derives controls from native checkbox values and clears stale download status", () => {
    for (const persisted of [false, true]) {
        const ui = page({checked: [0]});
        ui.submit();
        ui.items[0].checked = false;
        ui.items[2].checked = true;
        ui.selectAll.checked = true;
        ui.selectAll.indeterminate = false;
        ui.selectedDownload.disabled = true;
        ui.clear.hidden = true;
        ui.restore(persisted);
        assert.equal(ui.downloadStatus.hidden, true);
        assert.equal(ui.downloadStatus.textContent, "");
        assert.equal(ui.selectionStatus.textContent, "1 item selected on this page.");
        assert.equal(ui.selectAll.checked, false);
        assert.equal(ui.selectAll.indeterminate, true);
        assert.equal(ui.selectedDownload.disabled, false);
        assert.equal(ui.clear.hidden, false);
        ui.items.forEach(item => { item.checked = false; });
        ui.restore(persisted);
        assert.equal(ui.selectedDownload.disabled, true);
        assert.equal(ui.clear.hidden, true);
    }
});

test("list and icon controls expose their state and persist only the allowed view preference", () => {
    const ui = page({stored: "grid"});
    assert.equal(ui.controls.hidden, false);
    assert.equal(ui.explorer.getAttribute("data-storage-view"), "grid");
    assert.equal(ui.gridView.getAttribute("aria-pressed"), "true");
    assert.equal(ui.listView.getAttribute("aria-pressed"), "false");
    ui.listView.click();
    assert.equal(ui.explorer.getAttribute("data-storage-view"), "list");
    assert.equal(ui.gridView.getAttribute("aria-pressed"), "false");
    assert.equal(ui.listView.getAttribute("aria-pressed"), "true");
    assert.deepEqual(ui.storageWrites, [["qc-storage-view", "list"]]);
    assert.ok(ui.storageReads.every(key => key === "qc-storage-view"));
    assert.deepEqual(ui.network, []);
});

test("invalid or inaccessible local storage leaves working list and icon controls", () => {
    for (const options of [{stored: "<img src=x>"}, {stored: "GRID"}, {storageThrows: true}]) {
        const ui = page(options);
        assert.equal(ui.explorer.getAttribute("data-storage-view"), "list");
        ui.gridView.click();
        assert.equal(ui.explorer.getAttribute("data-storage-view"), "grid");
        assert.equal(ui.gridView.getAttribute("aria-pressed"), "true");
        assert.deepEqual(ui.storageWrites, [["qc-storage-view", "grid"]]);
    }
});

test("Back restoration refreshes the view preference changed in another folder", () => {
    const ui = page();
    ui.stored("grid");
    ui.restore();
    assert.equal(ui.explorer.getAttribute("data-storage-view"), "grid");
    assert.equal(ui.gridView.getAttribute("aria-pressed"), "true");
});

test("connection copy reads exact code text only after the user's click and announces success", async () => {
    const ui = page();
    ui.address.textContent = '<sftp://example.test/a?x="1">';
    assert.deepEqual(ui.clipboardWrites, []);
    ui.copyAddress.click();
    assert.deepEqual(ui.clipboardWrites, ['<sftp://example.test/a?x="1">']);
    await flush();
    assert.equal(ui.copyStatus.hidden, false);
    assert.equal(ui.copyStatus.getAttribute("role"), "status");
    assert.equal(ui.copyStatus.getAttribute("aria-live"), "polite");
    assert.equal(ui.copyStatus.textContent, "Copied to clipboard.");
    assert.equal(ui.copyStatus.children.length, 0, "Code content is never injected as markup");
    ui.copyCommand.click();
    await flush();
    assert.equal(ui.clipboardWrites[1], "sftp -P 2222 user@example.test");
    assert.deepEqual(ui.network, []);
});

test("denied, missing and synchronously failed clipboard access offers manual copying", async () => {
    for (const clipboard of [null, () => Promise.reject(new Error("not allowed")), () => { throw new Error("unavailable"); }]) {
        const ui = page({clipboard});
        ui.copyAddress.click();
        await flush();
        assert.equal(ui.copyStatus.hidden, false);
        assert.match(ui.copyStatus.textContent, /Select the text above and copy it manually/);
        assert.deepEqual(ui.network, []);
        assert.deepEqual(ui.timers, []);
    }
});

test("browser clipboard getters that deny access also show the manual fallback", () => {
    const ui = page();
    Object.defineProperty(ui.window.navigator, "clipboard", {get() { throw new Error("policy denied"); }});
    ui.copyAddress.click();
    assert.match(ui.copyStatus.textContent, /copy it manually/);
    assert.deepEqual(ui.clipboardWrites, []);
});

test("copying an absent or non-code target never reads or writes unrelated content", async () => {
    for (const target of ["missing", "unrelated"]) {
        const ui = page();
        const unrelated = ui.node("input", {id: "unrelated"});
        unrelated.value = "private form value";
        ui.copyAddress.setAttribute("data-storage-copy-target", target);
        ui.copyAddress.click();
        await flush();
        assert.deepEqual(ui.clipboardWrites, []);
        assert.match(ui.copyStatus.textContent, /copy it manually/);
        assert.doesNotMatch(ui.copyStatus.textContent, /private form value/);
    }
});

test("a newer copy result wins if earlier clipboard requests finish out of order", async () => {
    const pending = [];
    const ui = page({clipboard: () => new Promise((resolve, reject) => { pending.push({resolve, reject}); })});
    ui.copyAddress.click();
    ui.copyCommand.click();
    pending[1].resolve();
    await flush();
    assert.equal(ui.copyStatus.textContent, "Copied to clipboard.");
    pending[0].reject(new Error("old denied request"));
    await flush();
    assert.equal(ui.copyStatus.textContent, "Copied to clipboard.");
    assert.equal(ui.clipboardWrites.length, 2, "Only explicit copy clicks wrote to the clipboard");
});

test("Back restoration clears copy feedback and ignores a late old clipboard result", async () => {
    let finish;
    const ui = page({clipboard: () => new Promise(resolve => { finish = resolve; })});
    ui.copyAddress.click();
    assert.equal(ui.copyStatus.textContent, "Copying…");
    ui.restore();
    finish();
    await flush();
    assert.equal(ui.copyStatus.hidden, true);
    assert.equal(ui.copyStatus.textContent, "");
    assert.equal(ui.clipboardWrites.length, 1);
});

test("a cancelled copy and pages without explorer or connection controls stay inert", async () => {
    const ui = page();
    ui.copyAddress.dispatchEvent({type: "click", defaultPrevented: true});
    await flush();
    assert.deepEqual(ui.clipboardWrites, []);
    const bare = page({withExplorer: false, withSelection: false, withConnection: false});
    bare.restore();
    assert.deepEqual(bare.network, []);
    assert.deepEqual(bare.timers, []);
    assert.deepEqual(bare.clipboardWrites, []);
});
