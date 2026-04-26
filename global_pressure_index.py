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
}

# Display config
REGION_DISPLAY = {
    'me':     {'flag': '\U0001f54c', 'name': 'Middle East',       'hub': 'rhetoric-index.html'},   # 🕌
    'asia':   {'flag': '\U0001f30f', 'name': 'Asia & Pacific',    'hub': 'rhetoric-asia.html'},    # 🌏
    'europe': {'flag': '\U0001f30d', 'name': 'Europe',            'hub': 'rhetoric-europe.html'},  # 🌍
    'wha':    {'flag': '\U0001f30e', 'name': 'Western Hemisphere','hub': 'rhetoric-wha.html'},     # 🌎
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
TOP_GLOBAL_SIGNALS_COUNT = 7
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
    """Get top_signals[] from a BLUF dict, fallback to signals[]."""
    if not bluf:
        return []
    return bluf.get('top_signals') or bluf.get('signals') or []


def _level_of(bluf):
    """Get max/peak level from a BLUF."""
    if not bluf:
        return 0
    return int(bluf.get('max_level', bluf.get('peak_level', 0)) or 0)


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
    return max(int(s.get('level', 0) or 0) for s in sigs)


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


def _narrative_houthi_fragility(blufs):
    """Yemen baseline + Iran-US off-ramp active = fragile quiescence narrative."""
    me = blufs.get('me')
    if not me:
        return None
    has_diplomatic = _has_signal_category(me, 'diplomatic_active', 'mediation_active', 'off_ramp_active')
    yemen_signals = [s for s in _signals_of(me)
                     if 'yemen' in (s.get('theatre', '') + s.get('short_text', '')).lower()]
    yemen_low = not yemen_signals or all(int(s.get('level', 0) or 0) < 3 for s in yemen_signals)
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
    _narrative_dprk_russia_axis,
    _narrative_wha_cascade,
    _narrative_houthi_fragility,
    # Fallback always last
    _narrative_global_baseline,
]


def _detect_narratives(blufs):
    """Run all detectors and return narratives sorted by priority descending."""
    narratives = []
    for detector in NARRATIVE_DETECTORS:
        try:
            narrative = detector(blufs)
            if narrative:
                narratives.append(narrative)
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
    """
    if not blufs:
        return 0
    regional_levels = [_level_of(b) for b in blufs.values()]
    max_regional = max(regional_levels) if regional_levels else 0

    # Cross-theater convergence boost
    high_priority_narratives = [n for n in narratives if n.get('priority', 0) >= 11
                                 and n.get('category') not in ('global_baseline', 'global_warning')]
    convergence_boost = 1 if high_priority_narratives else 0

    return min(5, max_regional + convergence_boost)


# ============================================================
# GLOBAL TOP SIGNALS
# ============================================================
def _build_global_top_signals(blufs, narratives):
    """
    Top N signals across all regions + narrative-derived signals.
    """
    signals = []

    # 1. Promote top narratives to signals
    for n in narratives[:3]:
        if n.get('category') in ('global_baseline', 'global_warning'):
            continue
        signals.append({
            'priority':   n['priority'],
            'category':   n['category'],
            'theatre':    'global',
            'level':      5 if n['priority'] >= 13 else 4,
            'icon':       n['icon'],
            'color':      n['color'],
            'short_text': n['headline'][:80],
            'long_text':  n['detail'],
            'regions':    n.get('regions', []),
        })

    # 2. Pull top regional signals (alphabetical, then by priority)
    for region in CARD_ORDER:
        bluf = blufs.get(region)
        if not bluf:
            continue
        for sig in _signals_of(bluf)[:2]:  # top 2 per region
            signals.append({
                'priority':   int(sig.get('priority', 5) or 5) - 2,  # demote vs. narratives
                'category':   sig.get('category', 'regional'),
                'theatre':    region,
                'level':      sig.get('level', 0),
                'icon':       sig.get('icon', '\u2022'),
                'color':      sig.get('color', '#6b7280'),
                'short_text': sig.get('short_text', sig.get('text', ''))[:80],
                'long_text':  sig.get('long_text', sig.get('short_text', '')),
            })

    # Dedupe by category+theatre, sort by priority, return top N
    seen = set()
    deduped = []
    for s in sorted(signals, key=lambda x: x.get('priority', 0), reverse=True):
        key = f"{s.get('theatre', '')}:{s.get('category', '')}"
        if key not in seen:
            seen.add(key)
            deduped.append(s)
    return deduped[:TOP_GLOBAL_SIGNALS_COUNT]


# ============================================================
# BLUF SYNTHESIS
# ============================================================
def _synthesize_global_bluf(blufs, narratives, global_level):
    """
    Generate the 3-5 sentence analyst-prose BLUF.
    Top narratives drive the lead; regional summaries follow.
    """
    date_str = datetime.now(timezone.utc).strftime('%b %d, %Y %H:%MZ')
    parts = [f'Global Pressure Index ({date_str}):']

    # Lead: highest-priority narrative
    leading = next((n for n in narratives if n.get('category')
                    not in ('global_baseline', 'global_warning')), None)

    if leading:
        parts.append(leading['headline'] + '.')
        parts.append(leading['detail'])
    else:
        # Fallback to baseline narrative
        baseline = next((n for n in narratives), None)
        if baseline:
            parts.append(baseline['headline'] + '.')
            parts.append(baseline['detail'])

    # Secondary narratives (briefly)
    secondary = [n for n in narratives[1:3] if n.get('category')
                 not in ('global_baseline', 'global_warning')]
    if secondary:
        sec_lines = [f"{n['icon']} {n['headline']}" for n in secondary]
        parts.append('Concurrent signals: ' + '; '.join(sec_lines) + '.')

    # Regional summary line
    region_levels = []
    for r in CARD_ORDER:
        bluf = blufs.get(r)
        if bluf:
            region_levels.append(f"{REGION_DISPLAY[r]['name']} L{_level_of(bluf)}")
    if region_levels:
        parts.append('Regional posture: ' + ', '.join(region_levels) + '.')

    parts.append(f"Global level: L{global_level} -- {GLOBAL_LEVEL_LABELS.get(global_level, '')}.")

    return ' '.join(parts)


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
        'top_signals':   _signals_of(bluf)[:3],
        'trackers_live': bluf.get('trackers_live', bluf.get('theatres_live', 0)),
        'avg_score':     bluf.get('avg_score', 0),
    }


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

        # Regional cards in alphabetical order
        regional_cards = []
        for region in CARD_ORDER:
            regional_cards.append(_build_regional_card(region, blufs.get(region)))

        result = {
            'success':         True,
            'from_cache':      False,
            'generated_at':    datetime.now(timezone.utc).isoformat(),
            'version':         '2.0.0',
            'global_level':    global_level,
            'global_label':    GLOBAL_LEVEL_LABELS.get(global_level, ''),
            'global_color':    GLOBAL_LEVEL_COLORS.get(global_level, '#6b7280'),
            'bluf':            bluf_prose,
            'narratives':      narratives,
            'top_signals':     top_signals,
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

        print(f'[GPI v2.0] Built: L{global_level} {GLOBAL_LEVEL_LABELS.get(global_level)} '
              f'| narratives={len(narratives)} | signals={len(top_signals)} | regions={len(blufs)}/4')
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
