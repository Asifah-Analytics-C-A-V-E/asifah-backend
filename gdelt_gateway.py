"""
Asifah Analytics -- GDELT Gateway
v2.4.0 -- October 18 2026  |  portable, drop into any backend (same file everywhere)

═══════════════════════════════════════════════════════════════════════
WHY v2.4.0 EXISTS -- A REGRESSION, THEN THREE THINGS NOBODY KNEW
═══════════════════════════════════════════════════════════════════════
1. THE REGRESSION. v2.0 -> v2.3.1 shipped Sept 19-21 (proper breaker,
   throttle memory, two-layer cache with an Upstash L2, call budget on its
   own clock, spend_by_label, env tunables, 429-not-retried) and was
   confirmed live Sept 27. On Oct 4 a Hungary fix was written against a
   copy of the OLD v1.0 file, numbered "v1.1.0", and deployed to all five
   backends -- overwriting v2.3.1. The version number went DOWN and nothing
   noticed. Symptoms for two weeks:
     * gdelt_trickle walked its list to warm a "shared" cache that no longer
       existed, and its health() could not import SHARED_CACHE_TTL_SEC.
     * Render's GDELT_MIN_INTERVAL_SEC=5 was ignored: v1.1.0 hard-coded 1.0.
     * military_tracker reported 'gdelt_gateway < v2.0' in its own payload.
   Lesson (HANDOVER_SOURCE_HEALTH_AUDIT §5.3, again): read __version__
   before editing a shared module, and never let a number go backwards.

2. GDELT'S LIMIT. One request per ~5s per IP; an IP that exceeds it is
   blocked for ~15 minutes -- longer than the violation (field report,
   GDELT DOC pipeline write-up). v1.1.0 paced at 1s and cooled down for
   300s, so it walked straight back into a block that had not lifted:
   the live log was "429 ... CIRCUIT OPEN for 300s" on a loop.

3. TWO INSTANCES. ME runs 2 Render instances (1 worker, 4 threads each).
   Every pacing clock, breaker and cache in v1.x lived in process memory,
   so two instances ran two independent clocks against one rate limit.

4. LANGUAGE WAS NEVER FILTERED. v1.x sent `&sourcelang=ara` as a URL
   parameter. GDELT DOC 2.0: operators "must be used as part of the value
   of the QUERY field" and "cannot be used as URL parameters on their own".
   Every non-English gateway query came back unfiltered. Now appended to
   the query text as `sourcelang:<code>`.

═══════════════════════════════════════════════════════════════════════
WHAT v2.4.0 DOES
═══════════════════════════════════════════════════════════════════════
  * SHARED SLOT       -- one GDELT request per MIN_INTERVAL_SEC across every
                         instance (Upstash SET NX PX). Floored at 5.0s: an env
                         var cannot set it below GDELT's own limit.
  * SHARED STAND-DOWN -- any 429 sets gdelt_gw:throttled_until for
                         THROTTLE_SEC (15 min) and EVERY instance stands down.
                         429 is never retried (v2.3.1).
  * TWO-LAYER CACHE   -- L1 in-process + L2 Upstash, SHARED_CACHE_TTL_SEC
                         (env GDELT_CACHE_TTL_SEC). The trickle's whole thesis.
  * BUDGET            -- per-service call budget on its OWN wall clock
                         (GDELT_MAX_CALLS_PER_CYCLE per GDELT_BUDGET_WINDOW_SEC),
                         shared by that service's instances via Upstash.
  * BREAKER           -- per-process, half-open: after cooldown exactly one
                         failure reopens it; one success closes it.
  * spend_by_label    -- per-module attribution of real HTTP calls.
  * sourcelang        -- in the query, where GDELT reads it. `sourcelang=`
                         accepted as a keyword alias (Syria News passed it and
                         got a TypeError, then fell back to calling GDELT direct).
  * FAILS OPEN        -- Upstash unreachable -> local-only pacing/cache, and
                         gateway_stats()['shared_cache'] says 'local_only'
                         rather than pretending.

DOCTRINE (unchanged): absence-honest. gdelt_fetch() returns [] both for a
true empty and for a refusal; gdelt_fetch_probed() says which via
probe['sensed'] and probe['reason'] ('throttled', 'circuit_open',
'budget_exhausted', 'slot_wait_timeout', 'rate_limited', 'timeout', ...).

PUBLIC SURFACE (unchanged names; every existing caller works untouched)
    gdelt_fetch(query, language='eng', timespan='3d', maxrecords=75, label='', refresh=False)
    gdelt_fetch_probed(...)  -> (articles, probe)
    gateway_stats()          -> dict (keys read by trickle, military, /debug)
    reset_cycle()            -> compatibility no-op-ish (clears local breaker)
    SHARED_CACHE_TTL_SEC     -> imported by gdelt_trickle.health()

ENV (all optional)
    GDELT_MIN_INTERVAL_SEC     default 5.5  (floor 5.0)
    GDELT_THROTTLE_SEC         default 900  (stand-down after a 429)
    GDELT_CACHE_TTL_SEC        default 64800 (18h; must exceed one trickle lap)
    GDELT_MAX_CALLS_PER_CYCLE  default 500
    GDELT_BUDGET_WINDOW_SEC    default 21600 (6h)
    GDELT_SLOT_MAX_WAIT_SEC    default 90
    GDELT_SLOT_SCOPE           default 'platform' (one clock for every backend
                               sharing this Upstash -- conservative, because
                               Render egress IPs are not guaranteed distinct)

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import time
import uuid
import hashlib
import threading
from datetime import datetime, timezone

import requests

__version__ = '2.4.0'


def _env_f(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_i(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return int(default)


# ── Tunables ────────────────────────────────────────────────────────────
GDELT_FLOOR_SEC       = 5.0     # GDELT's published-in-practice per-IP limit
MIN_INTERVAL_SEC      = max(GDELT_FLOOR_SEC, _env_f('GDELT_MIN_INTERVAL_SEC', 5.5))
THROTTLE_SEC          = _env_i('GDELT_THROTTLE_SEC', 900)
SHARED_CACHE_TTL_SEC  = _env_i('GDELT_CACHE_TTL_SEC', 64800)
MAX_CALLS_PER_WINDOW  = _env_i('GDELT_MAX_CALLS_PER_CYCLE', 500)
BUDGET_WINDOW_SEC     = max(60, _env_i('GDELT_BUDGET_WINDOW_SEC', 21600))
SLOT_MAX_WAIT_SEC     = _env_f('GDELT_SLOT_MAX_WAIT_SEC', 90)
SLOT_SCOPE            = os.environ.get('GDELT_SLOT_SCOPE', 'platform')
BUDGET_SCOPE          = os.environ.get('GDELT_BUDGET_SCOPE',
                                       os.environ.get('RENDER_SERVICE_NAME', 'default'))
CONNECT_TIMEOUT       = 10
READ_TIMEOUT          = _env_i('GDELT_READ_TIMEOUT', 25)
MAX_RETRIES           = _env_i('GDELT_MAX_RETRIES', 1)     # timeouts only
FAILURE_CIRCUIT       = _env_i('GDELT_FAILURE_CIRCUIT', 4)
CIRCUIT_COOLDOWN      = _env_i('GDELT_CIRCUIT_COOLDOWN_SEC', 300)
L1_MAX_ENTRIES        = 400
THROTTLE_CHECK_EVERY  = 5.0     # seconds between shared stand-down reads

GDELT_DOC_API = 'https://api.gdeltproject.org/api/v2/doc/doc'
KEY_PREFIX    = 'gdelt_gw:'

UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_URL')
               or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                 or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
WORKER_ID = '%s-%s' % (os.getpid(), uuid.uuid4().hex[:8])
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _now():
    return time.time()


def _sleep(s):
    time.sleep(s)


# ── Upstash (fails open) ────────────────────────────────────────────────
_redis_state = {'ok': bool(UPSTASH_URL and UPSTASH_TOKEN), 'errors': 0, 'last_error': None}


def _r(cmd, timeout=4):
    """One Upstash REST command. Returns `result`, or raises."""
    resp = requests.post(UPSTASH_URL,
                         headers={'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
                         json=[str(c) for c in cmd], timeout=timeout)
    resp.raise_for_status()
    return (resp.json() or {}).get('result')


def _redis(cmd, default=None):
    """Upstash call that never raises. Marks the shared layer degraded on error."""
    if not _redis_state['ok']:
        return default
    try:
        return _r(cmd)
    except Exception as e:
        _redis_state['errors'] += 1
        _redis_state['last_error'] = '%s: %s' % (type(e).__name__, str(e)[:120])
        return default


def _shared_available():
    return bool(_redis_state['ok'])


# ── State (per process; published with PROCESS_STARTED_AT, §5.6) ───────
_sem = threading.Semaphore(1)
_lock = threading.Lock()
_state = {
    'last_call': 0.0, 'consecutive_fail': 0, 'circuit_open_until': 0.0,
    'circuit_trips': 0, 'half_open': False, 'last_success_at': None,
    'throttled_until': 0.0, 'throttle_checked_at': 0.0,
    'calls': 0, 'ok': 0, 'timeouts': 0, 'rate_limited': 0, 'errors': 0,
    'cache_hits': 0, 'l1_hits': 0, 'l2_hits': 0, 'requests_seen': 0,
    'circuit_skips': 0, 'throttle_skips': 0, 'budget_skips': 0,
    'slot_waits': 0, 'slot_timeouts': 0, 'articles': 0,
}
_spend = {}           # label root -> real HTTP calls
_l1 = {}              # key -> (expires_at, articles)
_warned_kwargs = set()


# ── Cache ───────────────────────────────────────────────────────────────
def _cache_key(query, timespan, maxrecords):
    raw = '%s|%s|%s' % (query, timespan, maxrecords)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def _l1_get(k):
    hit = _l1.get(k)
    if not hit:
        return None
    if _now() > hit[0]:
        _l1.pop(k, None)
        return None
    return hit[1]


def _l1_put(k, articles):
    _l1[k] = (_now() + SHARED_CACHE_TTL_SEC, articles)
    if len(_l1) > L1_MAX_ENTRIES:
        for old in sorted(_l1, key=lambda x: _l1[x][0])[:100]:
            _l1.pop(old, None)


def _l2_get(k):
    raw = _redis(['GET', KEY_PREFIX + 'c:' + k])
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _l2_put(k, articles):
    _redis(['SET', KEY_PREFIX + 'c:' + k, json.dumps(articles), 'EX', SHARED_CACHE_TTL_SEC])


# ── Shared stand-down (429) ─────────────────────────────────────────────
def _throttled_remaining():
    now = _now()
    with _lock:
        local = _state['throttled_until']
        stale = (now - _state['throttle_checked_at']) >= THROTTLE_CHECK_EVERY
    if stale and _shared_available():
        raw = _redis(['GET', KEY_PREFIX + 'throttled_until'])
        try:
            shared = float(raw) if raw else 0.0
        except (TypeError, ValueError):
            shared = 0.0
        with _lock:
            _state['throttle_checked_at'] = now
            if shared > _state['throttled_until']:
                _state['throttled_until'] = shared
            local = _state['throttled_until']
    rem = local - now
    return rem if rem > 0 else 0


def _set_throttled():
    until = _now() + THROTTLE_SEC
    with _lock:
        _state['throttled_until'] = max(_state['throttled_until'], until)
    _redis(['SET', KEY_PREFIX + 'throttled_until', '%.3f' % until, 'EX', THROTTLE_SEC])
    return until


# ── Budget on its own wall clock (§5.1) ─────────────────────────────────
def _budget_key():
    window = int(_now() // BUDGET_WINDOW_SEC)
    return KEY_PREFIX + 'budget:%s:%d' % (BUDGET_SCOPE, window)


_local_budget = {'window': None, 'used': 0}


def _budget_take():
    """Consume one call. Returns (allowed, used_after)."""
    if _shared_available():
        k = _budget_key()
        used = _redis(['INCR', k])
        if used is not None:
            try:
                used = int(used)
            except (TypeError, ValueError):
                used = None
        if used is not None:
            if used == 1:
                _redis(['EXPIRE', k, BUDGET_WINDOW_SEC + 120])
            return used <= MAX_CALLS_PER_WINDOW, used
    window = int(_now() // BUDGET_WINDOW_SEC)
    with _lock:
        if _local_budget['window'] != window:
            _local_budget.update({'window': window, 'used': 0})
        _local_budget['used'] += 1
        used = _local_budget['used']
    return used <= MAX_CALLS_PER_WINDOW, used


def _budget_used():
    if _shared_available():
        raw = _redis(['GET', _budget_key()])
        try:
            return int(raw) if raw else 0
        except (TypeError, ValueError):
            pass
    window = int(_now() // BUDGET_WINDOW_SEC)
    with _lock:
        return _local_budget['used'] if _local_budget['window'] == window else 0


# ── Shared pacing slot ──────────────────────────────────────────────────
def _acquire_slot(tag):
    """Block until this process may send one request, or give up.

    Shared: SET gdelt_gw:slot:<scope> NX PX <interval>. Whoever sets it owns
    the next interval; everyone else waits. Local pacing is ALSO enforced, so
    a lost Upstash connection degrades to v1.x behaviour, not to no pacing.
    """
    deadline = _now() + SLOT_MAX_WAIT_SEC
    waited = False
    while True:
        if _throttled_remaining() > 0:
            return False, 'throttled'
        with _lock:
            gap = _now() - _state['last_call']
        local_wait = MIN_INTERVAL_SEC - gap
        if local_wait > 0:
            if _now() + local_wait > deadline:
                break
            waited = True
            _sleep(local_wait)
            continue
        if not _shared_available():
            return True, None
        res = _redis(['SET', KEY_PREFIX + 'slot:' + SLOT_SCOPE, WORKER_ID,
                      'NX', 'PX', int(MIN_INTERVAL_SEC * 1000)], default='__ERR__')
        if res == 'OK' or res == '__ERR__':      # owned, or Upstash hiccup (fail open)
            if waited:
                with _lock:
                    _state['slot_waits'] += 1
            return True, None
        if _now() + 0.5 > deadline:
            break
        waited = True
        _sleep(min(1.0, MIN_INTERVAL_SEC / 4.0))
    with _lock:
        _state['slot_timeouts'] += 1
    print('[GDELT Gateway] %s: no slot within %ds -- skipping (not a GDELT answer)'
          % (tag, int(SLOT_MAX_WAIT_SEC)))
    return False, 'slot_wait_timeout'


# ── Breaker (per process, half-open) ────────────────────────────────────
def _circuit_state():
    with _lock:
        if _now() < _state['circuit_open_until']:
            return 'open', _state['circuit_open_until'] - _now()
        if _state['circuit_open_until'] > 0 and not _state['half_open'] \
                and _state['consecutive_fail'] >= FAILURE_CIRCUIT:
            # Cooldown over: half-open. Exactly one more failure reopens.
            _state['half_open'] = True
            _state['consecutive_fail'] = FAILURE_CIRCUIT - 1
        return ('half_open' if _state['half_open'] else 'closed'), 0


def _record_call(label):
    root = (label or 'unlabelled').split('/')[0]
    with _lock:
        _state['last_call'] = _now()
        _state['calls'] += 1
        _spend[root] = _spend.get(root, 0) + 1


def _fail(kind):
    with _lock:
        if kind == 'timeout':
            _state['timeouts'] += 1
        elif kind == 'rate_limited':
            _state['rate_limited'] += 1
        else:
            _state['errors'] += 1
        _state['consecutive_fail'] += 1
        tripped = False
        if _state['consecutive_fail'] >= FAILURE_CIRCUIT and _now() >= _state['circuit_open_until']:
            _state['circuit_open_until'] = _now() + CIRCUIT_COOLDOWN
            _state['circuit_trips'] += 1
            _state['half_open'] = False
            tripped = True
        return tripped


def _succeed(n):
    with _lock:
        _state['ok'] += 1
        _state['articles'] += n
        _state['consecutive_fail'] = 0
        _state['half_open'] = False
        _state['circuit_open_until'] = 0.0
        _state['last_success_at'] = datetime.now(timezone.utc).isoformat()


# ── Query shaping ───────────────────────────────────────────────────────
def _apply_language(query, language):
    """GDELT reads sourcelang ONLY inside the query text (DOC 2.0 docs)."""
    q = (query or '').strip()
    lang = (language or '').strip()
    if not lang or lang.lower() in ('eng', 'english', 'en'):
        return q
    if 'sourcelang:' in q.lower():
        return q            # caller already put it where GDELT reads it
    return '%s sourcelang:%s' % (q, lang)


def _parse(payload):
    """GDELT doc API -> canonical article dicts (shape unchanged since v1.0)."""
    out = []
    for a in (payload or {}).get('articles', []) or []:
        title = (a.get('title') or '').strip()
        if not title:
            continue
        out.append({
            'title':       title,
            'description': (a.get('seendate') or ''),
            'url':         a.get('url') or '',
            'source':      a.get('domain') or 'GDELT',
            'published':   a.get('seendate') or '',
            'feed_type':   'gdelt',
            'language':    a.get('language') or '',
        })
    return out


def _probe(sensed, reason, attempts=0, cached=False, layer=None):
    return {'sensed': sensed, 'reason': reason, 'attempts': attempts,
            'cached': cached, 'cache_layer': layer}


# ── Public API ──────────────────────────────────────────────────────────
def gdelt_fetch_probed(query, language='eng', timespan='3d', maxrecords=75,
                       label='', refresh=False, sourcelang=None, **extra):
    """Fetch through the shared gateway. Returns (articles, probe).

    probe['sensed'] is True only when GDELT (or a cache of a real GDELT
    answer) produced this result. An empty list with sensed=False means we
    did not get to look -- never score that as quiet.
    """
    if sourcelang and (not language or language == 'eng'):
        language = sourcelang
    if extra:
        bad = tuple(sorted(extra))
        if bad not in _warned_kwargs:
            _warned_kwargs.add(bad)
            print('[GDELT Gateway] ignoring unknown kwargs %s (from %s)' % (list(bad), label or '?'))
    tag = label or language or 'eng'
    full_query = _apply_language(query, language)
    k = _cache_key(full_query, timespan, maxrecords)
    with _lock:
        _state['requests_seen'] += 1

    if not refresh:
        hit = _l1_get(k)
        if hit is not None:
            with _lock:
                _state['cache_hits'] += 1
                _state['l1_hits'] += 1
            return list(hit), _probe(True, None, cached=True, layer='l1')
        hit = _l2_get(k)
        if hit is not None:
            _l1_put(k, hit)
            with _lock:
                _state['cache_hits'] += 1
                _state['l2_hits'] += 1
            return list(hit), _probe(True, None, cached=True, layer='l2')

    attempts = 0
    last_reason = 'not attempted'
    for attempt in range(MAX_RETRIES + 1):
        rem = _throttled_remaining()
        if rem > 0:
            with _lock:
                _state['throttle_skips'] += 1
            return [], _probe(False, 'throttled', attempts)
        state, open_for = _circuit_state()
        if state == 'open':
            with _lock:
                _state['circuit_skips'] += 1
            return [], _probe(False, 'circuit_open', attempts)

        # Bounded wait for the in-process lock too: with 4 threads, an
        # unbounded `with _sem:` could stack 4 x SLOT_MAX_WAIT_SEC of stall.
        if not _sem.acquire(timeout=SLOT_MAX_WAIT_SEC):
            with _lock:
                _state['slot_timeouts'] += 1
            return [], _probe(False, 'slot_wait_timeout', attempts)
        try:
            ok, why = _acquire_slot(tag)
            if not ok:
                if why == 'throttled':
                    with _lock:
                        _state['throttle_skips'] += 1
                return [], _probe(False, why, attempts)
            allowed, used = _budget_take()
            if not allowed:
                with _lock:
                    _state['budget_skips'] += 1
                if used == MAX_CALLS_PER_WINDOW + 1:
                    print('[GDELT Gateway] call budget spent (%d per %dh, scope %s) -- '
                          'standing down until the window rolls'
                          % (MAX_CALLS_PER_WINDOW, BUDGET_WINDOW_SEC // 3600, BUDGET_SCOPE))
                return [], _probe(False, 'budget_exhausted', attempts)

            attempts += 1
            _record_call(label)
            params = {'query': full_query, 'mode': 'ArtList', 'format': 'json',
                      'maxrecords': maxrecords, 'timespan': timespan}
            try:
                resp = requests.get(
                    GDELT_DOC_API, params=params,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    headers={'User-Agent': 'AsifahAnalytics/%s (OSINT monitoring tool; '
                                           '+https://asifahanalytics.com)' % __version__})
            except requests.exceptions.Timeout:
                last_reason = 'timeout'
                tripped = _fail('timeout')
                print('[GDELT Gateway] %s: timeout after %ds (attempt %d/%d)%s'
                      % (tag, READ_TIMEOUT, attempt + 1, MAX_RETRIES + 1,
                         ' -- CIRCUIT OPEN %ds' % CIRCUIT_COOLDOWN if tripped else ''))
                if tripped or attempt >= MAX_RETRIES:
                    return [], _probe(False, 'timeout', attempts)
                continue
            except Exception as e:
                _fail('error')
                print('[GDELT Gateway] %s: %s: %s' % (tag, type(e).__name__, str(e)[:110]))
                return [], _probe(False, type(e).__name__, attempts)

            if resp.status_code == 429:
                # Never retried (v2.3.1). One refusal stands the WHOLE platform
                # down for THROTTLE_SEC, because GDELT's block outlasts the
                # violation and every retry inside it extends nothing but the log.
                _fail('rate_limited')
                _set_throttled()
                print('[GDELT Gateway] %s: 429 -- platform stand-down %ds (shared)'
                      % (tag, THROTTLE_SEC))
                return [], _probe(False, 'rate_limited', attempts)

            if resp.status_code != 200:
                _fail('error')
                print('[GDELT Gateway] %s: HTTP %s' % (tag, resp.status_code))
                return [], _probe(False, 'http_%s' % resp.status_code, attempts)

            try:
                articles = _parse(resp.json())
            except Exception:
                _fail('error')
                print('[GDELT Gateway] %s: unparseable body (%d bytes)'
                      % (tag, len(getattr(resp, 'content', b'') or b'')))
                return [], _probe(False, 'unparseable_body', attempts)

            _succeed(len(articles))
            _l1_put(k, articles)
            _l2_put(k, articles)
            print('[GDELT Gateway] %s: %d articles' % (tag, len(articles)))
            return articles, _probe(True, None, attempts)
        finally:
            _sem.release()

    return [], _probe(False, last_reason, attempts)


def gdelt_fetch(query, language='eng', timespan='3d', maxrecords=75, label='',
                refresh=False, sourcelang=None, **extra):
    """Backwards-compatible: article list only. See gdelt_fetch_probed()."""
    articles, _p = gdelt_fetch_probed(query, language=language, timespan=timespan,
                                      maxrecords=maxrecords, label=label,
                                      refresh=refresh, sourcelang=sourcelang, **extra)
    return articles


def gateway_stats():
    """Operational snapshot. Counters are PER PROCESS (see process_started_at);
    throttle, budget, slot and L2 cache are SHARED via Upstash."""
    state, open_for = _circuit_state()
    thr = _throttled_remaining()
    with _lock:
        s = {k: v for k, v in _state.items()
             if k not in ('last_call', 'circuit_open_until', 'throttled_until',
                          'throttle_checked_at', 'half_open')}
        spend = dict(sorted(_spend.items(), key=lambda kv: -kv[1]))
    used = _budget_used()
    s.update({
        'version':              __version__,
        'gateway_version':      __version__,
        'process_started_at':   PROCESS_STARTED_AT,
        'worker_id':            WORKER_ID,
        'success_rate':         round(s['ok'] / float(max(s['calls'], 1)), 2),
        'interval_now':         MIN_INTERVAL_SEC,
        'min_interval_sec':     MIN_INTERVAL_SEC,
        'circuit_state':        state,
        'circuit_open':         state == 'open' or thr > 0,
        'circuit_open_for':     int(max(open_for, thr)),
        'throttled':            thr > 0,
        'throttled_for':        int(thr),
        'throttle_sec':         THROTTLE_SEC,
        'budget_scope':         BUDGET_SCOPE,
        'budget_window_sec':    BUDGET_WINDOW_SEC,
        'budget_max':           MAX_CALLS_PER_WINDOW,
        'budget_used':          used,
        'budget_left':          max(0, MAX_CALLS_PER_WINDOW - used),
        'spend_by_label':       spend,
        'cache_entries':        len(_l1),
        'shared_cache':         'upstash' if _shared_available() and _redis_state['errors'] == 0
                                else ('upstash_degraded' if _shared_available() else 'local_only'),
        'shared_cache_ttl_sec': SHARED_CACHE_TTL_SEC,
        'redis_errors':         _redis_state['errors'],
        'redis_last_error':     _redis_state['last_error'],
        'slot_scope':           SLOT_SCOPE,
        'generated_at':         datetime.now(timezone.utc).isoformat(),
        'note': ('Zero articles with throttle/circuit/budget skips means the gateway '
                 'did not ask GDELT -- it does NOT mean the world was quiet.'),
    })
    return s


def reset_cycle():
    """Compatibility. Clears the LOCAL breaker only; the shared 429 stand-down is
    deliberately untouched (a cycle boundary must not erase a live block, §5.1)."""
    with _lock:
        _state['consecutive_fail'] = 0
        _state['circuit_open_until'] = 0.0
        _state['half_open'] = False


def _reset_all_for_test():
    with _lock:
        for k in list(_state):
            _state[k] = None if k == 'last_success_at' else (False if k == 'half_open' else 0 if isinstance(_state[k], int) else 0.0)
        _spend.clear()
    _l1.clear()
    _local_budget.update({'window': None, 'used': 0})
    _redis_state.update({'errors': 0, 'last_error': None})


# ============================================================
# SELF-TEST   python3 gdelt_gateway.py
# TEST 0 is a canary: the harness must produce a real success before any
# negative result is believed.
# ============================================================
if __name__ == '__main__':
    import sys
    print('GDELT Gateway v%s -- self-test\n' % __version__)
    failures = []

    def check(name, cond, detail=''):
        print('   %-4s %s %s' % ('PASS' if cond else 'FAIL', name, detail))
        if not cond:
            failures.append(name)

    # Virtual clock + fake Upstash so the suite is fast and deterministic.
    clock = {'t': 1_000_000.0}
    _now = lambda: clock['t']                                   # noqa: E731
    def _sleep(s):                                               # noqa: F811
        clock['t'] += max(0.0, s)

    class FakeRedis(object):
        def __init__(self):
            self.kv, self.exp, self.down = {}, {}, False
        def _alive(self, k):
            if k in self.exp and clock['t'] >= self.exp[k]:
                self.kv.pop(k, None); self.exp.pop(k, None)
            return k in self.kv
        def cmd(self, c):
            if self.down:
                raise IOError('upstash unreachable')
            op = c[0].upper()
            if op == 'GET':
                return self.kv.get(c[1]) if self._alive(c[1]) else None
            if op == 'SET':
                k, v, rest = c[1], c[2], [x.upper() for x in c[3:]]
                if 'NX' in rest and self._alive(k):
                    return None
                self.kv[k] = v
                if 'EX' in rest:
                    self.exp[k] = clock['t'] + float(c[3 + rest.index('EX') + 1])
                elif 'PX' in rest:
                    self.exp[k] = clock['t'] + float(c[3 + rest.index('PX') + 1]) / 1000.0
                else:
                    self.exp.pop(k, None)
                return 'OK'
            if op == 'INCR':
                n = int(self.kv.get(c[1], 0)) + 1 if self._alive(c[1]) else 1
                self.kv[c[1]] = str(n)
                return n
            if op == 'EXPIRE':
                self.exp[c[1]] = clock['t'] + float(c[2]); return 1
            raise ValueError(op)

    fr = FakeRedis()
    _r = lambda cmd, timeout=4: fr.cmd([str(x) for x in cmd])   # noqa: E731
    _redis_state['ok'] = True

    class Resp(object):
        def __init__(self, code=200, body='default'):
            self.status_code = code
            self.content = b'x'
            self._b = ({'articles': [{'title': 'Riyadh airport strike', 'url': 'u1', 'domain': 'arabnews.com'},
                                     {'title': 'Aramco HQ hit', 'url': 'u2', 'domain': 'apnews.com'}]}
                       if body == 'default' else body)
        def json(self):
            if self._b is None:
                raise ValueError('not json')
            return self._b

    sent = []
    real_get = requests.get
    def ok_get(url, params=None, **k):
        sent.append(dict(params or {})); return Resp()
    def rl_get(url, params=None, **k):
        sent.append(dict(params or {})); return Resp(429, None)
    def to_get(url, params=None, **k):
        sent.append(dict(params or {})); raise requests.exceptions.Timeout('sim')

    def fresh():
        _reset_all_for_test(); fr.kv.clear(); fr.exp.clear(); fr.down = False
        _redis_state['ok'] = True; del sent[:]; clock['t'] += 10_000

    print('TEST 0 -- CANARY')
    fresh(); requests.get = ok_get
    a, p = gdelt_fetch_probed('canary', label='canary')
    check('0a', len(a) == 2 and p['sensed'] and len(sent) == 1, 'arts=%d sensed=%s http=%d' % (len(a), p['sensed'], len(sent)))
    if failures:
        print('CANARY FAILED -- harness broken'); requests.get = real_get; sys.exit(1)

    print('TEST 1 -- language goes INTO the query (GDELT ignores the URL param)')
    fresh(); requests.get = ok_get
    gdelt_fetch('قطر', language='ara', label='qatar/ara')
    check('1a', sent[-1]['query'] == 'قطر sourcelang:ara', repr(sent[-1]['query']))
    check('1b', 'sourcelang' not in sent[-1], 'no URL param')
    gdelt_fetch('Qatar', language='eng', label='qatar/eng')
    check('1c', sent[-1]['query'] == 'Qatar', 'eng unchanged')
    gdelt_fetch('Hungary sourcelang:hun', language='hun', label='x')
    check('1d', sent[-1]['query'].count('sourcelang:') == 1, 'not duplicated')

    print('TEST 2 -- Syria News signatures: sourcelang= kwarg and positional')
    fresh(); requests.get = ok_get
    a, p = gdelt_fetch_probed('Syria', sourcelang='ara', maxrecords=20, timespan='7d')
    check('2a', p['sensed'] and sent[-1]['query'].endswith('sourcelang:ara'), sent[-1]['query'])
    a, p = gdelt_fetch_probed('Damascus', 'ara')
    check('2b', p['sensed'] and sent[-1]['query'].endswith('sourcelang:ara'))

    print('TEST 3 -- L1 then L2 cache (L2 is what the trickle warms)')
    fresh(); requests.get = ok_get
    gdelt_fetch('Hormuz', label='trickle/military')
    n = len(sent); a, p = gdelt_fetch_probed('Hormuz')
    check('3a', len(sent) == n and p['cache_layer'] == 'l1', 'L1 hit, no HTTP')
    _l1.clear()      # simulate the OTHER instance (or a restart)
    a, p = gdelt_fetch_probed('Hormuz')
    check('3b', len(sent) == n and p['cache_layer'] == 'l2' and len(a) == 2, 'L2 hit across instances')
    a, p = gdelt_fetch_probed('Hormuz', refresh=True)
    check('3c', len(sent) == n + 1 and not p['cached'], 'refresh=True bypasses cache read')

    print('TEST 4 -- a 429 is NOT retried and stands the whole platform down')
    fresh(); requests.get = rl_get
    a, p = gdelt_fetch_probed('Q429', label='saudi/eng')
    check('4a', len(sent) == 1 and p['reason'] == 'rate_limited' and not p['sensed'], 'one call, honest')
    check('4b', fr._alive(KEY_PREFIX + 'throttled_until'), 'shared stand-down written')
    _reset_all_for_test()      # the other instance: fresh process memory, same Redis
    requests.get = ok_get; n = len(sent)
    a, p = gdelt_fetch_probed('Q-other', label='qatar/eng')
    check('4c', len(sent) == n and p['reason'] == 'throttled', 'other instance stands down too')
    clock['t'] += THROTTLE_SEC + 1
    _reset_all_for_test()
    a, p = gdelt_fetch_probed('Q-after', label='qatar/eng')
    check('4d', p['sensed'] and len(sent) == n + 1, 'resumes after %ds' % THROTTLE_SEC)

    print('TEST 5 -- shared slot: two instances cannot both call inside the interval')
    fresh(); requests.get = ok_get
    gdelt_fetch('S1')
    t1 = clock['t']; _reset_all_for_test()      # other instance, local clock empty
    gdelt_fetch('S2')
    check('5a', clock['t'] - t1 >= MIN_INTERVAL_SEC - 0.01, 'waited %.2fs >= %.1fs' % (clock['t'] - t1, MIN_INTERVAL_SEC))

    print('TEST 6 -- interval floor: env cannot go below GDELT\'s 5s')
    check('6a', MIN_INTERVAL_SEC >= GDELT_FLOOR_SEC, 'MIN_INTERVAL_SEC=%.1f' % MIN_INTERVAL_SEC)

    print('TEST 7 -- budget on its own clock, shared by the service\'s instances')
    fresh(); requests.get = ok_get
    fr.kv[_budget_key()] = str(MAX_CALLS_PER_WINDOW)
    n = len(sent); a, p = gdelt_fetch_probed('B1')
    check('7a', p['reason'] == 'budget_exhausted' and len(sent) == n, 'no HTTP once spent')
    clock['t'] += BUDGET_WINDOW_SEC
    a, p = gdelt_fetch_probed('B2')
    check('7b', p['sensed'], 'new window refills')

    print('TEST 8 -- breaker: timeouts trip it; half-open probe closes it')
    fresh(); requests.get = to_get
    for i in range(4):
        gdelt_fetch_probed('T%d' % i)
    check('8a', gateway_stats()['circuit_state'] == 'open', gateway_stats()['circuit_state'])
    n = len(sent); a, p = gdelt_fetch_probed('T-skip')
    check('8b', p['reason'] == 'circuit_open' and len(sent) == n, 'open circuit: no HTTP')
    clock['t'] += CIRCUIT_COOLDOWN + 1; requests.get = ok_get
    a, p = gdelt_fetch_probed('T-probe')
    check('8c', p['sensed'] and gateway_stats()['circuit_state'] == 'closed', 'probe success closes')

    print('TEST 9 -- doctrine: real empty vs refusal vs unparseable')
    fresh(); requests.get = lambda url, params=None, **k: Resp(200, {'articles': []})
    a, p = gdelt_fetch_probed('EMPTY')
    check('9a', a == [] and p['sensed'], 'real zero is sensed')
    requests.get = lambda url, params=None, **k: Resp(200, None)
    a, p = gdelt_fetch_probed('HTML')
    check('9b', not p['sensed'] and p['reason'] == 'unparseable_body', p['reason'])

    print('TEST 10 -- Upstash down: fails open to local-only, and SAYS so')
    fresh(); requests.get = ok_get; fr.down = True
    a, p = gdelt_fetch_probed('LOCAL1')
    check('10a', p['sensed'], 'still fetches')
    check('10b', gateway_stats()['shared_cache'] != 'upstash', gateway_stats()['shared_cache'])

    print('TEST 11 -- stats contract (trickle, military, /debug read these)')
    fresh(); requests.get = ok_get
    gdelt_fetch('C1', label='trickle/military'); gdelt_fetch('C2', label='saudi/ara')
    s = gateway_stats()
    need = ('circuit_open', 'circuit_state', 'budget_left', 'cache_entries', 'cache_hits',
            'shared_cache', 'throttled', 'timeouts', 'spend_by_label', 'gateway_version',
            'process_started_at', 'success_rate')
    check('11a', all(k in s for k in need), 'missing=%s' % [k for k in need if k not in s])
    check('11b', s['spend_by_label'].get('trickle') == 1 and s['spend_by_label'].get('saudi') == 1, s['spend_by_label'])
    check('11c', s['gateway_version'] == '2.4.0' and isinstance(SHARED_CACHE_TTL_SEC, int))

    print('TEST 12 -- unknown kwargs never TypeError (they are logged once)')
    fresh(); requests.get = ok_get
    a, p = gdelt_fetch_probed('K1', mode='ArtList')
    check('12a', p['sensed'])

    requests.get = real_get
    if failures:
        print('\nFAILURES: %s' % failures); sys.exit(1)
    print('\nALL GATEWAY TESTS PASSED (v%s)' % __version__)
