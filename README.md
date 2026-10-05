# asifah-backend

**Middle East & North Africa theatre backend — and the canonical layer for
[Asifah Analytics](https://asifahanalytics.com)**

This service does two jobs. It is the MENA theatre backend, and it is where the
platform's cross-cutting layers live: the Global Pressure Index, the convergence
registry and detector, the commodity and corridor registries, and the country-id
canon that every other backend resolves against. Sister backends cover Europe &
Eurasia, Asia & the Pacific, Africa and the Western Hemisphere.

> **What this is.** A one-person project, built on nights and weekends, running
> on free tiers and stubbornness. No affiliation with or endorsement by any
> government or organisation. If it has been useful to you,
> ☕ [a coffee](https://buymeacoffee.com/asifahanalytics) pays for the hosting
> that keeps it up.

> 🚨 **Not for operational use.** Analytical and research purposes only. See
> [`LICENSE`](./LICENSE).

**Scale:** 92 modules, 198 registered routes. The largest service on the platform.

---

## 🌍 Coverage

| Country | Role |
|---|---|
| 🇮🇷 Iran | **Resident hub.** Protests, financial pulse, strike-window detector |
| 🇮🇱 Israel | **Resident hub.** Stability module |
| 🇱🇧 Lebanon | Events, humanitarian, stability |
| 🇸🇾 Syria | Humanitarian; Idlib and the Badiya |
| 🇮🇶 Iraq | Humanitarian, stability |
| 🇾🇪 Yemen | Stability |
| 🇴🇲 Oman | Dual-axis stability anchor (v2.0) |
| 🇶🇦 Qatar | Mediation class (Jul 2026); stability |
| 🇸🇦 Saudi Arabia | Friction + détente shim (Jul 2026); stability |
| 🇦🇪 UAE | Aligned hub (Jul 2026); stability |
| 🇱🇾 Libya | Rhetoric, humanitarian, oil pulse — **built but not wired into the regional BLUF, see below** |

**Resident hubs:** `iran` and `israel`. Their rims are assembled here and read by
every other backend through shared Redis.

Countries without a tracker are absent from the MENA read, not assessed as quiet.

> ### ⚠️ Known defect: Libya
>
> `rhetoric_tracker_libya.py` is complete and registered — ten routes, its own
> humanitarian and oil-pulse modules. Two things are wrong with how it connects:
>
> 1. **It is absent from `TRACKER_KEYS` in `me_regional_bluf.py`.** The tracker
>    runs and nothing rolls it up, so Libya never reaches the regional BLUF or
>    the GPI.
> 2. **Its cross-theatre fingerprint expires too fast.** Lines 1024 and 1079
>    write `crosstheater:libya:fingerprint` with `ttl=8 * 3600`. Its own rhetoric
>    cache gets 24h, and `spoke_wheel_reader` treats anything over 24h as stale.
>    An 8-hour TTL on a key rewritten far less often than that means the
>    fingerprint is simply gone for most of the cycle.
>
> Consequence: Libya reads `present: false` on the Russia wheel — the only dark
> spoke on the rim, and one of the three largest Russian deployments on the
> continent. **That absence is plumbing, not a finding.** Exactly the failure
> mode this platform exists to avoid: a gap that looks like a reading.

---

## 🏗 Architecture

### Theatre layer

Per-country rhetoric trackers and signal interpreters, humanitarian and
stability modules, rolled up by `me_regional_bluf.py` into a single regional
posture and signal pool.

### Canonical layer (consumed by every other backend)

| Area | Modules |
|---|---|
| **Global Pressure Index** | `global_pressure_index.py`, `gpi_snapshot.py`, `gpi_delta.py`, `gpi_tagging_audit.py` |
| **Convergence** | `convergence_registry.py`, `convergence_detector.py`, `convergence_endpoints.py`, `humanitarian_convergence_detector.py`, `commodity_structural_convergence.py`, `fertilizer_convergence.py`, `diplomatic_convergence_gatherer.py` |
| **Commodity & corridors** | `commodity_tracker.py`, `commodity_signal_interpreter.py`, `corridor_dependence.py`, `food_price_pulse.py`, `fews_net.py` |
| **Country canon** | `country_ids.py` — one id per country; every reader door canonicalises through it |
| **Detectors** | `cascade_detector.py`, `absorption_detector.py`, `jawboning_detector.py`, `market_blackswan_detector.py`, `conflict_repricing_detector.py`, `iran_strike_window_detector.py` |
| **Market** | `market_fetch.py`, `market_prose.py`, `butterfly_reader.py` |
| **Military** | `military_tracker.py`, `military_signal_interpreter.py` |
| **Aviation & disaster** | `notam_monitor.py`, `disaster_feeds.py` |
| **Ingestion** | `gdelt_gateway.py`, `gdelt_trickle.py`, `brave_gateway.py`, `rss_monitor.py`, `telegram_signals.py`, `telegram_scraper.py`, `bluesky_signals_me.py`, `think_tank_feeds.py`, `unhcr_feeds.py`, `world_bank_gatherer.py`, `us_voice_signals.py`, `humanitarian_article_gatherer.py`, `kinetic_activity_gatherer.py` |
| **Operations** | `instance_lock.py`, `feed_health.py`, `framework_gates.py`, `tempo_baseline.py`, `strike_window_history.py` |
| **Shared libraries** | `spoke_wheel_reader.py`, `trajectory_reader.py`, `theatre_state.py` |

**Shared libraries deploy byte-identical to every backend.** `spoke_wheel_reader.py`,
`trajectory_reader.py`, `theatre_state.py` and `gdelt_gateway.py` are library
code, not data. If you change one here, change it everywhere.

**One writer, many readers.** The registries above have exactly one producer —
this service. Asia and Africa read them through `convergence_proxy_*` and
`commodity_proxy_*`. Europe currently carries a local fork of
`convergence_registry.py` five months behind this one; that is a defect tracked
in the Europe repo, not a pattern to copy.

---

## 🚀 Deployment

Deploys to Render via GitHub auto-deploy.

### Render configuration

```
Language:        Python 3.11+
Build Command:   pip install -r requirements.txt
Start Command:   gunicorn app:app --timeout 300 --workers 2
Health Check:    /health
```

> ⚠️ **CRITICAL:** the start command MUST include `--timeout 300 --workers 2`.
> Render's default 30-second timeout is shorter than a full scan cycle, and this
> is the single most common deploy bug across Asifah backends.

### Environment variables

Set in the Render dashboard. **Secrets belong in environment variables, never in
source** — anything committed to this repository should be assumed public and
rotated.

| Variable | Purpose |
|---|---|
| `UPSTASH_REDIS_URL` / `UPSTASH_REDIS_REST_URL` | Upstash Redis REST endpoint |
| `UPSTASH_REDIS_TOKEN` / `UPSTASH_REDIS_REST_TOKEN` | Upstash Redis REST bearer token |
| `NEWSAPI_KEY` | NewsAPI.org |
| `BRAVE_API_KEY`, `BRAVE_DAILY_BUDGET` | Brave Search + daily call budget |
| `ALPHA_VANTAGE_KEY`, `EODHD_API_KEY`, `FRED_API_KEY`, `TASE_API_KEY` | Market and macro data |
| `ACLED_API_KEY`, `ACLED_EMAIL` | ACLED conflict event data |
| `DTM_API_KEY`, `RELIEFWEB_APPNAME` | IOM Displacement Tracking Matrix, ReliefWeb |
| `CARTO_API_KEY` | Mapping |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` / `TELEGRAM_RESOLVE_BUDGET` | Telegram MTProto |
| `OREF_RELAY_URL` | Alert relay |
| `EUROPE_BACKEND_URL`, `ASIA_BACKEND_URL`, `WHA_BACKEND_URL`, `AFRICA_BACKEND_URL` | Sister backends, for the GPI's regional reads |
| `ADMIN_REFRESH_KEY`, `ASIFAH_ADMIN_TOKEN` | Admin-gated refresh endpoints |
| `PYTHONUNBUFFERED` | Set to `1` — forces stdout flush for Render Live Tail visibility |

Tuning: `GDELT_TRICKLE_*` (enabled, lap, backoff, budget), `FEED_HEALTH_TTL_SEC`,
`FEED_SILENT_DAYS`, `FEED_DEAD_DAYS`, `INSTANCE_LOCK_TTL_SEC`,
`HUMANITARIAN_BLUF_TTL_SEC`, `HUMANITARIAN_WARM_INTERVAL_SEC`,
`RHETORIC_SCAN_DISABLED`.

> ⚠️ **`EUROPE_BACKEND_URL` resolves to `asifa-europe-backend.onrender.com` —
> no `h`.** The Europe repo is named with one; the deployed service is not.

### Manual redeploy

Auto-deploy is enabled, but the canonical practice is to confirm each deploy
manually in the Render dashboard so the deploy log can be read before scans run.

> On a 404 after deploy, read the **startup sequence** in the log, not the tail.
> An import error prints its traceback at boot and has usually scrolled away by
> the time you look. `app.py` prints each module's import result and a full
> traceback on failure — that output is the diagnosis.

---

## 📡 Endpoints

198 routes are registered; full inventory at `/debug/routes`. The ones used most:

| Endpoint | Purpose |
|---|---|
| `/api/gpi` | **Global Pressure Index** — every theatre, every axis |
| `/api/gpi/delta` · `/api/gpi/delta/summary` | What changed, over 1d / 7d / 30d windows. The newsletter payload |
| `/api/rhetoric/me/bluf` | MENA regional BLUF — `?force=true` rebuilds |
| `/api/rhetoric/<country>` · `/history` · `/summary` | Country trackers |
| `/api/cax/scan` · `/api/cax/history/<country>` · `/api/cax/probe` | Convergence detector — scan, per-country history, and a probe reporting which caches are warm |
| `/api/commodity-pressure/bluf` | Commodity pressure synthesis |
| `/api/humanitarian-convergence/bluf` | Humanitarian convergence synthesis |
| `/api/cascade-convergence/bluf` | Cascade synthesis |
| `/api/food-price-pulse/bluf` | Food price pulse |
| `/api/notams` · `/flight-cancellations` | Aviation notices and disruption |
| `/scan-iran-protests` | Iran protest intensity and casualty tracking |
| `/health` · `/rate-limit` · `/debug/routes` | Operational |

`?force=true` bypasses the cache and runs a live scan.

> ⚠️ `?force=true` on a cold service can exceed a five-minute client timeout.
> On this backend a forced GPI rebuild fans out to all five theatres. Prefer the
> cached read unless a rebuild is genuinely needed.

---

## 🤝 Cross-backend integration

Three altitudes: sensors below, analyst in the middle, global index above.

```
     ME trackers          Europe BLUF   Asia BLUF   WHA BLUF   Africa BLUF
          │                     │           │          │            │
          ▼                     └───────────┴──────────┴────────────┘
   me_regional_bluf.py                      │
          │                                 ▼
          └──────────────────►  global_pressure_index.py
                                            │
                                 gpi_snapshot.py (daily archive)
                                            │
                                 gpi_delta.py (what changed)

   Canonical registries produced here, proxied by every other backend:
     convergence_registry · commodity_tracker · corridor_dependence · country_ids
```

---

## 📋 Working practices

**Doctrine.** Every module here follows the platform-wide analytical discipline:

- **Convergence, not prediction.** Report the signals that are present. Never
  assert that an outcome is imminent, likely, or dated.
- **`unknown` is a state, never a silence.** A sensor that could not read
  something says so. It does not emit a zero.
- **A real zero is not an unread zero.** "Measured, found nothing" and "nobody
  measured" are different findings and render differently.
- **Absence is reported, not inferred.** A country without a tracker is absent
  from the regional read, not assessed as quiet.
- **Silence can be the signal.** For claiming actors, quiet against their own
  baseline is a tempo change, not calm.
- **Claims are labelled as claims.** Where a reading rests on an interested
  party's unconfirmed assertions, it is reported as claimed, not established.
- **One writer, many readers.** Data has exactly one producer; everything else
  proxies to it.
- **Every layer up gets a narrower lens.** Country pages show everything their
  sensors emit; the regional BLUF gates; the GPI narrows again.

**Engineering.**

- Surgical find/replace edits preferred over full-file rewrites
- AST validation before every deploy is mandatory:
  `python3 -c "import ast; ast.parse(open('FILE.py').read()); print('ok')"`
- Static reference data carries `source`, source URL and a `data_as_of` date —
  date-stamp rather than hardcode, so staleness is visible rather than assumed
- Canary-first testing: a harness must prove it can produce a POSITIVE before any
  negative result from it is believed
- A diagnostic that lies is worse than no diagnostic. A health check that cannot
  fail is not a health check — test the check against a known failure before
  trusting a green light

---

## 🔒 Security & privacy

- **No user data.** No accounts, no registration, no personal data collected or
  stored. The service processes public reporting only.
- **Caching.** Scan results and synthesis caches live in Upstash Redis with
  explicit TTLs, plus an in-process layer. Nothing user-identifying is cached.
- **Secrets.** All credentials belong in Render environment variables. Anything
  that has been committed to this repository should be treated as public and
  rotated.
- **CORS.** Restricted to the site origin and GitHub Pages.

---

## Licence

**© 2025–2026 RCGG. All rights reserved.** Proprietary — see
[`LICENSE`](./LICENSE).

Copying, modifying, redistributing, sublicensing, hosting unauthorised instances
of this API, or commercially exploiting this software in whole or in part
requires prior written permission from the copyright holder.

Donations support running costs. They buy no licence, no warranty, no support
obligation and no influence over what gets built.

---

## 📞 Contact

- **Email:** [asifahanalytics@gmail.com](mailto:asifahanalytics@gmail.com)
- **Instagram:** [@asifahanalytics](https://instagram.com/asifahanalytics)
- ☕ [Buy Me a Coffee](https://buymeacoffee.com/asifahanalytics) — pays for hosting

[asifahanalytics.com](https://asifahanalytics.com) · *Not for operational use*

---

*Last updated: 5 October 2026*
