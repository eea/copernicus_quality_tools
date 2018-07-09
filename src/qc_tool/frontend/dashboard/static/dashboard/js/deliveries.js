$('#tbl-files').bootstrapTable({
    cache: false,
    striped: true,
    search: true,
    pagination: true,
    showColumns: true,
    sortName: 'name',
    sortOrder: 'desc',
    url: "/data/files/",
    pageSize: 20,
    pageList: [20, 50, 100, 500],
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
   return moment(value).format('YYYY-MM-DD HH:mm:ss');
}

function actionsFormatter(value, row) {
    // for example /start_job/clc/guest/clc2012_cz.zip
    var start_job_url = '/start_job/' + row.product_ident + '/' + row.filename + '/';
    var btn_data = '<div class="btn-group">';

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
        // job is not running --> QC button enabled
        btn_data += '<a class="btn btn-sm btn-success" role="button" data-toggle="tooltip" ';
        btn_data += 'title="Run quality controls for this delivery." href="' + start_job_url + '" ' + '>QC</a>';
        btn_data += '<button onclick="delete_function(' + row.id + ', \'' + row.filename + '\')" ';
        btn_data += 'class="btn btn-sm btn-danger delete-button" data-toggle="tooltip" title="Delete this delivery.">';
        btn_data += 'Delete</button>';
        //data-toggle="modal" data-target="#confirm-delete">Delete</button>';
    }

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
    //console.log("statusFormatter");
    var uuid = row["last_job_uuid"];
    // special formatting failed --> NOT OK, value --> OK
    if (value == "failed") {
        value = "checks failed";
    } else if (value == "ok") {
        value = "checks passed"
    } else if (value == "error") {
        value = "error";
    }

    if (uuid) {
        return ['<a class="like" href="',
                "/result/",
                uuid,
                '" title="Show results">',
                value,
                '</a>'].join('');
    } else {
        return 'Not checked'
    }
}

function statusCellStyle(value, row, index) {

    if (value == "failed" || value == "error" || value == "NOT OK") {
        return { classes: "danger" }
    }
    return {};
}


function delete_function(id, filename) {
    console.log("clicked delete!");
        var dlg_ok = BootstrapDialog.show({
            type: BootstrapDialog.TYPE_DANGER,
            title: "Are you sure you want to delete the delivery ZIP file?",
            message: filename,
            buttons: [{
                label: "Yes",
                cssClass: "btn-default",
                action: function(dialog) {
                    console.log("user confirmed delete.");

                    data = {"id": id, "filename": filename};
                    $.ajax({
                        type: "POST",
                        url: "/delivery/delete/",
                        data: data,
                        dataType: "json",
                        success: function(result) {
                            console.log("file deleted successfully!") ;
                            $('#tbl-files').bootstrapTable('refresh');
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
                            $('#tbl-files').bootstrapTable('refresh');
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
