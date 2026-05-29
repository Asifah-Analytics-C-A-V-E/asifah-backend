"""
Israel Stability Backend v1.0.0
Standalone microservice for Israel Stability Index

Deployed on: asifah-backend (Render) — same service as app.py
Redis: Same Upstash instance as ME/Europe backends (key: israel_cache)

MODULES:
- Economic indicators: NIS/USD (Yahoo Finance + fallback), TASE TA-35 index
- Conflict scanning: Google News RSS (ToI, Haaretz, JPost, Ynet, JPost)
- Strike/incident tracker: ACLED API (with RSS fallback when key unavailable)
- Knesset/coalition politics scanner
- Leadership status badges: Netanyahu, Bennett, Gallant, Smotrich, Ben Gvir
- Stability score: Active-war calibrated (not chronic-collapse like Lebanon)

SCORING MODEL (active war baseline):
  base = 50
  + economic_health (NIS stability, TASE performance)     max +10
  - war_intensity (conflict scan score)                   max -25
  - coalition_fragility                                   max -15
  - regional_threat_level (Iran, Hezbollah, Houthi)       max -15
  + hostage_deal_bonus (if active deal/ceasefire)         max +8
  - humanitarian_pressure (ICJ/ICC/intl isolation)        max -5
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import json

# curl_cffi: TLS/JA3 fingerprint impersonation for RSS feeds blocked by Cloudflare
# at the network layer. v1.5.0 (May 29 2026 — cascaded from us_stability.py).
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    curl_requests = None
    CURL_CFFI_AVAILABLE = False
    print("[Israel Stability] WARNING: curl_cffi not installed — TLS impersonation unavailable")
import os
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

try:
    from telegram_signals import fetch_telegram_signals
    TELEGRAM_AVAILABLE = True
    print("[Israel] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Israel] ⚠️ Telegram signals not available")
# ========================================
# CONFIGURATION
# ========================================

UPSTASH_URL   = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')
ACLED_API_KEY = os.environ.get('ACLED_API_KEY')       # Optional — falls back to RSS
ACLED_EMAIL   = os.environ.get('ACLED_EMAIL')          # Required with ACLED key
TASE_API_KEY  = os.environ.get('TASE_API_KEY')         # TASE Data Hub — indices online
REDIS_CACHE_KEY = 'israel_cache'
CACHE_TTL_SECONDS = 4 * 60 * 60  # 4 hours

# Political figures — status is semi-static, updated via news scan heuristics
POLITICAL_FIGURES = {
    'netanyahu': {
        'name': 'Benjamin Netanyahu',
        'title': 'Prime Minister',
        'party': 'Likud',
        'flag': '🇮🇱',
        'icon': '🏛️',
        'status': 'ACTIVE',
        'status_color': '#4ade80',
        'note': 'On trial (bribery/fraud); coalition dependent on far-right'
    },
    'bennett': {
        'name': 'Naftali Bennett',
        'title': 'Former PM / Opposition',
        'party': 'New Right (ind.)',
        'flag': '🇮🇱',
        'icon': '🌟',
        'status': 'WATCHING',
        'status_color': '#facc15',
        'note': 'Dark horse PM candidate; vocal critic of war management'
    },
    'gallant': {
        'name': 'Yoav Gallant',
        'title': 'Former Defense Minister',
        'party': 'Likud (dismissed Nov 2024)',
        'flag': '🇮🇱',
        'icon': '⚔️',
        'status': 'DISMISSED',
        'status_color': '#fb923c',
        'note': 'Dismissed Nov 2024 over hostage/ceasefire disagreements'
    },
    'smotrich': {
        'name': 'Bezalel Smotrich',
        'title': 'Finance Minister',
        'party': 'Religious Zionism',
        'flag': '🇮🇱',
        'icon': '💰',
        'status': 'ACTIVE',
        'status_color': '#4ade80',
        'note': 'Controls settlement policy; key coalition veto player'
    },
    'ben_gvir': {
        'name': 'Itamar Ben Gvir',
        'title': 'National Security Minister',
        'party': 'Otzma Yehudit',
        'flag': '🇮🇱',
        'icon': '🔥',
        'status': 'ACTIVE',
        'status_color': '#f87171',
        'note': 'Far-right; repeatedly threatened to collapse govt over Gaza deal'
    }
}

# ========================================
# REDIS HELPERS (same pattern as Lebanon)
# ========================================

def _redis_available():
    return bool(UPSTASH_URL and UPSTASH_TOKEN)

def _redis_get(key):
    try:
        response = requests.get(
            f"{UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            timeout=5
        )
        data = response.json()
        if data.get('result'):
            return json.loads(data['result'])
        return None
    except Exception as e:
        print(f"[Redis] GET error: {str(e)[:100]}")
        return None

def _redis_set(key, value, ex=None):
    try:
        cmd = ["SET", key, json.dumps(value)]
        if ex:
            cmd += ["EX", ex]
        response = requests.post(
            f"{UPSTASH_URL}",
            headers={
                "Authorization": f"Bearer {UPSTASH_TOKEN}",
                "Content-Type": "application/json"
            },
            json=cmd,
            timeout=5
        )
        result = response.json()
        if result.get('result') == 'OK':
            print(f"[Redis] ✅ Saved key: {key}")
            return True
        return False
    except Exception as e:
        print(f"[Redis] SET error: {str(e)[:100]}")
        return False

def load_israel_cache():
    if _redis_available():
        data = _redis_get(REDIS_CACHE_KEY)
        if data:
            print(f"[Cache] ✅ Loaded israel_cache from Redis")
            return data
    return {
        'last_updated': None,
        'history': {},
        'metadata': {'storage': 'tmp_fallback'}
    }

def save_israel_cache(cache_data):
    cache_data['last_updated'] = datetime.now(timezone.utc).isoformat()
    if _redis_available():
        _redis_set(REDIS_CACHE_KEY, cache_data, ex=CACHE_TTL_SECONDS)
        return
    # /tmp fallback (ephemeral on Render — warns)
    print("[Cache] ⚠️ Redis not available — data will not persist across deploys")

def update_israel_history(snapshot: dict):
    """Append today's snapshot to rolling 90-day history."""
    try:
        cache = load_israel_cache()
        today = datetime.now(timezone.utc).date().isoformat()
        cache['history'][today] = snapshot
        # Keep 90 days max
        if len(cache['history']) > 90:
            for old in sorted(cache['history'].keys())[:-90]:
                del cache['history'][old]
        save_israel_cache(cache)
        print(f"[Cache] ✅ History updated for {today} ({len(cache['history'])} days)")
    except Exception as e:
        print(f"[Cache] History update error: {str(e)}")

# ========================================
# ECONOMIC INDICATORS
# ========================================

