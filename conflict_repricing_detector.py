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
from market_prose import market_disclaimer

VERSION = '0.4.0'  # Slice 4b (europe_ukraine theater + per-theater seeds)
CACHE_TTL_HOURS = 12

DISCLAIMER = market_disclaimer(
    subject="market positioning",
    forecast_of=" of whether the off-ramp holds",
    coda=("It reports what informed capital appears to be pricing; the reader "
          "completes the inference."))

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
        'contradiction_tail': ('the tape and the Lebanon front are positioned the '
                               'same way this cycle'),
        'structural_alternative': ('it views the broader Israel-Iran threat as '
                                   'structural beyond this particular framework'),
        'instruments': [
            {'id': 'broad', 'name': 'Israel ETF (EIS)', 'ticker': 'EIS',
             'role': 'broad risk', 'peace_direction': 'up'},
            {'id': 'fx', 'name': 'the shekel', 'ticker': 'ILS=X',
             'role': 'FX risk premium', 'peace_direction': 'down'},  # USD/ILS down = shekel stronger
            {'id': 'defense_spread', 'name': 'defense (Elbit) vs the broad index',
             'ticker': 'ESLT', 'spread_vs': 'EIS',
             'role': 'defense demand', 'peace_direction': 'down'},
            {'id': 'oil', 'name': 'Brent', 'ticker': 'BZ=F',
             'role': 'war-premium commodity', 'peace_direction': 'down'},
        ],
        'phrasing': {
            'broad': ('broad Israel equities are firming',
                      'broad Israel equities are weakening'),
            'fx': ('the shekel is weakening', 'the shekel is strengthening'),
            'defense_spread': ('defense (Elbit) is outperforming the broad index',
                               'defense (Elbit) is underperforming the broad index'),
            'oil': ('Brent is firming', 'Brent is softening'),
        },
        'leg_names': {'broad': 'broad equities', 'fx': 'the shekel',
                      'defense_spread': 'defense demand', 'oil': 'oil'},
        'episodes': [
            {'id': 'oct_2023_war_onset', 'date': 'Oct 2023',
             'regime': 'war_expansion_riskoff', 'label': 'the Oct 2023 war onset',
             'signature': ['broad:escalation', 'fx:escalation',
                           'defense_spread:escalation', 'oil:escalation']},
            {'id': 'jan_2026_rising_lion', 'date': 'Jan 2026',
             'regime': 'winning_war_rally', 'label': 'the Jan 2026 Rising Lion rally',
             'signature': ['broad:peace', 'fx:peace',
                           'defense_spread:escalation', 'oil:escalation']},
            {'id': 'mar_2026_war_week', 'date': 'Mar 2026',
             'regime': 'winning_war_rally', 'label': 'the Mar 2026 war-week rally',
             'signature': ['broad:peace', 'fx:peace',
                           'defense_spread:escalation', 'oil:escalation']},
            {'id': 'jun_2026_reescalation', 'date': 'Jun 8 2026',
             'regime': 'war_expansion_riskoff',
             'label': 'the Jun 8 2026 re-escalation selloff',
             'signature': ['broad:escalation', 'fx:escalation',
                           'defense_spread:escalation', 'oil:escalation']},
            {'id': 'jun_2025_ceasefire', 'date': 'Jun 2025',
             'regime': 'peace_dividend', 'label': 'the Jun 2025 ceasefire risk-on',
             'signature': ['broad:peace', 'fx:peace',
                           'defense_spread:peace', 'oil:peace']},
        ],
    },
    'europe_ukraine': {
        'display': 'Europe',
        'flag': '\U0001F1EA\U0001F1FA',
        'rhetoric_key': 'rhetoric:ukraine:latest',   # Slice 4a off-ramp fingerprint
        'rhetoric_label': 'Russia-Ukraine off-ramp',
        'contradiction_front': 'intensified strikes on both fronts',
        'contradiction_tail': ('the tape and the battlefield are positioned the '
                               'same way this cycle'),
        'structural_alternative': ('it regards European rearmament as structural and '
                                   'durable beyond a Ukraine truce'),
        'instruments': [
            {'id': 'broad', 'name': 'Europe ETF (VGK)', 'ticker': 'VGK',
             'role': 'broad risk', 'peace_direction': 'up'},
            {'id': 'fx', 'name': 'the euro', 'ticker': 'EURUSD=X',
             'role': 'FX risk premium', 'peace_direction': 'up'},  # EUR/USD up = euro stronger
            {'id': 'defense_spread', 'name': 'European defense (Rheinmetall) vs the broad index',
             'ticker': 'RHM.DE', 'spread_vs': 'VGK',
             'role': 'defense demand', 'peace_direction': 'down'},
            {'id': 'oil', 'name': 'Brent', 'ticker': 'BZ=F',
             'role': 'war-premium commodity', 'peace_direction': 'down'},
        ],
        'phrasing': {
            'broad': ('broad European equities are firming',
                      'broad European equities are weakening'),
            'fx': ('the euro is strengthening', 'the euro is weakening'),
            'defense_spread': ('European defense (Rheinmetall) is outperforming the broad index',
                               'European defense (Rheinmetall) is underperforming the broad index'),
            'oil': ('Brent is firming', 'Brent is softening'),
        },
        'leg_names': {'broad': 'broad equities', 'fx': 'the euro',
                      'defense_spread': 'defense demand', 'oil': 'oil'},
        'episodes': [
            {'id': 'feb_2022_invasion', 'date': 'Feb 2022',
             'regime': 'war_expansion_riskoff',
             'label': 'the Feb 2022 invasion shock',
             'signature': ['broad:escalation', 'fx:escalation',
                           'defense_spread:escalation', 'oil:escalation']},
            {'id': 'ukraine_durable_ceasefire', 'date': 'archetype',
             'regime': 'peace_dividend',
             'label': 'a durable Russia-Ukraine ceasefire',
             'signature': ['broad:peace', 'fx:peace',
                           'defense_spread:peace', 'oil:peace']},
            {'id': 'eu_rearmament_structural', 'date': 'archetype',
             'regime': 'rearmament_structural',
             'label': 'a rearmament-structural peace',
             'signature': ['broad:peace', 'fx:peace',
                           'defense_spread:escalation', 'oil:peace']},
        ],
    },

    # ════════════════════════════════════════════════════════════════════
    # KOREA (v0.5.0 -- Jul 12 2026) -- the first mode='habituation' theater
    # ════════════════════════════════════════════════════════════════════
    # WHY THIS THEATER CANNOT USE THE OFF-RAMP SCHEMA:
    # Israel and europe_ukraine both ask "does informed capital price the peace
    # as durable?" That question requires a peace. Korea has none: the war never
    # ended. It has been an ARMISTICE since 1953. There is no ceasefire to
    # corroborate or contradict, so an off-ramp read here would be measuring a
    # thing that does not exist -- and would report its absence as calm.
    #
    # WHAT REPLACES IT:
    # The KOSPI has been shot at so many times it stopped flinching. The "Korea
    # discount" is a named, measured phenomenon: a missile test that once moved
    # Seoul now moves it a tenth of a percent. So the question inverts --
    #
    #     HAS THE MARKET GONE NUMB, AND WHAT DOES IT TAKE TO WAKE IT?
    #
    # And that is not a cute framing. It is the SAME VARIABLE the rhetoric
    # tracker's leverage-integrity instrument measures, read from the other end.
    # Pyongyang's whole strategy depends on provocations still buying attention.
    # The tape is the scoreboard for whether they do. A test that moves nothing
    # means the leverage has decayed -- and by the tracker's own inverted read,
    # THAT is the dangerous condition, because a sidelined DPRK escalates to be
    # noticed. Two independent sensors, opposite ends, same variable. Convergence
    # in the doctrinal sense, not the decorative one.
    'korea': {
        'display': 'Korea',
        'flag': '\U0001F1F0\U0001F1F7',      # ROK -- the market that pays, not the one that shouts
        'mode': 'habituation',
        'rhetoric_key': 'rhetoric:dprk:latest',
        'rhetoric_label': 'DPRK provocation',
        # No off-ramp fields (contradiction_front / structural_alternative): there
        # is no off-ramp. Their absence is the point, not an oversight.
        'instruments': [
            {'id': 'broad', 'name': 'South Korea ETF (EWY)', 'ticker': 'EWY',
             'role': 'broad risk', 'peace_direction': 'up'},
            {'id': 'fx', 'name': 'the won', 'ticker': 'KRW=X',
             'role': 'FX risk premium', 'peace_direction': 'down'},  # USD/KRW down = won stronger
            {'id': 'defense_spread', 'name': 'defense (Hanwha Aerospace) vs the broad index',
             'ticker': '012450.KS', 'spread_vs': 'EWY',
             'role': 'defense demand', 'peace_direction': 'down'},
            # Fourth leg is REGIONAL CONTAGION, not a war-premium commodity. Korea
            # has no Brent. What it has is a neighbour: a missile over Japan drives
            # safe-haven flight into the yen. If Seoul flinches and Tokyo does not,
            # the market has read the event as a local Korean story.
            {'id': 'regional_contagion', 'name': 'the yen (safe-haven flight)',
             'ticker': 'JPY=X',
             'role': 'regional contagion', 'peace_direction': 'up'},  # USD/JPY up = yen weaker = no flight
        ],
        'phrasing': {
            'broad': ('South Korean equities are firming',
                      'South Korean equities are weakening'),
            'fx': ('the won is weakening', 'the won is strengthening'),
            'defense_spread': ('Korean defense (Hanwha) is outperforming the broad index',
                               'Korean defense (Hanwha) is underperforming the broad index'),
            'regional_contagion': ('the yen is weakening (no safe-haven flight)',
                                   'the yen is strengthening (safe-haven flight)'),
        },
        'leg_names': {'broad': 'Korean equities', 'fx': 'the won',
                      'defense_spread': 'defense demand',
                      'regional_contagion': 'regional contagion'},
        # Episode seeds. NOTE: numbness is SIGNATURE-LESS by construction -- an
        # all-flat tape produces an empty vote set, which cannot Jaccard-match
        # anything. That is correct and worth stating: the habituation read does
        # not lean on the episode library the way the off-ramp theaters do. The
        # library here exists to remember the FLINCHES, so we can see how far the
        # present has drifted from them.
        'episodes': [
            {'id': 'sep_2017_sixth_test', 'date': 'Sep 2017',
             'regime': 'market_flinch',
             'label': 'the Sep 2017 sixth-nuclear-test selloff (when Seoul still flinched)',
             'signature': ['broad:escalation', 'fx:escalation',
                           'defense_spread:escalation', 'regional_contagion:escalation']},
        ],
    },
}


