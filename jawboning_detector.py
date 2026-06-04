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

# ============================================================================
# 🚧 SECURITY TODO — INTERNAL-AUTH RETROFIT (deferred from Phase 2C)
# ============================================================================
#
# STATUS:    Open. Defer until Phase 3 (Asia proxy build) at the latest.
# RAISED:    May 15, 2026 — Phase 2C build session
# OWNER:     Rachel (architectural decision) + Claude (implementation)
#
# WHAT'S MISSING:
#   /api/jawboning/detect (POST and GET) currently has NO authentication.
#   Any internet caller who knows the URL can trigger Redis fingerprint
#   writes that cross-theater trackers will react to. Same gap exists on
#   absorption_detector.py's /api/absorption/detect endpoint.
#
# WHY DEFERRED:
#   1. Phase 2E smoke testing is easier from a browser without auth.
#   2. No non-browser callers exist yet — Asia/WHA proxies don't exist.
#   3. Current threat surface is low — platform is not publicly known.
#
# WHAT THE RETROFIT MUST INCLUDE (do BOTH together, not piecemeal):
#
#   A. THIS FILE (jawboning_detector.py)
#      - Add @require_internal_auth decorator helper (top-of-file)
#      - Apply to: POST /api/jawboning/detect
#      - Apply to: GET  /api/jawboning/detect
#      - LEAVE PUBLIC: /api/jawboning/active, /api/jawboning/active/<country>
#        (read-only diagnostics, no side effects)
#      - LEAVE PUBLIC: all /api/jawboning/signatures/* endpoints (already
#        public in jawboning_signatures.py, no change there)
#
#   B. absorption_detector.py — SAME RETROFIT
#      - Add @require_internal_auth decorator (identical implementation)
#      - Apply to: /api/absorption/detect
#      - LEAVE PUBLIC: any read-only diagnostic endpoints
#
#   C. ENVIRONMENT VARIABLES (set on EVERY backend that talks to ME)
#      - Env var name:  ASIFAH_INTERNAL_TOKEN
#      - Generate:      `python -c "import secrets; print(secrets.token_urlsafe(32))"`
#                       or use a password manager. ~32+ random chars.
#      - Set in Render dashboards for:
#          * asifah-backend          (ME — validates incoming)
#          * asifah-asia-backend     (Asia — calls ME via proxy)
#          * asifah-wha-backend      (WHA — calls ME via proxy)
#          * asifa-europe-backend    (Europe — future caller)
#          * asifah-cave-backend     (CAVE — future caller, when Peter builds)
#      - SAME VALUE in every backend (it's a shared secret, not per-service).
#
#   D. PROXY FILES (Phase 3+) — must include header
#      - jawboning_proxy_asia.py, jawboning_proxy_wha.py, future CAVE caller
#      - HTTP requests must include:
#          headers={'Authorization': f'Bearer {os.environ["ASIFAH_INTERNAL_TOKEN"]}'}
#
#   E. DECORATOR BEHAVIOR (when implemented)
#      - Read `Authorization: Bearer <token>` from request headers
#      - Compare against ASIFAH_INTERNAL_TOKEN env var (constant-time compare
#        via `hmac.compare_digest` to avoid timing attacks)
#      - 401 Unauthorized if missing/wrong token
#      - 503 Service Unavailable if env var not set on server (fail-secure)
#      - Log auth failures (with caller IP) but NEVER log the attempted token
#
#   F. SMOKE TEST PROCEDURE (post-retrofit)
#      - From browser: GET /api/jawboning/detect should return 401
#      - From curl with valid Bearer token: should return 200 + payload
#      - From curl with WRONG Bearer token: should return 401
#      - From Asia proxy (Phase 3+): should work transparently via env var
#
# ESTIMATED RETROFIT EFFORT:
#   ~60 lines of code across two files (decorator + applications + tests).
#   ~5 minutes of env-var setup across 3-4 Render backends.
#   Single session, lowest-risk if done as the FIRST task of Phase 3 before
#   any proxy code is written.
#
# ============================================================================

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
# DETECTION HELPERS — byte-for-byte mirror of rhetoric_tracker_india.py
# ============================================================================
#
# CRITICAL: These two helpers must produce IDENTICAL output to the inline
# versions currently in rhetoric_tracker_india.py lines 1238-1250. Phase 3's
# strangler-fig migration depends on byte-for-byte output parity. Any
# divergence here causes [Jawboning Compare] ❌ lines in Render logs and
# blocks the Modi cutover.
#
# If you ever need to "improve" these helpers, you must:
#   1. Update BOTH the inline version in rhetoric_tracker_india.py AND here
#   2. Run a full dual-track scan cycle to verify outputs still match
#   3. Only THEN deploy the change
# Or: cut over Modi to primitive-only first, THEN make the change in one
# place. After the Phase 3 cutover, the inline version goes away entirely.
# ============================================================================

