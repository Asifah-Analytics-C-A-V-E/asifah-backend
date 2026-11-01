"""
Asifah Analytics -- Airspace Watch (ME)  v2.0.0
November 1, 2026

Drop-in replacement for notam_monitor.py v1.1.0. Same file name, same
register_notam_endpoints(app) -- app.py needs no edit.

WHY v2.0.0
  v1.1.0 POSTed to the FAA NOTAM *website* search form with a spoofed browser
  User-Agent. The site began refusing it (HTTP 403, every airport, since at
  least Oct 18 2026) and the page kept saying "All Middle East airspace
  operating normally" -- a quiet sky that was really an unread sensor.
  The FAA's sanctioned route (NMS-API) needs a login.gov identity; Rachel
  ruled that out (Nov 1). This version reads three open, no-login sources:

  1. PAPER (regulator)   EASA Conflict Zone Information Bulletins (CZIBs)
                         JSON export + RSS. Official, structured, EU regulator.
  2. PAPER (US carriers) FAA "Prohibitions, Restrictions and Notices" page
                         (SFARs + KICZ international security NOTAMs).
  3. BEHAVIOUR           OpenSky Network live state vectors, counted per
                         region and compared with the same hour on prior days.
                         Airlines often reroute before regulators publish.

  The So What is the convergence: paper and behaviour agreeing, or
  behaviour moving AHEAD of paper (the early-warning case).

DOCTRINE
  - Absence-honest: a source that was not read says 'unread', never 'quiet'.
  - Thin ADS-B coverage (low baseline) says 'thin coverage', never 'normal'.
  - No baseline yet says 'baseline building' (needs 3 days).
  - One low sample is 'below normal', never 'sharp drop' (needs 2 in a row).
  - Descriptive states only -- no ladder level is asserted from traffic.

COST / LOAD
  - OpenSky: ~24 credits per scan x 48 scans/day ~= 1,150 of 4,000 free credits.
  - EASA + FAA: one fetch each per 6 hours.
  - Leader instance only (instance_lock.my_turn). Public requests read Redis
    and never trigger a scan (no ?force).
  - Credentials ONLY from env: OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET.

ENDPOINTS
  /api/airspace            full payload (?region=iran for one region)
  /api/notams              compatibility shape for the existing ME widget
  /api/airspace/health     per-source state, credits remaining, last errors
"""

import os
import re
import json
import time
import threading
import statistics
import html as _html
from datetime import datetime, timezone

import requests

AIRSPACE_VERSION = '2.0.0'
AIRSPACE_USER_AGENT = (f'AsifahAnalytics-ME-Airspace/{AIRSPACE_VERSION} '
                       f'(OSINT monitoring tool; +https://asifahanalytics.com)')

# ========================================
# CONFIG
# ========================================
UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
OPENSKY_CLIENT_ID = os.environ.get('OPENSKY_CLIENT_ID')
OPENSKY_CLIENT_SECRET = os.environ.get('OPENSKY_CLIENT_SECRET')

OPENSKY_TOKEN_URL = ('https://auth.opensky-network.org/auth/realms/opensky-network/'
                     'protocol/openid-connect/token')
OPENSKY_STATES_URL = 'https://opensky-network.org/api/states/all'
EASA_JSON_URL = ('https://www.easa.europa.eu/en/domains/air-operations/czibs/'
                 'export-json?page&_format=json')
EASA_RSS_URL = 'https://www.easa.europa.eu/en/domains/air-operations/czibs/feed.xml'
EASA_PAGE_URL = 'https://www.easa.europa.eu/en/domains/international-cooperation/easa-by-country/conflict-zones'
FAA_RESTRICTIONS_URL = 'https://www.faa.gov/air_traffic/publications/us_restrictions'

TRAFFIC_INTERVAL_SEC = 30 * 60        # behaviour: every 30 min
PAPER_INTERVAL_SEC = 6 * 60 * 60      # EASA + FAA: every 6 h
HISTORY_DAYS = 8                      # traffic samples kept
BASELINE_MIN_DAYS = 3                 # days of samples before any ratio is claimed
THIN_COVERAGE_MEDIAN = 5              # baseline median below this = thin coverage
CHANGES_KEEP = 60

K_LATEST = 'airspace:latest'
K_TRAFFIC = 'airspace:traffic_history'
K_PAPER = 'airspace:paper_snapshot'
K_CHANGES = 'airspace:changes'
K_LEGACY = 'mideast_notam_cache'      # v1.1.0 key -- overwritten so nothing stale lingers

