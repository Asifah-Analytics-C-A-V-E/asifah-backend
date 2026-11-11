"""
memory_probe.py -- v1.0.0 (Nov 8 2026)

WHY: the ME backend has been killed for running out of memory about once a
day (Nov 5-7). Boot logs cannot say why -- they are written AFTER the restart.
This module records, every 15 minutes, how big each worker process is and
which threads it is running, so the next crash leaves a trail:

  * RSS climbing steadily all day      -> a real leak (something keeps growing)
  * flat, then a cliff at one time     -> one heavy job (find it by the clock)
  * thread count climbing              -> a thread leak (scans spawned per request)

It costs nothing: no paid API, ~4 Upstash commands per worker per hour.
It never stores page content, only sizes and thread names.

Endpoints
  GET /api/memory            -> this worker now + every worker's last 48h series
  GET /api/memory?objects=1  -> also the 15 most common Python object types in
                                THIS worker (heavier; on demand only)

Register in app.py:
    from memory_probe import register_memory_probe
    register_memory_probe(app, backend='asifah-backend')
"""
import gc
import json
import os
import re
import socket
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import requests

PROBE_VERSION = '1.0.0'
INTERVAL_SEC = 15 * 60
KEEP_POINTS = 200                       # 200 x 15 min = 50 hours
KEY_PREFIX = 'memprobe:'
KEY_TTL = 3 * 24 * 3600

_URL = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
_STARTED = {'flag': False}
_BOOT = time.time()


def _cmd(*args):
    if not (_URL and _TOKEN):
        return None
    try:
        r = requests.post(_URL.rstrip('/'), headers={'Authorization': 'Bearer %s' % _TOKEN},
                          json=[str(a) for a in args], timeout=5)
        return r.json().get('result')
    except Exception as e:
        print('[MemProbe] redis error: %s' % str(e)[:120])
        return None


def _rss_mb():
    """Resident memory of this process, in MB (Linux /proc)."""
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except Exception:
        pass
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        return None


def _thread_groups():
    """Threads grouped by name with the trailing numbers removed, so 200
    'ThreadPoolExecutor-17_0' threads show as one big group."""
    names = [re.sub(r'[-_ ]?\d+(_\d+)?$', '', t.name or '?') for t in threading.enumerate()]
    return Counter(names).most_common(8)


def _snapshot(backend):
    return {
        't': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'backend': backend,
        'host': socket.gethostname()[:40],
        'pid': os.getpid(),
        'uptime_h': round((time.time() - _BOOT) / 3600.0, 2),
        'rss_mb': _rss_mb(),
        'threads': threading.active_count(),
        'thread_groups': _thread_groups(),
        'gc_counts': list(gc.get_count()),
    }


def _key(backend):
    return '%s%s:%s:%d' % (KEY_PREFIX, backend, socket.gethostname()[:40], os.getpid())


def _loop(backend):
    time.sleep(60)
    while True:
        try:
            snap = _snapshot(backend)
            k = _key(backend)
            _cmd('LPUSH', k, json.dumps(snap, separators=(',', ':')))
            _cmd('LTRIM', k, 0, KEEP_POINTS - 1)
            _cmd('EXPIRE', k, KEY_TTL)
            print('[MemProbe] %s pid=%s rss=%sMB threads=%s top=%s' % (
                backend, snap['pid'], snap['rss_mb'], snap['threads'],
                ', '.join('%s x%d' % g for g in snap['thread_groups'][:3])))
        except Exception as e:
            print('[MemProbe] loop error (non-fatal): %s' % str(e)[:120])
        time.sleep(INTERVAL_SEC)


def _top_objects(n=15):
    c = Counter(type(o).__name__ for o in gc.get_objects())
    return c.most_common(n)


def register_memory_probe(app, backend='backend'):
    from flask import jsonify, request

    if not _STARTED['flag']:
        _STARTED['flag'] = True
        threading.Thread(target=_loop, args=(backend,), daemon=True, name='memprobe').start()

    @app.route('/api/memory', methods=['GET'])
    def api_memory():
        now = _snapshot(backend)
        if request.args.get('objects') in ('1', 'true', 'yes'):
            now['top_objects'] = _top_objects()
        series = {}
        keys = _cmd('KEYS', KEY_PREFIX + backend + ':*') or []
        for k in keys[:12]:
            pts = _cmd('LRANGE', k, 0, KEEP_POINTS - 1) or []
            rows = []
            for p in reversed(pts):
                try:
                    d = json.loads(p)
                    rows.append([d.get('t'), d.get('rss_mb'), d.get('threads'),
                                 (d.get('thread_groups') or [[None, 0]])[0]])
                except Exception:
                    continue
            if rows:
                first, last = rows[0], rows[-1]
                series[k[len(KEY_PREFIX):]] = {
                    'points': len(rows),
                    'rss_first_mb': first[1], 'rss_last_mb': last[1],
                    'threads_first': first[2], 'threads_last': last[2],
                    'from': first[0], 'to': last[0],
                    'series': rows,      # [time, rss_mb, threads, biggest thread group]
                }
        return jsonify({
            'version': PROBE_VERSION,
            'read_me': ('rss_mb = memory of one worker. A steady climb across points is a leak; '
                        'a flat line with a jump points at the job running at that time; '
                        'threads climbing means scans are being started and never finishing.'),
            'this_worker_now': now,
            'workers': series,
        })

    print('[MemProbe] v%s registered: /api/memory (every %d min, %s)' % (
        PROBE_VERSION, INTERVAL_SEC // 60, backend))
