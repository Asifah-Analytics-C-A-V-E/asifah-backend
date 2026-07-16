"""
============================================================
ASIFAH ANALYTICS -- DIPLOMATIC CONVERGENCE GATHERER
Slice 1 (engine) v1.0.0 -- July 2026
============================================================
Backbone:    GDELT 2.0 Events (CAMEO-coded, georeferenced) -- the SAME pipe
             the kinetic gatherer drinks from, read for a different signal
             class: OFFICIAL TRAVEL AND MEETING EVENTS.

The question this answers: are two principals from countries with an ACTIVE
FILE between them (conflict, negotiation track, severed relations) converging
on the same third location in the same window -- outside the natural
multilateral calendar?

The July 21 2026 seed case: President Aoun (Lebanon) announced to Washington
July 21; PM Netanyahu (Israel) announced to Washington the same week. Neither
announcement referenced the other. The convergence IS the read. (Precedent:
the 2013 Muscat back-channel -- concurrent unannounced US/Iran official
presence in Oman preceded the announced JCPOA negotiations.)

CAMEO gives us the signal codes directly (root 03/04, full 3-digit EventCode):
    036  Express intent to meet or negotiate   (the announcement layer)
    042  Make a visit
    043  Host a visit
    044  Meet at a "third" location            (the Parent Trap code, literally)
    045  Mediate
    046  Engage in negotiation

Doctrine: convergence, not prediction. This module reports that travel
converges; it never claims a meeting will occur. Estimative prose only.
Absence-honest: no convergences -> quiet payload, never manufactured signal.

Suppression: known multilateral gatherings (UNGA, G7/G20, NATO, Davos, MSC,
COP) make co-location ROUTINE -- the exclusion calendar suppresses those
windows. This is the Black Swan calendar-multiplier pattern INVERTED:
scheduled gatherings suppress instead of amplify.

Venue weighting: mediation hubs (Muscat, Doha, Washington, Geneva, Cairo...)
carry weight -- the Diplomatic Hubs concept (Oman prototype, parking lot
since spring) is born here as a weight table.

Feeds:  GPI diplomatic axis via _narrative_diplomatic_convergence (recompute
        pattern -- the GPI reads this module's Redis key and owns its read).
============================================================
"""

import os
import io
import csv
import json
import time
import zipfile
import requests
import threading
from datetime import datetime, timezone, date

# ============================================================
# CONFIG
# ============================================================
GDELT_LASTUPDATE_URL = 'http://data.gdeltproject.org/gdeltv2/lastupdate.txt'
GDELT_EXPORT_FMT     = 'http://data.gdeltproject.org/gdeltv2/%s.export.CSV.zip'
GDELT_WINDOW_FILES   = 8              # most recent ~2h of global events per scan
GDELT_HTTP_TIMEOUT   = 20

DIPCONV_CACHE_KEY    = 'diplomatic:convergence:latest'
DIPCONV_TTL_SECONDS  = 26 * 3600      # outlast the 12h scan interval
SCAN_INTERVAL_HOURS  = 12

# Corroboration: an event needs at least this many articles behind it to count
# toward a convergence at full weight (thinly-coded events count at half).
MIN_ARTICLES_FULL    = 3

CONVERGENCE_DISCLAIMER = (
    'This is a CONVERGENCE indicator, NOT a prediction that a meeting will '
    'occur or that negotiations are underway. It reports that announced or '
    'reported official travel converges on the same location in the same '
    'window; the reader completes the inference.'
)

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_REST_URL') or os.environ.get('UPSTASH_REDIS_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN') or os.environ.get('UPSTASH_REDIS_TOKEN', '')

# ============================================================
# REDIS (Upstash REST -- same dual-env-var fallback as siblings)
# ============================================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        r = requests.get(f'{UPSTASH_REDIS_URL}/get/{key}',
                         headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                         timeout=8)
        raw = (r.json() or {}).get('result')
        return json.loads(raw) if raw else None
    except Exception:
        return None

def _redis_set(key, value, ttl_seconds=DIPCONV_TTL_SECONDS):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        body = json.dumps(["SET", key, json.dumps(value), "EX", ttl_seconds])
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                          data=body, timeout=8)
        return r.status_code == 200
    except Exception:
        return False

