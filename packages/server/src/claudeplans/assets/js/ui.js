// User switcher. The strict CSP (script-src 'self') forbids inline onchange, so
// this vendored same-origin script wires the <select> to a full-page navigation
// to the chosen user's landing page.
(function () {
  "use strict";
  var select = document.getElementById("user-select");
  if (!select) {
    return;
  }
  select.addEventListener("change", function () {
    var base = select.getAttribute("data-switch-base") || "/v1/users/";
    window.location.assign(base + encodeURIComponent(select.value) + "/");
  });
})();
