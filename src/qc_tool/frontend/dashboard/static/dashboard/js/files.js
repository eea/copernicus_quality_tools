$('#tbl-files').bootstrapTable({
    cache: false,
    striped: true,
    search: true,
    pagination: true,
    showColumns: true,
    sortName: 'name',
    sortOrder: 'desc',
    url: "/data/files",
    pageSize: 20,
    pageList: [20, 50, 100, 500],
});


function actionsFormatter(value, row) {
    //return "<a class=\"btn btn-xs btn-success glyphicon glyphicon-ok\"></a>";
    return "<button class=\"btn btn-sm btn-success \">QC</button>" +
           " <button class=\"btn btn-sm btn-default \" disabled>Del</button>" +
           " <button class=\"btn btn-sm btn-default \" disabled>Submit to EEA</button>";
}