// Table of runs; rows link to the run page via data-href (wired in main.js).
import { esc, fmtAgo, fmtDur } from "../utils.js";
import { emptyState } from "./emptyState.js";

export function runsTable(runs, { compact = false } = {}) {
  if (!runs.length) {
    return emptyState({
      title: "No runs yet.",
      text: "Runs started from this dashboard appear here, with their full log.",
      action: `<a class="btn btn-primary btn-sm" href="#/run">Start a run</a>`,
    });
  }
  return `<div class="table-wrap"><table class="data"><thead><tr>
    <th>Status</th><th>Question</th>${compact ? "" : "<th>Output</th>"}<th>Started</th><th style="text-align:right">Duration</th></tr></thead><tbody>
    ${runs.map((r) => `<tr class="clickable" data-href="#/run/${esc(r.id)}">
      <td><span class="status ${esc(r.status)}">${esc(r.status)}</span></td>
      <td><div class="truncate" style="max-width:${compact ? 300 : 460}px">${esc(r.question)}</div></td>
      ${compact ? "" : `<td class="mono" style="font-size:12px">${esc(r.output_name)}</td>`}
      <td class="muted" style="white-space:nowrap">${fmtAgo(r.started_at || r.created_at)}</td>
      <td class="num">${fmtDur(r.elapsed)}</td></tr>`).join("")}
  </tbody></table></div>`;
}
