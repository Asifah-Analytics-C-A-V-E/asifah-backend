"""
Asifah Analytics -- GDELT Gateway
v1.0.0 -- July 23 2026  |  portable, drop into any backend

═══════════════════════════════════════════════════════════════════════
THE PROBLEM
═══════════════════════════════════════════════════════════════════════
A live WHA scan produced this:

    [WHA GDELT] Timeout (>8s) -- breaking circuit for this scan     x12
    [Cuba GDELT] eng error: ... Read timed out
    [Cuba GDELT] spa error: ... Read timed out      (all six languages)
    [US Rhetoric GDELT] 429 rate limit -- skipping: eng
    [VZ Rhetoric] GDELT 429 -- short-circuit
    ...
    Total articles fetched: 566 (0 from GDELT, 0 from NewsAPI, 0 from Brave)

GDELT contributed ZERO across every WHA tracker. The cause is visible in the
interleaving of those log lines: the WHA country scanner, Cuba's six-language
sweep, US rhetoric, US stability, Venezuela, Peru and Chile were all calling
api.gdeltproject.org AT THE SAME TIME, from one process on one IP.

The backend was competing with itself. GDELT throttled, responses slowed past
the 5-8s timeouts, and every caller independently concluded GDELT was down.

Two compounding faults:
  1. NO PACING     -- dozens of concurrent requests from a single IP.
  2. SHORT TIMEOUTS-- 5s and 8s. GDELT's doc API routinely takes 10-20s under
                      load; those limits guaranteed failure exactly when the
                      service was busiest.

═══════════════════════════════════════════════════════════════════════
THE FIX
═══════════════════════════════════════════════════════════════════════
One gateway all trackers call, which:

  * SERIALISES  -- a semaphore admits one GDELT request at a time per process.
                   With --workers 1 --threads 4 this is sufficient; the threads
                   share memory so the lock is real.
  * PACES       -- a minimum interval between requests, so a burst of 60 calls
                   becomes a queue rather than a stampede.
  * WAITS PROPERLY -- realistic timeouts, because a slow answer beats no answer.
  * BACKS OFF   -- 429 escalates the interval for the rest of the cycle instead
                   of hammering harder.
  * DE-DUPLICATES -- identical queries inside one cycle are served from an
                   in-memory cache. Several trackers ask GDELT nearly the same
                   thing minutes apart; there is no reason to pay twice.

DOCTRINE: absence-honest. When GDELT genuinely fails the gateway returns empty
and says so in its stats. It never fabricates, and it never lets a caller
mistake "we throttled ourselves" for "the world went quiet" -- which is the
same class of error as reading a dead RSS feed as regional calm.

USAGE
    from gdelt_gateway import gdelt_fetch, gateway_stats
    articles = gdelt_fetch(query='Cuba OR Havana', language='eng', timespan='3d')

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import time
import threading
from datetime import datetime, timezone

import requests

__version__ = '1.0.0'

# ── Tunables ────────────────────────────────────────────────────────────
MAX_CONCURRENT   = 1      # one in flight per process; the whole point
MIN_INTERVAL_SEC = 1.0    # floor between requests
BACKOFF_INTERVAL = 4.0    # interval after a 429, for the rest of the cycle
CONNECT_TIMEOUT  = 10
READ_TIMEOUT     = 25     # was 5-8s at call sites; GDELT needs room
MAX_RETRIES      = 2
CACHE_TTL_SEC    = 900    # 15min -- comfortably longer than one scan cycle
FAILURE_CIRCUIT  = 4      # consecutive hard failures before pausing the cycle
CIRCUIT_COOLDOWN = 300    # how long the circuit stays open

GDELT_DOC_API = 'https://api.gdeltproject.org/api/v2/doc/doc'

_sem = threading.Semaphore(MAX_CONCURRENT)
_state_lock = threading.Lock()
_state = {
    'last_call':        0.0,
    'interval':         MIN_INTERVAL_SEC,
    'consecutive_fail': 0,
    'circuit_open_until': 0.0,
    'calls': 0, 'ok': 0, 'timeouts': 0, 'rate_limited': 0,
    'cache_hits': 0, 'circuit_skips': 0, 'articles': 0,
}
_cache = {}   # key -> (expires_at, articles)


def _now():
    return time.time()


def _cache_get(key):
    hit = _cache.get(key)
    if not hit:
        return None
    expires, data = hit
    if _now() > expires:
        _cache.pop(key, None)
        return None
    return data


def _cache_put(key, data):
    _cache[key] = (_now() + CACHE_TTL_SEC, data)
    if len(_cache) > 400:                     # bounded; oldest out first
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(k, None)


def _parse(payload):
    """GDELT doc API -> canonical article dicts."""
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


def gdelt_fetch(query, language='eng', timespan='3d', maxrecords=75, label=''):
    """
    Fetch from GDELT through the shared gateway.

    Returns a list of article dicts -- empty on failure, never None, never
    fabricated. Callers keep their own fallback logic; this only makes the
    attempt survivable.
    """
    tag = label or language
    cache_key = '%s|%s|%s|%s' % (query, language, timespan, maxrecords)

    cached = _cache_get(cache_key)
    if cached is not None:
        with _state_lock:
            _state['cache_hits'] += 1
        print('[GDELT Gateway] %s: cache hit (%d articles)' % (tag, len(cached)))
        return list(cached)

    with _state_lock:
        if _now() < _state['circuit_open_until']:
            _state['circuit_skips'] += 1
            remaining = int(_state['circuit_open_until'] - _now())
            print('[GDELT Gateway] %s: circuit open, %ds remaining -- skipping' % (tag, remaining))
            return []

    params = {
        'query':      query,
        'mode':       'ArtList',
        'format':     'json',
        'maxrecords': maxrecords,
        'timespan':   timespan,
    }
    if language and language != 'eng':
        params['sourcelang'] = language

    for attempt in range(MAX_RETRIES + 1):
        # SERIALISE: only one GDELT request in flight per process.
        with _sem:
            # PACE: honour the minimum interval measured from the last call.
            with _state_lock:
                gap = _now() - _state['last_call']
                wait = _state['interval'] - gap
            if wait > 0:
                time.sleep(wait)

            try:
                resp = requests.get(
                    GDELT_DOC_API, params=params,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    headers={'User-Agent': 'AsifahAnalytics/1.0 (+https://asifahanalytics.com)'},
                )
            except requests.exceptions.Timeout:
                with _state_lock:
                    _state['last_call'] = _now()
                    _state['calls'] += 1
                    _state['timeouts'] += 1
                    _state['consecutive_fail'] += 1
                    tripped = _state['consecutive_fail'] >= FAILURE_CIRCUIT
                    if tripped:
                        _state['circuit_open_until'] = _now() + CIRCUIT_COOLDOWN
                print('[GDELT Gateway] %s: timeout after %ds (attempt %d/%d)'
                      % (tag, READ_TIMEOUT, attempt + 1, MAX_RETRIES + 1))
                if attempt < MAX_RETRIES:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                return []
            except Exception as e:
                with _state_lock:
                    _state['last_call'] = _now()
                    _state['calls'] += 1
                    _state['consecutive_fail'] += 1
                print('[GDELT Gateway] %s: %s: %s' % (tag, type(e).__name__, str(e)[:110]))
                return []

            with _state_lock:
                _state['last_call'] = _now()
                _state['calls'] += 1

            if resp.status_code == 429:
                with _state_lock:
                    _state['rate_limited'] += 1
                    # Slow the whole process down for the rest of the cycle
                    # rather than letting each caller retry into the wall.
                    _state['interval'] = max(_state['interval'], BACKOFF_INTERVAL)
                print('[GDELT Gateway] %s: 429 -- interval raised to %.1fs'
                      % (tag, _state['interval']))
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_INTERVAL)
                    continue
                return []

            if resp.status_code != 200:
                with _state_lock:
                    _state['consecutive_fail'] += 1
                print('[GDELT Gateway] %s: HTTP %s' % (tag, resp.status_code))
                return []

            try:
                articles = _parse(resp.json())
            except Exception:
                # GDELT intermittently returns HTML or truncated JSON on 200.
                print('[GDELT Gateway] %s: unparseable body (%d bytes)'
                      % (tag, len(resp.content or b'')))
                return []

            with _state_lock:
                _state['ok'] += 1
                _state['articles'] += len(articles)
                _state['consecutive_fail'] = 0
            _cache_put(cache_key, articles)
            print('[GDELT Gateway] %s: %d articles' % (tag, len(articles)))
            return articles

    return []


def gateway_stats():
    """Operational snapshot -- useful in a /debug endpoint."""
    with _state_lock:
        s = dict(_state)
    total = max(s['calls'], 1)
    s['success_rate'] = round(s['ok'] / total, 2)
    s['interval_now'] = round(s['interval'], 2)
    s['circuit_open'] = _now() < s['circuit_open_until']
    s['cache_entries'] = len(_cache)
    s['generated_at'] = datetime.now(timezone.utc).isoformat()
    s['note'] = ('Serialised, paced GDELT access. A zero article count with '
                 'timeouts logged means the gateway could not reach GDELT -- it '
                 'does NOT mean the world was quiet.')
    return s


def reset_cycle():
    """Call at the start of a scan cycle to relax the backoff."""
    with _state_lock:
        _state['interval'] = MIN_INTERVAL_SEC
        _state['consecutive_fail'] = 0


# ============================================================
# SELF-TEST
# ============================================================
if __name__ == '__main__':
    import types, sys

    print('GDELT Gateway v%s -- self-test\n' % __version__)

    calls = {'n': 0, 'times': []}

    class FakeResp:
        def __init__(self, code=200, body=None):
            self.status_code = code
            self._b = body if body is not None else {'articles': [
                {'title': 'Cuba blackout deepens', 'url': 'http://x', 'domain': 'granma.cu'},
                {'title': 'Havana fuel queues', 'url': 'http://y', 'domain': '14ymedio.com'}]}
            self.content = b'{}'
        def json(self): return self._b

    def fake_get(url, **k):
        calls['n'] += 1
        calls['times'].append(time.time())
        return FakeResp()

    requests.get = fake_get

    print('TEST 1 -- pacing: 4 sequential calls respect MIN_INTERVAL')
    reset_cycle()
    t0 = time.time()
    for i in range(4):
        gdelt_fetch('Q%d' % i, language='eng', label='t%d' % i)
    elapsed = time.time() - t0
    print('  4 calls in %.2fs (floor %.1fs each)' % (elapsed, MIN_INTERVAL_SEC))
    assert elapsed >= MIN_INTERVAL_SEC * 2, elapsed
    print('  OK -- requests queued instead of stampeding\n')

    print('TEST 2 -- cache: identical query served without a new request')
    before = calls['n']
    r = gdelt_fetch('Q0', language='eng', label='repeat')
    print('  HTTP calls added: %d | articles: %d' % (calls['n'] - before, len(r)))
    assert calls['n'] == before and len(r) == 2
    print('  OK -- duplicate query cost nothing\n')

    print('TEST 3 -- concurrency: 6 threads serialise through the semaphore')
    reset_cycle(); _cache.clear(); calls['n'] = 0
    overlaps = {'max': 0, 'cur': 0}
    olock = threading.Lock()
    def tracking_get(url, **k):
        with olock:
            overlaps['cur'] += 1
            overlaps['max'] = max(overlaps['max'], overlaps['cur'])
        time.sleep(0.05)
        with olock:
            overlaps['cur'] -= 1
        return FakeResp()
    requests.get = tracking_get
    ts = [threading.Thread(target=gdelt_fetch, args=('CQ%d' % i,),
                           kwargs={'label': 'c%d' % i}) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    print('  peak concurrent GDELT requests: %d' % overlaps['max'])
    assert overlaps['max'] == 1, overlaps['max']
    print('  OK -- never more than one in flight (was the root cause)\n')

    print('TEST 4 -- 429 raises the interval for the rest of the cycle')
    reset_cycle(); _cache.clear()
    requests.get = lambda url, **k: FakeResp(429)
    gdelt_fetch('RL', label='ratelimited')
    s = gateway_stats()
    print('  interval now: %.1fs | rate_limited: %d' % (s['interval_now'], s['rate_limited']))
    assert s['interval_now'] >= BACKOFF_INTERVAL
    print('  OK -- backs off instead of hammering\n')

    print('TEST 5 -- timeout is honest, not fabricated')
    reset_cycle(); _cache.clear()
    def timeout_get(url, **k):
        raise requests.exceptions.Timeout('simulated')
    requests.get = timeout_get
    out = gdelt_fetch('TO', label='timeout')
    s = gateway_stats()
    print('  returned: %r | timeouts recorded: %d' % (out, s['timeouts']))
    assert out == [] and s['timeouts'] > 0
    print('  OK -- empty and logged, never invented\n')

    print('ALL GATEWAY TESTS PASSED')
    print('\nstats:', {k: v for k, v in gateway_stats().items()
                       if k in ('calls', 'ok', 'timeouts', 'rate_limited',
                                'cache_hits', 'success_rate')})
