"""
Asifah Analytics -- SOURCE CENSUS  (ME backend)
v1.0.0  (Nov 5 2026)

One link instead of five: /api/census reads every backend's /health feed
report, plus the ME backend's prediction-markets and commentary checks, and
answers three questions:

  1. What is broken?      every feed that is failing, dead or never worked,
                          with the reason, grouped by backend
  2. What is the risk?    how much of each backend depends on Google News
                          (one provider throttling Render = several regions
                          blind at once)
  3. Is it getting better? totals now vs the last census (kept 30 days)

v1.1.0 (Nov 5 2026): a feed nobody has fetched for 36h is RETIRED, not broken.
  When a URL is swapped (e.g. Times of Israel -> its Google News query), the
  old address keeps its record in feed_health forever, still saying "failing".
  Those are listed under 'retired' and left out of the broken count.

COST: $0. Five HTTP reads of our own backends, at most once per 30 minutes
(cached). No Claude calls. ?refresh=true re-reads (also at most every 10 min).
"""

import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

__version__ = '1.1.1'

BACKENDS = {
    'me':     'https://asifah-backend.onrender.com/health',
    'europe': 'https://asifa-europe-backend.onrender.com/health',
    'wha':    'https://asifah-wha-backend.onrender.com/health',
    'asia':   'https://asifah-asia-backend.onrender.com/health',
    'africa': 'https://asifah-africa-backend.onrender.com/health',
}
CACHE_KEY = 'census:latest'
HISTORY_KEY = 'census:history'
CACHE_SEC = 30 * 60
MANUAL_GAP = 600
UA = {'User-Agent': 'AsifahAnalytics-Census/1.0 (+https://www.asifahanalytics.com)'}

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
_MEM = {}
_state = {'last_manual': 0.0}
_lock = threading.Lock()


def _rget(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return _MEM.get(key)
    try:
        r = requests.get('%s/get/%s' % (UPSTASH_REDIS_URL, key),
                         headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN}, timeout=6)
        res = r.json().get('result') if r.status_code == 200 else None
        return json.loads(res) if res else None
    except Exception:
        return None


def _rset(key, value, ttl):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        _MEM[key] = json.loads(json.dumps(value, default=str))
        return
    try:
        requests.post('%s/set/%s' % (UPSTASH_REDIS_URL, key),
                      headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN,
                               'Content-Type': 'application/json'},
                      data=json.dumps(value, default=str), params={'EX': int(ttl)}, timeout=8)
    except Exception:
        pass


def _is_google(feed_id):
    return 'news.google.com' in (feed_id or '')


def _read_backend(name, url, out):
    t0 = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=50)   # a sleeping Render service takes ~30s to wake
        d = r.json() if r.status_code == 200 else None
        out[name] = {'ok': d is not None, 'http': r.status_code, 'data': d,
                     'seconds': round(time.time() - t0, 1)}
    except Exception as e:
        out[name] = {'ok': False, 'error': str(e)[:120], 'seconds': round(time.time() - t0, 1)}


RETIRED_AFTER_H = 36


def _hours_since(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).total_seconds() / 3600
    except Exception:
        return None


def _summarise(name, raw):
    if not raw.get('ok'):
        return {'backend': name, 'state': 'unread',
                'why': raw.get('error') or 'HTTP %s' % raw.get('http'),
                'note': 'Unread, not healthy: the backend did not answer (asleep or down).'}
    fh = (raw['data'] or {}).get('feeds') or {}
    feeds = fh.get('feeds') or {}
    if not feeds:
        return {'backend': name, 'state': fh.get('state') or 'no_feed_report',
                'why': fh.get('reason')}
    retired = []
    for label in list(feeds):
        h = _hours_since(feeds[label].get('last_check'))
        if h is not None and h > RETIRED_AFTER_H:
            retired.append({'feed': label, 'url': feeds[label].get('feed_id'),
                            'last_checked_hours_ago': round(h)})
            feeds = {k: v for k, v in feeds.items() if k != label}
    broken = []
    google = 0
    for label, f in feeds.items():
        if _is_google(f.get('feed_id')):
            google += 1
        if f.get('status') in ('failing', 'dead', 'never_worked'):
            broken.append({'feed': label, 'status': f.get('status'), 'why': f.get('why'),
                           'url': f.get('feed_id'), 'checks': f.get('checks')})
    order = {'dead': 0, 'never_worked': 1, 'failing': 2}
    broken.sort(key=lambda b: (order.get(b['status'], 3), b['feed'].lower()))
    total = len(feeds)
    rec = {
        'backend': name, 'state': 'assessed', 'feeds': total,
        'summary': fh.get('summary'),
        'healthy_pct': round(100.0 * (total - len(broken)) / total) if total else None,
        'google_news_share_pct': round(100.0 * google / total) if total else None,
        'broken': broken,
        'duplicate_labels': fh.get('duplicate_labels') or [],
        'retired': retired,
    }
    reddit = (raw['data'] or {}).get('reddit') or {}
    rl = sum(1 for t in (reddit.get('targets') or {}).values() if t.get('rate_limited'))
    if rl:
        rec['reddit_rate_limited_targets'] = rl
    bb = (raw['data'] or {}).get('brave_budget')
    if bb:
        rec['brave_spent_today'] = bb.get('spent_today')
        rec['brave_budget_daily'] = bb.get('budget_daily')
    return rec


