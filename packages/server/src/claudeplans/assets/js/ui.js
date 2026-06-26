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

// Sidebar collapse toggle. Persists across navigation via localStorage; the panel
// lives outside the htmx morph region, so the body class survives live doc updates.
(function () {
  "use strict";
  var btn = document.querySelector(".sidebar-toggle");
  if (!btn) {
    return;
  }
  var KEY = "sidebarCollapsed";
  function apply(collapsed) {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.setAttribute(
      "aria-label",
      collapsed ? "Expand sidebar" : "Collapse sidebar"
    );
  }
  apply(localStorage.getItem(KEY) === "1");
  btn.addEventListener("click", function () {
    var collapsed = !document.body.classList.contains("sidebar-collapsed");
    apply(collapsed);
    try {
      localStorage.setItem(KEY, collapsed ? "1" : "0");
    } catch (e) {
      /* storage unavailable; the toggle still works for this page */
    }
  });
})();
