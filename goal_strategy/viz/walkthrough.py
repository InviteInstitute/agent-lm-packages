"""View 1 — the walkthrough, as one self-contained HTML page (task 2 §B2/§B3).

Everything is serialised into the page: block-tree rows grouped by stack, the
untruncated path, events, geometry, and the goal profile. All stepping is
client-side (no Streamlit rerun per step); the Blockly canvas renders exactly
once, in a collapsible panel, from the same inlined vex_blocks.js the old
project used. The block-tree list is the steppable contract; Blockly
highlighting is best-effort only.
"""
from __future__ import annotations

import json
from pathlib import Path
from importlib.resources import files
from .assets import BLOCKLY_MEDIA

# vex_blocks.js stays a verbatim copy of the upstream definitions; the
# corrections file overwrites the parameter-carrying blocks with input_value
# sockets so authored numbers render (see vex_blocks_corrections.js header).
_BLOCKLY_JS = files("goal_strategy.viz").joinpath("vendor", "blockly_local.js").read_text()
_VEX_BLOCKS_JS = ((files("goal_strategy.viz") / "vex_blocks.js").read_text()
                  + "\n" + (files("goal_strategy.viz") / "vex_blocks_corrections.js").read_text())

_TEMPLATE = """
<div id="wt">
<style>
  #wt { font: 13px/1.45 -apple-system, "Segoe UI", sans-serif; color: #222; }
  #wt .grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.4fr) minmax(0, 1fr); gap: 10px; }
  #wt .panel { border: 1px solid #ddd; border-radius: 6px; padding: 8px;
               background: #fff; min-width: 0; overflow-y: auto; max-height: 560px; }
  #wt h4 { margin: 2px 0 6px; font-size: 12px; text-transform: uppercase;
           letter-spacing: .04em; color: #666; }
  #wt .stackhdr { font-weight: 600; margin: 8px 0 2px; padding: 3px 6px;
                  background: #f2f4f7; border-radius: 4px; }
  #wt .stackhdr .note { font-weight: 400; color: #777; font-size: 11px; }
  #wt .row { display: flex; gap: 6px; padding: 1px 4px; border-radius: 3px;
             cursor: default; white-space: nowrap; }
  #wt .row .gut { width: 14px; text-align: center; flex: none; }
  #wt .row.dim { color: #b5b5b5; }
  #wt .row.postexit { color: #c9c9c9; font-style: italic; }
  #wt .row.cur { background: #fff3c4; outline: 1px solid #e6c200; }
  #wt .row .iter { color: #8e44ad; font-size: 11px; margin-left: 6px; }
  #wt .row .fab { color: #e67e22; font-size: 11px; margin-left: 6px; }
  #wt .chip { display: inline-block; padding: 0 7px; border-radius: 9px;
              font-size: 11px; margin: 1px 2px; border: 1px solid transparent; }
  #wt .chip.rung { background: #eaf2fb; border-color: #b7d3f2; color: #1f5f9e; }
  #wt .chip.rung.live { background: #dff0d8; border-color: #9bc99b; color: #2c662d; }
  #wt .chip.trust { background: #fdeeee; border-color: #eab6b6; color: #a33; }
  #wt .chip.fabrication { background: #fdf3e7; border-color: #ecc9a0; color: #b26a00; }
  #wt .chip.scope { background: #f0eef8; border-color: #cdc6e8; color: #5b4ea3; }
  #wt .chip.sensing { background: #eef6f0; border-color: #a8d5b5; color: #1d7a3a; }
  #wt .chip.abstain { background: #f5f5f5; border-color: #ddd; color: #888; }
  #wt .evstrip { display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0; }
  #wt .ev { padding: 2px 8px; border-radius: 4px; border: 1px solid #b7d3f2;
            background: #eaf2fb; cursor: pointer; font-size: 11px; }
  #wt .ev.failure { border-color: #eab6b6; background: #fdeeee; }
  #wt .ev.attainment { border-color: #9bc99b; background: #dff0d8; }
  #wt .ev.post { opacity: .45; border-style: dashed; }
  #wt .ev.sel { outline: 2px solid #e6c200; }
  #wt .bar { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
  #wt .bar button { padding: 2px 10px; }
  #wt input[type=range] { flex: 1; }
  #wt .hdr { display: flex; gap: 14px; align-items: baseline; margin-bottom: 6px; }
  #wt .hdr b { font-size: 15px; }
  #wt details { margin-top: 10px; border: 1px solid #ddd; border-radius: 6px;
                padding: 4px 8px; background: #fff; }
  #wt .goalblock { margin-bottom: 10px; }
  #wt .ind { overflow-wrap: anywhere; margin: 3px 0 3px 8px; }
  #wt .val { color: #555; font-size: 11px; }
  #wt svg text { font-size: 10px; fill: #666; }
  #wt .fidelity { font-size: 12px; margin-top: 6px; padding: 6px;
                  background: #f8f9fb; border-radius: 4px; }
  #wt .hdr { flex-wrap: wrap; overflow-wrap: anywhere; }
  #wt .bar { flex-wrap: wrap; }
  #wt input[type=range] { min-width: 100px; }
  @media (max-width: 640px) {
    #wt .grid { grid-template-columns: minmax(0, 1fr); }
    #wt .panel { max-height: 480px; }
    #wt #tree { max-height: 240px; }
    #wt #goals { max-height: none; }
    #wt .bar button { padding: 6px 10px; }
    #wt .hdr b { flex-basis: 100%; }
  }
</style>
<div class="hdr">
  <b id="pid"></b>
  <span id="treatment"></span>
  <span id="cfgv" class="val"></span>
  <span id="exitnote" style="color:#a33"></span>
</div>
<div class="grid">
  <div class="panel" id="tree"><h4>authored blocks</h4></div>
  <div class="panel" style="overflow:hidden"><h4>path</h4><div id="pathbox"></div></div>
  <div class="panel" id="goals"><h4>goals</h4></div>
</div>
<div class="evstrip" id="evstrip"></div>
<div class="bar">
  <button id="prevev">◀ event</button><button id="prevstep">◀ step</button>
  <input type="range" id="scrub">
  <button id="nextstep">step ▶</button><button id="nextev">event ▶</button>
  <span id="steplabel" style="min-width:120px"></span>
</div>
<details id="blocklypanel">
  <summary id="blocklysummary">Blockly workspace</summary>
  <div id="blocklyDiv" style="height:420px;width:100%"></div>
</details>
</div>
<script>__BLOCKLY_JS__</script>
<script>__VEX_BLOCKS_JS__</script>
<script>
const P = __PAYLOAD__;
const n = P.path.length;
let cur = n ? 0 : -1;
let ws = null;

// ---------- header ----------
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
document.getElementById("pid").textContent = P.program_id;
document.getElementById("treatment").textContent =
  "treatment: " + (P.treatment === "execute" ? "B1 (execute)" :
                   P.treatment === "suppress" ? "B2 (suppress)" : "B3 (abstain)");
document.getElementById("cfgv").textContent = "config " + P.config_version;
if (P.exit_step !== null)
  document.getElementById("exitnote").textContent =
    "boundary exit at step " + P.exit_step +
    (P.boundary_exit_fabricated ? " (ON A FABRICATED STEP)" : "") +
    " — everything after is simulation fiction";

// ---------- events ----------
const allEvents = P.events.map(e => ({...e, post: false}))
  .concat(P.post_exit_events.map(e => ({...e, post: true})));
const jumpSteps = allEvents.map(e => Math.max(e.step, 0));

// rung state per indicator at the current step
function rungAt(indicator, step) {
  let rung = null, value = null;
  for (const e of allEvents) {
    if (e.indicator === indicator && e.step <= step) { rung = e.to_rung; value = e.value; }
  }
  return {rung, value};
}

// ---------- block tree ----------
const tree = document.getElementById("tree");
const eventsByBlock = {};
for (const e of allEvents) if (e.block_id) {
  (eventsByBlock[e.block_id] = eventsByBlock[e.block_id] || []).push(e);
}
const rowEls = {};   // block_id -> [row elements]
for (const g of P.stacks) {
  const hdr = document.createElement("div");
  hdr.className = "stackhdr";
  let label = "▸ " + g.hat_label;
  if (g.ordinal) label += "  (executed " + g.ordinal + ordSuffix(g.ordinal) + ")";
  hdr.textContent = label;
  if (g.note) {
    const s = document.createElement("span");
    s.className = "note"; s.textContent = "  — " + g.note;
    hdr.appendChild(s);
  }
  for (const f of g.trust_flags) {
    const c = document.createElement("span");
    c.className = "chip trust"; c.textContent = f;
    hdr.appendChild(c);
  }
  tree.appendChild(hdr);
  for (const r of g.rows) {
    const el = document.createElement("div");
    el.className = "row";
    if (g.kind === "orphan" || r.steps.length === 0) el.classList.add("dim");
    if (P.exit_step !== null && r.steps.length &&
        r.steps.every(s => s > P.exit_step)) el.classList.add("postexit");
    const gut = document.createElement("span"); gut.className = "gut";
    for (const e of (eventsByBlock[r.block_id] || []).slice(0, 2))
      gut.textContent += e.kind === "failure" ? "✖" : e.kind === "attainment" ? "●" : "○";
    el.appendChild(gut);
    const txt = document.createElement("span");
    txt.style.paddingLeft = (r.depth * 14) + "px";
    txt.textContent = r.label + (r.fields ? "  " + r.fields : "");
    el.appendChild(txt);
    if (r.steps.some(s => P.path[s] && P.path[s].fabricated)) {
      const f = document.createElement("span"); f.className = "fab";
      f.textContent = "◆ fabricated"; el.appendChild(f);
    }
    const it = document.createElement("span"); it.className = "iter";
    el.appendChild(it);
    el.dataset.steps = JSON.stringify(r.steps);
    (rowEls[r.block_id] = rowEls[r.block_id] || []).push(el);
    tree.appendChild(el);
  }
}
function ordSuffix(k){ return k===1?"st":k===2?"nd":k===3?"rd":"th"; }

// ---------- path SVG ----------
const box = document.getElementById("pathbox");
function buildSvg() {
  const pts = P.geometry.boundary.concat(P.path.map(p => [p.x, p.y]))
    .concat(P.gps_final ? [P.gps_final] : [])
    .concat([[P.origin.x, P.origin.y]]);
  let xmin = Math.min(...pts.map(p => p[0])), xmax = Math.max(...pts.map(p => p[0]));
  let ymin = Math.min(...pts.map(p => p[1])), ymax = Math.max(...pts.map(p => p[1]));
  const pad = 0.05 * Math.max(xmax - xmin, ymax - ymin, 1);
  xmin -= pad; xmax += pad; ymin -= pad; ymax += pad;
  const W = 520, H = 520;
  const sc = Math.min(W / (xmax - xmin), H / (ymax - ymin));
  const X = x => (x - xmin) * sc, Y = y => H - (y - ymin) * sc;
  let s = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#fafbfc">`;
  // zone bands (horizontal, clipped around their object)
  for (const zb of P.geometry.zone_bands) {
    const obj = P.geometry.objects.find(o => o.id === zb.object);
    const x0 = X(obj.x - 2 * obj.tolerance), x1 = X(obj.x + 2 * obj.tolerance);
    for (const b of zb.bands) {
      const fill = b.kind === "flagged" ? "rgba(192,57,43,.15)" :
                   b.kind === "undescribed" ? "rgba(230,126,34,.18)" : "rgba(39,174,96,.12)";
      s += `<rect x="${x0}" y="${Y(b.hi)}" width="${x1 - x0}" height="${Y(b.lo) - Y(b.hi)}"
             fill="${fill}"><title>${esc(zb.object)} ${esc(b.label)} [${b.lo.toFixed(0)}–${b.hi.toFixed(0)}]</title></rect>`;
      s += `<text x="${x1 + 3}" y="${(Y(b.lo) + Y(b.hi)) / 2}">${esc(b.label)}</text>`;
    }
  }
  if (P.geometry.boundary.length)
    s += `<polygon points="${P.geometry.boundary.map(p => X(p[0]) + "," + Y(p[1])).join(" ")}"
          fill="none" stroke="#999"/>`;
  for (const r of P.geometry.regions)
    s += `<rect x="${X(r.x_min)}" y="${Y(r.y_max)}" width="${X(r.x_max) - X(r.x_min)}"
          height="${Y(r.y_min) - Y(r.y_max)}" fill="rgba(46,134,193,.06)"
          stroke="rgba(46,134,193,.5)"/><text x="${X(r.x_min) + 3}" y="${Y(r.y_max) + 11}">${esc(r.id)}</text>`;
  for (const o of P.geometry.objects) {
    s += `<circle cx="${X(o.x)}" cy="${Y(o.y)}" r="${o.tolerance * sc}" fill="none"
          stroke="#c0392b" stroke-dasharray="3 3" opacity=".6"><title>${esc(o.id)}</title></circle>`;
    if (!o.piece) s += `<text x="${X(o.x) + 4}" y="${Y(o.y) - 4}">${esc(o.id)}</text>`;
    s += `<circle cx="${X(o.x)}" cy="${Y(o.y)}" r="3" fill="#c0392b"><title>${esc(o.id)}</title></circle>`;
  }
  s += `<circle cx="${X(P.origin.x)}" cy="${Y(P.origin.y)}" r="5" fill="#27ae60"/>`;
  // path segments
  const coords = [[P.origin.x, P.origin.y]].concat(P.path.map(p => [p.x, p.y]));
  s += `<polyline id="pathall" points="${coords.map(p => X(p[0]) + "," + Y(p[1])).join(" ")}"
        fill="none" stroke="#d5dbe1" stroke-width="1.5"/>`;
  s += `<polyline id="pathpre" points="" fill="none" stroke="#34495e" stroke-width="2.5"/>`;
  for (const p of P.path) {
    if (p.post_exit)
      s += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="2.5" fill="#ddd"><title>step ${p.step} POST-EXIT</title></circle>`;
    if (p.fabricated)
      s += `<rect x="${X(p.x) - 4}" y="${Y(p.y) - 4}" width="8" height="8"
            transform="rotate(45 ${X(p.x)} ${Y(p.y)})" fill="none" stroke="#e67e22"
            stroke-width="1.6"><title>step ${p.step} FABRICATED (${esc(p.block_type)})</title></rect>`;
    if (p.qualifying)
      s += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="6" fill="none" stroke="#8e44ad"
            stroke-width="1.4"><title>step ${p.step} qualifying (armed ∧ in tolerance)</title></circle>`;
  }
  for (const e of allEvents) {
    if (e.step < 0 || e.step >= n) continue;
    const p = P.path[e.step];
    s += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="7" fill="none"
          stroke="${e.kind === "failure" ? "#c0392b" : "#2e86c1"}" stroke-width="2"
          ${e.post ? 'stroke-dasharray="2 2" opacity=".5"' : ""}>
          <title>step ${e.step}: ${esc(e.goal)} · ${esc(e.indicator)} → ${esc(e.to_rung)}</title></circle>`;
  }
  if (P.gps_final && P.sim_final) {
    s += `<line x1="${X(P.sim_final[0])}" y1="${Y(P.sim_final[1])}" x2="${X(P.gps_final[0])}"
          y2="${Y(P.gps_final[1])}" stroke="#16a085" stroke-dasharray="4 3"/>`;
    s += `<circle cx="${X(P.gps_final[0])}" cy="${Y(P.gps_final[1])}" r="6" fill="#16a085">
          <title>real final GPS (${P.gps_final[0].toFixed(0)}, ${P.gps_final[1].toFixed(0)})</title></circle>`;
    s += `<text x="${X(P.gps_final[0]) + 6}" y="${Y(P.gps_final[1])}">real GPS</text>`;
  }
  s += `<circle id="curmark" r="6" fill="#e6c200" stroke="#7a6a00"/></svg>`;
  box.innerHTML = s;
  window._X = X; window._Y = Y;
}
buildSvg();

// ---------- goals panel ----------
const goalsEl = document.getElementById("goals");
function renderGoals() {
  let html = "<h4>goals</h4>";
  for (const g of P.goals) {
    html += `<div class="goalblock"><b>${esc(g.goal)}</b>`;
    for (const ind of g.indicators) {
      const live = rungAt(ind.name, cur);
      html += `<div class="ind">${esc(ind.name)} <span class="val">(${esc(ind.kind)} · ${esc(ind.channel)})</span><br>`;
      if (ind.abstained) {
        html += `<span class="chip abstain">abstained: ${esc(ind.abstain_reason)}</span>`;
      } else {
        if (live.rung) html += `<span class="chip rung live">now: ${esc(live.rung)}</span>`;
        html += `<span class="chip rung">final: ${ind.rung ?? "—"}</span>`;
        const v = live.value ?? ind.value;
        if (v !== null && v !== undefined)
          html += ` <span class="val">value ${typeof v === "number" ? v.toFixed(1) : esc(v)}</span>`;
      }
      for (const [grp, names] of Object.entries(P.flag_groups))
        for (const f of ind.flags.filter(f => names.includes(f)))
          html += `<span class="chip ${grp}">${esc(f)}</span>`;
      html += `</div>`;
    }
    html += `</div>`;
  }
  html += `<div class="fidelity"><b>final-position fidelity</b><br>`;
  if (P.fidelity.agreement !== null)
    html += `off-island agreement: ${P.fidelity.agreement ? "✓ sim and GPS agree" : "✗ DISAGREE"}
             (sim ${P.fidelity.sim_off ? "off" : "on"}, gps ${P.fidelity.gps_off ? "off" : "on"})<br>`;
  html += P.fidelity.error_mm !== null
    ? `gps_final_error_mm: ${P.fidelity.error_mm.toFixed(0)}mm`
    : `gps_final_error_mm: null — ${esc(P.fidelity.reason ?? "n/a")}`;
  html += `</div>`;
  if (!n) {
    html += `<div class="fidelity" style="margin-top:6px"><b>zero path steps</b><br>` +
      (P.parse_failed ? "workspace XML failed to parse." :
       P.unknown_reporter_blocks.length
        ? "unevaluable condition(s) kept execution from producing steps — unknown reporter blocks: "
          + esc(P.unknown_reporter_blocks.join(", "))
        : "the program produces no movement.") + `</div>`;
  }
  goalsEl.innerHTML = html;
}

// ---------- event strip ----------
const strip = document.getElementById("evstrip");
allEvents.forEach((e, i) => {
  const el = document.createElement("span");
  el.className = "ev " + e.kind + (e.post ? " post" : "");
  el.textContent = `s${e.step < 0 ? "·origin" : e.step} ${e.goal === "__boundary__" ? "BOUNDARY EXIT" : e.goal + "→" + e.to_rung}`;
  el.title = `${esc(e.indicator)}: ${e.from_rung ?? "∅"} → ${esc(e.to_rung)}` +
             (e.flags.length ? " [" + e.flags.join(", ") + "]" : "");
  el.onclick = () => { cur = Math.max(e.step, 0); render(i); };
  strip.appendChild(el);
});

// ---------- stepping ----------
const scrub = document.getElementById("scrub");
scrub.min = 0; scrub.max = Math.max(n - 1, 0); scrub.value = cur;
scrub.oninput = () => { cur = +scrub.value; render(); };
document.getElementById("prevstep").onclick = () => { cur = Math.max(0, cur - 1); render(); };
document.getElementById("nextstep").onclick = () => { cur = Math.min(n - 1, cur + 1); render(); };
document.getElementById("prevev").onclick = () => {
  const prior = jumpSteps.filter(s => s < cur);
  if (prior.length) { cur = Math.max(...prior); render(); }
};
document.getElementById("nextev").onclick = () => {
  const later = jumpSteps.filter(s => s > cur);
  if (later.length) { cur = Math.min(...later); render(); }
};

function render(selEvent = -1) {
  scrub.value = cur;
  const p = P.path[cur];
  document.getElementById("steplabel").textContent =
    n ? `step ${cur}/${n - 1}` + (p && p.post_exit ? " (post-exit)" : "") : "no steps";
  // tree highlight + iteration counters
  document.querySelectorAll("#wt .row").forEach(el => {
    el.classList.remove("cur");
    const it = el.querySelector(".iter"); if (it) it.textContent = "";
  });
  if (p && rowEls[p.block_id]) {
    for (const el of rowEls[p.block_id]) {
      el.classList.add("cur");
      const steps = JSON.parse(el.dataset.steps);
      if (steps.length > 1) {
        const k = steps.indexOf(cur);
        if (k >= 0) el.querySelector(".iter").textContent =
          `iteration ${k + 1} of ${steps.length}`;
      }
      el.scrollIntoView({block: "nearest"});
    }
  }
  // path prefix + current marker
  const coords = [[P.origin.x, P.origin.y]].concat(P.path.slice(0, cur + 1).map(q => [q.x, q.y]));
  document.getElementById("pathpre").setAttribute("points",
    coords.map(q => window._X(q[0]) + "," + window._Y(q[1])).join(" "));
  const mark = document.getElementById("curmark");
  const at = p ? [p.x, p.y] : [P.origin.x, P.origin.y];
  mark.setAttribute("cx", window._X(at[0])); mark.setAttribute("cy", window._Y(at[1]));
  // event selection
  document.querySelectorAll("#wt .ev").forEach((el, i) =>
    el.classList.toggle("sel", i === selEvent));
  renderGoals();
  // Blockly highlight — best-effort only (§B2); the list is the contract
  if (ws && p) { try { ws.highlightBlock(p.block_id); } catch (err) {} }
}

// ---------- Blockly canvas ----------
const panel = document.getElementById("blocklypanel");
document.getElementById("blocklysummary").textContent =
  `Blockly workspace — ${P.n_top_level_stacks} stack${P.n_top_level_stacks === 1 ? "" : "s"}`
  + ` (${P.n_handler_stacks} handler, ${P.n_top_level_stacks - P.n_handler_stacks} unattached)`;
if (P.n_top_level_stacks > 1) panel.setAttribute("open", "");
try {
  defineVexBlocks();
  defineVexBlockCorrections();
  ws = Blockly.inject("blocklyDiv", {
    readOnly: true, media: __BLOCKLY_MEDIA__, sounds: false, scrollbars: true,
    zoom: {controls: true, wheel: true, startScale: 0.75},
    theme: Blockly.Themes.Classic,
  });
  const dom = Blockly.utils.xml.textToDom(__WORKSPACE_XML_JSON__);
  stubUnknownBlocks(dom);
  Blockly.Xml.domToWorkspace(dom, ws);
  ws.scrollCenter();
} catch (err) {
  document.getElementById("blocklyDiv").innerHTML =
    "<pre style='color:#a33'>Blockly render failed: " +
    esc(String(err).slice(0, 200)) + "</pre>";
}
render();
</script>
"""


def walkthrough_html(payload: dict) -> str:
    payload_json = json.dumps(payload).replace("</", "<\\/")
    xml_json = json.dumps(payload.get("workspace_xml", "")).replace("</", "<\\/")
    return (_TEMPLATE
            .replace("__BLOCKLY_MEDIA__", json.dumps(BLOCKLY_MEDIA)).replace("__BLOCKLY_JS__", _BLOCKLY_JS).replace("__VEX_BLOCKS_JS__", _VEX_BLOCKS_JS)
            .replace("__PAYLOAD__", payload_json)
            .replace("__WORKSPACE_XML_JSON__", xml_json))
