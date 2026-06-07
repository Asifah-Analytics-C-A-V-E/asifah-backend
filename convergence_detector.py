"""
=======================================================================
  ASIFAH ANALYTICS -- CONVERGENCE DETECTOR (multi-axis, live)
  v0.4.0 (Jun 6 2026) -- STEP 4: HISTORY + SO-WHAT PROSE
=======================================================================

WHAT THIS IS
  A transversal layer that reads the four live signal axes already on
  the ME backend and asks, per country: how many INDEPENDENT axes are
  lit at the same time? Agreement across axes beats one loud headline.

    Axis 1 -- KINETIC    : kinetic_activity_gatherer  (Redis: kinetic:global:latest)
                           per country: band normal/elevated/high/surge
    Axis 2 -- COMMODITY  : commodity_tracker          (Redis: commodity_tracker_cache)
                           country_summaries[id].alert_level (same band scale)
    Axis 3 -- RHETORIC   : regional BLUFs             (Redis: rhetoric:<region>:regional_bluf)
                           theatre_summary[id].level  (L0-L5 escalation)
    Axis 4 -- HUMANITARIAN: humanitarian_convergence  (Redis: humanitarian_convergence:bluf:latest)
                           per-country MAX of signals[].level (3-5). Covers
                           countries WITHOUT rhetoric trackers -- the axis
                           that lets Africa (e.g. an Ebola outbreak) read as
                           convergence even with no rhetoric page.

NORMALIZATION (common 0-3 intensity ladder)
    kinetic / commodity band : normal=0 elevated=1 high=2 surge=3
    rhetoric level L0-L5     : L0/L1=0  L2=1  L3=2  L4/L5=3
    humanitarian level 3-5   : L3=1     L4=2  L5=3   (any signal => active)
  An axis is "active" for a country at intensity >= 1.

TIERING (the analytic claim -- count of co-active axes)
    4 active -> QUAD       3 active -> TRIPLE
    2 active -> DUAL       1 active -> SINGLE       0 -> quiet (omitted)
  Ranked by tier, then by summed intensity within tier.

HISTORY (v0.4.0)
  Each scan, on a guarded 6h cadence, snapshots every active country's
  four-axis profile to a rolling Redis list (cax:hist:<country>, last 120,
  90d TTL). On every scan we read the series back (one pipeline call) and
  attach a `history` block per country: persistence (consecutive readings
  at this tier), novelty (first time at/above this tier in the window),
  direction (rising/steady/easing by summed intensity), peak, first_seen.

PROSE (v0.4.0)
  Each record gets a plain-language `so_what`: what is co-active, what is
  driving it, how it compares to the country's own recent history, and the
  convergence-not-prediction framing. Axis jargon is translated to what
  each stream actually MEASURES.

NAMESPACE
  Routes under /api/cax/* -- the /api/convergence/* namespace belongs to
  convergence_registry.py (a different module). Do not mix.

USAGE FROM ME BACKEND app.py
    from convergence_detector import register_convergence_detector_endpoints
    register_convergence_detector_endpoints(app)

CONVERGENCE-NOT-PREDICTION
  Reports which signal streams are co-active. Does not forecast actions.
"""

import os
import json
import time
import requests
from datetime import datetime, timezone

# ----------------------------------------------------------------------
# Redis (Upstash REST). Reads + a guarded, low-frequency snapshot write.
# ----------------------------------------------------------------------
_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')   or os.environ.get('UPSTASH_REDIS_REST_URL')
_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

KINETIC_CACHE_KEY   = 'kinetic:global:latest'
COMMODITY_CACHE_KEY = 'commodity_tracker_cache'
RHETORIC_BLUF_KEYS  = {
    'me':     'rhetoric:me:regional_bluf',
    'wha':    'rhetoric:wha:regional_bluf',
    'europe': 'rhetoric:europe:regional_bluf',
    'asia':   'rhetoric:asia:regional_bluf',
    # 'africa': 'rhetoric:africa:regional_bluf',   # FUTURE -- BLUF not built yet
}
HUMANITARIAN_CACHE_KEY = 'humanitarian_convergence:bluf:latest'

