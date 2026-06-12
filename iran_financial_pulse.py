"""
iran_financial_pulse.py -- Iran Financial Pulse module (ME backend)
v1.0.0 -- June 12, 2026

Powers the Financial Pulse card on the Iran stability page. Canonical
financial_pulse contract (Russia/Nigeria/Mexico pattern):

    financial_pulse: {
        market_status, updated_at,
        tiles: { KEY: { name, ticker, value, change_pct_24h, tier,
                        source, sparkline[], note } },
        capital_flight_convergence: { active, note }   <- Iran-specific
    }

Three tiles:

    TEDPIX -- Tehran Stock Exchange All-Share. NOT on Yahoo; scraped
              from public mirrors (NGX donor pattern: multi-mirror,
              regex patterns, plausibility bounds, graceful
              degradation, own Redis sparkline history).
    USDIRR -- USD/IRR BLACK MARKET rate. Reuses get_exchange_rate()
              from iran_protests.py (live bonbast.com scrape, honest
              static fallback). INVERTED polarity: rising = weaker
              rial. Own Redis sparkline history.
    BRENT  -- BZ=F via Yahoo (query1->query2 + Chrome UA). Iran's
              export benchmark; sanctions-discounted Iranian Light
              prices reference Brent-linked formulas.

THE IRAN-SPECIFIC ANALYTICAL TWIST (capital-flight convergence):
On most pulses, equities UP = confidence. TEDPIX is rial-denominated:
when the rial collapses, Iranians hedge inflation by piling INTO
equities. TEDPIX rising WHILE the rial weakens is therefore consistent
with capital flight, not confidence -- the inverse of every other
pulse on the platform. The module detects this convergence (both 7-day
trends rising) and emits an estimative note. Convergence, not
prediction: we report the pattern; the reader completes the inference.

Caching: Redis-first 12h TTL, lazy refresh on request (no background
thread, no cross-worker lock). ?force=true bypasses. Serve-stale-
honestly when all sources fail.

NOTE ON TEDPIX REACHABILITY: tsetmc/tgju reachability from a US-hosted
Render box under wartime Iranian network conditions is UNVERIFIED.
The module degrades gracefully: last-known Redis value flagged stale,
or tile omitted entirely on first-ever run. /debug shows which mirror
(if any) succeeded -- check it after first deploy.

Endpoints:
    GET /api/iran/financial-pulse            -- cache-first payload
    GET /api/iran/financial-pulse?force=true -- force fresh pull
    GET /api/iran/financial-pulse/debug      -- mirror + cache diagnostics
"""

import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from flask import request, jsonify

VERSION = '1.0.0'
CACHE_KEY = 'pulse:iran:financial'
HIST_KEY_TEDPIX = 'pulse:iran:hist:tedpix'
HIST_KEY_IRR = 'pulse:iran:hist:irr'
CACHE_TTL_HOURS = 12
HIST_MAX_POINTS = 30

# ------------------------------------------------------------
# Redis REST helpers (Upstash) -- both env-name conventions
# ------------------------------------------------------------
REDIS_URL = (os.environ.get('UPSTASH_REDIS_REST_URL')
             or os.environ.get('UPSTASH_REDIS_URL', '')).rstrip('/')
REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_REST_TOKEN')
               or os.environ.get('UPSTASH_REDIS_TOKEN', ''))

_memory_cache = {}


def _redis_get(key):
    if not REDIS_URL or not REDIS_TOKEN:
        return _memory_cache.get(key)
    try:
        r = requests.get(f'{REDIS_URL}/get/{key}',
                         headers={'Authorization': f'Bearer {REDIS_TOKEN}'},
                         timeout=(5, 10))
        if r.status_code == 200:
            raw = r.json().get('result')
            if raw:
                return json.loads(raw)
    except Exception as e:
        print(f'[Iran Pulse] Redis GET failed ({e}); memory fallback')
        return _memory_cache.get(key)
    return None


def _redis_set(key, value):
    _memory_cache[key] = value
    if not REDIS_URL or not REDIS_TOKEN:
        return
    try:
        requests.post(REDIS_URL,
                      headers={'Authorization': f'Bearer {REDIS_TOKEN}'},
                      json=['SET', key, json.dumps(value)],
                      timeout=(5, 10))
    except Exception as e:
        print(f'[Iran Pulse] Redis SET failed ({e}); memory only')


