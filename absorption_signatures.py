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
from datetime import datetime, timezone, timedelta


# ============================================================================
# REDIS CONFIG (mirrors commodity_tracker.py pattern)
# ============================================================================
# A3 FIX (May 13, 2026): Accept BOTH env var naming conventions.
#
# Background: The ME backend was originally configured with
# UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN. Newer trackers (Asia
# rhetoric_tracker_india.py and the absorption_detector module) use the
# shorter UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN. If ME only has the shorter
# names set, this file's Redis path silently no-ops — every
# write_absorption_signature() returns False and downstream callers see
# persisted: false. The fallback below resolves either configuration.
#
# The platform invariant: ME and Asia share ONE Upstash instance. Whatever
# names are set on a given backend, they should point at the same URL/token.
UPSTASH_REDIS_URL = (
    os.environ.get('UPSTASH_REDIS_REST_URL')
    or os.environ.get('UPSTASH_REDIS_URL')
    or ''
)
UPSTASH_REDIS_TOKEN = (
    os.environ.get('UPSTASH_REDIS_REST_TOKEN')
    or os.environ.get('UPSTASH_REDIS_TOKEN')
    or ''
)

# Startup diagnostic — surfaces immediately in Render deploy logs so we
# know whether the env var fallback worked on first boot without having
# to wait for a real signature write attempt.
if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
    print(f"[Absorption Signatures] ✅ Redis configured "
          f"(URL ends '...{UPSTASH_REDIS_URL[-24:]}', token present)")
else:
    print("[Absorption Signatures] ⚠️ Redis NOT configured — "
          "write/read paths will silently no-op. Set either "
          "UPSTASH_REDIS_URL+UPSTASH_REDIS_TOKEN or "
          "UPSTASH_REDIS_REST_URL+UPSTASH_REDIS_REST_TOKEN in Render.")

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
        'source':                  'manual_v1',
        'authored_by':             'Asifah Analyst Desk',
        'authored_at':             '2026-05-11T18:30:00Z',
        'ttl_hours':               ABSORPTION_TTL_HOURS,

        # ── Analytical decay ──────────────────────────────────────────────
        # Static signatures grow stale as conditions evolve. Setting an
        # explicit validity window forces the analyst desk to re-author
        # before the analysis lags behind events. Computed staleness fields
        # are appended in read_absorption_signature() at read time.
        'analytical_validity_days': 30,
    },

    #
    # ════════════════════════════════════════════════════════════════════
    # 🚨 PHASE 2 BACKLOG REMINDER 🚨
    # ════════════════════════════════════════════════════════════════════
    # The static catalog is intentionally manual for Phase 1. When new
    # leader interventions are detected (e.g. "Modi on copper", "Putin on
    # gold", "Xi on rare earths"), they will NOT have a So What analysis
    # until either (a) an analyst hand-writes a static entry here, or
    # (b) Phase 2 India/Russia/China Rhetoric Trackers generate dynamic
    # signatures by reading cross-theater fingerprints.
    #
    # Phase 2 goal: rhetoric trackers write to Redis at
    #     absorption_signature:{intervention_id}
    # with the same schema, classifying each new intervention as offensive
    # vs defensive statecraft and identifying upstream stressors from the
    # shared cross-theater fingerprint dict. Then THIS catalog becomes a
    # fallback only — for historically significant / hand-curated cases.
    #
    # Until Phase 2 ships, expect "no So What block" on:
    #   - New commodities (Modi on copper, etc.)
    #   - New speakers (Putin, Xi, Erdogan, etc.)
    #   - Variants on existing themes (Modi on gold *boost_demand* during
    #     a future RBI reserve accumulation push, etc.)
    # ════════════════════════════════════════════════════════════════════
}


# ============================================================================
# READ PATH — Redis-first with static fallback
# ============================================================================

def _compute_staleness(signature):
    """
    Compute staleness metadata for a signature based on authored_at +
    analytical_validity_days. Mutates and returns the signature dict.

    Adds fields:
      analytical_validity_until: ISO timestamp when analysis expires
      days_since_authored:       int (negative if authored_at is in future)
      days_until_expiry:         int (negative if expired)
      staleness_status:          'fresh' | 'aging' | 'stale' | 'expired'
      staleness_pct:             float 0.0-1.0+ (>1.0 = expired)
      should_render:             False if expired, True otherwise

    Thresholds (relative to analytical_validity_days):
       0–50% → fresh    (no clutter — render BLUF normally)
      50–80% → aging    (subtle "analysis aging" cue)
      80–100% → stale   (visible "may have changed" warning)
      >100% → expired   (analysis hidden by component; signal still rendered)
    """
    if not signature:
        return signature

    validity_days = signature.get('analytical_validity_days', 30)
    authored_at_str = signature.get('authored_at', '')

    try:
        # Tolerant ISO parsing — handles 'Z' suffix and bare datetimes
        s = authored_at_str.replace('Z', '+00:00') if authored_at_str else ''
        authored_dt = datetime.fromisoformat(s) if s else None
        if authored_dt and authored_dt.tzinfo is None:
            authored_dt = authored_dt.replace(tzinfo=timezone.utc)
    except Exception:
        authored_dt = None

    if not authored_dt:
        # No valid authored_at — treat as fresh by default (defensive)
        signature['analytical_validity_until'] = None
        signature['days_since_authored']       = None
        signature['days_until_expiry']         = None
        signature['staleness_status']          = 'fresh'
        signature['staleness_pct']             = 0.0
        signature['should_render']             = True
        return signature

    now = datetime.now(timezone.utc)
    expires_at = authored_dt + timedelta(days=validity_days)
    days_since = (now - authored_dt).total_seconds() / 86400.0
    days_until = (expires_at - now).total_seconds() / 86400.0
    pct = days_since / validity_days if validity_days > 0 else 1.0

    if pct >= 1.0:
        status = 'expired'
        should_render = False
    elif pct >= 0.80:
        status = 'stale'
        should_render = True
    elif pct >= 0.50:
        status = 'aging'
        should_render = True
    else:
        status = 'fresh'
        should_render = True

    signature['analytical_validity_until'] = expires_at.isoformat()
    signature['days_since_authored']       = round(days_since, 1)
    signature['days_until_expiry']         = round(days_until, 1)
    signature['staleness_status']          = status
    signature['staleness_pct']             = round(pct, 3)
    signature['should_render']             = should_render
    return signature


