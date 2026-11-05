"""
Asifah Analytics -- Prediction Markets reader  (ME backend)
v1.0.0  (Nov 5 2026)

WHAT IT DOES
  Every 2 hours it reads the public odds on a curated list of Polymarket and
  Kalshi markets (prediction_markets_watchlist.py), keeps 9 days of its own
  price history in Redis, and flags four things:

    settled     -- a market on the list settled in the last 72h (often the real news:
                   e.g. "ceasefire holds through Nov 4" settling NO).
    jump        -- odds moved 10+ points in 24h or 15+ points in 7 days,
                   on a market with enough money in it to mean something.
    consensus   -- traders price the pressure outcome at 85%+: it is now the
                   expectation, so there is little left to win by betting on it.
    divergence  -- the odds and Asifah's own reading disagree (markets moving
                   toward pressure while we read quiet, or the reverse).

DOCTRINE (Rachel, Nov 5 2026)
  Markets sit BESIDE the score. Nothing here raises or lowers an Asifah level.
  Every number is labelled as traders' odds. Thin markets are shown but never
  flagged. Divergence is the only bridge into the scoring layer, and it is a
  flag for a human, not an input.

COST
  $0. Both APIs are public read-only, no keys. No Claude calls anywhere in this
  file. About 40 small requests every 2 hours.

ROUTES
  /api/markets                  everything (cached)
  /api/markets/page/<key>       items for one page: gpi, military, commodities,
                                market-watch, region:me, iran, uk, ...
  /api/markets/debug            per-item health: which markets failed, which
                                rolled, which need a new slug
  /api/markets/discover         busy geopolitical markets NOT on the watchlist
                                (suggestions for Rachel to approve)
  ?refresh=true                 rebuild now (honoured at most once per 10 min)

REDIS
  pm:latest     the payload other backends and the GPI voice read
  pm:history    9 days of our own price snapshots, per market
  pm:settled    settled markets, remembered for 7 days
  pm:discover   discovery cache (6h)
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta

import requests

try:
    from prediction_markets_watchlist import WATCHLIST
except Exception as _e:  # never take the backend down over a bad edit
    print('[Markets] watchlist failed to load: %s' % _e)
    WATCHLIST = []

__version__ = '1.0.1'   # Nov 5 2026: change_source only when there is a change; threshold items with a unit lead with the middle estimate; settled dates for the page

POLY_API = 'https://gamma-api.polymarket.com'
KALSHI_API = 'https://api.elections.kalshi.com/trade-api/v2'
UA = {'User-Agent': 'AsifahAnalytics/1.0 (+https://www.asifahanalytics.com)'}

LATEST_KEY = 'pm:latest'
HISTORY_KEY = 'pm:history'
SETTLED_KEY = 'pm:settled'
DISCOVER_KEY = 'pm:discover'
LATEST_TTL = 24 * 3600
HISTORY_DAYS = 9              # enough for the 7-day change; keeps the Redis value well under 1 MB
SETTLED_KEEP_DAYS = 7
SETTLED_FLAG_HOURS = 72

REFRESH_EVERY_SEC = 2 * 3600
MANUAL_REFRESH_MIN_GAP = 600
KALSHI_SPACING_SEC = 1.2      # Kalshi answers 429 if hit too fast
POLY_SPACING_SEC = 0.25

# Flag thresholds (probabilities 0..1)
JUMP_24H = 0.10
JUMP_7D = 0.15
CONSENSUS = 0.85
DIVERGENCE_MOVE_7D = 0.15
# A market is "thin" (shown, never flagged) below these
THIN_POLY_LIQUIDITY = 15000.0
THIN_KALSHI_OPEN_INTEREST = 10000.0
LADDER_MIN_DAYS_LEFT = 14     # v1.0.0: a deadline days away mostly moves on the calendar, not the news

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

_MEM = {}                     # fallback store when Redis is not configured (tests)
_build_lock = threading.Lock()
_state = {'last_manual': 0.0, 'thread': False}


# ════════════════════════════════════════════════════════════════════════
# REDIS (Upstash REST) -- same pattern as gpi_voice.py
# ════════════════════════════════════════════════════════════════════════
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
        return True
    try:
        r = requests.post('%s/set/%s' % (UPSTASH_REDIS_URL, key),
                          headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN,
                                   'Content-Type': 'application/json'},
                          data=json.dumps(value, default=str), params={'EX': int(ttl)}, timeout=8)
        return r.status_code == 200
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════════
# SMALL HELPERS
# ════════════════════════════════════════════════════════════════════════
def _now():
    return datetime.now(timezone.utc)


def _parse_dt(s):
    if not s:
        return None
    s = str(s).strip().replace(' ', 'T')
    if s.endswith('+00'):
        s += ':00'
    s = s.replace('Z', '+00:00')
    s = re.sub(r'(\+00:00)+:00:00$', '+00:00', s)
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _f(x, default=None):
    try:
        if x is None or x == '':
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _pct(p):
    if p is None:
        return None
    v = p * 100
    if 0 < v < 1:
        return '<1%'
    if 99 < v < 100:
        return '>99%'
    return '%d%%' % round(v)


def _pts(d):
    if d is None:
        return None
    return '%+d pts' % round(d * 100)


def _short_date(dt):
    if not dt:
        return ''
    return '%s %d' % (dt.strftime('%b'), dt.day) + ('' if dt.year == _now().year else ', %d' % dt.year)


def _get_json(url, params=None, tries=3):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=20)
            if r.status_code == 429:
                time.sleep(2.5 * (i + 1))
                last = 'HTTP 429 (rate limited)'
                continue
            if r.status_code != 200:
                last = 'HTTP %s' % r.status_code
                time.sleep(1)
                continue
            return r.json(), None
        except Exception as e:
            last = str(e)[:120]
            time.sleep(1)
    return None, last


# ════════════════════════════════════════════════════════════════════════
# NORMALISERS: both exchanges -> one market shape
# ════════════════════════════════════════════════════════════════════════
def _mid(bid, ask, last):
    if bid is not None and ask is not None and 0 <= ask - bid <= 0.10 and ask > 0:
        return round((bid + ask) / 2, 4)
    if last is not None:
        return last
    return None


def _norm_poly(m, event):
    prices = m.get('outcomePrices')
    try:
        prices = json.loads(prices) if isinstance(prices, str) else prices
    except Exception:
        prices = None
    p_list = _f(prices[0]) if prices else None
    bid, ask, last = _f(m.get('bestBid')), _f(m.get('bestAsk')), _f(m.get('lastTradePrice'))
    closed = bool(m.get('closed'))
    resolved = (m.get('umaResolutionStatus') == 'resolved') or (closed and prices and p_list in (0.0, 1.0))
    prob = p_list if resolved else (_mid(bid, ask, last) if bid is not None or last is not None else p_list)
    return {
        'mid': 'poly:%s' % m.get('id'),
        'question': m.get('question') or event.get('title'),
        'option': (m.get('groupItemTitle') or '').strip(),
        'prob': prob,
        'chg_24h_api': _f(m.get('oneDayPriceChange')),
        'chg_7d_api': _f(m.get('oneWeekPriceChange')),
        'end': _parse_dt(m.get('endDate')),
        'open': (not closed) and bool(m.get('active', True)) and m.get('acceptingOrders') is not False,
        'resolved': bool(resolved),
        'resolved_yes': (p_list == 1.0) if resolved else None,
        'resolved_at': _parse_dt(m.get('closedTime')) or _parse_dt(m.get('umaEndDate')),
        'disputed': m.get('umaResolutionStatus') == 'disputed',
        'depth': _f(m.get('liquidityNum'), _f(m.get('liquidity'), 0.0)),
        'depth_kind': 'liquidity',
        'volume_24h': _f(m.get('volume24hr'), 0.0),
        'placeholder': prices is None,
    }


def _norm_kalshi(m, event):
    bid, ask = _f(m.get('yes_bid_dollars')), _f(m.get('yes_ask_dollars'))
    last, prev = _f(m.get('last_price_dollars')), _f(m.get('previous_price_dollars'))
    status = (m.get('status') or '').lower()
    result = (m.get('result') or '').lower()
    resolved = result in ('yes', 'no')
    prob = (1.0 if result == 'yes' else 0.0) if resolved else _mid(bid, ask, last)
    # an empty book (bid 0 / ask 1) carries no information
    if not resolved and bid == 0 and ask == 1:
        prob = last
    return {
        'mid': 'kalshi:%s' % m.get('ticker'),
        'question': m.get('title') or event.get('title'),
        'option': (m.get('yes_sub_title') or m.get('subtitle') or '').strip(),
        'prob': prob,
        'chg_24h_api': (prob - prev) if (prob is not None and prev is not None and not resolved) else None,
        'chg_7d_api': None,
        'end': _parse_dt(m.get('close_time')),
        'open': status in ('active', 'open') and not resolved,
        'resolved': resolved,
        'resolved_yes': (result == 'yes') if resolved else None,
        'resolved_at': _parse_dt(m.get('settlement_ts')) or _parse_dt(m.get('updated_time')),
        'disputed': False,
        'depth': _f(m.get('open_interest_fp'), 0.0),
        'depth_kind': 'open_interest',
        'volume_24h': _f(m.get('volume_24h_fp'), 0.0),
        'placeholder': False,
    }


def _thin(mk, source):
    if source == 'polymarket':
        return (mk.get('depth') or 0) < THIN_POLY_LIQUIDITY
    return (mk.get('depth') or 0) < THIN_KALSHI_OPEN_INTEREST


# ════════════════════════════════════════════════════════════════════════
# FETCHERS
# ════════════════════════════════════════════════════════════════════════
def _fetch_poly(item):
    data, err = _get_json('%s/events' % POLY_API, {'slug': item['ref']})
    if err:
        return None, err
    if not data:
        return None, 'slug not found on Polymarket (event removed or renamed)'
    ev = data[0]
    mk = [_norm_poly(m, ev) for m in (ev.get('markets') or [])]
    mk = [m for m in mk if not m['placeholder']]
    return {'title': ev.get('title'), 'url': 'https://polymarket.com/event/%s' % item['ref'],
            'markets': mk, 'event_end': _parse_dt(ev.get('endDate')),
            'event_closed': bool(ev.get('closed'))}, None


def _fetch_kalshi(item):
    data, err = _get_json('%s/events' % KALSHI_API,
                          {'series_ticker': item['ref'], 'status': 'open',
                           'with_nested_markets': 'true'})
    if err:
        return None, err
    events = (data or {}).get('events') or []
    if not events:
        return None, 'no open events in this Kalshi series (series ended or renamed)'
    now = _now()
    min_days = item.get('event_min_days') or 0

    def ev_close(e):
        ends = [_parse_dt(m.get('close_time')) for m in (e.get('markets') or [])]
        ends = [x for x in ends if x]
        return max(ends) if ends else None

    cands = []
    for e in events:
        c = ev_close(e)
        if c and (c - now).days >= min_days:
            cands.append((c, e))
    if not cands:
        return None, 'no open event at least %d days out' % min_days
    # the event with the most money in it (Dec 31 oil, not a thin Nov 30 side-bet)
    def oi(e):
        return sum(_f(m.get('open_interest_fp'), 0.0) for m in (e.get('markets') or []))
    cands.sort(key=lambda t: -oi(t[1]))
    ev = cands[0][1]
    mk = [_norm_kalshi(m, ev) for m in (ev.get('markets') or [])]
    return {'title': ev.get('title'),
            'url': 'https://kalshi.com/markets/%s' % item['ref'].lower(),
            'markets': mk, 'event_end': cands[0][0], 'event_closed': False,
            'event_ticker': ev.get('event_ticker')}, None


# ════════════════════════════════════════════════════════════════════════
# HISTORY: our own snapshots, so "moved 15 points this week" is ours to say
# ════════════════════════════════════════════════════════════════════════
def _hist_change(series, now_ts, prob, hours, tol_hours):
    if prob is None or not series:
        return None
    target = now_ts - hours * 3600
    best = None
    for ts, p in series:
        if abs(ts - target) <= tol_hours * 3600:
            if best is None or abs(ts - target) < abs(best[0] - target):
                best = (ts, p)
    if not best or best[1] is None:
        return None
    return round(prob - best[1], 4)


def _change(mk, hist, now_ts):
    series = hist.get(mk['mid']) or []
    c24 = _hist_change(series, now_ts, mk['prob'], 24, 6)
    c7 = _hist_change(series, now_ts, mk['prob'], 24 * 7, 18)
    src = 'asifah_history' if (c24 is not None or c7 is not None) else None
    if c24 is None and mk.get('chg_24h_api') is not None:
        c24, src = round(mk['chg_24h_api'], 4), 'exchange'
    if c7 is None and mk.get('chg_7d_api') is not None:
        c7 = round(mk['chg_7d_api'], 4)
        src = src or 'exchange'
    return c24, c7, src


# ════════════════════════════════════════════════════════════════════════
# SELECTORS: which market inside the event is the one to show
# ════════════════════════════════════════════════════════════════════════
_NUM_RX = re.compile(r'-?\$?([\d,]+(?:\.\d+)?)')


def _strike(mk):
    m = _NUM_RX.search(mk.get('option') or '')
    return _f(m.group(1).replace(',', '')) if m else None


def _select(item, ev, now):
    mks = ev['markets']
    if item.get('pick'):
        words = item['pick'].lower()
        mks = [m for m in mks if words in ('%s %s' % (m['question'], m['option'])).lower()]
    open_mk = [m for m in mks if m['open'] and m['prob'] is not None
               and (m['end'] is None or m['end'] > now)]
    sel = item['selector']
    if sel == 'single':
        pool = open_mk or [m for m in mks if m['resolved']]
        return (pool[:1], [])
    if sel == 'ladder':
        future = sorted([m for m in open_mk
                         if m['end'] and (m['end'] - now).days >= LADDER_MIN_DAYS_LEFT],
                        key=lambda m: m['end'])
        if not future:
            future = sorted(open_mk, key=lambda m: m['end'] or now)
        head = future[:1]
        rest = future[1:]
        detail = []
        if rest:
            detail.append(rest[len(rest) // 2] if len(rest) > 1 else rest[0])
            if rest[-1] not in detail:
                detail.append(rest[-1])
        return (head, detail)
    if sel == 'field':
        ranked = sorted(open_mk, key=lambda m: -(m['prob'] or 0))
        return (ranked[:1], ranked[1:3])
    if sel == 'threshold':
        priced = [m for m in open_mk if _strike(m) is not None]
        if not priced:
            return (open_mk[:1], [])
        # the strike traders are least sure about (closest to 50/50) says the most;
        # a counted quantity ('unit') leads with its middle estimate instead
        solid = [m for m in priced if not _thin(m, item['source'])] or priced
        head = min(solid, key=lambda m: abs((m['prob'] or 0) - 0.5))
        if item.get('unit'):
            md = _threshold_median(item, ev, now) or {}
            mid_mk = [m for m in priced if md.get('strike') is not None and _strike(m) == md['strike']]
            if mid_mk:
                head = mid_mk[0]
        others = sorted([m for m in priced if m is not head], key=lambda m: _strike(m))
        return ([head], others)
    return (open_mk[:1], [])


def _threshold_median(item, ev, now):
    """For 'above N' ladders: the highest strike traders still give 50%+."""
    priced = [m for m in ev['markets'] if m['open'] and m['prob'] is not None
              and _strike(m) is not None and (m['end'] is None or m['end'] > now)]
    if len(priced) < 3:
        return None
    priced.sort(key=lambda m: _strike(m))
    opt = ' '.join(m['option'].lower() for m in priced)
    if 'below' in opt:      # "X or below": P rises with strike
        above = [m for m in priced if m['prob'] >= 0.5]
        return {'kind': 'below', 'strike': _strike(above[0]) if above else None,
                'label': above[0]['option'] if above else None}
    above = [m for m in priced if m['prob'] >= 0.5]
    return {'kind': 'above', 'strike': _strike(above[-1]) if above else None,
            'label': above[-1]['option'] if above else None}


# ════════════════════════════════════════════════════════════════════════
# READING ONE ITEM
# ════════════════════════════════════════════════════════════════════════
def _p_pressure(item, prob):
    if prob is None:
        return None
    ym = item.get('yes_means')
    if ym == 'more_pressure':
        return prob
    if ym == 'less_pressure':
        return round(1 - prob, 4)
    return None


def _toward(item, delta):
    """'toward pressure' / 'away from pressure' for a change in P(yes)."""
    if delta is None or not delta:
        return None
    ym = item.get('yes_means')
    if ym == 'more_pressure':
        return 'toward pressure' if delta > 0 else 'away from pressure'
    if ym == 'less_pressure':
        return 'away from pressure' if delta > 0 else 'toward pressure'
    return None


def _our_level(item, gpi):
    """Asifah's own reading for the item's countries (GPI country rollup)."""
    if not gpi or not item.get('countries'):
        return None
    roll = {r.get('country'): r for r in (gpi.get('country_rollup') or []) if isinstance(r, dict)}
    best = None
    for c in item['countries']:
        r = roll.get(c)
        if r and r.get('max_level') is not None:
            lv = int(r['max_level'])
            if best is None or lv > best['level']:
                best = {'level': lv, 'country': c}
    return best


def _market_view(mk, item, hist, now_ts):
    c24, c7, src = _change(mk, hist, now_ts)
    return {
        'market_id': mk['mid'],
        'question': mk['question'],
        'option': mk['option'],
        'prob': mk['prob'],
        'odds': _pct(mk['prob']),
        'p_pressure': _p_pressure(item, mk['prob']),
        'change_24h': c24, 'change_7d': c7, 'change_source': src,
        'ends': mk['end'].isoformat() if mk['end'] else None,
        'ends_label': _short_date(mk['end']),
        'depth': round(mk['depth'] or 0),
        'depth_kind': mk['depth_kind'],
        'volume_24h': round(mk['volume_24h'] or 0),
        'thin': _thin(mk, item['source']),
    }


def _read_item(item, ev, err, hist, settled_mem, gpi, now):
    now_ts = now.timestamp()
    out = {k: item.get(k) for k in ('id', 'label', 'source', 'ref', 'selector', 'yes_means',
                                    'axis', 'pages', 'countries', 'note', 'unit')}
    out['flags'] = []
    out['settled_recent'] = []
    if err or not ev:
        out.update(status='unavailable', error=err, read='Odds unread: %s.' % (err or 'no data'))
        return out
    out['url'] = ev['url']
    out['event_title'] = ev.get('title')

    # 1. settled markets (inside this event) -- remembered for a week
    for m in ev['markets']:
        if not m['resolved'] or m['resolved_at'] is None:
            continue
        age_h = (now - m['resolved_at']).total_seconds() / 3600
        if age_h > SETTLED_KEEP_DAYS * 24:
            continue
        # A deadline passing with nothing happening ("deal by Oct 31" -> NO on
        # Nov 1) is routine. News is a market settling EARLY (the ceasefire
        # ladder settling NO days before its date) or settling YES.
        # On a "continues through <date>" ladder (status_quo) a YES only means
        # nothing happened, so only an early NO is news there.
        early = bool(m['end'] and m['resolved_at'] < m['end'] - timedelta(hours=12))
        yes_news = m['resolved_yes'] and not item.get('status_quo')
        if not (early or yes_news):
            continue
        key = '%s|%s' % (item['id'], m['mid'])
        if key not in settled_mem:
            settled_mem[key] = {'item': item['id'], 'market_id': m['mid'],
                                'question': m['question'], 'option': m['option'],
                                'resolved_yes': m['resolved_yes'], 'early': early,
                                'deadline': m['end'].isoformat() if m['end'] else None,
                                'resolved_at': m['resolved_at'].isoformat()}
    mine = sorted([s for s in settled_mem.values() if s['item'] == item['id']],
                  key=lambda s: (s.get('deadline') or s['resolved_at']))
    # A ladder settling NO on 12 deadlines at once is ONE event: keep the earliest
    # deadline that settled each way.
    seen_way = set()
    for s in mine:
        if s['resolved_yes'] in seen_way:
            continue
        seen_way.add(s['resolved_yes'])
        rdt = _parse_dt(s['resolved_at'])
        s2 = dict(s, hours_ago=round((now - rdt).total_seconds() / 3600, 1),
                  settled_label=('YES' if s['resolved_yes'] else 'NO'),
                  settled_on=_short_date(rdt))
        out['settled_recent'].append(s2)

    head, detail = _select(item, ev, now)
    if item['selector'] == 'threshold':
        out['median'] = _threshold_median(item, ev, now)
    if not head:
        if out['settled_recent']:
            out['status'] = 'settled'
        else:
            out['status'] = 'no_open_market'
            out['read'] = 'No open market left in this event; the watchlist entry needs a new slug.'
            return out
    else:
        out['status'] = 'ok'
        out['headline'] = _market_view(head[0], item, hist, now_ts)
        out['detail'] = [_market_view(m, item, hist, now_ts) for m in detail]
        if item['selector'] == 'threshold':
            # one question spread over many strikes: judge the money on the whole ladder
            total = sum((m['depth'] or 0) for m in ev['markets'] if m['open'])
            floor = THIN_POLY_LIQUIDITY if item['source'] == 'polymarket' else THIN_KALSHI_OPEN_INTEREST
            for v in [out['headline']] + out['detail']:
                v['thin'] = total < floor
            out['ladder_depth'] = round(total)
        if out['headline']['thin']:
            out['status'] = 'thin'

    # threshold items: the biggest mover across ALL strikes is the signal
    if item['selector'] == 'threshold' and out.get('headline'):
        views = [out['headline']] + out['detail']
        movers = [v for v in views if v['change_24h'] is not None and not v['thin']]
        if movers:
            big = max(movers, key=lambda v: abs(v['change_24h']))
            if abs(big['change_24h']) >= JUMP_24H:
                out['biggest_mover'] = big

    out['our_level'] = _our_level(item, gpi)
    _flag(out, item)
    out['read'] = _sentence(out, item)
    return out


# ════════════════════════════════════════════════════════════════════════
# FLAGS + PLAIN SENTENCES
# ════════════════════════════════════════════════════════════════════════
def _flag(out, item):
    f = out['flags']
    for s in out['settled_recent']:
        if s['hours_ago'] <= SETTLED_FLAG_HOURS:
            f.append({'kind': 'settled',
                      'text': '"%s" settled %s %.0fh ago' % (s['question'] or s['option'],
                                                              s['settled_label'], s['hours_ago'])})
            break
    h = out.get('headline')
    if not h:
        return
    target = out.get('biggest_mover') or h
    if not target['thin']:
        c24, c7 = target['change_24h'], target['change_7d']
        if (c24 is not None and abs(c24) >= JUMP_24H) or (c7 is not None and abs(c7) >= JUMP_7D):
            day = c24 is not None and abs(c24) >= JUMP_24H
            use = c24 if day else c7
            win = '24h' if day else '7 days'
            f.append({'kind': 'jump', 'direction': _toward(item, use),
                      'text': '%s %s in %s' % (target['option'] or 'odds', _pts(use), win)})
    # Consensus is an early warning only when the EXPECTED outcome is the
    # pressure event itself ("no deal by Nov 30" at 97% is just the status quo).
    pressure_is_event = item['yes_means'] == 'more_pressure' or item.get('status_quo')
    if (pressure_is_event and not h['thin'] and h['p_pressure'] is not None
            and h['p_pressure'] >= CONSENSUS):
        f.append({'kind': 'consensus',
                  'text': 'traders price the pressure outcome at %s' % _pct(h['p_pressure'])})
    ol = out.get('our_level')
    if ol and not h['thin'] and h['change_7d'] is not None and item['yes_means'] != 'neutral':
        d = h['change_7d']
        moved_up = (_toward(item, d) == 'toward pressure') and abs(d) >= DIVERGENCE_MOVE_7D
        moved_down = (_toward(item, d) == 'away from pressure') and abs(d) >= DIVERGENCE_MOVE_7D
        if moved_up and ol['level'] <= 2:
            f.append({'kind': 'divergence', 'which': 'markets_ahead',
                      'text': 'odds moved %s toward pressure this week while Asifah reads %s at L%d'
                              % (_pts(abs(d)), ol['country'], ol['level'])})
        elif moved_down and ol['level'] >= 4:
            f.append({'kind': 'divergence', 'which': 'markets_calmer',
                      'text': 'odds moved %s away from pressure this week while Asifah reads %s at L%d'
                              % (_pts(abs(d)), ol['country'], ol['level'])})


def _sentence(out, item):
    """One plain sentence for the page. Always attributes the number to traders."""
    h = out.get('headline')
    parts = []
    if out.get('status') == 'settled' and out['settled_recent']:
        s = out['settled_recent'][0]
        parts.append('Traders\' market settled %s on "%s".'
                     % (s['settled_label'], s['question'] or s['option']))
    if h:
        if item['selector'] == 'field':
            lead = 'Traders favour %s at %s' % (h['option'] or h['question'], h['odds'])
        elif item['selector'] == 'threshold':
            md = out.get('median') or {}
            unit = (' ' + item['unit']) if item.get('unit') else ''
            if md.get('label') and item.get('unit'):
                lead = 'Traders\' middle estimate: %s%s' % (md['label'].lower(), unit)
            else:
                lead = 'Traders price "%s%s" at %s' % (h['option'], unit, h['odds'])
        elif item['selector'] == 'ladder' and h['option']:
            opt = h['option']
            if item.get('status_quo'):
                lead = 'Traders\' odds it holds through %s: %s' % (opt, h['odds'])
            elif opt.lower().startswith(('before', 'by ')):
                lead = 'Traders\' odds of yes %s: %s' % (opt[0].lower() + opt[1:], h['odds'])
            else:
                lead = 'Traders\' odds of yes by %s: %s' % (opt, h['odds'])
        else:
            lead = 'Traders price yes at %s' % h['odds']
        ch = []
        if h['change_24h'] is not None and abs(h['change_24h']) >= 0.02:
            ch.append('%s in 24h' % _pts(h['change_24h']))
        if h['change_7d'] is not None and abs(h['change_7d']) >= 0.03:
            ch.append('%s in 7 days' % _pts(h['change_7d']))
        parts.append(lead + (' (%s).' % ', '.join(ch) if ch else '.'))
        if out.get('biggest_mover') and out['biggest_mover'] is not h:
            b = out['biggest_mover']
            parts.append('Biggest move: "%s" %s in 24h (now %s).' % (b['option'], _pts(b['change_24h']), b['odds']))
        if h['thin']:
            parts.append('Thin market: little money behind these odds.')
    return ' '.join(parts) if parts else 'No readable odds.'


# ════════════════════════════════════════════════════════════════════════
# BUILD
# ════════════════════════════════════════════════════════════════════════
def build(reason='scheduled'):
    if not _build_lock.acquire(blocking=False):
        return {'status': 'already_running'}
    t0 = time.time()
    try:
        now = _now()
        now_ts = now.timestamp()
        hist = _rget(HISTORY_KEY) or {}
        settled_mem = _rget(SETTLED_KEY) or {}
        gpi = _rget('gpi:global:latest')
        items, errors = [], {'polymarket': 0, 'kalshi': 0}
        counts = {'polymarket': 0, 'kalshi': 0}
        for item in WATCHLIST:
            try:
                if item['source'] == 'kalshi':
                    ev, err = _fetch_kalshi(item)
                    time.sleep(KALSHI_SPACING_SEC)
                else:
                    ev, err = _fetch_poly(item)
                    time.sleep(POLY_SPACING_SEC)
            except Exception as e:
                ev, err = None, 'fetch crashed: %s' % str(e)[:100]
            counts[item['source']] += 1
            if err:
                errors[item['source']] += 1
            try:
                rec = _read_item(item, ev, err, hist, settled_mem, gpi, now)
            except Exception as e:
                rec = {'id': item.get('id'), 'label': item.get('label'), 'status': 'unavailable',
                       'error': 'read crashed: %s' % str(e)[:120], 'flags': [], 'pages': item.get('pages')}
            items.append(rec)
            # record history for every market we displayed
            for v in ([rec.get('headline')] + list(rec.get('detail') or [])):
                if v and v.get('prob') is not None:
                    hist.setdefault(v['market_id'], []).append([round(now_ts), round(v['prob'], 3)])

        # prune history and settled memory
        cutoff = now_ts - HISTORY_DAYS * 86400
        hist = {k: [p for p in v if p[0] >= cutoff][-110:] for k, v in hist.items()}
        hist = {k: v for k, v in hist.items() if v}
        s_cut = now - timedelta(days=SETTLED_KEEP_DAYS)
        settled_mem = {k: v for k, v in settled_mem.items()
                       if (_parse_dt(v.get('resolved_at')) or now) >= s_cut}

        flagged = [i for i in items if i.get('flags')]
        payload = {
            'version': __version__,
            'generated_at': now.isoformat(),
            'reason': reason,
            'label': "Traders' odds on public prediction markets (Polymarket, Kalshi). "
                     "Context only: these never change an Asifah level.",
            'items': items,
            'flagged': [{'id': i['id'], 'label': i.get('label'), 'flags': i['flags'],
                         'read': i.get('read')} for i in flagged],
            'health': {
                'watchlist_size': len(WATCHLIST),
                'fetched': counts, 'fetch_errors': errors,
                'ok': sum(1 for i in items if i.get('status') in ('ok', 'thin', 'settled')),
                'thin': sum(1 for i in items if i.get('status') == 'thin'),
                'needs_attention': [{'id': i.get('id'), 'status': i.get('status'),
                                     'why': i.get('error') or i.get('read')}
                                    for i in items if i.get('status') in ('unavailable', 'no_open_market')],
                'gpi_levels_read': bool(gpi),
                'seconds': round(time.time() - t0, 1),
            },
        }
        _rset(HISTORY_KEY, hist, (HISTORY_DAYS + 2) * 86400)
        _rset(SETTLED_KEY, settled_mem, (SETTLED_KEEP_DAYS + 2) * 86400)
        _rset(LATEST_KEY, payload, LATEST_TTL)
        print('[Markets] built %d items in %.0fs (%d flagged, %d need attention)'
              % (len(items), payload['health']['seconds'], len(flagged),
                 len(payload['health']['needs_attention'])))
        return payload
    finally:
        _build_lock.release()


def latest():
    return _rget(LATEST_KEY)


def _age_sec(p):
    d = _parse_dt((p or {}).get('generated_at'))
    return (_now() - d).total_seconds() if d else None


# ════════════════════════════════════════════════════════════════════════
# FOR THE GPI VOICE (read by gpi_voice.py; never calls anything external)
# ════════════════════════════════════════════════════════════════════════
def voice_context(max_items=8):
    """Compact, labelled market context for the plain-language writer.

    Returns {'fingerprint_flags': [...], 'items': [...]} or None.
    fingerprint_flags only holds slow-moving facts (settled, consensus,
    divergence) so a twitchy price cannot force a rewrite on its own.
    """
    p = latest()
    age = _age_sec(p)
    if not p or age is None or age > 12 * 3600:
        return None
    rows, fp = [], []
    for it in p.get('items') or []:
        if not it.get('flags') or 'gpi' not in (it.get('pages') or []) and not any(
                f['kind'] in ('settled', 'divergence') for f in it['flags']):
            continue
        h = it.get('headline') or {}
        rows.append({
            'question': it.get('label'),
            'traders_odds_now': h.get('odds'),
            'what_yes_means': {'more_pressure': 'more pressure', 'less_pressure': 'less pressure'}
                              .get(it.get('yes_means'), 'neither'),
            'change_24h_points': round(h['change_24h'] * 100) if h.get('change_24h') is not None else None,
            'change_7d_points': round(h['change_7d'] * 100) if h.get('change_7d') is not None else None,
            'flags': [f['text'] for f in it['flags']],
            'settled': [('"%s" settled %s' % (s['question'] or s['option'], s['settled_label']))
                        for s in (it.get('settled_recent') or [])[:2]],
            'contract_note': it.get('note'),
            'asifah_level_for_country': (it.get('our_level') or {}).get('level'),
        })
        for f in it['flags']:
            if f['kind'] in ('settled', 'consensus', 'divergence'):
                fp.append('%s:%s' % (it['id'], f['kind']))
        if len(rows) >= max_items:
            break
    if not rows:
        return None
    return {'fingerprint_flags': sorted(set(fp)), 'items': rows,
            'as_of_utc': p.get('generated_at')}


# ════════════════════════════════════════════════════════════════════════
# DISCOVERY: suggestions only -- nothing is added without Rachel
# ════════════════════════════════════════════════════════════════════════
DISCOVER_TAGS = ('geopolitics', 'middle-east', 'ukraine', 'china', 'world-elections',
                 'economy', 'commodities')


def discover():
    cached = _rget(DISCOVER_KEY)
    if cached and (_age_sec(cached) or 1e9) < 6 * 3600:
        return cached
    have = {w['ref'] for w in WATCHLIST}
    seen, out = set(), []
    for tag in DISCOVER_TAGS:
        data, err = _get_json('%s/events' % POLY_API,
                              {'active': 'true', 'closed': 'false', 'order': 'volume24hr',
                               'ascending': 'false', 'limit': 40, 'tag_slug': tag})
        time.sleep(POLY_SPACING_SEC)
        for e in data or []:
            s = e.get('slug')
            if not s or s in have or s in seen:
                continue
            seen.add(s)
            liq = _f(e.get('liquidity'), 0.0)
            if liq < THIN_POLY_LIQUIDITY:
                continue
            out.append({'source': 'polymarket', 'ref': s, 'title': e.get('title'),
                        'tag': tag, 'volume_24h': round(_f(e.get('volume24hr'), 0.0)),
                        'liquidity': round(liq), 'markets': len(e.get('markets') or []),
                        'ends': (e.get('endDate') or '')[:10],
                        'url': 'https://polymarket.com/event/%s' % s})
    out.sort(key=lambda r: -r['volume_24h'])
    payload = {'generated_at': _now().isoformat(), 'not_on_watchlist': out[:60],
               'note': 'Suggestions only. Add an entry to prediction_markets_watchlist.py to track one.'}
    _rset(DISCOVER_KEY, payload, 7 * 3600)
    return payload


# ════════════════════════════════════════════════════════════════════════
# SCHEDULER + ROUTES
# ════════════════════════════════════════════════════════════════════════
def _loop():
    time.sleep(120)
    try:
        from instance_lock import my_turn
    except Exception:
        my_turn = lambda job: True     # noqa: E731  (no lock module: run, fail-open)
    while True:
        try:
            if not my_turn('prediction_markets'):
                continue
            age = _age_sec(latest())
            if age is None or age >= REFRESH_EVERY_SEC - 120:
                build('scheduled')
        except Exception as e:
            print('[Markets] scheduled build failed (non-fatal): %s' % str(e)[:200])
        time.sleep(30 * 60)


def start_scheduler():
    if _state['thread']:
        return
    _state['thread'] = True
    threading.Thread(target=_loop, daemon=True, name='prediction-markets').start()


def _page_items(p, key):
    key = (key or '').lower()
    return [i for i in (p.get('items') or []) if key in [x.lower() for x in (i.get('pages') or [])]]


def register_prediction_markets_routes(app, start=True):
    from flask import jsonify, request

    def _maybe_refresh():
        if request.args.get('refresh', 'false').lower() != 'true':
            return None
        if time.time() - _state['last_manual'] < MANUAL_REFRESH_MIN_GAP:
            return 'refresh ignored: last manual refresh was under 10 minutes ago'
        _state['last_manual'] = time.time()
        build('manual')
        return 'refreshed'

    @app.route('/api/markets')
    def _pm_all():
        note = _maybe_refresh()
        p = latest()
        if not p:
            return jsonify({'available': False,
                            'note': 'First read not built yet (runs ~2 minutes after deploy).'}), 200
        out = dict(p)
        out['available'] = True
        out['age_minutes'] = round((_age_sec(p) or 0) / 60)
        if note:
            out['refresh'] = note
        return jsonify(out)

    @app.route('/api/markets/page/<key>')
    def _pm_page(key):
        p = latest()
        if not p:
            return jsonify({'available': False, 'items': []}), 200
        items = _page_items(p, key)
        return jsonify({'available': True, 'page': key, 'generated_at': p.get('generated_at'),
                        'age_minutes': round((_age_sec(p) or 0) / 60),
                        'label': p.get('label'), 'items': items,
                        'flagged': [i['id'] for i in items if i.get('flags')]})

    @app.route('/api/markets/debug')
    def _pm_debug():
        note = _maybe_refresh()
        p = latest() or {}
        rows = [{'id': i.get('id'), 'status': i.get('status'), 'source': i.get('source'),
                 'ref': i.get('ref'), 'error': i.get('error'),
                 'headline': (i.get('headline') or {}).get('option') or (i.get('headline') or {}).get('question'),
                 'odds': (i.get('headline') or {}).get('odds'),
                 'depth': (i.get('headline') or {}).get('depth'),
                 'change_source': (i.get('headline') or {}).get('change_source'),
                 'flags': [f['kind'] for f in i.get('flags') or []],
                 'read': i.get('read')} for i in p.get('items') or []]
        hist = _rget(HISTORY_KEY) or {}
        return jsonify({'version': __version__, 'generated_at': p.get('generated_at'),
                        'age_minutes': round((_age_sec(p) or 0) / 60) if p else None,
                        'health': p.get('health'), 'history_markets': len(hist),
                        'history_points': sum(len(v) for v in hist.values()),
                        'refresh': note, 'items': rows})

    @app.route('/api/markets/discover')
    def _pm_discover():
        return jsonify(discover())

    if start:
        start_scheduler()
    print('[Markets] routes registered: /api/markets, /page/<key>, /debug, /discover (v%s, %d watched)'
          % (__version__, len(WATCHLIST)))
