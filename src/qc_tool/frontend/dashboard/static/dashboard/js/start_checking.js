$(document).ready(function() {

    $("#tbl_check_details").hide();
    $("#product_type_link").hide();

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

    $.getJSON("data/product_list/", function(obj) {

        var prods = obj.product_list;

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
    var detail_url = "data/product/" + valueSelected + "/";
    console.log(detail_url);
    $.getJSON(detail_url , function(obj) {
        var checks = obj.product_info.checks
        $("#tbl_check_details > tbody").html("");
        var tbody = ''
        for (var i=0;i<checks.length;i++){
            tbody += "<tr><td>" + checks[i].check_ident + "</td>" + "<td>" + checks[i].description + "</td>";
            tbody += "<td>" + checks[i].required + "</td>";
            tbody += "<td><input name=\"selected_checks[]\" type=\"checkbox\" value=\"" + checks[i].check_ident + "\" checked";
            if (checks[i].required) {
                tbody += " disabled";
            }
            tbody += "></td></tr>";
        }
        $("#tbl_check_details > tbody").html(tbody);

        //show table if hidden
        if($("#tbl_check_details").is(':hidden')){
            $("#tbl_check_details").show();
        }

        //show json product type config file link if hidden
        $("#product_type_link").attr("href", "data/product_type/" + valueSelected + "/");
        if($("#product_type_link").is(':hidden')){
            $("#product_type_link").show();
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