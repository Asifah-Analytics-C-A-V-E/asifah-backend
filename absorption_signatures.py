"""
================================================================================
absorption_signatures.py — Asifah Analytics
================================================================================
ECONOMIC ABSORPTION SIGNATURES — Phase 1 architectural stub.

The "So What" layer for leader commodity interventions. Where the leader
interventions module (commodity_tracker.py) answers "WHAT did this leader say
and what's the surface taxonomy?", this module answers "WHY did this happen
and what does it signal next?".

Two analytical layers live here:

  1. UPSTREAM CAUSAL ATTRIBUTION — "This intervention is downstream of
     {theater} pressure transmitting through {mechanism}." Looking BACK along
     the chain.

  2. FORWARD INDICATION — "Watch for {next rung} within {timeframe}. Historical
     analog: {country, year}. Trigger conditions: ..." Looking FORWARD.

ARCHITECTURE

  Phase 1 (today):     Static catalog (ABSORPTION_SIGNATURES_STATIC) hand-
                       curated by analyst desk. Demo-ready signatures for
                       high-value cases (Modi gold call, future Trump oil,
                       future Xi rare earths, etc.).

  Phase 2 (rhetoric    India Rhetoric Tracker (and other country trackers)
   trackers):          will generate these dynamically by reading shared
                       cross-theater fingerprints, applying classification
                       logic, and writing to Redis. This module reads Redis
                       first, falls back to static. NO REFACTOR NEEDED.

  Phase 5 (GPI):       Global Pressure Index aggregates absorption signatures
                       as the "absorption dimension" alongside the existing
                       escalation dimension.

USAGE

  Read:
    from absorption_signatures import read_absorption_signature
    sig = read_absorption_signature('india_gold_suppress_demand_2026_05_11')

  Endpoints:
    GET /api/absorption-signature/<intervention_id>
    GET /api/absorption-signatures           (debug — list all known)

  Register in app.py:
    from absorption_signatures import register_absorption_endpoints
    register_absorption_endpoints(app)

v1.0.0 — May 11 2026 · Butterfly Build Phase 1
================================================================================
"""

import os
import json
import requests
from datetime import datetime, timezone


# ============================================================================
# REDIS CONFIG (mirrors commodity_tracker.py pattern)
# ============================================================================

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_REST_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')

ABSORPTION_TTL_HOURS = 168   # 7 days — static signatures don't go stale fast


def _absorption_redis_key(intervention_id):
    """Canonical Redis key for an absorption signature fingerprint."""
    return f"absorption_signature:{intervention_id}"


def _normalize_intervention_id(intervention_id):
    """
    Tolerant lookup helper. The cached fingerprint from the pre-Patch5.5 scan
    has format `india_gold_suppress_demand_` (trailing underscore from missing
    date). The post-fix format is `india_gold_suppress_demand_2026_05_11`.

    For static-catalog matching we normalize both to the trimmed base form so
    the same signature matches regardless of which version of the fingerprint
    is in Redis.

    Returns the normalized intervention_id (lowercased, trailing underscores
    stripped, date suffix stripped).
    """
    if not intervention_id:
        return ''
    s = intervention_id.lower().strip().rstrip('_')
    # Strip date suffix if present (YYYY_MM_DD at the end)
    parts = s.split('_')
    if len(parts) >= 3 and parts[-3].isdigit() and parts[-2].isdigit() and parts[-1].isdigit():
        s = '_'.join(parts[:-3])
    return s


# ============================================================================
# STATIC CATALOG — Hand-curated absorption signatures
# ============================================================================
# Phase 1 demo data. Add entries here to expand. Phase 2 rhetoric trackers
# will eventually write dynamic signatures to Redis that override these.
#
# Key format: normalized intervention_id (no trailing _, no date suffix).
# Example: 'india_gold_suppress_demand'
# ============================================================================

