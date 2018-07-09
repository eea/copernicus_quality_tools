$(function () {
  /* 1. OPEN THE FILE EXPLORER WINDOW */
  $(".js-upload-files").click(function () {
    $("#fileupload").click();
  });

  /* 2. INITIALIZE THE FILE UPLOAD COMPONENT */
  $("#fileupload").fileupload({
    dataType: 'json',

    sequentialUploads: true,  /* 1. SEND THE FILES ONE BY ONE */
    start: function (e) {  /* 2. WHEN THE UPLOADING PROCESS STARTS, SHOW THE MODAL */
      $("#modal-progress").modal("show");
    },
    stop: function (e) {  /* 3. WHEN THE UPLOADING PROCESS FINALIZE, HIDE THE MODAL */
      $("#modal-progress").modal("hide");
    },
    progressall: function (e, data) {  /* 4. UPDATE THE PROGRESS BAR */
      var progress = parseInt(data.loaded / data.total * 100, 10);
      var strProgress = progress + "%";
      $(".progress-bar").css({"width": strProgress});
      $(".progress-bar").text(strProgress);
    },
    done: function (e, data) {  /* 3. PROCESS THE RESPONSE FROM THE SERVER */
      if (data.result.is_valid) {
        $("#files_heading").prepend("Uploaded file");
        $("#files_table tbody").prepend(

          '<tr><td><div class="alert alert-success">File <strong>' + data.result.url + '</strong> uploaded successfully.</div></td></tr>'
        );
      } else {

        $("#files_table tbody").prepend(

          '<tr><td><div class="alert alert-danger">File <strong>' + data.result.message + '</strong></div></td></tr>'
        );
      }
    }
  });

});