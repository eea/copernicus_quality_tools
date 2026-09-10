/* Client-side product catalog table with shared controls and accessibility. */
(function (window, $) {
    "use strict";

    var dataTableUi = window.QcDataTableUi;
    var tableSelector = "#tbl-products";
    var announcementTimer;

    function cellText(value) {
        return $.trim(
            $("<div>").html(
                String(value === undefined || value === null ? "" : value)
            ).text()
        );
    }

    function metricNumber(value) {
        var source = String(value === undefined || value === null ? "" : value);
        var progressValue = source.match(
            /<progress\b[^>]*\bvalue=["']?([0-9]+(?:\.[0-9]+)?)/i
        );
        var textValue;

        if (progressValue) {
            return Number(progressValue[1]);
        }
        textValue = source.replace(/<[^>]+>/g, " ").match(
            /-?[0-9]+(?:[.,][0-9]+)?/
        );
        return textValue ? Number(textValue[0].replace(",", ".")) : -1;
    }

    function productMetricSorter(left, right) {
        return metricNumber(left) - metricNumber(right);
    }

    function productTextSorter(left, right) {
        return cellText(left).localeCompare(cellText(right), undefined, {
            sensitivity: "base"
        });
    }

    function productSearch(data, text, filters) {
        var query = String(text || "").trim().toLocaleLowerCase();
        var plan = filters && filters.plan;
        return data.filter(function (row) {
            var identity = $("<div>").html(row.description)
                .find(".product-table__title, .product-table__ident")
                .map(function () { return $(this).text(); }).get().join(" ");
            return (!plan || cellText(row.plan_status) === plan) &&
                identity.toLocaleLowerCase().indexOf(query) >= 0;
        });
    }

    function announceRows($table) {
        var allRows = $table.bootstrapTable("getData") || [];
        var pageRows = $table.bootstrapTable("getData", {
            useCurrentPage: true
        }) || [];
        var options = $table.bootstrapTable("getOptions") || {};
        var first;
        var last;
        var message;

        if (!allRows.length) {
            message = "No products match these filters. Clear filters to see all products.";
        } else if (pageRows.length === allRows.length) {
            message = allRows.length === 1
                ? "One product shown."
                : allRows.length + " products shown.";
        } else {
            first = ((Number(options.pageNumber) || 1) - 1) *
                (Number(options.pageSize) || pageRows.length) + 1;
            last = first + pageRows.length - 1;
            message = "Showing products " + first + " through " + last +
                " of " + allRows.length + " matching products.";
        }
        $("#products-live-status").text(message);
        $("#products-clear-filters").prop("hidden", !(
            $("#products-search").val() || $("#products-plan-filter").val()
        ));
    }

    function scheduleAnnouncement($table) {
        window.clearTimeout(announcementTimer);
        announcementTimer = window.setTimeout(function () {
            announceRows($table);
        }, 0);
    }

    function enhance($table) {
        dataTableUi.enhance($table, {
            subject: "products",
            region: "Product catalog table",
            controls: "Product export",
            export: "Export filtered products as CSV",
            search: "Search products by name or identifier"
        });
    }

    function exportButton($table) {
        return dataTableUi.csvExportButton($table, {
            filename: "products.csv",
            text: "Export CSV",
            label: "Export filtered products as CSV"
        });
    }

    function init() {
        var $table = $(tableSelector);

        if (!$table.length || !dataTableUi || !$.fn.bootstrapTable) {
            return;
        }
        $table.on(
            "post-body.bs.table column-switch.bs.table " +
            "column-switch-all.bs.table",
            function () {
                enhance($table);
            }
        );
        $table.on(
            "post-body.bs.table search.bs.table page-change.bs.table",
            function () {
                scheduleAnnouncement($table);
            }
        );
        $table.bootstrapTable(dataTableUi.options({
            search: true,
            searchSelector: "#products-search",
            searchTimeOut: 150,
            toolbar: "#products-toolbar",
            customSearch: productSearch,
            pagination: true,
            showColumns: false,
            buttons: function () {
                return {exportView: exportButton($table)};
            },
            buttonsOrder: ["exportView"],
            sortName: "description",
            sortOrder: "asc",
            pageSize: 20,
            pageList: [20, 50, 100, 500],
            formatNoMatches: function () {
                return "No products match these filters. Try another name or delivery plan.";
            }
        }));
        $("#products-toolbar").prop("hidden", false);
        $("#products-plan-filter").on("change", function () {
            var plan = this.options[this.selectedIndex].getAttribute("data-plan-label");
            $table.bootstrapTable("filterBy", plan ? {plan: plan} : {});
        });
        $("#products-clear-filters").on("click", function () {
            $("#products-plan-filter").val("");
            $table.bootstrapTable("filterBy", {});
            $table.bootstrapTable("resetSearch", "");
            $("#products-search").trigger("focus");
        });
        enhance($table);
        scheduleAnnouncement($table);
    }

    window.productMetricSorter = productMetricSorter;
    window.productTextSorter = productTextSorter;
    $(init);
}(window, window.jQuery));
