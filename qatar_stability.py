# -*- coding: utf-8 -*-
"""
Qatar Stability Backend — v0.5.0 (May 29 2026)
=====================================================

Lives on the ME backend (asifah-backend.onrender.com) alongside Israel, Lebanon,
Iran, Iraq. This v0.5 ships:
  - QSE QSI index fetcher (Yahoo ^QSI)
  - QNB (Qatar National Bank) fetcher (Yahoo QNBK.QA)
  - Brent crude full Financial Pulse fetcher (Yahoo BZ=F, with sparkline)
  - Per-tile market_status logic (QSE Sun-Thu, QNB same as QSE, Brent ICE 24/5)
  - Aggregate market_status (open/closed/pre-market/after-hours/partial)
  - Canonical Financial Pulse Card payload assembly
  - Hardened Google News RSS fetcher (curl_cffi + {*} namespace wildcard)
  - Background refresh loop (12h cycle)

v0.5 explicitly does NOT include:
  - Stability vector scoring (deferred to v1.0)
  - Rhetoric tracker integration (Qatar has no tracker yet)
  - Humanitarian module
  - Knowledge Library content

Patterns mirrored from israel_stability.py / china_stability.py for consistency.
"""

import os
import json
import time
import threading
import requests
import xml.etree.ElementTree as ET
import urllib.parse
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

# curl_cffi: TLS/JA3 fingerprint impersonation for RSS feeds blocked by Cloudflare
# at the network layer. v1.5.0 (May 29 2026 — cascaded from us_stability.py).
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    curl_requests = None
    CURL_CFFI_AVAILABLE = False
    print("[Qatar Stability] WARNING: curl_cffi not installed — TLS impersonation unavailable")


# ============================================
# CONFIG
# ============================================

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_REST_URL') or os.environ.get('UPSTASH_REDIS_URL', '')).rstrip('/')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN') or os.environ.get('UPSTASH_REDIS_TOKEN', '')
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY', '')

CACHE_KEY = 'qatar_stability_v0.5'
HISTORY_KEY = 'qatar_stability_history'
CACHE_TTL = 12 * 3600  # 12 hours


# ============================================
# REDIS HELPERS
# ============================================

def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        url = f"{UPSTASH_REDIS_URL}/get/{key}"
        headers = {'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = data.get('result')
            if result:
                try:
                    return json.loads(result)
                except (json.JSONDecodeError, TypeError):
                    return result
    except Exception as e:
        print(f"[Qatar Stability] Redis GET error: {str(e)[:80]}")
    return None


def _redis_set(key, value, ttl=None):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        url = UPSTASH_REDIS_URL
        headers = {
            'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
            'Content-Type': 'application/json',
        }
        payload = ['SET', key, json.dumps(value)]
        if ttl:
            payload.extend(['EX', str(ttl)])
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Qatar Stability] Redis SET error: {str(e)[:80]}")
    return False


