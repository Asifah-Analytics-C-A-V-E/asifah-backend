# -*- coding: utf-8 -*-
"""kinetic_activity_gatherer.py  --  Asifah Analytics  (Slice 1: engine)

Gap-filling kinetic-activity tracker for the UNCOVERED world.

Backbone:    GDELT 2.0 Events (CAMEO-coded, georeferenced) -- gives us the
             event type, a conflict/cooperation intensity (Goldstein), and a
             location, WITHOUT us having to pre-write keywords per country.
Scoring:     CAMEO root codes map onto the Asifah escalation ladder
             (routine statement -> posturing/exercise -> coercion -> kinetic)
             plus a parallel de-escalation / cooperation track.
Surfaces to: GPI as the 'global_kinetic' virtual region (wired in Slice 2).

DISCIPLINE: convergence framing, NOT prediction. We report what kinetic
activity is PRESENT, not whether/where force WILL be used.

NOTE (first-deploy verification): the GDELT Events file fetch + FIPS country
mapping below are built to the documented GDELT 2.0 schema but have NOT been
live-tested in this environment. The first force-scan is where we confirm the
response shape, the window size, and the FIPS->country attribution -- same
"verify on first deploy" discipline as the Badil RSS URL.
"""

import os
import io
import csv
import json
import time
import zipfile
import threading
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

KINETIC_CACHE_KEY   = 'kinetic:global:latest'
KINETIC_TTL_SECONDS = 13 * 3600       # 13h (outlasts the 12h scan gap)
SCAN_INTERVAL_HOURS = 12              # 2x/day

# GDELT 2.0 Events: the 15-min export files carry the full CAMEO coding.
GDELT_LASTUPDATE_URL = 'http://data.gdeltproject.org/gdeltv2/lastupdate.txt'
GDELT_EXPORT_FMT     = 'http://data.gdeltproject.org/gdeltv2/%s.export.CSV.zip'
GDELT_WINDOW_FILES   = 8              # v1: sample the most recent ~2h of global events per scan
GDELT_HTTP_TIMEOUT   = 20

# Corroboration gate: a CAMEO event needs at least this many articles behind it
# before it can set a country's peak level (kills single-source false positives).
MIN_ARTICLES_FOR_PEAK = 3

CONVERGENCE_DISCLAIMER = (
    "This is a CONVERGENCE indicator, NOT a probability of action. Active "
    "signals indicate that kinetic activity is being reported in open sources; "
    "they do not predict whether or when further force will be used."
)

# ============================================================
# CROSS-WORKER SCHEDULER LOCK  [Jun 2026]  (baked in from line one)
# gunicorn --workers 2 starts this scheduler in BOTH workers. Without this lock
# both would scan and double every GDELT pull. Atomic Upstash SET NX EX makes
# exactly ONE worker own the scan; the owner renews each cycle (TTL > cycle so
# ownership never lapses while alive); if it dies, the lock expires and another
# worker takes over. Fail-open: if Redis is unreachable we proceed.
# ============================================================
_SCHED_WORKER_ID = f"w{os.getpid()}"