# ------------------------------------------------------------
# Rhetoric off-ramp reader
# ------------------------------------------------------------
_MATURITY_PHRASE = {
    'framework': 'framework, unsigned',
    'signed': 'signed, implementation pending',
    'implementing': 'implementation underway',
}


_PROVOCATION_PHRASE = {
    'nuclear_test':   'a nuclear test',
    'icbm':           'an ICBM launch',
    'satellite':      'a satellite launch',
    'irbm':           'an IRBM launch',
    'srbm':           'short-range launches',
    'cruise':         'cruise-missile launches',
    'sub_threshold':  'sub-threshold provocation',
}


def _read_provocation(cfg):
    """HABITUATION MODE: read the DPRK provocation fingerprint, not an off-ramp.

    Absence-honest in two DIFFERENT ways, and the distinction is load-bearing:
      - feed_missing = the tracker has never written. We know NOTHING. Say so.
      - No provocation this cycle = the tracker wrote, and it is genuinely quiet.
    Collapsing these would let a dead tracker masquerade as a calm peninsula --
    the same class of error as a dead RSS feed masquerading as an actor's silence.
    """
    fp = _redis_get(cfg['rhetoric_key'])
    if not fp:
        return {'feed_missing': True, 'active': False, 'maturity': 'none',
                'maturity_phrase': 'rhetoric feed pending',
                'contradiction_active': False, 'diplomatic_max_raw': None,
                'provocation_class': None, 'provocation_phrase': None}
    pclass = fp.get('provocation_class') or None
    return {
        'feed_missing': False,
        'active': bool(fp.get('provocation_active')),
        'provocation_class': pclass,
        'provocation_phrase': _PROVOCATION_PHRASE.get(pclass, pclass or 'a provocation'),
        'leverage_integrity': fp.get('leverage_integrity'),
        'maturity': 'none',
        'maturity_phrase': 'n/a -- armistice, not ceasefire',
        'contradiction_active': False,
        'diplomatic_max_raw': None,
    }


