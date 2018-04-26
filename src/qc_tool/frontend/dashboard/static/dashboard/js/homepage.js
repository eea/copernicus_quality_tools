$(document).ready(function() {

    $.getJSON("files", function(obj) {

        var filepaths = obj.files;

        for (var i=0;i<filepaths.length;i++){
           $('<option/>').val(filepaths[i]).html(filepaths[i]).appendTo('#select_file');
        }
    });

    $.getJSON("product_types", function(obj) {

        var prods = obj.product_types;

        var options = '';
        $.each(prods, function(key, value){
            options += '<option value=' + key + '>' + value + '</option>';
        });
        document.getElementById("select_product_type").options.length = 0;
        document.getElementById("select_product_type").innerHTML = options;
    });

    // when product type is changed
    $( "#select_product_type" ).change(function() {
        //populate product type info
        var optionSelected = $("option:selected", this);
        var valueSelected = this.value;
        var detail_url = "product_type_details/" + valueSelected;
        console.log(detail_url);
        $.getJSON(detail_url , function(obj) {
            var checks = obj.product_type.checks
            $("#tbl_check_details > tbody").html("");
            var tbody = ''
            for (var i=0;i<checks.length;i++){
                tbody += "<tr><td>" + checks[i].check_ident + "</td>" + "<td></td>";
                var check_params = checks[i].parameters;
                console.log(check_params);
                if (check_params) {
                    var param_values = "";
                    var num_params = 0;
                    $.each(check_params, function(key, value) {
                        if (num_params > 0) {
                            param_values += ", ";
                        }
                        param_values += key + ": " + value;
                        num_params += 1;
                    });

                    console.log(param_values);
                    tbody += "<td>" + param_values + "</td>";
                } else {
                    tbody += "<td></td>";
                }
                tbody += "<td>" + checks[i].required + "</td>";
                tbody += "<td><input type=\"checkbox\" checked";
                if (checks[i].required) {
                    tbody += " disabled";
                }
                tbody += "></td></tr>";
                //console.log(checks[i].check_ident);
            }
            //console.log(tbody);
            $("#tbl_check_details > tbody").html(tbody);
        });
    });

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