# ------------------------------------------------------------
# Own-history sparklines (NGX donor pattern): scraped sources have
# no historical series, so we accumulate one scan at a time.
# Entries: {'date': 'YYYY-MM-DD', 'value': float}. One per day.
# ------------------------------------------------------------
def _append_history(hist_key, value):
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    hist = _redis_get(hist_key) or []
    if not isinstance(hist, list):
        hist = []
    hist = [h for h in hist if h.get('date') != today]
    hist.append({'date': today, 'value': float(value)})
    hist = sorted(hist, key=lambda h: h['date'])[-HIST_MAX_POINTS:]
    _redis_set(hist_key, hist)
    return hist


def _hist_change_pct(hist, days_back=1):
    """% change between latest point and the point days_back earlier
    (by position, since scans are ~daily). None if not enough data."""
    if not hist or len(hist) < days_back + 1:
        return None
    latest = hist[-1]['value']
    prior = hist[-1 - days_back]['value']
    if not prior:
        return None
    return round((latest - prior) / prior * 100, 2)


# ------------------------------------------------------------
# Tier logic (canonical thresholds)
# ------------------------------------------------------------
def _tier_standard(chg):
    if chg is None:
        return 'stable'
    if chg <= -2:
        return 'stress'
    if chg <= -1:
        return 'warning'
    if chg >= 2:
        return 'rally'
    return 'stable'


def _tier_inverted(chg):
    """USD/IRR: RISING = weaker rial = stress."""
    if chg is None:
        return 'stable'
    if chg >= 2:
        return 'stress'
    if chg >= 1:
        return 'warning'
    if chg <= -2:
        return 'rally'
    return 'stable'


# ------------------------------------------------------------
# TEDPIX scraper (NGX donor pattern: mirrors + patterns + plausibility)
# ------------------------------------------------------------
TEDPIX_MIN_PLAUSIBLE = 1_000_000      # TEDPIX ~2.1M early 2025; wide
TEDPIX_MAX_PLAUSIBLE = 20_000_000     # bounds for wartime volatility
SCRAPE_TIMEOUT = (6, 14)
CHROME_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
             'AppleWebKit/537.36 (KHTML, like Gecko) '
             'Chrome/124.0.0.0 Safari/537.36')

# Each mirror: (name, url, [regex patterns]). Patterns capture the index
# value with Western or grouped digits; Persian digits normalized first.
TEDPIX_MIRRORS = [
    ('tsetmc-index-api',
     'http://old.tsetmc.com/tsev2/data/Index.aspx?i=32097828799138957&t=value',
     [r'(\d{6,9}(?:\.\d+)?)\s*$',          # last bare value in CSV tail
      r',(\d{7,9}(?:\.\d+)?)']),
    ('tgju-tse-profile',
     'https://www.tgju.org/profile/tse_index',
     [r'"p"\s*:\s*"?([\d,]{7,12})"?',
      r'data-price="([\d,]{7,12})"',
      r'class="[^"]*price[^"]*"[^>]*>\s*([\d,]{7,12})']),
    ('shakhesban-tedpix',
     'https://shakhesban.com/markets/index',
     [r'(?:TEDPIX|\u0634\u0627\u062e\u0635 \u06a9\u0644)[^\d]{0,80}([\d,]{7,12})']),
]

_PERSIAN_DIGITS = str.maketrans('\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9'
                                '\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669',
                                '01234567890123456789')


def _scrape_tedpix():
    """Returns {'value', 'source'} or None. Tries each mirror in order."""
    for name, url, patterns in TEDPIX_MIRRORS:
        try:
            r = requests.get(url, headers={'User-Agent': CHROME_UA},
                             timeout=SCRAPE_TIMEOUT)
            if r.status_code != 200 or not r.text:
                continue
            text = r.text.translate(_PERSIAN_DIGITS)
            for pat in patterns:
                m = re.search(pat, text, re.M)
                if not m:
                    continue
                try:
                    val = float(m.group(1).replace(',', ''))
                except ValueError:
                    continue
                if TEDPIX_MIN_PLAUSIBLE <= val <= TEDPIX_MAX_PLAUSIBLE:
                    print(f'[Iran Pulse] TEDPIX {val:,.0f} via {name}')
                    return {'value': val, 'source': name}
        except Exception as e:
            print(f'[Iran Pulse] TEDPIX mirror {name} failed: {e}')
            continue
    return None


