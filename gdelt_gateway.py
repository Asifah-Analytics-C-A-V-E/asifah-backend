"""
Asifah Analytics -- GDELT Gateway
v2.3.0 -- September 20 2026  |  portable, drop into any backend

═══════════════════════════════════════════════════════════════════════
WHAT v1.0 GOT RIGHT
═══════════════════════════════════════════════════════════════════════
Serialising and pacing GDELT access was correct and stays untouched. The
backend really was competing with itself, and one request in flight per
process really was the fix.

═══════════════════════════════════════════════════════════════════════
WHAT v1.0 GOT WRONG -- THE LOCKOUT
═══════════════════════════════════════════════════════════════════════
A live ME scan on Sep 19 2026 produced an hour of this and nothing else:

    [GDELT Gateway] military/ara: circuit open, 114s remaining -- skipping
    [GDELT Gateway] me/heb:       circuit open, 113s remaining -- skipping
    [GDELT Gateway] military/ukr: circuit open,  92s remaining -- skipping
    ... several hundred more, across 16 language variants

Not one request reached GDELT. The circuit had latched permanently.

THE MECHANISM, exactly:

  1. Four consecutive failures set consecutive_fail = 4, which is
     FAILURE_CIRCUIT, so the circuit opened for CIRCUIT_COOLDOWN.
  2. Every call during the cooldown hit this early return:

         if _now() < _state['circuit_open_until']:
             _state['circuit_skips'] += 1
             return []

     which does NOT touch consecutive_fail. The counter stayed at 4.
  3. When the cooldown expired, the next call went through with the
     counter STILL at 4. One failure took it to 5, which is >= 4, so the
     circuit reopened immediately for another 300 seconds.
  4. Repeat forever.

The only escape was a single success landing on the one attempt allowed
per five minutes, or a process restart. consecutive_fail was also cleared
by reset_cycle() -- which no caller has ever imported.

THE COST, traced end to end:

    GDELT locks out
      -> every tracker sees 0 GDELT articles
      -> 'news_index_total < 60' and '(gdelt + newsapi) < 10' are always
         true, so the Brave FALLBACK fires as a PRIMARY on every scan
      -> ~460 Brave queries/day against a 6,000/month plan
      -> Brave 402s on Sep 12; seven days dark before anyone noticed
      -> corpus silently collapses from 7 sources to 3

One unreset counter. A month of degraded data and a spent API budget.

═══════════════════════════════════════════════════════════════════════
THE v2.0 FIX
═══════════════════════════════════════════════════════════════════════
  * PROPER HALF-OPEN -- when the cooldown expires the breaker enters
    half-open and admits exactly ONE probe. Success closes it and clears
    the counter; failure reopens it. The state is explicit instead of
    being inferred from a counter that nothing resets.
  * AUTO CYCLE RESET -- a gap longer than CYCLE_IDLE_SEC between calls is
    a new scan cycle: the interval relaxes and the failure count clears,
    with no caller change required. reset_cycle() still works for anyone
    who wants to be explicit. Five repos call this gateway; a fix that
    needed all five edited would not have been a fix.
  * QUIET SKIPS -- an open breaker logged once per call, which is how one
    hour of logs became several hundred identical lines and hid the
    actual failures. It now logs on transition and then periodically.
  * OBSERVABLE -- gateway_stats() reports the breaker state, how many
    times it has opened, and the last real error. It already existed and
    was never wired to an endpoint; there is a note below on doing that.

DOCTRINE: absence-honest. When GDELT genuinely fails the gateway returns
empty and says so in its stats. It never fabricates, and it never lets a
caller mistake "we throttled ourselves" for "the world went quiet" --
which is the same class of error as reading a dead RSS feed as regional
calm. v1.0 was honest about the empty result and silent about the reason,
which turned out to be the more expensive half.

══════════════════════════════════════════════════════════════════════
v2.1 -- THE BACKOFF WITH AMNESIA
══════════════════════════════════════════════════════════════════════
A 429 raised `interval` to BACKOFF_INTERVAL "for the rest of the cycle".
But CIRCUIT_COOLDOWN is 300s and CYCLE_IDLE_SEC is 120s, so every breaker
cooldown was read as a new cycle, which reset `interval` to the floor. The
backoff could not survive the event that raised it. Sep 20: 36 rate-limited
responses, interval_now still 1.0. Fixed with throttled_until, which has
its own clock.

══════════════════════════════════════════════════════════════════════
v2.3 -- THE SAME MISTAKE, ONE FUNCTION DOWN
══════════════════════════════════════════════════════════════════════
v2.2 hung the call budget off _maybe_new_cycle() -- the same unreliable
signal. Sep 20, one scan: calls=139 with budget_left=150, which is
arithmetically impossible unless the budget reset mid-scan. It did, every
time the breaker cooled down. 139 calls got through a 150-call budget and
rate_limited went from 36 to 67. A limit whose clock someone else winds
is not a limit.

v2.3 gives the budget its own window (BUDGET_WINDOW_SEC), independent of
cycles, breakers and idle gaps.

v2.3 also adds SPEND ATTRIBUTION. The gateway has always seen a `label` on
every call -- me/ara, humanitarian/eng, commodity/brave, oman/fas -- and
never counted by it. Sep 20 measured 609 DISTINCT queries in one scan, so
the cache cannot help and the budget can only ration. The query set has to
come down, and spend_by_label is what turns that from guesswork into a
list of which module is asking for what.

USAGE
    from gdelt_gateway import gdelt_fetch, gateway_stats
    articles = gdelt_fetch(query='Cuba OR Havana', language='eng', timespan='3d')

    # Recommended, in any /debug endpoint:
    #     'gdelt_gateway': gateway_stats()

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import hashlib
import time
import threading
from datetime import datetime, timezone

import requests

__version__ = '2.3.0'

# ── Tunables ────────────────────────────────────────────────────────────
# Every tunable is env-overridable so pacing can be retuned from the Render
# dashboard without a deploy -- which matters when the thing being tuned is
# how hard we lean on a service that is currently refusing us.
MAX_CONCURRENT   = 1      # one in flight per process; the whole point
MIN_INTERVAL_SEC = float(os.environ.get('GDELT_MIN_INTERVAL_SEC', '1.0'))
BACKOFF_INTERVAL = float(os.environ.get('GDELT_BACKOFF_INTERVAL', '4.0'))
CONNECT_TIMEOUT  = 10
READ_TIMEOUT     = 25     # was 5-8s at call sites; GDELT needs room
MAX_RETRIES      = 2
CACHE_TTL_SEC    = 900    # 15min -- comfortably longer than one scan cycle
FAILURE_CIRCUIT  = 4      # consecutive hard failures before pausing the cycle
CIRCUIT_COOLDOWN = 300    # how long the breaker stays open before a probe

# A gap this long between calls means the previous scan cycle ended. The
# gateway relaxes itself rather than carrying a bad cycle's state forward
# into a fresh one. v1.0 depended on reset_cycle() for this and no caller
# ever called it, so state accumulated for the life of the process --
# which on Render is days.
CYCLE_IDLE_SEC   = 120
# How long a 429 is remembered ACROSS cycle resets. v2.0 reset `interval`
# back to the floor on every new cycle, and a 300s breaker cooldown always
# counts as a new cycle -- so the 4s backoff could never survive the very
# event it was raised for. Sep 20 2026: 36 rate-limited responses and
# interval_now still read 1.0.
THROTTLE_MEMORY_SEC = 1800

# v2.2, Sep 20 2026: budget + shared cache.
# 457 GDELT attempts in one scan, 36 answered 429. By then the breaker was
# not the problem -- the request volume was. And CACHE_TTL_SEC above is
# in-process only, so it dies on restart: the ME backend restarted four
# times that morning and cache_hits read 0. These are the actual fix.
SHARED_CACHE_TTL_SEC = int(os.environ.get('GDELT_CACHE_TTL_SEC', '21600'))  # 6h

# v2.3 -- the budget, on its own clock.
# BUDGET_WINDOW_SEC is a wall-clock window, not a 'cycle'. Nothing the
# breaker or an idle gap does can reset it early. GDELT_MAX_CALLS_PER_CYCLE
# is kept as the env name so an existing Render variable still works.
BUDGET_WINDOW_SEC = int(os.environ.get('GDELT_BUDGET_WINDOW_SEC', '3600'))
MAX_CALLS_PER_WINDOW = int(os.environ.get('GDELT_MAX_CALLS_PER_CYCLE', '150'))
MAX_CALLS_PER_CYCLE = MAX_CALLS_PER_WINDOW   # back-compat alias

UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_URL')
               or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                 or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
REDIS_OK = bool(UPSTASH_URL and UPSTASH_TOKEN)

# An open breaker used to log once per skipped call. With 16 language
# variants across several trackers that is hundreds of identical lines per
# scan, which is how the real failures became invisible.
SKIP_LOG_EVERY   = 50

GDELT_DOC_API = 'https://api.gdeltproject.org/api/v2/doc/doc'

# Breaker states
CLOSED, OPEN, HALF_OPEN = 'closed', 'open', 'half_open'

_sem = threading.Semaphore(MAX_CONCURRENT)
_state_lock = threading.Lock()
_state = {
    'last_call':        0.0,
    'interval':         MIN_INTERVAL_SEC,
    'consecutive_fail': 0,
    'circuit':          CLOSED,
    'circuit_open_until': 0.0,
    'circuit_opens':    0,
    'probe_in_flight':  False,
    'skips_since_log':  0,
    'last_error':       '',
    'throttled_until':  0.0,   # v2.1 -- survives _maybe_new_cycle()
    'window_start':     0.0,   # v2.3 -- the budget's OWN clock
    'window_calls':     0,     # v2.3 -- GDELT calls spent in this window
    'windows':          0,
    'budget_skips':     0,     # refused because the budget was spent
    'redis_hits':       0,     # served from the shared 6h cache
    'redis_writes':     0,
    'requests_seen':    0,     # v2.3 -- gdelt_fetch calls THIS WINDOW
    'requests_total':   0,     # v2.3 -- and cumulative, so the two are
                               #         never confused again
    'cycles':           0,
    'calls': 0, 'ok': 0, 'timeouts': 0, 'rate_limited': 0,
    'cache_hits': 0, 'circuit_skips': 0, 'articles': 0,
}
_cache = {}   # key -> (expires_at, articles)   L1, in-process
_window_keys = set()   # v2.3 -- distinct cache keys seen this WINDOW

# v2.3 -- spend attribution. label -> counters. Reset with the window, so
# a reading always answers 'in the last hour, who asked for what'.
_label_spend = {}


def _label_bump(label, field, n=1):
    """Count one event against a label. Call with _state_lock held."""
    rec = _label_spend.get(label)
    if rec is None:
        rec = {'requests': 0, 'calls': 0, 'cache_hits': 0,
               'budget_refused': 0, 'circuit_refused': 0, 'articles': 0}
        _label_spend[label] = rec
    rec[field] = rec.get(field, 0) + n


def _now():
    return time.time()


def _redis(cmd):
    """One Upstash REST command. Returns the 'result' value or None.

    Same shape as brave_gateway's helper, deliberately: one way to talk to
    Upstash across the platform, so a credential change is one change.
    """
    if not REDIS_OK:
        return None
    try:
        r = requests.post(UPSTASH_URL, headers={
            'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
            json=cmd, timeout=6)
        if r.ok:
            return (r.json() or {}).get('result')
    except Exception as e:
        with _state_lock:
            _state['last_error'] = 'redis: %s' % str(e)[:100]
    return None


def _redis_key(key):
    """Hashed -- queries carry Arabic, Hebrew, Farsi, spaces and quotes."""
    return 'gdelt:cache:' + hashlib.md5(key.encode('utf-8')).hexdigest()


def _cache_get(key):
    """L1 in-process, then L2 Upstash.

    L1 is fast and dies on restart. L2 survives restarts AND is shared
    across every backend, so a query another repo already answered costs
    this one nothing. That is the whole point: on Sep 20 the ME backend
    restarted four times and every restart began from an empty cache.
    """
    hit = _cache.get(key)
    if hit:
        expires, data = hit
        if _now() <= expires:
            return data
        _cache.pop(key, None)

    if not REDIS_OK:
        return None
    raw = _redis(['GET', _redis_key(key)])
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    _cache[key] = (_now() + CACHE_TTL_SEC, data)   # promote into L1
    with _state_lock:
        _state['redis_hits'] += 1
    return data


def _cache_put(key, data):
    _cache[key] = (_now() + CACHE_TTL_SEC, data)
    if len(_cache) > 400:                     # bounded; oldest out first
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(k, None)
    if not REDIS_OK or not data:
        return

    def _write():
        # Fire-and-forget: a failed cache write costs one future miss and
        # must never add latency to a request that already succeeded.
        try:
            _redis(['SET', _redis_key(key), json.dumps(data),
                    'EX', str(SHARED_CACHE_TTL_SEC)])
            with _state_lock:
                _state['redis_writes'] += 1
        except Exception:
            pass
    threading.Thread(target=_write, daemon=True).start()


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


# ════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ════════════════════════════════════════════════════════════════════
# Call with _state_lock held.

def _maybe_new_cycle():
    """A long silence means the last scan finished. Start clean.

    v2.1: 'clean' no longer means 'forget that GDELT was throttling us'.
    A recent 429 keeps the slower interval, because the thing that caused
    it -- our own request volume -- has not changed just because the
    breaker sat out a cooldown.
    """
    if _state['last_call'] and (_now() - _state['last_call']) > CYCLE_IDLE_SEC:
        if _now() < _state['throttled_until']:
            _state['interval'] = max(_state['interval'], BACKOFF_INTERVAL)
        else:
            _state['interval'] = MIN_INTERVAL_SEC
        _state['consecutive_fail'] = 0
        _state['cycles'] += 1
        # v2.3 -- the budget is NOT reset here. That was the v2.2 bug: a
        # 300s breaker cooldown looks exactly like an idle gap, so the
        # budget refreshed itself every time the breaker tripped and never
        # bound at all. See _maybe_new_window().
        if _state['circuit'] == OPEN and _now() >= _state['circuit_open_until']:
            _state['circuit'] = HALF_OPEN


def _maybe_new_window():
    """Roll the budget window on its own wall clock.

    Deliberately independent of _maybe_new_cycle(). A breaker cooldown, a
    quiet period, a restarted scan -- none of them are reasons to hand out
    a fresh allowance of requests to a service that is rate-limiting us.
    Call with _state_lock held.
    """
    now = _now()
    if not _state['window_start']:
        _state['window_start'] = now
        return
    if now - _state['window_start'] >= BUDGET_WINDOW_SEC:
        _state['window_start'] = now
        _state['window_calls'] = 0
        _state['requests_seen'] = 0
        _state['budget_skips'] = 0
        _state['windows'] += 1
        _window_keys.clear()
        _label_spend.clear()


def _admit(tag):
    """Decide whether this call may reach GDELT.

    Returns (allowed, is_probe). The half-open probe is what v1.0 lacked:
    without it, the only way out of an open breaker was a success on the
    single attempt the expired cooldown happened to allow, evaluated
    against a failure counter that had never been cleared.
    """
    _maybe_new_cycle()
    _maybe_new_window()

    if _state['circuit'] == OPEN:
        if _now() < _state['circuit_open_until']:
            _state['circuit_skips'] += 1
            _label_bump(tag, 'circuit_refused')
            _state['skips_since_log'] += 1
            if _state['skips_since_log'] == 1 or \
                    _state['skips_since_log'] % SKIP_LOG_EVERY == 0:
                print('[GDELT Gateway] %s: circuit open, %ds remaining '
                      '(%d calls skipped)'
                      % (tag, int(_state['circuit_open_until'] - _now()),
                         _state['skips_since_log']))
            return False, False
        # Cooldown served. Clear the counter so the probe is judged on its
        # own merits rather than on a stale tally.
        _state['circuit'] = HALF_OPEN
        _state['consecutive_fail'] = 0
        print('[GDELT Gateway] %s: cooldown served after %d skipped calls '
              '-- probing' % (tag, _state['skips_since_log']))
        _state['skips_since_log'] = 0

    # The budget. gdelt_fetch checks the cache BEFORE calling this, so a
    # cached answer is always free; only calls that would actually reach
    # GDELT are counted. A probe is exempt: refusing the one request that
    # could close the breaker would wedge it open for the whole window.
    if _state['circuit'] != HALF_OPEN and \
            _state['window_calls'] >= MAX_CALLS_PER_WINDOW:
        _state['budget_skips'] += 1
        _label_bump(tag, 'budget_refused')
        if _state['budget_skips'] == 1 or _state['budget_skips'] % 50 == 0:
            print('[GDELT Gateway] %s: budget spent (%d/%d calls this '
                  '%dmin window); %d further requests refused. This is a '
                  'BUDGET stand-down, not a GDELT outage.'
                  % (tag, _state['window_calls'], MAX_CALLS_PER_WINDOW,
                     BUDGET_WINDOW_SEC // 60, _state['budget_skips']))
        return False, False

    if _state['circuit'] == HALF_OPEN:
        if _state['probe_in_flight']:
            _state['circuit_skips'] += 1
            _label_bump(tag, 'circuit_refused')
            return False, False
        _state['probe_in_flight'] = True
        return True, True

    return True, False


def _record_success(is_probe, n_articles):
    with _state_lock:
        _state['ok'] += 1
        _state['articles'] += n_articles
        _state['consecutive_fail'] = 0
        if is_probe:
            _state['probe_in_flight'] = False
        if _state['circuit'] != CLOSED:
            print('[GDELT Gateway] circuit CLOSED -- GDELT answering again')
        _state['circuit'] = CLOSED


def _record_failure(is_probe, reason):
    """Returns True if this failure opened (or reopened) the breaker."""
    with _state_lock:
        _state['last_error'] = str(reason)[:160]
        _state['consecutive_fail'] += 1
        if is_probe:
            _state['probe_in_flight'] = False
        # A failed probe reopens immediately -- it is direct evidence that
        # GDELT is still unwell, and waiting for another three failures
        # would just mean three more doomed requests.
        tripped = (is_probe and _state['circuit'] == HALF_OPEN) or \
                  _state['consecutive_fail'] >= FAILURE_CIRCUIT
        if tripped:
            _state['circuit'] = OPEN
            _state['circuit_open_until'] = _now() + CIRCUIT_COOLDOWN
            _state['circuit_opens'] += 1
            _state['skips_since_log'] = 0
            print('[GDELT Gateway] circuit OPEN for %ds (%s)'
                  % (CIRCUIT_COOLDOWN, str(reason)[:80]))
        return tripped


def gdelt_fetch(query, language='eng', timespan='3d', maxrecords=75, label='',
                refresh=False):
    """
    Fetch from GDELT through the shared gateway.

    Returns a list of article dicts -- empty on failure, never None, never
    fabricated. Callers keep their own fallback logic; this only makes the
    attempt survivable.

    refresh=True skips the cache READ for this query only, and still writes
    the fresh result back. That is what a user pressing Refresh on a
    regional page should pass; every existing caller keeps the default and
    is unaffected.
    """
    tag = label or language
    cache_key = '%s|%s|%s|%s' % (query, language, timespan, maxrecords)

    with _state_lock:
        _maybe_new_window()
        _state['requests_seen'] += 1
        _state['requests_total'] += 1
        _window_keys.add(cache_key)
        _label_bump(tag, 'requests')

    if not refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            with _state_lock:
                _state['cache_hits'] += 1
                _label_bump(tag, 'cache_hits')
            return list(cached)

    with _state_lock:
        allowed, is_probe = _admit(tag)
    if not allowed:
        return []

    try:
        return _do_fetch(query, language, timespan, maxrecords, tag,
                         cache_key, is_probe)
    except Exception as e:
        # Belt and braces: a probe must never be left in flight, or the
        # breaker would wedge half-open and admit nothing at all -- the
        # same failure mode as v1.0 wearing a different hat.
        _record_failure(is_probe, e)
        print('[GDELT Gateway] %s: unexpected %s: %s'
              % (tag, type(e).__name__, str(e)[:110]))
        return []


def _do_fetch(query, language, timespan, maxrecords, tag, cache_key, is_probe):
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
                    _state['window_calls'] += 1
                    _label_bump(tag, 'calls')
                    _state['timeouts'] += 1
                print('[GDELT Gateway] %s: timeout after %ds (attempt %d/%d)'
                      % (tag, READ_TIMEOUT, attempt + 1, MAX_RETRIES + 1))
                if attempt < MAX_RETRIES and not is_probe:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                _record_failure(is_probe, 'timeout after %ds' % READ_TIMEOUT)
                return []
            except Exception as e:
                with _state_lock:
                    _state['last_call'] = _now()
                    _state['calls'] += 1
                    _state['window_calls'] += 1
                    _label_bump(tag, 'calls')
                _record_failure(is_probe, e)
                print('[GDELT Gateway] %s: %s: %s' % (tag, type(e).__name__, str(e)[:110]))
                return []

            with _state_lock:
                _state['last_call'] = _now()
                _state['calls'] += 1
                _state['window_calls'] += 1
                _label_bump(tag, 'calls')

            if resp.status_code == 429:
                with _state_lock:
                    _state['rate_limited'] += 1
                    # Slow the whole process down for the rest of the cycle
                    # rather than letting each caller retry into the wall.
                    _state['interval'] = max(_state['interval'], BACKOFF_INTERVAL)
                    # v2.1 -- and remember it past the next cycle reset.
                    _state['throttled_until'] = _now() + THROTTLE_MEMORY_SEC
                print('[GDELT Gateway] %s: 429 -- interval raised to %.1fs'
                      % (tag, _state['interval']))
                if attempt < MAX_RETRIES and not is_probe:
                    time.sleep(BACKOFF_INTERVAL)
                    continue
                _record_failure(is_probe, 'HTTP 429 rate limited')
                return []

            if resp.status_code != 200:
                _record_failure(is_probe, 'HTTP %s' % resp.status_code)
                print('[GDELT Gateway] %s: HTTP %s' % (tag, resp.status_code))
                return []

            try:
                articles = _parse(resp.json())
            except Exception:
                # GDELT intermittently returns HTML or truncated JSON on 200.
                _record_failure(is_probe, 'unparseable body on HTTP 200')
                print('[GDELT Gateway] %s: unparseable body (%d bytes)'
                      % (tag, len(resp.content or b'')))
                return []

            # A 200 carrying an empty article list is a SUCCESS, not a
            # failure: GDELT was reached and answered. Counting it as a
            # failure would let a quiet query open the breaker for
            # everybody, which is the reverse of what a breaker is for.
            with _state_lock:
                _label_bump(tag, 'articles', len(articles))
            _record_success(is_probe, len(articles))
            _cache_put(cache_key, articles)
            print('[GDELT Gateway] %s: %d articles' % (tag, len(articles)))
            return articles

    _record_failure(is_probe, 'retries exhausted')
    return []


def gateway_stats():
    """Operational snapshot -- wire this into a /debug endpoint.

    v1.0 had this function and nothing ever called it, so an hour of
    total lockout was only visible to whoever happened to read the logs.
    """
    with _state_lock:
        s = dict(_state)
    total = max(s['calls'], 1)
    s['success_rate'] = round(s['ok'] / total, 2)
    s['interval_now'] = round(s['interval'], 2)
    s['circuit_state'] = s['circuit']
    s['circuit_open'] = s['circuit'] == OPEN and _now() < s['circuit_open_until']
    s['circuit_remaining_sec'] = max(0, int(s['circuit_open_until'] - _now())) \
        if s['circuit_open'] else 0
    s['gateway_version'] = __version__
    s['cache_entries'] = len(_cache)
    # v2.3 -- these three are now all WINDOW-scoped, so they are directly
    # comparable. In v2.2 requests_seen was cumulative and distinct was
    # per-cycle, and comparing them was meaningless.
    s['distinct_queries'] = len(_window_keys)
    s['budget_max'] = MAX_CALLS_PER_WINDOW
    s['budget_left'] = max(0, MAX_CALLS_PER_WINDOW - s['window_calls'])
    s['budget_window_min'] = BUDGET_WINDOW_SEC // 60
    s['window_age_sec'] = int(_now() - s['window_start']) if s['window_start'] else 0
    s['min_interval'] = MIN_INTERVAL_SEC
    with _state_lock:
        s['spend_by_label'] = {k: dict(v) for k, v in sorted(
            _label_spend.items(), key=lambda kv: -kv[1]['requests'])}
    s['shared_cache'] = 'upstash' if REDIS_OK else 'in-process only'
    s['shared_cache_ttl_h'] = round(SHARED_CACHE_TTL_SEC / 3600.0, 1)
    s['throttled'] = _now() < s['throttled_until']
    s['throttled_remaining_sec'] = max(0, int(s['throttled_until'] - _now()))
    s['generated_at'] = datetime.now(timezone.utc).isoformat()
    s['note'] = ('Serialised, paced, budgeted GDELT access. A zero article '
                 'count with timeouts logged means the gateway could not reach '
                 'GDELT -- it does NOT mean the world was quiet. circuit_skips '
                 'high with circuit_opens=1 means the breaker latched (gateway '
                 'fault). budget_skips high means we asked for more than the '
                 'window allows -- read spend_by_label to see who asked.')
    return s


def reset_cycle():
    """Relax the backoff at the start of a scan cycle.

    Kept for callers who want to be explicit. It is no longer required --
    _maybe_new_cycle() does this automatically after CYCLE_IDLE_SEC --
    because in v1.0 this function was the only thing that cleared the
    failure counter and no caller in any repo ever imported it.
    """
    with _state_lock:
        _state['interval'] = MIN_INTERVAL_SEC
        _state['consecutive_fail'] = 0
        if _state['circuit'] == OPEN and _now() >= _state['circuit_open_until']:
            _state['circuit'] = HALF_OPEN


# ============================================================
# SELF-TEST
# ============================================================
if __name__ == '__main__':
    print('GDELT Gateway v%s -- self-test\n' % __version__)

    _real_get = requests.get
    calls = {'n': 0}

    class FakeResp:
        def __init__(self, code=200, body=None):
            self.status_code = code
            self._b = body if body is not None else {'articles': [
                {'title': 'Cuba blackout deepens', 'url': 'http://x', 'domain': 'granma.cu'},
                {'title': 'Havana fuel queues', 'url': 'http://y', 'domain': '14ymedio.com'}]}
            self.content = b'{}'
        def json(self): return self._b

    def _fresh():
        """Reset all module state between tests."""
        _cache.clear()
        _window_keys.clear()
        _label_spend.clear()
        calls['n'] = 0
        with _state_lock:
            _state.update({
                'last_call': 0.0, 'interval': MIN_INTERVAL_SEC,
                'consecutive_fail': 0, 'circuit': CLOSED,
                'circuit_open_until': 0.0, 'circuit_opens': 0,
                'probe_in_flight': False, 'skips_since_log': 0,
                'last_error': '', 'cycles': 0,
                'calls': 0, 'ok': 0, 'timeouts': 0, 'rate_limited': 0,
                'cache_hits': 0, 'circuit_skips': 0, 'articles': 0,
                'throttled_until': 0.0, 'window_start': 0.0,
                'window_calls': 0, 'windows': 0, 'budget_skips': 0,
                'redis_hits': 0, 'redis_writes': 0,
                'requests_seen': 0, 'requests_total': 0,
            })

    def ok_get(url, **k):
        calls['n'] += 1
        return FakeResp()

    def fail_get(url, **k):
        calls['n'] += 1
        raise requests.exceptions.Timeout('simulated')

    # ---------------------------------------------------------------
    print('TEST 1 -- pacing: sequential calls respect MIN_INTERVAL')
    _fresh(); requests.get = ok_get
    t0 = time.time()
    for i in range(4):
        gdelt_fetch('Q%d' % i, language='eng', label='t%d' % i)
    elapsed = time.time() - t0
    assert elapsed >= MIN_INTERVAL_SEC * 2, elapsed
    print('  4 calls in %.2fs -- queued, not stampeding\n' % elapsed)

    print('TEST 2 -- cache: identical query costs nothing')
    before = calls['n']
    r = gdelt_fetch('Q0', language='eng', label='repeat')
    assert calls['n'] == before and len(r) == 2
    print('  duplicate served from cache\n')

    print('TEST 3 -- concurrency: 6 threads serialise to 1 in flight')
    _fresh()
    peak = {'max': 0, 'cur': 0}
    olock = threading.Lock()
    def tracking_get(url, **k):
        with olock:
            peak['cur'] += 1; peak['max'] = max(peak['max'], peak['cur'])
        time.sleep(0.05)
        with olock:
            peak['cur'] -= 1
        return FakeResp()
    requests.get = tracking_get
    ts = [threading.Thread(target=gdelt_fetch, args=('CQ%d' % i,),
                           kwargs={'label': 'c%d' % i}) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert peak['max'] == 1, peak['max']
    print('  peak concurrent requests: 1 (was the original root cause)\n')

    print('TEST 4 -- THE v1.0 BUG: breaker must not latch permanently')
    _fresh(); requests.get = fail_get
    for i in range(FAILURE_CIRCUIT):
        gdelt_fetch('F%d' % i, label='fail%d' % i)
    s = gateway_stats()
    assert s['circuit_state'] == OPEN, s['circuit_state']
    print('  %d failures -> circuit %s (correct)' % (FAILURE_CIRCUIT, s['circuit_state']))

    skipped_before = gateway_stats()['circuit_skips']
    for i in range(200):
        gdelt_fetch('S%d' % i, label='skip')
    s = gateway_stats()
    assert s['circuit_skips'] - skipped_before == 200
    print('  200 calls during cooldown skipped without touching the network')

    # Serve the cooldown, then let GDELT recover.
    with _state_lock:
        _state['circuit_open_until'] = _now() - 1
    requests.get = ok_get
    out = gdelt_fetch('PROBE', label='probe')
    s = gateway_stats()
    print('  after cooldown + healthy GDELT: circuit=%s, articles=%d'
          % (s['circuit_state'], len(out)))
    assert s['circuit_state'] == CLOSED, s['circuit_state']
    assert len(out) == 2
    print('  OK -- breaker RECOVERS. v1.0 could not: consecutive_fail was')
    print('       never cleared, so the first post-cooldown failure')
    print('       re-tripped it forever.\n')

    print('TEST 5 -- failed probe reopens rather than wedging')
    _fresh(); requests.get = fail_get
    for i in range(FAILURE_CIRCUIT):
        gdelt_fetch('F%d' % i, label='f')
    with _state_lock:
        _state['circuit_open_until'] = _now() - 1
    gdelt_fetch('PROBE', label='probe')          # probe fails
    s = gateway_stats()
    assert s['circuit_state'] == OPEN, s['circuit_state']
    assert not s['probe_in_flight'], 'probe left in flight -- would wedge'
    print('  probe failed -> circuit %s, probe_in_flight=%s\n'
          % (s['circuit_state'], s['probe_in_flight']))

    print('TEST 6 -- idle gap clears state without any caller change')
    _fresh(); requests.get = fail_get
    for i in range(FAILURE_CIRCUIT - 1):
        gdelt_fetch('F%d' % i, label='f')
    assert gateway_stats()['consecutive_fail'] == FAILURE_CIRCUIT - 1
    with _state_lock:                             # simulate a scan gap
        _state['last_call'] = _now() - (CYCLE_IDLE_SEC + 5)
    requests.get = ok_get
    gdelt_fetch('NEWCYCLE', label='newcycle')
    s = gateway_stats()
    assert s['consecutive_fail'] == 0 and s['cycles'] == 1
    print('  new cycle detected: consecutive_fail cleared, cycles=%d' % s['cycles'])
    print('  OK -- no caller has ever imported reset_cycle(); now it is')
    print('       no longer required.\n')

    print('TEST 7 -- HTTP 200 with zero articles is success, not failure')
    _fresh()
    requests.get = lambda url, **k: FakeResp(200, {'articles': []})
    for i in range(FAILURE_CIRCUIT + 2):
        gdelt_fetch('EMPTY%d' % i, label='empty')
    s = gateway_stats()
    assert s['circuit_state'] == CLOSED, s['circuit_state']
    print('  %d empty-but-valid responses -> circuit %s'
          % (FAILURE_CIRCUIT + 2, s['circuit_state']))
    print('  OK -- a quiet query cannot open the breaker for everyone.\n')

    print('TEST 8 -- 429 raises the interval')
    _fresh()
    requests.get = lambda url, **k: FakeResp(429)
    gdelt_fetch('RL', label='ratelimited')
    s = gateway_stats()
    assert s['interval_now'] >= BACKOFF_INTERVAL
    print('  interval now %.1fs, rate_limited=%d\n'
          % (s['interval_now'], s['rate_limited']))

    print('TEST 9 -- timeout is honest, never fabricated')
    _fresh(); requests.get = fail_get
    out = gdelt_fetch('TO', label='timeout')
    s = gateway_stats()
    assert out == [] and s['timeouts'] > 0
    print('  returned %r, timeouts=%d\n' % (out, s['timeouts']))

    print('TEST 10 -- v2.2 BUG: a breaker cooldown must not refill the budget')
    _fresh(); requests.get = ok_get
    _saved_budget = MAX_CALLS_PER_WINDOW
    globals()['MAX_CALLS_PER_WINDOW'] = 5
    for i in range(5):
        gdelt_fetch('B%d' % i, label='budget')
    assert gateway_stats()['budget_left'] == 0
    # Simulate exactly what broke v2.2: a long idle gap (breaker cooldown).
    with _state_lock:
        _state['last_call'] = _now() - (CYCLE_IDLE_SEC + 5)
    gdelt_fetch('AFTER_COOLDOWN', label='budget')
    s = gateway_stats()
    print('  after a %ds idle gap: budget_left=%d, budget_skips=%d'
          % (CYCLE_IDLE_SEC + 5, s['budget_left'], s['budget_skips']))
    assert s['budget_left'] == 0, 'budget refilled -- the v2.2 bug is back'
    assert s['budget_skips'] >= 1
    print('  OK -- the budget held. v2.2 would have handed out 5 more.\n')

    print('TEST 11 -- the window DOES roll on its own clock')
    with _state_lock:
        _state['window_start'] = _now() - (BUDGET_WINDOW_SEC + 1)
    gdelt_fetch('NEW_WINDOW', label='budget')
    s = gateway_stats()
    print('  window rolled: windows=%d, budget_left=%d'
          % (s['windows'], s['budget_left']))
    assert s['windows'] == 1 and s['budget_left'] == MAX_CALLS_PER_WINDOW - 1
    globals()['MAX_CALLS_PER_WINDOW'] = _saved_budget
    print('  OK -- time, and only time, refills the budget.\n')

    print('TEST 12 -- spend attribution names the spender')
    _fresh(); requests.get = ok_get
    for i in range(6):
        gdelt_fetch('MIL%d' % i, label='me/ara')
    for i in range(2):
        gdelt_fetch('HUM%d' % i, label='humanitarian/eng')
    gdelt_fetch('MIL0', label='me/ara')            # cache hit
    s = gateway_stats()
    for lbl, rec in s['spend_by_label'].items():
        print('  %-20s requests=%d calls=%d cache_hits=%d articles=%d'
              % (lbl, rec['requests'], rec['calls'],
                 rec['cache_hits'], rec['articles']))
    assert s['spend_by_label']['me/ara']['calls'] == 6
    assert s['spend_by_label']['me/ara']['cache_hits'] == 1
    assert s['spend_by_label']['humanitarian/eng']['calls'] == 2
    print('  OK -- this is the list we trim query sets from.\n')

    print('TEST 13 -- requests_seen and distinct_queries share a scope')
    _fresh(); requests.get = ok_get
    for i in range(5):
        gdelt_fetch('D%d' % i, label='scope')
    for i in range(3):
        gdelt_fetch('D0', label='scope')           # repeats
    s = gateway_stats()
    print('  requests_seen=%d distinct=%d requests_total=%d'
          % (s['requests_seen'], s['distinct_queries'], s['requests_total']))
    assert s['requests_seen'] == 8 and s['distinct_queries'] == 5
    print('  OK -- comparable at last; v2.2 compared cumulative to per-cycle.\n')

    print('TEST 14 -- stats payload is JSON-serialisable')
    import json as _json
    _json.dumps(gateway_stats())
    print('  OK -- a set or a lock in _state would break every endpoint.\n')

    requests.get = _real_get
    print('ALL GATEWAY TESTS PASSED')
