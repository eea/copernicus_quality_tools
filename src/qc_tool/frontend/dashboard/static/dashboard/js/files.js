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

function actionsFormatter(value, row) {
    // for example /start_job/clc/guest/clc2012_cz.zip
    var start_job_url = '/start_job/' + row.product_ident + '/' + row.filename + '/';
    var btn_data = '<a class="btn btn-sm btn-success" role="button" href="' + start_job_url + '">QC</a>' //" class="btn btn-sm btn-success" role="button"><span class="glyphicon glyphicon-cog" aria-hidden="true"></span>QC</a><button class="btn btn-sm btn-default" disabled>Del</button><button class="btn btn-sm btn-default" disabled>Submit to EEA</button>";
    btn_data += " <button class=\"btn btn-sm btn-default \" disabled>Del</button>";
    btn_data += " <button class=\"btn btn-sm btn-default \" disabled>Submit to EEA</button>";
    return btn_data;
}