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
  liquidity:"Liquidity & monetary", sentiment:"Sentiment & speculation", macro:"Macro stress & breadth",
  context:"Context (not scored)" };
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

const CONTEXT_IDS = ["cpi_yoy", "core_cpi_yoy", "ppi_yoy", "payrolls_yoy", "unemployment", "job_openings", "fed_funds"];
const CONTEXT_LABEL = { cpi_yoy:"CPI YoY", core_cpi_yoy:"Core CPI", ppi_yoy:"PPI YoY",
  payrolls_yoy:"Payrolls YoY", unemployment:"Unemployment", job_openings:"Job openings", fed_funds:"Fed funds" };
// "Macro backdrop" strip under the Score History chart: the same context indicators as
// CONTEXT_IDS above, minus job_openings (a thousands-level, not a percent -- it can't share
// the "%" y-axis the rest of these sit on). CPI and the policy rate default to visible since
// they're the two most commonly-referenced series; the rest start "legendonly" to keep the
// strip readable, one click away in the legend.
const BACKDROP_IDS = ["cpi_yoy", "core_cpi_yoy", "ppi_yoy", "payrolls_yoy", "unemployment", "fed_funds"];
const BACKDROP_DEFAULT_VISIBLE = new Set(["cpi_yoy", "fed_funds"]);
const BACKDROP_COLOR = { cpi_yoy:"#6ea8fe", core_cpi_yoy:"#8b93a3", ppi_yoy:"#b98cce",
  payrolls_yoy:"#4caf7d", unemployment:"#d64545", fed_funds:"#e0b83c" };
// Distinct line colors for the multi-indicator compare views, reusing hues already
// established elsewhere in the palette (raw-line blue, froth-pct amber, cool green, bubble red).
const COMPARE_PALETTE = ["#6ea8fe", "#e0b83c", "#4caf7d", "#d64545"];
// Pinned indicator ids for the drill-down comparison, IN ADDITION to whatever the
// <select> currently shows (the primary). See compareSet() for how these combine.
// 0 extras = original single-indicator view; 1-3 = comparison view (2-4 total).
let EXTRA_COMPARE = [];

let LATEST, HISTORY, INDICATORS, EPISODES, WIN = "full";

