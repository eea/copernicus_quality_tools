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

function disabledAction(label, message) {
    return $('<button>', {
        'class': 'btn btn-sm btn-default',
        'data-toggle': 'tooltip',
        'title': message,
        'disabled': true,
        'text': label
    });
}

function actionsFormatter(value, row) {
    var $buttons = $('<div>', {'class': 'btn-group'});

    if (CAN_RUN_QC) {
        if (canRunQc(row)) {
            $('<a>', {
                'class': 'btn btn-sm btn-success',
                'role': 'button',
                'data-toggle': 'tooltip',
                'title': 'Run quality controls for this delivery.',
                'href': '/setup_job?' + $.param({deliveries: row.id}),
                'text': 'QC'
            }).appendTo($buttons);
        } else {
            $buttons.append(disabledAction("QC", "Quality controls are not available for this delivery."));
        }
    }

    if (CAN_DELETE) {
        if (canDelete(row)) {
            $('<button>', {
                'class': 'btn btn-sm btn-danger delete-button',
                'data-toggle': 'tooltip',
                'title': 'Delete this delivery.',
                'text': 'Delete'
            })
                .attr('data-delivery-id', String(row.id))
                .attr('data-delivery-filename', String(row.filename || ''))
                .appendTo($buttons);
        } else {
            $buttons.append(disabledAction("Delete", "This delivery cannot be deleted."));
        }
    }

    if (SUBMISSION_ENABLED && CAN_SUBMIT) {
        if (canSubmit(row)) {
            $('<button>', {
                'class': 'btn btn-sm btn-default submit-delivery-button',
                'data-toggle': 'tooltip',
                'title': 'Send this delivery to EEA for approval.',
                'text': 'Submit to EEA'
            })
                .attr('data-delivery-id', String(row.id))
                .attr('data-delivery-filename', String(row.filename || ''))
                .appendTo($buttons);
        } else {
            $buttons.append(disabledAction("Submit to EEA", "This delivery is not ready for submission."));
        }
    }

    return $buttons.prop('outerHTML');
}

function statusFormatter(value, row, index) {
    if (value == "file_not_found") {
        value = '<span class="glyphicon glyphicon-exclamation-sign" aria-hidden="true"> </span>';
        value += '<span class="text-danger">FILE NOT FOUND</span>';
        return value;
    }
    if (!row.last_job_status) {
        return 'Not checked';
    }
    if (value == "ok") {
        if (row["date_submitted"] !== null) {
            value = "submitted";
        } else {
            value = "passed";
        }
    }
    return $('<a>', {
        'class': 'like',
        'href': '/result/' + encodeURIComponent(String(row.last_job_uuid)),
        'title': 'Show results',
        'text': String(value)
    }).prop('outerHTML');
}

function statusCellStyle(value, row, index) {

    if (value == "ok") {
        return { classes: "success"}
    }
    if (value == "failed" || value == "error") {
        return { classes: "danger" }
    }
    return {};
}


function toggle_select_button() {
    var selectedRows = $("#tbl-deliveries").bootstrapTable("getSelections");
    var qcCount = selectedRows.filter(canRunQc).length;
    var deleteCount = selectedRows.filter(canDelete).length;
    var submitCount = selectedRows.filter(canSubmit).length;

    $("#btn-qc-multi")
        .prop("disabled", qcCount === 0)
        .text(qcCount ? "QC all selected (" + qcCount + ")" : "QC all selected");
    $("#btn-delete-multi")
        .prop("disabled", deleteCount === 0)
        .text(deleteCount ? "Delete selected (" + deleteCount + ")" : "Delete selected");
    $("#btn-submit-multi")
        .prop("disabled", submitCount === 0)
        .text(submitCount ? "Submit selected (" + submitCount + ")" : "Submit selected");
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
    var msg_title = "Are you sure you want to delete the delivery ZIP file?";

    // number of deliveries to delete
    console.log(delivery_ids);
    console.log(filenames);
    var num_deliveries = delivery_ids.toString().split(",").length;

    if (num_deliveries > 1) {
        msg_title = "Are you sure you want to delete " + num_deliveries + " delivery ZIP files?";
    }
    var filenameList = filenames.toString().split(',');
    var msg_filenames = listDialogMessage(
        filenameList.slice(0, 10),
        Math.max(filenameList.length - 10, 0)
    );
    var dlg_ok = BootstrapDialog.show({
        type: BootstrapDialog.TYPE_DANGER,
        title: msg_title,
        message: msg_filenames,
        buttons: [{
            label: "Yes",
            cssClass: "btn-default",
            action: function(dialog) {
                data = {"ids": delivery_ids};
                $.ajax({
                    type: "POST",
                    url: "/delivery/delete/",
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        if (result.status === "error") {
                            var dlg_err = BootstrapDialog.show({
                                type: BootstrapDialog.TYPE_WARNING,
                                title: "Cannot delete deliveries.",
                                message: textDialogMessage("Error deleting deliveries. " + result.message),
                                buttons: [{
                                    label: "OK",
                                    cssClass: "btn-default",
                                    action: function(dialog) {dialog.close();}
                                }]
                            });
                        }
                        $('#tbl-deliveries').bootstrapTable('refresh');
                        dialog.close();
                    },
                    error: function(result)  {
                        var error_message = "Unspecified error.";
                            if (result.hasOwnProperty("responseJSON")) {
                                error_message = result.responseJSON.message;
                            }
                            var dlg_err = BootstrapDialog.show({
                                type: BootstrapDialog.TYPE_WARNING,
                                title: "Error",
                                message: textDialogMessage(error_message),
                                buttons: [{
                                    label: "OK",
                                    cssClass: "btn-default",
                                    action: function(dialog) {dialog.close();}
                                }]
                            });
                    }
                });
            }
        }, {
            label: "No",
            cssClass: "btn-default",
            action: function(dialog) {dialog.close();}
        }]
    });
}

