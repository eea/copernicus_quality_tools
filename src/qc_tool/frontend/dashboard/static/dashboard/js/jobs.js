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

$('#tbl-jobs').bootstrapTable({
    cache: false,
    striped: true,
    search: true,
    pagination: true,
    showColumns: true,
    sortName: 'name',
    sortOrder: 'desc',
    url: "/data/jobs/" + $('#job_filename').text(),
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

function dateFormatter(value, row) {
   return moment(value).format('YYYY-MM-DD HH:mm:ss');
}

function qcListFormatter(value, row) {
    if(value) {
        return('Default (Full)')
    } else {
        return('User-defined (Partial)')
    }
}

function actionsFormatter(value, row) {
    return "<a class=\"btn btn-xs btn-success glyphicon glyphicon-ok\"></a>";
}

function jobUuidFormatter(value, row, index) {
    return [
            '<a class="like" href="', "/result/", value, '" title="Show results">',
                value,
            '</a>'].join('');
}