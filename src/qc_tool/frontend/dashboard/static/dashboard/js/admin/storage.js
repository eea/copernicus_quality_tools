/* Local storage-browser controls. Downloads stay native; the server owns files. */
(function (window, document) {
    "use strict";
    var selectionForms = Array.prototype.slice.call(document.querySelectorAll("[data-storage-selection-form]"));
    var explorers = Array.prototype.slice.call(document.querySelectorAll("[data-storage-explorer]"));
    var downloadStatus = document.querySelector("[data-storage-download-status]");
    var copyStatus = document.querySelector("[data-storage-copy-status]");
    var copySequence = 0;

    function clearDownloadStatus() {
        if (!downloadStatus) return;
        downloadStatus.hidden = true;
        downloadStatus.textContent = "";
    }
    function announceDownload() {
        if (!downloadStatus) return;
        // A streamed attachment leaves this page open. It has no reliable
        // client-side completion event and must never leave a permanent spinner.
        downloadStatus.textContent = "Your browser will start the ZIP after checking the files. Keep the download connection open until your browser finishes.";
        downloadStatus.hidden = false;
    }
    function items(form) {
        return Array.prototype.slice.call(form.querySelectorAll("[data-storage-item]")).filter(function (item) {
            return item.getAttribute("name") === "paths" && item.getAttribute("type") === "checkbox" && !item.disabled;
        });
    }
    function updateSelection(form) {
        var available = items(form);
        var count = available.filter(function (item) { return item.checked; }).length;
        available.forEach(function (item) {
            var row = item.closest("[data-storage-row]");
            if (row) row.classList.toggle("storage-row--selected", item.checked);
        });
        var all = form.querySelector("[data-storage-select-all]");
        var status = form.querySelector("[data-storage-selection-status]");
        var download = form.querySelector("[data-storage-selected-download]");
        var clear = form.querySelector("[data-storage-clear]");
        if (all) {
            all.checked = available.length > 0 && count === available.length;
            all.indeterminate = count > 0 && count < available.length;
            all.disabled = available.length === 0;
        }
        if (status) status.textContent = count
            ? count + " item" + (count === 1 ? "" : "s") + " selected on this page."
            : "Select files or folders to download together.";
        if (download) download.disabled = count === 0;
        if (clear) clear.hidden = count === 0;
        return count;
    }
    function clearSelection(form) {
        items(form).forEach(function (item) { item.checked = false; });
        clearDownloadStatus();
        updateSelection(form);
    }
    selectionForms.forEach(function (form) {
        var all = form.querySelector("[data-storage-select-all]");
        var clear = form.querySelector("[data-storage-clear]");
        if (all) all.hidden = false;
        form.addEventListener("change", function (event) {
            if (event.target === all) {
                items(form).forEach(function (item) { item.checked = all.checked; });
            }
            clearDownloadStatus();
            updateSelection(form);
        });
        if (clear) clear.addEventListener("click", function () {
            clearSelection(form);
        });
        form.addEventListener("submit", function (event) {
            if (event.defaultPrevented) return;
            if (!updateSelection(form)) {
                event.preventDefault();
                var status = form.querySelector("[data-storage-selection-status]");
                if (status) status.textContent = "Select at least one file or folder to download.";
                clearDownloadStatus();
                return;
            }
            // Preserve the GET and every selected paths value. No fetch, POST,
            // automatic retries, or permanent pending state belongs here.
            announceDownload();
        });
        updateSelection(form);
    });
    document.querySelectorAll("[data-storage-download]").forEach(function (link) {
        link.addEventListener("click", function (event) {
            if (!event.defaultPrevented) announceDownload();
        });
    });

    function preferredView() {
        try {
            var stored = window.localStorage.getItem("qc-storage-view");
            if (stored === "list" || stored === "grid") return stored;
        } catch (_unavailableStorage) { /* View controls also work without storage. */ }
        return "list";
    }
    function setView(explorer, view) {
        explorer.setAttribute("data-storage-view", view);
        explorer.querySelectorAll("[data-storage-view-choice]").forEach(function (button) {
            button.setAttribute("aria-pressed", button.getAttribute("data-storage-view-choice") === view ? "true" : "false");
        });
    }
    explorers.forEach(function (explorer) {
        explorer.addEventListener("keydown", function (event) {
            // Keep text editing, native links and browser shortcuts untouched
            // outside the folder view. Selection never carries to another page.
            var target = event.target;
            if (event.defaultPrevented || !target || !explorer.contains(target) ||
                target.closest("textarea, select, [contenteditable]")) return;
            var input = target.closest("input");
            if (input && input.getAttribute("type") !== "checkbox" && input.getAttribute("type") !== "radio") return;
            var form = explorer.querySelector("[data-storage-selection-form]");
            if (!form) return;
            if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey &&
                (event.key === "a" || event.key === "A") && items(form).length) {
                event.preventDefault();
                items(form).forEach(function (item) { item.checked = true; });
                clearDownloadStatus();
                updateSelection(form);
            } else if (event.key === "Escape" && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey &&
                items(form).some(function (item) { return item.checked; })) {
                event.preventDefault();
                clearSelection(form);
            }
        });
        explorer.querySelectorAll("[data-storage-keyboard-hint]").forEach(function (hint) { hint.hidden = false; });
        explorer.querySelectorAll("[data-storage-view-choice]").forEach(function (button) {
            button.addEventListener("click", function () {
                var view = button.getAttribute("data-storage-view-choice");
                if (view !== "list" && view !== "grid") return;
                explorers.forEach(function (current) { setView(current, view); });
                try { window.localStorage.setItem("qc-storage-view", view); }
                catch (_unavailableStorage) { /* Keep the user's current view. */ }
            });
        });
        setView(explorer, preferredView());
        explorer.querySelectorAll("[data-storage-view-controls]").forEach(function (controls) { controls.hidden = false; });
    });

    function showCopyStatus(text) {
        if (!copyStatus) return;
        copyStatus.setAttribute("role", "status");
        copyStatus.setAttribute("aria-live", "polite");
        copyStatus.textContent = text;
        copyStatus.hidden = false;
    }
    function manualCopy() {
        showCopyStatus("Could not copy automatically. Select the text above and copy it manually.");
    }
    document.querySelectorAll("[data-storage-copy]").forEach(function (button) {
        button.addEventListener("click", function (event) {
            if (event.defaultPrevented) return;
            var current = ++copySequence;
            var target = document.getElementById(button.getAttribute("data-storage-copy-target"));
            if (!target || target.tagName !== "CODE" || !target.textContent) {
                manualCopy();
                return;
            }
            try {
                var clipboard = window.navigator && window.navigator.clipboard;
                if (!clipboard || typeof clipboard.writeText !== "function") { manualCopy(); return; }
                // Call directly in this user gesture, without requesting access
                // or reading the clipboard when the page is opened.
                var result = clipboard.writeText(target.textContent);
                showCopyStatus("Copying…");
                Promise.resolve(result).then(function () {
                    if (current === copySequence) showCopyStatus("Copied to clipboard.");
                }).catch(function () {
                    if (current === copySequence) manualCopy();
                });
            } catch (_copyUnavailable) { manualCopy(); }
        });
    });

    window.addEventListener("pageshow", function () {
        clearDownloadStatus();
        selectionForms.forEach(updateSelection);
        explorers.forEach(function (explorer) { setView(explorer, preferredView()); });
        copySequence += 1;
        if (copyStatus) { copyStatus.hidden = true; copyStatus.textContent = ""; }
    });
}(window, document));
