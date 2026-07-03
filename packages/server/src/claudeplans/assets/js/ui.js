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

// Expand/collapse persistence for every details[data-project] — project nodes
// and each project's nested archived group. Expand state is owned by the
// client: idiomorph is configured to never touch the `open` attribute on these
// <details> (see the beforeAttributeUpdated default below), so live sidebar SSE
// morphs update the tree, titles, and status dots without ever reopening a
// node the user collapsed. Stored state is therefore applied once on load;
// the afterSwap hook only binds click handlers on nodes added by a live
// update. Toggles are recorded under a stable per-node key (the project slug,
// or "<project>//archived" for an archived group).
(function () {
  "use strict";
  // Freeze `open` against morphs. The htmx morph ext merges
  // Idiomorph.defaults.callbacks into every morph config (read live at morph
  // time), and the attribute-sync loop skips an update when this returns false.
  // Without it, the snapshot sidebar frame sent on SSE connect re-adds the
  // server-default `open` to a project the user just collapsed, so the collapse
  // does not survive navigation. Scoped to the `open` attribute on
  // details[data-project] — project nodes AND each project's nested archived
  // group (keyed "<project>//archived") — so both join the same persistence;
  // every other attribute (status dots, titles, aria-current) morphs normally.
  if (window.Idiomorph && Idiomorph.defaults && Idiomorph.defaults.callbacks) {
    Idiomorph.defaults.callbacks.beforeAttributeUpdated = function (attr, node) {
      if (attr === "open" && node.matches && node.matches("details[data-project]")) {
        return false;
      }
    };
  }
  // v2: the v1 map was polluted by an earlier build that recorded morph-driven
  // toggles as user intent; bump the key to abandon that corrupted state.
  var KEY = "sidebarProjectsOpen.v2";
  var bound = new WeakSet();
  function read() {
    try {
      return JSON.parse(localStorage.getItem(KEY)) || {};
    } catch (e) {
      /* storage unavailable or corrupt; treat as no stored state */
      return {};
    }
  }
  function write(map) {
    try {
      localStorage.setItem(KEY, JSON.stringify(map));
    } catch (e) {
      /* storage unavailable; the toggle still works for this page */
    }
  }
  function apply() {
    var stored = read();
    var nodes = document.querySelectorAll(".sidebar details[data-project]");
    nodes.forEach(function (el) {
      var project = el.dataset.project;
      if (Object.prototype.hasOwnProperty.call(stored, project)) {
        el.open = stored[project];
      }
      if (!bound.has(el)) {
        bound.add(el);
        // Record only USER intent: a click on this node's own <summary>. The
        // native <details> toggle runs as the click's default action, so read
        // the resulting state on the next frame. Listening to `toggle` instead
        // would also capture idiomorph's morph-driven attribute sync (e.g. the
        // snapshot frame sent on SSE connect), which would clobber stored state.
        el.addEventListener("click", function (ev) {
          var summary = el.querySelector(":scope > summary");
          if (!summary || !summary.contains(ev.target)) return;
          requestAnimationFrame(function () {
            var map = read();
            map[el.dataset.project] = el.open;
            write(map);
          });
        });
      }
    });
  }
  apply();
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    var t = evt.detail && evt.detail.target;
    if (t && t.id === "sidebar-content") apply();
  });
})();
