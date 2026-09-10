/* Explicit per-file and batch actions; adapters own checks and transport. */
(function(window) {
    "use strict";
    var ui = window.qcUpload;
    if (!ui) return;

    ui.createQueue = function(root, options) {
        var labels = Object.assign({add: "Add", overwrite: "Overwrite", addAll: "Add all", overwriteAll: "Add all & overwrite",
            ready: "Ready to add", pending: "Adding…", failed: "Could not add", completed: "added", running: "Adding…"}, options.labels);
        var list = root.querySelector("[data-upload-list]");
        var container = root.querySelector("[data-upload-queue]");
        var summary = root.querySelector("[data-upload-queue-summary]");
        var all = root.querySelector("[data-upload-add-all]");
        var batchDescription = root.querySelector("[data-upload-batch-description]");
        var hint = root.querySelector("[data-upload-queue-hint]");
        var announcement = root.querySelector("[data-upload-announcement]");
        var entries = [];
        var active = null;
        var redirected = false;
        var batchActive = false;
        var serial = 0;
        var picker = ui.createPicker(root, {
            extensions: options.extensions, maxBytes: options.maxBytes,
            deferValidation: true, onSelect: select
        });
        picker.input.multiple = true;
        root.querySelectorAll("[data-upload-native]").forEach(function(node) { node.hidden = true; });

        function present(entry, value) {
            Object.assign(entry, value);
            entry.row.update({
                state: entry.state, label: entry.label, percent: entry.percent,
                error: entry.message, url: entry.url, linkLabel: entry.linkLabel,
                canPause: Boolean(entry.controls && entry.controls.pause),
                canCancel: Boolean(entry.controls && entry.controls.cancel),
                canRemove: entry !== active || ["checking", "uploading", "saving", "paused"].indexOf(entry.state) === -1
            });
            refresh();
        }
        function refresh() {
            var ready = entries.filter(function(entry) { return entry.state === "selected"; }).length;
            var replacements = entries.filter(function(entry) { return entry.state === "replaceable"; }).length;
            var checking = entries.filter(function(entry) { return entry.state === "checking"; }).length;
            var done = entries.filter(function(entry) { return entry.state === "completed"; }).length;
            var waiting = entries.filter(function(entry) { return entry.state === "queued"; }).length;
            var needsAttention = entries.filter(function(entry) { return ["blocked", "failed", "canceled"].indexOf(entry.state) !== -1; }).length;
            container.hidden = !entries.length;
            summary.textContent = entries.length + (entries.length === 1 ? " file" : " files") +
                (ready ? " · " + ready + " ready" : "") + (checking ? " · " + checking + " checking" : "") +
                (replacements ? " · " + replacements + " to replace" : "") +
                (done ? " · " + done + " " + labels.completed : "") + (needsAttention ? " · " + needsAttention + " to review" : "");
            var runningBatch = batchActive && Boolean(active || waiting);
            all.hidden = !runningBatch && (ready + replacements < 2 || checking > 0 || redirected);
            all.disabled = Boolean(active) || redirected;
            all.textContent = runningBatch ? labels.running + " (" + (waiting + (active ? 1 : 0)) + " remaining)" :
                (replacements ? labels.overwriteAll : labels.addAll) + " (" + (ready + replacements) + ")";
            if (batchDescription) {
                batchDescription.hidden = all.hidden || runningBatch || !replacements;
                batchDescription.textContent = (ready ? ready + " new " + (ready === 1 ? "file" : "files") + " · " : "") +
                    replacements + (replacements === 1 ? " replacement" : " replacements") + ". Files that need attention are skipped.";
            }
            hint.hidden = !active;
            picker.setSelected(entries.length > 0);
        }
        function fail(entry, error) {
            if (error.redirecting) {
                redirected = true;
                picker.setBusy(true);
                present(entry, {state: "checking", label: "Sign in to continue", message: "", percent: null});
            } else {
                if (error.recheck) {
                    entry.attempted = false;
                    entry.overwriteKey = null;
                    entry.availableOverwriteKey = null;
                }
                present(entry, {
                    state: error.canceled ? "canceled" : error.blocked ? "blocked" : "failed",
                    label: error.canceled ? "Canceled" : error.blocked ? "Already uploaded" : labels.failed,
                    message: error.message || "The file could not be added. Try again.",
                    percent: null, url: error.url || "", linkLabel: error.linkLabel || ""
                });
            }
        }
        async function check(entry) {
            if (!options.check || entry.attempted) return true;
            present(entry, {state: "checking", label: "Checking your uploads…", message: "", percent: null});
            try {
                var result = await options.check(entry);
                if (entries.indexOf(entry) === -1) return false;
                if (result && result.blocked) {
                    var replaceable = result.overwriteKey !== undefined && result.overwriteKey !== null;
                    if (replaceable && entry.overwriteKey === result.overwriteKey) return true;
                    entry.overwriteKey = null;
                    entry.availableOverwriteKey = replaceable ? result.overwriteKey : null;
                    present(entry, {state: replaceable ? "replaceable" : "blocked", label: result.label || (replaceable ? "Already uploaded" : "Needs attention"), message: result.message, url: result.url, linkLabel: result.linkLabel, percent: null});
                    return false;
                }
                if (entry.overwriteKey !== null) {
                    entry.overwriteKey = null;
                    entry.availableOverwriteKey = null;
                    present(entry, {state: "selected", label: labels.ready, message: "The original file is no longer present. Select " + labels.add + " to continue."});
                    return false;
                }
                return true;
            } catch (error) {
                if (entries.indexOf(entry) !== -1) fail(entry, error);
                return false;
            }
        }
        function remove(entry) {
            if (entry === active || entries.indexOf(entry) === -1) return;
            entries.splice(entries.indexOf(entry), 1);
            entry.row.element.remove();
            refresh();
            announcement.textContent = entry.file.name + " removed from the queue.";
            picker.browse.focus();
        }
        function select(files) {
            files.forEach(function(file) {
                var key = options.key ? options.key(file) : file.name;
                var duplicate = entries.some(function(entry) { return entry.key === key && !entry.duplicate; });
                var entry = {id: ++serial, file: file, key: key, state: "selected", label: labels.ready, percent: null, message: "", meta: {}, attempted: false, duplicate: duplicate, overwriteKey: null, availableOverwriteKey: null};
                entries.push(entry);
                entry.row = ui.createFile(list, {
                    name: file.name, size: file.size, announcement: announcement, labels: labels,
                    detail: options.describe ? options.describe(file) : "",
                    add: function() { add(entry); }, overwrite: function() { overwrite(entry); }, retry: function() { add(entry); }, retryStates: ["failed", "canceled"],
                    remove: function() { remove(entry); }, removalStates: ["selected", "replaceable", "blocked", "failed", "canceled", "checking", "queued"],
                    pause: function() { if (entry.controls) entry.controls.pause(); },
                    resume: function() { if (entry.controls) entry.controls.resume(); },
                    cancel: function() { if (entry.controls) entry.controls.cancel(); }
                });
                var validation = picker.validate([file]);
                if (duplicate || validation) {
                    present(entry, {state: "blocked", label: duplicate ? "Already in this queue" : "Invalid file", message: validation || "This filename is already listed. Remove this extra selection or choose a differently named file."});
                } else if (options.check) {
                    check(entry).then(function(ready) {
                        if (ready && entries.indexOf(entry) !== -1) present(entry, {state: "selected", label: labels.ready});
                    });
                } else present(entry, {});
            });
            picker.input.value = "";
        }
        function add(entry) {
            if (redirected || entries.indexOf(entry) === -1 || ["selected", "failed", "canceled"].indexOf(entry.state) === -1) return;
            present(entry, {state: "queued", label: "Waiting…", message: "", url: "", percent: null});
            pump();
        }
        function overwrite(entry) {
            if (redirected || entries.indexOf(entry) === -1 || entry.state !== "replaceable") return;
            entry.overwriteKey = entry.availableOverwriteKey;
            present(entry, {state: "queued", label: "Waiting to replace…", message: "", url: "", percent: null});
            pump();
        }
        async function pump() {
            if (active || redirected) return;
            var entry = entries.find(function(item) { return item.state === "queued"; });
            if (!entry) { batchActive = false; refresh(); return; }
            active = entry;
            refresh();
            if (await check(entry) && !redirected) {
                try {
                    entry.attempted = true;
                    present(entry, {state: "uploading", label: labels.pending, message: "", percent: null});
                    var result = await options.send(entry, function(value) {
                        if (active === entry && !redirected && ["checking", "uploading", "saving", "paused"].indexOf(entry.state) !== -1) present(entry, value);
                    });
                    present(entry, {state: "completed", label: result.label || "Added", message: result.message || "", percent: 100, url: result.url, linkLabel: result.linkLabel});
                } catch (error) { fail(entry, error); }
            }
            active = null;
            refresh();
            pump();
        }
        function addAll() {
            if (redirected || active) return;
            batchActive = true;
            entries.filter(function(entry) { return entry.state === "selected" || entry.state === "replaceable"; }).forEach(function(entry) {
                entry.overwriteKey = entry.state === "replaceable" ? entry.availableOverwriteKey : null;
                present(entry, {state: "queued", label: entry.overwriteKey !== null ? "Waiting to replace…" : "Waiting…", message: ""});
            });
            pump();
        }
        all.addEventListener("click", addAll);
        refresh();
        return {picker: picker, entries: entries, add: add, overwrite: overwrite, addAll: addAll, remove: remove};
    };
})(window);
