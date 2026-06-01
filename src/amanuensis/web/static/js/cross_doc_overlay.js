/* cross_doc_overlay.js — Cytoscape overlay for cross-doc relations (Phase 2b M8 T8.6).
 *
 * Behavior:
 *   - Listens for ``change`` events on ``#cross-doc-toggle``.
 *   - When toggled ON:
 *       * Reads the current source id from ``window.location.pathname`` —
 *         the relation-graph route is ``/distillations/<src>/relations``,
 *         so the segment immediately after ``distillations/`` is the
 *         source id.
 *       * Fetches ``/distillations/<src>/relations/atom-entity-index?include_cross_doc=1``.
 *       * For each cross-doc edge, adds a Cytoscape edge with a dashed
 *         orange line style (matches Phase 2a's entity-hover orange so
 *         the overlay reads as "annotation, not primary content").
 *       * Tags each overlay edge with ``data-cross-doc-id`` so the
 *         remove pass can target only overlay edges and leave intra-doc
 *         edges untouched.
 *       * Attaches a click handler that navigates to
 *         ``/cross-doc-relations/<id>``.
 *       * Edges whose endpoint atom is NOT present in the current
 *         Cytoscape canvas (e.g. the other side of the cross-doc edge
 *         lives in a different distillation) are skipped — Cytoscape
 *         requires source + target nodes to exist before an edge can
 *         be added.
 *   - When toggled OFF:
 *       * Removes every edge tagged ``data-cross-doc-id``.
 *
 * Soft-cap / chunking note: the existing ``relation_graph.html`` page
 * does not currently chunk by section (the 2000-edge soft cap from the
 * spec is not yet implemented), so the overlay simply fetches the full
 * set for the current source. When chunking lands, this script should
 * be extended to filter ``cross_doc_edges`` by the currently-selected
 * section. Tracked as a follow-up; the M11 Playwright spec
 * (T11.2) will exercise the toggle interactively.
 *
 * No automated test for this JS lands in M8 — Playwright coverage is
 * scheduled for M11 T11.2. Keep the behaviour comments above in sync
 * with whatever shape that spec expects so the test author can pattern-
 * match without re-reading the spec.
 */