# History config
HIST_KEY_PREFIX       = 'cax:hist:'
HIST_GUARD_KEY        = 'cax:hist:last_snapshot_ts'
HIST_MAXLEN           = 120                 # ~30 days at a 6h cadence
HIST_TTL_SEC          = 90 * 24 * 3600      # dead countries self-expire
SNAPSHOT_INTERVAL_SEC = 6 * 3600            # write at most once per 6h bucket

DISCLAIMER = ("This is a CONVERGENCE indicator, NOT a probability of action. "
              "Co-active signal streams indicate that independent reporting axes "
              "agree; they do not predict whether or when action will occur.")


def _redis_get(key):
    """Read-only GET from Upstash REST. Returns parsed JSON or None. Never scans."""
    if not (_REDIS_URL and _REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {_REDIS_TOKEN}"},
            timeout=6,
        )
        data = resp.json()
        if data.get("result") is not None:
            return json.loads(data["result"])
    except Exception as e:
        print(f"[ConvergenceDetector] Redis GET {key} error: {e}")
    return None


def _redis_pipeline(commands):
    """Run a batch of Redis commands in ONE Upstash REST /pipeline call.
    `commands` is a list of arg-arrays, e.g. [["LRANGE","k","0","119"], ...].
    Returns a list of raw results (same order), or [] on any failure.
    Degrades gracefully -- callers must tolerate [] (history simply won't
    accrue / read), so a Redis hiccup never breaks /scan.
    """
    if not (_REDIS_URL and _REDIS_TOKEN) or not commands:
        return []
    try:
        resp = requests.post(
            f"{_REDIS_URL}/pipeline",
            headers={"Authorization": f"Bearer {_REDIS_TOKEN}",
                     "Content-Type": "application/json"},
            data=json.dumps(commands),
            timeout=8,
        )
        out = resp.json()
        if isinstance(out, list):
            return [item.get('result') if isinstance(item, dict) else item for item in out]
    except Exception as e:
        print(f"[ConvergenceDetector] Redis pipeline error: {e}")
    return []


# ----------------------------------------------------------------------
# Normalization tables
# ----------------------------------------------------------------------
BAND_INTENSITY = {'normal': 0, 'elevated': 1, 'high': 2, 'surge': 3}
RHETORIC_LEVEL_INTENSITY = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3, 5: 3}
HUMANITARIAN_LEVEL_INTENSITY = {3: 1, 4: 2, 5: 3}   # any humanitarian signal => active
TIER_BY_COUNT = {0: 'quiet', 1: 'single', 2: 'dual', 3: 'triple', 4: 'quad'}
TIER_RANK = {'quad': 4, 'triple': 3, 'dual': 2, 'single': 1, 'quiet': 0}
TIER_WORD = {'quad': 'quadruple', 'triple': 'triple', 'dual': 'dual', 'single': 'single-axis'}

# A commodity headline shared across this many countries is a GLOBAL commodity
# condition (one macro story stamped onto every exposed country), not per-country
# corroboration. v0.5.0 detects + EXPOSES these; tier-demotion is a later flip.
GLOBAL_COMMODITY_MIN = 6
_NAME_TOKENS = {
    'usa': ['united states', 'u.s.', 'us-', '-us', 'us '],
    'uae': ['uae', 'emirates'], 'drc': ['dr congo', 'congo', 'drc'],
    'united_kingdom': ['united kingdom', 'britain', 'uk'],
    'south_korea': ['south korea', 'korea'], 'saudi_arabia': ['saudi'],
}

# Plain-language description of what each axis MEASURES (no jargon).
AXIS_PHRASE = {
    'kinetic':      'armed-conflict event reporting',
    'commodity':    'commodity-supply pressure in news flow',
    'rhetoric':     'escalatory official rhetoric',
    'humanitarian': 'humanitarian distress reporting (displacement, disease, food)',
}

