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


function actionsFormatter(value, row) {
    //return "<a class=\"btn btn-xs btn-success glyphicon glyphicon-ok\"></a>";

    console.log(row);
    var start_job_url = '/start_job/' + row.filename + '/' + row.product_ident + '/';
    console.log(start_job_url);
    var btn_data = '<a class="btn btn-sm btn-success" role="button" href="' + start_job_url + '">QC</a>' //" class="btn btn-sm btn-success" role="button"><span class="glyphicon glyphicon-cog" aria-hidden="true"></span>QC</a><button class="btn btn-sm btn-default" disabled>Del</button><button class="btn btn-sm btn-default" disabled>Submit to EEA</button>";
    btn_data += " <button class=\"btn btn-sm btn-default \" disabled>Del</button>";
    btn_data += " <button class=\"btn btn-sm btn-default \" disabled>Submit to EEA</button>";
    return btn_data;

    //return "<button class=\"btn btn-sm btn-success \">QC</button>" +
    //       " <button class=\"btn btn-sm btn-default \" disabled>Del</button>" +
    //       " <button class=\"btn btn-sm btn-default \" disabled>Submit to EEA</button>";
}