# -*- coding: utf-8 -*-
"""
Libya Oil Pulse -- Production-STATUS Sensor  (v1.0.0, June 21 2026)
==================================================================

Lives on the ME backend (asifah-backend.onrender.com) alongside the Libya
humanitarian module. Surfaces the current STATUS of Libyan oil operations
from open-source signals:

  - NOC force-majeure declarations (and liftings)
  - Port / terminal and field blockades, shut-ins, and reopenings
  - Output / production figures when reported

This is a SENSOR, not a market card. It reports what open sources say about
Libyan oil OPERATIONS -- NOT price. (Price is global and shared by the whole
planet; in Libya, oil is weaponized by blockade, not quoted on a screen.)
The analyst read -- blockade-as-leverage, the east-west revenue dispute --
lives in the rhetoric / BLUF layer, not here.

Doctrine:
  - Sensor below, analyst above. Raw status, sourced and timestamped.
  - Absence stays honest: when no disruption signals are present, the band is
    'flowing' with a plain "no active disruption signals" headline. We never
    manufacture a status.

Scaffolding (Redis helpers, hardened Google News RSS fetcher, background loop,
endpoint registration) mirrors saudi_stability.py for consistency. The data
layer (status detection) is new.

Endpoints:
  GET /api/libya/oil-pulse              -- full payload (Redis-cached)
  GET /api/libya/oil-pulse?force=true   -- force a fresh scan
  GET /api/libya/oil-pulse/history      -- recent status snapshots
  GET /debug/libya-oil-pulse            -- raw detector output for inspection
"""

import os
import re
import json
import time
import threading
import requests
import xml.etree.ElementTree as ET
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# curl_cffi: TLS/JA3 impersonation for RSS feeds blocked at the network layer.
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    curl_requests = None
    CURL_CFFI_AVAILABLE = False
    print("[Libya Oil Pulse] WARNING: curl_cffi not installed -- TLS impersonation unavailable")


# ============================================
# CONFIG
# ============================================

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL', '').rstrip('/')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '')

CACHE_KEY = 'libya_oil_pulse:latest'
HISTORY_KEY = 'libya_oil_pulse:history'
CACHE_TTL = 6 * 3600  # 6 hours

__version__ = '1.1.0'
RECENCY_WINDOW_DAYS = 90  # only events within this window drive the status band


# ============================================
# REDIS HELPERS  (cloned from saudi_stability.py)
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
        print(f"[Libya Oil Pulse] Redis GET error: {str(e)[:80]}")
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
        print(f"[Libya Oil Pulse] Redis SET error: {str(e)[:80]}")
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
        r = requests.post(url, headers=headers,
                          json=['LPUSH', key, json.dumps(value)], timeout=10)
        requests.post(url, headers=headers,
                      json=['LTRIM', key, '0', str(max_len - 1)], timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Libya Oil Pulse] Redis LPUSH error: {str(e)[:80]}")
    return False


# ============================================
# HARDENED GOOGLE NEWS RSS  (cloned from saudi_stability.py)
# ============================================

