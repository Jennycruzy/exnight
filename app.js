const $ = (id) => document.getElementById(id);
const STATIC_SITE = window.location.hostname.endsWith("github.io");
const siteUrl = (path) => new URL(path, new URL(".", window.location.href)).toString();
let latestData = null;
let staticDecisions = null;
let staticSignalDates = null;
let activeFilter = "ALL";
let activeSymbol = "ALL";
let activeDate = null;
let chartSymbol = null;
const routes = new Set(["home", "signals", "recorder", "evidence", "validation"]);

function currentRoute() {
  const route = window.location.hash.replace(/^#\/?/, "").split("/")[0].toLowerCase();
  return routes.has(route) ? route : "home";
}

function updateRoute({scroll = true} = {}) {
  const route = currentRoute();
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.dataset.view === route));
  document.querySelectorAll(".section-nav [data-route-link]").forEach((link) => {
    const active = link.dataset.routeLink === route;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  if (scroll) window.scrollTo({top: 0, behavior: "smooth"});
}

function esc(value) {
  return String(value ?? "—").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[char]));
}

function number(value, digits = 2) {
  return value == null || Number.isNaN(Number(value)) ? "—" : Number(value).toFixed(digits);
}

function verdict(value) {
  const text = value || "UNKNOWN";
  return `<span class="verdict ${esc(text)}">${esc(text)}</span>`;
}

function signed(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const text = Number(value).toFixed(digits);
  return text.startsWith("-") ? `−${text.slice(1)}` : text;
}

function pctText(value, digits = 3) {
  return value == null ? "—" : `${signed(value * 100, digits)}%`;
}

function renderComparison(comparison) {
  if (comparison.status !== "AVAILABLE") {
    $("summary-headline").textContent = "Exnight decides whether stepping out before an ex-date is worth it";
    $("comparison-body").innerHTML = `<tr><td colspan="6" class="empty">Comparison unavailable.</td></tr>`;
    return;
  }
  const exit = comparison.rows.find((row) => row.name === "Always step out") || {};
  $("summary-headline").textContent = `Stepping out before every ex-date lost ${signed(-exit.active_bps_per_event)} bps per event. Exnight stood down.`;
  $("comparison-body").innerHTML = comparison.rows.map((row) => `<tr><td><strong>${esc(row.name)}</strong></td><td>${row.trades}</td>`
    + `<td class="${row.active_bps_per_event < 0 ? "negative" : ""}">${row.active_bps_per_event == null ? "—" : `${signed(row.active_bps_per_event)} bps`}</td>`
    + `<td>${row.beat_hold_share == null ? "—" : `${Math.round(row.beat_hold_share * 100)}% of events`}</td>`
    + `<td>${pctText(row.total_return)}</td><td>${signed(row.sharpe, 2)}</td></tr>`).join("");
  $("comparison-note").textContent = `${comparison.events} events over ${comparison.days} days, using only information published before each decision. `
    + "Holding's negative return comes from market moves on those nights. The always-step-out comparison was added after the results were known and changes no frozen input.";
}

function renderUpcoming(v3) {
  if (v3.status !== "AVAILABLE") {
    $("upcoming-body").innerHTML = `<tr><td colspan="6" class="empty">No forward schedule available.</td></tr>`;
    $("upcoming-tag").textContent = "UNAVAILABLE";
    return;
  }
  $("upcoming-tag").textContent = `${v3.scored} OF ${v3.events.length} SCORED`;
  $("upcoming-note").textContent = `Every event with a verified dividend worth at least ${number(v3.min_gross_yield_bp, 1)} bps of the price, the smallest size where stepping out could ever pay. `
    + `Each decision is frozen before the 20:00 ET sell cutoff. V3 currently expects a drop of at least ${number(v3.lower_ratio, 2)} of the dividend, `
    + "below the 0.70 a holder keeps after 30% withholding, so it holds unless that estimate tightens.";
  $("upcoming-body").innerHTML = v3.events.map((event) => {
    const outcome = event.score_status === "NOT_SCORED" ? `<span class="source">after ${esc(event.ex_date)} 10:30 ET</span>`
      : `${verdict(event.realised_verdict || event.score_status)}<br><span class="source">price fell ${number(event.realised_pdr, 2)}× the dividend · ${esc(event.score_status)}</span>`;
    const why = event.verdict === "PENDING" ? event.reason
      : event.verdict === "NO_SIGNAL" ? (event.reason || "evidence incomplete")
      : `break-even yield ${event.breakeven_yield_bp == null ? "not reachable" : `${number(event.breakeven_yield_bp, 0)} bps`} · ${event.entitlement_tier === "E1_DOCUMENTED_PRECEDENT" ? "30% withholding documented" : "withholding 0–30%"}`;
    return `<tr><td><strong>${esc(event.symbol)}</strong></td><td>${esc(event.ex_date)}</td><td>$${number(event.gross_dividend, 4)}<br><span class="source">${number(event.gross_yield_bp, 0)} bps of price</span></td>`
      + `<td>${verdict(event.verdict)}</td><td class="source">${esc(why)}</td><td>${outcome}</td></tr>`;
  }).join("");
}

