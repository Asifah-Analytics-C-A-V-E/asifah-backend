"""
Asifah Analytics -- THE WEEK IN MARKETS: what the tape is afraid of  (ME backend)
v1.0.0  (Nov 21 2026)

WHY THIS EXISTS
  Week to Nov 20 2026: Nasdaq about -10% (worst week since March 2020), S&P 500
  -8.6% and into correction, VIX 36. Market Watch could not see it. Its
  fragility detector runs on MONTHLY data -- it measures how dry the forest is,
  and a week like this is lightning. Rachel (Nov 21): "we need to catch what
  happened and be able to talk about what it reflects (what kinds of fears it
  reflects) and what that could mean on a wider global scale."

WHAT IT DOES
  Every 6 hours it reads daily closes for ~30 instruments (US indices, chips,
  Nvidia, VIX and its 3-month curve, Treasury yields, the dollar, gold, silver,
  oil, bitcoin, junk vs Treasury bonds, and a dozen world indices) and asks the
  cross-asset question: over the last FIVE sessions, which fears does the
  pattern of moves fit? Each fear is a deterministic rule with its numbers:

    ai_unwind        chips / Nvidia fall much harder than the market
    panic            VIX 30+, or short-term fear above 3-month fear (curve inverted)
    forced_selling   stocks, gold and crypto fall TOGETHER: cash is being raised
    growth_scare     yields and oil fall with stocks: slowdown priced over inflation
    policy_squeeze   yields RISE with stocks falling: rates are the threat
    no_fed_put       traders expect the Fed to HIKE into the selloff (pm:latest)
    credit_stress    junk bonds fall against Treasuries: the scare reaches lending
    war_supply       oil jumps with stocks falling: a supply shock
    dollar_squeeze   dollar firm in a scare: tight money for dollar borrowers abroad
    global_contagion several world markets fall 3%+ on the week

  And the dogs that did NOT bark (credit, war supply) are said out loud, because
  "not yet in credit" is half the answer to "how bad is this?".

  Context lines (never scored, labelled): oil vs Asifah's Hormuz ship counts,
  the outage cluster vs traders' odds on a cyber attribution, NVIDIA leadership
  odds, the Fed. All read from Redis keys other modules already write.

DOCTRINE
  * Exposure, not instruction. Nothing here says buy, sell, hold or "check your
    401(k)". It says what the prices reflect and where else it can travel.
  * Unread, not calm: a missing instrument is listed as missing; a rule whose
    inputs are missing does not fire and is not reported as quiet.
  * Never scored. This is a reading of prices, beside the GPI, not in it.

COST
  $0. Yahoo's public chart endpoint (same route market_blackswan_detector uses),
  ~30 small GETs every 6h. Redis: 1 SET + 2 GETs per run; the route serves an
  in-process copy for 10 minutes to protect Upstash command volume.
  No Claude call anywhere in this file. ?refresh=true rebuilds (max once per 10 min).

ROUTES
  /api/market-week          the read
  /api/market-week/debug    per-instrument fetch health
"""

import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

__version__ = '1.2.0'   # Nov 22 2026 (b): ARCHIVE -- every day's fear pattern is banked (market:week:archive) + a week library (provisional: Nov 16-20 2026); 'echoes' = closest past weeks once the record has any. (1.1.0) Nov 22 2026: every instrument measured over the S&P's dates (bitcoin trades weekends); backup tickers (Israel, Saudi); credit explained in plain words with live 'signs it is changing'

REDIS_KEY = 'market:week:latest'
ARCHIVE_KEY = 'market:week:archive'      # v1.2.0: {as_of: compact fingerprint}
ARCHIVE_MAX = 520                         # ~2 years of trading days
ARCHIVE_TTL = 3 * 365 * 86400
ECHO_MIN = 0.5                            # Jaccard on fear sets
ECHO_GAP_DAYS = 14                        # never compare a week with itself

# v1.2.0 -- THE WEEK LIBRARY (scaffolding, Nov 22 2026). Hand-entered weeks
# whose fear pattern is worth comparing against. 'provisional' entries are shown
# as context but never offered as an echo until reviewed (calendar: Dec 5 2026).
# At review: add older reference weeks (Mar 2020, Aug 2015, Aug 2024 yen-carry
# unwind, Oct 2008...) by RE-COMPUTING their fear sets from Yahoo history with
# read_week(), never by typing fear ids from memory.
WEEK_LIBRARY = [
    {'id': 'ai_unwind_2026', 'as_of': '2026-11-20', 'window': 'Nov 13 to Nov 20 2026',
     'label': 'AI-leader unwind (Huang exit, SEC inquiry report)', 'provisional': True,
     'fear_ids': ['ai_unwind', 'dollar_squeeze', 'forced_selling', 'global_contagion',
                  'growth_scare', 'no_fed_put', 'panic'],
     'credit': 'held (junk bonds -0.8%, banks better than the index)',
     'equities_r5': -8.61},
]
REDIS_TTL = 30 * 3600
REFRESH_EVERY_SEC = 6 * 3600
MANUAL_REFRESH_MIN_GAP = 600
SERVE_CACHE_SEC = 600
SPACING_SEC = 0.35
SESSIONS = 5

