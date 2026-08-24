(function () {
    "use strict";

    var backLink = document.querySelector("[data-error-back]");
    if (!backLink || !document.referrer) {
        return;
    }

    try {
        var referrer = new URL(document.referrer, window.location.href);
        if (
            referrer.origin !== window.location.origin ||
            referrer.href === window.location.href
        ) {
            return;
        }

        backLink.addEventListener("click", function (event) {
            event.preventDefault();
            window.history.back();
        });
    } catch (_error) {
        // Keep the link's homepage fallback when the referrer cannot be parsed.
    }
}());
