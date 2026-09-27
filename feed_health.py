"""
Asifah Analytics -- FEED HEALTH
v1.0.0 -- September 27 2026  |  portable, drop into any backend

WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════
Reuters retired feeds.reuters.com. Every Africa scan then spent a full
timeout on a host that no longer resolved, and returned zero articles from
it, and said nothing. We found out days later, by reading a log by hand.

A source that goes quiet looks exactly like a quiet source. The corpus
shrinks, the numbers still render, and the only visible symptom is an
analysis that is slightly wrong in a direction nobody can name.

WHAT THIS DOES
═══════════════════════════════════════════════════════════════════════
Every fetch reports its outcome here. The record lives in Upstash, so it
survives restarts and is shared across instances and repos. A feed is then
classified by its OWN history, not by one bad night:

    healthy        delivered items within the silent window
    quiet          reached, but empty lately -- MAYBE nothing is happening
    silent         reached, and empty for FEED_SILENT_DAYS (default 3)
    failing        reachable but erroring / non-200 recently
    dead           no successful fetch for FEED_DEAD_DAYS (default 7)
    never_worked   recorded, never once returned an item
    unknown        no record, or Redis unreachable -- NOT the same as fine

ABSENCE-HONEST BY CONSTRUCTION. 'quiet' and 'silent' and 'dead' are three
different claims, and this module refuses to collapse them. A world that
got calmer and a feed that got retired are not the same finding.

USAGE
═══════════════════════════════════════════════════════════════════════
    from feed_health import record_fetch, feed_report

    articles = fetch_rss(url)
    record_fetch('africa', url, items=len(articles))            # success path
    record_fetch('africa', url, items=0, http_status=404)       # HTTP fault
    record_fetch('africa', url, items=0, error=e)               # exception

    # in any /health endpoint:
    'feeds': feed_report('africa')

One call per fetch. Two Upstash writes per call, which is nothing next to
the HTTP fetch it is describing.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    requests = None

__version__ = '1.0.0'

UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_URL')
               or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                 or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
REDIS_OK = bool(UPSTASH_URL and UPSTASH_TOKEN and requests is not None)

SILENT_DAYS = float(os.environ.get('FEED_SILENT_DAYS', '3'))
DEAD_DAYS   = float(os.environ.get('FEED_DEAD_DAYS', '7'))
RECORD_TTL  = int(os.environ.get('FEED_HEALTH_TTL_SEC', str(45 * 24 * 3600)))
KEY_PREFIX  = 'feedhealth:'

_lock = threading.Lock()
_local = {}          # backend -> {feed_key: record}  (mirror; survives nothing)


def _now():
    return time.time()


def _iso(ts=None):
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _feed_key(feed_id):
    """Stable short key. Feed ids are URLs: Arabic, query strings, colons."""
    return hashlib.md5(feed_id.encode('utf-8')).hexdigest()[:16]


def _redis(cmd, timeout=5):
    if not REDIS_OK:
        return None
    try:
        r = requests.post(UPSTASH_URL,
                          headers={'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
                          json=cmd, timeout=timeout)
        if r.ok:
            return (r.json() or {}).get('result')
    except Exception as e:
        print('[FeedHealth] redis error: %s' % str(e)[:90])
    return None


def _load(backend, fkey):
    raw = _redis(['GET', '%s%s:%s' % (KEY_PREFIX, backend, fkey)])
    if raw:
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return None
    return None


def _save(backend, fkey, rec):
    _redis(['SET', '%s%s:%s' % (KEY_PREFIX, backend, fkey),
            json.dumps(rec, default=str), 'EX', str(RECORD_TTL)])
    _redis(['SADD', '%sindex:%s' % (KEY_PREFIX, backend), fkey])
    _redis(['EXPIRE', '%sindex:%s' % (KEY_PREFIX, backend), str(RECORD_TTL)])


def record_fetch(backend, feed_id, items=0, http_status=None, error=None,
                 label=None, duration_ms=None):
    """Record one fetch attempt against one feed.

    items       : how many articles came back (0 is a fact, not a failure)
    http_status : the code, when there was one
    error       : exception or string, when the fetch never completed
    label       : human name for the feed, if the id is an ugly URL
    """
    fkey = _feed_key(feed_id)
    rec = _load(backend, fkey) or {
        'feed_id':      feed_id,
        'label':        label or feed_id,
        'backend':      backend,
        'first_seen':   _iso(),
        'checks':       0,
        'items_total':  0,
        'last_items':   0,
        'last_check':   None,
        'last_items_at': None,      # last time it returned >=1 item
        'last_ok_at':   None,       # last time it was REACHED (200/no error)
        'consecutive_empty':  0,
        'consecutive_failed': 0,
        'last_http':    None,
        'last_error':   None,
    }
    if label:
        rec['label'] = label

    reached = (error is None) and (http_status is None or int(http_status) == 200)
    rec['checks'] += 1
    rec['last_check'] = _iso()
    rec['last_items'] = int(items or 0)
    rec['last_http'] = http_status
    if duration_ms is not None:
        rec['last_duration_ms'] = int(duration_ms)

    if error is not None:
        rec['last_error'] = ('%s: %s' % (type(error).__name__, str(error))
                             if isinstance(error, BaseException) else str(error))[:160]
        rec['consecutive_failed'] += 1
    elif not reached:
        rec['last_error'] = 'HTTP %s' % http_status
        rec['consecutive_failed'] += 1
    else:
        rec['last_ok_at'] = _iso()
        rec['consecutive_failed'] = 0
        rec['last_error'] = None

    if items:
        rec['items_total'] += int(items)
        rec['last_items_at'] = _iso()
        rec['consecutive_empty'] = 0
    elif reached:
        rec['consecutive_empty'] += 1

    with _lock:
        _local.setdefault(backend, {})[fkey] = rec
    _save(backend, fkey, rec)
    return rec


def _age_days(iso_str):
    if not iso_str:
        return None
    try:
        then = datetime.fromisoformat(iso_str)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 86400.0
    except Exception:
        return None


def classify(rec):
    """One word for what this feed is doing, plus why. Never guesses."""
    if not rec:
        return 'unknown', 'No record for this feed.'

    since_items = _age_days(rec.get('last_items_at'))
    since_ok    = _age_days(rec.get('last_ok_at'))

    # ORDER MATTERS. How a feed is failing is more useful than the fact that
    # it has never delivered: 'never_worked' on a host that stopped resolving
    # sends you to check the URL for a typo instead of reading the error.
    if rec.get('consecutive_failed', 0) >= 3:
        return ('failing',
                '%d consecutive failed fetches. Last: %s'
                % (rec['consecutive_failed'], rec.get('last_error')))

    if since_ok is None:
        # Never once reached. Two attempts is not a verdict -- a feed added
        # an hour ago and a feed retired last month must not read the same.
        if rec.get('checks', 0) < 3:
            return ('failing',
                    'Never successfully reached, but only %d attempt(s) so far '
                    '-- too early to call it dead. Last error: %s'
                    % (rec.get('checks', 0), rec.get('last_error') or 'none recorded'))
        return ('dead',
                'Never successfully reached in %d attempts. Last error: %s'
                % (rec.get('checks', 0), rec.get('last_error') or 'none recorded'))

    if since_ok > DEAD_DAYS:
        return ('dead',
                'Not successfully reached in %.1f days. Last error: %s'
                % (since_ok, rec.get('last_error') or 'none recorded'))

    if rec.get('items_total', 0) == 0 and rec.get('checks', 0) >= 3:
        return ('never_worked',
                'Checked %d times and has never returned an item. Either the '
                'URL is wrong or the feed has nothing we can parse.'
                % rec['checks'])

    if since_items is None:
        return ('never_worked', 'Reached, but has never delivered an item.')

    if since_items > DEAD_DAYS:
        return ('dead',
                'Reachable but has delivered nothing in %.1f days. A live host '
                'serving an empty or changed feed looks exactly like this.'
                % since_items)

    if since_items > SILENT_DAYS:
        return ('silent',
                'Reached fine, no items in %.1f days (threshold %.0f). This is '
                'NOT evidence of quiet -- verify the feed before treating its '
                'silence as a finding.' % (since_items, SILENT_DAYS))

    if rec.get('last_items', 0) == 0:
        return ('quiet',
                'Reached, last fetch empty, but delivered %.1f days ago. '
                'Probably genuine quiet.' % since_items)

    return ('healthy', 'Delivered %d items on the last check.' % rec['last_items'])


def feed_report(backend, include_healthy=True):
    """Everything known about this backend's feeds, classified.

    Wire into /health. The summary counts are the part worth alerting on.
    """
    out = {
        'version':      __version__,
        'backend':      backend,
        'silent_days':  SILENT_DAYS,
        'dead_days':    DEAD_DAYS,
        'generated_at': _iso(),
    }
    if not REDIS_OK:
        out['state'] = 'could_not_assess'
        out['reason'] = ('Upstash not configured, so no feed history exists. '
                         'This is NOT a clean bill of health.')
        return out

    keys = _redis(['SMEMBERS', '%sindex:%s' % (KEY_PREFIX, backend)]) or []
    feeds, summary = {}, {}
    for fkey in keys:
        rec = _load(backend, fkey)
        if not rec:
            # Index entry whose record expired: the feed stopped being checked.
            summary['expired'] = summary.get('expired', 0) + 1
            continue
        status, why = classify(rec)
        summary[status] = summary.get(status, 0) + 1
        if status == 'healthy' and not include_healthy:
            continue
        feeds[rec.get('label') or rec.get('feed_id')] = {
            'status':        status,
            'why':           why,
            'last_check':    rec.get('last_check'),
            'last_items_at': rec.get('last_items_at'),
            'last_items':    rec.get('last_items'),
            'items_total':   rec.get('items_total'),
            'checks':        rec.get('checks'),
            'consecutive_empty':  rec.get('consecutive_empty'),
            'consecutive_failed': rec.get('consecutive_failed'),
            'last_http':     rec.get('last_http'),
            'last_error':    rec.get('last_error'),
            'feed_id':       rec.get('feed_id'),
        }

    out['state'] = 'assessed'
    out['feed_count'] = len(keys)
    out['summary'] = dict(sorted(summary.items(), key=lambda kv: -kv[1]))
    out['needs_attention'] = sorted(
        name for name, f in feeds.items()
        if f['status'] in ('dead', 'never_worked', 'failing', 'silent'))
    out['feeds'] = feeds
    return out


def forget_feed(backend, feed_id):
    """Drop a feed's record -- use when a dead feed is pulled from the config."""
    fkey = _feed_key(feed_id)
    _redis(['DEL', '%s%s:%s' % (KEY_PREFIX, backend, fkey)])
    _redis(['SREM', '%sindex:%s' % (KEY_PREFIX, backend), fkey])
    with _lock:
        _local.get(backend, {}).pop(fkey, None)
    return True


