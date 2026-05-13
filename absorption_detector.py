"""
Asifah Analytics — ABSORPTION DETECTOR (shared helper, ME-hosted)
v1.0.1 — May 2026 — Butterfly Build Phase 2 foundation

PLACEMENT: ME backend (asifah-backend.onrender.com), co-located with
absorption_signatures.py. The HTTP endpoint that exposes this detector to
other backends lives in absorption_signatures.py's register_absorption_endpoints()
as POST /api/absorption/detect.

PURPOSE:
========
This module is a shared classification helper that any country's rhetoric
tracker can call (via its theater's proxy module) to detect
ECONOMIC_ABSORPTION_SIGNATURES from the combination of:
  (a) UPSTREAM fingerprints already written by other trackers (Iran, China,
      Pakistan, US, etc.) into Redis cross-theater keys
  (b) the country's OWN current rhetoric signals from its own scan

The detector returns structured absorption results. It does NOT persist;
storage lives in absorption_signatures.py (read_/write_absorption_signature).

WHY A SHARED HELPER:
====================
India is the platform's first absorber-class tracker, but it won't be the
last. Mexico will absorb US tariff pressure. Egypt will absorb Suez/Red Sea
pressure. Turkey will absorb Fed tightening. Each tracker should NOT
re-implement the absorption-detection wheel.

ARCHITECTURE:
=============

  Asia backend                ME backend                  Redis (shared)
  ──────────────              ──────────────              ──────────────
  rhetoric_tracker_india.py
       │
       ▼
  absorption_proxy_asia.py    /api/absorption/detect
       │  HTTPS POST          (registered by
       └─────────────────────▶ absorption_signatures.py)
                                    │
                                    ▼
                              absorption_detector.py  ←  THIS FILE
                                    │  (calls)
                                    ▼
                              absorption_signatures.   write_absorption_signature(...)
                              py
                                    │                                │
                                    └────────────────────────────────┴───────▶  Redis

USAGE — from absorption_signatures.py's /api/absorption/detect handler:
=======================================================================
    from absorption_detector import detect_absorption, detect_and_persist
    results = detect_absorption(
        country='india',
        upstream_fingerprints=body['upstream_fingerprints'],
        own_signals=body['own_signals'],
    )

USAGE — direct (from a co-located ME-backend caller, e.g., GPI):
================================================================
    from absorption_detector import detect_absorption
    results = detect_absorption('india', upstream_fps, own_signals)

DETECTION RULES (v1.0):
=======================
Rules are declarative. Each rule says: "if these upstream fingerprints fire
AND these own signals fire, emit this absorption signature."

NOTE on signature_id form:
  Use the NORMALIZED form (no trailing date) as the signature_id. The static
  catalog in absorption_signatures.py is keyed on the normalized form
  (e.g., 'india_gold_suppress_demand'), and _normalize_intervention_id()
  handles the dated form ('india_gold_suppress_demand_2026_05_11') for
  backward compat. Always emit the normalized form from rules here so
  catalog lookups succeed first-try.

CONFIDENCE SCORING:
===================
Confidence is a 0.0-1.0 float derived from:
  - Strength of upstream signals (when_upstream fired? how many fingerprints?)
  - Strength of own signals (when_own fired?)
  - Recency of upstream fingerprints (fresher = higher confidence)

If confidence falls below MIN_CONFIDENCE_TO_EMIT, the rule does NOT fire.

ADDING NEW RULES:
=================
To add a new country's absorption rules:
  1. Add static signature to absorption_signatures.py ABSORPTION_SIGNATURES_STATIC
     (in normalized form, e.g., 'mexico_pemex_us_tariff_absorption')
  2. Add detection rule to ABSORPTION_RULES below
  3. Caller (its theater's proxy module) POSTs to /api/absorption/detect

CHANGELOG:
==========
  v1.0.0 (2026-05-12): Initial build — India absorption rules, generic
                       detector framework.
  v1.0.1 (2026-05-12): Re-homed to ME backend (was briefly on Asia in a
                       drafting iteration). Fixed signature_id to use the
                       normalized form (no date suffix) to match
                       absorption_signatures.py catalog keys.

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
from datetime import datetime, timezone

# ============================================================================
# CONFIG
# ============================================================================
ABSORPTION_DETECTOR_VERSION = '1.0.1'

# Confidence weights — tunable
WEIGHT_UPSTREAM_FIRED   = 0.50   # how much the upstream side contributes
WEIGHT_OWN_SIGNAL_FIRED = 0.35   # how much the own side contributes
WEIGHT_RECENCY_BONUS    = 0.15   # bonus for fresh upstream fingerprints

# Confidence floor — below this, don't emit at all
MIN_CONFIDENCE_TO_EMIT = 0.35


# ============================================================================
# DETECTION RULES — declarative catalog
# ============================================================================
# Each rule defines:
#   rule_id            — unique identifier for this rule (logging only)
#   country            — which country this rule applies to
#   description        — human-readable rule description
#   when_upstream(fps) — predicate over upstream fingerprints dict
#                        (returns truthy = upstream side fires)
#   when_own(own)      — predicate over own_signals dict
#                        (returns truthy = own side fires)
#   signature_id       — NORMALIZED signature key in absorption_signatures.py
#                        ABSORPTION_SIGNATURES_STATIC catalog
#   upstream_stressors — list of stressor labels to attribute (for display)
#   cohesion_stress_level — 0-5 cohesion contribution (drives internal dash)
#
# Both when_upstream AND when_own must fire for the rule to emit.

ABSORPTION_RULES = [

    # ── INDIA · Gold suppression under Hormuz+Fed pressure (Modi May 2026)
    {
        'rule_id':         'india_gold_modi_2026_05',
        'country':         'india',
        'description':     (
            "Modi public exhortation to suspend gold buying classified as "
            "defensive statecraft when upstream Iran/Hormuz oil pressure AND "
            "Fed-driven USD strength are present."
        ),
        'when_upstream':   lambda fps: (
            (fps.get('iran', {}).get('theatre_score', 0) >= 40)
            or (fps.get('iran', {}).get('iran_hormuz_pressure'))
            or any(t in (fps.get('iran', {}).get('named_targets') or [])
                   for t in ['hormuz', 'strait of hormuz', 'persian gulf'])
        ),
        'when_own':        lambda own: bool(own.get('modi_gold_jawboning')),
        'signature_id':    'india_gold_suppress_demand',
        'upstream_stressors':    ['iran_hormuz_oil', 'fed_dollar_strength'],
        'cohesion_stress_level': 1,
    },

    # ── INDIA · RBI FX defense under multi-axis pressure
    {
        'rule_id':         'india_rbi_fx_defense_v1',
        'country':         'india',
        'description':     (
            "RBI active rupee defense (FX intervention, gold accumulation, "
            "swap signaling) classified as defensive monetary statecraft "
            "when upstream oil pressure AND/OR US-side dollar dynamics fire."
        ),
        'when_upstream':   lambda fps: (
            (fps.get('iran', {}).get('theatre_score', 0) >= 30)
            or (fps.get('us', {}).get('us_executive_volatility', 0) >= 1.5)
        ),
        'when_own':        lambda own: bool(own.get('rbi_fx_defense')),
        'signature_id':    'india_rbi_fx_defense',
        'upstream_stressors':    ['iran_hormuz_oil', 'fed_dollar_strength'],
        'cohesion_stress_level': 1,
    },

    # ── INDIA · Tariff absorption under US-side pressure
    {
        'rule_id':         'india_us_tariff_absorption_v1',
        'country':         'india',
        'description':     (
            "Indian rhetoric absorbing US tariff/H-1B/tech-export pressure. "
            "Fires when US tracker has India in its outbound_targets list "
            "AND India shows commerce-ministry/MEA defensive language."
        ),
        'when_upstream':   lambda fps: any(
            t.get('country') == 'india'
            for t in (fps.get('us', {}).get('us_outbound_targets') or [])
        ),
        'when_own':        lambda own: bool(
            own.get('mea_us_friction_active')
            or own.get('commerce_tariff_response')
        ),
        'signature_id':    'india_us_tariff_absorption',
        'upstream_stressors':    ['us_tariff_pressure', 'us_h1b_pressure'],
        'cohesion_stress_level': 2,
    },

    # ── INDIA · LAC tension absorption (China side)
    {
        'rule_id':         'india_china_lac_absorption_v1',
        'country':         'india',
        'description':     (
            "India absorbing China LAC pressure. Fires when China tracker "
            "PLA level elevated AND India armed-forces voice active."
        ),
        'when_upstream':   lambda fps: (
            (fps.get('china', {}).get('pla_level', 0) >= 3)
            or (fps.get('china', {}).get('level', 0) >= 3)
        ),
        'when_own':        lambda own: bool(own.get('armed_forces_lac_active')),
        'signature_id':    'india_china_lac_absorption',
        'upstream_stressors':    ['china_pla_lac_posture'],
        'cohesion_stress_level': 1,
    },

    # ── INDIA · Pakistan/Kashmir absorption
    {
        'rule_id':         'india_pakistan_kashmir_absorption_v1',
        'country':         'india',
        'description':     (
            "India absorbing Pakistan LoC/Kashmir escalation. Fires when "
            "Pakistan kashmir_loc_level elevated AND India own LoC/Kashmir "
            "signals active."
        ),
        'when_upstream':   lambda fps: (
            (fps.get('pakistan', {}).get('kashmir_loc_level', 0) >= 3)
            or (fps.get('pakistan', {}).get('pakistan_india_active'))
        ),
        'when_own':        lambda own: bool(own.get('kashmir_loc_active')),
        'signature_id':    'india_pakistan_kashmir_absorption',
        'upstream_stressors':    ['pakistan_loc_escalation'],
        'cohesion_stress_level': 2,
    },

    # ── INDIA · Modi austerity jawboning (May 2026, multi-axis pressure)
    {
        'rule_id':         'india_modi_austerity_v1',
        'country':         'india',
        'description':     (
            "Modi public-rhetoric campaign for broad consumption restraint "
            "(foreign-travel suspension, SPG-convoy cuts, government "
            "austerity measures, non-essential-spending appeals). "
            "Classified as defensive aggregate-demand statecraft when ANY "
            "upstream pressure axis is active. The mechanism: rhetoric "
            "moves consumer behavior + discretionary stocks BEFORE policy "
            "levers engage — validated by Reuters reporting on consumer-"
            "staples + premium-discretionary stock declines following "
            "Modi's austerity call (May 13, 2026)."
        ),
        'when_upstream':   lambda fps: (
            # Any non-trivial upstream pressure qualifies — austerity is a
            # general-purpose absorption response, not commodity-specific
            (fps.get('iran', {}).get('theatre_score', 0) >= 30)
            or (fps.get('china', {}).get('level', 0) >= 3)
            or (fps.get('us', {}).get('us_executive_volatility', 0) >= 1.0)
            or any(
                (isinstance(t, dict) and t.get('country') == 'india')
                or (isinstance(t, str) and t.lower() == 'india')
                for t in (fps.get('us', {}).get('us_outbound_targets') or [])
            )
        ),
        'when_own':        lambda own: bool(own.get('modi_austerity_active')),
        'signature_id':    'india_modi_austerity_jawboning',
        'upstream_stressors':    ['multi_axis_pressure', 'fed_dollar_strength'],
        'cohesion_stress_level': 2,
    },

    # NOTE: Add rules for other absorber-class trackers (Mexico, Egypt, Turkey)
    # here as those trackers come online. Each rule needs a matching static
    # catalog entry in absorption_signatures.py ABSORPTION_SIGNATURES_STATIC.
]


# ============================================================================
# HELPERS — recency, confidence, evidence trail
# ============================================================================

def _fingerprint_recency_hours(fp):
    """
    Given an upstream fingerprint dict, return how many hours since it was
    written. Returns 99 if no timestamp present (treated as stale).
    Looks for: 'ts', 'updated_at', 'written_at' fields.
    """
    if not fp:
        return 99.0
    for field in ('ts', 'updated_at', 'written_at'):
        v = fp.get(field)
        if not v:
            continue
        try:
            dt = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
            delta = datetime.now(timezone.utc) - dt
            return max(0.0, delta.total_seconds() / 3600.0)
        except Exception:
            continue
    return 99.0


def _compute_confidence(rule, upstream_fps, own_signals):
    """
    Compute 0.0-1.0 confidence that the absorption signature applies right now.
    """
    score = 0.0

    try:
        if rule['when_upstream'](upstream_fps):
            score += WEIGHT_UPSTREAM_FIRED
    except Exception:
        pass

    try:
        if rule['when_own'](own_signals):
            score += WEIGHT_OWN_SIGNAL_FIRED
    except Exception:
        pass

    if upstream_fps:
        freshest = min(
            (_fingerprint_recency_hours(fp) for fp in upstream_fps.values()),
            default=99.0
        )
        if freshest < 6:
            score += WEIGHT_RECENCY_BONUS
        elif freshest < 12:
            score += WEIGHT_RECENCY_BONUS * 0.6
        elif freshest < 24:
            score += WEIGHT_RECENCY_BONUS * 0.3

    return min(1.0, score)


def _build_upstream_evidence(rule, upstream_fps):
    """
    Build a structured evidence trail showing WHICH upstream signals fired.
    Returns list of: [{'theater': 'iran', 'field': 'theatre_score', 'value': 65}, ...]
    """
    evidence = []
    if not upstream_fps:
        return evidence

    interesting_fields = {
        'iran':     ['theatre_score', 'irgc_level', 'iran_hormuz_pressure',
                     'proxy_activation_level', 'iran_brics_alignment_active',
                     'iran_gold_for_oil_active', 'iran_dedollarization_active'],
        'china':    ['level', 'pla_level', 'xi_level', 'econ_level',
                     'china_brics_architect_active',
                     'china_yuan_internationalization_active'],
        'pakistan': ['theatre_level', 'theatre_score', 'kashmir_loc_level',
                     'nuclear_doctrine_level', 'pakistan_india_active'],
        'us':       ['us_active', 'us_composite_score',
                     'us_executive_volatility', 'us_dhs_enforcement_active'],
    }
    for theater, fields in interesting_fields.items():
        fp = upstream_fps.get(theater) or {}
        for field in fields:
            v = fp.get(field)
            if v is None or v is False or v == 0:
                continue
            evidence.append({
                'theater': theater,
                'field':   field,
                'value':   v,
            })
    return evidence


# ============================================================================
# MAIN ENTRY POINTS
# ============================================================================

def detect_absorption(country, upstream_fingerprints=None, own_signals=None):
    """
    Run all absorption rules for `country` against the provided upstream
    fingerprints and own signals. Returns a list of structured absorption
    results, one per fired rule (could be 0, 1, or many).

    Args:
        country: lowercase country slug ('india', 'mexico', etc.)
        upstream_fingerprints: dict mapping theater→fingerprint dict
        own_signals: dict of caller-provided signal flags

    Returns:
        list[dict] — one entry per fired rule. Empty list if nothing fires.
    """
    upstream_fingerprints = upstream_fingerprints or {}
    own_signals = own_signals or {}
    country = (country or '').lower().strip()

    results = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for rule in ABSORPTION_RULES:
        if rule['country'] != country:
            continue

        try:
            upstream_fired = bool(rule['when_upstream'](upstream_fingerprints))
        except Exception as e:
            print(f"[Absorption Detector] when_upstream error in {rule['rule_id']}: {e}")
            upstream_fired = False

        try:
            own_fired = bool(rule['when_own'](own_signals))
        except Exception as e:
            print(f"[Absorption Detector] when_own error in {rule['rule_id']}: {e}")
            own_fired = False

        if not (upstream_fired and own_fired):
            continue

        confidence = _compute_confidence(rule, upstream_fingerprints, own_signals)
        if confidence < MIN_CONFIDENCE_TO_EMIT:
            continue

        results.append({
            'signature_id':          rule['signature_id'],
            'rule_id':               rule['rule_id'],
            'country':               country,
            'detected_at':           now_iso,
            'confidence':            round(confidence, 3),
            'upstream_stressors':    list(rule.get('upstream_stressors') or []),
            'cohesion_stress_level': int(rule.get('cohesion_stress_level') or 0),
            'upstream_evidence':     _build_upstream_evidence(rule, upstream_fingerprints),
            'detector_version':      ABSORPTION_DETECTOR_VERSION,
            'rule_description':      rule.get('description', ''),
        })

    return results


def detect_and_persist(country, upstream_fingerprints=None, own_signals=None):
    """
    Like detect_absorption, but ALSO persists each fired result via
    absorption_signatures.write_absorption_signature(). Each result in the
    returned list gets a 'persisted' boolean indicating Redis write success.

    Called by /api/absorption/detect when the request body has persist=true.
    """
    results = detect_absorption(country, upstream_fingerprints, own_signals)
    if not results:
        return results

    try:
        from absorption_signatures import write_absorption_signature
    except ImportError:
        print("[Absorption Detector] absorption_signatures module not importable; "
              "results returned but NOT persisted.")
        for r in results:
            r['persisted'] = False
        return results

    for r in results:
        try:
            ok = write_absorption_signature(r['signature_id'], r)
            r['persisted'] = bool(ok)
        except Exception as e:
            print(f"[Absorption Detector] persist error for "
                  f"{r['signature_id']}: {e}")
            r['persisted'] = False

    return results


# ============================================================================
# SELF-TEST / SANITY CHECK
# ============================================================================

def _selftest():
    """Sanity test — fires the Modi-gold rule with a synthetic input."""
    fake_iran = {
        'ts':                  datetime.now(timezone.utc).isoformat(),
        'theatre_score':       65,
        'irgc_level':          3,
        'iran_hormuz_pressure': True,
        'named_targets':       ['hormuz', 'persian gulf'],
    }
    upstream = {'iran': fake_iran}
    own = {'modi_gold_jawboning': True}

    results = detect_absorption('india', upstream, own)
    print(f"[Absorption Detector self-test] Results: {len(results)} rule(s) fired")
    for r in results:
        print(f"  → {r['signature_id']} (confidence {r['confidence']})")
        print(f"    rule: {r['rule_id']}")
        print(f"    upstream evidence: {len(r['upstream_evidence'])} signals")
    return results


if __name__ == '__main__':
    _selftest()
