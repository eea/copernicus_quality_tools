function display_product_info(product_ident) {
    var detail_url = "/data/product/" + product_ident + "/";
    $.getJSON(detail_url , function(obj) {
        var checks = obj.job_status.checks
        $("#tbl_check_details > tbody").html("");
        var tbody = ""
        for (var i=0;i<checks.length;i++){
            
            if(!checks[i].system) { // system checks are not shown
                tbody += "<tr>";
                tbody += "<td>" + checks[i].check_ident + "</td>";
                tbody += "<td>" + checks[i].description + "</td>";
                tbody += '<td><input name="selected_checks[]" type="checkbox" value="' + checks[i].check_ident + '" checked';
                if (checks[i].required) { // Required checks have a disabled checkbox that cannot be unchecked.
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
        $("#product_type_link").attr("href", "/data/product_config/" + product_ident + "/");
        if($("#product_type_link").is(':hidden')){
            $("#product_type_link").show();
        }
    });
}


$(document).ready(function() {

    $("#tbl_check_details").hide();
    $("#product_type_link").hide();

    var selected_product_ident = document.getElementById("preselected_product").value;

    // retrieve list of available product types (product is pre-selected from url parameter)
    $.getJSON("/data/product_list/", function(obj) {

        var selected_product_exists = false;
        var prods = obj.product_list;

        var options = '';
        options += '<option hidden >Select product type ...</option>';
        for (var i=0;i<prods.length;i++){
            if(prods[i].name === selected_product_ident) {
                options += '<option value=' + prods[i].name + ' selected>' + prods[i].description + '</option>';
                selected_product_exists = true;
            } else {
                options += '<option value=' + prods[i].name + '>' + prods[i].description + '</option>';
            }
        }
        document.getElementById("select_product_type").options.length = 0;
        document.getElementById("select_product_type").innerHTML = options;

        // display checks for pre-selected product type
        if (selected_product_exists) {
            display_product_info(selected_product_ident);
        }
    });


    $('#check_form').submit(function(event){
        event.preventDefault();
        run_checks();
    });


    // When product type is changed in the dropdown, update product detail info.
    $('#select_product_type').change(function() {
        //populate product type info
        var optionSelected = $("option:selected", this);
        display_product_info(this.value);
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
        "filepath": $("#current_username").val() + "/" + $("#preselected_file").val(),
        "optional_check_idents": selected_checks.join(",")
    };
    console.log(data);

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
                            console.log(result);
                            // If the user click OK, then redirect to jobs page for now.
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
        },
        error: function(result) {
            $("#modal-spinner").modal("hide");
            var dlg_err = BootstrapDialog.show({
                title: "Error",
                message: "WPS server probably does not respond. Please try later.",
                buttons: [{
                    label: "OK",
                    cssClass: "btn-default",
                    action: function(dialog) {dialog.close();}
                }]
            });
        }
    });
}