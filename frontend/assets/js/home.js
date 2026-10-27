// Home page: trade ticket (cost + sizing sliders), pipeline track, results chart, phase track.
(function () {
  "use strict";

  // ---- Config mirrored from config/costs.yaml and config/risk.yaml -------------------------
  var COSTS = {
    brokerage_pct: 0.03, brokerage_cap_per_order: 20.0, stt_sell_pct: 0.025,
    exchange_txn_pct: 0.00297, sebi_pct: 0.0001, stamp_buy_pct: 0.003, gst_pct: 18.0, slippage_pct: 0.05,
  };
  var RISK = { risk_per_trade_pct: 1.0, max_position_value_pct_of_cash: 100, min_edge_cost_multiple: 3.0 };
  var CAPITAL = 1000; // config/settings.yaml starting_capital

  var MINUS = "−";
  function fmt(n, d) {
    if (!isFinite(n)) return "n/a";
    var s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
    return (n < 0 ? MINUS : "") + s;
  }
  function rs(n, d) { return (n < 0 ? MINUS : "") + "₹" + fmt(Math.abs(n), d === undefined ? 2 : d); }
  function $(id) { return document.getElementById(id); }

  // Port of bot.backtest.costs.CostModel.leg_fees, kept term for term.
  function legFees(side, value) {
    var c = COSTS;
    var brokerage = Math.min(value * c.brokerage_pct / 100, c.brokerage_cap_per_order);
    var exchange = value * c.exchange_txn_pct / 100;
    var sebi = value * c.sebi_pct / 100;
    var gst = (brokerage + exchange + sebi) * c.gst_pct / 100;
    var stt = side === "sell" ? value * c.stt_sell_pct / 100 : 0;
    var stamp = side === "buy" ? value * c.stamp_buy_pct / 100 : 0;
    return { brokerage: brokerage, exchange: exchange, sebi: sebi, gst: gst, stt: stt, stamp: stamp,
      total: brokerage + exchange + sebi + gst + stt + stamp };
  }

  // Port of RiskManager.size + the min_edge rule.
  function evaluate(capital, price, stopPct, rr) {
    var stopDist = price * stopPct / 100;
    var byRisk = capital * RISK.risk_per_trade_pct / 100 / stopDist;
    var slip = 1 + COSTS.slippage_pct / 100;
    var cashCap = capital * RISK.max_position_value_pct_of_cash / 100;
    var byCash = cashCap / (price * slip * 1.002);
    var qty = Math.floor(Math.min(byRisk, byCash));
    var out = { qty: qty, limitedBy: byRisk <= byCash ? "risk" : "cash", stopDist: stopDist };
    if (qty < 1) { out.verdict = "qty_below_1"; return out; }
    var value = qty * price;
    var buy = legFees("buy", value), sell = legFees("sell", value);
    var slippage = 2 * value * COSTS.slippage_pct / 100;
    var est = buy.total + sell.total + slippage;
    var risk = qty * stopDist;
    var target = qty * Math.abs(rr * stopDist);
    out.value = value; out.buy = buy; out.sell = sell; out.slippage = slippage; out.est = est;
    out.risk = risk; out.target = target; out.need = RISK.min_edge_cost_multiple * est;
    out.verdict = target <= out.need ? "min_edge" : "approved";
    return out;
  }

  function ticket() {
    var price = $("t-price"), stop = $("t-stop"), rr = 1.5;
    function stat(k, v) { return "<div><dt>" + k + "</dt><dd>" + v + "</dd></div>"; }
    function row(k, v, cls) { return "<tr" + (cls ? " class=\"" + cls + "\"" : "") + "><td>" + k + "</td><td class=\"n\">" + v + "</td></tr>"; }

    function render() {
      var p = parseFloat(price.value), s = parseFloat(stop.value);
      $("t-price-v").textContent = "₹" + fmt(p, 0);
      $("t-stop-v").textContent = fmt(s, 2) + "%";
      var r = evaluate(CAPITAL, p, s, rr), v = $("t-verdict");
      if (r.verdict === "qty_below_1") {
        v.className = "verdict block";
        v.innerHTML = "<span>Blocked. &#8377;1,000 cannot buy 1 share here.</span><code>qty_below_1</code>";
        $("tb-gain").style.width = "0"; $("tb-cost").style.width = "0";
        $("tb-gain-v").textContent = "n/a"; $("tb-cost-v").textContent = "n/a";
        $("t-stats").innerHTML = stat("Shares", "0") + stat("Round-trip cost", "n/a") + stat("Cost per 1 R", "n/a");
        $("t-rows").innerHTML = row("No trade, so no fees", "");
        return;
      }
      var pass = r.verdict === "approved";
      v.className = "verdict " + (pass ? "pass" : "block");
      v.innerHTML = pass ? "<span>Passes. The target beats 3 times the costs.</span><code>approved</code>"
        : "<span>Blocked. The target is too small for the costs.</span><code>min_edge</code>";
      var max = Math.max(r.target, r.need);
      $("tb-gain").style.width = (r.target / max * 100).toFixed(1) + "%";
      $("tb-cost").style.width = (r.need / max * 100).toFixed(1) + "%";
      $("tb-gain-v").textContent = rs(r.target);
      $("tb-cost-v").textContent = rs(r.need);
      $("t-stats").innerHTML = stat("Shares", String(r.qty)) + stat("Round-trip cost", rs(r.est)) + stat("Cost per 1 R", fmt(r.est / r.risk, 2) + " R");
      var b = r.buy, x = r.sell;
      $("t-rows").innerHTML =
        row("Position value, " + r.qty + " shares (limited by " + (r.limitedBy === "risk" ? "1% risk" : "cash") + ")", rs(r.value)) +
        row("Brokerage, both legs", rs(b.brokerage + x.brokerage, 3)) +
        row("STT, sell leg", rs(b.stt + x.stt, 3)) +
        row("Exchange and SEBI fee", rs(b.exchange + x.exchange + b.sebi + x.sebi, 3)) +
        row("Stamp duty, buy leg", rs(b.stamp + x.stamp, 3)) +
        row("GST", rs(b.gst + x.gst, 3)) +
        row("Slippage, both legs", rs(r.slippage, 3)) +
        row("Estimated round-trip cost", rs(r.est), "sum");
    }
    price.addEventListener("input", render);
    stop.addEventListener("input", render);
    document.querySelectorAll("#t-rr button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        rr = parseFloat(btn.dataset.rr);
        document.querySelectorAll("#t-rr button").forEach(function (o) { o.setAttribute("aria-pressed", String(o === btn)); });
        render();
      });
    });
    $("ticket").addEventListener("submit", function (e) { e.preventDefault(); });
    render();
  }

  // ---- Pipeline: numbered list + detail panel --------------------------------------------
  var STAGES = [
    { name: "Data feed", status: "partial", code: "src/bot/data/",
      input: "Fyers 1-minute history today, live ticks later", output: "Clean 1-minute and 5-minute candles",
      what: "Downloads and cleans candles. The live tick feed is not built yet.",
      items: ["Quality report on missing bars, duplicates, broken prices and jumps over 5% in a minute",
        "Keeps 09:15 to 15:29 only and drops special sessions such as Muhurat trading"] },
    { name: "Features", status: "built", code: "src/bot/features/engine.py",
      input: "Closed candles for the stock and the Nifty 50", output: "25 numbers per candle",
      what: "Turns candles into measurements, using only candles that have already closed.",
      items: ["VWAP distance, RSI, EMA 9, 21 and 50, ATR, volume against its average, Nifty trend",
        "Tests confirm that changing future candles never changes past features"] },
    { name: "Detectors", status: "built", code: "src/bot/detectors/",
      input: "Candles and features", output: "A candidate with direction, entry, stop and target",
      what: "Three setups look for a trade. The stop sits 1 ATR from entry and the target at 1.5 times the risk.",
      items: ["Opening range breakout on 1.5 times average volume", "VWAP reclaim or rejection, from 09:35", "Pullback to EMA21 inside an established trend"] },
    { name: "ML model", status: "todo", code: "src/bot/ml/",
      input: "The candidate and its features", output: "Probability the target is hit before the stop",
      what: "Phase 4. A LightGBM model trained on every past signal, including rejected ones.",
      items: ["Time-based splits only, never shuffled", "Calibrated on a separate window before use"] },
    { name: "Jev check", status: "todo", code: "src/bot/jev/",
      input: "A compact state with every number pre-computed", output: "Direction, quality and trap answers",
      what: "Phase 5. The TypeSafe Jev model can veto a trade but never start one.",
      items: ["No answer within 800 ms means no trade", "Kept only if it beats the ML-only version on unseen data"] },
    { name: "Decision gate", status: "built", code: "src/bot/decision/gate.py",
      input: "Candidate, model score and Jev answers", output: "Pass, or the name of the failed check",
      what: "Compares every answer with the thresholds in settings.yaml.",
      items: ["Three modes: rules only, rules plus ML, rules plus ML plus Jev", "A missing answer counts as a rejection"] },
    { name: "Risk manager", status: "built", code: "src/bot/risk/manager.py",
      input: "Approved candidate and account state", output: "A share quantity, or the rule that blocked it",
      what: "Eight checks in a fixed order. The first one that fails is saved as the reason.",
      items: ["Kill switch, entry window 09:30 to 14:45, 3% daily loss limit", "3 trades a day, 1 open position, stop after 2 losses in a row",
        "At least 1 share, and a target worth more than 3 times the costs"] },
    { name: "Execution", status: "todo", code: "src/bot/execution/",
      input: "An approved order", output: "A fill, a stop-loss order and an exit",
      what: "Phases 7 and 8. A paper broker first, then a Zerodha Kite adapter.",
      items: ["A stop-loss order right after every fill", "Only this module may talk to the broker, and a test enforces it"] },
    { name: "Storage", status: "partial", code: "src/bot/storage/models.py",
      input: "Every stage's output", output: "One decision record per signal",
      what: "Database tables exist. Backtests save their results as files, and alerts are not built yet.",
      items: ["The dashboard on this site reads exported backtest runs", "Secrets are removed from every log line"] },
  ];
  var STATUS_TEXT = { built: "Built", partial: "Partly built", todo: "Not built" };

  function pipeline() {
    var list = $("stage-list"), panel = $("stage-panel");
    STAGES.forEach(function (st, i) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "tab"); b.id = "stage-" + i; b.setAttribute("aria-controls", "stage-panel");
      b.innerHTML = "<span class=\"no\">" + String(i + 1).padStart(2, "0") + "</span><span class=\"nm\">" + st.name + "</span><span class=\"badge " + st.status + "\">" +
        STATUS_TEXT[st.status] + "</span><span class=\"out\">" + st.output + "</span>";
      b.addEventListener("click", function () { select(i, true); });
      b.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); select((i + 1) % STAGES.length, true, true); }
        if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); select((i - 1 + STAGES.length) % STAGES.length, true, true); }
      });
      li.appendChild(b); list.appendChild(li);
    });
    function select(i, animate, focus) {
      list.querySelectorAll("button").forEach(function (b, j) { b.setAttribute("aria-selected", String(i === j)); b.tabIndex = i === j ? 0 : -1; });
      if (focus) list.querySelectorAll("button")[i].focus();
      var st = STAGES[i], nextI = (i + 1) % STAGES.length;
      panel.setAttribute("aria-labelledby", "stage-" + i);
      panel.innerHTML = "<div class=\"sp-top\"><span class=\"eyebrow\">Stage " + String(i + 1).padStart(2, "0") + " of 09</span><span class=\"badge " + st.status + "\">" + STATUS_TEXT[st.status] + "</span></div>" +
        "<h3>" + st.name + "</h3><p class=\"desc\">" + st.what + "</p>" +
        "<dl><div><dt>Input</dt><dd>" + st.input + "</dd></div><div><dt>Output</dt><dd>" + st.output + "</dd></div><div><dt>Code</dt><dd class=\"code\">" + st.code + "</dd></div></dl>" +
        "<ul>" + st.items.map(function (x) { return "<li>" + x + "</li>"; }).join("") + "</ul>" +
        "<button type=\"button\" class=\"link-btn next\">" + (nextI === 0 ? "Back to the first stage" : "Next stage: " + STAGES[nextI].name) + "</button>";
      panel.querySelector(".next").addEventListener("click", function () { select(nextI, true); });
      if (animate) { panel.classList.remove("swap"); void panel.offsetWidth; panel.classList.add("swap"); }
    }
    select(0, false);
  }

  // ---- Experiment results (docs/experiments/2026-10-12-timeframe.md) ---------------------
  // [name, trades, win %, net rupees, max DD %, signals, signal win %, net R per signal, chosen]
  var SELECT = [
    ["1-min, stop 1.0 ATR, RR 1.5", 10, 30.0, -29.6, 3.0, 58165, 36.2, -2.44],
    ["5-min, stop 1.0 ATR, RR 1.5", 172, 48.8, -88.3, 16.8, 14475, 37.7, -1.01, true],
    ["5-min, stop 1.0 ATR, RR 2.0", 328, 33.8, -376.9, 38.3, 14199, 30.0, -1.04],
    ["5-min, stop 1.5 ATR, RR 1.5", 360, 38.6, -430.3, 43.3, 13904, 32.7, -0.70],
    ["5-min, stop 1.5 ATR, RR 2.0", 419, 34.4, -435.4, 43.9, 13545, 23.5, -0.71],
  ];
  var HOLDOUT = [
    ["1-min, stop 1.0 ATR, RR 1.5", 0, null, 0, null, 13657, 35.4, -2.92],
    ["5-min, stop 1.0 ATR, RR 1.5", 10, 20.0, -39.9, null, 3397, 39.9, -1.10, true],
  ];

  function rChart() {
    var host = $("r-chart"), scale = 2.5;
    host.innerHTML = "<div class=\"rbars\" role=\"img\" aria-label=\"Net R per signal for five versions. All are below zero.\">" + SELECT.map(function (r) {
      return "<div class=\"rbar" + (r[8] ? " chosen" : "") + "\"><span class=\"lbl\">" + r[0] + "</span><span class=\"track\"><span class=\"fill\" data-w=\"" +
        (Math.abs(r[7]) / scale * 100).toFixed(1) + "\"></span></span><span class=\"val\">" + fmt(r[7], 2) + "</span></div>";
    }).join("") + "</div>";
    var grow = function () { host.querySelectorAll(".fill").forEach(function (f) { f.style.width = f.dataset.w + "%"; }); };
    if (!("IntersectionObserver" in window)) { grow(); return; }
    setTimeout(grow, 1200); // never leave the bars empty if the section is not scrolled to
    var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { grow(); io.disconnect(); } }, { threshold: 0.3 });
    io.observe(host);
  }

  function resultsTable() {
    function cell(v, d, signed) {
      if (v === null) return "<td class=\"n muted\">n/a</td>";
      return "<td class=\"n" + (signed && v < 0 ? " loss" : "") + "\">" + fmt(v, d) + "</td>";
    }
    function rowsFor(title, data) {
      return "<tr><td colspan=\"8\" class=\"group\">" + title + "</td></tr>" + data.map(function (r) {
        return "<tr" + (r[8] ? " class=\"highlight\"" : "") + "><td>" + r[0] + "</td>" + cell(r[1], 0) + cell(r[2], 1) + cell(r[3], 1, true) +
          cell(r[4], 1) + cell(r[5], 0) + cell(r[6], 1) + cell(r[7], 2, true) + "</tr>";
      }).join("");
    }
    $("results-body").innerHTML = rowsFor("Selection window, 17 Oct 2025 to 31 Jul 2026", SELECT) + rowsFor("Holdout, 1 Aug to 9 Oct 2026", HOLDOUT);
  }

  // ---- Build stages ----------------------------------------------------------------------
  var PHASES = [
    ["done", "Foundations", "Config, secrets handling, database models, logging and tests."],
    ["done", "Data and features", "Fyers download, quality report and 25 features with look-ahead tests."],
    ["done", "Detectors and backtester", "Three setups, the cost model and the first results after costs."],
    ["todo", "ML model", "A model trained on every signal, tested walk-forward and calibrated.", true],
    ["todo", "Jev layer", "The Jev client with a hard timeout and a three-way comparison."],
    ["partial", "Dashboard", "The operator dashboard exists. ML and Jev pages wait for phases 4 and 5."],
    ["todo", "Paper trading", "Live data, a paper broker, the kill switch and alerts, for four weeks."],
    ["todo", "Live with ₹1,000", "The broker adapter and stop-loss checks, tested on 1 share."],
  ];
  var PHASE_STATUS = { done: ["built", "Built"], partial: ["partial", "Partly built"], todo: ["todo", "Not started"] };
  function phases() {
    $("stages").innerHTML = PHASES.map(function (p, i) {
      var st = PHASE_STATUS[p[0]];
      return "<li class=\"" + (p[3] ? "next" : "") + "\"><div class=\"st-top\"><span class=\"st-no\">Stage " + String(i + 1).padStart(2, "0") + (p[3] ? " &middot; next" : "") +
        "</span><span class=\"badge " + st[0] + "\">" + st[1] + "</span></div><h3>" + p[1] + "</h3><p>" + p[2] + "</p></li>";
    }).join("");
  }

  document.addEventListener("DOMContentLoaded", function () {
    ticket(); pipeline(); rChart(); resultsTable(); phases();
  });
})();
