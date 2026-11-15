"""
Asifah Analytics -- CHOKEPOINT TRANSITS  v1.0.0  (Nov 15 2026)

Ship counts through the watched chokepoints, against their pre-war normal.

WHY THIS EXISTS
  The military tracker reads a chokepoint from how much is being REPORTED
  about it. That fails exactly when it matters most: a strait that has been
  nearly shut for months becomes routine news, the reporting thins, and the
  tile drifts down to "Contested" while almost no ships are moving. Rachel,
  Nov 15 2026: Hormuz read Contested while traders gave <1% odds of traffic
  returning to normal. Reporting measures attention; this measures ships.

SOURCE
  IMF PortWatch, Daily_Chokepoints_Data (free, public, no key). Daily counts of
  ships crossing each chokepoint, built from satellite AIS by the IMF and
  Oxford. Two honest limits, both carried into every sentence this module
  writes:
    * it runs about a week behind (the latest day is usually 5-8 days old);
    * it counts ships whose transponders are on -- vessels running dark are
      missed, so in a war zone the count is a floor, not the total.

WHAT IT PRODUCES (Redis chokepoint:transits:v1, refreshed at most every 12h)
  Per chokepoint: the last-7-day average, the pre-war average (calendar 2025,
  before the Iran-US war that began in February 2026), the ratio, a band,
  a FLOOR for the military tracker's level, how long the condition has held
  (standing_since), and whether the latest week is a STEP CHANGE (a fresh
  drop, or a reopening). Bab el-Mandeb and Suez also carry a second baseline
  from before the Red Sea attacks (Jan-Oct 2023).

  Floors (7-day average as a share of pre-war):
     75%+          normal           no floor
     50-75%        reduced          monitored
     25-50%        heavily reduced  contested
     under 25%     near-halted      disrupted

DOCTRINE
  * A standing condition is not news. The floor keeps the tile honest
    (Disrupted), and standing=True tells every reader it is long-running.
  * A step change IS news: a fresh halving of traffic, or traffic doubling
    back toward normal (a reopening is flagged as news too).
  * Unread, not calm: if PortWatch cannot be read, no floor is applied and
    the tile falls back to reporting alone. Never a guessed number.

COST
  Free API. About ten small requests every 12 hours, plus one Redis SET.
  The pre-war baselines are computed once and kept for 30 days.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta, date

import requests

__version__ = '1.0.0'

PORTWATCH_URL = ('https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/'
                 'Daily_Chokepoints_Data/FeatureServer/0/query')

# Asifah chokepoint id -> PortWatch portid. Only clean one-to-one matches.
# (Black Sea, Baltic, South China Sea, Caribbean and Arctic are seas, not a
# single counted passage, so they stay on reporting alone.)
PORTWATCH_IDS = {
    'hormuz':        ('chokepoint6',  'Strait of Hormuz'),
    'bab_el_mandeb': ('chokepoint4',  'Bab el-Mandeb'),
    'suez':          ('chokepoint1',  'the Suez Canal'),
    'bosporus':      ('chokepoint3',  'the Bosporus'),
    'taiwan_strait': ('chokepoint11', 'the Taiwan Strait'),
    'luzon_strait':  ('chokepoint14', 'the Luzon Strait'),
    'malacca':       ('chokepoint5',  'the Strait of Malacca'),
    'panama_canal':  ('chokepoint2',  'the Panama Canal'),
    'gibraltar':     ('chokepoint8',  'the Strait of Gibraltar'),
    'magellan':      ('chokepoint21', 'the Strait of Magellan'),
}

BASELINE_LABEL = 'the 2025 average, before the war'
BASELINE_RANGE = ('2025-01-01', '2025-12-31')
# Red Sea passages were already cut by the Houthi attacks from late 2023, so
# 2025 is itself a damaged year there. A second, older baseline says so.
LONG_BASELINE = {
    'bab_el_mandeb': ('2023-01-01', '2023-10-31', 'before the Red Sea attacks (Jan-Oct 2023)'),
    'suez':          ('2023-01-01', '2023-10-31', 'before the Red Sea attacks (Jan-Oct 2023)'),
}
HISTORY_DAYS = 300            # enough to date a condition that began in early 2026

BANDS = [  # (min ratio, band, floor level, words)
    (0.75, 'normal',          None,        'normal'),
    (0.50, 'reduced',         'monitored', 'reduced'),
    (0.25, 'heavily_reduced', 'contested', 'heavily reduced'),
    (0.0,  'near_halted',     'disrupted', 'near-halted'),
]

REDIS_KEY = 'chokepoint:transits:v1'
BASELINE_KEY = 'chokepoint:transits:baseline:v1'
REFRESH_SEC = 12 * 3600
REDIS_TTL = 36 * 3600
BASELINE_TTL = 30 * 24 * 3600

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

_mem = {'data': None, 'at': 0.0}
_lock = threading.Lock()


# ── Redis (same REST pattern as the trackers) ─────────────────────────────
def _rget(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(f"{UPSTASH_REDIS_URL}/get/{key}",
                         headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'}, timeout=6)
        body = r.json()
        return json.loads(body['result']) if body.get('result') else None
    except Exception:
        return None


def _rset(key, value, ttl):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(f"{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl)}",
                          headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                          data=json.dumps(value, default=str), timeout=8)
        return r.ok
    except Exception:
        return False


# ── PortWatch ─────────────────────────────────────────────────────────────
def _fetch(portid, start, end=None):
    """Daily rows for one chokepoint, oldest first. Paginates. Raises on failure."""
    where = "portid='%s' AND date >= '%s'" % (portid, start)
    if end:
        where += " AND date <= '%s'" % end
    rows, offset = [], 0
    for _ in range(10):
        r = requests.get(PORTWATCH_URL, params={
            'where': where, 'outFields': 'date,n_total,n_tanker',
            'orderByFields': 'date ASC', 'resultOffset': offset,
            'resultRecordCount': 1000, 'f': 'json'}, timeout=25)
        r.raise_for_status()
        j = r.json()
        if j.get('error'):
            raise RuntimeError(str(j['error'])[:160])
        feats = j.get('features') or []
        for f in feats:
            a = f.get('attributes') or {}
            d = a.get('date')
            if isinstance(d, (int, float)):            # epoch ms on some layers
                d = datetime.fromtimestamp(d / 1000, tz=timezone.utc).date().isoformat()
            if d and a.get('n_total') is not None:
                rows.append((str(d)[:10], int(a['n_total']), int(a.get('n_tanker') or 0)))
        if not j.get('exceededTransferLimit') or not feats:
            break
        offset += len(feats)
    return rows


def _avg(xs):
    return (sum(xs) / len(xs)) if xs else None


def _band(ratio):
    for lo, band, floor, words in BANDS:
        if ratio >= lo:
            return band, floor, words
    return BANDS[-1][1:]


def _baselines(force=False):
    """{cp_id: {'avg': x, 'avg_tanker': y, 'long_avg': z|None}} -- 30-day cache."""
    if not force:
        b = _rget(BASELINE_KEY)
        if isinstance(b, dict) and b.get('chokepoints'):
            return b['chokepoints']
    out = {}
    for cp, (pid, _name) in PORTWATCH_IDS.items():
        try:
            rows = _fetch(pid, *BASELINE_RANGE)
            if len(rows) < 200:                    # too thin to call a baseline
                continue
            rec = {'avg': round(_avg([r[1] for r in rows]), 1),
                   'avg_tanker': round(_avg([r[2] for r in rows]), 1), 'days': len(rows)}
            if cp in LONG_BASELINE:
                s, e, _lbl = LONG_BASELINE[cp]
                lr = _fetch(pid, s, e)
                if len(lr) >= 150:
                    rec['long_avg'] = round(_avg([r[1] for r in lr]), 1)
            out[cp] = rec
        except Exception as ex:
            print('[Chokepoint transits] baseline %s unread: %s' % (cp, str(ex)[:120]))
    if out:
        _rset(BASELINE_KEY, {'chokepoints': out, 'computed_at': datetime.now(timezone.utc).isoformat(),
                             'range': BASELINE_RANGE}, BASELINE_TTL)
    return out


def _nice_date(iso):
    try:
        d = date.fromisoformat(iso)
        return d.strftime('%b %-d')
    except Exception:
        return iso


def _read_one(cp, pid, name, base):
    start = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()
    rows = _fetch(pid, start)
    if len(rows) < 14:
        return None
    totals = [r[1] for r in rows]
    avg7 = _avg(totals[-7:])
    prev = _avg(totals[-35:-7]) if len(totals) >= 35 else None
    b = base.get('avg') or 0
    if not b:
        return None
    ratio = avg7 / b
    band, floor, words = _band(ratio)

    # How long has it held? Walk back the rolling 7-day ratio until it was
    # last in a better band than today's.
    since = None
    if band != 'normal':
        rank = [x[1] for x in BANDS].index(band)
        i = len(totals) - 1
        while i >= 6:
            r7 = _avg(totals[i - 6:i + 1]) / b
            if [x[1] for x in BANDS].index(_band(r7)[0]) < rank:
                break
            since = rows[i - 6][0]
            i -= 1
        if i < 6:
            since = None                            # older than our window: say "for months"
    latest = rows[-1][0]
    lag = (date.today() - date.fromisoformat(latest)).days

    step = None
    if prev:
        if avg7 <= 0.5 * prev and (prev - avg7) / b >= 0.15:
            step = 'drop'
        elif avg7 >= 2 * prev and (avg7 - prev) / b >= 0.15:
            step = 'rise'

    pct = round(ratio * 100)
    plain = ('%s: about %s ships a day crossed in the week to %s, against a 2025 average of '
             'about %s a day before the war -- roughly %s%% of normal (%s).'
             % (name[0].upper() + name[1:], _fmt(avg7), _nice_date(latest), _fmt(b), pct, words))
    if band != 'normal':
        if since:
            days = (date.fromisoformat(latest) - date.fromisoformat(since)).days
            plain += ' It has been at this level since %s (%s days): a standing condition, not new.' % (
                _nice_date(since), days)
        else:
            plain += ' It has been at this level for the whole of our %s-day window: a standing condition, not new.' % HISTORY_DAYS
    if step == 'drop':
        plain += ' NEW: traffic fell by half or more against the previous four weeks.'
    elif step == 'rise':
        plain += ' NEW: traffic doubled against the previous four weeks -- a possible reopening.'
    long_avg = base.get('long_avg')
    if long_avg:
        plain += ' Against %s it is about %s%% (%s a day then).' % (
            LONG_BASELINE[cp][2], round(avg7 / long_avg * 100), _fmt(long_avg))
    plain += (' Source: IMF PortWatch ship counts from satellite AIS, about %s days behind; '
              'ships with transponders off are missed, so this is a floor.' % lag)

    return {
        'chokepoint': cp, 'name': name, 'portwatch_id': pid,
        'latest_date': latest, 'lag_days': lag,
        'avg_7d': round(avg7, 1), 'avg_prev_28d': round(prev, 1) if prev else None,
        'avg_7d_tanker': round(_avg([r[2] for r in rows[-7:]]), 1),
        'baseline_avg': b, 'baseline_label': BASELINE_LABEL,
        'ratio_pct': pct, 'band': band, 'band_words': words, 'floor_level': floor,
        'standing': band != 'normal' and step != 'drop',
        'standing_since': since, 'step_change': step,
        'long_baseline_avg': long_avg,
        'long_baseline_pct': round(avg7 / long_avg * 100) if long_avg else None,
        'long_baseline_label': LONG_BASELINE[cp][2] if cp in LONG_BASELINE else None,
        'last_7': [{'date': r[0], 'ships': r[1]} for r in rows[-7:]],
        'plain': plain,
    }


def _fmt(x):
    return ('%.0f' % x) if x >= 10 else ('%.1f' % x).rstrip('0').rstrip('.')


def refresh(force=False):
    """Read PortWatch and store. Never raises. Returns the stored record."""
    base = _baselines(force=force)
    out = {}
    for cp, (pid, name) in PORTWATCH_IDS.items():
        if cp not in base:
            continue
        try:
            rec = _read_one(cp, pid, name, base[cp])
            if rec:
                out[cp] = rec
        except Exception as ex:
            print('[Chokepoint transits] %s unread: %s' % (cp, str(ex)[:120]))
    data = {'chokepoints': out, 'fetched_at': datetime.now(timezone.utc).isoformat(),
            'version': __version__, 'source': 'IMF PortWatch (Daily_Chokepoints_Data)',
            'baseline': BASELINE_LABEL}
    if out:
        _rset(REDIS_KEY, data, REDIS_TTL)
        _mem.update(data=data, at=time.time())
        print('[Chokepoint transits] v%s: %s' % (__version__, ', '.join(
            '%s %s%%' % (k, v['ratio_pct']) for k, v in out.items())))
    return data


def get_transits(allow_fetch=True):
    """Cached read. Memory first, then Redis; fetches PortWatch only when the
    stored read is older than 12h (and allow_fetch). Never raises; {} if unread."""
    now = time.time()
    if _mem['data'] and now - _mem['at'] < 3600:
        return _mem['data']
    data = _rget(REDIS_KEY)
    age = None
    if isinstance(data, dict) and data.get('fetched_at'):
        try:
            age = now - datetime.fromisoformat(data['fetched_at']).timestamp()
        except Exception:
            age = None
    if isinstance(data, dict) and age is not None and age < REFRESH_SEC:
        _mem.update(data=data, at=now)
        return data
    if allow_fetch and _lock.acquire(blocking=False):
        try:
            fresh = refresh()
            if fresh.get('chokepoints'):
                return fresh
        finally:
            _lock.release()
    return data if isinstance(data, dict) else {}


LEVEL_RANK = {'open': 0, 'monitored': 1, 'contested': 2, 'disrupted': 3}


def apply_floors(postures, thresholds, watched=()):
    """Raise each chokepoint posture to its transit floor (never lower it) and
    attach the transit read. Mutates and returns postures. Never raises.

    thresholds: the military tracker's CHOKEPOINT_THRESHOLDS (labels/icons).
    watched: chokepoints listed even at zero signals."""
    try:
        tr = (get_transits() or {}).get('chokepoints') or {}
    except Exception:
        return postures
    for cp, t in tr.items():
        p = postures.get(cp)
        if p is None:
            if cp not in watched and not t.get('floor_level'):
                continue
            p = postures[cp] = {'chokepoint': cp, 'alert_level': 'open', 'signal_count': 0,
                                'critical_signal_count': 0, 'score': 0.0, 'top_signals': []}
        p['transits'] = t
        fl = t.get('floor_level')
        cur = p.get('alert_level', 'open')
        p['reporting_level'] = cur
        if fl and LEVEL_RANK.get(fl, 0) > LEVEL_RANK.get(cur, 0):
            p['alert_level'] = fl
            p['alert_label'] = thresholds.get(fl, {}).get('label', fl.title())
            p['alert_icon'] = thresholds.get(fl, {}).get('icon', '')
            p['level_basis'] = 'ship_counts'
        else:
            p['level_basis'] = 'reporting'
        p['standing'] = bool(t.get('standing'))
        p['step_change'] = t.get('step_change')
        p['ship_traffic'] = t.get('plain')
    return postures
