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
    queryParams: function(p) {
        return {
            search: p.search,
            limit: p.limit,
            offset: p.offset,
            sort: p.sort,
            order: p.order
        };
    },
    onLoadSuccess: function() {

    }
});
