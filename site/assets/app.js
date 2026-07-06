const REGIME = {
  cool: ["Cool", "var(--cool)", "#4caf7d"],
  warm: ["Warm", "var(--warm)", "#e0b83c"],
  frothy: ["Frothy", "var(--frothy)", "#e07b3c"],
  bubble_risk: ["Bubble risk", "var(--bubble)", "#d64545"],
};
// Fallback regime band edges, used only if history.json has no regime_bands field.
const DEFAULT_REGIME_BANDS = [
  { name: "cool", upper: 40 },
  { name: "warm", upper: 70 },
  { name: "frothy", upper: 85 },
  { name: "bubble_risk", upper: 100 },
];
// Returns the three interior edges [cool-upper, warm-upper, frothy-upper]; the
// bubble_risk band always tops out at 100.
function regimeEdges() {
  const bands = (HISTORY && HISTORY.regime_bands) || DEFAULT_REGIME_BANDS;
  return [bands[0].upper, bands[1].upper, bands[2].upper];
}
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
const STAGE_NAMES = ["Valuation", "Leverage peak", "Curve turn", "Credit widen", "Breadth break", "Confirmed"];
const PLOT_BASE = { paper_bgcolor:"#1b2029", plot_bgcolor:"#1b2029",
  font:{color:"#e6e9ef", size:12}, margin:{l:45,r:15,t:10,b:35} };
const CFG = { displayModeBar:false, responsive:true };

let LATEST, HISTORY, INDICATORS, EPISODES, WIN = "full";

async function boot() {
  [LATEST, HISTORY, INDICATORS, EPISODES] = await Promise.all(
    ["latest", "history", "indicators", "episodes"].map(n => fetch(`data/${n}.json`).then(r => r.json())));
  document.getElementById("asof").textContent = `as of ${LATEST.as_of}`;
  renderGauge(); renderPillars(); renderHistory(); initPicker();
  initHistoryTabs(); renderStress();
  renderAnalogs(); renderRadar(); renderAnalogTable();
  renderSequence();
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
  const [e1, e2, e3] = regimeEdges();
  Plotly.newPlot("gauge", [{
    type: "indicator", mode: "gauge+number", value: c.score,
    gauge: {
      axis: { range: [0, 100], tickvals: [0, e1, e2, e3, 100] },
      bar: { color: hex },
      steps: [
        { range: [0, e1], color: "rgba(76,175,125,.25)" },
        { range: [e1, e2], color: "rgba(224,184,60,.25)" },
        { range: [e2, e3], color: "rgba(224,123,60,.25)" },
        { range: [e3, 100], color: "rgba(214,69,69,.3)" },
      ],
    },
  }], { ...PLOT_BASE, height: 210, margin: {l:25,r:25,t:20,b:5} }, CFG);
  document.getElementById("regime-label").innerHTML =
    `<span style="color:${hex}">${label}</span> · composite ${c.score}`;
}

function renderPillars() {
  const el = document.getElementById("pillars");
  el.innerHTML = "";
  const [e1, e2, e3] = regimeEdges();
  for (const [p, d] of Object.entries(LATEST.pillars)) {
    const score = d[WIN];
    const row = document.createElement("div");
    row.className = "pillar-row";
    const deltas = [d.delta_1m, d.delta_3m]
      .map(x => x == null ? "–" : (x > 0 ? "+" : "") + x.toFixed(1)).join(" / ");
    const color = score == null ? "#555" :
      score >= e3 ? "#d64545" : score >= e2 ? "#e07b3c" : score >= e1 ? "#e0b83c" : "#4caf7d";
    row.innerHTML =
      `<div>${PILLAR_LABEL[p]}${d.partial ? '<span class="chip">partial</span>' : ""}</div>` +
      `<div class="bar-track"><div class="bar-fill" style="width:${score ?? 0}%;background:${color}"></div></div>` +
      `<div class="delta">${score == null ? "n/a" : score.toFixed(1)}<br>${deltas}</div>`;
    el.appendChild(row);
  }
}

function crisisShapes() {
  const markers = HISTORY.crisis_markers ||
    (HISTORY.episode_peaks || []).map(d => ({ date: d, library: true }));
  return markers.map(m => ({
    type: "line", x0: m.date, x1: m.date, y0: 0, y1: 1, yref: "paper",
    line: { color: m.library ? "#d64545" : "#8b93a3", width: 1, dash: "dot" } }));
}

