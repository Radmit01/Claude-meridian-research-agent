// Document detail drawer: metadata, citable sections (cited one highlighted),
// full text, and file actions (download, replace, restore, delete).
import { api } from "../api.js";
import { esc, fmtAgo, fmtSize, icons, loading, errorBox, setKey } from "../utils.js";
import { openDrawer, setDrawer, closeDrawer } from "./drawer.js";
import { openUploadDocModal } from "./uploadDocModal.js";
import { getState, loadHealth, updateCorpus } from "../store.js";
import { toast } from "./toast.js";

const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

export async function openDocDrawer(docId, ref = "", { onChange } = {}) {
  openDrawer(`<div class="drawer-body">${loading(4)}</div>`);
  let d;
  try { d = await api.corpus.get(docId); }
  catch (e) { setDrawer(`<div class="drawer-body">${errorBox(e)}</div>`); return; }

  const nref = norm(ref);
  const hitIdx = nref ? d.outline.findIndex((o) => { const n = norm(o.ref); return n && (n === nref || n.includes(nref) || nref.includes(n)); }) : -1;
  const busy = !!getState().activeRun;
  await loadHealth();
  const editsAllowed = getState().health?.allow_corpus_edits !== false;
  const editsTitle = "Corpus edits are disabled — the hackathon rules require using only the fixed corpus supplied. Set ALLOW_CORPUS_EDITS=1 to override for local testing.";
  const disabledAttr = (reason) => (reason ? `disabled title="${esc(reason)}"` : "");

  const drawer = setDrawer(`
    <div class="drawer-head">
      <div><div class="row"><span class="cite ${setKey(d.doc_id)}" style="pointer-events:none"><span class="id">${esc(d.doc_id)}</span><span class="ref">${esc(d.format)}</span></span>
        <span class="eyebrow">${esc(d.source_set)}</span>${d.is_custom ? `<span class="tag butter">uploaded</span>` : ""}</div>
        <h2>${esc(d.title)}</h2>
        <div class="mono muted" style="font-size:12px">${esc(d.filename || "file not found")} · ${fmtSize(d.size)}${d.modified_at ? ` · modified ${fmtAgo(d.modified_at)}` : ""}</div></div>
      <button class="icon-btn" data-x aria-label="Close">${icons.close}</button>
    </div>
    <div class="drawer-actions">
      ${d.filename ? `<a class="btn btn-quiet btn-sm" href="${api.corpus.fileUrl(d.doc_id)}">${icons.download} Download</a>` : ""}
      <button class="btn btn-quiet btn-sm" data-act="replace" ${!editsAllowed ? disabledAttr(editsTitle) : busy ? "disabled" : ""}>${icons.upload} Replace file</button>
      ${d.backups.length ? `<button class="btn btn-quiet btn-sm" data-act="restore" ${!editsAllowed ? disabledAttr(editsTitle) : busy ? "disabled" : `title="${esc(d.backups[0])}"`}>Restore previous</button>` : ""}
      ${d.is_custom ? `<button class="btn btn-quiet btn-sm danger" data-act="delete" ${!editsAllowed ? disabledAttr(editsTitle) : busy ? "disabled" : ""}>Delete</button>` : ""}
    </div>
    ${!editsAllowed ? `<div class="note" style="margin:0 20px 16px">Corpus edits are disabled — fixed-corpus rule. Set <span class="mono">ALLOW_CORPUS_EDITS=1</span> to override for local testing.</div>` : ""}
    <div class="drawer-body">
      ${ref ? `<div class="note ${hitIdx >= 0 ? "pine" : "warn"}" style="margin-bottom:16px">Cited as <strong class="mono" style="font-size:12.5px">[${esc(d.doc_id)}, ${esc(ref)}]</strong>${hitIdx >= 0 ? "" : " — no exactly matching section label in the extracted outline."}</div>` : ""}
      ${d.extraction_error ? `<div class="note warn" style="margin-bottom:16px">${esc(d.extraction_error)}</div>` : ""}
      ${d.status && d.status !== "ok" ? `<div class="note warn" style="margin-bottom:16px">This document ${esc(d.status)}${d.error ? `: ${esc(d.error)}` : ""}. Packs should list it under Coverage Gaps.</div>` : ""}
      ${d.file_count > 1 ? `<div class="note warn" style="margin-bottom:16px">${d.file_count} files match ${esc(d.doc_id)}*; extraction needs exactly one.</div>` : ""}
      ${d.outline.length ? `<div class="eyebrow" style="margin-bottom:10px">Citable sections · ${d.outline.length}</div>
        ${d.outline.map((o, i) => `<details class="outline-item ${i === hitIdx ? "hit" : ""}" ${i === hitIdx ? 'open id="hit"' : ""}><summary>${esc(o.ref)}</summary>${o.preview ? `<div class="prev">${esc(o.preview)}</div>` : ""}</details>`).join("")}` : ""}
      ${d.text ? `<details style="margin-top:18px"><summary class="btn btn-quiet btn-sm" style="list-style:none;display:inline-flex">Show full extracted text</summary><div class="doc-text" style="margin-top:10px">${esc(d.text)}</div></details>` : ""}
    </div>`);

  drawer.querySelector("[data-x]").addEventListener("click", closeDrawer);
  drawer.querySelector("#hit")?.scrollIntoView({ block: "center" });

  const after = async (msg) => {
    toast(msg);
    updateCorpus(await api.corpus.list());
    onChange && onChange();
  };
  drawer.querySelector('[data-act="replace"]')?.addEventListener("click", () => {
    closeDrawer();
    openUploadDocModal({ mode: "replace", docId: d.doc_id, onDone: () => onChange && onChange() });
  });
  drawer.querySelector('[data-act="restore"]')?.addEventListener("click", async () => {
    if (!confirm(`Restore the previous file for ${d.doc_id}? The current file is removed.`)) return;
    try { const r = await api.corpus.restore(d.doc_id); await after(`Restored ${r.restored}`); openDocDrawer(d.doc_id, ref, { onChange }); }
    catch (e) { toast(e.message, { tone: "error" }); }
  });
  drawer.querySelector('[data-act="delete"]')?.addEventListener("click", async () => {
    if (!confirm(`Delete ${d.doc_id} from the corpus? Its file moves to Corpus/.backup/.`)) return;
    try { await api.corpus.remove(d.doc_id); closeDrawer(); await after(`${d.doc_id} deleted`); }
    catch (e) { toast(e.message, { tone: "error" }); }
  });
}