ABSORPTION_SIGNATURES_STATIC = {

    # ── INDIA · GOLD · SUPPRESS DEMAND ────────────────────────────────────
    # Modi's May 2026 call for Indians to suspend gold buying for one year.
    # The flagship Phase 1 demo signature.
    'india_gold_suppress_demand': {
        # ── Identity ──────────────────────────────────────────────────────
        'intervention_id_normalized': 'india_gold_suppress_demand',
        'country':                    'india',
        'commodity':                  'gold',
        'speaker':                    'Narendra Modi',
        'direction':                  'suppress_demand',

        # ── Classification ────────────────────────────────────────────────
        'classification':             'defensive_statecraft',
        'pressure_class':             'balance_of_payments',
        'confidence':                 0.85,

        # ── Upstream attribution ──────────────────────────────────────────
        'upstream_stressors': [
            {
                'theater':         'iran',
                'mechanism':       'hormuz_oil_pricing',
                'fingerprint_ref': {
                    'redis_key': 'rhetoric:crosstheater:fingerprints',
                    'theater':   'iran',
                    'field':     'named_targets',
                    'expects':   ['hormuz', 'strait'],
                },
                'contribution':    0.70,
                'note':            'Sustained Iran-US friction at the Strait of Hormuz has kept Brent elevated above $85, expanding India\'s oil import bill.',
            },
            {
                'theater':         'global',
                'mechanism':       'fed_policy_tightening',
                'fingerprint_ref': None,
                'contribution':    0.20,
                'note':            'Strong dollar on Fed positioning compounds INR pressure from two directions simultaneously.',
            },
        ],

        # ── Transmission chain ────────────────────────────────────────────
        'transmission_chain': [
            {'step': 1, 'label': 'Iran-US friction at the Strait of Hormuz',     'theater': 'iran'},
            {'step': 2, 'label': 'Brent crude elevated above $85/bbl',           'theater': 'commodities'},
            {'step': 3, 'label': 'India oil import bill rises sharply',          'theater': 'india'},
            {'step': 4, 'label': 'Rupee weakens vs USD',                          'theater': 'india'},
            {'step': 5, 'label': 'FX reserves absorb pressure from two sides',   'theater': 'india'},
            {'step': 6, 'label': 'Modi: suppress discretionary gold imports',    'theater': 'india', 'is_intervention': True},
        ],

        # ── Forward indication ────────────────────────────────────────────
        'escalation_ladder': {
            'current_rung': 'jawboning',
            'next_rungs': [
                {'name': 'import_duty_hike',    'description': 'Gold import duty raised 2–5 percentage points',         'estimated_days': 75,  'probability': 0.55},
                {'name': 'capital_controls',    'description': 'Tighter LRS limits on outward investment',              'estimated_days': 150, 'probability': 0.20},
                {'name': 'imf_consultation',    'description': '1991-style BoP crisis requiring IMF involvement',       'estimated_days': 240, 'probability': 0.05},
            ],
            'trigger_conditions': [
                'Brent sustained above $90/bbl for 30+ consecutive days',
                'INR breaks 88/USD',
                'FX reserves drop below $580B',
            ],
            'analyst_note': 'Any two trigger conditions firing simultaneously raises probability of formal duty action within 30 days.',
        },

        # ── Historical analog ─────────────────────────────────────────────
        'historical_analog': {
            'country':       'india',
            'year':          1991,
            'event':         'Balance of payments crisis',
            'preceded':      'IMF structural adjustment loan; pledging of gold reserves to the Bank of England',
            'similarity':    'Discretionary-import suppression rhetoric preceded the formal pledging of gold reserves. The 2026 sequence is following the same playbook at an earlier rung.',
        },

        # ── Diplomatic-cable-style read-out ───────────────────────────────
        'so_what_short': (
            "Modi's call for Indians to suspend gold purchases for a year is "
            "downstream defensive statecraft, not a domestic gold story. "
            "Sustained Iran-US friction at the Strait of Hormuz has elevated "
            "Brent crude, expanding India's oil import bill and pressuring the "
            "rupee against an already-strong dollar. Modi is reaching for the "
            "highest-leverage discretionary import India can suppress (gold, "
            "~$72B annual imports, 90%+ imported) before resorting to formal "
            "policy. Watch for a gold import duty hike within 60–90 days if "
            "Hormuz tension persists. Historical echo of India's 1991 "
            "balance-of-payments playbook."
        ),

        'so_what_long': (
            "THE CHAIN. Iran's posture toward the Strait of Hormuz over the "
            "spring of 2026 has kept Brent crude elevated above $85 for weeks. "
            "India imports roughly 85% of its crude, and at sustained $85+ "
            "pricing, the marginal cost to India's oil import bill runs into "
            "the tens of billions annually. The rupee has weakened in lockstep "
            "— and with the dollar simultaneously strong on Fed positioning, "
            "India's FX reserves are absorbing pressure from two directions at "
            "once. Modi's exhortation against gold buying is the most visible "
            "signal that the government has begun reaching for the "
            "discretionary-import lever."
            "\n\n"
            "WHY GOLD SPECIFICALLY. India is the world's second-largest gold "
            "consumer, with annual imports near $72 billion. Roughly 90%+ of "
            "consumed gold is imported. Gold is also the most price-elastic "
            "discretionary import India has — domestic demand can be "
            "meaningfully suppressed by social signaling and policy without "
            "immediate economic damage (unlike fuel or fertilizer). Suppressing "
            "gold is the cheapest FX defense move available to a head of state "
            "short of a formal duty announcement. That Modi is moving to "
            "verbal suppression BEFORE announcing a duty hike is itself a "
            "signal — it suggests internal debate about how visibly to "
            "acknowledge the FX stress."
            "\n\n"
            "WHAT TO WATCH. The escalation ladder from here is well-traveled "
            "in Indian economic history. First rung (current): leader "
            "jawboning. Second rung (60–90 days, if Brent sustains > $90): a "
            "gold import duty hike, likely 2–5 percentage points. Third rung "
            "(3–6 months, if INR breaks 88/USD): tighter capital controls or "
            "LRS limits on outward investment. Fourth rung (less likely, but "
            "the historical analog): a 1991-style BoP crisis requiring IMF "
            "consultation. The 1991 episode also began with "
            "discretionary-import suppression rhetoric before the formal "
            "pledging of gold reserves to the Bank of England. The platform "
            "should track three trigger conditions: Brent sustained above $90 "
            "for 30+ days, INR breaking 88/USD, and FX reserves dropping "
            "below $580B. Any two firing simultaneously raises the probability "
            "of formal duty action within 30 days."
        ),

        # ── Provenance ────────────────────────────────────────────────────
        'source':       'manual_v1',
        'authored_by':  'Asifah Analyst Desk',
        'authored_at':  '2026-05-11T18:30:00Z',
        'ttl_hours':    ABSORPTION_TTL_HOURS,
    },

    # ── (Add more static signatures here as analyst desk hand-curates them) ──
}


