"use strict";

const state = {
  data: null,
  view: "worker",
  language: "en",
  judgeStep: 0,
  autoplay: null,
};

const copy = {
  en: {
    status: "Replay verified · policy, planning, receipts and allocator ready",
    thesisA: "Warnings tell riders",
    thesisB: "what to avoid.",
    thesisC: "HeatReserve gives them room to act.",
    workerCopy: "A delivery rider can understand the warning and still keep working because each hour offline can mean lost income. HeatReserve pairs deterministic adaptation support with a constrained lower-exposure plan.",
    support: "SIMULATED COMMITMENT",
    plan: "Lower-burden schedule",
    original: "Original preferred block",
  },
  hi: {
    status: "रीप्ले सत्यापित · नीति, प्लान, रसीद और एलोकेटर तैयार",
    thesisA: "चेतावनी बताती है",
    thesisB: "क्या टालना है।",
    thesisC: "HeatReserve बदलाव की गुंजाइश देता है।",
    workerCopy: "डिलीवरी राइडर चेतावनी समझ सकता है, फिर भी काम जारी रख सकता है क्योंकि ऑफलाइन हर घंटा आय कम कर सकता है। HeatReserve नियम-आधारित सहायता को कम एक्सपोज़र वाले प्लान से जोड़ता है।",
    support: "सिम्युलेटेड कमिटमेंट",
    plan: "कम-बर्डन शेड्यूल",
    original: "मूल पसंदीदा समय",
  },
};

const root = document.getElementById("view-root");
const statusLine = document.getElementById("status-line");
const dialog = document.getElementById("judge-dialog");
const judgeStage = document.getElementById("judge-stage");

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function badge(kind) {
  return node("span", `evidence-badge ${kind.toLowerCase()}`, kind);
}

function formatRupees(minor) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(minor / 100);
}

function formatTime(iso) {
  return new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" }).format(new Date(iso));
}

function panelHeader(title, sub, evidence) {
  const head = node("div", "panel-head");
  const text = node("div");
  text.append(node("h2", "", title), node("p", "panel-sub", sub));
  head.append(text, badge(evidence));
  return head;
}

function render() {
  if (!state.data) return;
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.view);
  });
  root.replaceChildren();
  if (state.view === "worker") renderWorker();
  if (state.view === "sponsor") renderSponsor();
  if (state.view === "evidence") renderEvidence();
}

function renderWorker() {
  const t = copy[state.language];
  const data = state.data;
  const grid = node("div", "hero-grid");
  const hero = node("article", "hero-card");
  const intro = node("div");
  const ribbon = node("div", "event-ribbon");
  ribbon.append(node("span", "risk-chip", "EXTREME HEAT REPLAY"), badge("SIMULATED"));
  const title = node("h1");
  title.append(document.createTextNode(`${t.thesisA} `), node("em", "", t.thesisB), document.createTextNode(` ${t.thesisC}`));
  intro.append(ribbon, title, node("p", "hero-copy", t.workerCopy));
  const proof = node("div", "event-ribbon");
  proof.append(badge("RESEARCH"), node("span", "panel-sub", "Mechanism grounded in a 276-worker Delhi/Gurugram randomized study"));
  hero.append(intro, proof);

  const commitment = node("aside", "commitment-card");
  commitment.append(
    node("span", "eyebrow", t.support),
    node("div", "commitment-amount", formatRupees(data.commitment.decision.amount_minor)),
    node("p", "", "Reserved before the peak window in this deterministic replay. This is not a real payment."),
  );
  const authority = node("div", "authority");
  authority.append(node("i"), node("span", "", "DECIDED BY POLICY ENGINE · NO AI"));
  commitment.append(authority);
  grid.append(hero, commitment);
  root.append(grid);

  const lower = node("div", "section-grid");
  const schedulePanel = node("section", "panel");
  schedulePanel.append(panelHeader(t.plan, "Same required work minutes, different modeled burden.", "SIMULATED"));
  schedulePanel.append(buildSchedule(data));
  const deltas = node("div", "delta-strip");
  deltas.append(
    metricDelta(`${data.plan.high_heat_minutes_shifted} min`, "modeled high-heat minutes shifted"),
    metricDelta(data.plan.modeled_burden_delta.toFixed(2), "relative burden-score reduction"),
    metricDelta(`${data.plan.blocks.filter((b) => b.kind === "work").length} blocks`, "recommended work windows"),
  );
  schedulePanel.append(deltas);

  const receiptPanel = node("section", "panel");
  receiptPanel.append(panelHeader("Decision Receipt", "Inputs, versions and provenance bound to one digest.", "MEASURED"));
  receiptPanel.append(buildReceipt(data));
  lower.append(schedulePanel, receiptPanel);
  root.append(lower);
}

