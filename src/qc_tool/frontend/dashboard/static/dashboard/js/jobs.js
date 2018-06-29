function format_rows() {
    // adding colors to table rows
    console.log('format_rows')
    $ ('tbody tr').each(function() {
        if($(this).find('td:last').text() === 'PASSED') {
            $(this).find('td').addClass('success');
        } else if ($(this).find('td:last').text() === 'FAILED'){
            $(this).find('td').addClass('danger');
        }
    });
}

$('#tbl-runs').bootstrapTable({
    cache: false,
    striped: true,
    search: true,
    pagination: true,
    showColumns: true,
    sortName: 'name',
    sortOrder: 'desc',
    url: "data/jobs",
    pageSize: 20,
    pageList: [20, 50, 100, 500],
    onPageChange: function() {
        format_rows();
    },
    onLoadSuccess: function() {
        format_rows
    },
    onSort: function() {
        console.log('onSort')
        format_rows();
    }
});

function actionsFormatter(value, row) {
    return "<a class=\"btn btn-xs btn-success glyphicon glyphicon-ok\"></a>";
}

function checkingDetailFormatter(value, row, index) {
    return [
            '<a class="like" href="', "/result/", value, '" title="Show results">',
                value,
            '</a>'].join('');
}