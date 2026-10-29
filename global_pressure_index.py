"""
global_pressure_index.py
Asifah Analytics — Global Pressure Index Engine
v3.7.0 — Jul 25 2026 (NARRATIVE DECAY)
v3.10.0 add-on — Oct 28 2026: israel_formation_window narrative (caretaker Israel x hot Iran axis)
v3.12.0 — Oct 28 2026 (SEVERITY vs MOTION):
  * L5 NOVELTY GATE. Global L5 now means "a NEW L5 front within 14 days" (or a
    front that went quiet 3+ days and re-ignited). A war that has been at L5
    for weeks with nothing new added reads L4 SUSTAINED CONFLICT -- day N. The
    war is not hidden: the kinetic axis and every regional page keep their
    honest L5. GPI-only (Rachel, Oct 28). L6 red-line breach is NEVER gated.
  * GOVERNANCE AXIS (5th). Elections, caretaker periods, government formation,
    successions, coups, legitimacy contests. Non-kinetic butterflies with
    kinetic consequences -- they were filed under 'diplomatic', which means
    talks BETWEEN states, not who governs INSIDE one.
  * STANDING-WATCH TIER for narratives. A structural watch (wheat, diamonds,
    phosphate, clusters) that is not moving collapses below the toplines and
    re-opens itself the moment its headline changes.
  * NARRATIVE DECAY WIRED IN. _apply_narrative_decay() shipped Jul 25 and was
    never called by anything. It now runs, and counts at most one cycle per
    11h so a burst of ?force=true rebuilds cannot age a signal in an afternoon.
  * Payload version reads GPI_VERSION (was a literal '3.0.0' since spring).
v3.13.0 — Oct 28 2026 (L6 DOCTRINE + governance token fix):
  * L6 = GLOBAL SHOCK: systemic event class (WMD use excl. tests/drills/threats;
    nuclear-adversary clash; Article-5 attack on NATO; invasion/blockade of a
    NEW state; head of state killed; coup in a nuclear state; mass casualty at
    national-trauma scale, per-capita: 9/11 ~10/M, Oct 7 ~122/M) AND observed
    world reaction (UNSC emergency / NATO Art 4-5 / G7 emergency) naming the
    country; holds 7 days. Tracker L6 that fails is demoted to L5 in the GPI.
  * _is_governance_signal is whole-token ('commodity_coupling' matched 'coup').
v3.14.0 — Oct 29 2026 (SEVERITY vs MOTION on the axes):
  * Each axis carries motion: new / sustained / unread (gpi:axis_motion; kinetic
    reads the L5 gate's onsets). Tabs and prose show "L5 · sustained" etc., and
    the prose explains why an axis can sit above the index.
  * Axis chip words come from each axis's own ladder -- humanitarian L5 no
    longer reads "ACTIVE CONFLICT" (L5 assertion rule).
v3.15.0 — Oct 29 2026 (COMMODITY WEBS):
  * Registry narratives take a LIVE headline and detail when the stamping
    layer supplies one (convergence_states[id].live_headline / live_detail).
    commodity_web.py does: "Rice convergence -- India restricting exports and
    the world price rising while Nigeria is already under stress" instead of
    a static template. Every other entry is unchanged (no live text -> template).
  * A stamped level_hint/priority (the web's own L3/L4/L5) is used when a
    narrative is promoted into the signal feed; before, any priority >= 13
    promoted at L5, so a fresh L3 watch would have read as L5.
  * Registry narratives honour an entry's 'axes' list. Before this, a
    registry narrative with no NARRATIVE_AXIS_SETS row fell through to the
    KINETIC default -- a rice web would have counted as war.
v3.16.0 — Oct 29 2026 (EVIDENCE GATES ON ECONOMIC NARRATIVES):
  * Conditions are not events. Market-fragility cards are L3 standing unless
    the Taiwan-exposed semis instrument actually falls (TSM/SOXX: -15%/30d or
    -7%/5 sessions) and/or an actual L5 kinetic event hits the Taiwan theatre:
    one = L4, both = L5. The plain fragility card's priority map ran
    backwards (elevated band = priority 13 = promoted L5) -- fixed.
  * Breadth is not news. "Global <commodity> pressure -- N exposed countries"
    surfaces only when that commodity has earned L4+ on the commodity ladder.
  * COMMODITY EVIDENCE CAP. Regional "Composite commodity pressure: SURGE"
    signals (news-volume points) set the economic axis to L5 while every
    commodity had earned only L3. At GPI altitude a country's commodity
    signal is capped at what that commodity has earned; country pages keep
    their own reading, and the payload keeps level_country + level_capped.
  * The "no cross-theater convergence detected" fallback no longer appears
    beside convergence narratives (it contradicted the page).
  * Narratives may carry fresh=False (a condition is standing by definition);
    _tier_narratives already honours it.
(prior: v3.6.0 May 23 2026 AFRICA-READY; v3.5.0 May 21 2026 ENRICHED OUTPUT; v2.0.0 April 2026 baseline)

NARRATIVE DECAY (v3.7.0): the GPI surfaces what is CHANGING. A signal that has
said the same thing at the same level for weeks is a standing condition, not a
topline -- and while it holds a headline slot, something moving cannot. Decay
keys on MOVEMENT, never on a curated list: a genuine crisis moves and is never
touched; a static tally yields. Applied at GPI ranking only -- regional BLUFs
and country pages rank on their own terms.

THE TOP OF THE ANALYTICAL PYRAMID.

Synthesizes all four regional BLUFs (ME, Asia, Europe, WHA) into:
1. A SINGLE GLOBAL LEVEL (0-5) for the index.html dynamic button
2. AN ANALYST-PROSE BLUF that detects cross-theater convergence narratives
   ("China rising, signals point to Taiwan takeover days away", "Russia-Iran
   uranium axis active despite IAEA pressure", "Houthi quiescence fragile")
3. STRUCTURED REGIONAL CARDS for the GPI page
4. A LIGHTWEIGHT /level ENDPOINT for the landing page button

ARCHITECTURE:
- /api/gpi          → full synthesis (cached 12h, force=true to refresh)
- /api/gpi/level    → minimal {level, label, color} for index.html button
- /api/gpi/debug    → cache inspection

NARRATIVE DETECTION:
Each detector function reads regional BLUFs + cross-theater signals and either:
  - returns a Narrative dict (priority, prose, regions involved)
  - returns None (no narrative detected this scan)

The narrative registry is extensible — add a new function, append to NARRATIVE_DETECTORS,
and it joins the synthesis pipeline. Future CAVE / energy narratives slot in cleanly.

ENERGY/CAVE ROADMAP (NOT IMPLEMENTED TODAY):
- Reserved scan_data fields: energy_pressure, oil_pressure, lng_pressure, uranium_pressure
- Reserved narrative categories: energy_crunch, supply_disruption, sanctions_evasion
- Reserved cross-theater signals: cave_*

Author: RCGG / Asifah Analytics
"""

import os
import json
import traceback
import re
from datetime import datetime, timezone
import requests


# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '')

# Regional BLUF endpoints (all must return canonical schema or shim-normalized)
# These backends each host /api/rhetoric/{region}/bluf
REGIONAL_BLUF_ENDPOINTS = {
    'me':     os.environ.get('ME_BACKEND_URL',     'https://asifah-backend.onrender.com')         + '/api/rhetoric/me/bluf',
    'asia':   os.environ.get('ASIA_BACKEND_URL',   'https://asifah-asia-backend.onrender.com')   + '/api/rhetoric/asia/bluf',
    'europe': os.environ.get('EUROPE_BACKEND_URL', 'https://asifa-europe-backend.onrender.com') + '/api/rhetoric/europe/bluf',
    'wha':    os.environ.get('WHA_BACKEND_URL',    'https://asifah-wha-backend.onrender.com')    + '/api/rhetoric/wha/bluf',
    # v3.6 (May 23 2026) -- Africa theatre placeholder.
    # Activates when africa_regional_bluf.py + rhetoric_tracker_sudan.py ship.
    # Until then, fetch returns None and GPI gracefully skips. The convergence
    # registry already has 3 africa-trigger_region entries (cobalt_drc_active,
    # diamonds_sanctions_regime, phosphate_food_security) ready to consume this.
    'africa': os.environ.get('AFRICA_BACKEND_URL', 'https://asifah-africa-backend.onrender.com') + '/api/rhetoric/africa/bluf',
    # v2.3 (May 17, 2026) — Humanitarian Convergence Detector
    # Pseudo-region: distributed weak-signal aggregation across countries
    # WITHOUT dedicated Asifah trackers. Lives on ME backend; consumed by
    # GPI exactly like a 5th regional BLUF.
    'global_humanitarian': os.environ.get('ME_BACKEND_URL', 'https://asifah-backend.onrender.com') + '/api/humanitarian-convergence/bluf',
    # v2.4 (May 17, 2026) -- Cascade Commodity Detector
    # Pseudo-region: detects chokepoint -> intermediate -> downstream commodity
    # cascades (sulfur cascade is first chain). Signals tagged pressure_type=
    # 'economic' so they flow into the GPI economic axis. Same architectural
    # pattern as humanitarian convergence.
    'global_cascade': os.environ.get('ME_BACKEND_URL', 'https://asifah-backend.onrender.com') + '/api/cascade-convergence/bluf',
    # v3.7 (Jun 2026) -- Commodity Pressure Detector
    # Pseudo-region: surfaces high/surge per-commodity news-signal pressure,
    # gated to a real supply-relevant driver + import-dependent exposure.
    # Signals tagged pressure_type='economic'. Same architectural pattern as
    # the cascade + humanitarian pseudo-regions; GPI needs no logic changes.
    'global_commodity': os.environ.get('ME_BACKEND_URL', 'https://asifah-backend.onrender.com') + '/api/commodity-pressure/bluf',
    # v3.8 (Jun 10 2026) -- Food Price Pulse (Slice 3)
    # Pseudo-region: WFP-measured domestic staple prices, ~98 countries,
    # gated to high-band + multi-staple (broad-basket stress pattern).
    # Signals tagged pressure_type='economic'. Same architectural pattern
    # as humanitarian / cascade / commodity; GPI needs no axes changes.
    'global_food': os.environ.get('ME_BACKEND_URL', 'https://asifah-backend.onrender.com') + '/api/food-price-pulse/bluf',
}

# Display config
REGION_DISPLAY = {
    'me':     {'flag': '\U0001f54c', 'name': 'Middle East',       'hub': 'rhetoric-index.html'},   # 🕌
    'asia':   {'flag': '\U0001f30f', 'name': 'Asia & Pacific',    'hub': 'rhetoric-asia.html'},    # 🌏
    'europe': {'flag': '\U0001f30d', 'name': 'Europe',            'hub': 'rhetoric-europe.html'},  # 🌍
    'wha':    {'flag': '\U0001f30e', 'name': 'Western Hemisphere','hub': 'rhetoric-wha.html'},     # 🌎
    'africa': {'flag': '\U0001f30d', 'name': 'Africa',            'hub': 'rhetoric-africa.html'},  # 🌍 (v3.6, activates with africa.html)
    # v2.3 — Humanitarian Convergence Detector pseudo-region
    'global_humanitarian': {'flag': '\U0001f198', 'name': 'Global Humanitarian', 'hub': 'gpi.html'},  # 🆘
    'global_cascade': {'flag': '\u2697\ufe0f', 'name': 'Global Cascade', 'hub': 'gpi.html'},  # alembic emoji
}

# Alphabetical card order (matches Rachel's "presumably alphabetical" spec)
# v3.6 (May 23 2026): africa added in alphabetical position. Renders when
# africa BLUF endpoint activates; until then, _signals_of() returns [] gracefully.
CARD_ORDER = ['africa', 'asia', 'europe', 'me', 'wha']

# Global level labels + colors (matches canonical regional schema)
# ── CANONICAL LADDER (Oct 3 2026) ────────────────────────────────────
# Aligned to the five regional BLUFs and asifah-standard-shell.js. This dict
# used to read BASELINE / MONITORING--RHETORIC / WARNING / ELEVATED /
# INCIDENT, which meant L3 was "ELEVATED" here, "Direct Threat" on the ME
# BLUF and "Confrontation" on the Asia page -- one number, three words.
#
# L6 is kept and is GPI-ONLY. A global index legitimately exceeds any single
# theatre: five theatres each at Active Conflict is a different world from
# one, and RED-LINE BREACH is the rung that says so. The regional ladders
# stop at 5 because a theatre cannot exceed its own ceiling.
#
# CHIP language. For prose use theatre_state.py, which is axis-aware.
GLOBAL_LEVEL_LABELS = {
    0: 'MONITORING',
    1: 'RHETORIC',
    2: 'WARNING',
    3: 'CONFRONTATION',
    4: 'COERCION',
    5: 'ACTIVE CONFLICT',
    6: 'GLOBAL SHOCK',      # v3.13.0 -- L6 doctrine; was 'RED-LINE BREACH' (tit-for-tat qualified)
}

GLOBAL_LEVEL_COLORS = {
    0: '#6b7280',   # slate
    1: '#3b82f6',   # blue
    2: '#f59e0b',   # amber
    3: '#f97316',   # orange
    4: '#ef4444',   # red
    5: '#dc2626',   # dark red
    6: '#991b1b',   # deepest red -- red-line breach beyond active conflict
}

# ══════════════════════════════════════════════════════════════════════
# COUNTRY TOUCH TAGS (Jul 27 2026)
# ══════════════════════════════════════════════════════════════════════
# A signal BELONGS to a theatre. It TOUCHES countries. Those are different
# relations and the GPI only modelled the first, so cross-theatre references
# were invisible to grouping.
#
# The Jul 27 tagging audit found the cost: four of twenty displayed signals
# referenced Iran under FOUR different theatre tags --
#   dual_chokepoint    (global)        names iran, yemen
#   houthi_fragility   (global)        names iran, yemen
#   iran_deescalation  (global)        names iran
#   alignment_drift    (saudi_arabia)  names iran, israel
# -- so Iran occupied a fifth of the page under five headings, and the
# grouping logic could not see any of them as related.
#
# RE-TAGGING WOULD BE WRONG. A simultaneous Hormuz + Bab el-Mandeb read is a
# MARITIME signal, not an Iran signal; forcing it into an Iran theatre would
# lose what it is. So the theatre stays, and a separate `countries` list
# records what the signal touches. Many-to-many, which is what it always was.
#
# Downstream this gives two things: a pill per country on the headline, and a
# per-country rollup that can gather every signal touching Iran regardless of
# where it was filed.

# v3.8.0 -- ONE country-id canon for the whole platform.
try:
    from country_ids import canonical as _canon, display as _canon_display
    _CANON_AVAILABLE = True
except ImportError:
    _CANON_AVAILABLE = False
    def _canon(x):
        return (str(x).strip().lower().replace('-', '_').replace(' ', '_')
                if x else '')
    _canon_display = None
    print('[GPI] *** country_ids NOT installed -- country tags will NOT be '
          'canonicalized. GPI will keep disagreeing with the convergence '
          'detector about us/usa and drc/dr congo. Deploy country_ids.py. ***')

# SUPERSEDED v3.8.0 by country_ids.ALIASES. Kept because the two sets below
# are still read to build _CANON_COUNTRY_SET, and because it records what this
# file used to believe.
COUNTRY_TOUCH_ALIASES = {
    'united states': 'us', 'usa': 'us', 'u.s.': 'us', 'america': 'us',
    'north korea': 'dprk', 'south korea': 'south_korea',
    'saudi arabia': 'saudi_arabia', 'burkina faso': 'burkina_faso',
    'south sudan': 'south_sudan', 'south africa': 'south_africa',
    'central african republic': 'car', 'uae': 'uae',
    'emirates': 'uae', 'united arab emirates': 'uae',
}

# Word-boundary matched. ' mali' inside 'somalia' and 'car' inside 'carrier'
# are the traps this exists to avoid -- the same class the Telegram relevance
# gate documents.
COUNTRY_TOUCH_TERMS = [
    'afghanistan', 'algeria', 'armenia', 'azerbaijan', 'bahrain', 'belarus',
    'brazil', 'burkina faso', 'central african republic', 'chad', 'chile',
    'china', 'colombia', 'cuba', 'cyprus', 'denmark', 'drc', 'egypt',
    'ethiopia', 'gaza', 'georgia', 'greece', 'greenland', 'haiti', 'hungary',
    'india', 'indonesia', 'iran', 'iraq', 'israel', 'japan', 'jordan',
    'kazakhstan', 'kenya', 'kuwait', 'lebanon', 'libya', 'madagascar', 'mali',
    'mexico', 'moldova', 'morocco', 'mozambique', 'myanmar', 'niger',
    'nigeria', 'north korea', 'dprk', 'oman', 'pakistan', 'panama', 'peru',
    'philippines', 'poland', 'qatar', 'russia', 'rwanda', 'saudi arabia',
    'somalia', 'south africa', 'south korea', 'south sudan', 'sudan', 'syria',
    'taiwan', 'tanzania', 'thailand', 'tunisia', 'turkey', 'uae', 'uganda',
    'ukraine', 'venezuela', 'vietnam', 'yemen', 'united states', 'usa',
]

# Geographic features that IMPLY a country. Found Jul 27 2026 in testing: the
# dual_chokepoint signal reads "Hormuz and Bab el-Mandeb simultaneous" and
# tagged ZERO countries, because chokepoints are not country names. A maritime
# signal that cannot reach Iran or Yemen is exactly the cross-theatre blindness
# this whole layer exists to fix.
#
# Deliberately conservative: only features whose country attribution is
# uncontested. Disputed waters are left out -- attributing the South China Sea
# to one claimant would be an editorial act, not a tagging one.
GEO_FEATURE_COUNTRIES = {
    'hormuz':          ['iran', 'oman', 'uae'],
    'strait of hormuz': ['iran', 'oman', 'uae'],
    'bab el-mandeb':   ['yemen', 'djibouti'],
    'bab al-mandab':   ['yemen', 'djibouti'],
    'red sea':         ['yemen', 'egypt', 'saudi_arabia'],
    'suez':            ['egypt'],
    'taiwan strait':   ['taiwan', 'china'],
    'kerch':           ['russia', 'ukraine'],
    'black sea':       ['russia', 'ukraine', 'turkey'],
    'bosphorus':       ['turkey'],
    'dardanelles':     ['turkey'],
    'malacca':         ['malaysia', 'indonesia', 'singapore'],
    'panama canal':    ['panama'],
    'senkaku':         ['japan', 'china'],
    'donbas':          ['ukraine'],
    'crimea':          ['ukraine', 'russia'],
    'sahel':           ['mali', 'niger', 'burkina_faso'],
    'liptako-gourma':  ['mali', 'niger', 'burkina_faso'],
    'gaza strip':      ['gaza', 'israel'],
    'west bank':       ['israel'],
    'golan':           ['syria', 'israel'],
    'kashmir':         ['india', 'pakistan'],
    'korean peninsula': ['dprk', 'south_korea'],
}

_GEO_FEATURE_RE = re.compile(
    r'\b(' + '|'.join(re.escape(t) for t in
                      sorted(GEO_FEATURE_COUNTRIES, key=len, reverse=True)) + r')\b',
    re.IGNORECASE)

