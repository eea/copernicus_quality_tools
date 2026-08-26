$('#tbl-boundaries-raster').bootstrapTable({
    cache: false,
    striped: false,
    search: false,
    pagination: false,
    showColumns: false,
    sortName: 'filename',
    sortOrder: 'asc',
    url: $('#tbl-boundaries-raster').data('url'),
    escape: true,
    pageSize: 20,
    pageList: [20, 50, 100, 500],
    formatNoMatches: function () {
        return $('#tbl-boundaries-raster').data('empty-message');
    }
});

$('#tbl-boundaries-vector').bootstrapTable({
    cache: false,
    striped: false,
    search: false,
    pagination: false,
    showColumns: false,
    sortName: 'filename',
    sortOrder: 'asc',
    url: $('#tbl-boundaries-vector').data('url'),
    escape: true,
    pageSize: 20,
    pageList: [20, 50, 100, 500],
    formatNoMatches: function () {
        return $('#tbl-boundaries-vector').data('empty-message');
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
