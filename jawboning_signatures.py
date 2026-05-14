"""
================================================================================
jawboning_signatures.py — Asifah Analytics
================================================================================
JAWBONING SIGNATURES — Phase 3 shared primitive.

Models leader-level rhetorical pressure as a first-class, direction-aware
platform primitive. Where the absorption module answers "is upstream pressure
being absorbed into downstream rhetoric?", this module answers a complementary
question:

  "Is a leader using public rhetoric to move a market, sector, or country's
   behavior — and in which DIRECTION is the pressure flowing?"

TWO DIRECTIONAL MODES — single catalog, dual semantics
--------------------------------------------------------------------------------

  COMMAND jawboning (top-down):
    The leader is CREATING pressure outward. A command-node head-of-state
    publicly pressures a market, sector, foreign government, or company to
    move in a desired direction, without firing the formal policy lever.
    Example: Trump telling US oil companies to lower prices. Trump threatening
    tariffs on Mexico to extract migration concessions. Trump pressuring the
    Fed to lower rates.

    Pressure flow:  LEADER → TARGET
    Cross-theater impact:  HIGH (US command-node rhetoric ripples into Iran,
                                  China, Russia, Mexico, Cuba, Greenland
                                  trackers simultaneously)

  ABSORBER jawboning (bottom-up / inward):
    Upstream pressure is being absorbed by the leader through a domestic ask.
    The leader is MANAGING incoming pressure by redirecting it toward citizens
    or domestic actors. The rhetoric is compensatory, not coercive.
    Example: Modi telling Indian households to buy less gold *because* RBI is
    losing FX reserves *because* of Hormuz pressure on oil imports. Modi's
    austerity rhetoric absorbs upstream economic stress into a domestic ask.

    Pressure flow:  UPSTREAM STRESSOR → LEADER → DOMESTIC COMPENSATION
    Cross-theater impact:  MEDIUM (signals which downstream country is
                                    currently under stress from which
                                    upstream source)

CACHING CONTRACT — Asifah platform principle
--------------------------------------------------------------------------------

  Every endpoint a user can hit serves Redis-cached data on first hit.
  Live computation is the fallback path, not the default. Users never wait
  for a fresh scan unless they explicitly opt in.

  This module follows the contract in three ways:

  1. CATALOG HYDRATION:  At module load, the full catalog is written to
                          Redis (full blob + per-entry keys). First production
                          deploy populates the cache automatically.

  2. CATALOG READS:       read_jawboning_signature() and list_jawboning_signatures()
                          ALWAYS check Redis first, fall back to the in-memory
                          static catalog only on cache miss (e.g., fresh Redis
                          instance, or expired TTL).

  3. FINGERPRINT WRITES:  Detector module writes 'jawboning:{dir}:{country}:
                          {target}' keys with 24h TTL. Cross-theater readers
                          (Iran, China, Cuba, Russia trackers) read these
                          directly — no detector roundtrip needed.

ARCHITECTURE
--------------------------------------------------------------------------------

  Phase 1 (today):     Static nested catalog (JAWBONING_SIGNATURES_STATIC)
                       hand-curated. 13 entries at launch:
                         - 11 Trump command signatures (4 domestic, 6 foreign-
                           policy, 1 strategic partner)
                         - 2 Modi absorber signatures (migrated from inline
                           computation in rhetoric_tracker_india.py)

  Phase 2 (detection): jawboning_detector.py reads this catalog, applies the
                       trigger-keyword matching against per-leader actor
                       rhetoric, and writes Redis fingerprints.

  Phase 3 (cross-     Iran, China, Russia, Cuba, Greenland, Mexico (future),
   theater reads):    Saudi (future) trackers read the relevant Trump command
                      fingerprints and amplify their own actor scores.

  Phase 4 (Black      Black Swan module consumes ALL jawboning fingerprints
   Swan inputs):      as Origin-axis upstream-signal inputs.

USAGE
--------------------------------------------------------------------------------

  Read a single signature (Redis-first, static fallback):
    from jawboning_signatures import read_jawboning_signature
    sig = read_jawboning_signature('trump_on_iran')

  List signatures by leader / country / direction:
    from jawboning_signatures import (
        get_signatures_by_leader,
        get_signatures_by_country,
        get_signatures_by_direction,
    )

  Endpoints:
    GET /api/jawboning/signatures              → full catalog (Redis-cached)
    GET /api/jawboning/signatures/<sig_id>     → single entry (Redis-cached)
    GET /api/jawboning/signatures?leader=trump → filtered by leader

  Register in app.py:
    from jawboning_signatures import register_jawboning_signatures_endpoints
    register_jawboning_signatures_endpoints(app)

v1.0.0 — May 14 2026 · Path B Architectural Primitive
================================================================================
"""