# ------------------------------------------------------------
# USD/IRR black market -- reuse iran_protests.get_exchange_rate()
# (live bonbast scrape with honest static fallback, same backend)
# ------------------------------------------------------------
def _fetch_irr():
    try:
        from iran_protests import get_exchange_rate
        ex = get_exchange_rate() or {}
        rate = ex.get('usd_to_irr')
        if rate:
            return {'value': float(rate),
                    'source': ex.get('source', 'bonbast.com')}
    except Exception as e:
        print(f'[Iran Pulse] IRR via iran_protests failed: {e}')
    return None


# ------------------------------------------------------------
# Brent via Yahoo (query1->query2 + Chrome UA; tolerance-fixed
# 24h math per the Mexico v1.0.1 lesson)
# ------------------------------------------------------------
YAHOO_HOSTS = ['https://query1.finance.yahoo.com',
               'https://query2.finance.yahoo.com']


def _fetch_brent():
    for host in YAHOO_HOSTS:
        try:
            url = f'{host}/v8/finance/chart/BZ%3DF?range=1mo&interval=1d'
            r = requests.get(url, headers={'User-Agent': CHROME_UA},
                             timeout=(5, 15))
            if r.status_code != 200:
                continue
            result = (r.json().get('chart') or {}).get('result')
            if not result:
                continue
            res = result[0]
            meta = res.get('meta') or {}
            quote = ((res.get('indicators') or {}).get('quote') or [{}])[0]
            closes = [c for c in (quote.get('close') or []) if c is not None]
            if not closes:
                continue
            price = meta.get('regularMarketPrice')
            if price is None:
                price = closes[-1]
            if len(closes) >= 2:
                # 0.05% relative tolerance (float-noise lesson, Jun 12)
                if abs(price - closes[-1]) <= abs(price) * 0.0005:
                    prev = closes[-2]
                else:
                    prev = closes[-1]
            else:
                prev = price
            chg = round((price - prev) / prev * 100, 2) if prev else 0.0
            return {'value': round(float(price), 2),
                    'change_pct_24h': chg,
                    'sparkline': [round(float(c), 2) for c in closes[-22:]],
                    'source': 'Yahoo Finance (BZ=F)'}
        except Exception as e:
            print(f'[Iran Pulse] Brent {host} failed: {e}')
            continue
    return None


# ------------------------------------------------------------
# Market status -- Tehran Stock Exchange trades the IRANIAN week:
# Saturday-Wednesday, 09:00-12:30 Tehran (UTC+3:30, no DST since 2022).
# ------------------------------------------------------------
def _tse_market_status():
    now_teh = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
    # Python weekday(): Mon=0 ... Sun=6. TSE closed Thu(3) + Fri(4).
    if now_teh.weekday() in (3, 4):
        return 'closed'
    minutes = now_teh.hour * 60 + now_teh.minute
    if 9 * 60 <= minutes < 12 * 60 + 30:
        return 'open'
    return 'closed'


