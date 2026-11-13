// Small, dependency-free helpers shared by components and pages.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const pad = (n) => String(n).padStart(2, "0");

export function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

export function fmtAgo(ts) {
  if (!ts) return "—";
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  if (d < 86400 * 7) return `${Math.floor(d / 86400)}d ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export const fmtClock = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour12: false });

export const fmtSize = (b) =>
  b == null ? "—" : b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

export const setKey = (docId) => (docId || "").slice(0, 2);
export const SET_NAMES = { CL: "Client", EX: "External", PV: "Protiviti" };
export const SET_LABELS = { CL: "Set A — Client materials", EX: "Set B — External context", PV: "Set C — Internal Protiviti" };

export const statusClass = (s) => (!s ? "" : /^ok/.test(s) ? "ok" : /no extractable/.test(s) ? "empty" : "failed");

/** Tagged template that builds a DOM fragment from an HTML string. */
export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export const icons = {
  arrow: `<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" stroke-width="1.6"/></svg>`,
  plus: `<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="1.6"/></svg>`,
  close: `<svg width="14" height="14" viewBox="0 0 14 14"><path d="M2 2l10 10M12 2L2 12" stroke="currentColor" stroke-width="1.6"/></svg>`,
  search: `<svg width="15" height="15" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5"/><path d="M11 11l3.5 3.5" stroke="currentColor" stroke-width="1.5"/></svg>`,
  upload: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 11V2M4 6l4-4 4 4M2 11v3h12v-3" stroke="currentColor" stroke-width="1.5"/></svg>`,
  sync: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M13.5 6A5.5 5.5 0 0 0 3 4.5M2.5 10A5.5 5.5 0 0 0 13 11.5" stroke="currentColor" stroke-width="1.5"/><path d="M3 1.5v3h3M13 14.5v-3h-3" stroke="currentColor" stroke-width="1.5"/></svg>`,
  download: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 2v9M4 7l4 4 4-4M2 14h12" stroke="currentColor" stroke-width="1.5"/></svg>`,
  file: `<svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M7 3h10l5 5v17H7z" stroke="currentColor" stroke-width="1.5"/><path d="M17 3v5h5" stroke="currentColor" stroke-width="1.5"/></svg>`,
};

export const loading = (rows = 3) =>
  `<div class="fade-in" style="display:grid;gap:14px">${'<div class="skeleton" style="height:90px"></div>'.repeat(rows)}</div>`;

export const errorBox = (e) =>
  `<div class="note warn"><strong>Couldn't load this view.</strong> ${esc(e.message || e)}</div>`;