# ============================================================================
# READ PATH — Redis-first with static fallback
# ============================================================================

def read_absorption_signature(intervention_id):
    """
    Look up an absorption signature for a leader intervention.

    Lookup order:
        1. Redis at absorption_signature:{intervention_id}   (Phase 2 source)
        2. Static catalog at normalized key                  (Phase 1 source)
        3. None

    Returns the signature dict, or None if not found.
    """
    if not intervention_id:
        return None

    # ── Try Redis first (Phase 2 rhetoric tracker dynamic signatures) ────
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            key = _absorption_redis_key(intervention_id)
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{key}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            if resp.status_code == 200:
                result = resp.json().get('result')
                if result:
                    return json.loads(result)
        except Exception as e:
            print(f"[Absorption Signatures] Redis read error ({intervention_id}): {str(e)[:120]}")

    # ── Fall back to static catalog ──────────────────────────────────────
    normalized = _normalize_intervention_id(intervention_id)
    static_match = ABSORPTION_SIGNATURES_STATIC.get(normalized)
    if static_match:
        # Return a shallow copy with the original intervention_id attached so
        # the consumer knows which intervention it matched against.
        return {
            **static_match,
            'matched_intervention_id': intervention_id,
            'source_type':             'static_catalog',
        }

    return None


def list_known_signatures():
    """
    List all known absorption signatures (static catalog + Redis if available).
    Used by the debug endpoint and by Phase 2 discovery.

    Returns a list of dicts: [{'intervention_id_normalized': ..., 'source_type': ...}, ...]
    """
    out = []
    for key, sig in ABSORPTION_SIGNATURES_STATIC.items():
        out.append({
            'intervention_id_normalized': key,
            'country':                    sig.get('country'),
            'commodity':                  sig.get('commodity'),
            'speaker':                    sig.get('speaker'),
            'classification':             sig.get('classification'),
            'source_type':                'static_catalog',
        })
    # Note: We don't enumerate Redis keys here (would require a SCAN). When
    # Phase 2 lands and writes dynamic signatures, we'll add a SCAN-based
    # listing or maintain a separate index key.
    return out


