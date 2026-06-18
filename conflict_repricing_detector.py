"""
conflict_repricing_detector.py
Asifah Analytics -- Conflict Repricing Detector (market-belief layer)

Reads a theater's de-escalation OFF-RAMP fingerprint (from the rhetoric layer)
together with that theater's market instruments, and reports whether informed
capital is repricing in a way CONSISTENT WITH believing the off-ramp is durable
-- or refusing to. This is an analyst-layer read of MARKET BELIEF, never a
forecast and never investment advice.

Doctrine: convergence, not prediction. The detector reads how the market is
POSITIONED and articulates what that positioning COULD indicate -- an estimative
disjunction ("consistent with one of two readings: ... or ...") -- paired with
the rhetoric layer. The reader completes the inference.

Per-instrument polarity (durable peace direction), so "peace" is never a uniform
"everything drops":
  - broad index / FX  : risk gauges      -> durable peace = UP / stronger
  - defense spread     : demand gauge     -> durable peace = COMPRESSES
  - oil (Brent)        : war-premium      -> durable peace = DOWN
The signal is COHERENCE across instruments, not any single move.

Portable across theaters via THEATER_CONFIG (drift-engine pattern):
  - israel         : LIVE -- reads rhetoric:iran:latest de-escalation fingerprint
  - europe_ukraine : Slice 4 -- needs a Russia-Ukraine off-ramp fingerprint first

SLICES
  1 (this file): Israel end-to-end -- config, fetchers, rhetoric reader,
                 polarity/coherence scorer, estimative prose builder, Redis +
                 GPI bundle, endpoints.
  2          : episode library + Jaccard similarity matching.
  3          : GPI-altitude surfacing narrative (_narrative_conflict_repricing).
  4          : Ukraine off-ramp fingerprint -> wire europe_ukraine config.
"""

import os
import json
import requests
from datetime import datetime, timezone

VERSION = '0.1.0'  # Slice 1
CACHE_TTL_HOURS = 12

DISCLAIMER = ("This is a CONVERGENCE read of market positioning, NOT a forecast "
              "of whether the off-ramp holds and NOT investment advice. It "
              "reports what informed capital appears to be pricing; the reader "
              "completes the inference.")

# Move thresholds (percent) -- a move smaller than this is treated as flat.
DEFAULT_MOVE_THRESHOLD = 1.0
SPREAD_MOVE_THRESHOLD = 1.5
WINDOW_TRADING_DAYS = 5          # ~1 trading week
COHERENCE_MIN = 3                # of 4 instruments agreeing one direction

# ------------------------------------------------------------
# Redis REST helpers (Upstash) -- both env-name conventions
# ------------------------------------------------------------
REDIS_URL = (os.environ.get('UPSTASH_REDIS_REST_URL')
             or os.environ.get('UPSTASH_REDIS_URL', '')).rstrip('/')
REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_REST_TOKEN')
               or os.environ.get('UPSTASH_REDIS_TOKEN', ''))

_memory_cache = {}


def _redis_get(key):
    if not REDIS_URL or not REDIS_TOKEN:
        return _memory_cache.get(key)
    try:
        r = requests.get(f'{REDIS_URL}/get/{key}',
                         headers={'Authorization': f'Bearer {REDIS_TOKEN}'},
                         timeout=(5, 10))
        if r.status_code == 200:
            raw = r.json().get('result')
            if raw:
                return json.loads(raw)
    except Exception as e:
        print(f'[Repricing] Redis GET failed ({e}); memory fallback')
        return _memory_cache.get(key)
    return None


def _redis_set(key, value):
    _memory_cache[key] = value
    if not REDIS_URL or not REDIS_TOKEN:
        return
    try:
        requests.post(REDIS_URL,
                      headers={'Authorization': f'Bearer {REDIS_TOKEN}'},
                      json=['SET', key, json.dumps(value)],
                      timeout=(5, 15))
    except Exception as e:
        print(f'[Repricing] Redis SET failed ({e})')