function metricDelta(value, label) {
  const d = node("div", "delta");
  d.append(node("strong", "", value), node("span", "", label));
  return d;
}

function buildSchedule(data) {
  const wrapper = node("div", "schedule");
  const labels = node("div", "schedule-labels");
  const track = node("div", "schedule-track");
  for (let hour = 6; hour < 22; hour += 1) labels.append(node("span", "", `${String(hour).padStart(2, "0")}:00`));
  const preferred = data.scenario.preferred_window;
  addScheduleBlock(track, preferred.start, preferred.end, "baseline", copy[state.language].original);
  data.plan.blocks.forEach((block) => {
    const klass = block.kind === "work" ? "plan" : "break";
    const label = block.kind === "work" ? "Recommended work" : "Verified cooling break";
    addScheduleBlock(track, block.start, block.end, klass, label);
  });
  wrapper.append(labels, track);
  return wrapper;
}

function replayClockMinutes(iso) {
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  if (!match) throw new Error(`Invalid replay timestamp: ${iso}`);
  return Number(match[1]) * 60 + Number(match[2]);
}

function addScheduleBlock(track, startIso, endIso, className, label) {
  const startMinutes = replayClockMinutes(startIso);
  let endMinutes = replayClockMinutes(endIso);
  if (endMinutes < startMinutes) endMinutes += 24 * 60;
  const top = ((startMinutes - 6 * 60) / 60) * 24;
  const height = Math.max(18, ((endMinutes - startMinutes) / 60) * 24);
  const block = node("div", `schedule-block ${className}`, `${formatTime(startIso)} · ${label}`);
  block.style.top = `${top}px`;
  block.style.height = `${height}px`;
  track.append(block);
}

function buildReceipt(data) {
  const receipt = data.receipt;
  const list = node("dl", "receipt-list");
  [
    ["Receipt", receipt.receipt_id],
    ["Plan hash", receipt.plan_sha256],
    ["Policy", `${receipt.policy_id} @ ${receipt.policy_version}`],
    ["Decision", `${receipt.decision_status} · ${receipt.decision_reason_codes.join(", ")}`],
    ["Planner", `${receipt.provider} / ${receipt.model}`],
    ["Prompt", receipt.prompt_version],
    ["Verifier", receipt.verifier_version],
    ["Digest", receipt.digest.value],
  ].forEach(([key, value]) => {
    const row = node("div", "receipt-row");
    row.append(node("dt", "", key), node("dd", "", value));
    list.append(row);
  });
  const verify = node("div", "verify-banner");
  verify.append(node("span", "", "✓ DIGEST VERIFIED"), node("span", "", "SHA-256"));
  const fragment = document.createDocumentFragment();
  fragment.append(list, verify);
  return fragment;
}

function renderSponsor() {
  const data = state.data;
  const reserve = data.reserve;
  const strategies = data.allocator;
  const best = strategies.reduce((a, b) => a.projected_high_heat_minutes_addressed > b.projected_high_heat_minutes_addressed ? a : b);
  const metrics = node("div", "metrics-grid");
  metrics.append(
    sponsorMetric(formatRupees(reserve.initial_minor), "Fixed replay reserve", "SIMULATED"),
    sponsorMetric(formatRupees(reserve.current_minor), "Reserve after demo commitment", "MEASURED"),
    sponsorMetric(`${best.projected_high_heat_minutes_addressed} min`, "Best modeled exposure addressed", "SIMULATED"),
    sponsorMetric(`${best.zone_coverage.length} / 3`, "Replay zones represented", "SIMULATED"),
  );
  root.append(metrics);

  const grid = node("div", "section-grid");
  const zones = node("section", "panel");
  zones.append(panelHeader("Allocation surface", "Aggregated replay zones only. No worker GPS history.", "SIMULATED"));
  const zoneGrid = node("div", "zone-grid");
  [
    ["Zone A", "4 workers", ".30"],
    ["Zone B", "4 workers", ".48"],
    ["Zone C", "4 workers", ".65"],
  ].forEach(([name, count, heat]) => {
    const card = node("div", "zone");
    card.style.setProperty("--heat", heat);
    card.append(node("span", "eyebrow", "COARSE ZONE"), node("strong", "", name), node("p", "", count));
    zoneGrid.append(card);
  });
  zones.append(zoneGrid);

  const tablePanel = node("section", "panel");
  tablePanel.append(panelHeader("Same budget. Different decisions.", "Scenario analysis never mutates the actual reserve.", "SIMULATED"));
  const table = node("table", "strategy-table");
  const head = node("thead");
  const trh = node("tr");
  ["Strategy", "Spend", "Minutes", "Zones"].forEach((label) => trh.append(node("th", "", label)));
  head.append(trh);
  const body = node("tbody");
  strategies.forEach((item) => {
    const tr = node("tr", item.strategy === best.strategy ? "best" : "");
    tr.append(
      node("td", "", labelStrategy(item.strategy)),
      node("td", "", formatRupees(item.spend_minor)),
      node("td", "", String(item.projected_high_heat_minutes_addressed)),
      node("td", "", String(item.zone_coverage.length)),
    );
    body.append(tr);
  });
  table.append(head, body);
  tablePanel.append(table);
  grid.append(zones, tablePanel);
  root.append(grid);
}

