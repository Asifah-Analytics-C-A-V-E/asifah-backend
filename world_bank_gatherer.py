"""
world_bank_gatherer.py
Asifah Analytics -- ME Backend Module
v1.0.0 -- June 22, 2026

WORLD BANK STRUCTURAL-STRESS GATHERER

Purpose:
  A discovery layer. Sweeps World Bank Indicators API (free, keyless, REST)
  across ALL countries every ~24h to surface STRUCTURAL stress -- the slow,
  accumulating pressure (inflation, water stress, food-import dependence,
  thin reserves, unemployment, poverty, food insecurity) that historically
  precedes acute crises but that no single article or country page captures.

  This is the "what are we NOT watching yet" engine. It ranks countries by
  compound structural stress so the analyst can refocus the roadmap on whoever
  is quietly bubbling up.

Doctrine placement:
  SENSOR layer. This module reports raw structural readings with sourcing and
  data_as_of years -- it does NOT interpret. The estimative read ("consistent
  with accumulating subsistence-cost pressure") belongs to the analyst layer
  (humanitarian_convergence_detector.py), which consumes this module's Redis
  payload the same way it consumes UNHCR structured displacement deltas.

  Absence stays honest: indicators that return no data for a country are simply
  absent from that country's profile -- never zero-filled, never guessed.

Canonical writer/reader pattern:
  - This module (the WRITER) pulls indicators and writes a per-country
    structural profile to Redis.
  - humanitarian_convergence_detector.py (the READER, future wiring) reads
    worldbank:structural:latest and emits canonical structural_stress signals
    into the humanitarian convergence BLUF -> GPI.

DATA SOURCE:
  World Bank Indicators API v2 -- https://api.worldbank.org/v2
  Free, no API key, no auth, no rate limits, CC BY 4.0 (attribution required).
  Cadence: most indicators are ANNUAL. We pull most-recent-values (mrv=5) per
  indicator and compute latest value + change vs the prior available year.

REDIS KEYS:
  worldbank:structural:latest    -- canonical per-country structural profile (50h TTL)
  worldbank:gatherer:lastrun     -- last run timestamp + diagnostics

ENDPOINTS:
  GET /api/worldbank-gatherer/scan?force=true   Trigger fresh pull; returns ranked stress
  GET /api/worldbank-gatherer/health            Health + last run + country/indicator counts

SCHEDULE:
  Auto-runs every 24h via daemon thread (matches gatherer pattern). WB data is
  annual, so this is deliberately low-frequency. The pull is light: one API
  call per indicator (country/all), so a refresh is a handful of calls.

Author: RCGG / Asifah Analytics
"""

import os
import json
import time
import threading
import traceback
from datetime import datetime, timezone

import requests

# ============================================================
# CONFIG
# ============================================================
WB_API_BASE = "https://api.worldbank.org/v2"
WB_MRV = 5                      # most-recent 5 values per indicator (latest + history for delta)
WB_PER_PAGE = 20000            # one page covers all countries x 5 years
WB_TIMEOUT = 20                # WB can be slow on big all-country pulls

REFRESH_HOURS = 24
BOOT_DELAY_SECONDS = 90
STRUCTURAL_CACHE_KEY = "worldbank:structural:latest"
LASTRUN_KEY = "worldbank:gatherer:lastrun"
CACHE_TTL = 50 * 3600          # survive a missed 24h run

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