YAHOO_HOSTS = ['https://query1.finance.yahoo.com', 'https://query2.finance.yahoo.com']
CHROME_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

# key: (yahoo ticker, display name, kind)   kind: pct | yield | level
TAPE = {
    'spx':    ('^GSPC',     'S&P 500',               'pct'),
    'ndx':    ('^IXIC',     'Nasdaq',                'pct'),
    'dji':    ('^DJI',      'Dow',                   'pct'),
    'rut':    ('^RUT',      'Russell 2000 (small firms)', 'pct'),
    'rsp':    ('RSP',       'Equal-weight S&P 500',  'pct'),
    'spy':    ('SPY',       'S&P 500 fund',          'pct'),
    'smh':    ('SMH',       'Chip stocks (SMH)',     'pct'),
    'nvda':   ('NVDA',      'NVIDIA',                'pct'),
    'xlf':    ('XLF',       'US banks & finance (XLF)', 'pct'),
    'vix':    ('^VIX',      'VIX (expected 30-day swings)', 'level'),
    'vix3m':  ('^VIX3M',    'VIX 3-month',           'level'),
    'tnx':    ('^TNX',      'US 10-year yield',      'yield'),
    'fvx':    ('^FVX',      'US 5-year yield',       'yield'),
    'dxy':    ('DX-Y.NYB',  'US dollar index',       'pct'),
    'gold':   ('GC=F',      'Gold',                  'pct'),
    'silver': ('SI=F',      'Silver',                'pct'),
    'wti':    ('CL=F',      'Oil (WTI)',             'pct'),
    'brent':  ('BZ=F',      'Oil (Brent)',           'pct'),
    'btc':    ('BTC-USD',   'Bitcoin',               'pct'),
    'hyg':    ('HYG',       'Junk bonds (HYG)',      'pct'),
    'ief':    ('IEF',       'Treasuries 7-10y (IEF)', 'pct'),
}
WORLD = {
    'n225':   ('^N225',     'Japan',       'apac'),
    'kospi':  ('^KS11',     'South Korea', 'apac'),
    'twii':   ('^TWII',     'Taiwan',      'apac'),
    'hsi':    ('^HSI',      'Hong Kong',   'apac'),
    'sse':    ('000001.SS', 'Shanghai',    'apac'),
    'sensex': ('^BSESN',    'India',       'apac'),
    'dax':    ('^GDAXI',    'Germany',     'europe'),
    'ftse':   ('^FTSE',     'UK',          'europe'),
    'cac':    ('^FCHI',     'France',      'europe'),
    # v1.1.0: Yahoo 404s '^TA35.TA' and returns no bars for '^TASI.SR' from Render;
    # a list = try in order. EIS / KSA are the US-listed country funds (in dollars).
    'ta35':   (['TA35.TA', '^TA35.TA', 'EIS'], 'Israel',  'me'),
    'tasi':   (['^TASI.SR', 'KSA'],           'Saudi Arabia', 'me'),
    'bvsp':   ('^BVSP',     'Brazil',      'wha'),
    'mxx':    ('^MXX',      'Mexico',      'wha'),
    'eem':    ('EEM',       'Emerging markets fund', 'em'),
}

# Thresholds (5-session moves, percent / basis points)
STOCKS_DOWN = -2.0
AI_GAP = -2.5            # chips vs S&P, points
NVDA_DROP = -10.0
VIX_PANIC = 30.0
CURVE_INVERT = 1.0       # VIX / VIX3M
HAVEN_DROP = -3.0        # gold
SPEC_DROP = -5.0         # bitcoin / silver
YIELD_MOVE_BP = 10.0
OIL_MOVE = 3.0
OIL_SHOCK = 5.0
CREDIT_GAP = -2.0        # HYG vs IEF, points
HY_DROP = -1.5           # junk bonds themselves must fall
DOLLAR_FIRM = 0.3
WORLD_DROP = -3.0
FED_HIKE_ODDS = 0.60

_MEM = {}
_state = {'thread': False, 'last_manual': 0.0, 'served': None, 'served_at': 0.0}
_lock = threading.Lock()