def _has_phrase(actor_result, phrases):
    """
    Did this actor's matched_triggers list mention any of these phrases?

    Mirror of rhetoric_tracker_india.py inline helper. Case-insensitive
    substring match against the joined triggers string.

    Args:
        actor_result: dict — single actor's scan output. Expected to contain
                      'matched_triggers' (list of strings). Defensive against
                      None and missing keys.
        phrases: list of strings — phrases to search for. Lowercased per phrase.

    Returns:
        bool — True if ANY phrase appears as substring in joined triggers.
    """
    triggers = actor_result.get('matched_triggers', []) or []
    joined   = ' '.join(triggers).lower()
    return any(p.lower() in joined for p in phrases)


def _articles_mention(actor_result, phrases):
    """
    Did this actor's top_articles list mention any of these phrases?

    Mirror of rhetoric_tracker_india.py inline helper. Checks title + trigger
    fields of each article, case-insensitive substring match.

    Args:
        actor_result: dict — single actor's scan output. Expected to contain
                      'top_articles' (list of article dicts with 'title' +
                      'trigger' keys). Defensive against None / missing keys.
        phrases: list of strings — phrases to search for.

    Returns:
        bool — True if ANY phrase appears as substring in ANY article's
        title or trigger fields. Returns on first match.
    """
    for art in actor_result.get('top_articles', []) or []:
        t = (art.get('title') or '').lower() + ' ' + (art.get('trigger') or '').lower()
        for p in phrases:
            if p.lower() in t:
                return True
    return False


# ============================================================================
# ACTOR GATE EVALUATOR
# ============================================================================
#
# Each catalog signature declares an 'actor_gate' dict mapping actor_cluster_id
# to minimum_level (e.g., {'pmo': 2} or {'executive_branch': 2}). For the
# signature to be eligible to fire, EVERY listed cluster must meet its level
# threshold in the caller's actor_results.
#
# If actor_results is missing a gated cluster entirely, the gate fails
# (returns False). Treating "missing cluster" as "level 0" is the canonical
# behavior — never speculate about what a tracker didn't measure.
# ============================================================================

def _evaluate_actor_gate(actor_gate, actor_results):
    """
    Check whether all required actor clusters meet their level thresholds.

    Args:
        actor_gate:     dict — {actor_cluster_id: minimum_level, ...}
                        Empty dict ({}) means no gating — signature always
                        eligible. None is treated as empty dict.
        actor_results:  dict — {actor_cluster_id: {'level': int, ...}, ...}
                        The per-actor output from the tracker's scan.

    Returns:
        bool — True if ALL gates pass. False if any cluster is below
        threshold or missing entirely.
    """
    if not actor_gate:
        return True  # No gate = always eligible
    if not isinstance(actor_results, dict):
        return False  # Defensive: no actor data → no signature fires

    for cluster_id, min_level in actor_gate.items():
        cluster = actor_results.get(cluster_id) or {}
        # ── FIELD NAME COMPATIBILITY (May 16, 2026) ───────────────────────
        # Different trackers use different field names for the 0-4 band:
        #   - ME family (Iran, Lebanon, Israel, etc.) uses 'level'
        #   - WHA US tracker uses 'tier'
        #   - Asia trackers may use either depending on age
        # The detector accepts whichever is present, with 'level' winning
        # if both are set (canonical). Falls back to 0 if neither exists.
        actual_level = cluster.get('level',
                       cluster.get('tier', 0))
        if actual_level < min_level:
            print(f"[Jawboning Detector] gate FAIL for cluster '{cluster_id}': "
                  f"actual_level={actual_level} < required={min_level}")
            return False
    return True

# ============================================================================
# THE PUBLIC API — detect_jawboning()
# ============================================================================
#
# Called once per scan cycle, per leader, by every theater tracker. Returns
# a dict of signature_id → bool indicating which signatures fired this scan.
#
# For each signature in the catalog matching the given leader_id:
#   1. Apply actor_gate — does the tracker have the required clusters active?
#   2. If gate passes, check trigger_keywords + trigger_keywords_native via
#      _has_phrase against the matched_triggers of any gated cluster
#   3. ALSO check via _articles_mention against the top_articles of any
#      gated cluster
#   4. If EITHER check fires → signature is True
#   5. On True, write the Redis fingerprint with envelope metadata
#
# The (_has_phrase OR _articles_mention) two-check pattern is canonical from
# rhetoric_tracker_india.py — both checks operate against the gated cluster
# specifically, NOT against arbitrary actor data. This is what makes Modi
# signatures specifically check PMO and Trump signatures specifically check
# executive_branch.
# ============================================================================

