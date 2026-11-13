// Upload a corpus document: add a new DOC-ID or replace an existing file.
import { api } from "../api.js";
import { esc, SET_LABELS } from "../utils.js";
import { loadCorpus, getState, updateCorpus } from "../store.js";
import { openModal, closeModal } from "./modal.js";
import { dropzoneHTML, bindDropzone } from "./dropzone.js";
import { progressHTML, setProgress } from "./progressBar.js";
import { toast } from "./toast.js";

const ACCEPT = ".docx,.pdf,.xlsx";

/**
 * @param {{mode?: "new"|"replace", docId?: string, onDone?: (result) => void}} opts
 */
export async function openUploadDocModal({ mode = "new", docId = "", onDone } = {}) {
  const corpus = await loadCorpus().catch(() => ({ documents: [] }));
  const docs = corpus.documents || [];
  const busy = getState().activeRun;
  let file = null;

  const modal = openModal({
    title: "Upload a corpus document",
    eyebrow: "Corpus · upload",
    width: 600,
    body: `
      <div class="segmented" role="tablist">
        <button data-mode="new" role="tab">Add new document</button>
        <button data-mode="replace" role="tab">Replace existing file</button>
      </div>
      <div class="form-grid">
        <div data-for="new">
          <label class="field"><span class="field-label">Source set</span>
            <select class="input" name="set">${Object.entries(SET_LABELS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
          <div class="form-row">
            <label class="field"><span class="field-label">DOC-ID <span class="muted">(optional)</span></span>
              <input class="input mono" name="docid" placeholder="auto, e.g. CL-11" maxlength="5"></label>
            <label class="field" style="flex:2"><span class="field-label">Title</span>
              <input class="input" name="title" placeholder="Defaults to the file name" maxlength="120"></label>
          </div>
        </div>
        <div data-for="replace">
          <label class="field"><span class="field-label">Document to replace</span>
            <select class="input" name="target">${docs.map((d) => `<option value="${esc(d.doc_id)}" data-format="${esc(d.format)}">${esc(d.doc_id)} · ${esc(d.title)} (.${esc(d.format)})</option>`).join("")}</select></label>
          <p class="field-hint" data-hint></p>
        </div>
        ${dropzoneHTML({ accept: ACCEPT, hint: ".docx, .pdf or .xlsx · up to 25 MB" })}
        ${progressHTML()}
        ${busy ? `<div class="note warn">A research run is in progress. Uploads are blocked until it finishes so the corpus doesn't change mid-run.</div>` : ""}
        <div class="note" data-error hidden></div>
      </div>`,
    footer: `<span class="muted" style="font-size:13px" data-summary></span><span class="spacer"></span>
      <button class="btn btn-quiet btn-sm" data-close>Cancel</button>
      <button class="btn btn-primary btn-sm" data-submit disabled>Upload</button>`,
  });

  const q = (sel) => modal.querySelector(sel);
  const submit = q("[data-submit]");
  const errorBox = q("[data-error]");

  const paint = () => {
    modal.querySelectorAll(".segmented button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    modal.querySelectorAll("[data-for]").forEach((el) => (el.hidden = el.dataset.for !== mode));
    const opt = q('[name="target"]').selectedOptions[0];
    const target = docs.find((d) => d.doc_id === (opt && opt.value));
    q("[data-hint]").innerHTML = target
      ? target.is_custom
        ? "Uploaded document: any supported file type is accepted."
        : `One of the original 28: the new file must also be <b>.${esc(target.format)}</b>. The current file is kept in <span class="mono">Corpus/.backup/</span> and can be restored.`
      : "";
    const summary = file
      ? mode === "new"
        ? `Adds ${q('[name="docid"]').value.trim().toUpperCase() || "a new " + q('[name="set"]').value + " DOC-ID"}`
        : `Replaces ${q('[name="target"]').value}`
      : "";
    q("[data-summary]").textContent = summary;
    submit.disabled = !file || !!busy;
  };

  modal.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => { mode = b.dataset.mode; paint(); }));
  modal.querySelectorAll("select, input").forEach((el) => el.addEventListener("input", paint));
  if (docId) q('[name="target"]').value = docId;
  bindDropzone(modal, { accept: ACCEPT, onFile: (f) => { file = f; errorBox.hidden = true; paint(); } });
  paint();

  submit.addEventListener("click", async () => {
    submit.disabled = true;
    submit.textContent = "Uploading…";
    errorBox.hidden = true;
    const payload = mode === "new"
      ? { file, mode, setKey: q('[name="set"]').value, docId: q('[name="docid"]').value.trim().toUpperCase(), title: q('[name="title"]').value.trim() }
      : { file, mode, docId: q('[name="target"]').value };
    try {
      const res = await api.corpus.upload(payload, (p) => setProgress(modal, p, p < 1 ? undefined : "Extracting…"));
      setProgress(modal, 1, "Done");
      const listing = await api.corpus.list();
      updateCorpus(listing);
      closeModal();
      toast(`${res.doc_id} ${res.action}${res.document.status ? ` · ${res.document.status}` : ""}`);
      onDone && onDone(res);
    } catch (e) {
      errorBox.hidden = false;
      errorBox.className = "note warn";
      errorBox.textContent = e.message;
      submit.disabled = false;
      submit.textContent = "Upload";
    }
  });
}