def _fetch_google_news_rss(query, label, max_items=15):
    """Three-tier RSS fetcher: Chrome UA -> Firefox UA on 403 -> curl_cffi TLS."""
    articles = []
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"
    headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/130.0.0.0 Safari/537.36'),
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
        if resp.status_code == 403:
            print(f"[Libya Oil Pulse] GNews '{label}': HTTP 403 -- retrying with Firefox UA")
            ff = dict(headers)
            ff['User-Agent'] = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) '
                                'Gecko/20100101 Firefox/130.0')
            ff.pop('Sec-Ch-Ua', None)
            ff.pop('Sec-Ch-Ua-Mobile', None)
            ff.pop('Sec-Ch-Ua-Platform', None)
            ff['Referer'] = 'https://duckduckgo.com/'
            time.sleep(1.2)
            resp = requests.get(url, timeout=(5, 15), headers=ff, allow_redirects=True)
        if resp.status_code == 403 and CURL_CFFI_AVAILABLE:
            print(f"[Libya Oil Pulse] GNews '{label}': HTTP 403 -- retrying with curl_cffi")
            try:
                time.sleep(0.8)
                cc = curl_requests.get(url, impersonate='chrome', timeout=15, allow_redirects=True)
                if cc.status_code == 200:
                    class _CCWrapper:
                        def __init__(self, c):
                            self.status_code = c.status_code
                            self.content = c.content
                            self.text = c.text
                    resp = _CCWrapper(cc)
                    print(f"[Libya Oil Pulse] GNews '{label}': curl_cffi rescued")
            except Exception as cc_err:
                print(f"[Libya Oil Pulse] GNews '{label}': curl_cffi error {str(cc_err)[:80]}")
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            all_items = (root.findall('.//{*}item') or root.findall('.//{*}entry'))
            for item in all_items[:max_items]:
                title_el = item.find('{*}title')
                link_el = item.find('{*}link')
                pub_el = item.find('{*}pubDate')
                src_el = item.find('{*}source')
                if title_el is not None and title_el.text:
                    link_text = ''
                    if link_el is not None:
                        link_text = (link_el.text or link_el.get('href') or '').strip()
                    src_name = (src_el.text.strip() if (src_el is not None and src_el.text) else label)
                    articles.append({
                        'title': title_el.text.strip(),
                        'url': link_text,
                        'published': pub_el.text if (pub_el is not None and pub_el.text) else '',
                        'source': src_name,
                    })
        print(f"[Libya Oil Pulse] GNews '{label}': {len(articles)} articles")
    except Exception as e:
        print(f"[Libya Oil Pulse] GNews error: {str(e)[:80]}")
    return articles


# ============================================
# OIL-STATUS DETECTOR  (the new data layer)
# ============================================

# Named Libyan terminals/ports and fields to watch. (canonical, type, aliases)
FACILITIES = [
    ('Es Sider', 'port', ['es sider', 'es sidra', 'sidra terminal', 'sidra port']),
    ('Ras Lanuf', 'port', ['ras lanuf', 'ras lanouf']),
    ('Zueitina', 'port', ['zueitina', 'zuetina']),
    ('Brega', 'port', ['marsa el brega', 'marsa al-brega', 'brega port', 'brega terminal']),
    ('Hariga', 'port', ['hariga', 'marsa al-hariga', 'marsa el-hariga']),
    ('Zawiya', 'port', ['zawiya', 'zawia']),
    ('Mellitah', 'port', ['mellitah']),
    ('Sharara', 'field', ['sharara', 'el sharara', 'al-sharara']),
    ('El Feel', 'field', ['el feel', 'el-feel', 'elephant field']),
    ('Waha', 'field', ['waha oil', 'waha field', 'waha concession']),
    ('Sarir', 'field', ['sarir field', 'sarir oil']),
    ('Messla', 'field', ['messla']),
    ('Abu Attifel', 'field', ['abu attifel']),
    ('El Wafa', 'field', ['el wafa', 'wafa field']),
    ('Nafoora', 'field', ['nafoora', 'nafura']),
]

# Reopen / de-escalation language (checked FIRST -- "lifts force majeure" is a reopen)
REOPEN_KEYWORDS = [
    'lifts force majeure', 'lifted force majeure', 'force majeure lifted',
    'resume production', 'resumes production', 'resumed production',
    'reopen', 'reopened', 'reopens', 'restart production', 'restarts production',
    'restarted production', 'back online', 'loading resumes', 'resume loading',
    'resume exports', 'resumes exports', 'lifts blockade', 'lifted blockade',
    'production restored', 'output restored', 'reopening',
    'lifting force majeure', 'lifting the force majeure', 'after lifting',
    'ends blockade', 'ended blockade', 'ends the blockade', 'first oil export',
    'oil export after', 'export resumes', 'exports resume',
]

