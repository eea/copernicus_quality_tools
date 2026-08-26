/* Server-backed delivery table state, filters, and accessibility. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
    var formatters = window.QcDeliveryFormatters || {};
    var tableSelector = "#tbl-deliveries";
    var allowedStatuses = [
        "all", "not_validated", "running", "passed", "failed", "submitted"
    ];
    var state = {
        deliveryStatus: initialStatus(),
        search: "",
        product: "",
        aoi: ""
    };
    var inputTimers = {};

    function initialStatus() {
        var value;
        try {
            value = new URL(window.location.href).searchParams.get("delivery_status");
        } catch (error) {
            value = null;
        }
        return allowedStatuses.indexOf(value) >= 0 ? value : "all";
    }

    function currentFilter() {
        var filter = {};
        if (state.product) {
            filter.product_description = state.product;
        }
        if (state.aoi) {
            filter.aoi_code = state.aoi;
        }
        return filter;
    }

    function deliveryQueryParams(params) {
        var filter = currentFilter();
        params.delivery_status = state.deliveryStatus;
        params.search = state.search;
        params.filter = Object.keys(filter).length ? JSON.stringify(filter) : "";
        return params;
    }

    function selectedRows() {
        return $(tableSelector).bootstrapTable("getSelections") || [];
    }

    function rows() {
        return $(tableSelector).bootstrapTable("getData") || [];
    }

    function setBusy(isBusy) {
        $(".deliveries-table-region .fixed-table-body").attr(
            "aria-busy",
            isBusy ? "true" : "false"
        );
    }

    function announce(message) {
        $("#deliveries-live-status").text(message);
    }

    function updateStatusControls() {
        $("[data-delivery-status]").each(function () {
            var isActive = $(this).attr("data-delivery-status") === state.deliveryStatus;
            $(this)
                .toggleClass("is-active", isActive)
                .attr("aria-pressed", isActive ? "true" : "false");
        });
    }

    function updateStatusCounts(counts) {
        if (!counts) {
            return;
        }
        Object.keys(counts).forEach(function (status) {
            var numericCount = Number(counts[status]);
            $("[data-delivery-status-count='" + status + "']").text(
                Number.isFinite(numericCount) && numericCount >= 0 ? numericCount : "\u2014"
            );
        });
    }

    function filtersActive() {
        return state.deliveryStatus !== "all" || Boolean(state.search || state.product || state.aoi);
    }

    function updateClearButton() {
        $("#btn-clear-filters").prop("disabled", !filtersActive());
    }

    function updateAddressBar() {
        var url;
        try {
            url = new URL(window.location.href);
            if (state.deliveryStatus === "all") {
                url.searchParams.delete("delivery_status");
            } else {
                url.searchParams.set("delivery_status", state.deliveryStatus);
            }
            window.history.replaceState({}, "", url.pathname + url.search + url.hash);
        } catch (error) {
            return;
        }
    }

    function clearSelection() {
        $(tableSelector).bootstrapTable("uncheckAll");
    }

    function refresh(options) {
        clearSelection();
        setBusy(true);
        $(tableSelector).bootstrapTable(
            "refresh",
            $.extend({silent: true, pageNumber: 1}, options)
        );
    }

    function selectStatus(status) {
        if (allowedStatuses.indexOf(status) < 0 || status === state.deliveryStatus) {
            return;
        }
        state.deliveryStatus = status;
        updateStatusControls();
        updateClearButton();
        updateAddressBar();
        refresh();
    }

    function scheduleInputFilter(name, value) {
        window.clearTimeout(inputTimers[name]);
        inputTimers[name] = window.setTimeout(function () {
            state[name] = value;
            updateClearButton();
            refresh();
        }, 250);
    }

    function resetFilters() {
        state.deliveryStatus = "all";
        state.search = "";
        state.product = "";
        state.aoi = "";
        $("#delivery-filter-search, #delivery-filter-aoi").val("");
        $("#delivery-filter-product").val("");
        updateStatusControls();
        updateClearButton();
        updateAddressBar();
        refresh();
    }

    function bindFilters() {
        $("#delivery-status-filters").on("click", "[data-delivery-status]", function () {
            selectStatus($(this).attr("data-delivery-status"));
        });
        $("#delivery-filter-search").on("input", function () {
            scheduleInputFilter("search", String($(this).val() || "").trim());
        });
        $("#delivery-filter-product").on("change", function () {
            state.product = String($(this).val() || "");
            updateClearButton();
            refresh();
        });
        $("#delivery-filter-aoi").on("input", function () {
            scheduleInputFilter("aoi", String($(this).val() || "").trim());
        });
        $("#btn-clear-filters").on("click", resetFilters);
        $("#btn-refresh-deliveries").on("click", function () {
            refresh({pageNumber: $(tableSelector).bootstrapTable("getOptions").pageNumber});
            announce("Refreshing deliveries.");
        });
    }

    function labelSelectableRows() {
        var tableRows = rows();
        $(tableSelector + " input[name='btSelectAll']").attr(
            "aria-label",
            "Select all eligible deliveries on this page"
        );
        $(tableSelector + " input[name='btSelectItem']").each(function (index) {
            var row = tableRows[index] || {};
            $(this).attr("aria-label", "Select " + String(row.filename || "delivery"));
        });
    }

    function makeSortControlsAccessible() {
        var options = $(tableSelector).bootstrapTable("getOptions") || {};
        $(tableSelector + " thead th").removeAttr("aria-sort");
        $(tableSelector + " thead .th-inner.sortable").each(function () {
            var $control = $(this);
            var $header = $control.closest("th");
            var field = $header.attr("data-field");
            var label = $.trim($control.clone().children().remove().end().text()) || field;
            $control.attr({
                role: "button",
                tabindex: "0",
                "aria-label": "Sort by " + label
            }).off("keydown.qcSort").on("keydown.qcSort", function (event) {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    $(this).trigger("click");
                }
            });
            if (field === options.sortName) {
                $header.attr("aria-sort", options.sortOrder === "asc" ? "ascending" : "descending");
            }
        });
    }

    function updateTableAccessibility() {
        var $scrollRegion = $(".deliveries-table-region .fixed-table-body").first();
        $scrollRegion.attr({
            role: "region",
            "aria-labelledby": "deliveries-table-title",
            tabindex: "0",
            "aria-busy": $scrollRegion.attr("aria-busy") || "false"
        });
        labelSelectableRows();
        makeSortControlsAccessible();
    }

    function noMatchesMessage() {
        if (filtersActive()) {
            return "No deliveries match these filters. Clear filters to see all deliveries.";
        }
        if (config.canUpload) {
            return "No deliveries yet. Upload a delivery ZIP file to get started.";
        }
        return "No deliveries are currently available for your account.";
    }

    function bindTableEvents() {
        $(tableSelector)
            .on("refresh.bs.table", function () {
                setBusy(true);
            })
            .on("load-success.bs.table", function (event, response) {
                var count = rows().length;
                setBusy(false);
                updateStatusCounts(response && response.status_counts);
                updateTableAccessibility();
                announce(
                    "Showing " + count + " " +
                    (count === 1 ? "delivery" : "deliveries") + " on this page."
                );
            })
            .on("post-body.bs.table post-header.bs.table sort.bs.table", updateTableAccessibility)
            .on("page-change.bs.table search.bs.table", clearSelection)
            .on("load-error.bs.table", function () {
                setBusy(false);
                announce("Deliveries could not be loaded. Please try again.");
            });
    }

    function exportQuery() {
        var options = $(tableSelector).bootstrapTable("getOptions") || {};
        return deliveryQueryParams({
            sort: options.sortName || "id",
            order: options.sortOrder || "desc",
            offset: 0,
            limit: 1000
        });
    }

    function init() {
        updateStatusControls();
        updateClearButton();
        bindFilters();
        bindTableEvents();
        $(tableSelector).bootstrapTable({
            cache: false,
            url: config.deliveriesDataUrl,
            pageSize: 20,
            pageList: [20, 50, 100, 500],
            pagination: true,
            sidePagination: "server",
            search: false,
            showColumns: false,
            sortName: "id",
            sortOrder: "desc",
            queryParams: deliveryQueryParams,
            formatNoMatches: noMatchesMessage
        });
        updateTableAccessibility();
    }

    window.deliveryQueryParams = deliveryQueryParams;
    window.QcDeliveryTable = {
        init: init,
        rows: rows,
        selectedRows: selectedRows,
        canRunQc: formatters.canRunQc,
        canDelete: formatters.canDelete,
        canSubmit: formatters.canSubmit,
        refresh: refresh,
        announce: announce,
        exportQuery: exportQuery,
        setBusy: setBusy
    };
}(window, window.jQuery));