def detect_jawboning(leader_id,
                     country_id,
                     actor_results,
                     articles=None,
                     write_fingerprints=True,
                     scan_id=None):
    """
    Detect all jawboning signatures for a given leader against current
    actor_results. Returns a flat dict mapping signature_id → bool.

    Args:
        leader_id: str — 'trump', 'modi', etc. Used to filter the catalog
                   so a single tracker scan only evaluates relevant signatures.
        country_id: str — the originating country code ('us', 'india'). Used
                    for Redis fingerprint key construction and as a sanity
                    check against the catalog entry's country_id.
        actor_results: dict — per-actor scan output from the tracker. Each
                       cluster value should have 'level', 'matched_triggers',
                       and 'top_articles' keys (graceful degradation if any
                       are missing).
        articles: list — OPTIONAL. Currently unused; reserved for future
                  enrichment where signature triggers might scan all articles
                  rather than only top_articles per gated cluster. Pass it
                  through; the detector ignores it for v1.
        write_fingerprints: bool — if True (default), positive detections
                            write Redis fingerprints with 24h TTL. Set to
                            False for dry-run / comparison-mode (used in
                            Phase 3 strangler-fig logging).
        scan_id: str — OPTIONAL diagnostic identifier (e.g., scan timestamp)
                 written into fingerprint metadata. Useful for debugging
                 which scan cycle generated a given fingerprint.

    Returns:
        dict — {signature_id: bool, ...} for every signature in the catalog
        matching this leader_id. Signatures that don't match the leader are
        NOT included in the return dict (not "False" — absent).

    Examples:
        >>> detect_jawboning('modi', 'india', actor_results)
        {'modi_on_gold': True, 'modi_on_austerity': False}

        >>> detect_jawboning('trump', 'us', actor_results, write_fingerprints=False)
        {'trump_on_oil': True, 'trump_on_iran': True, 'trump_on_fed': False, ...}
    """
    results = {}
    fingerprints_written = []

    # Defensive: empty/None actor_results → nothing can fire, return empty
    if not isinstance(actor_results, dict):
        print(f"[Jawboning Detector] {leader_id} scan called with invalid actor_results "
              f"(type={type(actor_results).__name__}) — returning empty dict")
        return results

    # Pull the catalog via the Redis-first reader (caching contract honored)
    try:
        catalog = list_jawboning_signatures()
    except Exception as e:
        print(f"[Jawboning Detector] Failed to load catalog: {e} — returning empty dict")
        return results

    # Walk EVERY directional bucket the catalog defines (command, absorber,
    # mediator, and any future class). A leader could in principle have
    # signatures in more than one bucket; we don't hardcode the set so new
    # pressure modes work the moment they're added to the catalog.
    for direction in catalog:
        signatures = catalog.get(direction, {}) or {}
        for sig_id, sig in signatures.items():
            # Filter by leader_id — only evaluate signatures for this leader
            if sig.get('leader_id') != leader_id:
                continue

            # Sanity check: country_id should match (drop with a warning if not)
            if sig.get('country_id') != country_id:
                print(f"[Jawboning Detector] ⚠️ Signature {sig_id} has country_id="
                      f"{sig.get('country_id')!r} but called with country_id={country_id!r}"
                      f" — skipping")
                continue

            # Step 1: Apply the actor gate
            actor_gate = sig.get('actor_gate') or {}
            if not _evaluate_actor_gate(actor_gate, actor_results):
                results[sig_id] = False
                continue  # Gate failed — signature cannot fire

            # Step 2 + 3: Evaluate trigger phrases against EACH gated cluster's
            # matched_triggers AND top_articles. The signature fires if ANY
            # gated cluster matches via EITHER check.
            #
            # Catalog has trigger_keywords (English) + trigger_keywords_native
            # (other languages). Merge both for evaluation — _has_phrase and
            # _articles_mention both lowercase-substring-match, which works
            # across scripts (Devanagari, Arabic, Chinese, etc.) without
            # special casing.
            all_phrases = (sig.get('trigger_keywords') or []) + \
                          (sig.get('trigger_keywords_native') or [])

            if not all_phrases:
                # No triggers defined → signature is dormant. Catalog
                # consistency issue worth flagging in logs but not crashing.
                print(f"[Jawboning Detector] ⚠️ Signature {sig_id} has empty "
                      f"trigger_keywords — treating as dormant (always False)")
                results[sig_id] = False
                continue

            fired = False
            # When actor_gate is empty (e.g., all Trump signatures by convention),
            # check ALL clusters in actor_results — "no gate" means "any US cluster
            # mentioning these phrases counts." Without this fallback, gateless
            # signatures could never fire because actor_gate.keys() iterates zero
            # times. (Fix discovered May 17, 2026 — silent failure on all 11 Trump
            # signatures since deployment.)
            clusters_to_check = list(actor_gate.keys()) if actor_gate else list(actor_results.keys())
            for cluster_id in clusters_to_check:
                cluster = actor_results.get(cluster_id) or {}
                if _has_phrase(cluster, all_phrases) or \
                   _articles_mention(cluster, all_phrases):
                    fired = True
                    break  # One matching cluster is sufficient

            results[sig_id] = fired

            # Step 4: Write fingerprint on positive detection
            if fired and write_fingerprints:
                metadata = {
                    'leader_id':      leader_id,
                    'confidence':     sig.get('confidence'),
                    'target_sector':  sig.get('target_sector'),
                    'pattern_basis':  sig.get('pattern_basis'),
                }
                if scan_id:
                    metadata['scan_id'] = scan_id

                success = write_fingerprint(
                    direction    = direction,
                    country_id   = country_id,
                    target_key   = sig.get('target_key'),
                    signature_id = sig_id,
                    metadata     = metadata,
                )
                if success:
                    fingerprints_written.append(
                        _fingerprint_redis_key(direction, country_id, sig.get('target_key'))
                    )

    # Diagnostic summary log
    fired_ids = [k for k, v in results.items() if v]
    if fired_ids:
        print(f"[Jawboning Detector] {leader_id}/{country_id} scan: "
              f"{len(fired_ids)}/{len(results)} signatures fired → {fired_ids}")
        if fingerprints_written:
            print(f"[Jawboning Detector]   Fingerprints written: {fingerprints_written}")
    else:
        print(f"[Jawboning Detector] {leader_id}/{country_id} scan: "
              f"0/{len(results)} signatures fired")

    return results


