// Populate content of deliveries table from /data/delivery/list/ URL.
global_query_params = {};

function customSearchFunction(text, value, field, data) {
    console.log("customSearchFunction!")
 }

 function queryParams(params) {
    console.log(params);
    if (params.filter) {
        //delete params.filter;
        if (global_query_params.offset != params.offset) {
            global_query_params = params;
            return params;
        } else if (global_query_params.sort != params.sort) {
            global_query_params = params;
            return params;
        } else if (global_query_params.order != params.order) {
            global_query_params = params;
            return params;
        } else if (global_query_params.limit != params.limit) {
            global_query_params = params;
            return params;
        } else {
            if (JSON.stringify(params.filter) === JSON.stringify(global_query_params.filter)) {
                global_query_params = params;
                console.log("No change of filter params!");
                return false;
            }
        }
    }
    global_query_params = params;
    return params;
}

function fileSizeFormatter(value, row) {

    function formatBytes(bytes,decimals) {
       if(bytes == null) return null;
       if(bytes == 0) return '0 Bytes';
       var k = 1024,
           dm = decimals || 2,
           sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'],
           i = Math.floor(Math.log(bytes) / Math.log(k));
       return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }
    return formatBytes(value, 2)
}

function dateFormatter(value, row) {
   if (value) {
        return moment.utc(value).local().format('YYYY-MM-DD HH:mm:ss');
   } else {
        return null;
   }
}

function typeFormatter(value) {
    var label = value === 's3' ? 'S3' : 'Local';
    return $('<span>', {
        'class': 'delivery-type delivery-type--' + (value === 's3' ? 's3' : 'local'),
        'text': label
    }).prop('outerHTML');
}

function checkboxFormatter(value, row) {
    return {
        disabled: !canRunQc(row) && !canDelete(row) && !canSubmit(row),
        checked: false
    };
}


function isDeliveryBusy(row) {
    return row.last_job_status === "waiting" || row.last_job_status === "running";
}

function canRunQc(row) {
    return CAN_RUN_QC && row.can_run_qc && !isDeliveryBusy(row) && !row.date_submitted;
}

function canDelete(row) {
    return CAN_DELETE && row.can_delete && !isDeliveryBusy(row) && !row.date_submitted;
}

function canSubmit(row) {
    return SUBMISSION_ENABLED && CAN_SUBMIT && row.can_submit &&
        row.last_job_status === "ok" && !row.date_submitted;
}

function actionIcon(symbol) {
    var namespace = 'http://www.w3.org/2000/svg';
    var icon = document.createElementNS(namespace, 'svg');
    var use = document.createElementNS(namespace, 'use');
    icon.setAttribute('class', 'ui-icon');
    icon.setAttribute('aria-hidden', 'true');
    icon.setAttribute('focusable', 'false');
    use.setAttribute('href', UI_ICON_SPRITE + '#' + symbol);
    icon.appendChild(use);
    return icon;
}

function appendActionContent($action, icon, label, visuallyHidden) {
    $action.append(actionIcon(icon));
    $action.append($('<span>', {
        'class': visuallyHidden ? 'sr-only' : 'delivery-row-action-label',
        'text': label
    }));
    return $action;
}

