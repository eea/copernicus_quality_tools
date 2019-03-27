// Populate content of deliveries table from /data/delivery/list/ URL.
$('#tbl-deliveries').bootstrapTable({
    cache: false,
    striped: true,
    search: true,
    pagination: true,
    showColumns: true,
    sortName: 'name',
    sortOrder: 'desc',
    url: "/data/delivery/list/",
    pageSize: 20,
    pageList: [20, 50, 100, 500],
    formatNoMatches: function () {
        return 'No deliveries found. Please upload a delivery ZIP file.';
    }
});

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
   if (row.date_submitted !== null) {
        return {
            disabled:true,
            checked: false
        };
   } else {
        return {
            disabled: false
        };
   }
}


function actionsFormatter(value, row) {
    // for example /setup_job/1234
    var btn_data = '<div class="btn-group">';

    if (row.last_job_status === "waiting" || row.last_job_status === "running" || row.date_submitted) {
        // job is running --> QC button disabled, Delete button disabled
        var tooltip_message = "QC job is currently running.";
        if (row.is_submitted) {
            tooltip_message = "Delivery has been already submitted to EEA.";
        }
        btn_data += "<a class=\"btn btn-sm btn-success\" role=\"button\" disabled data-toggle=\"tooltip\"";
        btn_data += 'title="Cannot run quality controls for this delivery. ' + tooltip_message;
        btn_data += '">QC</a>';
        btn_data += ' <button class="btn btn-sm btn-default" data-toggle="tooltip" ';
        btn_data += 'title="Cannot delete this delivery. ' + tooltip_message + '" disabled>Delete</button>';
    } else {
        // job is not running and delivery is not submitted --> QC button is enabled
        btn_data += '<a class="btn btn-sm btn-success" role="button" data-toggle="tooltip" ';
        btn_data += 'title="Run quality controls for this delivery." href="/setup_job?deliveries=' + row.id + '" >QC</a>';
        btn_data += '<button onclick="delete_function(' + row.id + ', \'' + row.filename + '\')" ';
        btn_data += 'class="btn btn-sm btn-danger delete-button" data-toggle="tooltip" title="Delete this delivery.">';
        btn_data += 'Delete</button>';
    }

    // "Submit to EEA" button visibility is controlled by the SUBMISSION_ENABLED setting.
    if (SUBMISSION_ENABLED) {
        if (row.date_submitted) {
            btn_data += ' <button class="btn btn-sm btn-default disabled data-toggle="tooltip" ';
            btn_data += 'title="Delivery has already been submitted to EEA.">Submit to EEA</button>';
        } else {
            if (row.last_job_status === "ok") {
                btn_data += ' <button onclick="submit_eea_function(' + row.id + ', \'' + row.filename + '\')"';
                btn_data += ' class="btn btn-sm btn-default data-toggle="tooltip"';
                btn_data += ' title="Click to send the delivery to EEA for approval.">Submit to EEA</button>';
            } else {
                btn_data += ' <button class="btn btn-sm btn-default disabled data-toggle="tooltip"';
                btn_data += ' title="Delivery cannot be submitted to EEA. QC status is not OK.">Submit to EEA</button>';
            }
        }
    }
    btn_data += '</div>';
    return btn_data;
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
    return ['<a class="like" href="/result/', row.last_job_uuid, '" title="Show results">', value, '</a>'].join('');
}

function statusCellStyle(value, row, index) {

    if (value == "ok") {
        return { classes: "success"}
    }
    if (value == "failed" || value == "error" || value == "expired") {
        return { classes: "danger" }
    }
    return {};
}


// Enable or disable 'QC all selected' button based on selected rows
function toggle_select_button() {
    var numChecked = $("#tbl-deliveries").bootstrapTable("getSelections").length;
    if (numChecked === 0) {
        $("#btn-qc-multi").text("QC all selected");
        $("#btn-qc-multi").prop("disabled", true);
        $("#btn-delete-multi").text("Delete all selected");
        $("#btn-delete-multi").prop("disabled", true);
    } else {
        $("#btn-qc-multi").text("QC all selected (" + numChecked + ")");
        $("#btn-qc-multi").prop("disabled", false);
        $("#btn-delete-multi").text("Delete all selected (" + numChecked + ")");
        $("#btn-delete-multi").prop("disabled", false);
    }
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
    if (num_deliveries > 10) {
        msg_filenames = filenames.split(",").slice(0, 10).join("<br>") + "<br> ...and " + (num_deliveries - 10) + " others.";
    } else if (num_deliveries > 0) {
        msg_filenames = filenames.split(",").slice(0, 10).join("<br>");
    }
    var dlg_ok = BootstrapDialog.show({
        type: BootstrapDialog.TYPE_DANGER,
        title: msg_title,
        message: msg_filenames, //filenames.replace(/,/g, "<br>"), //replaces all commas by newline.
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
                                message: "Error deleting deliveries. " + result.message,
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
                                message: error_message,
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
        message: "Delivery file name: " + filename,
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
                            message: result.message,
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
                            message: error_message,
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

function update_job_statuses() {
    // Refreshes rows in the deliveries table with 'running' or 'waiting' status.

    // deliveries: data for all deliveries visible in the ui table
    var deliveries = $("#tbl-deliveries").bootstrapTable("getData");
    for(var i=0, len=deliveries.length; i < len; i++) {
        if(deliveries[i].last_job_status === "waiting" || deliveries[i].last_job_status === "running") {
            var delivery_status_url = "/job/update/" + deliveries[i].last_job_uuid + "/";

            // sends a request to the server and asks for new status of running or waiting job.
            $.ajax({
                type: "get",
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

    // "QC all selected" button is clicked
    $('#btn-qc-multi').on('click', function() {
        console.log("QC all selected button clicked!");
        if ($("#tbl-deliveries").bootstrapTable("getSelections").length === 0) {
            alert("Please select at least one delivery.");
        }
        var selected_delivery_ids = $.map($("#tbl-deliveries").bootstrapTable('getSelections'), function (row) {
            return row.id
        });
        $(location).attr("href","/setup_job?deliveries=" + selected_delivery_ids.join(","));
    })

    // "Delete all selected" button is clicked
    $('#btn-delete-multi').on('click', function() {
        console.log("Delete all selected button clicked!");
        if ($("#tbl-deliveries").bootstrapTable("getSelections").length === 0) {
            alert("Please select at least one delivery.");
            toggle_select_button();
            return;
        }
        var selected_delivery_ids = $.map($("#tbl-deliveries").bootstrapTable('getSelections'), function (row) {
            return row.id
        });
        var selected_delivery_filenames = $.map($("#tbl-deliveries").bootstrapTable('getSelections'), function (row) {
            return row.filename
        });
        delete_function(selected_delivery_ids.join(","), selected_delivery_filenames.join(","));
    });

    // Start the timer to auto-refresh status of running jobs. Check for updates every 5 seconds.
    toggle_select_button();
    update_job_statuses();
    setInterval(function(){update_job_statuses();}, 5000);
});
