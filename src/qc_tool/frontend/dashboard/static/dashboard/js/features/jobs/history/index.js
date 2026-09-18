/* Initialize the read-only QC job history and its shared table controls. */
(function (window, $) {
    "use strict";

    var history = window.QcJobHistory = window.QcJobHistory || {};

    $(function () {
        history.createTable();
    });
}(window, window.jQuery));
