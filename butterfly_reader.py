"""
================================================================================
butterfly_reader.py — Asifah Analytics
================================================================================
BUTTERFLY READER — Cross-theater signal reader with per-consumer predicates

THE LAYER MODEL
---------------
Layer 4 (Writers):    jawboning_detector + tracker scans → write Redis fingerprints
Layer 3 (Storage):    Redis (multiple key patterns coexist; see "PATTERNS" below)
Layer 2 (READER):     THIS MODULE — reads all patterns, applies predicates, returns bundle
Layer 1 (Narrators):  absorption_signatures, convergence_registry, regional BLUFs, GPI

THE BUTTERFLY EFFECT
--------------------
Modi mentions gold → writes modi_on_gold fingerprint → other trackers READ it →
they amplify their own actor scoring → their "So What Factor" reflects it →
their regional BLUF aggregates → GPI sees compounded global pressure.

This module is the READ side of that chain. Each tracker that wants to consume
cross-theater signals calls (locally on ME, or via butterfly_proxy_{theater}.py
from Asia/Europe/WHA):

    bundle = read_butterfly_signals(consumer_theater='us')

And gets back the canonical 4-field bundle:
    {
        'upstream_fingerprints':  {<theater>: {<envelope>}, ...},
        'amplifier_actor_deltas': {<actor>: +N, ...},
        'context_notes':          ["..."],
        'upstream_stressors':     ['iran_hormuz_oil', ...],
    }

PATTERNS HANDLED
----------------
Pattern A — Shared dict:  rhetoric:crosstheater:fingerprints (Iran, China sub-keys)
Pattern B — Direct key:   fingerprint:<theater>:current (US, India)
                          crosstheater:pakistan:fingerprint (Pakistan)
Pattern C — Atomic keys:  fingerprint:<theater>:<signal_name> (Belarus, Ukraine)
Pattern D — Snapshot:     rhetoric:<theater>:latest (heavyweight; subset extracted)

ADDING A NEW CONSUMER
---------------------
1. Add an entry to PREDICATE_LIBRARY at the bottom of this file
2. Define the predicate functions (one per cross-theater amplification rule)
3. Done — the reader infrastructure handles dispatch automatically

v1.0.0 — May 16 2026 · Cross-Theater Butterfly Reader
================================================================================
"""

import os
import json
import requests
from datetime import datetime, timezone

# ============================================================================
# REDIS HELPERS (mirrors jawboning_detector.py pattern)
# ============================================================================

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

CROSSTHEATER_SHARED_KEY = 'rhetoric:crosstheater:fingerprints'