function render(data) {
  latestData = data;
  const recorder = data.recorder || {};
  const meta = (data.signals || {}).meta || {};
  const rows = (data.signals || {}).rows || [];
  const health = data.depth || {};
  const score = data.forward_score || {};
  const observation = data.observation || {};
  const provenance = data.provenance || {};
  const competition = data.competition || {};
  const failed = recorder.status !== "PASS";
  const scored = observation.status === "SCORED";

  renderComparison(data.comparison || {});
  renderUpcoming(data.v3 || {});

  const generated = new Date(data.generated_at);
  $("as-of").textContent = Number.isNaN(generated.getTime()) ? "Snapshot time unknown" : `Snapshot ${generated.toLocaleString([], {year:"numeric", month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", timeZoneName:"short"})}`;
  $("event-date").textContent = observation.event_date || meta.event_date || "window pending";
  $("headline").textContent = scored
    ? (failed ? "Recorder audit needs attention" : score.status === "PASS" ? "Forward window scored" : "Recording passed; score incomplete")
    : (failed ? "Observation window needs attention" : "Observation window is collecting");
  $("hero-copy").textContent = scored ? (observation.message || score.message || "Saved forward evidence is available.")
    : failed ? `${(recorder.errors || []).join(" · ")} Decisions remain available, with the recording issue shown in their evidence.`
    : "The recorder is collecting evidence for the scheduled forward window.";
  const hero = $("hero-status"); hero.className = `hero-status ${failed ? "bad" : "ok"}`;
  hero.innerHTML = `<span class="status-orb"></span><div><strong>${failed ? "Recorder attention" : scored ? "Recorder passed" : "Recorder healthy"}</strong><small>${(recorder.sample_count || 0).toLocaleString()} saved samples</small></div>`;

  $("metric-samples").textContent = (recorder.sample_count || 0).toLocaleString();
  $("metric-samples-note").textContent = `${Object.keys(recorder.symbols || {}).length} monitored symbols`;
  const scoredEvents = score.report?.results || [];
  $("metric-events").textContent = scored ? scoredEvents.length : (meta.events ?? "—");
  $("metric-events-note").textContent = scored ? `${scoredEvents.filter((row) => row.complete).length} with resolved cash basis` : `${meta.rows || 0} frozen notional rows`;
  const counts = meta.verdict_counts || {};
  $("metric-signals").textContent = Object.entries(counts).map(([key, value]) => `${value} ${key}`).join(" · ") || "—";
  $("metric-signals-note").textContent = `For ex-date ${meta.event_date || "—"}`;
  $("metric-depth").textContent = health.event_count ? `${health.book_supported_count}/${health.event_count}` : (health.status || "UNKNOWN");
  $("metric-depth-note").textContent = health.message || "No capacity report";
  $("landing-signal-count").textContent = (meta.rows || rows.length || 0).toLocaleString();
  $("landing-signal-note").textContent = `${meta.events || rows.length || 0} forward events`;
  $("landing-recorder-count").textContent = (recorder.sample_count || 0).toLocaleString();
  $("landing-recorder-note").textContent = `${Object.keys(recorder.symbols || {}).length} monitored symbols`;
  $("landing-evidence-count").textContent = score.status || "UNKNOWN";
  $("landing-evidence-note").textContent = provenance.status === "PASS" ? "provenance complete" : "provenance review";
  $("landing-validation-count").textContent = competition.sample?.eligible_ex_ante ?? "—";
  $("landing-validation-note").textContent = `${competition.oos?.policy?.event_count ?? 0} OOS events`;

  $("validation-resolved").textContent = competition.sample?.resolved_usable ?? "—";
  $("validation-eligible").textContent = competition.sample?.eligible_ex_ante ?? "—";
  $("validation-oos-events").textContent = competition.oos?.policy?.event_count ?? "—";
  $("validation-oos-days").textContent = `${competition.oos_days ?? "—"} calendar days`;
  $("validation-trades").textContent = competition.oos?.policy?.trade_count ?? "—";
  const series = [
    ["Exnight policy", competition.oos?.policy, "sharpe"],
    ["HOLD benchmark", competition.oos?.benchmark, "sharpe"],
    ["Active", competition.oos?.active, "information_ratio"],
  ];
  $("validation-series").innerHTML = series.map(([name, item, ratio]) => `<tr><td><strong>${name}</strong></td><td>${item?.total_return == null ? "—" : `${number(item.total_return * 100, 3)}%`}</td><td>${number(item?.[ratio], 2)}</td><td>${item?.maximum_drawdown == null ? "—" : `${number(item.maximum_drawdown * 100, 3)}%`}</td></tr>`).join("");
  $("validation-assumptions").innerHTML = `<dt>Historical costs</dt><dd>MODELED_EXECUTION</dd><dt>Slippage grid</dt><dd>${(competition.cost_grid_bps || []).join(" / ") || "—"} bps round trip</dd><dt>Withholding range</dt><dd>${(competition.withholding_range || []).join(" / ") || "—"}%</dd><dt>Interpretation</dt><dd>Exnight matched HOLD because no EXIT cleared the frozen rule.</dd>`;
  $("validation-note").innerHTML = `<strong>Rolling 30-day Sharpe · INSUFFICIENT_EVENTS</strong>${competition.oos?.policy?.trade_count ?? 0} OOS EXIT trades across ${competition.oos?.policy?.event_count ?? 0} events. Active return is zero; an active information ratio is undefined.`;
  $("validation-folds").innerHTML = (competition.folds || []).map((fold) => `<tr><td>${esc(fold.fold)}</td><td>${esc(fold.training_end)}</td><td>${esc(fold.test_period)}</td><td>${esc(fold.selected_rung)}</td><td>${number(fold.pdr_estimate, 3)}</td><td>${fold.test_events ?? "—"}</td><td>${fold.test_trades ?? "—"}</td><td>${number(fold.test_sharpe, 2)}</td></tr>`).join("") || `<tr><td colspan="8" class="empty">No walk-forward scorecard available.</td></tr>`;

  activeDate = data.signals.meta.event_date || activeDate;
  $("signal-date").innerHTML = (meta.available_dates || []).map((date) => `<option value="${esc(date)}" ${date === activeDate ? "selected" : ""}>${esc(date)}</option>`).join("");
  const symbolsInRows = [...new Set(rows.map((row) => row.symbol).filter(Boolean))].sort();
  if (!symbolsInRows.includes(activeSymbol)) activeSymbol = "ALL";
  $("signal-symbol").innerHTML = ["ALL", ...symbolsInRows].map((symbol) => `<option value="${esc(symbol)}" ${symbol === activeSymbol ? "selected" : ""}>${symbol === "ALL" ? "All symbols" : esc(symbol)}</option>`).join("");
  const visibleRows = rows.filter((row) => (activeFilter === "ALL" || row.verdict === activeFilter) && (activeSymbol === "ALL" || row.symbol === activeSymbol));
  $("signals-body").innerHTML = visibleRows.length ? visibleRows.map((row) => {
    const edge = row.exit_edge_lower == null ? "—" : `${number(row.exit_edge_lower, 3)} / ${number(row.cost_per_share, 3)}`;
    const source = `${row.sell_book_source || "—"} → ${row.buy_book_source || "—"}`;
    const rowIndex = rows.indexOf(row);
    return `<tr class="signal-row" data-row-index="${rowIndex}" tabindex="0" aria-label="Open ${esc(row.symbol)} signal detail"><td><strong>${esc(row.symbol)}</strong><br><span class="source">${esc(row.spot_symbol)} · ${esc(row.ex_date)}</span></td><td>$${Number(row.notional_usd || 0).toLocaleString()}</td><td>${verdict(row.verdict)}<br><span class="source">${esc(row.reason || "no additional reason")}</span></td><td class="${row.exit_edge_lower > 0 ? "positive" : "negative"}">${esc(edge)}</td><td class="source">${esc(source)}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="empty">No rows match the current filters.</td></tr>`;

  const filterValues = ["ALL", ...Object.keys(meta.verdict_counts || {})];
  $("signal-filters").innerHTML = filterValues.map((filter) => `<button type="button" class="filter-button ${activeFilter === filter ? "active" : ""}" data-filter="${esc(filter)}">${esc(filter)}${filter === "ALL" ? "" : ` · ${meta.verdict_counts[filter] || 0}`}</button>`).join("");

  const symbols = recorder.symbols || {};
  $("recorder-list").innerHTML = Object.entries(symbols).map(([symbol, item]) => {
    const coverage = Math.round((item.book_coverage || 0) * 100);
    const warn = coverage === 0 || (item.max_gap_seconds || 0) > 180;
    return `<div class="health-row"><div class="health-name"><strong>${esc(symbol)}</strong><small>${(item.rows || 0).toLocaleString()} rows · ${recorder.mode === "COMPLETED_WINDOW" ? "ended" : "last"} ${esc(item.last_age_display)}</small></div><div class="health-stat"><strong>${coverage}% public book</strong><div class="health-bar"><i class="${warn ? "warn" : ""}" style="width:${Math.max(coverage, 3)}%"></i></div></div></div>`;
  }).join("");
  $("recorder-badge").className = `badge ${failed ? "bad" : "ok"}`; $("recorder-badge").textContent = recorder.status || "UNKNOWN";
  $("recorder-errors").textContent = (recorder.errors || []).join(" · ");

  $("score-badge").className = `badge ${score.status === "PASS" ? "ok" : "warn"}`; $("score-badge").textContent = score.status || "UNKNOWN";
  $("score-panel").innerHTML = `<strong>${esc(score.status || "UNKNOWN")}</strong>${esc(score.message || "No forward-score report available.")}`;
  $("forward-events").innerHTML = (score.report?.results || []).map((event) => {
    const decision = event.notionals?.find((item) => item.notional_usd === 1000)?.frozen_verdict || "NO_SIGNAL";
    const prices = event.pre_price == null || event.post_price == null
      ? "Unavailable" : `${number(event.pre_price, 2)} → ${number(event.post_price, 2)}`;
    const outcome = event.complete
      ? (event.pre_price === event.post_price ? "No price change" : "Cash basis resolved")
      : "Cash-adjusted result unavailable";
    return `<tr><td><strong>${esc(event.symbol)}</strong></td><td><span class="verdict ${esc(decision)}">${esc(decision)}</span></td><td>${event.gross_dividend == null ? "Unresolved" : "Resolved"}</td><td>${esc(prices)}</td><td>${esc(outcome)}</td></tr>`;
  }).join("") || `<tr><td colspan="5" class="empty">No scored forward events available.</td></tr>`;
  $("timeline-observation").className = `timeline-item ${scored ? (failed ? "active" : "done") : "active"}`;
  $("timeline-observation-note").textContent = scored ? `${(recorder.sample_count || 0).toLocaleString()} samples; ${failed ? "integrity review needed" : "cadence passed"}` : "Recorder is collecting one-minute samples";
  $("timeline-forward").className = `timeline-item ${score.status === "PASS" ? "done" : scored ? "active" : ""}`;
  $("timeline-forward-note").textContent = scored ? (score.message || "Forward score available") : "Runs after the observation window closes";
  $("provenance-badge").className = `badge ${provenance.status === "PASS" ? "ok" : "warn"}`; $("provenance-badge").textContent = provenance.status || "UNKNOWN";
  $("provenance-list").innerHTML = `<dt>Manifest</dt><dd>${provenance.manifest_present ? "run_manifest_v1.json" : "missing"}</dd><dt>Signal events</dt><dd>${provenance.signal_events || 0}</dd><dt>Manifest events</dt><dd>${provenance.manifest_events || 0}</dd><dt>Commit</dt><dd>${esc(provenance.code_commit || "—")}</dd><dt>Coverage note</dt><dd>${provenance.missing_events?.length ? `Missing ${provenance.missing_events.length} event(s) from historical summary` : "Complete"}</dd>`;
  $("limits-list").innerHTML = (data.limits || []).map((item) => `<li>${esc(item)}</li>`).join("");
  $("downloads").innerHTML = (data.downloads || []).length ? `<span>DOWNLOAD EVIDENCE</span>${data.downloads.map((item) => `<a href="${esc(item.href)}">${esc(item.label)}</a>`).join("")}` : "<span>No evidence downloads available.</span>";
  renderChart(recorder);
}

function renderChart(recorder) {
  const symbols = Object.keys(recorder.symbols || {});
  if (!symbols.includes(chartSymbol)) chartSymbol = symbols[0];
  $("chart-symbol").innerHTML = symbols.map((symbol) => `<option value="${esc(symbol)}" ${symbol === chartSymbol ? "selected" : ""}>${esc(symbol)}</option>`).join("");
  const series = (recorder.symbols?.[chartSymbol]?.series || []).filter((point) => point.price != null);
  if (series.length < 2) { $("recorder-chart").innerHTML = '<span class="empty">Chart samples are unavailable in this snapshot. The saved recorder audit is shown below.</span>'; return; }
  const width = 900, height = 230, pad = 28;
  const prices = series.map((point) => Number(point.price));
  const low = Math.min(...prices), high = Math.max(...prices), spread = high - low || Math.max(high * 0.001, 1);
  const points = series.map((point, index) => {
    const x = pad + (index / (series.length - 1)) * (width - pad * 2);
    const y = height - pad - ((Number(point.price) - low) / spread) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const bookPoints = series.map((point, index) => {
    if (!point.book) return "";
    const x = pad + (index / (series.length - 1)) * (width - pad * 2);
    const y = height - pad - ((Number(point.price) - low) / spread) * (height - pad * 2);
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.5" class="book-point"/>`;
  }).join("");
  $("recorder-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="${esc(chartSymbol)} price series"><line x1="${pad}" y1="${pad}" x2="${width - pad}" y2="${pad}" class="chart-grid"/><line x1="${pad}" y1="${height / 2}" x2="${width - pad}" y2="${height / 2}" class="chart-grid"/><line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="chart-grid"/><polyline points="${points.join(" ")}" class="price-line"/>${bookPoints}<text x="${pad}" y="16" class="chart-label">${number(high, 4)}</text><text x="${pad}" y="${height - 5}" class="chart-label">${number(low, 4)}</text></svg>`;
}

function showSignal(row) {
  if (!row) return;
  $("dialog-title").textContent = `${row.symbol} · $${Number(row.notional_usd || 0).toLocaleString()}`;
  const note = row.reason || row.buy || "No additional guardrail note.";
  $("dialog-body").innerHTML = `<dt>Verdict</dt><dd>${verdict(row.verdict)}</dd><dt>Event</dt><dd>${esc(row.event_id)}</dd><dt>Reference price</dt><dd>${number(row.price, 4)}</dd><dt>Dividend</dt><dd>Gross ${number(row.gross_dividend, 4)} · net ${number(row.net_dividend, 4)}</dd><dt>Exit edge / cost</dt><dd>${number(row.exit_edge_lower, 4)} / ${number(row.cost_per_share, 4)}</dd><dt>Book evidence</dt><dd>${esc(row.sell_book_source)} → ${esc(row.buy_book_source)}</dd><div class="dialog-note">${esc(note)}</div>`;
  $("signal-dialog").showModal();
}

function renderDecision(result) {
  const target = $("decision-result");
  if (result.status !== "FOUND") {
    target.className = "decision-result decision-empty";
    target.innerHTML = `<strong>No decision available</strong><span>${esc(result.message || "This token has not been evaluated yet.")}</span>`;
    return;
  }
  const rows = result.rows || [];
  const verdicts = [...new Set(rows.map((row) => row.verdict || "NO_SIGNAL"))];
  const summary = verdicts.length === 1 ? verdicts[0] : "VARIES BY SIZE";
  target.className = "decision-result decision-found";
  target.innerHTML = `
    <div class="decision-summary">
      <div><span>${esc(result.symbol)} · ${esc(result.spot_symbol)}</span><strong>${esc(summary)}</strong><small>Nearest evaluated event · ${esc(result.event_date)}</small></div>
      ${verdicts.length === 1 ? verdict(verdicts[0]) : '<span class="verdict HOLD">CHECK SIZE</span>'}
    </div>
    <div class="decision-options">${rows.map((row) => `
      <article>
        <span>$${Number(row.notional_usd || 0).toLocaleString()} trade size</span>
        ${verdict(row.verdict)}
        <p>${esc(row.reason || "Decision produced from the saved Strategy v1 evidence.")}</p>
        <small>Edge ${number(row.exit_edge_lower, 4)} · cost ${number(row.cost_per_share, 4)} · ${esc(row.sell_book_source || "no sell-book evidence")} → ${esc(row.buy_book_source || "no buy-book evidence")}</small>
      </article>`).join("")}</div>
    <a class="decision-more" href="#/signals">Open full decision evidence →</a>`;
}

function currentStaticDecision(record) {
  if (!record?.events) return record;
  const dates = Object.keys(record.events).sort();
  const today = new Date().toISOString().slice(0, 10);
  const selected = dates.find((date) => date >= today) || dates.at(-1);
  return {
    status: "FOUND", symbol: record.symbol, spot_symbol: record.spot_symbol,
    event_date: selected, rows: record.events[selected] || [], available_dates: dates,
  };
}

async function lookupDecision(symbol) {
  const target = $("decision-result");
  target.className = "decision-result decision-loading";
  target.innerHTML = "<span>Checking saved Exnight decisions…</span>";
  try {
    if (STATIC_SITE) {
      if (!staticDecisions) {
        const response = await fetch(siteUrl("api/decisions.json"), {cache:"no-store"});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        staticDecisions = await response.json();
      }
      const key = symbol.toUpperCase().replace(/[^A-Z0-9]/g, "");
      renderDecision(currentStaticDecision(staticDecisions[key]) || {
        status: "NOT_EVALUATED", query: symbol,
        message: "This token has no saved Exnight decision.",
      });
    } else {
      const response = await fetch(`/api/decision?symbol=${encodeURIComponent(symbol)}&t=${Date.now()}`, {cache:"no-store"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderDecision(await response.json());
    }
  } catch (error) {
    target.className = "decision-result decision-empty";
    target.innerHTML = `<strong>Decision lookup unavailable</strong><span>${esc(error.message)}</span>`;
  }
}

async function refresh() {
  try {
    const dateQuery = activeDate ? `&date=${encodeURIComponent(activeDate)}` : "";
    const url = STATIC_SITE ? siteUrl("api/summary.json") : `/api/summary?t=${Date.now()}${dateQuery}`;
    const response = await fetch(url, {cache:"no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (STATIC_SITE && activeDate && activeDate !== data.signals?.meta?.event_date) {
      if (!staticSignalDates) {
        const datesResponse = await fetch(siteUrl("api/signal_dates.json"), {cache:"no-store"});
        if (!datesResponse.ok) throw new Error(`HTTP ${datesResponse.status}`);
        staticSignalDates = await datesResponse.json();
      }
      if (staticSignalDates[activeDate]) data.signals = staticSignalDates[activeDate];
    }
    render(data); $("error").classList.add("hidden");
  } catch (error) {
    $("error").textContent = `Dashboard data unavailable: ${error.message}`; $("error").classList.remove("hidden");
  }
}

document.addEventListener("click", (event) => {
  const filter = event.target.closest?.("[data-filter]");
  if (filter) { activeFilter = filter.dataset.filter; if (latestData) render(latestData); return; }
  const row = event.target.closest?.(".signal-row");
  if (row && latestData) showSignal(latestData.signals.rows[Number(row.dataset.rowIndex)]);
});
document.addEventListener("keydown", (event) => {
  if ((event.key === "Enter" || event.key === " ") && event.target.closest?.(".signal-row")) {
    event.preventDefault(); const row = event.target.closest(".signal-row");
    if (latestData) showSignal(latestData.signals.rows[Number(row.dataset.rowIndex)]);
  }
});
$("refresh-button").addEventListener("click", refresh);
$("dialog-close").addEventListener("click", () => $("signal-dialog").close());
$("signal-date").addEventListener("change", (event) => { activeDate = event.target.value; refresh(); });
$("signal-symbol").addEventListener("change", (event) => { activeSymbol = event.target.value; if (latestData) render(latestData); });
$("chart-symbol").addEventListener("change", (event) => { chartSymbol = event.target.value; if (latestData) renderChart(latestData.recorder); });
$("decision-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const symbol = $("decision-symbol").value.trim();
  if (symbol) lookupDecision(symbol);
});

window.addEventListener("hashchange", () => updateRoute());
updateRoute({scroll: false});
refresh();
// The public Pages site is a fixed snapshot; only the local dashboard polls for new data.
if (!STATIC_SITE) setInterval(refresh, 30000);