def _read_offramp(cfg):
    """Pull the de-escalation fingerprint for this theater's rhetoric key.

    Mode dispatch (v0.5.0): habituation theaters (Korea) read a provocation
    fingerprint instead. Using the wrong reader produces confident nonsense --
    an off-ramp read on a war that never ended would report the permanent
    absence of a ceasefire as calm.
    """
    if cfg.get('mode') == 'habituation':
        return _read_provocation(cfg)
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
    # Decontaminate the broad gauge before scoring coherence. The broad ETF (EIS)
    # CONTAINS the defense/energy names whose war premium we isolate via the
    # defense spread and oil. When the defense spread is COMPRESSING (peace vote)
    # and the broad index is merely DOWN, that broad decline is being led by the
    # same deflating war-premium sectors -- it is NOT an independent risk-off
    # signal. Neutralize it to 'flat'. We deliberately do NOT flip it to 'peace':
    # that would double-count the defense vote and manufacture coherence, which
    # the convergence doctrine forbids (a derived signal is an echo, not a vote).
    _bid = {s['id']: s for s in scored}
    _broad = _bid.get('broad')
    _def = _bid.get('defense_spread')
    if (_broad and _def and _def.get('vote') == 'peace'
            and _broad.get('vote') == 'escalation'
            and (_broad.get('change_pct') or 0) < 0):
        _broad['raw_vote'] = _broad['vote']
        _broad['vote'] = 'flat'
        _broad['neutralized'] = ('broad decline led by war-premium (defense/energy) '
                                 'deflation -- not an independent risk-off read')

    peace = [s for s in scored if s['vote'] == 'peace']
    esc = [s for s in scored if s['vote'] == 'escalation']
    available = [s for s in scored if s['vote'] not in ('unavailable',)]

    if len(available) < COHERENCE_MIN:
        return 'insufficient_data', peace, esc

    # ── HABITUATION MODE (Korea) ──
    # We are not asking whether the market believes a peace. We are asking
    # whether it still REACTS. The finding lives in the pairing of a live
    # provocation against a tape that did not move.
    if offramp.get('mode') == 'habituation' or offramp.get('provocation_phrase') is not None \
            or offramp.get('feed_missing'):
        if offramp.get('feed_missing'):
            return 'rhetoric_pending', peace, esc
        moved = len(peace) + len(esc)
        if offramp['active']:
            # A provocation fired. Did anyone flinch?
            if len(esc) >= COHERENCE_MIN and len(peace) == 0:
                return 'market_alert', peace, esc      # the tape woke up
            if moved == 0:
                return 'numb', peace, esc              # THE headline finding
            return 'partial_flinch', peace, esc        # some legs moved, not coherent
        # No provocation this cycle.
        if moved >= COHERENCE_MIN:
            return 'unattributed_move', peace, esc     # something moved it; not Pyongyang
        return 'quiet', peace, esc

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
def _phrase_instrument(s, vote_kind, cfg):
    """Plain-language phrase for one instrument, per-theater (config-driven)."""
    up = (s['change_pct'] or 0) > 0
    ph = (cfg.get('phrasing') or {}).get(s['id'])
    if ph:
        return ph[0] if up else ph[1]   # (up_phrase, down_phrase)
    return s['name']


