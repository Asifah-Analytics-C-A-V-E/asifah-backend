"""
Asifah Analytics -- Airspace Watch  v3.0.0  (SHARED MODULE -- byte-identical on all five backends)
November 1, 2026

One file, five backends. Each backend calls
    register_airspace_endpoints(app, '<backend>', legacy_route='/api/<x>/notams')
with backend in: me | europe | asia | africa | wha
and gets ONLY its own regions, its own Redis keys and its own widget feed --
the WHA page never sees Ukraine.

v3.0.0 (Nov 1 2026) -- generalised from ME notam_monitor.py v2.1.0. ME keeps a
5-line notam_monitor.py shim so ME app.py needs no edit. Africa / Asia / Europe
used dead FAA routes (API without credentials, or the NOTAM website form that
returns 403); WHA had no airspace sensor at all.

SOURCES (no logins)
  PAPER      EASA Conflict Zone Information Bulletins (JSON + RSS) and the FAA
             "Prohibitions, Restrictions and Notices" page (SFAR + KICZ).
             Fetched once per 6 h and SHARED through Redis (airspace:paper:shared),
             so five backends do not each hit EASA and the FAA.
  BEHAVIOUR  Airborne aircraft per region: OpenSky Network (OAuth client creds in
             env OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET), else adsb.lol (no key).
             Baselines per provider, per region, same clock hour on prior days.
             One OpenSky account = 4,000 credits/day shared by all backends, so
             cadence differs by backend (ME 30 min, EU/Asia 60, Africa/WHA 120).

DOCTRINE
  Unread is not quiet. Thin coverage is labelled, not scored. No baseline -> no
  claim (3 days). One low reading is 'below normal'; 'sharp drop' needs two.
  Descriptive states only -- no ladder level is asserted from traffic.

History of the ME module this grew from (v2.0.0 / v2.1.0) is in
claude/ME_APP_AUDIT_2026-11-01.md.
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

AIRSPACE_VERSION = '3.0.0'
# v2.1.0 (Nov 1 2026): the standard crawler form "Mozilla/5.0 (compatible; Name/ver; +url)"
# -- the convention Googlebot/Bingbot use. It names us truthfully (no browser is
# impersonated) but passes WAFs that reject anything not starting "Mozilla/5.0".
# faa.gov returned 403 to the bare 'AsifahAnalytics-...' string on the first live run.
AIRSPACE_USER_AGENT = (f'Mozilla/5.0 (compatible; AsifahAnalytics-Airspace/{AIRSPACE_VERSION}; '
                       f'+https://asifahanalytics.com)')   # backend tag added by configure()

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
ADSBLOL_POINT_URL = 'https://api.adsb.lol/v2/point/{lat}/{lon}/{radius}'   # radius in nm, max 250
PROVIDER_LABELS = {'os': 'OpenSky Network', 'al': 'adsb.lol'}
EASA_JSON_URL = ('https://www.easa.europa.eu/en/domains/air-operations/czibs/'
                 'export-json?page&_format=json')
EASA_RSS_URL = 'https://www.easa.europa.eu/en/domains/air-operations/czibs/feed.xml'
EASA_PAGE_URL = 'https://www.easa.europa.eu/en/domains/international-cooperation/easa-by-country/conflict-zones'
FAA_RESTRICTIONS_URL = 'https://www.faa.gov/air_traffic/publications/us_restrictions'

PAPER_INTERVAL_SEC = 6 * 60 * 60      # EASA + FAA: every 6 h (shared across backends)
HISTORY_DAYS = 8                      # traffic samples kept
BASELINE_MIN_DAYS = 3                 # days of samples before any ratio is claimed
THIN_COVERAGE_MEDIAN = 5              # baseline median below this = thin coverage
CHANGES_KEEP = 60
RSS_FALLBACK_DAYS = 180
K_PAPER_SHARED = 'airspace:paper:shared'

# ========================================
# REGION SETS -- one per backend.
#   bbox  = (lat_min, lat_max, lon_min, lon_max), approximate national airspace +
#           approaches; boxes may overlap at borders ("over or near X").
#   paper = lower-case substrings matched against EASA / FAA country names.
#   traffic=False skips the aircraft count (huge or ADS-B-dark areas where a
#           count would only ever say 'thin coverage' while spending credits).
# ========================================
def _R(name, flag, fir, bbox, paper, traffic=True):
    return {'name': name, 'flag': flag, 'fir': fir, 'bbox': bbox, 'paper': paper, 'traffic': traffic}


REGION_SETS = {
    'me': {
        'label': 'Middle East', 'tag': 'ME', 'traffic_interval_min': 30,
        'regions': {
            'israel':       _R('Israel', '🇮🇱', 'LLLL', (29.4, 33.4, 34.2, 35.9), ['israel']),
            'lebanon':      _R('Lebanon', '🇱🇧', 'OLBB', (33.0, 34.7, 35.1, 36.7), ['lebanon']),
            'syria':        _R('Syria', '🇸🇾', 'OSTT', (32.3, 37.4, 35.6, 42.4), ['syria']),
            'iran':         _R('Iran', '🇮🇷', 'OIIX', (25.0, 39.8, 44.0, 63.4), ['iran']),
            'iraq':         _R('Iraq', '🇮🇶', 'ORBB', (29.0, 37.4, 38.8, 48.6), ['iraq']),
            'jordan':       _R('Jordan', '🇯🇴', 'OJAC', (29.2, 33.4, 34.9, 39.3), ['jordan']),
            'egypt':        _R('Egypt', '🇪🇬', 'HECC', (22.0, 31.7, 24.7, 36.9), ['egypt']),
            'saudi_arabia': _R('Saudi Arabia', '🇸🇦', 'OEJD', (16.3, 32.2, 34.5, 55.7), ['saudi']),
            'uae':          _R('UAE', '🇦🇪', 'OMAE', (22.6, 26.1, 51.5, 56.4), ['united arab emirates', 'uae', 'persian gulf', 'gulf of oman']),
            'qatar':        _R('Qatar', '🇶🇦', 'OTDF', (24.4, 26.2, 50.7, 51.7), ['qatar', 'persian gulf']),
            'bahrain':      _R('Bahrain', '🇧🇭', 'OBBB', (25.5, 26.4, 50.3, 50.9), ['bahrain', 'persian gulf']),
            'kuwait':       _R('Kuwait', '🇰🇼', 'OKAC', (28.5, 30.1, 46.5, 48.5), ['kuwait', 'persian gulf']),
            'oman':         _R('Oman', '🇴🇲', 'OOMM', (16.6, 26.4, 52.0, 59.9), ['oman']),
            'yemen':        _R('Yemen', '🇾🇪', 'OYSC', (12.1, 19.0, 42.5, 54.0), ['yemen']),
        },
        'neighbours': {
            'iran': ['iraq', 'saudi_arabia', 'oman', 'uae'], 'iraq': ['iran', 'saudi_arabia', 'jordan', 'syria'],
            'syria': ['iraq', 'jordan', 'lebanon'], 'israel': ['jordan', 'egypt', 'lebanon'],
            'lebanon': ['syria', 'israel'], 'yemen': ['saudi_arabia', 'oman'],
        },
    },
    'europe': {
        'label': 'Europe', 'tag': 'EU', 'traffic_interval_min': 60,
        'regions': {
            'ukraine':        _R('Ukraine', '🇺🇦', 'UKBV', (44.3, 52.4, 22.1, 40.2), ['ukraine']),
            'russia_west':    _R('Western Russia', '🇷🇺', 'UUWV', (50.0, 60.0, 27.0, 45.0), ['russia']),
            'belarus':        _R('Belarus', '🇧🇾', 'UMMV', (51.2, 56.2, 23.2, 32.8), ['belarus']),
            'moldova':        _R('Moldova', '🇲🇩', 'LUUU', (45.4, 48.5, 26.6, 30.2), ['moldova']),
            'poland':         _R('Poland', '🇵🇱', 'EPWW', (49.0, 54.9, 14.1, 24.2), ['poland']),
            'baltic':         _R('Baltic States', '🇪🇺', 'EYVL', (53.9, 59.7, 20.9, 28.2), ['lithuania', 'latvia', 'estonia', 'baltic']),
            'romania':        _R('Romania', '🇷🇴', 'LRBB', (43.6, 48.3, 20.2, 29.7), ['romania']),
            'turkey':         _R('Turkey', '🇹🇷', 'LTAA', (35.8, 42.1, 26.0, 44.8), ['turkey', 'türkiye', 'turkiye']),
            'south_caucasus': _R('South Caucasus', '🇦🇲', 'UDDD', (38.8, 43.6, 40.0, 50.4), ['armenia', 'azerbaijan', 'georgia']),
            'greece':         _R('Greece', '🇬🇷', 'LGGG', (34.8, 41.8, 19.3, 29.7), ['greece']),
            'cyprus':         _R('Cyprus', '🇨🇾', 'LCCC', (34.5, 35.7, 32.2, 34.6), ['cyprus']),
            'albania':        _R('Albania', '🇦🇱', 'LAAA', (39.6, 42.7, 19.2, 21.1), ['albania']),
            'belgium':        _R('Belgium', '🇧🇪', 'EBBU', (49.5, 51.5, 2.5, 6.4), ['belgium']),
            'denmark':        _R('Denmark', '🇩🇰', 'EKDK', (54.5, 57.8, 8.0, 15.2), ['denmark']),
            'greenland':      _R('Greenland', '🇬🇱', 'BGGL', (59.7, 83.7, -73.0, -11.0), ['greenland'], traffic=False),
        },
        'neighbours': {
            'ukraine': ['poland', 'romania', 'moldova'], 'russia_west': ['baltic', 'belarus'],
            'belarus': ['poland', 'baltic'],
        },
    },
    'asia': {
        'label': 'Asia-Pacific', 'tag': 'AS', 'traffic_interval_min': 60,
        'regions': {
            'taiwan_strait':    _R('Taiwan Strait', '🇹🇼', 'RCAA', (21.5, 27.0, 117.0, 123.0), ['taiwan', 'china']),
            'korean_peninsula': _R('Korean Peninsula', '🇰🇷', 'RKRR', (33.0, 43.0, 124.0, 131.0), ['korea', 'dprk']),
            'japan':            _R('Japan / Okinawa', '🇯🇵', 'RJJJ', (24.0, 36.0, 123.0, 141.0), ['japan']),
            'south_china_sea':  _R('South China Sea', '🌊', 'RPHI', (5.0, 22.0, 108.0, 121.0), ['south china sea', 'philippines']),
            'vietnam':          _R('Vietnam', '🇻🇳', 'VVHN', (8.4, 23.4, 102.1, 109.5), ['vietnam', 'viet nam']),
            'pakistan':         _R('Pakistan', '🇵🇰', 'OPKR', (23.6, 37.1, 60.9, 77.8), ['pakistan']),
            'afghanistan':      _R('Afghanistan', '🇦🇫', 'OAKX', (29.4, 38.5, 60.5, 74.9), ['afghanistan']),
            'india':            _R('India (north/west)', '🇮🇳', 'VIDF', (20.0, 35.0, 68.0, 84.0), ['india']),
            'myanmar':          _R('Myanmar', '🇲🇲', 'VYYF', (9.8, 28.5, 92.2, 101.2), ['myanmar', 'burma']),
            'central_asia':     _R('Central Asia', '🇰🇿', 'UAAA', (37.0, 55.5, 46.5, 87.0), ['kazakhstan', 'kyrgyz', 'tajikistan', 'turkmenistan', 'uzbekistan'], traffic=False),
        },
        'neighbours': {'pakistan': ['afghanistan', 'india'], 'taiwan_strait': ['japan', 'south_china_sea']},
    },
    'africa': {
        'label': 'Africa', 'tag': 'AF', 'traffic_interval_min': 120,
        'regions': {
            'sudan':        _R('Sudan', '🇸🇩', 'HSSS', (8.7, 22.2, 21.8, 38.6), ['sudan']),
            'south_sudan':  _R('South Sudan', '🇸🇸', 'HJJJ', (3.5, 12.2, 24.1, 35.9), ['south sudan']),
            'ethiopia':     _R('Ethiopia', '🇪🇹', 'HAAA', (3.4, 14.9, 33.0, 48.0), ['ethiopia', 'eritrea']),
            'somalia':      _R('Somalia', '🇸🇴', 'HCSM', (-1.7, 12.0, 41.0, 51.4), ['somalia']),
            'kenya':        _R('Kenya', '🇰🇪', 'HKNA', (-4.7, 5.0, 33.9, 41.9), ['kenya']),
            'uganda':       _R('Uganda', '🇺🇬', 'HUEC', (-1.5, 4.2, 29.6, 35.0), ['uganda']),
            'rwanda':       _R('Rwanda', '🇷🇼', 'HRYR', (-2.9, -1.0, 28.8, 30.9), ['rwanda']),
            'drc':          _R('DR Congo', '🇨🇩', 'FZZA', (-13.5, 5.4, 12.2, 31.3), ['congo', 'drc']),
            'libya':        _R('Libya', '🇱🇾', 'HLLL', (19.5, 33.2, 9.4, 25.2), ['libya']),
            'chad':         _R('Chad', '🇹🇩', 'FTTT', (7.4, 23.5, 13.5, 24.0), ['chad']),
            'niger':        _R('Niger', '🇳🇪', 'DRRR', (11.7, 23.5, 0.2, 16.0), ['niger'], traffic=False),
            'mali':         _R('Mali', '🇲🇱', 'GOOO', (10.1, 25.0, -12.3, 4.3), ['mali'], traffic=False),
            'burkina_faso': _R('Burkina Faso', '🇧🇫', 'DFFF', (9.4, 15.1, -5.5, 2.4), ['burkina']),
            'nigeria':      _R('Nigeria', '🇳🇬', 'DNKK', (4.3, 13.9, 2.7, 14.7), ['nigeria']),
            'morocco':      _R('Morocco', '🇲🇦', 'GMMM', (27.6, 35.9, -13.2, -1.0), ['morocco', 'western sahara']),
            'mozambique':   _R('Mozambique (north)', '🇲🇿', 'FQBE', (-17.0, -10.4, 34.5, 40.9), ['mozambique']),
            'south_africa': _R('South Africa', '🇿🇦', 'FAJA', (-34.8, -22.1, 16.5, 32.9), ['south africa']),
        },
        'neighbours': {'sudan': ['chad', 'south_sudan', 'ethiopia'], 'somalia': ['kenya', 'ethiopia']},
    },
    'wha': {
        'label': 'Western Hemisphere', 'tag': 'WHA', 'traffic_interval_min': 120,
        'regions': {
            'venezuela': _R('Venezuela', '🇻🇪', 'SVZM', (0.6, 12.2, -73.4, -59.8), ['venezuela']),
            'colombia':  _R('Colombia', '🇨🇴', 'SKED', (-4.2, 12.5, -79.0, -66.9), ['colombia']),
            'cuba':      _R('Cuba', '🇨🇺', 'MUFH', (19.8, 23.3, -85.0, -74.1), ['cuba']),
            'haiti':     _R('Haiti', '🇭🇹', 'MTEG', (18.0, 20.1, -74.5, -71.6), ['haiti']),
            'mexico':    _R('Mexico', '🇲🇽', 'MMFR', (14.5, 32.7, -118.4, -86.7), ['mexico']),
            'panama':    _R('Panama', '🇵🇦', 'MPZL', (7.2, 9.7, -83.0, -77.2), ['panama']),
            'peru':      _R('Peru', '🇵🇪', 'SPIM', (-18.4, 0.0, -81.3, -68.7), ['peru']),
            'chile':     _R('Chile', '🇨🇱', 'SCEZ', (-56.0, -17.5, -75.7, -66.4), ['chile']),
            'brazil':    _R('Brazil', '🇧🇷', 'SBBS', (-33.8, 5.3, -73.9, -34.8), ['brazil'], traffic=False),
        },
        'neighbours': {'venezuela': ['colombia'], 'haiti': ['cuba']},
    },
}

# Active configuration -- set once per process by configure(). One process = one backend.
BACKEND = None
REGIONS = {}
NEIGHBOURS = {}
PAPER_ALIASES = {}
TRAFFIC_INTERVAL_SEC = 30 * 60
K_LATEST = K_TRAFFIC = K_PAPER = K_CHANGES = None
K_LEGACY = None


def configure(backend):
    """Select the region set for this process. Called by register_airspace_endpoints."""
    global BACKEND, REGIONS, NEIGHBOURS, PAPER_ALIASES, TRAFFIC_INTERVAL_SEC
    global K_LATEST, K_TRAFFIC, K_PAPER, K_CHANGES, K_LEGACY, AIRSPACE_USER_AGENT
    if backend not in REGION_SETS:
        raise ValueError(f'unknown backend {backend!r}; expected one of {sorted(REGION_SETS)}')
    cfg = REGION_SETS[backend]
    BACKEND = backend
    REGIONS = cfg['regions']
    NEIGHBOURS = cfg['neighbours']
    PAPER_ALIASES = {k: v['paper'] for k, v in REGIONS.items()}
    TRAFFIC_INTERVAL_SEC = cfg['traffic_interval_min'] * 60
    K_LATEST = f'airspace:{backend}:latest'
    K_TRAFFIC = f'airspace:{backend}:traffic_history'
    K_PAPER = f'airspace:{backend}:paper_snapshot'
    K_CHANGES = f'airspace:{backend}:changes'
    K_LEGACY = 'mideast_notam_cache' if backend == 'me' else None   # v1.1.0 key, overwritten so nothing stale lingers
    AIRSPACE_USER_AGENT = (f"Mozilla/5.0 (compatible; AsifahAnalytics-{cfg['tag']}-Airspace/{AIRSPACE_VERSION}; "
                           f"+https://asifahanalytics.com)")
    return cfg


def credits_per_scan(regions=None):
    """OpenSky /states/all cost by bbox area (sq deg): <=25:1, <=100:2, <=400:3, else 4."""
    total = 0
    for r in (regions or REGIONS).values():
        if not r.get('traffic', True):
            continue
        lat0, lat1, lon0, lon1 = r['bbox']
        a = (lat1 - lat0) * (lon1 - lon0)
        total += 1 if a <= 25 else 2 if a <= 100 else 3 if a <= 400 else 4
    return total


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
    rows = payload
    if isinstance(payload, dict):
        rows = None
        for k in ('data', 'nodes', 'rows', 'items', 'results'):
            if isinstance(payload.get(k), list):
                rows = payload[k]
                break
        if rows is None:
            lists = [v for v in payload.values() if isinstance(v, list)]
            if lists:
                rows = max(lists, key=len)
            elif payload and all(isinstance(v, dict) for v in payload.values()):
                rows = list(payload.values())          # {"0": {...}, "1": {...}}
            else:
                rows = []
    out = []
    for r in rows or []:
        if isinstance(r, dict) and isinstance(r.get('node'), dict):
            r = r['node']                              # Drupal views wraps rows as {"node": {...}}
        if not isinstance(r, dict):
            continue
        name = _squash(_strip_tags(r.get('name', '') or r.get('title', '')))
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
        title, desc, link = tag('title'), tag('description'), tag('link')
        lm = re.search(r'czib-(\d{4}-\d{2})-?(r\d+)?', link or '', re.I)
        if lm:
            czib_id = lm.group(1) + ('-' + lm.group(2).upper() if lm.group(2) else '')
        else:
            idm = _CZIB_ID_RX.search(title + ' ' + desc)
            czib_id = _squash(idm.group(1)).replace(' ', '') if idm else None
        items.append({'title': title, 'czib_id': czib_id,
                      'country': re.sub(r'^airspace of (the )?', '', title, flags=re.I).strip(),
                      'link': link, 'pub': _iso(_parse_any_dt(tag('pubDate')))})
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
            j = r.json()
            src['json_shape'] = (f"list[{len(j)}]" if isinstance(j, list) else
                                 f"dict keys={list(j)[:6]}" if isinstance(j, dict) else type(j).__name__)
            czibs = parse_easa_json(j)
    except Exception as e:
        src['error'] = f'JSON {type(e).__name__}: {str(e)[:120]}'

    # RSS: pick up CZIB numbers + any revision newer than the JSON's record.
    rss = []
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
    elif rss:
        # Fallback: the RSS has no status or expiry. Newest item per country, published
        # within RSS_FALLBACK_DAYS, is shown as LISTED with status unconfirmed -- and the
        # source reports 'partial', so change detection (which needs 'read') stays off.
        cutoff = _now().timestamp() - RSS_FALLBACK_DAYS * 86400
        newest = {}
        for i in rss:
            if not i['pub'] or datetime.fromisoformat(i['pub']).timestamp() < cutoff:
                continue
            k = i['country'].lower()
            if k not in newest or i['pub'] > newest[k]['pub']:
                newest[k] = i
        for i in newest.values():
            czibs.append({'nid': i['link'], 'name': i['title'], 'country': i['country'],
                          'status': 'Active', 'status_confirmed': False, 'issued': i['pub'],
                          'valid_until': None,
                          'valid_until_text': 'Status and expiry not confirmed (read from EASA RSS).',
                          'updated': i['pub'], 'czib_id': i['czib_id'], 'source_url': i['link']})
        src.update(state='partial', read_at=_iso(_now()), count=len(czibs),
                   note=f'JSON gave no rows; RSS fallback (newest per country, last {RSS_FALLBACK_DAYS} days)')
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
            last = None
            for attempt in (1, 2):
                try:
                    r = requests.post(OPENSKY_TOKEN_URL, data={
                        'grant_type': 'client_credentials',
                        'client_id': OPENSKY_CLIENT_ID,
                        'client_secret': OPENSKY_CLIENT_SECRET,
                    }, headers={'User-Agent': AIRSPACE_USER_AGENT}, timeout=(30, 30))
                    if r.status_code != 200:
                        return None, f'token HTTP {r.status_code}'
                    j = r.json()
                    self.token = j.get('access_token')
                    self.expires = time.time() + int(j.get('expires_in', 1800))
                    return self.token, None if self.token else 'token missing in response'
                except Exception as e:
                    last = f'token {type(e).__name__} (attempt {attempt})'
                    time.sleep(5)
            return None, last


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


def scan_opensky():
    """Returns ({region: count}, source_state)."""
    src = {'state': 'unread', 'read_at': None, 'error': None, 'credits_remaining': None,
           'regions_read': 0, 'regions_total': len(_traffic_keys()), 'provider': 'os'}
    token, err = _token.get()
    if not token:
        src['error'] = err
        return {}, src
    counts = {}
    for key in _traffic_keys():
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
        src['state'] = 'read' if len(counts) == len(_traffic_keys()) else 'partial'
        src['read_at'] = _iso(_now())
    return counts, src


def _traffic_keys():
    return [k for k, v in REGIONS.items() if v.get('traffic', True)]


def _region_circle(key):
    """bbox -> (lat, lon, radius_nm) for point queries. Radius capped at 250 nm, so
    the biggest regions (Iran, Saudi, Egypt) are sampled, not covered -- the same
    circle every time, so the same-hour comparison still holds."""
    import math
    lat0, lat1, lon0, lon1 = REGIONS[key]['bbox']
    lat, lon = (lat0 + lat1) / 2, (lon0 + lon1) / 2
    dlat = (lat1 - lat0) * 60 / 2
    dlon = (lon1 - lon0) * 60 * math.cos(math.radians(lat)) / 2
    return round(lat, 2), round(lon, 2), int(max(25, min(250, math.hypot(dlat, dlon))))


def count_airborne_adsblol(ac_list):
    n = 0
    for a in ac_list or []:
        if not isinstance(a, dict) or a.get('lat') is None or a.get('lon') is None:
            continue
        if a.get('alt_baro') == 'ground':
            continue
        n += 1
    return n


def scan_adsblol():
    """Fallback behaviour provider: adsb.lol community ADS-B, no key."""
    src = {'state': 'unread', 'read_at': None, 'error': None, 'regions_read': 0,
           'regions_total': len(_traffic_keys()), 'provider': 'al'}
    counts = {}
    for key in _traffic_keys():
        lat, lon, rad = _region_circle(key)
        try:
            r = requests.get(ADSBLOL_POINT_URL.format(lat=lat, lon=lon, radius=rad),
                             headers={'User-Agent': AIRSPACE_USER_AGENT}, timeout=(15, 30))
            if r.status_code == 429:
                src['error'] = 'rate limited'
                src['state'] = 'rate_limited'
                break
            if r.status_code != 200:
                src['error'] = f'{key}: HTTP {r.status_code}'
                continue
            counts[key] = count_airborne_adsblol((r.json() or {}).get('ac'))
            time.sleep(1.5)                      # polite: well under 1 request/second
        except Exception as e:
            src['error'] = f'{key}: {type(e).__name__}'
    src['regions_read'] = len(counts)
    if counts:
        src['state'] = 'read' if len(counts) == len(_traffic_keys()) else 'partial'
        src['read_at'] = _iso(_now())
    return counts, src


def scan_traffic():
    """OpenSky first; adsb.lol only if OpenSky could not be read at all."""
    counts, src = scan_opensky()
    if counts:
        return counts, src
    first_err = src.get('error')
    counts, src2 = scan_adsblol()
    src2['fallback_from'] = f'OpenSky: {first_err}'
    return counts, src2


def append_history(history, counts, now=None, provider='os'):
    """history = {'<provider>:<region>': [[epoch_min, count], ...]} -> trimmed to HISTORY_DAYS.
    Keyed per provider: two networks' counts are never mixed into one baseline."""
    now = now or _now()
    t = int(now.timestamp() // 60)
    cutoff = t - HISTORY_DAYS * 24 * 60
    history = history or {}
    for k in list(history):
        history[k] = [row for row in history[k] if row[0] >= cutoff]
        if not history[k]:
            del history[k]
    for k, c in counts.items():
        hk = f'{provider}:{k}'
        rows = history.get(hk, [])
        rows.append([t, int(c)])
        history[hk] = rows
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
    'above_normal': 'Above normal', 'thin_coverage': 'Thin coverage', 'not_measured': 'Not measured',
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
            'traffic': (assess_region_traffic((history or {}).get(
                f"{traffic_src.get('provider', 'os')}:{key}", []))
                if meta.get('traffic', True) else
                {'state': 'not_measured', 'now': None, 'baseline': None, 'ratio': None, 'days': 0}),
        }
        regions[key]['traffic']['provider'] = PROVIDER_LABELS.get(traffic_src.get('provider', 'os'))
        regions[key]['traffic']['word'] = TRAFFIC_WORDS.get(regions[key]['traffic']['state'], '')
    fresh = [s for s in (easa_src, faa_src, traffic_src) if s.get('state') == 'read']
    some = [s for s in (easa_src, faa_src, traffic_src) if s.get('state') in ('read', 'partial', 'stale')]
    state = 'read' if len(fresh) == 3 else ('partial' if some else 'unread')
    return {
        'success': True,
        'version': AIRSPACE_VERSION,
        'backend': BACKEND,
        'region_label': REGION_SETS[BACKEND]['label'] if BACKEND else None,
        'scanned_at': _iso(_now()),
        'state': state,
        'sources': {'easa': easa_src, 'faa': faa_src, 'opensky': traffic_src},   # key kept for the page
        'regions': regions,
        'changes': (changes or [])[:20],
        'lines': build_lines(regions, changes),
        'all_czibs_active': [{k: c.get(k) for k in ('country', 'name', 'czib_id', 'valid_until', 'source_url')}
                             for c in czibs if c['status'].lower() == 'active'],
        'method': ('Paper: EASA conflict-zone bulletins + FAA prohibitions page. Behaviour: airborne aircraft '
                   'counted per region (OpenSky Network; adsb.lol if OpenSky is unreachable -- never mixed), compared with the median for the same clock hour '
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
                'source': t.get('provider') or 'ADS-B',
                'source_url': ('https://adsb.lol/' if t.get('provider') == 'adsb.lol'
                               else 'https://opensky-network.org/'),
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
        shared = _rget(K_PAPER_SHARED)
        if shared and time.time() - shared.get('at', 0) < PAPER_INTERVAL_SEC:
            # Another backend fetched EASA + FAA within 6 h -- reuse it.
            czibs, easa_src = shared['czibs'], {**shared['easa'], 'via': 'shared cache'}
            faa_sections, faa_src = shared['faa_sections'], {**shared['faa'], 'via': 'shared cache'}
        else:
            czibs, easa_src = fetch_easa()
            faa_sections, faa_src = fetch_faa()
            # Share only when EASA was read: a failed fetch must not be reused by four other
            # backends for 6 h. (FAA's state is shared as-is -- a 403 here is a 403 there.)
            if easa_src.get('state') in ('read', 'partial'):
                _rset(K_PAPER_SHARED, {'czibs': czibs, 'easa': easa_src, 'faa_sections': faa_sections,
                                       'faa': faa_src, 'at': time.time()})
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
        history = append_history(history, counts, now, provider=traffic_src.get('provider', 'os'))
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
    if K_LEGACY:
        _rset(K_LEGACY, to_legacy_notams(payload))
    print(f"[Airspace:{BACKEND}] cycle: state={payload['state']} easa={pc['easa'].get('state')} "
          f"faa={pc['faa'].get('state')} traffic[{traffic_src.get('provider')}]={traffic_src.get('state')} "
          f"({traffic_src.get('regions_read')}/{len(_traffic_keys())}) credits_left={traffic_src.get('credits_remaining')}")
    return payload


def _unread_payload(reason):
    return {'success': True, 'version': AIRSPACE_VERSION, 'state': 'unread', 'warming': True,
            'reason': reason, 'regions': {}, 'lines': [], 'sources': {}, 'changes': []}


# ========================================
# FLASK REGISTRATION
# ========================================
def register_airspace_endpoints(app, backend, legacy_route=None, job_name=None):
    """backend: me | europe | asia | africa | wha.
    legacy_route: the path the existing page widget already calls (e.g. '/api/europe/notams');
    it gets the compatibility shape. The old route of the same path must be removed from app.py
    (Flask serves whichever rule was registered first)."""
    from flask import jsonify, request as flask_request
    cfg = configure(backend)
    job = job_name or ('notam_scan' if backend == 'me' else f'airspace_scan_{backend}')

    def api_airspace():
        data = _rget(K_LATEST) or _unread_payload('first scan not finished yet')
        region = (flask_request.args.get('region') or '').strip().lower()
        if region and data.get('regions'):
            r = data['regions'].get(region)
            if not r:
                return jsonify({'success': False, 'error': f'unknown region: {region}',
                                'regions': sorted(data['regions'])}), 404
            return jsonify({'success': True, 'region': region, 'data': r, 'state': data.get('state'),
                            'sources': data.get('sources'), 'scanned_at': data.get('scanned_at'),
                            'version': AIRSPACE_VERSION, 'backend': BACKEND})
        return jsonify(data)

    def api_legacy():
        # Public: never scans (no ?force). Reads what the scanner wrote.
        data = _rget(K_LATEST)
        if not data:
            out = to_legacy_notams(_unread_payload('first scan not finished yet'))
            out['state'] = 'unread'
            return jsonify(out)
        return jsonify(to_legacy_notams(data))

    def api_airspace_health():
        data = _rget(K_LATEST) or {}
        hist = _rget(K_TRAFFIC) or {}
        per_scan = credits_per_scan()
        return jsonify({
            'version': AIRSPACE_VERSION,
            'backend': BACKEND,
            'state': data.get('state', 'unread'),
            'scanned_at': data.get('scanned_at'),
            'sources': data.get('sources', {}),
            'opensky_configured': bool(OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET),
            'opensky_credits_est_per_day': per_scan * (1440 // cfg['traffic_interval_min']),
            'traffic_interval_min': cfg['traffic_interval_min'],
            'regions': sorted(REGIONS),
            'history_samples': {k: len(v) for k, v in hist.items()},
            'baseline_needs_days': BASELINE_MIN_DAYS,
        })

    app.add_url_rule('/api/airspace', 'airspace_watch_payload', api_airspace, methods=['GET'])
    app.add_url_rule('/api/airspace/health', 'airspace_watch_health', api_airspace_health, methods=['GET'])
    if legacy_route:
        app.add_url_rule(legacy_route, 'airspace_watch_legacy', api_legacy, methods=['GET'])
    print(f"[Airspace:{backend}] ✅ /api/airspace, /api/airspace/health"
          f"{', ' + legacy_route + ' (compat)' if legacy_route else ''} -- {len(REGIONS)} regions")

    def _loop():
        time.sleep(45)
        try:
            from instance_lock import my_turn as _my_turn
        except ImportError:
            _my_turn = lambda j: True   # single-instance backends: no lock module, always run
        first = True
        while True:
            if not _my_turn(job):
                continue
            try:
                run_cycle(force_paper=first)
                first = False
            except Exception as e:
                print(f"[Airspace:{backend}] cycle error: {type(e).__name__}: {str(e)[:200]}")
            time.sleep(TRAFFIC_INTERVAL_SEC)

    threading.Thread(target=_loop, daemon=True).start()
    print(f"[Airspace:{backend}] ✅ Background thread (traffic every {cfg['traffic_interval_min']} min, "
          f"paper every {PAPER_INTERVAL_SEC // 3600} h shared)")
