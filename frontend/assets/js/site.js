// Shared behaviour: theme button (Auto, Light, Dark), mobile menu, header rule on scroll, site config placeholders.
(function () {
  "use strict";
  var KEY = "tradebot-theme";
  var ORDER = ["auto", "light", "dark"];
  var LABEL = { auto: "Theme: Auto", light: "Theme: Light", dark: "Theme: Dark" };
  var root = document.documentElement;

  function readTheme() {
    try { var v = localStorage.getItem(KEY); return ORDER.indexOf(v) === -1 ? "auto" : v; } catch (e) { return "auto"; }
  }
  function writeTheme(v) {
    try { if (v === "auto") localStorage.removeItem(KEY); else localStorage.setItem(KEY, v); } catch (e) { /* storage blocked */ }
  }
  function applyTheme(v) {
    if (v === "light" || v === "dark") root.setAttribute("data-theme", v);
    else root.removeAttribute("data-theme");
    document.querySelectorAll(".theme-toggle").forEach(function (b) {
      b.innerHTML = "<span class=\"tt-k\">Theme: </span>" + LABEL[v].replace("Theme: ", "");
      b.setAttribute("aria-label", LABEL[v] + ". Select to change.");
    });
  }

  var stored = readTheme();
  if (stored !== "auto") applyTheme(stored);

  document.addEventListener("DOMContentLoaded", function () {
    var current = readTheme();
    applyTheme(current);
    document.querySelectorAll(".theme-toggle").forEach(function (b) {
      b.addEventListener("click", function () {
        current = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
        writeTheme(current); applyTheme(current);
      });
    });

    var menu = document.querySelector(".menu-btn"), nav = document.getElementById("site-nav");
    if (menu && nav) {
      var setMenu = function (open) { nav.classList.toggle("open", open); menu.setAttribute("aria-expanded", String(open)); menu.textContent = open ? "Close" : "Menu"; };
      menu.addEventListener("click", function () { setMenu(!nav.classList.contains("open")); });
      nav.querySelectorAll("a").forEach(function (a) { a.addEventListener("click", function () { setMenu(false); }); });
      document.addEventListener("keydown", function (e) { if (e.key === "Escape" && nav.classList.contains("open")) { setMenu(false); menu.focus(); } });
    }

    var header = document.querySelector(".site-header");
    if (header) {
      var onScroll = function () { header.classList.toggle("scrolled", window.scrollY > 8); };
      window.addEventListener("scroll", onScroll, { passive: true }); onScroll();
    }

    var cfg = window.SITE_CONFIG || {};
    document.querySelectorAll("[data-config]").forEach(function (el) {
      var k = el.getAttribute("data-config");
      var v = (cfg[k] || "").trim();
      if (v) { el.textContent = v; el.classList.remove("unset"); }
      else { el.textContent = "[" + k + " not set in assets/js/site-config.js]"; el.classList.add("unset"); }
    });
  });
})();
