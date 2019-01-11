function toggle_select_buttons() {
    var num_enabled_checked = 0;
    var num_enabled_unchecked = 0;
    var num_enabled = 0;

    $(":checkbox").each(function(index) {
        if(!$(this).prop('disabled')) {
            num_enabled += 1;
            if($(this).prop("checked")) {
                num_enabled_checked += 1;
            } else {
                num_enabled_unchecked += 1;
            }
        }
    });

    if(num_enabled_checked === num_enabled) {
        $("#btn_select_all").prop("disabled", true);
    } else {
        $("#btn_select_all").prop("disabled", false);
    }
    if(num_enabled_unchecked === num_enabled) {
        $("#btn_unselect_all").prop("disabled", true);
    } else {
        $("#btn_unselect_all").prop("disabled", false);
    }
}


function display_product_info(product_ident) {
    var detail_url = "/data/product/" + product_ident + "/";
    $.getJSON(detail_url , function(obj) {
        var checks = obj.job_status.checks
        $("#tbl_check_details > tbody").html("");
        $("#error_placeholder").html("");
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
        //$("#runs-bar").removeClass("hidden");

        // show json product type config file link if hidden
        $("#product_link").attr("href", "/data/product_config/" + product_ident + "/");
        if($("#product_link").is(':hidden')){
            $("#product_link").show();
        }

        //listen to checkbox events
        toggle_select_buttons();
        $(":checkbox").change(function() {
            console.log("checkbox change");
            toggle_select_buttons();
        })
    })
    .fail(function() {
        $("#tbl_check_details").hide();
        $("#tbl_check_details > tbody").html("");
        var product_error_msg = 'Error in configuration of <strong>' + product_ident + '</strong> product!'
        $("#error_placeholder").html('<div class="alert alert-danger">' + product_error_msg + '</div>');
        // show json product type config file link if hidden
        $("#product_link").attr("href", "/data/product_config/" + product_ident + "/");
        if($("#product_link").is(':hidden')){
            $("#product_link").show();
        }
    });
}


$(document).ready(function() {

    $("#tbl_check_details").hide();
    $("#product_link").hide();

    var selected_product_ident = document.getElementById("preselected_product").value;

    $('#check_form').submit(function(event){
        event.preventDefault();
        run_checks();
    });

    // When product type is changed in the dropdown, update product detail info.
    $('#select_product').change(function() {
        //populate product type info
        var optionSelected = $("option:selected", this);
        display_product_info(this.value);
    });
});


function unselect_all() {
    $(":checkbox").each(function(index) {
        if(!$(this).prop('disabled')) {
            $(this).prop("checked", false);
        }
    });
    toggle_select_buttons();
}

function select_all() {
    $(":checkbox").each(function(index) {
        if(!$(this).prop('disabled')) {
            $(this).prop("checked", true);
        }
    });
    toggle_select_buttons();
}


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
        "product_ident": $("#select_product").val(),
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
                    title: "QC Job successfully started",
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