function actionsFormatter(value, row) {
    var filename = String(row.filename || 'delivery');
    var $buttons = $('<div>', {
        'class': 'delivery-row-actions',
        'role': 'group',
        'aria-label': 'Actions for ' + filename
    });
    var actionCount = 0;

    if (canRunQc(row)) {
        appendActionContent($('<a>', {
            'class': 'btn btn-sm btn-qc delivery-row-qc',
            'role': 'button',
            'aria-label': 'Run quality controls for ' + filename,
            'href': SETUP_JOB_URL + '?' + $.param({deliveries: row.id})
        }), 'play', 'Run QC', false).appendTo($buttons);
        actionCount += 1;
    }

    if (canSubmit(row)) {
        appendActionContent($('<button>', {
            'class': 'btn btn-sm btn-submit submit-delivery-button',
            'type': 'button',
            'aria-label': 'Submit ' + filename + ' to EEA'
        }), 'send', 'Submit', false)
            .attr('data-delivery-id', String(row.id))
            .attr('data-delivery-filename', String(row.filename || ''))
            .appendTo($buttons);
        actionCount += 1;
    }

    if (canDelete(row)) {
        appendActionContent($('<button>', {
            'class': 'btn btn-sm btn-delete-outline delivery-row-delete delete-button',
            'type': 'button',
            'data-toggle': 'tooltip',
            'title': 'Delete delivery',
            'aria-label': 'Delete ' + filename
        }), 'trash', 'Delete', true)
            .attr('data-delivery-id', String(row.id))
            .attr('data-delivery-filename', String(row.filename || ''))
            .appendTo($buttons);
        actionCount += 1;
    }

    if (actionCount === 0) {
        return $('<span>', {
            'class': 'delivery-row-actions-empty',
            'aria-label': 'No actions available for ' + filename,
            'text': '\u2014'
        }).prop('outerHTML');
    }

    return $buttons.prop('outerHTML');
}

function statusFormatter(value, row, index) {
    var label;
    var modifier = 'neutral';

    if (value == "file_not_found") {
        label = 'File not found';
        modifier = 'failed';
    } else if (!row.last_job_status) {
        label = 'Not checked';
    } else if (value == "ok") {
        label = row.date_submitted !== null ? 'Submitted' : 'Passed';
        modifier = 'passed';
    } else {
        var statusLabels = {
            'waiting': 'Waiting',
            'running': 'Running',
            'partial': 'Partial',
            'failed': 'Failed',
            'error': 'Error',
            'worker timeout': 'Worker timeout',
            'worker lost': 'Worker unavailable'
        };
        label = statusLabels[value] || String(value);
        if (value === 'waiting' || value === 'running') {
            modifier = 'progress';
        } else if (
            value === 'failed' || value === 'error' || value === 'partial' ||
            value === 'worker timeout' || value === 'worker lost'
        ) {
            modifier = 'failed';
        }
    }

    var $status = $('<span>', {
        'class': 'delivery-status delivery-status--' + modifier,
        'text': label
    });
    if (!row.last_job_uuid) {
        return $status.prop('outerHTML');
    }

    return $('<a>', {
        'class': 'delivery-status-link',
        'href': '/result/' + encodeURIComponent(String(row.last_job_uuid)),
        'aria-label': 'View QC result for ' + String(row.filename || 'delivery') + ': ' + label
    }).append($status).prop('outerHTML');
}

function statusCellStyle(value, row, index) {
    return {classes: 'delivery-status-cell'};
}


function selectedDeliveryState() {
    var rows = $("#tbl-deliveries").bootstrapTable("getSelections") || [];
    return {
        rows: rows,
        total: rows.length,
        qcRows: rows.filter(canRunQc),
        deleteRows: rows.filter(canDelete),
        submitRows: rows.filter(canSubmit)
    };
}

function updateBulkActionButton(selector, baseLabel, eligibleCount, total, reason) {
    var $button = $(selector);
    if (!$button.length) {
        return;
    }
    var label = baseLabel;
    if (total > 0) {
        label += eligibleCount === total
            ? ' (' + total + ')'
            : ' (' + eligibleCount + ' of ' + total + ')';
    }
    var disabled = total === 0 || eligibleCount !== total;
    $button
        .prop('disabled', disabled)
        .attr('title', disabled && total > 0 ? reason : '')
        .attr('aria-label', label + (disabled && total > 0 ? '. ' + reason : ''))
        .find('.delivery-action-label')
        .text(label);
}