import os
import json
import requests
from datetime import datetime, timezone


# ============================================================================
# REDIS CONFIG  (mirrors absorption_signatures.py pattern)
# ============================================================================

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_REST_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')

# Catalog itself is static and rarely changes; cached at long TTL.
JAWBONING_CATALOG_TTL_HOURS = 168   # 7 days — catalog rarely changes

# Fingerprint TTL — how long a "Trump is currently jawboning X" flag stays TRUE
# in Redis after detection. 24h means a single afternoon of rhetoric persists
# through the next news cycle for cross-theater consumers to read.
JAWBONING_FINGERPRINT_TTL_HOURS = 24


# ============================================================================
# REDIS KEY HELPERS
# ============================================================================

def _catalog_redis_key_single(signature_id):
    """Redis key for a single catalog entry."""
    return f"jawboning_catalog:single:{signature_id}"


def _catalog_redis_key_full():
    """Redis key for the full catalog blob (used by list endpoint)."""
    return "jawboning_catalog:full"


def _fingerprint_redis_key(direction, country_id, target_key):
    """
    Canonical Redis key for an active jawboning fingerprint.

    Examples:
      jawboning:command:us:on_iran
      jawboning:command:us:on_oil
      jawboning:absorber:india:on_gold
      jawboning:absorber:india:on_austerity

    Cross-theater consumers (Iran tracker, China tracker, etc.) read these
    keys to know whether they're currently being jawboned. Written by
    jawboning_detector.py, read by every tracker.
    """
    return f"jawboning:{direction}:{country_id}:{target_key}"


# ============================================================================
# REDIS I/O — defensive, never crashes the caller on a Redis hiccup
# ============================================================================

def _redis_get(key):
    """GET a key from Upstash Redis REST. Returns parsed JSON or None on miss/error."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        r = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        result = r.json().get('result')
        if result is None:
            return None
        # Upstash returns JSON-stringified values; parse defensively
        try:
            return json.loads(result)
        except (TypeError, ValueError):
            return result
    except Exception as e:
        print(f"[Jawboning Signatures] Redis GET error for {key}: {e}")
        return None


def _redis_set(key, value, ttl_seconds=None):
    """SET a key in Upstash Redis REST with optional TTL. Silent on failure."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value) if not isinstance(value, str) else value
        url = f"{UPSTASH_REDIS_URL}/set/{key}"
        if ttl_seconds:
            url += f"?EX={ttl_seconds}"
        r = requests.post(
            url,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            data=payload,
            timeout=5,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[Jawboning Signatures] Redis SET error for {key}: {e}")
        return False


# ============================================================================
# THE STATIC CATALOG — nested by direction
# ============================================================================
#
# Per-entry schema (every entry has all of these fields):
#   leader_id              str   — canonical leader identifier
#   country_id             str   — ISO-style country code (us, india, etc.)
#   direction              str   — 'command' or 'absorber' (mirrors parent key)
#   target_sector          str   — short label for the thing being jawboned
#   target_key             str   — short snake_case key used in the Redis
#                                  fingerprint (jawboning:{dir}:{country}:{target_key})
#   target_actors          list  — who/what receives the pressure (command) OR
#                                  who/what absorbs the pressure (absorber)
#   trigger_keywords       list  — English phrases that signal the rhetoric
#   trigger_keywords_native list — same in non-English where relevant
#   mechanism              str   — the causal channel
#   upstream_stressors     list  — (absorber only) what's driving the absorber
#                                  to speak this way; empty list for command
#   cross_theater_writes   list  — Redis fingerprint keys this signature writes
#   pattern_basis          str   — 'analyst_curated' | 'auto_learned'
#   confidence             str   — 'high' | 'medium' | 'speculative'
#   historical_anchors     list  — known real-world events matching this pattern
#   analyst_summary_template str — diplomat-grade prose, plain language
#                                  (may interpolate {forward_indicators_joined})
#   forward_indicators     list  — what to watch for if this signature fires
# ============================================================================

JAWBONING_SIGNATURES_STATIC = {
    'command':  {},   # Filled in Chunk 1B — 11 Trump entries
    'absorber': {},   # Filled in Chunk 1C — 2 Modi entries (migrated)
}
