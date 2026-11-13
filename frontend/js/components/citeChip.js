// [DOC-ID, ref] citation chip. Clicking any [data-doc] element opens the
// document drawer (wired once in main.js).
import { esc, setKey } from "../utils.js";

export function citeChip(c, { label } = {}) {
  if (!c) return "";
  const ref = label ?? c.ref ?? "";
  return `<button class="cite ${esc(setKey(c.doc_id))}" data-doc="${esc(c.doc_id)}" data-ref="${esc(c.ref || "")}" title="${esc(c.doc_id)}${ref ? ", " + esc(ref) : ""}"><span class="id">${esc(c.doc_id)}</span>${ref ? `<span class="ref">${esc(ref)}</span>` : ""}</button>`;
}

export function docIdBadge(docId) {
  return `<span class="cite ${esc(setKey(docId))}" style="pointer-events:none"><span class="id">${esc(docId)}</span></span>`;
}