# ------------------------------------------------------------
# Yahoo recent-quote fetcher (host failover, Chrome UA)
# ------------------------------------------------------------
YAHOO_HOSTS = ['https://query1.finance.yahoo.com',
               'https://query2.finance.yahoo.com']
CHROME_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
             'AppleWebKit/537.36 (KHTML, like Gecko) '
             'Chrome/124.0.0.0 Safari/537.36')


def _fetch_yahoo_recent(ticker, window_days=WINDOW_TRADING_DAYS):
    """Return {'last', 'prev', 'change_pct', 'as_of'} or None.

    Pulls ~45 calendar days of daily closes (host failover) and computes the
    percent change from `window_days` trading sessions ago to the latest close.
    """
    encoded = requests.utils.quote(ticker, safe='')
    now = int(datetime.now(timezone.utc).timestamp())
    p1 = now - 45 * 86400
    for host in YAHOO_HOSTS:
        try:
            url = (f'{host}/v8/finance/chart/{encoded}'
                   f'?period1={p1}&period2={now + 86400}&interval=1d')
            r = requests.get(url, headers={'User-Agent': CHROME_UA},
                             timeout=(6, 25))
            if r.status_code != 200:
                continue
            result = (r.json().get('chart') or {}).get('result')
            if not result:
                continue
            res = result[0]
            closes = ((res.get('indicators') or {}).get('quote')
                      or [{}])[0].get('close') or []
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                continue
            last = float(closes[-1])
            idx = max(0, len(closes) - 1 - window_days)
            prev = float(closes[idx])
            change_pct = ((last - prev) / prev * 100.0) if prev else 0.0
            return {'last': round(last, 4), 'prev': round(prev, 4),
                    'change_pct': round(change_pct, 3),
                    'as_of': datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            print(f'[Repricing] Yahoo {host} {ticker} failed: {e}')
            continue
    return None


# ------------------------------------------------------------
# THEATER CONFIG -- the portability layer (drift-engine pattern)
# ------------------------------------------------------------
# Each instrument carries a `peace_direction`: the way it moves when a durable
# peace is being priced. 'up' = rises, 'down' = falls. The defense instrument is
# a SPREAD (defense return minus broad-index return); peace_direction 'down'
# means the spread COMPRESSES (defense underperforming the broad index).
THEATER_CONFIG = {
    'israel': {
        'display': 'Israel',
        'flag': '\U0001F1EE\U0001F1F1',
        'rhetoric_key': 'rhetoric:iran:latest',     # Phase-1 de-escalation fingerprint
        'rhetoric_label': 'US-Iran off-ramp',
        'contradiction_front': 'continued Israeli operations on the Lebanon front',
        'structural_alternative': ('it views the broader Israel-Iran threat as '
                                   'structural beyond this particular framework'),
        'instruments': [
            {'id': 'broad', 'name': 'TA-35', 'ticker': '^TA35',
             'role': 'broad risk', 'peace_direction': 'up'},
            {'id': 'fx', 'name': 'the shekel', 'ticker': 'ILS=X',
             'role': 'FX risk premium', 'peace_direction': 'down'},  # USD/ILS down = shekel stronger
            {'id': 'defense_spread', 'name': 'defense (Elbit) vs the broad index',
             'ticker': 'ESLT', 'spread_vs': '^TA35',
             'role': 'defense demand', 'peace_direction': 'down'},
            {'id': 'oil', 'name': 'Brent', 'ticker': 'BZ=F',
             'role': 'war-premium commodity', 'peace_direction': 'down'},
        ],
    },
    # 'europe_ukraine': built in Slice 4 once a Russia-Ukraine off-ramp
    # fingerprint exists. Instruments would be the European defense basket
    # (Rheinmetall/BAE/Leonardo/Thales) vs a broad index, EUR, and Brent;
    # structural_alternative = European rearmament structural beyond a truce.
}


# ------------------------------------------------------------
# Rhetoric off-ramp reader
# ------------------------------------------------------------
_MATURITY_PHRASE = {
    'framework': 'framework, unsigned',
    'signed': 'signed, implementation pending',
    'implementing': 'implementation underway',
}


def _read_offramp(cfg):
    """Pull the de-escalation fingerprint for this theater's rhetoric key."""
    fp = _redis_get(cfg['rhetoric_key']) or {}
    maturity = fp.get('de_escalation_maturity') or 'none'
    return {
        'active': maturity not in ('none', None, ''),
        'maturity': maturity,
        'maturity_phrase': _MATURITY_PHRASE.get(maturity, maturity),
        'contradiction_active': bool(fp.get('contradiction_active')),
        'diplomatic_max_raw': fp.get('diplomatic_max_raw'),
    }


# ------------------------------------------------------------
# Instrument scoring -- fetch, apply polarity, cast a vote
# ------------------------------------------------------------
def _vote_for(instrument, change_pct):
    """Map a percent move to a vote given the instrument's peace polarity.

    Returns ('peace' | 'escalation' | 'flat', signed_change_used).
    """
    threshold = (SPREAD_MOVE_THRESHOLD if instrument['id'] == 'defense_spread'
                 else DEFAULT_MOVE_THRESHOLD)
    if change_pct is None:
        return 'unavailable', None
    if abs(change_pct) < threshold:
        return 'flat', change_pct
    moving_up = change_pct > 0
    peace_is_up = instrument['peace_direction'] == 'up'
    # Move in the peace direction -> peace vote; opposite -> escalation vote.
    if moving_up == peace_is_up:
        return 'peace', change_pct
    return 'escalation', change_pct


def _gather_instruments(cfg):
    """Fetch every instrument, compute the defense spread, cast votes."""
    quotes = {}
    tickers = set()
    for ins in cfg['instruments']:
        tickers.add(ins['ticker'])
        if ins.get('spread_vs'):
            tickers.add(ins['spread_vs'])
    for tk in tickers:
        quotes[tk] = _fetch_yahoo_recent(tk)

    scored = []
    for ins in cfg['instruments']:
        q = quotes.get(ins['ticker'])
        if ins.get('spread_vs'):
            qb = quotes.get(ins['spread_vs'])
            if q and qb:
                change = q['change_pct'] - qb['change_pct']   # defense minus broad
            else:
                change = None
        else:
            change = q['change_pct'] if q else None
        vote, used = _vote_for(ins, change)
        scored.append({
            'id': ins['id'], 'name': ins['name'], 'role': ins['role'],
            'change_pct': used, 'vote': vote,
        })
    return scored


# ------------------------------------------------------------
# Coherence -> state classification
# ------------------------------------------------------------
def _classify(scored, offramp):
    peace = [s for s in scored if s['vote'] == 'peace']
    esc = [s for s in scored if s['vote'] == 'escalation']
    available = [s for s in scored if s['vote'] not in ('unavailable',)]

    if len(available) < COHERENCE_MIN:
        return 'insufficient_data', peace, esc

    peace_coherent = len(peace) >= COHERENCE_MIN and len(esc) == 0
    esc_coherent = len(esc) >= COHERENCE_MIN and len(peace) == 0

    if offramp['active']:
        if peace_coherent:
            return 'offramp_corroborated', peace, esc
        if esc_coherent:
            return 'offramp_contradicted', peace, esc
        return 'offramp_market_mixed', peace, esc
    # No active off-ramp -- bidirectional: read an escalation repricing if coherent.
    if esc_coherent:
        return 'escalation_repricing', peace, esc
    if peace_coherent:
        return 'calm_repricing', peace, esc
    return 'no_read', peace, esc


# ------------------------------------------------------------
# Observed-pattern phrasing
# ------------------------------------------------------------
def _phrase_instrument(s, vote_kind):
    """Plain-language phrase for one instrument given the direction it voted."""
    up = (s['change_pct'] or 0) > 0
    iid = s['id']
    if iid == 'broad':
        return 'the TA-35 is firming' if up else 'the TA-35 is weakening'
    if iid == 'fx':
        # ILS=X up = USD stronger = shekel weaker
        return 'the shekel is weakening' if up else 'the shekel is strengthening'
    if iid == 'defense_spread':
        return ('defense (Elbit) is outperforming the broad index' if up
                else 'defense (Elbit) is underperforming the broad index')
    if iid == 'oil':
        return 'Brent is firming' if up else 'Brent is softening'
    return s['name']


def _observed_pattern(scored, vote_kind):
    parts = [_phrase_instrument(s, vote_kind) for s in scored if s['vote'] == vote_kind]
    if not parts:
        return 'instruments are mixed'
    if len(parts) == 1:
        return parts[0]
    return ', '.join(parts[:-1]) + ' and ' + parts[-1]


# ------------------------------------------------------------
# The estimative prose builder (the locked output contract)
# ------------------------------------------------------------
def build_market_read(cfg, state, scored, offramp, peace, esc):
    d = cfg['display']
    label = cfg['rhetoric_label']
    mat = offramp['maturity_phrase']

    if state == 'offramp_contradicted':
        contradiction = (f" and {cfg['contradiction_front']}"
                         if offramp['contradiction_active'] else "")
        observed = _observed_pattern(scored, 'escalation')
        tail = (" -- the tape and the Lebanon front are positioned the same way "
                "this cycle" if offramp['contradiction_active'] else "")
        return (f"Market read ({d}): With an active {label} in the rhetoric layer "
                f"({mat}){contradiction}, {observed}. This repricing is consistent "
                f"with one of two readings: that informed capital is not pricing the "
                f"off-ramp as durable, or that {cfg['structural_alternative']}. In "
                f"either case the market is declining to price a peace dividend"
                f"{tail}. {DISCLAIMER}")

    if state == 'offramp_corroborated':
        observed = _observed_pattern(scored, 'peace')
        return (f"Market read ({d}): With an active {label} in the rhetoric layer "
                f"({mat}), {observed}. This repricing is consistent with informed "
                f"capital pricing the off-ramp as durable and beginning to discount "
                f"the regional risk premium. The rhetoric off-ramp and market "
                f"positioning are aligned on durability this cycle. {DISCLAIMER}")

    if state == 'offramp_market_mixed':
        return (f"Market read ({d}): An active {label} is present in the rhetoric "
                f"layer ({mat}), but market instruments are not moving coherently "
                f"relative to it this cycle -- no clean corroboration or "
                f"contradiction read. {DISCLAIMER}")

    if state == 'escalation_repricing':
        observed = _observed_pattern(scored, 'escalation')
        return (f"Market read ({d}): No active off-ramp in the rhetoric layer, and "
                f"{observed}. This repricing is consistent with informed capital "
                f"pricing an expanding war-risk premium. {DISCLAIMER}")

    if state == 'calm_repricing':
        observed = _observed_pattern(scored, 'peace')
        return (f"Market read ({d}): No named off-ramp in the rhetoric layer, yet "
                f"{observed}. This repricing is consistent with a compressing "
                f"war-risk premium absent a formal diplomatic track. {DISCLAIMER}")

    if state == 'insufficient_data':
        return (f"Market read ({d}): insufficient live market data this cycle to "
                f"read repricing against the rhetoric layer. {DISCLAIMER}")

    return (f"Market read ({d}): no coherent repricing signal relative to the "
            f"rhetoric layer this cycle. {DISCLAIMER}")


# ------------------------------------------------------------
# Scan orchestration
# ------------------------------------------------------------
_GPI_GATED_STATES = {'offramp_contradicted', 'offramp_corroborated',
                     'escalation_repricing'}


def run_scan(theater='israel'):
    cfg = THEATER_CONFIG.get(theater)
    if not cfg:
        return {'success': False, 'error': f'unknown theater: {theater}',
                'version': VERSION}

    offramp = _read_offramp(cfg)
    scored = _gather_instruments(cfg)
    state, peace, esc = _classify(scored, offramp)
    market_read = build_market_read(cfg, state, scored, offramp, peace, esc)

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        'success': True,
        'module': 'conflict_repricing_detector',
        'version': VERSION,
        'theater': theater,
        'display': cfg['display'],
        'flag': cfg['flag'],
        'state': state,
        'market_read': market_read,
        'offramp': offramp,
        'instruments': scored,
        'coherence': {'peace_votes': len(peace), 'escalation_votes': len(esc),
                      'min_required': COHERENCE_MIN},
        'disclaimer': DISCLAIMER,
        'last_updated': now,
    }

    _redis_set(f'repricing:{theater}:latest', payload)

    # Compact GPI bundle (consumed by Slice 3's narrative). Gated to states the
    # GPI should surface -- mixed / no_read / insufficient stay off the rollup.
    _redis_set(f'repricing:{theater}:gpi', {
        'theater': theater,
        'display': cfg['display'],
        'flag': cfg['flag'],
        'state': state,
        'gpi_eligible': state in _GPI_GATED_STATES,
        'market_read': market_read,
        'updated_at': now,
        'disclaimer': DISCLAIMER,
    })
    return payload