function crisisLabels(yPos) {
  const markers = HISTORY.crisis_markers ||
    (HISTORY.episode_peaks || []).map(d => ({ date: d }));
  return {
    x: markers.map(m => m.date), y: markers.map(() => yPos),
    mode: "markers", hoverinfo: "text", showlegend: false,
    text: markers.map(m => m.name ? `${m.name} (${m.date})` : m.date),
    marker: { size: 6, opacity: 0 },
  };
}

// Plotly's autorange includes shape/marker x-values even when far outside the
// actual data series (e.g. an 1929 crisis marker on a chart whose real data
// starts in 1990). Pin the x-axis to the plotted series' own span so
// out-of-range markers are clipped silently instead of stretching the axis.
function dateRange(dates) {
  return dates && dates.length ? { range: [dates[0], dates[dates.length - 1]] } : {};
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
  traces.push(crisisLabels(97));
  const shapes = crisisShapes().map(s => ({ ...s, y0: 0, y1: 100, yref: "y" }));
  const [e1, e2, e3] = regimeEdges();
  const bands = [[0,e1,"rgba(76,175,125,.05)"],[e1,e2,"rgba(224,184,60,.05)"],
                 [e2,e3,"rgba(224,123,60,.06)"],[e3,100,"rgba(214,69,69,.08)"]];
  for (const [y0,y1,c] of bands)
    shapes.push({ type:"rect", xref:"paper", x0:0, x1:1, y0, y1, fillcolor:c, line:{width:0} });
  Plotly.newPlot("history", traces,
    { ...PLOT_BASE, height: 340, shapes, yaxis: { range: [0, 100] },
      xaxis: dateRange(h.dates),
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
    { ...PLOT_BASE, height: 230, shapes: crisisShapes(),
      xaxis: dateRange(d.series.dates),
      yaxis: { title: { text: "raw value", font: { size: 11 } } } }, CFG);
  Plotly.newPlot("indicator-pct",
    [{ x: d.pct_series.dates, y: d.pct_series.values, name: "froth pct", line: { color: "#e0b83c", width: 1.4 } },
     crisisLabels(97)],
    { ...PLOT_BASE, height: 200, yaxis: { range: [0, 100] },
      xaxis: dateRange(d.pct_series.dates),
      shapes: [
        ...[80, 90].map(y => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y,
                                line: { color: "#d64545", width: 1, dash: "dot" } })),
        ...crisisShapes().map(s => ({ ...s, y0: 0, y1: 100, yref: "y" })),
      ] }, CFG);
}

function renderSequence() {
  const s = LATEST.sequence;
  const banner = document.getElementById("sequence-banner");
  const track = document.getElementById("sequence-track");
  if (!s) { banner.textContent = "Available after first scheduled run."; return; }
  banner.innerHTML = s.engaged
    ? `<span style="color:var(--frothy)">Sequence engaged</span> — current stage ${s.current_stage}`
    : "Sequence not engaged — no pre-crisis pattern in progress.";
  track.innerHTML = STAGE_NAMES.map((name, i) => {
    const st = s.stages[String(i + 1)] || {};
    let cls = "stage";
    if (st.fired === true && !st.lapsed) cls += " fired";
    else if (st.lapsed) cls += " lapsed";
    else if (st.fired === null) cls += " nodata";
    const sub = st.fired === true ? (st.fired_date || "") : st.fired === null ? "no data" : "";
    return `<div class="${cls}">${i + 1}. ${name}<br><span class="muted">${sub}</span></div>`;
  }).join("");
}

let SEL_ANALOG = 0;

function renderAnalogs() {
  const a = LATEST.analogs;
  const list = document.getElementById("analog-list");
  if (!a || !a.top.length) { list.textContent = "No analog data yet."; return; }
  list.innerHTML = a.top.map((t, i) =>
    `<div class="analog-row ${i === SEL_ANALOG ? "sel" : ""}" data-i="${i}">` +
    `${i + 1}. <a href="episodes/${t.episode}.html">${t.name}</a> at T${t.offset_months >= 0 ? "+" : ""}${t.offset_months}m ` +
    `— similarity ${(t.similarity * 100).toFixed(0)}% <span class="muted">(${t.n_shared} shared)</span></div>`).join("");
  list.querySelectorAll(".analog-row").forEach(row =>
    row.addEventListener("click", e => {
      if (e.target.tagName === "A") return;
      SEL_ANALOG = +row.dataset.i;
      renderAnalogs(); renderRadar(); renderAnalogTable();
    }));
  fetch("data/backtest.json").then(r => r.ok ? r.json() : null).then(bt => {
    if (!bt) return;
    const br = bt.base_rate;
    list.insertAdjacentHTML("beforeend",
      `<div class="muted" style="margin-top:6px;font-size:.75rem">Base rate: similarity ≥ ${br.threshold * 100}% occurred in ` +
      `${br.n_high_outside} of ${br.n_months} months OUTSIDE pre-crisis windows (small-sample caveat).</div>`);
  }).catch(() => {});
}

