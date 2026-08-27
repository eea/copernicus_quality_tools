function toggle_select_buttons() {
    var num_enabled_checked = 0;
    var num_enabled_unchecked = 0;
    var num_enabled = 0;

    $("#tbl_check_details :checkbox").each(function() {
        if(!$(this).prop('disabled')) {
            num_enabled += 1;
            if($(this).prop("checked")) {
                num_enabled_checked += 1;
            } else {
                num_enabled_unchecked += 1;
            }
        }
    });

    $("#btn_select_all").prop(
        "disabled",
        num_enabled === 0 || num_enabled_checked === num_enabled
    );
    $("#btn_unselect_all").prop(
        "disabled",
        num_enabled === 0 || num_enabled_unchecked === num_enabled
    );
}


function configuredUrl(attributeName, placeholder, value) {
    var template = $('#tool-canvas').attr(attributeName);
    return template.replace(placeholder, encodeURIComponent(String(value)));
}


function textDialogMessage(value) {
    return $('<div>').text(String(value));
}


function updateProductDefinitionLink(productIdent, label) {
    var url = configuredUrl(
        'data-product-definition-url-template',
        '__PRODUCT__',
        productIdent
    );
    $('#product_link_placeholder').empty().append(
        $('<a>').attr('href', url).text(label)
    );
}


function display_product_info(product_ident) {
    var detail_url = configuredUrl(
        'data-job-info-url-template',
        '__PRODUCT__',
        product_ident
    );
    $.getJSON(detail_url , function(obj) {
        var steps = Array.isArray(obj.job_result.steps) ? obj.job_result.steps : [];
        var $tbody = $("#tbl_check_details > tbody").empty();
        $("#error_placeholder").empty();
        for (var i = 0; i < steps.length; i++) {
            var step = steps[i];
            var check_ident = String(step.check_ident || '');
            if (check_ident.startsWith("qc_tool.")) {
                check_ident = check_ident.substring(8);
            }
            if (!step.system) { // Steps with system check are not shown.
                var $row = $('<tr>');
                $('<td>').text(String(step.step_nr)).appendTo($row);
                $('<td>').text(check_ident).appendTo($row);
                $('<td>').text(String(step.description || '')).appendTo($row);
                $('<td>').text(
                    Array.isArray(step.layers) ? step.layers.join(', ') : ''
                ).appendTo($row);
                var $checkbox = $('<input>', {
                    name: 'selected_steps[]',
                    type: 'checkbox',
                    value: String(step.step_nr)
                }).prop('checked', true).prop('disabled', Boolean(step.required));
                $('<td>').append($checkbox).appendTo($row);
                $row.appendTo($tbody);
            }
        }

        //show table if hidden
        if($("#tbl_check_details").is(":hidden")){
            $("#tbl_check_details").show();
        }

        // Update link to product definition.
        updateProductDefinitionLink(product_ident, 'Product Definition');

        // enable Run QC button
        $("#btn_run").prop("disabled", false);

        //listen to checkbox events
        toggle_select_buttons();
        $("#tbl_check_details :checkbox").off("change.qcSetup").on("change.qcSetup", function() {
            toggle_select_buttons();
        });
    })
    .fail(function() {
        $("#tbl_check_details").hide();
        $("#tbl_check_details > tbody").empty();
        $("#error_placeholder").empty().append(
            $('<div>', {'class': 'alert alert-danger'}).text(
                'Error in configuration of ' + product_ident + ' product!'
            )
        );
        updateProductDefinitionLink(product_ident, 'Show Product Definition');
    });
}


$(document).ready(function() {

    $("#tbl_check_details").hide();
    var selected_product_ident = document.getElementById("preselected_product").value;
    if (selected_product_ident === "Select product ...") {
        selected_product_ident = "None";
    }
    if (selected_product_ident && selected_product_ident !== "None") {
        display_product_info(selected_product_ident);
        $("#tbl_check_details").show();
    } else {
        $("#tbl_check_details").hide();
        $("#tbl_check_details > tbody").empty();
        $("#product_link_placeholder").empty();
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

    $("#btn_select_all").on("click", select_all);
    $("#btn_unselect_all").on("click", unselect_all);
});


function unselect_all() {
    $("#tbl_check_details :checkbox").each(function() {
        if(!$(this).prop('disabled')) {
            $(this).prop("checked", false);
        }
    });
    toggle_select_buttons();
}

function select_all() {
    $("#tbl_check_details :checkbox").each(function() {
        if(!$(this).prop('disabled')) {
            $(this).prop("checked", true);
        }
    });
    toggle_select_buttons();
}


function create_job() {

    // Validate if the user has selected a product.
    if ($("#select_product").val() === "Select product ...") {
        BootstrapDialog.show({
            title: "Error",
            message: "Please select a product.",
            buttons: [{
                label: "OK",
                cssClass: "btn-qc-secondary",
                action: function(dialog) {
                    dialog.close();
                }
            }]
        });
        return;
    }

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
        url: $('#tool-canvas').attr('data-create-job-url'),
        data: data,
        dataType: "json",
        success: function(result) {
            $("#modal-spinner").modal("hide");
            var msg_title = "QC Job has been added to queue.";
            if (result.num_created > 1) {
                msg_title = result.num_created + " QC jobs have been added to queue.";
            }
            BootstrapDialog.show({
                title: msg_title,
                message: textDialogMessage(result.message),
                buttons: [{
                    label: "OK",
                    cssClass: "btn-qc-secondary",
                    action: function(dialog) {
                        // If the user click OK, then redirect to jobs page for now.
                    $(location).attr(
                        'href',
                        $('#tool-canvas').attr('data-deliveries-url')
                    );
                    }
                }]
            });
        },
        error: function(result) {
            $("#modal-spinner").modal("hide");
            BootstrapDialog.show({
                title: "Error",
                message: "Error running job. Please try later.",
                buttons: [{
                    label: "OK",
                    cssClass: "btn-qc-secondary",
                    action: function(dialog) {dialog.close();}
                }]
            });
        }
    });
};