def _observed_pattern(scored, vote_kind, cfg):
    parts = [_phrase_instrument(s, vote_kind, cfg) for s in scored if s['vote'] == vote_kind]
    if not parts:
        return 'instruments are mixed'
    if len(parts) == 1:
        return parts[0]
    return ', '.join(parts[:-1]) + ' and ' + parts[-1]


# ------------------------------------------------------------
# The estimative prose builder (the locked output contract)
# ------------------------------------------------------------
def _build_habituation_read(cfg, state, scored, offramp, peace, esc):
    """HABITUATION PROSE (Korea). Estimative, precedent-anchored, no forecast."""
    d = cfg['display']
    prov = offramp.get('provocation_phrase') or 'a provocation'

    if state == 'rhetoric_pending':
        return (f"Market read ({d}): the DPRK rhetoric feed has not yet written a "
                f"provocation fingerprint, so the tape cannot be read against it this "
                f"cycle. Absence of a feed is not evidence of a quiet peninsula. "
                f"{DISCLAIMER}")

    if state == 'numb':
        lev = offramp.get('leverage_integrity')
        lev_txt = (f" The rhetoric layer reads leverage integrity at {lev}/100."
                   if lev is not None else "")
        return (f"Market read ({d}): {prov.capitalize()} registered in the rhetoric "
                f"layer this cycle, and not one of the four instruments moved beyond "
                f"threshold. The tape did not flinch. This is consistent with informed "
                f"capital having priced DPRK provocation as structural noise -- the "
                f"pattern the 'Korea discount' names -- rather than as a change in "
                f"condition.{lev_txt} Note the direction of that read: a provocation "
                f"that buys no attention is a provocation that bought no leverage, and "
                f"the historical pattern is that Pyongyang escalates when it is being "
                f"negotiated around, not when it is being courted. A numb tape is not "
                f"the same thing as a calm one. {DISCLAIMER}")

    if state == 'market_alert':
        observed = _observed_pattern(scored, 'escalation', cfg)
        return (f"Market read ({d}): {prov.capitalize()} registered in the rhetoric "
                f"layer, and the tape moved with it -- {observed}. This is a departure "
                f"from the habituated baseline: informed capital is pricing this event "
                f"as a change in condition rather than as routine. Deviation from "
                f"numbness is the signal here, and it is consistent either with an "
                f"event that differed in kind from the routine, or with a market "
                f"assumption that has broken. {DISCLAIMER}")

    if state == 'partial_flinch':
        legs = (cfg.get('leg_names') or {})
        moved = [legs.get(s['id'], s['id']) for s in scored
                 if s['vote'] in ('peace', 'escalation')]
        joined = ', '.join(moved[:-1]) + ' and ' + moved[-1] if len(moved) > 1 else moved[0]
        return (f"Market read ({d}): {prov.capitalize()} registered, and the tape moved "
                f"only partially -- {joined} responded while the remaining instruments "
                f"held flat. Not coherent enough to read as a repricing, but not the "
                f"full numbness of the habituated baseline either. A partial flinch. "
                f"{DISCLAIMER}")

    if state == 'unattributed_move':
        observed = _observed_pattern(scored, 'escalation' if len(esc) >= len(peace)
                                     else 'peace', cfg)
        return (f"Market read ({d}): no DPRK provocation in the rhetoric layer this "
                f"cycle, yet {observed}. This movement is NOT attributable to the "
                f"peninsula on the evidence available -- Korean assets carry global "
                f"semiconductor and trade exposure that moves them for reasons that "
                f"have nothing to do with Pyongyang. Reported, not attributed. "
                f"{DISCLAIMER}")

    if state == 'quiet':
        return (f"Market read ({d}): no DPRK provocation in the rhetoric layer and no "
                f"coherent movement across the instruments this cycle. Baseline. "
                f"{DISCLAIMER}")

    if state == 'insufficient_data':
        return (f"Market read ({d}): insufficient live market data this cycle to read "
                f"the tape against the rhetoric layer. {DISCLAIMER}")

    return f"Market read ({d}): no coherent read this cycle. {DISCLAIMER}"


