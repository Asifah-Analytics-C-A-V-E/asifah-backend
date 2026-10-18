"""
Asifah Analytics -- NewsAPI Gateway
v1.0.0 -- October 18 2026  |  portable, drop into any backend

=======================================================================
THE PROBLEM
=======================================================================
NewsAPI's free Developer plan allows 100 requests a day (in practice
also ~50 per 12 hours), with articles delayed 24 hours. On 18 Oct 2026
36 files across the 5 backends called it directly -- 69 queries per
Africa scan alone, 39 per WHA scan, every scan run twice (2 Render
instances) -- so the day's allowance was gone within minutes of
midnight and every caller then did:

    if response.status_code != 200:
        return []

A spent quota looked exactly like "no news". It never appeared in a log.

=======================================================================
THE FIX -- same shape as brave_gateway / gdelt_gateway
=======================================================================
  * ONE KEY, ONE DOOR  -- the gateway reads NEWSAPI_GATEWAY_KEY. The old
                          NEWSAPI_KEY / NEWS_API_KEY are deleted from
                          Render, so the 31 tracker modules that still
                          call NewsAPI directly find no key and skip
                          cleanly (they already guard on it). Only the
                          five app.py scoring paths come through here.
  * FALLBACK, NOT FEED -- default NEWSAPI_MODE=fallback: a real request
                          is made only when the GDELT gateway is blind
                          (platform stand-down, circuit open, or GDELT
                          budget spent) or the caller says it is thin
                          (have=<n> below NEWSAPI_THIN_THRESHOLD).
                          Cached results are always served -- free.
  * BUDGET             -- ROLLING windows counted in Upstash, per API key:
                          platform 45 per 12h and 90 per 24h (under the
                          50/100 ceiling), and each backend 9 per 12h so
                          Africa's 69 queries cannot starve the ME.
  * ROTATION           -- results cached 24h (L1 + Upstash L2). A query
                          served today is a free cache hit tomorrow, so
                          the budget flows to the queries NOT yet served:
                          over a few days every query gets its turn
                          instead of the first nine in the list forever.
  * STATUS LOGGING     -- every real request logs HTTP status plus
                          NewsAPI's own error code/message (rateLimited,
                          apiKeyExhausted, apiKeyInvalid, ...).
  * STAND-DOWN         -- 429 / apiKeyExhausted stands the whole platform
                          down (shared Upstash marker) for 6h; an invalid
                          or disabled key for 24h.
  * KEY HYGIENE        -- key sent in the X-Api-Key header, never in a URL;
                          stats show only a short hash of it.

DOCTRINE: absence is reported, not inferred. Every call returns a probe
saying whether NewsAPI was actually sensed and, if not, why --
'primary_healthy' (a deliberate skip) is a different thing from
'budget_backend' or 'rate_limited', and none of them is "no news".

USAGE
    from newsapi_gateway import newsapi_fetch_probed, newsapi_fetch, newsapi_stats
    articles, probe = newsapi_fetch_probed('Hezbollah OR Litani', days=7,
                                           label='me/hezbollah')
    # articles are NewsAPI's native shape (title, description, url,
    # publishedAt, source{id,name}, content, author) plus language='en'.

    register_newsapi_routes(app)   # adds GET /api/newsapi/health

ENV
    NEWSAPI_GATEWAY_KEY        the key (required)
    NEWSAPI_MODE               fallback (default) | always
    NEWSAPI_THIN_THRESHOLD     default 10  (used only when caller passes have=)
    NEWSAPI_BACKEND_CAP_12H    default 9
    NEWSAPI_PLATFORM_CAP_12H   default 45
    NEWSAPI_PLATFORM_CAP_24H   default 90
    NEWSAPI_CACHE_TTL_SEC      default 86400
    NEWSAPI_STANDDOWN_SEC      default 21600
    NEWSAPI_SCOPE              default RENDER_SERVICE_NAME

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import time
import uuid
import hashlib
import threading
from datetime import datetime, timezone, timedelta

import requests

__version__ = '1.0.0'


def _env_i(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return int(default)


# -- Tunables ---------------------------------------------------------------
API_KEY            = os.environ.get('NEWSAPI_GATEWAY_KEY', '').strip()
MODE               = (os.environ.get('NEWSAPI_MODE', 'fallback') or 'fallback').strip().lower()
THIN_THRESHOLD     = _env_i('NEWSAPI_THIN_THRESHOLD', 10)
BACKEND_CAP_12H    = _env_i('NEWSAPI_BACKEND_CAP_12H', 9)
PLATFORM_CAP_12H   = _env_i('NEWSAPI_PLATFORM_CAP_12H', 45)
PLATFORM_CAP_24H   = _env_i('NEWSAPI_PLATFORM_CAP_24H', 90)
CACHE_TTL_SEC      = _env_i('NEWSAPI_CACHE_TTL_SEC', 86400)
STANDDOWN_SEC      = _env_i('NEWSAPI_STANDDOWN_SEC', 21600)
KEY_BAD_SEC        = 86400
SCOPE              = (os.environ.get('NEWSAPI_SCOPE')
                      or os.environ.get('RENDER_SERVICE_NAME') or 'local')
MIN_INTERVAL_SEC   = 1.0
TIMEOUT            = (5, 15)
GDELT_CHECK_EVERY  = 30.0
H12, H24           = 12 * 3600, 24 * 3600

NEWSAPI_URL = 'https://newsapi.org/v2/everything'
KEY_ID = hashlib.sha1(API_KEY.encode('utf-8')).hexdigest()[:8] if API_KEY else 'none'
PREFIX = 'newsapi_gw:%s:' % KEY_ID

UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_URL')
               or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                 or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))

WORKER_ID = '%s-%s' % (os.getpid(), uuid.uuid4().hex[:8])
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()

# Codes NewsAPI returns in {"status":"error","code":...}
_EXHAUSTED_CODES = ('rateLimited', 'apiKeyExhausted')
_BAD_KEY_CODES = ('apiKeyInvalid', 'apiKeyDisabled', 'apiKeyMissing')


def _now():
    return time.time()


def _sleep(s):
    time.sleep(s)


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


# -- Upstash (never raises) ---------------------------------------------------
_redis_state = {'ok': bool(UPSTASH_URL and UPSTASH_TOKEN), 'errors': 0, 'last_error': None}


def _r(cmd, timeout=4):
    resp = requests.post(UPSTASH_URL,
                         headers={'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
                         json=[str(c) for c in cmd], timeout=timeout)
    resp.raise_for_status()
    return (resp.json() or {}).get('result')


def _redis(cmd, default=None):
    if not _redis_state['ok']:
        return default
    try:
        return _r(cmd)
    except Exception as e:
        _redis_state['errors'] += 1
        _redis_state['last_error'] = '%s: %s' % (type(e).__name__, str(e)[:120])
        return default


def _shared():
    return bool(_redis_state['ok'])


# -- Process state --------------------------------------------------------------
_lock = threading.Lock()
_http_lock = threading.Lock()
_state = {
    'requests_seen': 0, 'http_calls': 0, 'ok': 0, 'articles': 0,
    'l1_hits': 0, 'l2_hits': 0, 'last_call': 0.0,
    'standdown_until': 0.0, 'standdown_checked_at': 0.0, 'standdown_info': None,
    'gdelt_checked_at': 0.0, 'gdelt_blind': None, 'gdelt_why': '',
    'last_error': '', 'budget_block_until': 0.0, 'budget_block_reason': '',
}
_skips = {}            # reason -> count (this process)
_local_spend = []      # timestamps, used only when Upstash is unavailable
_l1 = {}               # cache key -> (expires_at, articles)
_recent = []           # last 25 outcomes, newest last


def _note(label, query, reason, n=0, status=None):
    with _lock:
        _recent.append({'at': _iso(_now()), 'label': label or 'unlabelled',
                        'query': (query or '')[:70], 'reason': reason,
                        'articles': n, 'http_status': status})
        del _recent[:-25]


def _skip(reason, label, query):
    with _lock:
        _skips[reason] = _skips.get(reason, 0) + 1
        c = _skips[reason]
    _note(label, query, reason)
    # Log the first of each reason and then every 25th -- informative, not spam.
    if c == 1 or c % 25 == 0:
        print('[NewsAPI Gateway] %s: skipped (%s) -- not "no news" [%d %s skips this process]'
              % (label or 'unlabelled', reason, c, reason))


# -- Cache ---------------------------------------------------------------------
def _cache_key(query, days, language, page_size):
    raw = '%s|%s|%s|%s' % (query, days, language, page_size)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def _trim(a):
    """Keep what scoring reads; keeps the Upstash value small."""
    src = a.get('source') or {}
    return {
        'source': {'id': src.get('id'), 'name': src.get('name') or 'NewsAPI'},
        'author': a.get('author'),
        'title': a.get('title') or '',
        'description': (a.get('description') or '')[:600],
        'url': a.get('url') or '',
        'publishedAt': a.get('publishedAt') or '',
        'content': (a.get('content') or '')[:400],
        'language': 'en',
    }


def _cache_get(k):
    with _lock:
        hit = _l1.get(k)
    if hit and hit[0] > _now():
        with _lock:
            _state['l1_hits'] += 1
        return [dict(a) for a in hit[1]], 'l1'
    raw = _redis(['GET', PREFIX + 'c:' + k])
    if raw:
        try:
            arts = json.loads(raw)
            with _lock:
                _state['l2_hits'] += 1
                _l1[k] = (_now() + CACHE_TTL_SEC, arts)
            return [dict(a) for a in arts], 'l2'
        except (TypeError, ValueError):
            pass
    return None, None


def _cache_put(k, arts):
    with _lock:
        _l1[k] = (_now() + CACHE_TTL_SEC, arts)
        if len(_l1) > 400:
            for old in sorted(_l1, key=lambda x: _l1[x][0])[:100]:
                _l1.pop(old, None)
    _redis(['SET', PREFIX + 'c:' + k, json.dumps(arts), 'EX', CACHE_TTL_SEC])


# -- Platform stand-down -----------------------------------------------------------
def _standdown_remaining():
    now = _now()
    with _lock:
        stale = (now - _state['standdown_checked_at']) >= 10
    if stale and _shared():
        raw = _redis(['GET', PREFIX + 'standdown'])
        info = None
        if raw:
            try:
                info = json.loads(raw)
            except (TypeError, ValueError):
                info = None
        with _lock:
            _state['standdown_checked_at'] = now
            if info and float(info.get('until', 0)) > _state['standdown_until']:
                _state['standdown_until'] = float(info['until'])
                _state['standdown_info'] = info
    with _lock:
        rem = _state['standdown_until'] - now
    return rem if rem > 0 else 0


def _set_standdown(seconds, code, message, label):
    until = _now() + seconds
    info = {'until': until, 'until_iso': _iso(until), 'code': code,
            'message': (message or '')[:200], 'set_by': '%s/%s' % (SCOPE, label or '?')}
    with _lock:
        _state['standdown_until'] = max(_state['standdown_until'], until)
        _state['standdown_info'] = info
    _redis(['SET', PREFIX + 'standdown', json.dumps(info), 'EX', int(seconds)])
    print('[NewsAPI Gateway] PLATFORM STAND-DOWN %dh -- %s: %s (all backends stop until %s)'
          % (seconds // 3600, code, (message or '')[:120], info['until_iso']))


# -- Is the primary (GDELT) blind? --------------------------------------------------
def _gdelt_blind():
    """(blind, why). Reads the GDELT gateway's own shared state; cached 30s.

    Unknown counts as blind: if we cannot tell whether the primary is
    working, the fallback is allowed to work.
    """
    now = _now()
    with _lock:
        if _state['gdelt_blind'] is not None and \
                (now - _state['gdelt_checked_at']) < GDELT_CHECK_EVERY:
            return _state['gdelt_blind'], _state['gdelt_why']
    blind, why = True, 'gdelt_gateway unavailable'
    try:
        import gdelt_gateway as gg
        if gg._throttled_remaining() > 0:
            why = 'gdelt throttled'
        elif gg._now() < gg._state.get('circuit_open_until', 0):
            why = 'gdelt circuit open'
        elif gg._budget_used() >= gg.MAX_CALLS_PER_WINDOW:
            why = 'gdelt budget spent'
        else:
            blind, why = False, 'gdelt healthy'
    except Exception as e:
        why = 'gdelt state unreadable (%s)' % type(e).__name__
    with _lock:
        _state['gdelt_blind'], _state['gdelt_why'] = blind, why
        _state['gdelt_checked_at'] = now
    return blind, why


# -- Rolling budget (Upstash sorted sets) -------------------------------------------
def _zkey_platform():
    return PREFIX + 'spend'


def _zkey_backend():
    return PREFIX + 'spend:' + SCOPE


def _usage():
    """{'backend_12h', 'platform_12h', 'platform_24h', 'layer'}"""
    now = _now()
    if _shared():
        pk, bk = _zkey_platform(), _zkey_backend()
        _redis(['ZREMRANGEBYSCORE', pk, '-inf', '%.3f' % (now - H24)])
        _redis(['ZREMRANGEBYSCORE', bk, '-inf', '%.3f' % (now - H24)])
        p24 = _redis(['ZCARD', pk])
        p12 = _redis(['ZCOUNT', pk, '%.3f' % (now - H12), '+inf'])
        b12 = _redis(['ZCOUNT', bk, '%.3f' % (now - H12), '+inf'])
        try:
            return {'backend_12h': int(b12), 'platform_12h': int(p12),
                    'platform_24h': int(p24), 'layer': 'upstash'}
        except (TypeError, ValueError):
            pass   # Upstash answered garbage or failed mid-way -> local
    with _lock:
        _local_spend[:] = [t for t in _local_spend if t > now - H24]
        n12 = sum(1 for t in _local_spend if t > now - H12)
        return {'backend_12h': n12, 'platform_12h': n12,
                'platform_24h': len(_local_spend), 'layer': 'local_only'}


def _budget_check():
    """(allowed, reason, usage)"""
    u = _usage()
    if u['layer'] == 'local_only':
        # No shared count: every instance on every backend would spend its
        # own cap. Halve it -- under-using a fallback beats a 429.
        if u['backend_12h'] >= max(1, BACKEND_CAP_12H // 2):
            return False, 'budget_backend', u
        return True, '', u
    if u['platform_24h'] >= PLATFORM_CAP_24H or u['platform_12h'] >= PLATFORM_CAP_12H:
        return False, 'budget_platform', u
    if u['backend_12h'] >= BACKEND_CAP_12H:
        return False, 'budget_backend', u
    return True, '', u


def _budget_record(label):
    now = _now()
    member = '%.3f:%s:%s' % (now, WORKER_ID, uuid.uuid4().hex[:6])
    if _shared():
        a = _redis(['ZADD', _zkey_platform(), '%.3f' % now, member])
        b = _redis(['ZADD', _zkey_backend(), '%.3f' % now, member])
        _redis(['EXPIRE', _zkey_platform(), H24 + 3600])
        _redis(['EXPIRE', _zkey_backend(), H24 + 3600])
        day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        _redis(['HINCRBY', PREFIX + 'labels:' + day, label or 'unlabelled', 1])
        _redis(['EXPIRE', PREFIX + 'labels:' + day, 2 * H24])
        if a is not None and b is not None:
            return
    with _lock:
        _local_spend.append(now)


def _probe(sensed, reason, cached=False, layer=None, status=None, code=None, skipped=False):
    return {'sensed': sensed, 'reason': reason, 'cached': cached, 'cache_layer': layer,
            'http_status': status, 'code': code, 'skipped': skipped, 'mode': MODE}


# -- Public ---------------------------------------------------------------------------
def _derive_label(prefix, query):
    """'me' + 'Hezbollah OR Litani' -> 'me/Hezbollah' (readable spend attribution)."""
    first = (query or '').split(' OR ')[0].strip().strip('"()')
    return '%s/%s' % (prefix or 'app', first[:30] or 'query')


def newsapi_fetch_probed(query, days=7, language='en', page_size=100, label='',
                         have=None, refresh=False, sort_by='publishedAt', prefix=None):
    """Return (articles, probe). Never raises; never fabricates.

    label   explicit attribution, e.g. 'me/hezbollah'. If omitted and prefix
            is given, derived from the query: prefix='me' -> 'me/Hezbollah'.
    have    how many articles the caller already holds; below
            NEWSAPI_THIN_THRESHOLD it opens the fallback gate on its own.
    """
    with _lock:
        _state['requests_seen'] += 1
    query = (query or '').strip()
    if not label and prefix:
        label = _derive_label(prefix, query)
    if not query:
        return [], _probe(False, 'empty_query', skipped=True)
    if not API_KEY:
        _skip('no_key', label, query)
        return [], _probe(False, 'no_key', skipped=True)

    days = max(1, min(int(days or 7), 29))     # Developer plan: ~1 month of history
    page_size = max(1, min(int(page_size or 100), 100))
    k = _cache_key(query, days, language, page_size)

    # 1. Cache -- always free, always served.
    if not refresh:
        arts, layer = _cache_get(k)
        if arts is not None:
            _note(label, query, 'cached_' + layer, len(arts))
            return arts, _probe(True, 'cached', cached=True, layer=layer)

    # 2. Platform stand-down.
    rem = _standdown_remaining()
    if rem > 0:
        _skip('stand_down', label, query)
        return [], _probe(False, 'stand_down', skipped=True)

    # 3. Fallback gate.
    if MODE != 'always':
        thin = have is not None and have < THIN_THRESHOLD
        blind, why = _gdelt_blind()
        if not (thin or blind):
            _skip('primary_healthy', label, query)
            return [], _probe(False, 'primary_healthy', skipped=True)

    # 4. Budget, then one request at a time per process (paced).
    with _http_lock:
        # A spent budget stays spent for a while: remember it for 60s so a
        # 69-query Africa loop does not cost 69 x 5 Upstash commands to learn it.
        if _now() < _state['budget_block_until']:
            _skip(_state['budget_block_reason'], label, query)
            return [], _probe(False, _state['budget_block_reason'], skipped=True)
        ok, why_not, usage = _budget_check()
        if not ok:
            with _lock:
                _state['budget_block_until'] = _now() + 60
                _state['budget_block_reason'] = why_not
            _skip(why_not, label, query)
            p = _probe(False, why_not, skipped=True)
            p['usage'] = usage
            return [], p
        wait = MIN_INTERVAL_SEC - (_now() - _state['last_call'])
        if wait > 0:
            _sleep(wait)
        from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
        params = {'q': query[:500], 'from': from_date, 'sortBy': sort_by,
                  'language': language, 'pageSize': page_size}
        _budget_record(label)          # a request that leaves counts, answered or not
        with _lock:
            _state['http_calls'] += 1
            _state['last_call'] = _now()
        try:
            resp = requests.get(NEWSAPI_URL, params=params, timeout=TIMEOUT,
                                headers={'X-Api-Key': API_KEY,
                                         'User-Agent': 'AsifahAnalytics/1.0'})
        except requests.exceptions.Timeout:
            print('[NewsAPI Gateway] %s: TIMEOUT' % (label or 'unlabelled'))
            _note(label, query, 'timeout')
            with _lock:
                _state['last_error'] = 'timeout'
            return [], _probe(False, 'timeout')
        except Exception as e:
            print('[NewsAPI Gateway] %s: %s' % (label or 'unlabelled', type(e).__name__))
            _note(label, query, 'error')
            with _lock:
                _state['last_error'] = '%s: %s' % (type(e).__name__, str(e)[:100])
            return [], _probe(False, 'error')

    status = resp.status_code
    try:
        body = resp.json()
    except Exception:
        body = None

    if status == 200 and isinstance(body, dict) and body.get('status') == 'ok':
        arts = [_trim(a) for a in (body.get('articles') or [])]
        with _lock:
            _state['ok'] += 1
            _state['articles'] += len(arts)
        _cache_put(k, arts)
        print('[NewsAPI Gateway] %s: HTTP 200 -- %d articles (totalResults %s)'
              % (label or 'unlabelled', len(arts), body.get('totalResults')))
        _note(label, query, 'ok', len(arts), status)
        return [dict(a) for a in arts], _probe(True, 'ok', status=status)

    code = (body or {}).get('code') if isinstance(body, dict) else None
    msg = (body or {}).get('message') if isinstance(body, dict) else None
    if not msg:
        msg = (getattr(resp, 'text', '') or '')[:160]
    with _lock:
        _state['last_error'] = 'HTTP %s %s: %s' % (status, code or '', (msg or '')[:120])
    print('[NewsAPI Gateway] %s: HTTP %s code=%s -- %s'
          % (label or 'unlabelled', status, code, (msg or '')[:160]))

    if status == 429 or code in _EXHAUSTED_CODES:
        _set_standdown(STANDDOWN_SEC, code or 'http_%s' % status, msg, label)
        reason = 'rate_limited'
    elif status == 401 or code in _BAD_KEY_CODES:
        _set_standdown(KEY_BAD_SEC, code or 'http_401', msg, label)
        reason = 'key_invalid'
    else:
        reason = 'http_%s' % status            # 400/426 parameter problems: no stand-down
    _note(label, query, reason, 0, status)
    return [], _probe(False, reason, status=status, code=code)


def newsapi_fetch(query, days=7, language='en', page_size=100, label='', have=None,
                  refresh=False, sort_by='publishedAt', prefix=None):
    """Same as newsapi_fetch_probed, list only."""
    return newsapi_fetch_probed(query, days=days, language=language, page_size=page_size,
                                label=label, have=have, refresh=refresh, sort_by=sort_by,
                                prefix=prefix)[0]


def newsapi_stats():
    u = _usage()
    rem = _standdown_remaining()
    blind, why = _gdelt_blind()
    labels = {}
    raw = _redis(['HGETALL', PREFIX + 'labels:' + datetime.now(timezone.utc).strftime('%Y-%m-%d')])
    if isinstance(raw, list):
        labels = {raw[i]: int(raw[i + 1]) for i in range(0, len(raw) - 1, 2)}
    elif isinstance(raw, dict):
        labels = {k: int(v) for k, v in raw.items()}
    with _lock:
        s = {k: v for k, v in _state.items() if k not in ('standdown_checked_at', 'gdelt_checked_at')}
        s['skips'] = dict(_skips)
        s['recent'] = list(_recent)
        s['l1_entries'] = len(_l1)
    s.update({
        'version': __version__, 'gateway_version': __version__,
        'configured': bool(API_KEY), 'key_id': KEY_ID, 'mode': MODE,
        'scope': SCOPE, 'worker_id': WORKER_ID, 'process_started_at': PROCESS_STARTED_AT,
        'shared_budget': u['layer'],
        'usage': {'backend_12h': u['backend_12h'], 'backend_cap_12h': BACKEND_CAP_12H,
                  'platform_12h': u['platform_12h'], 'platform_cap_12h': PLATFORM_CAP_12H,
                  'platform_24h': u['platform_24h'], 'platform_cap_24h': PLATFORM_CAP_24H},
        'stand_down': bool(rem), 'stand_down_for_sec': int(rem),
        'gdelt_blind': blind, 'gdelt_state': why,
        'spend_by_label_today': dict(sorted(labels.items(), key=lambda kv: -kv[1])),
        'cache_ttl_sec': CACHE_TTL_SEC, 'thin_threshold': THIN_THRESHOLD,
        'upstash_errors': _redis_state['errors'], 'upstash_last_error': _redis_state['last_error'],
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'note': ('Fallback source. skips.primary_healthy = GDELT was working, so NewsAPI '
                 'was deliberately not asked. budget_* = the cap is working. stand_down = '
                 'NewsAPI said the quota or key is spent; every backend waits.'),
    })
    s.pop('last_call', None)
    s.pop('standdown_until', None)
    return s


def register_newsapi_routes(app):
    """GET /api/newsapi/health on this backend. Never raises; returns True/False."""
    try:
        from flask import jsonify, make_response

        @app.route('/api/newsapi/health', methods=['GET'])
        def _newsapi_health():
            resp = make_response(jsonify(newsapi_stats()))
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp
        print('[NewsAPI Gateway] v%s loaded (%s, mode=%s, key %s) -- GET /api/newsapi/health'
              % (__version__, SCOPE, MODE, 'configured' if API_KEY else 'NOT configured'))
        return True
    except Exception as e:
        print('[NewsAPI Gateway] /api/newsapi/health not registered: %s' % str(e)[:120])
        return False


# =====================================================================
# SELF-TEST  --  python3 newsapi_gateway.py   (no network, no real Redis)
# =====================================================================
if __name__ == '__main__':
    import sys
    import types

    results = {'pass': 0, 'fail': 0}

    def check(name, cond, detail=''):
        results['pass' if cond else 'fail'] += 1
        print('  %s  %s%s' % ('PASS' if cond else 'FAIL', name, '' if cond else '  -- %s' % detail))

    # Virtual clock
    clock = {'t': 1_800_000_000.0}
    globals()['_now'] = lambda: clock['t']
    globals()['_sleep'] = lambda s: clock.__setitem__('t', clock['t'] + s)

    # Fake Upstash: strings, sorted sets, hashes
    class FakeRedis:
        def __init__(self):
            self.kv, self.z, self.h, self.up = {}, {}, {}, True

        def __call__(self, cmd, timeout=4):
            if not self.up:
                raise ConnectionError('upstash down')
            op = cmd[0].upper()
            a = cmd[1:]
            if op == 'GET':
                return self.kv.get(a[0])
            if op == 'SET':
                self.kv[a[0]] = a[1]
                return 'OK'
            if op == 'EXPIRE':
                return 1
            if op == 'ZADD':
                self.z.setdefault(a[0], {})[a[2]] = float(a[1])
                return 1
            if op == 'ZREMRANGEBYSCORE':
                hi = float(a[2])
                d = self.z.get(a[0], {})
                for m in [m for m, s in d.items() if s <= hi]:
                    del d[m]
                return 0
            if op == 'ZCARD':
                return len(self.z.get(a[0], {}))
            if op == 'ZCOUNT':
                lo = float(a[1])
                return sum(1 for s in self.z.get(a[0], {}).values() if s >= lo)
            if op == 'HINCRBY':
                d = self.h.setdefault(a[0], {})
                d[a[1]] = d.get(a[1], 0) + int(a[2])
                return d[a[1]]
            if op == 'HGETALL':
                d = self.h.get(a[0], {})
                out = []
                for kk, vv in d.items():
                    out += [kk, str(vv)]
                return out
            raise ValueError(op)

    fake = FakeRedis()
    globals()['_r'] = fake
    _redis_state['ok'] = True

    # Fake GDELT gateway state
    gg = types.ModuleType('gdelt_gateway')
    gstate = {'throttled': 0, 'used': 0}
    gg._throttled_remaining = lambda: gstate['throttled']
    gg._now = lambda: clock['t']
    gg._state = {'circuit_open_until': 0}
    gg._budget_used = lambda: gstate['used']
    gg.MAX_CALLS_PER_WINDOW = 500
    sys.modules['gdelt_gateway'] = gg

    http = {'n': 0, 'mode': 'ok', 'last_headers': None, 'last_params': None}

    class Resp:
        def __init__(self, code, body):
            self.status_code, self._b = code, body
            self.text = json.dumps(body)

        def json(self):
            return self._b

    def fake_get(url, params=None, timeout=None, headers=None):
        http['n'] += 1
        http['last_headers'], http['last_params'] = headers, params
        m = http['mode']
        if m == 'ok':
            return Resp(200, {'status': 'ok', 'totalResults': 2, 'articles': [
                {'source': {'id': None, 'name': 'Reuters'}, 'author': 'x', 'title': 'Litani strike',
                 'description': 'd', 'url': 'https://r.com/%d' % http['n'],
                 'publishedAt': '2026-10-17T10:00:00Z', 'content': 'c'},
                {'source': {'id': 'ap', 'name': 'AP'}, 'title': 't2', 'url': 'https://ap/%d' % http['n'],
                 'publishedAt': '2026-10-17T11:00:00Z'}]})
        if m == '429':
            return Resp(429, {'status': 'error', 'code': 'rateLimited',
                              'message': 'You have made too many requests recently.'})
        if m == '401':
            return Resp(401, {'status': 'error', 'code': 'apiKeyInvalid', 'message': 'Your API key is invalid.'})
        if m == '426':
            return Resp(426, {'status': 'error', 'code': 'parameterInvalid', 'message': 'too far in the past'})
        if m == 'timeout':
            raise requests.exceptions.Timeout('slow')
        raise RuntimeError(m)

    requests.get = fake_get

    def reset(key='TESTKEY-SECRET-123', mode='fallback', scope='me'):
        global API_KEY, KEY_ID, PREFIX, MODE, SCOPE
        API_KEY, MODE, SCOPE = key, mode, scope
        KEY_ID = hashlib.sha1(key.encode()).hexdigest()[:8] if key else 'none'
        PREFIX = 'newsapi_gw:%s:' % KEY_ID
        fake.kv.clear(); fake.z.clear(); fake.h.clear(); fake.up = True
        _redis_state['ok'] = True
        _l1.clear(); _skips.clear(); _local_spend.clear(); del _recent[:]
        _state.update({'requests_seen': 0, 'http_calls': 0, 'ok': 0, 'articles': 0, 'l1_hits': 0,
                       'l2_hits': 0, 'last_call': 0.0, 'standdown_until': 0.0,
                       'standdown_checked_at': 0.0, 'standdown_info': None,
                       'gdelt_checked_at': 0.0, 'gdelt_blind': None, 'gdelt_why': '', 'last_error': '',
                       'budget_block_until': 0.0, 'budget_block_reason': ''})
        gstate.update({'throttled': 0, 'used': 0})
        gg._state['circuit_open_until'] = 0
        http.update({'n': 0, 'mode': 'ok'})

    def gdelt(blind):
        gstate['throttled'] = 600 if blind else 0
        _state['gdelt_blind'] = None

    print('NewsAPI Gateway v%s -- self-test' % __version__)

    print('0 canary: the harness can see a failure')
    reset()
    check('canary: FakeRedis counts', fake(['ZADD', 'k', '1', 'm']) == 1 and fake(['ZCARD', 'k']) == 1)

    print('1 no key -> no HTTP, honest reason')
    reset(key='')
    a, p = newsapi_fetch_probed('Hezbollah', label='t/a')
    check('no_key reason', p['reason'] == 'no_key' and p['skipped'] and http['n'] == 0, p)

    print('2 fallback mode, GDELT healthy -> deliberate skip, no HTTP')
    reset(); gdelt(False)
    a, p = newsapi_fetch_probed('Hezbollah', label='me/hezbollah')
    check('primary_healthy', p['reason'] == 'primary_healthy' and http['n'] == 0, p)

    print('3 GDELT blind -> real request, native shape, key in header only')
    reset(); gdelt(True)
    a, p = newsapi_fetch_probed('Hezbollah', label='me/hezbollah')
    check('sensed ok', p['sensed'] and p['reason'] == 'ok' and len(a) == 2, p)
    check('native shape', a[0]['publishedAt'] and a[0]['source']['name'] == 'Reuters' and a[0]['language'] == 'en', a[0])
    check('key not in params', 'apiKey' not in (http['last_params'] or {}) and http['last_headers'].get('X-Api-Key'))
    check('label spend recorded', newsapi_stats()['spend_by_label_today'].get('me/hezbollah') == 1)

    print('4 cache: same query free even when GDELT healthy; L2 survives L1 loss')
    gdelt(False)
    n0 = http['n']
    a, p = newsapi_fetch_probed('Hezbollah', label='me/hezbollah')
    check('L1 hit', p['cached'] and p['cache_layer'] == 'l1' and len(a) == 2 and http['n'] == n0, p)
    _l1.clear()
    a, p = newsapi_fetch_probed('Hezbollah', label='me/hezbollah')
    check('L2 hit', p['cache_layer'] == 'l2' and http['n'] == n0, p)
    clock['t'] += CACHE_TTL_SEC + 5
    _l1.clear(); fake.kv.clear()     # L2 TTL is enforced by Upstash EX; emulate expiry
    a, p = newsapi_fetch_probed('Hezbollah', label='me/hezbollah')
    check('expired -> gate again', p['reason'] == 'primary_healthy', p)

    print('5 backend cap: 9 per rolling 12h, then rotation after window')
    reset(); gdelt(True)
    got = [newsapi_fetch_probed('q%d' % i, label='africa/app')[1]['reason'] for i in range(12)]
    check('9 ok then budget_backend', got.count('ok') == BACKEND_CAP_12H and got[-1] == 'budget_backend', got)
    check('9 HTTP calls', http['n'] == BACKEND_CAP_12H, http['n'])
    clock['t'] += H12 + 10
    _state['gdelt_blind'] = None
    r = newsapi_fetch_probed('q0', label='africa/app')[1]['reason']
    check('served query is free after window (L1/L2 cache)', r == 'cached', r)
    r = newsapi_fetch_probed('q10', label='africa/app')[1]['reason']
    check('unserved query gets budget next window', r == 'ok', r)

    print('6 platform cap shared across backends (45/12h)')
    reset(); gdelt(True)
    total = 0
    for b in range(6):
        SCOPE = 'svc%d' % b
        _state['budget_block_until'] = 0.0      # a different backend = a different process
        for i in range(BACKEND_CAP_12H):
            total += newsapi_fetch_probed('p%d-%d' % (b, i), label='x')[1]['reason'] == 'ok'
    check('platform cap holds', total == PLATFORM_CAP_12H and http['n'] == PLATFORM_CAP_12H, (total, http['n']))
    SCOPE = 'svc9'
    _state['budget_block_until'] = 0.0
    r = newsapi_fetch_probed('another', label='x')[1]['reason']
    check('new backend sees budget_platform', r == 'budget_platform', r)

    print('7 24h cap: second 12h window cannot exceed 90/day')
    clock['t'] += H12 + 1
    _state['gdelt_blind'] = None
    for b in range(6):
        SCOPE = 'svcB%d' % b
        _state['budget_block_until'] = 0.0
        for i in range(BACKEND_CAP_12H):
            newsapi_fetch_probed('pp%d-%d' % (b, i), label='x')
    check('<= 90 per 24h', http['n'] <= PLATFORM_CAP_24H, http['n'])

    print('8 429 rateLimited -> platform stand-down, other backends stop')
    reset(); gdelt(True); http['mode'] = '429'
    a, p = newsapi_fetch_probed('z1', label='me/iran')
    check('rate_limited reason', p['reason'] == 'rate_limited' and p['code'] == 'rateLimited', p)
    http['mode'] = 'ok'; n0 = http['n']
    SCOPE = 'other'
    _state['standdown_until'] = 0.0; _state['standdown_checked_at'] = 0.0   # a different process
    a, p = newsapi_fetch_probed('z2', label='wha/app')
    check('other backend stands down via Upstash', p['reason'] == 'stand_down' and http['n'] == n0, p)
    clock['t'] += STANDDOWN_SEC + 5
    fake.kv.pop(PREFIX + 'standdown', None)   # Upstash EX expiry
    _state['standdown_checked_at'] = 0.0
    a, p = newsapi_fetch_probed('z3', label='wha/app')
    check('after stand-down, requests resume', p['reason'] == 'ok', p)

    print('9 401 invalid key -> 24h stand-down')
    reset(); gdelt(True); http['mode'] = '401'
    a, p = newsapi_fetch_probed('k1', label='x')
    check('key_invalid', p['reason'] == 'key_invalid' and newsapi_stats()['stand_down_for_sec'] > 86000, p)

    print('10 426 parameter error -> logged, NO stand-down')
    reset(); gdelt(True); http['mode'] = '426'
    a, p = newsapi_fetch_probed('k2', label='x')
    check('http_426 + no stand-down', p['reason'] == 'http_426' and not newsapi_stats()['stand_down'], p)

    print('11 timeout counts as spend, honest reason')
    reset(); gdelt(True); http['mode'] = 'timeout'
    a, p = newsapi_fetch_probed('k3', label='x')
    check('timeout', p['reason'] == 'timeout' and newsapi_stats()['usage']['backend_12h'] == 1, p)

    print('12 Upstash down -> local_only, cap halved per process')
    reset(); gdelt(True); fake.up = True
    _redis_state['ok'] = False
    got = [newsapi_fetch_probed('u%d' % i, label='x')[1]['reason'] for i in range(10)]
    check('local cap = backend cap // 2', got.count('ok') == max(1, BACKEND_CAP_12H // 2), got)
    check('reported local_only', newsapi_stats()['shared_budget'] == 'local_only')

    print('12b budget memo: a spent budget is not re-asked of Upstash for 60s')
    reset(); gdelt(True)
    for i in range(BACKEND_CAP_12H + 1):
        newsapi_fetch_probed('m%d' % i, label='x')
    cmds = {'n': 0}
    real_fake = globals()['_r']
    def counting(cmd, timeout=4):
        if cmd[0] in ('ZCOUNT', 'ZCARD', 'ZREMRANGEBYSCORE'):
            cmds['n'] += 1
        return real_fake(cmd, timeout)
    globals()['_r'] = counting
    for i in range(30):
        newsapi_fetch_probed('mm%d' % i, label='x')
    check('30 skips cost 0 budget reads', cmds['n'] == 0, cmds['n'])
    clock['t'] += 61
    newsapi_fetch_probed('mm-late', label='x')
    check('memo expires after 60s', cmds['n'] > 0, cmds['n'])
    globals()['_r'] = real_fake

    print('12c prefix derives a readable label')
    reset(); gdelt(True)
    newsapi_fetch_probed('"Naim Qassem" OR Hezbollah', prefix='me')
    check('label me/Naim Qassem', _recent[-1]['label'] == 'me/Naim Qassem', _recent[-1])

    print('13 caller says thin (have<threshold) while GDELT healthy -> allowed')
    reset(); gdelt(False)
    a, p = newsapi_fetch_probed('t1', label='x', have=3)
    check('thin triggers', p['reason'] == 'ok', p)
    a, p = newsapi_fetch_probed('t2', label='x', have=50)
    check('not thin -> skip', p['reason'] == 'primary_healthy', p)

    print('14 mode=always bypasses the gate, keeps the budget')
    reset(mode='always'); gdelt(False)
    a, p = newsapi_fetch_probed('al', label='x')
    check('always mode fetches', p['reason'] == 'ok', p)

    print('15 stats: shape + no key leak; gdelt module missing = blind')
    reset(); gdelt(True)
    newsapi_fetch_probed('s1', label='me/x')
    st = newsapi_stats()
    for key in ('version', 'usage', 'skips', 'recent', 'stand_down', 'gdelt_blind', 'spend_by_label_today', 'key_id'):
        check('stats has %s' % key, key in st)
    check('key not leaked', 'TESTKEY-SECRET-123' not in json.dumps(st, default=str))
    sys.modules.pop('gdelt_gateway')
    _state['gdelt_blind'] = None
    check('no gdelt module -> blind (fallback allowed)', _gdelt_blind()[0] is True)
    sys.modules['gdelt_gateway'] = gg

    print('\n%d PASS, %d FAIL' % (results['pass'], results['fail']))
    sys.exit(1 if results['fail'] else 0)
