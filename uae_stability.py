# -*- coding: utf-8 -*-
"""
UAE Stability Backend — v0.5.0 (May 29 2026)
=====================================================

Lives on the ME backend (asifah-backend.onrender.com) alongside Israel, Lebanon,
Iran, Iraq. This v0.5 ships:
  - DFM DFMGI index fetcher (Yahoo ^DFMGI)
  - ADX General (Abu Dhabi) fetcher (Yahoo ^ADI)
  - Brent crude full Financial Pulse fetcher (Yahoo BZ=F, with sparkline)
  - Per-tile market_status logic (DFM Mon-Fri, ADX same as DFM, Brent ICE 24/5)
  - Aggregate market_status (open/closed/pre-market/after-hours/partial)
  - Canonical Financial Pulse Card payload assembly
  - Hardened Google News RSS fetcher (curl_cffi + {*} namespace wildcard)
  - Background refresh loop (12h cycle)

v0.5 explicitly does NOT include:
  - Stability vector scoring (deferred to v1.0)
  - Rhetoric tracker integration (UAE has no tracker yet)
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
    print("[UAE Stability] WARNING: curl_cffi not installed — TLS impersonation unavailable")


# ============================================
# CONFIG
# ============================================

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_REST_URL') or os.environ.get('UPSTASH_REDIS_URL', '')).rstrip('/')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN') or os.environ.get('UPSTASH_REDIS_TOKEN', '')
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY', '')

CACHE_KEY = 'uae_stability_v0.5'
HISTORY_KEY = 'uae_stability_history'
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
        print(f"[UAE Stability] Redis GET error: {str(e)[:80]}")
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
        print(f"[UAE Stability] Redis SET error: {str(e)[:80]}")
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
        print(f"[UAE Stability] Redis LPUSH error: {str(e)[:80]}")
    return False


# ============================================
# FINANCIAL PULSE — TILE FETCHERS
# ============================================

def _fetch_dfm_index():
    """
    Fetch DFM DFMGI index (^DFMGI) from Yahoo Finance.
    The DFMGI is the main equity benchmark of UAE, tracking ~200+ stocks.
    Returns Financial Pulse-shaped dict.
    v0.5.1 — UAE Financial Pulse (May 30 2026) — corrected ticker to ^DFMGI.
    """
    print("[UAE Stability] Fetching DFM DFMGI (^DFMGI)...")
    DFMGI_LAST_KNOWN_KEY = 'tasi_last_known'
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EDFMGI"
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
                print(f"[UAE Stability] DFMGI: {price:,.2f} ({change_pct:+.2f}%)")
                payload = {
                    'index': 'DFMGI',
                    'value': round(float(price), 2),
                    'change_pct_24h': round(change_pct, 3),
                    'trend': 'rising' if change_pct > 0.3 else ('falling' if change_pct < -0.3 else 'flat'),
                    'source': 'Yahoo Finance',
                    'sparkline': sparkline,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }
                # Cache for last-known fallback (7-day TTL)
                try:
                    _redis_set(DFMGI_LAST_KNOWN_KEY, {
                        'value': payload['value'],
                        'change_pct_24h': payload['change_pct_24h'],
                    }, ttl=7 * 24 * 3600)
                except Exception:
                    pass
                return payload
    except Exception as e:
        print(f"[UAE Stability] DFMGI fetch error: {str(e)[:80]}")

    # Last-known fallback
    try:
        cached = _redis_get(DFMGI_LAST_KNOWN_KEY)
        if cached:
            return {
                'index': 'DFMGI',
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
        'index': 'DFMGI',
        'value': None,
        'change_pct_24h': 0,
        'trend': 'unknown',
        'source': 'Unavailable',
        'sparkline': [],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


def _fetch_adx_index():
    """
    Fetch ADX General (Abu Dhabi) stock (^ADI) from Yahoo Finance.
    ADX is the world's largest oil company by revenue, ~98% state-owned by
    UAE government / PIF, and the single most important UAE-specific equity
    signal. UAE Vision 2030 anchor.
    v0.5.0 — UAE Financial Pulse (May 29 2026).
    """
    print("[UAE Stability] Fetching ADX General (Abu Dhabi) (^ADI)...")
    ARAMCO_LAST_KNOWN_KEY = 'adx_last_known'
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EADI"
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
                print(f"[UAE Stability] ADX: SAR {price:.2f} ({change_pct:+.2f}%)")
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
        print(f"[UAE Stability] ADX fetch error: {str(e)[:80]}")

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
    v0.5.0 — UAE Financial Pulse (May 29 2026).
    """
    print("[UAE Stability] Fetching Brent Crude full (BZ=F)...")
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
                print(f"[UAE Stability] Brent: ${price:.2f} ({change_pct:+.2f}%)")
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
        print(f"[UAE Stability] Brent fetch error: {str(e)[:80]}")

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