def build_market_read(cfg, state, scored, offramp, peace, esc):
    if cfg.get('mode') == 'habituation':
        return _build_habituation_read(cfg, state, scored, offramp, peace, esc)
    d = cfg['display']
    label = cfg['rhetoric_label']
    mat = offramp['maturity_phrase']

    if state == 'offramp_contradicted':
        contradiction = (f" and {cfg['contradiction_front']}"
                         if offramp['contradiction_active'] else "")
        observed = _observed_pattern(scored, 'escalation', cfg)
        tail = (f" -- {cfg['contradiction_tail']}"
                if offramp['contradiction_active'] else "")
        return (f"Market read ({d}): With an active {label} in the rhetoric layer "
                f"({mat}){contradiction}, {observed}. This repricing is consistent "
                f"with one of two readings: that informed capital is not pricing the "
                f"off-ramp as durable, or that {cfg['structural_alternative']}. In "
                f"either case the market is declining to price a peace dividend"
                f"{tail}. {DISCLAIMER}")

    if state == 'offramp_corroborated':
        observed = _observed_pattern(scored, 'peace', cfg)
        return (f"Market read ({d}): With an active {label} in the rhetoric layer "
                f"({mat}), {observed}. This repricing is consistent with informed "
                f"capital pricing the off-ramp as durable and beginning to discount "
                f"the regional risk premium. The rhetoric off-ramp and market "
                f"positioning are aligned on durability this cycle. {DISCLAIMER}")

    if state == 'offramp_market_mixed':
        if len(peace) >= 2 and len(esc) == 0:
            observed = _observed_pattern(scored, 'peace', cfg)
            return (f"Market read ({d}): An active {label} is present in the rhetoric "
                    f"layer ({mat}). The clean signals present -- {observed} -- lean "
                    f"toward informed capital pricing the off-ramp as durable, but the "
                    f"instruments are not yet fully coherent, so this is a directional "
                    f"lean rather than a corroboration read. {DISCLAIMER}")
        if len(esc) >= 2 and len(peace) == 0:
            observed = _observed_pattern(scored, 'escalation', cfg)
            return (f"Market read ({d}): An active {label} is present in the rhetoric "
                    f"layer ({mat}). The clean signals present -- {observed} -- lean "
                    f"toward the market declining to price the off-ramp as durable, but "
                    f"the instruments are not yet fully coherent, so this is a "
                    f"directional lean rather than a contradiction read. {DISCLAIMER}")
        return (f"Market read ({d}): An active {label} is present in the rhetoric "
                f"layer ({mat}), but market instruments are not moving coherently "
                f"relative to it this cycle -- no clean corroboration or "
                f"contradiction read. {DISCLAIMER}")

    if state == 'escalation_repricing':
        observed = _observed_pattern(scored, 'escalation', cfg)
        return (f"Market read ({d}): No active off-ramp in the rhetoric layer, and "
                f"{observed}. This repricing is consistent with informed capital "
                f"pricing an expanding war-risk premium. {DISCLAIMER}")

    if state == 'calm_repricing':
        observed = _observed_pattern(scored, 'peace', cfg)
        return (f"Market read ({d}): No named off-ramp in the rhetoric layer, yet "
                f"{observed}. This repricing is consistent with a compressing "
                f"war-risk premium absent a formal diplomatic track. {DISCLAIMER}")

    if state == 'insufficient_data':
        return (f"Market read ({d}): insufficient live market data this cycle to "
                f"read repricing against the rhetoric layer. {DISCLAIMER}")

    return (f"Market read ({d}): no coherent repricing signal relative to the "
            f"rhetoric layer this cycle. {DISCLAIMER}")


