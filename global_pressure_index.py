"""
global_pressure_index.py
Asifah Analytics — Global Pressure Index Engine
v2.0.0 — April 2026

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
}

# Display config
REGION_DISPLAY = {
    'me':     {'flag': '\U0001f54c', 'name': 'Middle East',       'hub': 'rhetoric-index.html'},   # 🕌
    'asia':   {'flag': '\U0001f30f', 'name': 'Asia & Pacific',    'hub': 'rhetoric-asia.html'},    # 🌏
    'europe': {'flag': '\U0001f30d', 'name': 'Europe',            'hub': 'rhetoric-europe.html'},  # 🌍
    'wha':    {'flag': '\U0001f30e', 'name': 'Western Hemisphere','hub': 'rhetoric-wha.html'},     # 🌎
    # v2.3 — Humanitarian Convergence Detector pseudo-region
    'global_humanitarian': {'flag': '\U0001f198', 'name': 'Global Humanitarian', 'hub': 'gpi.html'},  # 🆘
    'global_cascade': {'flag': '\u2697\ufe0f', 'name': 'Global Cascade', 'hub': 'gpi.html'},  # alembic emoji
}

# Alphabetical card order (matches Rachel's "presumably alphabetical" spec)
CARD_ORDER = ['asia', 'europe', 'me', 'wha']

# Global level labels + colors (matches canonical regional schema)
GLOBAL_LEVEL_LABELS = {
    0: 'BASELINE',
    1: 'MONITORING -- RHETORIC',
    2: 'WARNING',
    3: 'ELEVATED',
    4: 'INCIDENT',
    5: 'ACTIVE CONFLICT',
}

GLOBAL_LEVEL_COLORS = {
    0: '#6b7280',   # slate
    1: '#3b82f6',   # blue
    2: '#f59e0b',   # amber
    3: '#f97316',   # orange
    4: '#ef4444',   # red
    5: '#dc2626',   # dark red
}

# Cache
GPI_CACHE_KEY   = 'gpi:global:latest'
GPI_CACHE_TTL   = 12 * 3600   # 12h
LEVEL_CACHE_KEY = 'gpi:level:latest'
LEVEL_CACHE_TTL = 12 * 3600

# Synthesis tuning
TOP_GLOBAL_SIGNALS_COUNT = 15   # v3.5.0 May 21 2026 — bumped from 7; future-proofs for Africa + Arctic
REGIONAL_FETCH_TIMEOUT   = 8  # seconds


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
        # Then try label map
        return _LEVEL_LABEL_MAP.get(v, default)
    return default


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
PRESSURE_DIPLOMATIC   = 'diplomatic'
PRESSURE_HUMANITARIAN = 'humanitarian'

PRESSURE_AXES = (
    PRESSURE_KINETIC,
    PRESSURE_ECONOMIC,
    PRESSURE_DIPLOMATIC,
    PRESSURE_HUMANITARIAN,
)

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
        if 'pressure_type' not in s2 or s2['pressure_type'] not in PRESSURE_AXES:
            s2['pressure_type'] = _infer_pressure_type(s)
        tagged.append(s2)
    return tagged


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
        axes[axis] = {
            'axis':          axis,
            'label':         meta['label'],
            'icon':          meta['icon'],
            'color':         meta['color'],
            'description':   meta['description'],
            'level':         axis_level,
            'level_label':   GLOBAL_LEVEL_LABELS.get(axis_level, ''),
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
                         'shifts, and US-Japan-Taiwan coalition signaling cadence over next 48-72 hours.'),
        }
    return None


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
    if triggers >= 2:
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
# REGISTRY-DRIVEN CONVERGENCE DETECTOR (Layer 1)
# ════════════════════════════════════════════════════════════════════
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
                candidate = next(
                    (s for s in signals if s.get('category') == entry['trigger_signal_category']
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
        alert_level = state.get('alert_level', 'elevated')

        matches.append({
            'priority':         entry['priority'],
            'category':         entry['id'],
            'regions':          list(entry.get('regions', [])),
            'icon':             entry['icon'],
            'color':            entry['color'],
            'headline':         format_headline(entry, alert_level),
            'detail':           entry['detail'],
            'detected_via':     found_in_region,   # diagnostic: which region's signal triggered detection
        })
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
    nuclear_active = []
    for region, bluf in blufs.items():
        if not bluf:
            continue
        if bluf.get('nuclear_elevated') or _max_signal_level(bluf, 'nuclear_signaling') >= 4:
            nuclear_active.append(region)
    if nuclear_active:
        regions_str = ', '.join(REGION_DISPLAY[r]['name'] for r in nuclear_active)
        return {
            'priority': 15,
            'category': 'nuclear_signaling_global',
            'regions':  nuclear_active,
            'icon':     '\u2622\ufe0f',  # ☢️
            'color':    '#dc2626',
            'headline': f'Nuclear signaling active -- {regions_str}',
            'detail':   ('At least one regional theater shows nuclear-doctrine-language at coercion '
                         'threshold. This is the highest-stakes signal class on the platform; '
                         'watch for further escalation rhetoric or de-escalation off-ramp signaling.'),
        }
    return None


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


# Registry of detectors. Order doesn't matter -- sorting is by priority.
NARRATIVE_DETECTORS = [
    _narrative_nuclear_signaling_global,
    _narrative_china_taiwan_takeover,
    _narrative_dual_chokepoint,
    _narrative_russia_iran_axis,
    _narrative_arctic_convergence,
    _detect_convergences_from_registry,    # NEW: registry-driven (returns LIST of narratives)
    _narrative_dprk_russia_axis,
    _narrative_wha_cascade,
    _narrative_houthi_fragility,
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
    high_priority_narratives = [n for n in narratives if n.get('priority', 0) >= 11
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

        # Tier 3: Major regional narratives (came from narrative detector, single region)
        # We tag narrative-derived signals with theatre='global' and they have a 'regions' list.
        # Single-region narratives (1 region) sit here.
        if theatre == 'global' and isinstance(regions, list) and len(regions) == 1:
            return 10

        # Tier 4: Everything else
        return 0

    signals = []

    # 1. Promote top narratives to signals
    for n in narratives[:5]:   # widened from 3 to 5 since tier sort handles ranking
        if n.get('category') in ('global_baseline', 'global_warning'):
            continue
        signals.append({
            'priority':   n['priority'],
            'category':   n['category'],
            'theatre':    'global',
            'level':      5 if n['priority'] >= 13 else 4,
            'icon':       n['icon'],
            'color':      n['color'],
            'short_text': n['headline'][:120],     # v2.3.0: 80→120 — fits "Wheat-Lebanon convergence ... ELEVATED" (85 chars)
            'long_text':  n['detail'],
            'regions':    n.get('regions', []),
        })

    # 2. Pull top regional signals (alphabetical, then by priority)
    for region in CARD_ORDER:
        bluf = blufs.get(region)
        if not bluf:
            continue
        for sig in _signals_of(bluf)[:3]:  # v3.5.0 May 21 2026 — bumped from 2 to 3 per region
            signals.append({
                'priority':   int(sig.get('priority', 5) or 5) - 2,  # demote vs. narratives
                'category':   sig.get('category', 'regional'),
                'theatre':    region,
                'level':      sig.get('level', 0),
                'icon':       sig.get('icon', '\u2022'),
                'color':      sig.get('color', '#6b7280'),
                'short_text': sig.get('short_text', sig.get('text', ''))[:120],   # v2.3.0: 80→120 (consistency)
                'long_text':  sig.get('long_text', sig.get('short_text', '')),
                # No 'regions' key — single-region signals naturally Tier 2 or 4
            })

    # Compute tier-adjusted sort key for each signal
    for s in signals:
        s['_tier_boost'] = _tier_boost(s)
        s['_sort_key']   = s['_tier_boost'] + int(s.get('priority', 0) or 0)

    # Dedupe by category+theatre, sort by tier-adjusted score, return top N
    seen = set()
    deduped = []
    for s in sorted(signals, key=lambda x: x.get('_sort_key', 0), reverse=True):
        key = f"{s.get('theatre', '')}:{s.get('category', '')}"
        if key not in seen:
            seen.add(key)
            # Strip internal sort fields before returning
            s.pop('_tier_boost', None)
            s.pop('_sort_key', None)
            deduped.append(s)
    return deduped[:TOP_GLOBAL_SIGNALS_COUNT]


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
                       if n.get('category') not in ('global_baseline', 'global_warning')]
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

    # Step 1: Pool ALL signals from ALL regional BLUFs (incl. pseudo-regions)
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
                'level':         level,
                'priority':      int(sig.get('priority', 0) or 0),
                'pressure_type': sig.get('pressure_type') or _infer_pressure_type(sig),
                'icon':          sig.get('icon') or '',
                'short_text':    stext,
            })

    # Step 2: Sort globally by level DESC, priority DESC (highest-impact first)
    pooled_signals.sort(
        key=lambda s: (s['level'], s['priority']),
        reverse=True,
    )

    # Step 3: Take top 5 with axis-diversity preference — ensure we surface
    # at least one signal per active pressure axis when available, so the
    # BLUF reflects the multi-axis pressure landscape rather than just
    # the loudest single axis.
    live_signal_lines = []
    axes_represented = set()
    deferred = []
    for sig in pooled_signals:
        axis = sig.get('pressure_type', 'kinetic')
        # First pass: prefer one signal per axis (up to 4 unique axes)
        if axis not in axes_represented and len(live_signal_lines) < 4:
            axes_represented.add(axis)
            live_signal_lines.append(f"{sig['icon']} {sig['short_text']}".strip())
        else:
            deferred.append(sig)
        if len(live_signal_lines) >= 5:
            break
    # Second pass: fill remaining slots from deferred pool by global rank
    for sig in deferred:
        if len(live_signal_lines) >= 5:
            break
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
        for ax_name in ('kinetic', 'economic', 'diplomatic', 'humanitarian'):
            ax = axes_inner.get(ax_name, {}) or {}
            ax_level = ax.get('level', 0) or 0
            if ax_level > 0:
                axis_summary_parts.append(f"{ax_name.capitalize()} L{ax_level}")
        if axis_summary_parts:
            parts.append('Pressure axes: ' + ', '.join(axis_summary_parts) + '.')
    except Exception as _e:
        pass  # axes summary is enrichment; never blocks the BLUF

    parts.append(f"Global level: L{global_level} -- {GLOBAL_LEVEL_LABELS.get(global_level, '')}.")

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
    parts.append(
        f"Axis at L{axis_level} ({GLOBAL_LEVEL_LABELS.get(axis_level, '')}) -- "
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
    Generate all 4 per-axis BLUFs as a dict keyed by axis name.
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
                'narratives':    [],
                'top_signals':   [],
                'regional_cards': [],
            }

        narratives    = _detect_narratives(blufs)
        global_level  = _compute_global_level(blufs, narratives)
        bluf_prose    = _synthesize_global_bluf(blufs, narratives, global_level)
        top_signals   = _build_global_top_signals(blufs, narratives)
        # v2.2 — multi-axis pressure aggregation (kinetic / economic / diplomatic / humanitarian)
        # Headline level remains kinetic-driven; pressure_axes is additive payload for frontend.
        pressure_axes = _build_pressure_axes_payload(blufs, narratives)

        # Regional cards in alphabetical order
        regional_cards = []
        for region in CARD_ORDER:
            regional_cards.append(_build_regional_card(region, blufs.get(region)))

        # v3.0 — Per-axis BLUF generation (one focused prose per pressure axis)
        bluf_by_axis = _synthesize_all_axis_blufs(pressure_axes, blufs, global_level)

        result = {
            'success':         True,
            'from_cache':      False,
            'generated_at':    datetime.now(timezone.utc).isoformat(),
            'version':         '3.0.0',
            'global_level':    global_level,
            'global_label':    GLOBAL_LEVEL_LABELS.get(global_level, ''),
            'global_color':    GLOBAL_LEVEL_COLORS.get(global_level, '#6b7280'),
            'bluf':            bluf_prose,
            'bluf_by_axis':    bluf_by_axis,    # v3.0 — per-axis focused prose for click-through UX
            'narratives':      narratives,
            'top_signals':     top_signals,
            'pressure_axes':   pressure_axes,    # v2.2 — multi-axis stack payload
            'regional_cards':  regional_cards,
            'regions_live':    len(blufs),
            'regions_total':   len(REGIONAL_BLUF_ENDPOINTS),
        }

        _redis_set(GPI_CACHE_KEY, result)
        # Also cache the lightweight level-only payload
        level_payload = {
            'global_level':  global_level,
            'global_label':  GLOBAL_LEVEL_LABELS.get(global_level, ''),
            'global_color':  GLOBAL_LEVEL_COLORS.get(global_level, '#6b7280'),
            'generated_at':  result['generated_at'],
        }
        _redis_set(LEVEL_CACHE_KEY, level_payload, ttl=LEVEL_CACHE_TTL)

        # Build a compact multi-axis log line: "K5 E4 D3 H2"
        axis_str = ' '.join(
            f"{ax[0].upper()}{pressure_axes['axes'][ax]['level']}"
            for ax in PRESSURE_AXES
        )
        print(f'[GPI v2.2] Built: L{global_level} {GLOBAL_LEVEL_LABELS.get(global_level)} '
              f'| axes=[{axis_str}] | narratives={len(narratives)} '
              f'| signals={len(top_signals)} | regions={len(blufs)}/4')
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
                if age < LEVEL_CACHE_TTL:
                    cached['from_cache'] = True
                    return cached
            except Exception:
                pass

    # Fall through to full build (which writes the level cache as a side-effect)
    full = build_gpi(force=force)
    return {
        'global_level':  full.get('global_level', 0),
        'global_label':  full.get('global_label', ''),
        'global_color':  full.get('global_color', '#6b7280'),
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
