/* Server-backed delivery table state, filters, and accessibility. */
(function (window, $) {
    "use strict";

    var config = window.QC_DELIVERIES_CONFIG || {};
    var formatters = window.QcDeliveryFormatters || {};
    var dataTableUi = window.QcDataTableUi;
    var tableSelector = "#tbl-deliveries";
    function readConfig(id, fallback) {
        var element = document.getElementById(id);
        return element ? JSON.parse(element.textContent) : fallback;
    }

    var workflows = readConfig("delivery-workflow-config", {});
    var actionGroups = readConfig("delivery-action-groups", []);
    var allowedStatuses = ["all", "not_validated", "running", "passed", "failed", "submitted", "needs_correction", "accepted"];
    var latestCounts = null;
    var state = initialState();
    var inputTimers = {};
    var filters;
    var lastAnnouncement = "";
    var recoveringEmptyPage = false;

    function initialState() {
        var params;
        try { params = new URL(window.location.href).searchParams; }
        catch (_error) { params = new URLSearchParams(); }
        var status = params.get("delivery_status") || "all";
        var view = params.get("delivery_view");
        if (!Object.prototype.hasOwnProperty.call(workflows, view)) {
            view = status === "all" && params.has("delivery_status") ? "all" : "action_required";
            if (["running", "submitted", "accepted"].indexOf(status) >= 0) {
                view = {running: "running", submitted: "in_review", accepted: "completed"}[status];
            }
        }
        if (allowedStatuses.indexOf(status) < 0 ||
            (status !== "all" && workflows[view].statuses.indexOf(status) < 0)) status = "all";
        return {view: view, deliveryStatus: status, search: "", product: "", aoi: ""};
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
        params.delivery_view = state.view;
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
        if (message !== lastAnnouncement) {
            $("#deliveries-live-status").text(message);
            lastAnnouncement = message;
        }
    }

    function updateStatusControls() {
        $("[data-delivery-view]").each(function () {
            var isActive = $(this).attr("data-delivery-view") === state.view;
            $(this).toggleClass("is-active", isActive).attr("aria-pressed", isActive ? "true" : "false");
        });
    }

    function updateStatusOptions() {
        var select = document.getElementById("delivery-status-select");
        if (!select) return;
        var workflow = workflows[state.view];
        Array.from(select.options).forEach(function (option) {
            if (!option.value) return;
            var available = workflow.statuses.indexOf(option.value) >= 0;
            var selected = state.deliveryStatus === option.value;
            var count = latestCounts && Number(latestCounts[option.value]);
            option.hidden = !selected && (!available || (latestCounts && !count));
            option.disabled = option.hidden;
            if (latestCounts) option.textContent = option.dataset.statusLabel + " (" + (count || 0) + ")";
        });
        select.value = state.deliveryStatus === "all" ? "" : state.deliveryStatus;
        document.getElementById("delivery-status-field").hidden = workflow.statuses.length <= 1;
    }

    function updateViewPresentation() {
        $("#deliveries-table-title").text(workflows[state.view].label);
        updateStatusOptions();
    }

    function updateStatusCounts(counts, workflowCounts) {
        latestCounts = counts || latestCounts;
        Object.keys(workflowCounts || {}).forEach(function (view) {
            var count = Number(workflowCounts[view]);
            $("[data-delivery-view-count='" + view + "']").text(Number.isFinite(count) && count >= 0 ? count : "—");
            $("[data-delivery-view='" + view + "'] .qc-section-tabs__indicator").toggleClass("is-active", count > 0);
        });
        updateStatusOptions();
    }

    function renderActionGroups() {
        var table = document.querySelector(tableSelector);
        if (!table || !table.tBodies.length) return;
        var body = table.tBodies[0];
        body.querySelectorAll(".delivery-action-group").forEach(function (row) { row.remove(); });
        if (state.view !== "action_required") return;
        var data = rows(), previous = null;
        body.querySelectorAll("tr[data-index]").forEach(function (row) {
            var item = data[Number(row.getAttribute("data-index"))];
            if (!item || item.delivery_status === previous) return;
            previous = item.delivery_status;
            var group = actionGroups.find(function (entry) { return entry.value === previous; });
            if (!group) return;
            var heading = document.createElement("tr"), cell = document.createElement("th");
            heading.className = "delivery-action-group";
            cell.colSpan = row.cells.length;
            cell.setAttribute("scope", "rowgroup");
            var label = document.createElement("span");
            label.textContent = group.label;
            cell.appendChild(label);
            if (latestCounts) {
                var count = document.createElement("span");
                count.className = "delivery-action-group__count";
                count.textContent = String(latestCounts[group.value] || 0);
                count.setAttribute("aria-label", (latestCounts[group.value] || 0) + " deliveries in this group");
                cell.appendChild(count);
            }
            heading.appendChild(cell);
            body.insertBefore(heading, row);
        });
    }

    function resultTotal(response) {
        var pageCount = rows().length;
        var total = Number(response && response.total);

        if (!Number.isFinite(total) || total < 0) {
            total = pageCount;
        }
        return total;
    }

    function filtersActive() {
        return state.deliveryStatus !== "all" || Boolean(state.search || state.product || state.aoi);
    }

    function updateClearButton() {
        var extra = Number(Boolean(state.product)) + Number(Boolean(state.aoi)) + Number(state.deliveryStatus !== "all");
        filters.update({active: filtersActive(), count: extra});
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
            if (state.view !== "action_required") url.searchParams.set("delivery_view", state.view);
            else url.searchParams.delete("delivery_view");
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
        if (allowedStatuses.indexOf(status) < 0 ||
            (status !== "all" && workflows[state.view].statuses.indexOf(status) < 0)) {
            return;
        }
        state.deliveryStatus = status;
        updateStatusControls();
        updateViewPresentation();
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
        Object.keys(inputTimers).forEach(function (key) { window.clearTimeout(inputTimers[key]); });
        state.deliveryStatus = "all";
        state.search = "";
        state.product = "";
        state.aoi = "";
        $("#delivery-filter-search, #delivery-filter-aoi").val("");
        $("#delivery-filter-product").val("");
        updateStatusControls();
        updateViewPresentation();
        updateClearButton();
        updateAddressBar();
        refresh();
    }

    function bindFilters() {
        $("[data-delivery-view]").on("click", function () {
            var view = $(this).attr("data-delivery-view");
            if (!Object.prototype.hasOwnProperty.call(workflows, view)) return;
            state.view = view;
            selectStatus("all");
        });
        $("#delivery-status-select").on("change", function () {
            selectStatus(String($(this).val() || "all"));
        });
        $("#delivery-sort").on("change", function () {
            var order = String($(this).val());
            if (["priority", "newest", "oldest"].indexOf(order) < 0) return;
            clearSelection();
            $(tableSelector).bootstrapTable("refreshOptions", {
                pageNumber: 1, sortName: order === "priority" ? "priority" : "id",
                sortOrder: order === "newest" ? "desc" : "asc"
            });
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

    function updateTableAccessibility() {
        var $scrollRegion = $(".deliveries-table-region .fixed-table-body").first();
        $scrollRegion.attr(
            "aria-busy",
            $scrollRegion.attr("aria-busy") || "false"
        );
        labelSelectableRows();
        if (dataTableUi) {
            dataTableUi.enhance($(tableSelector), {
                subject: "deliveries",
                regionLabelledBy: "deliveries-table-title",
                controls: "Delivery display and export controls",
                columns: "Choose visible delivery columns",
                export: "Export filtered deliveries",
                toggleAll: "Show or hide all optional delivery columns"
            });
        }
    }

    function noMatchesMessage() {
        if (filtersActive()) {
            return "No deliveries match these filters. Clear filters to see this view again.";
        }
        if (state.view !== "all") return workflows[state.view].empty_message;
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
                var total = resultTotal(response);
                setBusy(false);
                updateStatusCounts(response && response.status_counts, response && response.workflow_counts);
                // A transition can remove the last row on a later page. The
                // table library clamps pagination without fetching that page.
                if (!count && total > 0 && !recoveringEmptyPage) {
                    recoveringEmptyPage = true;
                    refresh({pageNumber: 1});
                    return;
                }
                if (count || !total) recoveringEmptyPage = false;
                renderActionGroups();
                updateTableAccessibility();
                var resultMessage = "Showing " + count + " of " + total + " " + (total === 1 ? "delivery" : "deliveries") + ".";
                announce(resultMessage);
            })
            .on(
                "post-body.bs.table post-header.bs.table sort.bs.table " +
                "column-switch.bs.table column-switch-all.bs.table",
                function () { renderActionGroups(); updateTableAccessibility(); }
            )
            .on("sort.bs.table", function (_event, name, order) {
                $("#delivery-sort").val(name === "priority" ? "priority" : name === "id" ? (order === "desc" ? "newest" : "oldest") : "custom");
            })
            .on("page-change.bs.table search.bs.table", clearSelection)
            .on("load-error.bs.table", function () {
                setBusy(false);
                announce("Deliveries could not be loaded. Please try again.");
            });
    }

    function exportQuery() {
        var options = $(tableSelector).bootstrapTable("getOptions") || {};
        return deliveryQueryParams({
            sort: options.sortName || "priority",
            order: options.sortOrder || "asc"
        });
    }

    function deliveryRowStyle(row) {
        return {
            classes: row && ["running", "submitted", "accepted"].indexOf(row.delivery_status) >= 0
                ? "delivery-row--calm" : ""
        };
    }

    function tableOptions() {
        var options = {
            cache: false,
            url: config.deliveriesDataUrl,
            pageSize: 20,
            pageList: [20, 50, 100, 500],
            pagination: true,
            sidePagination: "server",
            search: false,
            showRefresh: true,
            toolbar: "#delivery-table-toolbar",
            sortName: "priority",
            sortOrder: "asc",
            queryParams: deliveryQueryParams,
            rowStyle: deliveryRowStyle,
            formatNoMatches: noMatchesMessage
        };

        return options;
    }

    function init() {
        filters = window.QcTableFilters.create(document.getElementById("delivery-table-toolbar"), {onClear: resetFilters});
        updateStatusControls();
        updateViewPresentation();
        filters.setExpanded(state.deliveryStatus !== "all");
        updateClearButton();
        bindFilters();
        bindTableEvents();
        dataTableUi.create($(tableSelector), {
            options: tableOptions(),
            labels: {subject: "deliveries", regionLabelledBy: "deliveries-table-title"},
            exports: {
                filename: "deliveries",
                server: {url: config.exportUrl, getQuery: exportQuery}
            }
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