def _compute_market_status_dfm():
    """
    DFM (UAE Stock Exchange) hours:
      Mon-Fri, 10:00-15:00 Arabian Standard Time (AST = UTC+3, no DST).
      Friday/Saturday: closed.
      Pre-open auction: 09:30-10:00.
    """
    uae_tz = timezone(timedelta(hours=4))   # GST (UTC+4)
    now_uae = datetime.now(uae_tz)
    weekday = now_uae.weekday()  # Mon=0 ... Sun=6
    minutes = now_uae.hour * 60 + now_uae.minute

    # Saturday=5, Sunday=6: weekend (UAE moved to Mon-Fri trading, Jan 2022)
    if weekday in (5, 6):
        return 'closed'

    # Trading days (Mon-Fri)
    if 570 <= minutes < 600:    # 09:30-10:00 pre-open auction
        return 'pre-market'
    if 600 <= minutes <= 900:   # 10:00-15:00 main session
        return 'open'
    if 900 < minutes <= 1020:   # 15:00-17:00 after-hours
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

def build_uae_financial_pulse(dfm_data, adx_data, brent_data):
    """
    Assemble the canonical Financial Pulse Card payload for UAE.

    Three tiles: DFM DFMGI, ADX General (Abu Dhabi), Brent Crude.
    Per-tile market_status + aggregate card-level status.
    All three tiles use STANDARD polarity (rising = good, falling = stress).

    Note on ADX market_status: ADX trades on DFM, so its hours
    match the DFM session.

    v0.5.0 — UAE Financial Pulse Card (May 29 2026).
    """
    dfm_status = _compute_market_status_dfm()
    adx_status  = dfm_status  # ADX trades on DFM, same hours
    brent_status   = _compute_market_status_brent()

    aggregate = _compute_market_status_aggregate([dfm_status, adx_status, brent_status])

    def _tier(chg):
        """Standard polarity tier: rising = good, falling = stress."""
        if chg <= -2:  return 'stress'
        if chg <= -1:  return 'warning'
        if chg >= 2:   return 'rally'
        return 'stable'

    # DFM tile
    tasi_chg = dfm_data.get('change_pct_24h', 0) or 0
    tasi_tile = {
        'name':           'DFM DFMGI',
        'ticker':         'DFMGI',
        'value':          dfm_data.get('value'),
        'change_pct_24h': tasi_chg,
        'trend':          dfm_data.get('trend', 'flat'),
        'tier':           _tier(tasi_chg),
        'source':         dfm_data.get('source', 'Yahoo Finance'),
        'market_status':  dfm_status,
        'timestamp':      dfm_data.get('timestamp'),
        'sparkline':      dfm_data.get('sparkline', []),
    }

    # ADX General (Abu Dhabi) tile
    adx_chg = adx_data.get('change_pct_24h', 0) or 0
    adx_tile = {
        'name':           'ADX General (Abu Dhabi)',
        'ticker':         '^ADI',
        'value':          adx_data.get('value'),
        'change_pct_24h': adx_chg,
        'trend':          adx_data.get('trend', 'flat'),
        'tier':           _tier(adx_chg),
        'source':         adx_data.get('source', 'Yahoo Finance'),
        'market_status':  adx_status,
        'timestamp':      adx_data.get('timestamp'),
        'sparkline':      adx_data.get('sparkline', []),
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

    return {
        'country':        'AE',
        'card_label':     'UAE Financial Pulse',
        'market_status':  aggregate,
        'last_refreshed': datetime.now(timezone.utc).isoformat(),
        'tiles': {
            'TADAWUL': tasi_tile,
            'ARAMCO':  adx_tile,
            'BRENT':   brent_tile,
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
    v1.5.2 (May 29 2026) — baked in from start for UAE.
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
            print(f"[UAE Stability] GNews '{label}': HTTP 403 — retrying with Firefox UA")
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
            print(f"[UAE Stability] GNews '{label}': HTTP 403 — retrying with curl_cffi TLS impersonation")
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
                    print(f"[UAE Stability] GNews '{label}': curl_cffi rescued")
                else:
                    print(f"[UAE Stability] GNews '{label}': curl_cffi also got HTTP {cc_resp.status_code}")
            except Exception as cc_err:
                print(f"[UAE Stability] GNews '{label}': curl_cffi error {str(cc_err)[:100]}")
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
        print(f"[UAE Stability] GNews '{label}': {len(articles)} articles")
    except Exception as e:
        print(f"[UAE Stability] GNews error: {str(e)[:80]}")
    return articles


# ============================================
# MAIN SCAN ORCHESTRATOR
# ============================================

def run_uae_stability_scan():
    """Full UAE stability scan. v0.5: economic indicators only.
    Returns the canonical payload with financial_pulse + articles.
    """
    scan_start = time.time()
    print(f"\n[UAE Stability] Starting scan at {datetime.now(timezone.utc).isoformat()}")

    # Fetch live financial indicators
    dfm = _fetch_dfm_index()
    adx  = _fetch_adx_index()
    brent   = _fetch_brent_full()

    # Build canonical Financial Pulse Card payload
    financial_pulse = build_uae_financial_pulse(dfm, adx, brent)

    # Fetch articles (light scan; v0.5 doesn't score them, just surfaces them)
    all_articles = []
    queries = [
        ('UAE Israel defense cooperation weapons training', 'GNews:UAE-Israel Axis'),
        ('UAE Iran relations trade Dubai', 'GNews:UAE-Iran Dual'),
        ('ADNOC OPEC UAE oil production', 'GNews:ADNOC Oil'),
        ('UAE Abraham Accords normalization', 'GNews:Accords'),
        ('DP World Jebel Ali UAE ports shipping', 'GNews:UAE Ports Hub'),
        ('UAE economy Dubai Abu Dhabi investment', 'GNews:UAE Economy'),
        ('UAE drone missile attack Houthi intercept', 'GNews:UAE Threat'),
    ]
    for query, label in queries:
        try:
            all_articles.extend(_fetch_google_news_rss(query, label))
            time.sleep(0.3)
        except Exception as e:
            print(f"[UAE Stability] GNews error {label}: {str(e)[:60]}")

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
        'country':           'AE',
        'country_name':      'United Arab Emirates',
        'scanned_at':        datetime.now(timezone.utc).isoformat(),
        'scan_duration_sec': scan_time,

        # Financial Pulse Card payload
        'financial_pulse':   financial_pulse,

        # Individual tile data (also exposed top-level for convenience)
        'dfm':           dfm,
        'adx':            adx,
        'brent':             brent,

        # Articles
        'articles':          deduped[:60],
        'total_articles':    len(deduped),

        'version': '1.0.0-uae-stability',
    }

    # Cache to Redis
    _redis_set(CACHE_KEY, result, ttl=CACHE_TTL)

    # Lightweight history snapshot
    _redis_lpush_trim(HISTORY_KEY, {
        'ts':             datetime.now(timezone.utc).isoformat(),
        'tasi_value':     dfm.get('value'),
        'adx_value':   adx.get('value'),
        'brent_value':    brent.get('value'),
        'market_status':  financial_pulse.get('market_status'),
    })

    print(f"[UAE Stability] Scan complete in {scan_time}s | "
          f"DFMGI={dfm.get('value')} · ADX={adx.get('value')} · "
          f"Brent={brent.get('value')} · {len(deduped)} articles")
    return result


# ============================================
# BACKGROUND REFRESH
# ============================================

def _background_loop():
    print("[UAE Stability] Background thread started (12h cycle)")
    time.sleep(300)   # 5 min stagger after boot (avoid contention with other backends)
    while True:
        try:
            print("[UAE Stability] Background refresh triggered")
            run_uae_stability_scan()
        except Exception as e:
            print(f"[UAE Stability] Background scan error: {str(e)[:120]}")
        time.sleep(12 * 3600)


# ============================================
# FLASK ENDPOINTS
# ============================================

def register_uae_stability_endpoints(app):
    """Register UAE stability endpoints on the provided Flask app.
    Endpoints:
      GET /api/uae/stability              — full payload (Redis-cached)
      GET /api/uae/stability?force=true   — force fresh scan, bypass cache
      GET /api/uae/stability/summary      — lightweight cached subset
      GET /api/uae/stability/history      — recent history snapshots
    """

    @app.route('/api/uae/stability', methods=['GET'])
    def api_uae_stability():
        """Return full UAE stability payload. ?force=true bypasses Redis cache."""
        force = request.args.get('force', '').lower() == 'true'

        if not force:
            cached = _redis_get(CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return jsonify(cached)

        # Live scan
        try:
            result = run_uae_stability_scan()
            result['from_cache'] = False
            return jsonify(result)
        except Exception as e:
            print(f"[UAE Stability] Scan error: {str(e)[:200]}")
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/uae/stability/summary', methods=['GET'])
    def api_uae_stability_summary():
        """Lightweight cached subset — used for header/index pages."""
        cached = _redis_get(CACHE_KEY) or {}
        return jsonify({
            'country':          'SA',
            'country_name':     'UAE',
            'scanned_at':       cached.get('scanned_at'),
            'dfm':          cached.get('dfm', {}),
            'adx':           cached.get('adx', {}),
            'brent':            cached.get('brent', {}),
            'financial_pulse':  cached.get('financial_pulse', {}),
            'version':          '0.5.0-uae-stability',
        })

    @app.route('/api/uae/stability/history', methods=['GET'])
    def api_uae_stability_history():
        """Return UAE stability history for trend chart."""
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

    print("[UAE Stability] ✅ Endpoints registered: /api/uae/stability (+ /summary, /history)")
