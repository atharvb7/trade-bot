// Dashboard page. Reads window.TRADEBOT_DATA written by scripts/export_frontend_data.py.
(function () {
  "use strict";
  var esc = window.Charts.esc;
  var MINUS = "−";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var VIEWS = ["performance", "trades", "funnel", "edge"];
  var SPEC_MIN_EDGE = 3; // config/risk.yaml min_edge_cost_multiple

  var SETUPS = { opening_range_breakout: "Opening range breakout", vwap_reclaim: "VWAP reclaim", trend_pullback: "Trend pullback" };
  var SETUP_SHORT = { opening_range_breakout: "ORB", vwap_reclaim: "VWAP", trend_pullback: "Pullback" };
  var REASONS = {
    min_edge: "Target too small for costs", outside_entry_window: "Outside 09:30 to 14:45", max_trades_per_day: "3 trades already today",
    losing_streak: "2 losses in a row today", max_open_positions: "Position already open", max_daily_loss: "Daily loss limit hit",
    qty_below_1: "Under 1 share", kill_switch: "Kill switch on", ml_prob: "ML probability too low", jev_present: "No Jev answer",
    jev_action: "Jev disagrees on direction", jev_confidence: "Jev confidence too low", jev_quality: "Jev quality too low",
    jev_trap: "Jev flags a trap", no_candidate: "No candidate",
  };
  var OUTCOMES = { target: "Target hit", stop: "Stopped out", timeout: "Square-off", no_entry: "No next bar" };
  var EXITS = { stop: "Stop", stop_gap: "Stop, gap", target: "Target", target_gap: "Target, gap", square_off: "Square-off", end_of_data: "End of data" };

  function num(n, d) {
    if (n === null || n === undefined || !isFinite(n)) return "n/a";
    var s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
    return (n < 0 ? MINUS : "") + s;
  }
  function signed(n, d) { return (n > 0 ? "+" : "") + num(n, d); }
  function rs(n, d) {
    if (n === null || n === undefined || !isFinite(n)) return "n/a";
    return (n < 0 ? MINUS : "") + "₹" + num(Math.abs(n), d === undefined ? 2 : d);
  }
  function pnlCls(n) { return n > 0 ? "gain" : n < 0 ? "loss" : ""; }
  function dt(s) { return s ? s.slice(8, 10) + " " + MONTHS[+s.slice(5, 7) - 1] + " " + s.slice(11, 16) : ""; }
  function day(s) { return s ? s.slice(8, 10) + " " + MONTHS[+s.slice(5, 7) - 1] : ""; }
  function fullDate(s) { return s ? +s.slice(8, 10) + " " + MONTHS[+s.slice(5, 7) - 1] + " " + s.slice(0, 4) : ""; }
  function reasonKey(status) { return String(status).replace(/^rejected_risk_/, "").replace(/^rejected_/, ""); }
  function reasonLabel(k) { return REASONS[k] || k.replace(/_/g, " "); }
  function setupLabel(k) { return SETUPS[k] || k; }
  function $(id) { return document.getElementById(id); }

  var DATA = window.TRADEBOT_DATA;
  var state = { run: null, view: "performance", by: "setup", filt: { symbol: "", setup: "", r: "all" }, sort: { k: "entry_ts", dir: "desc" }, sel: null };

  function init() {
    if (!DATA || !DATA.runs || !DATA.runs.length) {
      $("run-meta").innerHTML = "Run <code>python scripts/export_frontend_data.py</code> to create <code>frontend/data/runs.js</code>, then reload.";
      document.querySelectorAll(".kpis, .tabs, .view, .run-picker").forEach(function (el) { el.hidden = true; });
      return;
    }
    var sel = $("run");
    sel.innerHTML = DATA.runs.map(function (r, i) {
      return "<option value=\"" + i + "\">" + esc(r.label) + (r.created_at ? ", run " + esc(dt(r.created_at)) : "") + "</option>";
    }).join("");
    sel.addEventListener("change", function () { setRun(+sel.value); });
    $("generated").textContent = "Data exported " + fullDate(DATA.generated_at) + ", " + DATA.generated_at.slice(11, 16) +
      " UTC, from data/backtests/ by scripts/export_frontend_data.py.";

    document.querySelectorAll(".tabs button").forEach(function (b) {
      b.addEventListener("click", function () { setView(b.dataset.view, true); });
      b.addEventListener("keydown", function (e) {
        var i = VIEWS.indexOf(b.dataset.view);
        if (e.key === "ArrowRight") { e.preventDefault(); setView(VIEWS[(i + 1) % 4], true, true); }
        if (e.key === "ArrowLeft") { e.preventDefault(); setView(VIEWS[(i + 3) % 4], true, true); }
      });
    });
    document.querySelectorAll("#by-seg button").forEach(function (b) {
      b.addEventListener("click", function () {
        state.by = b.dataset.by;
        document.querySelectorAll("#by-seg button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        renderBy();
      });
    });
    $("f-symbol").addEventListener("change", function (e) { state.filt.symbol = e.target.value; renderTrades(); });
    $("f-setup").addEventListener("change", function (e) { state.filt.setup = e.target.value; renderTrades(); });
    document.querySelectorAll("#f-result button").forEach(function (b) {
      b.addEventListener("click", function () {
        state.filt.r = b.dataset.r;
        document.querySelectorAll("#f-result button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        renderTrades();
      });
    });
    document.querySelectorAll("#trades-table th button.sort").forEach(function (b) {
      b.addEventListener("click", function () {
        var k = b.dataset.k;
        state.sort = { k: k, dir: state.sort.k === k && state.sort.dir === "desc" ? "asc" : "desc" };
        renderTrades();
      });
    });
    window.addEventListener("hashchange", function () { var h = location.hash.slice(1); if (VIEWS.indexOf(h) !== -1) setView(h, false); });

    setRun(0);
    var h = location.hash.slice(1);
    setView(VIEWS.indexOf(h) !== -1 ? h : "performance", false);
  }

  function setView(v, push, focus) {
    state.view = v;
    VIEWS.forEach(function (name) {
      var on = name === v, tab = $("tab-" + name);
      tab.setAttribute("aria-selected", String(on)); tab.tabIndex = on ? 0 : -1;
      $("view-" + name).hidden = !on;
      if (on && focus) tab.focus();
    });
    if (push) { try { history.replaceState(null, "", "#" + v); } catch (e) { location.hash = v; } }
    // Charts measure their container, so draw the visible view after it is shown.
    if (state.run) renderView(v);
  }

  function setRun(i) {
    var r = DATA.runs[i];
    state.run = r; state.sel = null; state.filt = { symbol: "", setup: "", r: "all" };
    document.querySelectorAll("#f-result button").forEach(function (x) { x.setAttribute("aria-pressed", String(x.dataset.r === "all")); });
    $("run").value = String(i);
    var first = r.equity_daily.length ? r.equity_daily[0].date : null, last = r.equity_daily.length ? r.equity_daily[r.equity_daily.length - 1].date : null;
    $("run-meta").textContent = r.n_days + " trading days" + (first ? ", " + fullDate(first) + " to " + fullDate(last) : "") +
      ", " + r.bar_minutes + "-minute bars, " + r.mode.replace(/_/g, " ") + ", starting with " + rs(r.start_capital, 0) + ".";

    var notes = [];
    if (r.synthetic) notes.push("prices are a synthetic random walk, not market data, so judge the pipeline here, not the strategy");
    var me = r.config && r.config.risk ? r.config.risk.min_edge_cost_multiple : null;
    if (me !== null && me !== SPEC_MIN_EDGE) notes.push("the minimum edge rule is set to " + num(me, 1) + "x instead of " + SPEC_MIN_EDGE + "x");
    $("notices").innerHTML = notes.length ? "<p class=\"notice\"><strong>Sample run.</strong> In this run " + notes.join(", and ") + ".</p>" : "";

    $("count-trades").textContent = r.trades_total.toLocaleString("en-IN");
    $("count-signals").textContent = r.candidates.toLocaleString("en-IN");
    renderKpis(r);
    renderEmpty(r);
    fillFilters(r);
    renderView(state.view);
  }

  function renderView(v) {
    if (v === "performance") renderPerformance();
    if (v === "trades") renderTrades();
    if (v === "funnel") renderFunnel();
    if (v === "edge") renderEdge();
  }

  function kpi(k, v, s, cls) { return "<div class=\"kpi\"><span class=\"k\">" + k + "</span><span class=\"v " + (cls || "") + "\">" + v + "</span><span class=\"s\">" + s + "</span></div>"; }
  function renderKpis(r) {
    var m = r.metrics || {}, has = r.trades_total > 0;
    var none = "No trades in this run";
    $("kpis").innerHTML = [
      kpi("Net P&amp;L after costs", rs(m.net_pnl), has ? "Before costs " + rs(m.gross_pnl) : none, pnlCls(m.net_pnl)),
      kpi("Trades", (m.trades || 0).toLocaleString("en-IN"), "From " + r.candidates.toLocaleString("en-IN") + " signals"),
      kpi("Win rate", has ? num(m.win_rate, 1) + "%" : "n/a", has ? "Average " + rs(m.expectancy) + " per trade" : none),
      kpi("Max drawdown", has ? num(m.max_drawdown_pct, 1) + "%" : "n/a", "Ending equity " + rs(m.final_equity !== undefined ? m.final_equity : r.start_capital)),
    ].join("");
  }

  function renderEmpty(r) {
    var has = r.trades_total > 0;
    document.querySelectorAll("[data-needs=\"trades\"]").forEach(function (el) { el.hidden = !has; });
    document.querySelectorAll("[data-empty=\"trades\"]").forEach(function (el) {
      el.hidden = has;
      if (has) return;
      var top = r.rejection_reasons[0];
      el.innerHTML = "<h2>No trades in this run</h2><p>All " + r.candidates.toLocaleString("en-IN") + " signals were rejected" +
        (top ? ". The most common reason was " + esc(reasonLabel(top.reason.split(": ")[1] || top.reason).toLowerCase()) + " (<code>" + esc(top.reason.split(": ")[1] || top.reason) + "</code>), " + top.count.toLocaleString("en-IN") + " times." : ".") +
        " The decision funnel shows every reason, and the signal edge view shows what those signals would have earned.</p>" +
        "<button type=\"button\" class=\"btn small\" data-go=\"funnel\">Open the decision funnel</button>";
      el.querySelector("[data-go]").addEventListener("click", function () { setView("funnel", true, true); });
    });
  }

  // ---- Performance ----------------------------------------------------------------------
  function sortedTrades(r) { return r.trades.slice().sort(function (a, b) { return a.exit_ts < b.exit_ts ? -1 : a.exit_ts > b.exit_ts ? 1 : 0; }); }

  function renderPerformance() {
    var r = state.run; if (!r.trades_total) return;
    var t = sortedTrades(r), truncated = r.trades_total > r.trades.length;
    var shownSum = t.reduce(function (a, x) { return a + x.net_pnl; }, 0);
    // When only the latest trades were exported, start the curve where those trades began.
    var eq = truncated ? r.metrics.final_equity - shownSum : r.start_capital, peak = eq;
    var shownNote = truncated ? " of the latest " + r.trades.length : "";
    var start = truncated ? null : r.start_capital;
    var pts = [], dd = [];
    if (start !== null) { pts.push({ y: eq, label: day(t[0].entry_ts), tip: "<strong>Start</strong><br>Equity " + rs(eq) }); dd.push({ y: 0, label: day(t[0].entry_ts), tip: "Drawdown 0.0%" }); }
    t.forEach(function (x, i) {
      eq += x.net_pnl; peak = Math.max(peak, eq);
      var d = (peak - eq) / peak * 100;
      pts.push({ y: eq, label: day(x.exit_ts), tip: "<strong>Trade " + (i + 1) + shownNote + "</strong><br>" + esc(dt(x.exit_ts)) + " " + esc(x.symbol) + "<br>Net " + signed(x.net_pnl, 2) + "<br>Equity " + rs(eq) });
      dd.push({ y: -d, label: day(x.exit_ts), tip: "Drawdown " + num(d, 1) + "%<br>" + esc(dt(x.exit_ts)) });
    });
    window.Charts.line($("equity-chart"), { pts: pts, ref: r.start_capital, area: "ink", animate: true, height: 280, xLabels: false, aria: "Equity after costs for each closed trade" });
    window.Charts.line($("dd-chart"), { pts: dd, area: "loss", areaBase: 0, cls: "loss", height: 120, ticks: 3, aria: "Drawdown in percent" });
    renderBy();
    var m = r.metrics;
    window.Charts.bars($("cost-chart"), {
      height: 200, aria: "Gross profit and loss, costs and net",
      items: [
        { label: "Gross P&L", value: m.gross_pnl, cls: m.gross_pnl >= 0 ? "gain" : "loss", tip: "Gross " + rs(m.gross_pnl) },
        { label: "Costs", value: -m.total_costs, cls: "accent", tip: "Costs " + rs(m.total_costs) },
        { label: "Net P&L", value: m.net_pnl, tip: "Net " + rs(m.net_pnl) },
      ],
    });
    var kv = [
      ["Before costs", rs(m.gross_pnl)], ["Fees and charges", rs(m.total_costs)],
      ["Average per trade", rs(m.expectancy)], ["Profit factor", m.profit_factor === null ? "n/a" : num(m.profit_factor, 2)],
      ["Average win", rs(m.avg_win)], ["Average loss", rs(m.avg_loss)],
      ["Time in market", num(m.exposure_pct, 1) + "%"], ["Sharpe, annualised daily", num(m.sharpe, 2)],
    ];
    $("cost-kv").innerHTML = kv.map(function (p) { return "<div><dt>" + p[0] + "</dt><dd>" + p[1] + "</dd></div>"; }).join("");
  }

  function renderBy() {
    var r = state.run, k = state.by, rows = (r.breakdowns[k] || []).slice();
    if (k === "hour") rows.sort(function (a, b) { return a.key - b.key; }); else rows.sort(function (a, b) { return a.net_pnl - b.net_pnl; });
    var label = function (x) { return k === "hour" ? String(x.key).padStart(2, "0") + ":00" : k === "setup" ? setupLabel(x.key) : x.key; };
    $("by-key").textContent = { setup: "Setup", symbol: "Symbol", hour: "Entry hour" }[k];
    window.Charts.bars($("by-chart"), {
      height: 220, aria: "Net profit and loss by " + k,
      items: rows.map(function (x) { return { label: label(x), short: k === "setup" ? SETUP_SHORT[x.key] : (k === "symbol" ? String(x.key).slice(0, 5) : label(x)), value: x.net_pnl, tip: label(x) + ": " + rs(x.net_pnl) }; }),
    });
    $("by-body").innerHTML = rows.map(function (x) {
      return "<tr><td>" + esc(label(x)) + "</td><td class=\"n\">" + x.trades + "</td><td class=\"n\">" + num(x.win_rate, 1) + "</td><td class=\"n " + pnlCls(x.net_pnl) + "\">" + num(x.net_pnl, 2) + "</td><td class=\"n " + pnlCls(x.expectancy) + "\">" + num(x.expectancy, 2) + "</td></tr>";
    }).join("");
  }

  // ---- Trades ---------------------------------------------------------------------------
  function fillFilters(r) {
    var syms = {}, sets = {};
    r.trades.forEach(function (t) { syms[t.symbol] = 1; sets[t.setup] = 1; });
    $("f-symbol").innerHTML = "<option value=\"\">All symbols</option>" + Object.keys(syms).sort().map(function (s) { return "<option>" + esc(s) + "</option>"; }).join("");
    $("f-setup").innerHTML = "<option value=\"\">All setups</option>" + Object.keys(sets).sort().map(function (s) { return "<option value=\"" + esc(s) + "\">" + esc(setupLabel(s)) + "</option>"; }).join("");
  }

  function renderTrades() {
    var r = state.run; if (!r.trades_total) return;
    var f = state.filt, s = state.sort;
    var rows = r.trades.filter(function (t) {
      return (!f.symbol || t.symbol === f.symbol) && (!f.setup || t.setup === f.setup) &&
        (f.r === "all" || (f.r === "win" ? t.net_pnl > 0 : t.net_pnl <= 0));
    });
    rows.sort(function (a, b) {
      var x = a[s.k], y = b[s.k], c = x < y ? -1 : x > y ? 1 : 0;
      return s.dir === "asc" ? c : -c;
    });
    document.querySelectorAll("#trades-table th button.sort").forEach(function (b) {
      if (b.dataset.k === s.k) b.setAttribute("data-dir", s.dir); else b.removeAttribute("data-dir");
      b.closest("th").setAttribute("aria-sort", b.dataset.k === s.k ? (s.dir === "asc" ? "ascending" : "descending") : "none");
    });
    var net = rows.reduce(function (a, t) { return a + t.net_pnl; }, 0);
    $("f-count").textContent = rows.length + " of " + r.trades_total + " trades" + (r.trades_total > r.trades.length ? " (latest " + r.trades.length + " exported)" : "") + ". Net " + rs(net) + ".";
    if (!rows.length) {
      $("trades-body").innerHTML = "<tr><td colspan=\"11\" class=\"muted\">No trades match these filters.</td></tr>";
      return;
    }
    if (state.sel === null || rows.indexOf(state.sel) === -1) state.sel = rows[0];
    $("trades-body").innerHTML = rows.map(function (t, i) {
      return "<tr class=\"clickable\" tabindex=\"0\" data-i=\"" + i + "\" aria-selected=\"" + (t === state.sel) + "\"><td class=\"num\">" + esc(dt(t.entry_ts)) + "</td><td>" + esc(t.symbol) + "</td><td>" + esc(setupLabel(t.setup)) +
        "</td><td><span class=\"side " + t.direction + "\">" + t.direction + "</span></td><td class=\"n\">" + t.qty + "</td><td class=\"n\">" + num(t.entry_price, 2) +
        "</td><td class=\"n\">" + num(t.exit_price, 2) + "</td><td>" + esc(EXITS[t.exit_reason] || t.exit_reason) + "</td><td class=\"n " + pnlCls(t.gross_pnl) + "\">" + num(t.gross_pnl, 2) +
        "</td><td class=\"n\">" + num(t.costs, 2) + "</td><td class=\"n " + pnlCls(t.net_pnl) + "\">" + num(t.net_pnl, 2) + "</td></tr>";
    }).join("");
    $("trades-body").querySelectorAll("tr.clickable").forEach(function (tr) {
      var pick = function () {
        state.sel = rows[+tr.dataset.i];
        $("trades-body").querySelectorAll("tr").forEach(function (x) { x.setAttribute("aria-selected", String(x === tr)); });
        renderDetail();
        if (window.innerWidth < 960) $("trade-detail").scrollIntoView({ block: "start", behavior: "smooth" });
      };
      tr.addEventListener("click", pick);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
    renderDetail();
  }

  function renderDetail() {
    var t = state.sel, r = state.run; if (!t) return;
    var key = t.symbol + "|" + t.entry_ts.slice(0, 10), bars = r.bars[key];
    $("td-title").textContent = t.symbol + ", " + setupLabel(t.setup).toLowerCase() + ", " + t.direction + ", " + fullDate(t.entry_ts);
    var host = $("candle-chart");
    if (!bars || !bars.length) {
      host.innerHTML = "<p class=\"muted small\">Candles for this day were not exported.</p>";
    } else {
      var ei = -1, xi = -1, et = t.entry_ts.slice(11, 16), xt = t.exit_ts.slice(11, 16);
      bars.forEach(function (b, i) { if (b[0] === et) ei = i; if (b[0] === xt) xi = i; });
      window.Charts.candles(host, {
        bars: bars, height: 340, aria: "Candles for " + t.symbol + " on " + fullDate(t.entry_ts),
        series: [{ col: 5, cls: "ink" }, { col: 6, cls: "accent dash" }],
        levels: [
          { value: t.target, cls: "gain", label: "Target", from: ei >= 0 ? ei : undefined },
          { value: t.stop, cls: "loss", label: "Stop", from: ei >= 0 ? ei : undefined },
        ],
        marks: [{ kind: "entry", i: ei, price: t.entry_price }, { kind: "exit", i: xi, price: t.exit_price }],
      });
    }
    var held = (Date.parse(t.exit_ts) - Date.parse(t.entry_ts)) / 60000;
    var kv = [
      ["Side and quantity", t.direction + ", " + t.qty + " shares"], ["Filled", dt(t.entry_ts) + " at " + num(t.entry_price, 2)],
      ["Closed", dt(t.exit_ts) + " at " + num(t.exit_price, 2)], ["Exit reason", EXITS[t.exit_reason] || t.exit_reason],
      ["Stop", num(t.stop, 2)], ["Target", num(t.target, 2)], ["Held", held < 1 ? "Same bar" : num(held, 0) + " min"],
      ["Gross", rs(t.gross_pnl)], ["Costs", rs(t.costs)], ["Net", rs(t.net_pnl)],
    ];
    $("td-kv").innerHTML = kv.map(function (p, i) { return "<div><dt>" + p[0] + "</dt><dd" + (i === 9 ? " class=\"" + pnlCls(t.net_pnl) + "\"" : "") + ">" + esc(p[1]) + "</dd></div>"; }).join("");
  }

  // ---- Funnel ---------------------------------------------------------------------------
  function hbar(label, sub, value, max, cls, valText) {
    return "<div class=\"hbar\"><span class=\"lbl\">" + label + (sub ? "<code>" + esc(sub) + "</code>" : "") + "</span><span class=\"track\"><span class=\"fill " + (cls || "") +
      "\" style=\"width:" + (max ? (value / max * 100).toFixed(2) : 0) + "%\"></span></span><span class=\"val\">" + (valText || value.toLocaleString("en-IN")) + "</span></div>";
  }
  function renderFunnel() {
    var r = state.run, f = {};
    r.funnel.forEach(function (x) { f[x.stage] = x.count; });
    var n = f["Candidates"] || 0, useML = r.mode !== "rules_only", useJev = r.mode === "rules_ml_jev";
    var h = "<div class=\"hbars\">" + hbar("Signals found", "detectors", n, n, "");
    h += useML ? hbar("Passed ML", "ml_prob", f["Passed ML"], n, "") : hbar("ML model", "not used in " + r.mode, 0, n, "skipped", "skipped");
    h += useJev ? hbar("Passed Jev", "jev", f["Passed Jev"], n, "") : hbar("Jev check", "not used in " + r.mode, 0, n, "skipped", "skipped");
    h += hbar("Passed risk checks", "risk manager", f["Passed risk"], n, "accent");
    h += hbar("Filled", "next bar open", f["Filled"], n, "gain") + "</div>";
    $("funnel").innerHTML = h;
    var pct = n ? f["Filled"] / n * 100 : 0;
    $("funnel-note").textContent = n ? num(pct, 2) + "% of signals became trades." : "";
    var max = r.rejection_reasons.length ? r.rejection_reasons[0].count : 0;
    $("reasons").innerHTML = r.rejection_reasons.length ? "<div class=\"hbars\">" + r.rejection_reasons.map(function (x) {
      var k = x.reason.split(": ")[1] || x.reason;
      return hbar(esc(reasonLabel(k)), k, x.count, max, "loss");
    }).join("") + "</div>" : "<p class=\"muted\">No signals were rejected.</p>";
    var rej = r.rejected_sample.slice().reverse(), total = n - (f["Filled"] || 0);
    $("rej-note").textContent = "Latest " + rej.length.toLocaleString("en-IN") + " of " + total.toLocaleString("en-IN");
    $("rej-body").innerHTML = rej.map(function (x) {
      var k = reasonKey(x.final_status);
      return "<tr><td class=\"num\">" + esc(dt(x.ts)) + "</td><td>" + esc(x.symbol) + "</td><td>" + esc(setupLabel(x.setup)) + "</td><td><span class=\"side " + x.direction + "\">" + x.direction +
        "</span></td><td class=\"n\">" + num(x.entry, 2) + "</td><td class=\"n\">" + num(x.stop, 2) + "</td><td class=\"n\">" + num(x.target, 2) + "</td><td>" + esc(reasonLabel(k)) +
        "</td><td>" + esc(OUTCOMES[x.outcome] || x.outcome) + "</td><td class=\"n " + pnlCls(x.hyp_pnl_per_share) + "\">" + num(x.hyp_pnl_per_share, 2) + "</td></tr>";
    }).join("") || "<tr><td colspan=\"10\" class=\"muted\">No rejected signals.</td></tr>";
  }

  // ---- Edge -----------------------------------------------------------------------------
  function renderEdge() {
    var r = state.run, e = r.edge.overall || {};
    if (!e.candidates) {
      $("edge-kpis").innerHTML = ""; $("edge-chart").innerHTML = "<p class=\"muted\">No tradeable signals to score.</p>"; $("edge-body").innerHTML = "";
      return;
    }
    $("edge-kpis").innerHTML = [
      kpi("Signals scored", e.candidates.toLocaleString("en-IN"), "Inside the entry window"),
      kpi("Win rate", num(e.win_rate, 1) + "%", "Target before stop"),
      kpi("Breakeven", num(e.breakeven_win_rate, 1) + "%", "Needed at this reward to risk"),
      kpi("Gross R", signed(e.mean_gross_r, 2), "After slippage, before fees", pnlCls(e.mean_gross_r)),
      kpi("Fee R", MINUS + num(e.mean_fee_r, 2), "Fees per signal in R", "loss"),
      kpi("Net R", signed(e.mean_net_r, 2), "Per signal, after everything", pnlCls(e.mean_net_r)),
    ].join("");
    var rows = Object.keys(r.edge.by_setup).map(function (k) { return [k, r.edge.by_setup[k]]; });
    window.Charts.bars($("edge-chart"), {
      height: 200, aria: "Net R per signal by setup",
      items: rows.map(function (p) { return { label: setupLabel(p[0]), short: SETUP_SHORT[p[0]], value: p[1].mean_net_r, tip: setupLabel(p[0]) + ": " + signed(p[1].mean_net_r, 2) + " R" }; }),
    });
    $("edge-body").innerHTML = rows.map(function (p) {
      var s = p[1];
      return "<tr><td>" + esc(setupLabel(p[0])) + "</td><td class=\"n\">" + s.candidates.toLocaleString("en-IN") + "</td><td class=\"n\">" + num(s.win_rate, 1) + "</td><td class=\"n\">" + num(s.breakeven_win_rate, 1) +
        "</td><td class=\"n " + pnlCls(s.mean_gross_r) + "\">" + signed(s.mean_gross_r, 2) + "</td><td class=\"n loss\">" + MINUS + num(s.mean_fee_r, 2) + "</td><td class=\"n " + pnlCls(s.mean_net_r) + "\">" + signed(s.mean_net_r, 2) +
        "</td><td class=\"n\">" + num(s.median_risk_pct, 2) + "%</td></tr>";
    }).join("");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
