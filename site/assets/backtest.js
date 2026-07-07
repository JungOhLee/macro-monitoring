const DARK = { paper_bgcolor: "#1b2029", plot_bgcolor: "#1b2029", font: { color: "#e6e9ef", size: 12 } };
const CFG = { displayModeBar: false, responsive: true };
const fmtPct = v => v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

function renderReportCard(bt) {
  const rows = bt.report_card.map(r => {
    if (r.control) {
      return `<tr><td>${r.name}</td><td>${r.peak}</td>` +
             `<td colspan="5">${r.engaged_months} engaged month${r.engaged_months === 1 ? "" : "s"} in 2019 (control target: 0)</td>` +
             `<td>${r.note || ""}</td></tr>`;
    }
    return `<tr><td>${r.name}</td><td>${r.peak}</td><td>${r.first_engaged ?? "never"}</td>` +
           `<td>${r.first_stage4 ?? "never"}</td><td>${r.lead_months ?? "–"}</td>` +
           `<td>${fmtPct(r.max_drawdown_pct)}</td><td>${r.months_to_trough ?? "–"}</td><td>${r.note || ""}</td></tr>`;
  }).join("");
  document.getElementById("bt-report").innerHTML =
    `<table class="bt-table"><tr><th>Episode</th><th>Peak</th><th>First engaged</th>` +
    `<th>First stage ≥ 4</th><th>Lead (months)</th><th>Drawdown after peak</th>` +
    `<th>Months to trough</th><th>Note</th></tr>${rows}</table>`;
}

// The 3-row replay figure, unchanged from the previous inline version of this page.
function renderChart(bt) {
  const shapes = bt.episodes.filter(e => e.criterion !== false || e.control).map(e => {
    const peak = new Date(e.peak); const start = new Date(peak); start.setMonth(start.getMonth() - 24);
    return { type: "rect", x0: start.toISOString().slice(0, 10), x1: e.peak, y0: 0, y1: 1,
             yref: "paper", fillcolor: "rgba(214,69,69,.08)", line: { width: 0 } };
  });
  Plotly.newPlot("bt-chart", [
    { x: bt.months, y: bt.spx, name: "S&P 500 (log)", yaxis: "y", line: { color: "#e6e9ef", width: 1.4 } },
    { x: bt.months, y: bt.composite, name: "Composite", yaxis: "y2", line: { color: "#e0b83c", width: 1.2 } },
    { x: bt.months, y: bt.stage, name: "Sequence stage", yaxis: "y3", line: { color: "#d64545", width: 1.2, shape: "hv" } },
  ], { ...DARK, height: 520, shapes, grid: { rows: 3, columns: 1, roworder: "top to bottom" },
       yaxis: { type: "log", title: { text: "S&P 500" } },
       yaxis2: { range: [0, 100], title: { text: "score" } },
       yaxis3: { range: [0, 6.5], dtick: 1, title: { text: "stage" } },
       legend: { orientation: "h", y: -0.08 } }, CFG);
}

function renderCriteria(bt) {
  document.getElementById("bt-criteria").innerHTML = "<ul>" + bt.criteria.map(c =>
    `<li>${c.pass ? "✅" : "❌"} ${c.name} <span class="muted">(${c.detail})</span></li>`).join("") + "</ul>";
}

function renderAlarms(bt) {
  const head = `<tr><th>Engaged from</th><th>To</th><th>Months</th><th>Episode</th>` +
               `<th>S&P +12m later</th><th>Worst dip within 12m</th></tr>`;
  const row = a => `<tr><td>${a.start}</td><td>${a.end}</td><td>${a.months}</td>` +
    `<td>${a.episode ?? "–"}</td><td>${fmtPct(a.fwd_12m_pct)}</td><td>${fmtPct(a.max_dd_12m_pct)}</td></tr>`;
  const warn = bt.alarms.filter(a => a.in_window), fals = bt.alarms.filter(a => !a.in_window);
  document.getElementById("bt-alarms").innerHTML =
    `<h3>Warnings that preceded a crisis</h3>` +
    (warn.length ? `<table class="bt-table">${head}${warn.map(row).join("")}</table>`
                 : `<p class="muted">None.</p>`) +
    `<h3>False alarms</h3>` +
    (fals.length ? `<table class="bt-table">${head}${fals.map(row).join("")}</table>`
                 : `<p class="muted">None in ${bt.months.length} replayed months.</p>`);
}

function regimeOf(score, bands) {
  if (score == null) return null;
  for (const b of bands) if (score <= b.upper) return b.name;
  return bands[bands.length - 1].name;
}

// One grouped-box figure: x = group label, one box trace per horizon.
function fwdBoxFigure(elId, groups, bt, title) {
  const horizons = [["fwd_6m", "6m"], ["fwd_12m", "12m"], ["fwd_24m", "24m"]];
  const traces = horizons.map(([key, label]) => {
    const x = [], y = [];
    for (const g of groups) for (const i of g.idx) {
      const v = bt[key][i];
      if (v != null) { x.push(g.label); y.push(v); }
    }
    return { type: "box", name: label, x, y, boxpoints: false };
  });
  Plotly.newPlot(elId, traces, { ...DARK, boxmode: "group", height: 330,
    margin: { l: 45, r: 15, t: 30, b: 60 }, title: { text: title, font: { size: 13 } },
    yaxis: { title: { text: "forward return %" }, zeroline: true, zerolinecolor: "#8b93a3" },
    legend: { orientation: "h", y: -0.25 } }, CFG);
}

function pctNegative12m(bt, idx) {
  const vals = idx.map(i => bt.fwd_12m[i]).filter(v => v != null);
  return vals.length ? Math.round(100 * vals.filter(v => v < 0).length / vals.length) : null;
}

function renderForwardReturns(bt) {
  const n = bt.months.length;
  const all = { label: `all (n=${n})`, idx: [...Array(n).keys()] };

  const regimeGroups = bt.regime_bands.map(b => ({ name: b.name, label: b.name.replace("_", " "), idx: [] }));
  bt.composite.forEach((c, i) => {
    const r = regimeOf(c, bt.regime_bands);
    if (r) regimeGroups.find(g => g.name === r).idx.push(i);
  });
  regimeGroups.forEach(g => { g.label = `${g.label} (n=${g.idx.length})`; });
  fwdBoxFigure("bt-fwd-regime", [all, ...regimeGroups], bt,
               "S&P 500 forward returns by composite regime at the time");

  const stageGroups = [
    { label: "stage 0", test: s => s === 0 },
    { label: "stage 1–3", test: s => s >= 1 && s <= 3 },
    { label: "stage ≥ 4", test: s => s >= 4 },
  ].map(g => ({ label: g.label, idx: bt.stage.map((s, i) => g.test(s) ? i : -1).filter(i => i >= 0) }));
  stageGroups.forEach(g => { g.label = `${g.label} (n=${g.idx.length})`; });
  fwdBoxFigure("bt-fwd-stage", [all, ...stageGroups], bt,
               "S&P 500 forward returns by sequence stage at the time");

  const noteParts = [all, ...regimeGroups, ...stageGroups].map(g => {
    const p = pctNegative12m(bt, g.idx);
    return p == null ? null : `${g.label}: ${p}% of 12-month windows negative`;
  }).filter(Boolean);
  document.getElementById("bt-fwd-note").textContent = noteParts.join(" · ");
}

fetch("data/backtest.json").then(r => r.json()).then(bt => {
  renderReportCard(bt);
  renderChart(bt);
  renderCriteria(bt);
  renderForwardReturns(bt);
  renderAlarms(bt);
});