# ════════════════════════════════════════════════════════════════════════
# REDIS (Upstash REST)
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
# FETCH: daily closes, last ~month
# ════════════════════════════════════════════════════════════════════════
def _fetch_daily(ticker):
    """[(YYYY-MM-DD, close), ...] oldest first, or (None, reason)."""
    enc = requests.utils.quote(ticker, safe='')
    last_err = 'no answer'
    for host in YAHOO_HOSTS:
        try:
            r = requests.get('%s/v8/finance/chart/%s?range=1mo&interval=1d' % (host, enc),
                             headers={'User-Agent': CHROME_UA}, timeout=(6, 15))
            if r.status_code != 200:
                last_err = 'HTTP %s' % r.status_code
                continue
            res = ((r.json().get('chart') or {}).get('result') or [None])[0]
            if not res:
                last_err = 'empty chart'
                continue
            stamps = res.get('timestamp') or []
            closes = ((res.get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
            out = []
            for ts, c in zip(stamps, closes):
                if c is None:
                    continue
                d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
                if out and out[-1][0] == d:
                    out[-1] = (d, float(c))
                else:
                    out.append((d, float(c)))
            if len(out) >= 2:
                return out, None
            last_err = 'too few bars'
        except Exception as e:
            last_err = str(e)[:80]
    return None, last_err


def _yield_pct(v):
    """^TNX has been quoted both as 49.1 and as 4.91 over the years."""
    return v / 10.0 if v is not None and v > 20 else v


def _fetch_any(tickers):
    """Try each ticker in turn (v1.1.0). Returns (series, ticker_used, error)."""
    err = None
    for tk in (tickers if isinstance(tickers, (list, tuple)) else [tickers]):
        s, err = _fetch_daily(tk)
        if s:
            return s, tk, None
        time.sleep(SPACING_SEC)
    return None, None, err


def _at_or_before(series, d):
    best = None
    for i, (dd, _) in enumerate(series):
        if dd <= d:
            best = i
    return best


def _summarise(series, kind, ref=None):
    """ref = (base_date, as_of) of the S&P 500 (v1.1.0): every instrument is
    measured over the SAME dates, so bitcoin's weekend trading or a holiday in
    Tokyo does not quietly give it a different week."""
    if not series:
        return None
    if ref:
        i_last = _at_or_before(series, ref[1])
        i_base = _at_or_before(series, ref[0])
        if i_last is None:
            return None
        last_d, last = series[i_last]
        prev = series[i_last - 1][1] if i_last >= 1 else None
        base = series[i_base] if (i_base is not None and i_base < i_last) else None
    else:
        last_d, last = series[-1]
        prev = series[-2][1] if len(series) >= 2 else None
        base = series[-(SESSIONS + 1)] if len(series) >= SESSIONS + 1 else None
    rec = {'last': round(last, 4), 'as_of': last_d,
           'base_date': base[0] if base else None}
    if kind == 'yield':
        l, p = _yield_pct(last), _yield_pct(prev)
        b = _yield_pct(base[1]) if base else None
        rec.update(last=round(l, 3),
                   d1_bp=round((l - p) * 100, 1) if p is not None else None,
                   d5_bp=round((l - b) * 100, 1) if b is not None else None)
    else:
        rec.update(r1=round((last / prev - 1) * 100, 2) if prev else None,
                   r5=round((last / base[1] - 1) * 100, 2) if base else None)
    return rec


def _fetch_all():
    tape, world, missing = {}, {}, []
    raw = {}
    for k, (tk, name, kind) in TAPE.items():
        raw[k] = _fetch_any(tk)
        time.sleep(SPACING_SEC)
    ref_s = (raw.get('spx') or (None,))[0] or (raw.get('spy') or (None,))[0]
    ref = None
    if ref_s and len(ref_s) >= SESSIONS + 1:
        ref = (ref_s[-(SESSIONS + 1)][0], ref_s[-1][0])
    for k, (tk, name, kind) in TAPE.items():
        s, used, err = raw[k]
        rec = _summarise(s, kind, ref)
        if rec:
            rec.update(name=name, ticker=used, kind=kind)
            tape[k] = rec
        else:
            missing.append({'key': k, 'ticker': tk, 'why': err or 'no bar inside the S&P window'})
    for k, (tk, name, region) in WORLD.items():
        s, used, err = _fetch_any(tk)
        time.sleep(SPACING_SEC)
        rec = _summarise(s, 'pct', ref)
        if rec:
            rec.update(name=name, ticker=used, region=region)
            world[k] = rec
        else:
            missing.append({'key': k, 'ticker': tk, 'why': err or 'no bar inside the S&P window'})
    return tape, world, missing


# ════════════════════════════════════════════════════════════════════════
# READ: which fears does the week's pattern fit?
# ════════════════════════════════════════════════════════════════════════
def _v(tape, k, f='r5'):
    return (tape.get(k) or {}).get(f)


def _pc(x, signed=True):
    if x is None:
        return 'n/a'
    return ('%+.1f%%' if signed else '%.1f%%') % x


def _lc1(t):
    return t[:1].lower() + t[1:] if t else t


def _nice(d):
    try:
        return datetime.strptime(d, '%Y-%m-%d').strftime('%b %-d')
    except Exception:
        return d or '?'


def _pm_item(pm, iid):
    for it in (pm or {}).get('items') or []:
        if it.get('id') == iid:
            return it
    return None


CREDIT_EXPLAIN = (
    'Credit is the market where companies, banks and households BORROW. Stocks fall when investors lose '
    'hope about future profits: painful for savings, but the economy keeps running. The danger is when '
    'LENDERS get scared: companies cannot roll over their debts, hiring and investment stop, and defaults '
    'follow. That is how a market scare becomes a recession -- 2008 was a credit crisis; the 2022 tech '
    'slump mostly was not. "Not cracking yet" means lenders are still lending on normal terms: the scare '
    'is about what things are worth, not about whether they can be paid for.')


def _credit_watch(tape, eq):
    """The signs that would mean credit IS cracking, each with today's reading.
    Prices we measure, plus the news signs we cannot measure (said out loud)."""
    hyg, ief, xlf = _v(tape, 'hyg'), _v(tape, 'ief'), _v(tape, 'xlf')
    out = []
    if hyg is not None:
        out.append({'sign': 'Junk bonds themselves fall 1.5% or more in a week',
                    'now': 'junk bonds %s' % _pc(hyg), 'tripped': hyg <= HY_DROP})
    if xlf is not None and eq is not None:
        out.append({'sign': 'Bank and finance shares fall 2+ points harder than the market',
                    'now': 'banks %s vs S&P %s' % (_pc(xlf), _pc(eq)), 'tripped': (xlf - eq) <= -2.0})
    out.append({'sign': 'In the news: company bond sales pulled, private-credit funds limiting withdrawals, '
                        'a lender or bank needing rescue',
                'now': 'not measured here -- watch the reporting', 'tripped': None})
    return out


ORDER = ['ai_unwind', 'war_supply', 'panic', 'forced_selling', 'credit_stress', 'growth_scare',
         'policy_squeeze', 'no_fed_put', 'dollar_squeeze', 'global_contagion']
CLAUSE = {
    'ai_unwind': 'the AI leaders fell hardest',
    'war_supply': 'oil priced a supply shock',
    'panic': 'near-term fear spiked',
    'forced_selling': 'investors sold even gold and crypto to raise cash',
    'credit_stress': 'junk debt started to crack',
    'growth_scare': 'bonds and oil priced a slowdown',
    'policy_squeeze': 'rising yields offered no cushion',
    'no_fed_put': 'the Fed is expected to hike rather than rescue',
    'dollar_squeeze': 'money ran to the dollar',
    'global_contagion': 'the selling went global',
}


def read_week(tape, world, pm=None, transits=None):
    """Pure function: prices in, reading out. Tested offline."""
    eq = _v(tape, 'spx') if _v(tape, 'spx') is not None else _v(tape, 'spy')
    fears, not_yet, context = [], [], []
    if eq is None:
        return {'band': 'unread', 'band_words': 'Unread, not calm',
                'headline': 'The week in markets is unread: the S&P 500 could not be read.',
                'fears': [], 'not_yet': [], 'context': [], 'world': []}
    down = eq <= STOCKS_DOWN
    ndx, smh, nvda = _v(tape, 'ndx'), _v(tape, 'smh'), _v(tape, 'nvda')

    def add(fid, name, strength, reflects, evidence, global_):
        fears.append({'id': fid, 'name': name, 'strength': strength, 'reflects': reflects,
                      'evidence': evidence, 'global': global_})

    # 1. AI / concentration unwind
    gap = (smh - eq) if (smh is not None) else None
    if down and ((gap is not None and gap <= AI_GAP) or (nvda is not None and nvda <= NVDA_DROP)):
        ev = []
        if smh is not None:
            ev.append('chip stocks %s against the S&P 500\'s %s' % (_pc(smh), _pc(eq)))
        if nvda is not None:
            ev.append('NVIDIA %s' % _pc(nvda))
        rsp, spy = _v(tape, 'rsp'), _v(tape, 'spy')
        if rsp is not None and spy is not None and rsp - spy >= 1.0:
            ev.append('the average S&P stock (equal-weight %s) held up better than the index (%s), '
                      'so the selling is aimed at the giants' % (_pc(rsp), _pc(spy)))
        add('ai_unwind', 'The AI trade is being repriced',
            3 if (nvda is not None and nvda <= -15) or (gap is not None and gap <= -6) else 2,
            'Doubt that the money poured into AI will pay back on the timeline prices assumed -- and the '
            'discovery that a market this concentrated in a few AI leaders is only as steady as they are.',
            '; '.join(ev) + '.',
            'The AI build-out is a global supply chain: chips from Taiwan and South Korea, memory from Korea, '
            'data-centre money from the Gulf and Asia. A repricing of the US leaders travels down that chain.')

    # 2. Acute fear
    vix, vix3 = _v(tape, 'vix', 'last'), _v(tape, 'vix3m', 'last')
    ratio = round(vix / vix3, 2) if (vix and vix3) else None
    if vix is not None and (vix >= VIX_PANIC or (ratio is not None and ratio >= CURVE_INVERT)):
        ev = 'VIX at %.1f (%s on the week)' % (vix, _pc(_v(tape, 'vix')))
        if ratio is not None:
            ev += '; next-month fear %s three-month fear (ratio %.2f)' % (
                'above' if ratio >= 1 else 'below', ratio)
        add('panic', 'Fear of the next few days, not the next few months',
            3 if (vix >= 35 or (ratio or 0) >= 1.1) else 2,
            'When near-term fear outruns longer-term fear the curve inverts: investors are paying most to '
            'protect against what happens next week. Historically that marks acute stress, which can '
            'also mean the selling is crowded.',
            ev + '.',
            'Volatility is exported: global funds cut risk everywhere at once when US volatility spikes, '
            'whatever the local news.')

    # 3. Forced selling / dash for cash
    gold, silver, btc = _v(tape, 'gold'), _v(tape, 'silver'), _v(tape, 'btc')
    if down and gold is not None and gold <= HAVEN_DROP and (
            (btc is not None and btc <= SPEC_DROP) or (silver is not None and silver <= SPEC_DROP)):
        ev = 'gold %s, silver %s, bitcoin %s, alongside stocks %s' % (_pc(gold), _pc(silver), _pc(btc), _pc(eq))
        add('forced_selling', 'Investors raising cash: selling what they can, not what they want',
            3 if gold <= -6 else 2,
            'Havens (gold) and speculation (crypto) normally move apart. When they fall WITH stocks, '
            'investors are raising cash -- often to meet margin calls -- which is a sign of leverage being '
            'unwound, not of a view on gold or bitcoin.',
            ev + '.',
            'Forced selling crosses borders: funds sell abroad to cover losses at home, which is how a US '
            'scare becomes an emerging-market one.')

    # 4 / 5. Rates: growth scare or policy squeeze
    y10 = _v(tape, 'tnx', 'd5_bp')
    oil = _v(tape, 'wti') if _v(tape, 'wti') is not None else _v(tape, 'brent')
    if down and y10 is not None and y10 <= -YIELD_MOVE_BP and (oil is None or oil <= -OIL_MOVE):
        add('growth_scare', 'A slowdown priced ahead of inflation',
            2,
            'Bond yields and oil falling with stocks is the market voting for weaker growth: money moves '
            'into Treasuries and out of anything that needs a strong economy.',
            'US 10-year yield %+.0f bp to %.2f%%; oil %s.' % (y10, _v(tape, 'tnx', 'last'), _pc(oil)),
            'Falling oil in a war year is a demand verdict: it eases import bills (Egypt, India, Pakistan) '
            'and squeezes producer budgets (the Gulf, Nigeria, Russia).')
    elif down and y10 is not None and y10 >= YIELD_MOVE_BP:
        add('policy_squeeze', 'Rates are the threat',
            2,
            'Yields rising while stocks fall means the market fears inflation and tighter money more than '
            'a slowdown: the usual cushion (bonds rallying) is missing.',
            'US 10-year yield %+.0f bp to %.2f%%.' % (y10, _v(tape, 'tnx', 'last')),
            'Higher US yields pull money out of emerging markets and raise the cost of every dollar loan '
            'abroad.')

    # 6. No Fed put
    fed = _pm_item(pm, 'fed_next')
    fh = (fed or {}).get('headline') or {}
    if down and fh.get('prob') is not None and 'hike' in str(fh.get('option') or '').lower() \
            and fh['prob'] >= FED_HIKE_ODDS:
        add('no_fed_put', 'No rescue from the Fed',
            2,
            'Investors are used to the Fed easing when markets fall. This time traders expect a rate HIKE '
            'at the next meeting: the selloff is happening with the central bank leaning against it.',
            'Traders on Kalshi price "%s" at the next Fed decision at %s.' % (fh.get('option'), fh.get('odds')),
            'With the Fed tightening, the US is not exporting relief: dollar borrowers worldwide keep paying '
            'more.')

    # 7. Credit -- fires, or is reported as the dog that did not bark
    hyg, ief = _v(tape, 'hyg'), _v(tape, 'ief')
    credit_watch = _credit_watch(tape, eq)
    if hyg is not None and ief is not None:
        cg = round(hyg - ief, 2)
        # both: a Treasury rally alone (flight to safety) widens the gap without any lender pulling back
        if down and cg <= CREDIT_GAP and hyg <= HY_DROP:
            add('credit_stress', 'The scare is reaching lending',
                3,
                'Junk bonds falling against Treasuries means lenders are demanding more to fund weaker '
                'companies. That is how a stock-market scare becomes a funding problem for the real economy.',
                'junk bonds %s vs Treasuries %s (gap %+.1f points).' % (_pc(hyg), _pc(ief), cg),
                'Credit stress travels through banks and private lenders worldwide; watch European banks and '
                'emerging-market dollar bonds next.')
        elif down:
            not_yet.append({'id': 'credit_stress', 'name': 'Not (yet) a credit scare',
                            'text': 'Junk bonds %s while Treasuries %s: so far this is a repricing of hopes, not '
                                    'a crisis of funding. This is the line to watch -- if lenders start '
                                    'pulling back, the story changes.' % (_pc(hyg), _pc(ief)),
                            'explain': CREDIT_EXPLAIN, 'watch': credit_watch})

    # 8. War-supply shock -- or its absence
    if down and oil is not None and oil >= OIL_SHOCK:
        add('war_supply', 'A supply shock in energy',
            2,
            'Oil jumping while stocks fall is a supply fear: the market is pricing barrels that may not arrive.',
            'oil %s.' % _pc(oil),
            'An energy shock hits importers hardest -- Europe, South Asia, East Asia -- and feeds inflation '
            'everywhere.')

    # 9. Dollar
    dxy = _v(tape, 'dxy')
    if down and dxy is not None and dxy >= DOLLAR_FIRM:
        add('dollar_squeeze', 'The world still runs to the dollar',
            1,
            'Even in a US-made scare, money ran TO the dollar, not away from it.',
            'dollar index %s.' % _pc(dxy),
            'A firm dollar tightens money for countries that borrow in dollars. On Asifah\'s stability pages '
            'that bites first in places like Egypt, Pakistan, Argentina, Nigeria and Kenya.')

    # 10. World board
    wb = sorted([{'key': k, 'name': w['name'], 'region': w['region'], 'r5': w.get('r5')}
                 for k, w in world.items() if w.get('r5') is not None], key=lambda x: x['r5'])
    hit = [w for w in wb if w['r5'] <= WORLD_DROP]
    if down and len(hit) >= 3:
        chip = [w['name'] for w in hit if w['key'] in ('twii', 'kospi')]
        add('global_contagion', 'It did not stay in America',
            2 if len(hit) < 6 else 3,
            'Several world markets fell hard in the same week: the fear is being shared, not watched from '
            'a distance.',
            '%d of %d world markets fell 3%%+; hardest hit: %s.' % (
                len(hit), len(wb), ', '.join('%s %s' % (w['name'], _pc(w['r5'])) for w in hit[:4])),
            ('The chip-making markets (%s) carry the AI story directly. ' % ', '.join(chip) if chip else '')
            + 'When the world sells together, there are fewer places for capital to hide.')
    elif down and wb:
        held = [w for w in wb if w['r5'] > -1.0]
        if held:
            not_yet.append({'id': 'global_contagion', 'name': 'Largely a US story so far',
                            'text': 'Markets that held up: %s.' % ', '.join(
                                '%s %s' % (w['name'], _pc(w['r5'])) for w in held[-4:])})

    # ── CONTEXT (labelled, never part of the band) ──
    hz = ((transits or {}).get('chokepoints') or {}).get('hormuz') or {}
    if oil is not None and oil <= -OIL_MOVE and hz.get('band') not in (None, 'normal'):
        context.append({'kind': 'asifah', 'text':
                        'Oil fell %.1f%% this week even though Asifah\'s ship counts read the Strait of Hormuz at '
                        '%s of pre-war traffic (%s). Right now the market fears losing demand more than '
                        'losing supply.' % (abs(oil), ('%s%%' % hz.get('ratio_pct')) if hz.get('ratio_pct') is not None else 'a fraction',
                                            hz.get('band_words') or hz.get('band'))})
    hack, cause = _pm_item(pm, 'faa_hack'), _pm_item(pm, 'faa_cause')
    if hack and (hack.get('headline') or {}).get('odds'):
        t = ('The outage cluster (FAA ground stop Nov 13, banks, cloud and payment services): officials say '
             'there is no evidence of a cyberattack, and traders give an official hack attribution by Nov 30 '
             'only %s.' % hack['headline']['odds'])
        if cause and (cause.get('headline') or {}).get('option'):
            t += ' Their leading explanation for the FAA stop: "%s".' % cause['headline']['option'].lower()
        t += (' The fear in prices this week is the AI trade and the Fed, not the plumbing -- but repeated '
              'outages are themselves a reminder of how concentrated the digital system is.')
        context.append({'kind': 'markets', 'text': t})
    hr = _pm_item(pm, 'nvidia_huang_return')
    lc = _pm_item(pm, 'largest_company')
    if hr and (hr.get('headline') or {}).get('odds'):
        t = ('NVIDIA lost its founder-CEO on Nov 12; traders give his return by year-end %s.'
             % hr['headline']['odds'])
        if lc and (lc.get('headline') or {}).get('option'):
            t += ' For the world\'s largest company at year-end they now favour %s (%s).' % (
                lc['headline']['option'], lc['headline'].get('odds'))
        context.append({'kind': 'markets', 'text': t})

    # ── BAND ──
    strength = sum(f['strength'] for f in fears)
    ids = {f['id'] for f in fears}
    if 'panic' in ids and (eq <= -7 or 'forced_selling' in ids or 'credit_stress' in ids):
        band, words = 'acute', 'Acute stress'
    elif eq <= -4 or strength >= 5:
        band, words = 'stressed', 'Stressed'
    elif down or fears:
        band, words = 'uneasy', 'Uneasy'
    else:
        band, words = 'calm', 'Calm week'

    top = sorted(fears, key=lambda f: -f['strength'])
    ref = tape.get('spx') or tape.get('spy') or {}
    span = '%s to %s' % (_nice(ref.get('base_date')), _nice(ref.get('as_of')))
    moves = 'S&P 500 %s' % _pc(eq)
    if ndx is not None:
        moves += ', Nasdaq %s' % _pc(ndx)
    if fears:
        headline = '%s this week (%s). The tape is afraid of: %s.' % (
            moves, span, '; '.join(_lc1(f['name']) for f in top[:3]))
    elif down:
        headline = '%s this week (%s), without a clear cross-market fear pattern.' % (moves, span)
    else:
        headline = '%s this week (%s): no cross-market fear pattern.' % (moves, span)
    # So What: one deterministic sentence that strings the fears into a story,
    # then what is NOT happening -- the half of "how bad is this?" people skip.
    clauses = [CLAUSE[f['id']] for f in sorted(top, key=lambda f: ORDER.index(f['id']) if f['id'] in ORDER else 99)
               if f['id'] in CLAUSE]
    summary = ''
    if clauses:
        summary = 'In one line: %s.' % (clauses[0] if len(clauses) == 1 else
                                        ', '.join(clauses[:-1]) + ', and ' + clauses[-1])
        summary = summary[:13] + summary[13].upper() + summary[14:]
    nid = {n['id'] for n in not_yet}
    if 'credit_stress' in nid:
        summary += (' Credit has not cracked: for now this is a crisis of confidence in the story, not of '
                    'funding.')
    elif 'credit_stress' in ids:
        summary += ' Credit is cracking too, which is what turns a market scare into an economic one.'
    title = '%s this week (%s)' % (moves, span)
    return {'band': band, 'band_words': words, 'headline': headline, 'title': title, 'summary': summary,
            'credit_watch': credit_watch,
            'window': span, 'equities_r5': eq, 'fears': top, 'not_yet': not_yet,
            'context': context, 'world': wb,
            'fear_ids': sorted(ids)}


# ════════════════════════════════════════════════════════════════════════
# BUILD / SERVE
# ════════════════════════════════════════════════════════════════════════
def build(reason='scheduled'):
    if not _lock.acquire(blocking=False):
        return {'status': 'already_running'}
    t0 = time.time()
    try:
        tape, world, missing = _fetch_all()
        pm = _rget('pm:latest')
        transits = _rget('chokepoint:transits:v1')
        read = read_week(tape, world, pm, transits)
        payload = dict(read)
        payload.update({
            'version': __version__, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'reason': reason,
            'tape': tape,
            'label': ('A reading of prices over the last five trading sessions: which fears the pattern of '
                      'moves fits. Context beside the score, never part of it.'),
            'disclaimer': ('Exposure, not instruction: this describes what prices reflect and where it can '
                           'travel. It is not investment advice and says nothing about what anyone should buy, '
                           'sell or hold.'),
            'health': {'fetched': len(tape) + len(world), 'expected': len(TAPE) + len(WORLD),
                       'missing': missing, 'seconds': round(time.time() - t0, 1)},
        })
        if tape.get('spx') or tape.get('spy'):
            payload['echoes'] = _archive_and_echo(payload)
            _rset(REDIS_KEY, payload, REDIS_TTL)
        _state['served'], _state['served_at'] = payload, time.time()
        print('[Market week] built: %s, %d fears, %d/%d instruments in %.0fs'
              % (payload['band'], len(payload['fears']), payload['health']['fetched'],
                 payload['health']['expected'], payload['health']['seconds']))
        return payload
    finally:
        _lock.release()


def _jac(a, b):
    a, b = set(a or []), set(b or [])
    return len(a & b) / len(a | b) if (a or b) else 0.0


def _archive_and_echo(payload):
    """Bank today's fingerprint (one GET + at most one SET per build) and
    return the closest past weeks. Empty until the record has history: an
    empty list means 'no record yet', never 'nothing like this has happened'."""
    as_of = (payload.get('tape', {}).get('spx') or payload.get('tape', {}).get('spy') or {}).get('as_of')
    arch = _rget(ARCHIVE_KEY) or {}
    if not isinstance(arch, dict):
        arch = {}
    fp = {'window': payload.get('window'), 'band': payload.get('band'),
          'fear_ids': payload.get('fear_ids') or [], 'equities_r5': payload.get('equities_r5'),
          'credit_tripped': 'credit_stress' in (payload.get('fear_ids') or [])}
    if as_of and arch.get(as_of) != fp:
        arch[as_of] = fp
        if len(arch) > ARCHIVE_MAX:
            for k in sorted(arch)[:len(arch) - ARCHIVE_MAX]:
                arch.pop(k, None)
        _rset(ARCHIVE_KEY, arch, ARCHIVE_TTL)
    cur = payload.get('fear_ids') or []
    if not cur or not as_of:
        return []
    try:
        cut = datetime.strptime(as_of, '%Y-%m-%d').toordinal() - ECHO_GAP_DAYS
    except Exception:
        return []
    cands = []
    for d, f in arch.items():
        try:
            if datetime.strptime(d, '%Y-%m-%d').toordinal() > cut:
                continue
        except Exception:
            continue
        cands.append({'as_of': d, 'label': 'Week to %s' % _nice(d), 'window': f.get('window'),
                      'fear_ids': f.get('fear_ids'), 'equities_r5': f.get('equities_r5'),
                      'source': 'archive', 'j': _jac(cur, f.get('fear_ids'))})
    for w in WEEK_LIBRARY:
        if w.get('provisional') or w['as_of'] == as_of:
            continue
        cands.append(dict(w, source='library', j=_jac(cur, w.get('fear_ids'))))
    cands = [c for c in cands if c['j'] >= ECHO_MIN]
    cands.sort(key=lambda c: -c['j'])
    # one per stretch: keep the best day of each run of near-identical days
    out = []
    for c in cands:
        if any(abs(datetime.strptime(c['as_of'], '%Y-%m-%d').toordinal() -
                   datetime.strptime(o['as_of'], '%Y-%m-%d').toordinal()) < 7 for o in out):
            continue
        c['similarity_pct'] = round(c.pop('j') * 100)
        c['shared'] = sorted(set(cur) & set(c.get('fear_ids') or []))
        out.append(c)
        if len(out) >= 2:
            break
    return out


def latest():
    if _state['served'] and time.time() - _state['served_at'] < SERVE_CACHE_SEC:
        return _state['served']
    p = _rget(REDIS_KEY)
    if p:
        _state['served'], _state['served_at'] = p, time.time()
    return p


def _age_sec(p):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(p['generated_at'])).total_seconds()
    except Exception:
        return None


def _loop():
    time.sleep(150)
    try:
        from instance_lock import my_turn
    except Exception:
        my_turn = lambda job: True     # noqa: E731
    while True:
        try:
            if my_turn('market_week'):
                age = _age_sec(latest() or {})
                if age is None or age >= REFRESH_EVERY_SEC - 300:
                    build('scheduled')
        except Exception as e:
            print('[Market week] scheduled build failed (non-fatal): %s' % str(e)[:200])
        time.sleep(30 * 60)


def register_market_week_routes(app, start=True):
    from flask import jsonify, request

    def _maybe_refresh():
        if request.args.get('refresh', 'false').lower() != 'true':
            return None
        if time.time() - _state['last_manual'] < MANUAL_REFRESH_MIN_GAP:
            return 'refresh ignored: last manual refresh was under 10 minutes ago'
        _state['last_manual'] = time.time()
        build('manual')
        return 'refreshed'

    @app.route('/api/market-week')
    def _mw():
        note = _maybe_refresh()
        p = latest()
        if not p:
            return jsonify({'available': False,
                            'note': 'First read not built yet (runs ~3 minutes after deploy).'}), 200
        out = {k: v for k, v in p.items() if k != 'tape'}
        out['tape'] = p.get('tape')
        out['available'] = True
        out['age_minutes'] = round((_age_sec(p) or 0) / 60)
        if note:
            out['refresh'] = note
        return jsonify(out)

    @app.route('/api/market-week/debug')
    def _mw_debug():
        p = latest() or {}
        return jsonify({'version': __version__, 'generated_at': p.get('generated_at'),
                        'band': p.get('band'), 'fear_ids': p.get('fear_ids'),
                        'health': p.get('health'),
                        'tape': {k: {kk: v.get(kk) for kk in ('name', 'last', 'r1', 'r5', 'd5_bp', 'as_of')}
                                 for k, v in (p.get('tape') or {}).items()}})

    if start and not _state['thread']:
        _state['thread'] = True
        threading.Thread(target=_loop, daemon=True, name='market-week').start()
    print('[Market week] routes registered: /api/market-week, /debug (v%s, %d instruments)'
          % (__version__, len(TAPE) + len(WORLD)))
