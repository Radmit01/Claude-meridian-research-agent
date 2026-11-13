// Pipeline diagram (overview) and compact stage list (new-run page).
import { esc, pad } from "../utils.js";

export const STAGES = [
  { name: "Gateway auth", detail: "Atlas env + Entra bearer token", tag: "auth" },
  { name: "Triage", detail: "Open and classify every corpus document", tag: "single pass" },
  { name: "Retrieval", detail: "Select the documents worth deep analysis", tag: "1 agent" },
  { name: "Document analysis", detail: "Parallel batches extract cited findings", tag: "parallel" },
  { name: "Conflict detection", detail: "Cross-source contradictions + resolution basis", tag: "1 agent" },
  { name: "Synthesis + recommendations", detail: "Sections, coverage gaps, focus areas", tag: "parallel" },
  { name: "Drafting", detail: "Client-ready prose, citations untouched", tag: "parallel" },
  { name: "Render + validate", detail: "Deterministic markdown, citation checks", tag: "deterministic" },
];

const tagClass = (t) => (t === "parallel" ? "butter" : t === "deterministic" ? "ink" : "");

export function pipelineDiagram(stages = STAGES) {
  return `<div class="pipeline stagger">${stages.map((s, i) => {
    const t = STAGES[i]?.tag || "";
    return `<div class="p-step ${t === "deterministic" ? "det" : ""}">
      <span class="p-num">${pad(i)}</span>
      <div class="p-name">${esc(s.name)}</div>
      <div class="p-detail">${esc(s.detail)}</div>
      <div class="p-tag"><span class="tag ${tagClass(t)}">${esc(t)}</span></div>
    </div>`;
  }).join("")}</div>`;
}

export function stageListStatic() {
  return `<div class="frame"><div class="frame-head"><h3>What will run</h3><span class="eyebrow">8 stages</span></div>
    <ul class="stage-list">${STAGES.map((s, i) => `<li class="stage-row"><span class="s-ico">${i}</span>
      <div><div class="s-name">${esc(s.name)}</div><div class="s-detail">${esc(s.detail)}</div></div>
      <span class="tag ${tagClass(s.tag)}">${esc(s.tag)}</span></li>`).join("")}</ul></div>`;
}

/** Live stage list for a run snapshot. */
export function stageListLive(run, stages = STAGES) {
  const live = run.status === "running" || run.status === "queued";
  const done = run.status === "succeeded";
  return stages.map((s, i) => {
    let cls = "", ico = String(i);
    if (done || i < run.stage) { cls = "done"; ico = "✓"; }
    else if (i === run.stage && live) cls = "active";
    else if (i === Math.max(0, run.stage) && (run.status === "failed" || run.status === "cancelled")) { cls = "failed"; ico = "!"; }
    const dur = (run.stage_durations || {})[String(i)];
    return `<li class="stage-row ${cls}"><span class="s-ico">${ico}</span>
      <div><div class="s-name">${esc(s.name)}</div><div class="s-detail">${esc(s.detail)}</div></div>
      <span class="s-time">${dur != null ? dur.toFixed(1) + "s" : cls === "active" ? "running" : ""}</span></li>`;
  }).join("");
}
