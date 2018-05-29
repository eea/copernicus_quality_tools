$(document).ready(function(){
  $("#my-file").fileinput({
       uploadUrl:'/files/upload_handler/',
       asynchronous:true,
       hideThumbnailContent:true
    });
 });