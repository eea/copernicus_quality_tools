$(document).ready(function(){
    // $('label').first().addClass("sr-only");
    $('label').last().addClass("sr-only");

    $('#id_old_password').addClass("form-control");
    $('#id_old_password').attr({"placeholder": "Old password", "required": "", "autofocus":""});

    $('#id_new_password1').addClass("form-control");
    $('#id_new_password1').attr({"placeholder": "New password", "required": "", "type": "password"});

    $('#id_new_password2').addClass("form-control");
    $('#id_new_password2').attr({"placeholder": "Confirm new password", "required": "", "type": "password"});
});