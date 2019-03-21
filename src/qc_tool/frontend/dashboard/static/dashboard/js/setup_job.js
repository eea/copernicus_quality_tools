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
    var detail_url = "/data/job_info/" + product_ident + "/";
    $.getJSON(detail_url , function(obj) {
        var steps = obj.job_result.steps
        $("#tbl_check_details > tbody").html("");
        $("#error_placeholder").html("");
        var tbody = ""
        for (var i = 0; i < steps.length; i++) {

            var check_ident = steps[i].check_ident;
            if (check_ident.startsWith("qc_tool.")) {
                check_ident = check_ident.substring(8);
            }
            if (!steps[i].system) { // Steps with system check are not shown.
                tbody += "<tr>";
                tbody += "<td>" + steps[i].step_nr + "</td>";
                tbody += "<td>" + check_ident + "</td>";
                tbody += "<td>" + steps[i].description + "</td>";
                if (steps[i].layers) {
                    tbody += "<td>" + steps[i].layers.join(", ") + "</td>";
                } else {
                    tbody += "<td></td>";
                }
                tbody += '<td><input name="selected_steps[]" type="checkbox" value="' + steps[i].step_nr + '" checked';
                if (steps[i].required) { // Required steps have checkbox disabled.
                    tbody += " disabled";
                }
                tbody += "></td>";
                tbody += "</tr>";
            }
        }

        // add html content to the table with checkboxes.
        $("#tbl_check_details > tbody").html(tbody);

        //show table if hidden
        if($("#tbl_check_details").is(":hidden")){
            $("#tbl_check_details").show();
        }

        // Update link to product definition.
        $("#product_link_placeholder").html(
        '<a href="/data/product_definition/' + product_ident + '/">Product Definition</a>');

        // enable Run QC button
        $("#btn_run").prop("disabled", false);

        //listen to checkbox events
        toggle_select_buttons();
        $(":checkbox").change(function() {
            toggle_select_buttons();
        })
    })
    .fail(function() {
        $("#tbl_check_details").hide();
        $("#tbl_check_details > tbody").html("");
        var product_error_msg = 'Error in configuration of <strong>' + product_ident + '</strong> product!'
        $("#error_placeholder").html('<div class="alert alert-danger">' + product_error_msg + '</div>');
        // Update link to product definition.
        $("#product_link_placeholder").html(
        '<a href="/data/product_definition/' + product_ident + '/">Show Product Definition</a>');
    });
}


$(document).ready(function() {

    $("#tbl_check_details").hide();
    var selected_product_ident = document.getElementById("preselected_product").value;
    if (selected_product_ident != "None") {
        display_product_info(selected_product_ident);
        $("#tbl_check_details").show();
    } else {
        $("#tbl_check_details").hide();
        $("#tbl_check_details > tbody").html("");
        $("#product_link_placeholder").html("");
        $("#btn_run").prop("disabled", true);
    }

    // When user clicks the "Launch QA session" button.
    $('#check_form').submit(function(event){
        event.preventDefault();
        create_job();
    });

    $('#select_product').change(function() {
        //populate product info based on selected product ident.
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


function create_job() {

    $('#modal-spinner').modal('show');

    // retrieve the checkboxes from tbl_check_details table.
    var unselected_steps = [];
    $ ("#tbl_check_details tbody tr").each(function() {

        // search for unchecked checkbox in the table row
        var checkbox = $(this).find('input:checkbox');

        if (checkbox.length == 0) {
            console.log("could not find any checkboxes in the current row.");
        } else {
            if (!checkbox.prop('checked')) {
                unselected_steps.push(checkbox.val());
            }
        }
    });

    var data = {
        "delivery_ids": $("#delivery_ids").val(),
        "product_ident": $("#select_product").val(),
        "skip_steps": unselected_steps.join(",")
    };

    $.ajax({
        type: "POST",
        url: "/create_job",
        data: data,
        dataType: "json",
        success: function(result) {
            $("#modal-spinner").modal("hide");
            var msg_title = "QC Job has been added to queue.";
            if (result.num_created > 1) {
                msg_title = result.num_created + " QC jobs have been added to queue.";
            }
            var dlg_ok = BootstrapDialog.show({
                title: msg_title,
                message: result.message,
                buttons: [{
                    label: "OK",
                    cssClass: "btn-default",
                    action: function(dialog) {
                        // If the user click OK, then redirect to jobs page for now.
                        $(location).attr("href","/");
                    }
                }]
            });
        },
        error: function(result) {
            $("#modal-spinner").modal("hide");
            var dlg_err = BootstrapDialog.show({
                title: "Error",
                message: "Error running job. Please try later.",
                buttons: [{
                    label: "OK",
                    cssClass: "btn-default",
                    action: function(dialog) {dialog.close();}
                }]
            });
        }
    });
}