# Humanitarian detector emits sub-national ids; roll the high-value ones up to
# the parent country so a sub-region signal reinforces the parent's other axes.
SUBREGION_TO_COUNTRY = {
    'borno_state': 'nigeria',
    'north_kivu': 'drc', 'south_kivu': 'drc', 'ituri': 'drc',
    'tigray': 'ethiopia', 'amhara': 'ethiopia', 'afar_region': 'ethiopia',
    'darfur': 'sudan', 'khartoum': 'sudan', 'el_fasher': 'sudan',
    'aleppo': 'syria', 'idlib': 'syria',
    'saada': 'yemen', 'hodeidah': 'yemen', 'sanaa': 'yemen', 'aden': 'yemen',
    'kabul': 'afghanistan', 'kandahar': 'afghanistan',
    'mogadishu': 'somalia', 'bangui': 'car',
    'kampala': 'uganda', 'kigali': 'rwanda',
    'cap_haitien': 'haiti', 'port_au_prince': 'haiti',
    'cabo_delgado': 'mozambique', 'coxs_bazar': 'bangladesh',
    'bekaa_valley': 'lebanon',
    'gaza_north': 'gaza', 'khan_younis': 'gaza', 'rafah': 'gaza',
}

# ----------------------------------------------------------------------
# Country-id canonicalization. Commodity + rhetoric + humanitarian use
# lowercase ids; kinetic uses GDELT display names. Canonicalize to id.
# ----------------------------------------------------------------------
ID_TO_DISPLAY = {
    'usa':          'United States',
    'uae':          'United Arab Emirates',
    'drc':          'DR Congo',
    'south_korea':  'South Korea',
    'south_africa': 'South Africa',
    'saudi_arabia': 'Saudi Arabia',
    'eu':           'EU',
    'car':          'Central African Republic',
    'drc':          'DR Congo',
}
_NAME_TO_ID = {
    'United States':         'usa',
    'United Arab Emirates':  'uae',
    'DR Congo':              'drc',
    'Gaza Strip':            'gaza',
}


def _kinetic_name_to_id(name):
    """GDELT display name -> canonical lowercase id."""
    if name in _NAME_TO_ID:
        return _NAME_TO_ID[name]
    return name.lower().replace(' ', '_').replace('-', '_')


def _id_to_display(cid):
    """Canonical id -> human display name."""
    return ID_TO_DISPLAY.get(cid) or cid.replace('_', ' ').title()


# ----------------------------------------------------------------------
# Per-axis readers. Each returns {country_id: {intensity, label, score, driver}}
# plus an availability flag so a cold cache is visible, never silent.
# A country present with intensity 0 means "covered but quiet"; ABSENT means
# "no coverage for that axis" -- the prose layer uses this distinction.
# ----------------------------------------------------------------------
def _read_kinetic():
    kin = _redis_get(KINETIC_CACHE_KEY)
    if not kin:
        return {}, False
    out = {}
    for name, c in (kin.get('countries', {}) or {}).items():
        band = c.get('band', 'normal')
        events = c.get('top_events', []) or []
        drv = next((e for e in events if e.get('track') == 'conflict'), events[0] if events else None)
        driver = None
        if drv:
            driver = {'label': drv.get('label'), 'articles': drv.get('articles'),
                      'source': drv.get('source')}
        out[_kinetic_name_to_id(name)] = {
            'intensity': BAND_INTENSITY.get(band, 0), 'label': band,
            'score': c.get('conflict_score'), 'driver': driver,
        }
    return out, True


def _read_commodity():
    com = _redis_get(COMMODITY_CACHE_KEY)
    if not com:
        return {}, False
    out = {}
    for cid, c in (com.get('country_summaries', {}) or {}).items():
        level = c.get('alert_level', 'normal')
        sigs = c.get('top_signals', []) or []
        out[cid] = {
            'intensity': BAND_INTENSITY.get(level, 0), 'label': level,
            'score': c.get('total_score'), 'driver': sigs[0] if sigs else None,
        }
    return out, True


def _read_rhetoric():
    """Merge per-country theatre_summary across all regional BLUF caches."""
    out, availability = {}, {}
    for region, key in RHETORIC_BLUF_KEYS.items():
        bluf = _redis_get(key)
        availability[region] = bool(bluf)
        if not bluf:
            continue
        for cid, t in (bluf.get('theatre_summary', {}) or {}).items():
            level = t.get('level', 0) or 0
            out[cid] = {
                'intensity': RHETORIC_LEVEL_INTENSITY.get(level, 0),
                'label': t.get('label', ''), 'level': level,
                'score': t.get('score'), 'region': region,
                'driver': {'label': t.get('label'), 'level': level},
            }
    return out, availability