if __name__ == '__main__':
    print('Feed Health v%s -- self-test\n' % __version__)
    import types as _types
    from datetime import timedelta as _td

    store = {}
    sets = {}

    class _R(object):
        def __init__(self, result):
            self.ok = True
            self._r = result

        def json(self):
            return {'result': self._r}

    def _post(url, headers=None, json=None, timeout=None):
        c = json
        if c[0] == 'SET':
            store[c[1]] = c[2]
            return _R('OK')
        if c[0] == 'GET':
            return _R(store.get(c[1]))
        if c[0] == 'SADD':
            sets.setdefault(c[1], set()).add(c[2])
            return _R(1)
        if c[0] == 'SMEMBERS':
            return _R(sorted(sets.get(c[1], set())))
        if c[0] == 'SREM':
            sets.get(c[1], set()).discard(c[2])
            return _R(1)
        if c[0] == 'DEL':
            store.pop(c[1], None)
            return _R(1)
        if c[0] == 'EXPIRE':
            return _R(1)
        return _R(None)

    globals()['requests'] = _types.SimpleNamespace(post=_post)
    globals()['REDIS_OK'] = True
    globals()['UPSTASH_URL'] = 'https://fake'
    globals()['UPSTASH_TOKEN'] = 'tok'

    def _backdate(backend, feed_id, field, days):
        fkey = _feed_key(feed_id)
        rec = _load(backend, fkey)
        rec[field] = (datetime.now(timezone.utc) - _td(days=days)).isoformat()
        _save(backend, fkey, rec)

    print('TEST 1 -- a working feed is healthy')
    record_fetch('test', 'https://good.example/rss', items=12, http_status=200,
                 label='Good Feed')
    assert classify(_load('test', _feed_key('https://good.example/rss')))[0] == 'healthy'
    print('  OK\n')

    print('TEST 2 -- empty once is QUIET, not silent')
    record_fetch('test', 'https://good.example/rss', items=0, http_status=200,
                 label='Good Feed')
    st, why = classify(_load('test', _feed_key('https://good.example/rss')))
    assert st == 'quiet', st
    print('  %s -- %s\n' % (st, why[:60]))

    print('TEST 3 -- empty past the window is SILENT (and says not to trust it)')
    _backdate('test', 'https://good.example/rss', 'last_items_at', 4)
    st, why = classify(_load('test', _feed_key('https://good.example/rss')))
    assert st == 'silent' and 'NOT evidence of quiet' in why
    print('  %s -- %s\n' % (st, why[:70]))

    print('TEST 4 -- the Reuters case: host stops resolving')
    for _ in range(3):
        record_fetch('test', 'https://feeds.reuters.com/reuters/africaNews',
                     items=0, error=ConnectionError('Max retries exceeded'),
                     label='Reuters Africa')
    st, why = classify(_load('test', _feed_key('https://feeds.reuters.com/reuters/africaNews')))
    assert st in ('failing', 'dead'), st
    print('  %s -- %s\n' % (st, why[:80]))

    print('TEST 5 -- reachable but delivering nothing for a week is DEAD')
    record_fetch('test', 'https://stale.example/rss', items=1, http_status=200)
    _backdate('test', 'https://stale.example/rss', 'last_items_at', 9)
    st, why = classify(_load('test', _feed_key('https://stale.example/rss')))
    assert st == 'dead', st
    print('  %s -- a live host serving a dead feed is still dead\n' % st)

    print('TEST 6 -- a URL that never worked says so')
    for _ in range(3):
        record_fetch('test', 'https://typo.example/rss', items=0, http_status=200)
    st, _w = classify(_load('test', _feed_key('https://typo.example/rss')))
    assert st == 'never_worked', st
    print('  OK\n')

    print('TEST 7 -- the report names what needs attention')
    rpt = feed_report('test')
    print('  summary: %s' % rpt['summary'])
    print('  needs_attention: %s' % rpt['needs_attention'])
    assert rpt['state'] == 'assessed'
    assert 'Reuters Africa' in rpt['needs_attention']
    assert len(rpt['needs_attention']) == 4
    print('  OK\n')

    print('TEST 8 -- no Redis is NOT a clean bill of health')
    globals()['REDIS_OK'] = False
    rpt = feed_report('test')
    assert rpt['state'] == 'could_not_assess' and 'NOT a clean bill' in rpt['reason']
    print('  %s\n' % rpt['reason'][:72])

    print('ALL FEED HEALTH TESTS PASSED')
