import { api } from "../api.js";
import { esc } from "../utils.js";

export async function render({ view }) {
  const h = await api.health();
  const badge = (ok, yes = "set", no = "missing") => `<span class="${ok ? "ok-badge" : "no-badge"}">${ok ? yes : no}</span>`;
  const ready = h.env.every((e) => e.present) && !h.anthropic_api_key_set;
  view.innerHTML = `
    <div class="page-head fade-in"><div><div class="eyebrow">[ System ]</div><h1>Environment checks</h1>
      <p>What the pipeline needs before a run can succeed. Secret values are never sent to the browser, only whether each one is present.</p></div>
      <span class="tag ${ready ? "pine" : "orange"}">${ready ? "Ready to run" : "Needs attention"}</span></div>
    ${h.anthropic_api_key_set ? `<div class="note warn" style="margin-top:20px"><strong>ANTHROPIC_API_KEY is set.</strong> The CLI will prefer it and silently bypass the Atlas gateway. Unset it before running.</div>` : ""}
    <div class="split-even section" style="margin-top:24px">
      <div class="frame"><div class="frame-head"><h3>Atlas / Entra variables</h3>${badge(h.env_file, ".env found", "no .env")}</div>
        <ul class="check-list">${h.env.map((e) => `<li><code>${esc(e.name)}</code>${badge(e.present)}</li>`).join("")}
        <li><code>ANTHROPIC_API_KEY</code>${h.anthropic_api_key_set ? `<span class="no-badge">set, remove it</span>` : `<span class="ok-badge">not set</span>`}</li></ul></div>
      <div style="display:grid;gap:16px;align-content:start">
        <div class="frame"><div class="frame-head"><h3>Python packages</h3></div>
          <ul class="check-list">${Object.entries(h.dependencies).map(([k, v]) => `<li><code>${esc(k)}</code>${badge(v, "installed", "missing")}</li>`).join("")}</ul></div>
        <div class="frame"><div class="frame-head"><h3>Paths</h3></div>
          <ul class="check-list">
            <li><span>Corpus</span><code>${esc(h.corpus_dir)}/ · ${h.corpus_files} files · ${h.manifest_documents} in manifest</code></li>
            <li><span>Output</span><code>${esc(h.output_dir)}/</code></li>
            <li><span>API reference</span><a href="/api/docs" target="_blank" rel="noopener"><code>/api/docs</code></a></li></ul></div>
      </div>
    </div>
    <div class="frame section"><div class="frame-head"><h3>Command line equivalents</h3></div><div class="frame-body">
      <pre class="cmd"><span class="c"># start this dashboard</span>
python run_dashboard.py
<span class="c"># check the gateway is reachable</span>
python atlas_client.py
<span class="c"># run without the dashboard (original 28 documents only)</span>
python run_q1.py   <span class="c"># regulatory exposure</span>
python run_common.py   <span class="c"># all three questions</span>
<span class="c"># unit tests (no API key needed)</span>
python -m unittest discover -s tests -v</pre></div></div>`;
}