def _read_humanitarian():
    """Collapse the flat humanitarian signals list to one reading per country
    (MAX-severity signal), rolling sub-national ids up to the parent country."""
    hum = _redis_get(HUMANITARIAN_CACHE_KEY)
    if not hum:
        return {}, False
    out = {}
    for s in (hum.get('signals', []) or []):
        raw = s.get('country')
        if not raw:
            continue
        cid = SUBREGION_TO_COUNTRY.get(raw, raw)
        level = s.get('level', 0) or 0
        intensity = HUMANITARIAN_LEVEL_INTENSITY.get(level, 0)
        prev = out.get(cid)
        if prev is None or intensity > prev['intensity']:
            out[cid] = {
                'intensity': intensity, 'label': s.get('category', ''),
                'level': level, 'score': s.get('priority'),
                'driver': {'label': s.get('short_text'),
                           'category': s.get('category'), 'source': s.get('source')},
            }
    return out, True


# ----------------------------------------------------------------------
# History: read the rolling series for a set of countries (one pipeline call)
# ----------------------------------------------------------------------
def _read_history(country_ids):
    """Return {country_id: [snapshot, ...newest-first]} via a single pipeline."""
    ids = list(country_ids)
    if not ids:
        return {}
    cmds = [["LRANGE", f"{HIST_KEY_PREFIX}{cid}", "0", str(HIST_MAXLEN - 1)] for cid in ids]
    results = _redis_pipeline(cmds)
    series_by_id = {}
    for cid, raw_list in zip(ids, results or []):
        parsed = []
        for entry in (raw_list or []):
            try:
                parsed.append(json.loads(entry) if isinstance(entry, str) else entry)
            except Exception:
                continue
        series_by_id[cid] = parsed
    return series_by_id


def _history_metrics(current_tier, current_summed, series, now_iso):
    """Compute persistence / novelty / direction from a country's series.
    `series` is newest-first and does NOT include the current reading."""
    cur_rank = TIER_RANK.get(current_tier, 0)
    if not series:
        return {
            'readings': 0, 'persistence': 1, 'streak_hours': None,
            'first_in_window': True, 'days_since_prior_at_tier': None,
            'direction': 'new', 'prev_summed': None, 'delta_summed': None,
            'peak_summed': current_summed, 'first_seen': now_iso,
        }

    # persistence: consecutive newest snapshots at the SAME tier as now
    streak = 0
    for e in series:
        if e.get('tier') == current_tier:
            streak += 1
        else:
            break
    persistence = 1 + streak
    streak_hours = None
    if streak > 0:
        try:
            oldest_ts = series[streak - 1].get('ts')
            dt = datetime.fromisoformat(oldest_ts)
            now = datetime.fromisoformat(now_iso)
            streak_hours = round((now - dt).total_seconds() / 3600.0, 1)
        except Exception:
            streak_hours = None

    # novelty: most recent prior snapshot at rank >= current rank
    days_since = None
    for e in series:
        if TIER_RANK.get(e.get('tier'), 0) >= cur_rank:
            try:
                dt = datetime.fromisoformat(e.get('ts'))
                now = datetime.fromisoformat(now_iso)
                days_since = round((now - dt).total_seconds() / 86400.0, 1)
            except Exception:
                days_since = None
            break
    first_in_window = days_since is None

    # direction: current summed vs previous snapshot's summed
    prev_summed = series[0].get('summed_intensity')
    delta = None
    direction = 'steady'
    if isinstance(prev_summed, (int, float)):
        delta = current_summed - prev_summed
        direction = 'rising' if delta >= 1 else ('easing' if delta <= -1 else 'steady')

    peak = max([current_summed] + [e.get('summed_intensity', 0) for e in series])
    first_seen = series[-1].get('ts', now_iso)

    return {
        'readings': len(series), 'persistence': persistence, 'streak_hours': streak_hours,
        'first_in_window': first_in_window, 'days_since_prior_at_tier': days_since,
        'direction': direction, 'prev_summed': prev_summed, 'delta_summed': delta,
        'peak_summed': peak, 'first_seen': first_seen,
    }


