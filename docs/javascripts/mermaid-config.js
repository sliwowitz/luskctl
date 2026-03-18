// Make mermaid subgraph cluster backgrounds transparent.
// Material for MkDocs injects ID-scoped styles into each SVG that
// cannot be overridden by external CSS.  This MutationObserver
// sets fill="transparent" on cluster rects after mermaid renders.
document.addEventListener("DOMContentLoaded", function () {
  new MutationObserver(function () {
    document.querySelectorAll(".cluster > rect").forEach(function (rect) {
      rect.style.fill = "transparent";
    });
  }).observe(document.body, { childList: true, subtree: true });
});