def _acquire_scheduler_lock(name, ttl_seconds):
    """Return True if THIS worker owns the scheduler lock for `name`."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return True
    key = f"sched_lock:{name}"
    hdr = {"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}
    try:
        r = requests.post(UPSTASH_REDIS_URL, headers=hdr,
                          json=["SET", key, _SCHED_WORKER_ID, "NX", "EX", str(ttl_seconds)],
                          timeout=8)
        if r.ok and (r.json() or {}).get('result') == 'OK':
            return True
        g = requests.get(f"{UPSTASH_REDIS_URL}/get/{key}", headers=hdr, timeout=8)
        owner = (g.json() or {}).get('result') if g.ok else None
        if owner == _SCHED_WORKER_ID:
            requests.post(UPSTASH_REDIS_URL, headers=hdr,
                          json=["SET", key, _SCHED_WORKER_ID, "EX", str(ttl_seconds)],
                          timeout=8)
            return True
        return False
    except Exception as e:
        print(f"[SchedLock] {name}: lock check failed ({e}); proceeding (fail-open)")
        return True

# ============================================================
# REDIS HELPERS
# ============================================================
def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(f"{UPSTASH_REDIS_URL}/get/{key}",
                            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                            timeout=8)
        body = resp.json()
        if body.get('result'):
            return json.loads(body['result'])
    except Exception as e:
        print(f"[kinetic_gatherer] Redis get error: {str(e)[:120]}")
    return None

def _redis_set(key, value, ttl_seconds=KINETIC_TTL_SECONDS):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        requests.post(f"{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_seconds)}",
                      headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                      data=json.dumps(value),
                      timeout=8)
        return True
    except Exception as e:
        print(f"[kinetic_gatherer] Redis set error: {str(e)[:120]}")
        return False

# ============================================================
# CAMEO LADDER  --  root code -> (track, level, label)
# track: 'conflict' feeds the escalation ladder; 'cooperation' feeds the
# de-escalation track; 'statement' is base-level noise.
# level: Asifah L1..L5  (routine statement -> posturing/exercise -> kinetic)
# ============================================================
CAMEO_ROOT = {
    '01': ('statement',   1, 'Public statement'),
    '02': ('statement',   1, 'Appeal'),
    '03': ('cooperation', 2, 'Express intent to cooperate'),
    '04': ('cooperation', 2, 'Consult'),
    '05': ('cooperation', 3, 'Diplomatic cooperation'),
    '06': ('cooperation', 3, 'Material cooperation'),   # incl. peacekeeping
    '07': ('cooperation', 3, 'Provide aid'),
    '08': ('cooperation', 4, 'Yield'),                  # incl. ceasefire / withdraw
    '09': ('statement',   1, 'Investigate'),
    '10': ('conflict',    1, 'Demand'),
    '11': ('conflict',    1, 'Disapprove'),
    '12': ('conflict',    2, 'Reject'),
    '13': ('conflict',    2, 'Threaten'),
    '14': ('conflict',    2, 'Protest'),
    '15': ('conflict',    3, 'Exhibit force posture'),  # troop movement / "look at me" exercises
    '16': ('conflict',    3, 'Reduce relations'),
    '17': ('conflict',    4, 'Coerce'),
    '18': ('conflict',    4, 'Assault'),
    '19': ('conflict',    5, 'Fight'),                  # actual kinetic
    '20': ('conflict',    5, 'Use unconventional mass violence'),
}

# Per-country conflict-score bands (weighted event score -> band label).
BAND_SURGE    = 40
BAND_HIGH     = 20
BAND_ELEVATED = 8

# GDELT ActionGeo uses FIPS 10-4 country codes (NOT ISO!). These are the
# non-intuitive ones that matter most for the uncovered/active-conflict world.
# Anything not here falls back to the event's human-readable location name, so
# we never silently drop an event -- but verify these on first deploy.
FIPS_TO_COUNTRY = {
    'SU': 'Sudan',        'NG': 'Niger',        'NI': 'Nigeria',
    'BM': 'Myanmar',      'KU': 'Kuwait',       'AE': 'United Arab Emirates',
    'SA': 'Saudi Arabia', 'IR': 'Iran',         'IZ': 'Iraq',
    'IS': 'Israel',       'LE': 'Lebanon',      'SY': 'Syria',
    'YM': 'Yemen',        'UP': 'Ukraine',      'RS': 'Russia',
    'CH': 'China',        'TW': 'Taiwan',       'KN': 'North Korea',
    'CG': 'DR Congo',     'ET': 'Ethiopia',     'SO': 'Somalia',
    'ML': 'Mali',         'UV': 'Burkina Faso', 'LY': 'Libya',
    'PK': 'Pakistan',     'AF': 'Afghanistan',  'VE': 'Venezuela',
    'CO': 'Colombia',     'MX': 'Mexico',       'HA': 'Haiti',
    'EG': 'Egypt',        'JO': 'Jordan',       'TU': 'Turkey',
}

# GDELT 2.0 Events column indices (0-based, fixed 61-column schema).
COL_EVENT_ROOT   = 28
COL_QUADCLASS    = 29
COL_GOLDSTEIN    = 30
COL_NUM_ARTICLES = 33
COL_GEO_FULLNAME = 52
COL_GEO_COUNTRY  = 53   # FIPS
COL_GEO_LAT      = 56
COL_GEO_LONG     = 57
COL_SOURCEURL    = 60
MIN_COLS         = 61

# ============================================================
# GDELT FETCH
# ============================================================
def _recent_export_urls(n_files):
    """Return up to n_files recent GDELT export URLs, newest first.

    Reads lastupdate.txt for the newest 15-min stamp, then walks backward in
    15-min steps building timestamped URLs. Some slots may 404 -- caller skips.
    """
    urls = []
    try:
        resp = requests.get(GDELT_LASTUPDATE_URL, timeout=GDELT_HTTP_TIMEOUT)
        # lastupdate.txt: 3 lines "size hash url"; the export line ends in export.CSV.zip
        latest_url = None
        for line in resp.text.strip().splitlines():
            parts = line.split()
            if parts and parts[-1].endswith('export.CSV.zip'):
                latest_url = parts[-1]
                break
        if not latest_url:
            return urls
        # Extract the YYYYMMDDHHMMSS stamp from the filename.
        stamp = latest_url.rsplit('/', 1)[-1].split('.', 1)[0]
        t = datetime.strptime(stamp, '%Y%m%d%H%M%S')
        for i in range(n_files):
            ts = (t - timedelta(minutes=15 * i)).strftime('%Y%m%d%H%M%S')
            urls.append(GDELT_EXPORT_FMT % ts)
    except Exception as e:
        print(f"[kinetic_gatherer] lastupdate fetch error: {str(e)[:120]}")
    return urls

def _parse_event_row(row):
    """Map one GDELT TSV row to a kinetic event dict, or None if not relevant.

    Pure function -- unit-testable with synthetic rows.
    """
    if len(row) < MIN_COLS:
        return None
    root = (row[COL_EVENT_ROOT] or '').strip()
    mapping = CAMEO_ROOT.get(root)
    if not mapping:
        return None
    track, level, label = mapping
    try:
        articles = int(row[COL_NUM_ARTICLES] or 0)
    except ValueError:
        articles = 0
    try:
        goldstein = float(row[COL_GOLDSTEIN] or 0.0)
    except ValueError:
        goldstein = 0.0
    fips = (row[COL_GEO_COUNTRY] or '').strip()
    country = FIPS_TO_COUNTRY.get(fips)
    if not country:
        full = (row[COL_GEO_FULLNAME] or '').strip()
        # FullName is "City, ADM1, Country" -- take the country tail if present.
        country = full.split(',')[-1].strip() if full else None
    if not country:
        return None
    return {
        'country':   country,
        'fips':      fips,
        'track':     track,
        'level':     level,
        'label':     label,
        'articles':  articles,
        'goldstein': goldstein,
        'source':    (row[COL_SOURCEURL] or '').strip(),
    }

def _fetch_event_file(url):
    """Download + unzip + parse one GDELT export file into event dicts."""
    events = []
    try:
        resp = requests.get(url, timeout=GDELT_HTTP_TIMEOUT)
        if resp.status_code != 200:
            return events
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding='utf-8', errors='replace')
                for row in csv.reader(text, delimiter='\t'):
                    ev = _parse_event_row(row)
                    if ev:
                        events.append(ev)
    except Exception as e:
        print(f"[kinetic_gatherer] event file error {url.rsplit('/',1)[-1]}: {str(e)[:100]}")
    return events

def _gather_cameo_events():
    """Pull the recent window of GDELT export files; return all relevant events."""
    all_events = []
    urls = _recent_export_urls(GDELT_WINDOW_FILES)
    if not urls:
        print("[kinetic_gatherer] No GDELT export URLs resolved")
        return all_events
    ok_files = 0
    for url in urls:
        evs = _fetch_event_file(url)
        if evs:
            ok_files += 1
            all_events.extend(evs)
        time.sleep(0.3)   # gentle pacing
    print(f"[kinetic_gatherer] CAMEO: {len(all_events)} events from {ok_files}/{len(urls)} files")
    return all_events

# ============================================================
# AGGREGATION  (pure -- unit-testable)
# ============================================================
def _level_weight(level):
    # L1..L5 -> escalating weight; kinetic (L5) dominates.
    return {1: 1, 2: 3, 3: 6, 4: 12, 5: 25}.get(level, 0)

def _band_for_score(score):
    if score >= BAND_SURGE:    return 'surge'
    if score >= BAND_HIGH:     return 'high'
    if score >= BAND_ELEVATED: return 'elevated'
    return 'normal'

def _aggregate_by_country(events):
    """Roll events up to per-country conflict + cooperation readings."""
    buckets = defaultdict(lambda: {
        'conflict_score': 0.0, 'cooperation_score': 0.0,
        'peak_conflict_level': 0, 'peak_cooperation_level': 0,
        'conflict_events': 0, 'cooperation_events': 0,
        'top_events': [], 'sources': [],
    })
    for ev in events:
        b = buckets[ev['country']]
        w = _level_weight(ev['level']) * (1 + min(ev['articles'], 50) / 50.0)
        if ev['track'] == 'conflict':
            b['conflict_score'] += w
            b['conflict_events'] += 1
            # Only well-corroborated events can set the peak level.
            if ev['articles'] >= MIN_ARTICLES_FOR_PEAK:
                b['peak_conflict_level'] = max(b['peak_conflict_level'], ev['level'])
        elif ev['track'] == 'cooperation':
            b['cooperation_score'] += w
            b['cooperation_events'] += 1
            if ev['articles'] >= MIN_ARTICLES_FOR_PEAK:
                b['peak_cooperation_level'] = max(b['peak_cooperation_level'], ev['level'])
        # keep the loudest few events for the BLUF + source links
        if ev['articles'] >= MIN_ARTICLES_FOR_PEAK:
            b['top_events'].append({
                'label': ev['label'], 'level': ev['level'], 'track': ev['track'],
                'articles': ev['articles'], 'source': ev['source'],
            })
            if ev['source']:
                b['sources'].append(ev['source'])

    out = {}
    for country, b in buckets.items():
        b['top_events'] = sorted(b['top_events'],
                                 key=lambda e: (e['level'], e['articles']),
                                 reverse=True)[:5]
        b['sources'] = list(dict.fromkeys(b['sources']))[:5]   # dedup, cap
        b['conflict_score'] = round(b['conflict_score'], 1)
        b['cooperation_score'] = round(b['cooperation_score'], 1)
        b['band'] = _band_for_score(b['conflict_score'])
        out[country] = b
    return out

# ============================================================
# GATHER + CACHE
# ============================================================
def run_gather():
    """Full gather: pull CAMEO window, aggregate, write Redis. Returns summary."""
    started = time.time()
    events = _gather_cameo_events()
    countries = _aggregate_by_country(events)
    # rank by conflict score so the GPI / build-radar gets a ready ordering
    ranked = sorted(countries.items(), key=lambda kv: kv[1]['conflict_score'], reverse=True)
    payload = {
        'countries':       countries,
        'ranked':          [c for c, _ in ranked],
        'total_events':    len(events),
        'countries_hot':   sum(1 for _, b in ranked if b['band'] != 'normal'),
        'window_files':    GDELT_WINDOW_FILES,
        'generated_at':    datetime.now(timezone.utc).isoformat(),
        'disclaimer':      CONVERGENCE_DISCLAIMER,
    }
    _redis_set(KINETIC_CACHE_KEY, payload)
    print(f"[kinetic_gatherer] gather complete in {round(time.time()-started,1)}s: "
          f"{len(events)} events, {len(countries)} countries, "
          f"{payload['countries_hot']} hot")
    return payload

def get_kinetic_data(force_refresh=False):
    if not force_refresh:
        cached = _redis_get(KINETIC_CACHE_KEY)
        if cached:
            cached['from_cache'] = True
            return cached
    return run_gather()

# ============================================================
# SCHEDULER  (lock-gated)
# ============================================================
def _scheduler_loop():
    time.sleep(90)   # boot delay -- let the app finish starting
    while True:
        try:
            # Cross-worker guard: only the lock-owning worker scans. TTL (13h)
            # outlasts the 12h sleep so ownership persists between cycles; a
            # non-owner re-checks hourly so it can take over if the owner dies.
            if not _acquire_scheduler_lock('kinetic', KINETIC_TTL_SECONDS):
                time.sleep(3600)
                continue
            print("[kinetic_gatherer] Periodic scan starting (lock owner)...")
            run_gather()
            print(f"[kinetic_gatherer] Sleeping {SCAN_INTERVAL_HOURS}h.")
            time.sleep(SCAN_INTERVAL_HOURS * 3600)
        except Exception as e:
            print(f"[kinetic_gatherer] Scheduler error: {str(e)[:160]}")
            time.sleep(3600)

def start_background_scheduler():
    t = threading.Thread(target=_scheduler_loop, daemon=True, name='KineticGatherer')
    t.start()
    print(f"[kinetic_gatherer] Background scheduler started (interval: {SCAN_INTERVAL_HOURS}h)")

# ============================================================
# FLASK ENDPOINTS
# ============================================================
def register_kinetic_endpoints(app, start_scheduler=True):
    from flask import request, jsonify

    @app.route('/api/kinetic-activity', methods=['GET', 'OPTIONS'])
    def api_kinetic_activity():
        if request.method == 'OPTIONS':
            return '', 200
        force = request.args.get('force', 'false').lower() == 'true'
        if force:
            # async so the request doesn't block on a multi-file GDELT pull
            threading.Thread(target=run_gather, daemon=True, name='kinetic-force').start()
        data = get_kinetic_data(force_refresh=False)
        return jsonify(data or {'countries': {}, 'note': 'first scan pending'})

    @app.route('/api/kinetic-activity/debug', methods=['GET'])
    def api_kinetic_debug():
        cached = _redis_get(KINETIC_CACHE_KEY)
        return jsonify({
            'cache_present':  cached is not None,
            'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'window_files':   GDELT_WINDOW_FILES,
            'cameo_roots':    len(CAMEO_ROOT),
            'fips_mapped':    len(FIPS_TO_COUNTRY),
            'cache':          cached,
        })

    if start_scheduler:
        start_background_scheduler()
    print("[kinetic_gatherer] Routes registered: /api/kinetic-activity, /api/kinetic-activity/debug")

print("[kinetic_gatherer] Module loaded -- Slice 1 (engine) v0.1.0")