# Blockade / shut-in language
BLOCKADE_KEYWORDS = [
    'blockade', 'blockaded', 'shut down', 'shuts down', 'shut-in', 'shut in',
    'halt production', 'halts production', 'halted production',
    'suspend production', 'suspends production', 'suspended production',
    'closed the port', 'shut the port', 'port closure', 'stop loading',
    'stops loading', 'stopped loading', 'oil shutdown', 'production shutdown',
    'shut oilfield', 'shut oil field', 'exports halted', 'halt exports',
    'halts exports', 'force closure', 'protesters shut', 'closes oilfield',
]

# Widespread / national escalation language (bumps a band up)
ESCALATION_KEYWORDS = [
    'all oil', 'all ports', 'all fields', 'nationwide', 'national shutdown',
    'total shutdown', 'complete shutdown', 'exports halted', 'halt all oil',
    'shut all', 'entire oil', 'all oil exports', 'all terminals',
]

# Conditional / threat language -- a *possible* or *threatened* action, NOT a current one.
# Downgrades a force-majeure/blockade match to a 'threat' (does not drive shutdown).
CONDITIONAL_KEYWORDS = [
    'may announce', 'may declare', 'could declare', 'could announce',
    'plans to declare', 'set to declare', 'threatens', 'threaten to',
    'considering', 'weighs', 'warns of', 'risk of', 'fears of', 'mulls',
    'expected to declare', 'preparing to',
]

# Production-figure extraction (numbers + a bpd-style unit)
_PROD_RE = re.compile(
    r'([\d][\d.,]*)\s*(million|m|mn)?\s*(barrels?\s+(?:per|a)\s+day|bpd|b/d|bbl/?d|bbl per day)',
    re.IGNORECASE)


def _match_facility(text_lower):
    """Return (canonical_name, type) of the first facility mentioned, or (None, None)."""
    for name, ftype, aliases in FACILITIES:
        for a in aliases:
            if a in text_lower:
                return name, ftype
    return None, None


def _classify_event(title):
    """Classify a single article title into an oil-status event_type, or None."""
    t = title.lower()
    if any(k in t for k in REOPEN_KEYWORDS):
        return 'reopen'
    if 'force majeure' in t:
        return 'force_majeure'
    if any(k in t for k in BLOCKADE_KEYWORDS):
        return 'blockade'
    if _PROD_RE.search(title):
        return 'production'
    return None


_BAND_META = {
    'flowing':      ('Production Flowing',        '#22c55e'),
    'disrupted':    ('Localized Disruption',      '#eab308'),
    'force_majeure': ('Force Majeure Active',      '#f97316'),
    'shutdown':     ('Major / National Shutdown', '#ef4444'),
}

_DISCLAIMER = ("Sensor feed: open-source oil-production STATUS signals "
               "(NOC force-majeure declarations, port and field blockades/reopenings, "
               "and reported output), NOT price. It surfaces what is being reported about "
               "Libyan oil operations; it does not predict production or revenue outcomes.")


