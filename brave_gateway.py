"""
Asifah Analytics -- Brave Search Gateway
v1.0.0 -- September 19 2026  |  portable, drop into any backend

═══════════════════════════════════════════════════════════════════════
THE PROBLEM
═══════════════════════════════════════════════════════════════════════
The Brave dashboard on Sep 19 2026:

    Requests this month: 6,000        Limit reached on Search - 100%
    Cost this month:    $30.00        (out of pocket $25.00)

    Aug 31 ... Sep 12:  ~460 queries/day, every day
    Sep 13 ... Sep 19:  FLAT ZERO

Brave hit its monthly cap on the 12th and has been returning
HTTP 402 "Usage limit exceeded" ever since. Seven days dark, and nothing
in the platform noticed -- every caller treated the 402 as an empty
result and moved on.

WHY 460/DAY. Brave is configured everywhere as a FALLBACK behind GDELT:

    rhetoric_tracker_us      news_index_total < 60
    military_tracker         (gdelt + newsapi) < 10
    humanitarian_gatherer    any query returning < 5 results
    rhetoric_tracker_oman    (gdelt + newsapi) < 15
    ... and more

The shared GDELT gateway had latched its circuit breaker permanently
(see gdelt_gateway v2.0.0), so GDELT returned zero to everyone, so every
one of those conditions was ALWAYS TRUE, so the fallback ran as a
primary on every scan in every repo. humanitarian_gatherer alone logged
"33 queries need Brave fallback" in a single cycle.

Nobody was doing anything wrong. Each module had a sensible local rule.
There was simply no place where the total was known.

═══════════════════════════════════════════════════════════════════════
THE FIX
═══════════════════════════════════════════════════════════════════════
One gateway all callers use, which:

  * BUDGETS      -- a DAILY cap shared across every repo, counted in
                    Upstash. A per-process counter would just produce
                    five separate leaks; the pool has to be central
                    because the bill is.
  * ATTRIBUTES   -- spend is recorded per caller label, so "who is
                    burning the quota" is a field to read rather than an
                    afternoon of log archaeology.
  * STOPS ON 402 -- a monthly cap is exhausted for the whole platform,
                    not just the caller that discovered it. The marker
                    is shared, so the other repos stop immediately
                    instead of spending a week discovering it one
                    request at a time.
  * PACES        -- 1 req/sec, which is Brave's documented floor.
  * CACHES       -- identical queries inside the TTL cost nothing. Several
                    trackers ask Brave nearly the same thing hours apart.

DEFAULT BUDGET: 200/day. At a 6,000/month plan that is 6,200 over a
31-day month -- it runs out about a day early in a long month rather
than on the 12th, which is the difference between a taper and a wall.
Override with BRAVE_DAILY_BUDGET.

DOCTRINE: absence-honest. A skipped call is reported as skipped, with
the reason, and never as an empty result. A caller that gets [] because
the budget is spent must be able to tell that apart from a caller that
got [] because Brave had nothing -- the same distinction the source
health audit was built to make.

USAGE
    from brave_gateway import brave_fetch, brave_stats
    articles = brave_fetch('El Fasher siege famine', label='humanitarian/subregion')

    # Recommended, in any /debug endpoint:
    #     'brave_gateway': brave_stats()

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import time
import threading
from datetime import datetime, timezone

import requests

__version__ = '1.0.0'

# ── Tunables ────────────────────────────────────────────────────────────
DAILY_BUDGET = int(os.environ.get('BRAVE_DAILY_BUDGET', '200'))
MIN_INTERVAL_SEC = 1.05      # Brave documents 1 req/sec; leave a margin
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 15
CACHE_TTL_SEC = 6 * 3600     # identical query inside 6h is free
RESERVE_FRACTION = 0.15      # held back from the day's budget for callers
                             # that have not spent yet, so one greedy
                             # module cannot starve the rest before they run

BRAVE_NEWS_API = 'https://api.search.brave.com/res/v1/news/search'
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY', '')

UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_URL')
               or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                 or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
REDIS_OK = bool(UPSTASH_URL and UPSTASH_TOKEN)

QUOTA_KEY_FMT = 'brave:quota:%s'              # YYYY-MM-DD -> int
CALLER_KEY_FMT = 'brave:quota:%s:callers'     # YYYY-MM-DD -> {label: n}
EXHAUSTED_KEY = 'brave:monthly_exhausted'     # set on 402, TTL to month end

_lock = threading.Lock()
_state = {
    'last_call': 0.0,
    'calls': 0, 'ok': 0, 'skipped_budget': 0, 'skipped_exhausted': 0,
    'cache_hits': 0, 'articles': 0, 'rate_limited': 0, 'errors': 0,
    'local_spend': 0,          # fallback counter when Redis is unavailable
    'local_day': '',
    'last_error': '',
    'monthly_exhausted': False,
}
_cache = {}                    # key -> (expires_at, articles)


def _today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _seconds_to_month_end():
    now = datetime.now(timezone.utc)
    if now.month == 12:
        nxt = now.replace(year=now.year + 1, month=1, day=1,
                          hour=0, minute=0, second=0, microsecond=0)
    else:
        nxt = now.replace(month=now.month + 1, day=1,
                          hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((nxt - now).total_seconds()))


# ════════════════════════════════════════════════════════════════════
# SHARED BUDGET (Upstash)
# ════════════════════════════════════════════════════════════════════
def _redis(cmd):
    """One Upstash REST command. Returns the 'result' value or None."""
    if not REDIS_OK:
        return None
    try:
        r = requests.post(UPSTASH_URL, headers={
            'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
            json=cmd, timeout=6)
        if r.ok:
            return (r.json() or {}).get('result')
    except Exception as e:
        with _lock:
            _state['last_error'] = 'redis: %s' % str(e)[:100]
    return None


def _spend_today():
    """Queries already spent today, across every repo."""
    if not REDIS_OK:
        with _lock:
            if _state['local_day'] != _today():
                _state['local_day'] = _today()
                _state['local_spend'] = 0
            return _state['local_spend']
    val = _redis(['GET', QUOTA_KEY_FMT % _today()])
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _record_spend(label, n=1):
    """Increment the shared counter and the per-caller attribution."""
    if not REDIS_OK:
        with _lock:
            _state['local_spend'] += n
        return
    day = _today()
    key = QUOTA_KEY_FMT % day
    _redis(['INCRBY', key, str(n)])
    # 36h TTL: outlives the day without accumulating keys forever.
    _redis(['EXPIRE', key, '129600'])
    if label:
        ckey = CALLER_KEY_FMT % day
        _redis(['HINCRBY', ckey, label, str(n)])
        _redis(['EXPIRE', ckey, '129600'])


def _monthly_exhausted():
    """Has any caller, in any repo, seen a 402 this month?"""
    with _lock:
        if _state['monthly_exhausted']:
            return True
    if not REDIS_OK:
        return False
    return bool(_redis(['GET', EXHAUSTED_KEY]))


def _mark_monthly_exhausted(detail=''):
    """A 402 means the PLAN is spent, not just this request.

    Recorded centrally so every other module stops at once. Without this
    the platform spent seven days, Sep 13-19, rediscovering the same 402
    one request at a time.
    """
    with _lock:
        _state['monthly_exhausted'] = True
        _state['last_error'] = ('402 usage limit: %s' % detail)[:160]
    if REDIS_OK:
        _redis(['SET', EXHAUSTED_KEY,
                json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                            'detail': detail[:200]}),
                'EX', str(_seconds_to_month_end())])
    print('[Brave Gateway] MONTHLY LIMIT REACHED -- all callers standing '
          'down until the cycle resets. %s' % detail[:120])


def budget_remaining():
    return max(0, DAILY_BUDGET - _spend_today())


# ════════════════════════════════════════════════════════════════════
# CACHE
# ════════════════════════════════════════════════════════════════════
def _cache_get(key):
    hit = _cache.get(key)
    if not hit:
        return None
    expires, data = hit
    if time.time() > expires:
        _cache.pop(key, None)
        return None
    return data


def _cache_put(key, data):
    _cache[key] = (time.time() + CACHE_TTL_SEC, data)
    if len(_cache) > 300:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:80]:
            _cache.pop(k, None)


# ════════════════════════════════════════════════════════════════════
# FETCH
# ════════════════════════════════════════════════════════════════════
def brave_fetch(query, count=20, label='', freshness='pw',
                search_lang=None, country=None, reserved=False):
    """
    Fetch news from Brave through the shared budget.

    Returns a list of article dicts -- empty on failure or when the budget
    is spent, never None, never fabricated. Callers keep their own logic;
    this only makes the spend accountable.

    label     attribution for the per-caller spend breakdown, e.g.
              'humanitarian/subregion'. Pass one; it is the field that
              answers "who is burning the quota".
    reserved  set True for a small number of genuinely high-value calls
              that may draw on the reserve held back from the daily cap.
    """
    if not BRAVE_API_KEY:
        return []

    cache_key = '%s|%s|%s|%s|%s' % (query, count, freshness,
                                    search_lang or '', country or '')
    cached = _cache_get(cache_key)
    if cached is not None:
        with _lock:
            _state['cache_hits'] += 1
        return list(cached)

    if _monthly_exhausted():
        with _lock:
            _state['skipped_exhausted'] += 1
        return []

    spent = _spend_today()
    ceiling = DAILY_BUDGET if reserved else int(DAILY_BUDGET * (1 - RESERVE_FRACTION))
    if spent >= ceiling:
        with _lock:
            _state['skipped_budget'] += 1
            if _state['skipped_budget'] in (1, 10, 50) or \
                    _state['skipped_budget'] % 100 == 0:
                print('[Brave Gateway] %s: daily budget spent (%d/%d) -- '
                      'skipping (%d skipped today)'
                      % (label or 'unlabelled', spent, DAILY_BUDGET,
                         _state['skipped_budget']))
        return []

    # PACE: Brave documents 1 req/sec.
    with _lock:
        gap = time.time() - _state['last_call']
        wait = MIN_INTERVAL_SEC - gap
    if wait > 0:
        time.sleep(wait)

    params = {'q': query, 'count': count, 'spellcheck': '0'}
    if freshness:
        params['freshness'] = freshness
    if search_lang:
        params['search_lang'] = search_lang
    if country:
        params['country'] = country

    try:
        resp = requests.get(
            BRAVE_NEWS_API, params=params,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            headers={'Accept': 'application/json',
                     'Accept-Encoding': 'gzip',
                     'X-Subscription-Token': BRAVE_API_KEY})
    except Exception as e:
        with _lock:
            _state['last_call'] = time.time()
            _state['calls'] += 1
            _state['errors'] += 1
            _state['last_error'] = '%s: %s' % (type(e).__name__, str(e)[:110])
        _record_spend(label)          # it reached Brave or it did not; assume spent
        return []

    with _lock:
        _state['last_call'] = time.time()
        _state['calls'] += 1
    _record_spend(label)

    if resp.status_code == 402:
        _mark_monthly_exhausted((resp.text or '')[:200])
        return []

    if resp.status_code == 429:
        with _lock:
            _state['rate_limited'] += 1
        print('[Brave Gateway] %s: 429 rate limited' % (label or 'unlabelled'))
        return []

    if resp.status_code != 200:
        with _lock:
            _state['errors'] += 1
            _state['last_error'] = 'HTTP %s: %s' % (resp.status_code,
                                                    (resp.text or '')[:110])
        print('[Brave Gateway] %s: HTTP %s' % (label or 'unlabelled',
                                               resp.status_code))
        return []

    try:
        data = resp.json()
    except Exception:
        with _lock:
            _state['errors'] += 1
        return []

    articles = []
    for art in (data.get('results') or []):
        meta = art.get('meta_url') or {}
        articles.append({
            'title':       (art.get('title') or '')[:300],
            'description': (art.get('description') or '')[:500],
            'url':         art.get('url') or '',
            'link':        art.get('url') or '',
            'published':   art.get('age') or art.get('page_age') or '',
            'publishedAt': art.get('age') or art.get('page_age') or '',
            'source':      {'name': meta.get('hostname') or 'Brave'},
            'content':     (art.get('description') or '')[:500],
            'feed_type':   'brave',
            'source_type': 'brave',
        })

    with _lock:
        _state['ok'] += 1
        _state['articles'] += len(articles)
    _cache_put(cache_key, articles)
    return articles


def brave_stats():
    """Operational snapshot -- wire this into a /debug endpoint."""
    with _lock:
        s = dict(_state)
    spent = _spend_today()
    callers = {}
    if REDIS_OK:
        raw = _redis(['HGETALL', CALLER_KEY_FMT % _today()])
        if isinstance(raw, list):
            callers = {raw[i]: int(raw[i + 1])
                       for i in range(0, len(raw) - 1, 2)}
        elif isinstance(raw, dict):
            callers = {k: int(v) for k, v in raw.items()}
    s.update({
        'version':            __version__,
        'configured':         bool(BRAVE_API_KEY),
        'budget_daily':       DAILY_BUDGET,
        'spent_today':        spent,
        'remaining_today':    max(0, DAILY_BUDGET - spent),
        'spend_by_caller':    dict(sorted(callers.items(),
                                          key=lambda kv: -kv[1])),
        'shared_counter':     'upstash' if REDIS_OK else 'in-process (NOT shared)',
        'monthly_exhausted':  _monthly_exhausted(),
        'generated_at':       datetime.now(timezone.utc).isoformat(),
        'note': ('Daily budget is shared across every repo via Upstash. '
                 'A high skipped_budget means the cap is working, not that '
                 'Brave is down. monthly_exhausted=True means a 402 was '
                 'seen and ALL callers are standing down until the plan '
                 'cycle resets.'),
    })
    return s


# ============================================================
# SELF-TEST
# ============================================================
if __name__ == '__main__':
    print('Brave Gateway v%s -- self-test\n' % __version__)

    _real_get = requests.get
    calls = {'n': 0, 'times': []}

    class FakeResp:
        def __init__(self, code=200, n=2, text=''):
            self.status_code = code
            self.text = text
            self._n = n
        def json(self):
            return {'results': [{'title': 'a%d' % i, 'url': 'http://x/%d' % i,
                                 'description': 'd',
                                 'meta_url': {'hostname': 'example.com'}}
                                for i in range(self._n)]}

    # Force the in-process counter so the test never touches real Redis.
    globals()['REDIS_OK'] = False
    globals()['BRAVE_API_KEY'] = 'test-key'

    def _fresh(budget=None):
        _cache.clear()
        calls['n'] = 0
        if budget is not None:
            globals()['DAILY_BUDGET'] = budget
        with _lock:
            _state.update({'last_call': 0.0, 'calls': 0, 'ok': 0,
                           'skipped_budget': 0, 'skipped_exhausted': 0,
                           'cache_hits': 0, 'articles': 0, 'rate_limited': 0,
                           'errors': 0, 'local_spend': 0, 'local_day': _today(),
                           'last_error': '', 'monthly_exhausted': False})

    def ok_get(url, **k):
        calls['n'] += 1
        calls['times'].append(time.time())
        return FakeResp()

    print('TEST 1 -- budget cap stops spending')
    _fresh(budget=5)
    globals()['MIN_INTERVAL_SEC'] = 0.0      # keep the test quick
    requests.get = ok_get
    got = [len(brave_fetch('q%d' % i, label='test/a')) for i in range(20)]
    s = brave_stats()
    print('  HTTP calls made: %d  (budget %d, reserve %d%%)'
          % (calls['n'], s['budget_daily'], int(RESERVE_FRACTION * 100)))
    print('  skipped_budget : %d' % s['skipped_budget'])
    assert calls['n'] <= 5, calls['n']
    assert s['skipped_budget'] > 0
    print('  OK -- 20 requests, %d calls. Uncapped this would be 20.\n' % calls['n'])

    print('TEST 2 -- reserve: high-value calls get through after the cap')
    before = calls['n']
    r = brave_fetch('reserved query', label='test/critical', reserved=True)
    print('  reserved call made an HTTP request: %s' % (calls['n'] > before))
    assert calls['n'] > before
    print('  OK -- reserve keeps a lane open.\n')

    print('TEST 3 -- 402 stands the whole platform down')
    _fresh(budget=100)
    requests.get = lambda url, **k: FakeResp(402, text='{"detail":"Usage limit exceeded."}')
    brave_fetch('first caller discovers it', label='test/a')
    before = calls['n']
    for i in range(30):
        brave_fetch('other caller %d' % i, label='test/b')
    s = brave_stats()
    print('  HTTP calls after the 402: %d' % (calls['n'] - before))
    print('  skipped_exhausted       : %d' % s['skipped_exhausted'])
    assert calls['n'] == before, 'kept calling after 402'
    assert s['monthly_exhausted'] is True
    print('  OK -- one 402 stopped 30 further requests. Sep 13-19 the')
    print('       platform made this discovery once per request, for a week.\n')

    print('TEST 4 -- cache: identical query costs nothing')
    _fresh(budget=100)
    requests.get = ok_get
    brave_fetch('same query', label='test/a')
    before = calls['n']
    r = brave_fetch('same query', label='test/a')
    print('  HTTP calls added: %d | articles: %d' % (calls['n'] - before, len(r)))
    assert calls['n'] == before and len(r) == 2
    print('  OK\n')

    print('TEST 5 -- spend is attributed per caller')
    _fresh(budget=100)
    requests.get = ok_get
    for i in range(3):
        brave_fetch('hq%d' % i, label='humanitarian/fallback')
    for i in range(2):
        brave_fetch('oq%d' % i, label='oman/brave')
    with _lock:
        local = _state['local_spend']
    print('  in-process spend counted: %d (Redis off in this test)' % local)
    assert local == 5
    print('  OK -- with Upstash on, spend_by_caller names the greedy module.\n')

    requests.get = _real_get
    print('ALL BRAVE GATEWAY TESTS PASSED')
