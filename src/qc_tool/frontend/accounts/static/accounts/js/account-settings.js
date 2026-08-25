(function () {
  "use strict";

  function setCopyStatus(message) {
    var status = document.getElementById("credential-copy-status");
    if (status) {
      status.textContent = message;
    }
  }

  function fallbackCopy(input) {
    input.focus();
    input.select();
    input.setSelectionRange(0, input.value.length);
    return document.execCommand("copy");
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy-target]");
    if (!button) {
      return;
    }

    var input = document.querySelector(button.getAttribute("data-copy-target"));
    if (!input) {
      return;
    }

    var copyPromise;
    if (navigator.clipboard && window.isSecureContext) {
      copyPromise = navigator.clipboard.writeText(input.value);
    } else {
      try {
        copyPromise = fallbackCopy(input)
          ? Promise.resolve()
          : Promise.reject(new Error("Copy command was rejected."));
      } catch (error) {
        copyPromise = Promise.reject(error);
      }
    }

    copyPromise.then(function () {
      button.textContent = "Copied";
      setCopyStatus("Token copied. Store it securely before leaving this page.");
    }).catch(function () {
      input.focus();
      input.select();
      setCopyStatus("Automatic copy was unavailable. Copy the selected token manually.");
    });
  });

  document.addEventListener("submit", function (event) {
    var form = event.target.closest(
      "form[data-confirm-submit], form[data-disable-on-submit]"
    );
    if (!form) {
      return;
    }

    var confirmation = form.getAttribute("data-confirm-submit");
    if (confirmation && !window.confirm(confirmation)) {
      event.preventDefault();
      return;
    }

    var submitButton = form.querySelector('button[type="submit"]');
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.setAttribute("aria-busy", "true");
    }
  });
}());
