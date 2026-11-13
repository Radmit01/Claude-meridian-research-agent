export function progressHTML() {
  return `<div class="upload-progress" hidden><div class="up-track"><span></span></div><span class="mono up-label">0%</span></div>`;
}

export function setProgress(root, fraction, label) {
  const box = root.querySelector(".upload-progress");
  if (!box) return;
  box.hidden = false;
  const pct = Math.round(Math.max(0, Math.min(1, fraction)) * 100);
  box.querySelector(".up-track span").style.width = `${pct}%`;
  box.querySelector(".up-label").textContent = label || `${pct}%`;
}
