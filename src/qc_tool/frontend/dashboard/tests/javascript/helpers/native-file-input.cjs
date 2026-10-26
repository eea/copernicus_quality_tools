"use strict";

// A live, read-only FileList double. Unlike an array, it empties in place when
// the browser input is reset. Native dialog behavior still needs browser QA.
function nativeFileInput(input) {
    let selected = [];
    let open = false;
    let opens = 0;
    const files = {
        get length() { return selected.length; },
        item(index) { return selected[index] || null; },
        *[Symbol.iterator]() { for (let index = 0; index < selected.length; index++) yield selected[index]; },
        [Symbol.toStringTag]: "FileList",
    };
    function replace(values) {
        for (let index = 0; index < selected.length; index++) delete files[index];
        selected = Array.from(values);
        selected.forEach((_file, index) => Object.defineProperty(files, index, {
            configurable: true, enumerable: true, get: () => selected[index],
        }));
    }
    Object.defineProperty(input, "files", {configurable: true, get: () => files});
    Object.defineProperty(input, "value", {
        configurable: true,
        get: () => selected.length ? "C:\\fakepath\\" + selected[0].name : "",
        set(value) {
            if (value !== "") throw new Error("A file input can only be cleared by script");
            replace([]);
        },
    });
    const click = input.click.bind(input);
    input.click = function() {
        if (input.disabled) return;
        opens++;
        open = true;
        click();
    };
    return {
        files,
        get opens() { return opens; },
        choose(values) {
            if (!open) throw new Error("Open the native chooser first");
            open = false;
            const next = Array.from(values);
            const unchanged = next.length === selected.length && next.every((file, index) => file === selected[index]);
            if (unchanged) {
                input.dispatchEvent({type: "cancel"});
                return;
            }
            replace(next);
            input.dispatchEvent({type: "input"});
            input.dispatchEvent({type: "change"});
        },
        cancel() {
            if (!open) throw new Error("Open the native chooser first");
            open = false;
            input.dispatchEvent({type: "cancel"});
        },
    };
}

module.exports = {nativeFileInput};
