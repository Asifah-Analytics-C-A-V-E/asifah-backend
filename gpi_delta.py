"""
Asifah Analytics -- GPI Delta Engine  (Newsletter Slice 2)
v1.0.0 -- July 23 2026  |  ME backend (reads gpi_snapshot.py's archive)

WHAT THIS IS
═══════════════════════════════════════════════════════════════════════
Slice 1 banks one lean snapshot per day. This module turns that archive into
the thing the platform has never been able to say: WHAT CHANGED.

It is the analytical primitive under the weekly newsletter -- "what you need to
know to start the week" -- but it is useful well before any newsletter exists,
because it answers questions the GPI alone cannot:

  * Is the kinetic axis at L6 unusual, or has it been there for a week?
  * Is Somalia new to the top signals, or has it been leading for days?
  * Which signals appeared since Monday, and which quietly dropped off?
  * How long has Europe been CRITICAL?

DOCTRINE
═══════════════════════════════════════════════════════════════════════
Convergence, not prediction -- and that discipline extends here. This module
reports observed change and observed persistence. It never extrapolates a trend
forward, never says "rising toward," never implies a next value. A streak is a
fact about the past; the reader completes the inference.

Absence-honesty matters doubly in a time series. A day with no snapshot is
reported as a GAP, never interpolated. A delta computed across a gap says so.
Comparing against thin history is labelled thin rather than dressed up.

READS
═══════════════════════════════════════════════════════════════════════
  Redis LIST  gpi:history:daily  (written by gpi_snapshot.py, newest first)

ENDPOINTS
═══════════════════════════════════════════════════════════════════════
  GET /api/gpi/delta?days=7      -- diff today vs N days ago
  GET /api/gpi/delta/summary     -- multi-window (1d/7d/30d) + streaks.
                                    This is the newsletter payload.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import json
from datetime import datetime, timezone, timedelta

__version__ = '1.0.0'

try:
    from gpi_snapshot import read_history, HISTORY_CAP
    _SNAPSHOT_AVAILABLE = True
except ImportError:                                   # pragma: no cover
    _SNAPSHOT_AVAILABLE = False
    HISTORY_CAP = 84

    def read_history(limit=84):
        return []


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


def _parse_date(datestr):
    try:
        return datetime.strptime(_s(datestr), '%Y-%m-%d').date()
    except Exception:
        return None


# ============================================================
# WINDOW SELECTION
# ============================================================
def _find_comparison(history, days_back):
    """
    Pick the snapshot closest to `days_back` days before the newest one.

    Snapshots are daily but the archive can have GAPS (backend down, deploy
    window). Rather than silently comparing against whatever happens to sit at
    index N, we target a DATE and report the actual gap we landed on, so the
    caller can label an imprecise comparison honestly.
    """
    if len(history) < 2:
        return None, None
    newest = history[0]
    newest_date = _parse_date(_d(newest).get('date'))
    if not newest_date:
        return None, None
    target = newest_date - timedelta(days=days_back)

    best, best_gap = None, None
    for snap in history[1:]:
        d = _parse_date(_d(snap).get('date'))
        if not d:
            continue
        gap = abs((d - target).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = snap, gap
    if best is None:
        return None, None
    actual_days = (newest_date - _parse_date(_d(best).get('date'))).days
    return best, actual_days


def _window_sufficient(requested_days, actual_days):
    """
    Is the archive deep enough to honestly CALL this an N-day comparison?

    Doctrine guard. Without this the engine would happily label an 8-day-old
    snapshot as the '30 day' comparison, and a newsletter would then say
    'over the past month' on eight days of data. Tolerance scales with the
    window (a 30d read can sit a few days off; a 1d read cannot be 9 days off).
    """
    if actual_days is None:
        return False
    tolerance = max(1, int(round(requested_days * 0.2)))
    return actual_days >= max(1, requested_days - tolerance)


# ============================================================
# CORE DIFF
# ============================================================
def compare(current, previous):
    """
    Structured diff between two snapshots. Pure function -- no I/O.

    Signal identity (region|theatre|category) is what makes appeared/resolved
    meaningful; see gpi_snapshot.signal_identity.
    """
    cur, prev = _d(current), _d(previous)

    # ── global ──
    cg, pg = _d(cur.get('global')), _d(prev.get('global'))
    cur_lvl, prev_lvl = _i(cg.get('level')), _i(pg.get('level'))
    global_delta = {
        'from':      prev_lvl,
        'to':        cur_lvl,
        'change':    cur_lvl - prev_lvl,
        'direction': 'up' if cur_lvl > prev_lvl else 'down' if cur_lvl < prev_lvl else 'flat',
        'from_label': _s(pg.get('label')),
        'to_label':   _s(cg.get('label')),
    }

    # ── axes ──
    axes = {}
    for name in set(list(_d(cur.get('axes')).keys()) + list(_d(prev.get('axes')).keys())):
        c = _i(_d(_d(cur.get('axes')).get(name)).get('level'))
        p = _i(_d(_d(prev.get('axes')).get(name)).get('level'))
        if c != p:
            axes[name] = {'from': p, 'to': c, 'change': c - p,
                          'direction': 'up' if c > p else 'down'}

    # ── regions ──
    regions = {}
    for name in set(list(_d(cur.get('regions')).keys()) + list(_d(prev.get('regions')).keys())):
        c = _d(_d(cur.get('regions')).get(name))
        p = _d(_d(prev.get('regions')).get(name))
        cl, pl = _i(c.get('level')), _i(p.get('level'))
        posture_changed = _s(c.get('posture')) != _s(p.get('posture'))
        avail_changed = bool(c.get('available')) != bool(p.get('available'))
        tracker_delta = _i(c.get('trackers_live')) - _i(p.get('trackers_live'))
        if cl != pl or posture_changed or avail_changed or tracker_delta:
            regions[name] = {
                'from': pl, 'to': cl, 'change': cl - pl,
                'direction': 'up' if cl > pl else 'down' if cl < pl else 'flat',
                'posture_from': _s(p.get('posture')),
                'posture_to':   _s(c.get('posture')),
                'posture_changed': posture_changed,
                'availability_changed': avail_changed,
                'available_now': bool(c.get('available')),
                'tracker_delta': tracker_delta,
            }

    # ── signals ──
    cur_sigs = {_s(s.get('id')): _d(s) for s in _l(cur.get('signals')) if _s(_d(s).get('id'))}
    prev_sigs = {_s(s.get('id')): _d(s) for s in _l(prev.get('signals')) if _s(_d(s).get('id'))}

    appeared = [cur_sigs[k] for k in cur_sigs if k not in prev_sigs]
    resolved = [prev_sigs[k] for k in prev_sigs if k not in cur_sigs]
    escalated, deescalated, persisting = [], [], []
    for k in cur_sigs:
        if k not in prev_sigs:
            continue
        c_lvl, p_lvl = _i(cur_sigs[k].get('level')), _i(prev_sigs[k].get('level'))
        entry = dict(cur_sigs[k])
        entry['from'] = p_lvl
        entry['to'] = c_lvl
        if c_lvl > p_lvl:
            escalated.append(entry)
        elif c_lvl < p_lvl:
            deescalated.append(entry)
        else:
            persisting.append(entry)

    for lst in (appeared, resolved, escalated, deescalated):
        lst.sort(key=lambda s: -_i(s.get('level')))

    # ── narratives ──
    cur_narr = {_s(_d(n).get('category')) for n in _l(cur.get('narratives'))}
    prev_narr = {_s(_d(n).get('category')) for n in _l(prev.get('narratives'))}
    narr_map = {_s(_d(n).get('category')): _d(n) for n in _l(cur.get('narratives'))}
    prev_map = {_s(_d(n).get('category')): _d(n) for n in _l(prev.get('narratives'))}

    return {
        'from_date': _s(prev.get('date')),
        'to_date':   _s(cur.get('date')),
        'global':    global_delta,
        'axes':      axes,
        'regions':   regions,
        'signals': {
            'appeared':    appeared,
            'resolved':    resolved,
            'escalated':   escalated,
            'deescalated': deescalated,
            'persisting_count': len(persisting),
            'total_now':   len(cur_sigs),
            'total_then':  len(prev_sigs),
        },
        'narratives': {
            'appeared': [narr_map[c] for c in (cur_narr - prev_narr) if c in narr_map],
            'faded':    [prev_map[c] for c in (prev_narr - cur_narr) if c in prev_map],
            'sustained_count': len(cur_narr & prev_narr),
        },
    }


# ============================================================
# STREAKS -- persistence is a finding, not just change
# ============================================================
def compute_streaks(history, axis_floor=5, region_floor=4):
    """
    How long has the current condition held?

    A level that has been elevated for nine consecutive days is a different
    analytical object from one that spiked this morning, and the GPI alone
    cannot tell them apart. Streaks are stated as observed persistence only --
    never projected forward.
    """
    if not history:
        return {'available': False, 'reason': 'no history'}

    newest = _d(history[0])
    streaks = {'axes': {}, 'regions': {}, 'signals': [], 'global': None}

    # global level streak (consecutive days at or above today's level)
    cur_global = _i(_d(newest.get('global')).get('level'))
    run = 0
    for snap in history:
        if _i(_d(_d(snap).get('global')).get('level')) >= cur_global:
            run += 1
        else:
            break
    streaks['global'] = {'level': cur_global, 'days': run}

    # axis streaks at/above floor
    for name, a in _d(newest.get('axes')).items():
        lvl = _i(_d(a).get('level'))
        if lvl < axis_floor:
            continue
        run = 0
        for snap in history:
            if _i(_d(_d(_d(snap).get('axes')).get(name)).get('level')) >= axis_floor:
                run += 1
            else:
                break
        streaks['axes'][name] = {'level': lvl, 'days': run, 'floor': axis_floor}

    # region streaks at/above floor
    for name, r in _d(newest.get('regions')).items():
        lvl = _i(_d(r).get('level'))
        if lvl < region_floor:
            continue
        run = 0
        for snap in history:
            if _i(_d(_d(_d(snap).get('regions')).get(name)).get('level')) >= region_floor:
                run += 1
            else:
                break
        streaks['regions'][name] = {'level': lvl, 'days': run, 'floor': region_floor}

    # signal persistence + first-seen
    cur_ids = {_s(_d(s).get('id')): _d(s) for s in _l(newest.get('signals'))}
    for sid, sig in cur_ids.items():
        run = 0
        for snap in history:
            ids = {_s(_d(s).get('id')) for s in _l(_d(snap).get('signals'))}
            if sid in ids:
                run += 1
            else:
                break
        streaks['signals'].append({
            'id': sid, 'label': _s(sig.get('label')), 'level': _i(sig.get('level')),
            'days': run, 'first_seen_in_window': run < len(history),
        })
    streaks['signals'].sort(key=lambda s: (-s['days'], -s['level']))
    streaks['available'] = True
    streaks['window_days'] = len(history)
    return streaks


# ============================================================
# ARCHIVE HEALTH -- gaps are reported, never smoothed
# ============================================================
def archive_health(history):
    """Report depth and any missing days. A gap is a fact, not a defect to hide."""
    if not history:
        return {'depth': 0, 'gaps': [], 'contiguous': False,
                'note': 'No snapshots banked yet.'}
    dates = [_parse_date(_d(s).get('date')) for s in history]
    dates = [d for d in dates if d]
    gaps = []
    for i in range(len(dates) - 1):
        delta = (dates[i] - dates[i + 1]).days
        if delta > 1:
            gaps.append({'after': dates[i + 1].isoformat(),
                         'before': dates[i].isoformat(),
                         'missing_days': delta - 1})
    return {
        'depth': len(history),
        'newest': dates[0].isoformat() if dates else None,
        'oldest': dates[-1].isoformat() if dates else None,
        'span_days': (dates[0] - dates[-1]).days + 1 if len(dates) > 1 else 1,
        'gaps': gaps,
        'contiguous': not gaps,
    }


# ============================================================
# PUBLIC API
# ============================================================
def build_delta(days=7):
    """Diff the newest snapshot against ~`days` ago."""
    history = read_history(limit=HISTORY_CAP)
    health = archive_health(history)

    if len(history) < 2:
        return {
            'success': False,
            'reason': 'insufficient_history',
            'message': ('Delta needs at least two daily snapshots. History accumulates '
                        'in wall-clock time and cannot be backfilled.'),
            'archive': health,
        }

    prev, actual_days = _find_comparison(history, days)
    if prev is None:
        return {'success': False, 'reason': 'no_comparison_point', 'archive': health}

    diff = compare(history[0], prev)
    diff['success'] = True
    diff['requested_days'] = days
    diff['actual_days'] = actual_days
    diff['window_exact'] = (actual_days == days)
    diff['window_sufficient'] = _window_sufficient(days, actual_days)
    diff['archive'] = health
    if actual_days != days:
        diff['window_note'] = ('Closest available snapshot is %d days back, not %d -- '
                               'archive does not yet span the requested window.'
                               % (actual_days, days))
    return diff


def build_summary():
    """
    Multi-window summary + streaks. This is the newsletter payload.

    Windows chosen to match the intended Monday-morning read: what moved
    yesterday, what moved over the week, what moved over the month.
    """
    history = read_history(limit=HISTORY_CAP)
    health = archive_health(history)
    newest = _d(history[0]) if history else {}

    out = {
        'success': True,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'version': __version__,
        'archive': health,
        'current': {
            'date':    _s(newest.get('date')),
            'global':  _d(newest.get('global')),
            'axes':    {k: _i(_d(v).get('level')) for k, v in _d(newest.get('axes')).items()},
            'regions': {k: _i(_d(v).get('level')) for k, v in _d(newest.get('regions')).items()},
            'signal_count': _i(_d(newest.get('counts')).get('signals')),
        },
        'windows': {},
        'streaks': compute_streaks(history) if history else {'available': False},
        'doctrine_note': ('Observed change and observed persistence only. No trend is '
                          'projected forward. Gaps in the archive are reported, never '
                          'interpolated. Convergence, not prediction.'),
    }

    if len(history) < 2:
        out['success'] = False
        out['reason'] = 'insufficient_history'
        out['message'] = ('Banking has begun but no comparison is possible yet. '
                          'A 1-day delta becomes available on the second snapshot; '
                          'the 7-day window fills out over the first week.')
        return out

    for label, days in (('1d', 1), ('7d', 7), ('30d', 30)):
        prev, actual = _find_comparison(history, days)
        if prev is None or not _window_sufficient(days, actual):
            out['windows'][label] = {
                'available': False,
                'reason': 'archive does not span this window yet',
                'requested_days': days,
                'closest_available_days': actual,
                'note': ('Archive is %s day(s) deep; a %d-day comparison would be an '
                         'overclaim. This window opens as history accumulates.'
                         % (actual if actual is not None else 0, days)),
            }
            continue
        diff = compare(history[0], prev)
        out['windows'][label] = {
            'available':     True,
            'requested_days': days,
            'actual_days':   actual,
            'exact':         actual == days,
            'from_date':     diff['from_date'],
            'global':        diff['global'],
            'axes':          diff['axes'],
            'regions':       diff['regions'],
            'signals': {
                'appeared':    diff['signals']['appeared'][:8],
                'resolved':    diff['signals']['resolved'][:8],
                'escalated':   diff['signals']['escalated'][:8],
                'deescalated': diff['signals']['deescalated'][:8],
                'appeared_count':  len(diff['signals']['appeared']),
                'resolved_count':  len(diff['signals']['resolved']),
                'escalated_count': len(diff['signals']['escalated']),
                'persisting_count': diff['signals']['persisting_count'],
            },
            'narratives': diff['narratives'],
        }
    return out


# ============================================================
# ROUTES
# ============================================================
def register_gpi_delta_routes(app):
    """Register delta endpoints on the given Flask app."""
    from flask import jsonify, request as flask_request

    @app.route('/api/gpi/delta', methods=['GET'])
    def gpi_delta():
        try:
            days = int(flask_request.args.get('days', 7))
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(days, HISTORY_CAP))
        return jsonify(build_delta(days=days))

    @app.route('/api/gpi/delta/summary', methods=['GET'])
    def gpi_delta_summary():
        return jsonify(build_summary())

    print('[GPI Delta] \u2705 Routes registered: /api/gpi/delta, /api/gpi/delta/summary')


# ============================================================
# SELF-TEST
# ============================================================
if __name__ == '__main__':
    def snap(date, glvl, kinetic, africa_lvl, sigs, narrs=('china_taiwan_takeover',)):
        return {
            'v': 1, 'date': date, 'captured_at': date + 'T14:00:00+00:00',
            'global': {'level': glvl, 'label': 'L%d' % glvl},
            'axes': {'kinetic': {'level': kinetic, 'signal_count': 20},
                     'economic': {'level': 5, 'signal_count': 24}},
            'regions': {'africa': {'level': africa_lvl, 'posture': 'ELEVATED',
                                   'available': True, 'trackers_live': 1},
                        'me': {'level': 0, 'posture': 'Unavailable',
                               'available': False, 'trackers_live': 0}},
            'signals': [{'id': s[0], 'level': s[1], 'category': s[0].split('|')[-1],
                         'theatre': s[0].split('|')[1], 'label': s[0]} for s in sigs],
            'narratives': [{'category': c, 'priority': 14, 'headline': c} for c in narrs],
            'counts': {'signals': len(sigs), 'narratives': len(narrs)},
            'completeness': {'regions_live': 4, 'regions_expected': 5},
        }

    # 8 days, newest first
    hist = [
        snap('2026-07-23', 5, 6, 4, [('africa|somalia|red_line_breached', 6),
                                     ('europe|russia|red_line', 5),
                                     ('asia|taiwan|theatre_high', 4)]),
        snap('2026-07-22', 5, 6, 4, [('europe|russia|red_line', 5),
                                     ('asia|taiwan|theatre_high', 4)]),
        snap('2026-07-21', 5, 6, 3, [('europe|russia|red_line', 5),
                                     ('asia|taiwan|theatre_high', 3)]),
        snap('2026-07-20', 4, 5, 3, [('europe|russia|red_line', 4),
                                     ('wha|cuba|cascade', 4)]),
        snap('2026-07-19', 4, 5, 3, [('europe|russia|red_line', 4),
                                     ('wha|cuba|cascade', 4)]),
        snap('2026-07-18', 4, 5, 2, [('europe|russia|red_line', 4)]),
        snap('2026-07-17', 4, 4, 2, [('europe|russia|red_line', 4)]),
        snap('2026-07-16', 4, 4, 2, [('europe|russia|red_line', 4)], narrs=()),
    ]

    print('=' * 66)
    print('TEST 1 -- 1-day delta')
    print('=' * 66)
    d = compare(hist[0], hist[1])
    print('  global: L%s -> L%s (%s)' % (d['global']['from'], d['global']['to'], d['global']['direction']))
    print('  APPEARED:', [s['id'] for s in d['signals']['appeared']])
    print('  escalated:', [(s['id'], s['from'], s['to']) for s in d['signals']['escalated']])
    assert [s['id'] for s in d['signals']['appeared']] == ['africa|somalia|red_line_breached']
    print('  \u2705 Somalia correctly detected as NEW today')

    print()
    print('=' * 66)
    print('TEST 2 -- 7-day delta (level + region + signal churn)')
    print('=' * 66)
    d7 = compare(hist[0], hist[7])
    print('  global: L%s -> L%s (%+d)' % (d7['global']['from'], d7['global']['to'], d7['global']['change']))
    print('  axes changed:', {k: '%s->%s' % (v['from'], v['to']) for k, v in d7['axes'].items()})
    print('  regions changed:', {k: '%s->%s' % (v['from'], v['to']) for k, v in d7['regions'].items()})
    print('  appeared:', len(d7['signals']['appeared']), '| resolved:', len(d7['signals']['resolved']))
    print('  narratives appeared:', [n['category'] for n in d7['narratives']['appeared']])
    assert d7['global']['change'] == 1
    assert d7['axes']['kinetic']['from'] == 4 and d7['axes']['kinetic']['to'] == 6
    assert d7['regions']['africa']['change'] == 2
    print('  \u2705 multi-dimension diff correct')

    print()
    print('=' * 66)
    print('TEST 3 -- streaks (persistence as a finding)')
    print('=' * 66)
    st = compute_streaks(hist)
    print('  global L%s held for %d days' % (st['global']['level'], st['global']['days']))
    print('  kinetic axis >=L5 for %d days' % st['axes']['kinetic']['days'])
    print('  africa >=L4 for %d days' % st['regions']['africa']['days'])
    for s in st['signals'][:3]:
        print('    %-38s L%s  %d day(s)%s' % (s['id'], s['level'], s['days'],
              '  <-- NEW in window' if s['days'] == 1 else ''))
    assert st['global']['days'] == 3
    assert st['axes']['kinetic']['days'] == 6
    assert st['regions']['africa']['days'] == 2
    somalia = [s for s in st['signals'] if 'somalia' in s['id']][0]
    assert somalia['days'] == 1
    print('  \u2705 streaks + first-appearance correct')

    print()
    print('=' * 66)
    print('TEST 4 -- gap honesty (missing days are reported, not smoothed)')
    print('=' * 66)
    gapped = [hist[0], hist[1], hist[5], hist[6]]      # 20/19/18 missing
    h = archive_health(gapped)
    print('  depth=%d span=%d contiguous=%s' % (h['depth'], h['span_days'], h['contiguous']))
    print('  gaps:', h['gaps'])
    assert not h['contiguous'] and h['gaps'][0]['missing_days'] == 3
    print('  \u2705 3 missing days surfaced honestly')

    print()
    print('=' * 66)
    print('TEST 5 -- thin history degrades honestly')
    print('=' * 66)
    prev, actual = _find_comparison(hist[:3], 30)
    print('  asked for 30d, archive spans 3d -> closest is %d days back' % actual)
    assert actual == 2
    print('  \u2705 imprecise window reported rather than faked')

    print()
    print('ALL DELTA TESTS PASSED \u2705')