_COUNTRY_TOUCH_RE = re.compile(
    r'\b(' + '|'.join(re.escape(t) for t in
                      sorted(COUNTRY_TOUCH_TERMS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE)


def _norm_country(name):
    """Any inbound country spelling -> the platform's canonical id."""
    return _canon(name)


_CANON_COUNTRY_SET = {_canon(t) for t in COUNTRY_TOUCH_TERMS}
_CANON_COUNTRY_SET |= {_canon(v) for v in COUNTRY_TOUCH_ALIASES.values()}
_CANON_COUNTRY_SET |= {_canon(c) for vals in GEO_FEATURE_COUNTRIES.values()
                       for c in vals}
_CANON_COUNTRY_SET.discard('')


def _signal_countries(signal):
    """Countries a signal TOUCHES. Theatre first, then prose.

    An explicit `countries` list on the signal always wins -- source modules
    that know their own scope should say so rather than have it inferred from
    prose, which is a fallback and not a good one.
    """
    if not isinstance(signal, dict):
        return []
    explicit = signal.get('countries')
    if isinstance(explicit, (list, tuple)) and explicit:
        return sorted({_norm_country(c) for c in explicit if c})

    out = set()
    theatre = signal.get('theatre')
    # Container theatres are not countries -- tagging them as such would put
    # 'global' in a country rollup.
    if theatre and str(theatre).lower() not in (
            'global', 'worldwide', 'unknown', '', 'regional', 'synthesis'):
        out.add(_norm_country(theatre))

    # Narratives carry `regions` (e.g. ['global_market', 'me']) and use
    # headline/detail where signals use short_text/long_text. Reading all of
    # them means one extractor serves both populations.
    text = ' '.join(str(signal.get(k) or '') for k in
                    ('short_text', 'long_text', 'headline', 'detail',
                     'watch', 'so_what'))
    for r in (signal.get('regions') or []):
        rn = _norm_country(r)
        # Region buckets are not countries; only fold in real ones.
        if rn in _CANON_COUNTRY_SET:
            out.add(rn)
    for m in _COUNTRY_TOUCH_RE.finditer(text):
        out.add(_norm_country(m.group(1)))
    # Chokepoints and contested geographies imply countries the prose may never
    # name. A Hormuz signal is an Iran signal whether or not it says "Iran".
    for m in _GEO_FEATURE_RE.finditer(text):
        for c in GEO_FEATURE_COUNTRIES.get(m.group(1).lower(), []):
            out.add(_canon(c))
    return sorted(x for x in out if x)


def _attach_country_tags(signals):
    """Stamp `countries` onto every signal. Idempotent."""
    for s in signals or []:
        if isinstance(s, dict) and not s.get('countries'):
            s['countries'] = _signal_countries(s)
    return signals


def _build_country_rollup(signals, min_signals=2):
    """The full picture per country, across theatres.

    Answers "what does the Iran page owe to signals filed elsewhere?" -- which
    the theatre-keyed grouping structurally cannot, because those signals are
    not filed under Iran.

    min_signals=2 by default: a country appearing once is already visible in
    its own signal and does not need a rollup entry.
    """
    by_country = {}
    for s in signals or []:
        if not isinstance(s, dict):
            continue
        for c in (s.get('countries') or []):
            rec = by_country.setdefault(c, {
                'country': c, 'signal_count': 0, 'max_level': 0,
                'axes': set(), 'theatres': set(), 'signals': [],
                'own_theatre_signals': 0, 'referenced_from_elsewhere': 0,
            })
            rec['signal_count'] += 1
            try:
                rec['max_level'] = max(rec['max_level'], int(s.get('level') or 0))
            except (TypeError, ValueError):
                pass
            ax = s.get('pressure_type')
            if ax:
                rec['axes'].add(ax)
            th = _norm_country(s.get('theatre') or '')
            rec['theatres'].add(s.get('theatre') or 'global')
            if th == c:
                rec['own_theatre_signals'] += 1
            else:
                rec['referenced_from_elsewhere'] += 1
            if len(rec['signals']) < 8:
                rec['signals'].append({
                    'theatre':  s.get('theatre'),
                    'category': s.get('category'),
                    'level':    s.get('level'),
                    'text':     (s.get('short_text') or '')[:110],
                    'filed_elsewhere': th != c,
                })

    out = []
    for c, rec in by_country.items():
        if rec['signal_count'] < min_signals:
            continue
        rec['axes'] = sorted(rec['axes'])
        rec['theatres'] = sorted(rec['theatres'])
        # The number that matters: how much of this country's picture lives
        # OUTSIDE its own theatre. High = the country page is under-reporting.
        rec['cross_theatre_pct'] = round(
            rec['referenced_from_elsewhere'] / rec['signal_count'] * 100, 0)
        out.append(rec)
    out.sort(key=lambda r: (-r['signal_count'], -r['max_level']))
    return out


# ══════════════════════════════════════════════════════════════════════
# THEATRE STATE VOCABULARY (Jul 27 2026)
# ══════════════════════════════════════════════════════════════════════
# GLOBAL_LEVEL_LABELS above is SCORING language -- "INCIDENT", "ELEVATED".
# It answers "how high" and is right for the gauge. It is wrong for the
# landing page, where "Iran L5" tells a first-time visitor nothing at all.
#
# These are STATE descriptions: what a theatre is DOING, phrased so it reads
# as a finding rather than a score. "Iran: active war footing" is legible to
# anyone; "Iran L5" is legible only to us.
#
# DESIGNED FOR PEACETIME, deliberately. The global level has sat at L5 for so
# long that the low bands are untested -- so they are written to be INFORMATIVE
# on the way down, not just placeholders. If Iran fell to L2, "pressure
# building" is a real read; "L2" is not. A vocabulary that only works during
# war is a vocabulary that cannot report peace.
# The platform already models FOUR pressure axes (kinetic, economic,
# humanitarian, diplomatic -- see NARRATIVE_AXIS_SETS below). A single
# level-only vocabulary collapses them, and collapses them WRONGLY: a
# magnitude-9 earthquake that kills thousands is a legitimate L5, but calling
# it "active war footing" is not imprecise, it is false.
#
# Tohoku 2011 is the reference case and it sits in the market library as a
# deliberate null: exogenous, mass-casualty, no kinetic content whatsoever.
# The landing page must be able to say "mass-casualty emergency" without
# implying a war.
THEATRE_STATE = {
    'kinetic': {
        0: 'quiet',
        1: 'rhetorical signalling',
        2: 'pressure building',
        3: 'standoff hardening',
        4: 'armed incident',
        5: 'active war footing',
        # v3.13.0 -- on the GPI a kinetic L6 exists only as a CONFIRMED global
        # shock (tracker red-line breaches are demoted to L5), so the phrase
        # says what that is. Country pages keep 'red line breached' via the
        # shared shell / theatre_state.py, where L6 still means exactly that.
        6: 'world-altering escalation',
    },
    'humanitarian': {
        0: 'quiet',
        1: 'early humanitarian indicators',
        2: 'population pressure building',
        3: 'humanitarian conditions deteriorating',
        4: 'acute humanitarian emergency',
        5: 'mass-casualty humanitarian disaster',
        6: 'catastrophic humanitarian collapse',
    },
    'economic': {
        0: 'quiet',
        1: 'market signalling',
        2: 'cost pressure building',
        3: 'supply pressure hardening',
        4: 'acute supply disruption',
        5: 'economic rupture',
        6: 'systemic economic breakdown',
    },
    'diplomatic': {
        0: 'quiet',
        1: 'diplomatic signalling',
        2: 'diplomatic friction',
        3: 'diplomatic standoff',
        4: 'talks collapsed',
        5: 'diplomatic rupture',
        6: 'relations severed',
    },
    # v3.12.0 -- who governs, and on what authority. L3 is the normal reading
    # of a caretaker / formation window: authority is contested, not broken.
    'governance': {
        0: 'quiet',
        1: 'political signalling',
        2: 'political friction',
        3: 'governing authority contested',
        4: 'governance crisis',
        5: 'legitimacy rupture',
        6: 'constitutional order broken',
    },
}

# Category overrides. Some signals describe a MECHANISM the level and axis
# together still cannot convey -- a hub losing ground is not "an armed
# incident" even at L4, and a fuel blockade is not "acute supply disruption"
# when the point is that a CAPITAL is being strangled.
CATEGORY_STATE = {
    'hub_trajectory':         'network position shifting',
    'economic_siege':         'capital under economic siege',
    'client_hedging':         'patron dependency loosening',
    'insurgent_convergence':  'insurgent factions converging',
    'claiming_actor_silence': 'unusual quiet from a claiming actor',
    'red_line_breached':      'red line breached',
    'logistics_corridor':     'supply corridor under pressure',
    'bloc_cohesion':          'bloc cohesion tested',
    'market_fragility':       'market fragility elevated',
    'diplomatic_track':       'diplomatic track active',
    'government_formation':   'government formation underway',
    'displacement':           'mass displacement underway',
    'famine_risk':            'famine conditions emerging',
    'disease_outbreak':       'disease outbreak spreading',
    'natural_disaster':       'natural disaster response underway',
}

# Signals that predate pressure_type tagging default to kinetic (matching the
# GPI's own backwards-compat rule), but these categories are unambiguous and
# are mapped explicitly so an untagged humanitarian signal is never described
# as a military one.
CATEGORY_AXIS_HINTS = {
    'displacement': 'humanitarian', 'famine_risk': 'humanitarian',
    'disease_outbreak': 'humanitarian', 'natural_disaster': 'humanitarian',
    'humanitarian_compression': 'humanitarian', 'refugee_flow': 'humanitarian',
    'economic_siege': 'economic', 'logistics_corridor': 'economic',
    'market_fragility': 'economic', 'commodity_pressure': 'economic',
    'diplomatic_track': 'diplomatic', 'mediation': 'diplomatic',
    'kinetic_tempo': 'kinetic', 'red_line_breached': 'kinetic',
    'government_formation': 'governance', 'israel_formation_window': 'governance',
}


# ── v3 (Oct 3 2026) ─────────────────────────────────────────────────
# THEATRE_STATE / CATEGORY_STATE above were written here in July and called
# in exactly ONE place -- the landing-page banner. The ME regional BLUF and
# every tracker long_text below kept emitting raw levels, so the vocabulary
# that was designed to make this legible to a stranger reached one line of
# one page. theatre_state.py now carries it as a shared primitive, and the
# tables above are kept as the in-file fallback so this module still works
# if dropped into a backend without it.
try:
    from theatre_state import (theatre_state as _ts_shared,
                               state_with_level as _ts_level,
                               named_state as _ts_named)
    _TS_SHARED = True
except ImportError:
    _TS_SHARED = False
    def _ts_level(level, category=None, pressure_type=None, upper=False):
        p = _theatre_state(level, category, pressure_type)
        return '%s (L%s)' % (p.upper() if upper else p, level)
    def _ts_named(name, level, category=None, pressure_type=None):
        return '%s -- %s (L%s)' % (name, _theatre_state(level, category, pressure_type), level)


def _theatre_state(level, category=None, pressure_type=None):
    """Plain-language state, resolved by AXIS then level.

    Resolution order, most-specific first:
      1. category override  -- the mechanism, where it says more than either
      2. axis + level       -- the normal path
      3. kinetic + level    -- last resort, matching the GPI's own default
    """
    if category and category in CATEGORY_STATE:
        return CATEGORY_STATE[category]
    axis = (pressure_type or CATEGORY_AXIS_HINTS.get(category or '')
            or PRESSURE_KINETIC)
    if axis not in THEATRE_STATE:
        axis = PRESSURE_KINETIC
    try:
        lv = max(0, min(6, int(level or 0)))
    except (TypeError, ValueError):
        lv = 0
    return THEATRE_STATE[axis][lv]


# ============================================================
# LANDING-PAGE BANNER  (Sep 2026)
# ============================================================
# The landing page is a DOOR, not a room. Its only job is to earn a click.
#
# WHY NOT COUNTRIES: "Russia, Taiwan, Iraq" tells a geopolitically curious
# visitor what they already read this morning. It confirms rather than informs,
# and confirmation gives nobody a reason to click through. Signal-type labels
# (Kinetic / Economic) are worse -- they describe our taxonomy, not the world.
#
# WHAT GOES THERE INSTEAD: the leading CONVERGENCE, as a short compound tag.
# A connection is the one thing on this platform a well-informed reader cannot
# get elsewhere, and it opens a curiosity gap rather than closing one:
#     "Markets x Taiwan"        not  "Taiwan"
#     "Hormuz x Bab el-Mandeb"  not  "Iran, Yemen"
# Two nouns and a multiplication sign. The room is behind the door.
#
# L6 IS DIFFERENT. A red-line breach is rare enough to be its own hook, so it
# DISPLACES the level line and names the country. Note the gate is level == 6
# specifically, NOT the red_line_breached category: on 4 Sep four signals
# carried that category (Iraq, Russia, Somalia x2) and only Iraq was L6. Gating
# on category would fire constantly, which is exactly the failure mode the
# pinned-at-L5 gauge already demonstrates.

# Compound tags per narrative category. Kept as a registry rather than derived,
# because the phrasing is editorial and a bad auto-generated tag on the front
# door is worse than no tag. Unregistered categories fall through to a generic
# builder rather than rendering nothing.
# TITLE CASE, hand-set rather than machine-applied. A naive .title() would
# produce "Pla Tempo" and "Bab El-Mandeb" -- acronyms and name particles are
# exactly what automatic casing gets wrong, and this text sits on the front door.
CONVERGENCE_TAGS = {
    'market_fragility_semis_compound': 'Markets \u00d7 Taiwan Semis',
    'dual_chokepoint':                 'Hormuz \u00d7 Bab el-Mandeb',
    'china_taiwan_takeover':           'PLA Tempo \u00d7 Taiwan',
    # NOTE: no count here. An earlier version read "x Two Theatres" and went
    # stale the moment Europe dropped off -- the banner asserted two while the
    # narrative said one. A tag that states a number must DERIVE it; see
    # _compound_tag's dynamic branch below.
    'nuclear_signaling_global':        '',
    'iran_axis_convergence':           'Iran Axis \u00d7 Proxy Fronts',
    'iran_deescalation':               'Ceasefire \u00d7 Breach Risk',
    'wheat_lebanon':                   'Black Sea Wheat \u00d7 Lebanon',
    'wha_cascade':                     'Regime Stress \u00d7 Migration',
    'multiaxis_convergence':           'Independent Streams \u00d7 One Country',
    'hub_network_breadth':             'One Hub \u00d7 Many Regions',
    'contested_spoke':                 'One Node \u00d7 Many Hubs',
    'food_stress_convergence':         'Food Prices \u00d7 Conflict',
    'emplacement_precursor':           'Red Line \u00d7 Denial',
    'policy_branch_convergence':       'Three Theatres \u00d7 One Method',
    'israel_formation_window':         'Caretaker Israel \u00d7 Iran Axis',
    'houthi_fragility':                'Houthi Quiet \u00d7 Fragile',
    'market_fragility':                'Market Concentration \u00d7 Fragility',
}

# Words that stay lowercase inside a tag unless they lead it. Name particles
# ("Bab el-Mandeb") and joiners; everything else takes an initial capital.
_TAG_LOWER = {'el', 'al', 'de', 'da', 'von', 'van', 'the', 'of', 'and', 'in', 'on'}

# Acronyms that arrive LOWERCASE from category slugs and region codes. Without
# these, 'us_inbound_influence' renders as "Us Inbound Influence" -- the exact
# fault already fixed once in the GPI narrative prose. Reused here rather than
# re-derived so the two cannot drift apart.
_TAG_ACRONYMS = {'us', 'uk', 'eu', 'uae', 'drc', 'car', 'dprk', 'bri', 'ipc',
                 'laf', 'idf', 'isf', 'ivc', 'pla', 'adiz', 'nato', 'un', 'who',
                 'gdp', 'wha'}

# Region codes as they appear in narrative `regions` lists.
_TAG_REGION_NAMES = {'me': 'Middle East', 'wha': 'Western Hemisphere',
                     'asia': 'Asia-Pacific', 'asia_pacific': 'Asia-Pacific',
                     'europe': 'Europe', 'africa': 'Africa',
                     'middle_east': 'Middle East', 'global': 'Global',
                     'global_commodity': 'Commodities',
                     'global_market': 'Markets',
                     'global_humanitarian': 'Humanitarian'}


def _titlecase_tag(text):
    """Title-case a tag without destroying acronyms or name particles.

    Applied to the GENERIC fallback path only -- registry entries above are
    hand-cased. A token already containing an uppercase letter is left alone,
    which preserves PLA, US, BRI, IPC and anything else that arrives shouting.
    """
    def _case_word(w, lead):
        if not w:
            return w
        if any(c.isupper() for c in w):
            return w                              # already cased: PLA, BRI
        if w.lower() in _TAG_ACRONYMS:
            return w.upper()                      # us -> US, uae -> UAE
        if (not lead) and w.lower() in _TAG_LOWER:
            return w.lower()                      # particle mid-tag
        return w[0].upper() + w[1:]

    out, first = [], True
    for tok in str(text or '').split(' '):
        if not tok:
            continue
        if tok == '\u00d7':
            out.append(tok)
            continue
        # Hyphenated names are cased part-by-part so "bab el-mandeb" does not
        # become "Bab El-mandeb"; the particle rule applies inside the hyphen too.
        if '-' in tok:
            parts = tok.split('-')
            out.append('-'.join(_case_word(p, first and i == 0)
                                for i, p in enumerate(parts)))
        else:
            out.append(_case_word(tok, first))
        first = False
    return ' '.join(out)

# Never used as the headline: these describe the ABSENCE of a finding.
_NON_CONVERGENCE = {'global_baseline', 'global_warning', 'global_commodity_oil',
                    'global_commodity_gold', 'global_commodity_wheat'}


def _compound_tag(narr):
    """Short compound tag for one narrative. Two nouns and a multiplication sign."""
    cat = (narr or {}).get('category') or ''
    regions = [r for r in ((narr or {}).get('regions') or []) if r]

    # DYNAMIC TAGS. Categories whose second term depends on live data cannot be
    # a fixed string -- naming the REGION is both correct and more useful than
    # naming a count, and it cannot go stale.
    if cat == 'nuclear_signaling_global':
        if len(regions) == 1:
            return _titlecase_tag('Nuclear Signaling \u00d7 %s'
                                  % (_TAG_REGION_NAMES.get(regions[0])
                                     or _REGION_DISPLAY.get(regions[0], regions[0])))
        if len(regions) > 1:
            return 'Nuclear Signaling \u00d7 %d Theatres' % len(regions)
        return 'Nuclear Signaling'

    tag = CONVERGENCE_TAGS.get(cat)
    if tag:
        return tag
    # Generic fallback: pair the two regions it spans, which is at least a
    # relationship rather than a label.
    regions = [r for r in ((narr or {}).get('regions') or []) if r]
    if len(regions) >= 2:
        # _TAG_REGION_NAMES first: _REGION_DISPLAY carries prose forms like
        # "the Middle East" that read badly inside a two-noun tag.
        def _rn(r):
            return _TAG_REGION_NAMES.get(r) or _REGION_DISPLAY.get(r, r)
        return _titlecase_tag('%s \u00d7 %s' % (_rn(regions[0]), _rn(regions[1])))
    return _titlecase_tag(cat.replace('_', ' ')) if cat else ''


def _breach_line(full):
    """Level-6 red-line breach, or None. Displaces the level when present."""
    best = None
    for sig in (full.get('_all_signals_raw') or []) + (full.get('top_signals') or []):
        try:
            if int(sig.get('level') or 0) < 6:
                continue
        except Exception:
            continue
        if best is None or int(sig.get('priority') or 0) > int(best.get('priority') or 0):
            best = sig
    if not best:
        return None
    theatre = (best.get('theatre') or '').replace('_', ' ').title()
    txt = (best.get('short_text') or '')
    # Strip the leading flag+country prefix so the detail line does not repeat
    # the theatre name already shown beside the level.
    if ':' in txt:
        txt = txt.split(':', 1)[1].strip()
    # Landing-page text must stay TIGHT -- this line sits under a button, not in
    # a report. Red-line labels are written as "A / B" alternatives ("Attack on
    # US Embassy / Diplomatic Facility"), and the first alternative is always the
    # sharper, more concrete one. Take it and drop the rest.
    if ' / ' in txt:
        txt = txt.split(' / ', 1)[0].strip()
    # Same for dash appendages ("Mogadishu Penetration -- the state-survival
    # threshold"): the clause after the dash is usually explanation, not headline.
    #
    # BUT NOT ALWAYS. "IRAN: BREACH -- Operation True Promise" puts the generic
    # word first and the substance second, and blindly taking the left half
    # rendered the whole line as "BREACH". So keep the left side only when it
    # actually says something; otherwise take the right.
    _MIN_USEFUL = 14
    for _sep in (' -- ', ' \u2014 ', ' \u2013 '):
        if _sep in txt:
            _left, _right = [x.strip() for x in txt.split(_sep, 1)]
            txt = _left if len(_left) >= _MIN_USEFUL else (_right or _left)
    return {
        'level': 6,
        'label': L6_LABEL,
        'theatre': theatre or 'Global',
        'detail': txt[:90],
        'category': best.get('category'),
    }


def _banner(full):
    """What the landing page shows. L6 breach displaces the level; otherwise
    the level plus the leading convergence tag."""
    # v3.13.0 -- a CONFIRMED L6 event (held 7 days) leads, even after the
    # originating signal has scrolled out of the regional feeds.
    _l6 = full.get('l6') or {}
    if _l6.get('active') and _l6.get('events'):
        e = sorted(_l6['events'], key=lambda x: x.get('confirmed_at', ''))[-1]
        return {'mode': 'breach', 'level': 6, 'label': L6_LABEL,
                'theatre': str(e.get('theatre') or 'Global').replace('_', ' ').title(),
                'detail': (e.get('class_label') or '')[:90],
                'category': e.get('class'), 'day': e.get('day')}
    breach = _breach_line(full)
    if breach:
        return {'mode': 'breach', **breach}

    narrs = [n for n in (full.get('narratives') or [])
             if (n.get('category') or '') not in _NON_CONVERGENCE
             and n.get('tier') != 'standing']        # v3.12.0
    narrs.sort(key=lambda n: -int(n.get('priority') or 0))
    lead = narrs[0] if narrs else None
    return {
        'mode':     'level',
        'level':    full.get('global_level', 0),
        'label':    full.get('global_label', ''),
        'tag':      _compound_tag(lead) if lead else '',
        'category': (lead or {}).get('category', ''),
        'axis':     (lead or {}).get('pressure_type')
                    or CATEGORY_AXIS_HINTS.get((lead or {}).get('category') or '')
                    or PRESSURE_KINETIC,
    }

def _headline_signal(full):
    """The single most useful line for a first-time visitor.

    NOT the level -- the level has been pinned at L5 by sustained global
    conflict, so it carries no information and trains readers to stop looking.
    What moves is WHICH theatre leads and WHAT it is doing.
    """
    sigs = full.get('top_signals') or []
    if not sigs:
        return None
    top = sigs[0]
    theatre = (top.get('theatre') or '').replace('_', ' ').title()
    lvl = top.get('level')
    # pressure_type is what stops an earthquake reading as a war.
    axis = top.get('pressure_type')
    state = _theatre_state(lvl, top.get('category'), axis)
    return {
        'theatre':  theatre or 'Global',
        'level':    lvl,
        'state':    state,
        'category': top.get('category'),
        'axis':     (axis or CATEGORY_AXIS_HINTS.get(top.get('category') or '')
                     or PRESSURE_KINETIC),
        # "Iran -- active war footing" rather than "IRAN L5".
        'line':     (f'{theatre}: {state}' if theatre else state),
        'full_text': top.get('short_text') or '',
    }


def _motion_line(full):
    """One sentence about what CHANGED. Motion is the reason to click.

    Reads the delta engine rather than recomputing -- gpi_delta.py already
    tracks appeared / resolved / escalated with streaks, and it carries the
    doctrine guard that refuses to call a thin archive a 30-day comparison.
    """
    d = full.get('delta') or {}
    if not d or d.get('available') is False:
        return None
    esc = len(d.get('escalated') or [])
    app = len(d.get('appeared') or [])
    res = len(d.get('resolved') or [])
    if not (esc or app or res):
        return {'text': 'No signal changed band since the last comparison.',
                'escalated': 0, 'appeared': 0, 'resolved': 0, 'quiet': True}
    bits = []
    if esc: bits.append(f'{esc} escalated')
    if app: bits.append(f'{app} newly appeared')
    if res: bits.append(f'{res} resolved')
    window = d.get('window_days')
    tail = f' in the last {window} days' if window else ''
    return {'text': ' \u00b7 '.join(bits) + tail,
            'escalated': esc, 'appeared': app, 'resolved': res, 'quiet': False}


# Pre-dedupe signal snapshot, written by _build_global_top_signals each build
# and read by the tagging audit. Diagnostic only -- nothing analytical reads it.
_LAST_RAW_SIGNALS = []

# Cache
GPI_VERSION     = '3.16.0'   # v3.12.0 -- payload 'version' reads this (was a literal '3.0.0')
GPI_CACHE_KEY   = 'gpi:global:latest'
GPI_CACHE_TTL   = 12 * 3600   # 12h
LEVEL_CACHE_KEY = 'gpi:level:latest'
LEVEL_CACHE_TTL = 12 * 3600

# Synthesis tuning
# ══════════════════════════════════════════════════════════════════════
# NARRATIVE DECAY ENGINE  (v3.7.0, Jul 25 2026)
# ══════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════
# GLOBAL CONVERGENCE PANEL  (spoke & wheel at GPI altitude)
# ══════════════════════════════════════════════════════════════════════
# Every regional BLUF reads the hubs resident in ITS region. The GPI is the
# only altitude that reads them ALL AT ONCE -- which is where the question
# "are several hubs activating their networks simultaneously?" can finally be
# asked. A single hub converging is a regional finding; three converging in
# the same cycle is a global one, and nothing below this layer can see it.
#
# Hubs are DISCOVERED, not listed: whatever the keyspace contains gets read,
# so a hub that comes online later appears with no edit here.
def _build_global_convergence_panel():
    """Read every discoverable wheel. Never raises."""
    if not _WHEEL_READER:
        return None
    try:
        hubs = [h['hub'] for h in _discover_hubs()]
        if not hubs:
            return None
        panel = _build_wheel_panel(
            resident_hubs=hubs,
            local_countries=[],      # emanating is a REGIONAL read, not a global one
            region='global',
        )
        wheels = panel.get('resident_wheels', []) or []
        converged = [w for w in wheels if w.get('converged')]
        panel['converged_hubs'] = [w.get('hub') for w in converged]
        panel['converged_count'] = len(converged)
        panel['wheels_tracked'] = len(wheels)
        panel['total_lit'] = sum(int(w.get('lit_count', 0) or 0) for w in wheels)
        if len(converged) >= 2:
            names = ', '.join(str(w.get('hub', '')).title() for w in converged)
            panel['global_headline'] = (
                '%d hubs are converging simultaneously (%s). Multiple networks '
                'activating in the same cycle is a different read from any one '
                'of them doing so alone -- it is the pattern that regional '
                'altitude cannot see.' % (len(converged), names))
        elif len(converged) == 1:
            panel['global_headline'] = (
                'One hub converging (%s). A single wheel activating is a '
                'regional finding; it rides up on its own merits.'
                % str(converged[0].get('hub', '')).title())
        else:
            panel['global_headline'] = ''
        panel['subtitle'] = ('%d wheels tracked \u00b7 %d spokes lit'
                             % (len(wheels), panel['total_lit']))
        return panel
    except Exception as e:
        print(f"[GPI] Convergence panel failed (non-fatal): {str(e)[:140]}")
        return None


# ══════════════════════════════════════════════════════════════════════
# HUB NETWORK BREADTH  (Slice 2, Aug 2026)
# ══════════════════════════════════════════════════════════════════════
# THE GATING DOCTRINE THIS IMPLEMENTS:
#
#   Kinetic activity rides up on INTENSITY. Russia-Ukraine shelling reaches
#   GPI altitude because the event is the signal; it keeps the +11 kinetic
#   boost and this module never touches it.
#
#   Sub-kinetic INFLUENCE activity rides up on BREADTH. Africa Corps in Mali
#   is a Mali headline and an Africa BLUF headline on its own merits. Whether
#   it deserves GLOBAL altitude depends on whether the same hub shows up in
#   more places -- and there are two independent ways to qualify:
#
#     DEPTH  Mali + Somalia + CAR        several countries, one region
#     SPAN   Mali + Cuba + Poland        several regions
#
#   Either can carry it. Both together is the strongest read on the platform,
#   because it is simultaneously a regional campaign AND a global one.
#
# This is the generalisation of _narrative_iran_axis_convergence, which
# implemented exactly this logic hardcoded to Iran's proxy theatres ("GATE:
# breadth, not depth. Fires when >=3 proxies active"). Every hub now gets it.
#
# PRIORITY STAYS BELOW THE +11 KINETIC BOOST -- deliberately, and for the same
# reason the Iran detector does: an influence convergence must surface as a
# prominent narrative without inflating the kinetic-weighted global level.
# Mixing those axes would let a diplomatic pattern masquerade as escalation.

HUB_BREADTH_DEPTH_GATE = 3   # lit spokes inside ONE region
HUB_BREADTH_SPAN_GATE  = 3   # distinct regions with >=1 lit spoke

_HUB_ACRONYMS = {'us': 'US', 'uae': 'UAE', 'drc': 'DRC',
                 'car': 'CAR', 'dprk': 'DPRK', 'uk': 'UK'}

# Readable node_class labels. The registry keys are snake_case machine tokens;
# these are what a reader should actually see in prose.
_NODE_CLASS_LABEL = {
    'adversary': 'adversary', 'friction': 'friction',
    'aligned_multiplier': 'aligned multiplier',
    'expeditionary_client': 'expeditionary client',
    'resource_client': 'resource client', 'pacific_client': 'Pacific client',
    'bri_corridor': 'BRI corridor', 'ruptured': 'ruptured node',
    'inbound_target': 'inbound-pressure target',
    'axis_reversal_watch': 'axis-reversal watch',
    'normalisation_track': 'normalisation track',
    'recognition_wildcard': 'recognition wildcard',
    'cold_peace': 'cold peace', 'guarantor_ally': 'treaty ally',
    'security_assistance': 'security assistance',
    'hemispheric_adversary': 'hemispheric adversary',
    'hemispheric_partner': 'hemispheric partner',
    'fragile_state': 'fragile state', 'turkic_affinity': 'Turkic affinity',
    'proliferation_peer': 'proliferation peer',
    'proliferation_client': 'proliferation client',
    'expeditionary_supplier': 'expeditionary supplier',
    'proxy': 'proxy', 'mediation': 'mediation track', 'patron': 'patron',
    'client': 'client', 'peer': 'peer', 'unclassified': 'unclassified',
}


def _hub_label(h):
    """Hub name for prose. .title() turns 'us' into 'Us' -- this does not."""
    k = str(h or '').lower().replace('-', '_')
    return _HUB_ACRONYMS.get(k, k.replace('_', ' ').title())


def _nc_label(nc):
    k = str(nc or 'unclassified').lower()
    return _NODE_CLASS_LABEL.get(k, k.replace('_', ' '))


def _serial(items, conj='and'):
    """A / A and B / A, B and C -- never 'A and B and C'."""
    items = [str(i) for i in items if i]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return '%s %s %s' % (items[0], conj, items[1])
    return '%s %s %s' % (', '.join(items[:-1]), conj, items[-1])


_REGION_DISPLAY = {'africa': 'Africa', 'europe': 'Europe',
                   'middle_east': 'the Middle East',
                   'asia_pacific': 'Asia-Pacific',
                   'wha': 'the Western Hemisphere',
                   'unmapped': 'unmapped theatres'}

_PANEL_MEMO = {'ts': None, 'panel': None}


def _get_convergence_panel():
    """Memoised panel read. The payload and the breadth detector both need it,
    and a wheel read scans the keyspace -- doing that twice per request would
    double the Redis work for an identical answer."""
    now = datetime.now(timezone.utc)
    ts = _PANEL_MEMO.get('ts')
    if _PANEL_MEMO.get('panel') is not None and ts is not None:
        if (now - ts).total_seconds() < 60:
            return _PANEL_MEMO['panel']
    panel = _build_global_convergence_panel()
    _PANEL_MEMO['ts'] = now
    _PANEL_MEMO['panel'] = panel
    return panel


def _narrative_hub_network_breadth(blufs):
    """Hub influence measured by REACH rather than intensity.

    Returns a LIST (one narrative per qualifying hub) or None.

    Absence-honest throughout: a hub whose spokes are largely not reporting
    is reported with its coverage gap named, because breadth measured over a
    partial rim UNDERSTATES reach -- and a gate that fires on understated
    breadth would be silently conservative in a way no reader could see.

    Peers are already excluded upstream by spoke_wheel_reader._breadth:
    Iran/China/DPRK on the Russia wheel are wheel-to-wheel, and counting them
    would read hub-to-hub contact as a regional campaign.
    """
    panel = _get_convergence_panel()
    if not panel:
        return None
    by_hub = panel.get('breadth_by_hub') or {}
    if not by_hub:
        return None

    out = []
    for hub, b in sorted(by_hub.items()):
        depth = _decay_int(b.get('depth'), 0)
        span  = _decay_int(b.get('span'), 0)
        deep  = depth >= HUB_BREADTH_DEPTH_GATE
        wide  = span  >= HUB_BREADTH_SPAN_GATE
        if not (deep or wide):
            continue

        hub_name    = _hub_label(hub)
        regions_lit = b.get('regions_lit') or {}
        nc_mix      = b.get('node_class_mix') or {}
        lit_detail  = b.get('lit_detail') or {}
        depth_region = _REGION_DISPLAY.get(b.get('depth_region', ''),
                                           b.get('depth_region', ''))
        region_names = [_REGION_DISPLAY.get(r, r) for r in sorted(regions_lit)]

        # Denominators travel with the claim. Breadth is otherwise confounded
        # with build history -- a hub with 21 instrumented spokes will always
        # out-score one with 8, and a bare tally would report the roadmap as
        # a finding about the world.
        lit_total    = _decay_int(b.get('lit_count'), 0)
        reporting    = _decay_int(b.get('reporting_total'), 0)
        instrumented = _decay_int(b.get('instrumented_total'), 0)

        # Name the CHARACTER of the reach, not just its size. The two largest
        # node-class groupings say more than the spoke count does.
        top_mix = list(nc_mix.items())[:2]
        mix_phrase = _serial(['%d %s' % (len(v), _nc_label(k)) for k, v in top_mix])

        if deep and wide:
            headline = ('%s is lit on %d spokes across %d regions, with %d in %s alone'
                        % (hub_name, lit_total, span, depth, depth_region))
        elif wide:
            headline = ('%s is lit across %d regions simultaneously (%s)'
                        % (hub_name, span, _serial(region_names)))
        else:
            headline = ('%s is lit on %d spokes concentrated in %s'
                        % (hub_name, depth, depth_region))
        if mix_phrase:
            headline += ' — mostly %s' % mix_phrase

        detail = ('Influence read, not a kinetic one. %s registers %d lit spokes of %d '
                  'reporting (%d instrumented). '
                  % (hub_name, lit_total, reporting, instrumented))
        # Per region, name each spoke WITH its relationship class and level, so
        # a reader can tell an adversary rim from a client rim at a glance.
        for r in sorted(regions_lit):
            entries = lit_detail.get(r) or []
            if entries:
                _rd = _REGION_DISPLAY.get(r, r)
                _rd = _rd[0].upper() + _rd[1:]   # sentence-initial: "The Western Hemisphere"
                detail += ('%s — %s. ' % (
                    _rd,
                    _serial(['%s (%s, %s)' % (d['name'], _nc_label(d.get('node_class')),
                                              _ts_level(_decay_int(d.get('level'), 0)))
                             for d in entries])))
            else:
                detail += ('%s: %s. ' % (_REGION_DISPLAY.get(r, r),
                                         _serial(regions_lit[r])))

        if nc_mix:
            detail += ('Relationship mix across the lit rim: %s. This is what KIND of reach '
                       'the count describes -- a rim lit on adversaries reads differently '
                       'from one lit on resource clients or corridor states, and a spoke '
                       'total alone cannot distinguish them. '
                       % _serial(['%s (%s)' % (_nc_label(k), _serial(v))
                                  for k, v in list(nc_mix.items())[:4]]))

        if deep and wide:
            detail += ('This clears both breadth tests at once: several countries inside '
                       'a single region AND presence across separated regions. Those are '
                       'different findings -- a regional campaign and a global one -- and '
                       'their co-occurrence is the strongest reach signal the platform '
                       'measures. ')
        elif wide:
            detail += ('Separated regions lighting in the same cycle is the read no '
                       'regional BLUF can reach on its own; each would see one spoke and '
                       'correctly decline to generalise from it. ')
        else:
            detail += ('Concentration inside one region is a REGIONAL campaign read, not '
                       'a global one. It is surfaced here because the count exceeds what '
                       'single-country noise produces, not because reach is global. ')

        detail += ('Spoke levels reflect rhetoric and influence signals, so this narrative '
                   'is ranked BELOW kinetic escalation by design -- reach is not the same '
                   'thing as force, and the global level should not move as though it were. ')

        cov = b.get('coverage_note') or ''
        if cov:
            detail += cov + ' '
        detail += ('This composite is a CONVERGENCE indicator, NOT a probability of '
                   'action; each spoke is independently sourced and the reader completes '
                   'the inference.')

        out.append({
            'priority': 10 if (deep and wide) else 9,   # below the +11 kinetic boost
            'category': 'hub_network_breadth',
            'regions':  sorted(regions_lit) or ['global'],
            'icon':     '\U0001f578',    # web -- a rim, not a flag
            'color':    '#7c3aed',
            'headline': headline,
            'detail':   detail,
        })
    return out or None


_POLICY_BRANCH_KEY = 'israel:policy_branch:state'

_BRANCH_LABEL = {
    'negotiated':               'negotiated framework',
    'occupation':               'permanent security presence',
    'palestinian_governance':   'Palestinian governance',
    'permanent_administration': 'permanent administration',
    'incremental_annexation':   'incremental annexation',
    'unresolved':               'unresolved',
}
_THEATRE_LABEL = {'lebanon': 'Lebanon', 'gaza': 'Gaza', 'west_bank': 'the West Bank'}


def _narrative_policy_branch_convergence(blufs):
    """Do Lebanon, Gaza and the West Bank branch the same way at once?

    THE FRAMING: safety on Israel's northern border is a given for any Israeli
    government. HOW it is reached -- negotiated agreement versus occupation and
    annexation -- is the branch, and the same fork exists in all three theatres.

    NO SINGLE THEATRE'S BRANCH IS A POLICY FINDING. Each has a local
    explanation and each regional BLUF sees only its own. Two or more leaning
    the same way in the same cycle is a different object -- and it is a read
    regional altitude structurally cannot reach, because Lebanon is read on ME,
    the West Bank inside Israel, and Gaza across both.

    Ranked BELOW the +11 kinetic boost: a policy lean is not force.
    """
    st = _redis_get(_POLICY_BRANCH_KEY) or {}
    if not st:
        return None

    branches = st.get('branches') or {}
    hard = st.get('hard_branch_theatres') or []
    soft = st.get('soft_branch_theatres') or []
    read = st.get('theatres_read') or []

    # Two is the minimum that separates a pattern from a coincidence. One
    # theatre branching is always locally explicable and is not reported here.
    if len(hard) < 2 and len(soft) < 2:
        return None

    lean_side = 'hard' if len(hard) >= len(soft) else 'soft'
    group = hard if lean_side == 'hard' else soft
    names = _serial([_THEATRE_LABEL.get(t, t.replace('_', ' ').title()) for t in group])

    headline = ('%s branching toward %s outcomes simultaneously'
                % (names, 'unilateral' if lean_side == 'hard' else 'negotiated'))

    detail = ('Israeli policy in each of these theatres faces the same fork: the security '
              'objective is not in question, but the METHOD is -- negotiated agreement on one '
              'side, unilateral consolidation on the other. ')
    for t in read:
        b = branches.get(t) or {}
        detail += ('%s reads as %s (%s). '
                   % (_THEATRE_LABEL.get(t, t),
                      _BRANCH_LABEL.get(b.get('lean'), 'unresolved'),
                      (b.get('basis') or 'no basis recorded')[:90]))

    detail += ('%d of %d instrumented theatres lean the same way this cycle. The finding is '
               'the SIMULTANEITY -- a single theatre branching is locally explicable and is '
               'not reported here. It is also a read no regional BLUF can reach: Lebanon is '
               'read on the Middle East backend, the West Bank inside Israel, and Gaza across '
               'both, so only global altitude sees all three at once. '
               % (len(group), len(read)))

    # Freeze qualifier: during a decision freeze a lean is inertia, not choice.
    fz = {}
    try:
        from framework_gates import read_freeze_state
        fz = read_freeze_state() or {}
    except Exception:
        pass
    if fz.get('freeze'):
        detail += ('AN ISRAELI DECISION FREEZE IS IN EFFECT (electoral stage: %s). A lean '
                   'observed during a freeze reflects existing policy continuing by default '
                   'rather than a decision to pursue it: unilateral measures proceed '
                   'administratively while negotiated ones require a government able to sign. '
                   'That asymmetry is STRUCTURAL and must not be read as intent. '
                   % fz.get('state'))
    elif fz.get('known'):
        detail += ('No Israeli decision freeze is in effect, so this lean is not explained by '
                   'an absent counterparty. ')

    detail += ('This composite is a CONVERGENCE indicator, NOT a probability of action; each '
               'theatre is independently sourced and the reader completes the inference.')

    return {
        'priority': 10 if len(group) >= 3 else 9,
        'category': 'policy_branch_convergence',
        'regions': ['me'],
        'icon': '\U0001f500',
        'color': '#9333ea',
        'headline': headline,
        'detail': detail,
    }


_FORMATION_KEY = 'israel:government_formation'
_CROSSTHEATER_KEY = 'rhetoric:crosstheater:fingerprints'


def _narrative_israel_formation_window(blufs):
    """Israel without a formed government WHILE the Iran axis is hot.

    THE UNASKED QUESTION at global altitude: not "who will govern Israel" --
    the Israel rhetoric page tracks that path by path -- but "who takes the
    next big decision on the Iran war, and under what constraints?" A
    caretaker government keeps full war-making authority but operates under a
    restraint doctrine for NEW business (negotiated tracks, normalization,
    new frameworks). So during a formation window the asymmetry is
    structural: kinetic decisions remain available, negotiated ones are
    parked. No regional BLUF frames it this way, because the formation read
    lives on Israel's page and the Iran-axis read lives in the cross-theater
    fingerprints.

    Fires only when BOTH hold: a formation window is open (voted/formation)
    AND an Iran-axis theatre reads L3+. Ranked below the +11 kinetic boost:
    this is a constraint read, not force.
    """
    gf = _redis_get(_FORMATION_KEY) or {}
    if not gf.get('active') or gf.get('cycle_state') not in ('voted', 'formation'):
        return None
    fp = _redis_get(_CROSSTHEATER_KEY) or {}

    def _lv(t):
        try:
            return int((fp.get(t) or {}).get('level', 0) or 0)
        except Exception:
            return 0

    axis = {'Iran': _lv('iran'), 'Lebanon': _lv('lebanon'), 'Yemen': _lv('yemen'),
            'Iraq': _lv('iraq'), 'Syria': _lv('syria')}
    hot = {k: v for k, v in axis.items() if v >= 3}
    if not hot:
        return None

    names = gf.get('path_names') or {}
    lead = gf.get('leading_paths') or []
    lead_txt = (_serial([names.get(p, 'Path %s' % p) for p in lead])
                if lead else 'no formation path yet carrying firsthand coverage')
    hot_txt = _serial(['%s L%d' % (k, v) for k, v in sorted(hot.items(), key=lambda kv: -kv[1])])

    headline = ('Israel in caretaker formation while %s' % hot_txt)
    detail = ('Israel has no sworn-in government (%s; seats %s). Coverage of formation: %s. '
              % (str(gf.get('headline') or 'formation window open').rstrip('. '),
                 str(gf.get('results_status', 'unavailable')).lower(), lead_txt))
    detail += ('Meanwhile the Iran axis reads %s. The caretaker government retains full war-making '
               'authority, but operates under a restraint doctrine for NEW business, so the '
               'asymmetry is structural: kinetic decisions remain available while negotiated tracks '
               '(the Lebanon framework, any Syria or Saudi track) are parked until a government can '
               'sign. That is a constraint on method, not a statement of intent. ' % hot_txt)
    if gf.get('decision_freeze'):
        detail += 'The Israeli decision freeze is ON this cycle. '
    detail += ('Formation length therefore shapes which cabinet takes the next major Iran-axis '
               'decision. This composite is a CONVERGENCE indicator, NOT a probability of action.')

    return {
        'priority': 9,
        'category': 'israel_formation_window',
        'regions': ['me'],
        'icon': '\U0001f3db',
        'color': '#a78bfa',
        'pressure_type': 'diplomatic',
        'headline': headline,
        'detail': detail,
    }


def _narrative_emplacement_precursor(blufs):
    """The emplacement-precursor convergence, read from two tempo baselines.

    THE PATTERN, reconstructed from Abu al-Duhur (18 Aug 2026):
      1. dormant-facility reactivation      (weeks ahead, OSINT-visible)
      2. technical delegation               ("training and exchange of expertise")
      3. capability naming                  (radar, air-defence, troops)
      4. rival restates a SITE-SPECIFIC red line, invoking a security status quo
      5. emplacing hub DENIES, concurrently with 4

    Stages 4 and 5 running together is the configuration that preceded action --
    and the action struck the runway, not personnel: the infrastructure was
    destroyed before capability could arrive.

    TWO TARGETS, TWO MODES, DELIBERATELY:
      turkey  mode='tape'   emplacement / denial / redline
      israel  mode='actor'  redline (site-specific) / strike_claim / deconfliction
    Turkey denies, so there is no claiming actor to fall silent. Israel claims,
    so its silence is readable. Reading either in the other's mode produces
    confident nonsense.

    OUTPUT IS A TASKING TRIGGER, NOT A FORECAST. This layer cannot see what an
    intelligence service knows. It can say two independent curves are rising
    together and name what to go and ask.
    """
    try:
        from tempo_baseline import read_baseline
    except ImportError:
        return None

    try:
        tk = read_baseline('turkey') or {}
        il = read_baseline('israel') or {}
    except Exception as e:
        print(f'[GPI] emplacement precursor read failed (non-fatal): {str(e)[:120]}')
        return None

    # ABSENCE-HONEST: a baseline still accumulating is reported as such and the
    # detector stays silent. It never estimates a deviation it cannot support.
    if not (tk.get('ready') and il.get('ready')):
        return None

    def _dev(bl, stream):
        """Short-window tempo against long-window norm: mean_7d / mean_30d.

        NOT a single-day spike. compute_baseline() writes mean_7d, mean_30d,
        stdev, max and days per stream -- there is no per-day 'current' in the
        payload, and using the 7d mean is the better read anyway: one loud news
        cycle should not read as a tempo shift, whereas a week sustained above
        the monthly norm is exactly what tempo means.

        Returns None when the long-window mean is too small to divide by --
        a stream that barely fires cannot produce a meaningful ratio, and
        inventing one would manufacture signal from noise.
        """
        base = (bl.get('baselines') or {}).get(stream) or {}
        m30 = base.get('mean_30d') or 0
        m7 = base.get('mean_7d')
        if m7 is None or float(m30) < 1.0:
            return None
        return round(float(m7) / float(m30), 2)

    empl = _dev(tk, 'emplacement')
    deny = _dev(tk, 'denial')
    rline = _dev(il, 'redline')          # site-specific stream, NOT the general one

    if rline is None or (empl is None and deny is None):
        return None

    # The gate. A site-specific red line restated above baseline while the
    # emplacing hub's denial or emplacement tempo is also above baseline.
    REDLINE_GATE, COUNTERPART_GATE = 1.5, 1.5
    counterpart = max([v for v in (empl, deny) if v is not None] or [0])
    if rline < REDLINE_GATE or counterpart < COUNTERPART_GATE:
        return None

    both = (empl or 0) >= COUNTERPART_GATE and (deny or 0) >= COUNTERPART_GATE

    headline = ('Emplacement-precursor configuration: Israeli site-specific red-line tempo '
                'and Turkish %s tempo are both above baseline'
                % ('emplacement and denial' if both else
                   ('emplacement' if (empl or 0) >= (deny or 0) else 'denial')))

    detail = ('Israeli site-specific red-line tempo is running at %.1fx its 30-day norm over the past week. '
              % rline)
    if empl is not None:
        detail += 'Turkish emplacement tempo (facility work, delegations, capability naming) is at %.1fx. ' % empl
    if deny is not None:
        detail += 'Turkish denial tempo is at %.1fx. ' % deny

    detail += ('These are two independently sourced corpora on two different backends -- '
               'Turkey is gathered by Europe, Israel by the Middle East -- so neither '
               'regional BLUF sees both curves. ')

    detail += ('The pattern this matches: a rival restating a red line about a NAMED SITE '
               'while the emplacing hub flatly denies the activity. That configuration '
               'preceded the 18 August 2026 strike on Abu al-Duhur, where the runway was '
               'struck rather than personnel -- the infrastructure destroyed before the '
               'capability it was being prepared to receive could arrive. General deterrent '
               'language is excluded from this read; Israel restates broad red lines about '
               'Syria constantly and that is baseline, not signal. ')

    # Corpus honesty. Surge reads survive a degraded corpus -- a spike detected
    # despite fewer sources is MORE notable, not less -- but the reader is told.
    for lbl, bl in (('Turkish', tk), ('Israeli', il)):
        if bl.get('corpus_warning'):
            detail += ('%s corpus note: %s ' % (lbl, bl['corpus_warning']))

    detail += ('COLLECTION PROMPT -- this is a cue to task, not a forecast, and the honest '
               'limit of an open-source layer is that it cannot see what an intelligence '
               'service knows. Worth establishing directly: which specific site is at issue; '
               'whether physical preparation is under way there (runway or facility works, '
               'technical delegations, radar or air-defence emplacement); whether the host '
               'government has granted or is weighing consent; and how far apart the two '
               'sides\' accounts now are. A widening gap between a restated warning and a '
               'flat denial has historically closed through unilateral action against the '
               'infrastructure rather than negotiation over it. ')

    detail += ('This composite is a CONVERGENCE indicator, NOT a probability of action; '
               'each stream is independently sourced and the reader completes the inference.')

    return {
        'priority': 10 if both else 9,   # below the +11 kinetic boost
        'category': 'emplacement_precursor',
        'regions':  ['me', 'europe'],
        'icon':     '\U0001f6a7',
        'color':    '#b45309',
        'headline': headline,
        'detail':   detail,
    }


def _narrative_contested_spoke(blufs):
    """Two or more hubs lit on the SAME country in the same cycle.

    Orthogonal to hub_network_breadth: that measures one hub reaching wide,
    this measures several hubs pressing on one node. Abu al-Duhur (Aug 18
    2026) is the reference case -- Turkey and Israel both lit on Syria, with
    Turkey read on the Europe backend and Syria/Israel on ME, so no regional
    BLUF could see the collision. The GPI is the only altitude that can.

    OUTPUT IS A TASKING TRIGGER, NOT A FORECAST. A contested node says the
    collection question has changed, not that anything will happen. The
    narrative therefore ends by naming what an analyst should go and ask --
    which is the honest limit of an OSINT layer that cannot see intelligence.

    Ranked below the +11 kinetic boost: contestation is an influence read.
    """
    panel = _get_convergence_panel()
    if not panel:
        return None
    contested = panel.get('contested_spokes') or []
    if not contested:
        return None

    out = []
    for c in contested[:3]:          # top 3 by hub count then level
        hubs = c.get('hub_names') or []
        if len(hubs) < 2:
            continue
        disp = c.get('display') or c.get('country')
        hub_names = [_hub_label(h) for h in hubs]
        max_level = _decay_int(c.get('max_level'), 0)
        c_region = _REGION_DISPLAY.get(c.get('region', ''), c.get('region', ''))

        # Lead with the relationship classes -- "contested" is the finding, but
        # WHICH KIND of interest each hub holds is the analytically useful part.
        _nc = _serial(['%s as %s' % (_hub_label(h.get('hub')),
                                     _nc_label(h.get('node_class')))
                       for h in (c.get('hubs') or [])])
        headline = ('%s is contested: %s wheels lit simultaneously — %s'
                    % (disp, _serial(hub_names), _nc))

        detail = ('%d hubs register %s on their rim in the same cycle -- '
                  % (len(hubs), disp))
        detail += '; '.join(
            '%s at %s as %s%s' % (_hub_label(h.get('hub')),
                                  _ts_level(_decay_int(h.get('level'), 0)),
                                   _nc_label(h.get('node_class')),
                                   (' — "%s"' % h['top_signal'][:100]) if h.get('top_signal') else '')
            for h in (c.get('hubs') or []))
        detail += '. '

        rel = c.get('mutual_classification') or {}
        if rel:
            detail += ('These hubs classify each other in the platform registry as: %s. '
                       % _serial(['%s reads %s as %s'
                                   % (_hub_label(k.split('_reads_')[0]),
                                      _hub_label(k.split('_reads_')[1]), _nc_label(v))
                                   for k, v in sorted(rel.items())]))
        else:
            detail += ('Neither hub carries a classification of the other in the registry, '
                       'so whether this contest is rivalrous or cooperative is UNRESOLVED '
                       'here rather than assumed. ')

        if c.get('cross_region'):
            detail += ('The contesting hubs are not all resident in %s, so no single '
                       'regional BLUF reads both sides of this: each sees one hub pressing '
                       'and correctly declines to generalise. The collision is visible only '
                       'at global altitude. ' % c_region)

        detail += ('Two hubs on one node is a different finding from one hub across many '
                   'nodes. It does not by itself indicate escalation -- hubs can press the '
                   'same node cooperatively -- but it does mean the node is carrying '
                   'competing external interests at once. ')

        # The tasking trigger -- the actual product of this narrative. Roles are
        # NOT assigned: which hub is placing capability and which is objecting
        # cannot be read from a rim level, and asserting it backwards would be
        # worse than leaving it open. Which is which is part of the question.
        detail += ('COLLECTION PROMPT -- this is a cue to task, not a forecast. Four things '
                   'worth establishing directly about %s, none of which this layer can see: '
                   '(1) whether either of %s is placing or preparing to place physical '
                   'capability there -- facility rehabilitation, technical delegations, '
                   'radar or air-defence emplacement; (2) whether the host government has '
                   'granted or is weighing consent for it; (3) whether either hub has '
                   'restated a red line naming a specific site rather than the country in '
                   'general; and (4) whether one hub is denying activity the other is '
                   'asserting. A restated, site-specific red line running concurrently with '
                   'a flat denial is the configuration that has historically preceded '
                   'unilateral action against the emplacement rather than against the '
                   'personnel -- the infrastructure is struck before it can be used. '
                   % (disp, _serial(hub_names, 'or')))

        detail += ('This composite is a CONVERGENCE indicator, NOT a probability of '
                   'action; each wheel is independently sourced and the reader completes '
                   'the inference.')

        out.append({
            'priority': 10 if (len(hubs) >= 3 or max_level >= 4) else 9,
            'category': 'contested_spoke',
            'regions':  sorted({c.get('region', 'global')} | set(c.get('hub_regions') or [])),
            'icon':     '\u2694\uFE0F',
            'color':    '#0891b2',
            'headline': headline,
            'detail':   detail,
        })
    return out or None


def _decay_int(v, default=0):
    """Local int coercion -- this module has _safe_level but no generic int
    helper, and priority is not a 0-5 level so _safe_level would clamp it."""
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except Exception:
        return default


# ── Shared spoke-and-wheel reader (v1.0.6, Jul 25 2026) ──────────────
try:
    from spoke_wheel_reader import (build_convergence_panel as _build_wheel_panel,
                                    discover_hubs as _discover_hubs)
    _WHEEL_READER = True
except ImportError:
    _WHEEL_READER = False
    print("[GPI] spoke_wheel_reader not available -- convergence panel disabled")


DECAY_STATE_KEY = 'gpi:narrative_decay'
DECAY_STATE_TTL = 45 * 24 * 3600      # 45d -- long enough to span a slow crisis

# Scans run ~2x/day. Grace is generous on purpose: a real crisis should never
# be decayed for having a quiet Tuesday.
DECAY_GRACE_CYCLES = 6                # ~3 days at 12h cadence -- no penalty
DECAY_STEPS = (                       # (unchanged_cycles_at_or_above, penalty)
    (45, 6),                          # ~3+ weeks static -- yields the headline
    (30, 4),                          # ~2+ weeks static
    (16, 3),                          # ~1-2 weeks
    (10, 2),                          # ~5 days
    (7,  1),                          # ~3.5 days
)
DECAY_PRIORITY_FLOOR = 5              # never decay below this -- still visible
DECAY_RESOLUTION_BONUS = 1            # extra penalty once a level has FALLEN
DECAY_MIN_CYCLE_HOURS = 11            # v3.12.0 -- forced rebuilds do not count as cycles


def _decay_fingerprint(sig):
    """Stable identity for a signal across scans.

    Category + theatre + the opening of the long text. Deliberately NOT the
    full text: prose that re-renders with a refreshed figure each cycle would
    otherwise look like a brand-new signal forever and never decay.
    """
    try:
        cat = str(sig.get('category', '') or '').lower()
        th = str(sig.get('theatre', sig.get('region', '')) or '').lower()
        txt = str(sig.get('long_text') or sig.get('short_text') or '').lower()
        txt = ''.join(c for c in txt if c.isalnum() or c == ' ')[:70]
        return f'{cat}|{th}|{txt}'
    except Exception:
        return ''


def _apply_narrative_decay(signals):
    """Lower the priority of signals that have stopped moving.

    Reads/writes one Redis key holding {fingerprint: {level, cycles, first_seen}}.
    Absence-honest: if Redis is unreachable the signals pass through untouched
    rather than being silently reordered on incomplete history.
    """
    if not signals:
        return signals
    try:
        state = _redis_get(DECAY_STATE_KEY)
        if not isinstance(state, dict):
            state = {}
    except Exception:
        return signals

    now_iso = datetime.now(timezone.utc).isoformat()
    seen, new_state = set(), {}

    for s in signals:
        fp = _decay_fingerprint(s)
        if not fp:
            continue
        seen.add(fp)
        lvl = _safe_level(s.get('level', 0))
        prev = state.get(fp) if isinstance(state.get(fp), dict) else None

        if prev is None:
            rec = {'level': lvl, 'cycles': 0, 'first_seen': now_iso, 'fell': False,
                   'counted_at': now_iso}
        else:
            prev_lvl = _safe_level(prev.get('level', 0))
            if lvl != prev_lvl:
                # It MOVED. Reset -- this is the mechanism that keeps genuine
                # crises out of decay without naming any of them.
                rec = {'level': lvl, 'cycles': 0,
                       'first_seen': prev.get('first_seen', now_iso),
                       'fell': bool(lvl < prev_lvl),
                       'counted_at': now_iso}
            else:
                # v3.12.0 -- a "cycle" is a scheduled scan, not a build. Every
                # ?force=true is also a build, and an afternoon of testing used
                # to be able to age a signal by a week. Count at most one cycle
                # per DECAY_MIN_CYCLE_HOURS; otherwise carry the count forward.
                _cnt = int(prev.get('cycles', 0))
                _last = prev.get('counted_at') or prev.get('first_seen') or now_iso
                try:
                    _hrs = (datetime.now(timezone.utc)
                            - datetime.fromisoformat(_last)).total_seconds() / 3600.0
                except Exception:
                    _hrs = DECAY_MIN_CYCLE_HOURS
                if _hrs >= DECAY_MIN_CYCLE_HOURS:
                    _cnt += 1
                    _last = now_iso
                rec = {'level': lvl,
                       'cycles': _cnt,
                       'first_seen': prev.get('first_seen', now_iso),
                       'fell': bool(prev.get('fell')),
                       'counted_at': _last}
        new_state[fp] = rec

        cycles = rec['cycles']
        penalty = 0
        if cycles >= DECAY_GRACE_CYCLES:
            for threshold, p in DECAY_STEPS:
                if cycles >= threshold:
                    penalty = p
                    break
            # A level that has FALLEN and then gone flat is a resolving
            # condition, not a developing one. Decay it a step faster.
            if rec['fell'] and penalty:
                penalty += DECAY_RESOLUTION_BONUS

        if penalty:
            orig = _decay_int(s.get('priority', 5), 5)
            s['priority'] = max(DECAY_PRIORITY_FLOOR, orig - penalty)
            s['_decay_cycles'] = cycles
            s['_decay_penalty'] = penalty
            s['_decay_note'] = (
                'Unchanged for %d scan cycles -- ranked below moving signals. '
                'Standing condition, not a developing one.' % cycles)

    # Carry forward records for signals absent this cycle so a signal that
    # blinks out for one scan does not reset its decay clock.
    # v3.12.0: ...but not forever. Now that decay actually runs, the key is
    # rewritten every build and its TTL never lapses, so a signal that left for
    # good would otherwise sit in state indefinitely. 30 days absent = gone.
    for fp, rec in state.items():
        if fp not in seen and isinstance(rec, dict):
            try:
                _age_d = (datetime.now(timezone.utc) - datetime.fromisoformat(
                    rec.get('counted_at') or rec.get('first_seen') or now_iso)).days
            except Exception:
                _age_d = 0
            if _age_d <= 30:
                new_state[fp] = rec

    try:
        _redis_set(DECAY_STATE_KEY, new_state, ttl=DECAY_STATE_TTL)
    except Exception:
        pass
    return signals


TOP_GLOBAL_SIGNALS_COUNT = 20   # v3.6.0 May 23 2026 — bumped from 15; gives axis-distribution headroom
                                # for Africa + Arctic + Phase 2 humanitarian (Ebola, displacement) signals
MIN_SIGNALS_PER_AXIS     = 2    # v3.6.0 May 23 2026 — axis distribution guard. After the top
                                # CORE_HEADLINE_COUNT slots fill by tier+priority, the remaining slots
                                # (up to TOP_GLOBAL_SIGNALS_COUNT) prefer underrepresented axes so the
                                # final 20 isn't all kinetic. Ensures economic/diplomatic/humanitarian
                                # axes get visible representation when their signals exist.
CORE_HEADLINE_COUNT      = 12   # v3.6.0 May 23 2026 — first N slots are pure tier+priority (no axis
                                # rebalancing). Protects the headline narrative integrity. Slots 13-20
                                # apply axis-distribution logic.
DIPLOMATIC_SURFACE_CAP   = 5    # Jun 14 2026 — de-escalation MUST surface. Up to 5 simultaneous
                                # diplomatic / de-escalation tracks (Lebanon, Ukraine, Iran-US, and
                                # any others) are guaranteed a slot and never gate-kept out by the
                                # per-region top-3 cut. Diplomatic signals are SCORE REDUCERS, so the
                                # escalation-weighted tier sort buries them; this guarantees they show.
DIPLOMATIC_SIGNAL_PHRASES = ('cessation of hostilities',)
                                # Jun 14 2026 — text phrases that flag a signal as diplomatic even when
                                # its category/source does not. Kept deliberately narrow: 'cessation of
                                # hostilities' is unambiguous de-escalation language. (We avoid bare
                                # 'ceasefire' here, since 'ceasefire collapsed' is ESCALATION; the
                                # 'ceasefire' CATEGORY is already handled by _CATEGORY_AXIS_HINTS.)
REGIONAL_FETCH_TIMEOUT   = 20   # seconds -- Jul 23 2026: was 8, too tight for
                                # BLUFs that make their own outbound calls during
                                # build (ME fetches the Lebanon humanitarian
                                # backend). GPI was abandoning ME mid-rebuild.

# ============================================================
# REDIS HELPERS
# ============================================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
        result = resp.json().get('result')
        return json.loads(result) if result else None
    except Exception as e:
        print(f'[GPI v2.0] Redis GET error ({key}): {e}')
        return None


def _redis_set(key, value, ttl=GPI_CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str)
        params = {'EX': ttl} if ttl else {}
        resp = requests.post(
            f'{UPSTASH_REDIS_URL}/set/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type':  'application/json'
            },
            data=payload,
            params=params,
            timeout=5
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f'[GPI v2.0] Redis SET error ({key}): {e}')
        return False


# ============================================================
# REGIONAL BLUF FETCHERS
# ============================================================
def _fetch_regional_bluf(region, url):
    """Fetch a regional BLUF endpoint with timeout + graceful failure."""
    try:
        resp = requests.get(url, timeout=REGIONAL_FETCH_TIMEOUT)
        if resp.status_code != 200:
            print(f'[GPI v2.0] {region} BLUF HTTP {resp.status_code}')
            return None
        data = resp.json()
        if not data.get('success', True):
            print(f'[GPI v2.0] {region} BLUF returned success=false')
            return None
        return data
    except Exception as e:
        print(f'[GPI v2.0] {region} BLUF fetch error: {str(e)[:120]}')
        return None


def _fetch_all_regional_blufs():
    """Fetch all 4 regional BLUFs. Returns dict keyed by region."""
    blufs = {}
    for region, url in REGIONAL_BLUF_ENDPOINTS.items():
        data = _fetch_regional_bluf(region, url)
        if data:
            blufs[region] = data
            lvl = data.get('max_level', data.get('peak_level', 0))
            print(f'[GPI v2.0] {region}: loaded (L{lvl}, posture={data.get("posture_label", "")[:30]})')
    return blufs


# ============================================================
# SAFE-ACCESS HELPERS
# ============================================================
def _signals_of(bluf):
    """
    Get the full signal pool from a BLUF dict.

    v2.3.0 — Prefer `signals[]` (full pool) over `top_signals[]` (capped at 5).
    This matters for axis aggregation: if BLUF emits 8 signals but only the top 5
    make it into `top_signals[]`, axis cards reading the capped list miss any
    signal that got bumped (e.g. diplomatic at priority 10 bumped by 5 kinetic
    at priority 12-14). Reading `signals[]` first preserves axis-quota correctness.

    Falls back to `top_signals[]` for older BLUFs that don't emit `signals[]`.
    """
    if not bluf:
        return []
    return bluf.get('signals') or bluf.get('top_signals') or []


# ============================================================
# DEFENSIVE LEVEL COERCION (v2.1)
# ============================================================
# Signal `level` can arrive as either:
#   - numeric tier 0-5 (rhetoric trackers — canonical)
#   - string status label (commodity tracker: 'surge', 'elevated', etc.)
#   - None / missing
# This helper normalizes everything to a numeric tier 0-5.

_LEVEL_LABEL_MAP = {
    'surge': 5, 'critical': 5, 'crisis': 5,
    'high': 4, 'incident': 4,   # v3.x (Jun 18 2026): 'high' was MISSING -> coerced to 0
    'elevated': 3, 'heightened': 3, 'warning': 3, 'alert': 3,
    'active': 2, 'rising': 2, 'tensions': 2,
    'normal': 1, 'stable': 1, 'baseline': 1,
    'low': 0, 'monitoring': 0, 'none': 0,
}


def _safe_level(value, default=0):
    """Coerce signal level to integer tier (0-5), tolerating string labels."""
    if value is None:
        return default
    if isinstance(value, bool):  # bool is subclass of int — guard before int check
        return int(value)
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (ValueError, TypeError, OverflowError):
            return default
    if isinstance(value, str):
        v = value.strip().lower()
        if not v:
            return default
        # First try direct int parse (e.g. "3" or "5")
        try:
            return int(v)
        except ValueError:
            pass
        # ── v3.11.0 (Oct 6 2026) -- THE CANON TAKES OVER THE STRING PATH ──
        # _LEVEL_LABEL_MAP was one flat table coercing ANY word to a tier, so it
        # read a rhetoric band word with commodity-ladder generosity: a vector a
        # tracker merely called 'elevated' landed at L3, the same rung as a
        # measured commodity concentration. That is how L5 stopped meaning much.
        #
        # severity_canon routes the word through a declared instrument instead.
        # Rachel's Oct 6 ruling: the rhetoric reading wins on the overlapping
        # words, which moves eleven of eighteen labels DOWN, deliberately, so
        # that L5 and the rare L6 keep their weight.
        #
        # An unrecognised word no longer becomes `default` silently -- it is
        # counted and reported once per cycle by _canon_miss_report(). A missing
        # key is how 'high' read as 0 until Jun 18 2026.
        lvl = _canon_level(v)
        if lvl is not None:
            return lvl
        _CANON_MISSES[v] = _CANON_MISSES.get(v, 0) + 1
        return _LEVEL_LABEL_MAP.get(v, default)
    return default


# Words no ladder recognised this cycle, with how often each arrived. Reported
# rather than swallowed: the whole point of the canon is that a word nobody
# declared should be loud, not quiet.
_CANON_MISSES = {}
# Words that resolved, but where more than one instrument knows them and they
# disagree -- i.e. the platform guessed. Counting these is how we find out
# whether the guess is rare or routine.
_CANON_GUESSES = {}


def _canon_level(word, ladder=None):
    """Platform level for a status word via severity_canon. None when unknown.

    `ladder` should be passed by any caller that KNOWS which instrument produced
    the word -- a commodity reading is not a rhetoric band and must not be
    resolved by preference order. Callers that genuinely cannot know leave it
    None and the guess is recorded.
    """
    try:
        import severity_canon as _canon
    except ImportError:
        return None          # canon not deployed here yet -- old path stands
    try:
        if ladder:
            return _canon.to_platform(ladder, word)
        lvl, used, ambiguous = _canon.resolve(word)
        if ambiguous:
            _CANON_GUESSES[word] = _CANON_GUESSES.get(word, 0) + 1
        return lvl
    except Exception:
        return None


def _canon_miss_report():
    """One line per cycle. Absence-honest: prints even when clean, so silence
    in the log means 'checked and found none', not 'never ran'."""
    if _CANON_MISSES:
        print('[GPI] severity canon: %d word(s) no ladder recognises -- %s'
              % (len(_CANON_MISSES),
                 ', '.join('%s x%d' % (w, n)
                           for w, n in sorted(_CANON_MISSES.items(),
                                              key=lambda kv: -kv[1])[:8])))
    else:
        print('[GPI] severity canon: every status word resolved to a declared ladder')
    if _CANON_GUESSES:
        print('[GPI] severity canon: %d word(s) known to more than one instrument, '
              'resolved by preference order -- %s'
              % (len(_CANON_GUESSES),
                 ', '.join('%s x%d' % (w, n)
                           for w, n in sorted(_CANON_GUESSES.items(),
                                              key=lambda kv: -kv[1])[:8])))
    _CANON_MISSES.clear()
    _CANON_GUESSES.clear()


def _level_of(bluf):
    """Get max/peak level from a BLUF."""
    if not bluf:
        return 0
    return _safe_level(bluf.get('max_level', bluf.get('peak_level', 0)), default=0)


# ============================================================
# PRESSURE AXES (v2.2) — multi-dimensional pressure model
# ============================================================
# A signal can carry pressure on one of 4 orthogonal axes:
#   • kinetic      — strikes, mobilization, casualties, ultimatums (rhetoric trackers)
#   • economic     — commodity surges, currency stress, sanctions, supply chain
#   • diplomatic   — ceasefire arithmetic, mediation tempo, alliance reshuffling
#   • humanitarian — displacement flows, civilian harm, famine, refugee surges
#
# v2.2 design choice: HEADLINE level = kinetic max (preserves operator semantics:
# "L5 = active conflict"). Other axes surface in a sorted stack BENEATH the headline,
# so a quiet kinetic / hot economic regime reads as "L0 Monitoring · L5 📈 Economic".
#
# Backwards compat: signals without `pressure_type` default to 'kinetic'. Existing
# rhetoric trackers need no change. Commodity / diplomatic / humanitarian signals
# get tagged at the GPI ingestion layer (see _tag_pressure_type_at_ingest below)
# until their source modules can be migrated to emit pressure_type natively.

PRESSURE_KINETIC      = 'kinetic'
PRESSURE_ECONOMIC     = 'economic'

# ── Multi-axis tagging for narratives (Slice 3, Jun 13 2026) ──
# A narrative is often genuinely multi-axis: the market-fragility x Taiwan read
# is BOTH economic and kinetic by nature. This central map declares each
# narrative category's full axis set (primary first). The front-end renders one
# end-pill per axis. Single-axis or unlisted narratives fall back to their
# 'pressure_type' (or kinetic default). Keep primary axis first -- it drives the
# pressure_type used by the economic/kinetic axis aggregation.
NARRATIVE_AXIS_SETS = {
    'market_fragility_semis_compound': ['economic', 'kinetic'],
    'market_fragility':                ['economic'],
    'dual_chokepoint':                 ['kinetic', 'economic'],   # chokepoint = mil + supply shock
    'russia_iran_axis':                ['kinetic', 'economic'],   # coordination + sanctions evasion
    'food_stress_convergence':         ['economic', 'humanitarian'],
    'food_stress_gated':               ['economic'],
    'wheat_lebanon':                   ['economic', 'humanitarian'],
    'belt_and_road_resource_leverage': ['economic', 'diplomatic'],
    'nuclear_signaling_global':        ['kinetic'],
    'china_taiwan_takeover':           ['kinetic'],
    'scs_first_island_chain_axis':     ['kinetic', 'diplomatic'],
    'iran_strike_window':              ['kinetic'],
    'dprk_russia_axis':                ['kinetic', 'economic'],
    'arctic_convergence':              ['kinetic', 'diplomatic'],
    'wha_cascade':                     ['humanitarian', 'economic'],
    'houthi_fragility':                ['kinetic', 'economic'],
    'multiaxis_convergence':           ['kinetic', 'economic'],   # by definition cross-axis
    'turkey_regional_convergence':     ['kinetic', 'diplomatic'], # projection (hard-power) + alignment/mediation
    'iran_axis_convergence':           ['kinetic', 'economic', 'diplomatic'], # proxy arena + chokepoint/oil + mediation counterweight
    # Influence reach, NOT force. Diplomatic leads deliberately: a hub lit
    # across regions is an alignment/pressure finding, and listing kinetic
    # first would let reach render as escalation on the kinetic axis.
    'hub_network_breadth':             ['diplomatic', 'kinetic'],
    # Contestation is an alignment/pressure finding first. Kinetic is listed
    # because a contested node is where force gets used -- but second, so a
    # contest never renders as escalation on its own.
    'contested_spoke':                 ['diplomatic', 'kinetic'],
    # A precursor read, not an escalation read. Diplomatic first so a rising
    # warning/denial tempo never renders as force having been used.
    'emplacement_precursor':           ['diplomatic', 'kinetic'],
    # A method finding, not a force finding. Diplomatic leads so a policy lean
    # never renders as escalation on the kinetic axis.
    'policy_branch_convergence':       ['diplomatic', 'kinetic'],
    # v3.12.0 -- governance leads: the finding is WHO can decide in Jerusalem,
    # not a negotiation between states. Kinetic second because the Iran axis
    # is the reason it matters this week.
    'israel_formation_window':         ['governance', 'kinetic'],
}

def _axes_for_narrative(n):
    """Return the ordered axis list for a narrative dict. Priority:
    explicit category map > explicit pressure_type > kinetic default."""
    cat = n.get('category', '')
    if cat in NARRATIVE_AXIS_SETS:
        return list(NARRATIVE_AXIS_SETS[cat])
    # v3.15.0 -- a registry entry may declare its own axes; without this a
    # registry narrative with no row above defaulted to KINETIC.
    if isinstance(n.get('axes'), (list, tuple)) and n['axes']:
        return [a for a in n['axes'] if a in PRESSURE_AXES] or ['kinetic']
    pt = n.get('pressure_type')
    if pt and pt in PRESSURE_AXES:
        return [pt]
    return ['kinetic']
PRESSURE_DIPLOMATIC   = 'diplomatic'
PRESSURE_HUMANITARIAN = 'humanitarian'
PRESSURE_GOVERNANCE   = 'governance'   # v3.12.0 -- 5th axis

PRESSURE_AXES = (
    PRESSURE_KINETIC,
    PRESSURE_ECONOMIC,
    PRESSURE_DIPLOMATIC,
    PRESSURE_HUMANITARIAN,
    PRESSURE_GOVERNANCE,
)

# ── GOVERNANCE CATEGORIES (v3.12.0, Oct 28 2026) ──────────────────────
# Substrings matched against signal['category']. These OVERRIDE an explicit
# pressure_type, deliberately and only for this set: the Israel interpreter
# (and the ME BLUF axis map) tag government_formation as 'diplomatic' because
# there was no governance axis when they were written. Re-tagging here means
# the GPI is correct today without a coordinated fleet-wide migration; the
# sources can move to pressure_type='governance' whenever they are next touched,
# and nothing here needs to change when they do.
#
# Kept narrow on purpose. 'regime', 'protest' and 'unrest' are NOT here: a
# crackdown is kinetic and a protest wave can be humanitarian -- the category
# has to say WHO GOVERNS for it to belong on this axis.
GOVERNANCE_CATEGORY_HINTS = (
    'government_formation', 'formation_window', 'caretaker', 'election',
    'succession', 'coup', 'junta', 'legitimacy', 'governance',
    'no_confidence', 'parliament_dissolution', 'leadership_transition',
    'transition_of_power', 'constitutional_crisis',
)


def _axis_level_label(axis, level):
    """Chip word for an axis level, from THAT axis's own ladder.

    v3.14.0 (Oct 29 2026) -- every non-kinetic axis, not just governance. The
    humanitarian tab read "L5 · ACTIVE CONFLICT" over a Category-1 typhoon and
    three UNHCR statistics: the kinetic chip word on a non-kinetic axis, which
    is exactly what the L5 assertion rule (Oct 6) forbids. Kinetic keeps the
    canonical chip ladder."""
    if axis and axis != PRESSURE_KINETIC and axis in THEATRE_STATE:
        return _theatre_state(level, None, axis).upper()
    return GLOBAL_LEVEL_LABELS.get(level, '')


def _is_governance_signal(signal):
    """WHOLE-TOKEN match on the category, never substring. v3.12.0 shipped a
    substring test and 'commodity_coupling' matched 'coup' -- five commodity
    signals filed as governance on the first live build. '_coup_' must appear
    between token boundaries: coup, coup_attempt, sahel_coup -- not coupling."""
    cat = str((signal or {}).get('category') or '').lower()
    if not cat:
        return False
    cat = '_' + re.sub(r'[^a-z0-9]+', '_', cat).strip('_') + '_'
    return any(('_' + h + '_') in cat for h in GOVERNANCE_CATEGORY_HINTS)

PRESSURE_AXIS_META = {
    PRESSURE_KINETIC: {
        'label': 'Kinetic',
        'icon':  '⚔️',
        'color': '#dc2626',  # red — conflict
        'description': 'Strikes, mobilization, ultimatums, casualties.',
    },
    PRESSURE_ECONOMIC: {
        'label': 'Economic',
        'icon':  '📈',
        'color': '#f59e0b',  # amber — financial/commodity
        'description': 'Commodity surges, currency stress, sanctions, supply chain.',
    },
    PRESSURE_DIPLOMATIC: {
        'label': 'Diplomatic',
        'icon':  '🕊️',
        'color': '#0ea5e9',  # cyan — mediation tracks
        'description': 'Ceasefire arithmetic, mediation tempo, alliance shifts.',
    },
    PRESSURE_HUMANITARIAN: {
        'label': 'Humanitarian',
        'icon':  '🆘',
        'color': '#a855f7',  # purple — civilian/displacement
        'description': 'Displacement flows, civilian harm, famine, refugee surges.',
    },
    PRESSURE_GOVERNANCE: {
        'label': 'Governance',
        'icon':  '🏛️',
        'color': '#14b8a6',  # teal -- distinct from diplomatic cyan and humanitarian purple
        'description': 'Elections, caretaker periods, successions, coups, legitimacy contests.',
    },
}


# ── Inline tagging at GPI ingestion ──
# Phase 1 strategy: rather than modifying every source module, we infer a signal's
# pressure_type at the GPI ingestion layer using its category and source labels.
# This lets us roll out the multi-axis architecture WITHOUT a fleet-wide migration.
# As source modules are migrated to emit pressure_type natively, the inferred value
# will simply be overridden by the explicit one (we always trust an explicit value).

# Categories that map to specific axes when no explicit pressure_type is set.
# Keys are substrings checked against signal['category'] (case-insensitive).
_CATEGORY_AXIS_HINTS = {
    # Economic — commodity tracker emits these
    'commodity':         PRESSURE_ECONOMIC,
    'wheat':             PRESSURE_ECONOMIC,
    'oil':               PRESSURE_ECONOMIC,
    'gas':               PRESSURE_ECONOMIC,
    'energy':            PRESSURE_ECONOMIC,
    'currency':          PRESSURE_ECONOMIC,
    'sanction':          PRESSURE_ECONOMIC,
    'inflation':         PRESSURE_ECONOMIC,
    'supply_chain':      PRESSURE_ECONOMIC,
    'economic':          PRESSURE_ECONOMIC,
    'financial':         PRESSURE_ECONOMIC,
    'eurobond':          PRESSURE_ECONOMIC,

    # Diplomatic — diplomatic-track architecture emits these
    'diplomatic':        PRESSURE_DIPLOMATIC,
    'ceasefire':         PRESSURE_DIPLOMATIC,
    'mediation':         PRESSURE_DIPLOMATIC,
    'negotiation':       PRESSURE_DIPLOMATIC,
    'envoy':             PRESSURE_DIPLOMATIC,
    'witkoff':           PRESSURE_DIPLOMATIC,
    'salalah':           PRESSURE_DIPLOMATIC,
    'de_escalation':     PRESSURE_DIPLOMATIC,
    'off_ramp':          PRESSURE_DIPLOMATIC,   # Jun 14 2026 — ME diplomatic-track emits 'off_ramp_active'
    'green_line':        PRESSURE_DIPLOMATIC,

    # Humanitarian — migration model + humanitarian signal categories
    'humanitarian':      PRESSURE_HUMANITARIAN,
    'displacement':      PRESSURE_HUMANITARIAN,
    'refugee':           PRESSURE_HUMANITARIAN,
    'migration':         PRESSURE_HUMANITARIAN,
    'famine':            PRESSURE_HUMANITARIAN,
    'civilian_harm':     PRESSURE_HUMANITARIAN,
    'casualties':        PRESSURE_HUMANITARIAN,
    'idp':               PRESSURE_HUMANITARIAN,
    # v3.6 (May 23 2026) — Africa humanitarian scaffolding.
    # Disease outbreaks (Ebola, Marburg, cholera, mpox) are a canonical Africa
    # humanitarian signal class. When rhetoric_tracker_sudan.py + africa_regional_bluf.py
    # ship in Phase 2, they will emit signals with these category substrings; they will
    # automatically route into the Humanitarian axis without further GPI changes.
    'ebola':             PRESSURE_HUMANITARIAN,
    'marburg':           PRESSURE_HUMANITARIAN,
    'cholera':           PRESSURE_HUMANITARIAN,
    'mpox':              PRESSURE_HUMANITARIAN,
    'monkeypox':         PRESSURE_HUMANITARIAN,
    'outbreak':          PRESSURE_HUMANITARIAN,    # generic disease outbreak
    'disease':           PRESSURE_HUMANITARIAN,
    'epidemic':          PRESSURE_HUMANITARIAN,
    'pandemic':          PRESSURE_HUMANITARIAN,
    'who_emergency':     PRESSURE_HUMANITARIAN,    # WHO PHEIC declarations
    'health_emergency':  PRESSURE_HUMANITARIAN,
    # v3.6 — Africa-specific humanitarian signal categories (Phase 2 scaffolding)
    'sudan_conflict':    PRESSURE_HUMANITARIAN,    # Sudan RSF/SAF conflict + Darfur famine
    'tigray':            PRESSURE_HUMANITARIAN,    # Ethiopia Tigray humanitarian residue
    'sahel_displacement':PRESSURE_HUMANITARIAN,    # Mali/Burkina/Niger coup-belt displacement
    'kivu_displacement': PRESSURE_HUMANITARIAN,    # Eastern DRC M23/ADF/FDLR displacement
    'lake_chad':         PRESSURE_HUMANITARIAN,    # Boko Haram + climate-driven Chad basin crisis
    'food_security':     PRESSURE_HUMANITARIAN,    # IPC Phase 3+ classifications
}


def _infer_pressure_type(signal):
    """
    Determine pressure_type for a signal.
    Priority:
      1. Explicit signal['pressure_type'] (from migrated sources) — trusted.
      2. signal['category'] keyword match against _CATEGORY_AXIS_HINTS.
      3. Source-label fallbacks (commodity_tracker, commodity_proxy, etc.)
      4. Default: 'kinetic' (rhetoric trackers — current canonical).
    """
    # 0. v3.12.0 -- governance categories override (see GOVERNANCE_CATEGORY_HINTS).
    if _is_governance_signal(signal):
        return PRESSURE_GOVERNANCE

    # 1. Explicit pressure_type wins
    explicit = signal.get('pressure_type')
    if explicit and explicit in PRESSURE_AXES:
        return explicit

    # 2. Category keyword match
    category = (signal.get('category') or '').lower()
    if category:
        for hint, axis in _CATEGORY_AXIS_HINTS.items():
            if hint in category:
                return axis

    # 2b. Diplomatic phrase match (text) -- catches de-escalation language that
    # arrives WITHOUT a diplomatic category, e.g. 'cessation of hostilities'.
    _text = ((signal.get('short_text') or '') + ' '
             + (signal.get('long_text') or '') + ' '
             + (signal.get('text') or '')).lower()
    if _text and any(p in _text for p in DIPLOMATIC_SIGNAL_PHRASES):
        return PRESSURE_DIPLOMATIC

    # 3. Source-label fallbacks (for signals that come without a category)
    source = (signal.get('source') or '').lower()
    if 'commodity' in source or 'wheat' in source or 'oil' in source:
        return PRESSURE_ECONOMIC
    if 'diplomatic' in source or 'mediation' in source or 'envoy' in source:
        return PRESSURE_DIPLOMATIC
    if 'humanitarian' in source or 'displacement' in source or 'migration' in source:
        return PRESSURE_HUMANITARIAN

    # 4. Default: kinetic (rhetoric trackers)
    return PRESSURE_KINETIC


def _tag_pressure_axes(signals):
    """Tag every signal with pressure_type if not already set. Returns list with
    each signal augmented with `pressure_type` field. Idempotent."""
    tagged = []
    for s in signals or []:
        s2 = dict(s)  # shallow copy — don't mutate caller
        # v3.12.0: always resolve through _infer_pressure_type. It still trusts a
        # valid explicit value first, but it also applies the governance override,
        # which a "keep it if it's already set" check would skip.
        s2['pressure_type'] = _infer_pressure_type(s)
        tagged.append(s2)
    return tagged


# ============================================================
# AXIS MOTION  (v3.14.0, Oct 29 2026)
# ============================================================
# The index went to L4 SUSTAINED while Kinetic, Economic and Humanitarian each
# still read L5 -- correctly, because an axis level is SEVERITY (how bad is the
# worst reading on this axis) while the index level is MOTION (is the world
# getting worse this fortnight). Both are true; the page only showed one of
# them. Each axis now carries its own motion read:
#
#   new        something at the axis's top level appeared, or moved to that
#              level, within AXIS_MOTION_NEW_HOURS
#   sustained  every top-level reading has held longer than that
#   unread     no history to judge (Redis unreadable) -- said, not guessed
#
# Identity is category|theatre|country|LEVEL, never the prose: figures in the
# text refresh every scan and would make everything look new forever. A level
# change IS motion, so it is part of the key.
#
# Kinetic uses the L5 novelty gate's per-theatre onsets when the gate ran, so
# the kinetic tab and the index can never disagree about whether a front is new.
#
# DAY ZERO: readings present on the first run are seeded as sustained
# ("pre-dates tracking"), the same rule the L5 gate uses -- otherwise every axis
# would shout NEW for three days after deploy.
AXIS_MOTION_KEY        = 'gpi:axis_motion'
AXIS_MOTION_TTL        = 60 * 24 * 3600
AXIS_MOTION_NEW_HOURS  = 72
AXIS_MOTION_FORGET_DAYS = 14
_AXIS_MOTION_STATE = {'loaded': False, 'ok': False, 'data': None, 'dirty': False, 'first_run': False}


def _axis_motion_fp(sig):
    return '|'.join(str(sig.get(k) or '').lower() for k in ('category', 'theatre', 'country')) \
        + '|L%d' % _safe_level(sig.get('level', 0))


def _axis_motion_load():
    st = _AXIS_MOTION_STATE
    if not st['loaded']:
        data, ok = _redis_get_checked(AXIS_MOTION_KEY)
        st.update(loaded=True, ok=ok,
                  first_run=bool(ok and not isinstance(data, dict)),
                  data=(data if isinstance(data, dict) else ({} if ok else None)))
    return st


def _axis_motion(axis, axis_level, axis_signals):
    """Return {'motion','label','note','new'} for one axis."""
    if axis_level <= 0:
        return {'motion': 'quiet', 'label': '', 'note': '', 'new': []}
    gate = _LAST_LEVEL_GATE or {}
    # A confirmed L6 Global Shock is new escalation by definition.
    if axis == PRESSURE_KINETIC and (_LAST_L6 or {}).get('active'):
        _ev = sorted((_LAST_L6.get('events') or []), key=lambda e: e.get('confirmed_at', ''))
        _lbl = (_ev[-1].get('class_label') if _ev else '') or 'Global shock'
        return {'motion': 'new', 'label': 'new',
                'note': '%s -- confirmed world-altering event (L6 hold).' % _lbl,
                'new': [_lbl]}
    if axis == PRESSURE_KINETIC and axis_level >= 5 and gate.get('available', True) and (
            gate.get('fresh') or gate.get('sustained')):
        fresh = gate.get('fresh') or []
        if fresh:
            return {'motion': 'new', 'label': 'new',
                    'note': 'New L5 front within %d days: %s.' % (
                        L5_NOVELTY_DAYS, ', '.join(e['display'] for e in fresh)),
                    'new': [e['display'] for e in fresh]}
        return {'motion': 'sustained', 'label': 'sustained',
                'note': 'Every L5 front has held more than %d days -- severe, but nothing new '
                        'added.' % L5_NOVELTY_DAYS, 'new': []}

    st = _axis_motion_load()
    if not st['ok'] or st['data'] is None:
        return {'motion': 'unread', 'label': 'motion unread',
                'note': 'Motion history unreadable this cycle -- severity shown without the '
                        'new/sustained distinction.', 'new': []}
    data = st['data']
    first_run = bool(st.get('first_run'))      # applies to EVERY axis on the seeding run
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    book = data.setdefault(axis, {})
    top = [s for s in axis_signals if _safe_level(s.get('level', 0)) == axis_level]
    new_items = []
    for s in top:
        fp = _axis_motion_fp(s)
        rec = book.get(fp)
        if rec is None:
            rec = {'first_seen': now_iso, 'seeded': first_run}
            book[fp] = rec
        rec['last_seen'] = now_iso
        if not rec.get('seeded'):
            try:
                hrs = (now - datetime.fromisoformat(rec['first_seen'])).total_seconds() / 3600.0
            except Exception:
                hrs = AXIS_MOTION_NEW_HOURS + 1
            if hrs < AXIS_MOTION_NEW_HOURS:
                new_items.append((s.get('short_text') or s.get('category') or '')[:90])
    for fp in list(book.keys()):
        try:
            if (now - datetime.fromisoformat(book[fp].get('last_seen', now_iso))).days > AXIS_MOTION_FORGET_DAYS:
                book.pop(fp, None)
        except Exception:
            book.pop(fp, None)
    st['dirty'] = True
    if new_items:
        return {'motion': 'new', 'label': 'new',
                'note': '%d reading%s reached L%d within %dh: %s' % (
                    len(new_items), '' if len(new_items) == 1 else 's', axis_level,
                    AXIS_MOTION_NEW_HOURS, '; '.join(new_items[:3])),
                'new': new_items[:5]}
    return {'motion': 'sustained', 'label': 'sustained',
            'note': 'Every L%d reading on this axis has held more than %dh -- %s, but not '
                    'new this cycle.' % (axis_level, AXIS_MOTION_NEW_HOURS,
                                         'severe' if axis_level >= 4 else 'standing'), 'new': []}


def _axis_motion_save():
    st = _AXIS_MOTION_STATE
    if st.get('dirty') and st.get('ok') and isinstance(st.get('data'), dict):
        _redis_set(AXIS_MOTION_KEY, st['data'], ttl=AXIS_MOTION_TTL)
    st.update(loaded=False, ok=False, data=None, dirty=False, first_run=False)


def _build_pressure_axes_payload(blufs, narratives):
    """
    Build the per-axis aggregation payload that the frontend will consume.

    For each axis, returns:
      - level     : max signal level on that axis across all regions (0-5)
      - label     : display label e.g. 'Kinetic'
      - icon      : emoji
      - color     : hex
      - top_signals : top 5 signals on this axis, sorted by level desc
      - region_levels : dict of {region: max_level_on_this_axis}
                        (for understanding WHERE the pressure is)

    Headline level is computed elsewhere (kinetic-weighted, see _compute_global_level).
    This payload is purely for the multi-axis stack display.
    """
    # Collect every signal from every BLUF, plus narrative-derived signals
    all_signals = []
    for region, bluf in (blufs or {}).items():
        if not bluf:
            continue
        for sig in _signals_of(bluf):
            sig_with_region = dict(sig)
            sig_with_region.setdefault('theatre', region)
            sig_with_region.setdefault('region', region)
            all_signals.append(sig_with_region)

    # Tag everything with pressure_type (inferred or explicit)
    all_signals = _tag_pressure_axes(all_signals)

    # Build per-axis aggregation
    axes = {}
    for axis in PRESSURE_AXES:
        axis_signals = [s for s in all_signals if s.get('pressure_type') == axis]

        # Per-region max level on this axis (lets frontend show "where")
        region_levels = {}
        for s in axis_signals:
            region = s.get('region') or s.get('theatre') or 'unknown'
            lvl = _safe_level(s.get('level', 0))
            if lvl > region_levels.get(region, -1):
                region_levels[region] = lvl

        # Overall axis level = max across regions
        axis_level = max(region_levels.values()) if region_levels else 0

        # Top 5 signals on this axis, sorted by level desc then priority desc
        top_axis_signals = sorted(
            axis_signals,
            key=lambda s: (
                _safe_level(s.get('level', 0)),
                _safe_level(s.get('priority', 0)),
            ),
            reverse=True,
        )[:5]

        # Strip internal sort fields before returning
        top_axis_signals_clean = []
        for s in top_axis_signals:
            top_axis_signals_clean.append({
                'category':      s.get('category', ''),
                'theatre':       s.get('theatre') or s.get('region', ''),
                'region':        s.get('region') or s.get('theatre', ''),
                'level':         _safe_level(s.get('level', 0)),
                'pressure_type': s.get('pressure_type'),
                'icon':          s.get('icon', PRESSURE_AXIS_META[axis]['icon']),
                'color':         s.get('color', PRESSURE_AXIS_META[axis]['color']),
                'short_text':    (s.get('short_text') or s.get('text') or '')[:120],
                'long_text':     s.get('long_text') or s.get('short_text') or s.get('text') or '',
            })

        meta = PRESSURE_AXIS_META[axis]
        try:
            _mo = _axis_motion(axis, axis_level, axis_signals)
        except Exception as _mo_err:
            _mo = {'motion': 'unread', 'label': 'motion unread',
                   'note': 'Motion read failed: %s' % str(_mo_err)[:80], 'new': []}
        axes[axis] = {
            # v3.14.0 -- severity (level) and motion, side by side.
            'motion':        _mo['motion'],
            'motion_label':  _mo['label'],
            'motion_note':   _mo['note'],
            'motion_new':    _mo['new'],
            'axis':          axis,
            'label':         meta['label'],
            'icon':          meta['icon'],
            'color':         meta['color'],
            'description':   meta['description'],
            'level':         axis_level,
            'level_label':   _axis_level_label(axis, axis_level),
            'region_levels': region_levels,
            'signal_count':  len(axis_signals),
            'top_signals':   top_axis_signals_clean,
        }

    # Build a sorted stack ordering — highest-level axis first.
    # Tiebreaker: PRESSURE_AXES order (kinetic > economic > diplomatic > humanitarian)
    axis_order = sorted(
        PRESSURE_AXES,
        key=lambda a: (-axes[a]['level'], PRESSURE_AXES.index(a)),
    )

    return {
        'axes':            axes,           # full data, keyed by axis name
        'axes_ordered':    axis_order,     # sorted axis names, highest first
        'kinetic_level':   axes[PRESSURE_KINETIC]['level'],   # convenience accessor
        'headline_axis':   PRESSURE_KINETIC,                  # current headline driver
    }


def _has_signal_category(bluf, *categories):
    """True if any signal in this BLUF matches one of the given categories."""
    sigs = _signals_of(bluf)
    cats = set(categories)
    return any(s.get('category') in cats for s in sigs)


def _signals_in_category(bluf, *categories):
    """All signals matching any of the given categories."""
    sigs = _signals_of(bluf)
    cats = set(categories)
    return [s for s in sigs if s.get('category') in cats]


def _max_signal_level(bluf, *categories):
    """Max level among signals in given categories. Returns 0 if none."""
    sigs = _signals_in_category(bluf, *categories)
    if not sigs:
        return 0
    return max(_safe_level(s.get('level', 0)) for s in sigs)


# ============================================================
# NARRATIVE DETECTORS
# ============================================================
# Each detector reads the full blufs dict and returns a Narrative or None.
# Narratives have priority (higher = bigger story); top narratives drive the BLUF.
#
# Narrative shape:
#   {
#     'priority':     0-15,
#     'category':     'short_id',
#     'regions':      ['me', 'asia', ...],
#     'icon':         '🚨',
#     'color':        '#dc2626',
#     'headline':     'China rising — signals point to Taiwan takeover days away',
#     'detail':       'Longer paragraph for full BLUF expansion',
#   }


def _narrative_china_taiwan_takeover(blufs):
    """China L4+ + Taiwan kinetic signals → takeover narrative."""
    asia = blufs.get('asia')
    if not asia:
        return None
    asia_level = _level_of(asia)
    has_china_high = _has_signal_category(asia, 'theatre_high') and asia_level >= 4
    has_kinetic    = _has_signal_category(asia, 'kinetic_pressure', 'red_line_breached')
    has_deterrence = _has_signal_category(asia, 'deterrence_gap')
    if has_china_high and (has_kinetic or has_deterrence):
        return {
            'priority': 14,
            'category': 'china_taiwan_takeover',
            'regions':  ['asia'],
            'icon':     '\U0001f1e8\U0001f1f3',  # 🇨🇳
            'color':    '#dc2626',
            'headline': 'China at coercion threshold -- Taiwan kinetic signaling at incident level',
            'detail':   ('Asia-Pacific theater: People\'s Liberation Army (PLA) tempo plus Taiwan '
                         'deterrence-gap signals indicate the highest-stakes window in years for a '
                         'Taiwan Strait contingency. Watch for Air Defense Identification Zone (ADIZ) '
                         'violation surges, Taiwan Ministry of National Defense (MND) brevity-language '
                         'shifts, and US-Japan-Taiwan coalition signaling cadence.')   # static prose: no fixed window,
        }
    return None


def _narrative_scs_first_island_chain_axis(blufs):
    """South China Sea / first-island-chain convergence (Jun 2026).

    Fires when China pressure draws in the southern SCS claimant (Vietnam)
    alongside the cross-strait flashpoint (Taiwan). Reads the Asia BLUF's
    theatre_summary levels PLUS Vietnam's SCS red-line and two-front convergence
    signal categories, so it catches whichever downstream gate (butterfly
    two-front pressure or interpreter SCS convergence) surfaces in the Asia
    rollup -- no dependence on a single gate.

    Convergence framing, NOT prediction: reports that pressure is distributed
    across the arc, not that any single front will go kinetic.
    """
    asia = blufs.get('asia')
    if not asia:
        return None

    ts = asia.get('theatre_summary') or {}
    def _lvl(name):
        d = ts.get(name) or {}
        return _safe_level(d.get('threat_level', d.get('level', 0)))
    cn = _lvl('china')
    tw = _lvl('taiwan')
    vn = _lvl('vietnam')

    # Vietnam SCS activity can arrive as a signal even while its headline level is
    # modest (e.g. the two-front convergence read from Taiwan's fingerprint).
    vn_scs_signal = _has_signal_category(
        asia,
        'china_two_front_convergence',   # Beijing pressuring Taiwan AND Vietnam
        'sovereignty_erosion',           # CCG / survey / oil-gas incursion
        'kinetic_threshold',             # ramming / feature militarization
        'china_direct',                  # nine-dash enforcement, direct coercion
    )
    vn_scs_active = (vn >= 3) or vn_scs_signal

    # China is the driver; the axis is fundamentally about Vietnam being drawn in
    # alongside China pressure, so Vietnam must be genuinely SCS-active.
    if not (cn >= 3 and vn_scs_active):
        return None
    all_three = (tw >= 3)

    named = ['China']
    if tw >= 3:
        named.append('Taiwan')
    named.append('Vietnam')
    vn_note = ' + active SCS convergence signal' if (vn < 3 and vn_scs_signal) else ''

    if all_three:
        priority = 13
        headline = ('South China Sea axis -- simultaneous pressure across China, Taiwan, '
                    'and Vietnam along the first island chain')
    else:
        priority = 11
        headline = ('South China Sea axis forming -- pressure spans '
                    + ' + '.join(named) + ' in the same window')

    detail = (
        'Asia-Pacific maritime theater: pressure is distributed across the South China Sea / '
        'first-island-chain arc rather than concentrated on the Taiwan Strait alone. China is the '
        'driver (L' + str(cn) + '); Taiwan is the cross-strait flashpoint (L' + str(tw) + '); '
        'Vietnam is the southern claimant (L' + str(vn) + vn_note + '). A multi-front maritime '
        'posture stretches US and allied response capacity across separated theaters at once -- the '
        'combination is what compounds risk beyond any single chokepoint. Watch China Coast Guard / '
        'maritime-militia tempo around Vietnamese hydrocarbon blocks, ADIZ activity, and '
        'US / Japan / Philippines / India coalition signaling. This is a CONVERGENCE indicator, '
        'NOT a probability of action -- it reports that pressure spans the arc, not that any front '
        'will go kinetic.'
    )
    return {
        'priority': priority,
        'category': 'scs_first_island_chain_axis',
        'regions':  ['asia'],
        'icon':     '\U0001f30a',  # ocean wave
        'color':    '#f97316',
        'headline': headline,
        'detail':   detail,
    }


def _narrative_russia_iran_axis(blufs):
    """Russia + Iran cross-theater convergence (uranium / weapons / coordination)."""
    europe = blufs.get('europe')
    me     = blufs.get('me')
    if not europe or not me:
        return None

    russia_high = _has_signal_category(europe, 'theatre_high', 'crosstheater_iran_russia')
    russia_nuc  = _max_signal_level(europe, 'nuclear_signaling') >= 3
    iran_high   = _level_of(me) >= 3
    iran_signals = _signals_of(me)
    has_iran_proxy = any('iran' in (s.get('category', '') + s.get('short_text', '')).lower()
                         for s in iran_signals)

    triggers = sum([russia_high, russia_nuc, iran_high, has_iran_proxy])
    # v1.7.2 (Jun 18 2026): a genuine cross-theater axis requires BOTH a real
    # Europe/Russia-side signal AND an Iran-side signal. Previously any 2-of-4
    # triggers fired it -- but iran_high (= ME REGION L3+, held high by Lebanon/
    # Israel) and has_iran_proxy (Iran always emits commodity signals) are both
    # ME-internal and persistently true, so the "axis" fired with ZERO Russia
    # contribution and froze as the GPI lead. Gate on real cross-theater overlap.
    europe_side = russia_high or russia_nuc
    iran_side   = iran_high or has_iran_proxy
    if europe_side and iran_side:
        return {
            'priority': 13,
            'category': 'russia_iran_axis',
            'regions':  ['europe', 'me'],
            'icon':     '\U0001f91d',  # 🤝
            'color':    '#7c3aed',
            'headline': 'Russia-Iran axis active -- cross-theater coordination at elevated tempo',
            'detail':   ('Europe and Middle East theaters show simultaneous signaling: Russian nuclear '
                         'language, Iranian proxy activity, and documented weapons/material transfers. '
                         'Sanctions-evasion pathways under stress; uranium/Shahed flows likely '
                         'continuing despite Western pressure.'),
        }
    return None


def _narrative_iran_strike_window(blufs):
    """Iran Strike Window Convergence — surfaces operational-window indicators.

    Reads the strike_window field that rhetoric_tracker_iran.py now writes
    to its scan result (when severity >= elevated). Fires GPI narrative
    when severity is high or critical.

    FRAMING DISCIPLINE: Reports convergence, NOT prediction. Same analytical
    value as the underlying detector — just elevated to GPI visibility when
    the convergence pattern is significant enough to warrant cross-theater
    attention.
    """
    me = blufs.get('me')
    if not me:
        return None

    # The Iran tracker writes strike_window into its result; the ME BLUF
    # exposes the iran tracker's full signal data under tracker_data
    # (or via top_signals[]). Look for the strike_window field anywhere
    # we can find it.
    sw = None

    # Path 1: top-level on me bluf (if ME BLUF surfaced it explicitly)
    sw = me.get('strike_window')

    # Path 2: nested under iran tracker data
    if not sw:
        theatre_summary = me.get('theatre_summary') or {}
        iran_data = theatre_summary.get('iran') or {}
        sw = iran_data.get('strike_window')

    # Path 3: look in raw tracker data if exposed
    if not sw:
        tracker_data = me.get('tracker_data') or {}
        iran_data = tracker_data.get('iran') or {}
        sw = iran_data.get('strike_window')

    # Path 4: scan top_signals for strike-window category signal
    if not sw:
        signals = _signals_of(me)
        for s in signals:
            if 'strike_window' in (s.get('category', '') or ''):
                sw = s
                break

    if not sw:
        return None

    severity = (sw.get('severity') or '').lower()
    if severity not in ('high', 'critical'):
        return None   # Only surface to GPI at high+

    n_signals = sw.get('active_signal_count', 0) or len(sw.get('active_signals', []) or [])
    composite = sw.get('composite_score', 0)
    active_signals = sw.get('active_signals', []) or []
    active_multipliers = sw.get('active_multipliers', []) or []

    # Format signal list nicely
    signal_labels = {
        'iran_airspace':       'Iranian airspace closures',
        'regional_notams':     'regional NOTAM cluster',
        'pre_strike_posture':  'pre-strike posture (military)',
        'embassy_posture':     'embassy/evac alerts',
        'adversary_defensive': 'adversary defensive posture',
        'principal_friction':  'principal-to-principal friction',
        'rumored':             'rumored signals (OSINT)',
    }
    multiplier_labels = {
        'us_long_weekend':   'US long weekend',
        'religious_window':  'religious calendar',
        'dark_lunar_window': 'lunar window',
        'potus_anomaly':     'POTUS location anomaly',
    }
    signal_str = ', '.join(signal_labels.get(s, s) for s in active_signals[:4])
    mult_str = ', '.join(multiplier_labels.get(m, m) for m in active_multipliers[:3])

    if severity == 'critical':
        priority = 16  # Above russia_iran_axis (13), nuclear_signaling (15)
        headline = (
            f'Iran Strike Window: CRITICAL convergence -- '
            f'{n_signals} operational-window indicators active simultaneously'
        )
        detail = (
            f'The Iran Strike Window Detector reports CRITICAL convergence: '
            f'{n_signals} signals active, composite score {composite}. '
            f'Active signals include {signal_str}. '
        )
        if mult_str:
            detail += f'Calendar amplifiers active: {mult_str}. '
        detail += (
            'This is a CONVERGENCE indicator, not a prediction of imminent '
            'action -- multiple operational-window conditions are simultaneously '
            'permissive. Reader should track closely and form independent judgment.'
        )
    else:   # high
        priority = 14   # Between russia_iran_axis (13) and nuclear_signaling (15)
        headline = (
            f'Iran Strike Window: HIGH convergence -- '
            f'{n_signals} window-permissive signals active'
        )
        detail = (
            f'The Iran Strike Window Detector reports HIGH convergence: '
            f'{n_signals} signals, composite {composite}. '
            f'Pattern includes {signal_str}. '
        )
        if mult_str:
            detail += f'Amplified by {mult_str}. '
        detail += (
            'Operational-window conditions forming. Track for further signal '
            'accumulation; framing remains convergence, not prediction.'
        )

    return {
        'priority': priority,
        'category': 'iran_strike_window',
        'regions':  ['me'],
        'icon':     '\U0001f319',  # 🌙
        'color':    '#dc2626' if severity == 'critical' else '#f59e0b',
        'headline': headline,
        'detail':   detail,
    }


def _narrative_iran_deescalation(blufs):
    """US-Iran ceasefire trajectory at GPI altitude -- BIDIRECTIONAL (v1.8.0 - Jun 29 2026).

    Reads the Iran tracker's ceasefire_trajectory (a bidirectional read weighing
    consolidation vs breach from the same evidence) PLUS the maturity tag and
    contradiction flags (rhetoric:iran:latest). Surfaces the lean BOTH ways:
    consolidating/holding (green), strained (amber), fraying/breach-risk (orange/red).
    Convergence framing, never a forecast. Priority stays BELOW the +11 kinetic boost --
    a ceasefire read surfaces as a narrative, it does not drive the kinetic global level.

    Backward-compatible: if the Iran tracker has not yet emitted ceasefire_trajectory,
    falls back to the maturity-only behavior.
    """
    iran = _redis_get('rhetoric:iran:latest') or {}
    if not isinstance(iran, dict):
        return None

    traj       = iran.get('ceasefire_trajectory', {}) or {}
    lean       = traj.get('lean', 'quiet')
    maturity   = iran.get('de_escalation_maturity', 'none')
    milestones = iran.get('implementation_milestones', []) or []
    contra     = iran.get('contradiction_active', False)
    flags      = iran.get('contradiction_flags', []) or []

    has_offramp = maturity in ('framework', 'signed', 'implementing')
    has_lean    = lean not in ('quiet', '')
    if not has_offramp and not has_lean:
        return None

    n = len(milestones)
    plural = 's' if n != 1 else ''

    # Lean -> (color, icon, label). Green consolidating, amber strained, orange/red breach.
    LEAN_META = {
        'consolidating': ('#10b981', '\U0001f91d', 'consolidating'),
        'holding':       ('#10b981', '\U0001f91d', 'holding'),
        'strained':      ('#f59e0b', '\u2696\ufe0f', 'strained (bumpy road)'),
        'fraying':       ('#f97316', '\u26a0\ufe0f', 'fraying'),
        'breach_risk':   ('#ef4444', '\u26a0\ufe0f', 'breach-risk'),
        'quiet':         ('#10b981', '\U0001f91d', 'holding'),
    }
    color, icon, lean_label = LEAN_META.get(lean, LEAN_META['quiet'])

    # Headline: breach-leaning leads with the trajectory; otherwise maturity-flavored.
    if lean in ('fraying', 'breach_risk', 'strained'):
        headline = 'US-Iran ceasefire trajectory -- %s' % lean_label.upper()
    elif has_offramp and maturity == 'implementing':
        headline = ('US-Iran ceasefire -- framework moving toward implementation '
                    '(%d delivered milestone%s)' % (n, plural))
    elif has_offramp and maturity == 'signed':
        headline = 'US-Iran ceasefire -- signed framework, implementation pending'
    elif has_offramp:
        headline = 'US-Iran ceasefire -- active negotiation track (unsigned)'
    else:
        headline = 'US-Iran ceasefire trajectory -- %s' % lean_label.upper()

    # Detail: lead with the bidirectional trajectory read (strip its own trailing
    # disclaimer to avoid a mid-paragraph repeat), then maturity + contradiction context.
    detail = ''
    traj_detail = traj.get('detail', '') or ''
    _DISC = 'This is a CONVERGENCE indicator'
    traj_read = (traj_detail.split(_DISC)[0].strip() if _DISC in traj_detail else traj_detail.strip())
    if traj_read:
        detail += traj_read + ' '

    if has_offramp and maturity == 'implementing':
        detail += ('Off-ramp maturity reads implementing -- %d delivered milestone%s (%s). '
                   % (n, plural, ', '.join(milestones)))
    elif has_offramp and maturity == 'signed':
        detail += 'Off-ramp maturity reads signed framework, implementation pending. '
    elif has_offramp:
        detail += 'Off-ramp maturity reads active negotiation track, unsigned. '

    if contra:
        bits = []
        if 'israel_lebanon' in flags:
            bits.append('continued Israeli operations in Lebanon')
        if 'syria_hezbollah' in flags:
            bits.append('calls for Syria to act against Hezbollah')
        contra_txt = ' and '.join(bits) if bits else 'an unresolved Lebanon-front contradiction'
        detail += ('A live contradiction -- %s -- caps how deep any de-escalation reads; '
                   'the all-fronts framing is not yet borne out on the Lebanon front. ' % contra_txt)

    detail += ('Framing is convergence, not prediction -- a ceasefire read leaning toward '
               'consolidation or breach, with the reader completing the inference.')

    priority = 10 if lean in ('fraying', 'breach_risk') else 9   # still below the +11 kinetic boost

    return {
        'priority': priority,
        'category': 'iran_deescalation',
        'regions':  ['me'],
        'icon':     icon,
        'color':    color,
        'headline': headline,
        'detail':   detail.strip(),
    }

def _narrative_dprk_russia_axis(blufs):
    """DPRK-Russia coordination (ammunition / troops / weapons)."""
    europe = blufs.get('europe')
    if not europe:
        return None
    if _has_signal_category(europe, 'crosstheater_dprk_russia'):
        return {
            'priority': 11,
            'category': 'dprk_russia_axis',
            'regions':  ['europe', 'asia'],
            'icon':     '\U0001f6a9',  # 🚩
            'color':    '#7c3aed',
            'headline': 'North Korea-Russia axis active -- ammunition and personnel transfers documented',
            'detail':   ('North Korean (DPRK) ammunition stocks and reportedly personnel are flowing '
                         'to Russian forces. This sustains Russian war-fighting capacity, complicates '
                         'sanctions enforcement, and elevates Korean Peninsula unpredictability '
                         'as North Korea extracts technology transfers in return.'),
        }
    return None


def _narrative_arctic_convergence(blufs):
    """Russia arctic posture + Greenland sovereignty crisis simultaneously."""
    europe = blufs.get('europe')
    if not europe:
        return None
    if _has_signal_category(europe, 'arctic_convergence'):
        return {
            'priority': 12,
            'category': 'arctic_convergence',
            'regions':  ['europe'],
            'icon':     '\U0001f9ca',  # 🧊
            'color':    '#0ea5e9',
            'headline': 'Arctic convergence -- Russia exploiting US-Denmark sovereignty friction',
            'detail':   ('Russian Northern Fleet posture is simultaneously elevated with US-Greenland '
                         'sovereignty pressure signals. Classic Greenland-Iceland-United Kingdom (GIUK) '
                         'gap pressure window; sub-cable and undersea infrastructure should be '
                         'monitored for hybrid interference.'),
        }
    return None


# ════════════════════════════════════════════════════════════════════
# DEDICATED NARRATIVE: BELT-AND-ROAD RESOURCE LEVERAGE (v3.6.0)
# ════════════════════════════════════════════════════════════════════
# China's Belt-and-Road resource-leverage pattern is structurally important
# enough to warrant a dedicated narrative function rather than relying solely
# on the generic registry-driven detector. The generic detector fires on any
# single trigger; this function COUNTS how many anchor relationships are
# simultaneously under stress and amplifies the narrative accordingly.
#
# Anchor relationships (Phase 1A baseline, May 23 2026):
#   1. China-DRC cobalt          (~80% of DRC mining via CCP-linked entities)
#   2. China-Guinea bauxite      (SMB Winning + Boké rail + Conakry port)
#   3. China-Jordan potash       (SDIC 28% of Arab Potash Co since 2017)
#   4. China-Indonesia nickel    (Tsingshan + Huayou Sulawesi HPAL parks)
#
# Phase 2 anchors to add as Asifah expands:
#   - China-Zambia copper
#   - China-Angola infrastructure-for-resources
#   - China-Mozambique infrastructure
#   - China-Saudi/UAE energy partnerships
#   - China-Argentina lithium
#
# DETECTION LOGIC (v3.6.0):
#   Read each regional BLUF for signals carrying anchor-specific flags
#   ({anchor}_belt_and_road_active). Count how many distinct anchors fire.
#   Emit narrative scaled to anchor count:
#     1 anchor   -> no narrative (single-anchor stories belong to generic detector)
#     2 anchors  -> WATCH narrative (priority 12)
#     3 anchors  -> ELEVATED narrative (priority 14)
#     4+ anchors -> STRUCTURAL narrative (priority 16) — BRI architecture under stress
#
# CONVERGENCE FRAMING DISCIPLINE: We report WHAT signals are present, NOT
# WHETHER China's BRI architecture is "failing" or "succeeding." Active
# anchor stress is a measurement, not a verdict.
# ════════════════════════════════════════════════════════════════════
def _narrative_belt_and_road_resource_leverage(blufs):
    """
    Counts active Belt-and-Road resource-leverage anchor flags across regions.
    Emits a narrative only when 2+ anchors fire simultaneously.

    Phase 2 dependency: regional BLUFs (especially africa + asia + me) need
    to emit signals carrying the {anchor}_belt_and_road_active flag in their
    convergence_states. Until trackers ship, this function returns None
    silently (no false positives).
    """
    # Anchor flags Phase 2 trackers will set on relevant signals:
    ANCHORS = [
        ('drc_belt_and_road_active',         'DRC cobalt',          'africa'),
        ('guinea_belt_and_road_active',      'Guinea bauxite',      'africa'),
        ('jordan_belt_and_road_active',      'Jordan potash',       'me'),
        ('indonesia_belt_and_road_active',   'Indonesia nickel',    'asia'),
        # Phase 2+ additions (uncomment as trackers ship):
        # ('zambia_belt_and_road_active',     'Zambia copper',      'africa'),
        # ('angola_belt_and_road_active',     'Angola corridor',    'africa'),
        # ('argentina_belt_and_road_active',  'Argentina lithium',  'wha'),
    ]

    active_anchors = []
    for flag, label, primary_region in ANCHORS:
        # Scan primary region first, fallback to all regions for cross-stamped flags
        regions_to_scan = [primary_region] + [r for r in blufs.keys() if r != primary_region]
        for region in regions_to_scan:
            bluf = blufs.get(region)
            if not bluf:
                continue
            signals = _signals_of(bluf)
            if any(s.get(flag) for s in signals):
                active_anchors.append(label)
                break  # don't double-count this anchor across regions

    n_active = len(active_anchors)

    # 0 or 1 anchor active: no dedicated narrative (let generic detector handle)
    if n_active < 2:
        return None

    anchor_list = ', '.join(active_anchors)

    if n_active >= 4:
        priority = 16
        severity_label = 'STRUCTURAL'
        headline = (
            f'Belt-and-Road resource leverage: STRUCTURAL convergence -- '
            f'{n_active} anchor relationships simultaneously stressed'
        )
        detail = (
            f'CONVERGENCE READOUT: {n_active} anchor relationships in China\'s '
            f'Belt-and-Road resource-leverage architecture are simultaneously '
            f'showing stress: {anchor_list}. WHAT THIS MEASURES: Chinese state '
            f'capital + flagship-resource-company stake + infrastructure '
            f'investment is the canonical BRI playbook (SDIC-Jordan, China-DRC, '
            f'China-Guinea, China-Indonesia). When 4+ anchors fire simultaneously, '
            f'either (a) Western counter-positioning is accelerating (Lobito '
            f'Corridor, Project Vault, Orion MOU), (b) host-country renegotiation '
            f'rhetoric is concurrent across multiple sovereign actors, or '
            f'(c) coordinated stress is signaling structural pressure on the BRI '
            f'commercial architecture itself. FRAMING DISCIPLINE: This is a '
            f'CONVERGENCE indicator, NOT a prediction of BRI collapse or success. '
            f'Active anchor stress is a measurement.'
        )
    elif n_active == 3:
        priority = 14
        severity_label = 'ELEVATED'
        headline = (
            f'Belt-and-Road resource leverage: ELEVATED -- '
            f'{n_active} anchors stressed ({anchor_list})'
        )
        detail = (
            f'Three of the canonical Belt-and-Road resource-leverage anchor '
            f'relationships are simultaneously showing stress: {anchor_list}. '
            f'When 3+ anchors fire concurrently, the pattern suggests either '
            f'coordinated Western counter-positioning or coordinated host-country '
            f'renegotiation pressure. Watch: Arab-Chinese Cooperation Forum '
            f'outcomes, Lobito Corridor throughput, Indonesian '
            f'nickel export-policy shifts, DRC-Beijing renegotiation signals. '
            f'CONVERGENCE framing -- not prediction.'
        )
    else:  # n_active == 2
        priority = 12
        severity_label = 'WATCH'
        headline = (
            f'Belt-and-Road resource leverage: WATCH -- '
            f'{n_active} anchors stressed ({anchor_list})'
        )
        detail = (
            f'Two Belt-and-Road resource-leverage anchor relationships are '
            f'concurrently showing stress: {anchor_list}. Single-anchor stress '
            f'is routine; concurrent multi-anchor stress is the early signal '
            f'that the broader BRI commercial architecture may be entering a '
            f'period of recalibration. CONVERGENCE framing -- not prediction.'
        )

    return {
        'priority': priority,
        'category': 'belt_and_road_resource_leverage',
        'regions':  ['africa', 'asia', 'me'],   # Cross-regional by definition (Tier 1)
        'icon':     '\U0001f3ed',                # 🏭
        'color':    '#a855f7',                    # purple — regime axis
        'headline': headline[:120],
        'detail':   detail,
        'pressure_type': 'economic',   # BRI resource leverage is economic-axis primary
        'severity_label': severity_label,
        'anchor_count':   n_active,
        'active_anchors': active_anchors,
    }


# ════════════════════════════════════════════════════════════════════
# REGISTRY-DRIVEN CONVERGENCE DETECTOR (Layer 1)
# ════════════════════════════════════════════════════════════════════
# v3.10.0 -- how many live nodes a cluster needs before it is reported as a
# regional pattern rather than as separate country readings. Two is the point at
# which "broader than one country" becomes a true statement; one is an anecdote.
CLUSTER_ROLLUP_MIN_NODES = 2


def _detect_convergences_from_registry(blufs):
    """
    Generic Tier-1 cross-axis convergence detector.

    Loops CONVERGENCE_REGISTRY entries, checks each one's trigger signal in the
    appropriate regional BLUF, and emits a narrative for any active convergence.

    A convergence is "active" when:
      - The trigger signal exists in the trigger_region's BLUF
      - The signal carries the per-convergence flag (e.g. {id}_active = True)
        which is set by ME BLUF's Layer 2 enrichment when commodity threshold is met

    Adding a new convergence is now zero-code in this file — just add a registry entry
    in convergence_registry.py and Layer 2 takes care of the flag-setting upstream.

    Returns:
        list of narrative dicts (possibly empty) — one per active convergence.
    """
    try:
        from convergence_registry import (
            CONVERGENCE_REGISTRY,
            format_headline,
            convergence_priority,
            cluster_status,
            all_clusters,
        )
    except ImportError:
        # Registry module not available — silent no-op
        return []

    matches = []
    for entry in CONVERGENCE_REGISTRY:
        # Primary detection: scan trigger_region first (canonical source).
        # Fallback: if trigger_region's signal is unavailable (e.g. ME BLUF stale),
        # fall through to OTHER regions in entry.regions[]. Layer 2 enrichments stamp
        # the same {id}_active flag on cross-regional signals (e.g. Europe Ukraine
        # commodity signal also carries wheat_lebanon_active when applicable). This
        # is belt-and-suspenders cross-regional convergence detection.
        primary_region = entry.get('trigger_region')
        all_regions    = [primary_region] + [r for r in entry.get('regions', []) if r != primary_region]

        trigger_sig = None
        found_in_region = None
        for region in all_regions:
            bluf = blufs.get(region)
            if not bluf:
                continue
            signals = _signals_of(bluf)
            # In primary region, look for the canonical trigger_signal_category.
            # In fallback regions, look for ANY signal carrying the {id}_active flag.
            active_flag = f'{entry["id"]}_active'
            if region == primary_region:
                # v3.9.0 -- an entry may declare trigger_signal_categories (a
                # list) when its analytic scope is reached under more than one
                # country id. wheat_gaza is scoped to Gaza, but Palestinian
                # food-security reporting arrives as humanitarian_palestine, so
                # a single exact category meant Layer 2 built the enriched
                # signal and Layer 1 never found it. Falls back to the singular
                # field, so every other entry is untouched.
                _cats = (entry.get('trigger_signal_categories')
                         or [entry['trigger_signal_category']])
                candidate = next(
                    (s for s in signals if s.get('category') in _cats
                     and s.get(active_flag)),
                    None
                )
            else:
                candidate = next(
                    (s for s in signals if s.get(active_flag)),
                    None
                )
            if candidate:
                trigger_sig = candidate
                found_in_region = region
                break

        if not trigger_sig:
            continue

        # Pull the convergence state stamped by Layer 2 (alert level + signal count)
        states = trigger_sig.get('convergence_states') or {}
        state = states.get(entry['id']) or {}
        # v3.10.0 (Oct 6 2026) -- THE DEFAULT THAT INVENTED A READING.
        # This was `state.get('alert_level', 'elevated')`. On the cross-regional
        # fallback path a signal carries the {id}_active flag but NOT the
        # convergence_states dict, so `state` is {} and the card printed
        # "global wheat ELEVATED" -- a specific, quotable pressure level that
        # nobody measured, and the reason the GPI and the commodities page have
        # been disagreeing about wheat. A hardcoded default is not a reading.
        alert_level = state.get('alert_level') or 'unread'
        alert_stamped = bool(state.get('alert_level'))
        # Freshness tiering (Jun 2026): topline only when Layer 2 marks the commodity
        # pressure RISING. A steady baseline drops to watch_priority AND sheds its
        # cross-regional tag (so it loses the +30 Tier-1 boost in top_signals too),
        # leaving the structural read as context, not a topline. Default True keeps
        # legacy behavior if Layer 2 has not yet stamped is_fresh.
        is_fresh = state.get('is_fresh', True)
        # Only entries that OPT IN to watch tiering (define watch_priority) are
        # demoted when stale. convergence_priority + format_headline already no-op
        # for non-opted-in entries; this keeps the cross-regional tag intact for them.
        opted_in = bool(entry.get('watch_priority'))
        conv_regions = (list(entry.get('regions', []))
                        if (is_fresh or not opted_in)
                        else [found_in_region or entry.get('trigger_region')])

        # v3.15.0 -- a stamping layer may grade its own reading (the commodity
        # web stamps L3 watch / L4 convergence / L5 compound). Without this a
        # fresh L3 watch promoted into the feed at priority 13 -> L5.
        _lvl_hint = state.get('web_level')
        _prio = (state.get('priority') if (is_fresh and state.get('priority'))
                 else convergence_priority(entry, is_fresh))
        matches.append({
            'priority':         _prio,
            'level_hint':       _lvl_hint,
            'category':         entry['id'],
            'regions':          conv_regions,
            'icon':             entry['icon'],
            'color':            entry['color'],
            # v3.15.0 -- a stamping layer that composes its own text (the
            # commodity web) supplies it; otherwise the registry template.
            'headline':         (state.get('live_headline')
                                 or format_headline(entry, alert_level, is_fresh)),
            'detail':           state.get('live_detail') or entry['detail'],
            'axes':             entry.get('axes'),
            'detected_via':     found_in_region,   # diagnostic: which region's signal triggered detection
            'fresh':            is_fresh,           # diagnostic: topline vs watch tier
            # v3.10.0 -- False means Layer 2 never stamped a pressure level for
            # this entry and the word in the headline is a placeholder, not a
            # measurement. The page renders the caveat; it is never silent.
            'alert_stamped':    alert_stamped,
            'cluster':          entry.get('cluster'),
        })

    # ════════════════════════════════════════════════════════════════
    # v3.10.0 (Oct 6 2026) -- CLUSTER ROLLUP
    #
    # Until now this function appended one card per registry entry and stopped.
    # Four Levant wheat nodes firing produced four cards, each independently
    # claiming a country, and the reader had to assemble "this is one regional
    # story" unaided. Meanwhile cluster_status() -- which has produced exactly
    # that sentence since September -- was called by nothing anywhere in the
    # platform.
    #
    # The rollup does NOT delete the per-entry cards. Each keeps its country
    # detail and gains `clustered_into`; the page nests them under the cluster
    # card. Deleting them would trade one kind of information loss for another.
    #
    # Single-node clusters are left alone: cluster_status itself says a lone node
    # is "not yet a regional pattern", and promoting one would be the overclaim
    # this layer exists to prevent.
    # ════════════════════════════════════════════════════════════════
    try:
        by_cluster = {}
        for m in matches:
            cid = m.get('cluster')
            if cid:
                by_cluster.setdefault(cid, []).append(m)

        cluster_cards = []
        for cid, members in by_cluster.items():
            if len(members) < CLUSTER_ROLLUP_MIN_NODES:
                continue
            cs = cluster_status(cid, [m['category'] for m in members])
            if not cs:
                continue

            for m in members:
                m['clustered_into'] = cid

            # The cluster inherits the loudest member's priority -- it is the
            # same finding at a wider aperture, not a louder one. +0, not +1.
            top = max(members, key=lambda m: m.get('priority', 0))
            regions = []
            for m in members:
                for r in (m.get('regions') or []):
                    if r not in regions:
                        regions.append(r)

            card = {
                'priority':      top.get('priority', 0),
                'category':      'cluster:%s' % cid,
                'regions':       regions,
                'icon':          top.get('icon', '\U0001f310'),
                'color':         top.get('color', '#f59e0b'),
                'headline':      cs['headline'],
                'detail':        cs.get('shared_mechanism', '') or cs.get('why_together', ''),
                'detected_via':  'cluster_rollup',
                # A cluster is as fresh as its freshest member: one node rising
                # makes the regional reading news even if the others are steady.
                'fresh':         any(m.get('fresh') for m in members),
                'is_cluster':    True,
                'cluster':       cid,
                'cluster_state': cs,
                'member_ids':    [m['category'] for m in members],
                # If ANY member's pressure level was unstamped, say so at the
                # cluster level too -- otherwise the rollup would launder an
                # unread node into a confident regional claim.
                'alert_stamped': all(m.get('alert_stamped', True) for m in members),
            }
            cluster_cards.append(card)

        _canon_miss_report()
        if cluster_cards:
            matches.extend(cluster_cards)
            print('[GPI] cluster rollup: %d cluster card(s) -- %s'
                  % (len(cluster_cards),
                     '; '.join('%s %d/%d' % (c['cluster'],
                                             c['cluster_state']['active_count'],
                                             c['cluster_state']['total'])
                               for c in cluster_cards)))
        else:
            # Absence-honest: say that no cluster reached the threshold, and name
            # what WAS seen, so "no cluster card" is distinguishable from "the
            # rollup did not run".
            print('[GPI] cluster rollup: no cluster reached %d live nodes (clusters '
                  'with live members: %s)'
                  % (CLUSTER_ROLLUP_MIN_NODES,
                     ', '.join('%s=%d' % (k, len(v)) for k, v in by_cluster.items())
                     or 'none'))
    except Exception as _cluster_err:
        print('[GPI] cluster rollup error (non-critical, per-entry cards '
              'unaffected): %s' % str(_cluster_err)[:200])

    return matches


def _narrative_houthi_fragility(blufs):
    """Yemen baseline + Iran-US off-ramp active = fragile quiescence narrative."""
    me = blufs.get('me')
    if not me:
        return None
    has_diplomatic = _has_signal_category(me, 'diplomatic_active', 'mediation_active', 'off_ramp_active')
    yemen_signals = [s for s in _signals_of(me)
                     if 'yemen' in (s.get('theatre', '') + s.get('short_text', '')).lower()]
    yemen_low = not yemen_signals or all(_safe_level(s.get('level', 0)) < 3 for s in yemen_signals)
    if has_diplomatic and yemen_low:
        return {
            'priority': 9,
            'category': 'houthi_fragility',
            'regions':  ['me'],
            'icon':     '\U0001f1fe\U0001f1ea',  # 🇾🇪
            'color':    '#f59e0b',
            'headline': 'Houthi quiescence fragile -- Iran-US off-ramp holding for now',
            'detail':   ('Yemen tracker shows baseline-level activity while Iran-US diplomatic '
                         'tracks remain active. Houthi posture historically responds to Iranian '
                         'strategic direction with 1-3 week lag; ceasefire collapse would likely '
                         'trigger Bab el-Mandeb / Red Sea reactivation within days.'),
        }
    return None


def _narrative_dual_chokepoint(blufs):
    """Hormuz + Bab el-Mandeb simultaneous pressure (ME-specific)."""
    me = blufs.get('me')
    if not me:
        return None
    if _has_signal_category(me, 'dual_chokepoint'):
        return {
            'priority': 13,
            'category': 'dual_chokepoint',
            'regions':  ['me'],
            'icon':     '\U0001f6a2',  # 🚢
            'color':    '#dc2626',
            'headline': 'Maritime supply-chain black swan -- Hormuz and Bab el-Mandeb simultaneous',
            'detail':   ('Iran (Hormuz) and Yemen (Bab el-Mandeb) chokepoint signals are elevated '
                         'simultaneously. This is the high-impact, low-probability scenario that '
                         'would shock global energy and shipping markets within hours of activation.'),
        }
    return None


def _narrative_wha_cascade(blufs):
    """Western Hemisphere migration / regime fracture cascade."""
    wha = blufs.get('wha')
    if not wha:
        return None
    if _has_signal_category(wha, 'regime_fracture', 'migration_surge', 'wha_cascade'):
        return {
            'priority': 10,
            'category': 'wha_cascade',
            'regions':  ['wha'],
            'icon':     '\U0001f30e',  # 🌎
            'color':    '#ef4444',
            'headline': 'Western Hemisphere cascade -- regime fracture + migration pressure converging',
            'detail':   ('Western Hemisphere shows simultaneous regime stress (Cuba, Venezuela, or '
                         'Haiti vectors) and migration surge signals. Hemispheric stability under '
                         'compound pressure; SOUTHCOM monitoring tempo elevated.'),
        }
    return None


def _narrative_nuclear_signaling_global(blufs):
    """Russia OR any other region at nuclear-signaling threshold."""
    nuclear_active, evidence = [], []
    for region, bluf in blufs.items():
        if not bluf:
            continue
        if bluf.get('nuclear_elevated') or _max_signal_level(bluf, 'nuclear_signaling') >= 4:
            nuclear_active.append(region)
            # CARRY THE EVIDENCE (Sep 2026). This detector is a pure pass-through
            # on a boolean, and it used to discard everything behind it -- so the
            # platform's PRIORITY-15 narrative, its highest-stakes signal class,
            # told an analyst only that "at least one regional theater shows
            # nuclear-doctrine-language" with nothing whatsoever to check.
            #
            # The trigger phrase existed two functions upstream the entire time,
            # unpacked into a throwaway variable. An alarm this loud has to be
            # auditable from its own output or it trains the reader to ignore it.
            trig = (bluf.get('nuclear_trigger')
                    or (bluf.get('so_what') or {}).get('nuclear_trigger') or '')
            lvl = (bluf.get('nuclear_level')
                   or (bluf.get('so_what') or {}).get('nuclear_level') or 0)
            evidence.append({'region': region, 'trigger': trig, 'level': lvl})

    if nuclear_active:
        regions_str = ', '.join(REGION_DISPLAY[r]['name'] for r in nuclear_active)
        detail = ('At least one regional theater shows nuclear-doctrine-language at coercion '
                  'threshold. This is the highest-stakes signal class on the platform. ')

        named = [e for e in evidence if e.get('trigger')]
        if named:
            detail += ('WHAT FIRED IT: '
                       + '; '.join('%s at L%s on "%s"'
                                   % (REGION_DISPLAY.get(e['region'], {}).get('name', e['region']),
                                      e['level'] or '?', e['trigger'])
                                   for e in named)
                       + '. The matched phrase is shown so the reading can be checked against '
                         'the source rather than taken on trust. ')
        unnamed = [e for e in evidence if not e.get('trigger')]
        if unnamed:
            # Absence-honest: a region can set the flag without exposing what set
            # it. Say so rather than implying evidence the payload does not carry.
            detail += ('COVERAGE GAP: %s flagged nuclear elevation without an attached '
                       'trigger phrase, so the specific language is not visible at this '
                       'altitude and must be read from the regional tracker directly. '
                       % ', '.join(REGION_DISPLAY.get(e['region'], {}).get('name', e['region'])
                                   for e in unnamed))

        detail += ('Watch for further escalation rhetoric or de-escalation off-ramp signaling. '
                   'A nuclear-axis reading is a CONVERGENCE indicator, NOT a probability of use.')

        return {
            'priority': 15,
            'category': 'nuclear_signaling_global',
            'regions':  nuclear_active,
            'icon':     '\u2622\ufe0f',  # ☢️
            'color':    '#dc2626',
            'headline': f'Nuclear signaling active -- {regions_str}',
            'detail':   detail,
            'evidence': evidence,
        }
    return None


KINETIC_BUNDLE_KEY = 'kinetic:global:latest'
MARKET_FRAGILITY_BUNDLE_KEY = 'blackswan:market:gpi'  # Market Watch fragility detector (Jun 13 2026)


_COUNTRY_NAME_ALIASES = {
    # normalized variant -> canonical short name (pulse/kinetic style).
    # Exact matching + this table avoids the containment traps
    # (Sudan vs South Sudan, Niger vs Nigeria).
    'syrian arab republic': 'syria',
    'state of palestine': 'palestine',
    'palestinian territories': 'palestine',
    'turkiye': 'turkey',
    'democratic republic of the congo': 'dr congo',
    'drc': 'dr congo',
    'republic of moldova': 'moldova',
    'lao pdr': 'laos',
    "lao people's democratic republic": 'laos',
    'united republic of tanzania': 'tanzania',
    'myanmar (burma)': 'myanmar',
    'burma': 'myanmar',
    'venezuela (bolivarian republic of)': 'venezuela',
    'bolivia (plurinational state of)': 'bolivia',
    'east timor': 'timor-leste',
}


def _normalize_country_name(name):
    """Any inbound country NAME -> the platform's canonical id."""
    return _canon(name)


def _names_match(a, b):
    """Exact country matching after canonicalization.
    Deliberately NOT containment-based: 'Sudan' must never match
    'South Sudan', nor 'Niger' match 'Nigeria'."""
    a = _normalize_country_name(a)
    b = _normalize_country_name(b)
    return bool(a) and a == b


def _narrative_food_stress_convergence(blufs):
    """FOOD x KINETIC x HUMANITARIAN compound read (Slice 3b, Jun 10 2026).

    Doctrine: sensors below, analyst above. The food pulse (sensor) reports
    measured multi-staple price stress; this detector reads it TOGETHER with
    kinetic activity (GDELT CAMEO gatherer) and the humanitarian convergence
    layer for the same countries. Co-occurrence across independent layers is
    the compound pattern consistent with elevated famine / unrest /
    humanitarian-crisis risk -- stated estimatively, never predictively.
    """
    food = blufs.get('global_food')
    food_signals = _signals_of(food)
    if not food_signals:
        return None

    # Layer 2: kinetic gatherer bundle (same Redis; names like 'Afghanistan')
    kinetic = _redis_get(KINETIC_BUNDLE_KEY) or {}
    kinetic_hot = {name: c.get('band') for name, c in (kinetic.get('countries') or {}).items()
                   if c.get('band') in ('elevated', 'high', 'surge')}

    # Layer 3: humanitarian convergence signals carry a 'country' field
    hum = blufs.get('global_humanitarian')
    hum_countries = set()
    for sig in _signals_of(hum):
        cname = sig.get('country')
        if cname and _safe_level(sig.get('level', 0)) >= 2:
            hum_countries.add(cname)

    compound = []
    food_only = []
    for sig in food_signals:
        country = sig.get('country') or ''
        layers = ['food']
        kin_band = None
        for kname, band in kinetic_hot.items():
            if _names_match(country, kname):
                layers.append('kinetic')
                kin_band = band
                break
        for hname in hum_countries:
            if _names_match(country, hname):
                layers.append('humanitarian')
                break
        entry = {'country': country, 'layers': layers, 'kinetic_band': kin_band,
                 'staples': sig.get('short_text', ''), 'level': _safe_level(sig.get('level', 0))}
        if len(layers) >= 2:
            compound.append(entry)
        else:
            food_only.append(entry)

    if compound:
        triple = [e for e in compound if len(e['layers']) == 3]
        names = ', '.join(e['country'] for e in compound[:5])
        layer_bits = []
        for e in compound[:4]:
            others = '+'.join(l for l in e['layers'] if l != 'food')
            layer_bits.append('%s (food+%s)' % (e['country'], others))
        return {
            'priority': 7 if triple else 8,
            'category': 'food_stress_convergence',
            'regions':  ['global_food', 'global_humanitarian'],
            'icon':     '\U0001f33e',
            'color':    '#dc2626' if triple else '#ef4444',
            'headline': ('Food-price stress co-occurring with %s signals in %d countr%s -- %s'
                         % ('kinetic and humanitarian' if triple else 'independent pressure',
                            len(compound), 'y' if len(compound) == 1 else 'ies', names)),
            'detail':   ('WFP-measured multi-staple domestic price stress is co-occurring with '
                         'independent pressure layers in the same countries: %s. '
                         'Cross-layer co-occurrence of measured food stress with kinetic or '
                         'humanitarian signals is the compound pattern that has historically '
                         'preceded famine conditions and subsistence-driven unrest. This is a '
                         'convergence read of present conditions, not a prediction of outcome.'
                         % '; '.join(layer_bits)),
        }
    # Food-only: gated multi-staple stress with no cross-layer overlap yet.
    names = ', '.join(e['country'] for e in food_only[:5])
    return {
        'priority': 12,
        'category': 'food_stress_gated',
        'regions':  ['global_food'],
        'icon':     '\U0001f33e',
        'color':    '#f59e0b',
        'headline': ('Multi-staple food-price stress measured in %d countr%s -- %s'
                     % (len(food_only), 'y' if len(food_only) == 1 else 'ies', names)),
        'detail':   ('WFP-measured domestic prices show high-band anomalies across multiple '
                     'staples in %s -- broad-basket stress against each country\'s own '
                     'baseline, the pattern that has historically preceded subsistence-driven '
                     'unrest. No kinetic or humanitarian co-occurrence detected this cycle; '
                     'watch for cross-layer convergence. Convergence indicator, not a prediction.'
                     % names),
    }




# ── COMMODITY EVIDENCE CAP  (v3.16.0, Oct 29 2026) ─────────────────────────
# Live Oct 29: every commodity in the evidence-earned commodity BLUF read L3
# (news only), yet the economic AXIS read L5 -- from country-level signals on
# the regional backends: "Composite commodity pressure: SURGE -- 218 pts"
# (Saudi Arabia, Qatar, UAE, Afghanistan) and "BELARUS: Commodity Pressure:
# SURGE -- POTASH (52 signals)". Those are news-volume scores. At GPI altitude
# a country's commodity signal may not claim more than the commodity itself
# has EARNED on the evidence ladder (price and/or physical disruption).
#
# Altitude principle: the country pages keep their own reading (they are
# not touched); the GPI recalibrates what it lifts to the global stack, and
# keeps the original as level_country so the cap is visible, not silent.
_COMMODITY_SIGNAL_CATS = ('commodity_coupling', 'commodity', 'commodity_pressure',
                          'commodity_surge', 'commodity_exposure')
_COMMODITY_CAP_REGION = 'global_commodity'


def _apply_commodity_evidence_cap(blufs):
    """Cap regional commodity-news signals at the commodity's earned level.

    Returns a small report. Never raises; a failure leaves signals untouched.
    """
    rep = {'capped': 0, 'earned': {}, 'basis': None}
    try:
        cb = (blufs or {}).get(_COMMODITY_CAP_REGION)
        earned = {}
        for sg in _signals_of(cb or {}):
            c = sg.get('commodity')
            if c and not sg.get('web_carrier'):
                earned[str(c)] = max(earned.get(str(c), 0), _safe_level(sg.get('level', 0)))
        rep['earned'] = earned
        if cb:
            ceiling_default = max(earned.values()) if earned else 3
            rep['basis'] = 'commodity BLUF read'
        else:
            # Absence-honest: with no evidence ladder to consult, nothing has
            # EARNED more than watch. Unread is not a licence to read L5.
            ceiling_default = 3
            rep['basis'] = 'commodity BLUF unavailable -- unearned, capped at watch'
        names = sorted(earned.keys(), key=len, reverse=True)
        for region, bluf in (blufs or {}).items():
            if region == _COMMODITY_CAP_REGION or not isinstance(bluf, dict):
                continue
            pools = [bluf.get('signals'), bluf.get('top_signals')]
            for pool in pools:
                for sg in pool or []:
                    if not isinstance(sg, dict):
                        continue
                    cat = str(sg.get('category') or '')
                    if cat not in _COMMODITY_SIGNAL_CATS:
                        continue
                    lvl = _safe_level(sg.get('level', 0))
                    txt = (sg.get('short_text') or '').lower()
                    named = next((c for c in names
                                  if re.search(r'\b%s\b' % re.escape(c.replace('_', ' ')), txt)), None)
                    cap = earned.get(named, 3) if named else ceiling_default
                    cap = max(cap, 3)    # never below watch: the country IS exposed
                    if lvl > cap:
                        sg.setdefault('level_country', sg.get('level'))
                        sg['level'] = cap
                        sg['level_capped'] = (
                            'GPI evidence cap: country commodity-news reading %s, held at L%d '
                            'because %s has earned only L%d on the price/disruption ladder'
                            % (str(sg.get('level_country')).upper(), cap,
                               (named or 'no tracked commodity'), cap))
                        if 'GPI-held' not in (sg.get('short_text') or ''):
                            sg['short_text'] = ('%s · GPI-held at L%d: not price/disruption-confirmed'
                                                % ((sg.get('short_text') or '').rstrip(), cap))[:200]
                        rep['capped'] += 1
    except Exception as e:
        rep['error'] = str(e)[:160]
    if rep['capped']:
        print('[GPI] commodity evidence cap: %d regional commodity signal(s) held at earned level (%s)'
              % (rep['capped'], rep['basis']))
    return rep


# ════════════════════════════════════════════════════════════════════════
# EVIDENCE GATES FOR ECONOMIC NARRATIVES  (v3.16.0, Oct 29 2026)
# ════════════════════════════════════════════════════════════════════════
# Rachel's commodity ruling, extended GPI-wide: a CONDITION (a fragility
# reading, a news-volume breadth count) is not an EVENT. Conditions sit at L3
# and are standing by definition; the level is earned by a market actually
# moving and/or a physical/kinetic event actually happening.
#
# Live Oct 29: "Market fragility HIGH AND Taiwan-Strait kinetic signaling"
# promoted the economic axis to L5 on priority alone, while every commodity
# read L3; and "Global oil pressure -- 45 exposed countries off one shared
# headline" sat in the toplines as if breadth of coverage were news.

SEMIS_MOVE_30D = 15.0   # % fall in the Taiwan-exposed semis instrument over ~30 days
SEMIS_MOVE_5D  = 7.0    # % fall over five sessions
_TAIWAN_THEATRES = ('taiwan', 'china', 'taiwan_strait', 'cross_strait')
_KINETIC_EVENT_CATS = ('red_line_breached', 'kinetic_pressure', 'kinetic_threshold')


def _semis_market_move():
    """Has the Taiwan-exposed semiconductor instrument actually FALLEN?

    Reads the commodity tracker's hourly sparkline cache (TSM, failing over to
    the SOXX/SMH semis ETFs -- here the equity IS the exposed asset, so a proxy
    is acceptable, unlike for a raw commodity). Never fetches. Returns
    {'state': 'move'|'flat'|'unread', ...}; unread is never read as calm.
    """
    bundle = _redis_get('commodity_sparkline_bundle') or {}
    sp = (bundle.get('sparklines') or {}).get('semiconductors') if isinstance(bundle, dict) else None
    if not isinstance(sp, dict):
        return {'state': 'unread', 'reason': 'semiconductor price not in the sparkline cache'}
    closes = []
    for v in sp.get('spark') or []:
        v = v.get('value') if isinstance(v, dict) else v
        try:
            closes.append(float(v))
        except (TypeError, ValueError):
            pass
    try:
        c30 = float(sp.get('change_pct_30d')) if sp.get('change_pct_30d') is not None else None
    except (TypeError, ValueError):
        c30 = None
    c5 = ((closes[-1] - closes[-6]) / closes[-6] * 100) if len(closes) >= 6 and closes[-6] else None
    tk = sp.get('source_ticker_used') or sp.get('ticker') or 'TSM'
    out = {'ticker': tk, 'change_pct_30d': round(c30, 1) if c30 is not None else None,
           'change_pct_5d': round(c5, 1) if c5 is not None else None}
    if c30 is not None and c30 <= -SEMIS_MOVE_30D:
        out.update(state='move', phrase='%s down %.0f%% over 30 days' % (tk, abs(c30)))
    elif c5 is not None and c5 <= -SEMIS_MOVE_5D:
        out.update(state='move', phrase='%s down %.0f%% over five sessions' % (tk, abs(c5)))
    elif c30 is None and c5 is None:
        out.update(state='unread', reason='semiconductor price series too short')
    else:
        out.update(state='flat', phrase='%s not falling (%s over 30 days)'
                   % (tk, ('%+.0f%%' % c30) if c30 is not None else 'n/a'))
    return out


def _taiwan_kinetic_event(asia):
    """An actual L5 kinetic event in the Taiwan/China theatre -- not signaling."""
    for sg in _signals_of(asia or {}):
        th = str(sg.get('theatre') or '').lower()
        if th in _TAIWAN_THEATRES and sg.get('category') in _KINETIC_EVENT_CATS \
                and _safe_level(sg.get('level', 0)) >= 5:
            return sg.get('short_text') or th
    return None

def _narrative_market_fragility(blufs):
    """MARKET FRAGILITY (economic axis) + the FRAGILITY x KINETIC compound read
    (Slice 3, Jun 13 2026). Black Swan #2 integration.

    Doctrine: sensors below, analyst above. The Market Watch detector
    (market_blackswan_detector.py) is the sensor -- it measures endogenous
    financial fragility (how dry the forest is) against ~100 years of market
    history. This GPI detector is the analyst: it surfaces that fragility on
    the economic axis AND reads it TOGETHER with the platform's kinetic layers.

    The flagship compound read: a fragile, AI/semiconductor-concentrated market
    (the dry forest) co-occurring with Taiwan-Strait kinetic signaling (the
    lightning aimed squarely at it). A Chinese move against Taiwan that
    threatens TSMC/semiconductor output would strike the exact sector driving
    the fragility -- neither tracker alone says much; together they are a
    compound pattern no market-only or conflict-only tool surfaces.

    Convergence framing, NOT prediction. Fragility describes present
    conditions; it does not forecast a drawdown, and the kinetic read does not
    forecast an invasion. The reader completes the inference.
    """
    frag = _redis_get(MARKET_FRAGILITY_BUNDLE_KEY) or {}
    band = frag.get('band')
    if not band or band == 'normal':
        return None  # nothing to surface this cycle

    composite = frag.get('composite')
    ai_active = bool(frag.get('ai_thematic_active'))
    feats = frag.get('active_features') or []
    lag = frag.get('historical_lag_read')
    disclaimer = frag.get('disclaimer', '')

    # ── ANALOG STRENGTH GUARD (Jul 26 2026) ───────────────────────────────
    # The bundle previously carried `top_analog` as a bare LABEL, so a 33%
    # match and an 80% match were indistinguishable at this altitude and the
    # GPI could headline a thin resemblance with full confidence. The Market
    # Watch page got this guard today; the GPI is the more important place to
    # have it, because a GPI signal travels further than a page a reader is
    # already scrutinising.
    #
    # Doctrine: a weak analog is CONTEXT, never a headline.
    ms = frag.get('match_strength') or {}
    ms_level = ms.get('level') or 'unknown'
    ms_pct = ms.get('top_pct')
    analog = frag.get('top_analog_detail') or {}
    sw = frag.get('so_what') or {}
    gsync = frag.get('global_sync') or {}

    analog_is_usable = ms_level in ('strong', 'moderate')

    def _analog_phrase():
        """One clause about the analog, honest about its weight."""
        if not analog.get('label'):
            return ''
        pct = f'{ms_pct:.0f}%' if isinstance(ms_pct, (int, float)) else 'low'
        if analog_is_usable:
            mech = analog.get('mechanism')
            base = (' The closest historical analog is %s (%s feature overlap)'
                    % (analog['label'], pct))
            return base + (' -- mechanism: %s.' % mech if mech else '.')
        # Thin match: name it, but say plainly that it does not carry weight.
        return (' No close historical analog: the nearest is %s at only %s feature '
                'overlap, which is context rather than a fit. Present conditions are '
                'not well described by anything in a ~100-year library -- itself a '
                'finding, not a gap.' % (analog['label'], pct))

    def _sync_phrase():
        """Global positioning -- lets this read see beyond a US-derived composite."""
        n = gsync.get('count_near_high')
        if not isinstance(n, int) or n < 3:
            return ''
        names = ', '.join(gsync.get('near_high') or [])
        return (' %d major markets (%s) sit within 5%% of their 24-month highs -- '
                'synchronised global positioning leaves no market placed to absorb '
                'a shock on behalf of the others.' % (n, names))

    # --- Compound check: AI/semiconductor fever x Taiwan-Strait kinetic ---
    asia = blufs.get('asia')
    tw_kinetic = False
    cn_high = False
    if asia:
        tw_kinetic = _has_signal_category(
            asia, 'kinetic_pressure', 'red_line_breached', 'kinetic_threshold',
            'deterrence_gap', 'china_two_front_convergence')
        cn_high = _has_signal_category(asia, 'theatre_high') and _level_of(asia) >= 4

    semis_compound = ai_active and (tw_kinetic or cn_high)

    band_label = band.upper()
    feat_phrase = ', '.join(f.replace('_', ' ') for f in feats[:4]) if feats else 'multiple fragility signals'

    if semis_compound:
        # v3.16.0 -- EARNED LEVEL. Fragility + signaling are CONDITIONS (L3,
        # standing). A real fall in the Taiwan-exposed semis instrument, or an
        # actual L5 kinetic event in the Taiwan theatre, lifts it to L4; both
        # together L5. Priority follows the level, so a condition can no longer
        # promote into the feed at L5 on priority alone.
        _mv = _semis_market_move()
        _ev = _taiwan_kinetic_event(asia)
        _lvl = 3 + int(_mv.get('state') == 'move') + int(bool(_ev))
        _basis = []
        _basis.append('market: ' + (_mv.get('phrase') or _mv.get('reason') or _mv.get('state')))
        _basis.append('kinetic: ' + ('L5 event -- %s' % _ev if _ev
                                     else 'signaling only, no L5 event in the Taiwan theatre'))
        _gate_txt = (' EVIDENCE GATE: L%d -- %s. A fragility reading and cross-strait '
                     'signaling are conditions, not events; this card earns L4 when the '
                     'exposed market actually falls or a kinetic event actually happens, '
                     'and L5 when both do.' % (_lvl, '; '.join(_basis)))
        _head = {3: 'Standing condition: market fragility %s with Taiwan-Strait signaling -- '
                    'the AI/semiconductor exposure, no market or kinetic event yet',
                 4: 'Market fragility %s AND Taiwan-Strait pressure -- the AI/semiconductor '
                    'convergence is now showing in evidence',
                 5: 'Market fragility %s AND a Taiwan-Strait event with the semiconductor '
                    'market falling -- the AI/semiconductor convergence is live'}[_lvl] % band_label
        return {
            'priority': {3: 8, 4: 11, 5: 13}[_lvl],
            'level_hint': _lvl,
            'fresh': False if _lvl == 3 else None,
            'evidence_gate': {'level': _lvl, 'market': _mv, 'kinetic_event': _ev},
            'category': 'market_fragility_semis_compound',
            'regions':  ['asia', 'global_market'],
            'icon':     '\U0001f9e8',  # 🧨
            'color':    '#dc2626',
            'pressure_type': 'economic',
            'headline': _head,
            'detail':   (f'The Market Watch fragility detector reads {band} (composite {composite}), with the '
                         'AI/data-center/semiconductor thematic running hot -- the concentration '
                         'that defines the current market is precisely the sector most exposed to a '
                         'Taiwan-Strait disruption. Simultaneously, the Asia-Pacific theater is '
                         'showing kinetic / cross-strait signaling. A Chinese move threatening '
                         'Taiwan semiconductor output would strike the exact sector driving market '
                         'fragility: a compound pattern in which an endogenously fragile market '
                         '(the dry forest) co-occurs with the one geopolitical fuse most precisely '
                         'aimed at it.' + _analog_phrase() + _sync_phrase() +
                         ' This is a convergence read of present conditions across two '
                         'independent layers, not a prediction that either a drawdown or a Taiwan '
                         f'contingency will occur. {("Pattern note: " + lag) if lag else ""}'
                         + _gate_txt),
        }

    # --- Economic-axis fragility surface (no kinetic co-occurrence yet) ---
    detail = ('The Market Watch fragility detector reads %s (composite %s) on endogenous '
              'market-fragility convergence, driven by %s. This measures how dry the forest '
              'is -- valuation, concentration, and momentum conditions consistent with '
              'historical pre-drawdown patterns -- not whether or when a drawdown occurs. '
              'No kinetic co-occurrence with the AI/semiconductor exposure this cycle; the '
              'compound read to watch is fragility plus a Taiwan-Strait disruption.%s%s %s'
              % (band, composite, feat_phrase, _analog_phrase(), _sync_phrase(),
                 ('Pattern note: ' + lag) if lag else ''))
    # v3.16.0 -- a fragility reading alone is a CONDITION: L3, standing. The
    # old map ran backwards ({'critical': 9, 'high': 11, 'elevated': 13}) --
    # the MILDEST band got the highest priority and promoted into the feed at
    # L5. The band still leads the headline; it no longer sets the level.
    return {
        'priority': 8,
        'level_hint': 3,
        'fresh': False,
        'category': 'market_fragility',
        'regions':  ['global_market'],
        'icon':     '\U0001f9a2',  # 🦢
        'color':    '#f59e0b' if band in ('elevated',) else '#ef4444',
        'pressure_type': 'economic',
        'headline': ('Market-fragility convergence reads %s -- %s'
                     % (band_label, feat_phrase)),
        'detail':   detail,
        # Carried up from the sensor so a GPI reader can CHECK the read rather
        # than take it. A signal nobody can falsify is a claim, not analysis.
        'watch':          sw.get('watch'),
        'analog_quality': ms_level,
    }


def _repricing_narrative(redis_key, offramp_label, category, regions):
    """Shared conflict-repricing market-belief read at GPI altitude (Slice 4c).

    Reads a conflict_repricing_detector GPI bundle (repricing:<theater>:gpi):
    whether informed capital is pricing the named off-ramp as durable, refusing
    to, or repricing an expanding war premium with no off-ramp present. The
    detector is the sensor; this is the analyst surfacing its read alongside the
    diplomatic track.

    Gated to gpi_eligible states (corroborated / contradicted / escalation
    repricing) -- mixed / insufficient / no_read stay off the rollup (absence
    stays honest). Priority is pinned BELOW the +11 global-level boost: a
    market-belief read never raises the global level; the kinetic trackers own
    that. Single region so it never takes the cross-theater +30 tier.

    Convergence framing, NOT prediction and NOT investment advice. The detail is
    the detector's already-estimative prose; the reader completes the inference.
    """
    bundle = _redis_get(redis_key) or {}
    if not isinstance(bundle, dict) or not bundle.get('gpi_eligible'):
        return None
    state = bundle.get('state')

    market_read  = bundle.get('market_read', '') or ''
    episode_read = bundle.get('episode_read', '') or ''
    detail = (market_read + (' ' + episode_read if episode_read else '')).strip()
    if not detail:
        return None

    if state == 'offramp_contradicted':
        pr, color = 10, '#f59e0b'
        headline = (f'Markets are not pricing the {offramp_label} as durable -- '
                    f'the tape diverges from the diplomatic track')
    elif state == 'offramp_corroborated':
        pr, color = 8, '#10b981'
        headline = (f'Markets are pricing the {offramp_label} as durable -- '
                    f'the tape and the diplomatic track agree')
    elif state == 'escalation_repricing':
        pr, color = 10, '#ef4444'
        headline = ('Markets repricing an expanding war-risk premium -- '
                    'no diplomatic off-ramp present')
    else:
        return None

    return {
        'priority': pr,
        'category': category,
        'regions':  regions,
        'icon':     '\U0001F4CA',  # bar chart
        'color':    color,
        'pressure_type': 'economic',
        'headline': headline,
        'detail':   detail,
    }


# ═══════════════════════════════════════════════════════════════
# v3.12.0 (Oct 6 2026) -- FRAGILITY x ARRIVING EXOGENOUS SHOCK
# ═══════════════════════════════════════════════════════════════
# THE LOOP market_blackswan_detector ASKS FOR AND NOTHING CLOSED.
#
# That module is a FRAGILITY index, not a shock detector, and it is explicit
# about the limit. 9/11 and COVID sit in its episode library as NULL CASES,
# filed on purpose, and its own ruling on an exogenous match reads:
#
#     "Exogenous analogs are NULL CASES and are in the library on purpose.
#      Earthquakes, attacks and pandemics carry no market pre-signal. If the
#      closest match is exogenous, the honest read is that this module has
#      little to say AND THE GPI KINETIC AND HUMANITARIAN AXES ARE THE WATCH.
#      Absence of a market warning is not absence of risk."
#
# Nothing performed that watch. The GPI reads the fragility bundle and the
# humanitarian BLUF, and has never put them in the same sentence.
#
# WHAT THIS DETECTOR DOES NOT DO
# ------------------------------
# It does not predict a drawdown, and it does not ask the fragility index to
# forecast a pandemic -- that is precisely the corruption the Market Watch
# module was built to refuse. Adding a health or geopolitical feature to a
# ~100-year endogenous composite would make a clean instrument dirty and tell
# you nothing it does not already say.
#
# The two layers stay independent and are READ TOGETHER:
#   dry forest    how brittle the market is right now (endogenous, measured)
#   lightning     a containment shock actually underway (observed, not forecast)
#
# Neither is a prediction. The conjunction is the finding, and the honest
# headline is a question about absorption, not about direction.
#
# THREE-STATE ON THE MARKET SIDE. An unreadable fragility bundle is NOT a calm
# market. When a shock is arriving and the forest cannot be measured, that is
# its own card and it says so -- the unread-versus-zero rule this platform
# keeps relearning.
# ═══════════════════════════════════════════════════════════════

# Containment behaviour at or above this GPI level counts as a shock that is
# actually underway rather than a story about one.
EXO_CONTAINMENT_MIN_LEVEL = 4
EXO_HEALTH_MIN_LEVEL = 5          # a high-severity health emergency alone also qualifies

# Export channels a containment action in that country would run through.
# DECLARED, never inferred: a country absent from this table is reported as
# "export exposure not instrumented", never as having none. Extend deliberately.
EXO_EXPORT_CHANNELS = {
    'russia':   'wheat, fertiliser, crude, gas, nickel, palladium',
    'ukraine':  'wheat, corn, sunflower oil, Black Sea corridor',
    'china':    'manufactured goods, rare earths, container shipping',
    'india':    'rice, generic pharmaceuticals',
    'brazil':   'soy, beef, iron ore',
    'drc':      'cobalt, copper',
    'chile':    'copper, lithium',
    'indonesia':'nickel, palm oil, thermal coal',
}


def _narrative_fragility_exogenous_watch(blufs):
    """A containment shock underway, read against measured market fragility.

    Doctrine: sensors below, analyst above. The Market Watch detector measures
    the forest; the humanitarian detector observes the lightning. This function
    is the analyst that reads them in one sentence, and it is careful to say
    what neither sensor can support.
    """
    hum = blufs.get('global_humanitarian')
    if not hum:
        return None

    sigs = _signals_of(hum) or []

    # ── THE SHOCK: containment ACTIONS, or a high-severity health emergency ──
    containment, health = [], []
    for sg in sigs:
        if not isinstance(sg, dict):
            continue
        cat = sg.get('category')
        try:
            lvl = int(sg.get('level') or 0)
        except (TypeError, ValueError):
            continue
        if cat == 'containment_behaviour' and lvl >= EXO_CONTAINMENT_MIN_LEVEL:
            containment.append(sg)
        elif cat == 'health_emergency' and lvl >= EXO_HEALTH_MIN_LEVEL:
            health.append(sg)
    if not (containment or health):
        return None

    shock = sorted(containment or health,
                   key=lambda x: -int(x.get('level') or 0))[0]
    country = shock.get('country') or 'an unnamed country'
    c_label = str(country).replace('_', ' ').title()
    actions = [k for k in (shock.get('matched_keywords') or [])][:4]
    action_phrase = ('; '.join(actions)) if actions else 'containment measures'

    # ── THE CLAIM GAP, when the humanitarian layer published one ──
    gap_clause = ''
    gap = hum.get('claim_behaviour_gap')
    if isinstance(gap, dict) and not gap.get('_error'):
        row = gap.get(country) or gap.get(str(country).split('_')[0]) or {}
        if isinstance(row, dict) and row.get('state') == 'diverging':
            gap_clause = (
                ' The humanitarian layer also reads the official language in %s as '
                'reassurance-dominant relative to the containment it is carrying out. '
                'That is a watch condition and NOT evidence of concealment -- '
                'vigorous precaution with calm public messaging is also what a '
                'well-run response looks like -- but it means the public claim is '
                'not a reliable guide to the size of the measures.' % c_label)

    # ── THE EXPORT CHANNEL, declared or honestly absent ──
    chan = EXO_EXPORT_CHANNELS.get(str(country).lower())
    if chan:
        export_clause = (
            ' Transmission channel if the measures widen: %s runs %s. Restrictions on '
            'movement, ports or air cargo reach prices through those channels before '
            'they reach any health statistic.' % (c_label, chan))
    else:
        export_clause = (
            ' Export exposure for %s is NOT instrumented in this detector. That is an '
            'unmeasured channel, not an absent one.' % c_label)

    # ── THE FOREST: three states, and unreadable is one of them ──
    frag = _redis_get(MARKET_FRAGILITY_BUNDLE_KEY)
    if not frag or not frag.get('band'):
        return {
            'priority': 12,
            'category': 'exogenous_shock_unmeasured_market',
            'regions':  ['global_humanitarian', 'global_market'],
            'icon':     '\U0001f32b\ufe0f',
            'color':    '#6b7280',
            'pressure_type': 'economic',
            'headline': ('Containment shock underway in %s while market fragility is '
                         'UNREAD this cycle' % c_label),
            'detail':   ('%s is carrying out observable containment -- %s. The Market '
                         'Watch fragility bundle could not be read this cycle, so this '
                         'platform cannot say how much absorptive capacity the market '
                         'has. UNREAD IS NOT CALM: no fragility reading is being '
                         'reported here, and none should be inferred.%s%s '
                         'Convergence, not prediction.'
                         % (c_label, action_phrase, gap_clause, export_clause)),
            'alert_stamped': False,
        }

    band = frag.get('band')
    composite = frag.get('composite')
    feats = frag.get('active_features') or []
    feat_phrase = ', '.join(f.replace('_', ' ') for f in feats[:4]) or 'no named features'
    analog = frag.get('top_analog_detail') or {}
    exo_analog = (analog.get('type') == 'exogenous_shock')

    if band == 'normal':
        detail_open = ('The Market Watch fragility detector reads NORMAL (composite %s): '
                       'on its own measures the market is not in a brittle state, so a '
                       'shock of this kind arrives into ordinary conditions. '
                       % composite)
        pr = 14
    else:
        detail_open = ('The Market Watch fragility detector reads %s (composite %s), '
                       'driven by %s -- a measure of how much absorptive capacity the '
                       'market has, not of what is about to happen to it. A shock '
                       'arriving into that state is a different event from the same '
                       'shock arriving into a calm one. ' % (band.upper(), composite, feat_phrase))
        pr = {'critical': 10, 'high': 11, 'elevated': 13}.get(band, 13)

    null_clause = (
        ' The fragility module states its own limit here and this card repeats it '
        'rather than working around it: exogenous events -- earthquakes, attacks, '
        'pandemics -- carry NO market pre-signal, and its closest historical analog '
        'is itself an exogenous null case. Absence of a market warning is not '
        'absence of risk.' if exo_analog else
        ' The fragility module carries no pre-signal for exogenous events of this '
        'kind by design; its reading describes the forest, never the lightning.')

    return {
        'priority': pr,
        'category': 'fragility_exogenous_watch',
        'regions':  ['global_humanitarian', 'global_market'],
        'icon':     '\U0001f9a0',    # microbe
        'color':    '#ef4444' if band in ('high', 'critical') else '#f59e0b',
        'pressure_type': 'economic',
        'headline': ('Containment shock underway in %s against a %s market-fragility '
                     'reading' % (c_label, str(band).upper())),
        'detail':   (detail_open +
                     'Simultaneously, %s is carrying out observable containment: %s. '
                     'These are two independent layers -- one endogenous and measured '
                     'over a century of market history, one observed in this week\'s '
                     'reporting -- and neither forecasts the other.%s%s%s '
                     'The question this card raises is about ABSORPTION, not '
                     'direction: how much capacity is there if these measures widen. '
                     'Convergence, not prediction.'
                     % (c_label, action_phrase, null_clause, gap_clause, export_clause)),
        'alert_stamped': True,
    }


def _narrative_conflict_repricing(blufs):
    """Israel / US-Iran off-ramp market-belief read (Slice 3, Jun 18 2026)."""
    return _repricing_narrative('repricing:israel:gpi', 'US-Iran off-ramp',
                                'conflict_repricing_israel', ['me'])


def _narrative_conflict_repricing_europe(blufs):
    """Europe / Russia-Ukraine off-ramp market-belief read (Slice 4c, Jun 19 2026)."""
    return _repricing_narrative('repricing:europe_ukraine:gpi',
                                'Russia-Ukraine off-ramp',
                                'conflict_repricing_europe', ['europe'])


def _narrative_global_baseline(blufs):
    """Fallback: when no narratives detected, summarize the elevated regions."""
    elevated = [(r, _level_of(b)) for r, b in blufs.items() if _level_of(b) >= 3]
    if elevated:
        elevated.sort(key=lambda x: x[1], reverse=True)
        top_region = REGION_DISPLAY[elevated[0][0]]['name']
        return {
            'priority': 3,
            'category': 'global_warning',
            'regions':  [r for r, _ in elevated],
            'icon':     '\u26a0\ufe0f',  # ⚠️
            'color':    '#f97316',
            'headline': f'{top_region} at elevated tempo -- no cross-theater convergence detected',
            'detail':   (f'Highest current pressure: {top_region} at L{elevated[0][1]}. '
                         f'No cross-theater convergence narratives triggered; regional pressures '
                         f'remain compartmented for now.'),
        }
    return {
        'priority': 1,
        'category': 'global_baseline',
        'regions':  list(blufs.keys()),
        'icon':     '\U0001f30d',  # 🌍
        'color':    '#6b7280',
        'headline': 'Global posture at baseline -- all theaters at monitoring or below',
        'detail':   'No theaters above warning level. Routine OSINT signal collection ongoing.',
    }


def _narrative_multiaxis_convergence(blufs):
    """Cross-theater convergence from the multi-axis detector (convergence_detector.py).

    Surfaces two things the per-region BLUFs cannot see on their own:
      1. GLOBAL COMMODITY CONDITIONS -- a single commodity headline registering across
         many exposed countries at once (a broad market condition, not a country-specific
         shock; relocated here from per-country scoring so it stops inflating tiers).
      2. The strongest genuine per-country MULTI-AXIS convergences -- countries where
         several independent reporting streams are elevated at the same time.

    Convergence framing only: reports co-active streams, never predicts action.
    Imports build_convergence directly (same backend) -- pure read, no side effects.
    """
    try:
        from convergence_detector import build_convergence
        cax = build_convergence()
    except Exception as e:
        print(f"[GPI] multi-axis convergence detector unavailable: {str(e)[:120]}")
        return None

    AXIS_WORD = {
        'kinetic':      'armed-conflict reporting',
        'commodity':    'commodity-news pressure',
        'rhetoric':     'escalatory official rhetoric',
        'humanitarian': 'humanitarian distress reporting',
    }
    cards = []

    # (1) Global commodity conditions -- broad and cross-theater by nature.
    # v3.16.0 -- BREADTH IS NOT NEWS. One headline registering across N exposed
    # countries is a coverage count. The card now surfaces only when the
    # commodity has EARNED L4+ on the commodity tracker's evidence ladder (a
    # confirmed price move and/or physical disruption), and takes that level.
    # A news-only commodity (L3) gets no card: its own economic signal already
    # says "watch, not yet act", and a second card would repeat it.
    _earned = {}
    for _sg in _signals_of(blufs.get('global_commodity') or {}):
        _c = _sg.get('commodity')
        if _c:
            _earned[_c] = (_safe_level(_sg.get('level', 0)), _sg.get('level_basis'),
                           _sg.get('short_text') or '')
    for g in (cax.get('global_conditions') or [])[:2]:
        _cid = str(g.get('commodity', 'x'))
        _lv, _lb, _st = _earned.get(_cid, (0, None, ''))
        if _lv < 4:
            print('[GPI] breadth card for %s suppressed: commodity reads L%s (%s) -- '
                  'breadth of coverage is not evidence' % (_cid, _lv, _lb or 'not admitted'))
            continue
        n = g.get('country_count', 0)
        nm = (g.get('commodity_name') or g.get('commodity') or 'commodity')
        sample = ', '.join((g.get('countries') or [])[:6])
        cards.append({
            'priority': {4: 10, 5: 12}.get(_lv, 10),
            'level_hint': _lv,
            'evidence_gate': {'commodity_level': _lv, 'level_basis': _lb},
            'category': 'global_commodity_' + _cid,
            'regions':  ['global_commodity'],
            'icon':     '\U0001f6e2\ufe0f',  # oil drum
            'color':    '#f59e0b',
            'headline': f'Global {nm.lower()} pressure -- {n} exposed countries off one shared headline',
            'detail':   (f'A single {nm.lower()} story is registering as commodity-news pressure across '
                         f'roughly {n} exposed countries at once ({sample}{" and others" if n > 6 else ""}). '
                         f'"Commodity-news pressure" here means the weighted volume and severity of matched '
                         f'reporting -- it is NOT a price move and NOT a country-specific supply shock. It '
                         f'surfaces at the global altitude precisely because it is broad: a market-wide '
                         f'condition rather than convergence on any one country. Driving headline: '
                         f'"{(g.get("headline") or "")[:140]}". EVIDENCE GATE: surfaced because '
                         f'{nm.lower()} has earned L{_lv} on the commodity ladder '
                         f'({(_lb or "").replace("_", " ")}) -- {_st[:120]}'),
        })

    # (2) Strongest genuine per-country multi-axis convergences
    strong = [r for r in cax.get('records', []) if r.get('active_count', 0) >= 3][:5]
    if strong:
        def _desc(r):
            streams = ', '.join(AXIS_WORD.get(a, a) for a in r.get('active_axes', []))
            return f"{r['display']} ({r['tier']}: {streams})"
        regions = sorted({(rr['axes'].get('rhetoric') or {}).get('region')
                          for rr in strong if rr['axes'].get('rhetoric')})
        regions = [r for r in regions if r] or ['me']
        cards.append({
            'priority': 10,
            'category': 'multiaxis_convergence',
            'regions':  regions,
            'icon':     '\U0001f500',  # twisted arrows
            'color':    '#38bdf8',
            'headline': f"Multi-axis convergence -- {strong[0]['display']} leads at {strong[0]['tier']}",
            'detail':   ('Countries where several INDEPENDENT reporting streams are elevated at the same '
                         'time -- the more streams that agree, the less likely the reading is noise in any '
                         'single feed. Active now: ' + '; '.join(_desc(r) for r in strong[:4]) + '. '
                         '(Tiers: quad = all four streams, triple = three, dual = two.) This is a convergence '
                         'reading -- independent streams agreeing -- not a forecast of action.'),
        })

    return cards or None


def _narrative_iran_axis_convergence(blufs):
    """
    CONVERGENCE: Iran-aligned proxy fronts elevated simultaneously -- the Axis
    acting as one arena (Unity of Fronts / wahdat al-sahat). The read is the
    SIMULTANEITY plus Iran's standing command posture, NOT a kinetic body-count.
    As the acute missile-exchange phase recedes, THIS is the narrative that carries
    the Iran story: continued influence over proxies, chokepoint leverage, and
    oil/shipping repricing -- pressure that persists after the volleys stop.

    Self-contained RECOMPUTE (mirrors the Iran tracker index, but owned here):
      - proxy slices  rhetoric:crosstheater:fingerprints[<theater>] {ts, level,
                      top_phrases, named_targets}. Set: Yemen, Lebanon, Iraq, Gaza,
                      West Bank. Freshness-gated <=24h; L2+ counts.
      - Syria         RUPTURED node -- post-Dec-2024 the corridor is severed; counted
                      OUT of activation and surfaced as the broken land bridge, not a
                      live limb (its L2+ now reflects forces hostile to Tehran).
      - iran slice    hub posture READ straight from ['iran']: unity_of_fronts_level,
                      is_command_node, level (NOT recomputed).

    Absence-honest: stale/unwritten proxies skipped; absent mediation named as absent,
    never inferred. Mediation (Oman/Qatar) is OPPOSITE-sign -- it sits BESIDE the
    alarm as a counterweight, it does NOT net against it.

    Priority is kept BELOW the +11 kinetic global-boost: an INFLUENCE convergence
    surfaces as a prominent narrative but never inflates the kinetic-weighted global
    level (that would mix axes). It rises naturally as the kinetic detectors quiet.

    GATE: breadth, not depth. Fires when >=3 proxies active (L2+), OR Unity of Fronts
    elevated (>=2) with >=2 proxies active. Otherwise silent.
    """
    PROXY_THEATERS = ['yemen', 'lebanon', 'iraq', 'gaza', 'west_bank']
    FRESH_HOURS  = 24
    ACTIVE_LEVEL = 2
    LADDER = {0: 0, 1: 1, 2: 2, 3: 4, 4: 5, 5: 5}  # 5-proxy rescale; breadth jump at 3 preserved

    ct = _redis_get('rhetoric:crosstheater:fingerprints')
    if not isinstance(ct, dict):
        return None

    now = datetime.now(timezone.utc)
    def _fresh(fp):
        try:
            return (now - datetime.fromisoformat(fp['ts'])).total_seconds() / 3600.0 <= FRESH_HOURS
        except Exception:
            return False

    active = {}
    all_phrases, all_targets = {}, {}
    for name in PROXY_THEATERS:
        fp = ct.get(name)
        if not isinstance(fp, dict) or not _fresh(fp):
            continue
        lvl = _safe_level(fp.get('level', 0))
        if lvl < ACTIVE_LEVEL:
            continue
        phrases = fp.get('top_phrases', []) or []
        targets = fp.get('named_targets', []) or []
        active[name] = {'level': lvl, 'phrases': phrases, 'targets': targets}
        for p in phrases:
            all_phrases.setdefault(str(p)[:30].lower(), []).append(name)
        for t in targets:
            all_targets.setdefault(t, []).append(name)

    # -- Lebanon spoke de-linking (consumes Lebanon's framework fingerprint) --
    # Mirrors the Syria rupture: 'active' implementation = spoke leaving the Axis,
    # counted OUT; 'partial' = wobbling (counted, flagged); 'none' (current Stalled
    # reality) = full proxy. Dormant until Lebanon's framework actually advances.
    lfp = ct.get('lebanon') if isinstance(ct.get('lebanon'), dict) else {}
    lebanon_delinking = (str(lfp.get('spoke_delinking', 'none') or 'none').lower()
                         if _fresh(lfp) else 'none')
    if lebanon_delinking == 'active' and 'lebanon' in active:
        del active['lebanon']

    n = len(active)
    proxy_level = LADDER[min(n, 5)]
    shared_phrases = {p: t for p, t in all_phrases.items() if len(t) >= 2}
    shared_targets = {t: ns for t, ns in all_targets.items() if len(ns) >= 2}
    if shared_phrases and proxy_level < 5:
        proxy_level = min(proxy_level + 1, 5)
    if shared_targets and proxy_level < 5:
        proxy_level = min(proxy_level + 1, 5)

    # Syria -- ruptured corridor (counted OUT; surfaced as severed land bridge)
    sfp = ct.get('syria')
    syria_ruptured = (isinstance(sfp, dict) and _fresh(sfp)
                      and _safe_level(sfp.get('level', 0)) >= ACTIVE_LEVEL)

    # Hub posture -- READ from the iran slice (not recomputed)
    iran_fp = ct.get('iran') if isinstance(ct.get('iran'), dict) else {}
    uof_level     = _safe_level(iran_fp.get('unity_of_fronts_level', 0))
    uof_grievance = iran_fp.get('unity_of_fronts_grievance')
    is_command    = bool(iran_fp.get('is_command_node'))
    iran_level    = _safe_level(iran_fp.get('level', 0))

    # Venezuela -- Iran EXPEDITIONARY node (Caribbean foothold). Read the hub's
    # far-node presence from VZ's multi-hub slice; NEVER folded into the regional
    # proxy count (node_class 'expeditionary' = global reach, not a Levant front).
    # This is Iran's GLOBAL spread surfacing at the GPI, per the three-altitude rule.
    vfp = ct.get('venezuela') if isinstance(ct.get('venezuela'), dict) else {}
    vz_iran_reach = 0
    if _fresh(vfp) and str(vfp.get('node_class', '')).lower() == 'expeditionary':
        _vhub = (vfp.get('hub_presence', {}) or {}).get('iran', {}) or {}
        vz_iran_reach = _safe_level(_vhub.get('level', 0))

    converged = (n >= 3) or (uof_level >= 2 and n >= 2)
    if not converged:
        return None

    # Mediation counterweight (forward hook; opposite-sign, never nets against alarm)
    mediation = []
    for med in ('oman', 'qatar'):
        mfp = ct.get(med)
        if isinstance(mfp, dict) and _fresh(mfp):
            if mfp.get('mediation_active') or _safe_level(mfp.get('level', 0)) >= 2:
                mediation.append(med.title())

    # Chokepoint / oil drift (absence-honest -- from observed proxy phrases ONLY)
    MARITIME = ('hormuz', 'strait', 'shipping', 'tanker', 'cargo', 'red sea', 'bab el', 'maritime')
    chokepoint = any(any(tok in ' '.join(d['phrases']).lower() for tok in MARITIME)
                     for d in active.values())

    names_titled = sorted(t.replace('_', ' ').title() for t in active)

    # ---- Prose: LEAD with Unity of Fronts, drift toward influence ----
    if uof_level >= 2:
        lead = ("Unity of Fronts (wahdat al-sahat) is elevated -- %s: Iran-aligned fronts are "
                "speaking and acting as a single arena rather than as separate theaters"
                % _ts_level(uof_level))
        if uof_grievance:
            lead += " around a shared grievance (%s)" % str(uof_grievance)
        lead += ". "
        headline = ("Iran Axis convergence -- Unity of Fronts %s, %d proxy fronts active"
                    % (_ts_level(uof_level), n))
    else:
        lead = "Iran-aligned proxy fronts are simultaneously active across separated theaters. "
        headline = "Iran Axis convergence -- %d proxy fronts active simultaneously" % n

    detail = lead
    detail += ("Active fronts: " + ", ".join(names_titled)
               + " (recomputed activation %s). " % _ts_level(proxy_level))
    if shared_targets:
        detail += ("Shared named targets across fronts (" + ", ".join(list(shared_targets)[:3])
                   + ") sharpen the read from parallel noise toward coordination. ")
    elif shared_phrases:
        detail += ("Synchronized framing across fronts is consistent with coordination rather than "
                   "coincidence. ")
    if syria_ruptured:
        detail += ("Syria registers active but is read as the SEVERED land bridge, not a live limb -- "
                   "post-2024 its signal reflects forces hostile to Tehran, so it is counted out of the "
                   "activation and surfaced as the broken corridor. ")
    if lebanon_delinking == 'active':
        detail += ("Lebanon is read as a DE-LINKING spoke: under the signed Trilateral Framework, "
                   "implementation signals are advancing, so its front activity is counted OUT of the "
                   "Axis activation and surfaced as a spoke contracting away from Tehran. ")
    elif lebanon_delinking == 'partial':
        detail += ("Lebanon's signed-framework implementation is contested -- the spoke is wobbling: "
                   "counted in the activation but flagged as a potential off-ramp if implementation advances. ")
    if vz_iran_reach >= ACTIVE_LEVEL:
        detail += ("Iran's reach extends to the Caribbean: Venezuela registers Iranian expeditionary "
                   "presence (%s) as a FAR node -- surfaced as global reach, NOT counted in the regional "
                   "proxy activation. The Axis arena (Levant) and the expeditionary footprint (Caribbean) "
                   "are distinct reads; together they mark the span of Iran's influence rather than its "
                   "kinetic weight. " % _ts_level(vz_iran_reach))
    if is_command or iran_level >= 2:
        detail += "Tehran's own posture reads as command-node (hub) rather than a co-equal front. "
    if chokepoint:
        detail += ("Pressure is migrating from open kinetic exchange toward chokepoint leverage -- "
                   "maritime and shipping signals in the front phrases are consistent with Iran "
                   "exercising influence through the Strait and Red Sea rather than direct volleys. ")
    if mediation:
        detail += ("A mediation track is concurrently active (" + ", ".join(mediation) + "); it sits "
                   "BESIDE this convergence as an off-ramp counterweight and does not net against the "
                   "proxy-pressure read. ")
    else:
        detail += "No active mediation counterweight detected this cycle. "
    detail += ("This composite is a CONVERGENCE indicator, NOT a probability of action; each front is "
               "independently sourced and the reader completes the inference.")

    high_band = (proxy_level >= 4) or (uof_level >= 3)
    priority  = 10 if high_band else 9   # below +11 kinetic boost -- influence, not kinetic escalation

    return {
        'priority': priority,
        'category': 'iran_axis_convergence',
        'regions':  ['me'],
        'icon':     '\U0001f517',   # link/chain -- fronts linked as one arena (NOT a flag)
        'color':    '#be185d',      # deep rose -- distinct from kinetic crimson / turkey orange / russia-iran purple
        'headline': headline,
        'detail':   detail,
    }


def _narrative_turkey_regional_convergence(blufs):
    """
    CONVERGENCE: Turkey's fingerprints elevated simultaneously across SEPARATED
    theaters. The read is the simultaneity, NOT a Turkey scorecard. Two written
    conventions are unified from shared Redis (cross-backend):

      - spoke:turkey:<c>           reactive periphery (Europe). Polarity in
                                   'relationship' (alignment / friction / rivalry).
                                   Live writers: greece, cyprus, azerbaijan.
      - turkey:theater_footprints  active projection theaters (ME). Turkey pushing
                                   hard-power/economic/diplomatic INTO a theater.
                                   Live writers: libya (spoke #1), syria (spoke #2).
      - crosstheater['turkey']     the Turkey tracker's OWN read of relationships it
                                   tracks but the theater does not: israel_friction
                                   (Israel friction node) + lebanon_vector (Lebanon
                                   projection node). Israel/Lebanon carry no native
                                   Turkey actor, so this slice is their honest source.
                                   Freshness-gated (<=48h) -- a stale slice is skipped.

    Absence-honest: unwritten nodes are skipped, and a theater sourced twice is
    de-duplicated to the hottest read. New projection theaters join automatically
    (the footprints dict is iterated); new periphery spokes join via PERIPHERY_SPOKES.

    GATE (tunable): a genuine cross-theater convergence requires breadth, not a
    single hot spot. Fires when >=3 theaters are active (L2+), OR >=2 active spanning
    BOTH a projection theater AND a peripheral one. Otherwise stays silent.
    """
    PERIPHERY_SPOKES = ['greece', 'cyprus', 'azerbaijan', 'armenia']  # spoke:turkey:<c> writers (Israel arrives via the self-slice, block 3; armenia joined Jul 12 2026 -- normalization-track polarity)
    ACTIVE_LEVEL     = 2     # L2+ = concrete moves, not declaratory rhetoric
    REL_LABEL = {
        'peer_rivalry': 'rivalry', 'rivalry': 'rivalry',
        'friction': 'friction', 'alignment': 'alignment', 'axis': 'alignment',
    }

    nodes = []  # each: {theater, level, kind, descriptor, top}

    # 1) Reactive periphery -- individual spoke:turkey:<c> keys
    for c in PERIPHERY_SPOKES:
        fp = _redis_get('spoke:turkey:' + c)
        if not isinstance(fp, dict):
            continue
        nodes.append({
            'theater':    c,
            'level':      _safe_level(fp.get('level', 0)),
            'kind':       'periphery',
            'descriptor': REL_LABEL.get(str(fp.get('relationship', '')).lower(), 'friction'),
            'top':        fp.get('top_signal', ''),
        })

    # 2) Active projection -- shared turkey:theater_footprints {theater: {...}}
    footprints = _redis_get('turkey:theater_footprints')
    if isinstance(footprints, dict):
        for theater, fp in footprints.items():
            if not isinstance(fp, dict):
                continue
            nodes.append({
                'theater':    str(theater),
                'level':      _safe_level(fp.get('level', 0)),
                'kind':       'projection',
                'descriptor': str(fp.get('mode', 'dormant')).lower(),
                'top':        (fp.get('top_phrases') or [''])[0],
            })

    # 3) Turkey self-slice -- rhetoric:crosstheater:fingerprints['turkey']. The Turkey
    #    tracker's own read of relationships the theater trackers do NOT carry: Israel
    #    (friction) and Lebanon (projection vector). Israel/Lebanon have no native Turkey
    #    actor, so this slice is their honest source. Freshness-gated to <=48h.
    FRESH_HOURS           = 48
    ISRAEL_FRICTION_LEVEL = {'normal': 0, 'simmering': 1, 'elevated': 2, 'high': 3}
    LEBANON_VECTOR_LEVEL  = {'dormant': 0, 'rhetoric': 1, 'soft_power': 2,
                             'economic': 2, 'security': 3, 'kinetic_risk': 4}
    LEBANON_VECTOR_MODE   = {'dormant': 'dormant', 'rhetoric': 'diplomatic',
                             'soft_power': 'soft_power', 'economic': 'economic',
                             'security': 'hard_power', 'kinetic_risk': 'hard_power'}
    _ct = _redis_get('rhetoric:crosstheater:fingerprints')
    _tk = _ct.get('turkey') if isinstance(_ct, dict) else None
    if isinstance(_tk, dict):
        _fresh = False
        try:
            _age_h = (datetime.now(timezone.utc)
                      - datetime.fromisoformat(_tk['ts'])).total_seconds() / 3600.0
            _fresh = _age_h <= FRESH_HOURS
        except Exception:
            _fresh = False
        if _fresh:
            _isr = str(_tk.get('israel_friction', 'normal')).lower()
            nodes.append({
                'theater':    'israel',
                'level':      ISRAEL_FRICTION_LEVEL.get(_isr, 0),
                'kind':       'periphery',
                'descriptor': 'friction',
                'top':        'Turkey-Israel friction: ' + _isr,
            })
            _lv = str(_tk.get('lebanon_vector', 'dormant')).lower()
            nodes.append({
                'theater':    'lebanon',
                'level':      max(LEBANON_VECTOR_LEVEL.get(_lv, 0),
                                  _safe_level(_tk.get('lebanon_vector_stage', 0))),
                'kind':       'projection',
                'descriptor': LEBANON_VECTOR_MODE.get(_lv, 'dormant'),
                'top':        'Turkey-Lebanon vector: ' + _lv,
            })

    # De-duplicate by theater (a theater sourced twice -> keep the hottest read)
    _best = {}
    for _n in nodes:
        _cur = _best.get(_n['theater'])
        if _cur is None or _n['level'] > _cur['level']:
            _best[_n['theater']] = _n
    nodes = list(_best.values())

    if not nodes:
        return None

    active          = [n for n in nodes if n['level'] >= ACTIVE_LEVEL]
    theaters_active = {n['theater'] for n in active}
    has_projection  = any(n['kind'] == 'projection' for n in active)
    has_periphery   = any(n['kind'] == 'periphery'  for n in active)

    converged = (len(theaters_active) >= 3) or \
                (len(active) >= 2 and has_projection and has_periphery)
    if not converged:
        return None

    peak = max(active, key=lambda n: n['level'])

    # Projection clause (theaters + mode mix)
    proj_th   = sorted({n['theater'].title() for n in active if n['kind'] == 'projection'})
    proj_mode = sorted({n['descriptor'] for n in active
                        if n['kind'] == 'projection' and n['descriptor'] != 'dormant'})
    # Periphery clause (grouped by polarity)
    peri_by = {}
    for n in active:
        if n['kind'] == 'periphery':
            peri_by.setdefault(n['descriptor'], []).append(n['theater'].title())

    parts = []
    if proj_th:
        mode_txt = ('/'.join(m.replace('_', '-') for m in proj_mode) + ' ') if proj_mode else ''
        parts.append(mode_txt + 'projection in ' + ' and '.join(proj_th))
    peri_bits = []
    for rel in ('alignment', 'friction', 'rivalry'):
        if peri_by.get(rel):
            peri_bits.append(rel + ' with ' + ' and '.join(sorted(peri_by[rel])))
    if peri_bits:
        parts.append('; '.join(peri_bits))
    spread = '; '.join(p for p in parts if p)

    headline = ("Turkey convergence -- %d fingerprints elevated across %d theaters"
                % (len(active), len(theaters_active)))
    detail = (
        "Turkish signals are simultaneously elevated across separated theaters: " + spread + ". "
        "Peak: " + peak['theater'].title() + " (L" + str(peak['level']) + "). Concurrent hard-power "
        "projection and peripheral friction across theaters that do not share a local driver is "
        "consistent with a phase of assertive, multi-front Turkish posture -- the breadth that has "
        "historically accompanied Ankara pressing several files at once. This is a CONVERGENCE "
        "indicator, NOT a probability of action; each node is independently sourced and the reader "
        "completes the inference."
    )

    return {
        'priority': 13,
        'category': 'turkey_regional_convergence',
        'regions':  sorted({'europe' if n['kind'] == 'periphery' else 'me' for n in active}),
        'icon':     '\U0001f9ed',   # compass -- projection/convergence, deliberately NOT a Turkey flag
        'color':    '#ea580c',      # burnt orange -- distinct from russia_iran purple / arctic blue
        'headline': headline,
        'detail':   detail,
    }


# Registry of detectors. Order doesn't matter -- sorting is by priority.
NARRATIVE_DETECTORS = [
    _narrative_nuclear_signaling_global,
    _narrative_iran_strike_window,                       # convergence framing (May 22 2026)
    _narrative_iran_deescalation,                        # off-ramp at altitude 3 (Jun 18 2026)
    _narrative_china_taiwan_takeover,
    _narrative_scs_first_island_chain_axis,             # Jun 2026 -- China+Taiwan+Vietnam SCS arc
    _narrative_dual_chokepoint,
    _narrative_russia_iran_axis,
    _narrative_arctic_convergence,
    _narrative_belt_and_road_resource_leverage,          # v3.6.0 May 23 2026 — multi-anchor BRI detector
    _detect_convergences_from_registry,                  # registry-driven (returns LIST of narratives)
    _narrative_dprk_russia_axis,
    _narrative_wha_cascade,
    _narrative_houthi_fragility,
    _narrative_multiaxis_convergence,                    # multi-axis + global-commodity (Jun 6 2026)
    _narrative_food_stress_convergence,                  # food x kinetic x humanitarian (Jun 10 2026)
    _narrative_market_fragility,                         # market fragility x Taiwan semis (Black Swan #2, Jun 13 2026)
    _narrative_fragility_exogenous_watch,                # fragility x arriving containment shock (Oct 6 2026)
    _narrative_conflict_repricing,                       # off-ramp market-belief read (Slice 3, Jun 18 2026)
    _narrative_conflict_repricing_europe,                # Europe off-ramp market-belief read (Slice 4c, Jun 19 2026)
    _narrative_turkey_regional_convergence,              # Turkey cross-theater convergence (projection + periphery, Jun 28 2026)
    _narrative_iran_axis_convergence,                    # Iran Unity-of-Fronts / proxy-arena influence read (Jun 29 2026)
    _narrative_hub_network_breadth,                      # ANY hub: depth (countries/region) or span (regions) — Slice 2, Aug 2026
    _narrative_contested_spoke,                          # MANY hubs on ONE node — Abu al-Duhur geometry, Aug 2026
    _narrative_emplacement_precursor,                    # redline tempo × denial tempo — tasking trigger, Aug 2026
    _narrative_policy_branch_convergence,                # Lebanon/Gaza/West Bank branching together — Slice 5, Aug 2026
    _narrative_israel_formation_window,                  # caretaker Israel x hot Iran axis — Oct 28 2026
    # Fallback always last
    _narrative_global_baseline,
]


def _detect_narratives(blufs):
    """Run all detectors and return narratives sorted by priority descending.

    Detectors may return either:
      - a single narrative dict
      - a list of narrative dicts (e.g. registry-driven convergence detector)
      - None (no match)
    """
    narratives = []
    for detector in NARRATIVE_DETECTORS:
        try:
            result = detector(blufs)
            if not result:
                continue
            if isinstance(result, list):
                # List-returning detector — extend
                narratives.extend(result)
            else:
                # Single-narrative detector — append
                narratives.append(result)
        except Exception as e:
            print(f'[GPI v2.0] Narrative detector error ({detector.__name__}): {str(e)[:120]}')
    narratives.sort(key=lambda n: n.get('priority', 0), reverse=True)
    # v3.16.0 -- the fallback says "no cross-theater convergence detected".
    # Live Oct 29 it sat in the toplines beside 12 convergence narratives,
    # contradicting the page. It now appears only when it is true.
    if any(n.get('category') not in ('global_baseline', 'global_warning') for n in narratives):
        narratives = [n for n in narratives
                      if n.get('category') not in ('global_baseline', 'global_warning')]

    # Deduplicate categories (in case fallback fires alongside others)
    seen = set()
    deduped = []
    for n in narratives:
        cat = n.get('category', '')
        if cat not in seen:
            seen.add(cat)
            deduped.append(n)
    return deduped


# ============================================================
# L5 NOVELTY GATE  (v3.12.0, Oct 28 2026)
# ============================================================
# Rachel, Oct 28: "if our GPI always is L5 -- then it means nothing." A gauge
# pinned at maximum carries no information and trains readers to stop looking.
#
# SEVERITY vs MOTION. Every regional page keeps its honest L5: a war is a war.
# The GLOBAL index answers a different question -- is the world getting
# worse THIS fortnight? So global L5 is reserved for a NEW L5 front:
#
#   fresh      -- a theatre reached kinetic L5 within L5_NOVELTY_DAYS (14)
#   re-ignited -- a theatre that was below L5 for L5_EPISODE_GAP_DAYS (3)+
#                 and came back (a new episode, not flicker)
#   breach     -- any L6 red-line breach signal bypasses the gate entirely
#
# Otherwise global reads L4 with the label SUSTAINED CONFLICT and a day count
# per theatre. That label is the guard against the OPPOSITE error the
# L5_ASSERTION_RULE warns about: the reader must never mistake "nothing new"
# for "nothing happening". L4 here does NOT mean COERCION.
#
# Precedent: the Russia "war floor" ruling (Option B) -- L4 is the active-
# combat baseline, L5 is escalation ABOVE the grind. This generalises it.
#
# DAY ZERO. On first deploy there is no onset history. Every theatre already
# at L5 is SEEDED as sustained ("since at least <deploy date>") rather than
# treated as new -- otherwise the gate would do nothing for its first 14 days.
# Seeded day counts are floors and are labelled as such, never as a start date.
#
# ABSENCE-HONEST. If Redis cannot be read, the gate does not run and says so:
# it will not call a front "new" or "sustained" without its history.
L5_NOVELTY_DAYS     = 14      # Leo's ruling, Oct 28 2026
L5_EPISODE_GAP_DAYS = 3       # below L5 this long = the episode ended
L5_ONSET_KEY        = 'gpi:l5_onsets'
L5_ONSET_TTL        = 400 * 24 * 3600
L5_FORGET_DAYS      = 60      # drop a theatre's record after 60 days off L5
SUSTAINED_LABEL     = 'SUSTAINED CONFLICT'
SUSTAINED_COLOR     = '#ef4444'

# Module-level so the prose builder can read the gate without a signature change
# rippling through every caller. Reset at the top of each build.
_LAST_LEVEL_GATE = {}
_LAST_COMMODITY_CAP = {}   # v3.16.0 -- commodity evidence cap report


def _redis_get_checked(key):
    """Like _redis_get, but tells 'key absent' apart from 'Redis failed'.
    Returns (value_or_None, ok)."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None, False
    try:
        resp = requests.get(f'{UPSTASH_REDIS_URL}/get/{key}',
                            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                            timeout=5)
        if resp.status_code != 200:
            return None, False
        result = resp.json().get('result')
        return (json.loads(result) if result else None), True
    except Exception as e:
        print(f'[GPI L5 gate] Redis GET error ({key}): {e}')
        return None, False


def _l5_theatres(blufs):
    """{theatre: region} for every theatre carrying a KINETIC signal at L5.

    Kinetic only: an L5 humanitarian or economic reading is real, but it is
    not 'active conflict' and must not hold the conflict gauge open. A region
    whose BLUF says L5 but exposes no L5 signal is kept as 'region:<r>' so a
    thin payload can never hide a war from the gate."""
    out = {}
    for region, bluf in (blufs or {}).items():
        if not bluf:
            continue
        found = False
        for s in _signals_of(bluf):
            if _safe_level(s.get('level', 0)) < 5:
                continue
            if _infer_pressure_type(s) != PRESSURE_KINETIC:
                continue
            th = str(s.get('theatre') or '').strip().lower()
            if not th or th in _UNGROUPED_THEATRES or th == region:
                th = f'region:{region}'
            out.setdefault(th, region)
            found = True
        # Geographic regions only: a pseudo-region (humanitarian, commodity,
        # food) at L5 is severity on a NON-kinetic axis, never a war front.
        if not found and region in CARD_ORDER and _level_of(bluf) >= 5:
            out.setdefault(f'region:{region}', region)
    return out


def _l6_breach_present(blufs):
    for region, bluf in (blufs or {}).items():
        for s in _signals_of(bluf):
            if _safe_level(s.get('level', 0)) >= 6:
                return str(s.get('theatre') or region)
    return None


def _theatre_display(th):
    if th.startswith('region:'):
        r = th.split(':', 1)[1]
        return REGION_DISPLAY.get(r, {}).get('name', r.upper())
    return th.replace('_', ' ').title()


def _sustained_theatres_snapshot():
    """Read-only view of which theatres are at SUSTAINED L5 (seeded, or onset
    older than the novelty window). Used by the L6 doctrine BEFORE the gate
    runs: an invasion of a theatre already at sustained war is the next phase,
    not a new state."""
    state, ok = _redis_get_checked(L5_ONSET_KEY)
    if not ok or not isinstance(state, dict):
        return set()
    out, now = set(), datetime.now(timezone.utc)
    for th, rec in (state.get('theatres') or {}).items():
        if not isinstance(rec, dict) or rec.get('below_since'):
            continue
        try:
            old = rec.get('seeded') or (
                (now - datetime.fromisoformat(rec.get('onset'))).days >= L5_NOVELTY_DAYS)
        except Exception:
            old = False
        if old:
            out.add(th.split(':', 1)[-1])
    return out


def _apply_l5_novelty_gate(level, blufs):
    """Return (level, gate_info). Only ever LOWERS 5 -> 4; never raises,
    never touches anything below 5, never touches an L6 breach."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    info = {
        'window_days':   L5_NOVELTY_DAYS,
        'gap_days':      L5_EPISODE_GAP_DAYS,
        'available':     True,
        'applied':       False,
        'level_in':      level,
        'level_out':     level,
        'fresh':         [],
        'sustained':     [],
        'breach':        None,
        'reason':        '',
    }
    current = _l5_theatres(blufs)

    state, ok = _redis_get_checked(L5_ONSET_KEY)
    if not ok:
        info['available'] = False
        info['reason'] = ('Novelty gate unavailable this cycle (onset history unreadable) '
                          '-- level shown without the sustained/new distinction.')
        return level, info

    first_run = state is None
    if not isinstance(state, dict):
        state = {}
    theatres = state.get('theatres') if isinstance(state.get('theatres'), dict) else {}
    tracking_began = state.get('tracking_began') or now_iso

    def _days_since(iso):
        try:
            return (now - datetime.fromisoformat(iso)).total_seconds() / 86400.0
        except Exception:
            return None

    # An episode ends only on an OBSERVED drop. The GPI builds on demand, so a
    # quiet weekend with no page loads is a gap in OBSERVATION, not a gap in
    # the war -- treating it as one would fire false "re-ignited" L5s after
    # every lull in traffic. 'below_since' is stamped only when a build actually
    # sees the theatre off L5, and cleared when it is seen at L5 again.
    for th, region in current.items():
        rec = theatres.get(th) if isinstance(theatres.get(th), dict) else None
        reignited = False
        if rec and rec.get('below_since'):
            below = _days_since(rec['below_since'])
            if below is not None and below >= L5_EPISODE_GAP_DAYS:
                rec = None                       # observed off L5 3+ days: new episode
                reignited = True
            else:
                rec.pop('below_since', None)     # a flicker -- same episode continues
        if rec is None:
            rec = {'onset': None if first_run else now_iso,
                   'seeded': bool(first_run),
                   'reignited': reignited,
                   'region': region}
        rec['last_seen'] = now_iso
        rec['region'] = region
        theatres[th] = rec

    # Theatres not at L5 this build: stamp the observed drop, and forget ones
    # long off L5 so the record does not grow without bound.
    for th in list(theatres.keys()):
        if th in current:
            continue
        rec = theatres[th] if isinstance(theatres[th], dict) else {}
        rec.setdefault('below_since', now_iso)
        theatres[th] = rec
        d = _days_since(rec.get('last_seen') or now_iso)
        if d is not None and d > L5_FORGET_DAYS:
            theatres.pop(th, None)

    _redis_set(L5_ONSET_KEY, {'tracking_began': tracking_began, 'theatres': theatres},
               ttl=L5_ONSET_TTL)

    began_days = _days_since(tracking_began) or 0
    for th in current:
        rec = theatres[th]
        if rec.get('seeded'):
            days = int(began_days)
            entry = {'theatre': th, 'display': _theatre_display(th), 'days': days,
                     'days_is_floor': True, 'since': tracking_began[:10],
                     'reignited': False}
        else:
            days = int(_days_since(rec.get('onset') or now_iso) or 0)
            entry = {'theatre': th, 'display': _theatre_display(th), 'days': days,
                     'days_is_floor': False, 'since': (rec.get('onset') or now_iso)[:10],
                     'reignited': bool(rec.get('reignited'))}
        if (not rec.get('seeded')) and days < L5_NOVELTY_DAYS:
            info['fresh'].append(entry)
        else:
            info['sustained'].append(entry)
    info['sustained'].sort(key=lambda e: -e['days'])
    info['fresh'].sort(key=lambda e: e['days'])

    if level < 5:
        info['reason'] = 'Below L5 -- gate not engaged.'
        return level, info

    breach = _l6_breach_present(blufs)
    if breach:
        info['breach'] = breach
        info['reason'] = ('Confirmed L6 event (%s) -- novelty gate bypassed; a world-altering '
                          'event is new escalation by definition.' % breach)
        return level, info

    if info['fresh']:
        names = ', '.join('%s (%s day %d)' % (e['display'],
                          're-ignited,' if e['reignited'] else 'new,', e['days'])
                          for e in info['fresh'])
        info['reason'] = 'New L5 front within %d days: %s.' % (L5_NOVELTY_DAYS, names)
        return level, info

    # No fresh front: sustained conflict.
    info['applied'] = True
    info['level_out'] = 4
    def _fmt(e):
        # A seeded theatre has no true start date -- print "ongoing since before
        # <date>", never a small day number that would read as a NEW conflict.
        if e['days_is_floor']:
            return '%s (ongoing since before %s)' % (e['display'], e['since'])
        return '%s (day %d)' % (e['display'], e['days'])
    info['label'] = SUSTAINED_LABEL
    info['summary'] = ('No new L5 front in %d days. Active conflict continues: %s.'
                       % (L5_NOVELTY_DAYS, ', '.join(_fmt(e) for e in info['sustained'][:6])))
    info['reason'] = info['summary']
    print(f"[GPI L5 gate] L5 -> L4 SUSTAINED: {info['summary'][:160]}")
    return 4, info