def _acquire_scheduler_lock(name, ttl_seconds):
    """Cross-worker guard (Redis SET NX EX) -- gunicorn --workers 2 would
    otherwise double every GDELT pull. Same pattern as the kinetic gatherer."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return True   # no Redis = single-process dev; let it run
    try:
        body = json.dumps(["SET", f"scheduler_lock:{name}", str(os.getpid()),
                           "NX", "EX", ttl_seconds])
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                          data=body, timeout=8)
        return (r.json() or {}).get('result') == 'OK'
    except Exception:
        return True

# ============================================================
# SIGNAL CODES  --  full 3-digit CAMEO EventCode (col 26)
# weight: contribution to a convergence when this event class is present.
# 036 is the ANNOUNCEMENT layer (intent) -- half weight, but it is the layer
# that fires BEFORE bodies move, which is exactly the early-warning value.
# ============================================================
DIPLOMATIC_EVENT_CODES = {
    '036': ('intent_to_meet',   0.5, 'Express intent to meet or negotiate'),
    '042': ('visit',            1.0, 'Make a visit'),
    '043': ('host_visit',       1.0, 'Host a visit'),
    '044': ('third_location',   1.5, 'Meet at a third location'),   # the Parent Trap code
    '045': ('mediation',        1.2, 'Mediate'),
    '046': ('negotiation',      1.3, 'Engage in negotiation'),
}

# Officialness gate: at least one actor must be government-coded. This is the
# kinetic gatherer's relevance-gate discipline applied to diplomacy -- keeps
# "two tourists visit Paris" out of the signal.
OFFICIAL_ACTOR_TYPES = frozenset({'GOV', 'MIL'})   # MIL: defense-minister class travel counts

# ============================================================
# WATCH PAIRS  --  country pairs with an ACTIVE FILE between them.
# CAMEO 3-char actor country codes. A convergence only fires when BOTH
# visitors at a destination form one of these pairs (or an event codes the
# pair directly). Curated, commented, and meant to be edited as files open
# and close. This gate is what keeps "everyone visits Washington constantly"
# from being a signal.
# ============================================================
WATCH_PAIRS = {
    frozenset({'ISR', 'LBN'}): 'Israel-Lebanon -- Trilateral Framework / direct-talks track',
    frozenset({'USA', 'IRN'}): 'US-Iran -- post-war de-escalation / nuclear file (Muscat 2013 precedent)',
    frozenset({'ISR', 'SYR'}): 'Israel-Syria -- post-Assad security file',
    frozenset({'ISR', 'SAU'}): 'Israel-Saudi -- normalization track',
    frozenset({'IND', 'PAK'}): 'India-Pakistan -- Kashmir / LoC file',
    frozenset({'ARM', 'AZE'}): 'Armenia-Azerbaijan -- Zangezur / peace-treaty track',
    frozenset({'RUS', 'UKR'}): 'Russia-Ukraine -- war termination file',
    frozenset({'USA', 'PRK'}): 'US-DPRK -- leverage-decay re-engagement watch',
    frozenset({'CHN', 'TWN'}): 'China-Taiwan -- cross-strait file',
    frozenset({'EGY', 'ETH'}): 'Egypt-Ethiopia -- GERD Nile file',
    frozenset({'TUR', 'GRC'}): 'Turkey-Greece -- Aegean file',
    frozenset({'USA', 'VEN'}): 'US-Venezuela -- sanctions / prisoner-channel file',
}

# ============================================================
# EXCLUSION CALENDAR  --  2026. Known multilateral gatherings where leader
# co-location is ROUTINE. Convergences at (destination, window) are tagged
# 'multilateral_window' and suppressed from scoring. The Black Swan calendar
# multiplier, inverted. MAINTENANCE: refresh annually; dates are windows, not
# exact summit days, deliberately padded.
# fips: GDELT ActionGeo FIPS code of the host country.
# ============================================================
EXCLUSION_CALENDAR_2026 = [
    {'name': 'Davos WEF',           'fips': 'SZ', 'start': '2026-01-17', 'end': '2026-01-26'},
    {'name': 'Munich Security Conf','fips': 'GM', 'start': '2026-02-11', 'end': '2026-02-18'},
    {'name': 'NATO Summit',         'fips': 'TU', 'start': '2026-07-06', 'end': '2026-07-10'},  # Ankara 2026
    {'name': 'UNGA High-Level Week','fips': 'US', 'start': '2026-09-19', 'end': '2026-10-01'},
    {'name': 'G20 Leaders Summit',  'fips': 'US', 'start': '2026-11-12', 'end': '2026-11-18'},  # Miami 2026
    {'name': 'COP31',               'fips': 'TU', 'start': '2026-11-06', 'end': '2026-11-20'},
]

# ============================================================
# VENUE WEIGHTS  --  the Diplomatic Hubs table (Oman prototype, finally born).
# Mediation-class venues make a convergence MORE meaningful: two adversary
# principals in Muscat on a random Thursday is the 2013 pattern. Keyed by
# ActionGeo FIPS. Unlisted venues weigh 1.0.
# ============================================================
VENUE_WEIGHTS = {
    'MU': ('Muscat/Oman',        1.6),   # THE back-channel venue (US-Iran 2013)
    'QA': ('Doha/Qatar',         1.5),   # hostage/ceasefire mediation standard
    'SZ': ('Geneva/Switzerland', 1.4),
    'US': ('Washington',         1.3),   # facilitated-direct-contact venue
    'EG': ('Cairo/Egypt',        1.3),
    'AE': ('Abu Dhabi/UAE',      1.3),
    'AU': ('Vienna/Austria',     1.3),   # nuclear-file venue (FIPS AU = Austria)
    'TU': ('Ankara/Istanbul',    1.2),
    'FR': ('Paris',              1.1),
    'IT': ('Rome',               1.1),
}

# Convergence score bands
BAND_SIGNIFICANT = 4.0
BAND_NOTABLE     = 2.5

# ============================================================
# GDELT 2.0 Events column indices (0-based, fixed 61-column schema).
# The kinetic gatherer reads the ROOT code (col 28); we need the FULL
# EventCode (col 26) because 042 vs 044 is the whole read, plus the actor
# COUNTRY codes (cols 7/17) because "who converges" is the signal.
# ============================================================
COL_DAY           = 1    # YYYYMMDD event date
COL_ACTOR1_NAME   = 6
COL_ACTOR1_CC     = 7    # Actor1CountryCode (CAMEO 3-char: USA/ISR/LBN/IRN...)
COL_ACTOR1_TYPE   = 12
COL_ACTOR2_NAME   = 16
COL_ACTOR2_CC     = 17
COL_ACTOR2_TYPE   = 22
COL_EVENT_CODE    = 26   # full 3-4 digit EventCode
COL_NUM_ARTICLES  = 33
COL_GEO_FULLNAME  = 52
COL_GEO_COUNTRY   = 53   # FIPS
COL_SOURCEURL     = 60
MIN_COLS          = 61

# ============================================================
# GDELT FETCH  (clone of the kinetic gatherer's proven fetch)
# ============================================================
def _recent_export_urls(n_files):
    try:
        resp = requests.get(GDELT_LASTUPDATE_URL, timeout=GDELT_HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        first_line = resp.text.strip().split('\n')[0]
        latest_url = first_line.split()[-1]
        ts = latest_url.split('/')[-1].split('.')[0]
        base = datetime.strptime(ts, '%Y%m%d%H%M%S')
        urls = []
        for i in range(n_files):
            t = base.timestamp() - i * 900   # 15-min steps back
            stamp = datetime.utcfromtimestamp(t).strftime('%Y%m%d%H%M%S')
            urls.append(GDELT_EXPORT_FMT % stamp)
        return urls
    except Exception as e:
        print(f'[dipconv_gatherer] lastupdate fetch failed: {str(e)[:100]}')
        return []

def _fetch_event_file(url):
    try:
        resp = requests.get(url, timeout=GDELT_HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        name = zf.namelist()[0]
        with zf.open(name) as f:
            text = io.TextIOWrapper(f, encoding='utf-8', errors='replace')
            return list(csv.reader(text, delimiter='\t'))
    except Exception:
        return []

# ============================================================
# PARSE  --  keep only official diplomatic-class events
# ============================================================
def _parse_event_row(row):
    """Map one GDELT TSV row to a diplomatic event dict, or None.
    Pure function -- unit-testable with synthetic rows."""
    if len(row) < MIN_COLS:
        return None
    code = (row[COL_EVENT_CODE] or '').strip()
    mapping = DIPLOMATIC_EVENT_CODES.get(code)
    if not mapping:
        return None
    kind, weight, label = mapping
    # Officialness gate: at least one GOV/MIL actor
    a1t = (row[COL_ACTOR1_TYPE] or '').strip().upper()
    a2t = (row[COL_ACTOR2_TYPE] or '').strip().upper()
    if a1t not in OFFICIAL_ACTOR_TYPES and a2t not in OFFICIAL_ACTOR_TYPES:
        return None
    a1c = (row[COL_ACTOR1_CC] or '').strip().upper()
    a2c = (row[COL_ACTOR2_CC] or '').strip().upper()
    if not a1c and not a2c:
        return None            # no attributable country on either actor
    try:
        articles = int(row[COL_NUM_ARTICLES] or 0)
    except ValueError:
        articles = 0
    day_raw = (row[COL_DAY] or '').strip()
    return {
        'code':        code,
        'kind':        kind,
        'weight':      weight,
        'label':       label,
        'actor1_cc':   a1c,
        'actor2_cc':   a2c,
        'actor1_name': (row[COL_ACTOR1_NAME] or '').strip()[:60],
        'actor2_name': (row[COL_ACTOR2_NAME] or '').strip()[:60],
        'dest_fips':   (row[COL_GEO_COUNTRY] or '').strip(),
        'dest_name':   (row[COL_GEO_FULLNAME] or '').strip()[:80],
        'articles':    articles,
        'day':         day_raw,
        'source':      (row[COL_SOURCEURL] or '').strip(),
    }

def _gather_events():
    urls = _recent_export_urls(GDELT_WINDOW_FILES)
    events, seen = [], set()
    for url in urls:
        for row in _fetch_event_file(url):
            ev = _parse_event_row(row)
            if not ev:
                continue
            # dedup on the identity that matters
            k = (ev['code'], ev['actor1_cc'], ev['actor2_cc'], ev['dest_fips'], ev['day'])
            if k in seen:
                continue
            seen.add(k)
            events.append(ev)
    return events

# ============================================================
# EXCLUSION CALENDAR CHECK
# ============================================================
def _in_multilateral_window(dest_fips, day_yyyymmdd):
    """True if (destination, date) falls inside a known multilateral gathering."""
    if not day_yyyymmdd or len(day_yyyymmdd) < 8:
        return None
    try:
        d = date(int(day_yyyymmdd[:4]), int(day_yyyymmdd[4:6]), int(day_yyyymmdd[6:8]))
    except ValueError:
        return None
    for w in EXCLUSION_CALENDAR_2026:
        if w['fips'] != dest_fips:
            continue
        s = date.fromisoformat(w['start'])
        e = date.fromisoformat(w['end'])
        if s <= d <= e:
            return w['name']
    return None

# ============================================================
# CONVERGENCE DETECTION  --  the core
# ============================================================
def detect_convergences(events):
    """Two detection modes, both watch-pair gated:

    MODE A (direct): a single event where actor1+actor2 ARE a watch pair and
    the code is third-location / negotiation / mediation class. GDELT coded
    the meeting itself.

    MODE B (convergent travel): visit-class events by DIFFERENT watch-pair
    members landing on the SAME third destination in the scan window. Neither
    event references the other -- the convergence is OURS to see. This is the
    Aoun/Bibi-to-Washington read.
    """
    convergences = []

    # ---- MODE A: directly-coded pair meetings ----
    for ev in events:
        pair = frozenset({ev['actor1_cc'], ev['actor2_cc']})
        if len(pair) != 2 or pair not in WATCH_PAIRS:
            continue
        if ev['kind'] not in ('third_location', 'negotiation', 'mediation', 'intent_to_meet'):
            continue
        art_mult = 1.0 if ev['articles'] >= MIN_ARTICLES_FULL else 0.5
        venue_name, venue_w = VENUE_WEIGHTS.get(ev['dest_fips'], (ev['dest_name'] or 'unlisted venue', 1.0))
        window = _in_multilateral_window(ev['dest_fips'], ev['day'])
        score = 0.0 if window else round(3.0 * ev['weight'] * venue_w * art_mult, 2)
        convergences.append({
            'mode':        'direct',
            'pair':        sorted(pair),
            'file':        WATCH_PAIRS[pair],
            'kind':        ev['kind'],
            'destination': venue_name,
            'dest_fips':   ev['dest_fips'],
            'score':       score,
            'suppressed':  window,
            'articles':    ev['articles'],
            'sources':     [ev['source']] if ev['source'] else [],
            'day':         ev['day'],
        })

    # ---- MODE B: convergent travel to a third location ----
    # bucket visit-class events by destination; visitor = whichever actor is
    # NOT the destination-country actor (for 042/043 GDELT codes visitor and
    # host on either side; we take both attributable countries as candidates).
    by_dest = {}
    for ev in events:
        if ev['kind'] not in ('visit', 'host_visit', 'intent_to_meet'):
            continue
        if not ev['dest_fips']:
            continue
        by_dest.setdefault(ev['dest_fips'], []).append(ev)

    for dest_fips, evs in by_dest.items():
        # visitors: attributable actor countries seen traveling to this dest
        visitors = {}   # cc -> best event
        for ev in evs:
            for cc in (ev['actor1_cc'], ev['actor2_cc']):
                if not cc:
                    continue
                prev = visitors.get(cc)
                if prev is None or ev['articles'] > prev['articles']:
                    visitors[cc] = ev
        ccs = list(visitors.keys())
        for i in range(len(ccs)):
            for j in range(i + 1, len(ccs)):
                pair = frozenset({ccs[i], ccs[j]})
                if pair not in WATCH_PAIRS:
                    continue
                # destination must be a THIRD country to the pair.
                # NOTE: FIPS (dest) vs CAMEO (actors) are different codebooks;
                # the cheap guard below catches the common identity cases
                # (US/USA, IS/ISR...) -- refine with a full map if needed.
                if dest_fips in (ccs[i][:2], ccs[j][:2]):
                    continue
                e1, e2 = visitors[ccs[i]], visitors[ccs[j]]
                art_mult = 1.0 if min(e1['articles'], e2['articles']) >= MIN_ARTICLES_FULL else 0.5
                w = (e1['weight'] + e2['weight']) / 2.0
                venue_name, venue_w = VENUE_WEIGHTS.get(dest_fips, ((e1['dest_name'] or 'unlisted venue'), 1.0))
                window = _in_multilateral_window(dest_fips, e1['day'] or e2['day'])
                score = 0.0 if window else round(3.0 * w * venue_w * art_mult, 2)
                convergences.append({
                    'mode':        'convergent_travel',
                    'pair':        sorted(pair),
                    'file':        WATCH_PAIRS[pair],
                    'kind':        f"{e1['kind']}+{e2['kind']}",
                    'destination': venue_name,
                    'dest_fips':   dest_fips,
                    'score':       score,
                    'suppressed':  window,
                    'articles':    e1['articles'] + e2['articles'],
                    'sources':     [s for s in (e1['source'], e2['source']) if s][:2],
                    'day':         e1['day'] or e2['day'],
                })

    # dedup: a direct-coded meet outranks its own convergent-travel shadow
    best = {}
    for c in convergences:
        k = (tuple(c['pair']), c['dest_fips'])
        if k not in best or c['score'] > best[k]['score']:
            best[k] = c
    out = sorted(best.values(), key=lambda c: c['score'], reverse=True)
    for c in out:
        c['band'] = ('significant' if c['score'] >= BAND_SIGNIFICANT else
                     'notable'     if c['score'] >= BAND_NOTABLE     else
                     'monitoring'  if c['score'] > 0                 else
                     'suppressed')
        # the estimative one-liner -- reader completes the inference
        if c['suppressed']:
            c['read'] = (f"{' and '.join(c['pair'])} co-location at {c['destination']} falls inside "
                         f"the {c['suppressed']} window -- routine multilateral gathering, not scored.")
        else:
            c['read'] = (f"Reported {c['pair'][0]} and {c['pair'][1]} official travel converging on "
                         f"{c['destination']} in the same window, outside any multilateral gathering, "
                         f"is consistent with facilitated contact on the {c['file'].split(' -- ')[1] if ' -- ' in c['file'] else 'active file'} "
                         f"-- the pattern that has historically preceded announced negotiations "
                         f"(Muscat 2013; Washington trilateral track 2025-26).")
    return out

# ============================================================
# GATHER + CACHE
# ============================================================
def run_gather():
    started = time.time()
    events = _gather_events()
    convergences = detect_convergences(events)
    active = [c for c in convergences if not c['suppressed'] and c['score'] > 0]
    payload = {
        'convergences':      convergences[:20],
        'active_count':      len(active),
        'top_band':          active[0]['band'] if active else 'quiet',
        'total_events':      len(events),
        'watch_pairs':       len(WATCH_PAIRS),
        'window_files':      GDELT_WINDOW_FILES,
        'generated_at':      datetime.now(timezone.utc).isoformat(),
        'disclaimer':        CONVERGENCE_DISCLAIMER,
    }
    _redis_set(DIPCONV_CACHE_KEY, payload)
    print(f"[dipconv_gatherer] gather complete in {round(time.time()-started,1)}s: "
          f"{len(events)} diplomatic events, {len(active)} active convergences, "
          f"top band {payload['top_band']}")
    return payload

def get_dipconv_data(force_refresh=False):
    if not force_refresh:
        cached = _redis_get(DIPCONV_CACHE_KEY)
        if cached:
            cached['from_cache'] = True
            return cached
    return run_gather()

# ============================================================
# SCHEDULER  (lock-gated, 12h)
# ============================================================
def _scheduler_loop():
    time.sleep(120)   # boot delay
    while True:
        try:
            if not _acquire_scheduler_lock('dipconv', DIPCONV_TTL_SECONDS):
                time.sleep(3600)
                continue
            print('[dipconv_gatherer] Periodic scan starting (lock owner)...')
            run_gather()
            print(f'[dipconv_gatherer] Sleeping {SCAN_INTERVAL_HOURS}h.')
            time.sleep(SCAN_INTERVAL_HOURS * 3600)
        except Exception as e:
            print(f'[dipconv_gatherer] Scheduler error: {str(e)[:160]}')
            time.sleep(3600)

def start_background_scheduler():
    t = threading.Thread(target=_scheduler_loop, daemon=True, name='DipConvGatherer')
    t.start()
    print(f'[dipconv_gatherer] Background scheduler started (interval: {SCAN_INTERVAL_HOURS}h)')

# ============================================================
# FLASK ENDPOINTS
# ============================================================
def register_diplomatic_convergence_endpoints(app, start_scheduler=True):
    from flask import request, jsonify

    @app.route('/api/diplomatic-convergence', methods=['GET', 'OPTIONS'])
    def api_diplomatic_convergence():
        if request.method == 'OPTIONS':
            return '', 200
        force = request.args.get('force', 'false').lower() == 'true'
        if force:
            threading.Thread(target=run_gather, daemon=True, name='dipconv-force').start()
        data = get_dipconv_data(force_refresh=False)
        return jsonify(data or {'convergences': [], 'note': 'first scan pending'})

    @app.route('/api/diplomatic-convergence/debug', methods=['GET'])
    def api_diplomatic_convergence_debug():
        cached = _redis_get(DIPCONV_CACHE_KEY)
        return jsonify({
            'cache_present':    cached is not None,
            'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'watch_pairs':      {' - '.join(sorted(p)): d for p, d in WATCH_PAIRS.items()},
            'exclusion_windows': EXCLUSION_CALENDAR_2026,
            'venue_weights':    {k: v for k, v in VENUE_WEIGHTS.items()},
            'event_codes':      {k: v[2] for k, v in DIPLOMATIC_EVENT_CODES.items()},
            'cache':            cached,
        })

    if start_scheduler:
        start_background_scheduler()
    print('[dipconv_gatherer] Routes registered: /api/diplomatic-convergence, '
          '/api/diplomatic-convergence/debug')

print('[dipconv_gatherer] Module loaded -- Slice 1 (engine) v1.0.0')
