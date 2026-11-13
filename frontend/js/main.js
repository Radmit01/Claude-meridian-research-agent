// Entry point: routes, global listeners, status polling.
import { $ } from "./utils.js";
import { defineRoutes, startRouter } from "./router.js";
import { pollActiveRun } from "./store.js";
import { mountStatusBar } from "./components/statusBar.js";
import { closeDrawer } from "./components/drawer.js";
import { closeModal } from "./components/modal.js";
import { openDocDrawer } from "./components/docDrawer.js";

import * as overview from "./pages/overview.js";
import * as runNew from "./pages/runNew.js";
import * as runWatch from "./pages/runWatch.js";
import * as runHistory from "./pages/runHistory.js";
import * as packList from "./pages/packList.js";
import * as packView from "./pages/packView.js";
import * as corpus from "./pages/corpus.js";
import * as system from "./pages/system.js";

const prettyPack = (s) => decodeURIComponent(s).replace(/\.md$/, "").replace(/_/g, " ");

defineRoutes([
  { pattern: /^\/?$/, nav: "overview", page: overview, crumbs: () => ["Overview"] },
  { pattern: /^\/run\/?$/, nav: "run", page: runNew, crumbs: () => ["New run"] },
  { pattern: /^\/run\/([\w-]+)$/, nav: "runs", page: runWatch, crumbs: (m) => ["Runs", `Run ${m[1]}`] },
  { pattern: /^\/runs\/?$/, nav: "runs", page: runHistory, crumbs: () => ["Run history"] },
  { pattern: /^\/packs\/?$/, nav: "packs", page: packList, crumbs: () => ["Research packs"] },
  { pattern: /^\/packs\/([^/]+?)(?:\/(\w+))?$/, nav: "packs", page: packView, crumbs: (m) => ["Research packs", prettyPack(m[1])] },
  { pattern: /^\/corpus\/?$/, nav: "corpus", page: corpus, crumbs: () => ["Corpus"] },
  { pattern: /^\/system\/?$/, nav: "system", page: system, crumbs: () => ["System"] },
]);

// Delegated clicks: any [data-doc] opens the document drawer; any [data-href] navigates.
document.addEventListener("click", (e) => {
  if (e.target.closest("#modal-root")) return;
  const doc = e.target.closest("[data-doc]");
  if (doc && !e.target.closest("#drawer")) {
    e.preventDefault();
    openDocDrawer(doc.dataset.doc, doc.dataset.ref || "");
    return;
  }
  const link = e.target.closest("[data-href]");
  if (link && !e.target.closest("a, button")) location.hash = link.dataset.href;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeModal(); closeDrawer(); }
  if (e.key === "Enter" && e.target.matches("[data-href][tabindex]")) location.hash = e.target.dataset.href;
});
$("#drawer-scrim").addEventListener("click", closeDrawer);
$("#menu-btn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));

mountStatusBar();
startRouter();
pollActiveRun();
setInterval(pollActiveRun, 4000);
