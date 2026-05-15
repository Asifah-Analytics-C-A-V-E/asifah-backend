"""
================================================================================
jawboning_detector.py — Asifah Analytics
================================================================================
JAWBONING DETECTOR — Phase 2 shared primitive (companion to jawboning_signatures.py)

The behavior side of the jawboning primitive. While jawboning_signatures.py
declares WHAT we're looking for (catalog of 13 signatures), this module
detects WHETHER any of them are firing for a given leader + actor-results
snapshot, and writes the resulting fingerprints to Redis for cross-theater
consumers to read.

THE CONTRACT
--------------------------------------------------------------------------------

  detect_jawboning(
      leader_id,            # str — 'trump', 'modi', etc.
      country_id,           # str — 'us', 'india', etc.
      actor_results,        # dict — per-actor scan output from the tracker
                            #         (must include 'level' + 'matched_triggers'
                            #          + 'top_articles' fields per actor)
      articles=None,        # list — optional fallback if actor_results is thin
      write_fingerprints=True,  # bool — write Redis keys on positive detection
  ) → {
      'modi_on_gold':      True,
      'modi_on_austerity': False,
  }

  Or for Trump:
  detect_jawboning('trump', 'us', actor_results) → {
      'trump_on_oil':            True,
      'trump_on_iran':           True,
      'trump_on_fed':            False,
      ...
  }

  Fingerprints written (on positive detection only, 24h TTL):
      jawboning:absorber:india:on_gold       → TRUE
      jawboning:command:us:on_iran           → TRUE
      jawboning:command:us:on_oil            → TRUE
      ...

  Cross-theater consumers read these keys directly — no detector round-trip
  required from those callers. The detector is called once per scan cycle
  on the tracker's home backend (via local function call on ME, or via the
  jawboning_proxy_{theater}.py HTTP bridge from Asia/WHA backends).

WHY THIS LIVES ON ME BACKEND
--------------------------------------------------------------------------------

  Single source of truth for jawboning detection logic. Iran/Israel/Lebanon/
  Yemen rhetoric trackers (all ME-local) call detect_jawboning() directly.
  Asia (Modi-India) and WHA (Trump-US) trackers proxy in via HTTP. Same code,
  same catalog, one place to update.

  Mirror of how absorption_detector.py works — see Phase 2 ABSORPTION rollout
  for the architecture precedent.

CACHING CONTRACT (PER PLATFORM PRINCIPLE)
--------------------------------------------------------------------------------

  Detection itself is NOT cached — every scan cycle computes fresh flags from
  fresh actor_results. That's correct: this primitive is the COMPUTE side of
  the jawboning data flow.

  However, fingerprint WRITES are cached in Redis at 24h TTL. Cross-theater
  consumers (Iran tracker reading "is Trump jawboning Iran right now?") hit
  Redis directly via _redis_get on the fingerprint key. That IS the cache.
  Consumers do NOT call detect_jawboning() — they read its persisted side-
  effects.

GRACEFUL DEGRADATION
--------------------------------------------------------------------------------

  Defensive everywhere:
    - actor_results missing a gated cluster → signature can't fire, returns False
    - Redis unreachable → fingerprint writes log a warning but don't crash
    - Catalog read fails → falls back to static catalog via Redis-first reader
    - Trigger keyword list is empty → signature is dormant (won't fire), no error
    - Caller passes None for actor_results → returns empty dict, no crash

  Philosophy: the detector NEVER crashes a tracker's scan cycle. Worst case,
  it returns an empty dict and the tracker proceeds normally.

v1.0.0 — May 15 2026 · Path B Architectural Primitive
================================================================================
"""

import os
import json
import requests
from datetime import datetime, timezone

# Import the catalog reader from the signatures module (Redis-first per
# the platform caching contract — list_jawboning_signatures() handles fallback).
from jawboning_signatures import (
    list_jawboning_signatures,
    _fingerprint_redis_key,
    JAWBONING_FINGERPRINT_TTL_HOURS,
)


# ============================================================================
# REDIS CONFIG  (mirrors jawboning_signatures.py pattern)
# ============================================================================

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_REST_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')