def _parse_published(s):
    """Parse an RSS pubDate (RFC 822) to an aware datetime, or None."""
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def detect_oil_status(articles):
    """
    Classify Libya's current oil-operations status from a list of article dicts
    ({title, url, published, source}). Returns the full pulse payload.
    Absence stays honest: no disruption signals -> 'flowing' with a plain headline.
    """
    events = []
    facilities_seen = {}   # name -> {'type', 'mentions', 'last_event', 'last_title'}
    counts = {'force_majeure': 0, 'blockade': 0, 'reopen': 0, 'production': 0, 'threat': 0}
    escalation = False
    production_figure = None

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_WINDOW_DAYS)
    stale_dropped = 0
    offtopic_dropped = 0

    for art in (articles or []):
        title = (art.get('title') or '').strip()
        if not title:
            continue
        tl = title.lower()

        # Relevance gate: must be about Libyan oil (kills cross-topic RSS bleed,
        # e.g. a Strait-of-Hormuz 'reopening' headline).
        fac_name, fac_type = _match_facility(tl)
        if 'libya' not in tl and fac_name is None:
            offtopic_dropped += 1
            continue

        # Recency gate: stale news (a 2020 force-majeure) is history, not current status.
        dt = _parse_published(art.get('published'))
        if dt is None or dt < cutoff:
            stale_dropped += 1
            continue

        etype = _classify_event(title)
        if not etype:
            continue

        # Conditional/threat downgrade: "may announce force majeure" is not a declaration.
        if etype in ('force_majeure', 'blockade') and any(k in tl for k in CONDITIONAL_KEYWORDS):
            etype = 'threat'

        counts[etype] = counts.get(etype, 0) + 1
        if etype in ('force_majeure', 'blockade') and any(k in tl for k in ESCALATION_KEYWORDS):
            escalation = True
        if fac_name:
            slot = facilities_seen.setdefault(
                fac_name, {'type': fac_type, 'mentions': 0, 'last_event': etype, 'last_title': title})
            slot['mentions'] += 1
            slot['last_event'] = etype
            slot['last_title'] = title

        if etype == 'production' and production_figure is None:
            m = _PROD_RE.search(title)
            if m:
                production_figure = {
                    'text': m.group(0).strip(),
                    'source_title': title,
                    'source_url': art.get('url', ''),
                    'source': art.get('source', ''),
                    'published': art.get('published', ''),
                }

        events.append({
            'event_type': etype,
            'facility': fac_name,
            'title': title,
            'url': art.get('url', ''),
            'source': art.get('source', ''),
            'published': art.get('published', ''),
        })

    # --- Status band ---
    fm, bl, ro = counts['force_majeure'], counts['blockade'], counts['reopen']
    th = counts['threat']
    disruption = fm + bl
    facility_count = len(facilities_seen)

    if disruption == 0 or ro > disruption:
        band = 'flowing'
    elif fm > 0:
        band = 'shutdown' if (escalation or facility_count >= 3) else 'force_majeure'
    else:  # blockade only
        band = 'shutdown' if escalation else 'disrupted'

    # A credible recent THREAT to declare force majeure (no actual shut-in, no offsetting
    # recovery) is amber, not green.
    if band == 'flowing' and th > 0 and ro == 0:
        band = 'disrupted'

    # --- Headline: lead with the most severe present event, else honest baseline ---
    def _first(etype):
        for e in events:
            if e['event_type'] == etype:
                return e
        return None

    lead = None
    if band in ('shutdown', 'force_majeure'):
        lead = _first('force_majeure') or _first('blockade')
    elif band == 'disrupted':
        lead = _first('blockade')
    else:  # flowing
        lead = _first('reopen')

    if lead:
        headline = lead['title']
    elif band == 'flowing':
        headline = f'No active disruption signals in the last {RECENCY_WINDOW_DAYS} days -- production reporting nominal.'
    else:
        headline = 'Oil-status signals detected.'

    label, color = _BAND_META[band]

    facilities = [
        {'name': n, 'type': d['type'], 'mentions': d['mentions'],
         'last_event': d['last_event'], 'last_title': d['last_title']}
        for n, d in sorted(facilities_seen.items(), key=lambda kv: -kv[1]['mentions'])
    ]

    return {
        'success': True,
        'as_of': datetime.now(timezone.utc).isoformat(),
        'status_band': band,
        'status_label': label,
        'status_color': color,
        'headline': headline,
        'production_figure': production_figure,
        'facilities': facilities,
        'events': events[:10],
        'event_counts': counts,
        'article_count': len(articles or []),
        'recent_event_count': len(events),
        'recency_window_days': RECENCY_WINDOW_DAYS,
        'stale_dropped': stale_dropped,
        'offtopic_dropped': offtopic_dropped,
        'source': 'Google News RSS -- NOC / oil-facility status signals',
        'disclaimer': _DISCLAIMER,
        'version': __version__,
    }