function submit_eea_function(id, filename) {
    console.log("clicked submit to EEA!");
    var dlg_ok = BootstrapDialog.show({
        title: "Are you sure you want to submit the delivery to EEA?",
        message: textDialogMessage("Delivery file name: " + filename),
        buttons: [{
            label: "Yes",
            cssClass: "btn-default",
            action: function(dialog) {
                console.log("Submit to EEA confirmed by the user.");

                data = {"id": id, "filename": filename};
                dialog.setMessage("Submitting to EEA...");
                $.ajax({
                    type: "POST",
                    url: "/delivery/submit/",
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        console.log("file marked successfully for submission to EEA!");
                        var dlg_success = BootstrapDialog.show({
                            title: "Delivery successfully submitted",
                            message: textDialogMessage(result.message),
                            buttons: [{
                                label: "OK",
                                cssClass: "btn-default",
                                action: function(success_dialog) {success_dialog.close();}
                            }]
                       });
                       $('#tbl-deliveries').bootstrapTable('refresh');
                       dialog.close();
                    },
                    error: function(result)  {
                      console.log("error in submit to EEA.");
                      console.log(result.responseJSON);
                      var error_message = "Unspecified error.";
                      if (result.hasOwnProperty("responseJSON")) {
                        error_message = result.responseJSON.message;
                      }
                      var dlg_err = BootstrapDialog.show({
                            type: BootstrapDialog.TYPE_WARNING,
                            title: "Error submitting delivery to EEA",
                            message: textDialogMessage(error_message),
                            buttons: [{
                                label: "OK",
                                cssClass: "btn-default",
                                action: function(error_dialog) {error_dialog.close();}
                            }]
                       });
                       dialog.close();
                    }
                })
            }
        }, {
            label: "No",
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
    var msg_filenames = listDialogMessage(
        name_array.slice(0, 10),
        Math.max(num_deliveries - 10, 0)
    );

    BootstrapDialog.show({
        type: BootstrapDialog.TYPE_PRIMARY,
        title: msg_title,
        message: msg_filenames,
        buttons: [{
            label: "Yes, Submit",
            cssClass: "btn-success",
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
                    url: "/delivery/submit_batch/",
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

                        $('#tbl-deliveries').bootstrapTable('refresh');
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

                            $("#tbl-deliveries").bootstrapTable("updateRow", {index: new_index, row: updated_delivery});
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
       url: "/data/delivery/list/",
       pageSize: 20,
       pageList: [20, 50, 100, 500],
       formatNoMatches: function () {
           return 'No deliveries found. Please upload a delivery ZIP file.';
       }
    });

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

    $('#tbl-deliveries').on('load-success.bs.table', function () {
        toggle_select_button();
    });

    $('#tbl-deliveries').on('column-search.bs.table', function (event, text) {
        event.preventDefault();
        console.log(event);
        console.log(text);
        
        event.stopImmediatePropagation();
        
    });

    // "QC all selected" button is clicked
    $('#btn-qc-multi').on('click', function() {
        console.log("QC all selected button clicked!");
        var runnableRows = $("#tbl-deliveries").bootstrapTable("getSelections").filter(canRunQc);
        if (runnableRows.length === 0) {
            alert("Please select at least one delivery that can run QC.");
            toggle_select_button();
            return;
        }
        var selected_delivery_ids = $.map(runnableRows, function (row) {
            return row.id
        });
        $(location).attr("href","/setup_job?deliveries=" + selected_delivery_ids.join(","));
    })

    // "Delete selected" button is clicked
    $('#btn-delete-multi').on('click', function() {
        console.log("Delete selected button clicked!");
        var deletableRows = $("#tbl-deliveries").bootstrapTable("getSelections").filter(canDelete);
        if (deletableRows.length === 0) {
            alert("Please select at least one delivery that can be deleted.");
            toggle_select_button();
            return;
        }
        var selected_delivery_ids = $.map(deletableRows, function (row) {
            return row.id
        });
        var selected_delivery_filenames = $.map(deletableRows, function (row) {
            return row.filename
        });
        delete_function(selected_delivery_ids.join(","), selected_delivery_filenames.join(","));
    });

    // "Submit selected" button is clicked
    $('#btn-submit-multi').on('click', function() {
        console.log("Submit selected button clicked!");
        var submittableRows = $("#tbl-deliveries").bootstrapTable("getSelections").filter(canSubmit);
        var numCheckedSubmittable = submittableRows.length;
        if (numCheckedSubmittable === 0) {
            alert("Please select at least one delivery with 'passed' status.");
            toggle_select_button();
            return;
        }
        // TODO - if some of the selected deliveries are not in "ok" status, show a warning message and ask user to confirm submission.

        var submittable_delivery_ids = $.map(submittableRows, function (row) {
            return row.id
        });
        var submittable_delivery_filenames = $.map(submittableRows, function (row) {
            return row.filename
        });
        submit_eea_batch_function(submittable_delivery_ids.join(","), submittable_delivery_filenames.join(","));
    });

    $("#btn-export").click(function() {
        const baseUrl = "/data/delivery/export/";
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