function toggle_select_button() {
    var state = selectedDeliveryState();
    var selectionLabel = state.total === 0
        ? 'No deliveries selected'
        : state.total + (state.total === 1 ? ' delivery' : ' deliveries') + ' selected on this page';
    $('#delivery-selection-summary').text(selectionLabel);
    $('#delivery-bulk-actions').prop('hidden', state.total === 0);
    $('#btn-clear-selection').prop('hidden', state.total === 0);

    var unavailableActions = [];
    if ($('#btn-qc-multi').length && state.qcRows.length !== state.total) {
        unavailableActions.push('Run QC');
    }
    if ($('#btn-submit-multi').length && state.submitRows.length !== state.total) {
        unavailableActions.push('Submit to EEA');
    }
    if ($('#btn-delete-multi').length && state.deleteRows.length !== state.total) {
        unavailableActions.push('Delete');
    }
    var guidance = 'Choose an action for every selected delivery.';
    if (state.total === 0) {
        guidance = 'Select eligible deliveries on this page to apply a bulk action.';
    } else if (unavailableActions.length > 0) {
        guidance = 'Adjust the selection: not every delivery is eligible for ' + unavailableActions.join(', ') + '.';
    }
    $('#delivery-selection-guidance').text(guidance);

    updateBulkActionButton(
        '#btn-qc-multi',
        'Run QC',
        state.qcRows.length,
        state.total,
        'Run QC requires every selected delivery to be eligible.'
    );
    updateBulkActionButton(
        '#btn-delete-multi',
        'Delete',
        state.deleteRows.length,
        state.total,
        'Delete requires every selected delivery to be eligible.'
    );
    updateBulkActionButton(
        '#btn-submit-multi',
        'Submit to EEA',
        state.submitRows.length,
        state.total,
        'Submission requires every selected delivery to have passed QC.'
    );
}

function selectionActionBlocked(message) {
    $('#delivery-selection-guidance').text(message);
    $('#deliveries-live-status').text(message);
}


function updateTableAccessibility() {
    var rows = $('#tbl-deliveries').bootstrapTable('getData') || [];

    $('.fixed-table-toolbar .search input')
        .attr('aria-label', 'Search deliveries');
    $('#tbl-deliveries input[name="btSelectAll"]')
        .attr('aria-label', 'Select all eligible deliveries on this page');
    $('#tbl-deliveries input[name="btSelectItem"]').each(function (index) {
        var row = rows[index] || {};
        var filename = String(row.filename || ('delivery ' + (index + 1)));
        $(this).attr('aria-label', 'Select ' + filename);
    });
}


function updateTableStructureAccessibility() {
    var $scrollRegion = $('.deliveries-table-region .fixed-table-body').first();
    $scrollRegion.attr({
        'role': 'region',
        'aria-labelledby': 'deliveries-table-title',
        'aria-busy': $scrollRegion.attr('aria-busy') || 'true',
        'tabindex': '0'
    });

    var filterLabels = {
        'filename': 'Filter by name',
        'date_uploaded': 'Filter by upload date',
        'product_description': 'Filter by product',
        'last_job_status': 'Filter by QC status'
    };
    $('#tbl-deliveries thead th').each(function () {
        var $header = $(this);
        var field = $header.attr('data-field');
        var filterLabel = filterLabels[field];
        if (filterLabel) {
            $header.find('.filter-control input, .filter-control select')
                .attr('aria-label', filterLabel);
        }
    });

    var options = $('#tbl-deliveries').bootstrapTable('getOptions') || {};
    $('#tbl-deliveries thead th').removeAttr('aria-sort');
    $('#tbl-deliveries thead .th-inner.sortable').each(function () {
        var $control = $(this);
        var $header = $control.closest('th');
        var field = $header.attr('data-field');
        var label = $.trim($control.clone().children().remove().end().text()) || field;
        $control
            .attr({
                'role': 'button',
                'tabindex': '0',
                'aria-label': 'Sort by ' + label
            })
            .off('keydown.qcSort')
            .on('keydown.qcSort', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    $(this).trigger('click');
                }
            });
        if (field === options.sortName) {
            $header.attr('aria-sort', options.sortOrder === 'asc' ? 'ascending' : 'descending');
        }
    });
}


function setDeliveryTableBusy(isBusy) {
    $('.deliveries-table-region .fixed-table-body')
        .attr('aria-busy', isBusy ? 'true' : 'false');
}


