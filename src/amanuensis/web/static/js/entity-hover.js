/* entity-hover.js — hover-by-entity highlight for the Cytoscape relation graph.
 *
 * Reads the #atom-entity-index JSON block (dict[atom_id, list[entity_id]])
 * planted by the relation_graph route (T8.6). On mouseover of any atom node,
 * highlights every other node that shares at least one entity. On mouseout,
 * clears all highlights. If the index is missing or empty this script is a
 * no-op. No Alpine required; vanilla JS that waits for the Alpine relationGraph
 * component to finish mounting (Phase 2a M8 T8.7). */
(function () {
  "use strict";

  function readAtomEntityIndex() {
    var el = document.getElementById("atom-entity-index");
    if (!el || !el.textContent) {
      return null;
    }
    try {
      var parsed = JSON.parse(el.textContent);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        return null;
      }
      return parsed;
    } catch (e) {
      return null;
    }
  }

  function attachHoverHandlers(cy, index) {
    // Build reverse map: entity_id → set of atom_ids that share it.
    var entityToAtoms = {};
    Object.keys(index).forEach(function (atomId) {
      var entityIds = index[atomId];
      if (!Array.isArray(entityIds)) {
        return;
      }
      entityIds.forEach(function (entityId) {
        if (!entityToAtoms[entityId]) {
          entityToAtoms[entityId] = [];
        }
        entityToAtoms[entityId].push(atomId);
      });
    });

    cy.on("mouseover", "node", function (evt) {
      var atomId = evt.target.id();
      var entityIds = index[atomId];
      if (!entityIds || entityIds.length === 0) {
        return;
      }
      // Collect every other atom that shares any of those entities.
      var peers = {};
      entityIds.forEach(function (entityId) {
        var siblings = entityToAtoms[entityId] || [];
        siblings.forEach(function (sibAtomId) {
          if (sibAtomId !== atomId) {
            peers[sibAtomId] = true;
          }
        });
      });
      Object.keys(peers).forEach(function (peerId) {
        cy.getElementById(peerId).addClass("entity-shared");
      });
    });

    cy.on("mouseout", "node", function () {
      cy.nodes().removeClass("entity-shared");
    });
  }

  function tryAttach() {
    var index = readAtomEntityIndex();
    if (!index || Object.keys(index).length === 0) {
      return;
    }
    // Wait for the Alpine relationGraph component to expose cy on window.
    // The component stores cy on its Alpine data object, not on window, so
    // we access it via the x-data binding on the parent section element.
    var section = document.querySelector("[x-data]");
    if (!section) {
      return;
    }
    // Alpine 3 exposes component data via Alpine.$data(el).
    var alpine = window.Alpine;
    if (!alpine || typeof alpine.$data !== "function") {
      return;
    }
    var data = alpine.$data(section);
    if (!data || !data.cy) {
      return;
    }
    attachHoverHandlers(data.cy, index);
  }

  // Run after Alpine has initialized its components.
  document.addEventListener("alpine:initialized", function () {
    tryAttach();
  });

  // Fallback: also try on DOMContentLoaded in case Alpine has already fired.
  document.addEventListener("DOMContentLoaded", function () {
    // Small delay to let Alpine finish mounting.
    setTimeout(tryAttach, 50);
  });
})();