async function boot() {
  [LATEST, HISTORY, INDICATORS, EPISODES] = await Promise.all(
    ["latest", "history", "indicators", "episodes"].map(n => fetch(`data/${n}.json`).then(r => r.json())));
  document.getElementById("asof").textContent = `as of ${LATEST.as_of}`;
  renderGauge(); renderPillars(); renderHistory(); renderContextPanel(); initPicker();
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

// Row 2 of the Score History figure: one thin line per percent-scale context indicator,
// all sharing the "y3" axis. Guards on the indicator actually being present in INDICATORS
// (display-only context indicators could in principle be absent from a given data build).
function macroBackdropTraces() {
  return BACKDROP_IDS.map(id => {
    const d = INDICATORS[id];
    if (!d) return null;
    return { x: d.series.dates, y: d.series.values, name: CONTEXT_LABEL[id], yaxis: "y3",
             line: { color: BACKDROP_COLOR[id], width: 1.2 },
             visible: BACKDROP_DEFAULT_VISIBLE.has(id) ? true : "legendonly" };
  }).filter(Boolean);
}

// Official NBER recession shading (HISTORY.recessions, [start, end] ISO-date pairs) --
// descriptive government dating, not this site's own judgment call. yref:"paper" spans the
// full figure height so the bands read across both the score row and the backdrop row.
function recessionShapes() {
  return (HISTORY.recessions || []).map(([start, end]) => ({
    type: "rect", xref: "x", yref: "paper", x0: start, x1: end, y0: 0, y1: 1,
    fillcolor: "rgba(139,147,163,0.14)", line: { width: 0 }, layer: "below",
  }));
}

// Plotly's autorange includes shape/marker x-values even when far outside the
// actual data series (e.g. an 1929 crisis marker on a chart whose real data
// starts in 1990). Pin the x-axis to the plotted series' own span so
// out-of-range markers are clipped silently instead of stretching the axis.
function dateRange(dates) {
  return dates && dates.length ? { range: [dates[0], dates[dates.length - 1]] } : {};
}

// Same idea as dateRange(), but pinned to the UNION of several series' spans (used by
// the multi-indicator compare views, whose selected indicators rarely share a start date
// -- e.g. Shiller CAPE from 1881 alongside a FRED series from the 1950s).
function unionDateRange(dateArrays) {
  const arrs = dateArrays.filter(a => a && a.length);
  if (!arrs.length) return {};
  let start = arrs[0][0], end = arrs[0][arrs[0].length - 1];
  for (const a of arrs) {
    if (a[0] < start) start = a[0];
    if (a[a.length - 1] > end) end = a[a.length - 1];
  }
  return { range: [start, end] };
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
  if (HISTORY.spx) {
    traces.push({ x: HISTORY.spx.dates, y: HISTORY.spx.values, name: "S&P 500 (log)",
                  yaxis: "y2", line: { color: "#8b93a3", width: 1 }, opacity: 0.55,
                  hovertemplate: "%{x|%Y-%m-%d} · %{y:,.0f}<extra>S&P 500</extra>" });
  }
  traces.push(crisisLabels(97));
  traces.push(...macroBackdropTraces());

  // crisisShapes() already emits yref:"paper", y0:0, y1:1 -- unlike the drill-down charts
  // (which override that to a single axis' own 0-100 range since they're one row), this
  // figure has TWO rows now, so the paper-referenced form is used as-is here specifically
  // so the vertical crisis lines span both the score row and the backdrop row beneath it.
  const shapes = [...recessionShapes(), ...crisisShapes()];
  const [e1, e2, e3] = regimeEdges();
  const bands = [[0,e1,"rgba(76,175,125,.05)"],[e1,e2,"rgba(224,184,60,.05)"],
                 [e2,e3,"rgba(224,123,60,.06)"],[e3,100,"rgba(214,69,69,.08)"]];
  // Regime bands stay yref:"y" (row 1's own axis, still ranged 0-100) -- with that axis'
  // domain now confined to [0.38, 1], these rects render only behind row 1, never row 2.
  for (const [y0,y1,c] of bands)
    shapes.push({ type:"rect", xref:"paper", x0:0, x1:1, y0, y1, fillcolor:c, line:{width:0} });
  Plotly.newPlot("history", traces,
    { ...PLOT_BASE, height: 520, shapes,
      yaxis: { domain: [0.38, 1], range: [0, 100] },
      yaxis2: { overlaying: "y", side: "right", type: "log", showgrid: false,
                tickfont: { size: 9, color: "#8b93a3" } },
      // Row 2, "Macro backdrop": own y-axis (percent scale, own domain), anchored to the
      // SAME xaxis "x" as row 1 -- there is only one x-axis on this whole figure, which is
      // what makes zoom/pan sync between the two rows structural rather than something that
      // needs Plotly's `matches` axis-linking (unsupported by the vendored partial bundle).
      yaxis3: { domain: [0, 0.30], anchor: "x", title: { text: "%", font: { size: 10 } },
                tickfont: { size: 9, color: "#8b93a3" } },
      xaxis: dateRange(h.dates),
      legend: { orientation: "h", y: -0.12 } }, CFG);
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
  sel.addEventListener("change", () => renderIndicator());
  document.getElementById("compare-add").addEventListener("click", () => pinCompare(sel.value));
  renderIndicator();
}

// The compare set is DERIVED, not stored wholesale: slot 0 is always whatever the
// <select> currently shows (so "changing the primary replaces the first chip" falls out
// for free -- there's nothing to explicitly replace), and EXTRA_COMPARE holds the 0-3
// pinned additional ids. If a pinned id happens to equal the current primary (e.g. right
// after pinning it, before the user picks something else to compare it against) it's
// filtered out of the effective set so it doesn't render as a visual duplicate.
function compareSet() {
  const primary = document.getElementById("indicator-picker").value;
  return [primary, ...EXTRA_COMPARE.filter(id => id !== primary)];
}

// "+ Compare" pins the CURRENTLY SELECTED (primary) indicator so it survives the next
// change to the <select> -- the natural way to build a 2nd/3rd/4th comparison member is:
// pin the indicator you're looking at, then pick the next one in the dropdown.
function pinCompare(id) {
  if (!id || EXTRA_COMPARE.includes(id) || EXTRA_COMPARE.length >= 3) return;
  EXTRA_COMPARE.push(id);
  renderIndicator();
}

function unpinCompare(id) {
  EXTRA_COMPARE = EXTRA_COMPARE.filter(x => x !== id);
  renderIndicator();
}

// Shared entry point for both the picker <select> and the context-panel tiles. Setting
// .value programmatically doesn't fire a native "change" event, so re-render explicitly.
function selectPrimary(id, scrollIntoView) {
  document.getElementById("indicator-picker").value = id;
  renderIndicator();
  if (scrollIntoView) {
    document.getElementById("drilldown").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// Chip row shows only the PINNED extras (the primary is already visible via the select,
// no need to duplicate it here) -- each removable with an x.
function renderCompareChips(ids) {
  const el = document.getElementById("compare-chips");
  const extras = ids.slice(1);
  el.innerHTML = extras.map(id => {
    const name = INDICATORS[id] ? INDICATORS[id].name : id;
    return `<span class="chip compare-chip">${name}<span class="chip-x" data-id="${id}">&times;</span></span>`;
  }).join("");
  el.querySelectorAll(".chip-x").forEach(x =>
    x.addEventListener("click", () => unpinCompare(x.dataset.id)));
  const sel = document.getElementById("indicator-picker");
  document.getElementById("compare-add").disabled =
    EXTRA_COMPARE.length >= 3 || EXTRA_COMPARE.includes(sel.value);
}

function renderIndicator() {
  const ids = compareSet();
  const d = INDICATORS[ids[0]];
  document.getElementById("indicator-meta").innerHTML =
    `<span class="chip">${d.role}</span><span class="chip">${d.direction}</span>` +
    `<span class="chip">${d.frequency}</span>` +
    `<span class="chip">pct ${d.latest.pct_full ?? "n/a"}</span>` +
    `<span class="chip">z ${d.latest.zscore ?? "n/a"}</span>` +
    (d.stale ? ' <span class="badge-stale">STALE</span>' : "") +
    ` <span class="muted">last obs ${d.last_obs}</span>`;
  renderCompareChips(ids);
  if (ids.length <= 1) {
    renderSingleIndicator(d);
  } else {
    renderCompare(ids);
  }
}

// ONE two-row figure, same construction as renderHistory(): a SINGLE shared x-axis (row
// domains live on separate y-axes anchored to that one "x"), so zoom/pan sync is
// structural rather than event-wired. Row 1 (top, taller) is the raw value line + the S&P
// overlay; row 2 (bottom) is the froth-percentile line + its 80/90 guide lines. The pct
// series typically starts well after the raw series (percentile qualification window), so
// the x-axis is pinned to the UNION of both spans -- the pct line simply begins partway
// across the shared timeline instead of on a separately-scaled axis.
function renderSingleIndicator(d) {
  const traces = [{ x: d.series.dates, y: d.series.values, name: "raw", line: { color: "#6ea8fe", width: 1.4 } }];
  if (HISTORY.spx) {
    traces.push({ x: HISTORY.spx.dates, y: HISTORY.spx.values, name: "S&P 500 (log)",
                  yaxis: "y2", line: { color: "#8b93a3", width: 1 }, opacity: 0.55,
                  hovertemplate: "%{x|%Y-%m-%d} · %{y:,.0f}<extra>S&P 500</extra>" });
  }
  traces.push({ x: d.pct_series.dates, y: d.pct_series.values, name: "froth pct",
                yaxis: "y3", line: { color: "#e0b83c", width: 1.4 } });
  traces.push({ ...crisisLabels(97), yaxis: "y3" });

  // crisisShapes() already emits yref:"paper" -- used as-is so the dashed crisis lines
  // span both rows. The 80/90 guide lines are anchored to yaxis3 (the pct row's own
  // axis) so they never bleed onto the raw row above.
  const shapes = [
    ...crisisShapes(),
    ...[80, 90].map(y => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, yref: "y3",
                            line: { color: "#d64545", width: 1, dash: "dot" } })),
  ];

  Plotly.newPlot("indicator-chart", traces,
    { ...PLOT_BASE, height: 460, shapes,
      xaxis: unionDateRange([d.series.dates, d.pct_series.dates]),
      yaxis: { domain: [0.38, 1], title: { text: "raw value", font: { size: 11 } } },
      yaxis2: { overlaying: "y", side: "right", type: "log", showgrid: false,
                tickfont: { size: 9, color: "#8b93a3" } },
      yaxis3: { domain: [0, 0.30], anchor: "x", range: [0, 100],
                tickfont: { size: 9, color: "#8b93a3" } } }, CFG);
}

// 2-4 indicators, ONE figure: row 1 (taller, "220px-equivalent" domain share) is every
// selected indicator's percentile overlaid on ONE shared 0-100 axis -- the comparable
// scale, since "rank versus own history" means the same thing regardless of units. Rows
// 2..N+1 are raw small multiples, one per indicator, each on its own y-axis (raw units
// aren't comparable the way percentiles are) with a paper-referenced row annotation
// standing in for a legend. All rows anchor to the SAME single "x" axis (never a
// per-row x2/x3/x4 the way the old two-figure small multiples faked a shared look), so
// zoom/pan sync is structural, and the axis is pinned to the union of every selected
// indicator's raw AND pct spans.
function renderCompare(ids) {
  const n = ids.length;
  const gap = 0.03;
  const pctW = 220, rowW = 140;
  const totalW = pctW + rowW * n;
  const avail = 1 - gap * n; // n gaps total: pct-row1, row1-row2, ..., row(n-1)-row(n)
  const unit = avail / totalW;
  const pctH = unit * pctW;
  const rowH = unit * rowW;
  const pctBottom = 1 - pctH;
  const xr = unionDateRange(ids.flatMap(id => [INDICATORS[id].series.dates, INDICATORS[id].pct_series.dates]));

  const traces = ids.map((id, i) => {
    const d = INDICATORS[id];
    return { x: d.pct_series.dates, y: d.pct_series.values, name: d.name,
              line: { color: COMPARE_PALETTE[i % COMPARE_PALETTE.length], width: 1.6 } };
  });
  traces.push(crisisLabels(97));

  const layout = { ...PLOT_BASE, height: 220 + 140 * n + 60,
                   margin: { ...PLOT_BASE.margin, t: 34 },
                   shapes: [
                     ...crisisShapes(),
                     ...[80, 90].map(y => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y,
                                             line: { color: "#d64545", width: 1, dash: "dot" } })),
                   ],
                   annotations: [],
                   xaxis: xr,
                   yaxis: { domain: [pctBottom, 1], range: [0, 100],
                            tickfont: { size: 9, color: "#8b93a3" } },
                   legend: { orientation: "h", y: 1.1, x: 0 } };

  let top = pctBottom - gap;
  ids.forEach((id, i) => {
    const d = INDICATORS[id];
    const bottom = top - rowH;
    const suffix = String(i + 2); // row axes start at 2 -- the pct row is axis 1 (unsuffixed)
    traces.push({ x: d.series.dates, y: d.series.values, name: d.name, showlegend: false,
                  yaxis: "y" + suffix,
                  line: { color: COMPARE_PALETTE[i % COMPARE_PALETTE.length], width: 1.3 } });
    layout["yaxis" + suffix] = { domain: [bottom, top], anchor: "x",
                                  tickfont: { size: 9, color: "#8b93a3" } };
    layout.annotations.push({ xref: "paper", yref: "paper", x: 0.01, y: top - 0.015,
                              xanchor: "left", yanchor: "top", showarrow: false,
                              text: d.name, font: { size: 10, color: "#8b93a3" } });
    top = bottom - gap;
  });

  Plotly.newPlot("indicator-chart", traces, layout, CFG);
}