# ============================================================
# L6 DOCTRINE -- GLOBAL SHOCK  (v3.13.0, Oct 28 2026)
# ============================================================
# Rachel's ruling, Oct 28: L6 fires ONLY for an event so big that "the world
# sits back and goes 'oh shit'" -- one that changes what happens at the UN and
# how NATO responds. Never for tit-for-tat inside an ongoing war of escalation.
# Until now, any tracker signal scored level 6 lit the global banner (Iraq did
# on 4 Sep for a red-line breach that was part of the exchange). Tracker L6 is
# now a CANDIDATE, not a verdict. Three tests, all required:
#
#   1. CLASS. The event belongs to a systemic class (L6_CLASSES below). WMD use
#      excludes tests, drills, exercises and threats -- the DPRK tests
#      constantly and none of it is L6. Mass casualty is scaled to the
#      population (Oct 7 in Israel sits at the 9/11 bar; one van ramming does
#      not). Invasion / blockade only counts against a theatre that was NOT
#      already at sustained L5 -- a new state, not the next phase of a war.
#   2. WORLD REACTION. Observed institutional response naming the event or the
#      country: an emergency UN Security Council session, NATO Article 4/5, an
#      emergency G7 / General Assembly session. The NATO class specifically
#      needs Article 5 -- Article 4 consultations follow drone debris, and
#      that is not a world-altering event.
#   3. HOLD. A confirmed L6 holds the global index for L6_HOLD_DAYS (7). After
#      that it is the new normal and goes through the L5 novelty gate like any
#      other front. L6 marks the moment; it is not a permanent state.
#
# A tracker L6 that fails is DEMOTED to L5 inside the GPI only (the tracker's
# own page keeps its reading), and the payload says why. Absence-honest: if the
# reaction check cannot run, a candidate is reported as UNCONFIRMED, never as
# confirmed and never as nothing.
L6_HOLD_DAYS      = 7
L6_EVENTS_KEY     = 'gpi:l6_events'
L6_EVENTS_TTL     = 400 * 24 * 3600
L6_REACTION_DAYS  = 3        # reaction must be this recent
L6_LABEL          = 'GLOBAL SHOCK'

