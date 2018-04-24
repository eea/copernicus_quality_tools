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
    url: "/checking_tasks.json",
    pageSize: 20,
    pageList: [20, 50, 100, 500],
    onLoadSuccess: function() {
        console.log('load success!')
        //$('tbody tr').append('<td><a href="#" class="btn btn-info btn-xs"><i class="fa fa-pencil"></i> RUN </a></td>');
    }
});

function run_process() {

    $('#modal-spinner').modal('show');
    var data = {
        "product_type_name": $("#select_product").val(),
        "filepath": $("#select_file").val(),
        "layer_name": $("#select_layer").val()
    };

    var product_type_name = $("#select_product").val();
    var filepath = $("#select_file").val();
    var layer_name = $("#select_layer").val();

    var run_url = "/run_wps_execute?product_type_name=" + product_type_name + "&filepath=" + filepath + "&layer_name=" + layer_name;

    var wps_base = "http://192.168.2.72:5000/wps?service=WPS&version=1.0.0&request=Execute&identifier=cop_sleep";
    var wps_url = wps_base + "&DataInputs=delay=1.3;cycles=10;exit_ok=true;filepath=/home/bum/bac;layer_name=my_layer;product_type_name=big_product&lineage=true&status=true&storeExecuteResponse=true"

    $.ajax({
        type: 'POST',
        url: run_url,
        data: data,
        dataType: 'json',
        success: function(result) {
            console.log(result);
            $('#modal-spinner').modal('hide');

            if (result.status=="OK") {
                var dlg_ok = BootstrapDialog.show({title: 'Checking Task is successfully triggered', message: result.message, buttons: [{label: 'OK', cssClass: 'btn-default', action: function(dialog) {dialog.close();}}]});
            } else {
                var dlg_err = BootstrapDialog.show({title: 'Error', message: result.message, buttons: [{label: 'OK', cssClass: 'btn-default', action: function(dialog) {dialog.close();}}]});
            }
        }
    });
}
