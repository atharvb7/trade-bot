// Small SVG chart helpers. Every chart is drawn at the container's real pixel width so text
// stays 11px on any screen, and redrawn when the container resizes. Colours come from CSS classes
// that read theme tokens, so a theme switch needs no redraw.
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var MINUS = "−";

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c]; }); }

  function niceTicks(min, max, count) {
    if (min === max) { min -= 1; max += 1; }
    var span = max - min, step = Math.pow(10, Math.floor(Math.log10(span / count)));
    var err = span / count / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    var lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [];
    for (var v = lo; v <= hi + step / 2; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : v);
    return { ticks: out, lo: lo, hi: hi, step: step };
  }
  function fmtTick(v, step) {
    var d = step >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log10(step)));
    var s = Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
    return (v < 0 ? MINUS : "") + s;
  }

  // Register a draw function that re-runs on resize.
  var observers = new WeakMap();
  function mount(host, draw) {
    var run = function () { draw(Math.max(260, Math.floor(host.clientWidth))); };
    run();
    if (!window.ResizeObserver) return;
    var prev = observers.get(host); if (prev) prev.disconnect();
    var last = host.clientWidth;
    var ro = new ResizeObserver(function () {
      var w = host.clientWidth; if (Math.abs(w - last) < 2) return; last = w; run();
    });
    ro.observe(host); observers.set(host, ro);
  }

  function tooltip(host) {
    var t = host.querySelector(".tooltip");
    if (!t) { t = document.createElement("div"); t.className = "tooltip"; t.hidden = true; host.appendChild(t); }
    return {
      show: function (html, x, y, W) {
        t.innerHTML = html; t.hidden = false;
        var tw = t.offsetWidth, left = x + 14;
        if (left + tw > W) left = x - tw - 14;
        if (left < 0) left = 0;
        t.style.left = left + "px"; t.style.top = Math.max(0, y - 10) + "px";
      },
      hide: function () { t.hidden = true; },
    };
  }

  // Hover handling: map pointer x to the nearest index.
  function hover(host, svg, n, xOf, onIdx, onLeave) {
    var hit = svg.querySelector(".hit");
    function at(e) {
      var r = svg.getBoundingClientRect(), px = e.clientX - r.left, best = 0, bd = Infinity;
      for (var i = 0; i < n; i++) { var d = Math.abs(xOf(i) - px); if (d < bd) { bd = d; best = i; } }
      onIdx(best, e.clientY - r.top);
    }
    hit.addEventListener("pointermove", at);
    hit.addEventListener("pointerdown", at);
    hit.addEventListener("pointerleave", onLeave);
  }

  // Line chart with optional reference line and area. pts: [{y, label, tip}]
  function line(host, o) {
    mount(host, function (W) {
      var H = o.height || 260, m = { t: 12, r: 16, b: o.xLabels === false ? 8 : 26, l: 56 };
      var ys = o.pts.map(function (p) { return p.y; }).concat(o.ref !== undefined ? [o.ref] : []);
      var nt = niceTicks(Math.min.apply(null, ys), Math.max.apply(null, ys), o.ticks || 5);
      var n = o.pts.length, iw = W - m.l - m.r, ih = H - m.t - m.b;
      var x = function (i) { return m.l + (n === 1 ? iw / 2 : i / (n - 1) * iw); };
      var y = function (v) { return m.t + (nt.hi - v) / (nt.hi - nt.lo) * ih; };
      var s = "<svg xmlns=\"" + NS + "\" width=\"" + W + "\" height=\"" + H + "\" viewBox=\"0 0 " + W + " " + H + "\" role=\"img\" aria-label=\"" + esc(o.aria || "Line chart") + "\">";
      s += "<g class=\"grid\">" + nt.ticks.map(function (t) { return "<line x1=\"" + m.l + "\" x2=\"" + (W - m.r) + "\" y1=\"" + y(t).toFixed(1) + "\" y2=\"" + y(t).toFixed(1) + "\"/>"; }).join("") + "</g>";
      s += nt.ticks.map(function (t) { return "<text x=\"" + (m.l - 8) + "\" y=\"" + (y(t) + 4).toFixed(1) + "\" text-anchor=\"end\">" + fmtTick(t, nt.step) + "</text>"; }).join("");
      if (o.xLabels !== false) {
        var every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 90))));
        for (var i = 0; i < n; i += every) s += "<text x=\"" + x(i).toFixed(1) + "\" y=\"" + (H - 8) + "\" text-anchor=\"" + (i === 0 ? "start" : "middle") + "\">" + esc(o.pts[i].label) + "</text>";
      }
      var d = o.pts.map(function (p, i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p.y).toFixed(1); }).join("");
      if (o.area) {
        var base = y(o.areaBase !== undefined ? o.areaBase : nt.lo);
        s += "<path class=\"area " + o.area + "\" d=\"" + d + "L" + x(n - 1).toFixed(1) + " " + base.toFixed(1) + "L" + x(0).toFixed(1) + " " + base.toFixed(1) + "Z\"/>";
      }
      if (o.ref !== undefined) s += "<line class=\"ln ref\" x1=\"" + m.l + "\" x2=\"" + (W - m.r) + "\" y1=\"" + y(o.ref).toFixed(1) + "\" y2=\"" + y(o.ref).toFixed(1) + "\"/>";
      s += "<path class=\"ln " + (o.cls || "ink") + (o.animate ? " draw" : "") + "\" d=\"" + d + "\"/>";
      s += "<line class=\"cursor\" y1=\"" + m.t + "\" y2=\"" + (H - m.b) + "\" x1=\"-10\" x2=\"-10\"/><circle class=\"dot\" r=\"4\" cx=\"-10\" cy=\"-10\"/>";
      s += "<rect class=\"hit\" x=\"" + m.l + "\" y=\"0\" width=\"" + iw + "\" height=\"" + H + "\" fill=\"transparent\"/></svg>";
      host.innerHTML = s;
      var svg = host.querySelector("svg");
      var path = svg.querySelector(".draw");
      if (path) { path.style.setProperty("--len", Math.ceil(path.getTotalLength())); }
      var tt = tooltip(host), cur = svg.querySelector(".cursor"), dot = svg.querySelector(".dot");
      hover(host, svg, n, x, function (i, py) {
        var cx = x(i).toFixed(1);
        cur.setAttribute("x1", cx); cur.setAttribute("x2", cx);
        dot.setAttribute("cx", cx); dot.setAttribute("cy", y(o.pts[i].y).toFixed(1));
        if (o.pts[i].tip) tt.show(o.pts[i].tip, x(i), py, W);
      }, function () { cur.setAttribute("x1", -10); cur.setAttribute("x2", -10); dot.setAttribute("cx", -10); tt.hide(); });
    });
  }

  // Vertical bars, signed values. items: [{label, value, tip}]
  function bars(host, o) {
    mount(host, function (W) {
      var H = o.height || 220, m = { t: 16, r: 12, b: 34, l: 56 };
      var vals = o.items.map(function (d) { return d.value; }).concat([0]);
      var nt = niceTicks(Math.min.apply(null, vals), Math.max.apply(null, vals), 4);
      var n = o.items.length, iw = W - m.l - m.r, ih = H - m.t - m.b, bw = Math.min(56, iw / n * 0.62);
      var cx = function (i) { return m.l + (i + 0.5) * iw / n; };
      var y = function (v) { return m.t + (nt.hi - v) / (nt.hi - nt.lo) * ih; };
      var s = "<svg xmlns=\"" + NS + "\" width=\"" + W + "\" height=\"" + H + "\" viewBox=\"0 0 " + W + " " + H + "\" role=\"img\" aria-label=\"" + esc(o.aria || "Bar chart") + "\">";
      s += "<g class=\"grid\">" + nt.ticks.map(function (t) { return "<line x1=\"" + m.l + "\" x2=\"" + (W - m.r) + "\" y1=\"" + y(t).toFixed(1) + "\" y2=\"" + y(t).toFixed(1) + "\"/>"; }).join("") + "</g>";
      s += nt.ticks.map(function (t) { return "<text x=\"" + (m.l - 8) + "\" y=\"" + (y(t) + 4).toFixed(1) + "\" text-anchor=\"end\">" + fmtTick(t, nt.step) + "</text>"; }).join("");
      var slotW = iw / n;
      var tooLong = o.items.some(function (d) { return d.label.length * 6.8 > slotW - 8; });
      var shortTooLong = o.items.some(function (d) { return (d.short || d.label).length * 6.8 > slotW - 4; });
      o.items.forEach(function (d, i) {
        var y0 = y(0), y1 = y(d.value), top = Math.min(y0, y1), h = Math.max(1, Math.abs(y1 - y0));
        s += "<rect class=\"bar " + (d.cls || (d.value >= 0 ? "gain" : "loss")) + "\" x=\"" + (cx(i) - bw / 2).toFixed(1) + "\" y=\"" + top.toFixed(1) + "\" width=\"" + bw.toFixed(1) + "\" height=\"" + h.toFixed(1) + "\"><title>" + esc(d.tip || d.label) + "</title></rect>";
        var lbl = tooLong && d.short ? d.short : d.label;
        if (!(tooLong && shortTooLong)) s += "<text x=\"" + cx(i).toFixed(1) + "\" y=\"" + (H - 14) + "\" text-anchor=\"middle\">" + esc(lbl) + "</text>";
      });
      s += "<line class=\"axis-zero\" x1=\"" + m.l + "\" x2=\"" + (W - m.r) + "\" y1=\"" + y(0).toFixed(1) + "\" y2=\"" + y(0).toFixed(1) + "\"/></svg>";
      host.innerHTML = s;
    });
  }

  // Intraday candles with level lines and entry/exit markers.
  function candles(host, o) {
    mount(host, function (W) {
      var H = o.height || 340, m = { t: 12, r: 64, b: 26, l: 56 };
      var b = o.bars, n = b.length;
      var lo = Infinity, hi = -Infinity;
      b.forEach(function (r) { lo = Math.min(lo, r[3]); hi = Math.max(hi, r[2]); });
      (o.levels || []).forEach(function (l) { if (l.value !== null && isFinite(l.value)) { lo = Math.min(lo, l.value); hi = Math.max(hi, l.value); } });
      var pad = (hi - lo) * 0.04; lo -= pad; hi += pad;
      var nt = niceTicks(lo, hi, 5);
      var iw = W - m.l - m.r, ih = H - m.t - m.b, slot = iw / n, cw = Math.max(1, Math.min(9, slot * 0.64));
      var x = function (i) { return m.l + (i + 0.5) * slot; };
      var y = function (v) { return m.t + (nt.hi - v) / (nt.hi - nt.lo) * ih; };
      var s = "<svg xmlns=\"" + NS + "\" width=\"" + W + "\" height=\"" + H + "\" viewBox=\"0 0 " + W + " " + H + "\" role=\"img\" aria-label=\"" + esc(o.aria || "Candle chart") + "\">";
      s += "<g class=\"grid\">" + nt.ticks.filter(function (t) { return t >= lo && t <= hi; }).map(function (t) { return "<line x1=\"" + m.l + "\" x2=\"" + (W - m.r) + "\" y1=\"" + y(t).toFixed(1) + "\" y2=\"" + y(t).toFixed(1) + "\"/>"; }).join("") + "</g>";
      s += nt.ticks.filter(function (t) { return t >= lo && t <= hi; }).map(function (t) { return "<text x=\"" + (m.l - 8) + "\" y=\"" + (y(t) + 4).toFixed(1) + "\" text-anchor=\"end\">" + fmtTick(t, nt.step) + "</text>"; }).join("");
      var every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 70))));
      for (var i = 0; i < n; i += every) s += "<text x=\"" + x(i).toFixed(1) + "\" y=\"" + (H - 8) + "\" text-anchor=\"middle\">" + esc(b[i][0]) + "</text>";
      b.forEach(function (r, i) {
        var up = r[4] >= r[1], c = up ? "up" : "down";
        s += "<line class=\"wick " + c + "\" x1=\"" + x(i).toFixed(1) + "\" x2=\"" + x(i).toFixed(1) + "\" y1=\"" + y(r[2]).toFixed(1) + "\" y2=\"" + y(r[3]).toFixed(1) + "\"/>";
        var top = y(Math.max(r[1], r[4])), h = Math.max(1, Math.abs(y(r[1]) - y(r[4])));
        s += "<rect class=\"candle " + c + "\" x=\"" + (x(i) - cw / 2).toFixed(1) + "\" y=\"" + top.toFixed(1) + "\" width=\"" + cw.toFixed(1) + "\" height=\"" + h.toFixed(1) + "\"/>";
      });
      (o.series || []).forEach(function (sr) {
        var d = "", pen = false;
        b.forEach(function (r, i) { var v = r[sr.col]; if (v === null || !isFinite(v)) { pen = false; return; } d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); pen = true; });
        if (d) s += "<path class=\"ln " + sr.cls + "\" d=\"" + d + "\"/>";
      });
      (o.levels || []).forEach(function (l) {
        if (l.value === null || !isFinite(l.value)) return;
        var from = l.from !== undefined ? x(l.from) - slot / 2 : m.l;
        s += "<line class=\"ln dash " + l.cls + "\" x1=\"" + from.toFixed(1) + "\" x2=\"" + (W - m.r) + "\" y1=\"" + y(l.value).toFixed(1) + "\" y2=\"" + y(l.value).toFixed(1) + "\"/>";
        s += "<text class=\"lvl-label " + l.cls + "\" x=\"" + (W - m.r + 6) + "\" y=\"" + (y(l.value) + 4).toFixed(1) + "\">" + esc(l.label) + "</text>";
      });
      (o.marks || []).forEach(function (mk) {
        if (mk.i < 0) return;
        var mx = x(mk.i), my = y(mk.price);
        s += mk.kind === "entry"
          ? "<path class=\"mark entry\" d=\"M" + (mx - 6).toFixed(1) + " " + (my - 6).toFixed(1) + "L" + (mx + 6).toFixed(1) + " " + my.toFixed(1) + "L" + (mx - 6).toFixed(1) + " " + (my + 6).toFixed(1) + "Z\"><title>Entry " + mk.price.toFixed(2) + "</title></path>"
          : "<rect class=\"mark exit\" x=\"" + (mx - 5).toFixed(1) + "\" y=\"" + (my - 5).toFixed(1) + "\" width=\"10\" height=\"10\"><title>Exit " + mk.price.toFixed(2) + "</title></rect>";
      });
      s += "<line class=\"cursor\" y1=\"" + m.t + "\" y2=\"" + (H - m.b) + "\" x1=\"-10\" x2=\"-10\"/>";
      s += "<rect class=\"hit\" x=\"" + m.l + "\" y=\"0\" width=\"" + iw + "\" height=\"" + H + "\" fill=\"transparent\"/></svg>";
      host.innerHTML = s;
      var svg = host.querySelector("svg"), tt = tooltip(host), cur = svg.querySelector(".cursor");
      hover(host, svg, n, x, function (i, py) {
        var r = b[i], cx = x(i).toFixed(1);
        cur.setAttribute("x1", cx); cur.setAttribute("x2", cx);
        tt.show("<strong>" + esc(r[0]) + "</strong><br>O " + r[1].toFixed(2) + "  H " + r[2].toFixed(2) + "<br>L " + r[3].toFixed(2) + "  C " + r[4].toFixed(2) +
          (r[5] !== null ? "<br>VWAP " + r[5].toFixed(2) : "") + (r[6] !== null ? "<br>EMA21 " + r[6].toFixed(2) : ""), x(i), py, W);
      }, function () { cur.setAttribute("x1", -10); cur.setAttribute("x2", -10); tt.hide(); });
    });
  }

  window.Charts = { line: line, bars: bars, candles: candles, niceTicks: niceTicks, esc: esc };
})();
