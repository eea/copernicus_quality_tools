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

function run_process() {

    $('#modal-spinner').modal('show');
    var data = {
        "tools": JSON.stringify(tools_sequence),
        "name": $("#run_name").val(),
        "description": $("#run_description").val()
    };

    $.post("/processing/run", data, function(result, textStatus) {
        $('#modal-spinner').modal('hide');
        if (result.status=="OK") {
            var dlg_ok = BootstrapDialog.show({title: 'Process is successfully triggered', message: result.message, buttons: [{label: 'OK', cssClass: 'btn-default', action: function(dialog) {dialog.close();}}]});
        } else {
            var dlg_err = BootstrapDialog.show({title: 'Error', message: result.message, buttons: [{label: 'OK', cssClass: 'btn-default', action: function(dialog) {dialog.close();}}]});
        }
    }, "json");

}
