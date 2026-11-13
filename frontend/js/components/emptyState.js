import { esc } from "../utils.js";

export function emptyState({ title, text = "", action = "" }) {
  return `<div class="empty-state"><div class="big">${esc(title)}</div>${text ? `<p>${esc(text)}</p>` : ""}${action}</div>`;
}
