import { api } from "../api.js";
import { icons } from "../utils.js";
import { runsTable } from "../components/runsTable.js";

export async function render({ view }) {
  const { runs } = await api.runs.list();
  view.innerHTML = `
    <div class="page-head fade-in"><div><div class="eyebrow">[ Run history ]</div><h1>Every run, with its log</h1>
      <p>Runs started from the dashboard are kept in <span class="mono">output/runs/</span>. Packs produced from the command line appear under Research packs.</p></div>
      <a class="btn btn-primary" href="#/run">New run ${icons.arrow}</a></div>
    <div class="frame section" style="margin-top:24px">${runsTable(runs)}</div>`;
}