# ============================================================
# STRUCTURAL-STRESS INDICATORS
# ============================================================
# stress_when 'above' -> high value is stress; 'below' -> low value is stress.
# Thresholds are deliberately conservative so only genuinely elevated readings
# count as stress. All tunable in one place.
INDICATORS = {
    'inflation': {
        'code': 'FP.CPI.TOTL.ZG',  'label': 'Consumer inflation',
        'unit': '%',     'threshold': 15.0,  'extreme': 50.0,  'stress_when': 'above',
        'source': 'World Bank / IMF IFS',
    },
    'food_insecurity': {
        'code': 'SN.ITK.MSFI.ZS',  'label': 'Food insecurity (moderate+severe)',
        'unit': '% pop', 'threshold': 40.0,  'extreme': 65.0,  'stress_when': 'above',
        'source': 'World Bank / FAO (SOFI)',
    },
    'water_stress': {
        'code': 'ER.H2O.FWST.ZS',  'label': 'Water stress (withdrawal / available)',
        'unit': '%',     'threshold': 70.0,  'extreme': 100.0, 'stress_when': 'above',
        'source': 'World Bank / FAO AQUASTAT (SDG 6.4.2)',
    },
    'reserves_months': {
        'code': 'FI.RES.TOTL.MO',  'label': 'Reserves (months of imports)',
        'unit': 'months', 'threshold': 3.0,  'extreme': 1.0,   'stress_when': 'below',
        'source': 'World Bank / IMF',
    },
    'food_import_dependence': {
        'code': 'TM.VAL.FOOD.ZS.UN', 'label': 'Food imports (% of merchandise imports)',
        'unit': '%',     'threshold': 20.0,  'extreme': 35.0,  'stress_when': 'above',
        'source': 'World Bank / UN Comtrade',
    },
    'unemployment': {
        'code': 'SL.UEM.TOTL.ZS',  'label': 'Unemployment (% labor force, ILO)',
        'unit': '%',     'threshold': 15.0,  'extreme': 25.0,  'stress_when': 'above',
        'source': 'World Bank / ILO (modeled)',
    },
    'poverty': {
        'code': 'SI.POV.DDAY',     'label': 'Poverty headcount ($2.15/day)',
        'unit': '% pop', 'threshold': 30.0,  'extreme': 50.0,  'stress_when': 'above',
        'source': 'World Bank PIP',
    },
}

# ============================================================
# REDIS HELPERS (canonical Upstash REST pattern)
# ============================================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        if not resp.ok:
            return None
        raw = resp.json().get('result')
        if raw is None:
            return None
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return raw
    except Exception as e:
        print(f"[worldbank_gatherer] Redis GET error ({key}): {str(e)[:80]}")
        return None


def _redis_set(key, value, ttl=CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str) if not isinstance(value, str) else value
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/set/{key}",
            headers={
                "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                "Content-Type":  "application/json",
            },
            data=payload,
            params={"EX": ttl} if ttl else {},
            timeout=8,
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f"[worldbank_gatherer] Redis SET error ({key}): {str(e)[:80]}")
        return False


# ============================================================
# WORLD BANK FETCH
# ============================================================
def _fetch_country_meta():
    """
    Return {iso3: {name, iso2, region, income, capital}} for real countries only
    (World Bank aggregates such as 'World' or 'Arab World' are filtered out).
    Returns {} on failure -- caller degrades gracefully.
    """
    try:
        url = f"{WB_API_BASE}/country?format=json&per_page=400"
        resp = requests.get(url, timeout=WB_TIMEOUT)
        if not resp.ok:
            return {}
        body = resp.json()
        if not isinstance(body, list) or len(body) < 2 or not isinstance(body[1], list):
            return {}
        out = {}
        for c in body[1]:
            region = (c.get('region') or {})
            # Aggregates carry region.value == 'Aggregates'; skip them.
            if (region.get('value') or '').strip().lower() == 'aggregates':
                continue
            iso3 = c.get('id')
            if not iso3:
                continue
            out[iso3] = {
                'name':    c.get('name', iso3),
                'iso2':    c.get('iso2Code', ''),
                'region':  region.get('value', ''),
                'income':  (c.get('incomeLevel') or {}).get('value', ''),
                'capital': c.get('capitalCity', ''),
            }
        return out
    except Exception as e:
        print(f"[worldbank_gatherer] country meta fetch failed: {str(e)[:100]}")
        return {}


def _fetch_indicator(code):
    """
    Pull one indicator for all countries, most-recent 5 values.
    Returns {iso3: [(year:int, value:float), ...]} ordered most-recent-first,
    nulls dropped. Returns {} on failure (absence stays honest).
    """
    try:
        url = (f"{WB_API_BASE}/country/all/indicator/{code}"
               f"?format=json&per_page={WB_PER_PAGE}&mrv={WB_MRV}")
        resp = requests.get(url, timeout=WB_TIMEOUT)
        if not resp.ok:
            print(f"[worldbank_gatherer] {code}: HTTP {resp.status_code}")
            return {}
        body = resp.json()
        if not isinstance(body, list) or len(body) < 2 or not isinstance(body[1], list):
            print(f"[worldbank_gatherer] {code}: unexpected payload shape")
            return {}
        series = {}
        for row in body[1]:
            iso3 = row.get('countryiso3code') or ''
            val = row.get('value')
            date = row.get('date')
            if not iso3 or val is None or date is None:
                continue
            try:
                year = int(date)
                fval = float(val)
            except (ValueError, TypeError):
                continue
            series.setdefault(iso3, []).append((year, fval))
        # ensure most-recent-first
        for iso3 in series:
            series[iso3].sort(key=lambda t: t[0], reverse=True)
        return series
    except Exception as e:
        print(f"[worldbank_gatherer] {code} fetch failed: {str(e)[:100]}")
        return {}


