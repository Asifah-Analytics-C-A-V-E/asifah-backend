"""
Asifah Analytics -- INSTANCE LOCK
v1.0.0 -- September 27 2026  |  portable, drop into any backend

WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════
Sep 27 2026: /api/gdelt-trickle/stats and /health, ten seconds apart,
answered with different started_at values. The ME backend runs TWO Render
instances -- a deliberate capacity decision -- and each instance imports
every module and starts every background thread. The web app SHOULD run
twice. The background workers should not.

Duplicated background work is invisible in the payload and expensive
everywhere else: two GDELT walkers on one query list, two full scans every
four hours, two Telegram sweeps resolving the same handles, two Reddit
sweeps racing each other into the same 429.

Two modules already solved this privately (humanitarian_article_gatherer
and commodity_tracker each carry their own copy of an Upstash SET NX EX
lock). This is that pattern, extracted once, so the next background thread
gets it in two lines instead of forty.

USAGE
═══════════════════════════════════════════════════════════════════════
    from instance_lock import own_this_job

    def _my_loop():
        while True:
            if not own_this_job('me_background_refresh'):
                time.sleep(300)          # standby: re-check, take over if owner dies
                continue
            ...do the work...
            time.sleep(INTERVAL)

Call it EVERY cycle, not once: the owner renews its claim, and a standby
takes over within ttl_sec of the owner dying.

FAIL-OPEN, ON PURPOSE. No Upstash, or an unreachable Upstash, returns True
-- a stalled job is worse than a duplicated one. lock_status() says which
state produced the answer, so 'we checked and we own it' and 'we could not
check' never look alike (handover lesson 5.5).

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import threading
import time
import uuid
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

DEFAULT_TTL_SEC = int(os.environ.get('INSTANCE_LOCK_TTL_SEC', '900'))   # 15 min
KEY_PREFIX = 'sched_lock:'

# Unique per PROCESS. Two Render instances can share a pid, so the pid
# alone is not an identity -- that is why the uuid is here.
WORKER_ID = '%s-%s' % (os.getpid(), uuid.uuid4().hex[:8])

_lock = threading.Lock()
_jobs = {}     # job -> {'role', 'checks', 'lost', 'last_at', 'last_error'}


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _rec(job):
    return _jobs.setdefault(job, {
        'role': 'unknown', 'checks': 0, 'lost': 0,
        'last_at': None, 'last_error': None,
    })


def _cmd(payload, timeout=6):
    return requests.post(UPSTASH_URL,
                         headers={'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
                         json=payload, timeout=timeout)


def own_this_job(job, ttl_sec=DEFAULT_TTL_SEC, quiet=False):
    """True if THIS process should run `job`. Call once per cycle."""
    key = KEY_PREFIX + job
    with _lock:
        rec = _rec(job)
        rec['checks'] += 1
        rec['last_at'] = _iso()
        previous = rec['role']

    if not REDIS_OK:
        with _lock:
            _rec(job)['role'] = 'unknown'
        return True

    try:
        r = _cmd(['SET', key, WORKER_ID, 'NX', 'EX', str(int(ttl_sec))])
        if r.ok and (r.json() or {}).get('result') == 'OK':
            with _lock:
                _rec(job)['role'] = 'owner'
            if not quiet and previous != 'owner':
                print('[InstanceLock] %s: this instance OWNS it (%s)' % (job, WORKER_ID))
            return True

        g = requests.get('%s/get/%s' % (UPSTASH_URL, key),
                         headers={'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
                         timeout=6)
        holder = (g.json() or {}).get('result') if g.ok else None

        if holder == WORKER_ID:
            _cmd(['SET', key, WORKER_ID, 'EX', str(int(ttl_sec))])   # renew
            with _lock:
                _rec(job)['role'] = 'owner'
            return True

        with _lock:
            rec = _rec(job)
            if rec['role'] == 'owner':
                rec['lost'] += 1
                if not quiet:
                    print('[InstanceLock] %s: lost to %s -- standing by'
                          % (job, str(holder)[:40]))
            elif not quiet and rec['role'] != 'standby':
                print('[InstanceLock] %s: another instance owns it -- standing by' % job)
            rec['role'] = 'standby'
        return False

    except Exception as e:
        with _lock:
            rec = _rec(job)
            rec['role'] = 'unknown'
            rec['last_error'] = str(e)[:120]
        if not quiet:
            print('[InstanceLock] %s: lock check failed (%s) -- proceeding (fail-open)'
                  % (job, str(e)[:80]))
        return True


def release(job):
    """Give up a lock deliberately (shutdown, or a one-shot job finishing)."""
    if not REDIS_OK:
        return False
    key = KEY_PREFIX + job
    try:
        g = requests.get('%s/get/%s' % (UPSTASH_URL, key),
                         headers={'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
                         timeout=6)
        if g.ok and (g.json() or {}).get('result') == WORKER_ID:
            _cmd(['DEL', key])
            with _lock:
                _rec(job)['role'] = 'released'
            return True
    except Exception:
        pass
    return False


def lock_status():
    """Wire into any /health endpoint: who is doing what on this instance."""
    with _lock:
        jobs = {k: dict(v) for k, v in _jobs.items()}
    return {
        'version':   __version__,
        'worker_id': WORKER_ID,
        'redis_ok':  REDIS_OK,
        'ttl_sec':   DEFAULT_TTL_SEC,
        'note':      ('No Upstash configured -- every job reports role=unknown '
                      'and runs (fail-open). With two instances that means '
                      'duplicated work.') if not REDIS_OK else None,
        'jobs':      jobs,
    }


if __name__ == '__main__':
    print('Instance Lock v%s -- self-test\n' % __version__)
    import sys, types
    store = {}

    class FakeResp(object):
        def __init__(self, result):
            self.ok = True
            self._r = result

        def json(self):
            return {'result': self._r}

    def fake_post(url, headers=None, json=None, timeout=None):
        cmd = json
        if cmd[0] == 'SET':
            k, v = cmd[1], cmd[2]
            if 'NX' in cmd and k in store:
                return FakeResp(None)
            store[k] = v
            return FakeResp('OK')
        if cmd[0] == 'DEL':
            store.pop(cmd[1], None)
            return FakeResp(1)

    def fake_get(url, headers=None, timeout=None):
        return FakeResp(store.get(url.split('/get/')[1]))

    globals()['requests'] = types.SimpleNamespace(post=fake_post, get=fake_get)
    globals()['REDIS_OK'] = True
    globals()['UPSTASH_URL'] = 'https://fake'
    globals()['UPSTASH_TOKEN'] = 'tok'

    print('TEST 1 -- first caller owns it')
    assert own_this_job('demo') is True
    assert _jobs['demo']['role'] == 'owner'
    print('  OK\n')

    print('TEST 2 -- a second process stands by')
    mine = WORKER_ID
    globals()['WORKER_ID'] = 'other-instance'
    _jobs.clear()
    assert own_this_job('demo') is False
    assert _jobs['demo']['role'] == 'standby'
    print('  OK -- one owner, one standby\n')

    print('TEST 3 -- the owner renews rather than re-claiming')
    globals()['WORKER_ID'] = mine
    _jobs.clear()
    assert own_this_job('demo') is True
    assert store['sched_lock:demo'] == mine
    print('  OK\n')

    print('TEST 4 -- the standby takes over when the owner dies')
    store.clear()                      # lock expired
    globals()['WORKER_ID'] = 'other-instance'
    assert own_this_job('demo') is True
    print('  OK -- no job is orphaned\n')

    print('TEST 5 -- release gives it back')
    assert release('demo') is True
    assert 'sched_lock:demo' not in store
    print('  OK\n')

    print('TEST 6 -- no Upstash: fail-open, and SAY so')
    globals()['REDIS_OK'] = False
    _jobs.clear()
    assert own_this_job('demo') is True
    assert _jobs['demo']['role'] == 'unknown'
    s = lock_status()
    assert s['note'] and 'duplicated work' in s['note']
    print('  role=unknown, not owner -- "could not check" is its own state\n')

    print('ALL INSTANCE LOCK TESTS PASSED')
