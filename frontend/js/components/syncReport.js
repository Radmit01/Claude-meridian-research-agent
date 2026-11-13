// Result of POST /api/corpus/sync, shown on the corpus page.
import { esc, fmtAgo } from "../utils.js";
import { docIdBadge } from "./citeChip.js";

const LABELS = {
  indexed: ["First sync", "pine-soft"],
  added: ["Added", "pine"],
  modified: ["Modified", "butter"],
  restored: ["File back", "pine-soft"],
  missing: ["File missing", "orange"],
  removed: ["Removed", "orange-soft"],
};

export function syncReport(res) {
  const changes = res.changes || [];
  const summary = Object.entries(res.summary || {})
    .map(([k, n]) => `<span class="tag ${k === "unchanged" ? "" : (LABELS[k] || [])[1] || ""}">${n} ${esc(k)}</span>`)
    .join("");
  const rows = changes.filter((c) => c.change !== "indexed");
  return `<div class="frame sync-report fade-in">
    <div class="frame-head"><h3>Sync complete</h3><span class="eyebrow">${fmtAgo(res.synced_at)} · ${res.duration}s</span></div>
    <div class="frame-body" style="display:grid;gap:12px">
      <div class="row">${summary}</div>
      ${rows.length ? `<ul class="change-list">${rows.map((c) => {
        const [label, cls] = LABELS[c.change] || [c.change, ""];
        return `<li data-doc="${esc(c.doc_id)}">${docIdBadge(c.doc_id)}<span class="tag ${cls}">${esc(label)}</span><span class="muted mono" style="font-size:12px">${esc(c.status || "")}</span></li>`;
      }).join("")}</ul>` : `<p class="muted" style="margin:0">${changes.length ? "Baseline recorded for every document." : "No changes since the last sync."}</p>`}
      ${res.untracked_files && res.untracked_files.length ? `<div class="note warn"><strong>${res.untracked_files.length} file(s) in Corpus/ aren't linked to any DOC-ID</strong> and will be ignored by runs: <span class="mono" style="font-size:12px">${res.untracked_files.map(esc).join(", ")}</span>. Upload them here to give them an ID.</div>` : ""}
    </div></div>`;
}