def _maybe_snapshot(records, now_epoch, now_iso):
    """Guarded write: at most once per SNAPSHOT_INTERVAL_SEC, append every
    active country's profile to its rolling list (one pipeline call)."""
    last = _redis_get(HIST_GUARD_KEY) or 0
    try:
        last = float(last)
    except Exception:
        last = 0
    if now_epoch - last < SNAPSHOT_INTERVAL_SEC:
        return False
    cmds = []
    for r in records:
        snap = {
            'ts': now_iso, 'tier': r['tier'], 'active_count': r['active_count'],
            'summed_intensity': r['summed_intensity'],
            'axes': {a: (r['axes'][a]['intensity'] if r['axes'].get(a) else 0)
                     for a in ('kinetic', 'commodity', 'rhetoric', 'humanitarian')},
        }
        key = f"{HIST_KEY_PREFIX}{r['country']}"
        cmds.append(["LPUSH", key, json.dumps(snap)])
        cmds.append(["LTRIM", key, "0", str(HIST_MAXLEN - 1)])
        cmds.append(["EXPIRE", key, str(HIST_TTL_SEC)])
    cmds.append(["SET", HIST_GUARD_KEY, str(int(now_epoch))])
    _redis_pipeline(cmds)
    return True


# ----------------------------------------------------------------------
# Prose: plain-language "so what" per country
# ----------------------------------------------------------------------
def _driver_text(reading):
    """Best human string out of an axis driver dict (never dumps a raw dict)."""
    d = (reading or {}).get('driver')
    if not d:
        return None
    if isinstance(d, dict):
        # commodity driver shape: {commodity_name, article_title, ...}
        if d.get('article_title') or d.get('commodity_name'):
            name = d.get('commodity_name')
            head = d.get('article_title')
            if name and head:
                return f"{name}: {head}"
            return name or head
        for k in ('label', 'short_text', 'title', 'headline', 'text'):
            if d.get(k):
                return str(d[k])
        return None   # known dict, no usable field -- never dump the repr
    return str(d)[:140]


def _so_what(record, hist):
    cid_axes = record['axes']
    active = record['active_axes']
    tier = record['tier']
    disp = record['display']

    # 1) lead
    n = record['active_count']
    lead = f"{disp}: {TIER_WORD.get(tier, tier)} convergence -- {n} independent signal stream{'s' if n != 1 else ''} active at once."

    # 2) what is co-active (plain language)
    phrases = [AXIS_PHRASE[a] for a in ('kinetic', 'commodity', 'rhetoric', 'humanitarian') if a in active]
    if len(phrases) == 1:
        whatline = f" Active stream: {phrases[0]}."
    else:
        whatline = f" Co-active: {', '.join(phrases[:-1])} and {phrases[-1]}."

    # honest coverage note: rhetoric absent because no tracker exists yet
    if 'rhetoric' not in active and cid_axes.get('rhetoric') is None:
        whatline += " (No rhetoric tracker for this country yet, so that axis can't weigh in.)"

    # 3) drivers from the active axes
    drv_bits = []
    for a in active:
        t = _driver_text(cid_axes.get(a))
        if t:
            short = 'conflict' if a == 'kinetic' else ('commodity' if a == 'commodity'
                    else ('rhetoric' if a == 'rhetoric' else 'humanitarian'))
            drv_bits.append(f"'{t}' ({short})")
    driverline = f" Leading drivers: {'; '.join(drv_bits[:2])}." if drv_bits else ""

    # honesty: a shared_global commodity is elevated here but reflects a broad market-wide
    # move -- it is excluded from the tier above and surfaced separately as a global condition.
    com = cid_axes.get('commodity')
    sharedline = ""
    if com and com.get('shared_global'):
        nm = (com.get('driver') or {}).get('commodity_name', 'commodity')
        sharedline = (f" ({nm} pressure is also elevated here, but it reflects a broad market-wide "
                      f"move and is surfaced separately as a global condition rather than counted "
                      f"as {disp}-specific convergence.)")

    # 4) history comparison
    if hist['readings'] == 0:
        histline = " No prior convergence history recorded yet."
    elif hist['first_in_window']:
        histline = f" First time {disp} has reached {TIER_WORD.get(tier, tier)} convergence in the recorded window."
    else:
        parts = []
        if hist['persistence'] > 1:
            hrs = f" (~{hist['streak_hours']}h)" if hist['streak_hours'] else ""
            parts.append(f"held at this level across the last {hist['persistence']} readings{hrs}")
        if hist['direction'] in ('rising', 'easing'):
            parts.append(f"the combined signal is {hist['direction']}")
        elif hist['direction'] == 'steady' and hist['persistence'] > 1:
            parts.append("the combined signal is steady")
        if hist.get('days_since_prior_at_tier') is not None and hist['persistence'] == 1:
            parts.append(f"last at this level {hist['days_since_prior_at_tier']}d ago")
        histline = (" " + disp + " has " + "; ".join(parts) + ".") if parts else ""

    tail = " This is a convergence reading -- independent streams agreeing -- not a forecast of action."
    return (lead + whatline + driverline + sharedline + histline + tail).strip()