# Event verbs that mean it HAPPENED. A class match also needs one of these.
_L6_HAPPENED = (r'\b(?:struck|strikes?|attack(?:ed|s)?|hit|detonat\w*|explod\w*|used|'
                r'deployed|released|fired|launched at|killed|assassinat\w*|seized|'
                r'invad\w*|crossed into|blockad\w*|massacre\w*|bomb(?:ed|ing)s?|'
                r'shot down|downed|clash(?:ed|es)?)\b')
# HARD exclusions -- anywhere in the signal: it was a test, a drill, or history.
# The DPRK tests constantly; none of it is L6.
_L6_NOT_EVENT = (r'\b(?:test(?:s|ed|ing)?|test[- ]fir\w*|drills?|military exercises?|'
                 r'exercises? (?:near|off|around)|simulat\w*|rehears\w*|wargam\w*|'
                 r'hypothetical|scenario|anniversary|years? ago|commemorat\w*)\b')
# SOFT exclusions -- only when they sit right before the event itself ("threatens
# a nuclear strike", "could invade"). Anywhere else they are ordinary analysis
# ("Tehran may retaliate") and must not veto a real event.
_L6_HEDGE = (r'\b(?:threat(?:s|en\w*)?|warn(?:s|ed|ing)? (?:of|that)|could|would|might|may|'
             r'if|plans? to|preparing to|vows? to|pledg\w* to|readiness to|prepared to|'
             r'considering|option of|risk of|fears? of|capable of|able to carry|'
             r'carrying|could carry|dual[- ]use)\b')