def _redis_lpush_trim(key, value, max_len=168):
    """Append to a Redis list and trim to max_len entries."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        url = UPSTASH_REDIS_URL
        headers = {
            'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
            'Content-Type': 'application/json',
        }
        # LPUSH
        r = requests.post(url, headers=headers,
                          json=['LPUSH', key, json.dumps(value)],
                          timeout=10)
        # LTRIM to keep latest N
        requests.post(url, headers=headers,
                      json=['LTRIM', key, '0', str(max_len - 1)],
                      timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Qatar Stability] Redis LPUSH error: {str(e)[:80]}")
    return False


# ============================================
# FINANCIAL PULSE — TILE FETCHERS
# ============================================

def _fetch_qse_index():
    """
    Fetch QSE QSI index (^QSI) from Yahoo Finance.
    The QSI is the main equity benchmark of Qatar, tracking ~200+ stocks.
    Returns Financial Pulse-shaped dict.
    v0.5.1 — Qatar Financial Pulse (May 30 2026) — corrected ticker to ^QSI.
    """
    print("[Qatar Stability] Fetching QSE QSI (^QSI)...")
    QSI_LAST_KNOWN_KEY = 'tasi_last_known'
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EQSI"
        r = requests.get(url, params={'interval': '1d', 'range': '1mo'},
                         timeout=10,
                         headers={'User-Agent': 'Mozilla/5.0 (AsifahAnalytics/1.0)'})
        if r.status_code == 200:
            data = r.json()
            result = (data.get('chart', {}).get('result') or [{}])[0]
            meta = result.get('meta', {})
            price = meta.get('regularMarketPrice')
            # v0.5.1 fix (May 30 2026): previousClose = yesterday's close (correct for 24h%);
            # chartPreviousClose = first datapoint in chart range (gives MONTHLY% not 24h%)
            prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
            if price is not None and prev_close not in (None, 0):
                change_pct = ((price - prev_close) / prev_close) * 100
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
                except Exception:
                    pass
                print(f"[Qatar Stability] QSI: {price:,.2f} ({change_pct:+.2f}%)")
                payload = {
                    'index': 'QSI',
                    'value': round(float(price), 2),
                    'change_pct_24h': round(change_pct, 3),
                    'trend': 'rising' if change_pct > 0.3 else ('falling' if change_pct < -0.3 else 'flat'),
                    'source': 'Yahoo Finance',
                    'sparkline': sparkline,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }
                # Cache for last-known fallback (7-day TTL)
                try:
                    _redis_set(QSI_LAST_KNOWN_KEY, {
                        'value': payload['value'],
                        'change_pct_24h': payload['change_pct_24h'],
                    }, ttl=7 * 24 * 3600)
                except Exception:
                    pass
                return payload
    except Exception as e:
        print(f"[Qatar Stability] QSI fetch error: {str(e)[:80]}")

    # Last-known fallback
    try:
        cached = _redis_get(QSI_LAST_KNOWN_KEY)
        if cached:
            return {
                'index': 'QSI',
                'value': cached.get('value'),
                'change_pct_24h': cached.get('change_pct_24h', 0),
                'trend': 'unknown',
                'source': 'Yahoo Finance (last known)',
                'sparkline': [],
                'estimated': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        pass

    return {
        'index': 'QSI',
        'value': None,
        'change_pct_24h': 0,
        'trend': 'unknown',
        'source': 'Unavailable',
        'sparkline': [],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


def _fetch_qnb_stock():
    """
    Fetch QNB (Qatar National Bank) stock (QNBK.QA) from Yahoo Finance.
    QNB is the world's largest oil company by revenue, ~98% state-owned by
    Qatar government / PIF, and the single most important Qatar-specific equity
    signal. Qatar Vision 2030 anchor.
    v0.5.0 — Qatar Financial Pulse (May 29 2026).
    """
    print("[Qatar Stability] Fetching QNB (Qatar National Bank) (QNBK.QA)...")
    ARAMCO_LAST_KNOWN_KEY = 'qnb_last_known'
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/QNBK.QA"
        r = requests.get(url, params={'interval': '1d', 'range': '1mo'},
                         timeout=10,
                         headers={'User-Agent': 'Mozilla/5.0 (AsifahAnalytics/1.0)'})
        if r.status_code == 200:
            data = r.json()
            result = (data.get('chart', {}).get('result') or [{}])[0]
            meta = result.get('meta', {})
            price = meta.get('regularMarketPrice')
            # v0.5.1 fix (May 30 2026): previousClose = yesterday's close (correct for 24h%);
            # chartPreviousClose = first datapoint in chart range (gives MONTHLY% not 24h%)
            prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
            if price is not None and prev_close not in (None, 0):
                change_pct = ((price - prev_close) / prev_close) * 100
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
                except Exception:
                    pass
                print(f"[Qatar Stability] QNB: SAR {price:.2f} ({change_pct:+.2f}%)")
                payload = {
                    'index': 'ARAMCO',
                    'value': round(float(price), 2),
                    'change_pct_24h': round(change_pct, 3),
                    'trend': 'rising' if change_pct > 0.3 else ('falling' if change_pct < -0.3 else 'flat'),
                    'source': 'Yahoo Finance',
                    'sparkline': sparkline,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }
                try:
                    _redis_set(ARAMCO_LAST_KNOWN_KEY, {
                        'value': payload['value'],
                        'change_pct_24h': payload['change_pct_24h'],
                    }, ttl=7 * 24 * 3600)
                except Exception:
                    pass
                return payload
    except Exception as e:
        print(f"[Qatar Stability] QNB fetch error: {str(e)[:80]}")

    # Last-known fallback
    try:
        cached = _redis_get(ARAMCO_LAST_KNOWN_KEY)
        if cached:
            return {
                'index': 'ARAMCO',
                'value': cached.get('value'),
                'change_pct_24h': cached.get('change_pct_24h', 0),
                'trend': 'unknown',
                'source': 'Yahoo Finance (last known)',
                'sparkline': [],
                'estimated': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        pass

    return {
        'index': 'ARAMCO',
        'value': None,
        'change_pct_24h': 0,
        'trend': 'unknown',
        'source': 'Unavailable',
        'sparkline': [],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


def _fetch_brent_full():
    """
    Fetch Brent Crude oil (BZ=F) with sparkline (Financial Pulse-shaped).
    Note: ME backend may already have a _fetch_brent_price() that returns a tuple.
    This function returns the FULL Financial Pulse tile shape with sparkline.
    Distinct from the tuple-style fetcher used by older stability scoring.
    v0.5.0 — Qatar Financial Pulse (May 29 2026).
    """
    print("[Qatar Stability] Fetching Brent Crude full (BZ=F)...")
    BRENT_LAST_KNOWN_KEY = 'brent_full_last_known'
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F"
        r = requests.get(url, params={'interval': '1d', 'range': '1mo'},
                         timeout=10,
                         headers={'User-Agent': 'Mozilla/5.0 (AsifahAnalytics/1.0)'})
        if r.status_code == 200:
            data = r.json()
            result = (data.get('chart', {}).get('result') or [{}])[0]
            meta = result.get('meta', {})
            price = meta.get('regularMarketPrice')
            # v0.5.1 fix (May 30 2026): previousClose = yesterday's close (correct for 24h%);
            # chartPreviousClose = first datapoint in chart range (gives MONTHLY% not 24h%)
            prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
            if price is not None and prev_close not in (None, 0):
                change_pct = ((price - prev_close) / prev_close) * 100
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
                except Exception:
                    pass
                print(f"[Qatar Stability] Brent: ${price:.2f} ({change_pct:+.2f}%)")
                payload = {
                    'index': 'BRENT',
                    'value': round(float(price), 2),
                    'change_pct_24h': round(change_pct, 3),
                    'trend': 'rising' if change_pct > 0.3 else ('falling' if change_pct < -0.3 else 'flat'),
                    'source': 'Yahoo Finance (ICE Brent)',
                    'sparkline': sparkline,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }
                try:
                    _redis_set(BRENT_LAST_KNOWN_KEY, {
                        'value': payload['value'],
                        'change_pct_24h': payload['change_pct_24h'],
                    }, ttl=7 * 24 * 3600)
                except Exception:
                    pass
                return payload
    except Exception as e:
        print(f"[Qatar Stability] Brent fetch error: {str(e)[:80]}")

    # Last-known fallback
    try:
        cached = _redis_get(BRENT_LAST_KNOWN_KEY)
        if cached:
            return {
                'index': 'BRENT',
                'value': cached.get('value'),
                'change_pct_24h': cached.get('change_pct_24h', 0),
                'trend': 'unknown',
                'source': 'Yahoo Finance (last known)',
                'sparkline': [],
                'estimated': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        pass

    return {
        'index': 'BRENT',
        'value': None,
        'change_pct_24h': 0,
        'trend': 'unknown',
        'source': 'Unavailable',
        'sparkline': [],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


# ============================================
# MARKET STATUS COMPUTATIONS
# ============================================

def _fetch_ttf_gas():
    """
    Dutch TTF natural gas front-month (Yahoo TTF=F) -- the LNG-demand proxy.
    For Qatar this is the demand-side price signal for its defining export:
    EU gas stress reprices Qatari LNG cargo economics in near-real-time.
    Verify-on-deploy: if TTF=F is unavailable, tile shows last-known/null honestly.
    """
    print("[Qatar Stability] Fetching TTF gas (TTF=F)...")
    TTF_LAST_KNOWN_KEY = 'ttf_last_known'
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/TTF%3DF"
        params = {'interval': '1h', 'range': '5d'}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; AsifahAnalytics/1.0)'}
        r = requests.get(url, params=params, headers=headers, timeout=12)
        data = r.json()
        result_data = data.get('chart', {}).get('result', [None])[0]
        if result_data:
            closes = [c for c in result_data.get('indicators', {}).get('quote', [{}])[0].get('close', []) if c]
            meta = result_data.get('meta', {})
            price = meta.get('regularMarketPrice') or (closes[-1] if closes else None)
            prev = meta.get('chartPreviousClose') or (closes[-25] if len(closes) > 25 else (closes[0] if closes else None))
            if price:
                change_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
                out = {'index': 'TTF', 'value': round(price, 2), 'change_pct_24h': change_pct,
                       'trend': 'up' if change_pct > 0.3 else ('down' if change_pct < -0.3 else 'flat'),
                       'source': 'Yahoo Finance (ICE Endex TTF)',
                       'timestamp': datetime.now(timezone.utc).isoformat(),
                       'sparkline': [round(c, 2) for c in closes[-24:]]}
                _redis_set(TTF_LAST_KNOWN_KEY, out, ttl=7*24*3600)
                print(f"[Qatar Stability] TTF: {price:,.2f} ({change_pct:+.2f}%)")
                return out
    except Exception as e:
        print(f"[Qatar Stability] TTF fetch error: {str(e)[:120]}")
    lk = _redis_get(TTF_LAST_KNOWN_KEY)
    return lk if lk else {'index': 'TTF', 'value': None, 'change_pct_24h': 0, 'trend': 'flat',
                          'source': 'unavailable', 'timestamp': None, 'sparkline': []}


def _compute_market_status_qse():
    """
    QSE (Qatar Stock Exchange) hours:
      Sun-Thu, 10:00-15:00 Arabian Standard Time (AST = UTC+3, no DST).
      Friday/Saturday: closed.
      Pre-open auction: 09:30-10:00.
    """
    qatar_tz = timezone(timedelta(hours=3))
    now_qatar = datetime.now(qatar_tz)
    weekday = now_qatar.weekday()  # Mon=0 ... Sun=6
    minutes = now_qatar.hour * 60 + now_qatar.minute

    # Friday=4, Saturday=5: weekend, market closed
    if weekday in (4, 5):
        return 'closed'

    # Trading days (Sun-Thu)
    if 540 <= minutes < 570:    # 09:00-09:30 pre-open auction
        return 'pre-market'
    if 570 <= minutes <= 795:   # 09:30-13:15 main session (QSE)
        return 'open'
    if 795 < minutes <= 900:    # 13:15-15:00 after-hours
        return 'after-hours'
    return 'closed'


def _compute_market_status_brent():
    """
    ICE Brent crude futures hours:
      Sun 19:00 ET → Fri 18:00 ET, with a 60-min break each day.
      Simplified: Mon-Fri = open; Sat = closed; Sun morning closed, Sun evening open.
      For Financial Pulse purposes: treat as 'open' Mon-Fri, 'closed' Sat,
      and 'closed' on Sunday before 19:00 ET / open after.
    """
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()  # Mon=0 ... Sun=6

    # Saturday: closed
    if weekday == 5:
        return 'closed'

    # Sunday: closed until 19:00 ET (23:00 UTC)
    if weekday == 6:
        if now_utc.hour < 23:
            return 'closed'
        return 'open'

    # Friday: closed after 18:00 ET (22:00 UTC)
    if weekday == 4 and now_utc.hour >= 22:
        return 'closed'

    # Mon-Thu and Fri-before-18:00-ET: open
    return 'open'


def _compute_market_status_aggregate(statuses):
    """Aggregate per-tile statuses into card-header pill state.
    Rules:
      - All 'open' -> 'open'
      - All 'closed' -> 'closed'
      - Mixed (some open, some not) -> 'partial'
      - No 'open' but pre-market present -> 'pre-market'
      - No 'open' but after-hours present -> 'after-hours'
    """
    if not statuses:
        return 'closed'
    unique = set(statuses)
    if unique == {'open'}:
        return 'open'
    if unique == {'closed'}:
        return 'closed'
    if 'open' in unique:
        return 'partial'
    if 'pre-market' in unique:
        return 'pre-market'
    if 'after-hours' in unique:
        return 'after-hours'
    return 'closed'


# ============================================
# FINANCIAL PULSE CARD ASSEMBLY
# ============================================

def build_qatar_financial_pulse(qse_data, qnb_data, brent_data, ttf_data):
    """
    Assemble the canonical Financial Pulse Card payload for Qatar.

    Three tiles: QSE QSI, QNB (Qatar National Bank), Brent Crude.
    Per-tile market_status + aggregate card-level status.
    All three tiles use STANDARD polarity (rising = good, falling = stress).

    Note on QNB market_status: QNB trades on QSE, so its hours
    match the QSE session.

    v0.5.0 — Qatar Financial Pulse Card (May 29 2026).
    """
    qse_status = _compute_market_status_qse()
    qnb_status  = qse_status  # QNB trades on QSE, same hours
    brent_status   = _compute_market_status_brent()

    aggregate = _compute_market_status_aggregate([qse_status, qnb_status, brent_status])

    def _tier(chg):
        """Standard polarity tier: rising = good, falling = stress."""
        if chg <= -2:  return 'stress'
        if chg <= -1:  return 'warning'
        if chg >= 2:   return 'rally'
        return 'stable'

    # QSE tile
    tasi_chg = qse_data.get('change_pct_24h', 0) or 0
    tasi_tile = {
        'name':           'QSE QSI',
        'ticker':         'QSI',
        'value':          qse_data.get('value'),
        'change_pct_24h': tasi_chg,
        'trend':          qse_data.get('trend', 'flat'),
        'tier':           _tier(tasi_chg),
        'source':         qse_data.get('source', 'Yahoo Finance'),
        'market_status':  qse_status,
        'timestamp':      qse_data.get('timestamp'),
        'sparkline':      qse_data.get('sparkline', []),
    }

    # QNB (Qatar National Bank) tile
    qnb_chg = qnb_data.get('change_pct_24h', 0) or 0
    qnb_tile = {
        'name':           'QNB (Qatar National Bank)',
        'ticker':         'QNBK.QA',
        'value':          qnb_data.get('value'),
        'change_pct_24h': qnb_chg,
        'trend':          qnb_data.get('trend', 'flat'),
        'tier':           _tier(qnb_chg),
        'source':         qnb_data.get('source', 'Yahoo Finance'),
        'market_status':  qnb_status,
        'timestamp':      qnb_data.get('timestamp'),
        'sparkline':      qnb_data.get('sparkline', []),
    }

    # Brent Crude tile
    brent_chg = brent_data.get('change_pct_24h', 0) or 0
    brent_tile = {
        'name':           'Brent Crude',
        'ticker':         'BZ=F',
        'value':          brent_data.get('value'),
        'change_pct_24h': brent_chg,
        'trend':          brent_data.get('trend', 'flat'),
        'tier':           _tier(brent_chg),
        'source':         brent_data.get('source', 'Yahoo Finance (ICE Brent)'),
        'market_status':  brent_status,
        'timestamp':      brent_data.get('timestamp'),
        'sparkline':      brent_data.get('sparkline', []),
    }

    # TTF gas tile (LNG-demand proxy -- Qatar's defining export signal)
    ttf_chg = ttf_data.get('change_pct_24h', 0) or 0
    ttf_tile = {
        'name':           'TTF Gas (EU)',
        'ticker':         'TTF=F',
        'value':          ttf_data.get('value'),
        'change_pct_24h': ttf_chg,
        'trend':          ttf_data.get('trend', 'flat'),
        'tier':           _tier(ttf_chg),
        'source':         ttf_data.get('source', 'Yahoo Finance (ICE Endex TTF)'),
        'market_status':  brent_status,
        'timestamp':      ttf_data.get('timestamp'),
        'sparkline':      ttf_data.get('sparkline', []),
    }

    return {
        'country':        'QA',
        'card_label':     'Qatar Financial Pulse',
        'market_status':  aggregate,
        'last_refreshed': datetime.now(timezone.utc).isoformat(),
        'tiles': {
            'TADAWUL': tasi_tile,
            'ARAMCO':  qnb_tile,
            'BRENT':   brent_tile,
            'TTF':     ttf_tile,
        },
    }


# ============================================
# HARDENED GOOGLE NEWS RSS (v1.5.2 cascade)
# ============================================

def _fetch_google_news_rss(query, label, max_items=15):
    """Hardened RSS fetcher with three-tier defense:
       - Chrome 130 + Client Hints headers
       - Firefox UA fallback on 403
       - curl_cffi TLS impersonation on persistent 403
       - {*} namespace wildcard XML parser
    v1.5.2 (May 29 2026) — baked in from start for Qatar.
    """
    articles = []
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"
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
        resp = requests.get(url, timeout=(5, 15), headers=headers, allow_redirects=True)
        # Tier 2: Firefox UA on 403
        if resp.status_code == 403:
            print(f"[Qatar Stability] GNews '{label}': HTTP 403 — retrying with Firefox UA")
            firefox_headers = dict(headers)
            firefox_headers['User-Agent'] = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) '
                                              'Gecko/20100101 Firefox/130.0')
            firefox_headers.pop('Sec-Ch-Ua', None)
            firefox_headers.pop('Sec-Ch-Ua-Mobile', None)
            firefox_headers.pop('Sec-Ch-Ua-Platform', None)
            firefox_headers['Referer'] = 'https://duckduckgo.com/'
            time.sleep(1.2)
            resp = requests.get(url, timeout=(5, 15), headers=firefox_headers, allow_redirects=True)
        # Tier 3: curl_cffi TLS impersonation
        if resp.status_code == 403 and CURL_CFFI_AVAILABLE:
            print(f"[Qatar Stability] GNews '{label}': HTTP 403 — retrying with curl_cffi TLS impersonation")
            try:
                time.sleep(0.8)
                cc_resp = curl_requests.get(url, impersonate='chrome',
                                            timeout=15, allow_redirects=True)
                if cc_resp.status_code == 200:
                    class _CCWrapper:
                        def __init__(self, cc):
                            self.status_code = cc.status_code
                            self.content = cc.content
                            self.text = cc.text
                    resp = _CCWrapper(cc_resp)
                    print(f"[Qatar Stability] GNews '{label}': curl_cffi rescued")
                else:
                    print(f"[Qatar Stability] GNews '{label}': curl_cffi also got HTTP {cc_resp.status_code}")
            except Exception as cc_err:
                print(f"[Qatar Stability] GNews '{label}': curl_cffi error {str(cc_err)[:100]}")
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            # {*} wildcard namespace parser
            all_items = (root.findall('.//{*}item') or
                         root.findall('.//{*}entry'))
            for item in all_items[:max_items]:
                title_el = item.find('{*}title')
                link_el  = item.find('{*}link')
                pub_el   = item.find('{*}pubDate')
                if title_el is not None and title_el.text:
                    link_text = ''
                    if link_el is not None:
                        link_text = (link_el.text or link_el.get('href') or '').strip()
                    articles.append({
                        'title':       title_el.text.strip(),
                        'description': title_el.text.strip(),
                        'url':         link_text,
                        'publishedAt': pub_el.text if (pub_el is not None and pub_el.text) else '',
                        'source':      {'name': label},
                        'content':     title_el.text.strip(),
                        'language':    'en',
                    })
        print(f"[Qatar Stability] GNews '{label}': {len(articles)} articles")
    except Exception as e:
        print(f"[Qatar Stability] GNews error: {str(e)[:80]}")
    return articles


# ============================================
# MAIN SCAN ORCHESTRATOR
# ============================================

def run_qatar_stability_scan():
    """Full Qatar stability scan. v0.5: economic indicators only.
    Returns the canonical payload with financial_pulse + articles.
    """
    scan_start = time.time()
    print(f"\n[Qatar Stability] Starting scan at {datetime.now(timezone.utc).isoformat()}")

    # Fetch live financial indicators
    qse = _fetch_qse_index()
    qnb  = _fetch_qnb_stock()
    brent   = _fetch_brent_full()
    ttf     = _fetch_ttf_gas()

    # Build canonical Financial Pulse Card payload
    financial_pulse = build_qatar_financial_pulse(qse, qnb, brent, ttf)

    # Fetch articles (light scan; v0.5 doesn't score them, just surfaces them)
    all_articles = []
    queries = [
        ('Qatar Iran US mediation talks Doha', 'GNews:Qatar Mediation'),
        ('Qatar North Field LNG QatarEnergy expansion', 'GNews:Qatar LNG'),
        ('Al Udeid air base US forces Qatar', 'GNews:Al Udeid'),
        ('Qatar Saudi UAE GCC relations', 'GNews:GCC Cohesion'),
        ('Qatar Turkey military base defense', 'GNews:Qatar-Turkey'),
        ('Qatar economy sovereign wealth QIA', 'GNews:Qatar Economy'),
        ('Qatar Hamas Gaza negotiations', 'GNews:Qatar Gaza File'),
    ]
    for query, label in queries:
        try:
            all_articles.extend(_fetch_google_news_rss(query, label))
            time.sleep(0.3)
        except Exception as e:
            print(f"[Qatar Stability] GNews error {label}: {str(e)[:60]}")

    # Deduplicate articles by URL
    seen = set()
    deduped = []
    for art in all_articles:
        url = (art.get('url') or '').strip()
        if url and url not in seen:
            seen.add(url)
            deduped.append(art)

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success':           True,
        'country':           'QA',
        'country_name':      'Qatar',
        'scanned_at':        datetime.now(timezone.utc).isoformat(),
        'scan_duration_sec': scan_time,

        # Financial Pulse Card payload
        'financial_pulse':   financial_pulse,

        # Individual tile data (also exposed top-level for convenience)
        'qse':           qse,
        'qnb':            qnb,
        'brent':             brent,
        'ttf':               ttf,

        # Articles
        'articles':          deduped[:60],
        'total_articles':    len(deduped),

        'version': '1.0.0-qatar-stability',
    }

    # Cache to Redis
    _redis_set(CACHE_KEY, result, ttl=CACHE_TTL)

    # Lightweight history snapshot
    _redis_lpush_trim(HISTORY_KEY, {
        'ts':             datetime.now(timezone.utc).isoformat(),
        'tasi_value':     qse.get('value'),
        'qnb_value':   qnb.get('value'),
        'brent_value':    brent.get('value'),
        'market_status':  financial_pulse.get('market_status'),
    })

    print(f"[Qatar Stability] Scan complete in {scan_time}s | "
          f"QSI={qse.get('value')} · QNB={qnb.get('value')} · "
          f"Brent={brent.get('value')} · {len(deduped)} articles")
    return result


# ============================================
# BACKGROUND REFRESH
# ============================================

def _background_loop():
    print("[Qatar Stability] Background thread started (12h cycle)")
    time.sleep(300)   # 5 min stagger after boot (avoid contention with other backends)
    while True:
        try:
            print("[Qatar Stability] Background refresh triggered")
            run_qatar_stability_scan()
        except Exception as e:
            print(f"[Qatar Stability] Background scan error: {str(e)[:120]}")
        time.sleep(12 * 3600)


# ============================================
# FLASK ENDPOINTS
# ============================================

def register_qatar_stability_endpoints(app):
    """Register Qatar stability endpoints on the provided Flask app.
    Endpoints:
      GET /api/qatar/stability              — full payload (Redis-cached)
      GET /api/qatar/stability?force=true   — force fresh scan, bypass cache
      GET /api/qatar/stability/summary      — lightweight cached subset
      GET /api/qatar/stability/history      — recent history snapshots
    """

    @app.route('/api/qatar/stability', methods=['GET'])
    def api_qatar_stability():
        """Return full Qatar stability payload. ?force=true bypasses Redis cache."""
        force = request.args.get('force', '').lower() == 'true'

        if not force:
            cached = _redis_get(CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return jsonify(cached)

        # Live scan
        try:
            result = run_qatar_stability_scan()
            result['from_cache'] = False
            return jsonify(result)
        except Exception as e:
            print(f"[Qatar Stability] Scan error: {str(e)[:200]}")
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/qatar/stability/summary', methods=['GET'])
    def api_qatar_stability_summary():
        """Lightweight cached subset — used for header/index pages."""
        cached = _redis_get(CACHE_KEY) or {}
        return jsonify({
            'country':          'SA',
            'country_name':     'Qatar',
            'scanned_at':       cached.get('scanned_at'),
            'qse':          cached.get('qse', {}),
            'qnb':           cached.get('qnb', {}),
            'brent':            cached.get('brent', {}),
            'financial_pulse':  cached.get('financial_pulse', {}),
            'version':          '0.5.0-qatar-stability',
        })

    @app.route('/api/qatar/stability/history', methods=['GET'])
    def api_qatar_stability_history():
        """Return Qatar stability history for trend chart."""
        history = _redis_get(HISTORY_KEY)
        if not isinstance(history, list):
            history = []
        return jsonify({
            'success': True,
            'history': history,
            'count':   len(history),
        })

    # Start background refresh thread
    t = threading.Thread(target=_background_loop, daemon=True)
    t.start()

    print("[Qatar Stability] ✅ Endpoints registered: /api/qatar/stability (+ /summary, /history)")
