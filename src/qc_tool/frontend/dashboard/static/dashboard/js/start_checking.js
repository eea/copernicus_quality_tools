$(document).ready(function() {

    $("#tbl_check_details").hide();

    $.getJSON("data/files", function(obj) {

        var filepaths = obj;

        var options = '';
        options += '<option hidden >Select file to check ...</option>';
        for (var i=0;i<filepaths.length;i++){
            options += '<option value=' + filepaths[i].filepath + '>' + filepaths[i].filepath + '</option>';
        }
        document.getElementById("select_file").options.length = 0;
        document.getElementById("select_file").innerHTML = options;
    });

    $.getJSON("product_types", function(obj) {

        var prods = obj.product_types;

        var options = '';
        options += '<option hidden >Select product type ...</option>';
        for (var i=0;i<prods.length;i++){
            options += '<option value=' + prods[i].name + '>' + prods[i].description + '</option>';
        }
        document.getElementById("select_product_type").options.length = 0;
        document.getElementById("select_product_type").innerHTML = options;
    });


    $('#check_form').submit(function(event){
        event.preventDefault();
        console.log('check form submit!');
        run_checks();
    });

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
            tbody += "<td><input name=\"selected_checks[]\" type=\"checkbox\" value=\"" + checks[i].check_ident + "\" checked";
            if (checks[i].required) {
                tbody += " disabled";
            }
            tbody += "></td></tr>";
            //console.log(checks[i].check_ident);
        }
        //console.log(tbody);
        $("#tbl_check_details > tbody").html(tbody);

        //show table if hidden
        if($("#tbl_check_details").is(':hidden')){
            $("#tbl_check_details").show();
        }
    });
});



function run_checks() {

    // run process if form is valid

    console.log("run_checks()");

    $('#modal-spinner').modal('show');

    // original call was via HTTP GET
    //var product_type_name = $("#select_product").val();
    //var filepath = $("#select_file").val();
    //var run_url = "/run_wps_execute?product_type_name=" + data.product_type_name + "&filepath=" + data.filepath;

    // the wps must called from from the django run_wps_execute function because it does not support cross-site requests
    // the following two lines show example WPS calls
    // var wps_base = "http://192.168.2.72:5000/wps?service=WPS&version=1.0.0&request=Execute&identifier=cop_sleep";
    // var wps_url = wps_base + "&DataInputs=delay=1.3;cycles=10;exit_ok=true;filepath=/home/bum/bac;layer_name=my_layer;product_type_name=big_product&lineage=true&status=true&storeExecuteResponse=true"

    var run_url = "/run_wps_execute";

    // retrieve the checkboxes
    var selected_checks = [];
    $ ('tbody tr').each(function() {
        console.log($(this).find('td:first').text());
        var checkbox = $(this).find('input');
        console.log(checkbox);
        is_checked = checkbox.is(':checked');
        if (is_checked) {
            selected_checks.push(checkbox.val());
        }
        console.log(is_checked);
    });
    console.log(selected_checks);


    var data = {
        "product_type_name": $("#select_product_type").val(),
        "filepath": $("#select_file").val(),
        "optional_check_idents": selected_checks.join(",")
    };

    $.ajax({
        type: 'POST',
        url: run_url,
        data: data,
        dataType: 'json',
        success: function(result) {
            console.log(result);
            $('#modal-spinner').modal('hide');

            if (result.status=="OK") {
                var dlg_ok = BootstrapDialog.show({
                    title: 'Checking Task is successfully triggered',
                    message: result.message,
                    buttons: [{
                        label: 'OK',
                        cssClass: 'btn-default',
                        action: function(dialog) {
                            $(location).attr('href','/');
                            //dialog.close();
                        }
                    }]
                });

            } else {
                var dlg_err = BootstrapDialog.show({title: 'Error', message: result.message, buttons: [{label: 'OK', cssClass: 'btn-default', action: function(dialog) {dialog.close();}}]});
            }
        }
    });
}