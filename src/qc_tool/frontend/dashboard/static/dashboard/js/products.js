(function () {
  "use strict";

  var search = document.querySelector("[data-products-search]");
  var products = Array.prototype.slice.call(
    document.querySelectorAll("[data-product]")
  );
  var empty = document.querySelector("[data-products-empty]");
  var status = document.querySelector("[data-products-status]");

  if (!search || !products.length) {
    return;
  }

  function filterProducts() {
    var query = search.value.trim().toLocaleLowerCase();
    var visible = 0;

    products.forEach(function (product) {
      var matches = !query || product.textContent.toLocaleLowerCase().indexOf(query) !== -1;
      product.hidden = !matches;
      if (matches) {
        visible += 1;
      }
    });

    if (empty) {
      empty.hidden = visible !== 0;
    }
    if (status) {
      status.textContent = visible + " product" + (visible === 1 ? "" : "s") + " shown.";
    }
  }

  search.addEventListener("input", filterProducts);
}());
