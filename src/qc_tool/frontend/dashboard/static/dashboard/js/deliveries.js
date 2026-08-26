/* Deliveries workspace bootstrap.
 *
 * Page behavior is intentionally split into table, actions, and polling
 * modules. Keeping this file declarative prevents one workflow from growing
 * into another monolithic dashboard script.
 */
(function (window, $) {
    "use strict";

    $(function () {
        if (!window.QcDeliveryTable) {
            return;
        }
        window.QcDeliveryTable.init();
        if (window.QcDeliveryActions) {
            window.QcDeliveryActions.init();
        }
        if (window.QcDeliveryPolling) {
            window.QcDeliveryPolling.init();
        }
    });
}(window, window.jQuery));