function updateDeliverySummary(summary) {
    if (!summary) {
        return;
    }
    var values = {
        '#delivery-summary-total': summary.total,
        '#delivery-summary-passed': summary.passed,
        '#delivery-summary-in-progress': summary.in_progress,
        '#delivery-summary-failed': summary.failed,
        '#delivery-summary-not-checked': summary.not_checked,
        '#delivery-summary-other': summary.other
    };
    Object.keys(values).forEach(function (selector) {
        var value = Number(values[selector]);
        $(selector).text(Number.isFinite(value) && value >= 0 ? value : '\u2014');
    });
    $('#delivery-summary-other-wrap').prop('hidden', !(Number(summary.other) > 0));
}


var scheduledTableRefresh = null;

function scheduleTableRefresh() {
    window.clearTimeout(scheduledTableRefresh);
    scheduledTableRefresh = window.setTimeout(function () {
        $('#tbl-deliveries').bootstrapTable('refresh', {silent: true});
    }, 250);
}


function textDialogMessage(value) {
    return $('<div>').text(String(value || ''));
}


function listDialogMessage(values, omittedCount) {
    var $message = $('<div>');
    values.forEach(function (value) {
        $('<div>').text(String(value)).appendTo($message);
    });
    if (omittedCount > 0) {
        $('<div>').text('...and ' + omittedCount + ' others.').appendTo($message);
    }
    return $message;
}


function submissionResultMessage(result) {
    var $message = $('<div>');
    $('<div>').text(String(result.message || '')).appendTo($message);
    if (Array.isArray(result.failed) && result.failed.length > 0) {
        $('<strong>').text('Issues:').appendTo($message);
        result.failed.forEach(function (issue) {
            $('<div>').text(String(issue)).appendTo($message);
        });
    }
    return $message;
}


function delete_function(delivery_ids, filenames) {
    var msg_title = "Delete this delivery?";
    var num_deliveries = delivery_ids.toString().split(",").length;

    if (num_deliveries > 1) {
        msg_title = "Delete " + num_deliveries + " deliveries?";
    }
    var filenameList = filenames.toString().split(',');
    var msg_filenames = $('<div>')
        .append($('<p>').text(
            num_deliveries === 1
                ? 'The delivery ZIP and its QC history will no longer be available. This action cannot be undone.'
                : 'The selected delivery ZIP files and their QC histories will no longer be available. This action cannot be undone.'
        ))
        .append(listDialogMessage(
            filenameList.slice(0, 10),
            Math.max(filenameList.length - 10, 0)
        ));
    BootstrapDialog.show({
        type: BootstrapDialog.TYPE_DANGER,
        title: msg_title,
        message: msg_filenames,
        buttons: [{
            label: num_deliveries === 1 ? "Delete delivery" : "Delete " + num_deliveries + " deliveries",
            cssClass: "btn-danger",
            action: function(dialog) {
                var $button = this;
                var data = {"ids": delivery_ids};
                $button.disable();
                $button.spin();
                $.ajax({
                    type: "POST",
                    url: DELIVERY_DELETE_URL,
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        if (result.status === "error") {
                            BootstrapDialog.show({
                                type: BootstrapDialog.TYPE_WARNING,
                                title: "Cannot delete deliveries.",
                                message: textDialogMessage("Error deleting deliveries. " + result.message),
                                buttons: [{
                                    label: "OK",
                                    cssClass: "btn-default",
                                    action: function(dialog) {dialog.close();}
                                }]
                            });
                            dialog.close();
                            return;
                        }
                        $('#tbl-deliveries').bootstrapTable('uncheckAll');
                        $('#tbl-deliveries').bootstrapTable('refresh');
                        $('#deliveries-live-status').text(result.message || 'Selected deliveries deleted.');
                        dialog.close();
                    },
                    error: function(result)  {
                        var error_message = "Unspecified error.";
                        if (result.responseJSON && result.responseJSON.message) {
                            error_message = result.responseJSON.message;
                        }
                        dialog.close();
                        BootstrapDialog.show({
                            type: BootstrapDialog.TYPE_WARNING,
                            title: "Delivery could not be deleted",
                            message: textDialogMessage(error_message),
                            buttons: [{
                                label: "OK",
                                cssClass: "btn-default",
                                action: function(errorDialog) {errorDialog.close();}
                            }]
                        });
                    }
                });
            }
        }, {
            label: "Cancel",
            cssClass: "btn-default",
            action: function(dialog) {dialog.close();}
        }]
    });
}