# ----------------------------------------------------------------------
# Global commodity conditions: one headline stamped across many countries
# ----------------------------------------------------------------------
def _country_named_in(title, cid, display):
    """Is this country actually named in the commodity headline?"""
    t = (title or '').lower()
    if display and display.lower() in t:
        return True
    if cid.replace('_', ' ') in t:
        return True
    return any(tok in t for tok in _NAME_TOKENS.get(cid, []))


def _tag_commodity_clusters(commodity):
    """Group commodity readings by their driving article. Any article shared
    across >= GLOBAL_COMMODITY_MIN countries is a GLOBAL condition. Annotate each
    member's commodity reading with `shared_global` (False if the country is named
    in the headline -- then it IS country-specific, e.g. Iran in a US-Iran oil story).
    Returns a list of global_conditions for the GPI cross-theater layer.
    ADDITIVE: this does NOT change tier counting yet."""
    clusters = {}
    for cid, c in commodity.items():
        d = c.get('driver') or {}
        key = d.get('article_url') or d.get('article_title')
        if not key:
            continue
        clusters.setdefault(key, []).append(cid)

    global_conditions = []
    for key, cids in clusters.items():
        if len(cids) < GLOBAL_COMMODITY_MIN:
            continue
        sample = commodity[cids[0]].get('driver') or {}
        title = sample.get('article_title', '')
        specific, shared = [], []
        for cid in cids:
            disp = _id_to_display(cid)
            if _country_named_in(title, cid, disp):
                commodity[cid]['shared_global'] = False
                specific.append(disp)
            else:
                commodity[cid]['shared_global'] = True
                shared.append(disp)
        global_conditions.append({
            'axis':           'commodity',
            'commodity':      sample.get('commodity'),
            'commodity_name': sample.get('commodity_name'),
            'headline':       title,
            'url':            sample.get('article_url'),
            'country_count':  len(cids),
            'countries':      sorted(shared),
            'named_specific': sorted(specific),
        })
    global_conditions.sort(key=lambda g: g['country_count'], reverse=True)
    return global_conditions


