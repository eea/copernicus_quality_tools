/* Native header menus share the workspace appearance without a JS framework. */
(function(document) {
    "use strict";
    function openMenus() { return document.querySelectorAll("details[data-header-menu][open]"); }
    document.addEventListener("click", function(event) {
        openMenus().forEach(function(menu) {
            if (!menu.contains(event.target)) menu.open = false;
        });
    });
    document.addEventListener("keydown", function(event) {
        if (event.key !== "Escape") return;
        openMenus().forEach(function(menu) {
            menu.open = false;
            if (menu.contains(event.target)) {
                menu.querySelector("summary").focus();
                event.preventDefault();
            }
        });
    });
})(document);
