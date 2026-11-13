// Transient status message at the bottom of the screen.
import { $ } from "../utils.js";

let timer;
export function toast(message, { tone = "default", ms = 2600 } = {}) {
  const el = $("#toast");
  el.textContent = message;
  el.dataset.tone = tone;
  el.classList.add("show");
  clearTimeout(timer);
  timer = setTimeout(() => el.classList.remove("show"), ms);
}
