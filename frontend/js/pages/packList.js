import { api } from "../api.js";
import { esc, fmtAgo, icons } from "../utils.js";
import { emptyState } from "../components/emptyState.js";
import { openImportPackModal } from "../components/importPackModal.js";
import { toast } from "../components/toast.js";

export async function render({ view, rerender }) {
  const { packs } = await api.packs.list();
  view.innerHTML = `
    <div class="page-head fade-in"><div><div class="eyebrow">[ Research packs ]</div><h1>Generated packs</h1>
      <p>Each pack has the same four mandatory sections: Findings, Conflicts and Reconciliation, Coverage Gaps, Sources Consulted.</p></div>
      <div class="row"><button class="btn btn-quiet" data-import>${icons.upload} Import pack</button><a class="btn btn-primary" href="#/run">New run ${icons.arrow}</a></div></div>
    <div class="pack-list section stagger" style="margin-top:24px">
      ${packs.length ? packs.map((p) => `<div class="frame pack-item" data-href="#/packs/${encodeURIComponent(p.name)}" tabindex="0" role="link">
        <span class="badge ${p.qid ? "" : "custom"}">${p.qid || (p.name.startsWith("Imported_") ? "IMP" : "Q+")}</span>
        <div style="min-width:0"><div class="eyebrow">${esc(p.label)} · updated ${fmtAgo(p.updated_at)}</div>
          <h3>${esc(p.question)}</h3>
          <div class="stats-inline"><span><b>${p.stats.findings}</b> findings</span><span><b>${p.stats.sections}</b> sections</span><span><b>${p.stats.conflicts}</b> conflicts</span><span><b>${p.stats.gaps}</b> gaps</span><span><b>${p.stats.cited_documents}</b> docs cited</span></div></div>
        <div class="row">
          ${p.is_fixed ? "" : `<button class="btn btn-quiet btn-sm danger" data-delete="${esc(p.name)}">Delete</button>`}
          <span class="link-arrow">Open ${icons.arrow}</span></div></div>`).join("")
      : `<div class="frame">${emptyState({ title: "No packs yet.", text: "Run one of the fixed questions, or import a pack you already have.", action: `<a class="btn btn-primary btn-sm" href="#/run">Start a run</a>` })}</div>`}
    </div>`;

  view.querySelector("[data-import]").addEventListener("click", () =>
    openImportPackModal({ onDone: (res) => (location.hash = `#/packs/${encodeURIComponent(res.name)}`) }));
  view.querySelectorAll("[data-delete]").forEach((b) => b.addEventListener("click", async (e) => {
    e.stopPropagation();
    const name = b.dataset.delete;
    if (!confirm(`Delete ${name} from output/? This can't be undone.`)) return;
    try { await api.packs.remove(name); toast("Pack deleted"); rerender(); } catch (err) { toast(err.message, { tone: "error" }); }
  }));
}
