/* probandum_tree.js — Cytoscape mount for the probandum subtree page (Phase 2c M10 T10.4).
 *
 * Behavior:
 *   - Reads the JSON endpoint URL + root probandum id from
 *     ``#probandum-tree-root``'s ``data-tree-url`` and
 *     ``data-probandum-id`` attributes.
 *   - Fetches the JSON payload, mounts Cytoscape into ``#cy-tree``
 *     with the ``dagre`` layout (top-to-bottom), and applies the
 *     per-kind node + edge styling spec'd in the M10 task text.
 *   - On node click, navigates to the appropriate detail page:
 *       * probandum kind   → /probanda/<id>
 *       * atom             → /distillations/<source>/atoms/<id>
 *       * cross-doc-relation → /cross-doc-relations/<id>
 *   - Surfaces the soft-cap "truncated" flag by un-hiding
 *     ``#probandum-tree-expand-controls`` when set.
 *
 * No automated test ships in M10 — the Cytoscape mount itself is
 * exercised only by the JSON-endpoint route tests and the HTML page's
 * script-tag presence test. Playwright coverage is deferred to a
 * future milestone.
 */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function nodeStyleFor(kind) {
    // Returns a partial Cytoscape style override for a node by kind.
    // The base style block (below) sets shared defaults; we override
    // shape + colour here so the per-kind discriminator is visible.
    switch (kind) {
      case "ultimate":
        return { "background-color": "#ef4444", shape: "ellipse" };
      case "penultimate":
        return { "background-color": "#f97316", shape: "ellipse" };
      case "interim":
        return { "background-color": "#facc15", shape: "ellipse" };
      case "atom":
        return { "background-color": "#3b82f6", shape: "rectangle" };
      case "cross-doc-relation":
        return { "background-color": "#a855f7", shape: "diamond" };
      default:
        return { "background-color": "#737373", shape: "ellipse" };
    }
  }

  function edgeStyleFor(kind) {
    switch (kind) {
      case "supports":
        return { "line-color": "#22c55e", "line-style": "solid", "target-arrow-color": "#22c55e" };
      case "attacks":
        return { "line-color": "#ef4444", "line-style": "solid", "target-arrow-color": "#ef4444" };
      case "undercuts":
        return { "line-color": "#9ca3af", "line-style": "dashed", "target-arrow-color": "#9ca3af" };
      default:
        return { "line-color": "#737373", "line-style": "solid", "target-arrow-color": "#737373" };
    }
  }

  function detailUrlForNode(data) {
    if (!data || !data.id) return null;
    if (data.kind === "atom" && data.source_id) {
      return "/distillations/" + encodeURIComponent(data.source_id) +
             "/atoms/" + encodeURIComponent(data.id);
    }
    if (data.kind === "cross-doc-relation") {
      return "/cross-doc-relations/" + encodeURIComponent(data.id);
    }
    // Default: probandum-flavored detail.
    return "/probanda/" + encodeURIComponent(data.id);
  }

  function mount(rootEl, payload) {
    if (!window.cytoscape) return;
    // Register the dagre extension. Re-registration throws, so guard.
    if (window.cytoscapeDagre) {
      try {
        window.cytoscape.use(window.cytoscapeDagre);
      } catch (e) {
        // Already registered; subsequent layout() calls still resolve.
      }
    }

    var elements = [];
    (payload.nodes || []).forEach(function (n) {
      var style = nodeStyleFor((n.data || {}).kind);
      var el = { data: n.data, style: style };
      elements.push(el);
    });
    (payload.edges || []).forEach(function (e) {
      var style = edgeStyleFor((e.data || {}).kind);
      var el = { data: e.data, style: style };
      elements.push(el);
    });

    var cy = window.cytoscape({
      container: document.getElementById("cy-tree"),
      elements: elements,
      layout: { name: "dagre", rankDir: "TB", nodeSep: 60, rankSep: 80 },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: "#f5f5f5",
            "font-size": "10px",
            "text-wrap": "wrap",
            "text-max-width": "140px",
            "text-valign": "center",
            "text-halign": "center",
            "text-background-color": "#171717",
            "text-background-opacity": 0.8,
            "text-background-padding": "2px",
            width: "44px",
            height: "44px",
          },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            width: 2,
          },
        },
      ],
    });

    cy.on("tap", "node", function (evt) {
      var url = detailUrlForNode(evt.target.data());
      if (url) {
        window.location.href = url;
      }
    });

    if (payload.truncated) {
      var ctrl = document.getElementById("probandum-tree-expand-controls");
      if (ctrl) ctrl.classList.remove("hidden");
    }
    var status = document.getElementById("probandum-tree-status");
    if (status) {
      status.textContent = (payload.nodes || []).length + " nodes, " +
        (payload.edges || []).length + " edges";
    }
  }

  ready(function () {
    var root = document.getElementById("probandum-tree-root");
    if (!root) return;
    var url = root.getAttribute("data-tree-url");
    if (!url) return;
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("HTTP " + resp.status);
        }
        return resp.json();
      })
      .then(function (payload) {
        mount(root, payload);
      })
      .catch(function (err) {
        var status = document.getElementById("probandum-tree-status");
        if (status) {
          status.textContent = "failed to load subtree: " + err.message;
        }
      });
  });
})();