# ============================================================================
# WRITE PATH — For Phase 2 rhetoric trackers to call
# ============================================================================

def write_absorption_signature(intervention_id, signature):
    """
    Write an absorption signature to Redis. Intended for Phase 2 rhetoric
    trackers to call when they generate dynamic signatures.

    Returns True on success, False otherwise.
    """
    if not intervention_id or not signature:
        return False
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False

    # Always stamp provenance + audit fields
    signature_to_write = {
        **signature,
        'written_at':  datetime.now(timezone.utc).isoformat(),
    }

    key = _absorption_redis_key(intervention_id)
    ttl_seconds = int(signature.get('ttl_hours', ABSORPTION_TTL_HOURS)) * 3600

    try:
        url = f"{UPSTASH_REDIS_URL}/setex/{key}/{ttl_seconds}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(signature_to_write, default=str),
            timeout=5
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Absorption Signatures] Write error ({intervention_id}): {str(e)[:120]}")
        return False


# ============================================================================
# ENDPOINTS
# ============================================================================

def register_absorption_endpoints(app):
    """
    Register absorption-signature endpoints on the Flask app.
    Call from app.py:
        from absorption_signatures import register_absorption_endpoints
        register_absorption_endpoints(app)
    """
    from flask import jsonify, request as flask_request

    @app.route('/api/absorption-signature/<intervention_id>', methods=['GET', 'OPTIONS'])
    def api_absorption_signature(intervention_id):
        """
        Return the absorption signature for a single leader intervention.
        Falls back to static catalog if no Redis entry exists.
        Returns 200 with `signature: null` if no signature is known — this is
        the expected case for most interventions and should not be treated as
        an error by the client.
        """
        if flask_request.method == 'OPTIONS':
            return '', 200
        intervention_id = (intervention_id or '').strip()
        sig = read_absorption_signature(intervention_id)
        return jsonify({
            'success':         True,
            'intervention_id': intervention_id,
            'signature':       sig,
            'has_signature':   sig is not None,
            'last_updated':    datetime.now(timezone.utc).isoformat(),
        })

    @app.route('/api/absorption-signatures', methods=['GET', 'OPTIONS'])
    def api_absorption_signatures_list():
        """
        List all known absorption signatures (debug + discovery).
        Phase 1: lists static catalog only. Phase 2 will add Redis-backed list.
        """
        if flask_request.method == 'OPTIONS':
            return '', 200
        catalog = list_known_signatures()
        return jsonify({
            'success':       True,
            'count':         len(catalog),
            'signatures':    catalog,
            'phase':         '1.0 — static catalog',
            'last_updated':  datetime.now(timezone.utc).isoformat(),
        })

    print("[Absorption Signatures] ✅ Endpoints registered:")
    print("  GET  /api/absorption-signature/<intervention_id>")
    print("  GET  /api/absorption-signatures")