# ============================================================================
# REDIS I/O — defensive, never crashes the caller on a Redis hiccup
# ============================================================================
#
# These are local copies (intentional) of the helpers in jawboning_signatures.
# Duplication is preferable to a cross-module dependency for these tiny
# functions — keeps the detector's blast radius contained if signatures.py
# is ever refactored.
# ============================================================================

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
        print(f"[Jawboning Detector] Redis SET error for {key}: {e}")
        return False


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
        try:
            return json.loads(result)
        except (TypeError, ValueError):
            return result
    except Exception as e:
        print(f"[Jawboning Detector] Redis GET error for {key}: {e}")
        return None


# ============================================================================
# FINGERPRINT WRITER — the cross-theater contract
# ============================================================================
#
# Cross-theater consumers (Iran tracker, China tracker, etc.) read these
# keys directly via _redis_get on jawboning:{direction}:{country}:{target_key}.
# 24h TTL means a single afternoon of rhetoric persists through the next
# news cycle.
#
# Returns a list of fingerprint key strings that were successfully written,
# for logging / debugging visibility on what fired during a scan.
# ============================================================================

def write_fingerprint(direction, country_id, target_key, signature_id, metadata=None):
    """
    Write a single jawboning fingerprint to Redis.

    Args:
      direction:    'command' or 'absorber'
      country_id:   originating country (us, india, etc.)
      target_key:   the on_X key from the catalog entry (on_iran, on_gold, etc.)
      signature_id: the full catalog signature id, stored as metadata payload
      metadata:     optional dict — additional context written into the value

    The Redis VALUE is a small JSON envelope so consumers can read context
    (which signature, when written, what scan triggered it) instead of just
    a bare TRUE flag. Backwards-compatible: consumers that only check
    "does this key exist?" still work.

    Returns:
      True if the write succeeded, False otherwise.
    """
    key = _fingerprint_redis_key(direction, country_id, target_key)
    ttl = JAWBONING_FINGERPRINT_TTL_HOURS * 3600
    envelope = {
        'fired':          True,
        'signature_id':   signature_id,
        'direction':      direction,
        'country_id':     country_id,
        'target_key':     target_key,
        'written_at':     datetime.now(timezone.utc).isoformat(),
        'metadata':       metadata or {},
    }
    return _redis_set(key, envelope, ttl)


def read_fingerprint(direction, country_id, target_key):
    """
    Read a single jawboning fingerprint. Returns the envelope dict if active,
    None if expired or never set.

    This is the function cross-theater readers will call:
        from jawboning_detector import read_fingerprint
        active = read_fingerprint('command', 'us', 'on_iran')
        if active:
            # Iran tracker amplifies IRGC + foreign-policy actor scores
            ...
    """
    key = _fingerprint_redis_key(direction, country_id, target_key)
    return _redis_get(key)


# ============================================================================
# DIAGNOSTIC HELPERS
# ============================================================================

def list_active_fingerprints(country_id=None, direction=None):
    """
    Diagnostic: scan all known fingerprint keys for active ones.

    Note: Upstash REST doesn't expose KEYS *, so we iterate over the catalog
    (which we DO know all the keys for) and check each one. O(13) — fine.

    Used by /api/jawboning/active endpoint for dashboards + debugging.
    """
    catalog = list_jawboning_signatures()
    active = []
    for cat_direction, sigs in catalog.items():
        if direction and cat_direction != direction:
            continue
        for sig_id, sig in sigs.items():
            if country_id and sig.get('country_id') != country_id:
                continue
            fp = read_fingerprint(
                cat_direction,
                sig.get('country_id'),
                sig.get('target_key'),
            )
            if fp:
                active.append({
                    'signature_id':  sig_id,
                    'direction':     cat_direction,
                    'country_id':    sig.get('country_id'),
                    'target_key':    sig.get('target_key'),
                    'envelope':      fp,
                })
    return active


# ============================================================================
# NEXT: detect_jawboning() — Chunk 2B
# ============================================================================
#
# Chunk 2B will add the core detect_jawboning() function plus its two private
# helpers (_has_phrase, _articles_mention) and the actor_gate evaluator. That
# function is the byte-for-byte mirror of the inline logic currently in
# rhetoric_tracker_india.py — and the same function, called with leader_id=
# 'trump', will detect Trump signatures using the same catalog-driven logic.
#
# Chunk 2C will add the /api/jawboning/detect endpoint that Asia + WHA
# proxies will call.
# ============================================================================
