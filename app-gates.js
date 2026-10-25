
(function () {
  "use strict";

  const LS_AI_KEY = "india_regime_deepseek_key";
  const LS_AI_MODEL = "india_regime_deepseek_model";
  const LS_MANUAL = "india_regime_manual_v1";
  const LS_RUN = "india_regime_gates_run_v1";
  const LS_EVALS = "india_regime_eval_history_v1";

  const SLEEVES = {
    "Risk-On": {
      ow: ["Broad equities", "Midcaps (liquidity expanding)", "Discretionary", "IT & growth on dips"],
      uw: ["Excess cash", "Deep defensives as core", "Gold as primary"],
    },
    "Cyclicals-Reflation": {
      ow: ["Banks / PSU banks", "Industrials & capital goods", "Commodities / energy", "Autos if volumes confirm"],
      uw: ["Long-duration rate-sensitives", "Crowded midcap momentum without liquidity"],
    },
    "Selective cyclicals / dry powder": {
      ow: ["Selective quality banks", "Select industrials", "Commodities (small)", "Dry powder / cash"],
      uw: ["Crowded high-beta midcaps", "Full auto + NBFC chase", "Leverage"],
    },
    "Staples-Defensives": {
      ow: ["FMCG / staples", "Pharma", "Quality defensives", "Select bonds as growth cools"],
      uw: ["High-beta midcaps", "Leveraged cyclicals", "Commodity beta if growth falling"],
    },
    "Risk-Off": {
      ow: ["Cash / liquid funds", "Gold", "High-quality defensives only"],
      uw: ["Cyclicals", "High-beta midcaps", "NBFCs with ALM risk", "Fresh leverage"],
    },
    Unclear: {
      ow: ["Preserve dry powder", "Wait for dial consensus", "Size down"],
      uw: ["New high-conviction cyclical bets", "Leverage", "Acting on one indicator"],
    },
  };

  let snapshot = { market: {}, generated_at_ist: "offline" };
  let manual = {};
  try { manual = JSON.parse(localStorage.getItem(LS_MANUAL) || "{}") || {}; } catch (e) { manual = {}; }

  function mkt(key) {
    return (snapshot && snapshot.market && snapshot.market[key]) || {};
  }

  function majorityDirection(dirs) {
    const known = dirs.filter((d) => d && d !== "unknown" && d !== "flat");
    if (known.length < 1) return { score: "Unclear", detail: "insufficient known directions" };
    const rising = known.filter((d) => d === "rising").length;
    const falling = known.filter((d) => d === "falling").length;
    const n = known.length;
    if (rising / n >= 0.6) return { score: "Rising", detail: rising + "/" + n + " rising" };
    if (falling / n >= 0.6) return { score: "Falling", detail: falling + "/" + n + " falling" };
    return { score: "Unclear", detail: "mixed (" + rising + "↑ " + falling + "↓ of " + n + ")" };
  }

  function scoreGrowth() {
    const dirs = [manual.gdp_dir, manual.iip_dir].filter(Boolean);
    const knownMacros = dirs.filter((d) => d && d !== "unknown" && d !== "flat");
    if (knownMacros.length < 1) {
      return { score: "Unclear", detail: "Need GDP/IIP direction (Nifty alone never decides Growth)" };
    }
    return Object.assign({ dial: "Growth" }, majorityDirection(dirs));
  }

  function scoreInflation() {
    const coreDir = manual.core_dir || "unknown";
    const foodDir = manual.food_dir || "unknown";
    const cpiDir = manual.cpi_dir || "unknown";
    const brentDir = mkt("brent").direction || "unknown";
    const dirs = [cpiDir, coreDir, foodDir, brentDir];
    const base = majorityDirection(dirs);
    // Transitory: crude/food rising but core not rising sticky
    const foodishRising =
      (foodDir === "rising" || brentDir === "rising") &&
      coreDir !== "rising" &&
      (coreDir === "falling" || coreDir === "flat" || coreDir === "unknown");
    if (foodishRising && base.score === "Rising") {
      return { score: "Transitory", detail: (base.detail || "") + " · Transitory (food/crude without sticky core)" };
    }
    return Object.assign({ dial: "Inflation" }, base);
  }

  function scoreLiquidity() {
    const dirs = [];
    const stance = manual.rbi_stance || "unknown";
    if (stance === "tightening") dirs.push("falling"); // contracting liquidity
    else if (stance === "accommodative") dirs.push("rising");
    const us10 = mkt("us10y").direction || manual.us10y_dir || "unknown";
    const dxy = mkt("dxy").direction || "unknown";
    const inr = mkt("inr_usd").direction || "unknown";
    const india10 = manual.india10y_dir || "unknown";
    // rising yields / DXY / INR-per-USD => contracting
    function toLiq(dir) {
      if (dir === "rising") return "falling";
      if (dir === "falling") return "rising";
      return dir;
    }
    [us10, dxy, inr, india10].forEach((d) => dirs.push(toLiq(d)));
    const fii = Number(manual.fii);
    if (!isNaN(fii)) {
      if (fii > 500) dirs.push("rising");
      else if (fii < -500) dirs.push("falling");
    }
    const base = majorityDirection(dirs);
    // Hard stress: FII very negative + INR weakening + DXY rising
    const hard =
      (!isNaN(fii) && fii < -2000) ||
      (inr === "rising" && dxy === "rising" && (us10 === "rising" || india10 === "rising"));
    let score = base.score;
    if (score === "Rising") score = "Expanding";
    else if (score === "Falling") score = "Contracting";
    if (hard) score = "Contracting";
    return {
      score: score,
      detail: (base.detail || "") + (hard ? " · hard stress overlay" : ""),
      hard: hard,
    };
  }

  function quadrant(g, i) {
    const inf = i === "Transitory" ? "Falling" : i; // Transitory ≠ Rising for quadrant
    if (g === "Unclear" || inf === "Unclear") return "Unclear";
    if (g === "Rising" && (inf === "Falling")) return "Goldilocks";
    if (g === "Rising" && inf === "Rising") return "Reflation";
    if (g === "Falling" && inf === "Rising") return "Stagflation";
    if (g === "Falling" && inf === "Falling") return "Slowdown";
    return "Unclear";
  }

  function mapSleeve(g, i, l) {
    const quad = quadrant(g, i);
    let sleeve = "Unclear";
    const notes = [];
    if (quad === "Unclear" || g === "Unclear") {
      return { sleeve: "Unclear", regime: "Regime unclear / transitional", confidence: "Unclear", rationale: "Dial conflict or insufficient data.", quad: quad };
    }
    if (l === "Contracting" || (arguments[3] && arguments[3].hard)) {
      notes.push("Liquidity contracting — defensive tilt.");
    }
    if (quad === "Goldilocks" && l === "Expanding") sleeve = "Risk-On";
    else if (quad === "Goldilocks") sleeve = "Selective cyclicals / dry powder";
    else if (quad === "Reflation" && l !== "Contracting") sleeve = "Cyclicals-Reflation";
    else if (quad === "Reflation" && l === "Contracting") sleeve = "Selective cyclicals / dry powder";
    else if (quad === "Slowdown") sleeve = "Staples-Defensives";
    else if (quad === "Stagflation") sleeve = "Risk-Off";
    else sleeve = "Unclear";

    if (l === "Contracting" && (sleeve === "Risk-On" || sleeve === "Cyclicals-Reflation")) {
      sleeve = "Selective cyclicals / dry powder";
      notes.push("Liquidity override cut Risk-On/full cyclicals.");
    }

    let confidence = "Moderate";
    const unclearN = [g, i, l].filter((x) => x === "Unclear").length;
    if (unclearN >= 1 || sleeve === "Unclear") confidence = "Unclear";
    else if (l === "Contracting" && (quad === "Reflation" || quad === "Goldilocks")) confidence = "Moderate";
    else if (unclearN === 0) confidence = "Strong";

    const regime =
      (quad === "Unclear" ? "Regime unclear / transitional" : quad) +
      (l === "Contracting" ? " + Tightening liquidity" : l === "Expanding" ? " + Expanding liquidity" : "") +
      (i === "Transitory" ? " · Inflation Transitory" : "");

    return {
      sleeve: sleeve,
      regime: regime,
      confidence: confidence,
      rationale: notes.join(" ") || ("Mapped from " + quad + " with liquidity " + l + "."),
      quad: quad,
    };
  }

  function loadConfirmState() {
    try { return JSON.parse(localStorage.getItem(LS_EVALS) || "null"); } catch (e) { return null; }
  }

  function applyConfirmation(call, recordEval) {
    const prev = loadConfirmState();
    let status = "live";
    let confirmedSleeve = prev && prev.confirmedSleeve;
    if (recordEval) {
      const hist = (prev && prev.history) || [];
      hist.push({ t: Date.now(), sleeve: call.sleeve, sig: call.sleeve });
      const lastTwo = hist.slice(-2);
      if (lastTwo.length === 2 && lastTwo[0].sleeve === lastTwo[1].sleeve && lastTwo[0].sleeve !== "Unclear") {
        status = "confirmed";
        confirmedSleeve = lastTwo[0].sleeve;
      }
      localStorage.setItem(LS_EVALS, JSON.stringify({ history: hist.slice(-20), confirmedSleeve: confirmedSleeve }));
    } else if (confirmedSleeve && confirmedSleeve === call.sleeve) {
      status = "confirmed";
    }
    return { status: status, confirmedSleeve: confirmedSleeve };
  }

  function buildDialScores() {
    const g = scoreGrowth();
    const i = scoreInflation();
    const l = scoreLiquidity();
    const call = mapSleeve(g.score, i.score, l.score, l);
    const confirm = applyConfirmation(call, false);
    return { g: g, i: i, l: l, call: call, confirm: confirm };
  }

  async function callDeepSeek(messages, opt) {
    opt = opt || {};
    const key = ((document.getElementById("ai-key") || {}).value || "").trim() || localStorage.getItem(LS_AI_KEY) || "";
    const model = ((document.getElementById("ai-model") || {}).value) || localStorage.getItem(LS_AI_MODEL) || "deepseek-chat";
    if (!key) throw new Error("Paste a DeepSeek API key in Settings first.");
    const body = { model: model, temperature: 0.2, messages: messages };
    if (opt.json !== false) body.response_format = { type: "json_object" };
    const res = await fetch("https://api.deepseek.com/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + key },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(function () { return {}; });
    if (!res.ok) {
      const msg = (data.error && (data.error.message || data.error)) || res.statusText;
      throw new Error("DeepSeek " + res.status + ": " + msg);
    }
    const content = data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content;
    if (opt.json === false) return content;
    try { return JSON.parse(content); } catch (e) {
      const m = String(content || "").match(/\{[\s\S]*\}/);
      if (m) return JSON.parse(m[0]);
      throw new Error("Could not parse JSON from DeepSeek");
    }
  }

  const GATE_META = [
    { id: 1, name: "QUESTION" },
    { id: 2, name: "REGIME" },
    { id: 3, name: "CHANGE" },
    { id: 4, name: "GAP" },
    { id: 5, name: "DRIVER" },
    { id: 6, name: "STAGE" },
    { id: 7, name: "EDGE" },
  ];

  const LEADING_DEFAULTS = [
    "PMI new orders flipped",
    "Yield curve / G-Sec signal flipped",
    "Credit growth trend flipped",
    "Earnings revisions breadth flipped",
    "FII flow regime flipped",
    "USD/INR stress flipped",
    "Sector rotation confirms new leaders",
    "Breadth (advance/decline) flipped",
  ];

  function defaultRun() {
    return {
      current: 1,
      stoppedAt: null,
      stopReason: null,
      maxGate: 7,
      g1: { sentence: "" },
      g2: { notes: "", last: null },
      g3: { flips: {}, aiSuggest: null },
      g4: { pricedIn: "", evidence: "", gap: "" },
      g5: { sectors: "", drivers: "", marginal: "", direction: "" },
      g6: { stage: 0, notes: "" },
      g7: { date: "", call: "", reason: "", edge: "", catalyst: "", invalidation: "", sizing: "", checkback: "", aiDraft: "" },
    };
  }

  let run = defaultRun();
  try {
    const saved = JSON.parse(localStorage.getItem(LS_RUN) || "null");
    if (saved && saved.g1) run = Object.assign(defaultRun(), saved);
  } catch (e) {}

  function saveRun() { localStorage.setItem(LS_RUN, JSON.stringify(run)); }
  function saveManual() { localStorage.setItem(LS_MANUAL, JSON.stringify(manual)); }

  function maxAllowedGate() {
    return Number((document.getElementById("practice-mode") || {}).value || 7);
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function verdictBox(kind, title, detail) {
    return '<div class="verdict ' + kind + '">' + title +
      '<div style="font-weight:500;font-size:.85rem;margin-top:6px">' + (detail || "") + "</div></div>";
  }

  function switchTab(name) {
    document.querySelectorAll(".tab").forEach(function (t) {
      t.classList.toggle("active", t.dataset.tab === name);
    });
    ["ops", "legacy", "settings"].forEach(function (id) {
      document.getElementById("view-" + id).classList.toggle("hidden", id !== name);
    });
    if (name === "legacy") renderLegacy();
  }

  document.getElementById("tabs").addEventListener("click", function (e) {
    var t = e.target.closest(".tab");
    if (t) switchTab(t.dataset.tab);
  });

  document.getElementById("btn-save-ai").onclick = function () {
    var k = document.getElementById("ai-key").value.trim();
    var m = document.getElementById("ai-model").value;
    if (k) localStorage.setItem(LS_AI_KEY, k);
    localStorage.setItem(LS_AI_MODEL, m);
    var st = document.getElementById("ai-settings-status");
    st.textContent = k ? "Saved locally." : "Model saved; key empty.";
    st.className = "status ok";
  };
  document.getElementById("btn-clear-ai").onclick = function () {
    localStorage.removeItem(LS_AI_KEY);
    document.getElementById("ai-key").value = "";
    document.getElementById("ai-settings-status").textContent = "Key cleared.";
  };
  document.getElementById("btn-reset-run").onclick = function () {
    run = defaultRun();
    run.maxGate = maxAllowedGate();
    saveRun();
    renderOps();
  };
  document.getElementById("practice-mode").onchange = function () {
    run.maxGate = maxAllowedGate();
    if (run.current > run.maxGate) run.current = run.maxGate;
    saveRun();
    renderOps();
  };
  document.getElementById("btn-legacy-refresh").onclick = function () { renderLegacy(); };

  function renderGateNav() {
    var maxG = maxAllowedGate();
    var nav = document.getElementById("gate-nav");
    nav.innerHTML = GATE_META.filter(function (g) { return g.id <= maxG; }).map(function (g) {
      var cls = "gate-pill";
      if (run.stoppedAt && g.id === run.stoppedAt) cls += " stopped";
      else if (g.id === run.current && !run.stoppedAt) cls += " current";
      else if (g.id < run.current || (run.stoppedAt && g.id < run.stoppedAt)) cls += " done";
      return '<span class="' + cls + '">G' + g.id + " " + g.name + "</span>";
    }).join("");
  }

  function stopHere(reason) {
    run.stoppedAt = run.current;
    run.stopReason = reason;
    saveRun();
    renderOps();
  }

  function proceed() {
    var maxG = maxAllowedGate();
    if (run.current >= maxG) {
      run.stoppedAt = null;
      run.stopReason = null;
      saveRun();
      renderOps();
      return;
    }
    run.current += 1;
    run.stoppedAt = null;
    run.stopReason = null;
    saveRun();
    renderOps();
  }

  function renderGate1() {
    return '<div class="panel"><h2>Gate 1 — QUESTION</h2>' +
      '<p class="muted">One sentence: what asset / horizon / decision? Cannot state → STOP.</p>' +
      '<label class="field">Decision sentence<textarea id="g1-sentence" class="blue" placeholder="e.g. Evaluate adding midcap banks over 3–6 months under current India regime">' +
      escapeHtml(run.g1.sentence || "") + "</textarea></label>" +
      '<div class="row" style="margin-top:10px"><button type="button" class="stop" id="g1-stop">STOP</button>' +
      '<button type="button" class="go" id="g1-go">PROCEED</button></div><div id="g1-verdict"></div></div>';
  }

  function wireGate1() {
    document.getElementById("g1-sentence").oninput = function (e) { run.g1.sentence = e.target.value; saveRun(); };
    document.getElementById("g1-stop").onclick = function () {
      document.getElementById("g1-verdict").innerHTML = verdictBox("stop", "STOP", "Cannot state the decision clearly.");
      stopHere("Gate 1: no clear question");
    };
    document.getElementById("g1-go").onclick = function () {
      var s = (document.getElementById("g1-sentence").value || "").trim();
      run.g1.sentence = s;
      if (!s) {
        document.getElementById("g1-verdict").innerHTML = verdictBox("stop", "STOP", "Write one sentence first.");
        stopHere("Gate 1: empty sentence");
        return;
      }
      proceed();
    };
  }

  function renderGate2() {
    var scores = buildDialScores();
    run.g2.last = { g: scores.g.score, i: scores.i.score, l: scores.l.score, sleeve: scores.call.sleeve, regime: scores.call.regime, confidence: scores.call.confidence };
    saveRun();
    var unclear = scores.call.sleeve === "Unclear" || scores.g.score === "Unclear";
    return '<div class="panel"><h2>Gate 2 — REGIME</h2>' +
      '<p class="muted">3 dials + market vote. majority ≥60%, Growth=GDP+IIP, Transitory≠Rising, liquidity stress. Conflict → STOP Unclear.</p>' +
      '<div class="row">' +
      '<div class="dial"><div class="name">Growth</div><div class="score">' + escapeHtml(scores.g.score) + '</div><div class="muted">' + escapeHtml(scores.g.detail || "") + "</div></div>" +
      '<div class="dial"><div class="name">Inflation</div><div class="score">' + escapeHtml(scores.i.score) + '</div><div class="muted">' + escapeHtml(scores.i.detail || "") + "</div></div>" +
      '<div class="dial"><div class="name">Liquidity</div><div class="score">' + escapeHtml(scores.l.score) + '</div><div class="muted">' + escapeHtml(scores.l.detail || "") + "</div></div>" +
      "</div>" +
      "<p style=\"margin-top:10px\"><strong>Sleeve:</strong> " + escapeHtml(scores.call.sleeve) +
      " · <strong>Conviction:</strong> " + escapeHtml(scores.call.confidence || "—") + "</p>" +
      '<p class="muted">' + escapeHtml(scores.call.regime || "") + "</p>" +
      '<label class="field">Notes / market vote<textarea id="g2-notes" class="blue">' + escapeHtml(run.g2.notes || "") + "</textarea></label>" +
      '<div class="row" style="margin-top:10px">' +
      '<button type="button" class="primary" id="g2-ai">Fill dials with AI <span class="ai-tag">AI</span></button>' +
      '<button type="button" class="stop" id="g2-stop">STOP Unclear</button>' +
      '<button type="button" class="go" id="g2-go"' + (unclear ? " disabled" : "") + ">PROCEED</button></div>" +
      '<div class="status" id="g2-status"></div><div id="g2-verdict"></div></div>';
  }

  function wireGate2() {
    document.getElementById("g2-notes").oninput = function (e) { run.g2.notes = e.target.value; saveRun(); };
    document.getElementById("g2-stop").onclick = function () {
      document.getElementById("g2-verdict").innerHTML = verdictBox("stop", "STOP — Unclear", "Wait for dial consensus.");
      stopHere("Gate 2: Unclear regime");
    };
    document.getElementById("g2-go").onclick = function () {
      var scores = buildDialScores();
      if (scores.call.sleeve === "Unclear" || scores.g.score === "Unclear") {
        document.getElementById("g2-verdict").innerHTML = verdictBox("stop", "STOP — Unclear", "Cannot proceed.");
        stopHere("Gate 2: Unclear on proceed");
        return;
      }
      applyConfirmation(scores.call, true);
      proceed();
    };
    document.getElementById("g2-ai").onclick = async function () {
      var st = document.getElementById("g2-status");
      st.className = "status loading"; st.textContent = "Calling DeepSeek…";
      try {
        var snapBrief = JSON.stringify({ generated: snapshot.generated_at_ist, market: snapshot.market || {} }).slice(0, 6000);
        var data = await callDeepSeek([
          { role: "system", content: "India macro regime assistant. Return JSON only. Schema keys: gdp,gdp_dir,iip,iip_dir,cpi,cpi_dir,core,core_dir,food,food_dir,fii,dii,repo,rbi_stance,india10y,india10y_dir,warnings (array). dirs in rising|falling|flat|unknown. rbi_stance in tightening|neutral|accommodative|unknown. Do not invent fake precision." },
          { role: "user", content: "Fill latest India macro dials. Yahoo snapshot (fact for market prints): " + snapBrief },
        ]);
        manual._ev = manual._ev || {};
        ["gdp", "iip", "cpi", "core", "food", "fii", "dii", "repo", "india10y"].forEach(function (k) {
          if (data[k] != null && data[k] !== "") { manual[k] = data[k]; manual._ev[k] = "ai"; }
        });
        ["gdp_dir", "iip_dir", "cpi_dir", "core_dir", "food_dir", "india10y_dir"].forEach(function (k) {
          if (data[k]) { manual[k] = data[k]; manual._ev[k] = "ai"; }
        });
        if (data.rbi_stance) { manual.rbi_stance = data.rbi_stance; manual._ev.rbi_stance = "ai"; }
        saveManual();
        st.className = "status ok";
        st.textContent = "AI fill applied (tagged ai). Verify MOSPI/RBI." + (data.warnings && data.warnings.length ? " Warnings: " + data.warnings.join("; ") : "");
        renderOps();
      } catch (e) {
        st.className = "status err"; st.textContent = String(e.message || e);
      }
    };
  }

  function renderGate3() {
    var flips = run.g3.flips || {};
    var checks = LEADING_DEFAULTS.map(function (label, idx) {
      return '<label class="check"><input type="checkbox" data-flip="' + idx + '"' + (flips[idx] ? " checked" : "") + "/> <span>" + escapeHtml(label) + "</span></label>";
    }).join("");
    var ai = run.g3.aiSuggest ? '<div class="muted" style="margin-top:8px"><span class="ai-tag">AI</span> ' + escapeHtml(JSON.stringify(run.g3.aiSuggest)).slice(0, 800) + "</div>" : "";
    return '<div class="panel"><h2>Gate 3 — CHANGE</h2>' +
      '<p class="muted">Leading-indicator watchlist. <strong>0–1 flipped → STOP</strong>.</p>' + checks + ai +
      '<div class="row" style="margin-top:10px">' +
      '<button type="button" class="primary" id="g3-ai">Suggest flips <span class="ai-tag">AI</span></button>' +
      '<button type="button" class="stop" id="g3-stop">STOP</button>' +
      '<button type="button" class="go" id="g3-go">PROCEED</button></div>' +
      '<div class="status" id="g3-status"></div><div id="g3-verdict"></div></div>';
  }

  function wireGate3() {
    document.querySelectorAll("[data-flip]").forEach(function (el) {
      el.onchange = function () { run.g3.flips[el.dataset.flip] = el.checked; saveRun(); };
    });
    function countFlips() {
      return Object.keys(run.g3.flips || {}).filter(function (k) { return run.g3.flips[k]; }).length;
    }
    document.getElementById("g3-stop").onclick = function () {
      document.getElementById("g3-verdict").innerHTML = verdictBox("stop", "STOP", "No confirmed change cluster.");
      stopHere("Gate 3: stopped");
    };
    document.getElementById("g3-go").onclick = function () {
      var n = countFlips();
      if (n <= 1) {
        document.getElementById("g3-verdict").innerHTML = verdictBox("stop", "STOP", n + " flipped — need ≥2.");
        stopHere("Gate 3: 0–1 flips");
        return;
      }
      proceed();
    };
    document.getElementById("g3-ai").onclick = async function () {
      var st = document.getElementById("g3-status");
      st.className = "status loading"; st.textContent = "Calling DeepSeek…";
      try {
        var data = await callDeepSeek([
          { role: "system", content: "India leading-indicator assistant. JSON: suggestions (array of {indicator,flipped,why}), summary. Be conservative." },
          { role: "user", content: "Decision: " + (run.g1.sentence || "") + "\nSleeve: " + ((run.g2.last && run.g2.last.sleeve) || "?") + "\nWatchlist: " + LEADING_DEFAULTS.join("; ") + "\nSnapshot: " + JSON.stringify(snapshot.market || {}).slice(0, 3000) },
        ]);
        run.g3.aiSuggest = data;
        saveRun();
        st.className = "status ok"; st.textContent = "AI suggestions ready (not auto-checked).";
        renderOps();
      } catch (e) { st.className = "status err"; st.textContent = String(e.message || e); }
    };
  }

  function renderGate4() {
    return '<div class="panel"><h2>Gate 4 — GAP</h2>' +
      '<p class="muted">Priced-in vs evidence. <strong>No gap → STOP</strong>.</p>' +
      '<label class="field">Priced in<textarea id="g4-priced" class="blue">' + escapeHtml(run.g4.pricedIn || "") + "</textarea></label>" +
      '<label class="field">Evidence<textarea id="g4-ev" class="blue">' + escapeHtml(run.g4.evidence || "") + "</textarea></label>" +
      '<label class="field">Named gap<textarea id="g4-gap" class="blue">' + escapeHtml(run.g4.gap || "") + "</textarea></label>" +
      '<div class="row" style="margin-top:10px"><button type="button" class="stop" id="g4-stop">STOP — no gap</button>' +
      '<button type="button" class="go" id="g4-go">PROCEED</button></div><div id="g4-verdict"></div></div>';
  }

  function wireGate4() {
    document.getElementById("g4-priced").oninput = function (e) { run.g4.pricedIn = e.target.value; saveRun(); };
    document.getElementById("g4-ev").oninput = function (e) { run.g4.evidence = e.target.value; saveRun(); };
    document.getElementById("g4-gap").oninput = function (e) { run.g4.gap = e.target.value; saveRun(); };
    document.getElementById("g4-stop").onclick = function () {
      document.getElementById("g4-verdict").innerHTML = verdictBox("stop", "STOP", "Already priced — no gap.");
      stopHere("Gate 4: no gap");
    };
    document.getElementById("g4-go").onclick = function () {
      var gap = (document.getElementById("g4-gap").value || "").trim();
      var priced = (document.getElementById("g4-priced").value || "").trim();
      var ev = (document.getElementById("g4-ev").value || "").trim();
      if (!gap || !priced || !ev) {
        document.getElementById("g4-verdict").innerHTML = verdictBox("stop", "STOP", "Fill all three fields or STOP.");
        stopHere("Gate 4: incomplete");
        return;
      }
      proceed();
    };
  }

  function renderGate5() {
    return '<div class="panel"><h2>Gate 5 — DRIVER</h2>' +
      '<p class="muted">Sectors → 2–4 drivers → marginal driver + direction. Ambiguous → TOO CLOSE / STOP.</p>' +
      '<label class="field">Candidate sectors<textarea id="g5-sec" class="blue">' + escapeHtml(run.g5.sectors || "") + "</textarea></label>" +
      '<label class="field">Drivers (2–4)<textarea id="g5-drv" class="blue">' + escapeHtml(run.g5.drivers || "") + "</textarea></label>" +
      '<label class="field">Marginal driver<input id="g5-marg" class="blue" value="' + escapeHtml(run.g5.marginal || "") + '"/></label>' +
      '<label class="field">Direction<select id="g5-dir" class="blue"><option value="">—</option><option value="up">up / favors</option><option value="down">down / against</option><option value="ambiguous">ambiguous</option></select></label>' +
      '<div class="row" style="margin-top:10px">' +
      '<button type="button" class="primary" id="g5-ai">Draft driver table <span class="ai-tag">AI</span></button>' +
      '<button type="button" class="stop" id="g5-stop">TOO CLOSE / STOP</button>' +
      '<button type="button" class="go" id="g5-go">PROCEED</button></div>' +
      '<div class="status" id="g5-status"></div><div id="g5-verdict"></div></div>';
  }

  function wireGate5() {
    document.getElementById("g5-dir").value = run.g5.direction || "";
    function sync() {
      run.g5.sectors = document.getElementById("g5-sec").value;
      run.g5.drivers = document.getElementById("g5-drv").value;
      run.g5.marginal = document.getElementById("g5-marg").value;
      run.g5.direction = document.getElementById("g5-dir").value;
      saveRun();
    }
    ["g5-sec", "g5-drv", "g5-marg", "g5-dir"].forEach(function (id) {
      document.getElementById(id).oninput = sync;
      document.getElementById(id).onchange = sync;
    });
    document.getElementById("g5-stop").onclick = function () {
      document.getElementById("g5-verdict").innerHTML = verdictBox("stop", "TOO CLOSE / STOP", "Marginal driver ambiguous.");
      stopHere("Gate 5: ambiguous");
    };
    document.getElementById("g5-go").onclick = function () {
      sync();
      if (!(run.g5.marginal || "").trim() || !run.g5.direction || run.g5.direction === "ambiguous") {
        document.getElementById("g5-verdict").innerHTML = verdictBox("stop", "TOO CLOSE / STOP", "Need clear marginal driver + direction.");
        stopHere("Gate 5: incomplete/ambiguous");
        return;
      }
      proceed();
    };
    document.getElementById("g5-ai").onclick = async function () {
      var st = document.getElementById("g5-status");
      st.className = "status loading"; st.textContent = "Calling DeepSeek…";
      try {
        var data = await callDeepSeek([
          { role: "system", content: "India equity sleeve driver assistant. JSON: sectors (string[]), drivers (array), marginal_driver, direction (up|down|ambiguous), notes." },
          { role: "user", content: "Question: " + (run.g1.sentence || "") + "\nSleeve: " + ((run.g2.last && run.g2.last.sleeve) || "") + "\nGap: " + (run.g4.gap || "") },
        ]);
        run.g5.sectors = (data.sectors || []).join(", ");
        run.g5.drivers = JSON.stringify(data.drivers || data, null, 2);
        run.g5.marginal = data.marginal_driver || "";
        run.g5.direction = data.direction || "";
        saveRun();
        st.className = "status ok"; st.textContent = "AI draft loaded — edit before PROCEED.";
        renderOps();
      } catch (e) { st.className = "status err"; st.textContent = String(e.message || e); }
    };
  }

  function renderGate6() {
    var stages = ["1 — Bonds rally", "2 — Rate-cut signal", "3 — Rate-sensitives bottom", "4 — Cyclicals recover", "5 — Commodities rally", "6 — Next tightening"];
    var opts = stages.map(function (s, i) {
      return '<option value="' + (i + 1) + '"' + (run.g6.stage === i + 1 ? " selected" : "") + ">" + s + "</option>";
    }).join("");
    return '<div class="panel"><h2>Gate 6 — STAGE</h2>' +
      '<p class="muted">Sequence checklist. <strong>Stage 1 or earlier → STOP rate-sensitives</strong>.</p>' +
      '<label class="field">Diagnosed stage<select id="g6-stage" class="blue"><option value="0">— / pre-stage 1</option>' + opts + "</select></label>" +
      '<label class="field">Notes<textarea id="g6-notes" class="blue">' + escapeHtml(run.g6.notes || "") + "</textarea></label>" +
      '<div class="row" style="margin-top:10px">' +
      '<button type="button" class="primary" id="g6-ai">Diagnose stage <span class="ai-tag">AI</span></button>' +
      '<button type="button" class="stop" id="g6-stop">STOP rate-sensitives</button>' +
      '<button type="button" class="go" id="g6-go">PROCEED</button></div>' +
      '<div class="status" id="g6-status"></div><div id="g6-verdict"></div></div>';
  }

  function wireGate6() {
    document.getElementById("g6-stage").onchange = function (e) { run.g6.stage = Number(e.target.value); saveRun(); };
    document.getElementById("g6-notes").oninput = function (e) { run.g6.notes = e.target.value; saveRun(); };
    document.getElementById("g6-stop").onclick = function () {
      document.getElementById("g6-verdict").innerHTML = verdictBox("stop", "STOP rate-sensitives", "Stage 1 or earlier.");
      stopHere("Gate 6: stage ≤1");
    };
    document.getElementById("g6-go").onclick = function () {
      var stg = Number(document.getElementById("g6-stage").value || 0);
      run.g6.stage = stg;
      if (stg <= 1) {
        document.getElementById("g6-verdict").innerHTML = verdictBox("stop", "STOP rate-sensitives", "Stage " + stg + " — too early.");
        stopHere("Gate 6: stage ≤1 on proceed");
        return;
      }
      proceed();
    };
    document.getElementById("g6-ai").onclick = async function () {
      var st = document.getElementById("g6-status");
      st.className = "status loading"; st.textContent = "Calling DeepSeek…";
      try {
        var data = await callDeepSeek([
          { role: "system", content: "India cycle stage diagnosis. JSON: stage (1-6), confidence, evidence (string[]), action. Stages: 1 bonds, 2 cut signal, 3 rate-sensitives bottom, 4 cyclicals, 5 commodities, 6 next tightening." },
          { role: "user", content: "Dials " + JSON.stringify(run.g2.last || {}) + " flips " + JSON.stringify(run.g3.flips || {}) + " snap " + JSON.stringify(snapshot.market || {}).slice(0, 2500) },
        ]);
        if (data.stage) run.g6.stage = Number(data.stage);
        run.g6.notes = (data.action || "") + "\n" + ((data.evidence || []).join("; ")) + "\n[AI draft]";
        saveRun();
        st.className = "status ok"; st.textContent = "AI stage draft loaded.";
        renderOps();
      } catch (e) { st.className = "status err"; st.textContent = String(e.message || e); }
    };
  }

  function journalText() {
    var g = run.g7;
    return [
      "# Gate 7 Journal",
      "Date: " + (g.date || ""),
      "Question: " + (run.g1.sentence || ""),
      "Regime: " + JSON.stringify(run.g2.last || {}),
      "Call: " + (g.call || ""),
      "Reason: " + (g.reason || ""),
      "Edge: " + (g.edge || ""),
      "Catalyst: " + (g.catalyst || ""),
      "Invalidation: " + (g.invalidation || ""),
      "Sizing: " + (g.sizing || ""),
      "Check-back: " + (g.checkback || ""),
      "Gap: " + (run.g4.gap || ""),
      "Stage: " + (run.g6.stage || ""),
      "Marginal driver: " + (run.g5.marginal || "") + " " + (run.g5.direction || ""),
      g.aiDraft ? ("\n--- AI draft (edit before trusting) ---\n" + g.aiDraft) : "",
    ].filter(Boolean).join("\n");
  }

  function downloadBlob(name, text, type) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: type }));
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function renderGate7() {
    var g = run.g7;
    return '<div class="panel"><h2>Gate 7 — EDGE</h2>' +
      '<p class="muted">Journal. Missing named edge or catalyst → STOP.</p>' +
      '<div class="row"><label class="field">Date<input id="g7-date" class="blue" value="' + escapeHtml(g.date || "") + '"/></label>' +
      '<label class="field">Call<input id="g7-call" class="blue" value="' + escapeHtml(g.call || "") + '"/></label></div>' +
      '<label class="field">Reason<textarea id="g7-reason" class="blue">' + escapeHtml(g.reason || "") + "</textarea></label>" +
      '<label class="field">Named edge<textarea id="g7-edge" class="blue">' + escapeHtml(g.edge || "") + "</textarea></label>" +
      '<label class="field">Catalyst<textarea id="g7-cat" class="blue">' + escapeHtml(g.catalyst || "") + "</textarea></label>" +
      '<label class="field">Invalidation<textarea id="g7-inv" class="blue">' + escapeHtml(g.invalidation || "") + "</textarea></label>" +
      '<label class="field">Sizing<textarea id="g7-size" class="blue">' + escapeHtml(g.sizing || "") + "</textarea></label>" +
      '<label class="field">Check-back<input id="g7-cb" class="blue" value="' + escapeHtml(g.checkback || "") + '"/></label>' +
      '<div class="row" style="margin-top:10px">' +
      '<button type="button" class="primary" id="g7-ai">Draft journal <span class="ai-tag">AI</span></button>' +
      '<button type="button" class="stop" id="g7-stop">STOP</button>' +
      '<button type="button" class="go" id="g7-go">COMPLETE journal</button>' +
      '<button type="button" class="ghost" id="g7-dl-md">Download MD</button>' +
      '<button type="button" class="ghost" id="g7-dl-json">Download JSON</button></div>' +
      '<div class="status" id="g7-status"></div><div id="g7-verdict"></div>' +
      "<h3>Printable entry</h3><pre class=\"journal\" id=\"g7-print\"></pre></div>";
  }

  function wireGate7() {
    var pairs = [["g7-date", "date"], ["g7-call", "call"], ["g7-reason", "reason"], ["g7-edge", "edge"], ["g7-cat", "catalyst"], ["g7-inv", "invalidation"], ["g7-size", "sizing"], ["g7-cb", "checkback"]];
    pairs.forEach(function (p) {
      var el = document.getElementById(p[0]);
      if (!el) return;
      el.oninput = function () {
        run.g7[p[1]] = el.value;
        saveRun();
        document.getElementById("g7-print").textContent = journalText();
      };
    });
    document.getElementById("g7-print").textContent = journalText();
    document.getElementById("g7-stop").onclick = function () {
      document.getElementById("g7-verdict").innerHTML = verdictBox("stop", "STOP", "Missing edge or catalyst.");
      stopHere("Gate 7: incomplete");
    };
    document.getElementById("g7-go").onclick = function () {
      run.g7.edge = document.getElementById("g7-edge").value;
      run.g7.catalyst = document.getElementById("g7-cat").value;
      if (!(run.g7.edge || "").trim() || !(run.g7.catalyst || "").trim()) {
        document.getElementById("g7-verdict").innerHTML = verdictBox("stop", "STOP", "Named edge and catalyst required.");
        stopHere("Gate 7: missing edge/catalyst");
        return;
      }
      run.stoppedAt = null;
      saveRun();
      document.getElementById("g7-verdict").innerHTML = verdictBox("go", "TRADE JOURNAL COMPLETE", "Write it down. Re-underwrite on check-back.");
      document.getElementById("g7-print").textContent = journalText();
    };
    document.getElementById("g7-dl-md").onclick = function () { downloadBlob("gate7-journal.md", journalText(), "text/markdown"); };
    document.getElementById("g7-dl-json").onclick = function () { downloadBlob("gate7-run.json", JSON.stringify(run, null, 2), "application/json"); };
    document.getElementById("g7-ai").onclick = async function () {
      var st = document.getElementById("g7-status");
      st.className = "status loading"; st.textContent = "Calling DeepSeek…";
      try {
        var data = await callDeepSeek([
          { role: "system", content: "Draft India regime trade journal. JSON keys: date,call,reason,edge,catalyst,invalidation,sizing,checkback,disclaimer. disclaimer must say AI draft not advice." },
          { role: "user", content: JSON.stringify({ g1: run.g1, g2: run.g2, g3: run.g3, g4: run.g4, g5: run.g5, g6: run.g6 }) },
        ]);
        ["date", "call", "reason", "edge", "catalyst", "invalidation", "sizing", "checkback"].forEach(function (k) {
          if (data[k]) run.g7[k] = String(data[k]);
        });
        run.g7.aiDraft = JSON.stringify(data, null, 2);
        saveRun();
        st.className = "status ok"; st.textContent = "AI draft loaded — edit every field before COMPLETE.";
        renderOps();
      } catch (e) { st.className = "status err"; st.textContent = String(e.message || e); }
    };
  }

  function renderOps() {
    run.maxGate = maxAllowedGate();
    renderGateNav();
    var show = run.stoppedAt || run.current;
    var renderers = { 1: renderGate1, 2: renderGate2, 3: renderGate3, 4: renderGate4, 5: renderGate5, 6: renderGate6, 7: renderGate7 };
    var wirers = { 1: wireGate1, 2: wireGate2, 3: wireGate3, 4: wireGate4, 5: wireGate5, 6: wireGate6, 7: wireGate7 };
    var htmlOut = renderers[show]();
    if (run.stoppedAt) {
      htmlOut += verdictBox("stop", "Stopped at Gate " + run.stoppedAt, escapeHtml(run.stopReason || ""));
      htmlOut += '<div class="row" style="margin-top:8px"><button type="button" class="ghost" id="btn-resume">Edit Gate ' + run.stoppedAt + " / reset stop</button></div>";
    }
    document.getElementById("gate-root").innerHTML = htmlOut;
    wirers[show]();
    var resume = document.getElementById("btn-resume");
    if (resume) {
      resume.onclick = function () {
        run.current = run.stoppedAt;
        run.stoppedAt = null;
        run.stopReason = null;
        saveRun();
        renderOps();
      };
    }
  }

  function renderLegacy() {
    var s = buildDialScores();
    document.getElementById("legacy-dials").innerHTML =
      '<div class="dial"><div class="name">Growth</div><div class="score">' + escapeHtml(s.g.score) + "</div></div>" +
      '<div class="dial"><div class="name">Inflation</div><div class="score">' + escapeHtml(s.i.score) + "</div></div>" +
      '<div class="dial"><div class="name">Liquidity</div><div class="score">' + escapeHtml(s.l.score) + "</div></div>";
    var sleeve = SLEEVES[s.call.sleeve] || SLEEVES.Unclear;
    var showBuy = s.call.confidence === "Strong" && s.confirm.status === "confirmed";
    document.getElementById("legacy-verdict").innerHTML =
      "<p><strong>" + escapeHtml(s.call.regime) + "</strong><br/>Sleeve: " + escapeHtml(s.call.sleeve) +
      " · Conviction: " + escapeHtml(s.call.confidence) + " · Confirm: " + escapeHtml(s.confirm.status) + "</p>" +
      '<p class="muted">' + escapeHtml(s.call.rationale || "") + "</p>" +
      '<div class="row"><div style="flex:1"><strong>OW' + (showBuy ? "" : " (guidance)") + "</strong><ul>" +
      sleeve.ow.map(function (x) { return "<li>" + escapeHtml(x) + "</li>"; }).join("") +
      '</ul></div><div style="flex:1"><strong>UW</strong><ul>' +
      sleeve.uw.map(function (x) { return "<li>" + escapeHtml(x) + "</li>"; }).join("") +
      "</ul></div></div>";
  }

  async function boot() {
    document.getElementById("ai-key").value = localStorage.getItem(LS_AI_KEY) || "";
    document.getElementById("ai-model").value = localStorage.getItem(LS_AI_MODEL) || "deepseek-chat";
    document.getElementById("practice-mode").value = String(run.maxGate || 7);
    try {
      var res = await fetch("./data/snapshot.json", { cache: "no-store" });
      if (res.ok) snapshot = await res.json();
    } catch (e) {
      snapshot = { generated_at_ist: "offline / snapshot unreadable", market: {} };
    }
    renderOps();
  }

  boot();
})();
