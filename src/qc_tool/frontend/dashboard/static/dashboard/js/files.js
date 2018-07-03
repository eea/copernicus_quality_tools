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
    var btn_data = '<a class="btn btn-sm btn-success" role="button" data-toggle="tooltip" title="Run quality controls for this file." href="' + start_job_url + '" ' + '>QC</a>' //" class="btn btn-sm btn-success" role="button"><span class="glyphicon glyphicon-cog" aria-hidden="true"></span>QC</a><button class="btn btn-sm btn-default" disabled>Del</button><button class="btn btn-sm btn-default" disabled>Submit to EEA</button>";
    btn_data += " <button class=\"btn btn-sm btn-default \" disabled>Del</button>";
    btn_data += " <button class=\"btn btn-sm btn-default \" disabled>Submit to EEA</button>";
    return btn_data;
}

function statusFormatter(value, row, index) {
    var uuid = row["last_job_uuid"];
    console.log(uuid);

    // special formatting failed --> NOT OK, value --> OK
    if (value == "failed") {
        value = "NOT OK"
    } else if (value == "ok") {
        value = "OK"
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

$(document).ready(function(){
    $('[data-toggle="tooltip"]').tooltip();
});