function submit_eea_function(id, filename) {
    BootstrapDialog.show({
        type: BootstrapDialog.TYPE_PRIMARY,
        title: "Submit this delivery to EEA?",
        message: $('<div>')
            .append($('<p>').text('The latest successful QC result will be used for submission.'))
            .append(textDialogMessage(filename)),
        buttons: [{
            label: "Submit delivery",
            cssClass: "btn-primary",
            action: function(dialog) {
                var $button = this;
                var data = {"id": id, "filename": filename};
                $button.disable();
                $button.spin();
                dialog.setMessage("Submitting to EEA...");
                $.ajax({
                    type: "POST",
                    url: DELIVERY_SUBMIT_URL,
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        BootstrapDialog.show({
                            title: "Delivery successfully submitted",
                            message: textDialogMessage(result.message),
                            buttons: [{
                                label: "OK",
                                cssClass: "btn-default",
                                action: function(success_dialog) {success_dialog.close();}
                            }]
                        });
                        $('#tbl-deliveries').bootstrapTable('uncheckAll');
                        $('#tbl-deliveries').bootstrapTable('refresh');
                        $('#deliveries-live-status').text(result.message || 'Delivery submitted to EEA.');
                        dialog.close();
                    },
                    error: function(result)  {
                        var error_message = "Unspecified error.";
                        if (result.responseJSON && result.responseJSON.message) {
                            error_message = result.responseJSON.message;
                        }
                        dialog.close();
                        BootstrapDialog.show({
                            type: BootstrapDialog.TYPE_WARNING,
                            title: "Error submitting delivery to EEA",
                            message: textDialogMessage(error_message),
                            buttons: [{
                                label: "OK",
                                cssClass: "btn-default",
                                action: function(error_dialog) {error_dialog.close();}
                            }]
                        });
                    }
                });
            }
        }, {
            label: "Cancel",
            cssClass: "btn-default",
            action: function(dialog) {dialog.close();}
        }]
    });
}


function submit_eea_batch_function(delivery_ids, filenames) {
    // Convert to arrays if they are comma-separated strings
    var id_array = Array.isArray(delivery_ids) ? delivery_ids : delivery_ids.toString().split(",");
    var name_array = Array.isArray(filenames) ? filenames : filenames.toString().split(",");
    var num_deliveries = id_array.length;

    var msg_title = num_deliveries > 1 
        ? "Submit " + num_deliveries + " deliveries to EEA?" 
        : "Submit delivery to EEA?";

    // Generate preview of filenames
    var msg_filenames = $('<div>')
        .append($('<p>').text('The latest successful QC result for each delivery will be used for submission.'))
        .append(listDialogMessage(
            name_array.slice(0, 10),
            Math.max(num_deliveries - 10, 0)
        ));

    BootstrapDialog.show({
        type: BootstrapDialog.TYPE_PRIMARY,
        title: msg_title,
        message: msg_filenames,
        buttons: [{
            label: num_deliveries === 1 ? "Submit delivery" : "Submit " + num_deliveries + " deliveries",
            cssClass: "btn-primary",
            action: function(dialog) {
                // Ensure we send BOTH ids and filenames as strings
                var data = {
                    "ids": id_array.join(","),
                    "filenames": name_array.join(",")
                };

                // Add a "Loading" state to the button
                var $btn = this;
                $btn.disable();
                $btn.spin();

                $.ajax({
                    type: "POST",
                    url: DELIVERY_SUBMIT_BATCH_URL,
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        dialog.close(); // Close the confirmation dialog
                        
                        // Show a Success/Summary Message
                        BootstrapDialog.show({
                            type: result.status === "ok" ? BootstrapDialog.TYPE_SUCCESS : BootstrapDialog.TYPE_WARNING,
                            title: "Submission Result",
                            message: submissionResultMessage(result),
                            buttons: [{
                                label: "OK",
                                action: function(d) { d.close(); }
                            }]
                        });

                        $('#tbl-deliveries').bootstrapTable('uncheckAll');
                        $('#tbl-deliveries').bootstrapTable('refresh');
                        $('#deliveries-live-status').text(result.message || 'Selected deliveries submitted to EEA.');
                    },
                    error: function(xhr) {
                        dialog.close();
                        var err_msg = (xhr.responseJSON && xhr.responseJSON.message) ? xhr.responseJSON.message : "Internal Server Error.";
                        
                        BootstrapDialog.show({
                            type: BootstrapDialog.TYPE_DANGER,
                            title: "System Error",
                            message: textDialogMessage(err_msg),
                            buttons: [{ label: "OK", action: function(d) { d.close(); }}]
                        });
                    }
                });
            }
        }, {
            label: "Cancel",
            action: function(dialog) { dialog.close(); }
        }]
    });
}