def _l6_hedged(txt, span):
    """True if hedging language sits in the 45 chars before the matched event."""
    lo = max(0, span[0] - 45)
    return bool(re.search(_L6_HEDGE, txt[lo:span[0] + 1]))

_NUCLEAR_STATES = {
    'us':       r'\b(?:united states|u\.s\.|us|american|pentagon|washington)\b',
    'russia':   r'\b(?:russia|russian|moscow|kremlin)\b',
    'china':    r'\b(?:china|chinese|pla|beijing)\b',
    'uk':       r'\b(?:united kingdom|uk|britain|british)\b',
    'france':   r'\b(?:france|french)\b',
    'india':    r'\b(?:india|indian)\b',
    'pakistan': r'\b(?:pakistan|pakistani)\b',
    'dprk':     r'\b(?:north korea|north korean|dprk|pyongyang)\b',
    'israel':   r'\b(?:israel|israeli|idf)\b',
}
# Adversarial pairs only. Two allies named in one story (a US-Israel joint
# strike statement) is not a clash between nuclear states.
_NUCLEAR_ADVERSARY_PAIRS = {
    frozenset(p) for p in (('us', 'russia'), ('us', 'china'), ('us', 'dprk'),
                           ('russia', 'uk'), ('russia', 'france'), ('china', 'india'),
                           ('india', 'pakistan'), ('china', 'uk'), ('china', 'france'))
}

