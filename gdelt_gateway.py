"""
Asifah Analytics -- GDELT Gateway
v1.1.0 -- October 4 2026  |  portable, drop into any backend

═══════════════════════════════════════════════════════════════════════
THE ORIGINAL PROBLEM (v1.0.0, July 23 2026)
═══════════════════════════════════════════════════════════════════════
A live WHA scan produced this:

    [WHA GDELT] Timeout (>8s) -- breaking circuit for this scan     x12
    [Cuba GDELT] eng error: ... Read timed out
    [US Rhetoric GDELT] 429 rate limit -- skipping: eng
    ...
    Total articles fetched: 566 (0 from GDELT, 0 from NewsAPI, 0 from Brave)

The backend was competing with itself: a dozen trackers calling
api.gdeltproject.org at the same time, from one process on one IP, each
with a 5-8s timeout, each independently concluding GDELT was down.

v1.0.0 answered that with a semaphore, pacing, realistic timeouts and a
per-query cache. Those parts worked.

═══════════════════════════════════════════════════════════════════════
WHAT v1.1.0 FIXES -- found in a live Europe log, October 4 2026
═══════════════════════════════════════════════════════════════════════
    [GDELT Gateway] hungary/hun: 429 -- interval raised to 4.0s     x14
    [GDELT Gateway] hungary/rus: timeout after 25s (attempt 1/3)
    [GDELT Gateway] hungary/rus: timeout after 25s (attempt 2/3)
    [GDELT Gateway] hungary/rus: timeout after 25s (attempt 3/3)
    ... again ...
    [Hungary] Scan complete in 474.87s

Read that first line fourteen times. "raised TO 4.0s" -- the same number,
every time. Three defects, each small, compounding into an eight-minute scan:

  1. THE BACKOFF DID NOT ESCALATE.
     `interval = max(interval, BACKOFF_INTERVAL)` raises 1.0 -> 4.0 once and
     is then a no-op forever. The fifteenth 429 was answered with exactly the
     same pacing as the first. A backoff that does not back off further is a
     constant with extra steps.

  2. A 429 DID NOT COUNT AS A FAILURE.
     `consecutive_fail` was incremented on timeouts and on other non-200s,
     but NOT on 429 -- the single most common failure mode. So the circuit
     breaker, the one mechanism that could have ended the Hungary scan early,
     could never trip from rate limiting no matter how long it continued.

  3. THE CIRCUIT WAS CHECKED ONCE, BEFORE THE RETRY LOOP.
     If another thread tripped the breaker while this call was on attempt 1,
     this call still spent attempts 2 and 3 -- up to 75 seconds -- hammering a
     service the process had already concluded was unreachable.

Proof that the fix is the right shape, from the same log: Turkey's tracker
carries its own breaker and finished in 11.5 seconds. Hungary, with no
working breaker, took 474.87. Same upstream, same minute, same outage.

v1.1.0 adds, on top of v1.0.0's serialising and pacing:

  * ESCALATING BACKOFF -- each 429 doubles the interval to a ceiling, instead
                          of pinning it at one value.
  * 429 COUNTS         -- rate limiting trips the circuit like any other
                          failure, because it IS one.
  * CIRCUIT RE-CHECKED -- before every attempt, not once per call.
  * FAIL FAST WHEN SICK-- once failures are consecutive, stop spending the
                          full retry ladder on each new query.
  * DECAY ON SUCCESS   -- the interval relaxes as GDELT recovers. (v1.0.0
                          only relaxed via reset_cycle(), which no backend
                          ever actually called, so a single 429 punished the
                          process until restart.)
  * PROBED FETCH       -- gdelt_fetch_probed() tells a caller WHY it got
                          nothing. See DOCTRINE.

DOCTRINE: absence-honest. When GDELT genuinely fails the gateway returns
empty and says so. It never fabricates, and it never lets a caller mistake
"we throttled ourselves" for "the world went quiet" -- the same class of
error as reading a dead RSS feed as regional calm, or an FAA 403 as clear
airspace. gdelt_fetch() returns [] on both a true empty result and a
failure; callers that need to tell those apart must use
gdelt_fetch_probed(), which returns (articles, probe) with probe['sensed'].

USAGE
    from gdelt_gateway import gdelt_fetch, gateway_stats
    articles = gdelt_fetch(query='Cuba OR Havana', language='eng', timespan='3d')

    # absence-honest variant
    from gdelt_gateway import gdelt_fetch_probed
    articles, probe = gdelt_fetch_probed(query='...', language='eng')
    if not probe['sensed']:
        ...   # we did not look; do NOT score this as quiet

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import time
import threading
from datetime import datetime, timezone

import requests

__version__ = '1.1.0'

# ── Tunables ────────────────────────────────────────────────────────────
MAX_CONCURRENT   = 1      # one in flight per process; the whole point
MIN_INTERVAL_SEC = 1.0    # floor between requests
BACKOFF_INTERVAL = 4.0    # interval immediately after the first 429
MAX_INTERVAL_SEC = 60.0   # ceiling; beyond this a scan is better off failing
BACKOFF_FACTOR   = 2.0    # each further 429 multiplies the interval
DECAY_FACTOR     = 0.75   # each clean success relaxes it back toward the floor
CONNECT_TIMEOUT  = 10
READ_TIMEOUT     = 25     # was 5-8s at call sites; GDELT needs room
MAX_RETRIES      = 2      # i.e. up to 3 attempts, when healthy
SICK_THRESHOLD   = 2      # consecutive failures after which we stop retrying
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
    'circuit_trips':    0,
    'last_success_at':  None,
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


def _register_failure(kind):
    """
    Record a failed attempt and trip the circuit if we have had enough.

    v1.0.0 called this for timeouts but not for 429s, which is why fourteen
    consecutive rate limits never opened the breaker. Every failure counts.
    """
    with _state_lock:
        _state['last_call'] = _now()
        _state['calls'] += 1
        if kind == 'timeout':
            _state['timeouts'] += 1
        elif kind == 'rate_limited':
            _state['rate_limited'] += 1
            # ESCALATE. Not max(interval, 4.0) -- that pins at 4.0 forever.
            cur = _state['interval']
            nxt = BACKOFF_INTERVAL if cur < BACKOFF_INTERVAL else cur * BACKOFF_FACTOR
            _state['interval'] = min(nxt, MAX_INTERVAL_SEC)
        _state['consecutive_fail'] += 1
        tripped = False
        if _state['consecutive_fail'] >= FAILURE_CIRCUIT and _now() >= _state['circuit_open_until']:
            _state['circuit_open_until'] = _now() + CIRCUIT_COOLDOWN
            _state['circuit_trips'] += 1
            tripped = True
        return tripped, _state['interval'], _state['consecutive_fail']


def _register_success(n_articles):
    with _state_lock:
        _state['last_call'] = _now()
        _state['calls'] += 1
        _state['ok'] += 1
        _state['articles'] += n_articles
        _state['consecutive_fail'] = 0
        _state['last_success_at'] = datetime.now(timezone.utc).isoformat()
        # DECAY: relax pacing as GDELT recovers. Without this a single 429
        # held the whole process at 4s/request until the next deploy, because
        # no backend ever called reset_cycle().
        _state['interval'] = max(MIN_INTERVAL_SEC, _state['interval'] * DECAY_FACTOR)


def _circuit_remaining():
    with _state_lock:
        remaining = _state['circuit_open_until'] - _now()
    return remaining if remaining > 0 else 0


def gdelt_fetch_probed(query, language='eng', timespan='3d', maxrecords=75, label=''):
    """
    Fetch from GDELT through the shared gateway.

    Returns (articles, probe).

    probe = {
        'sensed':  True only if GDELT actually answered with parseable JSON.
                   An empty list with sensed=True is a REAL zero. An empty
                   list with sensed=False means we never got to look.
        'reason':  None when sensed, otherwise why not.
        'attempts': how many HTTP attempts were spent.
        'cached':  served from the in-process cache.
    }

    This distinction is the whole point. A caller that scores
    "0 GDELT articles" as regional calm, when the truth is that the gateway
    was rate-limited into silence, is making the same error as reading a
    dead RSS feed as peace.
    """
    tag = label or language
    cache_key = '%s|%s|%s|%s' % (query, language, timespan, maxrecords)

    cached = _cache_get(cache_key)
    if cached is not None:
        with _state_lock:
            _state['cache_hits'] += 1
        print('[GDELT Gateway] %s: cache hit (%d articles)' % (tag, len(cached)))
        return list(cached), {'sensed': True, 'reason': None, 'attempts': 0, 'cached': True}

    params = {
        'query':      query,
        'mode':       'ArtList',
        'format':     'json',
        'maxrecords': maxrecords,
        'timespan':   timespan,
    }
    if language and language != 'eng':
        params['sourcelang'] = language

    attempts = 0
    last_reason = 'not attempted'

    for attempt in range(MAX_RETRIES + 1):
        # CIRCUIT CHECKED BEFORE EVERY ATTEMPT, not once per call. In v1.0.0 a
        # breaker tripped by another thread mid-call was simply not noticed,
        # and this call went on to spend its full retry ladder anyway.
        remaining = _circuit_remaining()
        if remaining > 0:
            with _state_lock:
                _state['circuit_skips'] += 1
            print('[GDELT Gateway] %s: circuit open, %ds remaining -- skipping'
                  % (tag, int(remaining)))
            return [], {'sensed': False, 'reason': 'circuit_open',
                        'attempts': attempts, 'cached': False}

        # FAIL FAST WHEN SICK: once failures are stacking up, do not spend the
        # full ladder on every new query. Hungary burned 150s on one language
        # this way, retrieving nothing.
        with _state_lock:
            sick = _state['consecutive_fail'] >= SICK_THRESHOLD
        if sick and attempt > 0:
            print('[GDELT Gateway] %s: %d consecutive failures -- not retrying'
                  % (tag, _state['consecutive_fail']))
            return [], {'sensed': False, 'reason': last_reason,
                        'attempts': attempts, 'cached': False}

        # SERIALISE: only one GDELT request in flight per process.
        with _sem:
            # PACE: honour the minimum interval measured from the last call.
            with _state_lock:
                gap = _now() - _state['last_call']
                wait = _state['interval'] - gap
            if wait > 0:
                time.sleep(wait)

            attempts += 1
            try:
                resp = requests.get(
                    GDELT_DOC_API, params=params,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    headers={'User-Agent':
                             'AsifahAnalytics/%s (OSINT monitoring tool; '
                             '+https://asifahanalytics.com)' % __version__},
                )
            except requests.exceptions.Timeout:
                last_reason = 'timeout'
                tripped, interval, nfail = _register_failure('timeout')
                print('[GDELT Gateway] %s: timeout after %ds (attempt %d/%d)%s'
                      % (tag, READ_TIMEOUT, attempt + 1, MAX_RETRIES + 1,
                         ' -- CIRCUIT OPEN for %ds' % CIRCUIT_COOLDOWN if tripped else ''))
                if tripped or attempt >= MAX_RETRIES:
                    return [], {'sensed': False, 'reason': 'timeout',
                                'attempts': attempts, 'cached': False}
                time.sleep(2.0 * (attempt + 1))
                continue
            except Exception as e:
                last_reason = type(e).__name__
                _register_failure('error')
                print('[GDELT Gateway] %s: %s: %s' % (tag, type(e).__name__, str(e)[:110]))
                return [], {'sensed': False, 'reason': last_reason,
                            'attempts': attempts, 'cached': False}

            if resp.status_code == 429:
                last_reason = 'rate_limited'
                tripped, interval, nfail = _register_failure('rate_limited')
                print('[GDELT Gateway] %s: 429 -- interval now %.1fs '
                      '(consecutive failures: %d)%s'
                      % (tag, interval, nfail,
                         ' -- CIRCUIT OPEN for %ds' % CIRCUIT_COOLDOWN if tripped else ''))
                if tripped or attempt >= MAX_RETRIES:
                    return [], {'sensed': False, 'reason': 'rate_limited',
                                'attempts': attempts, 'cached': False}
                time.sleep(interval)
                continue

            if resp.status_code != 200:
                last_reason = 'http_%s' % resp.status_code
                _register_failure('error')
                print('[GDELT Gateway] %s: HTTP %s' % (tag, resp.status_code))
                return [], {'sensed': False, 'reason': last_reason,
                            'attempts': attempts, 'cached': False}

            try:
                articles = _parse(resp.json())
            except Exception:
                # GDELT intermittently returns HTML or truncated JSON on 200.
                # A 200 we cannot parse is NOT a sensed empty result.
                last_reason = 'unparseable_body'
                _register_failure('error')
                print('[GDELT Gateway] %s: unparseable body (%d bytes)'
                      % (tag, len(resp.content or b'')))
                return [], {'sensed': False, 'reason': last_reason,
                            'attempts': attempts, 'cached': False}

            _register_success(len(articles))
            _cache_put(cache_key, articles)
            print('[GDELT Gateway] %s: %d articles' % (tag, len(articles)))
            return articles, {'sensed': True, 'reason': None,
                              'attempts': attempts, 'cached': False}

    return [], {'sensed': False, 'reason': last_reason,
                'attempts': attempts, 'cached': False}


def gdelt_fetch(query, language='eng', timespan='3d', maxrecords=75, label=''):
    """
    Backwards-compatible wrapper: returns the article list only.

    Signature and return shape are unchanged from v1.0.0, so every existing
    caller keeps working untouched. Callers that need to distinguish "GDELT
    said nothing" from "GDELT refused" should move to gdelt_fetch_probed().
    """
    articles, _probe = gdelt_fetch_probed(query, language=language,
                                          timespan=timespan,
                                          maxrecords=maxrecords, label=label)
    return articles


def gateway_stats():
    """Operational snapshot -- useful in a /debug endpoint."""
    with _state_lock:
        s = dict(_state)
    total = max(s['calls'], 1)
    s['success_rate'] = round(s['ok'] / total, 2)
    s['interval_now'] = round(s['interval'], 2)
    s['circuit_open'] = _now() < s['circuit_open_until']
    s['circuit_open_for'] = max(0, int(s['circuit_open_until'] - _now()))
    s['cache_entries'] = len(_cache)
    s['version'] = __version__
    s['generated_at'] = datetime.now(timezone.utc).isoformat()
    s.pop('circuit_open_until', None)
    s.pop('last_call', None)
    s['note'] = ('Serialised, paced GDELT access. A zero article count with '
                 'timeouts or rate limits logged means the gateway could not '
                 'reach GDELT -- it does NOT mean the world was quiet.')
    return s


def reset_cycle():
    """
    Call at the start of a scan cycle to relax the backoff.

    Kept for compatibility. As of v1.1.0 the interval also decays on its own
    after each success, so a process that never calls this still recovers --
    which matters, because no backend ever did.
    """
    with _state_lock:
        _state['interval'] = MIN_INTERVAL_SEC
        _state['consecutive_fail'] = 0


def _reset_all_for_test():
    """Full state reset. Test support only."""
    with _state_lock:
        _state.update({
            'last_call': 0.0, 'interval': MIN_INTERVAL_SEC,
            'consecutive_fail': 0, 'circuit_open_until': 0.0,
            'circuit_trips': 0, 'last_success_at': None,
            'calls': 0, 'ok': 0, 'timeouts': 0, 'rate_limited': 0,
            'cache_hits': 0, 'circuit_skips': 0, 'articles': 0,
        })
    _cache.clear()


# ============================================================
# SELF-TEST
#   python3 gdelt_gateway.py
#
# TEST 0 is a canary. It forces the harness to produce a POSITIVE result
# before any negative result is believed. A stubbed-out test rig reports
# "blocked / empty / failed" for every case and looks like a passing suite
# of negative assertions; this suite has been bitten by exactly that.
# ============================================================
if __name__ == '__main__':
    import sys

    print('GDELT Gateway v%s -- self-test\n' % __version__)

    _real_sleep = time.sleep
    _failures = []

    class _NoSleep(object):
        """Keeps wall-clock sane while still exercising the pacing maths."""
        slept = []
        def sleep(self, s):
            self.slept.append(s)
        def time(self):
            return _real_time()

    _real_time = time.time
    _real_time_mod = time

    def check(label, cond, detail=''):
        print('   %-4s %s %s' % ('PASS' if cond else 'FAIL', label, detail))
        if not cond:
            _failures.append(label)

    class FakeResp(object):
        def __init__(self, code=200, body='default', content=b'{}'):
            self.status_code = code
            self.content = content
            if body == 'default':
                body = {'articles': [
                    {'title': 'Cuba blackout deepens', 'url': 'http://x', 'domain': 'granma.cu'},
                    {'title': 'Havana fuel queues', 'url': 'http://y', 'domain': '14ymedio.com'}]}
            self._b = body
        def json(self):
            if self._b is None:
                raise ValueError('not json')
            return self._b

    _real_get = requests.get
    calls = {'n': 0}

    def ok_get(url, **k):
        calls['n'] += 1
        return FakeResp()

    def rl_get(url, **k):
        calls['n'] += 1
        return FakeResp(429, None)

    def to_get(url, **k):
        calls['n'] += 1
        raise requests.exceptions.Timeout('simulated')

    # ------------------------------------------------------------------
    print('TEST 0 -- CANARY: the harness can produce a genuine success')
    _reset_all_for_test()
    requests.get = ok_get
    arts, probe = gdelt_fetch_probed('canary', label='canary')
    check('0a', len(arts) == 2, 'articles=%d' % len(arts))
    check('0b', probe['sensed'] is True, 'sensed=%s' % probe['sensed'])
    check('0c', calls['n'] == 1, 'http calls=%d' % calls['n'])
    if _failures:
        print('\nCANARY FAILED -- the harness is broken. Nothing below is trustworthy.')
        requests.get = _real_get
        sys.exit(1)
    print('   canary green; negative results below are meaningful\n')

    # ------------------------------------------------------------------
    print('TEST 1 -- pacing: sequential calls respect MIN_INTERVAL (real clock)')
    _reset_all_for_test()
    requests.get = ok_get
    t0 = _real_time()
    for i in range(3):
        gdelt_fetch('Q%d' % i, label='t%d' % i)
    elapsed = _real_time() - t0
    check('1a', elapsed >= MIN_INTERVAL_SEC * 1.5,
          '3 calls in %.2fs (floor %.1fs each)' % (elapsed, MIN_INTERVAL_SEC))
    print()

    # From here on, pacing sleeps are stubbed so the suite stays fast.
    time = _NoSleep()

    # ------------------------------------------------------------------
    print('TEST 2 -- cache: an identical query costs no HTTP call')
    before = calls['n']
    r = gdelt_fetch('Q0', label='repeat')
    check('2a', calls['n'] == before, 'http calls added=%d' % (calls['n'] - before))
    check('2b', len(r) == 2, 'articles=%d' % len(r))
    a, p = gdelt_fetch_probed('Q0', label='repeat')
    check('2c', p['cached'] is True and p['sensed'] is True)
    print()

    # ------------------------------------------------------------------
    print('TEST 3 -- concurrency: 6 threads serialise through the semaphore')
    _reset_all_for_test()
    overlaps = {'max': 0, 'cur': 0}
    olock = threading.Lock()
    def tracking_get(url, **k):
        with olock:
            overlaps['cur'] += 1
            overlaps['max'] = max(overlaps['max'], overlaps['cur'])
        _real_sleep(0.05)
        with olock:
            overlaps['cur'] -= 1
        return FakeResp()
    requests.get = tracking_get
    ts = [threading.Thread(target=gdelt_fetch, args=('CQ%d' % i,),
                           kwargs={'label': 'c%d' % i}) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    check('3a', overlaps['max'] == 1, 'peak concurrent requests=%d' % overlaps['max'])
    print()

    # ------------------------------------------------------------------
    print('TEST 4 -- REGRESSION: 429 ESCALATES the interval (v1.0.0 pinned it)')
    _reset_all_for_test()
    requests.get = rl_get
    seen = []
    for i in range(4):
        with _state_lock:
            _state['circuit_open_until'] = 0.0      # isolate escalation from the breaker
            _state['consecutive_fail'] = 0
        gdelt_fetch('RL%d' % i, label='rl%d' % i)
        with _state_lock:
            seen.append(round(_state['interval'], 1))
    check('4a', seen[0] >= BACKOFF_INTERVAL, 'first 429 -> %.1fs' % seen[0])
    check('4b', len(set(seen)) > 1, 'intervals observed: %s' % seen)
    check('4c', seen == sorted(seen) and seen[-1] > seen[0],
          'strictly non-decreasing and actually grew: %s' % seen)
    check('4d', seen[-1] <= MAX_INTERVAL_SEC, 'ceiling respected (%.1f <= %.1f)'
          % (seen[-1], MAX_INTERVAL_SEC))
    print()

    # ------------------------------------------------------------------
    print('TEST 5 -- REGRESSION: consecutive 429s TRIP the circuit (the Hungary bug)')
    _reset_all_for_test()
    requests.get = rl_get
    for i in range(6):
        gdelt_fetch('HU%d' % i, label='hungary/hun')
    s = gateway_stats()
    check('5a', s['circuit_open'] is True, 'circuit_open=%s' % s['circuit_open'])
    check('5b', s['circuit_trips'] >= 1, 'trips=%d' % s['circuit_trips'])
    print()

    # ------------------------------------------------------------------
    print('TEST 6 -- an open circuit short-circuits later calls with no HTTP')
    before = calls['n']
    arts, probe = gdelt_fetch_probed('HU-after', label='hungary/rus')
    check('6a', calls['n'] == before, 'http calls added=%d' % (calls['n'] - before))
    check('6b', probe['sensed'] is False and probe['reason'] == 'circuit_open',
          'reason=%s' % probe['reason'])
    print()

    # ------------------------------------------------------------------
    print('TEST 7 -- timeouts are honest and bounded')
    _reset_all_for_test()
    requests.get = to_get
    before = calls['n']
    arts, probe = gdelt_fetch_probed('TO', label='timeout')
    spent = calls['n'] - before
    check('7a', arts == [] and probe['sensed'] is False, 'reason=%s' % probe['reason'])
    check('7b', spent <= MAX_RETRIES + 1, 'attempts spent=%d (max %d)' % (spent, MAX_RETRIES + 1))
    check('7c', gateway_stats()['timeouts'] > 0)
    print()

    # ------------------------------------------------------------------
    print('TEST 8 -- fail fast when sick: a second query does not re-spend the ladder')
    before = calls['n']
    gdelt_fetch_probed('TO2', label='timeout2')
    spent = calls['n'] - before
    check('8a', spent <= 2, 'attempts on the follow-up query=%d' % spent)
    print()

    # ------------------------------------------------------------------
    print('TEST 9 -- DOCTRINE: a real empty differs from a refusal')
    _reset_all_for_test()
    requests.get = lambda url, **k: FakeResp(200, {'articles': []})
    arts, probe = gdelt_fetch_probed('EMPTY', label='realzero')
    check('9a', arts == [] and probe['sensed'] is True,
          'real zero: sensed=%s' % probe['sensed'])
    _reset_all_for_test()
    requests.get = rl_get
    arts2, probe2 = gdelt_fetch_probed('REFUSED', label='refused')
    check('9b', arts2 == [] and probe2['sensed'] is False,
          'refusal: sensed=%s reason=%s' % (probe2['sensed'], probe2['reason']))
    check('9c', arts == arts2, 'both return [] -- only the probe tells them apart')
    print()

    # ------------------------------------------------------------------
    print('TEST 10 -- a 200 with an unparseable body is NOT a sensed zero')
    _reset_all_for_test()
    requests.get = lambda url, **k: FakeResp(200, None, b'<html>error</html>')
    arts, probe = gdelt_fetch_probed('HTML', label='html')
    check('10a', probe['sensed'] is False and probe['reason'] == 'unparseable_body',
          'reason=%s' % probe['reason'])
    print()

    # ------------------------------------------------------------------
    print('TEST 11 -- the interval DECAYS back toward the floor on success')
    _reset_all_for_test()
    with _state_lock:
        _state['interval'] = 32.0
    requests.get = ok_get
    for i in range(10):
        gdelt_fetch('DEC%d' % i, label='decay%d' % i)
    with _state_lock:
        final = _state['interval']
    check('11a', final < 32.0, 'interval relaxed 32.0 -> %.2f' % final)
    check('11b', final >= MIN_INTERVAL_SEC, 'never below the floor (%.2f)' % final)
    print()

    # ------------------------------------------------------------------
    print('TEST 12 -- backwards compatibility with every v1.0.0 caller')
    _reset_all_for_test()
    requests.get = ok_get
    out = gdelt_fetch('COMPAT', language='rus', timespan='7d',
                      maxrecords=75, label='europe/rus')
    check('12a', isinstance(out, list), 'returns a plain list')
    check('12b', len(out) == 2 and 'title' in out[0], 'article shape unchanged')
    print()

    time = _real_time_mod
    requests.get = _real_get

    if _failures:
        print('FAILURES: %s' % _failures)
        sys.exit(1)
    print('ALL GATEWAY TESTS PASSED (v%s)' % __version__)
    print('\nstats:', {k: v for k, v in gateway_stats().items()
                       if k in ('calls', 'ok', 'timeouts', 'rate_limited',
                                'cache_hits', 'circuit_skips', 'circuit_trips',
                                'success_rate', 'interval_now')})
