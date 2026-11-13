// Centered dialog. openModal returns the dialog element; the caller wires events.
import { $, esc, icons } from "../utils.js";

let onCloseCb = null;

export function openModal({ title, eyebrow = "", body, footer = "", width = 560, onClose } = {}) {
  closeModal();
  const root = $("#modal-root");
  root.innerHTML = `
    <div class="modal-scrim" data-close></div>
    <div class="modal fade-in" role="dialog" aria-modal="true" aria-label="${esc(title)}" style="max-width:${width}px">
      <div class="modal-head">
        <div>${eyebrow ? `<div class="eyebrow">${esc(eyebrow)}</div>` : ""}<h2>${esc(title)}</h2></div>
        <button class="icon-btn" data-close aria-label="Close">${icons.close}</button>
      </div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ""}
    </div>`;
  root.hidden = false;
  onCloseCb = onClose || null;
  root.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
  const first = root.querySelector(".modal-body select, .modal-body input:not([type=file]), .modal-body textarea");
  if (first) setTimeout(() => first.focus(), 30);
  return root.querySelector(".modal");
}

export function closeModal() {
  const root = $("#modal-root");
  if (!root || root.hidden) return;
  root.hidden = true;
  root.innerHTML = "";
  const cb = onCloseCb;
  onCloseCb = null;
  if (cb) cb();
}