def _is_fresh(payload, ttl_hours):
    try:
        then = datetime.fromisoformat(payload.get('last_updated')
                                      or payload.get('generated_at'))
        return (datetime.now(timezone.utc) - then).total_seconds() / 3600 < ttl_hours
    except Exception:
        return False


# ------------------------------------------------------------
# Flask endpoint registration
# ------------------------------------------------------------
def register_conflict_repricing_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/conflict-repricing/<theater>', methods=['GET', 'OPTIONS'])
    def api_conflict_repricing(theater):
        if request.method == 'OPTIONS':
            return '', 200
        if theater not in THEATER_CONFIG:
            return jsonify({'success': False,
                            'error': f'unknown theater: {theater}',
                            'available': sorted(THEATER_CONFIG.keys()),
                            'version': VERSION}), 404
        force = request.args.get('force', 'false').lower() == 'true'
        cache_key = f'repricing:{theater}:latest'
        if not force:
            cached = _redis_get(cache_key)
            if cached and _is_fresh(cached, CACHE_TTL_HOURS):
                cached['cached'] = True
                return jsonify(cached)
        payload = run_scan(theater)
        if payload and payload.get('success'):
            payload['cached'] = False
            return jsonify(payload)
        cached = _redis_get(cache_key)
        if cached:
            cached['cached'] = True
            cached['stale'] = True
            return jsonify(cached)
        return jsonify({'success': False,
                        'error': 'Scan failed (market data unreachable, no cache)',
                        'version': VERSION}), 503

    @app.route('/api/conflict-repricing/<theater>/debug', methods=['GET'])
    def api_conflict_repricing_debug(theater):
        if theater not in THEATER_CONFIG:
            return jsonify({'error': 'unknown theater',
                            'available': sorted(THEATER_CONFIG.keys())}), 404
        cfg = THEATER_CONFIG[theater]
        return jsonify({
            'theater': theater,
            'offramp': _read_offramp(cfg),
            'instruments': _gather_instruments(cfg),
            'version': VERSION,
        })

    print(f'[Repricing] Endpoints registered (v{VERSION}) '
          f'theaters={sorted(THEATER_CONFIG.keys())}')


if __name__ == '__main__':
    # Offline self-test of the prose builder (no network).
    cfg = THEATER_CONFIG['israel']
    off_active = {'active': True, 'maturity': 'framework',
                  'maturity_phrase': 'framework, unsigned',
                  'contradiction_active': True, 'diplomatic_max_raw': 4}
    contra = [
        {'id': 'broad', 'name': 'TA-125', 'role': 'broad risk', 'change_pct': -2.5, 'vote': 'escalation'},
        {'id': 'fx', 'name': 'the shekel', 'role': 'FX', 'change_pct': 1.2, 'vote': 'escalation'},
        {'id': 'defense_spread', 'name': 'defense', 'role': 'demand', 'change_pct': 2.0, 'vote': 'escalation'},
        {'id': 'oil', 'name': 'Brent', 'role': 'commodity', 'change_pct': 3.1, 'vote': 'escalation'},
    ]
    st, p, e = _classify(contra, off_active)
    print('STATE:', st)
    print(build_market_read(cfg, st, contra, off_active, p, e))