# ------------------------------------------------------------
# Episode library + Jaccard similarity (Slice 2)
# ------------------------------------------------------------
# Each market print has a SIGNATURE: the set of its active (non-flat) directional
# votes, in PEACE-polarity vote space (peace = moving toward durable-peace
# pricing). We Jaccard-match the live signature against a small library of
# LABELED historical regimes. Flat/neutralized votes are excluded -- only active
# legs carry signal (a convergence of one source is an echo). Post-hoc pattern
# memory + structural similarity; NOT machine learning and NOT a forecast.
_REGIME_PHRASE = {
    'war_expansion_riskoff': 'war-expansion risk-off',
    'winning_war_rally': 'winning-war rally',
    'peace_dividend': 'peace-dividend',
    'rearmament_structural': 'rearmament-structural',
}
_LEG_NAME = {'broad': 'broad equities', 'fx': 'the shekel',
             'defense_spread': 'defense demand', 'oil': 'oil'}

EPISODE_MATCH_FLOOR = 0.15   # below this, not a meaningful analog
EPISODE_TOP_N = 2


def _signature(scored):
    """Active (non-flat) directional votes as a token set, e.g. {'oil:peace'}."""
    return frozenset(f"{s['id']}:{s['vote']}" for s in scored
                     if s.get('vote') in ('peace', 'escalation'))


