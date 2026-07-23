"""
Asifah Analytics -- GPI Snapshot Writer  (Newsletter Slice 1)
v1.0.0 -- July 23 2026  |  ME backend (lives beside global_pressure_index.py)

WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════
Until now the Global Pressure Index had no memory. Every scan overwrote the
last one, so the platform could describe the present moment but never answer
"what CHANGED?" -- which is the entire premise of the weekly newsletter and,
more importantly, of the platform's own estimative voice. "Historically
precedes" is a claim about time; you cannot make it from a single frame.

This module banks one lean snapshot per UTC day so that deltas, streaks, and
week-over-week reads become computable. Time-series can only accumulate in
wall-clock time -- it cannot be backfilled -- so this runs from day one and
the analysis layer (gpi_delta.py, Slice 2) reads whatever has accrued.

DESIGN: LEAN AND STABLE ON PURPOSE
═══════════════════════════════════════════════════════════════════════
We deliberately do NOT snapshot the whole GPI payload. Capturing everything
means that the day the GPI schema evolves, every historical snapshot stops
comparing cleanly and the archive silently rots. Instead we store a small,
boring core -- levels, labels, categories, counts, identities -- versioned
with `v`, so it survives schema churn.

Signal IDENTITY is the crux: `region|theatre|category` is stable across scans,
which is what lets Slice 2 say "this signal is NEW today" vs "this signal has
been present for six days."

STORAGE (per the Mar 30 2026 architecture decision)
═══════════════════════════════════════════════════════════════════════
  Redis LIST  gpi:history:daily   -- newest first (LPUSH + LTRIM)
  Cap         84 entries          -- 12 weeks of daily snapshots
  TTL         NONE                -- history is the product; it must not expire
  Cadence     one snapshot per UTC day; a same-day re-run REPLACES the day's
              entry rather than adding a duplicate.

ENDPOINTS
═══════════════════════════════════════════════════════════════════════
  GET /api/gpi/snapshot            -- write today's snapshot now (idempotent)
  GET /api/gpi/history?days=N      -- read back the archive
  GET /debug/gpi-snapshot          -- Redis round-trip + archive health

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import time
import threading
from datetime import datetime, timezone

import requests

__version__ = '1.0.0'
SNAPSHOT_SCHEMA_VERSION = 1


# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL   = (os.environ.get('UPSTASH_REDIS_URL')
                       or os.environ.get('UPSTASH_REDIS_REST_URL') or '')
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN') or '')

HISTORY_KEY   = 'gpi:history:daily'
HISTORY_CAP   = 84                    # 12 weeks of daily snapshots
GPI_CACHE_KEY = 'gpi:global:latest'   # written by global_pressure_index.py

SNAPSHOT_INTERVAL_HOURS = 24
SNAPSHOT_BOOT_DELAY_SEC = 120         # let the app settle before first write

_snapshot_lock = threading.Lock()
_snapshot_running = False


# ============================================================
# REDIS (command-array to base URL, with the scheme guard learned Jul 23)
# ============================================================
def _redis_cmd(cmd_array, timeout=10):
    """
    Execute an Upstash REST command array. Returns (ok, result).

    Command-array form is used rather than path-style because snapshot payloads
    are large JSON blobs -- path-style would require URL-encoding the value into
    the URL and would break on length limits.
    """
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        print('[GPI Snapshot] Redis not configured -- URL or TOKEN missing')
        return False, None
    if not UPSTASH_REDIS_URL.startswith('http'):
        print("[GPI Snapshot] ABORT -- UPSTASH_REDIS_URL is not an https REST URL "
              "(starts with '%s...'). Upstash REST needs the https:// endpoint, "
              "not a redis:// connection string." % UPSTASH_REDIS_URL[:10])
        return False, None
    try:
        resp = requests.post(
            UPSTASH_REDIS_URL,
            headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
            json=cmd_array,
            timeout=timeout,
        )
        if resp.status_code != 200:
            print('[GPI Snapshot] Redis %s FAILED: HTTP %s body=%s'
                  % (cmd_array[0], resp.status_code, resp.text[:160]))
            return False, None
        return True, resp.json().get('result')
    except Exception as e:
        print('[GPI Snapshot] Redis %s EXCEPTION: %s: %s'
              % (cmd_array[0], type(e).__name__, str(e)[:140]))
        return False, None


def _redis_get_json(key):
    ok, result = _redis_cmd(['GET', key])
    if not ok or not result:
        return None
    try:
        return json.loads(result)
    except Exception:
        return None


# ============================================================
# SAFE ACCESSORS
# ============================================================
def _d(v):
    return v if isinstance(v, dict) else {}


def _l(v):
    return v if isinstance(v, list) else []


def _i(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _s(v, default=''):
    return v if isinstance(v, str) else default


# ============================================================
# SIGNAL IDENTITY -- the crux of every delta computation
# ============================================================
def signal_identity(sig):
    """
    Build a STABLE identity for a GPI signal.

    Delta analysis lives or dies on this: to say "this signal is new today" we
    need a key that survives re-scans, text edits, and score changes. Category +
    theatre + region is stable; short_text is not (prose gets tuned).

    GPI signals carry either `region` (str) or `regions` (list) -- handle both.
    """
    sig = _d(sig)
    region = _s(sig.get('region'))
    if not region:
        regions = _l(sig.get('regions'))
        region = _s(regions[0]) if regions else 'global'
    theatre = _s(sig.get('theatre'), 'unknown')
    category = _s(sig.get('category'), 'unknown')
    return '%s|%s|%s' % (region, theatre, category)


# ============================================================
# SNAPSHOT DISTILLATION
# ============================================================
def build_snapshot(gpi_data, captured_at=None):
    """
    Distill a full GPI payload into the lean, schema-stable snapshot record.

    Everything captured here is a level, label, count, or identity -- no prose
    bodies, no colors, no nested payloads. That is deliberate: the archive has
    to stay comparable across future GPI schema changes.
    """
    g = _d(gpi_data)
    now = captured_at or datetime.now(timezone.utc)

    # ── axes ──
    axes_block = _d(_d(g.get('pressure_axes')).get('axes'))
    axes = {}
    for axis_name, axis in axes_block.items():
        a = _d(axis)
        axes[axis_name] = {
            'level': _i(a.get('level')),
            'signal_count': _i(a.get('signal_count')),
        }

    # ── regions ──
    regions = {}
    for card in _l(g.get('regional_cards')):
        c = _d(card)
        key = _s(c.get('region'), 'unknown')
        regions[key] = {
            'level':          _i(c.get('level')),
            'posture':        _s(c.get('posture_label')),
            'available':      bool(c.get('available', False)),
            'trackers_live':  _i(c.get('trackers_live')),
            'trackers_total': _i(c.get('trackers_total')),
            'avg_score':      c.get('avg_score', 0),
        }

    # ── signals (identity + level only) ──
    signals = []
    seen = set()
    for sig in _l(g.get('top_signals')):
        s = _d(sig)
        ident = signal_identity(s)
        if ident in seen:
            continue
        seen.add(ident)
        signals.append({
            'id':       ident,
            'level':    _i(s.get('level')),
            'category': _s(s.get('category'), 'unknown'),
            'theatre':  _s(s.get('theatre'), 'unknown'),
            'axis':     _s(s.get('pressure_type')),
            'priority': _i(s.get('priority')),
            # one short label so the digest can name the signal without
            # re-fetching; trimmed because the archive stays lean
            'label':    _s(s.get('short_text'))[:160],
        })

    # ── narratives (identity only) ──
    narratives = []
    for n in _l(g.get('narratives')):
        nd = _d(n)
        narratives.append({
            'category': _s(nd.get('category'), 'unknown'),
            'priority': _i(nd.get('priority')),
            'headline': _s(nd.get('headline'))[:160],
        })

    completeness = _d(g.get('data_completeness'))

    return {
        'v':            SNAPSHOT_SCHEMA_VERSION,
        'date':         now.strftime('%Y-%m-%d'),
        'captured_at':  now.isoformat(),
        'global': {
            'level': _i(g.get('global_level')),
            'label': _s(g.get('global_label')),
        },
        'headline_axis': _s(_d(g.get('pressure_axes')).get('headline_axis')),
        'axes':          axes,
        'regions':       regions,
        'signals':       signals,
        'narratives':    narratives,
        'completeness': {
            'regions_live':     _i(completeness.get('regions_live')),
            'regions_expected': _i(completeness.get('regions_expected')),
            'picture_complete': bool(completeness.get('picture_complete', False)),
            'incomplete':       _l(completeness.get('incomplete_regions')),
        },
        'counts': {
            'signals':    len(signals),
            'narratives': len(narratives),
        },
    }


# ============================================================
# READ / WRITE ARCHIVE
# ============================================================
def read_history(limit=HISTORY_CAP):
    """Return snapshots newest-first. Empty list when nothing banked yet."""
    ok, result = _redis_cmd(['LRANGE', HISTORY_KEY, '0', str(max(0, int(limit) - 1))])
    if not ok or not result:
        return []
    out = []
    for item in result:
        try:
            out.append(json.loads(item))
        except Exception:
            continue
    return out


def _fetch_gpi(force=False):
    """
    Get current GPI state. Prefers the in-process function (same backend), so
    the snapshot never depends on an HTTP self-call. Falls back to the cache.
    """
    try:
        from global_pressure_index import build_gpi
        return build_gpi(force=force)
    except ImportError:
        print('[GPI Snapshot] global_pressure_index not importable -- reading cache')
    except Exception as e:
        print('[GPI Snapshot] build_gpi failed (%s) -- reading cache' % str(e)[:120])
    return _redis_get_json(GPI_CACHE_KEY)


def write_snapshot(force_gpi=False):
    """
    Capture today's snapshot.

    One entry per UTC day: a same-day re-run REPLACES the head rather than
    appending, so an hourly scheduler or a manual poke cannot inflate the
    archive with duplicates. Returns a small status dict.
    """
    gpi = _fetch_gpi(force=force_gpi)
    # Absence-honest: never bank an empty or failed GPI read. A missing day in
    # the archive is honest; a fabricated zero-state day would poison every
    # delta computed across it.
    if not gpi:
        return {'success': False, 'error': 'GPI data unavailable', 'written': False}
    if _d(gpi).get('success') is False:
        return {'success': False, 'error': 'GPI reported success=false', 'written': False}
    if not _d(gpi).get('global_level') and not _l(_d(gpi).get('regional_cards')):
        return {'success': False, 'error': 'GPI payload empty', 'written': False}

    snap = build_snapshot(gpi)
    payload = json.dumps(snap, default=str)

    # Is today already banked?
    head = read_history(limit=1)
    replaced = False
    if head and _d(head[0]).get('date') == snap['date']:
        ok, _ = _redis_cmd(['LSET', HISTORY_KEY, '0', payload])
        replaced = True
        if not ok:
            return {'success': False, 'error': 'LSET failed', 'written': False}
    else:
        ok, _ = _redis_cmd(['LPUSH', HISTORY_KEY, payload])
        if not ok:
            return {'success': False, 'error': 'LPUSH failed', 'written': False}
        _redis_cmd(['LTRIM', HISTORY_KEY, '0', str(HISTORY_CAP - 1)])

    ok_len, length = _redis_cmd(['LLEN', HISTORY_KEY])
    depth = _i(length) if ok_len else None

    print('[GPI Snapshot] %s snapshot for %s (global L%s, %d signals) -- archive depth %s'
          % ('REPLACED' if replaced else 'WROTE', snap['date'],
             snap['global']['level'], snap['counts']['signals'], depth))

    return {
        'success':       True,
        'written':       True,
        'replaced':      replaced,
        'date':          snap['date'],
        'global_level':  snap['global']['level'],
        'signal_count':  snap['counts']['signals'],
        'archive_depth': depth,
        'archive_cap':   HISTORY_CAP,
    }


# ============================================================
# SCHEDULER
# ============================================================
def _snapshot_loop(interval_hours=SNAPSHOT_INTERVAL_HOURS):
    def loop():
        time.sleep(SNAPSHOT_BOOT_DELAY_SEC)
        while True:
            global _snapshot_running
            with _snapshot_lock:
                if _snapshot_running:
                    time.sleep(60)
                    continue
                _snapshot_running = True
            try:
                write_snapshot()
            except Exception as e:
                print('[GPI Snapshot] scheduled write failed: %s' % str(e)[:160])
            finally:
                with _snapshot_lock:
                    _snapshot_running = False
            time.sleep(interval_hours * 3600)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print('[GPI Snapshot] Scheduler started (%ds boot delay -> every %dh)'
          % (SNAPSHOT_BOOT_DELAY_SEC, interval_hours))


# ============================================================
# ROUTES
# ============================================================
def register_gpi_snapshot_routes(app, start_scheduler=True):
    """Register snapshot endpoints on the given Flask app."""
    from flask import jsonify, request as flask_request

    @app.route('/api/gpi/snapshot', methods=['GET', 'POST'])
    def gpi_snapshot_write():
        force = flask_request.args.get('force', 'false').lower() in ('true', '1', 'yes')
        return jsonify(write_snapshot(force_gpi=force))

    @app.route('/api/gpi/history', methods=['GET'])
    def gpi_snapshot_history():
        try:
            days = int(flask_request.args.get('days', HISTORY_CAP))
        except (TypeError, ValueError):
            days = HISTORY_CAP
        days = max(1, min(days, HISTORY_CAP))
        hist = read_history(limit=days)
        return jsonify({
            'success':      True,
            'count':        len(hist),
            'cap':          HISTORY_CAP,
            'oldest':       hist[-1]['date'] if hist else None,
            'newest':       hist[0]['date'] if hist else None,
            'schema':       SNAPSHOT_SCHEMA_VERSION,
            'history':      hist,
            'note':         ('History accumulates in wall-clock time and cannot be '
                             'backfilled. Depth grows one entry per day.'),
        })

    @app.route('/debug/gpi-snapshot', methods=['GET'])
    def gpi_snapshot_debug():
        """Redis round-trip + archive health, in one call."""
        out = {
            'module':     'gpi_snapshot v%s' % __version__,
            'schema':     SNAPSHOT_SCHEMA_VERSION,
            'history_key': HISTORY_KEY,
            'cap':        HISTORY_CAP,
            'url_is_https_rest': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_URL.startswith('https')),
            'token_set':  bool(UPSTASH_REDIS_TOKEN),
        }
        ok_set, _ = _redis_cmd(['SET', 'gpi:snapshot:debug:ping',
                                json.dumps({'ping': datetime.now(timezone.utc).isoformat()}),
                                'EX', '120'])
        out['redis_write_ok'] = bool(ok_set)
        ok_len, length = _redis_cmd(['LLEN', HISTORY_KEY])
        out['archive_depth'] = _i(length) if ok_len else None
        hist = read_history(limit=3)
        out['newest_dates'] = [h.get('date') for h in hist]
        out['gpi_cache_present'] = _redis_get_json(GPI_CACHE_KEY) is not None
        out['verdict'] = ('Snapshot archive healthy' if ok_set and out['archive_depth']
                          else 'No snapshots banked yet -- hit /api/gpi/snapshot to seed'
                          if ok_set else 'Redis write failing -- see logs')
        return jsonify(out)

    if start_scheduler:
        _snapshot_loop()

    print('[GPI Snapshot] \u2705 Routes registered: /api/gpi/snapshot, /api/gpi/history, /debug/gpi-snapshot')


# ============================================================
# SELF-TEST
# ============================================================
if __name__ == '__main__':
    sample = {
        'success': True, 'global_level': 5, 'global_label': 'ACTIVE CONFLICT',
        'pressure_axes': {'headline_axis': 'kinetic', 'axes': {
            'kinetic': {'level': 6, 'signal_count': 23},
            'economic': {'level': 5, 'signal_count': 24},
        }},
        'regional_cards': [
            {'region': 'africa', 'level': 4, 'posture_label': 'ELEVATED', 'available': True,
             'trackers_live': 1, 'trackers_total': 1, 'avg_score': 35.0},
            {'region': 'me', 'level': 0, 'posture_label': 'Unavailable', 'available': False,
             'trackers_live': 0, 'trackers_total': 0},
        ],
        'top_signals': [
            {'category': 'red_line_breached', 'level': 6, 'region': 'africa',
             'theatre': 'somalia', 'pressure_type': 'kinetic', 'priority': 10,
             'short_text': 'SOMALIA: AUSSOM Collapse'},
            {'category': 'wheat_lebanon', 'level': 5, 'regions': ['me', 'europe'],
             'theatre': 'global', 'pressure_type': 'economic', 'priority': 13,
             'short_text': 'Wheat-Lebanon convergence'},
        ],
        'narratives': [{'category': 'china_taiwan_takeover', 'priority': 14,
                        'headline': 'China at coercion threshold'}],
        'data_completeness': {'regions_live': 4, 'regions_expected': 5,
                              'picture_complete': False, 'incomplete_regions': ['me']},
    }
    snap = build_snapshot(sample)
    print('Snapshot schema v%s for %s' % (snap['v'], snap['date']))
    print('  global:     L%s %s' % (snap['global']['level'], snap['global']['label']))
    print('  axes:       %s' % {k: v['level'] for k, v in snap['axes'].items()})
    print('  regions:    %s' % {k: v['level'] for k, v in snap['regions'].items()})
    print('  signals:    %d' % snap['counts']['signals'])
    for s in snap['signals']:
        print('     %s  L%s' % (s['id'], s['level']))
    print('  narratives: %d' % snap['counts']['narratives'])
    size = len(json.dumps(snap))
    print('  size:       %d bytes (x84 days = %.0f KB archive)' % (size, size * 84 / 1024))
    assert snap['signals'][0]['id'] == 'africa|somalia|red_line_breached'
    assert snap['signals'][1]['id'] == 'me|global|wheat_lebanon', snap['signals'][1]['id']
    print('\nIdentity keys stable \u2705  (region|theatre|category)')
