import { api } from "../api.js";
import { $, $$, esc, icons } from "../utils.js";
import { stageListStatic } from "../components/pipeline.js";
import { toast } from "../components/toast.js";
import { pollActiveRun } from "../store.js";

export async function render({ view, query }) {
  const [{ questions }, { active }] = await Promise.all([api.questions(), api.runs.list()]);
  const running = active && (active.status === "running" || active.status === "queued") ? active : null;
  const pre = query.get("q");
  let selected = questions.find((q) => q.id === pre) ? pre : questions[0]?.id || "custom";

  view.innerHTML = `
    <div class="page-head fade-in">
      <div><div class="eyebrow">[ New run ]</div><h1>Ask the research desk</h1>
      <p>Pick one of the three fixed questions or write your own. The coordinator runs all seven stages against the corpus and writes the pack to <span class="mono">output/</span>.</p></div>
    </div>
    <div class="run-layout section" style="margin-top:28px">
      <div class="frame ticks">
        <div class="frame-head"><h3>Question</h3><span class="eyebrow">Step 1 of 2</span></div>
        <div class="frame-body">
          <div class="choice-list">
            ${questions.map((q) => `<label class="choice" data-id="${q.id}">
              <input type="radio" name="q" value="${q.id}"><span class="radio"></span>
              <span><span class="c-title"><span class="q-id">${q.id}</span>${esc(q.label)} ${q.has_pack ? `<span class="tag pine-soft">overwrites pack</span>` : ""}</span>
              <span class="c-q" style="display:block">${esc(q.question)}</span></span></label>`).join("")}
            <label class="choice" data-id="custom">
              <input type="radio" name="q" value="custom"><span class="radio"></span>
              <span style="display:block"><span class="c-title">Custom question <span class="tag">new pack</span></span>
              <span class="c-q" style="display:block">Anything answerable from the corpus.</span></span></label>
          </div>
          <textarea class="input" id="custom-q" rows="3" placeholder="e.g. What is the state of Meridian's third-party and outsourcing risk management?" style="margin-top:12px"></textarea>
        </div>
      </div>
      <div style="display:grid;gap:16px">
        <div class="frame">
          <div class="frame-head"><h3>Before you start</h3><span class="eyebrow">Step 2 of 2</span></div>
          <div class="frame-body" style="display:grid;gap:12px">
            <div class="note">A browser window opens for Entra ID sign-in on the first stage. Keep it nearby; the run waits for it.</div>
            <div class="note pine">Expect roughly 2.5–4.5 minutes. Q3 is the slowest because its synthesis stage has the most findings. <span class="mono">[retry]</span> lines in the log are normal.</div>
            ${running ? `<div class="note warn">A run is already in progress. <a href="#/run/${esc(running.id)}"><strong>Watch it</strong></a> or cancel it before starting another.</div>` : ""}
            <div class="row" style="margin-top:4px">
              <button class="btn btn-primary" id="start-btn" ${running ? "disabled" : ""}>Start research run ${icons.arrow}</button>
              <span class="muted" id="start-msg" style="font-size:13px"></span>
            </div>
          </div>
        </div>
        ${stageListStatic()}
      </div>
    </div>`;

  const paint = () => {
    $$(".choice", view).forEach((c) => c.classList.toggle("selected", c.dataset.id === selected));
    $("#custom-q").style.display = selected === "custom" ? "" : "none";
  };
  $$(".choice", view).forEach((c) => c.addEventListener("click", () => {
    selected = c.dataset.id;
    paint();
    if (selected === "custom") $("#custom-q").focus();
  }));
  paint();

  $("#start-btn").addEventListener("click", async () => {
    const q = selected === "custom" ? $("#custom-q").value.trim() : questions.find((x) => x.id === selected).question;
    if (!q || q.length < 8) { toast("Write a question first."); $("#custom-q").focus(); return; }
    const btn = $("#start-btn");
    btn.disabled = true;
    $("#start-msg").textContent = "Starting…";
    try {
      const run = await api.runs.start(q);
      pollActiveRun();
      location.hash = `#/run/${run.id}`;
    } catch (e) {
      btn.disabled = false;
      $("#start-msg").textContent = "";
      toast(e.message, { tone: "error" });
    }
  });
}