(function () {
  "use strict";

  var TOGGLE_ID = "cross-doc-toggle";
  var OVERLAY_DATA_KEY = "crossDocId";
  var OVERLAY_LINE_COLOR = "#ff8c00"; // matches entity-hover orange (no purple).
  var OVERLAY_CLASS = "cross-doc-overlay-edge";

  function getSourceIdFromPath() {
    // Path is /distillations/<src>/relations[...]; pluck the segment.
    var parts = window.location.pathname.split("/").filter(Boolean);
    var idx = parts.indexOf("distillations");
    if (idx === -1 || idx + 1 >= parts.length) {
      return null;
    }
    return parts[idx + 1];
  }

  function getCyInstance() {
    // Mirrors entity-hover.js: cy is owned by the Alpine relationGraph
    // component on the parent section element. Access via Alpine.$data.
    var section = document.querySelector("[x-data]");
    if (!section) return null;
    var alpine = window.Alpine;
    if (!alpine || typeof alpine.$data !== "function") return null;
    var data = alpine.$data(section);
    return data && data.cy ? data.cy : null;
  }

  function registerOverlayStyle(cy) {
    // Add a Cytoscape style block for overlay edges. ``cy.style()`` is
    // additive; safe to call once per init.
    if (cy._crossDocStyleRegistered) {
      return;
    }
    cy.style()
      .selector("edge." + OVERLAY_CLASS)
      .style({
        "line-style": "dashed",
        "line-color": OVERLAY_LINE_COLOR,
        "target-arrow-color": OVERLAY_LINE_COLOR,
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "width": 2,
      })
      .update();
    cy._crossDocStyleRegistered = true;
  }

  function addOverlayEdges(cy, edges) {
    edges.forEach(function (edge) {
      // Cytoscape needs both endpoints to be on the current canvas. The
      // intra-doc graph only contains atoms from the current source, so
      // the "other side" of the cross-doc edge will usually be absent.
      // Pick the endpoint that DOES live on this canvas as the source
      // and synthesize the missing peer as a lightweight placeholder
      // node so the edge can render. Placeholder nodes carry
      // ``data-cross-doc-id`` too so the remove pass cleans them up.
      var localId = null;
      var peerId = null;
      var peerSourceId = null;
      var peerAtomId = null;
      if (cy.getElementById(edge.from_atom_id).nonempty()) {
        localId = edge.from_atom_id;
        peerId = edge.to_atom_id;
        peerSourceId = edge.to_source_id;
        peerAtomId = edge.to_atom_id;
      } else if (cy.getElementById(edge.to_atom_id).nonempty()) {
        localId = edge.to_atom_id;
        peerId = edge.from_atom_id;
        peerSourceId = edge.from_source_id;
        peerAtomId = edge.from_atom_id;
      } else {
        // Neither endpoint is on the current canvas — nothing to draw.
        return;
      }

      // Synthesize the peer node if absent. ``cross-doc-peer`` class
      // lets future styling (M11) differentiate it from intra-doc atoms.
      if (cy.getElementById(peerId).empty()) {
        cy.add({
          group: "nodes",
          data: {
            id: peerId,
            label: peerSourceId + " / " + peerAtomId.slice(0, 8) + "…",
            crossDocPeer: true,
            crossDocId: edge.id,
          },
          classes: "cross-doc-peer",
        });
      }

      // Add the overlay edge itself.
      var addedEdge = cy.add({
        group: "edges",
        data: {
          id: "overlay-" + edge.id,
          source: edge.from_atom_id,
          target: edge.to_atom_id,
          label: edge.kind,
          crossDocId: edge.id,
        },
        classes: OVERLAY_CLASS,
      });
      addedEdge.on("tap", function () {
        window.location.href = "/cross-doc-relations/" + edge.id;
      });
      // Keep ``localId`` referenced so closure-elision lints stay quiet;
      // it is also useful for future "highlight the local endpoint" UX.
      void localId;
    });
  }

  function removeOverlayEdges(cy) {
    // Remove every edge tagged with crossDocId, plus any synthesized
    // peer nodes. Order matters: remove edges first so node-removal
    // doesn't fail on dangling edges.
    cy.edges().forEach(function (edge) {
      if (edge.data(OVERLAY_DATA_KEY)) {
        edge.remove();
      }
    });
    cy.nodes().forEach(function (node) {
      if (node.data("crossDocPeer")) {
        node.remove();
      }
    });
  }

  function fetchOverlayEdges(sourceId) {
    var url =
      "/distillations/" +
      encodeURIComponent(sourceId) +
      "/relations/atom-entity-index?include_cross_doc=1";
    return fetch(url, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("overlay fetch failed: " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.cross_doc_edges)) {
          return [];
        }
        return data.cross_doc_edges;
      });
  }

  function onToggleChange(event) {
    var checked = event && event.target && event.target.checked;
    var cy = getCyInstance();
    if (!cy) {
      return;
    }
    registerOverlayStyle(cy);
    if (!checked) {
      removeOverlayEdges(cy);
      return;
    }
    var sourceId = getSourceIdFromPath();
    if (!sourceId) {
      return;
    }
    fetchOverlayEdges(sourceId)
      .then(function (edges) {
        // Defensive: clear any leftovers from a previous toggle cycle.
        removeOverlayEdges(cy);
        addOverlayEdges(cy, edges);
      })
      .catch(function (err) {
        // Best-effort — surface to the console for debugging but do
        // not break the page. The supervisor can re-toggle if needed.
        // eslint-disable-next-line no-console
        console.warn("[cross-doc-overlay]", err);
      });
  }

  function bind() {
    var toggle = document.getElementById(TOGGLE_ID);
    if (!toggle) {
      return;
    }
    toggle.addEventListener("change", onToggleChange);
  }

  // Run after Alpine has initialized.
  document.addEventListener("alpine:initialized", bind);
  // Fallback for the case where Alpine has already initialized by the
  // time this script evaluates.
  document.addEventListener("DOMContentLoaded", function () {
    setTimeout(bind, 50);
  });
})();
