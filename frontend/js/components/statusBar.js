// Topbar status pill + sidebar live-run card. Re-renders from the store.
import { $, esc, fmtDur } from "../utils.js";
import { subscribe } from "../store.js";
import { STAGES } from "./pipeline.js";

function paint(run) {
  const pill = $("#status-pill");
  const box = $("#sidebar-run");
  if (run) {
    const stage = STAGES[Math.max(0, Math.min(7, run.stage))];
    const pct = Math.round((Math.max(0, run.stage) / 8) * 100);
    pill.className = "status-pill running";
    pill.querySelector(".label").textContent = `Running · ${fmtDur(run.elapsed)}`;
    pill.onclick = () => (location.hash = `#/run/${run.id}`);
    pill.style.cursor = "pointer";
    box.hidden = false;
    box.innerHTML = `<a href="#/run/${esc(run.id)}" style="text-decoration:none;color:inherit;display:block">
      <div class="eyebrow">Live run · ${esc(run.id)}</div>
      <div class="sr-stage">${esc(stage ? stage.name : "Starting")}</div>
      <div class="bar"><span style="width:${pct}%"></span></div>
      <div class="sr-meta"><span>Stage ${Math.max(0, run.stage)}/7</span><span>${fmtDur(run.elapsed)}</span></div></a>`;
  } else {
    pill.className = "status-pill";
    pill.querySelector(".label").textContent = "Pipeline idle";
    pill.onclick = null;
    pill.style.cursor = "";
    box.hidden = true;
  }
}

export function mountStatusBar() {
  subscribe("activeRun", paint);
  paint(null);
}
