"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — TEMPO BASELINE ENGINE
  v1.0.0 (Jul 12 2026) · ME backend (PRIMARY)
═══════════════════════════════════════════════════════════════════════

The actor-baseline infrastructure the Black Swan Master Plan lists as a
blocker for the "Quiet Before Storm" module. Generic, registry-driven, and
platform-wide: adding DPRK, Hezbollah, the Houthis or Poland is ONE REGISTRY
LINE, not a new module.

WHY THIS LIVES ON THE ME BACKEND
--------------------------------
Baselines are LOCAL data with SHARED logic. Poland's corpus is gathered by the
Europe backend; Hezbollah's by ME. Nothing overlaps -- so a proxy would run the
data BACKWARDS (Europe gathers -> ships to ME -> ME computes -> Europe fetches
back). No proxy is needed, because every backend already shares one Upstash
Redis. Redis IS the bus.

  EMITTER  (~20 lines, in each rhetoric tracker, any backend)
      Writes raw daily counts + corpus health. No logic.
      Key: tempo:{target}:counts:{YYYY-MM-DD}   TTL 45d

  ENGINE   (this file, ME backend -- the ONE place the algorithm lives)
      Reads counts for any registered target. Rolling window. Deviation rules.
      Corpus-health guard. Writes tempo:{target}:baseline.

  READER   (one Redis GET, in each tracker)
      Hands the baseline to its interpreter.

Only TRACKERS emit: they are the only layer that touches the raw corpus. BLUFs
and the GPI never see an article, so they cannot count one -- they are readers.


TWO MODES — and the distinction is the whole analytical point
-------------------------------------------------------------
  mode='actor'  A CLAIMING actor. Hezbollah and the Houthis announce their
                operations. An actor that normally claims and suddenly goes
                silent is telling you something. Silence IS the signal.

  mode='tape'   A DENIABLE actor. Russia never claims a thing in Poland --
                deniability is the entire architecture. There is no claiming
                actor to fall silent, so measuring "actor silence" would measure
                nothing. Instead we measure the TAPE: attack tempo, attribution
                tempo, amplification tempo, each against its own baseline.

Using the wrong mode produces confident nonsense. Poland is not Hezbollah.


THE CORPUS-HEALTH GUARD — the reason this engine exists
--------------------------------------------------------
The existing per-tracker baselines (Lebanon, Yemen) have no denominator. If the
RSS feeds die, statement_count falls to zero and the tracker announces
"Unusual quiet -- possible operational security." That is not an actor going
dark. That is OUR FETCHERS DYING and the platform hallucinating menace from its
own outage.

So every count carries a corpus-health denominator (articles seen, sources
alive). When the corpus is sick relative to ITS OWN baseline, the engine
REFUSES to call a quiet -- it says "corpus degraded, cannot assess quiet" and
means it. Silence only means something when measured by a working sensor.

Surge calls survive a degraded corpus (a spike found despite fewer sources is
MORE notable, not less). Quiet calls do not. The asymmetry is deliberate.


ROLLING WINDOW, NOT EMA — the second fix
-----------------------------------------
The existing trackers use an exponential moving average (alpha=0.2). For a
quiet detector this is backwards: a sustained quiet DRAGS THE BASELINE DOWN
toward the quiet, so after ~5 quiet scans the anomaly self-cancels. The longer
an actor stays dark, the less anomalous the model thinks it is -- and the most
dangerous silence is precisely the one that lasts.

