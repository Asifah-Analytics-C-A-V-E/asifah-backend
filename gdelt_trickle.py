"""
Asifah Analytics -- GDELT TRICKLE FETCHER
v1.0.0 -- September 20 2026  |  portable, drop into any backend

═══════════════════════════════════════════════════════════════════════
WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════
Sep 20 2026, one ME scan, measured:

    requests_seen = 610   distinct = 609
    calls         = 77    rate_limited = 33   timeouts = 34
    cache_hits    = 25
    scan_time     = 23.1 min

Ten successful fetches out of six hundred and ten requests. Five separate
fixes shipped that day -- circuit breaker, throttle memory, call budget,
shared Upstash cache, slower pacing -- each helped at the margin and none
of them fixed it, because they all accepted the same shape:

    SIX HUNDRED AND TEN QUERIES FIRED IN ONE BURST.

That shape is the problem. GDELT is free, unauthenticated and heavily
loaded; 610 queries in twenty minutes from a datacenter IP is not a
request pattern it will serve, at any pacing.

But 610 queries spread across a TWELVE HOUR cycle is one query every
seventy seconds. That it will serve.

═══════════════════════════════════════════════════════════════════════
WHAT THIS DOES
═══════════════════════════════════════════════════════════════════════
A background thread walks the registered query list slowly and forever,
calling gdelt_fetch() one query at a time. Every success lands in the
shared Upstash cache. The scan then READS from that cache instead of
fetching, and never blocks on the network.

It is a slow DRIVER of the existing gateway, not a second client:
  * the circuit breaker still protects it
  * the call budget still caps it
  * spend_by_label still attributes it
  * cache writes go through the path already in production

CRITICAL INVARIANT -- CACHE TTL MUST EXCEED LAP TIME.
  lap_time = query_count * interval. With TTL below that, an entry
  expires before the walker returns to it and the scan finds a
  half-warm cache. Set GDELT_CACHE_TTL_SEC to roughly 1.2x the lap
  (610 queries * 70s = 11.9h lap -> 14h TTL). health() reports this
  ratio and says so out loud when it is wrong, because a silently
  half-warm cache looks exactly like a working one.

ABSENCE-HONEST: this never fabricates. A query that fails simply leaves
no cache entry, the scan gets nothing for it, and stats() says how many.

═══════════════════════════════════════════════════════════════════════
USAGE
═══════════════════════════════════════════════════════════════════════
    # in military_tracker.py, at module scope:
    from gdelt_trickle import register_queries
    register_queries('military', [
        {'query': q, 'language': lang, 'timespan': '7d', 'maxrecords': 50}
        for queries, lang, _name in query_blocks for q in queries
    ])

    # once, in app.py after all modules are imported:
    from gdelt_trickle import start_trickle, register_trickle_endpoints
    register_trickle_endpoints(app)
    start_trickle()

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import time
import threading
from datetime import datetime, timezone

__version__ = '1.0.0'

# ── Tunables (env-overridable, like the gateway) ─────────────────────
# TARGET_LAP_SEC is the contract: walk the WHOLE registered set in about
# this long. The interval is DERIVED from it, so adding queries slows the
# walker down rather than silently raising the request rate -- which is
# the mistake that produced the 610-in-20-minutes burst in the first place.
TARGET_LAP_SEC   = int(os.environ.get('GDELT_TRICKLE_LAP_SEC', '43200'))   # 12h
MIN_INTERVAL_SEC = float(os.environ.get('GDELT_TRICKLE_MIN_SEC', '20'))
MAX_INTERVAL_SEC = float(os.environ.get('GDELT_TRICKLE_MAX_SEC', '300'))
BOOT_DELAY_SEC   = int(os.environ.get('GDELT_TRICKLE_BOOT_DELAY', '180'))
ENABLED          = os.environ.get('GDELT_TRICKLE_ENABLED', '1') not in ('0', 'false', 'False')

# How long to rest when the gateway tells us it is refusing traffic. No
# point walking the list into an open breaker -- that just burns lap time.
BACKOFF_SEC      = float(os.environ.get('GDELT_TRICKLE_BACKOFF', '120'))

LOG_EVERY = int(os.environ.get('GDELT_TRICKLE_LOG_EVERY', '25'))

_lock = threading.Lock()
_queries = []          # [{'label','query','language','timespan','maxrecords'}]
_seen_keys = set()     # dedupe across registrations
_started = False

_state = {
    'laps':            0,
    'position':        0,
    'fetched':         0,     # returned >=1 article
    'empty':           0,     # reached GDELT, nothing to report
    'cached':          0,     # gateway served it from cache -- free
    'failed':          0,     # returned nothing AND was not a cache hit
    'backoffs':        0,
    'last_lap_sec':    None,
    'lap_started_at':  None,
    'last_query':      '',
    'last_at':         None,
    'started_at':      None,
    'errors':          0,
    'last_error':      '',
}


def _now():
    return time.time()


def _iso():
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════
# REGISTRATION
# ════════════════════════════════════════════════════════════════════

def register_queries(label, queries):
    """Register a module's GDELT queries for slow background refresh.

    label    short module tag -- becomes the gateway label, so this shows
             up in gateway_stats()['spend_by_label'] as trickle/<label>.
    queries  iterable of dicts: {'query', 'language', 'timespan', 'maxrecords'}
             or plain (query, language) tuples.

    Deduped on the same key the gateway caches by, so two modules asking
    the same question cost one fetch, not two. Returns the number added.
    """
    added = 0
    with _lock:
        for q in (queries or []):
            if isinstance(q, (tuple, list)):
                item = {'query': q[0],
                        'language': q[1] if len(q) > 1 else 'eng',
                        'timespan': q[2] if len(q) > 2 else '7d',
                        'maxrecords': q[3] if len(q) > 3 else 50}
            elif isinstance(q, dict):
                item = {'query': q.get('query'),
                        'language': q.get('language', 'eng'),
                        'timespan': q.get('timespan', '7d'),
                        'maxrecords': q.get('maxrecords', 50)}
            else:
                continue
            if not item['query']:
                continue
            key = '%s|%s|%s|%s' % (item['query'], item['language'],
                                   item['timespan'], item['maxrecords'])
            if key in _seen_keys:
                continue
            _seen_keys.add(key)
            item['label'] = 'trickle/%s' % label
            _queries.append(item)
            added += 1
    if added:
        print('[GDELT Trickle] %s registered %d queries (total %d, '
              'interval now %.0fs)' % (label, added, len(_queries), current_interval()))
    return added


def current_interval():
    """Seconds between fetches, derived from the lap target and set size."""
    n = len(_queries)
    if n <= 0:
        return MAX_INTERVAL_SEC
    return max(MIN_INTERVAL_SEC, min(MAX_INTERVAL_SEC, TARGET_LAP_SEC / float(n)))


# ════════════════════════════════════════════════════════════════════
# THE WALKER
# ════════════════════════════════════════════════════════════════════

def _gateway_is_refusing():
    """True when the breaker is open or the budget is spent.

    Walking into either just burns lap time on calls that never leave the
    building. Soft-fails to False: if we cannot read the gateway's state,
    proceed rather than stall.
    """
    try:
        from gdelt_gateway import gateway_stats
        s = gateway_stats() or {}
        if s.get('circuit_open'):
            return True
        if s.get('budget_left') is not None and s['budget_left'] <= 0:
            return True
    except Exception:
        pass
    return False


def _walk_once(fetch):
    """Fetch exactly one query and advance the cursor. Returns interval to wait."""
    with _lock:
        n = len(_queries)
        if n == 0:
            return MAX_INTERVAL_SEC
        if _state['position'] >= n:
            # Lap complete.
            _state['position'] = 0
            _state['laps'] += 1
            if _state['lap_started_at']:
                _state['last_lap_sec'] = round(_now() - _state['lap_started_at'], 1)
            _state['lap_started_at'] = _now()
            print('[GDELT Trickle] lap %d complete in %s -- fetched %d, cached %d, '
                  'empty %d, failed %d'
                  % (_state['laps'],
                     ('%.1f min' % (_state['last_lap_sec'] / 60.0))
                     if _state['last_lap_sec'] else 'n/a',
                     _state['fetched'], _state['cached'],
                     _state['empty'], _state['failed']))
        item = dict(_queries[_state['position']])
        pos = _state['position']
        _state['position'] += 1
        if _state['lap_started_at'] is None:
            _state['lap_started_at'] = _now()

    # Ask the gateway whether it is worth trying at all.
    if _gateway_is_refusing():
        with _lock:
            _state['backoffs'] += 1
        return BACKOFF_SEC

    try:
        from gdelt_gateway import gateway_stats
        before = (gateway_stats() or {}).get('cache_hits', 0)
    except Exception:
        before = None

    try:
        articles = fetch(item['query'],
                         language=item['language'],
                         timespan=item['timespan'],
                         maxrecords=item['maxrecords'],
                         label=item['label']) or []
        served_from_cache = False
        if before is not None:
            try:
                from gdelt_gateway import gateway_stats
                after = (gateway_stats() or {}).get('cache_hits', 0)
                served_from_cache = after > before
            except Exception:
                pass

        with _lock:
            _state['last_query'] = item['query'][:80]
            _state['last_at'] = _iso()
            if served_from_cache:
                _state['cached'] += 1
            elif articles:
                _state['fetched'] += 1
            else:
                # Reached-and-empty and never-reached are different facts, but
                # the gateway returns [] for both. Counted as failed here and
                # reconciled against gateway_stats() in health(), which CAN
                # tell them apart. Never guessed.
                _state['failed'] += 1
            done = _state['fetched'] + _state['cached'] + _state['empty'] + _state['failed']
        if LOG_EVERY and done % LOG_EVERY == 0:
            print('[GDELT Trickle] %d/%d this lap -- fetched %d, cached %d, failed %d'
                  % (pos + 1, len(_queries), _state['fetched'],
                     _state['cached'], _state['failed']))
    except Exception as e:
        with _lock:
            _state['errors'] += 1
            _state['last_error'] = str(e)[:160]
        print('[GDELT Trickle] %s: %s' % (type(e).__name__, str(e)[:120]))

    return current_interval()


def _loop():
    time.sleep(BOOT_DELAY_SEC)
    try:
        from gdelt_gateway import gdelt_fetch as fetch
    except ImportError as e:
        print('[GDELT Trickle] gdelt_gateway unavailable (%s) -- trickle disabled' % e)
        return
    print('[GDELT Trickle] walking %d queries at %.0fs intervals '
          '(target lap %.1fh)'
          % (len(_queries), current_interval(), TARGET_LAP_SEC / 3600.0))
    with _lock:
        _state['started_at'] = _iso()
        _state['lap_started_at'] = _now()
    while True:
        try:
            wait = _walk_once(fetch)
        except Exception as e:
            with _lock:
                _state['errors'] += 1
                _state['last_error'] = str(e)[:160]
            wait = current_interval()
        time.sleep(max(1.0, wait))


def start_trickle():
    """Start the background walker. Idempotent; safe to call more than once."""
    global _started
    with _lock:
        if _started:
            return False
        if not ENABLED:
            print('[GDELT Trickle] disabled by GDELT_TRICKLE_ENABLED')
            return False
        if not _queries:
            print('[GDELT Trickle] no queries registered -- not starting')
            return False
        _started = True
    t = threading.Thread(target=_loop, daemon=True, name='GDELTTrickle')
    t.start()
    print('[GDELT Trickle] started (boot delay %ds)' % BOOT_DELAY_SEC)
    return True


# ════════════════════════════════════════════════════════════════════
# OBSERVABILITY
# ════════════════════════════════════════════════════════════════════

def stats():
    with _lock:
        s = dict(_state)
    n = len(_queries)
    interval = current_interval()
    s.update({
        'version':          __version__,
        'enabled':          ENABLED,
        'running':          _started,
        'query_count':      n,
        'interval_sec':     round(interval, 1),
        'projected_lap_h':  round(n * interval / 3600.0, 2) if n else None,
        'target_lap_h':     round(TARGET_LAP_SEC / 3600.0, 2),
        'generated_at':     _iso(),
    })
    by_label = {}
    with _lock:
        for q in _queries:
            by_label[q['label']] = by_label.get(q['label'], 0) + 1
    s['queries_by_label'] = dict(sorted(by_label.items(), key=lambda kv: -kv[1]))
    return s


def health():
    """The one check that matters: is the cache TTL longer than a lap?

    A TTL shorter than the lap means entries expire before the walker
    returns to them, so the scan finds a half-warm cache -- which looks
    exactly like a working one from the outside. Said out loud here.
    """
    s = stats()
    out = {'version': __version__, 'ok': True, 'warnings': [],
           'trickle': s, 'generated_at': _iso()}
    try:
        from gdelt_gateway import SHARED_CACHE_TTL_SEC, gateway_stats
        ttl_h = SHARED_CACHE_TTL_SEC / 3600.0
        lap_h = s.get('projected_lap_h')
        out['cache_ttl_h'] = round(ttl_h, 2)
        out['lap_h'] = lap_h
        if lap_h:
            ratio = ttl_h / lap_h
            out['ttl_over_lap'] = round(ratio, 2)
            if ratio < 1.0:
                out['ok'] = False
                out['warnings'].append(
                    'CACHE TTL (%.1fh) IS SHORTER THAN ONE LAP (%.1fh). Entries '
                    'expire before the walker returns to them, so the scan will '
                    'find a HALF-WARM cache that looks healthy from outside. '
                    'Raise GDELT_CACHE_TTL_SEC to at least %d.'
                    % (ttl_h, lap_h, int(lap_h * 1.2 * 3600)))
            elif ratio < 1.15:
                out['warnings'].append(
                    'Cache TTL (%.1fh) barely exceeds one lap (%.1fh). Little '
                    'margin for a slow lap. Consider %d.'
                    % (ttl_h, lap_h, int(lap_h * 1.2 * 3600)))
        g = gateway_stats() or {}
        out['gateway'] = {
            'circuit_state': g.get('circuit_state'),
            'budget_left':   g.get('budget_left'),
            'cache_entries': g.get('cache_entries'),
            'shared_cache':  g.get('shared_cache'),
            'throttled':     g.get('throttled'),
        }
        if g.get('shared_cache') != 'upstash':
            out['ok'] = False
            out['warnings'].append(
                'Shared cache is NOT Upstash. The trickle writes into an '
                'in-process cache that dies on restart, so the scan will see '
                'nothing after a redeploy. Check UPSTASH_REDIS_* env vars.')
    except Exception as e:
        out['ok'] = False
        out['warnings'].append('Could not read gateway state: %s' % str(e)[:120])
    return out


def register_trickle_endpoints(app):
    from flask import jsonify

    @app.route('/api/gdelt-trickle/stats', methods=['GET'])
    def _trickle_stats():
        return jsonify(stats())

    @app.route('/api/gdelt-trickle/health', methods=['GET'])
    def _trickle_health():
        h = health()
        return jsonify(h), (200 if h['ok'] else 503)

    print('[GDELT Trickle] Registered: /api/gdelt-trickle/{stats,health}')
