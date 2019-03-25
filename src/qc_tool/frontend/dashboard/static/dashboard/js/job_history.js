
// Populate content of deliveries table from /data/delivery/list/ URL.
    $('#tbl-history').bootstrapTable({
        cache: false,
        striped: true,
        search: true,
        pagination: true,
        showColumns: true,
        sortName: 'name',
        sortOrder: 'desc',
        url: "/data/job_history/" + delivery_id + "/",
        pageSize: 20,
        pageList: [20, 50, 100, 500],
        formatNoMatches: function () {
            return 'No job history available.';
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
        return moment(value).format('YYYY-MM-DD HH:mm:ss');
   } else {
        return null;
   }
}


function delete_job_function(job_uuids) {
    var msg_title = "Are you sure you want to delete the job history?";

    // number of deliveries to delete
    console.log(job_uuids);
    var num_jobs = job_uuids.toString().split(",").length;

    if (num_jobs > 1) {
        msg_title = "Are you sure you want to delete " + num_jobs + " job history logs?";
    }
    if (num_jobs > 10) {
        msg_jobs = job_uuids.split(",").slice(0, 10).join("<br>") + "<br> ...and " + (num_jobs - 10) + " others.";
    } else if (num_jobs > 0) {
        msg_jobs = job_uuids.split(",").slice(0, 10).join("<br>");
    }
    var dlg_ok = BootstrapDialog.show({
        type: BootstrapDialog.TYPE_DANGER,
        title: msg_title,
        message: msg_jobs,
        buttons: [{
            label: "Yes",
            cssClass: "btn-default",
            action: function(dialog) {
                data = {"uuids": job_uuids};
                $.ajax({
                    type: "POST",
                    url: "/job/delete/",
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        if (result.status === "error") {
                            var dlg_err = BootstrapDialog.show({
                                type: BootstrapDialog.TYPE_WARNING,
                                title: "Cannot delete deliveries.",
                                message: "Error deleting job history. " + result.message,
                                buttons: [{
                                    label: "OK",
                                    cssClass: "btn-default",
                                    action: function(dialog) {dialog.close();}
                                }]
                            });
                        }
                        $('#tbl-history').bootstrapTable('refresh');
                        dialog.close();
                    },
                    error: function(result)  {
                         var dlg_err = BootstrapDialog.show({
                            type: BootstrapDialog.TYPE_WARNING,
                            title: "Error",
                            message: "Error deleting job history.",
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


function submittedFormatter(value, row, index) {
    if (!value) {
        return "No";
    } else {
        return "Yes";
    }
}

function statusFormatter(value, row, index) {
    if (value == "file_not_found") {
        value = '<span class="glyphicon glyphicon-exclamation-sign" aria-hidden="true"> </span>';
        value += '<span class="text-danger">FILE NOT FOUND</span>';
        return value;
    }
    if (!value) {
        return 'Not checked';
    }
    return ['<a class="like" href="/result/', row.job_uuid, '" title="Show results">', value, '</a>'].join('');
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
    var numChecked = $("#tbl-history").bootstrapTable("getSelections").length;
    if (numChecked === 0) {
        $("#btn-delete-multi").text("Delete all selected");
        $("#btn-delete-multi").prop("disabled", true);
    } else {
        $("#btn-delete-multi").text("Delete all selected (" + numChecked + ")");
        $("#btn-delete-multi").prop("disabled", false);
    }
}


function delete_function(job_uuids) {
    var msg_title = "Are you sure you want to delete the job history log?";

    // number of deliveries to delete
    console.log(job_uuids);
    var num_jobs = job_uuids.toString().split(",").length;

    if (num_jobs > 1) {
        msg_title = "Are you sure you want to delete " + num_deliveries + " job history logs?";
    }
    if (num_jobs > 10) {
        msg_jobs = job_uuids.split(",").slice(0, 10).join("<br>") + "<br> ...and " + (num_jobs - 10) + " others.";
    } else if (num_jobs > 0) {
        msg_jobs = job_uuids.split(",").slice(0, 10).join("<br>");
    }
    var dlg_ok = BootstrapDialog.show({
        type: BootstrapDialog.TYPE_DANGER,
        title: msg_title,
        message: msg_jobs,
        buttons: [{
            label: "Yes",
            cssClass: "btn-default",
            action: function(dialog) {
                data = {"ids": job_uuids};
                $.ajax({
                    type: "POST",
                    url: "/job/delete/",
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        if (result.status === "error") {
                            var dlg_err = BootstrapDialog.show({
                                type: BootstrapDialog.TYPE_WARNING,
                                title: "Cannot delete jobs.",
                                message: "Error deleting jobs. " + result.message,
                                buttons: [{
                                    label: "OK",
                                    cssClass: "btn-default",
                                    action: function(dialog) {dialog.close();}
                                }]
                            });
                        }
                        $('#tbl-history').bootstrapTable('refresh');
                        dialog.close();
                    },
                    error: function(result)  {
                         var dlg_err = BootstrapDialog.show({
                            type: BootstrapDialog.TYPE_WARNING,
                            title: "Error",
                            message: "Error deleting jobs.",
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



$(document).ready(function() {

    // Set defult tooltip in each table row.
    $('[data-toggle="tooltip"]').tooltip();

    // check one row
    $('#tbl-history').on('check.bs.table', function (e, row) {
        toggle_select_button();
    });

    // check all rows
    $('#tbl-history').on('check-all.bs.table', function () {
        toggle_select_button();
    });

    // uncheck one row
    $('#tbl-history').on('uncheck.bs.table', function (e, row) {
        toggle_select_button();
    });

    // uncheck all rows
    $('#tbl-history').on('uncheck-all.bs.table', function () {
        toggle_select_button();
    });

    $('#tbl-history').on('load-success.bs.table', function () {
        toggle_select_button();
    });


    // "Delete all selected" button is clicked
    $('#btn-delete-multi').on('click', function() {
        console.log("Delete all selected button clicked!");
        if ($("#tbl-history").bootstrapTable("getSelections").length === 0) {
            alert("Please select at least one delivery.");
            toggle_select_button();
            return;
        }
        var selected_job_uuids = $.map($("#tbl-history").bootstrapTable('getSelections'), function (row) {
            return row.job_uuid
        });
        delete_job_function(selected_job_uuids.join(","));
    })

    // Start the timer to auto-refresh status of running jobs. Check for updates every 5 seconds.
    toggle_select_button();
});
