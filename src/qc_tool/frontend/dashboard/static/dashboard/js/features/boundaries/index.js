/* Each boundary family owns its data; controls share the table lifecycle. */
(function (window, $) {
    "use strict";

    window.fileSizeFormatter = function (value) {
        if (value === null || value === undefined) return "—";
        var bytes = Number(value);
        if (!Number.isFinite(bytes) || bytes < 0) return "—";
        if (!bytes) return "0 Bytes";
        var units = ["Bytes", "KB", "MB", "GB", "TB", "PB"];
        var unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        return Number((bytes / Math.pow(1024, unit)).toFixed(2)) + " " + units[unit];
    };

    $(function () {
        ["raster", "vector"].forEach(function (family) {
            var $table = $("#tbl-boundaries-" + family);
            if (!$table.length) return;
            window.QcDataTableUi.create($table, {
                labels: {subject: family + " boundaries", regionLabelledBy: family + "-boundaries-title"},
                exports: {filename: family + "-boundaries"},
                options: {
                    cache: false,
                    search: true,
                    pagination: true,
                    sortName: "filename",
                    sortOrder: "asc",
                    url: $table.data("url"),
                    escape: true,
                    pageSize: 20,
                    pageList: [20, 50, 100, 500],
                    formatNoMatches: function () {
                        var options = $table.bootstrapTable("getOptions") || {};
                        return options.searchText ? "No boundaries match this search." : $table.data("empty-message");
                    }
                }
            });
        });
    });
}(window, window.jQuery));
