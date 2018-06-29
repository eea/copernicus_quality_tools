$(document).ready(function() {

    $("#tbl_check_details").hide();
    $("#product_type_link").hide();

    // retrieve list of files (this will go away..)
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

    // retrieve list of available product types (--> need to pre-select product type)
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
        run_checks();
    });

});


// when product type is changed
$( "#select_product_type" ).change(function() {
    //populate product type info
    var optionSelected = $("option:selected", this);
    var valueSelected = this.value;
    var detail_url = "data/product/" + valueSelected + "/";
    $.getJSON(detail_url , function(obj) {
        var checks = obj.job_status.checks
        $("#tbl_check_details > tbody").html("");
        var tbody = ""
        for (var i=0;i<checks.length;i++){
            tbody += "<tr>";
            tbody += "<td>" + checks[i].check_ident + "</td>";
            tbody += "<td>" + checks[i].description + "</td>";
            if(checks[i].system) {
                tbody += "<td></td>"
            } else {
                tbody += "<td><input name=\"selected_checks[]\" type=\"checkbox\" value=\"" + checks[i].check_ident + "\" checked";
                if (checks[i].required) {
                    tbody += " disabled";
                }
                tbody += "></td>";
            }
            tbody += "</tr>";
        }
        $("#tbl_check_details > tbody").html(tbody);

        //show table if hidden
        if($("#tbl_check_details").is(":hidden")){
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

    $('#modal-spinner').modal('show');

    var run_url = "/run_wps_execute";

    // retrieve the checkboxes
    var selected_checks = [];
    $ ('tbody tr').each(function() {
        var checkbox = $(this).find('input');
        is_checked = checkbox.prop('checked');
        is_disabled = checkbox.prop('disabled');
        if (!is_disabled && is_checked) {
            selected_checks.push(checkbox.val());
        }
    });

    var data = {
        "product_type_name": $("#select_product_type").val(),
        "filepath": $("#select_file").val(),
        "optional_check_idents": selected_checks.join(",")
    };

    $.ajax({
        type: "POST",
        url: run_url,
        data: data,
        dataType: "json",
        success: function(result) {
            $("#modal-spinner").modal("hide");

            if (result.status=="OK") {
                var dlg_ok = BootstrapDialog.show({
                    title: "QC Job is successfully triggered",
                    message: result.message,
                    buttons: [{
                        label: "OK",
                        cssClass: "btn-default",
                        action: function(dialog) {
                            // If the user click OK, then redirect to main page.
                            $(location).attr("href","/");
                        }
                    }]
                });

            } else {
                var dlg_err = BootstrapDialog.show({
                    title: "Error",
                    message: result.message,
                    buttons: [{
                        label: "OK",
                        cssClass: "btn-default",
                        action: function(dialog) {dialog.close();}
                    }]
                });
            }
        }
    });
}