function update_job_statuses() {
    // Refreshes rows in the deliveries table with 'running' or 'waiting' status.

    // deliveries: data for all deliveries visible in the ui table
    var deliveries = $("#tbl-deliveries").bootstrapTable("getData");
    for(var i=0, len=deliveries.length; i < len; i++) {
        if(deliveries[i].last_job_status === "waiting" || deliveries[i].last_job_status === "running") {
            var delivery_status_url = "/job/update/" + deliveries[i].last_job_uuid + "/";

            // sends a request to the server and asks for new status of running or waiting job.
            $.ajax({
                type: "POST",
                url: delivery_status_url,
                datatype:"json",
                success:function(updated_delivery)
                {
                    // if server sends a response: auto-refresh the correct row in the UI.
                    // the UI row is matched using job_uuid.
                    var deliveries_to_update = $("#tbl-deliveries").bootstrapTable("getData");
                    for(var new_index=0, new_len=deliveries_to_update.length; new_index < new_len; new_index++) {
                        if (deliveries_to_update[new_index].id === updated_delivery.id) {
                            // a matching row is found in the UI -> tell BootstrapTable to refresh it.
                            console.log("refreshing table row in UI with id: " + updated_delivery.id);

                            var statusChanged = deliveries_to_update[new_index].last_job_status !== updated_delivery.last_job_status;
                            $("#tbl-deliveries").bootstrapTable("updateRow", {index: new_index, row: updated_delivery});
                            if (statusChanged) {
                                scheduleTableRefresh();
                            }
                        }
                    }
                }
            });
        }
    }
}

