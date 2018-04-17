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
        "product": $("#select_product").val(),
        "filepath": $("#select_file").val(),
        "layer": $("#select_layer").val()
    };

    var wps_base = "http://192.168.2.72:5000/wps?service=WPS&version=1.0.0&request=Execute&identifier=cop_sleep";
    var wps_url = wps_base + "&DataInputs=delay=1.3;cycles=10;exit_ok=true;filepath=/home/bum/bac;layer_name=my_layer;product_type_name=big_product&lineage=true&status=true&storeExecuteResponse=true"

    $.ajax({
        type: 'GET',
        url: wps_url,
        dataType: 'xml',
        success: function(xml) {
            alert(xml);
            //$(xml).find("wps:ProcessAccepted").each(function() {
            //    var marker = $(this);
            //    alert(marker.text());
            //});
        }
    });
}
