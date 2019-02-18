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
        return moment(value).format('YYYY-MM-DD HH:mm:ss');
   } else {
        return null;
   }
}


function actionsFormatter(value, row) {
    // for example /start_job/1234/
    var start_job_url = '/start_job/' + row.id + '/';
    var btn_data = '<div class="btn-group">';
    var show_eea_button = row.eea_installation;

    if (row.qc_status === "file_not_found") {
        // file not found --> QC button disabled, Delete button enabled
        btn_data += "<a class=\"btn btn-sm btn-success\" role=\"button\" disabled data-toggle=\"tooltip\"";
        btn_data += 'title="Cannot run quality controls for this delivery. delivery ZIP file not found.';
        btn_data += '" href="' + start_job_url + '" ' + '>QC</a>';
        btn_data += '<button onclick="delete_function(' + row.id + ', \'' + row.filename + '\')" ';
        btn_data += 'class="btn btn-sm btn-danger delete-button" data-toggle="tooltip" title="Delete this delivery.">';
        btn_data += 'Delete</button>';

    } else if (row.qc_status === "running" || row.is_submitted) {
        // job is running --> QC button disabled, Delete button disabled
        var tooltip_message = "QC job is currently running.";
        if (row.is_submitted) {
            tooltip_message = "Delivery has been already submitted to EEA.";
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

    // "Submit to EEA" button visibility is controlled by the SUBMISSION_ENABLED setting.
    if (row.submission_enabled) {
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
    if (value == "file_not_found") {
        value = '<span class="glyphicon glyphicon-exclamation-sign" aria-hidden="true"> </span>';
        value += '<span class="text-danger">FILE NOT FOUND</span>';
        return value;
    }
    if (!uuid) {
        return 'Not checked';
    }
    if (value == "failed") {
        // Do nothing.
    } else if (value == "accepted" || value == "running") {
        if(row.percent == null) {
            value = "running (0 %)";
        } else {
            value = "running (" + row.percent + "% )";
        }
    } else if (value == "ok") {
        if (row["is_submitted"]) {
            value = "submitted";
        } else {
            value = "passed";
        }
    }

    return ['<a class="like" href="',
            "/result/", uuid, "/", row.product_ident,
            '" title="Show results">',
            value,
            '</a>'].join('');
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
                    error: function(result)  { q("error deleting file!") ;  }
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

function update_job_statuses() {
    // find deliveries with 'running' status
    $("a").each(function() {
        if($(this).text().startsWith("running") || $(this).text().startsWith("waiting")) {
            var hyperlink = $(this);

            // extract job_uuid from the hyperlink /result/<job_uuid>/<product_ident>/
            var url_parts = hyperlink.attr("href").split("/");
            var product_ident = url_parts[url_parts.length - 1];
            var job_uuid = url_parts[url_parts.length - 2];

            $.ajax({
                type:"get",
                url:"/delivery/update_job_status/" + job_uuid + "/",
                datatype:"json",
                success:function(data)
                {
                    // get row index
                    var row = hyperlink.parent().parent();

                    var index = row.attr("data-index");
                    var rowData = $("#tbl-deliveries").bootstrapTable('getData')[index];

                    // update QC status of the row.
                    if (rowData) {
                        rowData.last_job_uuid = job_uuid;
                        rowData.qc_status = data.job_status;
                        rowData.last_job_status = data.job_status;
                        rowData.percent = data.percent;
                        rowData.is_submitted = data.is_submitted;
			            rowData.product_ident = data.product_ident;

                        // Update background colour of the status cell.
                        var newCellStyle = statusCellStyle(rowData.qc_status, rowData, index);
                        hyperlink.parent().toggleClass(newCellStyle.classes);

                        // Redraw action buttons.
                        var original_buttons = hyperlink.parent().parent().find(".btn-group");
                        var new_buttons = actionsFormatter(null, rowData);
                        original_buttons.replaceWith(new_buttons);

                        // Update content of the status cell (status and percent).
                        var new_status_cell = statusFormatter(rowData.qc_status, rowData);
                        //hyperlink.text(new_status_cell.text());
                        hyperlink.replaceWith(new_status_cell);
                    }
                }
            });
        }
    });
}

$(document).ready(function(){
    $('[data-toggle="tooltip"]').tooltip();

    // start the timer for the deliveries. Check for updates every 5 seconds.
    update_job_statuses();
    setInterval(function(){update_job_statuses();}, 5000);
});