# ============================================================================
# ENDPOINT REGISTRATION
# ============================================================================
#
# Called from app.py at startup:
#     from jawboning_detector import register_jawboning_detector_endpoints
#     register_jawboning_detector_endpoints(app)
#
# Endpoints registered:
#   POST /api/jawboning/detect            — primary write-path (theater proxies)
#   GET  /api/jawboning/detect            — same logic, query-string params (smoke testing)
#   GET  /api/jawboning/active            — list all active fingerprints
#   GET  /api/jawboning/active/<country>  — filter active fingerprints by country
#
# SECURITY: see SECURITY TODO at top of file. None of these currently require
# authentication; the /detect endpoints will be gated by @require_internal_auth
# during Phase 3 retrofit.
# ============================================================================

def register_jawboning_detector_endpoints(app):
    """
    Register the jawboning detector endpoints on the Flask app.

    Idempotent in spirit but Flask will raise if called twice with the same
    routes on the same app instance — caller's responsibility to register
    exactly once per process.
    """
    from flask import request as flask_request, jsonify

    # ------------------------------------------------------------------------
    # /api/jawboning/detect — primary write-path
    # ------------------------------------------------------------------------
    @app.route('/api/jawboning/detect', methods=['POST', 'GET', 'OPTIONS'])
    def api_jawboning_detect():
        """
        Run the jawboning detector for a given leader + country + actor_results
        snapshot. Returns the per-signature fired/not-fired dict and (on
        positive detections, when write_fingerprints is true) writes Redis
        fingerprints with 24h TTL.

        POST body (JSON):
            {
                "leader_id":          "modi" | "trump" | ...,
                "country_id":         "india" | "us" | ...,
                "actor_results":      { "<cluster_id>": {level, matched_triggers, top_articles}, ... },
                "articles":           [...]            # optional, reserved for future
                "write_fingerprints": true,            # optional, default true
                "scan_id":            "..."            # optional diagnostic
            }

        GET query string (smoke testing — limited; no actor_results passed,
        so signature evaluation will be vacuous and nothing fires. Useful
        for "is this endpoint alive?" checks and as a stub for Phase 3
        when proxies start posting actual payloads):
            ?leader_id=modi&country_id=india&dry_run=true

        Returns (200 on success):
            {
                "success":              true,
                "leader_id":            "modi",
                "country_id":           "india",
                "results":              {"modi_on_gold": true, "modi_on_austerity": false},
                "fired_count":          1,
                "evaluated_count":      2,
                "wrote_fingerprints":   true | false,
                "served_at":            "<iso8601>"
            }

        Returns 400 on missing required fields, 500 on internal error.
        """
        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            # ---- Parse payload (POST body OR GET query string) ----
            if flask_request.method == 'POST':
                payload = flask_request.get_json(silent=True) or {}
                leader_id     = payload.get('leader_id')
                country_id    = payload.get('country_id')
                actor_results = payload.get('actor_results')
                articles      = payload.get('articles')
                scan_id       = payload.get('scan_id')
                # POST default: write fingerprints UNLESS caller opts out
                write_fingerprints = payload.get('write_fingerprints', True)
            else:  # GET
                leader_id     = flask_request.args.get('leader_id')
                country_id    = flask_request.args.get('country_id')
                actor_results = None  # GET doesn't pass complex actor_results
                articles      = None
                scan_id       = flask_request.args.get('scan_id')
                # GET default: NEVER write (browser smoke testing)
                # Override only if explicit ?dry_run=false AND ?force_write=true
                dry_run = flask_request.args.get('dry_run', 'true').lower() in ('true', '1', 'yes')
                force_write = flask_request.args.get('force_write', '').lower() in ('true', '1', 'yes')
                write_fingerprints = (not dry_run) and force_write

            # ---- Validate required fields ----
            if not leader_id or not country_id:
                return jsonify({
                    'success': False,
                    'error':   'leader_id and country_id are required',
                }), 400

            # ---- Run detection ----
            results = detect_jawboning(
                leader_id          = leader_id,
                country_id         = country_id,
                actor_results      = actor_results,
                articles           = articles,
                write_fingerprints = write_fingerprints,
                scan_id            = scan_id,
            )

            fired_count = sum(1 for v in results.values() if v)

            return jsonify({
                'success':            True,
                'leader_id':          leader_id,
                'country_id':         country_id,
                'results':            results,
                'fired_count':        fired_count,
                'evaluated_count':    len(results),
                'wrote_fingerprints': write_fingerprints,
                'served_at':          datetime.now(timezone.utc).isoformat(),
                'method':             flask_request.method,
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   f'{type(e).__name__}: {str(e)[:200]}',
            }), 500

    # ------------------------------------------------------------------------
    # /api/jawboning/active — list all currently-active fingerprints
    # ------------------------------------------------------------------------
    @app.route('/api/jawboning/active', methods=['GET', 'OPTIONS'])
    def api_jawboning_active_all():
        """
        Return all jawboning fingerprints currently active in Redis (within
        their 24h TTL window). Read-only diagnostic; safe to expose.

        Optional query params:
            ?direction=command|absorber  — filter by direction
        """
        if flask_request.method == 'OPTIONS':
            return '', 200
        try:
            direction = flask_request.args.get('direction')
            if direction and direction not in ('command', 'absorber'):
                return jsonify({
                    'success': False,
                    'error':   "direction must be 'command' or 'absorber'",
                }), 400
            active = list_active_fingerprints(direction=direction)
            return jsonify({
                'success':   True,
                'count':     len(active),
                'active':    active,
                'served_at': datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   f'{type(e).__name__}: {str(e)[:200]}',
            }), 500

    # ------------------------------------------------------------------------
    # /api/jawboning/active/<country_id> — filtered by country
    # ------------------------------------------------------------------------
    @app.route('/api/jawboning/active/<country_id>', methods=['GET', 'OPTIONS'])
    def api_jawboning_active_country(country_id):
        """
        Return active jawboning fingerprints originating in a given country.
        Useful for cross-theater readers asking "what is the US currently
        jawboning?" — they call /api/jawboning/active/us and get the list.
        """
        if flask_request.method == 'OPTIONS':
            return '', 200
        try:
            active = list_active_fingerprints(country_id=country_id)
            return jsonify({
                'success':    True,
                'country_id': country_id,
                'count':      len(active),
                'active':     active,
                'served_at':  datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   f'{type(e).__name__}: {str(e)[:200]}',
            }), 500

    # ------------------------------------------------------------------------
    # Logging on registration (mirrors signatures module style)
    # ------------------------------------------------------------------------
    print("[Jawboning Detector] ✅ Endpoints registered:")
    print("[Jawboning Detector]   POST /api/jawboning/detect")
    print("[Jawboning Detector]   GET  /api/jawboning/detect           (smoke-test, dry-run by default)")
    print("[Jawboning Detector]   GET  /api/jawboning/active")
    print("[Jawboning Detector]   GET  /api/jawboning/active/<country_id>")
    print("[Jawboning Detector]   ⚠️  Auth retrofit pending — see SECURITY TODO at top of file")
