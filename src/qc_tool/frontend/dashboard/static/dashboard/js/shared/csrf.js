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

    function loginUrlFromPayload(payload) {
        if (typeof payload === "string") {
            try {
                payload = JSON.parse(payload);
            } catch (_error) {
                return "";
            }
        }
        return payload && payload.code === "authentication_required" ?
            payload.login_url : "";
    }

    function redirectToLogin(loginUrl) {
        if (!loginUrl || !isSameOrigin(loginUrl)) {
            return false;
        }

        var currentPage = window.location.pathname + window.location.search +
            window.location.hash;
        var target = new URL(loginUrl, window.location.href);
        target.searchParams.set("next", currentPage);
        window.location.assign(target.pathname + target.search + target.hash);
        return true;
    }

    function responsePayload(xhr) {
        if (!xhr) return null;
        if (xhr.responseJSON) return xhr.responseJSON;
        if (xhr.responseType === "json") return xhr.response;
        if (xhr.responseType && xhr.responseType !== "text") return null;
        try {
            return JSON.parse(xhr.responseText || "null");
        } catch (_error) {
            return null;
        }
    }

    function handleUnauthorizedXhr(xhr) {
        if (window.qcMaintenance) window.qcMaintenance.observeXhr(xhr);
        if (!xhr || xhr.status !== 401) {
            return false;
        }
        var loginUrl = xhr.getResponseHeader("X-Login-URL") ||
            loginUrlFromPayload(responsePayload(xhr));
        return redirectToLogin(loginUrl);
    }

    window.qcCsrf = {
        getToken: getToken
    };
    window.qcAuth = {
        responsePayload: responsePayload,
        redirectFromPayload: function(payload) {
            return redirectToLogin(loginUrlFromPayload(payload));
        },
        handleUnauthorizedXhr: handleUnauthorizedXhr
    };

    if ($) {
        $(document).ajaxSend(function(_event, xhr, settings) {
            var token = getToken();
            var method = settings.type || settings.method || "GET";

            if (token && !isSafeMethod(method) && isSameOrigin(settings.url)) {
                xhr.setRequestHeader("X-CSRFToken", token);
            }
        });
        $(document).ajaxError(function(_event, xhr) {
            handleUnauthorizedXhr(xhr);
        });
        $(document).ajaxComplete(function(_event, xhr) {
            if (window.qcMaintenance) window.qcMaintenance.observeXhr(xhr);
        });
    }
})(window, document, window.jQuery);