A rolling window over raw daily counts does not decay. Day 20 of silence is
still measured against a normal that predates the silence.
"""

import os
import json
import statistics
from datetime import datetime, timezone, timedelta

import requests
from flask import jsonify, request

VERSION = '1.0.0'

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

COUNTS_TTL      = 45 * 24 * 3600     # raw daily counts
BASELINE_TTL    = 14 * 24 * 3600     # computed baseline
WINDOW_DAYS     = 30                 # rolling window
MIN_DAYS_READY  = 10                 # below this we make NO deviation call
SHORT_WINDOW    = 7                  # "recent" comparison window

# Corpus is "degraded" when it falls below this fraction of its own baseline.
CORPUS_SICK_RATIO = 0.55

SURGE_MULTIPLE  = 2.0    # current >= 2x baseline mean
QUIET_RATIO     = 0.30   # current <= 30% of baseline mean
QUIET_MIN_MEAN  = 3.0    # never call quiet on an actor who barely speaks anyway


# ════════════════════════════════════════════════════════════
# THE REGISTRY — adding a target is ONE ENTRY
# ════════════════════════════════════════════════════════════

TEMPO_REGISTRY = {
    # ── mode='actor' — CLAIMING actors. Silence is the signal. ──
    'hezbollah': {
        'theatre': 'lebanon', 'backend': 'me', 'mode': 'actor',
        'streams': ['statements'],
        'flag': '\U0001f1f1\U0001f1e7',
        'note': ('Claims its operations. An actor that normally claims and then goes quiet '
                 'is the canonical quiet-before-storm case: operational security, internal '
                 'confusion, or awaiting patron direction.'),
    },
    'houthis': {
        'theatre': 'yemen', 'backend': 'me', 'mode': 'actor',
        'streams': ['statements'],
        'flag': '\U0001f1fe\U0001f1ea',
        'note': ('Claims maritime operations, usually fast. A lengthening time-to-claim, or a '
                 'drop in claim cadence after a period of high tempo, is signal.'),
    },

    # ── mode='tape' — DENIABLE actors. Measure the tape, not the actor. ──
    'poland': {
        'theatre': 'poland', 'backend': 'europe', 'mode': 'tape',
        'streams': ['attack', 'attribution', 'amplification'],
        'flag': '\U0001f1f5\U0001f1f1',
        'note': ('Russia NEVER claims its hybrid operations in Poland -- deniability is the '
                 'architecture. There is no claiming actor to fall silent, so we measure the '
                 'tape: attack tempo, Polish attribution tempo, and amplification tempo. '
                 'Amplification surging while attacks go quiet is consistent with narrative '
                 'shaping ahead of an operation.'),
    },

    # ── Future targets: uncomment when the emitter ships in that tracker. ──
    # 'dprk': {
    #     'theatre': 'dprk', 'backend': 'asia', 'mode': 'actor',
    #     'streams': ['statements', 'kcna_cadence'],
    #     'flag': '\U0001f1f0\U0001f1f5',
    #     'note': 'The canonical quiet-before-storm case. KCNA routine pauses are signal.',
    # },
    # 'irgc': {
    #     'theatre': 'iran', 'backend': 'me', 'mode': 'actor',
    #     'streams': ['statements'],
    #     'flag': '\U0001f1ee\U0001f1f7',
    # },
    # 'greenland': {
    #     'theatre': 'greenland', 'backend': 'europe', 'mode': 'tape',
    #     'streams': ['inbound_rhetoric', 'amplification'],
    #     'flag': '\U0001f1ec\U0001f1f1',
    # },
}


# ════════════════════════════════════════════════════════════
# REDIS
# ════════════════════════════════════════════════════════════

def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(f'{UPSTASH_REDIS_URL}/get/{key}',
                         headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                         timeout=5)
        d = r.json()
        if d.get('result'):
            return json.loads(d['result'])
    except Exception as e:
        print(f'[Tempo] Redis get error ({key}): {str(e)[:100]}')
    return None


def _redis_setex(key, value, ttl):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(UPSTASH_REDIS_URL,
                          headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                                   'Content-Type': 'application/json'},
                          json=['SET', key, json.dumps(value, default=str), 'EX', ttl],
                          timeout=8)
        return r.status_code == 200
    except Exception as e:
        print(f'[Tempo] Redis set error ({key}): {str(e)[:100]}')
        return False


def counts_key(target, day):
    return f'tempo:{target}:counts:{day}'


def baseline_key(target):
    return f'tempo:{target}:baseline'


# ════════════════════════════════════════════════════════════
# EMITTER  (imported by trackers on ANY backend — no logic, just a write)
# ════════════════════════════════════════════════════════════

def emit_counts(target, streams, corpus):
    """Called by a rhetoric tracker at the end of each scan.

    Args:
        target: registry key ('hezbollah', 'poland', 'houthis'...)
        streams: dict of raw counts, e.g. {'statements': 12}
                 or {'attack': 4, 'attribution': 1, 'amplification': 7}
        corpus:  dict describing THE SENSOR'S OWN HEALTH -- the denominator that
                 lets the engine tell "the actor was quiet" apart from "we were
                 deaf". REQUIRED:
                     {'articles': int, 'sources_live': int, 'sources_total': int}

    Idempotent per day: a second scan on the same date overwrites, keeping the
    HIGHER stream counts and the HEALTHIER corpus reading (two scans a day
    should not halve the apparent tempo).
    """
    if target not in TEMPO_REGISTRY:
        print(f'[Tempo] emit_counts: unknown target {target!r} -- not in registry, ignoring')
        return False

    day = datetime.now(timezone.utc).date().isoformat()
    key = counts_key(target, day)

    corpus = corpus or {}
    articles = int(corpus.get('articles', 0) or 0)
    live = int(corpus.get('sources_live', 0) or 0)
    total = int(corpus.get('sources_total', 0) or 0)

    record = {
        'target': target,
        'day': day,
        'ts': datetime.now(timezone.utc).isoformat(),
        'streams': {k: int(v or 0) for k, v in (streams or {}).items()},
        'corpus': {'articles': articles, 'sources_live': live, 'sources_total': total},
    }

    prior = _redis_get(key)
    if isinstance(prior, dict):
        for k, v in (prior.get('streams') or {}).items():
            record['streams'][k] = max(record['streams'].get(k, 0), int(v or 0))
        pc = prior.get('corpus') or {}
        record['corpus']['articles'] = max(articles, int(pc.get('articles', 0) or 0))
        record['corpus']['sources_live'] = max(live, int(pc.get('sources_live', 0) or 0))
        record['corpus']['sources_total'] = max(total, int(pc.get('sources_total', 0) or 0))

    ok = _redis_setex(key, record, COUNTS_TTL)
    if ok:
        print(f"[Tempo] {target}: emitted {record['streams']} "
              f"(corpus: {record['corpus']['articles']} articles, "
              f"{record['corpus']['sources_live']}/{record['corpus']['sources_total']} sources)")
    return ok


# ════════════════════════════════════════════════════════════
# ENGINE — rolling window + corpus guard
# ════════════════════════════════════════════════════════════

def _load_window(target, days=WINDOW_DAYS):
    """Load the last N daily count records. Missing days are simply absent --
    we do NOT zero-fill. A day with no record is a day we did not scan, which is
    not the same as a day with nothing to report, and conflating them would
    manufacture quiet out of downtime."""
    today = datetime.now(timezone.utc).date()
    out = []
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        rec = _redis_get(counts_key(target, d))
        if isinstance(rec, dict) and rec.get('streams') is not None:
            out.append(rec)
    out.sort(key=lambda r: r.get('day', ''))
    return out


def compute_baseline(target):
    """Rolling-window baseline for one registered target. Writes
    tempo:{target}:baseline and returns it."""
    cfg = TEMPO_REGISTRY.get(target)
    if not cfg:
        return {'ready': False, 'reason': f'unknown target {target!r}'}

    window = _load_window(target)
    n = len(window)

    payload = {
        'target':       target,
        'mode':         cfg['mode'],
        'theatre':      cfg.get('theatre'),
        'streams':      cfg['streams'],
        'days_observed': n,
        'window_days':  WINDOW_DAYS,
        'computed_at':  datetime.now(timezone.utc).isoformat(),
        'version':      VERSION,
    }

    if n < MIN_DAYS_READY:
        payload.update({
            'ready': False,
            'reason': f'baseline accumulating ({n}/{MIN_DAYS_READY} days observed)',
            'baselines': {},
            'corpus_health': None,
            'suppress_quiet': True,
        })
        _redis_setex(baseline_key(target), payload, BASELINE_TTL)
        print(f'[Tempo] {target}: baseline NOT ready ({n}/{MIN_DAYS_READY} days)')
        return payload

    # ── Per-stream rolling stats. No EMA: a sustained quiet must NOT drag the
    # baseline down toward itself, or the longest and most dangerous silences
    # would look the most normal.
    baselines = {}
    for stream in cfg['streams']:
        series = [int((r.get('streams') or {}).get(stream, 0) or 0) for r in window]
        recent = series[-SHORT_WINDOW:] if len(series) >= SHORT_WINDOW else series
        try:
            stdev = statistics.pstdev(series) if len(series) > 1 else 0.0
        except statistics.StatisticsError:
            stdev = 0.0
        baselines[stream] = {
            'mean_7d':   round(statistics.mean(recent), 2) if recent else 0.0,
            'mean_30d':  round(statistics.mean(series), 2) if series else 0.0,
            'stdev':     round(stdev, 2),
            'max':       max(series) if series else 0,
            'days':      len(series),
        }

    # ── Corpus baseline: how healthy is the SENSOR normally?
    arts = [int((r.get('corpus') or {}).get('articles', 0) or 0) for r in window]
    live = [int((r.get('corpus') or {}).get('sources_live', 0) or 0) for r in window]
    corpus_baseline = {
        'mean_articles':     round(statistics.mean(arts), 1) if arts else 0.0,
        'mean_sources_live': round(statistics.mean(live), 1) if live else 0.0,
    }

    payload.update({
        'ready':           True,
        'reason':          None,
        'baselines':       baselines,
        'corpus_baseline': corpus_baseline,
        'suppress_quiet':  False,   # per-scan; evaluate() recomputes against live corpus
    })
    _redis_setex(baseline_key(target), payload, BASELINE_TTL)
    print(f'[Tempo] {target}: baseline READY ({n} days) -- '
          + ', '.join(f"{k} mean7d={v['mean_7d']}" for k, v in baselines.items()))
    return payload


def read_baseline(target, live_corpus=None):
    """READER — what a tracker calls before handing the baseline to its
    interpreter. One Redis GET, plus the corpus guard applied against THIS
    scan's corpus health.

    THE GUARD: if this scan's corpus is materially sicker than its own baseline,
    we set suppress_quiet=True. A quiet read is then refused -- because we
    cannot distinguish "the actor went silent" from "we went deaf." Surge reads
    survive: a spike detected despite fewer sources is MORE notable, not less.
    """
    bl = _redis_get(baseline_key(target))
    if not isinstance(bl, dict):
        return {'ready': False, 'reason': 'no baseline computed yet',
                'suppress_quiet': True, 'baselines': {}, 'target': target}

    if not bl.get('ready'):
        bl['suppress_quiet'] = True
        return bl

    cb = bl.get('corpus_baseline') or {}
    mean_arts = cb.get('mean_articles') or 0
    mean_live = cb.get('mean_sources_live') or 0

    if live_corpus and mean_arts >= 5:
        arts = int(live_corpus.get('articles', 0) or 0)
        live = int(live_corpus.get('sources_live', 0) or 0)
        art_ratio = (arts / mean_arts) if mean_arts else 1.0
        src_ratio = (live / mean_live) if mean_live else 1.0
        health = round(min(art_ratio, src_ratio), 2)
        sick = health < CORPUS_SICK_RATIO
        bl['corpus_health'] = health
        bl['suppress_quiet'] = sick
        if sick:
            bl['corpus_warning'] = (
                f'CORPUS DEGRADED (health {health:.2f}): this scan saw {arts} articles from '
                f'{live} live sources against a baseline of {mean_arts:.0f} articles / '
                f'{mean_live:.0f} sources. Quiet reads are SUPPRESSED -- we cannot tell an '
                f'actor going silent from our own sensor going deaf. Surge reads remain valid.')
            print(f'[Tempo] {target}: ⚠️ CORPUS DEGRADED (health {health:.2f}) -- '
                  f'quiet calls suppressed')
    else:
        bl['corpus_health'] = None
        bl['suppress_quiet'] = False

    return bl


def evaluate(target, current_streams, live_corpus=None):
    """Full deviation read for a target. The ONE place the deviation algorithm
    lives -- change it here, every theatre changes.

    Returns flags + an estimative read. Absence-honest and corpus-guarded."""
    bl = read_baseline(target, live_corpus)
    cfg = TEMPO_REGISTRY.get(target, {})
    mode = cfg.get('mode', 'tape')

    out = {
        'target': target, 'mode': mode,
        'ready': bl.get('ready', False),
        'suppress_quiet': bl.get('suppress_quiet', True),
        'corpus_health': bl.get('corpus_health'),
        'corpus_warning': bl.get('corpus_warning'),
        'baselines': bl.get('baselines', {}),
        'flags': [], 'surges': [], 'quiets': [],
        'read': bl.get('reason') or 'Baseline accumulating -- no deviation call yet.',
    }
    if not bl.get('ready'):
        return out

    for stream, now in (current_streams or {}).items():
        base = (bl.get('baselines') or {}).get(stream)
        if not base:
            continue
        mean = base.get('mean_30d') or 0
        now = int(now or 0)

        if mean >= 1 and now >= mean * SURGE_MULTIPLE:
            f = f'{stream} SURGE ({now} vs {mean:.1f} baseline)'
            out['flags'].append(f)
            out['surges'].append(stream)
        elif (mean >= QUIET_MIN_MEAN and now <= mean * QUIET_RATIO
              and not out['suppress_quiet']):
            f = f'{stream} ANOMALOUS QUIET ({now} vs {mean:.1f} baseline)'
            out['flags'].append(f)
            out['quiets'].append(stream)

    parts = []
    if out['flags']:
        parts.append('Tempo deviation: ' + '; '.join(out['flags']) + '.')

    # ── Mode-specific estimative reads ──
    if mode == 'actor' and out['quiets']:
        parts.append(
            f"{target.title()} is a claiming actor: it normally announces its operations. A "
            'sustained drop below baseline is consistent with operational security, internal '
            'confusion, or awaiting patron direction -- the pattern that has historically '
            'preceded significant action rather than followed it. The reader completes the '
            'inference.')
    if mode == 'tape':
        if 'amplification' in out['surges'] and 'attack' in out['quiets']:
            parts.append(
                'Amplification is surging while attack tempo goes quiet. Consistent with '
                'narrative shaping ahead of an operation, or with a deliberate shift of '
                'instrument. Either way the quiet is not peace.')
        if 'attribution' in out['quiets'] and 'attack' in out['surges']:
            parts.append(
                'Attacks are surging while public attribution falls -- the state is absorbing '
                'hits without naming its attacker. That is a political signal, not a security '
                'one.')

    if out['suppress_quiet'] and out['corpus_warning']:
        parts.append(out['corpus_warning'])
    if not parts:
        parts.append('Tempo within baseline across all measured streams.')
    out['read'] = ' '.join(parts)
    return out


def compute_all():
    """Recompute every registered target. Called by the ME background loop."""
    results = {}
    for target in TEMPO_REGISTRY:
        try:
            bl = compute_baseline(target)
            results[target] = {'ready': bl.get('ready'), 'days': bl.get('days_observed')}
        except Exception as e:
            print(f'[Tempo] compute error for {target}: {str(e)[:120]}')
            results[target] = {'ready': False, 'error': str(e)[:100]}
    return results


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════

def register_tempo_endpoints(app):

    @app.route('/api/tempo/registry', methods=['GET'])
    def api_tempo_registry():
        return jsonify({
            'version': VERSION,
            'targets': {
                t: {'mode': c['mode'], 'theatre': c.get('theatre'),
                    'backend': c.get('backend'), 'streams': c['streams'],
                    'note': c.get('note', '')}
                for t, c in TEMPO_REGISTRY.items()
            },
            'config': {
                'window_days': WINDOW_DAYS, 'min_days_ready': MIN_DAYS_READY,
                'surge_multiple': SURGE_MULTIPLE, 'quiet_ratio': QUIET_RATIO,
                'corpus_sick_ratio': CORPUS_SICK_RATIO,
            },
        })

    @app.route('/api/tempo/<target>', methods=['GET'])
    def api_tempo_target(target):
        if target not in TEMPO_REGISTRY:
            return jsonify({'error': f'unknown target {target!r}',
                            'known': sorted(TEMPO_REGISTRY.keys())}), 404
        if request.args.get('force', 'false').lower() == 'true':
            return jsonify(compute_baseline(target))
        return jsonify(read_baseline(target))

    @app.route('/api/tempo/compute', methods=['GET', 'POST'])
    def api_tempo_compute():
        return jsonify({'success': True, 'results': compute_all(),
                        'computed_at': datetime.now(timezone.utc).isoformat()})

    @app.route('/debug/tempo', methods=['GET'])
    def debug_tempo():
        """Per-target: how many days of tape, is it ready, and what does the raw
        window actually look like."""
        out = {}
        for target in TEMPO_REGISTRY:
            window = _load_window(target)
            bl = _redis_get(baseline_key(target)) or {}
            out[target] = {
                'mode':           TEMPO_REGISTRY[target]['mode'],
                'days_in_window': len(window),
                'ready':          bl.get('ready', False),
                'reason':         bl.get('reason'),
                'baselines':      bl.get('baselines', {}),
                'corpus_baseline': bl.get('corpus_baseline'),
                'recent_days':    [{'day': r.get('day'), 'streams': r.get('streams'),
                                    'corpus': r.get('corpus')} for r in window[-5:]],
            }
        return jsonify({
            'version': VERSION,
            'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'targets': out,
        })

    print('[Tempo] Endpoints registered: /api/tempo/registry, /api/tempo/<target>, '
          '/api/tempo/compute, /debug/tempo')