function fmtContextValue(id, v) {
  if (v == null) return "n/a";
  if (id === "job_openings") return Math.round(v).toLocaleString("en-US") + "k";
  const dec = (id === "payrolls_yoy" || id === "fed_funds") ? 2 : 1;
  return v.toFixed(dec) + "%";
}

function fmtContextDelta(id, delta) {
  if (delta == null) return "";
  const dec = id === "job_openings" ? 0 : (id === "payrolls_yoy" || id === "fed_funds" ? 2 : 1);
  const up = delta > 0.0005, down = delta < -0.0005;
  const arrow = up ? "▲" : down ? "▼" : "–";
  const sign = up ? "+" : down ? "-" : "";
  const suffix = id === "job_openings" ? "k" : "pp";
  const mag = id === "job_openings"
    ? Math.round(Math.abs(delta)).toLocaleString("en-US")
    : Math.abs(delta).toFixed(dec);
  return `${arrow} ${sign}${mag}${suffix}`;
}

// Nearest observation to `targetTime` in a (date, value) series pair -- used to find the
// value ~12 months before the latest observation without assuming exact day alignment
// (monthly series don't all publish on the same day-of-month).
function valueNearDate(dates, values, targetTime) {
  let bestIdx = -1, bestDiff = Infinity;
  for (let i = 0; i < dates.length; i++) {
    const diff = Math.abs(new Date(dates[i]).getTime() - targetTime);
    if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
  }
  return bestIdx >= 0 ? values[bestIdx] : null;
}

