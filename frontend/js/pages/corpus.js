import { api } from "../api.js";
import { esc, fmtAgo, fmtSize, icons, statusClass, SET_LABELS } from "../utils.js";
import { loadCorpus, loadHealth, updateCorpus, getState, subscribe } from "../store.js";
import { openUploadDocModal } from "../components/uploadDocModal.js";
import { syncReport } from "../components/syncReport.js";
import { toast } from "../components/toast.js";

let lastReport = null;

export async function render({ view, onLeave }) {
  let data = await loadCorpus(true);
  await loadHealth();
  let filter = "all";
  let q = "";

  const paint = () => {
    const c = data.counts;
    const busy = !!getState().activeRun;
    const editsAllowed = getState().health?.allow_corpus_edits !== false;
    const match = (d) =>
      (filter === "all" || (filter === "custom" ? d.is_custom : filter === "issues" ? statusClass(d.status) !== "ok" || !d.filename : true)) &&
      (!q || `${d.doc_id} ${d.title} ${d.filename || ""}`.toLowerCase().includes(q));
    view.innerHTML = `
      <div class="page-head fade-in"><div><div class="eyebrow">[ Corpus ] · last sync ${fmtAgo(data.last_synced_at)}</div><h1>${c.total} documents, three source sets</h1>
        <p>Every run reads from this corpus. Upload a new document, replace a file, or sync after changing files in <span class="mono">Corpus/</span> by hand.</p></div>
        <div class="row">
          <button class="btn btn-quiet" data-sync>${icons.sync} Sync corpus</button>
          ${editsAllowed
            ? `<button class="btn btn-primary" data-upload ${busy ? "disabled title='A run is in progress'" : ""}>${icons.upload} Upload document</button>`
            : `<button class="btn btn-primary" disabled title="Corpus edits are disabled — the hackathon rules require using only the fixed corpus supplied. Set ALLOW_CORPUS_EDITS=1 to override for local testing.">${icons.upload} Upload document</button>`}
        </div></div>
      ${!editsAllowed ? `<div class="note" style="margin-top:12px">Corpus edits (upload/replace/restore/delete) are disabled — fixed-corpus rule. Set <span class="mono">ALLOW_CORPUS_EDITS=1</span> to override for local testing.</div>` : ""}
      ${data.extraction_error ? `<div class="note warn" style="margin-top:20px">${esc(data.extraction_error)}</div>` : ""}
      <div class="stat-strip section" style="margin-top:24px">
        <div><span class="eyebrow">Readable</span><strong>${data.extraction_error ? "—" : c.ok}</strong></div>
        <div><span class="eyebrow">Empty</span><strong>${data.extraction_error ? "—" : c.empty}</strong></div>
        <div><span class="eyebrow">Failed</span><strong>${data.extraction_error ? "—" : c.failed}</strong></div>
        <div><span class="eyebrow">Missing file</span><strong>${c.missing}</strong></div>
        <div><span class="eyebrow">Uploaded</span><strong>${c.custom}</strong></div>
      </div>
      <div id="sync-slot" style="margin-top:16px">${lastReport ? syncReport(lastReport) : ""}</div>
      <div class="toolbar">
        <div class="search">${icons.search}<input class="input" id="c-search" placeholder="Search by DOC-ID, title or file" value="${esc(q)}"></div>
        <div class="chip-filter">${[["all", "All"], ["issues", "Needs attention"], ["custom", "Uploaded"]].map(([k, l]) => `<button data-filter="${k}" class="${filter === k ? "on" : ""}">${l}</button>`).join("")}</div>
      </div>
      <div class="corpus-cols stagger">
        ${Object.entries(SET_LABELS).map(([k, label]) => {
          const docs = data.documents.filter((d) => d.set_key === k && match(d));
          return `<div class="frame corpus-col"><div class="frame-head"><i class="set-${k}"></i><h3>${label}</h3><span class="spacer"></span><span class="eyebrow">${docs.length}</span></div>
            ${docs.length ? docs.map((d) => `<button class="doc-row" data-doc="${esc(d.doc_id)}"><span class="d-id">${esc(d.doc_id)}</span>
              <span><span class="d-title">${esc(d.title)} ${d.is_custom ? `<span class="tag butter" style="margin-left:4px">new</span>` : ""}${d.has_backup && !d.is_custom ? `<span class="tag" style="margin-left:4px">replaced</span>` : ""}</span>
              <span class="d-meta" style="display:block">${esc(d.format)} · ${fmtSize(d.size)}${d.outline_count != null ? ` · ${d.outline_count} sections` : ""}${!d.filename ? " · no file" : ""}</span></span>
              <span class="d-status ${d.filename ? statusClass(d.status) : "failed"}" title="${esc(d.filename ? d.status || "not extracted" : "file missing")}"></span></button>`).join("")
            : `<div class="muted" style="padding:16px;font-size:13.5px">No documents match.</div>`}</div>`;
        }).join("")}
      </div>`;

    view.querySelector("[data-upload]").addEventListener("click", () => openUploadDocModal({ onDone: async () => { data = await loadCorpus(); paint(); } }));
    view.querySelector("[data-sync]").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.innerHTML = `${icons.sync} Syncing…`;
      btn.classList.add("spinning");
      try {
        const res = await api.corpus.sync(e.shiftKey);
        lastReport = res;
        data = { documents: res.documents, counts: res.counts, extraction_error: res.extraction_error, last_synced_at: res.synced_at };
        updateCorpus(data);
        toast(`Synced · ${res.changes.filter((x) => x.change !== "indexed").length} change(s)`);
        paint();
      } catch (err) {
        toast(err.message, { tone: "error" });
        btn.disabled = false;
        btn.innerHTML = `${icons.sync} Sync corpus`;
      }
    });
    view.querySelector("#c-search").addEventListener("input", (e) => {
      q = e.target.value.trim().toLowerCase();
      const pos = e.target.selectionStart;
      paint();
      const inp = view.querySelector("#c-search");
      inp.focus();
      inp.setSelectionRange(pos, pos);
    });
    view.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => { filter = b.dataset.filter; paint(); }));
  };

  paint();
  // Drawer actions (replace/restore/delete) update the store; re-render from it.
  onLeave(subscribe("corpus", (c) => { if (c && c !== data) { data = { ...data, ...c }; paint(); } }));
  onLeave(subscribe("activeRun", () => paint()));
}