# ========================================
# REGIONS  (bbox = lat_min, lat_max, lon_min, lon_max -- approximate national
# airspace incl. near approaches. Boxes overlap at borders by design: the
# count is "aircraft over or near X", not a legal FIR boundary.)
# ========================================
REGIONS = {
    'israel':       {'name': 'Israel',       'flag': '🇮🇱', 'fir': 'LLLL',      'bbox': (29.4, 33.4, 34.2, 35.9)},
    'lebanon':      {'name': 'Lebanon',      'flag': '🇱🇧', 'fir': 'OLBB',      'bbox': (33.0, 34.7, 35.1, 36.7)},
    'syria':        {'name': 'Syria',        'flag': '🇸🇾', 'fir': 'OSTT',      'bbox': (32.3, 37.4, 35.6, 42.4)},
    'iran':         {'name': 'Iran',         'flag': '🇮🇷', 'fir': 'OIIX',      'bbox': (25.0, 39.8, 44.0, 63.4)},
    'iraq':         {'name': 'Iraq',         'flag': '🇮🇶', 'fir': 'ORBB',      'bbox': (29.0, 37.4, 38.8, 48.6)},
    'jordan':       {'name': 'Jordan',       'flag': '🇯🇴', 'fir': 'OJAC',      'bbox': (29.2, 33.4, 34.9, 39.3)},
    'egypt':        {'name': 'Egypt',        'flag': '🇪🇬', 'fir': 'HECC',      'bbox': (22.0, 31.7, 24.7, 36.9)},
    'saudi_arabia': {'name': 'Saudi Arabia', 'flag': '🇸🇦', 'fir': 'OEJD',      'bbox': (16.3, 32.2, 34.5, 55.7)},
    'uae':          {'name': 'UAE',          'flag': '🇦🇪', 'fir': 'OMAE',      'bbox': (22.6, 26.1, 51.5, 56.4)},
    'qatar':        {'name': 'Qatar',        'flag': '🇶🇦', 'fir': 'OTDF',      'bbox': (24.4, 26.2, 50.7, 51.7)},
    'bahrain':      {'name': 'Bahrain',      'flag': '🇧🇭', 'fir': 'OBBB',      'bbox': (25.5, 26.4, 50.3, 50.9)},
    'kuwait':       {'name': 'Kuwait',       'flag': '🇰🇼', 'fir': 'OKAC',      'bbox': (28.5, 30.1, 46.5, 48.5)},
    'oman':         {'name': 'Oman',         'flag': '🇴🇲', 'fir': 'OOMM',      'bbox': (16.6, 26.4, 52.0, 59.9)},
    'yemen':        {'name': 'Yemen',        'flag': '🇾🇪', 'fir': 'OYSC',      'bbox': (12.1, 19.0, 42.5, 54.0)},
}

# How EASA/FAA country names map onto our regions. Lower-case substring match.
PAPER_ALIASES = {
    'israel': ['israel'],
    'lebanon': ['lebanon'],
    'syria': ['syria'],
    'iran': ['iran'],
    'iraq': ['iraq'],
    'jordan': ['jordan'],
    'egypt': ['egypt'],
    'saudi_arabia': ['saudi'],
    'uae': ['united arab emirates', 'uae', 'persian gulf', 'gulf of oman'],
    'qatar': ['qatar', 'persian gulf'],
    'bahrain': ['bahrain', 'persian gulf'],
    'kuwait': ['kuwait', 'persian gulf'],
    'oman': ['oman'],                     # 'gulf of oman' also contains 'oman'
    'yemen': ['yemen'],
}

# Neighbours used for the reroute rule (traffic leaving A shows up over B).
NEIGHBOURS = {
    'iran': ['iraq', 'saudi_arabia', 'oman', 'uae'],
    'iraq': ['iran', 'saudi_arabia', 'jordan', 'syria'],
    'syria': ['iraq', 'jordan', 'lebanon'],
    'israel': ['jordan', 'egypt', 'lebanon'],
    'lebanon': ['syria', 'israel'],
    'yemen': ['saudi_arabia', 'oman'],
}

# ========================================
# SMALL HELPERS
# ========================================
def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat() if dt else None


def _strip_tags(s):
    return _html.unescape(re.sub(r'<[^>]+>', ' ', s or '')).replace('\xa0', ' ')


def _squash(s):
    return re.sub(r'\s+', ' ', s or '').strip()


# ========================================
# REDIS (Upstash REST, same pattern as v1.1.0)
# ========================================
def _rget(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(f"{UPSTASH_REDIS_URL}/get/{key}",
                         headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=8)
        res = r.json().get('result')
        return json.loads(res) if res else None
    except Exception as e:
        print(f"[Airspace] Redis get {key} error: {str(e)[:120]}")
        return None


def _rset(key, value):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(f"{UPSTASH_REDIS_URL}/set/{key}",
                          headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                                   "Content-Type": "application/json"},
                          data=json.dumps(value, default=str), timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Airspace] Redis set {key} error: {str(e)[:120]}")
        return False


