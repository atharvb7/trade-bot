# Trade-bot website

Static site for the project: a project page, a backtest dashboard, a privacy policy and terms.
No build step, no framework, no third-party requests. Fonts are self-hosted.

```
frontend/
  index.html          project page (trade ticket sliders, pipeline, results, build status)
  dashboard.html      backtest dashboard (reads data/runs.js)
  privacy.html        privacy policy
  terms.html          terms and conditions
  404.html            not-found page (uses root-relative paths, so serve the site from the domain root)
  favicon.svg / .ico / -32.png, apple-touch-icon.png, icon-192.png, icon-512.png, site.webmanifest
  robots.txt
  assets/css/         site.css (tokens, shared), home.css, dashboard.css
  assets/js/          site-config.js (fill in before launch), site.js, home.js, charts.js, dashboard.js
  assets/fonts/       Nunito Sans and IBM Plex Mono woff2 files with their OFL licences
  data/runs.js        exported backtest runs (generated, do not edit by hand)
```

## Update the dashboard data

```bash
pip install -e .                       # once, so scripts can import bot
python scripts/run_backtest.py --bar-minutes 5            # real data in data/parquet
python scripts/run_backtest.py --synthetic --bar-minutes 5 # or synthetic data
python scripts/export_frontend_data.py                     # writes frontend/data/runs.js
python -m http.server 8000 --directory frontend           # preview at http://localhost:8000
```

`export_frontend_data.py` exports every run in `data/backtests/`. Pass `--runs <id> <id>` to pick
specific runs. The dashboard shows a "Synthetic data" notice for synthetic runs and a
"Research override" notice when the minimum edge rule differs from 3x.

The sample `data/runs.js` in this folder holds two synthetic runs made on 27 October 2026:
one with the spec risk rules (0 trades, every signal blocked) and one with the minimum edge
rule set to 0 for research (159 trades). Replace them with real runs before launch.

## Launch checklist

Do not make the site public until every item is done.

- [ ] Custom domain connected on your host, with HTTPS on.
- [ ] `assets/js/site-config.js` filled in: `operatorName`, `contactEmail`, `domain`, `hostingProvider`.
      Empty values show a red "not set" marker on the legal pages and footer.
- [ ] Privacy policy and terms read through and, ideally, reviewed by a lawyer. They describe this
      site exactly as built: no cookies, no analytics, no forms. If you add any of those, update the
      privacy policy first.
- [ ] Favicon set present (already done: svg, ico, png, apple-touch, manifest icons).
- [ ] No "made with" badges or generator tags. None are included. Check your host does not inject one.
- [ ] `data/runs.js` regenerated from the runs you want to show.
- [ ] 404 page configured on your host (Netlify and Cloudflare Pages pick up `404.html` automatically;
      GitHub Pages does too when the site is served from the domain root).

## Hosting notes

Any static host works: Cloudflare Pages, Netlify, GitHub Pages, or an S3 bucket behind a CDN.
Point the host at the `frontend/` folder with no build command.

Do not put the kill switch or any broker control on this public site. The Streamlit dashboard in
`dashboard/` is the operator console and should stay bound to localhost.