# ----------------------------------------------------------------------
# The join
# ----------------------------------------------------------------------
def build_convergence():
    now_epoch = int(time.time())
    now_iso = datetime.now(timezone.utc).isoformat()

    kinetic,   kin_ok  = _read_kinetic()
    commodity, com_ok  = _read_commodity()
    rhetoric,  rhe_avail = _read_rhetoric()
    humanitarian, hum_ok = _read_humanitarian()

    global_conditions = _tag_commodity_clusters(commodity)

    all_ids = set(kinetic) | set(commodity) | set(rhetoric) | set(humanitarian)
    records = []
    for cid in all_ids:
        axes = {
            'kinetic':      kinetic.get(cid),
            'commodity':    commodity.get(cid),
            'rhetoric':     rhetoric.get(cid),
            'humanitarian': humanitarian.get(cid),
        }
        # v0.6.0: a shared_global commodity axis (one headline across many exposed
        # countries) is relocated to the global-conditions layer -- it no longer
        # inflates this country's per-country convergence tier.
        active = [name for name, a in axes.items()
                  if a and a.get('intensity', 0) >= 1
                  and not (name == 'commodity' and a.get('shared_global'))]
        count = len(active)
        if count == 0:
            continue
        records.append({
            'country':          cid,
            'display':          _id_to_display(cid),
            'tier':             TIER_BY_COUNT[min(count, 4)],
            'active_count':     count,
            'active_axes':      active,
            'summed_intensity': sum(axes[a]['intensity'] for a in active),
            'axes':             axes,
        })

    records.sort(key=lambda r: (TIER_RANK[r['tier']], r['summed_intensity']), reverse=True)

    # History: read each active country's series in one pipeline call, attach metrics + prose
    series_by_id = _read_history([r['country'] for r in records])
    for r in records:
        hist = _history_metrics(r['tier'], r['summed_intensity'],
                                series_by_id.get(r['country'], []), now_iso)
        r['history'] = hist
        r['so_what'] = _so_what(r, hist)

    tier_counts = {'quad': 0, 'triple': 0, 'dual': 0, 'single': 0}
    for r in records:
        tier_counts[r['tier']] += 1

    # Payload-level summary prose
    top = records[0]['display'] if records else None
    summary = (f"{tier_counts['quad']} quad / {tier_counts['triple']} triple / "
               f"{tier_counts['dual']} dual / {tier_counts['single']} single-axis countries active"
               + (f"; strongest: {top}." if top else "."))

    return {
        'records':       records,
        'tier_counts':   tier_counts,
        'summary':       summary,
        'availability':  {'kinetic': kin_ok, 'commodity': com_ok,
                          'rhetoric': rhe_avail, 'humanitarian': hum_ok},
        'global_conditions': global_conditions,
        'now_epoch':     now_epoch,
        'now_iso':       now_iso,
    }


def register_convergence_detector_endpoints(app):
    """Register the convergence-detector endpoints on the ME Flask app."""
    from flask import jsonify

    @app.route('/api/cax/scan', methods=['GET'])
    def cax_scan():
        """Four-axis join + tiering + history + prose. Guarded snapshot on 6h cadence."""
        try:
            result = build_convergence()
            # guarded history write (at most once per 6h, one pipeline call)
            try:
                wrote = _maybe_snapshot(result['records'], result['now_epoch'], result['now_iso'])
            except Exception as e:
                print(f"[ConvergenceDetector] snapshot error: {e}")
                wrote = False
            return jsonify({
                'success':         True,
                'version':         '0.6.0',
                'step':            '6 (global-commodity demotion live -- shared headlines relocated)',
                'generated_at':    result['now_iso'],
                'tier_counts':     result['tier_counts'],
                'summary':         result['summary'],
                'availability':    result['availability'],
                'global_conditions': result['global_conditions'],
                'snapshot_written': wrote,
                'count':           len(result['records']),
                'records':         result['records'],
                'disclaimer':      DISCLAIMER,
            })
        except Exception as e:
            print(f"[ConvergenceDetector] /scan error: {e}")
            return jsonify({'success': False, 'error': str(e)[:300]}), 500

    @app.route('/api/cax/history/<country>', methods=['GET'])
    def cax_history(country):
        """Raw rolling history series for one country (newest-first)."""
        cid = country.strip().lower()
        series = _read_history([cid]).get(cid, [])
        return jsonify({
            'success': True, 'version': '0.6.0', 'country': cid,
            'display': _id_to_display(cid), 'readings': len(series),
            'series': series,
        })

    @app.route('/api/cax/probe', methods=['GET'])
    def cax_probe():
        """Lightweight availability probe -- which caches are warm right now."""
        kin = _redis_get(KINETIC_CACHE_KEY)
        com = _redis_get(COMMODITY_CACHE_KEY)
        rhe = {r: bool(_redis_get(k)) for r, k in RHETORIC_BLUF_KEYS.items()}
        hum = _redis_get(HUMANITARIAN_CACHE_KEY)
        return jsonify({
            'success': True, 'version': '0.6.0',
            'redis_configured': bool(_REDIS_URL and _REDIS_TOKEN),
            'kinetic_warm':      bool(kin),
            'commodity_warm':    bool(com),
            'rhetoric_warm':     rhe,
            'humanitarian_warm': bool(hum),
            'probed_at': datetime.now(timezone.utc).isoformat(),
        })

    print("[ConvergenceDetector] Registered: /api/cax/scan, /api/cax/history/<c>, /api/cax/probe  (v0.6.0)")
