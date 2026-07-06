const REGIME = {
  cool: ["Cool", "var(--cool)", "#4caf7d"],
  warm: ["Warm", "var(--warm)", "#e0b83c"],
  frothy: ["Frothy", "var(--frothy)", "#e07b3c"],
  bubble_risk: ["Bubble risk", "var(--bubble)", "#d64545"],
};
const PILLAR_LABEL = { valuation:"Valuation", leverage:"Leverage & credit",
  liquidity:"Liquidity & monetary", sentiment:"Sentiment & speculation", macro:"Macro stress & breadth" };
const HISTORY_TABS = [
  { key: "composite", label: "Composite" },
  { key: "valuation", label: "Valuation" },
  { key: "leverage", label: "Leverage" },
  { key: "liquidity", label: "Liquidity" },
  { key: "sentiment", label: "Sentiment" },
  { key: "macro", label: "Macro breadth" },
  { key: "stress", label: "Confirmation stress" },
];
let HTAB = "composite";
const PLOT_BASE = { paper_bgcolor:"#1b2029", plot_bgcolor:"#1b2029",
  font:{color:"#e6e9ef", size:12}, margin:{l:45,r:15,t:10,b:35} };
const CFG = { displayModeBar:false, responsive:true };

let LATEST, HISTORY, INDICATORS, WIN = "full";

async function boot() {
  [LATEST, HISTORY, INDICATORS] = await Promise.all(
    ["latest", "history", "indicators"].map(n => fetch(`data/${n}.json`).then(r => r.json())));
  document.getElementById("asof").textContent = `as of ${LATEST.as_of}`;
  renderGauge(); renderPillars(); renderHistory(); initPicker();
  initHistoryTabs(); renderStress();
  document.getElementById("window-toggle").addEventListener("change", e => {
    WIN = e.target.checked ? "rolling20y" : "full";
    renderGauge(); renderPillars(); renderHistory(); renderStress();
  });
}

function initHistoryTabs() {
  const el = document.getElementById("history-tabs");
  for (const t of HISTORY_TABS) {
    const b = document.createElement("button");
    b.textContent = t.label;
    b.dataset.key = t.key;
    if (t.key === HTAB) b.classList.add("active");
    b.addEventListener("click", () => {
      HTAB = t.key;
      el.querySelectorAll("button").forEach(x => x.classList.toggle("active", x.dataset.key === HTAB));
      renderHistory();
    });
    el.appendChild(b);
  }
}

function renderStress() {
  const s = (LATEST.stress || {})[WIN] || (LATEST.stress || {}).full;
  const el = document.getElementById("stress-label");
  if (!s) { el.textContent = ""; return; }
  const color = s.label === "confirming" ? "#d64545" : s.label === "elevated" ? "#e0b83c" : "#4caf7d";
  el.innerHTML = `Confirmation stress: <span style="color:${color}">${s.score} (${s.label})</span>`;
}

function comp() { return LATEST.composite[WIN] || LATEST.composite.full; }

function renderGauge() {
  const c = comp();
  const [label, , hex] = REGIME[c.regime];
  Plotly.newPlot("gauge", [{
    type: "indicator", mode: "gauge+number", value: c.score,
    gauge: {
      axis: { range: [0, 100], tickvals: [0, 40, 70, 85, 100] },
      bar: { color: hex },
      steps: [
        { range: [0, 40], color: "rgba(76,175,125,.25)" },
        { range: [40, 70], color: "rgba(224,184,60,.25)" },
        { range: [70, 85], color: "rgba(224,123,60,.25)" },
        { range: [85, 100], color: "rgba(214,69,69,.3)" },
      ],
    },
  }], { ...PLOT_BASE, height: 210, margin: {l:25,r:25,t:20,b:5} }, CFG);
  document.getElementById("regime-label").innerHTML =
    `<span style="color:${hex}">${label}</span> · composite ${c.score}`;
}

function renderPillars() {
  const el = document.getElementById("pillars");
  el.innerHTML = "";
  for (const [p, d] of Object.entries(LATEST.pillars)) {
    const score = d[WIN];
    const row = document.createElement("div");
    row.className = "pillar-row";
    const deltas = [d.delta_1m, d.delta_3m]
      .map(x => x == null ? "–" : (x > 0 ? "+" : "") + x.toFixed(1)).join(" / ");
    const color = score == null ? "#555" :
      score >= 85 ? "#d64545" : score >= 70 ? "#e07b3c" : score >= 40 ? "#e0b83c" : "#4caf7d";
    row.innerHTML =
      `<div>${PILLAR_LABEL[p]}${d.partial ? '<span class="chip">partial</span>' : ""}</div>` +
      `<div class="bar-track"><div class="bar-fill" style="width:${score ?? 0}%;background:${color}"></div></div>` +
      `<div class="delta">${score == null ? "n/a" : score.toFixed(1)}<br>${deltas}</div>`;
    el.appendChild(row);
  }
}