def _side_checks():
    """The two ME lanes built Nov 5: traders' odds and commentary."""
    out = {}
    try:
        import prediction_markets as pm
        p = pm.latest() or {}
        h = p.get('health') or {}
        out['prediction_markets'] = {'ok': h.get('ok'), 'of': h.get('watchlist_size'),
                                     'fetch_errors': h.get('fetch_errors'),
                                     'needs_attention': h.get('needs_attention'),
                                     'generated_at': p.get('generated_at')}
    except Exception as e:
        out['prediction_markets'] = {'state': 'unread', 'why': str(e)[:80]}
    try:
        import think_tank_feeds as tt
        c = tt.get_commentary() or {}
        h = c.get('health') or {}
        out['commentary'] = {'ok': h.get('ok'), 'of': h.get('sources'), 'dead': h.get('dead'),
                             'empty': h.get('empty'), 'history_days': c.get('history_days'),
                             'generated_at': c.get('last_updated')}
    except Exception as e:
        out['commentary'] = {'state': 'unread', 'why': str(e)[:80]}
    try:                                                   # v1.1.1: Wikipedia lane
        import wikipedia_attention as wa
        w = wa.latest() or {}
        h = w.get('health') or {}
        out['wikipedia'] = {'ok': h.get('ok'), 'of': h.get('articles'),
                            'failed': [f.get('project', '') + ':' + f.get('title', '') + ' -- ' + f.get('why', '')
                                       for f in (h.get('failed') or [])][:20],
                            'generated_at': w.get('generated_at')}
    except Exception as e:
        out['wikipedia'] = {'state': 'unread', 'why': str(e)[:80]}
    return out


def build():
    raws, threads = {}, []
    for name, url in BACKENDS.items():
        t = threading.Thread(target=_read_backend, args=(name, url, raws))
        t.start()
        threads.append(t)
    for t in threads:
        t.join(60)
    backends = [_summarise(n, raws.get(n) or {'ok': False, 'error': 'no answer in 60s'}) for n in BACKENDS]
    assessed = [b for b in backends if b.get('state') == 'assessed']
    total = sum(b['feeds'] for b in assessed)
    healthy = sum(b['feeds'] - len(b['broken']) for b in assessed)
    broken = sum(len(b['broken']) for b in assessed)
    google = sum(round(b['feeds'] * (b['google_news_share_pct'] or 0) / 100.0) for b in assessed)
    now = datetime.now(timezone.utc).isoformat()
    hist = _rget(HISTORY_KEY) or []
    prev = hist[-1] if hist else None
    totals = {'feeds': total, 'healthy': healthy, 'broken': broken,
              'google_news_share_pct': round(100.0 * google / total) if total else None,
              'backends_read': len(assessed), 'backends_total': len(BACKENDS)}
    risks = []
    for b in assessed:
        if (b.get('google_news_share_pct') or 0) >= 80:
            risks.append('%s depends on Google News for %d%% of its feeds: if Google throttles Render, '
                         'it goes blind.' % (b['backend'].upper(), b['google_news_share_pct']))
        if b.get('reddit_rate_limited_targets'):
            risks.append('%s: anonymous Reddit is rate-limited on %d targets (expected until API access).'
                         % (b['backend'].upper(), b['reddit_rate_limited_targets']))
    payload = {
        'version': __version__, 'generated_at': now,
        'totals': totals,
        'change_since_last': ({'when': prev['at'], 'healthy': healthy - prev['healthy'],
                               'broken': broken - prev['broken']} if prev else None),
        'risks': risks,
        'backends': backends,
        'lanes': _side_checks(),
        'note': 'Unread backends are said, never counted as healthy.',
    }
    hist = (hist + [{'at': now, 'healthy': healthy, 'broken': broken, 'feeds': total}])[-60:]
    _rset(HISTORY_KEY, hist, 31 * 86400)
    _rset(CACHE_KEY, payload, CACHE_SEC + 300)
    return payload


def latest(refresh=False):
    with _lock:
        p = _rget(CACHE_KEY)
        age = None
        if p:
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(p['generated_at'])).total_seconds()
            except Exception:
                age = None
        manual_ok = refresh and time.time() - _state['last_manual'] >= MANUAL_GAP
        if p and age is not None and age < CACHE_SEC and not manual_ok:
            return p
        if refresh:
            _state['last_manual'] = time.time()
        return build()


def register_census_routes(app):
    from flask import jsonify, request

    @app.route('/api/census')
    def _census():
        return jsonify(latest(refresh=request.args.get('refresh', 'false').lower() == 'true'))

    print('[Census] route registered: /api/census (v%s)' % __version__)
