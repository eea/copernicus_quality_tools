/* Progressive enhancement for the shared header; native Profile stays usable without JS. */
(function(document) {
    "use strict";
    const headers = [];
    document.querySelectorAll(".site-header").forEach(function(header) {
        const toggle = header.querySelector("[data-header-toggle]");
        if (!toggle) return;
        header.setAttribute("data-navigation-ready", "");
        headers.push({header, toggle});
        toggle.addEventListener("click", function() {
            toggle.setAttribute("aria-expanded", toggle.getAttribute("aria-expanded") === "true" ? "false" : "true");
        });
    });

    function openMenus() { return document.querySelectorAll("details[data-header-menu][open]"); }
    document.addEventListener("click", function(event) {
        openMenus().forEach(function(menu) {
            if (!menu.contains(event.target)) menu.open = false;
        });
        headers.forEach(function({header, toggle}) {
            if (!header.contains(event.target)) toggle.setAttribute("aria-expanded", "false");
        });
    });
    document.addEventListener("keydown", function(event) {
        if (event.key !== "Escape") return;
        let closedProfile = false;
        openMenus().forEach(function(menu) {
            menu.open = false;
            if (menu.contains(event.target)) {
                menu.querySelector("summary").focus();
                event.preventDefault();
                closedProfile = true;
            }
        });
        if (closedProfile) return;
        headers.forEach(function({header, toggle}) {
            if (toggle.getAttribute("aria-expanded") !== "true") return;
            toggle.setAttribute("aria-expanded", "false");
            if (header.contains(event.target) && toggle.getClientRects().length) {
                toggle.focus();
                event.preventDefault();
            }
        });
    });
})(document);