# ========================================
# 1. EASA CZIBs
# ========================================
_CZIB_ID_RX = re.compile(r'(?:CZIB[-\s]?)?(20\d{2}-\d{2}\s?-?\s?R\d+|20\d{2}-\d{2})', re.I)


def _parse_ddmmyyyy(s):
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', s or '')
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_any_dt(s):
    if not s:
        return None
    m = re.search(r'datetime="([^"]+)"', s)
    raw = m.group(1) if m else _squash(_strip_tags(s))
    iso = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', raw.replace('Z', '+00:00'))  # +0300 -> +03:00
    try:
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw)
    except Exception:
        return None


def parse_easa_json(payload):
    """EASA export -> list of CZIB dicts. Accepts a list or {'data': [...]}."""
    rows = payload.get('data', payload) if isinstance(payload, dict) else payload
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        name = _squash(_strip_tags(r.get('name', '')))
        country = _squash(_strip_tags(r.get('country', ''))) or name
        valid_until = _parse_ddmmyyyy(r.get('valid_until_date', '')) or \
            _parse_ddmmyyyy(_strip_tags(r.get('field_easa_valid_until_descr', '')))
        out.append({
            'nid': str(r.get('Nid', '')),
            'name': name,
            'country': country,
            'status': _squash(r.get('status', '')),
            'issued': _iso(_parse_any_dt(r.get('issued_date', ''))),
            'valid_until': _iso(valid_until),
            'valid_until_text': _squash(_strip_tags(r.get('field_easa_valid_until_descr', ''))),
            'updated': _iso(_parse_any_dt(r.get('updated', ''))),
            'czib_id': None,
            'source_url': (f"https://www.easa.europa.eu/en/node/{r.get('Nid')}"
                           if r.get('Nid') else EASA_PAGE_URL),
        })
    return out


