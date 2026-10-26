/* Clipboard mechanics only; each page owns its feedback and fallback policy. */
(function(window, document) {
    "use strict";

    function legacyCopy(text, input) {
        var temporary = !input;
        var previousFocus = document.activeElement;
        if (temporary) {
            input = document.createElement("textarea");
            input.value = text;
            input.setAttribute("readonly", "");
            input.style.position = "fixed";
            input.style.opacity = "0";
            document.body.appendChild(input);
        }
        try {
            input.focus();
            input.select();
            if (input.setSelectionRange) input.setSelectionRange(0, input.value.length);
            if (!document.execCommand || !document.execCommand("copy")) throw new Error("Copy command was rejected.");
        } finally {
            if (temporary) {
                input.remove();
                if (previousFocus && previousFocus.focus) previousFocus.focus();
            }
        }
    }

    function copy(text, options) {
        options = options || {};
        function fallback(error) {
            if (options.legacyFallback === false) return Promise.reject(error || new Error("Clipboard is unavailable."));
            try {
                legacyCopy(text, options.fallbackInput);
                return Promise.resolve();
            } catch (copyError) { return Promise.reject(copyError); }
        }
        // Keep the browser write inside the original user gesture.
        try {
            var clipboard = window.navigator && window.navigator.clipboard;
            if (!clipboard || typeof clipboard.writeText !== "function" || (options.secureOnly && !window.isSecureContext)) return fallback();
            return Promise.resolve(clipboard.writeText(text)).catch(function(error) {
                return options.fallbackOnError === false ? Promise.reject(error) : fallback(error);
            });
        } catch (error) {
            return options.fallbackOnError === false ? Promise.reject(error) : fallback(error);
        }
    }

    window.QcClipboard = {copy: copy};
})(window, document);