def _jaccard(a, b):
    u = a | b
    return (len(a & b) / len(u)) if u else 0.0


def _leg(tok, leg_names):
    return leg_names.get(tok.split(':', 1)[0], tok)


def _labeled_pool(theater):
    """Per-theater seed episodes + any operator-labeled episodes from Redis."""
    seeds = (THEATER_CONFIG.get(theater) or {}).get('episodes') or []
    extra = _redis_get(f'repricing:{theater}:labeled')
    return list(seeds) + (extra if isinstance(extra, list) else [])


def match_episodes(scored, theater='israel', top_n=EPISODE_TOP_N,
                   floor=EPISODE_MATCH_FLOOR):
    """Top-N labeled regimes most similar to the current signature (Jaccard).

    Pool = the seeded LABELED_EPISODES plus any episodes the operator has
    labeled into Redis via the /label endpoint (Slice 2b pattern memory).
    """
    sig = _signature(scored)
    leg_names = (THEATER_CONFIG.get(theater) or {}).get('leg_names') or _LEG_NAME
    out = []
    for ep in _labeled_pool(theater):
        ep_sig = frozenset(ep['signature'])
        j = _jaccard(sig, ep_sig)
        if j >= floor:
            shared = sorted({_leg(t, leg_names) for t in (sig & ep_sig)})
            out.append({'id': ep['id'], 'label': ep['label'], 'date': ep['date'],
                        'regime': ep['regime'], 'similarity': round(j, 3),
                        'shared_legs': shared})
    out.sort(key=lambda r: r['similarity'], reverse=True)
    return out[:top_n]


def episode_read(matches):
    """One estimative sentence naming the closest historical analog."""
    if not matches:
        return ("No labeled market-regime episode closely resembles this "
                "signature.")
    t = matches[0]
    pct = int(round(t['similarity'] * 100))
    legs = ', '.join(t['shared_legs']) if t['shared_legs'] else 'no shared legs'
    return (f"Closest historical analog: {t['label']} ({t['date']}), a "
            f"{_REGIME_PHRASE.get(t['regime'], t['regime'])} signature -- "
            f"~{pct}% similar this cycle, sharing {legs}.")