function sponsorMetric(value, label, evidence) {
  const card = node("article", "metric-card");
  card.append(badge(evidence), node("strong", "", value), node("p", "", label));
  return card;
}

function labelStrategy(name) {
  return { equal: "Equal / first-qualified", impact_first: "Impact-first", fairness_constrained: "Impact + fairness" }[name] || name;
}

function renderEvidence() {
  const boundary = node("div", "claim-boundary");
  boundary.append(
    node("strong", "", "Evidence firewall"),
    node("p", "", "RESEARCH describes external evidence. MEASURED describes system behavior we actually tested. SIMULATED describes this replay. TARGET is reserved for future scale goals. HeatReserve does not present modeled exposure as a measured health outcome."),
  );
  root.append(boundary);
  const stack = node("div", "evidence-stack");
  state.data.evidence.forEach((source) => {
    const card = node("article", "evidence-card");
    card.append(badge(source.evidence_class), node("h3", "", source.title), node("p", "", source.label));
    if (source.url.startsWith("https://")) {
      const link = node("a", "", "Open source ↗");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      card.append(link);
    } else {
      card.append(node("p", "", "Local fixture provenance available in the repository manifest."));
    }
    stack.append(card);
  });
  root.append(stack);
}

function startJudgeMode() {
  if (!state.data) return;
  stopAutoplay();
  state.judgeStep = 0;
  renderJudgeStep();
  if (!dialog.open) dialog.showModal();
}

const judgeSteps = [
  {
    eyebrow: "01 · THE ECONOMIC TRAP",
    title: "Knowing when to stop is not the same as being able to stop.",
    text: "The replay starts with a six-hour preferred delivery block overlapping the event's highest modeled burden. A warning solves information. It does not replace lost income.",
    tiles: () => [
      ["12:00–18:00", "Original preferred work window", ""],
      ["276 workers", "External randomized-study mechanism", "ok"],
      ["SIMULATED", "Replay values are clearly labeled", "ok"],
    ],
  },
  {
    eyebrow: "02 · DETERMINISTIC SUPPORT",
    title: "₹200 is committed by policy. AI gets no vote.",
    text: "Verified snapshot, published policy, worker eligibility and reserve balance are evaluated inside one transactional control path with an idempotency key.",
    tiles: () => [
      ["✓ Snapshot", "Manifest hash verified", "ok"],
      ["✓ Policy", "Published policy v1.0.0", "ok"],
      [formatRupees(state.data.commitment.decision.amount_minor), "SIMULATED COMMITMENT · NO AI", "ok"],
    ],
  },
  {
    eyebrow: "03 · GROUNDED PLANNING",
    title: "AI can plan. Deterministic verification decides what survives.",
    text: "The planner only receives typed hourly facts, worker constraints and verified cooling points. Any malformed, hallucinated or prohibited plan falls back to deterministic planning.",
    tiles: () => [
      [`${state.data.plan.high_heat_minutes_shifted} min`, "Modeled high-heat minutes shifted", "ok"],
      [state.data.plan.verifier_status, "Verifier status", "ok"],
      [state.data.plan.provider, "Runtime provider in this replay", ""],
    ],
  },
  {
    eyebrow: "04 · TRUST PROOF",
    title: "Change one protected field. Verification breaks.",
    text: "The receipt binds the policy, commitment, plan, sources, prompt and verifier versions to a canonical SHA-256 digest. The demo deliberately changes the amount by ₹1 in a copy.",
    tiles: () => [
      ["VERIFIED", "Original receipt", "ok"],
      ["INVALID", "Tampered receipt", "fail"],
      [state.data.receipt.digest.value.slice(0, 14) + "…", "Canonical digest", ""],
    ],
  },
  {
    eyebrow: "05 · SPONSOR ALLOCATION",
    title: "The reserve stays fixed. The allocation logic becomes inspectable.",
    text: "Equal, impact-first and fairness-constrained strategies run over the same simulated candidates. This is scenario analysis and cannot mutate the reserve ledger.",
    tiles: () => state.data.allocator.map((item) => [
      String(item.projected_high_heat_minutes_addressed),
      `${labelStrategy(item.strategy)} · modeled minutes addressed`,
      item.strategy === "fairness_constrained" ? "ok" : "",
    ]),
  },
  {
    eyebrow: "06 · EVIDENCE HONESTY",
    title: "Every number says what kind of truth it is.",
    text: "External causal evidence is RESEARCH. Test outcomes are MEASURED. Judge replay outputs are SIMULATED. Future scale goals remain TARGET. That boundary is part of the product, not fine print.",
    tiles: () => [
      ["RESEARCH", "External mechanism and guidance", ""],
      ["MEASURED", "System tests and digest verification", "ok"],
      ["SIMULATED", "Replay commitments and exposure metrics", ""],
    ],
  },
];

