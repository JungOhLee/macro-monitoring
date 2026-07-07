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

fetch("data/backtest.json").then(r => r.json()).then(bt => {
  renderReportCard(bt);
  renderChart(bt);
  renderCriteria(bt);
  renderAlarms(bt);
});