# ------------------------------------------------------------
# Pattern memory: auto-snapshot (Slice 2b)
# ------------------------------------------------------------
def _snapshot(theater, state, signature, offramp):
    """Auto-archive a meaningful scan's signature for later labeling (Slice 2b).

    Skips empty / non-readable states. Light dedup: an identical signature+state
    inside the last hour is not re-archived (prevents force-scan test spam).
    Capped at 200, newest last; no TTL (the cap bounds growth).
    """
    if state in ('insufficient_data', 'no_read'):
        return
    sig_list = sorted(signature)
    if not sig_list:
        return
    key = f'repricing:{theater}:snapshots'
    snaps = _redis_get(key)
    if not isinstance(snaps, list):
        snaps = []
    now = datetime.now(timezone.utc)
    if snaps:
        last = snaps[-1]
        if last.get('signature') == sig_list and last.get('state') == state:
            try:
                age = (now - datetime.fromisoformat(last['created_at'])).total_seconds()
                if age < 3600:
                    return
            except Exception:
                pass
    snaps.append({
        'id': now.strftime('%Y%m%dT%H%M%SZ'),
        'date': now.strftime('%Y-%m-%d'),
        'state': state,
        'signature': sig_list,
        'offramp_maturity': offramp.get('maturity'),
        'created_at': now.isoformat(),
    })
    _redis_set(key, snaps[-200:])


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
    matches = match_episodes(scored, theater)
    ep_read = episode_read(matches)
    _snapshot(theater, state, _signature(scored), offramp)

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
        'episode_read': ep_read,
        'similar_episodes': matches,
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
        'episode_read': ep_read,
        'top_analog': matches[0] if matches else None,
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

    @app.route('/api/conflict-repricing/<theater>/history', methods=['GET'])
    def api_conflict_repricing_history(theater):
        if theater not in THEATER_CONFIG:
            return jsonify({'error': 'unknown theater',
                            'available': sorted(THEATER_CONFIG.keys())}), 404
        return jsonify({
            'theater': theater,
            'snapshots': _redis_get(f'repricing:{theater}:snapshots') or [],
            'labeled': _redis_get(f'repricing:{theater}:labeled') or [],
            'seeds': (THEATER_CONFIG.get(theater) or {}).get('episodes') or [],
            'version': VERSION,
        })

    @app.route('/api/conflict-repricing/<theater>/label', methods=['POST'])
    def api_conflict_repricing_label(theater):
        # Operator tool: promote a snapshot into the labeled-episode pool that
        # match_episodes consults. Validates regime against the known taxonomy.
        if theater not in THEATER_CONFIG:
            return jsonify({'success': False, 'error': 'unknown theater',
                            'available': sorted(THEATER_CONFIG.keys())}), 404
        body = request.get_json(silent=True) or {}
        regime = body.get('regime')
        label = body.get('label')
        snap_id = body.get('id', 'latest')
        if regime not in _REGIME_PHRASE:
            return jsonify({'success': False,
                            'error': f'regime must be one of {sorted(_REGIME_PHRASE)}'}), 400
        if not label:
            return jsonify({'success': False, 'error': 'label is required'}), 400
        snaps = _redis_get(f'repricing:{theater}:snapshots') or []
        if not isinstance(snaps, list) or not snaps:
            return jsonify({'success': False, 'error': 'no snapshots to label'}), 404
        if snap_id == 'latest':
            snap = snaps[-1]
        else:
            snap = next((s for s in snaps if s.get('id') == snap_id), None)
        if not snap:
            return jsonify({'success': False,
                            'error': f'snapshot id not found: {snap_id}'}), 404
        episode = {
            'id': f"labeled_{snap['id']}",
            'date': body.get('date') or snap.get('date'),
            'regime': regime,
            'label': label,
            'signature': snap.get('signature', []),
        }
        labeled = _redis_get(f'repricing:{theater}:labeled')
        if not isinstance(labeled, list):
            labeled = []
        labeled.append(episode)
        _redis_set(f'repricing:{theater}:labeled', labeled[-200:])
        return jsonify({'success': True, 'labeled_episode': episode,
                        'total_labeled': len(labeled[-200:]), 'version': VERSION})

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
