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

    if (row.qc_status === "running" || row.submitted === "Yes") {
        // job is running --> QC button disabled, Delete button disabled
        btn_data += "<a class=\"btn btn-sm btn-success\" role=\"button\" disabled data-toggle=\"tooltip\"";
        btn_data += 'title="Cannot run quality controls for this delivery. Checks are currently running." href="' + start_job_url + '" ' + '>QC</a>';
        btn_data += ' <button class="btn btn-sm btn-default" data-toggle="tooltip" ';
        btn_data += 'title="Cannot delete this delivery. Checks are currently running." disabled>Delete</button>';
    } else {
        // job is not running --> QC button enabled
        btn_data += '<a class="btn btn-sm btn-success" role="button" data-toggle="tooltip" ';
        btn_data += 'title="Run quality controls for this delivery." href="' + start_job_url + '" ' + '>QC</a>';
        btn_data += ' <button onclick="delete_function(' + row.id + ', \'' + row.filename + '\')" class="btn btn-sm btn-danger delete-button" data-toggle="tooltip" title="Delete this delivery." data-toggle="modal" data-target="#confirm-delete">Delete</button>';
    }

    if (row.submitted === "No" && row.qc_status === "ok") {

        btn_data += ' <button class="btn btn-sm btn-default">Submit to EEA</button>';
    } else {

        btn_data += ' <button class="btn btn-sm btn-default disabled data-toggle="tooltip" title="Delivery cannot be submitted to EEA.">Submit to EEA</button>';

    }

    btn_data += '</div>';
    //console.log(btn_data);

    return btn_data;
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
                        url: "/delete_delivery/",
                        data: data,
                        dataType: "json",
                        success: function(result) {
                            console.log("file deleted successfully!") ;
                            $('#tbl-files').bootstrapTable('refresh');
                            dialog.close();
                        },
                            //$("#modal-spinner").modal("hide");
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

$(document).ready(function(){
    $('[data-toggle="tooltip"]').tooltip();
});