function episodeShapes() {
  return HISTORY.episode_peaks.map(d => ({
    type: "line", x0: d, x1: d, y0: 0, y1: 1, yref: "paper",
    line: { color: "#d64545", width: 1, dash: "dot" } }));
}

function renderHistory() {
  const h = HISTORY[WIN];
  if (!h) return;
  const traces = [];
  if (HTAB === "composite") {
    traces.push({ x: h.dates, y: h.composite, name: "Composite",
                  line: { color: "#e6e9ef", width: 2.4 } });
    for (const [p, vals] of Object.entries(h.pillars))
      traces.push({ x: h.dates, y: vals, name: PILLAR_LABEL[p],
                    line: { width: 1 }, opacity: 0.55, visible: "legendonly" });
    if (h.stress) traces.push({ x: h.dates, y: h.stress, name: "Confirmation stress",
                                line: { width: 1, dash: "dot" }, opacity: 0.5, visible: "legendonly" });
  } else if (HTAB === "stress") {
    if (h.stress) traces.push({ x: h.dates, y: h.stress, name: "Confirmation stress",
                                line: { color: "#e07b3c", width: 2.2 } });
    traces.push({ x: h.dates, y: h.composite, name: "Composite (ref)",
                  line: { color: "#8b93a3", width: 1, dash: "dash" }, opacity: 0.6 });
  } else {
    const vals = h.pillars[HTAB];
    if (vals) traces.push({ x: h.dates, y: vals, name: PILLAR_LABEL[HTAB],
                            line: { color: "#6ea8fe", width: 2.2 } });
    traces.push({ x: h.dates, y: h.composite, name: "Composite (ref)",
                  line: { color: "#8b93a3", width: 1, dash: "dash" }, opacity: 0.6 });
  }
  const shapes = episodeShapes().map(s => ({ ...s, y0: 0, y1: 100, yref: "y" }));
  const bands = [[0,40,"rgba(76,175,125,.05)"],[40,70,"rgba(224,184,60,.05)"],
                 [70,85,"rgba(224,123,60,.06)"],[85,100,"rgba(214,69,69,.08)"]];
  for (const [y0,y1,c] of bands)
    shapes.push({ type:"rect", xref:"paper", x0:0, x1:1, y0, y1, fillcolor:c, line:{width:0} });
  Plotly.newPlot("history", traces,
    { ...PLOT_BASE, height: 340, shapes, yaxis: { range: [0, 100] },
      legend: { orientation: "h", y: -0.15 } }, CFG);
}

function initPicker() {
  const sel = document.getElementById("indicator-picker");
  const ids = Object.keys(INDICATORS).sort((a, b) =>
    INDICATORS[a].pillar.localeCompare(INDICATORS[b].pillar));
  for (const id of ids) {
    const o = document.createElement("option");
    o.value = id;
    o.textContent = `${PILLAR_LABEL[INDICATORS[id].pillar]} · ${INDICATORS[id].name}`;
    sel.appendChild(o);
  }
  sel.addEventListener("change", () => renderIndicator(sel.value));
  renderIndicator(ids[0]);
}

function renderIndicator(id) {
  const d = INDICATORS[id];
  document.getElementById("indicator-meta").innerHTML =
    `<span class="chip">${d.role}</span><span class="chip">${d.direction}</span>` +
    `<span class="chip">${d.frequency}</span>` +
    `<span class="chip">pct ${d.latest.pct_full ?? "n/a"}</span>` +
    `<span class="chip">z ${d.latest.zscore ?? "n/a"}</span>` +
    (d.stale ? ' <span class="badge-stale">STALE</span>' : "") +
    ` <span class="muted">last obs ${d.last_obs}</span>`;
  Plotly.newPlot("indicator-raw",
    [{ x: d.series.dates, y: d.series.values, name: "raw", line: { color: "#6ea8fe", width: 1.4 } }],
    { ...PLOT_BASE, height: 230, shapes: episodeShapes(),
      yaxis: { title: { text: "raw value", font: { size: 11 } } } }, CFG);
  Plotly.newPlot("indicator-pct",
    [{ x: d.pct_series.dates, y: d.pct_series.values, name: "froth pct", line: { color: "#e0b83c", width: 1.4 } }],
    { ...PLOT_BASE, height: 200, yaxis: { range: [0, 100] },
      shapes: [
        ...[80, 90].map(y => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y,
                                line: { color: "#d64545", width: 1, dash: "dot" } })),
        ...episodeShapes().map(s => ({ ...s, y0: 0, y1: 100, yref: "y" })),
      ] }, CFG);
}

boot().catch(e => { document.body.insertAdjacentHTML("afterbegin",
  `<div class="card" style="border-color:#d64545">Failed to load data: ${e}</div>`); });
