$(function () {

  var n_selected = 0;
  var n_uploaded = 0;

  /* 1. OPEN THE FILE EXPLORER WINDOW */
  $(".js-upload-files").click(function () {
    $("#fileupload").click();
  });

  /* 2. INITIALIZE THE FILE UPLOAD COMPONENT */
  $("#fileupload").fileupload({
    dataType: 'json',
    progressServerRate: 0.3,
    progressServerDecayExp: 2,

    sequentialUploads: true,  /* 1. SEND THE FILES ONE BY ONE */

    start: function (e) {  /* 2. WHEN THE UPLOADING PROCESS STARTS, SHOW THE MODAL */
      $("#files_table tbody").html("");
      $("#modal-progress").modal("show");
      n_selected = 1;
      n_uploaded = 0;
    },
    stop: function (e) {  /* 3. WHEN THE UPLOADING PROCESS FINALIZE, HIDE THE MODAL */
      $("#modal-progress").modal("hide");
    },

    submit: function (e, data) {
        n_selected += data.files.length;
    },

    progressall: function (e, data) {  /* 4. UPDATE THE PROGRESS BAR */
      var progress = parseInt(data.loaded / data.total * 100, 10);
      var strProgress = progress + "%";
      $(".progress-bar").css({"width": strProgress});
      $(".progress-bar").text(strProgress) ;
      var n_uploaded_display = n_uploaded + 1;
      $(".modal-title").text("Uploading file " + n_uploaded_display + " / " + n_selected);
    },
    done: function (e, data) {  /* 3. PROCESS THE RESPONSE FROM THE SERVER */
      n_uploaded += 1;
      if (data.result.is_valid) {
        var msg = '<tr><td><div class="alert alert-success">'
        msg += '<span class="glyphicon glyphicon-ok"></span>';
        msg += ' File <strong>' + data.result.url + '</strong> uploaded successfully. ';
        msg += '<a class="btn btn-success btn-pull-right" href="/">Go Back to my Deliveries<a>';
        msg += '</div></td></tr>';
      } else {
        var msg = '<tr><td><div class="alert alert-danger">';
        msg += '<span class="glyphicon glyphicon-remove"></span> File <strong>';
        msg += data.result.message;
        msg += '</strong></div></td></tr>';
      }
      $("#files_table tbody").prepend(msg);
    }
  });

});