def fetch_nis_usd():
    """
    Fetch NIS/USD exchange rate.
    Primary: Yahoo Finance (ILS=X)
    Fallback: exchangerate-api open endpoint
    """
    print("[Israel Econ] Fetching NIS/USD...")
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/ILS=X?interval=1d&range=5d"
        r = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if r.status_code == 200:
            data = r.json()
            result = data.get('chart', {}).get('result', [{}])[0]
            meta = result.get('meta', {})
            price = meta.get('regularMarketPrice')
            prev  = meta.get('previousClose') or meta.get('chartPreviousClose')
            if price and price > 0:
                change_pct = ((price - prev) / prev * 100) if prev else 0
                trend = 'weakening' if change_pct > 0.1 else ('strengthening' if change_pct < -0.1 else 'stable')

                # v2.1.0 — Extract 5-day sparkline series from same response
                # (was previously discarded — Yahoo returns it for free with ?range=5d)
                sparkline = []
                try:
                    timestamps = result.get('timestamp') or []
                    closes = (result.get('indicators', {}) or {}).get('quote', [{}])[0].get('close') or []
                    for ts, close in zip(timestamps, closes):
                        if close is not None:
                            sparkline.append({
                                'time':  datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                                'value': round(float(close), 4),
                            })
                    print(f"[Israel Econ] ✅ NIS sparkline: {len(sparkline)} datapoints")
                except Exception as e:
                    print(f"[Israel Econ] NIS sparkline parse error: {str(e)[:80]}")

                print(f"[Israel Econ] ✅ NIS/USD: {price:.4f} ({change_pct:+.2f}%)")
                return {
                    'usd_to_ils': round(price, 4),
                    'change_pct_24h': round(change_pct, 3),
                    'trend': trend,
                    'source': 'Yahoo Finance',
                    'sparkline': sparkline,        # v2.1.0
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
    except Exception as e:
        print(f"[Israel Econ] Yahoo Finance NIS error: {str(e)[:80]}")

    # Fallback
    try:
        r = requests.get("https://open.exchangerate-api.com/v6/latest/USD", timeout=10)
        if r.status_code == 200:
            rate = r.json().get('rates', {}).get('ILS')
            if rate:
                print(f"[Israel Econ] ✅ NIS/USD fallback: {rate:.4f}")
                return {
                    'usd_to_ils': round(rate, 4),
                    'change_pct_24h': 0,
                    'trend': 'stable',
                    'source': 'ExchangeRate-API',
                    'sparkline': [],   # v2.1.0 — fallback has no historical series
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
    except Exception as e:
        print(f"[Israel Econ] Fallback NIS error: {str(e)[:80]}")

    print("[Israel Econ] Using NIS estimate")
    return {
        'usd_to_ils': 3.70,
        'change_pct_24h': 0,
        'trend': 'stable',
        'source': 'Estimated',
        'estimated': True,
        'sparkline': [],   # v2.1.0
        'timestamp': datetime.now(timezone.utc).isoformat()
    }


def fetch_tase_index():
    """
    Fetch Tel Aviv Stock Exchange TA-35 index.
    Primary:  TASE Data Hub API (datawise.tase.co.il) — last-rate + intraday
    Fallback: Yahoo Finance (^TA35 / ^TA125)
    """
    print("[Israel Econ] Fetching TASE TA-35...")

    # ── Check if TASE is open (Sun–Thu, Israel time) ──
    israel_tz = timezone(timedelta(hours=3))  # IST = UTC+3
    now_israel = datetime.now(israel_tz)
    tase_closed = now_israel.weekday() in (4, 5)  # 4=Friday, 5=Saturday
    if tase_closed:
        print(f"[Israel Econ] TASE closed (weekday={now_israel.weekday()}) — skipping to Yahoo fallback")

    # ── Primary: TASE official API (only when market may be open) ──
    if TASE_API_KEY and not tase_closed:
        try:
            headers = {
                "accept": "application/json",
                "accept-language": "en-US",
                "apikey": TASE_API_KEY
            }
            # Last rate — current index value
            r = requests.get(
                "https://datawise.tase.co.il/v1/tase-indices-online-data/last-rate",
                params={"indexId": 22},
                headers=headers,
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                # Response is a list; find indexId=22
                entries = data if isinstance(data, list) else data.get('result', [data])
                entry = next((e for e in entries if str(e.get('indexId', '')) == '22'), entries[0] if entries else {})
                value = entry.get('lastIndexRate') or entry.get('indexRate') or entry.get('rate')
                change = entry.get('change') or entry.get('changeRate') or 0
                if value:
                    value = float(str(value).replace(',', ''))
                    change_pct = float(str(change).replace(',', '')) if change else 0
                    print(f"[Israel Econ] ✅ TASE API TA-35: {value:,.2f} ({change_pct:+.2f}%)")

                    # ── Intraday sparkline ──
                    sparkline = []
                    try:
                        open_time = "09:40:00"
                        r2 = requests.get(
                            "https://datawise.tase.co.il/v1/tase-indices-online-data/intraday",
                            params={"indexId": 22, "startTime": open_time},
                            headers=headers,
                            timeout=10
                        )
                        if r2.status_code == 200:
                            intraday_data = r2.json()
                            entries2 = intraday_data if isinstance(intraday_data, list) else intraday_data.get('result', [])
                            sparkline = [
                                {
                                    'time': e.get('lastSaleTime', ''),
                                    'value': float(str(e.get('lastIndexRate', 0)).replace(',', ''))
                                }
                                for e in entries2
                                if e.get('lastIndexRate')
                            ]
                            print(f"[Israel Econ] ✅ Intraday: {len(sparkline)} datapoints")
                    except Exception as e2:
                        print(f"[Israel Econ] Intraday error: {str(e2)[:80]}")

                    return {
                        'index': 'TA35',
                        'value': round(value, 2),
                        'change_pct_24h': round(change_pct, 3),
                        'trend': 'rising' if change_pct > 0.3 else ('falling' if change_pct < -0.3 else 'flat'),
                        'source': 'TASE Data Hub',
                        'sparkline': sparkline,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
            print(f"[Israel Econ] TASE API returned {r.status_code} — falling back to Yahoo")
        except Exception as e:
            print(f"[Israel Econ] TASE API error: {str(e)[:80]}")

   # ── Yahoo Finance fallback ──
    TASE_LAST_KNOWN_KEY = 'tase_last_known'
    print("[Israel Econ] Using Yahoo Finance fallback for TASE...")
    for ticker in ['^TA35', '^TA125', 'TA35.TA', 'TA125.TA']:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
            r = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            if r.status_code == 200:
                data = r.json()
                result = data.get('chart', {}).get('result', [{}])[0]
                meta   = result.get('meta', {})
                price  = meta.get('regularMarketPrice')
                prev   = meta.get('previousClose') or meta.get('chartPreviousClose')
                if price and price > 0:
                    change_pct = ((price - prev) / prev * 100) if prev else 0
                    print(f"[Israel Econ] ✅ Yahoo {ticker}: {price:,.2f} ({change_pct:+.2f}%)")
                    # Cache this good value for use when market is closed
                    try:
                        if _redis_available():
                            _redis_set(TASE_LAST_KNOWN_KEY, json.dumps({'value': round(price, 2), 'change_pct_24h': round(change_pct, 3)}), ex=7*24*3600)
                    except Exception:
                        pass
                    return {
                        'index': ticker.replace('^', ''),
                        'value': round(price, 2),
                        'change_pct_24h': round(change_pct, 3),
                        'trend': 'rising' if change_pct > 0.3 else ('falling' if change_pct < -0.3 else 'flat'),
                        'source': 'Yahoo Finance',
                        'sparkline': [],
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
        except Exception as e:
            print(f"[Israel Econ] Yahoo {ticker} error: {str(e)[:80]}")
            continue

    # Last resort: serve cached last-known value
    try:
        if _redis_available():
            cached_tase = _redis_get(TASE_LAST_KNOWN_KEY)
            if cached_tase:
                last = json.loads(cached_tase)
                print(f"[Israel Econ] Using last-known TASE value: {last['value']}")
                return {
                    'index': 'TA35',
                    'value': last['value'],
                    'change_pct_24h': last.get('change_pct_24h', 0),
                    'trend': 'unknown',
                    'source': 'Yahoo Finance (last known)',
                    'sparkline': [],
                    'estimated': True,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
    except Exception as e:
        print(f"[Israel Econ] Last-known cache read failed: {e}")

    return {
        'index': 'TA35',
        'value': None,
        'change_pct_24h': 0,
        'trend': 'unknown',
        'source': 'Unavailable',
        'estimated': True,
        'sparkline': [],
        'timestamp': datetime.now(timezone.utc).isoformat()
    }


def fetch_eis_etf():
    """
    Fetch iShares MSCI Israel ETF (EIS) — proxy for foreign institutional
    confidence in Israeli equity markets. Trades on NYSE (so it tracks US
    investor sentiment toward Israel risk, NOT local TASE prices).

    Polarity: standard (rising EIS = global confidence; falling = stress).
    Source: Yahoo Finance v8 chart endpoint (free, no key).
    Returns same shape as fetch_tase_index() / fetch_nis_usd().

    v1.0.0 — added May 29 2026 for Financial Pulse Card spec.
    """
    print("[Israel Econ] Fetching EIS ETF (foreign institutional confidence)...")
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EIS"
        r = requests.get(url, params={'interval': '1d', 'range': '1mo'},
                         timeout=10,
                         headers={'User-Agent': 'Mozilla/5.0 (AsifahAnalytics/1.0)'})
        if r.status_code != 200:
            print(f"[Israel Econ] EIS HTTP {r.status_code} — returning unavailable")
            return {
                'index': 'EIS',
                'value': None,
                'change_pct_24h': 0,
                'trend': 'unknown',
                'source': 'Yahoo Finance (unavailable)',
                'sparkline': [],
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        data = r.json()
        result = (data.get('chart', {}).get('result') or [{}])[0]
        meta = result.get('meta', {})
        price = meta.get('regularMarketPrice')
        prev_close = meta.get('chartPreviousClose') or meta.get('previousClose')
        if price is None or prev_close in (None, 0):
            print("[Israel Econ] EIS: empty price field")
            return {
                'index': 'EIS',
                'value': None,
                'change_pct_24h': 0,
                'trend': 'unknown',
                'source': 'Yahoo Finance (no data)',
                'sparkline': [],
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        change_pct = ((price - prev_close) / prev_close) * 100

        # ── 30-day sparkline from same response ──
        sparkline = []
        try:
            timestamps = result.get('timestamp', []) or []
            closes = (result.get('indicators', {}).get('quote') or [{}])[0].get('close', []) or []
            for i, ts in enumerate(timestamps):
                if i < len(closes) and closes[i] is not None:
                    sparkline.append({
                        'time':  datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                        'value': round(float(closes[i]), 2),
                    })
            print(f"[Israel Econ] ✅ EIS sparkline: {len(sparkline)} datapoints")
        except Exception as e:
            print(f"[Israel Econ] EIS sparkline parse error: {str(e)[:80]}")

        print(f"[Israel Econ] ✅ EIS: ${price:.2f} ({change_pct:+.2f}%)")
        return {
            'index': 'EIS',
            'value': round(float(price), 2),
            'change_pct_24h': round(change_pct, 2),
            'trend': 'rising' if change_pct > 0.3 else ('falling' if change_pct < -0.3 else 'flat'),
            'source': 'Yahoo Finance',
            'sparkline': sparkline,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"[Israel Econ] EIS fetch error: {str(e)[:120]}")
        return {
            'index': 'EIS',
            'value': None,
            'change_pct_24h': 0,
            'trend': 'unknown',
            'source': 'Error',
            'sparkline': [],
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }


def _compute_market_status_tase():
    """Compute TASE market status: 'open' / 'closed' / 'pre-market' / 'after-hours'.

    TASE hours: Sunday–Thursday, 09:30–17:24 Israel time (IST = UTC+3,
    DST UTC+3, simplification OK for status display).
    Friday/Saturday: closed (Shabbat).
    Pre-market: 08:30–09:30
    After-hours: 17:24–19:00
    """
    israel_tz = timezone(timedelta(hours=3))
    now_israel = datetime.now(israel_tz)
    weekday = now_israel.weekday()  # Mon=0 ... Sun=6
    hour = now_israel.hour
    minute = now_israel.minute
    minutes_since_midnight = hour * 60 + minute

    # Friday=4, Saturday=5: Shabbat, market closed
    if weekday in (4, 5):
        return 'closed'

    # Normal trading day windows (Sun-Thu = weekday 6,0,1,2,3)
    if 510 <= minutes_since_midnight <= 570:        # 08:30–09:30
        return 'pre-market'
    if 570 < minutes_since_midnight <= 1044:        # 09:30–17:24
        return 'open'
    if 1044 < minutes_since_midnight <= 1140:       # 17:24–19:00
        return 'after-hours'
    return 'closed'


def _compute_market_status_us():
    """Compute US market status for EIS (NYSE-listed): same logic as us_stability.

    US market: Mon–Fri, 09:30–16:00 ET (approximated as UTC-4).
    """
    now_utc = datetime.now(timezone.utc)
    et_hour = (now_utc.hour - 4) % 24
    weekday = now_utc.weekday()
    if weekday >= 5:    # Sat/Sun
        return 'closed'
    if 9 <= et_hour < 16:
        return 'open'
    if 4 <= et_hour < 9:
        return 'pre-market'
    if 16 <= et_hour < 20:
        return 'after-hours'
    return 'closed'


def _compute_market_status_aggregate(statuses):
    """Compute card-header aggregate status from a list of per-tile statuses.

    Rules:
      - All 'open' → 'open'
      - All 'closed' → 'closed'
      - Mixed open/closed (or open/pre-market/after-hours) → 'partial'
      - Mixed pre-market or after-hours when none open → use most-trading state
    """
    if not statuses:
        return 'closed'
    unique = set(statuses)
    if unique == {'open'}:
        return 'open'
    if unique == {'closed'}:
        return 'closed'
    if 'open' in unique:
        return 'partial'    # any market open while others aren't
    if 'pre-market' in unique:
        return 'pre-market'
    if 'after-hours' in unique:
        return 'after-hours'
    return 'closed'


def build_israel_financial_pulse(nis_data, tase_data, eis_data):
    """Assemble the canonical Financial Pulse Card payload for Israel.

    Three tiles: TASE TA-35, NIS/USD, EIS ETF.
    Per-tile market_status + aggregate card-level status.
    Polarity-aware tier coloring (NIS inverted: rising USD/ILS = weakening shekel = stress).

    v1.0.0 — Financial Pulse Card spec (May 29 2026).
    """
    tase_status = _compute_market_status_tase()
    nis_status  = 'open'   # FX trades 24/5 globally; treat as always open during weekdays
    now_utc     = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:    # Sat/Sun: FX effectively closed
        nis_status = 'closed'
    eis_status  = _compute_market_status_us()

    aggregate = _compute_market_status_aggregate([tase_status, nis_status, eis_status])

    def _tier(chg, inverted=False):
        """Polarity-aware tier. Inverted=True for NIS (higher rate = bad)."""
        if inverted:
            chg = -chg
        if chg <= -2:  return 'stress'
        if chg <= -1:  return 'warning'
        if chg >= 2:   return 'rally'
        return 'stable'

    # TASE tile
    tase_value = tase_data.get('value')
    tase_chg = tase_data.get('change_pct_24h', 0) or 0
    tase_tile = {
        'name':           'TASE TA-35',
        'ticker':         'TA35',
        'value':          tase_value,
        'change_pct_24h': tase_chg,
        'trend':          tase_data.get('trend', 'flat'),
        'tier':           _tier(tase_chg),
        'source':         tase_data.get('source', 'TASE'),
        'market_status':  tase_status,
        'timestamp':      tase_data.get('timestamp'),
        'sparkline':      tase_data.get('sparkline', []),
    }

    # NIS/USD tile — inverted polarity (high rate = weak shekel = stress)
    # The NIS field is usd_to_ils (so value of 3.7 means 1 USD = 3.7 ILS, i.e. weak shekel)
    nis_value = nis_data.get('usd_to_ils')
    nis_chg = nis_data.get('change_pct_24h', 0) or 0
    nis_tile = {
        'name':           'NIS / USD',
        'ticker':         'ILS',
        'value':          nis_value,
        'change_pct_24h': nis_chg,
        'trend':          nis_data.get('trend', 'flat'),
        'tier':           _tier(nis_chg, inverted=True),
        'source':         nis_data.get('source', 'Yahoo Finance'),
        'market_status':  nis_status,
        'timestamp':      nis_data.get('timestamp'),
        'sparkline':      nis_data.get('sparkline', []),
    }

    # EIS tile — standard polarity (high price = global confidence)
    eis_value = eis_data.get('value')
    eis_chg = eis_data.get('change_pct_24h', 0) or 0
    eis_tile = {
        'name':           'iShares MSCI Israel',
        'ticker':         'EIS',
        'value':          eis_value,
        'change_pct_24h': eis_chg,
        'trend':          eis_data.get('trend', 'flat'),
        'tier':           _tier(eis_chg),
        'source':         eis_data.get('source', 'Yahoo Finance'),
        'market_status':  eis_status,
        'timestamp':      eis_data.get('timestamp'),
        'sparkline':      eis_data.get('sparkline', []),
    }

    return {
        'country':        'IL',
        'card_label':     'Israel Financial Pulse',
        'market_status':  aggregate,
        'last_refreshed': datetime.now(timezone.utc).isoformat(),
        'tiles': {
            'TASE':    tase_tile,
            'NIS_USD': nis_tile,
            'EIS':     eis_tile,
        },
    }


# ========================================
# CONFLICT & NEWS SCANNING
# ========================================

WAR_KEYWORDS = [
    # ── Active hostilities (war) ──
    'IDF strike', 'Israeli airstrike', 'Gaza offensive', 'IDF operation',
    'Hamas attack', 'missile attack Israel', 'drone Israel', 'ballistic missile Israel',
    'Iron Dome intercept', 'Ben Gurion Airport closed', 'Hezbollah fire',
    'Houthi missile', 'Iran attack Israel',
    # ── Hostage situation ──
    'hostage deal', 'hostage release', 'Gaza ceasefire', 'ceasefire collapse',
    'hostage negotiations', 'Sinwar', 'Hamas ceasefire',
    # ── Coalition crisis signals ──
    'Ben Gvir resign', 'Ben Gvir threatens', 'Smotrich coalition',
    'Netanyahu coalition', 'no confidence Netanyahu', 'coalition collapse',
    'Netanyahu resign', 'Netanyahu indictment',
    # ── Opposition signals (legacy index — kept for backward compat) ──
    'Bennett prime minister', 'Bennett challenge Netanyahu', 'Bennett coalition'
]

# v2.1.0 (April 2026) — Named keyword sets to replace error-prone slice indexing.
# The old [:14] / [14:22] / [22:30] / [30:] slices were OFF-BY-ONE and only
# detected ONE Bennett keyword instead of three. These sets are now the source
# of truth for the classifier; WAR_KEYWORDS list above is kept for backward
# compatibility with anything else that imports it.

WAR_KW_WAR = [
    'IDF strike', 'Israeli airstrike', 'Gaza offensive', 'IDF operation',
    'Hamas attack', 'missile attack Israel', 'drone Israel', 'ballistic missile Israel',
    'Iron Dome intercept', 'Ben Gurion Airport closed', 'Hezbollah fire',
    'Houthi missile', 'Iran attack Israel',
]

WAR_KW_HOSTAGE = [
    'hostage deal', 'hostage release', 'Gaza ceasefire', 'ceasefire collapse',
    'hostage negotiations', 'Sinwar', 'Hamas ceasefire',
]

WAR_KW_COALITION = [
    'Ben Gvir resign', 'Ben Gvir threatens', 'Smotrich coalition',
    'Netanyahu coalition', 'no confidence Netanyahu', 'coalition collapse',
    'Netanyahu resign', 'Netanyahu indictment',
    # New in v2.1.0
    'coalition crisis Israel', 'haredi draft', 'ultra-Orthodox draft',
    'Knesset dissolved', 'Knesset vote no confidence', 'Likud rebellion',
    'budget vote Israel', 'Otzma Yehudit', 'Religious Zionism Israel',
]

# ── OPPOSITION KEYWORDS — the big expansion ──
# Captures Bennett, Lapid, Eisenkot, Gantz, Liberman + the new "Together" party
# + bloc dynamics + early-elections signals. This is what fills the Opposition
# Watch card (formerly Bennett Watch).
OPPOSITION_KW = [
    # Bennett — full name + role variants
    'Bennett', 'Naftali Bennett', 'former PM Bennett', 'Bennett 2026',
    'Bennett polling', 'Bennett party', 'Bennett opposition', 'Bennett Knesset',
    'Bennett warned', 'Bennett criticized', 'Bennett to launch', 'Bennett new party',
    # Lapid
    'Lapid', 'Yair Lapid', 'Yesh Atid', 'Lapid opposition',
    'Lapid Bennett', 'opposition leader Lapid',
    # Together party (April 26, 2026 merger)
    'Together party', 'Together led by Bennett', 'Bennett Lapid alliance',
    'Bennett Lapid merger', 'Bennett Lapid unite', 'Bennett Lapid party',
    'opposition merger Israel', 'opposition unite Israel',
    # Eisenkot / Yashar
    'Eisenkot', 'Gadi Eisenkot', 'Yashar party', 'Yashar Israel',
    'Eisenkot Bennett', 'Eisenkot join', 'Yashar Eisenkot',
    # Gantz / National Unity
    'Gantz', 'Benny Gantz', 'National Unity Israel', 'Gantz party',
    'Gantz opposition', 'Gantz Knesset',
    # Liberman / Yisrael Beiteinu
    'Liberman', 'Avigdor Liberman', 'Yisrael Beiteinu',
    # Bloc dynamics
    'anti-Netanyahu bloc', 'opposition bloc Israel', 'Zionist opposition',
    'change bloc', 'opposition coalition Israel',
    # Early elections / electoral pressure
    'early elections Israel', 'October 2026 elections', 'Israel election 2026',
    'Knesset election', 'Israel election by October', 'snap election Israel',
    'dissolve Knesset', 'Israel goes to elections',
    # Polling signals
    'Israel poll', 'Channel 12 poll Israel', 'Channel 13 poll Israel',
    'Maariv poll', 'Walla poll Israel', 'Israeli poll seats',
]

# ── ELECTIONS PROXIMITY signals — high-priority subset ──
# These specifically trigger the new Elections Vector. When these surface,
# elections are imminent / called / being debated.
ELECTIONS_PROXIMITY_KW = [
    'early elections Israel', 'October 2026 elections', 'Israel election 2026',
    'snap election Israel', 'dissolve Knesset', 'Israel goes to elections',
    'Knesset dissolved', 'no confidence Netanyahu', 'no confidence vote Israel',
    'budget vote fails', 'coalition collapse', 'caretaker government Israel',
    'Israel election by October',
]

SEVERITY_HIGH = [
    'war', 'explosion', 'killed', 'dead', 'casualties', 'attack', 'strike',
    'fired', 'launched', 'intercepted', 'ceasefire collapse', 'escalation',
    'ground operation', 'invasion', 'offensive', 'missile', 'ballistic'
]

RSS_SOURCES = [
    # Times of Israel
    ('https://www.timesofisrael.com/feed/', 'Times of Israel'),
    # Jerusalem Post
    ('https://www.jpost.com/rss/rssfeedsfrontpage.aspx', 'Jerusalem Post'),
    # Haaretz (English)
    ('https://www.haaretz.com/cmlink/1.628765', 'Haaretz'),
    # Google News — Israel war
    ('https://news.google.com/rss/search?q=Israel+IDF+Gaza+war&hl=en&gl=US&ceid=US:en', 'Google News - War'),
    # Google News — coalition
    ('https://news.google.com/rss/search?q=Netanyahu+coalition+Knesset&hl=en&gl=US&ceid=US:en', 'Google News - Coalition'),
    # Google News — Bennett
    ('https://news.google.com/rss/search?q=Naftali+Bennett+Israel+politics&hl=en&gl=US&ceid=US:en', 'Google News - Bennett'),
    # Google News — hostages
    ('https://news.google.com/rss/search?q=Israel+hostage+deal+Gaza+ceasefire&hl=en&gl=US&ceid=US:en', 'Google News - Hostages'),
    # Ynet (English via Google)
    ('https://news.google.com/rss/search?q=Ynet+Israel&hl=en&gl=US&ceid=US:en', 'Ynet'),
]


def _parse_rss_articles(url, source_name, days=7):
    """Fetch and parse RSS feed, returning articles within date window.

    v1.5.2 (May 29 2026 — cascaded from us_stability.py):
      - Chrome 130 + Client Hints fingerprint (defeats most bot detection)
      - Firefox UA fallback on 403 (defeats Chrome-specific blocks)
      - curl_cffi TLS impersonation on persistent 403 (defeats Cloudflare network layer)
      - {*} namespace wildcard XML parser (handles RSS 2.0, RSS 1.0/RDF, Atom uniformly)
    """
    articles = []
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/130.0.0.0 Safari/537.36'
        ),
        'Accept': ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                   'application/rss+xml;q=0.9,image/avif,image/webp,*/*;q=0.8'),
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Cache-Control': 'max-age=0',
        'Sec-Ch-Ua': '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'Referer': 'https://www.google.com/',
        'DNT': '1',
    }
    try:
        r = requests.get(url, timeout=10, headers=headers, allow_redirects=True)
        # Tier 2: Firefox UA on 403
        if r.status_code == 403:
            print(f"[RSS] {source_name}: HTTP 403 — retrying with Firefox UA")
            firefox_headers = {
                'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) '
                               'Gecko/20100101 Firefox/130.0'),
                'Accept': ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                           'image/avif,image/webp,*/*;q=0.8'),
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Referer': 'https://duckduckgo.com/',
            }
            time.sleep(1.2)
            r = requests.get(url, timeout=10, headers=firefox_headers, allow_redirects=True)
        # Tier 3: curl_cffi TLS impersonation on persistent 403
        if r.status_code == 403 and CURL_CFFI_AVAILABLE:
            print(f"[RSS] {source_name}: HTTP 403 — retrying with curl_cffi TLS impersonation")
            try:
                time.sleep(0.8)
                cc_resp = curl_requests.get(url, impersonate='chrome',
                                            timeout=10, allow_redirects=True)
                if cc_resp.status_code == 200:
                    class _CCWrapper:
                        def __init__(self, cc):
                            self.status_code = cc.status_code
                            self.content = cc.content
                            self.text = cc.text
                    r = _CCWrapper(cc_resp)
                    print(f"[RSS] {source_name}: ✅ curl_cffi rescued (TLS impersonation)")
                else:
                    print(f"[RSS] {source_name}: curl_cffi also got HTTP {cc_resp.status_code}")
            except Exception as cc_err:
                print(f"[RSS] {source_name}: curl_cffi error {str(cc_err)[:100]}")
        if r.status_code != 200:
            return articles

        # {*} wildcard namespace parser — handles RSS 2.0, RSS 1.0/RDF, Atom uniformly
        root = ET.fromstring(r.content)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        all_items = (root.findall('.//{*}item') or
                     root.findall('.//{*}entry'))
        for item in all_items:
            title_el = item.find('{*}title')
            link_el  = item.find('{*}link')
            pub_el   = (item.find('{*}pubDate') or
                        item.find('{*}published') or
                        item.find('{*}updated'))
            desc_el  = (item.find('{*}description') or
                        item.find('{*}summary'))
            if title_el is None:
                continue
            pub_str = pub_el.text if (pub_el is not None and pub_el.text) else ''
            # Date filter
            if pub_str:
                try:
                    pub_dt = parsedate_to_datetime(pub_str)
                    if pub_dt < cutoff:
                        continue
                except Exception:
                    pass
            # Link handling — Atom <link href="..."/> vs RSS <link>...</link>
            link_text = ''
            if link_el is not None:
                link_text = (link_el.text or link_el.get('href') or '').strip()
            articles.append({
                'title': (title_el.text or '').strip(),
                'url': link_text,
                'published': pub_str,
                'source': source_name,
                'description': (desc_el.text or '')[:200] if (desc_el is not None and desc_el.text) else ''
            })
        # Diagnostic (May 29 2026 — cascaded from us_stability.py): log success/empty
        # so we can verify which feeds are populating cleanly after hardening.
        if articles:
            print(f"[RSS] {source_name}: ✅ {len(articles)} items")
        else:
            # Only log "0 items" if we actually got a 200 — otherwise the HTTP error
            # already logged. all_items count tells us whether parse succeeded.
            try:
                if r.status_code == 200:
                    raw_count = len(all_items) if 'all_items' in locals() else 0
                    if raw_count == 0:
                        print(f"[RSS] {source_name}: ⚠️ 200 OK but 0 items parsed (check feed format)")
                    else:
                        print(f"[RSS] {source_name}: ⚠️ {raw_count} items parsed but all filtered out (date window)")
            except Exception:
                pass
    except Exception as e:
        print(f"[RSS] {source_name} error: {str(e)[:80]}")
    return articles


def scan_israel_conflict(days=7):
    """
    Scan RSS feeds + Telegram for conflict, coalition, and hostage indicators.
    Returns scored conflict data + article list.
    """
    print("[Israel Conflict] Starting scan...")
    all_articles = []

    for url, name in RSS_SOURCES:
        fetched = _parse_rss_articles(url, name, days=days)
        all_articles.extend(fetched)
        print(f"[Israel Conflict] {name}: {len(fetched)} articles")

    if TELEGRAM_AVAILABLE:
        try:
            telegram_msgs = fetch_telegram_signals(hours_back=days*24, include_extended=True)
            if telegram_msgs:
                for msg in telegram_msgs:
                    all_articles.append({
                        'title': msg.get('title', '')[:200],
                        'url': msg.get('url', ''),
                        'published': msg.get('published', ''),
                        'source': msg.get('source', 'Telegram'),
                        'description': msg.get('title', '')[:200]
                    })
                print(f"[Israel Conflict] Telegram: {len(telegram_msgs)} messages")
        except Exception as e:
            print(f"[Israel Conflict] Telegram error: {str(e)[:100]}")

    # Deduplicate by title
    seen = set()
    unique = []
    for a in all_articles:
        key = a['title'].strip().lower()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(a)
    all_articles = unique

    # Score each article
    war_hits       = 0
    coalition_hits = 0
    hostage_hits   = 0
    bennett_hits   = 0   # v2.1.0 — now counts ALL opposition mentions, not just Bennett
    elections_hits = 0   # v2.1.0 — early-elections proximity signals
    high_severity  = 0

    war_articles       = []
    coalition_articles = []
    hostage_articles   = []
    bennett_articles   = []   # v2.1.0 — opposition articles (Bennett, Lapid, Eisenkot, Gantz, Together, etc.)
    elections_articles = []   # v2.1.0 — articles specifically mentioning early elections / dissolution / etc.

    for a in all_articles:
        t = a['title'].lower()
        d = a.get('description', '').lower()
        combined = t + ' ' + d

        # v2.1.0 — Use named keyword sets (was: error-prone slice indexing)
        is_war        = any(kw.lower() in combined for kw in WAR_KW_WAR)
        is_hostage    = any(kw.lower() in combined for kw in WAR_KW_HOSTAGE)
        is_coalition  = any(kw.lower() in combined for kw in WAR_KW_COALITION)
        is_opposition = any(kw.lower() in combined for kw in OPPOSITION_KW)
        is_elections  = any(kw.lower() in combined for kw in ELECTIONS_PROXIMITY_KW)
        is_severe     = any(kw in combined for kw in SEVERITY_HIGH)

        if is_war:
            war_hits += 1
            war_articles.append(a)
        if is_coalition:
            coalition_hits += 1
            coalition_articles.append(a)
        if is_hostage:
            hostage_hits += 1
            hostage_articles.append(a)
        if is_opposition:
            bennett_hits += 1
            bennett_articles.append(a)
        if is_elections:
            elections_hits += 1
            elections_articles.append(a)
        if is_severe:
            high_severity += 1

    # Conflict intensity score 0-100
    conflict_score = min(100,
        war_hits * 4 +
        high_severity * 3 +
        coalition_hits * 2 +
        hostage_hits * 1
    )

    # Coalition fragility score 0-100
    # v2.1.0 — Now factors in ALL opposition mentions (was: only Bennett's narrow set)
    coalition_score = min(100, coalition_hits * 8 + bennett_hits * 3 + elections_hits * 5)

    # v2.1.0 — Elections proximity score 0-100 (separate from coalition fragility)
    # Powers the new Elections Vector — reflects how imminent / publicly debated
    # an early dissolution actually is. Different from coalition fragility because
    # a coalition can be fragile WITHOUT election triggers firing yet.
    elections_proximity_score = min(100, elections_hits * 10)

    # Hostage/ceasefire status heuristic
    ceasefire_active = hostage_hits > 0 and any(
        'ceasefire' in a['title'].lower() or 'deal' in a['title'].lower()
        for a in hostage_articles
    )

    print(f"[Israel Conflict] War:{war_hits} | Coalition:{coalition_hits} | Hostage:{hostage_hits} | Opposition:{bennett_hits} | Elections:{elections_hits}")
    print(f"[Israel Conflict] Conflict: {conflict_score}/100 | Coalition fragility: {coalition_score}/100 | Elections proximity: {elections_proximity_score}/100")

    return {
        'conflict_score': conflict_score,
        'coalition_score': coalition_score,
        'elections_proximity_score': elections_proximity_score,
        'war_article_count': war_hits,
        'coalition_article_count': coalition_hits,
        'hostage_article_count': hostage_hits,
        'bennett_mentions': bennett_hits,         # legacy field name kept for backward compat
        'opposition_mentions': bennett_hits,      # v2.1.0 — preferred new name
        'elections_mentions': elections_hits,     # v2.1.0
        'high_severity_count': high_severity,
        'ceasefire_active': ceasefire_active,
        'articles': {
            'war': war_articles[:10],
            'coalition': coalition_articles[:8],
            'hostage': hostage_articles[:8],
            'bennett': bennett_articles[:8],      # legacy bucket (now contains all opposition)
            'opposition': bennett_articles[:8],   # v2.1.0 — preferred new bucket name
            'elections': elections_articles[:6],  # v2.1.0
        },
        'all_articles': all_articles[:40]
    }

# ========================================
# ACLED STRIKE TRACKER (with RSS fallback)
# ========================================

def fetch_acled_strikes():
    """
    Fetch recent strike/conflict events from ACLED API.
    Requires ACLED_API_KEY + ACLED_EMAIL env vars.
    Falls back to RSS strike mentions if key unavailable.
    """
    print("[ACLED] Fetching Israel strikes...")

    if ACLED_API_KEY and ACLED_EMAIL:
        try:
            # ACLED API v2 — events in Israel/Gaza/Lebanon last 30 days
            since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
            params = {
                'key': ACLED_API_KEY,
                'email': ACLED_EMAIL,
                'country': 'Israel|Palestine|Lebanon',
                'event_date': since,
                'event_date_where': 'BETWEEN',
                'event_date_to': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                'event_type': 'Explosions/Remote violence|Battles|Strategic developments',
                'limit': 200,
                'fields': 'event_date|event_type|sub_event_type|actor1|actor2|country|location|latitude|longitude|fatalities|notes',
                'format': 'json'
            }
            r = requests.get('https://api.acleddata.com/acled/read', params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                events = data.get('data', [])
                print(f"[ACLED] ✅ {len(events)} events retrieved")
                return {
                    'source': 'ACLED',
                    'event_count': len(events),
                    'events': events[:100],
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'acled_available': True
                }
        except Exception as e:
            print(f"[ACLED] API error: {str(e)[:100]}")

    # === FALLBACK: RSS + Telegram strike mentions ===
    print("[ACLED] No API key — using RSS + Telegram strike fallback")
    strike_articles = []
    strike_queries = [
        'IDF airstrike Gaza today',
        'Israeli strike Lebanon Syria',
        'Houthi missile Israel',
        'Iran attack Israel strike'
    ]
    for q in strike_queries:
        url = f"https://news.google.com/rss/search?q={q.replace(' ', '+')}&hl=en&gl=US&ceid=US:en"
        strike_articles.extend(_parse_rss_articles(url, 'Google News - Strikes', days=7))

    if TELEGRAM_AVAILABLE:
        try:
            telegram_msgs = fetch_telegram_signals(hours_back=168, include_extended=True)
            if telegram_msgs:
                for msg in telegram_msgs:
                    strike_articles.append({
                        'title': msg.get('title', '')[:200],
                        'url': msg.get('url', ''),
                        'published': msg.get('published', ''),
                        'source': msg.get('source', 'Telegram'),
                        'description': msg.get('title', '')[:200]
                    })
                print(f"[ACLED Fallback] Telegram: {len(telegram_msgs)} messages added")
        except Exception as e:
            print(f"[ACLED Fallback] Telegram error: {str(e)[:100]}")

    # Deduplicate
    seen = set()
    unique_strikes = []
    for a in strike_articles:
        k = a['title'].strip().lower()[:80]
        if k not in seen:
            seen.add(k)
            unique_strikes.append(a)

    return {
        'source': 'RSS_fallback',
        'event_count': len(unique_strikes),
        'events': [],  # No lat/lng without ACLED
        'articles': unique_strikes[:15],
        'acled_available': False,
        'acled_note': 'Register at acleddata.com for free research API key. Set ACLED_API_KEY and ACLED_EMAIL env vars.',
        'last_updated': datetime.now(timezone.utc).isoformat()
    }

# ========================================
# KNESSET / COALITION POLITICS
# ========================================

# Static coalition data — update as needed
COALITION_DATA = {
    'pm': 'Benjamin Netanyahu',
    'president': 'Isaac Herzog',
    'defense_minister': 'Israel Katz (since Nov 2024)',
    'coalition_seats': 64,
    'knesset_total': 120,
    'majority_threshold': 61,
    'coalition_parties': [
        {'name': 'Likud', 'seats': 32, 'leader': 'Netanyahu'},
        {'name': 'Shas', 'seats': 11, 'leader': 'Deri'},
        {'name': 'United Torah Judaism', 'seats': 7, 'leader': 'Gafni'},
        {'name': 'Religious Zionism', 'seats': 7, 'leader': 'Smotrich'},
        {'name': 'Otzma Yehudit', 'seats': 6, 'leader': 'Ben Gvir'},
        {'name': 'Noam', 'seats': 1, 'leader': 'Maoz'}
    ],
    'opposition_leader': 'Naftali Bennett (Together / מחר — formerly Bennett 2026 + Yesh Atid)',
    'opposition_party': 'Together (מחר) — led by Bennett, merged Apr 26 2026',
    'opposition_other_blocs': [
        'Yashar! (Eisenkot) — courted to join Together',
        'National Unity (Gantz)',
        'Yisrael Beiteinu (Liberman)',
        'Democrats / Labor',
        'Hadash-Taal / Ra\'am (Arab parties)',
    ],
    'formed': '2022-12-29',
    'next_election': 'By October 2026 (can be called earlier)',
    'war_cabinet_active': False,  # Gantz resigned June 2024
    'icc_warrants': ['Netanyahu', 'Gallant (former)'],
    'criminal_trial': 'Netanyahu — bribery, fraud, breach of trust (ongoing)',
}


def scan_knesset_news():
    """Scan for Knesset/coalition/election news."""
    print("[Knesset] Scanning political news...")
    knesset_queries = [
        'Netanyahu Knesset coalition 2026',
        'Israel election early vote',
        'Ben Gvir Smotrich coalition threat',
        'Naftali Bennett Israel leadership'
    ]
    articles = []
    for q in knesset_queries:
        url = f"https://news.google.com/rss/search?q={q.replace(' ','+')}+Israel&hl=en&gl=US&ceid=US:en"
        articles.extend(_parse_rss_articles(url, 'Google News - Politics', days=14))

    if TELEGRAM_AVAILABLE:
        try:
            telegram_msgs = fetch_telegram_signals(hours_back=336, include_extended=True)
            if telegram_msgs:
                for msg in telegram_msgs:
                    articles.append({
                        'title': msg.get('title', '')[:200],
                        'url': msg.get('url', ''),
                        'published': msg.get('published', ''),
                        'source': msg.get('source', 'Telegram'),
                        'description': msg.get('title', '')[:200]
                    })
                print(f"[Knesset] Telegram: {len(telegram_msgs)} messages added")
        except Exception as e:
            print(f"[Knesset] Telegram error: {str(e)[:100]}")

    # Deduplicate
    seen = set()
    unique = []
    for a in articles:
        k = a['title'].strip().lower()[:80]
        if k not in seen:
            seen.add(k)
            unique.append(a)

    # Check for election signals
    election_keywords = ['early election', 'snap election', 'coalition collapse', 'no confidence', 'new election']
    election_signals  = [a for a in unique if any(kw in a['title'].lower() for kw in election_keywords)]

    print(f"[Knesset] {len(unique)} political articles | {len(election_signals)} election signals")
    return {
        'articles': unique[:20],
        'election_signal_count': len(election_signals),
        'election_signals': election_signals[:5],
        'coalition_data': COALITION_DATA
    }

# ========================================
# LEADERSHIP STATUS (dynamic update from news)
# ========================================

def build_leadership_status(conflict_data, knesset_data):
    """
    Return leadership badges with dynamically updated notes
    based on recent news scan hits.
    """
    figures = {k: dict(v) for k, v in POLITICAL_FIGURES.items()}

    all_titles = [
        a['title'].lower()
        for a in (
            knesset_data.get('articles', []) +
            conflict_data.get('articles', {}).get('coalition', []) +
            conflict_data.get('articles', {}).get('bennett', [])
        )
    ]

    # Netanyahu — check for coalition threat signals
    if any('resign' in t or 'no confidence' in t or 'coalition collapse' in t for t in all_titles):
        figures['netanyahu']['status'] = 'UNDER PRESSURE'
        figures['netanyahu']['status_color'] = '#fb923c'

    # Ben Gvir — check for resignation threats
    if any('ben gvir' in t and ('resign' in t or 'threat' in t or 'quit' in t) for t in all_titles):
        figures['ben_gvir']['status'] = 'THREATENING EXIT'
        figures['ben_gvir']['status_color'] = '#f87171'

    # Bennett — check for active campaigning signals
    if conflict_data.get('bennett_mentions', 0) > 2:
        figures['bennett']['status'] = 'ACTIVE'
        figures['bennett']['status_color'] = '#6495ED'

    return figures

# ========================================
# STABILITY SCORE CALCULATION
# ========================================

# ============================================
# COMMODITY PRESSURE CONFIG (Phase 3, May 5 2026)
# ============================================
# Reads commodity_tracker_cache Redis key (written by commodity_tracker.py).
# Israel has 6 commodity exposures: potash + natural_gas (producer side),
# wheat + corn + soybeans + oil (consumer side).
#
# Stability penalty is dict-driven so it stays flexible — to add penalties
# for other commodities later, just add entries here.
#
# CURRENT POLICY (May 5 2026): Wheat-only.
#   - Wheat: bread inflation = coalition stress lever. Israel imports ~80%
#            of wheat consumption (Black Sea + US). Penalty magnitude lower
#            than Iran's because Israel = stronger institutions, not regime risk.
#   - Other commodities tracked but not yet penalty-enabled.
COMMODITY_REDIS_KEY = 'commodity_tracker_cache'

COMMODITY_PENALTY_CONFIG = {
    'wheat': {
        'penalty_high':  -2,
        'penalty_surge': -5,
        'rationale':     'Wheat surge → bread inflation → coalition stress (Netanyahu fragile)',
    },
    # Future-flex (commented out, ready to enable):
    # 'oil':          {'penalty_high': -2, 'penalty_surge': -4,
    #                  'rationale': 'Oil surge → fuel inflation + military operations cost'},
    # 'corn':         {'penalty_high': -1, 'penalty_surge': -2,
    #                  'rationale': 'Corn surge → livestock + food prices'},
    # 'soybeans':     {'penalty_high': -1, 'penalty_surge': -2,
    #                  'rationale': 'Soy surge → food + feed cost stress'},
    # 'natural_gas':  {'penalty_high': 0,  'penalty_surge': 0,
    #                  'rationale': 'Israel is producer; surge = export revenue boost (no penalty)'},
    # 'potash':       {'penalty_high': 0,  'penalty_surge': 0,
    #                  'rationale': 'Israel is producer (ICL); surge benefits export revenue'},
}


def _read_israel_commodity_pressure():
    """
    Read commodity-pressure data for Israel from shared Redis cache.

    Returns a dict shaped like:
        {
            'commodity_pressure': float,       # Israel-specific score
            'alert_level':        str,         # normal|elevated|high|surge
            'commodity_summaries': [...],
            'last_updated':       str,
        }
    Returns None if cache cold, Israel not in bundle, or any error.
    """
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_URL}/get/{COMMODITY_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            timeout=5
        )
        data = resp.json()
        if not data.get('result'):
            return None
        bundle = json.loads(data['result'])
        if not isinstance(bundle, dict):
            return None

        country_summaries = bundle.get('country_summaries', {}) or {}
        commodity_summary = bundle.get('commodity_summaries', {}) or {}
        israel_country = country_summaries.get('israel') or {}
        if not israel_country:
            return None

        israel_score = float(israel_country.get('total_score', 0) or 0)
        israel_alert = str(israel_country.get('alert_level', 'normal') or 'normal')
        israel_breakdown = israel_country.get('commodity_signals', {}) or {}

        commodity_summaries_out = []
        for commodity_id, breakdown in israel_breakdown.items():
            full = commodity_summary.get(commodity_id, {}) or {}
            commodity_summaries_out.append({
                'commodity':           commodity_id,
                'name':                full.get('name', commodity_id.title()),
                'icon':                full.get('icon', '📊'),
                'role':                breakdown.get('role'),
                'rank':                breakdown.get('rank'),
                'note':                breakdown.get('note'),
                'signal_count':        int(breakdown.get('signal_count', 0) or 0),
                'global_alert_level':  str(full.get('alert_level', 'normal') or 'normal'),
                'global_signal_count': int(full.get('signal_count', 0) or 0),
                'global_total_score':  float(full.get('total_score', 0) or 0),
                'sparkline':           full.get('sparkline'),
            })

        return {
            'commodity_pressure':  israel_score,
            'alert_level':         israel_alert,
            'commodity_summaries': commodity_summaries_out,
            'last_updated':        bundle.get('last_updated', bundle.get('cached_at')),
        }
    except Exception as e:
        print(f"[Israel Commodity] Read error (non-fatal): {str(e)[:120]}")
        return None


def calculate_israel_stability(economic_data, tase_data, conflict_data, knesset_data, strike_data):
    """
    Israel Stability Score (0–100)

    Active-war calibrated model. Unlike Lebanon (chronic collapse),
    Israel has a functioning state under severe war stress.
    A score of 50-60 = "stressed but functional" during active war.
    """
    print("[Israel Stability] Calculating score (v1.0.0 active-war model)...")

    base = 50

    # ── Economic component (+10 max) ──
    econ_bonus = 0
    nis = economic_data.get('usd_to_ils', 3.7)
    nis_change = abs(economic_data.get('change_pct_24h', 0))
    tase_change = tase_data.get('change_pct_24h', 0) if tase_data else 0

    # NIS: pre-war ~3.45; war stress ~3.6-3.9; severe pressure >4.0
    if nis < 3.60:
        econ_bonus += 5   # Relatively stable
    elif nis < 3.80:
        econ_bonus += 2   # Mild war pressure
    elif nis < 4.00:
        econ_bonus += 0   # Elevated pressure
    else:
        econ_bonus -= 3   # Severe pressure

    # TASE performance
    if tase_change > 0.5:
        econ_bonus += 3
    elif tase_change > 0:
        econ_bonus += 1
    elif tase_change < -1.5:
        econ_bonus -= 3
    elif tase_change < -0.5:
        econ_bonus -= 1

    econ_bonus = max(-8, min(10, econ_bonus))
    print(f"[Israel Stability] Economic: {econ_bonus:+d} (NIS={nis:.3f}, TASE={tase_change:+.2f}%)")

    # ── War intensity (-25 max) ──
    conflict_score = conflict_data.get('conflict_score', 0)
    war_impact = int((conflict_score / 100) * 25)
    print(f"[Israel Stability] War impact: -{war_impact} (conflict_score={conflict_score})")

    # ── Coalition fragility (-15 max) ──
    # v2.1.0 — Now incorporates elections_proximity_score: when articles are
    # explicitly discussing early elections / dissolution / no-confidence votes,
    # the coalition isn't just fragile, it's in active electoral pressure mode.
    coalition_score = conflict_data.get('coalition_score', 0)
    elections_proximity = conflict_data.get('elections_proximity_score', 0)
    election_signals = knesset_data.get('election_signal_count', 0)
    coalition_impact = int((coalition_score / 100) * 10) \
                     + int((elections_proximity / 100) * 4) \
                     + min(election_signals * 2, 3)
    coalition_impact = min(coalition_impact, 15)
    print(f"[Israel Stability] Coalition impact: -{coalition_impact} (coalition_score={coalition_score}, elections_proximity={elections_proximity}, election_signals={election_signals})")

    # ── Regional threat (-15 max) ──
    # Static baseline — Iran/Hezbollah/Houthi ongoing
    # Will be made dynamic with ACLED when key is available
    event_count = strike_data.get('event_count', 0)
    if event_count > 50:
        regional_impact = 15
    elif event_count > 20:
        regional_impact = 10
    elif event_count > 5:
        regional_impact = 7
    else:
        # RSS fallback: use conflict scan as proxy
        regional_impact = 8  # Baseline: Iran/Hezbollah/Houthi threats always present
    print(f"[Israel Stability] Regional impact: -{regional_impact} (events={event_count})")

    # ── Hostage/ceasefire deal bonus (+8 max) ──
    hostage_bonus = 0
    if conflict_data.get('ceasefire_active', False):
        hostage_bonus = 8
    elif conflict_data.get('hostage_article_count', 0) > 3:
        hostage_bonus = 3  # Active negotiations signal
    print(f"[Israel Stability] Hostage bonus: +{hostage_bonus}")

    # ── Humanitarian/ICC pressure (-5 max) ──
    # ICJ/ICC proceedings, international isolation — static for now
    humanitarian_drag = -4
    print(f"[Israel Stability] Humanitarian drag: {humanitarian_drag}")

    # ── Rhetoric penalty (v1.1.0 — dual dashboard) ──
    # Inbound: when Iran/Hezbollah are actively striking Israel,
    # regional_impact increases dynamically beyond the static baseline.
    # Outbound: annexation rhetoric at L3+ adds coalition pressure drag.
    INBOUND_PENALTY  = {0:0, 1:0, 2:-2, 3:-5, 4:-12, 5:-20}
    OUTBOUND_PENALTY = {0:0, 1:0, 2:0,  3:-3, 4:-6,  5:-10}
    ALERT_PENALTY    = {0:0, 1:-1, 2:-2, 3:-4, 4:-7, 5:-10}
    rhetoric_inbound  = 0
    rhetoric_outbound = 0
    rhetoric_alerts   = 0
    try:
        if UPSTASH_URL and UPSTASH_TOKEN:
            resp = requests.get(
                f"{UPSTASH_URL}/get/rhetoric:israel:latest",
                headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                timeout=5
            )
            rdata = resp.json()
            if rdata.get('result'):
                rc = json.loads(rdata['result'])
                inbound_lv  = rc.get('inbound_max_level', 0)
                outbound_lv = rc.get('annexation_level', 0)
                alert_lv    = rc.get('alert_level', 0)
                rhetoric_inbound  = INBOUND_PENALTY.get(inbound_lv, 0)
                rhetoric_outbound = OUTBOUND_PENALTY.get(outbound_lv, 0)
                rhetoric_alerts   = ALERT_PENALTY.get(alert_lv, 0)
                print(f"[Israel Stability] Rhetoric: inbound={rhetoric_inbound} (L{inbound_lv}), outbound={rhetoric_outbound} (L{outbound_lv}), alerts={rhetoric_alerts} (L{alert_lv})")
    except Exception as e:
        print(f"[Israel Stability] Rhetoric penalty skipped: {e}")

    # ── Commodity penalty (Phase 3 — May 5 2026) ──
    # Per-commodity stability penalties driven by COMMODITY_PENALTY_CONFIG.
    # Currently wheat-only (bread → coalition stress lever).
    commodity_pressure_data = _read_israel_commodity_pressure()
    commodity_penalty = 0
    commodity_penalty_detail = {}
    try:
        if commodity_pressure_data and commodity_pressure_data.get('commodity_summaries'):
            for summary in commodity_pressure_data['commodity_summaries']:
                cid = str(summary.get('commodity', '')).lower()
                config = COMMODITY_PENALTY_CONFIG.get(cid)
                if not config:
                    continue
                global_alert = str(summary.get('global_alert_level', 'normal')).lower()
                if global_alert == 'surge':
                    delta = config.get('penalty_surge', 0)
                elif global_alert == 'high':
                    delta = config.get('penalty_high', 0)
                else:
                    delta = 0
                if delta != 0:
                    commodity_penalty += delta
                    commodity_penalty_detail[cid] = {
                        'penalty':   delta,
                        'alert':     global_alert,
                        'rationale': config.get('rationale', ''),
                    }
            if commodity_penalty:
                print(f"[Israel Stability] Commodity penalty: {commodity_penalty} (detail: {commodity_penalty_detail})")
    except Exception as e:
        print(f"[Israel Stability] Commodity penalty skipped: {e}")

    # ── Final score ──
    score = (
        base
        + econ_bonus
        - war_impact
        - coalition_impact
        - regional_impact
        + hostage_bonus
        + humanitarian_drag
        + rhetoric_inbound
        + rhetoric_outbound
        + rhetoric_alerts
        + commodity_penalty
    )
    score = max(0, min(100, int(score)))

    if score >= 70:
        risk_level = 'Stressed but Functional'
        risk_color = 'yellow'
    elif score >= 50:
        risk_level = 'Moderate War Stress'
        risk_color = 'orange'
    elif score >= 30:
        risk_level = 'High War Stress'
        risk_color = 'red'
    else:
        risk_level = 'Crisis Level'
        risk_color = 'red'

    # Trend
    trend = 'stable'
    if conflict_data.get('conflict_score', 0) > 60 or coalition_impact > 8:
        trend = 'worsening'
    elif hostage_bonus >= 8 and econ_bonus > 0:
        trend = 'improving'

    print(f"[Israel Stability] ✅ Score: {score}/100 ({risk_level})")
    print(f"[Israel Stability] Components: base={base}, econ={econ_bonus:+}, war=-{war_impact}, coalition=-{coalition_impact}, regional=-{regional_impact}, hostage=+{hostage_bonus}, humanitarian={humanitarian_drag}")

    print(f"[Israel Stability] ✅ Score: {score}/100 ({risk_level}) | rhetoric_inbound={rhetoric_inbound} outbound={rhetoric_outbound} alerts={rhetoric_alerts}")

    return {
        'score': score,
        'risk_level': risk_level,
        'risk_color': risk_color,
        'trend': trend,
        'components': {
            'base': base,
            'economic_bonus': econ_bonus,
            'war_impact': -war_impact,
            'coalition_impact': -coalition_impact,
            'regional_impact': -regional_impact,
            'hostage_bonus': hostage_bonus,
            'humanitarian_drag': humanitarian_drag,
            'rhetoric_inbound': rhetoric_inbound,
            'rhetoric_outbound': rhetoric_outbound,
            'rhetoric_alerts': rhetoric_alerts,
            # v2.1.0 — elections proximity surfaced for frontend's new Elections Vector card
            'elections_proximity_score': conflict_data.get('elections_proximity_score', 0),
            'opposition_mentions': conflict_data.get('opposition_mentions', 0),
            'elections_mentions': conflict_data.get('elections_mentions', 0),
            # v2.2.0 — commodity penalty exposure for frontend stability breakdown
            'commodity_penalty': commodity_penalty,
            'commodity_penalty_detail': commodity_penalty_detail,
        },
        '_commodity_pressure_for_payload': commodity_pressure_data,
        'version': '2.2.0-commodity-aware'
    }

# ========================================
# TRENDS
# ========================================

def get_israel_trends(days=30):
    """Return sparkline-ready trend data from Redis history."""
    try:
        cache = load_israel_cache()
        history = cache.get('history', {})
        if not history:
            return {'success': False, 'message': 'Building trend data...', 'days_collected': 0}

        dates = sorted(history.keys(), reverse=True)[:days]
        dates.reverse()

        trends = {
            'dates': [],
            'stability': [],
            'nis_rate': [],
            'tase': [],
            'conflict_score': [],
            'coalition_score': []
        }
        for d in dates:
            snap = history[d]
            trends['dates'].append(d)
            trends['stability'].append(snap.get('stability_score', 0))
            trends['nis_rate'].append(snap.get('nis_usd', 0))
            trends['tase'].append(snap.get('tase_value', 0))
            trends['conflict_score'].append(snap.get('conflict_score', 0))
            trends['coalition_score'].append(snap.get('coalition_score', 0))

        return {
            'success': True,
            'days_collected': len(dates),
            'trends': trends,
            'storage': 'redis' if _redis_available() else 'tmp_file'
        }
    except Exception as e:
        return {'success': False, 'message': str(e), 'days_collected': 0}

# ========================================
# API ENDPOINTS
# ========================================

def scan_israel_stability():
    """Main Israel stability endpoint — runs all modules and returns full payload."""
    try:
        force_refresh = request.args.get('refresh', '').lower() == 'true'
        print(f"[Israel] Starting full scan (refresh={force_refresh})...")

        # Check cache unless forced refresh
        if not force_refresh and _redis_available():
            cached = _redis_get(REDIS_CACHE_KEY)
            if cached and cached.get('last_updated'):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached['last_updated'])).total_seconds()
                if age < CACHE_TTL_SECONDS:
                    print(f"[Israel] ✅ Returning cached data ({int(age/60)}m old)")
                    cached['from_cache'] = True
                    return jsonify(cached)

        # Run all modules
        economic  = fetch_nis_usd()
        tase      = fetch_tase_index()
        eis       = fetch_eis_etf()   # v1.0.0 — Financial Pulse Card (May 29 2026)
        conflict  = scan_israel_conflict(days=7)
        knesset   = scan_knesset_news()
        strikes   = fetch_acled_strikes()
        leadership = build_leadership_status(conflict, knesset)
        stability = calculate_israel_stability(economic, tase, conflict, knesset, strikes)

        # Build canonical Financial Pulse Card payload (3 tiles + market_status)
        financial_pulse = build_israel_financial_pulse(economic, tase, eis)

        # Build today's history snapshot
        snapshot = {
            'stability_score': stability['score'],
            'nis_usd': economic.get('usd_to_ils', 0),
            'tase_value': tase.get('value', 0),
            'eis_value': eis.get('value', 0),    # v1.0.0 — Financial Pulse
            'conflict_score': conflict.get('conflict_score', 0),
            'coalition_score': conflict.get('coalition_score', 0),
            'hostage_articles': conflict.get('hostage_article_count', 0),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        update_israel_history(snapshot)

        # Pull commodity pressure off stability (private handoff key from calc)
        commodity_pressure_for_response = stability.pop('_commodity_pressure_for_payload', None)

        payload = {
            'success': True,
            'stability': stability,
            'commodity_pressure': commodity_pressure_for_response,
            'economic': {
                'nis': economic,
                'tase': tase,
                'eis': eis,                          # v1.0.0 — Financial Pulse
            },
            'financial_pulse': financial_pulse,      # v1.0.0 canonical 3-tile card payload
            'conflict': {
                'score': conflict.get('conflict_score', 0),
                'coalition_score': conflict.get('coalition_score', 0),
                # v2.1.0 — new fields
                'elections_proximity_score': conflict.get('elections_proximity_score', 0),
                'opposition_mentions': conflict.get('opposition_mentions', 0),
                'elections_mentions': conflict.get('elections_mentions', 0),
                'opposition_articles': conflict.get('articles', {}).get('opposition', [])[:6],
                'elections_articles': conflict.get('articles', {}).get('elections', [])[:6],
                # Other content
                'war_articles': conflict.get('articles', {}).get('war', [])[:8],
                'coalition_articles': conflict.get('articles', {}).get('coalition', [])[:5],
                'hostage_articles': conflict.get('articles', {}).get('hostage', [])[:5],
                'bennett_articles': conflict.get('articles', {}).get('bennett', [])[:4],     # legacy, kept for backward compat
                'ceasefire_active': conflict.get('ceasefire_active', False),
                'high_severity_count': conflict.get('high_severity_count', 0),
                'bennett_mentions': conflict.get('bennett_mentions', 0)                       # legacy, kept for backward compat
            },
            'strikes': {
                'source': strikes.get('source'),
                'event_count': strikes.get('event_count', 0),
                'events': strikes.get('events', [])[:50],
                'articles': strikes.get('articles', [])[:10],
                'acled_available': strikes.get('acled_available', False),
                'acled_note': strikes.get('acled_note', '')
            },
            'knesset': {
                'coalition': knesset.get('coalition_data', {}),
                'election_signal_count': knesset.get('election_signal_count', 0),
                'election_signals': knesset.get('election_signals', []),
                'articles': knesset.get('articles', [])[:10]
            },
            'leadership': leadership,
            'all_articles': conflict.get('all_articles', [])[:30],
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'version': '1.0.0-israel',
            'from_cache': False
        }

        # Cache the full payload — but only if TASE data is valid
        # If TASE is unavailable, use shorter TTL so it retries sooner
        tase_ok = payload.get('economic', {}).get('tase', {}).get('value') is not None
        cache_ttl = CACHE_TTL_SECONDS if tase_ok else 30 * 60  # 30 min retry if TASE failed
        if _redis_available():
            _redis_set(REDIS_CACHE_KEY, payload, ex=cache_ttl)
        if not tase_ok:
            print("[Israel] ⚠️ TASE unavailable — cache TTL set to 30min for retry")

        return jsonify(payload)

    except Exception as e:
        print(f"[Israel] ❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


def api_israel_trends():
    """Sparkline trend data endpoint."""
    try:
        days = min(int(request.args.get('days', 30)), 90)
        return jsonify(get_israel_trends(days))
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'days_collected': 0}), 500


def api_israel_leadership():
    """Leadership status badges — lightweight, no full scan."""
    return jsonify({
        'success': True,
        'figures': POLITICAL_FIGURES,
        'coalition': COALITION_DATA,
        'last_updated': datetime.now(timezone.utc).isoformat()
    })


def api_israel_strikes():
    """Strike/incident data for heatmap."""
    try:
        data = fetch_acled_strikes()
        return jsonify({'success': True, **data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def robots():
    return "User-agent: *\nDisallow: /\n", 200, {'Content-Type': 'text/plain'}


def register_israel_stability_endpoints(flask_app):
    flask_app.add_url_rule('/scan-israel-stability', view_func=scan_israel_stability, methods=['GET'])
    flask_app.add_url_rule('/api/israel-trends', view_func=api_israel_trends, methods=['GET'])
    flask_app.add_url_rule('/api/israel-leadership', view_func=api_israel_leadership, methods=['GET'])
    flask_app.add_url_rule('/api/israel-strikes', view_func=api_israel_strikes, methods=['GET'])
    flask_app.add_url_rule('/robots.txt', view_func=robots)
    print("[Israel Stability] ✅ Routes registered")
