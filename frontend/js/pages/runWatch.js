import { api } from "../api.js";
import { $, esc, fmtClock, fmtDur, icons } from "../utils.js";
import { stageListLive } from "../components/pipeline.js";
import { toast } from "../components/toast.js";
import { setState, pollActiveRun } from "../store.js";

export async function render({ view, params, onLeave }) {
  const id = params[0];
  let run = await api.runs.get(id);
  const stages = run.stages;
  let lastTick = Date.now();

  view.innerHTML = `
    <div class="page-head fade-in">
      <div style="min-width:0"><div class="eyebrow">[ Run ${esc(run.id)} ]</div>
        <h1 style="font-size:clamp(22px,2.4vw,30px);max-width:40ch">${esc(run.question)}</h1>
        <p class="mono" style="font-size:12px">→ output/${esc(run.output_name)}</p></div>
      <div class="row"><div><div class="eyebrow">Elapsed</div><div class="timer" id="timer">00:00</div></div>
        <button class="btn btn-quiet btn-sm" id="cancel-btn">Cancel run</button></div>
    </div>
    <div id="result" style="margin-top:20px"></div>
    <div class="run-layout section" style="margin-top:20px">
      <div class="frame ticks">
        <div class="frame-head"><h3>Pipeline</h3><span class="status" id="run-status"></span></div>
        <ul class="stage-list" id="stages"></ul>
        <div class="progress"><span id="progress" style="width:0"></span></div>
      </div>
      <div>
        <div class="console-head"><span class="lights"><i></i><i></i><i></i></span><span>coordinator log</span><label style="display:flex;gap:6px;align-items:center;cursor:pointer"><input type="checkbox" id="follow" checked> follow</label></div>
        <div class="console" id="console"><div class="console-empty">Waiting for output…</div></div>
      </div>
    </div>`;

  const consoleEl = $("#console");
  let lineCount = 0;
  const appendEvent = (ev) => {
    if (lineCount === 0) consoleEl.innerHTML = "";
    lineCount++;
    const div = document.createElement("div");
    div.className = `ln ${ev.kind}`;
    div.innerHTML = `<time>${fmtClock(ev.t)}</time><span>${esc(ev.text)}</span>`;
    consoleEl.appendChild(div);
    if ($("#follow").checked) consoleEl.scrollTop = consoleEl.scrollHeight;
  };

  const paint = () => {
    const live = run.status === "running" || run.status === "queued";
    const done = run.status === "succeeded";
    $("#run-status").className = `status ${run.status}`;
    $("#run-status").textContent = run.status;
    $("#cancel-btn").style.display = live ? "" : "none";
    $("#stages").innerHTML = stageListLive(run, stages);
    $("#progress").style.width = `${done ? 100 : Math.round((Math.max(0, run.stage) / 8) * 100)}%`;

    const res = $("#result");
    if (done) {
      const s = run.summary || {};
      const issues = [...(s.citation_issues || []), ...(s.structure_issues || [])];
      const ci = (s.citation_issues || []).length, si = (s.structure_issues || []).length;
      res.innerHTML = `<div class="result-card fade-in"><div><div class="eyebrow">Pack ready · ${fmtDur(run.elapsed)}</div>
        <h3>${s.sections ?? "–"} sections · ${s.conflicts ?? "–"} conflicts · ${s.gaps ?? "–"} gaps</h3>
        <div style="font-size:13.5px;opacity:.85">${ci} citation issue${ci === 1 ? "" : "s"} · ${si} structure issue${si === 1 ? "" : "s"}</div></div>
        <a class="btn" href="#/packs/${encodeURIComponent(run.output_name)}">Open pack ${icons.arrow}</a></div>
        ${issues.length ? `<div class="note warn" style="margin-top:10px">${issues.map(esc).join("<br>")}</div>` : ""}`;
    } else if (run.status === "failed") {
      res.innerHTML = `<div class="result-card failed fade-in"><div><div class="eyebrow">Run failed at stage ${Math.max(0, run.stage)} · ${fmtDur(run.elapsed)}</div>
        <h3>${esc(run.error || "Unknown error")}</h3><div style="font-size:13.5px;opacity:.85">The full traceback is in the log. A 401/403 usually means the Atlas gateway or Entra token; check the System page.</div></div>
        <a class="btn" href="#/system">System checks</a></div>`;
    } else if (run.status === "cancelled") {
      res.innerHTML = `<div class="note warn fade-in">This run was cancelled.</div>`;
    } else res.innerHTML = "";
  };
  paint();
  (run.events || []).forEach(appendEvent);

  const tick = () => {
    const live = run.status === "running" || run.status === "queued";
    const el = $("#timer");
    if (el) el.textContent = fmtDur(run.elapsed + (live ? (Date.now() - lastTick) / 1000 : 0));
  };
  tick();
  const timer = setInterval(tick, 500);
  onLeave(() => clearInterval(timer));

  $("#cancel-btn").addEventListener("click", async () => {
    if (!confirm("Cancel this run? The current subagent call will finish first.")) return;
    try { await api.runs.cancel(id); toast("Cancellation requested"); } catch (e) { toast(e.message, { tone: "error" }); }
  });

  if (run.status === "running" || run.status === "queued") {
    const close = api.runs.stream(id, (run.events || []).length, {
      log: appendEvent,
      state: (s) => {
        run = { ...run, ...s };
        lastTick = Date.now();
        paint();
        setState({ activeRun: s.status === "running" || s.status === "queued" ? s : null });
      },
      end: () => { pollActiveRun(); if (run.status === "succeeded") toast("Research pack ready"); },
    });
    onLeave(close);
  }
}
