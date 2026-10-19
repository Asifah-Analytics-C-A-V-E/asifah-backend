"""
Asifah Analytics -- INSTANCE LOCK
v1.1.0 -- October 18 2026  |  portable, drop into any backend
   (v1.0.0 -- September 27 2026)

WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════
The ME backend runs TWO Render instances -- a deliberate capacity decision
-- and each instance imports every module and starts every background
thread. The web app SHOULD run twice. The background workers should not:
two scans means two hits on every RSS publisher, two Telegram sweeps
resolving the same handles (Oct 18: an 8-hour Telegram FloodWait), two
Reddit sweeps racing into the same 403 -- twice the footprint of a bot
for the same information.

WHAT v1.0.0 GOT WRONG (Oct 18 2026)
═══════════════════════════════════════════════════════════════════════
v1.0.0 locked each job with SET NX EX 900 (15 min) and the owner renewed
only when it next checked -- once per CYCLE, i.e. every 4-12 hours. So
the lock lapsed 15 minutes into every sleep, the standby (polling every
5 min) took it and ran the same scan, and the original owner took it
back on waking. Both instances scanned every cycle, ~20 minutes apart.
The "another instance owns it -- standing by" line was true for exactly
fifteen minutes. The Oct 18 log showed every scan twice.

Six modules carried private copies of the lock with a second bug: the
worker id was "w<pid>", and two Render containers start gunicorn the same
way, so both workers are usually pid 41 -- each saw "its own" id on the
lock and both ran.

v1.1.0 -- ONE LEADER PER BACKEND, RENEWED BY HEARTBEAT
═══════════════════════════════════════════════════════════════════════
  * One lease per service: sched_lock:leader:<RENDER_SERVICE_NAME>.
    The instance holding it runs ALL background jobs; the other serves
    web requests and stands by.
  * A heartbeat thread renews the lease every 3 min (TTL 10 min), so the
    leader keeps it through 12-hour sleeps. If the leader dies, the
    standby takes over within ~10 minutes. On clean shutdown (deploy) the
    leader releases it at once.
  * Per-job checks are LOCAL -- own_this_job() reads the heartbeat's last
    answer, it does not call Upstash. ~1 Upstash command per 3 minutes
    per instance, regardless of how many jobs there are.
  * my_turn(job) -- the one-line gate for a loop, with a STAGGER: the
    first job to ask goes at once, the next waits 30s, the next 60s ...
    so a reboot releases ~30 scans as a steady stream over ~15 minutes
    instead of all in the same minute.
  * Identity is pid + uuid; never the pid alone.
  * FAIL-OPEN, unchanged: no Upstash -> every job runs, and lock_status()
    says role='unknown' -- "we could not check" never looks like "we own it".

USAGE
═══════════════════════════════════════════════════════════════════════
    from instance_lock import my_turn

    def _my_loop():
        while True:
            if not my_turn('my_job'):
                continue                 # standby; my_turn already waited
            ...do the work...
            time.sleep(INTERVAL)

    own_this_job('my_job') still works exactly as before (True/False),
    for the callers written against v1.0.0.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import atexit
import threading
import time
import uuid
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    requests = None

__version__ = '1.1.0'

UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_URL')
               or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                 or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
REDIS_OK = bool(UPSTASH_URL and UPSTASH_TOKEN and requests is not None)


def _env_i(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return int(default)


LEASE_TTL_SEC   = _env_i('INSTANCE_LOCK_TTL_SEC', 600)        # 10 min
HEARTBEAT_SEC   = max(30, _env_i('INSTANCE_LOCK_HEARTBEAT_SEC', 180))
STAGGER_GAP_SEC = _env_i('INSTANCE_STAGGER_GAP_SEC', 30)      # between first runs
STANDBY_SLEEP   = 300
DEFAULT_TTL_SEC = LEASE_TTL_SEC                                # v1.0.0 name, kept
SCOPE   = (os.environ.get('INSTANCE_LOCK_SCOPE')
           or os.environ.get('RENDER_SERVICE_NAME') or 'local')
KEY_PREFIX = 'sched_lock:'
LEADER_KEY = KEY_PREFIX + 'leader:' + SCOPE

# Unique per PROCESS. Two Render instances usually share a pid (both start
# gunicorn the same way) -- that is why the uuid is here.
WORKER_ID = '%s-%s' % (os.getpid(), uuid.uuid4().hex[:8])
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()

# Lua: renew only if we still hold it; release only if we still hold it.
_RENEW_LUA = ("if redis.call('get', KEYS[1]) == ARGV[1] then "
              "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end")
_RELEASE_LUA = ("if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end")

_lock = threading.Lock()
_jobs = {}     # job -> {'role','checks','turns','last_at','stagger_sec','first_call_done'}
_slots = {'next': 0}
_leader = {
    'role': 'unknown',          # leader | standby | unknown
    'since': None, 'last_ok_at': None, 'last_error': None,
    'became_leader': 0, 'lost': 0, 'beats': 0, 'holder_seen': None,
    'heartbeat_running': False, 'eval_ok': True,
}


def _now():
    return time.time()


def _sleep(s):
    time.sleep(s)


def _iso():
    return datetime.now(timezone.utc).isoformat()


# -- Upstash ------------------------------------------------------------------
def _cmd(payload, timeout=6):
    """One Upstash REST command. Returns `result` (raises on transport error)."""
    r = requests.post(UPSTASH_URL,
                      headers={'Authorization': 'Bearer %s' % UPSTASH_TOKEN},
                      json=[str(p) for p in payload], timeout=timeout)
    body = r.json() if r.ok else {}
    if not r.ok or (isinstance(body, dict) and body.get('error')):
        raise RuntimeError('upstash: %s' % (body.get('error') if isinstance(body, dict)
                                            else r.status_code))
    return (body or {}).get('result')


def _claim():
    """Try to become leader. True if we hold the lease afterwards."""
    return _cmd(['SET', LEADER_KEY, WORKER_ID, 'NX', 'EX', LEASE_TTL_SEC]) == 'OK'


def _renew():
    """Extend our lease. True if we still hold it."""
    if _leader['eval_ok']:
        try:
            return int(_cmd(['EVAL', _RENEW_LUA, 1, LEADER_KEY, WORKER_ID,
                             LEASE_TTL_SEC]) or 0) == 1
        except RuntimeError as e:
            if 'upstash' in str(e) and 'NOSCRIPT' not in str(e):
                # Scripting refused on this plan -> fall back to GET + SET XX.
                _leader['eval_ok'] = False
            else:
                raise
    holder = _cmd(['GET', LEADER_KEY])
    if holder != WORKER_ID:
        _leader['holder_seen'] = holder
        return False
    return _cmd(['SET', LEADER_KEY, WORKER_ID, 'XX', 'EX', LEASE_TTL_SEC]) == 'OK'


def _beat():
    """One heartbeat: leaders renew, everyone else tries to claim."""
    if not REDIS_OK:
        with _lock:
            _leader['role'] = 'unknown'
        return 'unknown'
    try:
        with _lock:
            was = _leader['role']
        if was == 'leader':
            held = _renew()
        else:
            held = _claim()
        with _lock:
            _leader['beats'] += 1
            _leader['last_ok_at'] = _iso()
            _leader['last_error'] = None
            if held and was != 'leader':
                _leader['role'] = 'leader'
                _leader['since'] = _iso()
                _leader['became_leader'] += 1
                print('[InstanceLock] %s: this instance is now the BACKGROUND LEADER (%s) '
                      '-- it runs the scans; the other instance serves and stands by'
                      % (SCOPE, WORKER_ID))
            elif not held and was == 'leader':
                _leader['role'] = 'standby'
                _leader['lost'] += 1
                print('[InstanceLock] %s: LOST the leader lease -- standing by '
                      '(a scan already running will finish; no new ones start here)' % SCOPE)
            elif not held and was != 'standby':
                _leader['role'] = 'standby'
                print('[InstanceLock] %s: another instance is the background leader '
                      '-- standing by (takes over within %ds if it dies)'
                      % (SCOPE, LEASE_TTL_SEC))
            return _leader['role']
    except Exception as e:
        with _lock:
            _leader['last_error'] = str(e)[:140]
            # Fail-open, but keep a known leader a leader through a blip:
            # it still holds the lease until TTL unless someone else took it.
            if _leader['role'] != 'leader':
                _leader['role'] = 'unknown'
            return _leader['role']


def _heartbeat_loop():
    while True:
        _sleep(HEARTBEAT_SEC)
        _beat()


def _ensure_heartbeat():
    with _lock:
        if _leader['heartbeat_running']:
            return
        _leader['heartbeat_running'] = True
    _beat()                                   # decide now, not in 3 minutes
    threading.Thread(target=_heartbeat_loop, daemon=True,
                     name='InstanceLockHeartbeat').start()


def _release_leader():
    if not REDIS_OK or _leader['role'] != 'leader':
        return False
    try:
        if _leader['eval_ok']:
            _cmd(['EVAL', _RELEASE_LUA, 1, LEADER_KEY, WORKER_ID], timeout=3)
        elif _cmd(['GET', LEADER_KEY], timeout=3) == WORKER_ID:
            _cmd(['DEL', LEADER_KEY], timeout=3)
        with _lock:
            _leader['role'] = 'released'
        print('[InstanceLock] %s: leader lease released on shutdown' % SCOPE)
        return True
    except Exception:
        return False


atexit.register(_release_leader)


# -- Public ---------------------------------------------------------------------
def _rec(job):
    return _jobs.setdefault(job, {
        'role': 'unknown', 'checks': 0, 'turns': 0, 'last_at': None,
        'stagger_sec': None, 'first_call_done': False,
    })


def _take_slot():
    """Next first-run offset: 0, GAP, 2*GAP ... (caller holds _lock)."""
    off = _slots['next'] * max(0, STAGGER_GAP_SEC)
    _slots['next'] += 1
    return off


def own_this_job(job, ttl_sec=None, quiet=False):
    """True if THIS process should run `job` now. Call once per cycle.

    v1.1.0: True on the background leader (or when the lock cannot be
    checked -- fail-open). `ttl_sec` is accepted for v1.0.0 callers and
    ignored: the lease is renewed by the heartbeat, not by the caller.
    """
    _ensure_heartbeat()
    with _lock:
        role = _leader['role']
        rec = _rec(job)
        rec['checks'] += 1
        rec['last_at'] = _iso()
        previous = rec['role']
        rec['role'] = {'leader': 'owner', 'standby': 'standby'}.get(role, 'unknown')
        if rec['role'] == 'owner':
            rec['turns'] += 1
    if not quiet and rec['role'] != previous:
        if rec['role'] == 'owner':
            print('[InstanceLock] %s: running on this instance (leader)' % job)
        elif rec['role'] == 'standby':
            print('[InstanceLock] %s: another instance owns it -- standing by' % job)
        else:
            print('[InstanceLock] %s: lock could not be checked -- running (fail-open)' % job)
    return rec['role'] in ('owner', 'unknown')


def my_turn(job, standby_sleep=STANDBY_SLEEP):
    """Gate for the top of a background loop.

        while True:
            if not my_turn('saudi_rhetoric_scan'):
                continue
            ...

    First call: waits this job's stagger slot, so a reboot does not fire
    every scan in the same minute. Returns True when this instance should
    do the work now. Returns False after sleeping `standby_sleep` when
    another instance is the leader -- the caller just `continue`s.
    """
    with _lock:
        rec = _rec(job)
        first = not rec['first_call_done']
        rec['first_call_done'] = True
        if first:
            rec['stagger_sec'] = _take_slot()
        wait = rec['stagger_sec'] if first else 0
    if wait:
        print('[InstanceLock] %s: first run staggered %ds (steady stream, not a burst)'
              % (job, wait))
        _sleep(wait)
    if own_this_job(job):
        return True
    _sleep(standby_sleep)
    return False


def release(job=None):
    """Give up leadership deliberately (v1.0.0 signature kept)."""
    return _release_leader()


def lock_status():
    """Wire into any /health endpoint: who is doing what on this instance."""
    with _lock:
        jobs = {k: {kk: vv for kk, vv in v.items() if kk != 'first_call_done'}
                for k, v in _jobs.items()}
        leader = dict(_leader)
    return {
        'version':     __version__,
        'worker_id':   WORKER_ID,
        'process_started_at': PROCESS_STARTED_AT,
        'scope':       SCOPE,
        'redis_ok':    REDIS_OK,
        'role':        leader['role'],
        'leader':      leader,
        'lease_ttl_sec': LEASE_TTL_SEC, 'heartbeat_sec': HEARTBEAT_SEC,
        'stagger_gap_sec': STAGGER_GAP_SEC, 'jobs_staggered': _slots['next'],
        'ttl_sec':     LEASE_TTL_SEC,
        'note': (('No Upstash configured -- every job reports role=unknown and '
                  'runs (fail-open). With two instances that means duplicated work.')
                 if not REDIS_OK else
                 ('One leader per service runs every background job; the other '
                  'instance serves web requests. role=standby is healthy.')),
        'jobs':        jobs,
    }


# =====================================================================
# SELF-TEST  --  python3 instance_lock.py   (no network)
# =====================================================================
if __name__ == '__main__':
    import sys
    import types

    res = {'pass': 0, 'fail': 0}

    def check(name, cond, detail=''):
        res['pass' if cond else 'fail'] += 1
        print('  %s  %s%s' % ('PASS' if cond else 'FAIL', name, '' if cond else '  -- %s' % detail))

    clock = {'t': 1_800_000_000.0}
    slept = []
    globals()['_now'] = lambda: clock['t']

    def fake_sleep(s):
        slept.append(s)
        clock['t'] += s
    globals()['_sleep'] = fake_sleep

    class Store:
        def __init__(self):
            self.kv, self.exp, self.up, self.eval_ok, self.n = {}, {}, True, True, 0

        def _alive(self, k):
            if k in self.exp and self.exp[k] <= clock['t']:
                self.kv.pop(k, None)
                self.exp.pop(k, None)
            return k in self.kv

    store = Store()

    class Resp:
        def __init__(self, result=None, error=None):
            self.ok = True
            self._b = {'error': error} if error else {'result': result}

        def json(self):
            return self._b

    def fake_post(url, headers=None, json=None, timeout=None):
        if not store.up:
            raise ConnectionError('down')
        store.n += 1
        c = json
        op = c[0]
        if op == 'SET':
            k, v = c[1], c[2]
            alive = store._alive(k)
            if 'NX' in c and alive:
                return Resp(None)
            if 'XX' in c and not alive:
                return Resp(None)
            store.kv[k] = v
            if 'EX' in c:
                store.exp[k] = clock['t'] + int(c[c.index('EX') + 1])
            return Resp('OK')
        if op == 'GET':
            return Resp(store.kv.get(c[1]) if store._alive(c[1]) else None)
        if op == 'DEL':
            store.kv.pop(c[1], None)
            return Resp(1)
        if op == 'EVAL':
            if not store.eval_ok:
                return Resp(error='ERR unknown command EVAL')
            k, me = c[3], c[4]
            if not (store._alive(k) and store.kv[k] == me):
                return Resp(0)
            if 'expire' in c[1]:
                store.exp[k] = clock['t'] + int(c[5])
                return Resp(1)
            store.kv.pop(k, None)
            return Resp(1)
        raise ValueError(op)

    globals()['requests'] = types.SimpleNamespace(post=fake_post)
    globals()['REDIS_OK'] = True
    globals()['UPSTASH_URL'] = 'https://fake'
    globals()['UPSTASH_TOKEN'] = 'tok'

    def become(worker):
        """Switch this process's identity to simulate another instance."""
        globals()['WORKER_ID'] = worker
        _jobs.clear()
        _leader.update({'role': 'unknown', 'since': None, 'beats': 0,
                        'heartbeat_running': True, 'eval_ok': True})

    print('Instance Lock v%s -- self-test' % __version__)

    print('0 canary')
    check('fake store expires keys', (store.kv.update({'x': 1}) or store.exp.update({'x': clock['t'] - 1}) or True) and not store._alive('x'))

    print('1 first instance becomes leader; jobs run')
    become('A')
    check('A leader', _beat() == 'leader')
    check('own_this_job True on leader', own_this_job('demo', quiet=True) is True)

    print('2 second instance stands by; jobs do not run there')
    become('B')
    check('B standby', _beat() == 'standby')
    check('own_this_job False on standby', own_this_job('demo', quiet=True) is False)

    print('3 THE v1.0.0 BUG: leader keeps the lease through a 12h sleep')
    become('A'); _leader['role'] = 'leader'
    for _ in range(int(12 * 3600 / HEARTBEAT_SEC)):        # A heartbeats while its loop sleeps
        clock['t'] += HEARTBEAT_SEC
        _beat()
    check('A still leader after 12h', _leader['role'] == 'leader' and store.kv.get(LEADER_KEY) == 'A')
    saved = dict(_leader)
    become('B')
    check('B still standby after 12h (no lapse, no double scan)', _beat() == 'standby')
    become('A'); _leader.update(saved)

    print('4 leader dies -> standby takes over within the TTL')
    clock['t'] += LEASE_TTL_SEC + 1                          # A stops beating
    become('B')
    check('B leader after A dies', _beat() == 'leader')

    print('5 deploy: clean shutdown releases at once')
    check('release works', _release_leader() is True and not store._alive(LEADER_KEY))
    become('C')
    check('new instance leads immediately', _beat() == 'leader')

    print('6 same pid on both instances cannot both lead (uuid identity)')
    store.kv.clear(); store.exp.clear()
    become('41-aaaa1111'); r1 = _beat()
    become('41-bbbb2222'); r2 = _beat()
    check('one leader, one standby', sorted([r1, r2]) == ['leader', 'standby'], (r1, r2))

    print('7 lost lease is noticed and demotes')
    become('41-aaaa1111'); _leader['role'] = 'leader'
    store.kv[LEADER_KEY] = 'someone-else'; store.exp[LEADER_KEY] = clock['t'] + 600
    check('demoted to standby', _beat() == 'standby' and _leader['lost'] == 1)

    print('8 EVAL refused -> GET + SET XX fallback still renews')
    store.kv.clear(); store.exp.clear(); store.eval_ok = False
    become('E'); _beat()
    clock['t'] += HEARTBEAT_SEC
    check('renew without EVAL', _beat() == 'leader' and _leader['eval_ok'] is False)
    store.eval_ok = True

    print('9 per-job checks cost ZERO Upstash commands')
    n0 = store.n
    for i in range(500):
        own_this_job('job%d' % (i % 30), quiet=True)
    check('500 checks, 0 commands', store.n == n0, store.n - n0)

    print('10 my_turn: stagger once, then gate; standby sleeps and returns False')
    become('L'); store.kv.clear(); store.exp.clear(); _beat()
    del slept[:]
    _slots['next'] = 0
    my_turn('first_job')                       # slot 0: no wait
    t1 = my_turn('saudi_rhetoric_scan')        # slot 1: one gap
    t2 = my_turn('saudi_rhetoric_scan')        # no second stagger
    check('leader: True twice, staggered once', t1 and t2 and slept == [STAGGER_GAP_SEC], slept)
    become('S'); _beat(); del slept[:]; _slots['next'] = 0
    t3 = my_turn('saudi_rhetoric_scan')
    check('standby: False after standby sleep', t3 is False and slept[-1] == STANDBY_SLEEP, slept)

    print('11 stagger: N jobs -> N distinct slots, evenly spaced')
    become('L2'); store.kv.clear(); store.exp.clear(); _beat(); _slots['next'] = 0; del slept[:]
    names = ['job%d' % i for i in range(27)]
    for n in names:
        my_turn(n)
    offs = [_jobs[n]['stagger_sec'] for n in names]
    check('distinct, gap-spaced', offs == [i * STAGGER_GAP_SEC for i in range(27)], offs[:5])
    check('27 jobs released over %d min' % (offs[-1] // 60), offs[-1] <= 15 * 60)

    print('12 Upstash down: fail-open, role=unknown, and SAID so')
    become('U'); store.up = False
    check('unknown', _beat() == 'unknown' and own_this_job('x', quiet=True) is True)
    check('status says unknown', lock_status()['role'] == 'unknown')
    store.up = True

    print('13 a leader keeps leading through a brief Upstash blip')
    store.kv.clear(); store.exp.clear(); become('K'); _beat()
    store.up = False
    check('still leader during blip', _beat() == 'leader')
    store.up = True
    check('renews after blip', _beat() == 'leader')

    print('14 no Upstash configured at all: runs, status note warns')
    globals()['REDIS_OK'] = False
    become('N')
    check('runs', own_this_job('y', quiet=True) is True)
    check('note warns of duplication', 'duplicated work' in lock_status()['note'])

    print('\n%d PASS, %d FAIL' % (res['pass'], res['fail']))
    sys.exit(1 if res['fail'] else 0)
