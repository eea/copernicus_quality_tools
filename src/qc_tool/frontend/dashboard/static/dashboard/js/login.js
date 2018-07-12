$(document).ready(function(){
    $('label').first().addClass("sr-only");
    $('label').last().addClass("sr-only");

    $('#id_username').addClass("form-control");
    $('#id_username').attr({"placeholder": "Username", "required": "", "autofocus":""});

    $('#id_password').addClass("form-control");
    $('#id_password').attr({"placeholder": "Password", "required": "", "type": "password"});
});