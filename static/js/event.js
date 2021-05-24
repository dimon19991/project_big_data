$("button[name='btn_detail_event']").click(function() {

    window.location = "results/"+$(this).data('folder_data');

});

$("button[name='btn_download']").click(function() {

    window.location = "../download/"+$(this).data('folder_data');

});