# ============================================================
# STRESS ASSESSMENT
# ============================================================
def _assess_indicator(meta, points):
    """
    Given an indicator's config + a country's [(year, value), ...] (recent-first),
    return a reading dict, or None if no data.
    """
    if not points:
        return None
    latest_year, latest_val = points[0]
    prev_year, prev_val = (points[1] if len(points) > 1 else (None, None))

    delta = None
    pct_change = None
    if prev_val is not None and prev_val != 0:
        delta = round(latest_val - prev_val, 2)
        pct_change = round((latest_val - prev_val) / abs(prev_val) * 100.0, 1)
    elif prev_val is not None:
        delta = round(latest_val - prev_val, 2)

    thr = meta['threshold']
    if meta['stress_when'] == 'above':
        in_stress = latest_val >= thr
        is_extreme = latest_val >= meta['extreme']
        deteriorating = (delta is not None and delta > 0)
    else:  # 'below'
        in_stress = latest_val <= thr
        is_extreme = latest_val <= meta['extreme']
        deteriorating = (delta is not None and delta < 0)

    return {
        'code':          meta['code'],
        'label':         meta['label'],
        'unit':          meta['unit'],
        'value':         round(latest_val, 2),
        'year':          str(latest_year),
        'prev_value':    (round(prev_val, 2) if prev_val is not None else None),
        'prev_year':     (str(prev_year) if prev_year is not None else None),
        'delta':         delta,
        'pct_change':    pct_change,
        'threshold':     thr,
        'stress_when':   meta['stress_when'],
        'in_stress':     bool(in_stress),
        'is_extreme':    bool(is_extreme),
        'deteriorating': bool(deteriorating),
        'source':        meta['source'],
    }


def _stress_severity(stress_count, extreme_count):
    """Map compound-stress counts to a 0-3 severity for downstream ranking."""
    if extreme_count >= 2 or stress_count >= 4:
        return 3
    if extreme_count >= 1 or stress_count >= 3:
        return 3 if extreme_count >= 1 else 2
    if stress_count == 2:
        return 2
    if stress_count == 1:
        return 1
    return 0


# ============================================================
# MAIN SCAN
# ============================================================
def run_worldbank_scan():
    """
    Pull all indicators for all countries, build per-country structural profiles,
    write to Redis. Returns the payload dict.
    """
    started = time.time()
    countries = _fetch_country_meta()

    # Pull each indicator (one all-country call each).
    raw = {}
    pulled, failed = [], []
    for key, meta in INDICATORS.items():
        series = _fetch_indicator(meta['code'])
        if series:
            raw[key] = series
            pulled.append(meta['code'])
        else:
            failed.append(meta['code'])
        time.sleep(0.3)  # gentle pacing

    # Build per-country profiles.
    by_country = {}
    iso_set = set()
    for ind_series in raw.values():
        iso_set.update(ind_series.keys())

    for iso3 in iso_set:
        cmeta = countries.get(iso3)
        if cmeta is None:
            continue  # aggregate or unknown code -- skip (absence stays honest)

        readings = {}
        stressed, deteriorating, extreme = [], [], []
        for key, meta in INDICATORS.items():
            pts = raw.get(key, {}).get(iso3)
            r = _assess_indicator(meta, pts) if pts else None
            if r is None:
                continue
            readings[key] = r
            if r['in_stress']:
                stressed.append(key)
            if r['deteriorating']:
                deteriorating.append(key)
            if r['is_extreme']:
                extreme.append(key)

        if not readings:
            continue

        severity = _stress_severity(len(stressed), len(extreme))
        by_country[iso3] = {
            'country_name':    cmeta['name'],
            'iso2':            cmeta['iso2'],
            'region':          cmeta['region'],
            'income':          cmeta['income'],
            'indicators':      readings,
            'stressed':        stressed,
            'deteriorating':   deteriorating,
            'extreme':         extreme,
            'stress_count':    len(stressed),
            'stress_severity': severity,
        }

    payload = {
        'version':          '1.0.0',
        'generated_at':     datetime.now(timezone.utc).isoformat(),
        'source':           'World Bank Indicators API v2 (CC BY 4.0)',
        'source_url':       'https://api.worldbank.org/v2',
        'indicators_pulled': pulled,
        'indicators_failed': failed,
        'country_count':    len(by_country),
        'scan_seconds':     round(time.time() - started, 1),
        'by_country':       by_country,
    }

    _redis_set(STRUCTURAL_CACHE_KEY, payload, CACHE_TTL)
    _redis_set(LASTRUN_KEY, {
        'ran_at':            payload['generated_at'],
        'country_count':     payload['country_count'],
        'indicators_pulled': pulled,
        'indicators_failed': failed,
        'scan_seconds':      payload['scan_seconds'],
    }, CACHE_TTL)
    return payload