def read_absorption_signature(intervention_id):
    """
    Look up an absorption signature for a leader intervention.

    Lookup order:
        1. Redis at absorption_signature:{intervention_id}   (Phase 2 source)
        2. Static catalog at normalized key                  (Phase 1 source)
        3. None

    Returns the signature dict with staleness metadata appended, or None if
    not found. The signature is returned even when expired — the consumer
    (Web Component) honors `should_render: False` and hides the analysis
    UI without dropping the intervention itself.
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
                    sig = json.loads(result)
                    return _compute_staleness(sig)
        except Exception as e:
            print(f"[Absorption Signatures] Redis read error ({intervention_id}): {str(e)[:120]}")

    # ── Fall back to static catalog ──────────────────────────────────────
    normalized = _normalize_intervention_id(intervention_id)
    static_match = ABSORPTION_SIGNATURES_STATIC.get(normalized)
    if static_match:
        # Shallow copy so we don't mutate the static catalog on read
        sig_copy = {
            **static_match,
            'matched_intervention_id': intervention_id,
            'source_type':             'static_catalog',
        }
        return _compute_staleness(sig_copy)

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

    A3 FIX (May 13, 2026): Added diagnostic logging on the success/failure
    paths so the persisted: false symptom is debuggable from deploy logs
    without re-running the trace by hand.
    """
    if not intervention_id or not signature:
        print(f"[Absorption Signatures] Write skipped: missing intervention_id "
              f"or empty signature")
        return False
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        print(f"[Absorption Signatures] Write skipped for '{intervention_id}': "
              f"Redis env vars not configured on this backend")
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
        if resp.status_code == 200:
            print(f"[Absorption Signatures] ✅ Wrote '{intervention_id}' "
                  f"(TTL {ttl_seconds//3600}h)")
            return True
        else:
            print(f"[Absorption Signatures] ❌ Write failed for '{intervention_id}': "
                  f"HTTP {resp.status_code} — {resp.text[:160]}")
            return False
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

    @app.route('/api/absorption/detect', methods=['POST', 'OPTIONS'])
    def api_absorption_detect():
        """
        Run the absorption detector against caller-supplied upstream fingerprints
        and own_signals. Returns the list of fired signatures (with confidence,
        upstream evidence, and optional persistence).

        This endpoint is consumed by rhetoric trackers on other backends via
        their absorption_proxy_<theater>.py modules — e.g., Asia backend's
        absorption_proxy_asia.py calls this for the India rhetoric tracker.

        Expected JSON body:
            {
                "country":             "india",
                "upstream_fingerprints": {"iran": {...}, "china": {...}, ...},
                "own_signals":         {"modi_gold_jawboning": true, ...},
                "persist":             true        // optional, default false
            }

        Returns:
            {
                "success": true,
                "country": "india",
                "results": [
                    {
                        "signature_id":    "india_gold_suppress_demand",
                        "rule_id":         "india_gold_modi_2026_05",
                        "confidence":      0.85,
                        "upstream_stressors": [...],
                        "cohesion_stress_level": 1,
                        "upstream_evidence": [...],
                        "persisted":       true
                    }
                ],
                "result_count": 1,
                "last_updated": "..."
            }
        """
        if flask_request.method == 'OPTIONS':
            return '', 200

        # Lazy import — detector lives in absorption_detector.py alongside this
        # file on the ME backend. If it's not importable, we surface a clear
        # error rather than crashing the request.
        try:
            from absorption_detector import detect_absorption, detect_and_persist
        except ImportError as e:
            return jsonify({
                'success': False,
                'error':   f'Absorption detector not available on this backend: {e}',
                'results': [],
            }), 503

        body = flask_request.get_json(silent=True) or {}
        country = (body.get('country') or '').lower().strip()
        if not country:
            return jsonify({
                'success': False,
                'error':   "Missing required field 'country' in request body.",
                'results': [],
            }), 400

        upstream_fingerprints = body.get('upstream_fingerprints') or {}
        own_signals           = body.get('own_signals') or {}
        persist               = bool(body.get('persist', False))

        try:
            if persist:
                results = detect_and_persist(
                    country=country,
                    upstream_fingerprints=upstream_fingerprints,
                    own_signals=own_signals,
                )
            else:
                results = detect_absorption(
                    country=country,
                    upstream_fingerprints=upstream_fingerprints,
                    own_signals=own_signals,
                )
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   f'Detector error: {type(e).__name__}: {str(e)[:200]}',
                'results': [],
            }), 500

        return jsonify({
            'success':      True,
            'country':      country,
            'results':      results,
            'result_count': len(results),
            'persisted':    persist,
            'last_updated': datetime.now(timezone.utc).isoformat(),
        })

    print("[Absorption Signatures] ✅ Endpoints registered:")
    print("  GET  /api/absorption-signature/<intervention_id>")
    print("  GET  /api/absorption-signatures")
    print("  POST /api/absorption/detect")
