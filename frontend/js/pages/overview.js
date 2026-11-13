import { api } from "../api.js";
import { esc, fmtAgo, icons } from "../utils.js";
import { pipelineDiagram } from "../components/pipeline.js";
import { runsTable } from "../components/runsTable.js";
import { openUploadDocModal } from "../components/uploadDocModal.js";

export async function render({ view, rerender }) {
  const o = await api.overview();
  const packByName = Object.fromEntries(o.packs.map((p) => [p.name, p]));
  const sets = o.corpus.sets;
  const setEntries = [
    ["CL", "Set A — Client materials", sets["Set A - Client materials"] || 0],
    ["EX", "Set B — External context", sets["Set B - External context"] || 0],
    ["PV", "Set C — Internal Protiviti", sets["Set C - Internal Protiviti material"] || 0],
  ];
  const total = setEntries.reduce((a, s) => a + s[2], 0) || 1;

  view.innerHTML = `
    <section class="hero fade-in">
      <div>
        <div class="eyebrow"><b>●</b> Multi-agent research · Meridian Financial Group</div>
        <h1>Pre-engagement research, <em>cited to the section.</em></h1>
        <p>Seven agent roles read the corpus, reconcile what the client says against what regulators and the press say, and hand back a pack where every claim points to a DOC-ID and section.</p>
        <div class="hero-actions">
          <a class="btn btn-primary" href="#/run">Start a research run ${icons.arrow}</a>
          <button class="btn btn-ghost" data-upload>${icons.upload} Upload document</button>
        </div>
      </div>
      <div class="kpis stagger">
        <div class="kpi"><div class="eyebrow">Corpus documents</div><div class="value">${o.corpus.documents}</div><div class="sub">${o.corpus.cited} cited · synced ${fmtAgo(o.corpus.last_synced_at)}</div></div>
        <div class="kpi"><div class="eyebrow">Findings</div><div class="value">${o.totals.findings}</div><div class="sub">across ${o.packs.length} research pack${o.packs.length === 1 ? "" : "s"}</div></div>
        <div class="kpi accent"><div class="eyebrow">Conflicts flagged</div><div class="value">${o.totals.conflicts}</div><div class="sub">client vs. external accounts</div></div>
        <div class="kpi"><div class="eyebrow">Coverage gaps</div><div class="value">${o.totals.gaps}</div><div class="sub">${o.totals.recommendations} recommended focus areas</div></div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div><div class="eyebrow">[ 01 ] The three fixed questions</div><h2>Research packs</h2></div>
        <a class="link-arrow" href="#/packs">All packs ${icons.arrow}</a>
      </div>
      <div class="q-grid stagger">
        ${o.questions.map((q) => {
          const p = packByName[q.output_name];
          const s = p ? p.stats : null;
          return `<article class="frame ticks q-card">
            <div class="q-top"><span class="q-id">${q.id}</span>${p ? `<span class="tag pine-soft">Pack ready</span>` : `<span class="tag">Not generated</span>`}</div>
            <h3>${esc(q.label)}</h3>
            <p class="q-text">${esc(q.question)}</p>
            <div class="q-stats">
              <div><strong>${s ? s.findings : "—"}</strong><span>Findings</span></div>
              <div><strong>${s ? s.conflicts : "—"}</strong><span>Conflicts</span></div>
              <div><strong>${s ? s.gaps : "—"}</strong><span>Gaps</span></div>
              <div><strong>${s ? s.cited_documents : "—"}</strong><span>Docs cited</span></div>
            </div>
            <div class="q-actions">
              ${p ? `<a class="btn btn-ink btn-sm" href="#/packs/${encodeURIComponent(q.output_name)}">Open pack</a>` : ""}
              <a class="btn btn-quiet btn-sm" href="#/run?q=${q.id}">${p ? "Re-run" : "Run now"}</a>
            </div>
          </article>`;
        }).join("")}
      </div>
    </section>

    <section class="section">
      <div class="section-head"><div><div class="eyebrow">[ 02 ] Coordinator + 7 subagent roles</div><h2>How a pack gets made</h2></div></div>
      ${pipelineDiagram(o.stages)}
    </section>

    <section class="section split">
      <div class="frame">
        <div class="frame-head"><h3>Recent runs</h3><a class="link-arrow" href="#/runs">History ${icons.arrow}</a></div>
        ${runsTable(o.recent_runs, { compact: true })}
      </div>
      <div class="frame">
        <div class="frame-head"><h3>Corpus composition</h3><a class="link-arrow" href="#/corpus">Open corpus ${icons.arrow}</a></div>
        <div class="frame-body">
          <div class="comp-bar">${setEntries.map(([k, , n]) => `<div class="set-${k}" style="flex:${n}">${k} · ${n}</div>`).join("")}</div>
          <div class="legend">
            ${setEntries.map(([k, label, n]) => `<div class="legend-row"><i class="set-${k}"></i><span>${esc(label)}</span><span class="mono">${n} docs · ${Math.round((n / total) * 100)}%</span></div>`).join("")}
          </div>
          <div class="note pine" style="margin-top:18px">The corpus deliberately embeds one cross-source conflict (CL-05 vs EX-07) and one broken source (PV-06). Both should show up in a correct pack.</div>
        </div>
      </div>
    </section>`;

  view.querySelector("[data-upload]").addEventListener("click", () => openUploadDocModal({ onDone: rerender }));
}
