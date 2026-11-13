// Import an existing research pack (.md) into output/.
import { api } from "../api.js";
import { openModal, closeModal } from "./modal.js";
import { dropzoneHTML, bindDropzone } from "./dropzone.js";
import { progressHTML, setProgress } from "./progressBar.js";
import { toast } from "./toast.js";

export function openImportPackModal({ onDone } = {}) {
  let file = null;
  const modal = openModal({
    title: "Import a research pack",
    eyebrow: "Packs · upload",
    body: `<div class="form-grid">
      <p class="muted" style="margin:0">Upload a pack produced by <span class="mono">run_qN.py</span> or another machine. It must have the
      <span class="mono"># Research Pack:</span> title and the four mandatory sections.</p>
      ${dropzoneHTML({ accept: ".md", hint: "Markdown (.md) · up to 5 MB" })}
      ${progressHTML()}
      <div class="note warn" data-error hidden></div></div>`,
    footer: `<span class="spacer"></span><button class="btn btn-quiet btn-sm" data-close>Cancel</button>
      <button class="btn btn-primary btn-sm" data-submit disabled>Import pack</button>`,
  });
  const submit = modal.querySelector("[data-submit]");
  const err = modal.querySelector("[data-error]");
  bindDropzone(modal, { accept: ".md", onFile: (f) => { file = f; submit.disabled = !f; err.hidden = true; } });
  submit.addEventListener("click", async () => {
    submit.disabled = true;
    try {
      const res = await api.packs.import(file, (p) => setProgress(modal, p));
      closeModal();
      toast("Pack imported");
      onDone && onDone(res);
    } catch (e) {
      err.hidden = false;
      err.textContent = e.message;
      submit.disabled = false;
    }
  });
}