# ------------------------------------------------------------
# Pulse builder
# ------------------------------------------------------------
def _build_financial_pulse():
    tiles = {}
    tedpix_hist = None
    irr_hist = None

    # -- TEDPIX (scraped, own history) --
    ted = _scrape_tedpix()
    if ted:
        tedpix_hist = _append_history(HIST_KEY_TEDPIX, ted['value'])
    else:
        tedpix_hist = _redis_get(HIST_KEY_TEDPIX) or []
    if tedpix_hist:
        ted_val = tedpix_hist[-1]['value']
        ted_chg = _hist_change_pct(tedpix_hist, 1)
        tiles['TEDPIX'] = {
            'name': 'TEDPIX',
            'ticker': 'TSE All-Share',
            'value': ted_val,
            'change_pct_24h': ted_chg,
            'tier': _tier_standard(ted_chg),
            'source': (ted or {}).get('source', 'last-known (mirrors unreachable)'),
            'sparkline': [h['value'] for h in tedpix_hist],
            'note': 'Rial-denominated inflation hedge -- rising TEDPIX + '
                    'falling rial = capital-flight pattern, NOT confidence',
            'stale': ted is None,
        }

    # -- USD/IRR black market (own history) --
    irr = _fetch_irr()
    if irr:
        irr_hist = _append_history(HIST_KEY_IRR, irr['value'])
    else:
        irr_hist = _redis_get(HIST_KEY_IRR) or []
    if irr_hist:
        irr_val = irr_hist[-1]['value']
        irr_chg = _hist_change_pct(irr_hist, 1)
        tiles['USDIRR'] = {
            'name': 'USD/IRR (Black Market)',
            'ticker': 'IRR street rate',
            'value': irr_val,
            'change_pct_24h': irr_chg,
            'tier': _tier_inverted(irr_chg),
            'source': (irr or {}).get('source', 'last-known (bonbast unreachable)'),
            'sparkline': [h['value'] for h in irr_hist],
            'note': 'INVERTED polarity: rising = weaker rial. Black-market '
                    'rate, not the fictional official rate',
            'stale': irr is None,
        }

    # -- Brent --
    brent = _fetch_brent()
    if brent:
        tiles['BRENT'] = {
            'name': 'Brent Crude',
            'ticker': 'BZ=F',
            'value': brent['value'],
            'change_pct_24h': brent['change_pct_24h'],
            'tier': _tier_standard(brent['change_pct_24h']),
            'source': brent['source'],
            'sparkline': brent['sparkline'],
            'note': 'Iran export benchmark -- Iranian Light prices off '
                    'Brent-linked formulas at sanctions discounts',
        }

    if not tiles:
        return None

    # -- Capital-flight convergence (Iran-specific analytical layer) --
    ted_7d = _hist_change_pct(tedpix_hist or [], 7)
    irr_7d = _hist_change_pct(irr_hist or [], 7)
    convergence_active = (ted_7d is not None and irr_7d is not None
                          and ted_7d > 3.0 and irr_7d > 3.0)
    convergence = {
        'active': convergence_active,
        'tedpix_7d_pct': ted_7d,
        'irr_7d_pct': irr_7d,
        'note': ('TEDPIX rising alongside rial depreciation is consistent '
                 'with capital-flight hedging into equities rather than '
                 'market confidence -- the inflation-hedge pattern that has '
                 'historically accompanied Iranian currency crises.')
                if convergence_active else
                ('No capital-flight convergence detected this cycle '
                 '(requires both TEDPIX and USD/IRR 7-day trends rising). '
                 'History accumulates one point per scan -- the 7-day read '
                 'needs roughly a week of scans to come online.'),
    }

    return {
        'market_status': _tse_market_status(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'tiles': tiles,
        'capital_flight_convergence': convergence,
    }


def _is_fresh(payload):
    try:
        ts = payload.get('financial_pulse', {}).get('updated_at', '')
        then = datetime.fromisoformat(ts)
        return (datetime.now(timezone.utc) - then).total_seconds() / 3600 < CACHE_TTL_HOURS
    except Exception:
        return False


# ------------------------------------------------------------
# Flask endpoint registration
# ------------------------------------------------------------
def register_iran_financial_pulse_endpoints(app):

    @app.route('/api/iran/financial-pulse', methods=['GET', 'OPTIONS'])
    def api_iran_financial_pulse():
        if request.method == 'OPTIONS':
            return '', 200
        force = request.args.get('force', 'false').lower() == 'true'
        if not force:
            cached = _redis_get(CACHE_KEY)
            if cached and _is_fresh(cached):
                cached['cached'] = True
                return jsonify(cached)
        pulse = _build_financial_pulse()
        if pulse:
            payload = {'success': True, 'country': 'iran',
                       'financial_pulse': pulse,
                       'last_updated': pulse['updated_at'],
                       'cached': False, 'version': VERSION}
            _redis_set(CACHE_KEY, payload)
            return jsonify(payload)
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            cached['stale'] = True
            return jsonify(cached)
        return jsonify({'success': False, 'country': 'iran',
                        'error': 'Financial pulse unavailable (all sources '
                                 'unreachable, no cache)',
                        'version': VERSION}), 503

    @app.route('/api/iran/financial-pulse/debug', methods=['GET'])
    def api_iran_financial_pulse_debug():
        cached = _redis_get(CACHE_KEY)
        ted_hist = _redis_get(HIST_KEY_TEDPIX) or []
        irr_hist = _redis_get(HIST_KEY_IRR) or []
        return jsonify({
            'module': 'iran_financial_pulse',
            'version': VERSION,
            'redis_configured': bool(REDIS_URL and REDIS_TOKEN),
            'cache_present': bool(cached),
            'cache_fresh': _is_fresh(cached) if cached else False,
            'tiles_cached': list(((cached or {}).get('financial_pulse')
                                  or {}).get('tiles', {}).keys()),
            'tedpix_history_points': len(ted_hist),
            'irr_history_points': len(irr_hist),
            'tedpix_mirrors': [m[0] for m in TEDPIX_MIRRORS],
            'tse_market_status_now': _tse_market_status(),
        })

    print(f'[Iran Pulse] Endpoints registered (v{VERSION})')
