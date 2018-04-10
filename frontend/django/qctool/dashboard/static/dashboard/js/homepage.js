$(document).ready(function() {

});

$('#tbl-runs').bootstrapTable({
    cache: false,
    striped: true,
    search: true,
    pagination: true,
    showColumns: true,
    sortName: 'name',
    sortOrder: 'desc',
    url: "/jobs.json",
    pageSize: 20,
    pageList: [20, 50, 100, 500],
    onLoadSuccess: function() {
        console.log('load success!')
        $('tbody tr').append('<td><a href="#" class="btn btn-info btn-xs"><i class="fa fa-pencil"></i> RUN </a></td>');
    }
});
