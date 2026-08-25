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

  function disableSubmitButton(form, submitter) {
    var submitButton = submitter || form.querySelector('button[type="submit"]');
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.setAttribute("aria-busy", "true");
    }
  }

  var confirmDialog = document.getElementById("account-confirm-dialog");
  var pendingForm = null;
  var pendingSubmitter = null;

  if (confirmDialog) {
    confirmDialog.addEventListener("close", function () {
      var form = pendingForm;
      var submitter = pendingSubmitter;
      pendingForm = null;
      pendingSubmitter = null;

      if (confirmDialog.returnValue !== "confirm" || !form) {
        return;
      }

      form.setAttribute("data-confirmed", "true");
      if (typeof form.requestSubmit === "function") {
        if (submitter) {
          form.requestSubmit(submitter);
        } else {
          form.requestSubmit();
        }
      } else {
        form.submit();
      }
    });
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

    if (form.getAttribute("data-confirmed") === "true") {
      form.removeAttribute("data-confirmed");
      disableSubmitButton(form, event.submitter);
      return;
    }

    var confirmation = form.getAttribute("data-confirm-submit");
    if (confirmation) {
      if (confirmDialog && typeof confirmDialog.showModal === "function") {
        event.preventDefault();
        pendingForm = form;
        pendingSubmitter = event.submitter || null;
        confirmDialog.returnValue = "";

        var title = document.getElementById("account-confirm-title");
        var message = document.getElementById("account-confirm-message");
        var action = confirmDialog.querySelector("[data-confirm-dialog-action]");
        if (title) {
          title.textContent =
            form.getAttribute("data-confirm-title") || "Please confirm";
        }
        if (message) {
          message.textContent = confirmation;
        }
        if (action) {
          action.textContent = form.getAttribute("data-confirm-action") || "Continue";
        }

        confirmDialog.showModal();
        return;
      }

      if (!window.confirm(confirmation)) {
        event.preventDefault();
        return;
      }
    }

    disableSubmitButton(form, event.submitter);
  });
}());