# Population in millions, for the mass-casualty scale. Approximate and
# deliberately coarse -- the threshold is an order of magnitude, not a census.
# A country missing here falls back to the absolute floor only (and says so).
_POP_M = {
    'israel': 9.9, 'palestine': 5.4, 'gaza': 2.1, 'west_bank': 3.3, 'lebanon': 5.8,
    'syria': 24, 'jordan': 11.5, 'iraq': 46, 'iran': 90, 'yemen': 35,
    'saudi_arabia': 35, 'uae': 10, 'qatar': 3, 'kuwait': 4.9, 'bahrain': 1.6,
    'oman': 5.3, 'egypt': 115, 'turkey': 86, 'cyprus': 1.3, 'greece': 10.3,
    'russia': 144, 'ukraine': 37, 'belarus': 9, 'moldova': 2.4, 'poland': 37,
    'germany': 84, 'france': 68, 'uk': 69, 'united_kingdom': 69, 'spain': 48,
    'italy': 59, 'netherlands': 18, 'belgium': 11.8, 'sweden': 10.5, 'finland': 5.6,
    'norway': 5.5, 'denmark': 6, 'estonia': 1.4, 'latvia': 1.9, 'lithuania': 2.9,
    'romania': 19, 'serbia': 6.6, 'kosovo': 1.7, 'armenia': 3, 'azerbaijan': 10,
    'georgia': 3.7, 'kazakhstan': 20, 'afghanistan': 42, 'pakistan': 245,
    'india': 1440, 'bangladesh': 173, 'china': 1410, 'taiwan': 23, 'japan': 124,
    'south_korea': 52, 'north_korea': 26, 'philippines': 115, 'vietnam': 100,
    'indonesia': 280, 'myanmar': 54, 'thailand': 72, 'australia': 27,
    'us': 340, 'usa': 340, 'united_states': 340, 'canada': 41, 'mexico': 130,
    'colombia': 53, 'venezuela': 28, 'brazil': 212, 'cuba': 11, 'haiti': 11.8,
    'nigeria': 230, 'ethiopia': 130, 'sudan': 50, 'south_sudan': 11,
    'somalia': 19, 'kenya': 56, 'drc': 110, 'mali': 23, 'burkina_faso': 23,
    'niger': 27, 'chad': 19, 'libya': 7, 'algeria': 46, 'morocco': 38,
    'tunisia': 12, 'mozambique': 34, 'south_africa': 63, 'uganda': 49,
}
# The bar, anchored on Rachel's two reference cases:
#   9/11:  2,977 dead / 285M  ~ 10 per million
#   Oct 7: ~1,200 dead / 9.8M ~ 122 per million
# Either clears 10/M. A vehicle-ramming killing 10 in a country of 60M is 0.17/M.
# The absolute floor stops a small number in a small country tripping the
# per-capita test; the absolute ceiling catches a 1,000+ single attack anywhere.
L6_MASS_CASUALTY_PER_MILLION = 10.0
L6_MASS_CASUALTY_MIN_DEAD    = 250
L6_MASS_CASUALTY_ANY_DEAD    = 1000

