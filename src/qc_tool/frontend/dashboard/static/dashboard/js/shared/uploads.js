/* Shared upload presentation and selection. Adapters own requests and success. */
(function(window, document) {
    "use strict";

    var nextFileId = 0;

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        var units = ["KiB", "MiB", "GiB", "TiB"];
        var value = bytes / 1024;
        var index = 0;
        while (value >= 1024 && index < units.length - 1) {
            value /= 1024;
            index += 1;
        }
        return Number(value.toFixed(1)) + " " + units[index];
    }

    function createPicker(root, options) {
        options = options || {};
        var drop = root.querySelector("[data-upload-picker]");
        var input = drop.querySelector('input[type="file"]');
        var browse = drop.querySelector("[data-upload-browse]");
        var error = root.querySelector("[data-upload-error]");
        var hint = drop.querySelector("[data-upload-hint]");
        var extensions = options.extensions || [];
        var busy = false;
        var dragDepth = 0;

        input.setAttribute("aria-describedby", hint.id + " " + error.id);
        if (error.textContent.trim()) {
            input.setAttribute("aria-invalid", "true");
            browse.setAttribute("aria-invalid", "true");
        }

        function showError(message) {
            error.textContent = message;
            if (message) {
                input.setAttribute("aria-invalid", "true");
                browse.setAttribute("aria-invalid", "true");
            } else {
                input.removeAttribute("aria-invalid");
                browse.removeAttribute("aria-invalid");
            }
        }

        function files() { return Array.from(input.files || []); }

        function validate(selected) {
            selected = selected || files();
            if (!selected.length) return "Choose a file to upload.";
            if (!input.multiple && selected.length !== 1) return "Choose exactly one file at a time.";
            for (var i = 0; i < selected.length; i++) {
                var file = selected[i];
                var dot = file.name.lastIndexOf(".");
                var extension = dot < 0 ? "" : file.name.slice(dot + 1).toLowerCase();
                if (extensions.length && extensions.indexOf(extension) === -1) {
                    return "Choose " + extensions.map(function(value) { return "." + value; }).join(" or ") + " files only.";
                }
                if (!file.size) return file.name + " is empty. Choose a file with content.";
                if (options.maxBytes && file.size > options.maxBytes) {
                    return file.name + " exceeds the " + formatSize(options.maxBytes) + " file size limit.";
                }
            }
            return "";
        }

        function reject(message) {
            input.value = "";
            showError(message);
            if (options.onInvalid) options.onInvalid(message);
        }

        function select(selected) {
            if (busy) return;
            var message = options.deferValidation ? "" : validate(selected);
            if (message) {
                reject(message);
                return;
            }
            showError("");
            if (options.onSelect) options.onSelect(Array.from(selected));
        }

        browse.addEventListener("click", function() {
            if (!busy) input.click();
        });
        input.addEventListener("change", function() { select(files()); });
        // Keep the native input usable when JS is absent. With enhancement the
        // real button provides a consistent keyboard-accessible file chooser.
        if (input.files !== undefined) {
            input.hidden = true;
            browse.hidden = false;
        }
        if (window.DataTransfer && input.files !== undefined) {
            var title = drop.querySelector("[data-upload-picker-title]");
            if (drop.dataset.dropTitle) title.textContent = drop.dataset.dropTitle;
            drop.addEventListener("dragenter", function(event) {
                event.preventDefault();
                if (busy) return;
                dragDepth += 1;
                drop.classList.add("is-dragover");
            });
            drop.addEventListener("dragover", function(event) {
                event.preventDefault();
                if (event.dataTransfer) event.dataTransfer.dropEffect = busy ? "none" : "copy";
            });
            drop.addEventListener("dragleave", function(event) {
                event.preventDefault();
                dragDepth = Math.max(0, dragDepth - 1);
                if (!dragDepth) drop.classList.remove("is-dragover");
            });
            drop.addEventListener("drop", function(event) {
                event.preventDefault();
                dragDepth = 0;
                drop.classList.remove("is-dragover");
                if (busy || !event.dataTransfer) return;
                var selected = event.dataTransfer.files;
                // Text or links dragged within the page are not a replacement
                // file selection. Preserve both the input and its preview.
                if (!selected || !selected.length) return;
                var message = options.deferValidation ? "" : validate(selected);
                if (message) {
                    reject(message);
                    return;
                }
                try {
                    input.files = selected;
                } catch (_error) {
                    reject("Use the file chooser to select your file.");
                    browse.focus();
                    return;
                }
                select(selected);
            });
        }

        return {
            input: input,
            browse: browse,
            files: files,
            validate: validate,
            showError: showError,
            clear: function() { input.value = ""; showError(""); },
            setSelected: function(selected) {
                if (selected) drop.setAttribute("data-has-files", "true");
                else drop.removeAttribute("data-has-files");
            },
            setBusy: function(value) {
                busy = value;
                browse.disabled = value;
                drop.setAttribute("aria-disabled", String(value));
                root.querySelectorAll("[data-upload-idle]").forEach(function(node) { node.hidden = value; });
                root.querySelectorAll("[data-upload-pending]").forEach(function(node) { node.hidden = !value; });
                // Do not disable the file input: native multipart submission
                // omits disabled controls and would silently lose the upload.
            }
        };
    }

    function element(tag, className, parent, text) {
        var node = document.createElement(tag);
        node.className = className;
        if (text !== undefined) node.textContent = text;
        if (parent) parent.appendChild(node);
        return node;
    }

    function createFile(list, options) {
        var labels = options.labels || {};
        var row = element("li", "qc-upload-file", list);
        row.setAttribute("tabindex", "-1");
        var heading = element("div", "qc-upload-file__heading", row);
        var icon = element("span", "qc-upload-file__icon", heading);
        icon.setAttribute("aria-hidden", "true");
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", "ui-icon");
        svg.setAttribute("focusable", "false");
        var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
        var workspace = list.closest("[data-upload-icons]");
        use.setAttribute("href", (workspace ? workspace.dataset.uploadIcons : "") + "#file");
        svg.appendChild(use);
        icon.appendChild(svg);
        var identity = element("div", "qc-upload-file__identity", heading);
        var name = element("span", "qc-upload-file__name", identity, options.name);
        name.id = "qc-upload-file-" + (++nextFileId);
        row.setAttribute("aria-labelledby", name.id);
        element("span", "qc-upload-file__size", heading, formatSize(options.size));
        var detail = element("span", "qc-upload-file__detail", identity, options.detail || "");
        detail.hidden = !options.detail;
        var details = element("div", "qc-upload-file__feedback", row);
        var status = element("span", "qc-upload-file__status", details);
        status.id = name.id + "-status";
        var track = element("div", "qc-upload-file__track", row);
        track.setAttribute("role", "progressbar");
        track.setAttribute("aria-labelledby", name.id);
        track.setAttribute("aria-valuemin", "0");
        track.setAttribute("aria-valuemax", "100");
        var bar = element("div", "qc-upload-file__bar", track);
        bar.setAttribute("aria-hidden", "true");
        var error = element("p", "qc-upload-file__error", details);
        error.id = name.id + "-error";
        row.setAttribute("aria-describedby", status.id + " " + error.id);
        track.setAttribute("aria-describedby", error.id);
        var actions = element("div", "qc-upload-file__actions", heading);
        function action(label, hook, callback) {
            var button = element("button", "btn btn-default btn-qc-secondary", actions, label);
            button.type = "button";
            button.setAttribute(hook, "");
            button.setAttribute("aria-label", label + ": " + options.name);
            button.addEventListener("click", function() {
                var hadFocus = document.activeElement === button;
                if (callback) callback();
                // A retry hides its button immediately. Keep keyboard focus
                // on the file rather than losing it at the top of the page.
                if (hadFocus && button.hidden && document.contains(row) &&
                        (document.activeElement === button || document.activeElement === document.body)) {
                    row.focus();
                }
            });
            button.hidden = true;
            return button;
        }
        var add = action(labels.add || "Add", "data-upload-add", options.add);
        add.className = "btn btn-primary btn-qc-primary";
        var overwrite = action(labels.overwrite || "Overwrite", "data-upload-overwrite", options.overwrite);
        overwrite.className = "btn btn-default btn-qc-secondary qc-upload-file__replace";
        var retry = action("Retry upload", "data-upload-retry", options.retry);
        var pause = action("Pause", "data-upload-pause", options.pause);
        var resume = action("Resume", "data-upload-resume", options.resume);
        var cancel = action("Cancel upload", "data-upload-cancel", options.cancel);
        var remove = action("Remove", "data-upload-remove", options.remove);
        remove.className += " qc-upload-file__remove";
        remove.setAttribute("aria-label", "Remove " + options.name + " from the upload list");
        var link = element("a", "qc-upload-file__link", details);
        link.hidden = true;
        var lastPhase;
        return {
            element: row,
            update: function(value) {
                if (typeof value.detail === "string") {
                    detail.textContent = value.detail;
                    detail.hidden = !value.detail;
                }
                var phase = value.state + ":" + (value.error || "");
                row.setAttribute("data-state", value.state);
                status.textContent = value.label;
                // Ready actions already express the state. Keep the main row
                // compact; processing, warnings and results live below it.
                status.hidden = value.state === "selected";
                track.hidden = ["selected", "replaceable", "blocked", "failed", "checking", "queued", "canceled", "completed"].indexOf(value.state) !== -1;
                track.setAttribute("aria-valuetext", value.label);
                if (typeof value.percent === "number" && Number.isFinite(value.percent)) {
                    var bounded = Math.max(0, Math.min(100, value.percent));
                    track.setAttribute("aria-valuenow", String(bounded));
                    track.removeAttribute("data-indeterminate");
                    bar.style.width = bounded + "%";
                } else {
                    track.removeAttribute("aria-valuenow");
                    track.setAttribute("data-indeterminate", "true");
                    bar.style.width = "";
                }
                error.textContent = value.error || "";
                error.hidden = !value.error;
                retry.hidden = (options.retryStates || ["failed"]).indexOf(value.state) === -1 || !options.retry;
                remove.hidden = (options.removalStates || ["selected"]).indexOf(value.state) === -1 || !options.remove || value.canRemove === false;
                add.hidden = value.state !== "selected" || !options.add;
                overwrite.hidden = value.state !== "replaceable" || !options.overwrite;
                pause.hidden = value.state !== "uploading" || !value.canPause || !options.pause;
                resume.hidden = value.state !== "paused" || !options.resume;
                cancel.hidden = ["uploading", "paused"].indexOf(value.state) === -1 || !value.canCancel || !options.cancel;
                link.hidden = !value.url;
                if (value.url) {
                    link.href = value.url;
                    link.textContent = value.linkLabel || "View file";
                }
                actions.hidden = [retry, remove, add, overwrite, pause, resume, cancel].every(function(node) { return node.hidden; });
                details.hidden = status.hidden && error.hidden && link.hidden;
                if (options.announcement && phase !== lastPhase) {
                    options.announcement.textContent = options.name + ": " + value.label + (value.error ? ". " + value.error : "");
                    lastPhase = phase;
                }
            }
        };
    }

    function feedback(container, options) {
        var notice = element("div", "workspace-notice workspace-notice--" + options.tone);
        notice.setAttribute("role", options.tone === "danger" ? "alert" : "status");
        element("div", "qc-upload-feedback__message", notice, options.message);
        if (options.href) {
            var link = element("a", "btn " + (options.tone === "success" ? "btn-primary btn-qc-primary" : "btn-default btn-qc-secondary"), notice, options.label);
            link.href = options.href;
        }
        container.replaceChildren(notice);
    }

    window.qcUpload = {createPicker: createPicker, createFile: createFile, feedback: feedback, formatSize: formatSize};
})(window, document);
