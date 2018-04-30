$('#tbl-runs').bootstrapTable({
    cache: false,
    striped: true,
    search: true,
    pagination: true,
    showColumns: true,
    sortName: 'name',
    sortOrder: 'desc',
    url: "/checking_sessions",
    pageSize: 20,
    pageList: [20, 50, 100, 500],
    onLoadSuccess: function() {
        // adding colors to table rows
        $ ('tbody tr').each(function() {
            if($(this).find('td:last').text() === 'PASSED') {
                $(this).find('td').addClass('success');
            } else if ($(this).find('td:last').text() === 'FAILED'){
                $(this).find('td').addClass('danger');
            }
        });
    }
});


function checkingDetailFormatter(value, row, index) {
    return [
            '<a class="like" href="', "result/", value, '" title="Show check results">',
                value,
            '</a>'].join('');
}