# ============================================
# SCAN ORCHESTRATOR
# ============================================

_QUERIES = [
    ('Libya NOC oil force majeure', 'GNews:Libya FM'),
    ('Libya oil port blockade shut reopen', 'GNews:Libya Ports'),
    ('Libya oil production barrels per day NOC', 'GNews:Libya Output'),
    ('Libya Sharara El Feel oilfield', 'GNews:Libya Fields'),
    ('Libya Es Sider Ras Lanuf Zueitina oil terminal', 'GNews:Libya Terminals'),
]


def run_oil_pulse_scan():
    """Full scan: pull focused Libya oil-status news, detect status, cache, snapshot."""
    scan_start = time.time()
    print(f"\n[Libya Oil Pulse] Starting scan at {datetime.now(timezone.utc).isoformat()}")

    all_articles = []
    for query, label in _QUERIES:
        try:
            all_articles.extend(_fetch_google_news_rss(query, label))
            time.sleep(0.3)
        except Exception as e:
            print(f"[Libya Oil Pulse] GNews error {label}: {str(e)[:60]}")

    # Deduplicate by URL
    seen = set()
    deduped = []
    for art in all_articles:
        u = (art.get('url') or '').strip()
        if u and u not in seen:
            seen.add(u)
            deduped.append(art)

    result = detect_oil_status(deduped)
    result['scan_duration_sec'] = round(time.time() - scan_start, 1)

    _redis_set(CACHE_KEY, result, ttl=CACHE_TTL)
    _redis_lpush_trim(HISTORY_KEY, {
        'ts': result['as_of'],
        'status_band': result['status_band'],
        'event_counts': result['event_counts'],
    })

    print(f"[Libya Oil Pulse] Scan complete in {result['scan_duration_sec']}s | "
          f"band={result['status_band']} | events={result['event_counts']} | "
          f"{len(deduped)} articles")
    return result


# ============================================
# BACKGROUND REFRESH
# ============================================

def _background_loop():
    print("[Libya Oil Pulse] Background thread started (6h cycle)")
    time.sleep(150)  # boot stagger
    while True:
        try:
            print("[Libya Oil Pulse] Background refresh triggered")
            run_oil_pulse_scan()
        except Exception as e:
            print(f"[Libya Oil Pulse] Background scan error: {str(e)[:120]}")
        time.sleep(CACHE_TTL)


# ============================================
# FLASK ENDPOINTS
# ============================================

def register_libya_oil_pulse_endpoints(app):
    """Register Libya Oil Pulse endpoints on the provided Flask app."""
    from flask import jsonify, request

    @app.route('/api/libya/oil-pulse', methods=['GET'])
    def api_libya_oil_pulse():
        force = request.args.get('force', '').lower() == 'true'
        if not force:
            cached = _redis_get(CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return jsonify(cached)
        try:
            result = run_oil_pulse_scan()
            result['from_cache'] = False
            return jsonify(result)
        except Exception as e:
            print(f"[Libya Oil Pulse] Scan error: {str(e)[:200]}")
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/libya/oil-pulse/history', methods=['GET'])
    def api_libya_oil_pulse_history():
        history = _redis_get(HISTORY_KEY)
        if not isinstance(history, list):
            history = []
        return jsonify({'success': True, 'history': history, 'count': len(history)})

    @app.route('/debug/libya-oil-pulse', methods=['GET'])
    def debug_libya_oil_pulse():
        """Live scan, no cache -- inspect detector output + raw events."""
        try:
            result = run_oil_pulse_scan()
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    t = threading.Thread(target=_background_loop, daemon=True)
    t.start()
    print("[Libya Oil Pulse] Endpoints registered + background refresh started")


print(f"[Libya Oil Pulse] Module loaded -- v{__version__}")