const RADAR_AXES = ["valuation", "leverage", "liquidity", "sentiment", "macro"];

function radarPoints(scores, axes, cx, cy, rmax) {
  return axes.map((p, i) => {
    const v = (scores[p] ?? 0) / 100;
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / axes.length;
    return [cx + rmax * v * Math.cos(ang), cy + rmax * v * Math.sin(ang)];
  });
}

function renderRadar() {
  const svg = document.getElementById("radar");
  const note = document.getElementById("radar-note");
  const a = LATEST.analogs;
  svg.innerHTML = "";
  if (note) note.textContent = "";
  if (!a || !a.top.length) return;
  const t = a.top[SEL_ANALOG];
  const ep = (EPISODES.pillar_scores[t.episode] || {})[String(t.offset_months)] || {};
  const today = {};
  for (const [p, d] of Object.entries(LATEST.pillars)) today[p] = d.full ?? null;
  const cx = 150, cy = 135, rmax = 100;
  // Only draw axes with real data on BOTH polygons -- a pillar absent from the
  // episode snapshot (not yet qualified, no 10y history) or from today must never
  // be drawn as a false zero; it's dropped from the shape entirely.
  const axes = RADAR_AXES.filter(p => ep[p] != null && today[p] != null);
  const dropped = RADAR_AXES.filter(p => !axes.includes(p));
  if (note && dropped.length) {
    note.textContent = `Axes not shown (no data for this episode offset): ${dropped.map(p => PILLAR_LABEL[p]).join(", ")}`;
  }
  if (!axes.length) return;
  let grid = "";
  for (const frac of [0.25, 0.5, 0.75, 1]) {
    const ring = radarPoints(Object.fromEntries(axes.map(p => [p, frac * 100])), axes, cx, cy, rmax);
    grid += `<polygon points="${ring.map(p => p.join(",")).join(" ")}" fill="none" stroke="#2a3140" stroke-width="1"/>`;
  }
  const labels = axes.map((p, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / axes.length;
    const x = cx + (rmax + 16) * Math.cos(ang), y = cy + (rmax + 16) * Math.sin(ang);
    return `<text x="${x}" y="${y}" fill="#8b93a3" font-size="10" text-anchor="middle">${PILLAR_LABEL[p].split(" ")[0]}</text>`;
  }).join("");
  const poly = (scores, color, fillOp) => {
    const pts = radarPoints(scores, axes, cx, cy, rmax).map(p => p.join(",")).join(" ");
    return `<polygon points="${pts}" fill="${color}" fill-opacity="${fillOp}" stroke="${color}" stroke-width="1.6"/>`;
  };
  svg.innerHTML = grid + labels + poly(ep, "#d64545", 0.18) + poly(today, "#6ea8fe", 0.25) +
    `<text x="8" y="14" fill="#6ea8fe" font-size="10">today</text>` +
    `<text x="8" y="28" fill="#d64545" font-size="10">${t.episode} T${t.offset_months}m</text>`;
}

function renderAnalogTable() {
  const el = document.getElementById("analog-table");
  const a = LATEST.analogs;
  if (!a || !a.top.length) { el.innerHTML = ""; return; }
  const t = a.top[SEL_ANALOG];
  const snap = (EPISODES.snapshots[t.episode] || {})[String(t.offset_months)] || {};
  const rows = Object.keys(snap).filter(id => INDICATORS[id])
    .sort((x, y) => (snap[y] - (INDICATORS[y].latest.pct_full ?? 0)) - (snap[x] - (INDICATORS[x].latest.pct_full ?? 0)))
    .map(id => `<tr><td>${INDICATORS[id].name}</td>` +
      `<td>${INDICATORS[id].latest.pct_full ?? "–"}</td><td>${snap[id]}</td></tr>`).join("");
  el.innerHTML = `<table><tr><th>Indicator</th><th>today pct</th><th>${t.episode} T${t.offset_months}m</th></tr>${rows}</table>`;
}

boot().catch(e => { document.body.insertAdjacentHTML("afterbegin",
  `<div class="card" style="border-color:#d64545">Failed to load data: ${e}</div>`); });