def _redis_get(key, default=None):
    """GET a Redis key via Upstash REST. Returns parsed JSON or default."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return default
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if not resp.ok:
            return default
        data = resp.json()
        raw = data.get('result')
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw   # not JSON — return raw string
    except Exception:
        return default


def _redis_scan(pattern, max_keys=100):
    """SCAN Redis for keys matching pattern. Returns list of key names."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return []
    try:
        import urllib.parse
        url = (f"{UPSTASH_REDIS_URL}/scan/0/match/"
               f"{urllib.parse.quote(pattern)}/count/{max_keys}")
        resp = requests.get(
            url,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if not resp.ok:
            return []
        data = resp.json()
        result = data.get('result', [])
        if isinstance(result, list) and len(result) >= 2 and isinstance(result[1], list):
            return result[1]
        return []
    except Exception:
        return []


# ============================================================================
# PATTERN READERS — one per fingerprint storage convention
# ============================================================================

def _read_shared_dict_fingerprints():
    """
    Pattern A — Shared dict at CROSSTHEATER_SHARED_KEY.
    Returns dict of {theater: envelope, ...}. Iran and China write here.
    """
    shared = _redis_get(CROSSTHEATER_SHARED_KEY) or {}
    if not isinstance(shared, dict):
        return {}
    # Return only sub-keys that are themselves dicts (defensive)
    return {k: v for k, v in shared.items() if isinstance(v, dict)}


def _read_direct_envelope(theater):
    """
    Pattern B — Direct key fingerprint:<theater>:current.
    Used by US, India. Also handles crosstheater:pakistan:fingerprint variant.
    """
    # Try the canonical pattern first
    fp = _redis_get(f'fingerprint:{theater}:current')
    if isinstance(fp, dict):
        return fp
    # Pakistan-specific variant (legacy)
    if theater == 'pakistan':
        fp = _redis_get('crosstheater:pakistan:fingerprint')
        if isinstance(fp, dict):
            return fp
    return {}


def _read_atomic_signals(theater):
    """
    Pattern C — atomic keys fingerprint:<theater>:<signal_name>.
    Used by Belarus, Ukraine. Returns dict assembled from all matching keys.
    """
    keys = _redis_scan(f'fingerprint:{theater}:*', max_keys=50)
    if not keys:
        return {}
    # Filter out the canonical 'fingerprint:<theater>:current' since
    # that's Pattern B territory and would conflict
    keys = [k for k in keys if not k.endswith(':current')]
    if not keys:
        return {}
    assembled = {}
    for key in keys:
        # Extract signal name from 'fingerprint:belarus:wagner_active_belarus'
        parts = key.split(':', 2)
        if len(parts) < 3:
            continue
        signal_name = parts[2]
        raw = _redis_get(key)
        # Atomic values often come as {"value": "true"} or {"value": "0"}
        if isinstance(raw, dict) and 'value' in raw:
            assembled[signal_name] = raw['value']
        else:
            assembled[signal_name] = raw
    return assembled


def _read_snapshot_subset(theater):
    """
    Pattern D — full scan snapshot at rhetoric:<theater>:latest.
    Heavyweight (50-200KB). Extracts only the cross-theater-relevant subset
    so consumer trackers don't carry article lists in memory.
    """
    snapshot = _redis_get(f'rhetoric:{theater}:latest')
    if not isinstance(snapshot, dict):
        return {}
    # Extract fields commonly useful for cross-theater predicates.
    # Names vary across trackers (different generations of the codebase),
    # so try multiple aliases and let predicates pick what they need.
    subset = {
        'theatre_score':              snapshot.get('theatre_score'),
        'theatre_level':              snapshot.get('theatre_level'),
        'theatre_escalation_level':   snapshot.get('theatre_escalation_level'),
        'theatre_escalation_label':   snapshot.get('theatre_escalation_label'),
        'overall_level':              snapshot.get('overall_level'),
        'overall_label':              snapshot.get('overall_label'),
        'irgc_direct_level':          snapshot.get('irgc_direct_level'),
        'irgc_level':                 snapshot.get('irgc_level'),
        'proxy_activation_level':     snapshot.get('proxy_activation_level'),
        'nuclear_level':              snapshot.get('nuclear_level'),
        'regional_level':             snapshot.get('regional_level'),
        'pla_level':                  snapshot.get('pla_level'),
        'xi_level':                   snapshot.get('xi_level'),
        'mfa_level':                  snapshot.get('mfa_level'),
        'tao_level':                  snapshot.get('tao_level'),
        'econ_level':                 snapshot.get('econ_level'),
        'regime_signals':             snapshot.get('regime_signals'),
        'crosstheater_amplifiers':    snapshot.get('crosstheater_amplifiers'),
        'is_command_node':            snapshot.get('is_command_node'),
        'updated_at':                 (snapshot.get('scanned_at') or
                                       snapshot.get('timestamp') or
                                       snapshot.get('cached_at')),
        '_pattern':                   'D_snapshot',  # for diagnostics
    }
    # Drop None entries for cleanliness
    return {k: v for k, v in subset.items() if v is not None}


def _read_jawboning_fingerprints(country_id):
    """
    Special-case reader for jawboning fingerprints written by jawboning_detector.
    Returns {signature_id: fingerprint_envelope} for all command-direction
    signatures from this country (i.e., the country JAWBONING others).

    Used by predicates that care about who's actively pressuring whom.
    """
    keys = _redis_scan(f'jawboning:command:{country_id}:*', max_keys=50)
    out = {}
    for key in keys:
        env = _redis_get(key)
        if isinstance(env, dict):
            # Extract signature_id from 'jawboning:command:china:on_rare_earths'
            sig_id = env.get('signature_id') or key.split(':')[-1]
            out[sig_id] = env
    return out


# ============================================================================
# UNIVERSAL UPSTREAM COLLECTOR
# ============================================================================

# Map of which theaters are reachable via which pattern.
# Adjust this as new trackers come online.
THEATER_PATTERNS = {
    # Pattern A — shared dict (older ME family)
    'iran':    'A',
    'china':   'A',   # also has Pattern D snapshot for richer reads

    # Pattern B — direct key
    'us':       'B',
    'india':    'B',
    'pakistan': 'B',

    # Pattern C — atomic signals
    'belarus':  'C',
    'ukraine':  'C',

    # Pattern D — snapshot (fallback for anyone without B/C)
    'israel':   'D',
    'lebanon':  'D',
    'yemen':    'D',
    'iraq':     'D',
    'syria':    'D',
    'oman':     'D',
    'taiwan':   'D',
    'japan':    'D',
    'russia':   'D',
    'greenland':'D',
    'cuba':     'D',
    'peru':     'D',
    'chile':    'D',
}


def _collect_all_upstream(consumer_theater):
    """
    For the given consumer, fetch every theater's fingerprint using
    the appropriate pattern. Skips fetching the consumer's own theater.
    Returns {theater: envelope_dict} for whatever's available right now.
    """
    upstream = {}

    # First, pull the shared dict once (efficient batch read for Pattern A)
    shared = _read_shared_dict_fingerprints()

    for theater, pattern in THEATER_PATTERNS.items():
        if theater == consumer_theater:
            continue  # Don't read your own fingerprint

        if pattern == 'A':
            env = shared.get(theater, {})
            # Augment Pattern A with Pattern D snapshot when available
            # (gives predicates access to richer fields like pla_level)
            snap = _read_snapshot_subset(theater)
            if snap:
                # Merge — Pattern A wins on conflicts (it's the canonical butterfly write)
                merged = {**snap, **env}
                upstream[theater] = merged
            elif env:
                upstream[theater] = env

        elif pattern == 'B':
            env = _read_direct_envelope(theater)
            if env:
                upstream[theater] = env

        elif pattern == 'C':
            env = _read_atomic_signals(theater)
            if env:
                upstream[theater] = env

        elif pattern == 'D':
            env = _read_snapshot_subset(theater)
            if env:
                upstream[theater] = env

    return upstream


# ============================================================================
# PREDICATE FUNCTIONS — INDIA CONSUMER
# Ported byte-for-byte from rhetoric_tracker_india.py's _read_upstream_fingerprints
# so India's behavior does NOT change.
# ============================================================================

def _india_predicate_iran_hormuz(upstream, acc):
    """Hormuz pressure → boost PMO + economic_statecraft."""
    iran = upstream.get('iran', {})
    if not iran:
        return
    iran_score = int(iran.get('theatre_score', 0) or 0)
    iran_irgc = int(iran.get('irgc_level', iran.get('irgc_direct_level', 0)) or 0)
    iran_targets = iran.get('named_targets', []) or []

    hormuz_named = any(t in iran_targets for t in
                       ['hormuz', 'strait of hormuz', 'persian gulf'])
    hormuz_pressure = (
        bool(iran.get('iran_hormuz_pressure'))
        or hormuz_named
        or (iran_score >= 60 and iran_irgc >= 3)
    )
    if hormuz_pressure:
        acc['upstream_stressors'].append('iran_hormuz_oil')
        acc['context_notes'].append(
            f"Iran-Hormuz pressure active (theatre_score={iran_score}, "
            f"IRGC L{iran_irgc}) — Modi-class jawboning + RBI FX defense "
            f"more likely; PMO + economic_statecraft amplified."
        )
        acc['amplifier_actor_deltas']['pmo'] = (
            acc['amplifier_actor_deltas'].get('pmo', 0) + 1
        )
        acc['amplifier_actor_deltas']['economic_statecraft'] = (
            acc['amplifier_actor_deltas'].get('economic_statecraft', 0) + 1
        )


def _india_predicate_iran_brics(upstream, acc):
    """BRICS / dedollarization signaling → boost MEA + economic_statecraft."""
    iran = upstream.get('iran', {})
    if not iran:
        return
    if iran.get('iran_brics_alignment_active') or iran.get('iran_dedollarization_active'):
        acc['upstream_stressors'].append('iran_brics_dedollarization')
        acc['context_notes'].append(
            "Iran BRICS/dedollarization rhetoric active — India MEA + "
            "economic_statecraft positioning amplified (strategic autonomy frame)."
        )
        acc['amplifier_actor_deltas']['mea'] = (
            acc['amplifier_actor_deltas'].get('mea', 0) + 1
        )


def _india_predicate_china_lac(upstream, acc):
    """China PLA at LAC posture → boost armed_forces + MEA."""
    china = upstream.get('china', {})
    if not china:
        return
    china_pla = int(china.get('pla_level', 0) or 0)
    china_targets = china.get('named_targets', []) or []
    lac_named = any(t in china_targets for t in
                    ['lac', 'line of actual control', 'arunachal', 'ladakh'])
    if china_pla >= 3 or lac_named:
        acc['upstream_stressors'].append('china_pla_lac_posture')
        acc['context_notes'].append(
            f"China PLA posture at L{china_pla} (LAC-named: {lac_named}) — "
            "India armed_forces + MEA decision-making amplified."
        )
        acc['amplifier_actor_deltas']['armed_forces'] = (
            acc['amplifier_actor_deltas'].get('armed_forces', 0) + 1
        )
        acc['amplifier_actor_deltas']['mea'] = (
            acc['amplifier_actor_deltas'].get('mea', 0) + 1
        )


def _india_predicate_china_tech_coercion(upstream, acc):
    """China economic / tech coercion → boost commerce + economic_statecraft."""
    china = upstream.get('china', {})
    if not china:
        return
    econ_level = int(china.get('econ_level', 0) or 0)
    if econ_level >= 2:
        acc['upstream_stressors'].append('china_tech_economic_coercion')
        acc['context_notes'].append(
            f"China economic coercion at L{econ_level} — India commerce + "
            "economic_statecraft amplified (rare earth / semiconductor exposure)."
        )
        acc['amplifier_actor_deltas']['economic_statecraft'] = (
            acc['amplifier_actor_deltas'].get('economic_statecraft', 0) + 1
        )


def _india_predicate_china_brics_architecture(upstream, acc):
    """China BRICS architect role → boost MEA."""
    china = upstream.get('china', {})
    if not china:
        return
    regime = china.get('regime_signals', {}) or {}
    if int(regime.get('brics_architect', 0) or 0) >= 1:
        if 'china_brics_architecture' not in acc['upstream_stressors']:
            acc['upstream_stressors'].append('china_brics_architecture')
            acc['context_notes'].append(
                "China actively shaping BRICS architecture — India MEA "
                "balancing act amplified (membership math + yuan settlement)."
            )
            acc['amplifier_actor_deltas']['mea'] = (
                acc['amplifier_actor_deltas'].get('mea', 0) + 1
            )


def _india_predicate_pakistan_loc(upstream, acc):
    """Pakistan LoC escalation → boost armed_forces."""
    pak = upstream.get('pakistan', {})
    if not pak:
        return
    if pak.get('loc_escalation_active') or pak.get('kashmir_pressure_active'):
        acc['upstream_stressors'].append('pakistan_loc_escalation')
        acc['context_notes'].append(
            "Pakistan LoC/Kashmir pressure active — India armed_forces amplified."
        )
        acc['amplifier_actor_deltas']['armed_forces'] = (
            acc['amplifier_actor_deltas'].get('armed_forces', 0) + 1
        )


def _india_predicate_pakistan_nuclear(upstream, acc):
    """Pakistan nuclear signaling → boost MEA + armed_forces."""
    pak = upstream.get('pakistan', {})
    if not pak:
        return
    if pak.get('nuclear_signaling_active'):
        acc['upstream_stressors'].append('pakistan_nuclear_signaling')
        acc['context_notes'].append(
            "Pakistan nuclear signaling active — India MEA + armed_forces "
            "amplified (declaratory posture decisions)."
        )
        acc['amplifier_actor_deltas']['mea'] = (
            acc['amplifier_actor_deltas'].get('mea', 0) + 1
        )
        acc['amplifier_actor_deltas']['armed_forces'] = (
            acc['amplifier_actor_deltas'].get('armed_forces', 0) + 1
        )


def _india_predicate_us_tariffs(upstream, acc):
    """US tariff pressure → boost commerce + economic_statecraft."""
    us = upstream.get('us', {})
    if not us:
        return
    us_outbound = us.get('us_outbound_targets', []) or []
    india_targeted = any(t.get('country') == 'india' for t in us_outbound if isinstance(t, dict))
    if india_targeted or us.get('us_tariff_pressure_active'):
        acc['upstream_stressors'].append('us_tariff_pressure')
        acc['context_notes'].append(
            "US tariff rhetoric targeting India — commerce + economic_statecraft amplified."
        )
        acc['amplifier_actor_deltas']['economic_statecraft'] = (
            acc['amplifier_actor_deltas'].get('economic_statecraft', 0) + 1
        )


def _india_predicate_us_executive_volatility(upstream, acc):
    """US executive volatility high → boost MEA (uncertainty management)."""
    us = upstream.get('us', {})
    if not us:
        return
    vol = float(us.get('us_executive_volatility', 0) or 0)
    if vol >= 0.6:
        if 'us_executive_volatility' not in acc['upstream_stressors']:
            acc['upstream_stressors'].append('us_executive_volatility')
            acc['context_notes'].append(
                f"US executive volatility elevated ({vol:.2f}) — India MEA "
                "amplified (managing unpredictable US policy)."
            )
            acc['amplifier_actor_deltas']['mea'] = (
                acc['amplifier_actor_deltas'].get('mea', 0) + 1
            )


def _india_predicate_us_h1b(upstream, acc):
    """US H1B / immigration restrictions → boost MEA."""
    us = upstream.get('us', {})
    if not us:
        return
    if us.get('us_h1b_pressure_active') or us.get('us_immigration_restrictive'):
        if 'us_h1b_pressure' not in acc['upstream_stressors']:
            acc['upstream_stressors'].append('us_h1b_pressure')
            acc['context_notes'].append(
                "US H1B/immigration restrictions — India diaspora/services "
                "exports exposed; MEA amplified."
            )
            acc['amplifier_actor_deltas']['mea'] = (
                acc['amplifier_actor_deltas'].get('mea', 0) + 1
            )


# ============================================================================
# PREDICATE FUNCTIONS — US CONSUMER
# NEW. These are what the rhetoric-us.html "Cross-Theater Reads" card will surface.
# ============================================================================

def _us_predicate_iran_hormuz(upstream, acc):
    """Iran Hormuz pressure → boost us_executive + us_defense."""
    iran = upstream.get('iran', {})
    if not iran:
        return
    iran_score = int(iran.get('theatre_score', 0) or 0)
    iran_irgc = int(iran.get('irgc_level', iran.get('irgc_direct_level', 0)) or 0)
    iran_targets = iran.get('named_targets', []) or []
    hormuz_named = any(t in iran_targets for t in
                       ['hormuz', 'strait of hormuz', 'persian gulf'])
    hormuz_pressure = (
        bool(iran.get('iran_hormuz_pressure'))
        or hormuz_named
        or (iran_score >= 50 and iran_irgc >= 2)
    )
    if hormuz_pressure:
        acc['upstream_stressors'].append('iran_hormuz_oil_shock')
        acc['context_notes'].append(
            f"Iran-Hormuz pressure active (theatre_score={iran_score}, "
            f"IRGC L{iran_irgc}) — US oil price exposure + political pain at "
            "the pump; us_executive + us_defense amplified."
        )
        acc['amplifier_actor_deltas']['us_executive'] = (
            acc['amplifier_actor_deltas'].get('us_executive', 0) + 1
        )
        acc['amplifier_actor_deltas']['us_defense'] = (
            acc['amplifier_actor_deltas'].get('us_defense', 0) + 1
        )


def _us_predicate_iran_jawboning_inbound(upstream, acc):
    """Iran is actively jawboning US → boost us_executive."""
    iran_jaw = _read_jawboning_fingerprints('iran')
    targets_us = any(
        (env.get('target_country') == 'us') or
        ('us' in (env.get('target_actors', []) or []))
        for env in iran_jaw.values()
        if isinstance(env, dict)
    )
    if targets_us:
        acc['upstream_stressors'].append('iran_jawboning_us')
        acc['context_notes'].append(
            "Iran actively jawboning US — Trump response cycle likely; "
            "us_executive amplified."
        )
        acc['amplifier_actor_deltas']['us_executive'] = (
            acc['amplifier_actor_deltas'].get('us_executive', 0) + 1
        )


def _us_predicate_china_rare_earths(upstream, acc):
    """
    Xi rare-earth weaponization → boost us_executive + us_defense.
    Reads BOTH the China envelope AND jawboning fingerprints (canonical signal).
    """
    china = upstream.get('china', {})
    china_jaw = _read_jawboning_fingerprints('china')
    rare_earth_active = (
        'xi_on_rare_earths' in china_jaw
        or any('rare_earth' in k or 'critical_mineral' in k for k in china_jaw)
        or int(china.get('econ_level', 0) or 0) >= 3
    )
    if rare_earth_active:
        acc['upstream_stressors'].append('china_rare_earth_squeeze')
        acc['context_notes'].append(
            "China weaponizing critical minerals (rare earths / gallium / "
            "germanium) — defense industrial base + semiconductor sector "
            "exposed; us_executive + us_defense amplified."
        )
        acc['amplifier_actor_deltas']['us_executive'] = (
            acc['amplifier_actor_deltas'].get('us_executive', 0) + 1
        )
        acc['amplifier_actor_deltas']['us_defense'] = (
            acc['amplifier_actor_deltas'].get('us_defense', 0) + 1
        )


def _us_predicate_china_pla_taiwan(upstream, acc):
    """PLA at coercion posture → boost us_defense + us_state_dept."""
    china = upstream.get('china', {})
    if not china:
        return
    pla_level = int(china.get('pla_level', 0) or 0)
    overall_level = int(china.get('overall_level', 0) or 0)
    if pla_level >= 3 or overall_level >= 4:
        acc['upstream_stressors'].append('china_taiwan_coercion')
        acc['context_notes'].append(
            f"China PLA at L{pla_level} (overall L{overall_level}) — 7th Fleet "
            "posture decisions + arms-sales calculus; us_defense + us_state_dept "
            "amplified."
        )
        acc['amplifier_actor_deltas']['us_defense'] = (
            acc['amplifier_actor_deltas'].get('us_defense', 0) + 1
        )
        acc['amplifier_actor_deltas']['us_state_dept'] = (
            acc['amplifier_actor_deltas'].get('us_state_dept', 0) + 1
        )


def _us_predicate_russia_ukraine(upstream, acc):
    """Russia-Ukraine pressure → boost us_executive + us_defense."""
    russia = upstream.get('russia', {})
    ukraine = upstream.get('ukraine', {})
    russia_level = int(russia.get('overall_level', russia.get('theatre_level', 0)) or 0)
    ukraine_frontline = False
    if isinstance(ukraine, dict):
        fp = ukraine.get('frontline_pressure')
        if fp in (True, 'true', 'True', '1', 1):
            ukraine_frontline = True
    if russia_level >= 3 or ukraine_frontline:
        acc['upstream_stressors'].append('russia_ukraine_attrition')
        acc['context_notes'].append(
            f"Russia-Ukraine elevated (Russia L{russia_level}, "
            f"Ukraine frontline_pressure={ukraine_frontline}) — US aid continuity + "
            "NATO posture decisions; us_executive + us_defense amplified."
        )
        acc['amplifier_actor_deltas']['us_executive'] = (
            acc['amplifier_actor_deltas'].get('us_executive', 0) + 1
        )
        acc['amplifier_actor_deltas']['us_defense'] = (
            acc['amplifier_actor_deltas'].get('us_defense', 0) + 1
        )


def _us_predicate_mexico_border(upstream, acc):
    """Mexico cartel / border pressure → boost us_dhs_ice + us_executive."""
    mexico = upstream.get('mexico', {})
    if not mexico:
        return
    mexico_score = int(mexico.get('theatre_score', mexico.get('overall_level', 0) * 20) or 0)
    if mexico_score >= 50 or mexico.get('cartel_escalation_active'):
        acc['upstream_stressors'].append('mexico_border_pressure')
        acc['context_notes'].append(
            f"Mexico/cartel pressure rising (score={mexico_score}) — DHS/ICE "
            "posture changes + executive border framing; us_dhs_ice + "
            "us_executive amplified."
        )
        acc['amplifier_actor_deltas']['us_dhs_ice'] = (
            acc['amplifier_actor_deltas'].get('us_dhs_ice', 0) + 1
        )
        acc['amplifier_actor_deltas']['us_executive'] = (
            acc['amplifier_actor_deltas'].get('us_executive', 0) + 1
        )


# ============================================================================
# PREDICATE LIBRARY — dispatch by consumer theater
# Adding a new consumer? Add an entry here + define the predicate functions above.
# ============================================================================

PREDICATE_LIBRARY = {
    'india': [
        _india_predicate_iran_hormuz,
        _india_predicate_iran_brics,
        _india_predicate_china_lac,
        _india_predicate_china_tech_coercion,
        _india_predicate_china_brics_architecture,
        _india_predicate_pakistan_loc,
        _india_predicate_pakistan_nuclear,
        _india_predicate_us_tariffs,
        _india_predicate_us_executive_volatility,
        _india_predicate_us_h1b,
    ],
    'us': [
        _us_predicate_iran_hormuz,
        _us_predicate_iran_jawboning_inbound,
        _us_predicate_china_rare_earths,
        _us_predicate_china_pla_taiwan,
        _us_predicate_russia_ukraine,
        _us_predicate_mexico_border,
    ],
    # Future consumers: 'cuba', 'russia', 'iran', 'china', etc.
}


# ============================================================================
# PUBLIC API
# ============================================================================

def read_butterfly_signals(consumer_theater):
    """
    The main entrypoint. Read all relevant upstream fingerprints from Redis,
    apply per-consumer predicates, return the canonical 4-field bundle.

    Args:
        consumer_theater: str — 'india', 'us', 'cuba', 'russia', etc.
                          Must have an entry in PREDICATE_LIBRARY.

    Returns:
        dict with keys:
            upstream_fingerprints  — raw envelopes per theater
            amplifier_actor_deltas — actor scoring boosts for the consumer
            context_notes          — human-readable notes for BLUF / So What
            upstream_stressors     — stressor labels for UI pills
            consumer_theater       — echo of the request
            read_at                — ISO timestamp
            predicates_evaluated   — count for diagnostics
            theaters_with_data     — count for diagnostics
    """
    consumer_theater = (consumer_theater or '').lower().strip()

    # Step 1: collect all upstream theater fingerprints
    upstream_fps = _collect_all_upstream(consumer_theater)

    # Step 2: initialize accumulators
    accumulators = {
        'upstream_fingerprints':  upstream_fps,
        'amplifier_actor_deltas': {},
        'context_notes':          [],
        'upstream_stressors':     [],
    }

    # Step 3: dispatch to consumer's predicate list
    predicates = PREDICATE_LIBRARY.get(consumer_theater, [])
    for predicate_fn in predicates:
        try:
            predicate_fn(upstream_fps, accumulators)
        except Exception as e:
            # Defensive: a buggy predicate must not crash the whole read
            print(f"[Butterfly Reader] Predicate {predicate_fn.__name__} "
                  f"failed for {consumer_theater}: {type(e).__name__}: "
                  f"{str(e)[:150]}")

    # Step 4: build response bundle
    return {
        'upstream_fingerprints':  accumulators['upstream_fingerprints'],
        'amplifier_actor_deltas': accumulators['amplifier_actor_deltas'],
        'context_notes':          accumulators['context_notes'],
        'upstream_stressors':     accumulators['upstream_stressors'],
        'consumer_theater':       consumer_theater,
        'read_at':                datetime.now(timezone.utc).isoformat(),
        'predicates_evaluated':   len(predicates),
        'theaters_with_data':     len(upstream_fps),
        'success':                True,
    }


def list_known_consumers():
    """Return list of theater names that have predicates defined."""
    return sorted(PREDICATE_LIBRARY.keys())


def get_predicate_health(consumer_theater):
    """Diagnostic — list predicates registered for a consumer."""
    predicates = PREDICATE_LIBRARY.get(consumer_theater.lower().strip(), [])
    return {
        'consumer_theater':   consumer_theater,
        'predicate_count':    len(predicates),
        'predicate_names':    [p.__name__ for p in predicates],
        'known_consumers':    list_known_consumers(),
    }


# ============================================================================
# FLASK ENDPOINT REGISTRATION
# ============================================================================

def register_butterfly_endpoints(app):
    """
    Register butterfly reader endpoints on the ME backend.

    Routes:
        GET  /api/butterfly/read/<consumer_theater>     — main read endpoint
        GET  /api/butterfly/health                      — diagnostics
        GET  /api/butterfly/consumers                   — list registered consumers
    """
    from flask import jsonify, request

    @app.route('/api/butterfly/read/<consumer_theater>', methods=['GET', 'OPTIONS'])
    def api_butterfly_read(consumer_theater):
        if request.method == 'OPTIONS':
            return '', 200
        try:
            result = read_butterfly_signals(consumer_theater)
            return jsonify(result)
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({
                'success': False,
                'error': f'{type(e).__name__}: {str(e)[:200]}',
                'consumer_theater': consumer_theater,
            }), 500

    @app.route('/api/butterfly/health', methods=['GET'])
    def api_butterfly_health():
        consumer = request.args.get('consumer', 'us')
        return jsonify(get_predicate_health(consumer))

    @app.route('/api/butterfly/consumers', methods=['GET'])
    def api_butterfly_consumers():
        return jsonify({
            'success':         True,
            'consumers':       list_known_consumers(),
            'theater_patterns': THEATER_PATTERNS,
        })

    print("[Butterfly Reader] ✅ Endpoints registered:")
    print("  GET  /api/butterfly/read/<consumer_theater>")
    print("  GET  /api/butterfly/health?consumer=<theater>")
    print("  GET  /api/butterfly/consumers")
