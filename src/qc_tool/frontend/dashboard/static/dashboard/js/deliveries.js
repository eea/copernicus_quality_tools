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

function actionsFormatter(value, row) {
    // for example /start_job/clc/guest/clc2012_cz.zip
    var start_job_url = '/start_job/' + row.product_ident + '/' + row.filename + '/';
    var btn_data = '<div class="btn-group">';

    // EEA submit button is not shown in case of a local service provider installation.
    var show_eea_button = row.eea_installation;

    if (row.qc_status === "running" || row.is_submitted) {
        // job is running --> QC button disabled, Delete button disabled
        var tooltip_message = "QC checks are currently running.";
        if (row.is_submitted) {
            tooltip_message = "Delivery has already been submitted to EEA.";
        }
        btn_data += "<a class=\"btn btn-sm btn-success\" role=\"button\" disabled data-toggle=\"tooltip\"";
        btn_data += 'title="Cannot run quality controls for this delivery. ' + tooltip_message;
        btn_data += '" href="' + start_job_url + '" ' + '>QC</a>';
        btn_data += ' <button class="btn btn-sm btn-default" data-toggle="tooltip" ';
        btn_data += 'title="Cannot delete this delivery. ' + tooltip_message + '" disabled>Delete</button>';
    } else {
        // job is not running and delivery is not submitted --> QC button is enabled
        btn_data += '<a class="btn btn-sm btn-success" role="button" data-toggle="tooltip" ';
        btn_data += 'title="Run quality controls for this delivery." href="' + start_job_url + '" ' + '>QC</a>';
        btn_data += '<button onclick="delete_function(' + row.id + ', \'' + row.filename + '\')" ';
        btn_data += 'class="btn btn-sm btn-danger delete-button" data-toggle="tooltip" title="Delete this delivery.">';
        btn_data += 'Delete</button>';
    }

    if (show_eea_button) {
        if (row.is_submitted) {
            btn_data += ' <button class="btn btn-sm btn-default disabled data-toggle="tooltip" ';
            btn_data += 'title="Delivery has already been submitted to EEA.">Submit to EEA</button>';
        } else {
            if (row.qc_status === "ok") {
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

function submittedFormatter(value, row, index) {
    if (!value) {
        return "No";
    } else {
        return "Yes";
    }
}

function statusFormatter(value, row, index) {

    var uuid = row["last_job_uuid"];

    if (value == "failed") {
        value = "checks failed";
    }
    if (value == "running") {
        value = "running (" + row.percent + "% )"
    }
    if (value == "ok") {
        if (row["is_submitted"]) {
            value = "submitted";
        } else {
            value = "checks passed";
        }
    }

    if (uuid) {
        return ['<a class="like" href="',
                "/result/",
                uuid,
                '" title="Show results">',
                value,
                '</a>'].join('');
    } else {
        return 'Not checked';
    }
}

function statusCellStyle(value, row, index) {

    if (value == "ok") {
        return { classes: "success"}
    }
    if (value == "failed" || value == "error" || value == "NOT OK") {
        return { classes: "danger" }
    }
    return {};
}


function delete_function(id, filename) {
    var dlg_ok = BootstrapDialog.show({
        type: BootstrapDialog.TYPE_DANGER,
        title: "Are you sure you want to delete the delivery ZIP file?",
        message: filename,
        buttons: [{
            label: "Yes",
            cssClass: "btn-default",
            action: function(dialog) {
                data = {"id": id, "filename": filename};
                $.ajax({
                    type: "POST",
                    url: "/delivery/delete/",
                    data: data,
                    dataType: "json",
                    success: function(result) {
                        $('#tbl-deliveries').bootstrapTable('refresh');
                        dialog.close();
                    },
                    error: function(result)  { console.log("error deleting file!") ;  }
                })
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
                            console.log("file marked successfully for submission to EEA!") ;
                            $('#tbl-deliveries').bootstrapTable('refresh');
                            dialog.close();
                        },
                        error: function(result)  { console.log("error submitting file to EEA!") ;  }
                    })
                }
            }, {
                label: "No",
                cssClass: "btn-default",
                action: function(dialog) {dialog.close();}
            }]
        });
}

$(document).ready(function(){
    $('[data-toggle="tooltip"]').tooltip();
});
