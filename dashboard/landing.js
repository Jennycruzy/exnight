const $ = (id) => document.getElementById(id);
const STATIC_SITE = window.location.hostname.endsWith("github.io") || new URLSearchParams(window.location.search).has("static");

function fmt(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const text = Number(value).toFixed(digits);
  return text.startsWith("-") ? `−${text.slice(1)}` : text;
}

function chip(value) {
  const text = value || "—";
  return `<span class="verdict ${text}">${text}</span>`;
}

// Calculator: selling first avoids the price drop but gives up the dividend you would have kept,
// and pays a round-trip trading cost. All values are in basis points of the token price.
const inputs = {yield: $("c-yield"), pdr: $("c-pdr"), wh: $("c-wh"), cost: $("c-cost")};

function calc() {
  const y = Number(inputs.yield.value), pdr = Number(inputs.pdr.value);
  const wh = Number(inputs.wh.value) / 100, cost = Number(inputs.cost.value);
  const gain = pdr * y, keep = (1 - wh) * y, total = gain - keep - cost;
  const exit = total > 0;
  $("c-yield-v").textContent = `${(y / 100).toFixed(2)}%`;
  $("c-pdr-v").textContent = `${pdr.toFixed(2)}×`;
  $("c-wh-v").textContent = `${Math.round(wh * 100)}%`;
  $("c-cost-v").textContent = `${cost} bps`;
  $("c-verdict").textContent = exit ? "EXIT" : "HOLD";
  $("c-verdict").className = `calc-verdict ${exit ? "EXIT" : "HOLD"}`;
  $("c-sub").textContent = exit
    ? `Selling before the cutoff and buying back after wins by ${fmt(total)} bps.`
    : pdr <= 1 - wh
      ? "The expected drop is smaller than the dividend you'd keep, so selling can't win at any cost."
      : `Selling first would lose ${fmt(-total)} bps once costs are paid.`;
  const max = Math.max(gain, keep, cost, 1);
  [["gain", gain], ["keep", keep], ["cost", cost]].forEach(([key, value]) => {
    $(`b-${key}`).style.width = `${(value / max) * 100}%`;
    $(`b-${key}-v`).textContent = fmt(value);
  });
  $("l-gain").textContent = `+${fmt(gain)} bps`;
  $("l-keep").textContent = `−${fmt(keep)} bps`;
  $("l-cost").textContent = `−${fmt(cost)} bps`;
  $("l-total").textContent = `${total >= 0 ? "+" : ""}${fmt(total)} bps`;
  $("l-total").className = total > 0 ? "positive" : "negative";
  const usd = total / 10000 * 1000;
  $("c-usd").textContent = `${usd >= 0 ? "+" : "−"}$${Math.abs(usd).toFixed(2)}`;
}

Object.values(inputs).forEach((input) => input.addEventListener("input", () => {
  document.querySelectorAll("[data-preset], [data-pdr]").forEach((b) => {
    if (b.dataset.preset) b.classList.toggle("on", Number(b.dataset.preset) === Number(inputs.yield.value));
    if (b.dataset.pdr) b.classList.toggle("on", Number(b.dataset.pdr) === Number(inputs.pdr.value));
  });
  calc();
}));
document.querySelectorAll("[data-preset]").forEach((button) => button.addEventListener("click", () => {
  inputs.yield.value = button.dataset.preset; inputs.yield.dispatchEvent(new Event("input"));
}));
document.querySelectorAll("[data-pdr]").forEach((button) => button.addEventListener("click", () => {
  inputs.pdr.value = button.dataset.pdr; inputs.pdr.dispatchEvent(new Event("input"));
}));
calc();

// Live evidence from the same committed snapshot the app uses.
async function live() {
  try {
    const response = await fetch(STATIC_SITE ? "api/summary.json" : `/api/summary?t=${Date.now()}`, {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const exit = (data.comparison?.rows || []).find((row) => row.name === "Always step out");
    if (exit) {
      $("s-exit").textContent = fmt(exit.active_bps_per_event);
      if (exit.beat_hold_share != null) $("s-beat").textContent = `${Math.round(exit.beat_hold_share * 100)}%`;
    }
    if (data.comparison?.events) $("s-oos").textContent = data.comparison.events;
    const events = data.v3?.events || [];
    const scored = events.filter((event) => event.score_status && event.score_status !== "NOT_SCORED");
    $("s-live").textContent = `${scored.length} / ${events.length}`;
    const latest = scored.at(-1) || events[0];
    if (!latest) { $("lc-foot").textContent = "No live events scheduled."; return; }
    const done = latest.score_status && latest.score_status !== "NOT_SCORED";
    $("lc-symbol").textContent = latest.symbol;
    $("lc-verdict").innerHTML = chip(done ? (latest.modeled_verdict || latest.realised_verdict) : latest.verdict);
    $("lc-date").textContent = latest.ex_date;
    $("lc-div").textContent = `$${Number(latest.gross_dividend).toFixed(2)} · ${fmt(latest.gross_yield_bp, 0)} bps`;
    $("lc-frozen").innerHTML = chip(latest.verdict);
    const edge = latest.modeled_edge_keep_70pct;
    $("lc-edge").textContent = edge == null ? "pending" : `${edge < 0 ? "−" : "+"}$${Math.abs(edge).toFixed(2)} / share`;
    $("lc-edge").className = edge == null ? "" : edge < 0 ? "negative" : "positive";
    $("lc-rec").textContent = done ? latest.score_status : "in progress";
    const next = events.find((event) => !event.score_status || event.score_status === "NOT_SCORED");
    $("lc-foot").innerHTML = done
      ? `${edge != null && edge < 0 ? "Holding was right: selling first would have lost money. " : ""}${next ? `Next: <b>${next.symbol}</b> on ${next.ex_date}.` : "All scheduled events scored."}`
      : "Recording now. Graded automatically after the ex-date.";
  } catch (error) {
    $("lc-foot").textContent = `Live evidence unavailable (${error.message}).`;
  }
}
live();
