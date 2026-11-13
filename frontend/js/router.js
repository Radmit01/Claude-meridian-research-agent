// Hash router. Each page module exports `render(ctx)`; ctx gives the view
// element, route params, query and `onLeave(fn)` for cleanup.
import { $, $$, esc, loading, errorBox } from "./utils.js";
import { closeDrawer } from "./components/drawer.js";
import { closeModal } from "./components/modal.js";

let routes = [];
let cleanup = [];

export function defineRoutes(list) {
  routes = list;
}

export function navigate(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

export function route() {
  cleanup.forEach((fn) => { try { fn(); } catch (_) {} });
  cleanup = [];
  closeDrawer();
  closeModal();
  $("#sidebar").classList.remove("open");

  const [path, qs] = (location.hash || "#/").slice(1).split("?");
  const view = $("#view");
  for (const r of routes) {
    const m = path.match(r.pattern);
    if (!m) continue;
    $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === r.nav));
    const parts = ["Research desk", ...r.crumbs(m)];
    $("#crumbs").innerHTML = parts
      .map((p, i) => (i === parts.length - 1 ? `<b>${esc(p)}</b>` : esc(p)))
      .join('<span class="sep">/</span>');
    view.innerHTML = loading();
    window.scrollTo(0, 0);
    const ctx = {
      view,
      params: m.slice(1),
      query: new URLSearchParams(qs || ""),
      onLeave: (fn) => cleanup.push(fn),
      rerender: route,
    };
    Promise.resolve(r.page.render(ctx)).catch((e) => { view.innerHTML = errorBox(e); console.error(e); });
    return;
  }
  location.hash = "#/";
}

export function startRouter() {
  window.addEventListener("hashchange", route);
  route();
}