_DEATH_RX = re.compile(
    r'(?:(\d[\d,]{1,6})\s+(?:people\s+|civilians\s+|israelis\s+|americans\s+)?'
    r'(?:killed|dead|murdered|slain|deaths)|death toll (?:of|at|rises to|reaches|climbs to)\s+(\d[\d,]{1,6}))')
# Cumulative war tolls are not a single event.
_CUMULATIVE_RX = re.compile(r'\b(?:since (?:the|october|the start|the war|fighting)|total|cumulative|'
                            r'so far|to date|over the past|throughout|this year|in the war)\b')

# (class_id, label, pattern that must match, extra test name)
L6_CLASSES = [
    # 'nuclear-capable', 'nuclear site', 'nuclear programme' never match: the
    # Iran war produces those words daily and none of it is a weapon being used.
    ('wmd_use', 'Weapon of mass destruction used',
     r'\b(?:nuclear (?:weapon|bomb|strike|device|warhead|attack)|atomic bomb|radiological|'
     r'dirty bomb|chemical (?:weapon|attack)|nerve agent|sarin|novichok|\bvx\b|mustard gas|'
     r'chlorine (?:gas|attack)|biological (?:weapon|attack)|bioweapon|anthrax attack)\b', None),
    ('nuclear_plant_release', 'Nuclear plant struck with radiological release',
     r'\b(?:nuclear (?:power )?plant|reactor|zaporizhzhia|chernobyl|bushehr|dimona)\b.{0,80}'
     r'\b(?:radiation (?:leak|release)|radiological release|meltdown|radioactive (?:leak|release|plume))\b', None),
    ('nuclear_state_clash', 'Direct military clash between nuclear-armed adversaries', None, 'nuclear_pair'),
    ('nato_attacked', 'Armed attack on NATO territory (Article 5)',
     r'\b(?:nato (?:member|territory|ally)|article 5|article five)\b', None),
    ('new_invasion', 'Invasion or blockade of a new state',
     r'\b(?:full[- ]scale invasion|ground invasion|invaded|invasion of|naval blockade|blockade of|'
     r'quarantine of taiwan|amphibious assault)\b', 'fresh_front'),
    ('decapitation', 'Head of state or government killed',
     r'\b(?:president|prime minister|supreme leader|head of state|king|chancellor|premier)\b.{0,60}'
     r'\b(?:assassinated|killed in|was killed|killed by|dies in (?:an? )?(?:strike|attack|blast))\b', None),
    ('nuclear_state_coup', 'Coup in a nuclear-armed state',
     r'\b(?:coup|seized power|military takeover|junta takes)\b', 'nuclear_named'),
    ('mass_casualty', 'Mass-casualty attack at national-trauma scale',
     r'\b(?:attack|massacre|bombing|gunmen|militants|terror\w*|rampage|infiltrat\w*)\b', 'mass_casualty'),
]

# Institutional reaction phrases. ANY satisfies the general test; the NATO
# class needs one of the article-5 phrases specifically.
_REACTION_GENERAL = (r'\b(?:security council (?:emergency|urgent)|emergency (?:session|meeting) of the '
                     r'(?:un )?security council|unsc (?:emergency|urgent)|security council (?:to )?meet|'
                     r'emergency special session|general assembly emergency|article 4|article four|'
                     r'article 5|article five|g7 (?:emergency|leaders)|emergency g7|nato emergency)\b')
_REACTION_NATO = r'\b(?:article 5|article five)\b'
_REACTION_FEEDS = (
    'https://news.google.com/rss/search?q=%22Security+Council%22+emergency+when:3d&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=NATO+%22Article+5%22+OR+%22Article+4%22+when:3d&hl=en-US&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=G7+emergency+statement+when:3d&hl=en-US&gl=US&ceid=US:en',
)

_LAST_L6 = {}


def _l6_text(sig):
    return ' '.join(str(sig.get(k) or '') for k in ('category', 'short_text', 'long_text', 'text')).lower()


def _l6_country_key(sig, region=None):
    th = str(sig.get('theatre') or '').strip().lower().replace(' ', '_').replace('-', '_')
    if th in _POP_M:
        return th
    txt = _l6_text(sig)
    for k in sorted(_POP_M, key=len, reverse=True):
        if re.search(r'\b' + re.escape(k.replace('_', ' ')) + r'\b', txt):
            return k
    return th or (region or '')


def _l6_mass_casualty(sig, txt):
    """Return (passes, detail). Scaled to population, single event only."""
    if _CUMULATIVE_RX.search(txt):
        return False, 'casualty figure reads as a cumulative war toll, not a single event'
    dead = 0
    for m in _DEATH_RX.finditer(txt):
        raw = m.group(1) or m.group(2)
        try:
            dead = max(dead, int(raw.replace(',', '')))
        except Exception:
            pass
    if not dead:
        return False, 'no casualty figure in the signal'
    ck = _l6_country_key(sig)
    pop = _POP_M.get(ck)
    if dead >= L6_MASS_CASUALTY_ANY_DEAD:
        return True, '%d killed (above the %d single-attack floor)' % (dead, L6_MASS_CASUALTY_ANY_DEAD)
    if pop is None:
        return False, ('%d killed; population for %s unknown, so only the %d absolute bar applies'
                       % (dead, ck or 'theatre', L6_MASS_CASUALTY_ANY_DEAD))
    per_m = dead / pop
    if per_m >= L6_MASS_CASUALTY_PER_MILLION and dead >= L6_MASS_CASUALTY_MIN_DEAD:
        return True, ('%d killed = %.0f per million in %s (9/11 was ~10/M, Oct 7 ~122/M)'
                      % (dead, per_m, ck.replace('_', ' ').title(), ))
    return False, ('%d killed = %.2f per million in %s -- a grave attack, below the national-trauma bar'
                   % (dead, per_m, ck.replace('_', ' ').title()))


def _l6_classify(sig, sustained_theatres):
    """Return (class_id, label, detail) if the signal is a systemic-class EVENT, else (None, None, why)."""
    txt = _l6_text(sig)
    ev = re.search(_L6_HAPPENED, txt)
    if not ev:
        return None, None, 'no event verb -- reads as posture or rhetoric'
    if re.search(_L6_NOT_EVENT, txt):
        return None, None, 'test, drill, exercise or historical reference -- not an event'
    for cid, label, pat, extra in L6_CLASSES:
        m = re.search(pat, txt) if pat else None
        if pat and not m:
            continue
        if _l6_hedged(txt, m.span() if m else ev.span()):
            return None, None, 'hedged / threatened rather than reported as having happened'
        if extra == 'nuclear_pair':
            named = {k for k, rx in _NUCLEAR_STATES.items() if re.search(rx, txt)}
            pairs = [p for p in _NUCLEAR_ADVERSARY_PAIRS if p <= named]
            if not pairs:
                continue
            return cid, label, 'adversaries named: %s' % ', '.join(
                ' vs '.join(sorted(p)) for p in pairs)
        if extra == 'nuclear_named':
            if not any(re.search(rx, txt) for rx in _NUCLEAR_STATES.values()):
                continue
        if extra == 'fresh_front':
            th = str(sig.get('theatre') or '').strip().lower()
            if th in sustained_theatres:
                continue          # next phase of an existing war, not a new state
        if extra == 'mass_casualty':
            ok, why = _l6_mass_casualty(sig, txt)
            if not ok:
                return None, None, why
            return cid, label, why
        return cid, label, ''
    return None, None, 'no systemic class matched'


def _l6_fetch_reactions():
    """Recent institutional-reaction headlines. Returns (list_of_lowercase_titles, ok).
    Called ONLY when a class-passing candidate exists -- rare by design."""
    titles, ok_any = [], False
    try:
        import xml.etree.ElementTree as ET
    except Exception:
        return [], False
    for url in _REACTION_FEEDS:
        try:
            r = requests.get(url, timeout=8, headers={'User-Agent': 'AsifahAnalytics/1.0 (+https://asifahanalytics.com)'})
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            for it in root.iter('item'):
                t = (it.findtext('title') or '') + ' ' + (it.findtext('description') or '')
                titles.append(t.lower())
            ok_any = True
        except Exception as e:
            print(f'[GPI L6] reaction feed error: {str(e)[:100]}')
    return titles, ok_any


def _l6_reaction_for(sig, cid, reaction_pool):
    """Find a reaction line that matches the class requirement AND names the
    country / theatre (so a Security Council session on Sudan does not
    confirm an attack in Kuwait)."""
    need = _REACTION_NATO if cid == 'nato_attacked' else _REACTION_GENERAL
    ck = _l6_country_key(sig).replace('_', ' ')
    th = str(sig.get('theatre') or '').replace('_', ' ').lower()
    names = {n for n in (ck, th) if n and len(n) > 2}
    for line in reaction_pool:
        if re.search(need, line) and any(re.search(r'\b' + re.escape(n) + r'\b', line) for n in names):
            return line[:200]
    return None


def _evaluate_l6_doctrine(blufs, sustained_theatres, fetch_reactions=None):
    """Classify every tracker L6 / systemic candidate, confirm or demote, and
    maintain the 7-day hold. Mutates signal levels IN THE GPI'S COPY ONLY.
    Returns the l6 info dict (also stored on _LAST_L6)."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    info = {'active': False, 'events': [], 'candidates': [], 'demoted': [],
            'hold_days': L6_HOLD_DAYS, 'reaction_check': 'not_needed'}

    # 1. Candidates: tracker L6 signals, plus L5 kinetic signals whose TEXT is
    #    systemic class (a tracker that under-scores a nuclear detonation must
    #    not be able to hide it).
    cands = []
    for region, bluf in (blufs or {}).items():
        for s in _signals_of(bluf):
            lvl = _safe_level(s.get('level', 0))
            if lvl >= 6 or (lvl >= 5 and _infer_pressure_type(s) == PRESSURE_KINETIC):
                cands.append((region, s, lvl))

    passing = []
    for region, s, lvl in cands:
        cid, label, detail = _l6_classify(s, sustained_theatres)
        if cid:
            passing.append((region, s, lvl, cid, label, detail))
        elif lvl >= 6:
            s['level'] = 5
            s['l6_demoted'] = True
            s['l6_note'] = ('Scored L6 by its tracker; held at L5 in the GPI -- %s. '
                            'Global L6 is reserved for world-altering events.' % detail)
            info['demoted'].append({'theatre': s.get('theatre') or region,
                                    'short_text': (s.get('short_text') or '')[:120],
                                    'why': detail})

    # 2. World reaction -- fetched only if something passed the class test.
    reactions, reaction_ok = [], True
    if passing:
        fetcher = fetch_reactions or _l6_fetch_reactions
        reactions, reaction_ok = fetcher()
        info['reaction_check'] = 'ok' if reaction_ok else 'unavailable'

    state, st_ok = _redis_get_checked(L6_EVENTS_KEY)
    events = list((state or {}).get('events') or []) if isinstance(state, dict) else []

    for region, s, lvl, cid, label, detail in passing:
        th = str(s.get('theatre') or region)
        rx = _l6_reaction_for(s, cid, reactions) if reaction_ok else None
        cand = {'theatre': th, 'class': cid, 'class_label': label, 'detail': detail,
                'short_text': (s.get('short_text') or '')[:140], 'tracker_level': lvl,
                'reaction': rx}
        if rx:
            eid = '%s|%s' % (cid, th.lower())
            if not any(e.get('id') == eid and e.get('confirmed_at') and
                       (now - datetime.fromisoformat(e['confirmed_at'])).days < L6_HOLD_DAYS
                       for e in events):
                events.append({'id': eid, 'theatre': th, 'class': cid, 'class_label': label,
                               'detail': detail, 'headline': cand['short_text'],
                               'reaction': rx, 'confirmed_at': now_iso})
                print(f'[GPI L6] CONFIRMED {label} -- {th}: {cand["short_text"][:100]}')
            s['level'] = 6
            s['l6_confirmed'] = True
            cand['status'] = 'confirmed'
        else:
            cand['status'] = ('unconfirmed -- reaction check unavailable this cycle'
                              if not reaction_ok else
                              'unconfirmed -- no institutional reaction naming %s yet' % th)
            if lvl >= 6:
                s['level'] = 5
                s['l6_demoted'] = True
                s['l6_note'] = ('%s: systemic class, but %s. Held at L5 until the world '
                                'visibly reacts.' % (label, cand['status']))
        info['candidates'].append(cand)

    # 3. The 7-day hold.
    live = []
    for e in events:
        try:
            age = (now - datetime.fromisoformat(e['confirmed_at'])).total_seconds() / 86400.0
        except Exception:
            continue
        if age < L6_HOLD_DAYS:
            e2 = dict(e, day=int(age), expires_in_days=max(0, int(L6_HOLD_DAYS - age)))
            live.append(e2)
    info['events'] = live
    info['active'] = bool(live)
    if st_ok:
        keep = [e for e in events if (now - datetime.fromisoformat(e['confirmed_at'])).days < 365]
        _redis_set(L6_EVENTS_KEY, {'events': keep[-50:]}, ttl=L6_EVENTS_TTL)
    if info['demoted']:
        print(f'[GPI L6] demoted {len(info["demoted"])} tracker L6 signal(s) to L5 (not world-altering)')
    return info


# ============================================================
# STANDING-WATCH TIER FOR NARRATIVES  (v3.12.0, Oct 28 2026)
# ============================================================
# Rachel, Oct 28: structural watches (wheat, diamonds, phosphate, clusters)
# collapse by default and pop open when something changes -- or when the
# reader goes looking.
#
# A narrative is STANDING when either:
#   (a) Layer 2 says its underlying pressure is steady, not rising
#       (registry entries carry fresh=False), or
#   (b) its headline has not changed for NARRATIVE_STANDING_DAYS.
# "Changed" ignores digits, so a refreshed day-count or price does not read as
# movement -- a new country, a new level word or a new actor does.
#
# Rule (b) never applies to a kinetic-primary narrative at priority >= 13:
# those are war-class reads, and the novelty gate above already handles
# "sustained" for conflict. Standing is a DISPLAY tier: the narrative is still
# computed, still in the payload, still one click away. It is just not
# promoted into the signal feed, the BLUF lead, the banner, or the +1
# convergence boost while it is standing.
NARRATIVE_STANDING_KEY  = 'gpi:narrative_standing'
NARRATIVE_STANDING_TTL  = 60 * 24 * 3600
NARRATIVE_STANDING_DAYS = 3
STANDING_EXEMPT_KINETIC_PRIORITY = 13
_NARRATIVE_NEVER_TIERED = ('global_baseline', 'global_warning')


def _narrative_fingerprint(n):
    head = str(n.get('headline') or '').lower()
    head = ''.join(c for c in head if c.isalpha() or c == ' ')
    head = ' '.join(head.split())[:140]
    regs = ','.join(sorted(str(r) for r in (n.get('regions') or [])))
    return '%s|%s|%s' % (n.get('category', ''), regs, head)


def _tier_narratives(narratives):
    """Stamp each narrative with tier 'topline' | 'standing'. Toplines first."""
    if not narratives:
        return narratives
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    state, ok = _redis_get_checked(NARRATIVE_STANDING_KEY)
    if not isinstance(state, dict):
        state = {}
    new_state = {}

    for n in narratives:
        cat = n.get('category', '')
        if cat in _NARRATIVE_NEVER_TIERED:
            n['tier'] = 'topline'
            continue
        fp = _narrative_fingerprint(n)
        prev = state.get(cat) if isinstance(state.get(cat), dict) else None
        moved = False
        if prev and prev.get('fp') == fp:
            since = prev.get('since') or now_iso
        else:
            since = now_iso
            moved = prev is not None
        new_state[cat] = {'fp': fp, 'since': since}
        try:
            unchanged_days = (now - datetime.fromisoformat(since)).total_seconds() / 86400.0
        except Exception:
            unchanged_days = 0.0

        axes = _axes_for_narrative(n)
        war_class = (axes[:1] == [PRESSURE_KINETIC]
                     and int(n.get('priority', 0) or 0) >= STANDING_EXEMPT_KINETIC_PRIORITY)
        reason = None
        if n.get('fresh') is False:
            reason = 'Underlying pressure reported steady, not rising.'
        elif ok and unchanged_days >= NARRATIVE_STANDING_DAYS and not war_class:
            reason = 'Unchanged for %d days.' % int(unchanged_days)

        n['tier'] = 'standing' if reason else 'topline'
        n['standing_reason'] = reason
        n['unchanged_days'] = round(unchanged_days, 1) if ok else None
        n['moved_this_cycle'] = bool(moved)

    # Cluster members follow their cluster, so an umbrella and its countries
    # never split across the two tiers.
    cluster_tier = {n.get('cluster'): n.get('tier') for n in narratives if n.get('is_cluster')}
    for n in narratives:
        cid = n.get('clustered_into')
        if cid and not n.get('is_cluster') and cid in cluster_tier:
            n['tier'] = cluster_tier[cid]
            if n['tier'] == 'standing' and not n.get('standing_reason'):
                n['standing_reason'] = 'Part of a standing regional watch.'

    if ok:
        # Keep records for narratives absent this cycle so a one-scan blink
        # does not reset the clock; they age out with the key TTL.
        for cat, rec in state.items():
            if cat not in new_state and isinstance(rec, dict):
                new_state[cat] = rec
        _redis_set(NARRATIVE_STANDING_KEY, new_state, ttl=NARRATIVE_STANDING_TTL)

    narratives.sort(key=lambda n: (0 if n.get('tier') != 'standing' else 1,
                                   -int(n.get('priority', 0) or 0)))
    n_st = sum(1 for n in narratives if n.get('tier') == 'standing')
    print(f'[GPI tiers] {len(narratives) - n_st} topline / {n_st} standing narratives')
    return narratives


# ============================================================
# GLOBAL LEVEL ROLLUP
# ============================================================
def _compute_global_level(blufs, narratives):
    """
    Determine the single GPI level (0-5).
    Logic: max regional level, +1 if cross-theater convergence narratives present.

    L5 GATE (v3.4.0 — May 21 2026): Per platform L5 Reservation Contract,
    global L5 "ACTIVE CONFLICT" requires at least one region to be genuinely
    at L5 — convergence boost alone CANNOT push global to L5 from L4. This
    is belt-and-suspenders defense; the BLUFs themselves enforce the gate
    per-tracker, but this catches any future drift in BLUF behavior.
    """
    if not blufs:
        return 0
    regional_levels = [_level_of(b) for b in blufs.values()]
    max_regional = max(regional_levels) if regional_levels else 0

    # Cross-theater convergence boost
    # v3.12.0: a STANDING narrative cannot supply the convergence boost. Static
    # structural watches were one of the things holding the gauge up.
    high_priority_narratives = [n for n in narratives if n.get('priority', 0) >= 11
                                 and n.get('tier') != 'standing'
                                 and n.get('category') not in ('global_baseline', 'global_warning')]
    convergence_boost = 1 if high_priority_narratives else 0

    proposed_level = min(5, max_regional + convergence_boost)

    # L5 gate: convergence boost alone cannot push global to L5
    # — at least one region must be genuinely at L5 already.
    if proposed_level >= 5 and max_regional < 5:
        print(f"[GPI L5 gate] convergence boost would push global to L5 from "
              f"max_regional={max_regional}; capping at L4 per L5 Reservation Contract")
        return 4

    return proposed_level


# ============================================================
# GLOBAL TOP SIGNALS
# ============================================================
def _build_global_top_signals(blufs, narratives):
    """
    Top N signals across all regions + narrative-derived signals.

    Tiered sort (analyst-first hierarchy, v1.1):
      Tier 1 (+30 boost) — CROSS-REGIONAL COORDINATION (≥2 regions)
                          Things you won't see in any single regional dashboard.
                          russia_iran_axis, dprk_russia_axis, nuclear_signaling_global, etc.
      Tier 2 (+20 boost) — ACTIVE CONFLICT (L5 in any region)
                          There is a war happening here right now.
      Tier 3 (+10 boost) — SINGLE-REGION HIGH-PRIORITY NARRATIVES
                          china_taiwan_takeover, dual_chokepoint, wha_cascade
      Tier 4 (+0)        — Everything else (raw regional signals, baseline)

    Within each tier, raw priority breaks ties.
    """
    # Categories that are inherently cross-regional even when emitted from one region's
    # signals (e.g., a Russia tracker emits "crosstheater_iran_russia" — that's a Tier-1
    # signal even though only Europe surfaces it).
    CROSSTHEATER_CATEGORIES = {
        'crosstheater_iran_russia', 'crosstheater_russia_iran',
        'crosstheater_dprk_russia', 'crosstheater_china_iran',
        'crosstheater_iran_proxies', 'crosstheater_iran_israel',
        'crosstheater_lebanon_israel', 'crosstheater_yemen_israel',
        'crosstheater_syria_israel', 'crosstheater_iraq_israel',
        'multi_axis_convergence', 'dual_chokepoint',
    }

    def _tier_boost(signal):
        """Return priority boost based on which analyst tier the signal belongs to."""
        regions = signal.get('regions') or []
        category = signal.get('category', '')
        level = _safe_level(signal.get('level', 0))
        theatre = signal.get('theatre', '')

        # Tier 1: Cross-regional coordination (≥2 regions OR known crosstheater category)
        if (isinstance(regions, list) and len(regions) >= 2) or category in CROSSTHEATER_CATEGORIES:
            return 30

        # Tier 2: Active conflict — single region at L5
        if level >= 5 and theatre != 'global':
            return 20

        # Tier 2 (extended, Jun 18 2026): a BREACHED red line at high+ severity is
        # active-conflict class on its OWN merit -- it must NOT be buried just
        # because its home region's ambient level isn't L5. Fixes non-ME strategic
        # breaches (e.g. a record Ukrainian strike on Moscow) being floored to Tier 4
        # while every ME L5 signal gets +20. Gated to genuine breaches (short_text
        # carries the BREACH marker) so it never broadly amplifies high-volume noise.
        short = (signal.get('short_text') or '').upper()
        if level >= 4 and 'BREACH' in short and theatre != 'global':
            return 20

        # Tier 3: Major regional narratives (came from narrative detector, single region)
        # We tag narrative-derived signals with theatre='global' and they have a 'regions' list.
        # Single-region narratives (1 region) sit here.
        if theatre == 'global' and isinstance(regions, list) and len(regions) == 1:
            return 10

        # Tier 4: Everything else
        return 0

    signals = []

    # 1. Promote top narratives to signals
    # v3.12.0: standing watches are NOT promoted into the signal feed. They
    # stay on the page in their own collapsed tier; promoting them is how a
    # static wheat read kept taking headline slots from things that moved.
    _toplines = [n for n in narratives if n.get('tier') != 'standing']
    for n in _toplines[:5]:   # widened from 3 to 5 since tier sort handles ranking
        if n.get('category') in ('global_baseline', 'global_warning'):
            continue
        promoted = {
            'priority':   n['priority'],
            'category':   n['category'],
            'theatre':    'global',
            'level':      (int(n['level_hint']) if n.get('level_hint')
                           else (5 if n['priority'] >= 13 else 4)),
            'icon':       n['icon'],
            'color':      n['color'],
            'short_text': n['headline'][:120],     # v2.3.0: 80→120 — fits "Wheat-Lebanon convergence ... ELEVATED" (85 chars)
            'long_text':  n['detail'],
            'regions':    n.get('regions', []),
        }
        # v3.6.0 (May 23 2026): propagate pressure_type from narrative if set.
        # This lets dedicated narratives (BRI, sanctions evasion, etc.) declare
        # their axis explicitly rather than being defaulted to kinetic via the
        # inference layer (which has no category hint for narrative-derived signals).
        if n.get('pressure_type'):
            promoted['pressure_type'] = n['pressure_type']
        # Slice 3: attach full axis set (primary first) + keep pressure_type
        # aligned to the primary axis so axis aggregation stays correct.
        _axes = _axes_for_narrative(n)
        promoted['axes'] = _axes
        if _axes:
            promoted['pressure_type'] = _axes[0]
        signals.append(promoted)

    # 2. Pull top regional signals (alphabetical, then by priority)
    for region in CARD_ORDER:
        bluf = blufs.get(region)
        if not bluf:
            continue
        region_pool = _signals_of(bluf)
        pulled = list(region_pool[:3])  # v3.5.0 May 21 2026 — top 3 per region
        # De-escalation un-gate-keep (Jun 14 2026): the trackers catch diplomatic
        # signals and they reach the regional BLUFs, but a ceasefire / cessation-
        # of-hostilities signal usually ranks BELOW a region's kinetic top 3 during
        # active conflict -- so the [:3] cut silently dropped it from the feed. Pull
        # any diplomatic signal the cut missed so it reaches the candidate pool; the
        # diplomatic-axis allocation (Phase A) then surfaces it. Never gate-kept.
        # v3.12.0: governance rides the same pass. A caretaker government or a
        # formation window ranks below a region's kinetic top 3 by construction
        # -- that is precisely the non-kinetic butterfly the cut was hiding.
        for sig in region_pool[3:]:
            if _infer_pressure_type(sig) in (PRESSURE_DIPLOMATIC, PRESSURE_GOVERNANCE):
                pulled.append(sig)
        for sig in pulled:
            signals.append({
                'priority':      int(sig.get('priority', 5) or 5) - 2,  # demote vs. narratives
                'category':      sig.get('category', 'regional'),
                # v3.2 grouping fix (Jul 16 2026): PRESERVE the country theatre the
                # regional BLUF emitted ('iran', 'lebanon'...) instead of stamping
                # the region over it. Stamping 'me'/'europe' here destroyed country
                # provenance for every downstream consumer -- it's why All Vectors
                # couldn't group by country while the per-axis cards could. The
                # region lives in its own field now.
                'theatre':       sig.get('theatre') or region,
                'region':        region,
                'level':         sig.get('level', 0),
                'icon':          sig.get('icon', '\u2022'),
                'color':         sig.get('color', '#6b7280'),
                'short_text':    sig.get('short_text', sig.get('text', ''))[:120],   # v2.3.0: 80→120 (consistency)
                'long_text':     sig.get('long_text', sig.get('short_text', '')),
                'pressure_type': _infer_pressure_type(sig),  # lock axis
                # No 'regions' key — single-region signals naturally Tier 2 or 4
            })

    # v3.12.0 -- narrative decay, finally wired in (see _apply_narrative_decay).
    # Runs BEFORE the sort key so a static signal's lowered priority actually
    # changes its rank. Tier boosts are untouched: an L5 signal keeps its +20,
    # it just stops outranking OTHER L5 signals that are moving.
    try:
        signals = _apply_narrative_decay(signals)
    except Exception as _dec_err:
        print(f'[GPI decay] skipped (non-fatal): {str(_dec_err)[:120]}')

    # 2b. v3.14.0 (Oct 29 2026) -- PSEUDO-REGION MOVERS. Only CARD_ORDER regions
    # were ever pulled into this list, so a global feed (humanitarian, commodity,
    # food) could reach the axis tabs and the narratives but never All Vectors --
    # which is how Ebola leaving DR Congo for Kenya and Nigeria stayed off the
    # front page. Narrow by design: only a cross-border spread synthesis or a row
    # the feed itself flags as a GROWING concern, at most two per feed. Standing
    # feed rows (annual statistics, steady prices) stay on their tabs.
    for region, bluf in (blufs or {}).items():
        if region in CARD_ORDER or not bluf:
            continue
        movers = [sg for sg in _signals_of(bluf)
                  if sg.get('category') == 'outbreak_spread'
                  or (sg.get('growing_concern') and not sg.get('watch_only'))][:2]
        for sig in movers:
            signals.append({
                'priority':      int(sig.get('priority', 5) or 5) - 2,
                'category':      sig.get('category', 'regional'),
                'theatre':       sig.get('theatre') or region,
                'region':        region,
                'level':         sig.get('level', 0),
                'icon':          sig.get('icon', '\u2022'),
                'color':         sig.get('color', '#6b7280'),
                'short_text':    (sig.get('short_text') or sig.get('text') or '')[:180],
                'long_text':     sig.get('long_text', sig.get('short_text', '')),
                'pressure_type': _infer_pressure_type(sig),
                'pseudo_region_mover': True,
            })

    # Compute tier-adjusted sort key for each signal
    for s in signals:
        s['_tier_boost'] = _tier_boost(s)
        s['_sort_key']   = s['_tier_boost'] + int(s.get('priority', 0) or 0)

    # ── PRE-DEDUPE SNAPSHOT (Jul 27 2026) ─────────────────────────────
    # The Jul 27 tagging audit could not measure bundling because the GPI
    # never exposed this list -- it reported "raw 20 -> dedupe 20 -> discarded
    # 0", which is tautological when the input IS the post-dedupe output.
    #
    # Stashed on a module global rather than added to the return signature so
    # the single call site stays unchanged. Trimmed to the fields an audit
    # needs: the full objects would double the payload for a diagnostic almost
    # nobody reads, and _sort_key/_tier_boost are internals that get stripped
    # from the survivors anyway.
    global _LAST_RAW_SIGNALS
    _LAST_RAW_SIGNALS = [{
        'theatre':       s.get('theatre'),
        'category':      s.get('category'),
        'level':         s.get('level'),
        'priority':      s.get('priority'),
        'pressure_type': s.get('pressure_type'),
        'short_text':    (s.get('short_text') or '')[:160],
        'countries':     s.get('countries'),
    } for s in signals]

    # Dedupe by category+theatre, then apply tier+priority sort.
    # v3.6 (May 23 2026): split into two phases for axis-distribution control.
    seen = set()
    deduped = []
    for s in sorted(signals, key=lambda x: x.get('_sort_key', 0), reverse=True):
        key = f"{s.get('theatre', '')}:{s.get('category', '')}"
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    # ─────────────────────────────────────────────────────────────────────
    # AXIS DISTRIBUTION (v3.6.0 May 23 2026)
    # ─────────────────────────────────────────────────────────────────────
    # The first CORE_HEADLINE_COUNT slots fill by pure tier+priority — this
    # protects the analyst-priority headline narrative integrity (you never
    # want a wheat-price signal pre-empting an active-conflict L5 signal).
    #
    # Slots CORE_HEADLINE_COUNT..TOP_GLOBAL_SIGNALS_COUNT apply rebalancing:
    # the remaining slots PREFER signals from underrepresented axes so the
    # final 20 includes diplomatic + humanitarian + economic representation
    # rather than 20 kinetic. MIN_SIGNALS_PER_AXIS sets the floor we aim for.
    #
    # Why this matters: when Africa/Ebola signals + diamond sanctions + BRI
    # resource leverage all fire simultaneously, the headline tier still
    # gets the loudest narrative, but operators see the full picture in
    # slots 13-20 rather than only the kinetic axis. Sudan IDP surge during
    # active Iran kinetic = visible side-by-side.
    # Hard ceiling helper (Jun 14 2026): never surface more than
    # DIPLOMATIC_SURFACE_CAP diplomatic signals (keep the highest-ranked).
    # Applied to BOTH return paths so the cap holds whether or not the
    # axis-rebalancing branch runs.
    # ══════════════════════════════════════════════════════════════════════
    # NARRATIVE DECAY  (Jul 25 2026)
    # ══════════════════════════════════════════════════════════════════════
    # The GPI's job is to surface what is CHANGING. A signal that has said the
    # same thing at the same level for weeks is a standing condition, not a
    # topline -- and while it holds a headline slot, something moving cannot.
    #
    # KEYED ON MOVEMENT, NOT A CURATED LIST. That distinction is the whole
    # design: a genuinely ongoing crisis MOVES (new strikes, new rounds, new
    # casualty figures, new diplomatic cadence) and therefore never decays.
    # Iran/Hormuz, Russia-Ukraine and Israel-Hezbollah stay put on their own
    # merits. What decays is the static tally -- Lebanon's humanitarian totals
    # after the June 26 Trilateral Framework and the ceasefire that followed:
    # the crisis is entirely real, the numbers have simply stopped moving, and
    # a number that has stopped moving is no longer driving a GLOBAL cycle.
    #
    # It still shows at the altitudes where it IS the story -- the ME regional
    # BLUF and the Lebanon page -- because decay is applied here, at GPI
    # ranking, and nowhere else.
    #
    # Decay never removes a signal. It lowers priority so headline slots go to
    # movement, with a floor so a standing condition stays visible below.
    def _cap_diplomatic(lst):
        kept, dip_seen = [], 0
        for _s in lst:
            if _infer_pressure_type(_s) == PRESSURE_DIPLOMATIC:
                if dip_seen >= DIPLOMATIC_SURFACE_CAP:
                    continue
                dip_seen += 1
            kept.append(_s)
        return kept

    if len(deduped) <= CORE_HEADLINE_COUNT:
        # Not enough signals to need rebalancing — strip internals and return
        capped = _cap_diplomatic(deduped)
        for s in capped:
            s.pop('_tier_boost', None)
            s.pop('_sort_key', None)
        return capped[:TOP_GLOBAL_SIGNALS_COUNT]

    # Take first CORE_HEADLINE_COUNT as-is (pure tier+priority)
    headline_block = deduped[:CORE_HEADLINE_COUNT]
    candidate_pool = deduped[CORE_HEADLINE_COUNT:]
    remaining_slots = TOP_GLOBAL_SIGNALS_COUNT - CORE_HEADLINE_COUNT  # e.g. 20-12 = 8

    # Count axis representation already present in the headline block
    axis_counts = {axis: 0 for axis in PRESSURE_AXES}
    for s in headline_block:
        # Use existing pressure_type if tagged; otherwise infer
        axis = _infer_pressure_type(s)
        if axis in axis_counts:
            axis_counts[axis] += 1

    # Build the rebalanced tail: prefer candidates from axes currently below MIN_SIGNALS_PER_AXIS
    tail_block = []
    candidates_by_axis = {axis: [] for axis in PRESSURE_AXES}
    for s in candidate_pool:
        axis = _infer_pressure_type(s)
        if axis in candidates_by_axis:
            candidates_by_axis[axis].append(s)

    # Phase A: bring each axis up to its floor. Diplomatic gets a HIGHER floor
    # (DIPLOMATIC_SURFACE_CAP) and is filled FIRST, so de-escalation tracks are
    # guaranteed to surface and are not crowded out of the tail by other axes.
    _axis_floor = {ax: MIN_SIGNALS_PER_AXIS for ax in PRESSURE_AXES}
    _axis_floor[PRESSURE_DIPLOMATIC] = DIPLOMATIC_SURFACE_CAP
    _fill_order = [PRESSURE_DIPLOMATIC] + [ax for ax in PRESSURE_AXES if ax != PRESSURE_DIPLOMATIC]
    for axis in _fill_order:
        while (axis_counts[axis] < _axis_floor[axis]
               and candidates_by_axis[axis]
               and len(tail_block) < remaining_slots):
            picked = candidates_by_axis[axis].pop(0)
            tail_block.append(picked)
            axis_counts[axis] += 1

    # Phase B: fill any remaining slots from highest-priority leftover candidates
    if len(tail_block) < remaining_slots:
        leftovers = []
        for axis in PRESSURE_AXES:
            leftovers.extend(candidates_by_axis[axis])
        leftovers.sort(key=lambda x: x.get('_sort_key', 0), reverse=True)
        for s in leftovers:
            if len(tail_block) >= remaining_slots:
                break
            tail_block.append(s)

    # Combine + strip internal fields, then enforce the diplomatic ceiling.
    final = _cap_diplomatic(headline_block + tail_block)
    for s in final:
        s.pop('_tier_boost', None)
        s.pop('_sort_key', None)
    return final[:TOP_GLOBAL_SIGNALS_COUNT]


# ============================================================
# BLUF SYNTHESIS
# ============================================================
def _synthesize_global_bluf(blufs, narratives, global_level):
    """
    Generate the 3-5 sentence analyst-prose BLUF.
    Top narratives drive the lead; regional summaries follow.

    Narratives are re-sorted with tier boosts (v1.1):
      Cross-regional (≥2 regions) leads, then active-conflict regions,
      then single-region narratives. This mirrors the top_signals sort
      so the prose lead matches what the analyst sees in the signal list.
    """
    date_str = datetime.now(timezone.utc).strftime('%b %d, %Y %H:%MZ')
    parts = [f'Global Pressure Index ({date_str}):']

    # ── Re-sort narratives with tier boost so cross-regional leads ──
    def _narrative_tier_boost(n):
        regions = n.get('regions') or []
        # Cross-regional narrative (>=2 regions): leads
        if isinstance(regions, list) and len(regions) >= 2:
            return 30
        # Single-region narrative pointing at an L5 region: active-conflict tier
        for r in regions:
            bluf = blufs.get(r) or {}
            if _level_of(bluf) >= 5:
                return 20
        # Otherwise: standard regional narrative
        return 10

    real_narratives = [n for n in narratives
                       if n.get('category') not in ('global_baseline', 'global_warning')
                       and n.get('tier') != 'standing']   # v3.12.0: standing never leads
    real_narratives.sort(
        key=lambda n: _narrative_tier_boost(n) + int(n.get('priority', 0) or 0),
        reverse=True,
    )

    # Lead: highest tier-adjusted narrative
    leading = real_narratives[0] if real_narratives else None

    if leading:
        parts.append(leading['headline'] + '.')
        parts.append(leading['detail'])
    else:
        # Fallback to baseline narrative
        baseline = next((n for n in narratives), None)
        if baseline:
            parts.append(baseline['headline'] + '.')
            parts.append(baseline['detail'])

   # ────────────────────────────────────────────────────────────
    # DYNAMIC BLUF ENRICHMENT (v3.0 -- May 19, 2026)
    #
    # v3.0 FIX: Pool signals from ALL regional BLUFs FIRST, then sort
    # globally by level + priority + axis-diversity, THEN take top 5.
    #
    # Previous v2.5 bug: nested loops with outer `break` exited after
    # the FIRST region produced 5 signals, starving humanitarian +
    # cascade detector signals (which iterate later in dict order).
    # Symptom: BLUF felt static; humanitarian convergence never popped.
    #
    # Behavior change: BLUF now reflects the highest-impact signals
    # globally regardless of which region emitted them. Humanitarian
    # (L4-5 convergence) + cascade (L4-5 economic) now surface inline.
    # ────────────────────────────────────────────────────────────
    pooled_signals = []
    seen_short_texts = set()

    # Step 1a: Pool ALL signals from ALL regional BLUFs (incl. pseudo-regions)
    for region_key, bluf in (blufs or {}).items():
        if not isinstance(bluf, dict):
            continue
        sigs = bluf.get('top_signals') or bluf.get('signals') or []
        if not isinstance(sigs, list):
            continue
        for sig in sigs:
            if not isinstance(sig, dict):
                continue
            stext = sig.get('short_text') or sig.get('text') or ''
            stext = str(stext)[:140]
            if not stext or stext in seen_short_texts:
                continue
            level = _safe_level(sig.get('level', 0))
            if level < 2:
                continue
            seen_short_texts.add(stext)
            pooled_signals.append({
                'region':        region_key,
                'theatre':       sig.get('theatre', region_key),
                'level':         level,
                'priority':      int(sig.get('priority', 0) or 0),
                'pressure_type': _infer_pressure_type(sig),
                'icon':          sig.get('icon') or '',
                'short_text':    stext,
            })

    # Step 1b: ALSO pool cross-theater narratives (v3.7 May 25 2026)
    # Without this, narratives like 'Russia-Iran axis', 'China-Taiwan takeover',
    # 'Nuclear signaling' never surface in Driving Signals because they live in
    # the narratives list, not in any regional BLUF's top_signals. Result: the
    # BLUF prose felt static even when cross-theater convergences fired.
    # We promote each narrative into the pool with level derived from priority
    # (priority>=13 → L5, else L4) so they sort fairly against regional signals.
    for n in (narratives or []):
        if not isinstance(n, dict):
            continue
        cat = n.get('category', '')
        # Skip baseline/warning narratives (analytic filler, not real headlines)
        if cat in ('global_baseline', 'global_warning'):
            continue
        stext = n.get('headline', '')[:140]
        if not stext or stext in seen_short_texts:
            continue
        priority = int(n.get('priority', 0) or 0)
        level = 5 if priority >= 13 else 4
        seen_short_texts.add(stext)
        pooled_signals.append({
            'region':        '+'.join(n.get('regions') or ['global']),
            'theatre':       'global',                       # narratives are cross-theater
            'level':         level,
            'priority':      priority + 10,                  # +10 boost (narrative tier ≈ Tier 3)
            'pressure_type': (_axes_for_narrative(n)[0]),
            'axes':          _axes_for_narrative(n),
            'icon':          n.get('icon') or '',
            'short_text':    stext,
            'is_narrative':  True,
        })

    # Step 2: Sort globally by level DESC, priority DESC (highest-impact first)
    pooled_signals.sort(
        key=lambda s: (s['level'], s['priority']),
        reverse=True,
    )

    # Step 3: Pick up to 5 Driving Signals with STRICT axis + theatre diversity.
    # v3.7 (May 25 2026): Lebanon used to eat 2-3 slots because it dominated
    # both Kinetic AND Humanitarian. New rule: max 1 signal per axis AND
    # max 1 signal per theatre, except the lead signal which is unconstrained.
    # This forces the prose to surface a wider range of the actual world state.
    live_signal_lines = []
    axes_represented = set()
    theatres_represented = set()
    deferred = []
    for sig in pooled_signals:
        axis = sig.get('pressure_type', 'kinetic')
        theatre = sig.get('theatre', '')
        # First pass: max 1 per axis AND max 1 per theatre
        if axis in axes_represented or theatre in theatres_represented:
            deferred.append(sig)
            continue
        axes_represented.add(axis)
        theatres_represented.add(theatre)
        live_signal_lines.append(f"{sig['icon']} {sig['short_text']}".strip())
        if len(live_signal_lines) >= 5:
            break
    # Second pass: fill remaining slots from deferred pool by global rank
    # (still avoiding exact theatre duplication, but axis can repeat)
    for sig in deferred:
        if len(live_signal_lines) >= 5:
            break
        theatre = sig.get('theatre', '')
        # Allow theatre repeat only if we'd otherwise have <3 signals (defensive)
        if theatre in theatres_represented and len(live_signal_lines) >= 3:
            continue
        theatres_represented.add(theatre)
        live_signal_lines.append(f"{sig['icon']} {sig['short_text']}".strip())

    # Add the live-signals sentence if any surfaced
    if live_signal_lines:
        parts.append('Driving signals this scan: ' + '; '.join(live_signal_lines) + '.')

    # Secondary narratives (briefly) -- also use tier-sorted order
    secondary = real_narratives[1:3]
    if secondary:
        sec_lines = [f"{n['icon']} {n['headline']}" for n in secondary]
        parts.append('Concurrent narratives: ' + '; '.join(sec_lines) + '.')

    # Regional summary line
    region_levels = []
    for r in CARD_ORDER:
        bluf = blufs.get(r)
        if bluf:
            region_levels.append(f"{REGION_DISPLAY[r]['name']} L{_level_of(bluf)}")
    if region_levels:
        parts.append('Regional posture: ' + ', '.join(region_levels) + '.')

    # Pressure axes summary line (v2.5) -- shows axis breakdown inline
    # so the BLUF reflects multi-axis pressure even when the leading
    # narrative is single-axis.
    try:
        axes_payload = _build_pressure_axes_payload(blufs, narratives)
        axes_inner = (axes_payload or {}).get('axes', {})
        axis_summary_parts = []
        for ax_name in PRESSURE_AXES:   # v3.12.0: includes governance
            ax = axes_inner.get(ax_name, {}) or {}
            ax_level = ax.get('level', 0) or 0
            if ax_level > 0:
                _ml = ax.get('motion_label') if ax_level >= 4 else ''
                axis_summary_parts.append(f"{ax_name.capitalize()} L{ax_level}"
                                          + (f" ({_ml})" if _ml else ''))
        if axis_summary_parts:
            parts.append('Pressure axes: ' + ', '.join(axis_summary_parts) + '.')
    except Exception as _e:
        pass  # axes summary is enrichment; never blocks the BLUF

    # v3.12.0 -- when the novelty gate holds the index at L4, say WHY in the
    # same breath. "L4 -- COERCION" over a live war would be false.
    _gate = _LAST_LEVEL_GATE or {}
    _l6 = _LAST_L6 or {}
    # v3.14.0 -- when the index is held below its own axes, explain it once.
    try:
        if _gate.get('applied'):
            _hi = [ax for ax, d in ((axes_payload or {}).get('axes') or {}).items()
                   if (d or {}).get('level', 0) > global_level]
            if _hi:
                _new_hi = [ax for ax in _hi
                           if ((axes_payload or {}).get('axes') or {}).get(ax, {}).get('motion') == 'new']
                parts.append(
                    'Severity vs motion: the %s ax%s read%s higher than the index because axis '
                    'levels measure how severe the worst reading is, while the index measures '
                    'whether the world got worse this fortnight.%s' % (
                        ', '.join(a.title() for a in _hi), 'es' if len(_hi) > 1 else 'is',
                        '' if len(_hi) > 1 else 's',
                        (' New this cycle on: %s.' % ', '.join(a.title() for a in _new_hi))
                        if _new_hi else ''))
    except Exception:
        pass
    if _l6.get('active'):
        _e = sorted(_l6.get('events') or [], key=lambda x: x.get('confirmed_at', ''))[-1]
        parts.append(f"Global level: L6 -- {L6_LABEL}. {_e.get('class_label', '')} "
                     f"({str(_e.get('theatre', '')).replace('_', ' ').title()}), confirmed by "
                     f"institutional reaction; day {_e.get('day', 0)} of a {L6_HOLD_DAYS}-day hold, "
                     f"after which the novelty gate re-assesses.")
        return ' '.join(parts)
    if _gate.get('applied'):
        parts.append(f"Global level: L{global_level} -- {SUSTAINED_LABEL}. {_gate.get('summary', '')}")
    else:
        parts.append(f"Global level: L{global_level} -- {GLOBAL_LEVEL_LABELS.get(global_level, '')}.")
        if global_level >= 5 and _gate.get('fresh'):
            parts.append(_gate.get('reason', ''))

    return ' '.join(parts)


# ============================================================
# PER-AXIS BLUF GENERATORS (v3.0 -- May 19 2026)
# ============================================================
# Each axis gets its own focused prose synthesis using ONLY signals tagged
# with that pressure_type. Produces 4 BLUF variants the frontend can swap
# between when user clicks pressure vector cards.
#
# Architecture: pulls from the same axis payload that _build_pressure_axes_payload
# already constructs. Zero duplication of analytical logic.
# ============================================================

_AXIS_PROSE_PREAMBLES = {
    'kinetic': {
        'label':    'Kinetic',
        'icon':     '⚔️',
        'lens':     'strikes, mobilization, ultimatums, casualties',
        'open':     'Kinetic pressure view',
        'no_sig':   'No active kinetic signals — strikes / mobilization / ultimatums at baseline.',
    },
    'economic': {
        'label':    'Economic',
        'icon':     '📈',
        'lens':     'commodity surges, currency stress, sanctions, supply chain',
        'open':     'Economic pressure view',
        'no_sig':   'No active economic signals — commodity / currency / sanctions pressures at baseline.',
    },
    'diplomatic': {
        'label':    'Diplomatic',
        'icon':     '🕊️',
        'lens':     'ceasefire arithmetic, mediation tempo, alliance shifts',
        'open':     'Diplomatic pressure view',
        'no_sig':   'No active diplomatic signals — mediation tracks / ceasefire posture at baseline.',
    },
    'humanitarian': {
        'label':    'Humanitarian',
        'icon':     '🆘',
        'lens':     'displacement flows, civilian harm, famine, refugee surges',
        'open':     'Humanitarian pressure view',
        'no_sig':   'No active humanitarian signals — civilian-harm / displacement / famine indicators at baseline.',
    },
    'governance': {
        'label':    'Governance',
        'icon':     '🏛️',
        'lens':     'elections, caretaker periods, successions, coups, legitimacy contests',
        'open':     'Governance pressure view',
        'no_sig':   'No active governance signals — no election, formation window, succession or legitimacy contest is registering.',
    },
}


def _synthesize_axis_bluf(axis_name, axes_payload, blufs, global_level):
    """
    Generate a focused prose BLUF for a single pressure axis.

    Pulls signals from axes_payload (already segmented by pressure_type),
    names which regions are firing on this axis, and produces 3-5 sentences
    of analyst-prose specifically about that axis.

    Args:
        axis_name:     'kinetic' | 'economic' | 'diplomatic' | 'humanitarian'
        axes_payload:  output of _build_pressure_axes_payload()
        blufs:         regional BLUFs dict (for context)
        global_level:  overall GPI level

    Returns:
        str: focused multi-sentence BLUF for this axis
    """
    if axis_name not in _AXIS_PROSE_PREAMBLES:
        return ''
    meta = _AXIS_PROSE_PREAMBLES[axis_name]
    date_str = datetime.now(timezone.utc).strftime('%b %d, %Y %H:%MZ')

    # Pull this axis's data
    axis_data = (axes_payload or {}).get('axes', {}).get(axis_name, {}) or {}
    axis_level = axis_data.get('level', 0)
    axis_signals = axis_data.get('top_signals', []) or []
    region_levels = axis_data.get('region_levels', {}) or {}
    signal_count = axis_data.get('signal_count', 0)

    parts = []
    # Header
    parts.append(f"{meta['icon']} {meta['open']} ({date_str}):")

    # No-signal short-circuit
    if axis_level == 0 or not axis_signals:
        parts.append(meta['no_sig'])
        parts.append(f"(Headline GPI level remains L{global_level} -- driven by other axes.)")
        return ' '.join(parts)

    # Headline sentence: axis level + dominant regions
    region_strs = []
    for region, lvl in sorted(region_levels.items(), key=lambda x: -x[1]):
        region_name = REGION_DISPLAY.get(region, {}).get('name', region)
        region_strs.append(f"{region_name} L{lvl}")
    region_summary = ', '.join(region_strs) if region_strs else 'multi-region'
    _mo_note = axis_data.get('motion_note') or ''
    parts.append(
        f"Axis at L{axis_level} ({_axis_level_label(axis_name, axis_level)}"
        f"{', ' + axis_data.get('motion_label') if axis_data.get('motion_label') else ''}) -- "
        f"{signal_count} active signal(s) across {len(region_levels)} region(s): "
        f"{region_summary}."
    )

    # Top-signal sentences (up to 3) -- the specific story
    top_lines = []
    for sig in axis_signals[:3]:
        stext = (sig.get('short_text') or sig.get('text') or '')[:140]
        if stext:
            icon = sig.get('icon') or meta['icon']
            top_lines.append(f"{icon} {stext}")
    if top_lines:
        parts.append('Driving signals: ' + '; '.join(top_lines) + '.')
    # v3.14.0 -- say what the motion read means, and why this axis can sit above
    # the headline index without either number being wrong.
    if _mo_note:
        parts.append('Motion: ' + _mo_note)
    if axis_level > (global_level or 0) and axis_level >= 4:
        parts.append(f"Why this axis reads L{axis_level} while the index reads L{global_level}: "
                     f"an axis level is SEVERITY (how bad the worst reading is); the index "
                     f"level is MOTION (whether the world got worse this fortnight).")

    # Analytical lens reminder + cross-axis context
    other_axes_high = []
    all_axes = (axes_payload or {}).get('axes', {})
    for other_name, other_data in all_axes.items():
        if other_name == axis_name:
            continue
        if (other_data or {}).get('level', 0) >= 4:
            other_axes_high.append(
                f"{_AXIS_PROSE_PREAMBLES.get(other_name, {}).get('label', other_name)} L{other_data['level']}"
            )
    if other_axes_high:
        parts.append(
            f"Context: while {meta['label'].lower()} dominates this view, "
            f"other axes are also elevated -- {', '.join(other_axes_high)}."
        )

    return ' '.join(parts)


def _synthesize_all_axis_blufs(axes_payload, blufs, global_level):
    """
    Generate all per-axis BLUFs (5 since v3.12.0) as a dict keyed by axis name.
    Frontend uses this to swap content when user clicks pressure vector cards.
    """
    return {
        axis: _synthesize_axis_bluf(axis, axes_payload, blufs, global_level)
        for axis in PRESSURE_AXES
    }


# ============================================================
# REGIONAL CARD EXTRACTION
# ============================================================
def _build_regional_card(region, bluf):
    """Extract a small card representation for the GPI page."""
    if not bluf:
        return {
            'region':        region,
            'name':          REGION_DISPLAY[region]['name'],
            'flag':          REGION_DISPLAY[region]['flag'],
            'hub_url':       REGION_DISPLAY[region]['hub'],
            'available':     False,
            'level':         0,
            'level_label':   'UNAVAILABLE',
            'level_color':   '#6b7280',
            'posture_label': 'Unavailable',
            'posture_color': '#6b7280',
            'bluf_excerpt':  'Regional BLUF unavailable.',
            'top_signals':   [],
            'trackers_live':    0,
            'trackers_total':   0,
            'trackers_stale':   [],
            'trackers_missing': [],
            'picture_complete': False,   # region unreachable -> picture incomplete (honesty)
        }
    level = _level_of(bluf)
    bluf_text = bluf.get('bluf', '') or ''
    # Take first 300 chars as excerpt, prefer ending at sentence
    excerpt = bluf_text[:300]
    if len(bluf_text) > 300:
        last_period = excerpt.rfind('. ')
        if last_period > 100:
            excerpt = excerpt[:last_period + 1]
        else:
            excerpt += '...'

    # v2.3.0 — Regional card top_signals uses axis-quota (one per non-empty axis,
    # dynamic max 4). Previously took top 3 by priority, which on multi-axis-active
    # regions (like ME with kinetic L5 + humanitarian L5 + diplomatic L1) showed only
    # the 3 highest-priority kinetic signals and hid the other axes entirely. Now
    # each non-empty axis gets its top signal represented on the card.
    return {
        'region':        region,
        'name':          REGION_DISPLAY[region]['name'],
        'flag':          REGION_DISPLAY[region]['flag'],
        'hub_url':       REGION_DISPLAY[region]['hub'],
        'available':     True,
        'level':         level,
        'level_label':   GLOBAL_LEVEL_LABELS.get(level, ''),
        'level_color':   GLOBAL_LEVEL_COLORS.get(level, '#6b7280'),
        'posture_label': bluf.get('posture_label', '') or '',
        'posture_color': bluf.get('posture_color', '#6b7280'),
        'bluf_excerpt':  excerpt,
        'top_signals':   _build_axis_quota_signals(bluf),
        'trackers_live': bluf.get('trackers_live', bluf.get('theatres_live', 0)),
        'trackers_total':   bluf.get('trackers_total', 0),
        'trackers_stale':   bluf.get('trackers_stale', []) or [],
        'trackers_missing': bluf.get('trackers_missing', []) or [],
        'picture_complete': bluf.get('picture_complete', True),  # default True: pre-A/B/C regions
        'avg_score':     bluf.get('avg_score', 0),
    }


def _build_axis_quota_signals(bluf):
    """
    Build the regional card's top_signals using axis-quota:
    one highest-priority signal per non-empty axis, dynamic max 4 (one per axis).

    Why: prevents the regional card from showing all-kinetic when other axes are
    active. Each card represents a region's posture across the four pressure
    dimensions; the analytical principle is that one diplomatic signal in a
    largely-kinetic region is more informative than the 3rd-ranked kinetic signal.

    Returns list ordered by axis presence (kinetic, economic, diplomatic, humanitarian).
    """
    sigs = _signals_of(bluf)
    if not sigs:
        return []
    tagged = _tag_pressure_axes(sigs)

    # Walk axes in canonical order; pick top-priority signal per axis.
    out = []
    for axis in PRESSURE_AXES:
        candidates = [s for s in tagged if s.get('pressure_type') == axis]
        if not candidates:
            continue
        # Sort by priority desc, then level desc — pick the strongest per axis
        candidates.sort(
            key=lambda s: (
                _safe_level(s.get('priority', 0)),
                _safe_level(s.get('level', 0)),
            ),
            reverse=True,
        )
        out.append(candidates[0])
    return out


# ============================================================
# MAIN BUILD FUNCTION
# ============================================================
# ============================================================
# CANONICAL-TERM NORMALIZATION (Jul 2026)
# .title() on dynamic names and source inconsistency mangle acronyms/proper
# nouns in generated prose (ARAMCO->Aramco, DRC->Drc, ISKP->Iskp). This final
# pass restores canonical casing over GPI prose only. Extend CANONICAL_TERMS as
# new cases surface. Casing only -- first-reference spell-out is a separate feature.
# ============================================================
CANONICAL_TERMS = {
    'aramco': 'ARAMCO',
    'drc':    'DRC',
    'iskp':   'ISKP',
    # add more here as identified, e.g. 'uae': 'UAE', 'opec': 'OPEC'
}
_CANONICAL_RX = [(re.compile(r'\b' + re.escape(k) + r'\b', re.IGNORECASE), v)
                 for k, v in CANONICAL_TERMS.items()]

_PROSE_KEYS = {'headline', 'detail', 'short_text', 'long_text', 'text',
               'narrative', 'bluf', 'summary', 'situation', 'assessment'}

def _normalize_terms(text):
    """Restore canonical acronym/proper-noun casing in a single prose string."""
    if not isinstance(text, str) or not text:
        return text
    for rx, repl in _CANONICAL_RX:
        text = rx.sub(repl, text)
    return text

def _normalize_payload_terms(obj):
    """Recursively normalize canonical terms across the GPI payload's prose.
    Normalizes string values under a known prose key OR any multi-word string
    (prose has spaces; ids/colors/categories/urls do not), so structured
    fields like ids and hex colors are left untouched."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if k in _PROSE_KEYS or ' ' in v:
                    obj[k] = _normalize_terms(v)
            else:
                _normalize_payload_terms(v)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                if ' ' in item:
                    obj[i] = _normalize_terms(item)
            else:
                _normalize_payload_terms(item)
    return obj