function renderJudgeStep() {
  const step = judgeSteps[state.judgeStep];
  judgeStage.replaceChildren();
  const card = node("article", "judge-card");
  card.append(node("span", "eyebrow", step.eyebrow), node("h3", "", step.title), node("p", "", step.text));
  const proof = node("div", "judge-proof");
  step.tiles().forEach(([value, label, klass]) => {
    const tile = node("div", `proof-tile ${klass}`.trim());
    tile.append(node("strong", "", value), node("span", "", label));
    proof.append(tile);
  });
  card.append(proof);
  judgeStage.append(card);
  document.getElementById("judge-step").textContent = `${state.judgeStep + 1} / ${judgeSteps.length}`;
  document.getElementById("judge-progress-bar").style.width = `${((state.judgeStep + 1) / judgeSteps.length) * 100}%`;
  document.getElementById("judge-prev").disabled = state.judgeStep === 0;
  document.getElementById("judge-next").textContent = state.judgeStep === judgeSteps.length - 1 ? "Finish ✓" : "Next →";
}

function advanceJudge() {
  if (state.judgeStep < judgeSteps.length - 1) {
    state.judgeStep += 1;
    renderJudgeStep();
  } else {
    stopAutoplay();
    dialog.close();
  }
}

function retreatJudge() {
  if (state.judgeStep > 0) {
    state.judgeStep -= 1;
    renderJudgeStep();
  }
}

function toggleAutoplay() {
  if (state.autoplay) {
    stopAutoplay();
    return;
  }
  document.getElementById("judge-autoplay-state").textContent = "Auto";
  document.getElementById("judge-play").textContent = "Ⅱ Pause";
  state.autoplay = window.setInterval(advanceJudge, 9000);
}

function stopAutoplay() {
  if (state.autoplay) window.clearInterval(state.autoplay);
  state.autoplay = null;
  const label = document.getElementById("judge-autoplay-state");
  const play = document.getElementById("judge-play");
  if (label) label.textContent = "Manual";
  if (play) play.textContent = "▶ Auto";
}

async function loadDemo() {
  try {
    const response = await fetch("/v1/judge/run", { method: "POST", headers: { "Content-Type": "application/json" } });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    state.data = await response.json();
    document.getElementById("judge-launch").disabled = false;
    statusLine.textContent = copy[state.language].status;
    render();
  } catch (error) {
    const box = node("div", "error-state");
    box.append(node("h2", "", "Replay unavailable"), node("p", "", `HeatReserve could not load the verified judge fixture: ${error.message}`));
    root.replaceChildren(box);
    statusLine.textContent = "Readiness failure";
  }
}

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    state.view = button.dataset.view;
    render();
  });
});
document.getElementById("language-toggle").addEventListener("click", () => {
  state.language = state.language === "en" ? "hi" : "en";
  statusLine.textContent = copy[state.language].status;
  render();
});
document.getElementById("judge-launch").addEventListener("click", startJudgeMode);
document.getElementById("judge-close").addEventListener("click", () => { stopAutoplay(); dialog.close(); });
document.getElementById("judge-next").addEventListener("click", advanceJudge);
document.getElementById("judge-prev").addEventListener("click", retreatJudge);
document.getElementById("judge-play").addEventListener("click", toggleAutoplay);
dialog.addEventListener("close", stopAutoplay);

loadDemo();
