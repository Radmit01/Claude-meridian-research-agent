import { api } from "../api.js";
import { $, $$, esc, fmtAgo, pad, setKey, SET_NAMES, icons, statusClass } from "../utils.js";
import { citeChip, docIdBadge } from "../components/citeChip.js";
import { emptyState } from "../components/emptyState.js";
import { toast } from "../components/toast.js";
import { loadCorpus } from "../store.js";

function highlight(text, q) {
  const safe = esc(text);
  if (!q) return safe;
  const re = new RegExp(`(${esc(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  return safe.replace(re, "<mark>$1</mark>");
}

const GAP_KINDS = (r) =>
  /failed/i.test(r) ? ["r-failed", "Failed to process", ""]
  : /no extractable/i.test(r) ? ["r-empty", "Empty source", "butter"]
  : /withheld/i.test(r) ? ["r-withheld", "Withheld content", "orange"]
  : ["r-notcovered", "Not covered", "pine"];

export async function render({ view, params, onLeave }) {
  const name = decodeURIComponent(params[0]);
  const tab = params[1] || "findings";
  const [pack, corpus] = await Promise.all([api.packs.get(name), loadCorpus().catch(() => null)]);
  const titles = Object.fromEntries(((corpus && corpus.documents) || []).map((d) => [d.doc_id, d.title]));
  const s = pack.stats;
  const state = { q: "", sets: new Set(["CL", "EX", "PV"]) };

  const tabs = [
    ["findings", "Findings", s.findings],
    ["recommendations", "Focus areas", s.recommendations],
    ["conflicts", "Conflicts", s.conflicts],
    ["gaps", "Coverage gaps", s.gaps],
    ["sources", "Sources", s.sources],
  ];

  view.innerHTML = `
    <div class="page-head pack-head fade-in">
      <div style="min-width:0"><div class="eyebrow">[ Research pack ] · updated ${fmtAgo(pack.updated_at)}</div>
        <h1>${esc(pack.question)}</h1>
        <div class="pack-meta">
          <span class="tag">${s.sections} sections</span><span class="tag">${s.findings} findings</span>
          <span class="tag ${s.conflicts ? "orange" : ""}">${s.conflicts} conflict${s.conflicts === 1 ? "" : "s"}</span>
          <span class="tag butter">${s.gaps} gaps</span><span class="tag pine-soft">${s.cited_documents} docs cited</span>
        </div></div>
      <div class="pack-actions">
        <button class="btn btn-quiet btn-sm" id="copy-md">Copy markdown</button>
        <a class="btn btn-quiet btn-sm" href="${api.packs.rawUrl(name)}" download="${esc(name)}">${icons.download} Download .md</a>
        <a class="btn btn-primary btn-sm" href="#/run">Re-run</a>
      </div>
    </div>
    <nav class="tabs" role="tablist">${tabs.map(([k, label, n]) => `<button role="tab" data-tab="${k}" class="${k === tab ? "active" : ""}">${label}<span class="count">${n}</span></button>`).join("")}</nav>
    <div id="tab-body"></div>`;

  $("#copy-md").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(await api.packs.raw(name)); toast("Markdown copied"); }
    catch (e) { toast("Couldn't copy: " + e.message, { tone: "error" }); }
  });
  $$(".tabs button", view).forEach((b) => b.addEventListener("click", () => {
    history.replaceState(null, "", `#/packs/${encodeURIComponent(name)}/${b.dataset.tab}`);
    $$(".tabs button", view).forEach((x) => x.classList.toggle("active", x === b));
    paintTab(b.dataset.tab);
  }));

  function paintTab(t) {
    const body = $("#tab-body");
    if (t === "findings") return paintFindings(body);
    if (t === "recommendations") {
      body.innerHTML = pack.recommendations.length
        ? `<div class="rec-grid stagger">${pack.recommendations.map((r, i) => `<article class="frame rec"><span class="rec-n">${pad(i + 1)}</span><p>${esc(r.claim)}</p><div>${citeChip(r.citation)}</div></article>`).join("")}</div>`
        : `<div class="frame section">${emptyState({ title: "No focus areas.", text: "This pack has no Recommended Engagement Focus Areas section." })}</div>`;
      return;
    }
    if (t === "conflicts") {
      body.innerHTML = pack.conflicts.length ? pack.conflicts.map((c, i) => {
        const unresolved = /unresolved/i.test(c.resolution_basis);
        return `<article class="frame ticks conflict fade-in">
          <div class="conflict-subject"><div><div class="eyebrow">Conflict ${pad(i + 1)}</div><h3>${esc(c.subject)}</h3></div>
            <span class="tag ${unresolved ? "orange" : "pine"}">${esc(c.resolution_basis || "—")}</span></div>
          <div class="vs">
            <div class="vs-side"><div class="eyebrow">Source A</div><p>${esc(c.position_a?.position)}</p><div>${citeChip(c.position_a?.citation)}</div></div>
            <div class="vs-mid"><span>vs</span></div>
            <div class="vs-side"><div class="eyebrow">Source B</div><p>${esc(c.position_b?.position)}</p><div>${citeChip(c.position_b?.citation)}</div></div>
          </div>
          <div class="resolution"><div class="eyebrow">Reconciliation</div><p>${esc(c.resolution_note)}</p></div>
        </article>`;
      }).join("") : `<div class="frame section">${emptyState({ title: "No conflicts.", text: pack.no_conflict_note || "No contradictory evidence was detected across the corpus for this question." })}</div>`;
      return;
    }
    if (t === "gaps") {
      body.innerHTML = pack.gaps.length ? `<div class="stagger">${pack.gaps.map((g) => {
        const [c, label, tagc] = GAP_KINDS(g.reason);
        return `<article class="frame gap ${c}"><div class="rail"></div><div class="gap-body">
          <div class="row"><span class="tag ${tagc}">${label}</span>${g.source_doc_id ? citeChip({ doc_id: g.source_doc_id, ref: "" }, { label: titles[g.source_doc_id] || "source" }) : ""}</div>
          <h4>${esc(g.description)}</h4>
          <div class="gap-impact"><b>Impact on confidence.</b> ${esc(g.confidence_impact)}</div></div></article>`;
      }).join("")}</div>` : `<div class="frame section">${emptyState({ title: "No coverage gaps." })}</div>`;
      return;
    }
    if (t === "sources") paintSources(body);
  }

  function paintFindings(body) {
    body.innerHTML = `
      <div class="toolbar">
        <div class="search">${icons.search}<input class="input" id="f-search" placeholder="Search findings, e.g. sanctions" value="${esc(state.q)}"></div>
        <div class="chip-filter" id="f-sets">${["CL", "EX", "PV"].map((k) => `<button data-set="${k}" class="${state.sets.has(k) ? "on" : ""}"><i class="set-${k}"></i>${SET_NAMES[k]}</button>`).join("")}</div>
        <span class="spacer"></span><span class="muted mono" style="font-size:12px" id="f-count"></span>
      </div>
      <div class="findings-layout"><nav class="toc" id="toc"></nav><div id="f-list"></div></div>`;
    $("#f-search").addEventListener("input", (e) => { state.q = e.target.value.trim(); paintList(); });
    $$("#f-sets button").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.set;
      if (state.sets.has(k) && state.sets.size > 1) state.sets.delete(k); else state.sets.add(k);
      $$("#f-sets button").forEach((x) => x.classList.toggle("on", state.sets.has(x.dataset.set)));
      paintList();
    }));
    paintList();
  }

  let spy = null;
  onLeave(() => spy && spy.disconnect());

  function paintList() {
    const q = state.q.toLowerCase();
    let shown = 0;
    const secs = pack.sections.map((sec, si) => {
      const items = sec.findings.filter((f) => (!f.citation || state.sets.has(setKey(f.citation.doc_id))) &&
        (!q || f.claim.toLowerCase().includes(q) || (f.citation && `${f.citation.doc_id} ${f.citation.ref}`.toLowerCase().includes(q))));
      shown += items.length;
      return { sec, si, items };
    }).filter((x) => x.items.length);
    $("#f-count").textContent = `${shown} of ${s.findings} findings`;
    $("#toc").innerHTML = `<div class="eyebrow" style="padding:0 10px 10px">Sections</div>` +
      secs.map(({ sec, si, items }) => `<a href="#" data-target="sec-${si}"><span>${esc(sec.heading)}</span><span class="mono">${items.length}</span></a>`).join("");
    $("#f-list").innerHTML = secs.length ? secs.map(({ sec, si, items }) => `
      <section class="f-section" id="sec-${si}">
        <div class="f-section-head"><span class="idx">§${pad(si + 1)}</span><h3>${esc(sec.heading)}</h3><span class="mono">${items.length}</span></div>
        ${items.map((f, i) => `<div class="finding"><span class="n">${pad(i + 1)}</span><div><p>${highlight(f.claim, state.q)}</p>${citeChip(f.citation)}</div></div>`).join("")}
      </section>`).join("") : `<div class="frame">${emptyState({ title: "Nothing matches.", text: "Try a different term or turn a source set back on." })}</div>`;
    $$("#toc a").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      document.getElementById(a.dataset.target)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    if (spy) spy.disconnect();
    spy = new IntersectionObserver((entries) => {
      entries.forEach((en) => { if (en.isIntersecting) $$("#toc a").forEach((a) => a.classList.toggle("active", a.dataset.target === en.target.id)); });
    }, { rootMargin: "-80px 0px -70% 0px" });
    $$(".f-section").forEach((el) => spy.observe(el));
  }

  function paintSources(body) {
    const counts = {};
    [...pack.sections, { findings: pack.recommendations }].forEach((sec) => sec.findings.forEach((f) => {
      if (f.citation) counts[f.citation.doc_id] = (counts[f.citation.doc_id] || 0) + 1;
    }));
    pack.conflicts.forEach((c) => [c.position_a, c.position_b].forEach((p) => {
      if (p?.citation) counts[p.citation.doc_id] = (counts[p.citation.doc_id] || 0) + 1;
    }));
    const max = Math.max(1, ...Object.values(counts));
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12);
    body.innerHTML = `<div class="split section" style="margin-top:20px">
      <div class="frame"><div class="frame-head"><h3>Sources consulted</h3><span class="eyebrow">${pack.sources.length} documents</span></div>
        <div class="table-wrap"><table class="data"><thead><tr><th>DOC-ID</th><th>Title</th><th>Status</th><th style="text-align:right">Citations</th></tr></thead><tbody>
        ${pack.sources.map((r) => `<tr class="clickable" data-doc="${esc(r.doc_id)}"><td>${docIdBadge(r.doc_id)}</td>
          <td>${esc(titles[r.doc_id] || "")}${r.note ? `<div class="muted" style="font-size:12.5px">${esc(r.note)}</div>` : ""}</td>
          <td><span class="status ${statusClass(r.status)}">${esc(r.status)}</span></td><td class="num">${counts[r.doc_id] || "—"}</td></tr>`).join("")}
        </tbody></table></div></div>
      <div class="frame" style="align-self:start"><div class="frame-head"><h3>Most-cited documents</h3><span class="eyebrow">top ${top.length}</span></div>
        <div class="frame-body"><div class="bars">${top.map(([d, n]) => `<div class="bar-row"><span class="mono">${esc(d)}</span><div class="bar-track" title="${esc(titles[d] || d)}"><div class="bar-fill ${setKey(d)}" style="width:${(n / max) * 100}%"></div></div><span class="mono" style="text-align:right">${n}</span></div>`).join("")}</div>
        <div class="legend" style="margin-top:20px">${["CL", "EX", "PV"].map((k) => `<div class="legend-row"><i class="set-${k}"></i><span>${SET_NAMES[k]}</span><span class="mono">${Object.entries(counts).filter(([d]) => setKey(d) === k).reduce((a, [, n]) => a + n, 0)} citations</span></div>`).join("")}</div></div></div>
    </div>`;
  }

  paintTab(tab);
}
