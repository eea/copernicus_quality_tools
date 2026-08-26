(function () {
  "use strict";

  var operations = Array.prototype.slice.call(
    document.querySelectorAll("[data-api-operation]")
  );
  var groups = Array.prototype.slice.call(
    document.querySelectorAll("[data-api-group]")
  );
  var search = document.getElementById("api-operation-search");
  var emptyState = document.querySelector("[data-api-empty]");

  function visibleOperations() {
    return operations.filter(function (operation) {
      return !operation.hidden;
    });
  }

  function filterOperations() {
    var query = search ? search.value.trim().toLocaleLowerCase() : "";
    var matchCount = 0;

    operations.forEach(function (operation) {
      var haystack = (operation.getAttribute("data-api-search") || "").toLocaleLowerCase();
      var isMatch = !query || haystack.indexOf(query) !== -1;
      operation.hidden = !isMatch;
      if (isMatch) {
        matchCount += 1;
      }
    });

    groups.forEach(function (group) {
      group.hidden = !group.querySelector("[data-api-operation]:not([hidden])");
    });

    if (emptyState) {
      emptyState.hidden = matchCount !== 0;
    }
  }

  function setAllOperations(open) {
    visibleOperations().forEach(function (operation) {
      operation.open = open;
    });
  }

  function temporarilyConfirm(button) {
    var originalLabel = button.textContent;
    button.textContent = "Copied";
    button.setAttribute("aria-live", "polite");
    window.setTimeout(function () {
      button.textContent = originalLabel;
      button.removeAttribute("aria-live");
    }, 1600);
  }

  function legacyCopy(text) {
    var input = document.createElement("textarea");
    input.value = text;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    var copied = document.execCommand("copy");
    document.body.removeChild(input);
    return copied;
  }

  function copyExample(button) {
    var targetId = button.getAttribute("data-copy-target");
    var target = targetId ? document.getElementById(targetId) : null;
    if (!target) {
      return;
    }
    var text = target.textContent;
    var clipboard = navigator.clipboard;

    if (clipboard && typeof clipboard.writeText === "function") {
      clipboard.writeText(text).then(
        function () {
          temporarilyConfirm(button);
        },
        function () {
          if (legacyCopy(text)) {
            temporarilyConfirm(button);
          }
        }
      );
      return;
    }
    if (legacyCopy(text)) {
      temporarilyConfirm(button);
    }
  }

  if (search) {
    search.addEventListener("input", filterOperations);
  }

  var expandButton = document.querySelector("[data-api-expand]");
  if (expandButton) {
    expandButton.addEventListener("click", function () {
      setAllOperations(true);
    });
  }

  var collapseButton = document.querySelector("[data-api-collapse]");
  if (collapseButton) {
    collapseButton.addEventListener("click", function () {
      setAllOperations(false);
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy-target]");
    if (button) {
      copyExample(button);
    }
  });

  if (window.location.hash) {
    var target = document.getElementById(
      decodeURIComponent(window.location.hash.slice(1))
    );
    if (target && target.matches("details[data-api-operation]")) {
      target.open = true;
    }
  }
})();