function renderContextPanel() {
  const el = document.getElementById("context-tiles");
  el.innerHTML = "";
  for (const id of CONTEXT_IDS) {
    const d = INDICATORS[id];
    if (!d) continue;
    const dates = d.series.dates, vals = d.series.values;
    const latestVal = d.latest.value;
    let priorVal = null;
    if (dates.length) {
      const targetTime = new Date(dates[dates.length - 1]).getTime() - 365 * 86400000;
      priorVal = valueNearDate(dates, vals, targetTime);
    }
    const delta = (latestVal != null && priorVal != null) ? latestVal - priorVal : null;
    const pct = d.latest.pct_full;
    const tile = document.createElement("div");
    tile.className = "context-tile";
    tile.title = "vs ~12 months earlier" + (priorVal != null ? `: ${fmtContextValue(id, priorVal)}` : "");
    tile.innerHTML =
      `<div class="context-label">${CONTEXT_LABEL[id]}</div>` +
      `<div class="context-value">${fmtContextValue(id, latestVal)}</div>` +
      `<div class="context-delta">${fmtContextDelta(id, delta)}</div>` +
      `<span class="chip">pct ${pct != null ? Math.round(pct) : "n/a"}</span>`;
    tile.addEventListener("click", () => selectPrimary(id, true));
    el.appendChild(tile);
  }
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