# ============================================================
# THEATRE GROUPING + CONVERGENCE SYNTHESIS  (v3.2, Jul 15 2026)
# ============================================================
# Sidequest 2+3: five separate Iran signals as five separate cards is five
# true statements hiding one compound truth. This pass groups top_signals by
# THEATRE (country), attaches the axis pills present in the group, and writes
# ONE dynamic synthesis line that reads the whole story -- the convergence-at-
# country-level read the platform exists to make. Global/regional/multi-hub
# signals stay UNGROUPED by design (they are already synthesis products).
# Additive + non-breaking: emitted as `grouped_signals` alongside the intact
# `top_signals`, so existing consumers keep working until the frontend opts in.

# theatres that are synthesis products, not countries -- never grouped
_UNGROUPED_THEATRES = frozenset({
    'global', 'regional', 'asia', 'europe', 'middle east', 'middle_east',
    'western hemisphere', 'wha', 'africa', 'the western hemisphere',
})

_AXIS_ORDER = ['kinetic', 'economic', 'diplomatic', 'humanitarian', 'governance']

def _synthesize_theatre_group(theatre, sigs):
    """One dynamic line reading a country's WHOLE story this scan.

    Voice rules (canon): estimative, precedent-anchored where possible, never
    'will'. Multi-axis simultaneity IS the read -- name the axes, name the
    loudest signal on each, and say what stacking means. Single-axis groups
    get a narrower multiple-signals read.
    """
    by_axis = {}
    for sg in sigs:
        ax = (sg.get('pressure_type') or 'kinetic').lower()
        by_axis.setdefault(ax, []).append(sg)
    axes = [a for a in _AXIS_ORDER if a in by_axis]
    for a in by_axis:                      # any nonstandard axis tags trail
        if a not in axes:
            axes.append(a)
    peak = max((_safe_level(sg.get('level', 0)) for sg in sigs), default=0)
    name = theatre.upper()

    if len(axes) >= 2:
        # the compound read: name each axis with its loudest signal fragment
        frags = []
        for a in axes:
            loudest = max(by_axis[a], key=lambda sg: _safe_level(sg.get('level', 0)))
            frag = (loudest.get('short_text') or '')[:70].rstrip(' .;')
            frags.append(f"{a} ({frag})" if frag else a)
        return (f"{name} is running pressure on {len(axes)} axes simultaneously this scan -- "
                + '; '.join(frags) + ". "
                f"Multi-axis simultaneity at the country level is the compound read: "
                f"separate signals on separate channels converging on one theatre is "
                f"historically a stronger indicator than any single channel at the same level.")
    else:
        ax = axes[0] if axes else 'kinetic'
        n = len(sigs)
        return (f"{name}: {n} distinct {ax} signals active in the same window (peak L{peak}). "
                f"Breadth on a single axis reads as sustained pressure, not an isolated event.")

def _group_signals_by_theatre(top_signals):
    """Bucket top_signals by theatre. Returns (grouped, passthrough).

    grouped: list of {theatre, display, peak_level, axes, pills, signal_count,
             synthesis, signals[]} sorted by peak level desc then count.
    passthrough: global/regional/synthesis signals, order preserved.
    Groups form at >=2 signals; singletons stay in passthrough (a group of one
    is just a card with extra steps).
    """
    buckets, passthrough, order = {}, [], []
    for sg in top_signals or []:
        th = str(sg.get('theatre') or sg.get('region') or '').strip().lower()
        if not th or th in _UNGROUPED_THEATRES or '+' in th:
            passthrough.append(sg)
            continue
        if th not in buckets:
            buckets[th] = []
            order.append(th)
        buckets[th].append(sg)

    grouped = []
    for th in order:
        sigs = buckets[th]
        if len(sigs) < 2:
            passthrough.extend(sigs)       # singleton -- render as before
            continue
        axes_present = []
        for sg in sigs:
            ax = (sg.get('pressure_type') or 'kinetic').lower()
            if ax not in axes_present:
                axes_present.append(ax)
        axes_sorted = [a for a in _AXIS_ORDER if a in axes_present] + \
                      [a for a in axes_present if a not in _AXIS_ORDER]
        peak = max((_safe_level(sg.get('level', 0)) for sg in sigs), default=0)
        grouped.append({
            'theatre':      th,
            'display':      th.title(),
            'peak_level':   peak,
            'axes':         axes_sorted,           # the pills
            'signal_count': len(sigs),
            'synthesis':    _synthesize_theatre_group(th, sigs),
            'signals':      sigs,                  # full originals for peel-off by pill
        })
    grouped.sort(key=lambda g: (g['peak_level'], g['signal_count']), reverse=True)
    return grouped, passthrough


def build_gpi(force=False):
    """Build the full GPI synthesis."""
    if not force:
        cached = _redis_get(GPI_CACHE_KEY)
        if cached and cached.get('generated_at'):
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(cached['generated_at'])).total_seconds()
                if age < GPI_CACHE_TTL:
                    cached['from_cache'] = True
                    return cached
            except Exception:
                pass

    print('[GPI v2.0] Building global synthesis from all 4 regional BLUFs...')

    try:
        blufs = _fetch_all_regional_blufs()

        if not blufs:
            return {
                'success':       False,
                'error':         'No regional BLUFs available',
                'global_level':  0,
                'global_label':  'UNAVAILABLE',
                'global_color':  '#6b7280',
                'bluf':          'GPI unavailable -- no regional BLUFs reachable.',
                'convergence_panel': None,
                'narratives':    [],
                'top_signals':   [],
                'regional_cards': [],
            }

        # v3.16.0 -- before anything reads a level: a country's commodity-news
        # SURGE may not claim more than the commodity has earned.
        global _LAST_COMMODITY_CAP
        _LAST_COMMODITY_CAP = _apply_commodity_evidence_cap(blufs)

        # v3.14.0 -- fresh motion state per build (a failed build must not leave
        # a half-loaded state behind for the next one).
        _AXIS_MOTION_STATE.update(loaded=False, ok=False, data=None, dirty=False, first_run=False)
        narratives    = _detect_narratives(blufs)
        # v3.12.0 -- tier BEFORE the level: a standing watch may not supply the
        # convergence boost, so the tiers have to exist when the level is set.
        try:
            narratives = _tier_narratives(narratives)
        except Exception as _tier_err:
            print(f'[GPI tiers] skipped (non-fatal): {str(_tier_err)[:120]}')
        # v3.13.0 -- L6 doctrine runs FIRST: it demotes tracker L6 signals that
        # are not world-altering, so neither the level, the gate's breach bypass
        # nor the banner ever sees an unqualified L6.
        global _LAST_L6
        try:
            _LAST_L6 = _evaluate_l6_doctrine(blufs, _sustained_theatres_snapshot())
        except Exception as _l6_err:
            _LAST_L6 = {'active': False, 'events': [], 'candidates': [], 'demoted': [],
                        'error': str(_l6_err)[:160]}
            print(f'[GPI L6] doctrine error (non-fatal, nothing promoted): {str(_l6_err)[:160]}')
        global_level  = _compute_global_level(blufs, narratives)
        # v3.12.0 -- severity vs motion. Only ever lowers 5 -> 4.
        global _LAST_LEVEL_GATE
        _LAST_LEVEL_GATE = {}
        try:
            global_level, _LAST_LEVEL_GATE = _apply_l5_novelty_gate(global_level, blufs)
        except Exception as _gate_err:
            _LAST_LEVEL_GATE = {'available': False, 'applied': False,
                                'reason': 'Novelty gate error -- level shown ungated.'}
            print(f'[GPI L5 gate] error (non-fatal, ungated): {str(_gate_err)[:160]}')
        if _LAST_L6.get('active'):
            # A confirmed world-altering event holds the index at L6 for 7 days.
            global_level = 6
            global_label = GLOBAL_LEVEL_LABELS[6]
            global_color = GLOBAL_LEVEL_COLORS[6]
        elif _LAST_LEVEL_GATE.get('applied'):
            global_label = SUSTAINED_LABEL
            global_color = SUSTAINED_COLOR
        else:
            global_label = GLOBAL_LEVEL_LABELS.get(global_level, '')
            global_color = GLOBAL_LEVEL_COLORS.get(global_level, '#6b7280')
        bluf_prose    = _synthesize_global_bluf(blufs, narratives, global_level)
        top_signals   = _build_global_top_signals(blufs, narratives)
        # v2.2 — multi-axis pressure aggregation (kinetic / economic / diplomatic / humanitarian)
        # Headline level remains kinetic-driven; pressure_axes is additive payload for frontend.
        pressure_axes = _build_pressure_axes_payload(blufs, narratives)
        try:
            _axis_motion_save()
        except Exception as _ms_err:
            print(f'[GPI motion] save failed (non-fatal): {str(_ms_err)[:100]}')

        # Regional cards in alphabetical order
        regional_cards = []
        for region in CARD_ORDER:
            regional_cards.append(_build_regional_card(region, blufs.get(region)))

        # v3.0 — Per-axis BLUF generation (one focused prose per pressure axis)
        bluf_by_axis = _synthesize_all_axis_blufs(pressure_axes, blufs, global_level)

        # v3.1 -- Data-completeness honesty (Jun 13 2026): roll up each region's
        # cold-start gaps (trackers_missing / trackers_stale / picture_complete,
        # emitted by the A/B/C regional BLUFs) so the GPI never silently treats an
        # incomplete picture as a confident full read. Absence stays honest at GPI
        # altitude. Card-regions that have a real endpoint are checked (africa joins
        # automatically once its BLUF ships); the global_* convergence feeds are not.
        _card_regions = [r for r in CARD_ORDER if r in REGIONAL_BLUF_ENDPOINTS]
        _incomplete_regions = []
        _all_missing = []
        _all_stale = []
        for _region in _card_regions:
            _b = blufs.get(_region)
            if not _b:
                _incomplete_regions.append(_region)   # endpoint exists but unreachable this cycle
                continue
            if not _b.get('picture_complete', True):
                _incomplete_regions.append(_region)
            for _t in (_b.get('trackers_missing') or []):
                _all_missing.append(f'{_region}:{_t}')
            for _t in (_b.get('trackers_stale') or []):
                _all_stale.append(f'{_region}:{_t}')
        data_completeness = {
            'picture_complete':   (len(_incomplete_regions) == 0),
            'incomplete_regions': _incomplete_regions,
            'trackers_missing':   _all_missing,   # 'europe:greenland' form
            'trackers_stale':     _all_stale,
            'regions_live':       len([r for r in _card_regions if blufs.get(r)]),
            'regions_expected':   len(_card_regions),
        }

        result = {
            'success':         True,
            'from_cache':      False,
            'generated_at':    datetime.now(timezone.utc).isoformat(),
            'version':         GPI_VERSION,
            'global_level':    global_level,
            'global_label':    global_label,
            'global_color':    global_color,
            # v3.12.0 -- why the level reads what it reads (fresh vs sustained
            # fronts, day counts, breach bypass). The page renders this under
            # the badge; it is the honesty line for a held L4.
            'level_gate':      _LAST_LEVEL_GATE,
            'commodity_cap':   _LAST_COMMODITY_CAP,     # v3.16.0
            # v3.13.0 -- L6 doctrine: confirmed events (7-day hold), candidates
            # that passed the class test but lack world reaction, and tracker
            # L6 signals demoted to L5 with the reason.
            'l6':              _LAST_L6,
            'narrative_tiers': {
                'topline':  sum(1 for n in narratives if n.get('tier') != 'standing'),
                'standing': sum(1 for n in narratives if n.get('tier') == 'standing'),
                'standing_after_days': NARRATIVE_STANDING_DAYS,
            },
            'bluf':            bluf_prose,
            'bluf_by_axis':    bluf_by_axis,    # v3.0 — per-axis focused prose for click-through UX
            'convergence_panel': _get_convergence_panel(),
            # Narratives get country tags as well (Jul 27 2026). An earlier pass
            # tagged only top_signals, so the ECONOMIC card -- whose prose is
            # narrative-driven and routinely names "China, Brazil, India" or
            # "Qatar" mid-sentence -- rendered no pills at all. Narratives are
            # exactly where multi-country prose lives, so they were the worst
            # place to miss.
            'narratives':      _attach_country_tags(narratives),
            'top_signals':     _attach_country_tags(top_signals),
            # Per-country view ACROSS theatres (Jul 27 2026). grouped_signals
            # keys on theatre and therefore cannot see that four separate
            # signals all touch Iran. This can.
            'country_rollup':  _build_country_rollup(
                                   list(top_signals) + list(narratives or [])),
            # Diagnostic: the signal list BEFORE dedupe and capping. Lets the
            # tagging audit measure what bundling actually costs -- how many
            # signals collapsed, and how many slots that freed for others.
            '_all_signals_raw': list(_LAST_RAW_SIGNALS),
            # v3.2 (Jul 2026): theatre-grouped view -- countries with 2+ signals
            # collapse into one banner with axis pills + a convergence synthesis
            # line; global/regional/synthesis signals pass through ungrouped.
            # Additive: top_signals is untouched, frontends opt in.
            'grouped_signals': dict(zip(('groups', 'ungrouped'),
                                        _group_signals_by_theatre(top_signals))),
            'pressure_axes':   pressure_axes,    # v2.2 — multi-axis stack payload
            'regional_cards':  regional_cards,
            'regions_live':    len(blufs),
            'regions_total':   len(REGIONAL_BLUF_ENDPOINTS),
            'data_completeness': data_completeness,   # v3.1 honesty rollup
        }

        # Canonical-term normalization (Jul 2026): fix acronym casing (ARAMCO/DRC/ISKP)
        _normalize_payload_terms(result)

        _redis_set(GPI_CACHE_KEY, result)

        # Also cache the lightweight level-only payload.
        #
        # BUG FIXED Sep 2026 -- TWO WRITERS, ONE KEY, DIFFERENT SHAPES.
        # This block used to write ONLY global_level/label/color/generated_at.
        # build_gpi_level() separately builds a RICHER payload (headline, motion,
        # banner) but returns it without writing it back. So:
        #     force=true  -> full build -> rich payload returned  (looked fine)
        #     page load   -> reads THIS stripped cache           -> banner missing
        # The landing page therefore never saw `banner`, and with a 12h TTL it
        # stayed that way for half a day at a time. The same fault silently
        # swallowed `headline` and `motion` from 27 Jul onward -- six weeks of a
        # feature that was built, deployed, and never once rendered.
        #
        # Both writers must now emit the SAME SHAPE. Built here from `result`
        # rather than duplicating the logic, so the two cannot drift again.
        level_payload = {
            'global_level':  global_level,
            'global_label':  global_label,
            'global_color':  global_color,
            'level_gate':    {k: _LAST_LEVEL_GATE.get(k) for k in
                              ('applied', 'summary', 'reason', 'available')},
            'l6':            {'active': _LAST_L6.get('active', False),
                              'events': _LAST_L6.get('events', [])},
            'generated_at':  result['generated_at'],
            'headline':      _headline_signal(result),
            'motion':        _motion_line(result),
            'banner':        _banner(result),
        }
        _redis_set(LEVEL_CACHE_KEY, level_payload, ttl=LEVEL_CACHE_TTL)

        # Build a compact multi-axis log line: "K5 E4 D3 H2"
        axis_str = ' '.join(
            f"{ax[0].upper()}{pressure_axes['axes'][ax]['level']}"
            for ax in PRESSURE_AXES
        )
        print(f'[GPI v{GPI_VERSION}] Built: L{global_level} {global_label} '
              f'| axes=[{axis_str}] | narratives={len(narratives)} '
              f'| signals={len(top_signals)} | regions={len(blufs)}/{len(REGIONAL_BLUF_ENDPOINTS)}')
        return result

    except Exception as e:
        print(f'[GPI v2.0] BUILD EXCEPTION: {e}')
        print(traceback.format_exc())
        return {
            'success':       False,
            'error':         f'{type(e).__name__}: {str(e)[:300]}',
            'global_level':  0,
            'global_label':  'ERROR',
            'global_color':  '#6b7280',
            'bluf':          'GPI synthesis failed -- see backend logs.',
            'narratives':    [],
            'top_signals':   [],
            'regional_cards': [],
        }


def build_gpi_level(force=False):
    """Lightweight level-only endpoint for index.html button."""
    if not force:
        cached = _redis_get(LEVEL_CACHE_KEY)
        if cached and cached.get('generated_at'):
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(cached['generated_at'])).total_seconds()
                # A cache entry written by a PRE-FIX build carries no banner.
                # Serving it would silently blank the landing page's lead line,
                # which is exactly the failure this fix exists to end -- so treat
                # a bannerless entry as a miss and rebuild rather than trusting
                # the timestamp alone.
                if age < LEVEL_CACHE_TTL and cached.get('banner'):
                    cached['from_cache'] = True
                    return cached
                if age < LEVEL_CACHE_TTL:
                    print('[GPI Level] cached entry predates the banner field '
                          '-- rebuilding rather than serving a stripped payload')
            except Exception:
                pass

    # Fall through to full build (which writes the level cache as a side-effect)
    full = build_gpi(force=force)
    return {
        'global_level':  full.get('global_level', 0),
        'global_label':  full.get('global_label', ''),
        'global_color':  full.get('global_color', '#6b7280'),
        'level_gate':    {k: (full.get('level_gate') or {}).get(k) for k in
                          ('applied', 'summary', 'reason', 'available')},
        # Added Jul 27 2026. The landing page displayed ONLY the level, which
        # has been pinned at L5 by sustained global conflict -- a gauge at
        # maximum is a broken gauge. These two fields carry what actually
        # moves: which theatre leads, and what changed.
        'headline':      _headline_signal(full),
        'motion':        _motion_line(full),
        # Sep 2026: the banner the landing page actually renders. L6 breach
        # displaces the level; otherwise level + leading convergence tag.
        'banner':        _banner(full),
        'generated_at':  full.get('generated_at', datetime.now(timezone.utc).isoformat()),
        'success':       full.get('success', False),
    }


# ============================================================
# ROUTE REGISTRATION
# ============================================================
def register_gpi_routes(app):
    """Register GPI endpoints on the given Flask app."""
    from flask import jsonify, request as flask_request

    @app.route('/api/gpi', methods=['GET'])
    def get_gpi():
        force = flask_request.args.get('force', 'false').lower() == 'true'
        result = build_gpi(force=force)
        return jsonify(result)

    @app.route('/api/gpi/level', methods=['GET'])
    def get_gpi_level():
        force = flask_request.args.get('force', 'false').lower() == 'true'
        result = build_gpi_level(force=force)
        return jsonify(result)

    @app.route('/api/gpi/debug', methods=['GET'])
    def get_gpi_debug():
        cached_full  = _redis_get(GPI_CACHE_KEY)
        cached_level = _redis_get(LEVEL_CACHE_KEY)
        return jsonify({
            'full_cache_present':   cached_full is not None,
            'level_cache_present':  cached_level is not None,
            'full_cache':           cached_full,
            'level_cache':          cached_level,
            'configured_endpoints': REGIONAL_BLUF_ENDPOINTS,
        })

    print('[GPI v2.0] Routes registered: /api/gpi, /api/gpi/level, /api/gpi/debug')


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    print('Global Pressure Index Engine v2.0 -- standalone test')
    print('(Requires Redis env vars + reachable regional BLUF endpoints)')
    print()
    result = build_gpi(force=True)
    print(f"Global Level: L{result.get('global_level')} {result.get('global_label')}")
    print()
    print('BLUF:')
    print(result.get('bluf', ''))
    print()
    print('NARRATIVES:')
    for n in result.get('narratives', []):
        print(f"  P{n['priority']:>2} {n['icon']} {n['headline']}")
    print()
    print(f"Regions live: {result.get('regions_live')}/{result.get('regions_total')}")