$(document).ready(function() {

    // Set defult tooltip in each table row.
    $('[data-toggle="tooltip"]').tooltip();

    $('#tbl-deliveries').bootstrapTable({
       cache: false,
       striped: true,
       search: true,
       pagination: true,
       showColumns: true,
       sortName: 'id',
       sortOrder: 'desc',
       url: DELIVERIES_DATA_URL,
       pageSize: 20,
       pageList: [20, 50, 100, 500],
       formatNoMatches: function () {
           if (CAN_UPLOAD) {
               return 'No deliveries found. Upload a delivery ZIP file to get started.';
           }
           return 'No deliveries are currently available for your account.';
       }
    });

    updateTableAccessibility();
    updateTableStructureAccessibility();

    $('#tbl-deliveries').on('click', '.delete-button', function () {
        delete_function(
            $(this).attr('data-delivery-id'),
            $(this).attr('data-delivery-filename')
        );
    });

    $('#tbl-deliveries').on('click', '.submit-delivery-button', function () {
        submit_eea_function(
            $(this).attr('data-delivery-id'),
            $(this).attr('data-delivery-filename')
        );
    });

    $('#btn-clear-selection').on('click', function () {
        $('#tbl-deliveries').bootstrapTable('uncheckAll');
        toggle_select_button();
        $('#deliveries-live-status').text('Delivery selection cleared.');
    });

    // check one row
    $('#tbl-deliveries').on('check.bs.table', function (e, row) {
        toggle_select_button();
    });

    // check all rows
    $('#tbl-deliveries').on('check-all.bs.table', function () {
        toggle_select_button();
    });

    // uncheck one row
    $('#tbl-deliveries').on('uncheck.bs.table', function (e, row) {
        toggle_select_button();
    });

    // uncheck all rows
    $('#tbl-deliveries').on('uncheck-all.bs.table', function () {
        toggle_select_button();
    });

    $('#tbl-deliveries').on('refresh.bs.table', function () {
        setDeliveryTableBusy(true);
    });

    $('#tbl-deliveries').on('load-success.bs.table', function (event, response) {
        toggle_select_button();
        updateTableAccessibility();
        updateTableStructureAccessibility();
        updateDeliverySummary(response && response.summary);
        $('#tbl-deliveries [data-toggle="tooltip"]').tooltip();
        setDeliveryTableBusy(false);
        var visibleCount = $('#tbl-deliveries').bootstrapTable('getData').length;
        $('#deliveries-live-status').text(visibleCount + ' deliveries loaded.');
    });

    $('#tbl-deliveries').on('post-body.bs.table post-header.bs.table created-controls.bs.table sort.bs.table', function () {
        updateTableAccessibility();
        updateTableStructureAccessibility();
        $('#tbl-deliveries [data-toggle="tooltip"]').tooltip();
    });

    $('#tbl-deliveries').on('load-error.bs.table', function () {
        setDeliveryTableBusy(false);
        $('#deliveries-live-status').text('Deliveries could not be loaded. Please try again.');
    });

    $('#tbl-deliveries').on('column-search.bs.table', function (event, text) {
        event.preventDefault();
        console.log(event);
        console.log(text);
        
        event.stopImmediatePropagation();
        
    });

    // Run QC for the current-page selection. Mixed eligibility is never
    // silently reduced to a subset: users must first correct the selection.
    $('#btn-qc-multi').on('click', function() {
        var state = selectedDeliveryState();
        if (state.total === 0 || state.qcRows.length !== state.total) {
            toggle_select_button();
            selectionActionBlocked('Run QC requires every selected delivery to be eligible.');
            return;
        }
        var selectedDeliveryIds = $.map(state.rows, function (row) {
            return row.id;
        });
        window.location.assign(SETUP_JOB_URL + '?' + $.param({deliveries: selectedDeliveryIds.join(',')}));
    });

    // Delete every selected delivery, or none of them.
    $('#btn-delete-multi').on('click', function() {
        var state = selectedDeliveryState();
        if (state.total === 0 || state.deleteRows.length !== state.total) {
            toggle_select_button();
            selectionActionBlocked('Delete requires every selected delivery to be eligible.');
            return;
        }
        var selectedDeliveryIds = $.map(state.rows, function (row) {
            return row.id;
        });
        var selectedDeliveryFilenames = $.map(state.rows, function (row) {
            return row.filename;
        });
        delete_function(selectedDeliveryIds.join(','), selectedDeliveryFilenames.join(','));
    });

    // Submit every selected delivery, or none of them.
    $('#btn-submit-multi').on('click', function() {
        var state = selectedDeliveryState();
        if (state.total === 0 || state.submitRows.length !== state.total) {
            toggle_select_button();
            selectionActionBlocked('Submission requires every selected delivery to have passed QC.');
            return;
        }
        var selectedDeliveryIds = $.map(state.rows, function (row) {
            return row.id;
        });
        var selectedDeliveryFilenames = $.map(state.rows, function (row) {
            return row.filename;
        });
        submit_eea_batch_function(selectedDeliveryIds.join(','), selectedDeliveryFilenames.join(','));
    });

    $("#btn-export").click(function() {
        const baseUrl = DELIVERY_EXPORT_URL;
        const search = $("input.form-control.search-input").val(); // existing search input
        const filter = ""; // you can later capture filter JSON from bootstrap-table
        const sort = $("#tbl-deliveries").bootstrapTable("getOptions").sortName;
        const order = $("#tbl-deliveries").bootstrapTable("getOptions").sortOrder;

        // Construct query string
        const query = $.param({
            search: search,
            filter: filter,
            sort: sort,
            order: order
        });

        // Trigger Excel download
        window.location = `${baseUrl}?${query}`;
    });

    // Start the timer to auto-refresh status of running jobs. Check for updates every 5 seconds.
    toggle_select_button();

    if (UPDATE_JOB_STATUSES) {
        update_job_statuses();
        setInterval(function(){update_job_statuses();}, UPDATE_JOB_STATUSES_INTERVAL);
    }
});
