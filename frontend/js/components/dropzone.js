// Drag-and-drop file picker. Calls onFile(File) with the chosen file.
import { esc, fmtSize, icons } from "../utils.js";

export function dropzoneHTML({ accept, hint }) {
  return `<label class="dropzone" data-dropzone>
    <input type="file" accept="${esc(accept)}" hidden>
    <span class="dz-icon">${icons.file}</span>
    <span class="dz-empty"><strong>Drop a file here</strong> or <u>browse</u><br><span class="muted">${esc(hint)}</span></span>
    <span class="dz-file" hidden></span>
  </label>`;
}

export function bindDropzone(root, { accept, onFile }) {
  const zone = root.querySelector("[data-dropzone]");
  const input = zone.querySelector("input");
  const exts = accept.split(",").map((s) => s.trim().toLowerCase());
  const pick = (file) => {
    if (!file) return;
    const ok = exts.some((e) => file.name.toLowerCase().endsWith(e));
    zone.classList.toggle("invalid", !ok);
    zone.querySelector(".dz-empty").hidden = true;
    const f = zone.querySelector(".dz-file");
    f.hidden = false;
    f.innerHTML = `<strong>${esc(file.name)}</strong><span class="mono muted">${fmtSize(file.size)}${ok ? "" : ` · not ${esc(accept)}`}</span><span class="link-like">Choose another</span>`;
    onFile(ok ? file : null, file);
  };
  input.addEventListener("change", () => pick(input.files[0]));
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", (e) => pick(e.dataTransfer.files[0]));
}