def _rank_bubbling_up(payload, limit=25):
    """
    Factual ranking (sensor-layer) of the most structurally stressed countries.
    No estimative interpretation here -- that is the analyst layer's job.
    """
    rows = []
    for iso3, c in (payload.get('by_country') or {}).items():
        if c.get('stress_count', 0) <= 0:
            continue
        bits = []
        for key in c.get('stressed', []):
            r = c['indicators'].get(key, {})
            trend = ''
            if r.get('deteriorating'):
                trend = ' rising' if r.get('stress_when') == 'above' else ' falling'
            ext = ' [EXTREME]' if r.get('is_extreme') else ''
            bits.append(f"{r.get('label')}: {r.get('value')}{r.get('unit','')}"
                        f" ({r.get('year')}{trend}){ext}")
        rows.append({
            'iso3':            iso3,
            'country':         c.get('country_name', iso3),
            'region':          c.get('region', ''),
            'stress_count':    c.get('stress_count', 0),
            'stress_severity': c.get('stress_severity', 0),
            'extreme_count':   len(c.get('extreme', [])),
            'readout':         '; '.join(bits),
        })
    rows.sort(key=lambda r: (r['stress_severity'], r['stress_count'], r['extreme_count']),
              reverse=True)
    return rows[:limit]


# ============================================================
# SCHEDULER
# ============================================================
def _scheduler_loop():
    time.sleep(BOOT_DELAY_SECONDS)
    while True:
        try:
            print("[worldbank_gatherer] scheduled scan starting...")
            p = run_worldbank_scan()
            print(f"[worldbank_gatherer] scan complete: {p['country_count']} countries, "
                  f"{len(p['indicators_pulled'])} indicators ({p['scan_seconds']}s)")
            time.sleep(REFRESH_HOURS * 3600)
        except Exception as e:
            print(f"[worldbank_gatherer] scheduler error: {str(e)[:120]}")
            traceback.print_exc()
            time.sleep(600)  # back off 10min on unhandled exception


def _start_scheduler():
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name='WorldBankGatherer')
    thread.start()
    return thread


# ============================================================
# FLASK ROUTE REGISTRATION
# ============================================================
def register_worldbank_gatherer_routes(app, start_scheduler=True):
    """Canonical Asifah pattern: register endpoints + (optionally) start the daemon."""
    from flask import jsonify, request

    @app.route('/api/worldbank-gatherer/scan', methods=['GET', 'POST'])
    def worldbank_gatherer_scan():
        force = (request.args.get('force', '').lower() == 'true'
                 or request.args.get('refresh', '').lower() == 'true')
        try:
            payload = _redis_get(STRUCTURAL_CACHE_KEY)
            if force or not isinstance(payload, dict):
                payload = run_worldbank_scan()
            limit = request.args.get('limit', '25')
            try:
                limit = max(1, min(200, int(limit)))
            except (ValueError, TypeError):
                limit = 25
            return jsonify({
                'success':           True,
                'generated_at':      payload.get('generated_at'),
                'country_count':     payload.get('country_count'),
                'indicators_pulled': payload.get('indicators_pulled'),
                'indicators_failed': payload.get('indicators_failed'),
                'scan_seconds':      payload.get('scan_seconds'),
                'bubbling_up':       _rank_bubbling_up(payload, limit),
                'note': ('Sensor-layer structural readings. Estimative interpretation '
                         'is applied by the humanitarian convergence layer.'),
            }), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/worldbank-gatherer/health', methods=['GET'])
    def worldbank_gatherer_health():
        last = _redis_get(LASTRUN_KEY)
        return jsonify({
            'module':       'world_bank_gatherer',
            'version':      '1.0.0',
            'redis':        bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'indicators':   [m['code'] for m in INDICATORS.values()],
            'last_run':     last if isinstance(last, dict) else None,
            'refresh_hours': REFRESH_HOURS,
        }), 200

    if start_scheduler:
        _start_scheduler()

    print("[worldbank_gatherer] routes registered "
          "(/api/worldbank-gatherer/scan, /health)")
