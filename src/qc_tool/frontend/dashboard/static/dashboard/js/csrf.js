(function(window, document, $) {
    "use strict";

    function getToken() {
        var element = document.querySelector('meta[name="csrf-token"]');
        return element ? element.getAttribute("content") : "";
    }

    function isSafeMethod(method) {
        return /^(GET|HEAD|OPTIONS|TRACE)$/i.test(method);
    }

    function isSameOrigin(url) {
        var target = document.createElement("a");
        target.href = url;
        return target.protocol === window.location.protocol &&
            target.host === window.location.host;
    }

    window.qcCsrf = {
        getToken: getToken
    };

    if ($) {
        $(document).ajaxSend(function(_event, xhr, settings) {
            var token = getToken();
            var method = settings.type || settings.method || "GET";

            if (token && !isSafeMethod(method) && isSameOrigin(settings.url)) {
                xhr.setRequestHeader("X-CSRFToken", token);
            }
        });
    }
})(window, document, window.jQuery);
