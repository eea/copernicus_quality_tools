
// Populate content of deliveries table from /data/delivery/list/ URL.
$('#tbl-history').bootstrapTable({
    cache: false,
    striped: true,
    search: true,
    pagination: true,
    showColumns: true,
    sortName: 'name',
    sortOrder: 'desc',
    url: job_history_url,
    pageSize: 20,
    pageList: [20, 50, 100, 500],
    formatNoMatches: function () {
        return 'No job history available.';
    }
});

var deleteJobsEnabled = (
    typeof can_delete_jobs !== 'undefined' && can_delete_jobs
);

function dateFormatter(value, row) {
   if (value) {
        return moment.utc(value).local().format('YYYY-MM-DD HH:mm:ss');
   } else {
        return null;
   }
}


function textDialogMessage(value) {
    return $('<div>').text(String(value));
}


function jobListDialogMessage(jobUuids) {
    var values = String(jobUuids).split(',').slice(0, 10);
    var $message = $('<div>');
    values.forEach(function (value) {
        $('<div>').text(value).appendTo($message);
    });
    var total = String(jobUuids).split(',').length;
    if (total > values.length) {
        $('<div>').text('...and ' + (total - values.length) + ' others.').appendTo($message);
    }
    return $message;
}

function delete_job_function(job_uuids) {
    var msg_title = "Are you sure you want to delete the job history?";

    // number of jobs to delete
    var num_jobs = job_uuids.toString().split(",").length;

    if (num_jobs > 1) {
        msg_title = "Are you sure you want to delete " + num_jobs + " job history logs?";
    }
    var dlg_ok = BootstrapDialog.show({
        type: BootstrapDialog.TYPE_DANGER,
        title: msg_title,
        message: jobListDialogMessage(job_uuids),
        buttons: [{
            label: "Yes",
            cssClass: "btn-default",
            action: function(dialog) {
                data = {"uuids": job_uuids};
                $.ajax({
                    type: "POST",
                    url: job_delete_url,
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        if (result.status === "error") {
                            var dlg_err = BootstrapDialog.show({
                                type: BootstrapDialog.TYPE_WARNING,
                                title: "Cannot delete jobs.",
                                message: textDialogMessage(
                                    "Error deleting job history. " + result.message
                                ),
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


function statusFormatter(value, row, index) {
    var resultUrl = job_result_url_template.replace(
        job_uuid_url_placeholder,
        encodeURIComponent(String(row.job_uuid))
    );
    return $('<a>', {
        'class': 'like',
        'href': resultUrl,
        'title': 'Show results',
        'text': String(value)
    }).prop('outerHTML');
}


// Enable or disable 'QC all selected' button based on selected rows
function toggle_select_button() {
    if (!deleteJobsEnabled) {
        return;
    }
    var numChecked = $("#tbl-history").bootstrapTable("getSelections").length;
    if (numChecked === 0) {
        $("#btn-delete-multi").text("Delete all selected");
        $("#btn-delete-multi").prop("disabled", true);
    } else {
        $("#btn-delete-multi").text("Delete all selected (" + numChecked + ")");
        $("#btn-delete-multi").prop("disabled", false);
    }
}


$(document).ready(function() {

    // Set defult tooltip in each table row.
    $('[data-toggle="tooltip"]').tooltip();

    if (deleteJobsEnabled) {
        // check one row
        $('#tbl-history').on('check.bs.table', function () {
            toggle_select_button();
        });

        // check all rows
        $('#tbl-history').on('check-all.bs.table', function () {
            toggle_select_button();
        });

        // uncheck one row
        $('#tbl-history').on('uncheck.bs.table', function () {
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
                return row.job_uuid;
            });
            delete_job_function(selected_job_uuids.join(","));
        });

        toggle_select_button();
    }

});
