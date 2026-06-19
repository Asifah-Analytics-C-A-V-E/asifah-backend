"""
global_pressure_index.py
Asifah Analytics — Global Pressure Index Engine
v3.6.0 — May 23 2026 (AFRICA-READY + HUMANITARIAN SCAFFOLDING)
(prior: v3.5.0 May 21 2026 ENRICHED OUTPUT EDITION; v3.4.x earlier; v2.0.0 April 2026 baseline)

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
    # v3.6 (May 23 2026) -- Africa theatre placeholder.
    # Activates when africa_regional_bluf.py + rhetoric_tracker_sudan.py ship.
    # Until then, fetch returns None and GPI gracefully skips. The convergence
    # registry already has 3 africa-trigger_region entries (cobalt_drc_active,
    # diamonds_sanctions_regime, phosphate_food_security) ready to consume this.
    # 'africa': os.environ.get('AFRICA_BACKEND_URL', 'https://asifah-africa-backend.onrender.com') + '/api/rhetoric/africa/bluf',
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
REGIONAL_FETCH_TIMEOUT   = 8    # seconds


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
}

def _axes_for_narrative(n):
    """Return the ordered axis list for a narrative dict. Priority:
    explicit category map > explicit pressure_type > kinetic default."""
    cat = n.get('category', '')
    if cat in NARRATIVE_AXIS_SETS:
        return list(NARRATIVE_AXIS_SETS[cat])
    pt = n.get('pressure_type')
    if pt and pt in PRESSURE_AXES:
        return [pt]
    return ['kinetic']
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
    """US-Iran de-escalation off-ramp at GPI altitude (v1.7.0 - Jun 18 2026).

    Reads the maturity tag + contradiction flags the Iran rhetoric tracker emits
    (rhetoric:iran:latest). Convergence/estimative framing: reports that an
    off-ramp is present and how mature/reversible it is -- never predicts the war
    ends. Priority kept BELOW the global-level boost threshold (11) so a
    de-escalation narrative never raises the global level.
    """
    iran = _redis_get('rhetoric:iran:latest') or {}
    if not isinstance(iran, dict):
        return None
    maturity = iran.get('de_escalation_maturity', 'none')
    if maturity not in ('framework', 'signed', 'implementing'):
        return None

    milestones = iran.get('implementation_milestones', []) or []
    contra     = iran.get('contradiction_active', False)
    flags      = iran.get('contradiction_flags', []) or []
    n          = len(milestones)
    plural     = 's' if n != 1 else ''

    if maturity == 'implementing':
        headline = (f'US-Iran de-escalation -- framework moving toward implementation '
                    f'({n} delivered milestone{plural})')
        detail = (
            f'The Iran rhetoric tracker reports an off-ramp at implementing maturity: '
            f'{n} delivered milestone{plural} observed ({", ".join(milestones)}). '
            f'This is consistent with a durable de-escalation, though reversibility '
            f'language persists and the track remains conditional. ')
    elif maturity == 'signed':
        headline = 'US-Iran de-escalation -- signed framework, implementation pending'
        detail = (
            'The Iran rhetoric tracker reports a signed US-Iran framework. This is '
            'consistent with de-escalation, but implementation is pending and explicitly '
            'reversible on the 60-day track; no delivered milestones observed yet. ')
    else:  # framework
        headline = 'US-Iran de-escalation -- active negotiation track (unsigned)'
        detail = (
            'The Iran rhetoric tracker reports an active US-Iran negotiation track, '
            'consistent with an emerging off-ramp that is not yet signed. ')

    if contra:
        bits = []
        if 'israel_lebanon' in flags:
            bits.append('continued Israeli operations in Lebanon')
        if 'syria_hezbollah' in flags:
            bits.append('calls for Syria to act against Hezbollah')
        contra_txt = ' and '.join(bits) if bits else 'an unresolved Lebanon-front contradiction'
        detail += (
            f'A live contradiction -- {contra_txt} -- caps how deep the de-escalation '
            f'reads; the all-fronts framing is not yet borne out on the Lebanon front. ')

    detail += ('Framing is convergence, not prediction: an off-ramp is present and '
               'measurably maturing or stalling -- the reader completes the inference.')

    return {
        'priority': 9,    # below the +11 global-level boost; de-escalation never escalates
        'category': 'iran_deescalation',
        'regions':  ['me'],
        'icon':     '\U0001f91d',  # handshake
        'color':    '#10b981',      # diplomatic green
        'headline': headline,
        'detail':   detail,
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
            f'outcomes (June 2026), Lobito Corridor throughput, Indonesian '
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

        matches.append({
            'priority':         convergence_priority(entry, is_fresh),
            'category':         entry['id'],
            'regions':          conv_regions,
            'icon':             entry['icon'],
            'color':            entry['color'],
            'headline':         format_headline(entry, alert_level, is_fresh),
            'detail':           entry['detail'],
            'detected_via':     found_in_region,   # diagnostic: which region's signal triggered detection
            'fresh':            is_fresh,           # diagnostic: topline vs watch tier
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
    n = (name or '').strip().lower()
    return _COUNTRY_NAME_ALIASES.get(n, n)


def _names_match(a, b):
    """Exact country-name matching after normalization + alias mapping.
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
        return {
            'priority': 13,  # high -- a flagship cross-domain convergence
            'category': 'market_fragility_semis_compound',
            'regions':  ['asia', 'global_market'],
            'icon':     '\U0001f9e8',  # 🧨
            'color':    '#dc2626',
            'pressure_type': 'economic',
            'headline': ('Market fragility %s AND Taiwan-Strait kinetic signaling -- '
                         'the AI/semiconductor convergence'
                         % band_label),
            'detail':   ('The Market Watch fragility detector reads %s (composite %s), with the '
                         'AI/data-center/semiconductor thematic running hot -- the concentration '
                         'that defines the current market is precisely the sector most exposed to a '
                         'Taiwan-Strait disruption. Simultaneously, the Asia-Pacific theater is '
                         'showing kinetic / cross-strait signaling. A Chinese move threatening '
                         'Taiwan semiconductor output would strike the exact sector driving market '
                         'fragility: a compound pattern in which an endogenously fragile market '
                         '(the dry forest) co-occurs with the one geopolitical fuse most precisely '
                         'aimed at it. This is a convergence read of present conditions across two '
                         'independent layers, not a prediction that either a drawdown or a Taiwan '
                         'contingency will occur. %s'
                         % (band, composite, ('Pattern note: ' + lag) if lag else '')),
        }

    # --- Economic-axis fragility surface (no kinetic co-occurrence yet) ---
    detail = ('The Market Watch fragility detector reads %s (composite %s) on endogenous '
              'market-fragility convergence, driven by %s. This measures how dry the forest '
              'is -- valuation, concentration, and momentum conditions consistent with '
              'historical pre-drawdown patterns -- not whether or when a drawdown occurs. '
              'No kinetic co-occurrence with the AI/semiconductor exposure this cycle; the '
              'compound read to watch is fragility plus a Taiwan-Strait disruption. %s'
              % (band, composite, feat_phrase, ('Pattern note: ' + lag) if lag else ''))
    pr = {'critical': 9, 'high': 11, 'elevated': 13}.get(band, 13)
    return {
        'priority': pr,
        'category': 'market_fragility',
        'regions':  ['global_market'],
        'icon':     '\U0001f9a2',  # 🦢
        'color':    '#f59e0b' if band in ('elevated',) else '#ef4444',
        'pressure_type': 'economic',
        'headline': ('Market-fragility convergence reads %s -- %s'
                     % (band_label, feat_phrase)),
        'detail':   detail,
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

    # (1) Global commodity conditions -- broad and cross-theater by nature
    for g in (cax.get('global_conditions') or [])[:2]:
        n = g.get('country_count', 0)
        nm = (g.get('commodity_name') or g.get('commodity') or 'commodity')
        sample = ', '.join((g.get('countries') or [])[:6])
        cards.append({
            'priority': 9,
            'category': 'global_commodity_' + str(g.get('commodity', 'x')),
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
                         f'"{(g.get("headline") or "")[:140]}".'),
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
    _narrative_conflict_repricing,                       # off-ramp market-belief read (Slice 3, Jun 18 2026)
    _narrative_conflict_repricing_europe,                # Europe off-ramp market-belief read (Slice 4c, Jun 19 2026)
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
    for n in narratives[:5]:   # widened from 3 to 5 since tier sort handles ranking
        if n.get('category') in ('global_baseline', 'global_warning'):
            continue
        promoted = {
            'priority':   n['priority'],
            'category':   n['category'],
            'theatre':    'global',
            'level':      5 if n['priority'] >= 13 else 4,
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
        for sig in region_pool[3:]:
            if _infer_pressure_type(sig) == PRESSURE_DIPLOMATIC:
                pulled.append(sig)
        for sig in pulled:
            signals.append({
                'priority':      int(sig.get('priority', 5) or 5) - 2,  # demote vs. narratives
                'category':      sig.get('category', 'regional'),
                'theatre':       region,
                'level':         sig.get('level', 0),
                'icon':          sig.get('icon', '\u2022'),
                'color':         sig.get('color', '#6b7280'),
                'short_text':    sig.get('short_text', sig.get('text', ''))[:120],   # v2.3.0: 80→120 (consistency)
                'long_text':     sig.get('long_text', sig.get('short_text', '')),
                'pressure_type': sig.get('pressure_type') or _infer_pressure_type(sig),  # lock axis
                # No 'regions' key — single-region signals naturally Tier 2 or 4
            })

    # Compute tier-adjusted sort key for each signal
    for s in signals:
        s['_tier_boost'] = _tier_boost(s)
        s['_sort_key']   = s['_tier_boost'] + int(s.get('priority', 0) or 0)

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
    def _cap_diplomatic(lst):
        kept, dip_seen = [], 0
        for _s in lst:
            if (_s.get('pressure_type') or _infer_pressure_type(_s)) == PRESSURE_DIPLOMATIC:
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
        axis = s.get('pressure_type') or _infer_pressure_type(s)
        if axis in axis_counts:
            axis_counts[axis] += 1

    # Build the rebalanced tail: prefer candidates from axes currently below MIN_SIGNALS_PER_AXIS
    tail_block = []
    candidates_by_axis = {axis: [] for axis in PRESSURE_AXES}
    for s in candidate_pool:
        axis = s.get('pressure_type') or _infer_pressure_type(s)
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
                'pressure_type': sig.get('pressure_type') or _infer_pressure_type(sig),
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
            'data_completeness': data_completeness,   # v3.1 honesty rollup
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
