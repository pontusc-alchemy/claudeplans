// Command-palette search overlay. Strict CSP (script-src 'self', no inline) means
// this same-origin file builds the overlay in the DOM and wires every handler here.
// Searches across all of the user's projects via the data-uid on <body>; it no-ops
// only on the root user-picker, which has no user context.
(function () {
  "use strict";
  var body = document.body;
  var uid = body.getAttribute("data-uid");
  if (!uid) {
    return;
  }

  var searchBase = "/v1/users/" + encodeURIComponent(uid) + "/search";

  // --- build overlay DOM ---------------------------------------------------
  var overlay = document.createElement("div");
  overlay.className = "search-overlay";
  overlay.setAttribute("hidden", "");
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Search all projects");

  var box = document.createElement("div");
  box.className = "search-box";

  var input = document.createElement("input");
  input.className = "search-input";
  input.type = "text";
  input.setAttribute("autocomplete", "off");
  input.setAttribute("spellcheck", "false");
  input.setAttribute("aria-label", "Search query");
  input.placeholder = "Search all projects…";

  var results = document.createElement("ul");
  results.className = "search-results";

  var hint = document.createElement("div");
  hint.className = "search-hint";
  hint.textContent = "↑↓ navigate · ↵ open · esc close";

  box.appendChild(input);
  box.appendChild(results);
  box.appendChild(hint);
  overlay.appendChild(box);
  document.body.appendChild(overlay);

  // --- state ---------------------------------------------------------------
  var open = false;
  var hits = [];
  var selected = -1;
  var debounceTimer = null;
  var seq = 0; // race guard: drop stale fetch responses

  function openPalette(initial) {
    if (open) {
      return;
    }
    open = true;
    overlay.removeAttribute("hidden");
    input.value = initial || "";
    input.focus();
    if (input.value) {
      runQuery();
    } else {
      render();
    }
  }

  function closePalette() {
    if (!open) {
      return;
    }
    open = false;
    overlay.setAttribute("hidden", "");
    input.value = "";
    hits = [];
    selected = -1;
    results.replaceChildren();
  }

  // Hits can come from any of the user's projects, so the project segment comes
  // from the hit itself. The DOM id scheme lives in _doc_body.html: sections render
  // id="section-{anchor}", phases id="phase-{slug}" — mirror that here so the
  // fragment actually resolves (the hit's bare `anchor` alone would not match).
  function viewUrl(hit) {
    var url =
      "/v1/users/" +
      encodeURIComponent(uid) +
      "/projects/" +
      encodeURIComponent(hit.project) +
      "/docs/" +
      encodeURIComponent(hit.slug) +
      "/view";
    if (hit.anchor) {
      if (hit.kind === "phase") {
        url += "#phase-" + hit.anchor;
      } else if (hit.kind === "section") {
        url += "#section-" + hit.anchor;
      } else {
        url += "#" + hit.anchor;
      }
    }
    return url;
  }

  function go(hit) {
    if (hit) {
      window.location.assign(viewUrl(hit));
    }
  }

  function render() {
    results.replaceChildren();
    for (var i = 0; i < hits.length; i++) {
      var li = document.createElement("li");
      li.className = "search-hit" + (i === selected ? " selected" : "");

      var kind = document.createElement("span");
      kind.className = "search-kind";
      kind.textContent = hits[i].kind;

      var text = document.createElement("span");
      text.className = "search-text";
      text.textContent = hits[i].text;

      var doc = document.createElement("span");
      doc.className = "search-doc";
      var pname = hits[i].project_name || hits[i].project;
      doc.textContent =
        hits[i].kind === "title" ? pname : hits[i].title + " · " + pname;

      li.appendChild(kind);
      li.appendChild(text);
      li.appendChild(doc);
      (function (h) {
        li.addEventListener("mousedown", function (e) {
          e.preventDefault();
          go(h);
        });
      })(hits[i]);
      results.appendChild(li);
    }
  }

  function runQuery() {
    var q = input.value.trim();
    if (!q) {
      hits = [];
      selected = -1;
      render();
      return;
    }
    var mine = ++seq;
    fetch(searchBase + "?q=" + encodeURIComponent(q), {
      headers: { Accept: "application/json" }
    })
      .then(function (r) {
        return r.ok ? r.json() : { hits: [] };
      })
      .then(function (data) {
        if (mine !== seq || !open) {
          return;
        }
        hits = (data && data.hits) || [];
        selected = hits.length ? 0 : -1;
        render();
      })
      .catch(function () {
        if (mine === seq) {
          hits = [];
          selected = -1;
          render();
        }
      });
  }

  function move(delta) {
    if (!hits.length) {
      return;
    }
    selected = (selected + delta + hits.length) % hits.length;
    render();
    var el = results.children[selected];
    if (el && el.scrollIntoView) {
      el.scrollIntoView({ block: "nearest" });
    }
  }

  // --- events --------------------------------------------------------------
  input.addEventListener("input", function () {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(runQuery, 120);
  });

  overlay.addEventListener("mousedown", function (e) {
    if (e.target === overlay) {
      closePalette();
    }
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      move(-1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (selected >= 0) {
        go(hits[selected]);
      }
    }
  });

  // Open on the first printable keystroke anywhere on the page (or "/").
  document.addEventListener("keydown", function (e) {
    if (open || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) {
      return;
    }
    var t = e.target;
    var tag = t && t.tagName ? t.tagName.toUpperCase() : "";
    if (
      tag === "INPUT" ||
      tag === "TEXTAREA" ||
      tag === "SELECT" ||
      (t && t.isContentEditable)
    ) {
      return;
    }
    if (e.key === "/") {
      e.preventDefault();
      openPalette("");
    } else if (typeof e.key === "string" && e.key.length === 1 && e.key !== " ") {
      e.preventDefault();
      openPalette(e.key);
    }
  });
})();