def parse_easa_rss(xml_text):
    """RSS -> list of {title, czib_id, link, pub}. Best-effort; the JSON is primary."""
    items = []
    for block in re.findall(r'<item\b.*?</item>', xml_text or '', re.S | re.I):
        def tag(t):
            m = re.search(rf'<{t}[^>]*>(.*?)</{t}>', block, re.S | re.I)
            return _squash(_strip_tags(re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', m.group(1), flags=re.S))) if m else ''
        title, desc = tag('title'), tag('description')
        idm = _CZIB_ID_RX.search(title + ' ' + desc)
        items.append({'title': title, 'czib_id': _squash(idm.group(1)).replace(' ', '') if idm else None,
                      'link': tag('link'), 'pub': _iso(_parse_any_dt(tag('pubDate')))})
    return items


def fetch_easa():
    src = {'state': 'unread', 'read_at': None, 'error': None, 'count': 0, 'rss_items': 0}
    czibs = []
    try:
        r = requests.get(EASA_JSON_URL, headers={'User-Agent': AIRSPACE_USER_AGENT,
                                                 'Accept': 'application/json'}, timeout=25)
        if r.status_code != 200:
            src['error'] = f'JSON HTTP {r.status_code}'
        else:
            czibs = parse_easa_json(r.json())
    except Exception as e:
        src['error'] = f'JSON {type(e).__name__}: {str(e)[:120]}'

    # RSS: pick up CZIB numbers + any revision newer than the JSON's record.
    try:
        r = requests.get(EASA_RSS_URL, headers={'User-Agent': AIRSPACE_USER_AGENT}, timeout=25)
        if r.status_code == 200:
            rss = parse_easa_rss(r.text)
            src['rss_items'] = len(rss)
            for c in czibs:
                key = (c['country'] or c['name']).lower()
                hits = [i for i in rss if key and key.split(' (')[0] in i['title'].lower()]
                hits.sort(key=lambda i: i['pub'] or '', reverse=True)
                if hits:
                    c['czib_id'] = hits[0]['czib_id']
                    c['rss_latest'] = hits[0]['pub']
                    if hits[0]['link']:
                        c['source_url'] = hits[0]['link']
        elif not src['error']:
            src['error'] = f'RSS HTTP {r.status_code}'
    except Exception as e:
        if not src['error']:
            src['error'] = f'RSS {type(e).__name__}'

    if czibs:
        src.update(state='read', read_at=_iso(_now()), count=len(czibs))
    return czibs, src


# ========================================
# 2. FAA prohibitions page (SFAR + KICZ)
# ========================================
_KICZ_RX = re.compile(r'\b([A-Z]\d{4}/\d{2})\b')
_SFAR_RX = re.compile(r'\bSFAR\s*(?:No\.?\s*)?(\d{2,3}[A-Z]?)\b', re.I)


def parse_faa_page(page_html):
    """Split on headings; collect KICZ NOTAM numbers and SFARs under each heading.
    Returns ({heading_lower: {...}}, last_updated_text)."""
    sections = {}
    parts = re.split(r'(<h[2-5][^>]*>.*?</h[2-5]>)', page_html or '', flags=re.S | re.I)
    current = None
    for part in parts:
        hm = re.match(r'<h[2-5][^>]*>(.*?)</h[2-5]>', part, re.S | re.I)
        if hm:
            current = _squash(_strip_tags(hm.group(1)))
            continue
        if not current:
            continue
        text = _strip_tags(part)
        kicz = sorted(set(_KICZ_RX.findall(text)))
        sfar = sorted(set(s.upper() for s in _SFAR_RX.findall(text)))
        links = re.findall(r'href="([^"]+)"', part)
        if kicz or sfar:
            sec = sections.setdefault(current.lower(), {'heading': current, 'kicz': [], 'sfar': [], 'links': []})
            sec['kicz'] = sorted(set(sec['kicz']) | set(kicz))
            sec['sfar'] = sorted(set(sec['sfar']) | set(sfar))
            for l in links:
                if l not in sec['links'] and len(sec['links']) < 4:
                    sec['links'].append(l if l.startswith('http') else 'https://www.faa.gov' + l)
    lu = re.search(r'Last updated:?\s*([^<\n]{6,60})', _strip_tags(page_html or ''), re.I)
    return sections, (_squash(lu.group(1)) if lu else None)


def fetch_faa():
    src = {'state': 'unread', 'read_at': None, 'error': None, 'page_updated': None, 'sections': 0}
    try:
        r = requests.get(FAA_RESTRICTIONS_URL, headers={'User-Agent': AIRSPACE_USER_AGENT}, timeout=25)
        if r.status_code != 200:
            src['error'] = f'HTTP {r.status_code}'
            return {}, src
        sections, updated = parse_faa_page(r.text)
        if not sections:
            src['error'] = 'page read but no country sections parsed (layout change?)'
            src['state'] = 'parse_failed'
            return {}, src
        src.update(state='read', read_at=_iso(_now()), page_updated=updated, sections=len(sections))
        return sections, src
    except Exception as e:
        src['error'] = f'{type(e).__name__}: {str(e)[:120]}'
        return {}, src


# ========================================
# 3. OpenSky traffic
# ========================================
class _OpenSkyToken:
    def __init__(self):
        self.token = None
        self.expires = 0
        self.lock = threading.Lock()

    def get(self, force=False):
        if not (OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET):
            return None, 'OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET not set'
        with self.lock:
            if self.token and not force and time.time() < self.expires - 60:
                return self.token, None
            try:
                r = requests.post(OPENSKY_TOKEN_URL, data={
                    'grant_type': 'client_credentials',
                    'client_id': OPENSKY_CLIENT_ID,
                    'client_secret': OPENSKY_CLIENT_SECRET,
                }, headers={'User-Agent': AIRSPACE_USER_AGENT}, timeout=20)
                if r.status_code != 200:
                    return None, f'token HTTP {r.status_code}'
                j = r.json()
                self.token = j.get('access_token')
                self.expires = time.time() + int(j.get('expires_in', 1800))
                return self.token, None if self.token else 'token missing in response'
            except Exception as e:
                return None, f'token {type(e).__name__}'


_token = _OpenSkyToken()


def count_airborne(states):
    """states/all rows -> count of airborne aircraft with a position."""
    n = 0
    for s in states or []:
        try:
            if s[5] is None or s[6] is None:     # lon, lat
                continue
            if s[8]:                             # on_ground
                continue
            n += 1
        except (IndexError, TypeError):
            continue
    return n


def fetch_region_count(region_key, token):
    lat0, lat1, lon0, lon1 = REGIONS[region_key]['bbox']
    params = {'lamin': lat0, 'lamax': lat1, 'lomin': lon0, 'lomax': lon1}
    headers = {'User-Agent': AIRSPACE_USER_AGENT, 'Authorization': f'Bearer {token}'}
    r = requests.get(OPENSKY_STATES_URL, params=params, headers=headers, timeout=25)
    return r


def scan_traffic():
    """Returns ({region: count|None}, source_state)."""
    src = {'state': 'unread', 'read_at': None, 'error': None, 'credits_remaining': None,
           'regions_read': 0, 'regions_total': len(REGIONS)}
    token, err = _token.get()
    if not token:
        src['error'] = err
        return {}, src
    counts = {}
    for key in REGIONS:
        try:
            r = fetch_region_count(key, token)
            if r.status_code == 401:
                token, err = _token.get(force=True)
                if not token:
                    src['error'] = err
                    break
                r = fetch_region_count(key, token)
            rem = r.headers.get('X-Rate-Limit-Remaining')
            if rem is not None:
                src['credits_remaining'] = rem
            if r.status_code == 429:
                src['error'] = ('rate limited; retry after '
                                f"{r.headers.get('X-Rate-Limit-Retry-After-Seconds', '?')}s")
                src['state'] = 'rate_limited'
                break
            if r.status_code != 200:
                src['error'] = f'{key}: HTTP {r.status_code}'
                continue
            counts[key] = count_airborne((r.json() or {}).get('states'))
            time.sleep(0.5)
        except Exception as e:
            src['error'] = f'{key}: {type(e).__name__}'
    src['regions_read'] = len(counts)
    if counts:
        src['state'] = 'read' if len(counts) == len(REGIONS) else 'partial'
        src['read_at'] = _iso(_now())
    return counts, src


def append_history(history, counts, now=None):
    """history = {region: [[epoch_min, count], ...]} -> trimmed to HISTORY_DAYS."""
    now = now or _now()
    t = int(now.timestamp() // 60)
    cutoff = t - HISTORY_DAYS * 24 * 60
    history = history or {}
    for k, c in counts.items():
        rows = [row for row in history.get(k, []) if row[0] >= cutoff]
        rows.append([t, int(c)])
        history[k] = rows
    return history


def assess_region_traffic(rows, now=None):
    """Same-hour-of-day baseline from prior days. Doctrine states only."""
    now = now or _now()
    if not rows:
        return {'state': 'unread', 'now': None, 'baseline': None, 'ratio': None, 'days': 0}
    t_now = int(now.timestamp() // 60)
    latest = rows[-1]
    if t_now - latest[0] > 90:                       # newest sample older than 90 min
        return {'state': 'stale', 'now': latest[1], 'baseline': None, 'ratio': None, 'days': 0}
    minute_of_day = latest[0] % 1440
    prior = []
    days = set()
    for t, c in rows[:-1]:
        if latest[0] - t < 20 * 60:                  # exclude the last 20h (no self-baseline)
            continue
        d = abs((t % 1440) - minute_of_day)
        if min(d, 1440 - d) <= 60:                   # within +-1h of the same clock time
            prior.append(c)
            days.add(t // 1440)
    out = {'now': latest[1], 'baseline': None, 'ratio': None, 'days': len(days)}
    if len(days) < BASELINE_MIN_DAYS:
        out['state'] = 'baseline_building'
        return out
    base = statistics.median(prior)
    out['baseline'] = round(base, 1)
    if base < THIN_COVERAGE_MEDIAN:
        out['state'] = 'thin_coverage'
        return out
    ratio = latest[1] / base
    out['ratio'] = round(ratio, 2)
    prev_ratio = None
    if len(rows) >= 2 and latest[0] - rows[-2][0] <= 90:
        prev_ratio = rows[-2][1] / base
    if ratio < 0.5 and prev_ratio is not None and prev_ratio < 0.5:
        out['state'] = 'sharp_drop'
    elif ratio < 0.75:
        out['state'] = 'below_normal'
    elif ratio >= 1.5:
        out['state'] = 'above_normal'
    else:
        out['state'] = 'normal'
    return out


TRAFFIC_WORDS = {
    'sharp_drop': 'Sharp drop', 'below_normal': 'Below normal', 'normal': 'Normal',
    'above_normal': 'Above normal', 'thin_coverage': 'Thin coverage',
    'baseline_building': 'Baseline building', 'stale': 'Stale', 'unread': 'Unread',
}


# ========================================
# ASSEMBLY
# ========================================
def _paper_for_region(key, czibs, faa_sections):
    aliases = PAPER_ALIASES.get(key, [])
    active = [c for c in czibs if c['status'].lower() == 'active'
              and any(a in (c['country'] + ' ' + c['name']).lower() for a in aliases)]
    faa = None
    for head, sec in (faa_sections or {}).items():
        if any(a in head for a in aliases if a != 'persian gulf'):
            faa = faa or {'kicz': [], 'sfar': [], 'links': [], 'headings': []}
            faa['kicz'] = sorted(set(faa['kicz']) | set(sec['kicz']))
            faa['sfar'] = sorted(set(faa['sfar']) | set(sec['sfar']))
            faa['links'] = (faa['links'] + sec['links'])[:4]
            faa['headings'].append(sec['heading'])
    return active, faa


def _fingerprint(region_paper):
    out = {}
    for key, p in region_paper.items():
        out[key] = {
            'czib': sorted(f"{c['nid']}|{c.get('czib_id') or ''}|{c['valid_until'] or ''}|{c['updated'] or ''}"
                           for c in p['czib']),
            'kicz': (p['faa'] or {}).get('kicz', []),
            'sfar': (p['faa'] or {}).get('sfar', []),
        }
    return out


def diff_paper(prev, cur, now_iso):
    """Compare fingerprints -> list of change events. First run (prev None) = no events."""
    if not prev:
        return []
    events = []
    for key, c in cur.items():
        p = prev.get(key) or {'czib': [], 'kicz': [], 'sfar': []}
        name = REGIONS[key]['name']
        pn = {x.split('|')[0]: x for x in p['czib']}
        cn = {x.split('|')[0]: x for x in c['czib']}
        for nid in cn.keys() - pn.keys():
            events.append({'at': now_iso, 'region': key, 'kind': 'czib_new',
                           'text': f'EASA issued a conflict-zone bulletin covering {name}.'})
        for nid in pn.keys() - cn.keys():
            events.append({'at': now_iso, 'region': key, 'kind': 'czib_withdrawn',
                           'text': f'EASA bulletin covering {name} is no longer active.'})
        for nid in cn.keys() & pn.keys():
            if cn[nid] != pn[nid]:
                events.append({'at': now_iso, 'region': key, 'kind': 'czib_revised',
                               'text': f'EASA revised or extended its bulletin covering {name}.'})
        for k in sorted(set(c['kicz']) - set(p['kicz'])):
            events.append({'at': now_iso, 'region': key, 'kind': 'faa_new',
                           'text': f'FAA listed new security NOTAM {k} for {name}.'})
        for s in sorted(set(c['sfar']) - set(p['sfar'])):
            events.append({'at': now_iso, 'region': key, 'kind': 'faa_new',
                           'text': f'FAA listed SFAR {s} for {name}.'})
    return events


def build_lines(regions, changes):
    """So What lines: convergence and divergence between paper and behaviour."""
    lines = []
    for key, r in regions.items():
        name = r['name']
        paper = bool(r['czib']) or bool(r['faa'])
        st = r['traffic']['state']
        pct = None
        if r['traffic'].get('ratio') is not None:
            pct = round((1 - r['traffic']['ratio']) * 100)
        if st == 'sharp_drop' and paper:
            lines.append(f"{name}: regulators already warn, and traffic is {pct}% below its usual level for this hour "
                         f"-- paper and behaviour agree the airspace is being avoided.")
        elif st == 'sharp_drop' and not paper:
            lines.append(f"{name}: traffic is {pct}% below its usual level with no active EASA or FAA notice "
                         f"-- behaviour is moving ahead of the regulators. Watch for a bulletin.")
        elif st == 'below_normal' and not paper:
            lines.append(f"{name}: traffic is {pct}% below its usual level for this hour (no regulator notice); "
                         f"one reading, not yet a pattern.")
        if st == 'sharp_drop':
            ups = [regions[n]['name'] for n in NEIGHBOURS.get(key, [])
                   if n in regions and regions[n]['traffic']['state'] == 'above_normal']
            if ups:
                lines.append(f"Traffic leaving {name} appears over {', '.join(ups)} -- consistent with rerouting.")
    recent = [c for c in (changes or [])
              if c.get('at') and (_now() - datetime.fromisoformat(c['at'])).total_seconds() < 72 * 3600]
    for c in recent[:4]:
        lines.append(c['text'] + ' (last 72h)')
    if not lines:
        warned = [r['name'] for r in regions.values() if r['czib'] or r['faa']]
        if warned:
            lines.append(f"Standing regulator warnings cover {', '.join(warned)}; no new notice and no traffic "
                         f"anomaly detected this cycle.")
    return lines


def assemble(czibs, easa_src, faa_sections, faa_src, history, traffic_src, changes):
    regions = {}
    for key, meta in REGIONS.items():
        active, faa = _paper_for_region(key, czibs, faa_sections)
        regions[key] = {
            'name': meta['name'], 'flag': meta['flag'], 'fir': meta['fir'],
            'czib': [{k: c.get(k) for k in ('name', 'czib_id', 'issued', 'valid_until',
                                             'valid_until_text', 'updated', 'source_url')} for c in active],
            'faa': faa,
            'traffic': assess_region_traffic((history or {}).get(key, [])),
        }
        regions[key]['traffic']['word'] = TRAFFIC_WORDS.get(regions[key]['traffic']['state'], '')
    fresh = [s for s in (easa_src, faa_src, traffic_src) if s.get('state') == 'read']
    some = [s for s in (easa_src, faa_src, traffic_src) if s.get('state') in ('read', 'partial', 'stale')]
    state = 'read' if len(fresh) == 3 else ('partial' if some else 'unread')
    return {
        'success': True,
        'version': AIRSPACE_VERSION,
        'scanned_at': _iso(_now()),
        'state': state,
        'sources': {'easa': easa_src, 'faa': faa_src, 'opensky': traffic_src},
        'regions': regions,
        'changes': (changes or [])[:20],
        'lines': build_lines(regions, changes),
        'all_czibs_active': [{k: c.get(k) for k in ('country', 'name', 'czib_id', 'valid_until', 'source_url')}
                             for c in czibs if c['status'].lower() == 'active'],
        'method': ('Paper: EASA conflict-zone bulletins + FAA prohibitions page. Behaviour: airborne aircraft '
                   'counted per region by OpenSky Network, compared with the median for the same clock hour '
                   f'on prior days (needs {BASELINE_MIN_DAYS} days). ADS-B coverage is uneven; thin regions are '
                   'labelled, not scored.'),
    }


def to_legacy_notams(payload):
    """Shape for the existing ME widget (expects data.notams[])."""
    items = []
    for key, r in (payload.get('regions') or {}).items():
        for c in r['czib']:
            items.append({
                'region': key, 'country': r['name'], 'flag': r['flag'], 'icao_location': r['fir'],
                'type': 'EASA Conflict Zone Bulletin', 'type_color': 'red',
                'summary': f"{c['name']}{' (' + c['czib_id'] + ')' if c.get('czib_id') else ''}. "
                           f"{c.get('valid_until_text') or ''}".strip(),
                'valid_from': (c.get('issued') or '')[:10], 'valid_to': (c.get('valid_until') or '')[:10],
                'source': 'EASA', 'source_url': c.get('source_url'),
            })
        if r['faa']:
            ids = ', '.join((['SFAR ' + s for s in r['faa']['sfar']] + r['faa']['kicz'])[:6])
            items.append({
                'region': key, 'country': r['name'], 'flag': r['flag'], 'icao_location': r['fir'],
                'type': 'US Operator Restriction', 'type_color': 'orange',
                'summary': f"FAA restrictions listed for US operators: {ids}.",
                'valid_from': '', 'valid_to': '',
                'source': 'FAA', 'source_url': (r['faa']['links'] or [FAA_RESTRICTIONS_URL])[0],
            })
        t = r['traffic']
        if t['state'] in ('sharp_drop', 'below_normal'):
            items.append({
                'region': key, 'country': r['name'], 'flag': r['flag'], 'icao_location': r['fir'],
                'type': 'Traffic Drop' if t['state'] == 'sharp_drop' else 'Traffic Below Normal',
                'type_color': 'red' if t['state'] == 'sharp_drop' else 'yellow',
                'summary': f"{t['now']} aircraft airborne vs ~{t['baseline']} usual for this hour "
                           f"({round((1 - t['ratio']) * 100)}% below).",
                'valid_from': (payload.get('scanned_at') or '')[:10], 'valid_to': '',
                'source': 'OpenSky Network', 'source_url': 'https://opensky-network.org/',
            })
    order = {'red': 0, 'orange': 1, 'yellow': 2}
    items.sort(key=lambda x: order.get(x['type_color'], 9))
    return {
        'success': True, 'state': payload.get('state', 'unread'),
        'sources': payload.get('sources'), 'lines': payload.get('lines', []),
        'notams': items, 'total_notams': len(items), 'count': len(items),
        'timestamp': payload.get('scanned_at'), 'data_source': 'EASA + FAA + OpenSky',
        'version': AIRSPACE_VERSION, 'cached': True,
    }


# ========================================
# SCAN CYCLE
# ========================================
_paper_cache = {'czibs': [], 'easa': {'state': 'unread'}, 'faa_sections': {}, 'faa': {'state': 'unread'},
                'at': 0}


def run_cycle(force_paper=False):
    global _paper_cache
    now = _now()
    if force_paper or time.time() - _paper_cache['at'] >= PAPER_INTERVAL_SEC:
        czibs, easa_src = fetch_easa()
        faa_sections, faa_src = fetch_faa()
        # A failed fetch keeps the last good read, labelled stale -- the bulletins
        # did not vanish because EASA's server blinked.
        if easa_src.get('state') != 'read' and _paper_cache['czibs']:
            czibs = _paper_cache['czibs']
            easa_src = {**easa_src, 'state': 'stale', 'kept_from': _paper_cache['easa'].get('read_at')
                        or _paper_cache['easa'].get('kept_from')}
        if faa_src.get('state') != 'read' and _paper_cache['faa_sections']:
            faa_sections = _paper_cache['faa_sections']
            faa_src = {**faa_src, 'state': 'stale', 'kept_from': _paper_cache['faa'].get('read_at')
                       or _paper_cache['faa'].get('kept_from')}
        _paper_cache = {'czibs': czibs, 'easa': easa_src, 'faa_sections': faa_sections,
                        'faa': faa_src, 'at': time.time()}
    pc = _paper_cache

    counts, traffic_src = scan_traffic()
    history = _rget(K_TRAFFIC) or {}
    if counts:
        history = append_history(history, counts, now)
        _rset(K_TRAFFIC, history)

    payload = assemble(pc['czibs'], pc['easa'], pc['faa_sections'], pc['faa'], history, traffic_src, [])

    # Change detection only when BOTH paper sources were read (a failed fetch is not a withdrawal).
    changes = _rget(K_CHANGES) or []
    if pc['easa'].get('state') == 'read' and pc['faa'].get('state') == 'read':
        region_paper = {k: {'czib': [c for c in pc['czibs'] if c['status'].lower() == 'active'
                                     and any(a in (c['country'] + ' ' + c['name']).lower()
                                             for a in PAPER_ALIASES[k])],
                            'faa': _paper_for_region(k, [], pc['faa_sections'])[1]}
                        for k in REGIONS}
        fp = _fingerprint(region_paper)
        prev = _rget(K_PAPER)
        events = diff_paper(prev, fp, _iso(now))
        if events:
            changes = (events + changes)[:CHANGES_KEEP]
            _rset(K_CHANGES, changes)
        _rset(K_PAPER, fp)
    payload['changes'] = changes[:20]
    payload['lines'] = build_lines(payload['regions'], changes)

    _rset(K_LATEST, payload)
    _rset(K_LEGACY, to_legacy_notams(payload))
    print(f"[Airspace] cycle: state={payload['state']} easa={pc['easa'].get('state')} "
          f"faa={pc['faa'].get('state')} opensky={traffic_src.get('state')} "
          f"({traffic_src.get('regions_read')}/{len(REGIONS)}) credits_left={traffic_src.get('credits_remaining')}")
    return payload


def _unread_payload(reason):
    return {'success': True, 'version': AIRSPACE_VERSION, 'state': 'unread', 'warming': True,
            'reason': reason, 'regions': {}, 'lines': [], 'sources': {}, 'changes': []}


# ========================================
# FLASK REGISTRATION (name kept for app.py compatibility)
# ========================================
def register_notam_endpoints(app):
    from flask import jsonify, request as flask_request

    @app.route('/api/airspace', methods=['GET'])
    def api_airspace():
        data = _rget(K_LATEST) or _unread_payload('first scan not finished yet')
        region = (flask_request.args.get('region') or '').strip().lower()
        if region and data.get('regions'):
            r = data['regions'].get(region)
            if not r:
                return jsonify({'success': False, 'error': f'unknown region: {region}'}), 404
            return jsonify({'success': True, 'region': region, 'data': r, 'state': data.get('state'),
                            'sources': data.get('sources'), 'scanned_at': data.get('scanned_at'),
                            'version': AIRSPACE_VERSION})
        return jsonify(data)

    @app.route('/api/notams', methods=['GET'])
    def api_notams():
        # Public: never scans (no ?force). Reads what the leader wrote.
        data = _rget(K_LATEST)
        if not data:
            out = to_legacy_notams(_unread_payload('first scan not finished yet'))
            out['state'] = 'unread'
            return jsonify(out)
        return jsonify(to_legacy_notams(data))

    @app.route('/api/airspace/health', methods=['GET'])
    def api_airspace_health():
        data = _rget(K_LATEST) or {}
        hist = _rget(K_TRAFFIC) or {}
        return jsonify({
            'version': AIRSPACE_VERSION,
            'state': data.get('state', 'unread'),
            'scanned_at': data.get('scanned_at'),
            'sources': data.get('sources', {}),
            'opensky_configured': bool(OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET),
            'history_samples': {k: len(v) for k, v in hist.items()},
            'baseline_needs_days': BASELINE_MIN_DAYS,
        })

    print("[Airspace] ✅ Endpoints registered: /api/airspace, /api/notams (compat), /api/airspace/health")

    def _loop():
        time.sleep(45)
        try:
            from instance_lock import my_turn as _my_turn
        except ImportError:
            _my_turn = lambda job: True   # no lock module: run (fail-open)
        first = True
        while True:
            if not _my_turn('notam_scan'):
                continue
            try:
                run_cycle(force_paper=first)
                first = False
            except Exception as e:
                print(f"[Airspace] cycle error: {type(e).__name__}: {str(e)[:200]}")
            time.sleep(TRAFFIC_INTERVAL_SEC)

    threading.Thread(target=_loop, daemon=True).start()
    print(f"[Airspace] ✅ Background thread started (traffic {TRAFFIC_INTERVAL_SEC // 60} min, "
          f"paper {PAPER_INTERVAL_SEC // 3600} h, leader only)")
