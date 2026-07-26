"""
market_blackswan_detector.py -- Black Swan #2: Market Fragility Convergence
v1.0.0 -- June 12, 2026 -- ME backend (home of GPI + the convergence layer)

THE CONCEPT
-----------
True black swans are by definition undetectable -- you cannot predict the
lightning. What you CAN measure is how dry the forest is. This module
measures ENDOGENOUS FINANCIAL FRAGILITY: the convergence of conditions
that historically preceded bubble bursts and major drawdowns (1999-2000
dot-com, 2007-2008 GFC, 2021 everything-bubble). Exogenous shocks
(9/11, COVID) carry no reliable market pre-signal -- they are included
in the episode library as NULL CASES, and the platform's GPI kinetic
axis is the lightning watch. Fragility x active fuse = the compound
read, surfaced at GPI altitude.

THE SIX BLACK SWAN COMPONENTS (Iran Strike Window pattern, May 22 2026)
-----------------------------------------------------------------------
1. Signal classes with severity scaling  -> 10 market features (below)
2. Calendar/timing multipliers           -> rate-cycle pause, drawdown
                                            absence (amplifiers ONLY)
3. Composite scoring with severity bands -> normal/elevated/high/critical
4. Pattern memory + similarity matching  -> SEEDED from ~100 years of
                                            data; episode library is
                                            computed, not asserted
5. Convergence framing + disclaimer      -> fragility indicator, NOT a
                                            forecast, NOT investment
                                            advice
6. Rollup integration                    -> market-watch.html banner ->
                                            GPI economic axis

THE TEN FEATURE CLASSES (each: one feature, one named precedent)
----------------------------------------------------------------
F1  valuation_stretch    CAPE above 90th pct of trailing 30y (1929/1999/2021)
F2  parabolic_momentum   SPX 24m return z>1.5 (1999 blow-off)
F3  concentration        IXIC/GSPC ratio 24m z>1.5 (dot-com tech share)
F4  breadth_divergence   SPX near highs while RSP/SPY under 12m mean
                         (narrow leadership: 1999, 2007, 2021; data 2004+)
F5  vol_complacency      VIX 6m mean in bottom quintile (2006-07, 2017)
F6  curve_inversion      10y-2y inverted within 12m (1999/2006/2022 -- FRED,
                         Yahoo TNX-IRX fallback)
F7  leader_rollover      boom-leader ratio -10% off its high while SPX
                         within 5% of its high (financials 2007,
                         homebuilder analog; tech 2000)
F8  credit_stress        BAA-10Y spread widening >40bps over 6m (2007-08;
                         FRED, absent = feature unavailable)
F9  thematic_fever       AI basket SMH/SPY 24m z>2 (the data-center /
                         AI-capex thermometer; vendor-financing echo of
                         Lucent 1999; data 2000+)
F10 global_sync          3+ of Nikkei/DAX/FTSE/Sensex within 5% of 24m
                         highs (synchronized late-cycle: 2007, 2021)

DATA SOURCES (free; data-honesty fields in every payload)
---------------------------------------------------------
- Yahoo Finance chart API, monthly closes, range=max
  (query1 -> query2 failover + Chrome UA, platform canon)
- FRED (api.stlouisfed.org) via FRED_API_KEY env var: T10Y2Y, BAA10Y,
  FEDFUNDS. Module degrades gracefully when key absent.
- Shiller CAPE: embedded ANNUAL anchors (Robert Shiller, Yale,
  online data ie_data), linearly interpolated to monthly; current
  month approximated by drifting the latest anchor with SPX price
  change. Honest approximation, flagged in payload; anchors are a
  10-line dict to update quarterly.

ENDPOINTS
---------
GET /api/market-blackswan              current convergence read (12h cache)
GET /api/market-blackswan?force=true   force fresh scan
GET /api/market-blackswan/backtest     full monthly timeline 1992->present,
                                       episode lead-times computed from
                                       data, control-month verification
                                       (THE RECEIPTS -- run after deploy;
                                       60-120s first run, then 7d cache)
GET /api/market-blackswan/debug        source reachability + cache state

DISCLAIMER (ships in every payload, every altitude, non-removable)
------------------------------------------------------------------
This composite is a FRAGILITY indicator, NOT a market forecast and NOT
investment advice. Convergence with historical pre-drawdown patterns
describes present conditions; it does not predict whether or when a
drawdown will occur. Historical lead times are descriptive of past
episodes only.
"""

import os
import json
import math
import statistics
import requests
from datetime import datetime, timezone
from market_prose import market_disclaimer, analog_tail

VERSION = '1.2.0'   # Jul 26 2026: +5 non-US episodes, so_what layer, global_majors
CACHE_KEY = 'blackswan:market:latest'
BACKTEST_KEY = 'blackswan:market:backtest'
LIBRARY_KEY = 'blackswan:market:library'
SNAPSHOT_KEY = 'blackswan:market:snapshots'
GPI_BUNDLE_KEY = 'blackswan:market:gpi'   # compact read for the GPI fragility detector
CACHE_TTL_HOURS = 12
BACKTEST_TTL_HOURS = 168  # 7 days

DISCLAIMER = market_disclaimer(
    subject="endogenous market fragility",
    forecast_of=" of whether or when a drawdown occurs",
    coda=("Convergence with historical pre-drawdown patterns describes present "
          "conditions, not an outcome. " + analog_tail()))

# ------------------------------------------------------------
# Redis REST helpers (Upstash) -- both env-name conventions
# ------------------------------------------------------------
REDIS_URL = (os.environ.get('UPSTASH_REDIS_REST_URL')
             or os.environ.get('UPSTASH_REDIS_URL', '')).rstrip('/')
REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_REST_TOKEN')
               or os.environ.get('UPSTASH_REDIS_TOKEN', ''))
FRED_API_KEY = os.environ.get('FRED_API_KEY', '')

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
        print(f'[Market BlackSwan] Redis GET failed ({e}); memory fallback')
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
        print(f'[Market BlackSwan] Redis SET failed ({e}); memory only')


# ------------------------------------------------------------
# Shiller CAPE -- embedded annual anchors (mid-year values),
# linearly interpolated to monthly. Update quarterly: one dict.
# Source: Robert Shiller, Yale, online data (ie_data).
# ------------------------------------------------------------
CAPE_ANCHORS = {
    1985: 10.0, 1986: 13.0, 1987: 16.5, 1988: 14.0, 1989: 15.5,
    1990: 16.5, 1991: 17.5, 1992: 19.5, 1993: 20.5, 1994: 20.0,
    1995: 22.0, 1996: 25.0, 1997: 30.0, 1998: 36.0, 1999: 41.0,
    2000: 43.0, 2001: 32.0, 2002: 26.0, 2003: 24.0, 2004: 26.5,
    2005: 26.5, 2006: 26.5, 2007: 27.0, 2008: 22.0, 2009: 16.5,
    2010: 21.0, 2011: 22.5, 2012: 21.5, 2013: 23.5, 2014: 25.5,
    2015: 26.5, 2016: 26.0, 2017: 30.0, 2018: 32.5, 2019: 29.5,
    2020: 29.0, 2021: 37.5, 2022: 31.0, 2023: 30.0, 2024: 34.5,
    2025: 37.5,
}
CAPE_DATA_AS_OF = '2025 annual anchors (Shiller/Yale); current month '\
                  'approximated by SPX drift from the latest anchor'


def _cape_series(months, spx_by_month):
    """Monthly CAPE via linear interpolation of annual anchors; months
    beyond the last anchor drift with SPX price (earnings held flat --
    an honest approximation, flagged in the payload)."""
    years = sorted(CAPE_ANCHORS.keys())
    last_anchor_year = years[-1]
    anchor_month = f'{last_anchor_year}-07'
    out = {}
    for m in months:
        y = int(m[:4])
        mo = int(m[5:7])
        if y < years[0]:
            out[m] = None
            continue
        if m <= anchor_month:
            # interpolate between mid-year anchors
            frac = (mo - 7) / 12.0
            if mo >= 7:
                y0, y1 = y, min(y + 1, last_anchor_year)
            else:
                y0, y1 = max(y - 1, years[0]), y
                frac = (mo + 5) / 12.0
            c0 = CAPE_ANCHORS.get(y0)
            c1 = CAPE_ANCHORS.get(y1, c0)
            if c0 is None:
                out[m] = None
            else:
                out[m] = round(c0 + (c1 - c0) * max(0.0, min(1.0, frac)), 2)
        else:
            base_cape = CAPE_ANCHORS[last_anchor_year]
            base_px = spx_by_month.get(anchor_month)
            px = spx_by_month.get(m)
            if base_px and px:
                out[m] = round(base_cape * (px / base_px), 2)
            else:
                out[m] = base_cape
    return out


# ------------------------------------------------------------
# Yahoo monthly history (range=max) -- canonical failover + UA
# ------------------------------------------------------------
YAHOO_HOSTS = ['https://query1.finance.yahoo.com',
               'https://query2.finance.yahoo.com']
CHROME_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
             'AppleWebKit/537.36 (KHTML, like Gecko) '
             'Chrome/124.0.0.0 Safari/537.36')

TICKERS = {
    'spx': '^GSPC', 'ixic': '^IXIC', 'vix': '^VIX',
    'tnx': '^TNX', 'irx': '^IRX',
    'rsp': 'RSP', 'spy': 'SPY', 'smh': 'SMH', 'xlf': 'XLF',
    'n225': '^N225', 'dax': '^GDAXI', 'ftse': '^FTSE', 'sensex': '^BSESN',
}


def _fetch_yahoo_monthly(ticker):
    """Returns {'YYYY-MM': close} or None.
    v1.0.1: fetched in THREE bounded period1/period2 chunks. range=max on
    century-long series silently coerces 1mo bars to QUARTERLY (caught by
    the first live backtest, Jun 12 2026: 138 months where ~414 belonged).
    Bounded chunks of <=25 years each guarantee true monthly granularity."""
    encoded = requests.utils.quote(ticker, safe='')
    now = int(datetime.now(timezone.utc).timestamp())
    chunks = [(0, 631152000),            # 1970-01 .. 1990-01
              (631152000, 1104537600),   # 1990-01 .. 2005-01
              (1104537600, now + 86400)] # 2005-01 .. present
    merged = {}
    for p1, p2 in chunks:
        for host in YAHOO_HOSTS:
            try:
                url = (f'{host}/v8/finance/chart/{encoded}'
                       f'?period1={p1}&period2={p2}&interval=1mo')
                r = requests.get(url, headers={'User-Agent': CHROME_UA},
                                 timeout=(6, 25))
                if r.status_code != 200:
                    continue
                result = (r.json().get('chart') or {}).get('result')
                if not result:
                    continue
                res = result[0]
                stamps = res.get('timestamp') or []
                closes = ((res.get('indicators') or {}).get('quote')
                          or [{}])[0].get('close') or []
                for ts, c in zip(stamps, closes):
                    if c is None:
                        continue
                    d = datetime.fromtimestamp(ts, tz=timezone.utc)
                    merged[f'{d.year:04d}-{d.month:02d}'] = float(c)
                break  # chunk done; next chunk
            except Exception as e:
                print(f'[Market BlackSwan] Yahoo {host} {ticker} failed: {e}')
                continue
    return merged or None


# ------------------------------------------------------------
# FRED monthly series (graceful when key absent)
# ------------------------------------------------------------
FRED_SERIES = {'t10y2y': 'T10Y2Y', 'baa10y': 'BAA10Y', 'fedfunds': 'FEDFUNDS'}


def _fetch_fred_monthly(series_id):
    if not FRED_API_KEY:
        return None
    try:
        url = ('https://api.stlouisfed.org/fred/series/observations'
               f'?series_id={series_id}&api_key={FRED_API_KEY}'
               '&file_type=json&frequency=m&observation_start=1962-01-01')
        r = requests.get(url, timeout=(6, 25))
        if r.status_code != 200:
            return None
        out = {}
        for ob in r.json().get('observations', []):
            v = ob.get('value', '.')
            if v in ('.', '', None):
                continue
            out[ob['date'][:7]] = float(v)
        return out or None
    except Exception as e:
        print(f'[Market BlackSwan] FRED {series_id} failed: {e}')
        return None


def _gather_all_series():
    """Fetch everything once; returns dict of {name: {month: value}}."""
    data = {}
    for name, tk in TICKERS.items():
        data[name] = _fetch_yahoo_monthly(tk)
    for name, sid in FRED_SERIES.items():
        data[name] = _fetch_fred_monthly(sid)
    if data.get('spx'):
        months = sorted(data['spx'].keys())
        data['cape'] = _cape_series(months, data['spx'])
    else:
        data['cape'] = None
    return data


# ------------------------------------------------------------
# Pure-python series math (no numpy dependency on the backend)
# ------------------------------------------------------------
def _months_range(series):
    return sorted(series.keys())


def _month_shift(m, delta):
    y, mo = int(m[:4]), int(m[5:7])
    total = y * 12 + (mo - 1) + delta
    return f'{total // 12:04d}-{(total % 12) + 1:02d}'


def _trailing_return(series, m, months_back):
    a = series.get(_month_shift(m, -months_back))
    b = series.get(m)
    if not a or not b:
        return None
    return (b - a) / a * 100.0


def _trailing_values(series, m, months_back):
    out = []
    for i in range(months_back, -1, -1):
        v = series.get(_month_shift(m, -i))
        if v is not None:
            out.append(v)
    return out


def _zscore(value, history):
    h = [v for v in history if v is not None]
    if value is None or len(h) < 24:
        return None
    mu = statistics.fmean(h)
    sd = statistics.pstdev(h)
    if sd == 0:
        return 0.0
    return (value - mu) / sd


def _percentile_rank(value, history):
    h = sorted(v for v in history if v is not None)
    if value is None or len(h) < 24:
        return None
    below = sum(1 for v in h if v <= value)
    return below / len(h) * 100.0


def _near_high(series, m, window_months, within_pct):
    vals = _trailing_values(series, m, window_months)
    cur = series.get(m)
    if not vals or cur is None:
        return None
    return cur >= max(vals) * (1 - within_pct / 100.0)


def _max_drawdown(series, m, window_months):
    vals = _trailing_values(series, m, window_months)
    if len(vals) < 6:
        return None
    peak = vals[0]
    mdd = 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak * 100.0)
    return mdd


# ------------------------------------------------------------
# FEATURE ENGINE -- computes the 10 feature classes at month m.
# Each feature returns True (active), False (quiet), or None
# (data unavailable at that date -- excluded, never guessed).
# ------------------------------------------------------------
FEATURE_WEIGHTS = {
    'valuation_stretch': 1.0, 'parabolic_momentum': 1.0,
    'concentration': 1.0, 'breadth_divergence': 1.0,
    'vol_complacency': 0.75, 'curve_inversion': 1.0,
    'leader_rollover': 1.25, 'credit_stress': 1.0,
    'thematic_fever': 1.0, 'global_sync': 0.75,
}

FEATURE_PRECEDENTS = {
    'valuation_stretch': 'CAPE >90th pct of trailing 30y -- 1929, 1999, 2021',
    'parabolic_momentum': '24m SPX return z>1.5 -- the 1999 blow-off signature',
    'concentration': 'Nasdaq/SPX ratio 24m z>1.5 -- dot-com tech-share surge',
    'breadth_divergence': 'index at highs on narrow leadership -- 1999, 2007, 2021',
    'vol_complacency': 'VIX 6m mean in bottom quintile -- 2006-07, 2017',
    'curve_inversion': '10y-2y inverted within 12m -- preceded 2000, 2008 recessions',
    'leader_rollover': 'boom leader -10% off high while index holds -- financials mid-2007',
    'credit_stress': 'BAA-Treasury spread widening >40bps/6m -- 2007-08 onset',
    'thematic_fever': 'semis/SPX 24m z>2 -- AI/data-center capex thermometer (Lucent vendor-financing echo, 1999)',
    'global_sync': '3+ global majors within 5%% of 24m highs -- synchronized late-cycle 2007, 2021',
}


def _ratio_series(num, den):
    if not num or not den:
        return None
    out = {}
    for m, v in num.items():
        d = den.get(m)
        if d:
            out[m] = v / d
    return out or None


def compute_features(data, m):
    """Returns (features_dict, detail_dict) at month m."""
    spx, ixic, vix = data.get('spx'), data.get('ixic'), data.get('vix')
    cape = data.get('cape')
    f, detail = {}, {}

    # F1 valuation_stretch
    if cape and cape.get(m) is not None:
        hist = _trailing_values(cape, m, 360)
        pct = _percentile_rank(cape[m], hist)
        f['valuation_stretch'] = (pct is not None and pct >= 90.0)
        detail['valuation_stretch'] = {'cape': cape[m], 'pct_30y': round(pct, 1) if pct else None}
    else:
        f['valuation_stretch'] = None

    # F2 parabolic_momentum
    if spx:
        r24 = _trailing_return(spx, m, 24)
        hist = [_trailing_return(spx, _month_shift(m, -i), 24) for i in range(1, 241)]
        z = _zscore(r24, hist)
        f['parabolic_momentum'] = (z is not None and z > 1.5)
        detail['parabolic_momentum'] = {'spx_24m_pct': round(r24, 1) if r24 else None, 'z': round(z, 2) if z is not None else None}
    else:
        f['parabolic_momentum'] = None

    # F3 concentration (IXIC/SPX ratio momentum)
    ratio = _ratio_series(ixic, spx)
    if ratio and ratio.get(m):
        r24 = _trailing_return(ratio, m, 24)
        hist = [_trailing_return(ratio, _month_shift(m, -i), 24) for i in range(1, 241)]
        z = _zscore(r24, hist)
        f['concentration'] = (z is not None and z > 1.5)
        detail['concentration'] = {'ixic_spx_24m_pct': round(r24, 1) if r24 else None, 'z': round(z, 2) if z is not None else None}
    else:
        f['concentration'] = None

    # F4 breadth_divergence (RSP/SPY; data 2004+)
    rsp_spy = _ratio_series(data.get('rsp'), data.get('spy'))
    if rsp_spy and rsp_spy.get(m) and spx and len(_trailing_values(rsp_spy, m, 12)) >= 10:
        nh = _near_high(spx, m, 24, 5.0)
        rs12 = _trailing_values(rsp_spy, m, 12)
        under_mean = rsp_spy[m] < statistics.fmean(rs12)
        f['breadth_divergence'] = bool(nh and under_mean)
        detail['breadth_divergence'] = {'spx_near_24m_high': nh, 'rsp_spy_under_12m_mean': under_mean}
    else:
        f['breadth_divergence'] = None

    # F5 vol_complacency (VIX 1990+)
    if vix and vix.get(m):
        v6 = _trailing_values(vix, m, 6)
        v6m = statistics.fmean(v6) if v6 else None
        hist6 = []
        for i in range(1, 241):
            vv = _trailing_values(vix, _month_shift(m, -i), 6)
            if vv:
                hist6.append(statistics.fmean(vv))
        pct = _percentile_rank(v6m, hist6)
        f['vol_complacency'] = (pct is not None and pct <= 20.0)
        detail['vol_complacency'] = {'vix_6m_mean': round(v6m, 1) if v6m else None, 'pct': round(pct, 1) if pct is not None else None}
    else:
        f['vol_complacency'] = None

    # F6 curve_inversion (FRED T10Y2Y; Yahoo TNX-IRX fallback)
    t10y2y = data.get('t10y2y')
    inverted_12m = None
    if t10y2y:
        vals = [t10y2y.get(_month_shift(m, -i)) for i in range(0, 12)]
        vals = [v for v in vals if v is not None]
        inverted_12m = (min(vals) < 0) if vals else None
        detail['curve_inversion'] = {'source': 'FRED T10Y2Y', 'min_12m': round(min(vals), 2) if vals else None}
    elif data.get('tnx') and data.get('irx'):
        vals = []
        for i in range(0, 12):
            mm = _month_shift(m, -i)
            a, b = data['tnx'].get(mm), data['irx'].get(mm)
            if a is not None and b is not None:
                vals.append(a - b)
        inverted_12m = (min(vals) < 0.2) if vals else None
        detail['curve_inversion'] = {'source': 'Yahoo TNX-IRX proxy', 'min_12m': round(min(vals), 2) if vals else None}
    f['curve_inversion'] = inverted_12m

    # F7 leader_rollover -- best-performing boom ratio over trailing 3y,
    # now -10% off its 12m high while SPX within 5% of its own high.
    leader_candidates = {
        'ixic_spx': ratio,
        'smh_spy': _ratio_series(data.get('smh'), data.get('spy')),
        'xlf_spy': _ratio_series(data.get('xlf'), data.get('spy')),
    }
    best_name, best_r36 = None, None
    for name, rs in leader_candidates.items():
        if not rs or not rs.get(m):
            continue
        r36 = _trailing_return(rs, m, 36)
        if r36 is not None and (best_r36 is None or r36 > best_r36):
            best_name, best_r36 = name, r36
    if best_name and spx and spx.get(m):
        rs = leader_candidates[best_name]
        hi12 = max(_trailing_values(rs, m, 12) or [0])
        off_high = (rs[m] <= hi12 * 0.90) if hi12 else None
        spx_holding = _near_high(spx, m, 24, 5.0)
        f['leader_rollover'] = bool(off_high and spx_holding) if off_high is not None else None
        detail['leader_rollover'] = {'leader': best_name, 'leader_off_12m_high': off_high, 'spx_holding': spx_holding}
    else:
        f['leader_rollover'] = None

    # F8 credit_stress (FRED BAA10Y)
    baa = data.get('baa10y')
    if baa and baa.get(m) and baa.get(_month_shift(m, -6)):
        widen = (baa[m] - baa[_month_shift(m, -6)]) * 100.0  # bps
        f['credit_stress'] = widen > 40.0
        detail['credit_stress'] = {'baa10y_widen_6m_bps': round(widen, 0)}
    else:
        f['credit_stress'] = None

    # F9 thematic_fever (SMH/SPY; data 2000+)
    smh_spy = _ratio_series(data.get('smh'), data.get('spy'))
    if smh_spy and smh_spy.get(m):
        r24 = _trailing_return(smh_spy, m, 24)
        hist = [_trailing_return(smh_spy, _month_shift(m, -i), 24) for i in range(1, 241)]
        z = _zscore(r24, hist)
        f['thematic_fever'] = (z is not None and z > 2.0)
        detail['thematic_fever'] = {'smh_spy_24m_pct': round(r24, 1) if r24 else None, 'z': round(z, 2) if z is not None else None}
    else:
        f['thematic_fever'] = None

    # F10 global_sync
    majors = ['n225', 'dax', 'ftse', 'sensex']
    near = []
    for name in majors:
        s = data.get(name)
        if s and s.get(m):
            nh = _near_high(s, m, 24, 5.0)
            if nh is not None:
                near.append(1 if nh else 0)
    if len(near) >= 3:
        f['global_sync'] = sum(near) >= 3
        detail['global_sync'] = {'majors_near_24m_high': sum(near), 'of': len(near)}
    else:
        f['global_sync'] = None

    return f, detail


# ------------------------------------------------------------
# MULTIPLIERS -- amplifiers ONLY, never standalone (Black Swan law)
# ------------------------------------------------------------
def compute_multipliers(data, m):
    mults = {}
    ff = data.get('fedfunds')
    if ff and ff.get(m) and ff.get(_month_shift(m, -24)) and ff.get(_month_shift(m, -3)):
        hiked = (ff[m] - ff[_month_shift(m, -24)]) >= 1.5
        paused = abs(ff[m] - ff[_month_shift(m, -3)]) < 0.15
        if hiked and paused:
            mults['rate_cycle_pause'] = 0.15
    spx = data.get('spx')
    if spx and spx.get(m):
        mdd = _max_drawdown(spx, m, 18)
        if mdd is not None and mdd > -10.0:
            mults['drawdown_absence_18m'] = 0.10
    return mults


# ------------------------------------------------------------
# COMPOSITE + BANDS (Iran detector band semantics)
# ------------------------------------------------------------
def compute_composite(features, multipliers):
    base = sum(FEATURE_WEIGHTS[k] for k, v in features.items() if v is True)
    mult = 1.0 + sum(multipliers.values())
    score = round(base * mult, 2)
    if score >= 6.0:
        band = 'critical'
    elif score >= 4.5:
        band = 'high'
    elif score >= 3.0:
        band = 'elevated'
    else:
        band = 'normal'
    return score, band


# ------------------------------------------------------------
# EPISODE LIBRARY -- labels are historical fact; feature sets and
# lead times are COMPUTED from data at seed time, never asserted.
# ------------------------------------------------------------
EPISODES = [
    {'id': 'black_monday_1987', 'source_url': 'https://www.investopedia.com/terms/b/blackmonday.asp', 'label': 'Black Monday', 'anchor': '1987-08',
     'event_month': '1987-10', 'type': 'crash', 'drawdown': '-34% SPX in weeks',
     'note': 'pre-VIX/pre-FRED-spread era; partial features only'},
    {'id': 'ltcm_1998', 'source_url': 'https://www.investopedia.com/terms/l/longtermcapital.asp', 'label': 'LTCM / Russia default', 'anchor': '1998-06',
     'event_month': '1998-08', 'type': 'stress_event', 'drawdown': '-19% SPX'},
    {'id': 'dotcom_2000', 'source_url': 'https://www.investopedia.com/terms/d/dotcom-bubble.asp', 'label': 'Dot-com top', 'anchor': '1999-12',
     'event_month': '2000-03', 'type': 'bubble_burst', 'drawdown': '-49% SPX / -78% IXIC'},
    {'id': 'nine_eleven_2001', 'source_url': 'https://en.wikipedia.org/wiki/Economic_effects_of_the_September_11_attacks', 'label': '9/11 attacks', 'anchor': '2001-08',
     'event_month': '2001-09', 'type': 'exogenous_shock',
     'drawdown': '-12% SPX in 5 sessions',
     'note': 'NULL CASE: exogenous shocks carry no reliable market pre-signal; '
             'the GPI kinetic axis is the lightning watch'},
    {'id': 'gfc_2008', 'source_url': 'https://www.investopedia.com/terms/g/great-recession.asp', 'label': 'Global Financial Crisis top', 'anchor': '2007-10',
     'event_month': '2007-10', 'type': 'bubble_burst', 'drawdown': '-57% SPX'},
    {'id': 'downgrade_2011', 'source_url': 'https://en.wikipedia.org/wiki/August_2011_stock_markets_fall', 'label': 'US debt downgrade', 'anchor': '2011-06',
     'event_month': '2011-08', 'type': 'correction', 'drawdown': '-19% SPX'},
    {'id': 'china_2015', 'source_url': 'https://en.wikipedia.org/wiki/2015%E2%80%932016_Chinese_stock_market_turbulence', 'label': 'China deval / yuan shock', 'anchor': '2015-07',
     'event_month': '2015-08', 'type': 'correction', 'drawdown': '-12% SPX'},
    {'id': 'volmageddon_2018', 'source_url': 'https://www.investopedia.com/terms/v/volmageddon.asp', 'label': 'Q4 2018 / vol unwind', 'anchor': '2018-09',
     'event_month': '2018-10', 'type': 'correction', 'drawdown': '-20% SPX'},
    {'id': 'covid_2020', 'source_url': 'https://en.wikipedia.org/wiki/2020_stock_market_crash', 'label': 'COVID crash', 'anchor': '2020-01',
     'event_month': '2020-02', 'type': 'exogenous_shock', 'drawdown': '-34% SPX in 23 sessions',
     'note': 'NULL CASE (exogenous)'},
    {'id': 'everything_2021', 'source_url': 'https://www.investopedia.com/everything-bubble-5217463', 'label': 'Everything-bubble top', 'anchor': '2021-11',
     'event_month': '2022-01', 'type': 'bubble_burst', 'drawdown': '-25% SPX / -33% IXIC'},

    # ════════════════════════════════════════════════════════════════════
    # NON-US EPISODES (added Jul 26 2026)
    # ════════════════════════════════════════════════════════════════════
    # Every episode above is US-market-internal: valuation stretch, credit
    # stress, vol unwind, all measured in SPX/IXIC terms. That is a real bias,
    # not just a coverage gap -- the library could not RECOGNISE a policy-induced
    # or contagion-shaped bubble, because it had never seen one.
    #
    # DATA-SPINE CAVEAT, stated rather than hidden: the feature series behind
    # this detector are US (SPX, VIX, FRED spreads, CAPE). These episodes are
    # therefore scored on PARTIAL features -- the same limitation Black Monday
    # 1987 already carries. `data_spine: 'partial'` marks them so the prose can
    # say so. Matching on partial features is weaker evidence, and pretending
    # otherwise would be the dishonest option.
    {'id': 'plaza_1985', 'source_url': 'https://www.investopedia.com/terms/p/plaza-accord.asp', 'label': 'Plaza Accord -> Japanese asset bubble',
     'anchor': '1985-09', 'event_month': '1989-12', 'type': 'policy_induced_bubble',
     'drawdown': '-63% Nikkei by Aug 1992 (38,915 -> 14,309)',
     'data_spine': 'partial',
     'mechanism': ('coordinated currency intervention -> currency shock -> '
                   'domestic policy easing in response -> asset bubble -> '
                   'tightening -> burst'),
     'note': ('G5 intervened Sept 22 1985 to depreciate the dollar. The yen went '
              'from ~240/USD to ~120 by 1988. The resulting "endaka" export '
              'recession pushed the BOJ to cut its discount rate from 5.0% (Jan '
              '1986) to 2.5% (Feb 1987) -- the lowest in postwar Japanese history '
              '-- and the Louvre Accord (Feb 1987) gave political cover to HOLD '
              'it there for two further years. The Nikkei ran 12,598 -> 38,915, '
              '3.1x in 51 months. THE POINT: the bubble was the POLICY RESPONSE '
              'to the currency move, not the currency move itself. A detector '
              'watching only equity valuation would have seen a boom, not a '
              'mechanism.')},

    {'id': 'nikkei_1989', 'source_url': 'https://www.investopedia.com/terms/l/lost-decade.asp', 'label': 'Nikkei peak / Lost Decades',
     'anchor': '1989-06', 'event_month': '1989-12', 'type': 'bubble_burst',
     'drawdown': '-63% in 32 months; 34 years to regain the 1989 high',
     'data_spine': 'partial',
     'mechanism': ('terminal-phase asset bubble -> central-bank tightening -> '
                   'balance-sheet recession -> multi-decade stagnation'),
     'note': ('The tail the US library has no example of. Every US bubble_burst '
              'in this library recovered its prior high within a decade; the '
              'Nikkei took until 2024. Carrying this episode is what allows the '
              'detector to represent a burst whose consequence is stagnation '
              'rather than a V-shaped drawdown.')},

    {'id': 'asia_crisis_1997', 'source_url': 'https://www.investopedia.com/terms/a/asian-financial-crisis.asp', 'label': 'Asian financial crisis',
     'anchor': '1996-12', 'event_month': '1997-07', 'type': 'contagion',
     'drawdown': 'baht -50% in 6 months; regional equity/currency collapse',
     'data_spine': 'partial',
     'mechanism': ('currency peg + dollar-funded domestic lending -> reserve '
                   'depletion defending the peg -> forced float -> capital '
                   'flight -> contagion to countries with SIMILAR '
                   'VULNERABILITIES rather than similar geography'),
     'note': ('Thailand floated the baht July 2 1997 after reserves ran out. The '
              'tells were visible 12-18 months earlier: current account deficit '
              'at 8% of GDP, Bangkok office vacancy near 20%, export growth '
              'already broken by China\'s 1994 devaluation. Contagion then ran '
              'by VULNERABILITY PROFILE -- Indonesia, Malaysia, Philippines, '
              'then Korea in Jan 1998 -- which is the same logic the GPI wheel '
              'applies to hubs. This is the only cross-country episode in the '
              'library.')},

    {'id': 'carry_unwind_2024', 'source_url': 'https://www.investopedia.com/terms/c/currencycarrytrade.asp', 'label': 'Yen carry-trade unwind',
     'anchor': '2024-06', 'event_month': '2024-08', 'type': 'stress_event',
     'drawdown': '-12% Nikkei in one session (Aug 5 2024); global equity spillover',
     'data_spine': 'partial',
     'mechanism': ('funding-currency appreciation -> leveraged carry positions '
                   'unwound -> forced selling in UNRELATED assets -> volatility '
                   'transmitted globally from a domestic policy move'),
     'note': ('The recent, live-relevance case. A BOJ rate move plus yen '
              'strength unwound carry positions and transmitted a Japanese '
              'policy decision into a worldwide equity drawdown within days. '
              'Directly connected to the Nikkei/yen divergence read on '
              'japan-stability.html: STRONG yen + falling equities is this '
              'signature, and it is IMPORTED rather than domestic.')},

    {'id': 'tohoku_2011', 'source_url': 'https://en.wikipedia.org/wiki/2011_T%C5%8Dhoku_earthquake_and_tsunami', 'label': 'Tohoku earthquake / Fukushima',
     'anchor': '2011-01', 'event_month': '2011-03', 'type': 'exogenous_shock',
     'drawdown': '-16% Nikkei in 2 sessions',
     'data_spine': 'partial',
     'note': ('NULL CASE, deliberately included. A magnitude-9 earthquake has no '
              'market pre-signal and never will. It is in the library to keep '
              'the detector honest about its own limits: when a natural disaster '
              'moves an index, this module has nothing to say and the GPI '
              'kinetic and humanitarian axes are the read. Absence of a market '
              'warning is not absence of risk.')},
]

CONTROL_MONTHS = ['1995-06', '2004-06', '2013-06', '2016-06']


def _active_set(features):
    return sorted(k for k, v in features.items() if v is True)


def _jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def seed_episode_library(data):
    """Compute feature sets + composite at each episode anchor month."""
    library = []
    for ep in EPISODES:
        feats, detail = compute_features(data, ep['anchor'])
        mults = compute_multipliers(data, ep['anchor'])
        score, band = compute_composite(feats, mults)
        library.append({
            **ep,
            'active_features': _active_set(feats),
            'features_unavailable': sorted(k for k, v in feats.items() if v is None),
            'composite': score, 'band': band,
        })
    _redis_set(LIBRARY_KEY, {'seeded_at': datetime.now(timezone.utc).isoformat(),
                             'version': VERSION, 'episodes': library})
    return library


def similarity_matches(current_active, library, top_n=3):
    scored = []
    for ep in library:
        j = _jaccard(current_active, ep.get('active_features', []))
        scored.append({'id': ep['id'], 'label': ep['label'],
                       'type': ep['type'], 'event_month': ep['event_month'],
                       'drawdown': ep['drawdown'],
                       'similarity_pct': round(j * 100, 0),
                       'episode_features': ep.get('active_features', []),
                       # mechanism/data_spine carry the SO WHAT and the honesty
                       # caveat through to the prose layer.
                       'mechanism': ep.get('mechanism'),
                       'source_url': ep.get('source_url'),
                       'data_spine': ep.get('data_spine', 'full'),
                       'note': ep.get('note')})
    scored.sort(key=lambda x: -x['similarity_pct'])
    return scored[:top_n]


# ------------------------------------------------------------
# BACKTEST -- the receipts. Monthly timeline 1992->present;
# per-episode lead times COMPUTED (first month the band reached
# elevated/high before each labeled event); control months verified.
# ------------------------------------------------------------
def run_backtest(data, start='1992-01'):
    spx = data.get('spx') or {}
    months = [m for m in _months_range(spx) if m >= start]
    timeline = []
    for m in months:
        feats, _ = compute_features(data, m)
        mults = compute_multipliers(data, m)
        score, band = compute_composite(feats, mults)
        timeline.append({'month': m, 'score': score, 'band': band,
                         'active': _active_set(feats)})
    by_month = {t['month']: t for t in timeline}

    # Granularity self-check (v1.0.1): the bug this catches is Yahoo
    # silently degrading to quarterly bars. Median month-gap must be 1.
    gaps = []
    for a, b in zip(months, months[1:]):
        ya, ma = int(a[:4]), int(a[5:7])
        yb, mb = int(b[:4]), int(b[5:7])
        gaps.append((yb * 12 + mb) - (ya * 12 + ma))
    median_gap = statistics.median(gaps) if gaps else None
    if median_gap and median_gap > 1:
        print(f'[Market BlackSwan] WARNING: median month gap {median_gap} '
              f'-- data is NOT monthly; results unreliable')

    # Computed lead times (v1.0.1: index-based walk over the ACTUAL
    # timeline -- gap-tolerant): step back through evaluated months while
    # the band stays >= elevated; lead = months covered by that run.
    BAND_RANK = {'normal': 0, 'elevated': 1, 'high': 2, 'critical': 3}
    episode_reads = []
    spine_start = timeline[0]['month'] if timeline else None
    for ep in EPISODES:
        ev = ep['event_month']
        prior = [t for t in timeline if t['month'] < ev]
        if not prior:
            # OUTSIDE THE DATA SPINE (fixed Jul 26 2026). This previously said
            # `continue`, which SILENTLY DROPPED the episode from the library
            # table -- Black Monday 1987 has been invisible since launch for
            # this reason, and Plaza 1985 / Nikkei 1989 would have vanished the
            # same way. An episode we cannot backtest is not an episode that
            # did not happen; dropping it hides a limitation instead of
            # reporting one. It now appears WITH the reason it has no lead time.
            episode_reads.append({
                'id': ep['id'], 'label': ep['label'], 'type': ep['type'],
                'source_url': ep.get('source_url'),
                'event_month': ev,
                'lead_months_at_elevated_plus': None,
                'peak_band_in_lead_window': None,
                'band_at_event': None, 'score_at_event': None,
                'outside_data_spine': True,
                'expectation': (f'Outside the backtest window -- the feature '
                                f'series begin {spine_start or "later"}, so this '
                                f'episode cannot be scored. It is carried for '
                                f'pattern MATCHING, not lead-time evidence.'),
                'drawdown': ep.get('drawdown'),
                'note': ep.get('note'),
            })
            continue
        lead = 0
        peak_band = 'normal'
        for t in reversed(prior):
            if BAND_RANK[t['band']] >= 1:
                lead += 1
                if BAND_RANK[t['band']] > BAND_RANK[peak_band]:
                    peak_band = t['band']
            else:
                break
        at_event = by_month.get(ev) or prior[-1]
        episode_reads.append({
            'id': ep['id'], 'label': ep['label'], 'type': ep['type'],
            'source_url': ep.get('source_url'),
            'outside_data_spine': False,
            'event_month': ev,
            'lead_months_at_elevated_plus': lead,
            'peak_band_in_lead_window': peak_band,
            'band_at_event': at_event.get('band'),
            'score_at_event': at_event.get('score'),
            'expectation': ('pre-signal expected' if ep['type'] == 'bubble_burst'
                            else 'NULL CASE -- little/no pre-signal expected'
                            if ep['type'] == 'exogenous_shock' else 'partial pre-signal plausible'),
        })

    control_reads = []
    for m in CONTROL_MONTHS:
        if m in by_month:
            t = by_month[m]
            control_reads.append({'month': m, 'band': t['band'], 'score': t['score'],
                                  'pass': t['band'] in ('normal', 'elevated')})

    # Compact per-year band strip: worst band each year (N/E/H/C)
    strip = {}
    for t in timeline:
        y = t['month'][:4]
        rank = {'normal': 0, 'elevated': 1, 'high': 2, 'critical': 3}[t['band']]
        strip[y] = max(strip.get(y, 0), rank)
    band_strip = {y: 'NEHC'[r] for y, r in sorted(strip.items())}

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'version': VERSION,
        'start': start,
        'months_evaluated': len(timeline),
        'granularity_median_month_gap': median_gap,
        'granularity_ok': bool(median_gap == 1),
        'era_note': ('Pre-2000 episodes are scored on fewer available '
                     'features (RSP/SMH/XLF and VIX/FRED series start '
                     'later) -- lead times across eras are comparable in '
                     'direction, not magnitude.'),
        'episode_reads': episode_reads,
        'control_reads': control_reads,
        'band_strip_by_year': band_strip,
        'timeline': timeline,
        'disclaimer': DISCLAIMER,
    }


# ------------------------------------------------------------
# LAG-STATEMENT PROSE (the canonical template, locked Jun 12 2026)
# ------------------------------------------------------------
def _lag_prose(matches, backtest):
    if not matches:
        return None
    leads = {e['id']: e for e in (backtest or {}).get('episode_reads', [])}
    lines = []
    for mt in matches:
        if mt['similarity_pct'] < 40 or mt['type'] not in ('bubble_burst', 'crash'):
            continue
        lead = leads.get(mt['id'], {}).get('lead_months_at_elevated_plus')
        if lead:
            lines.append(f"Current convergence is {mt['similarity_pct']:.0f}% similar to the "
                         f"pattern preceding the {mt['label']} ({mt['event_month']}); in that "
                         f"episode, comparable readings preceded the event by approximately "
                         f"{lead} months ({mt['drawdown']}).")
        else:
            lines.append(f"Current convergence is {mt['similarity_pct']:.0f}% similar to the "
                         f"pattern preceding the {mt['label']} ({mt['event_month']}, "
                         f"{mt['drawdown']}).")
    if not lines:
        return None
    return ' '.join(lines) + ' ' + analog_tail()


# ------------------------------------------------------------
# SO-WHAT LAYER (Jul 26 2026)
# ------------------------------------------------------------
# _lag_prose above answers "how similar, and how long did that one take."
# It does NOT answer "so what" -- which is what a desk officer actually needs.
#
# The Israeli-defense example is the diagnostic: the page correctly flagged a
# post-Oct-7 analog and then stopped. The reader was told a pattern MATCHED but
# never told what the pattern MEANT, so the finding died on the page.
#
# THE DISCIPLINE, and it is the whole design constraint:
#   ALLOWED   -- state what the analog's MECHANISM was, and what interval
#                elapsed in THAT episode. Both are historical fact.
#   FORBIDDEN -- project that interval forward. "Historically this configuration
#                preceded X by N months" is checkable; "expect a correction
#                within six months" is a forecast wearing a hedge.
#
# The difference is not stylistic. The first statement can be falsified against
# the record; the second cannot be falsified until it is too late to matter.

# What each episode TYPE means for a reader, once matched. This is the layer
# that turns "33% similar to 1987" into something actionable.
_TYPE_SO_WHAT = {
    'bubble_burst': (
        'Bubble-burst analogs describe a market that repriced its own '
        'assumptions rather than reacting to an outside event. The tell is that '
        'the drawdown needed no trigger -- which is why waiting for one is the '
        'characteristic mistake.'),
    'policy_induced_bubble': (
        'Policy-induced analogs are the ones a valuation-only reading MISSES. '
        'The bubble was the policy RESPONSE to an external shock, not the shock. '
        'Watch the response, not the shock: currency moves and the central-bank '
        'reaction to them are the mechanism, and the equity index is downstream '
        'of both.'),
    'contagion': (
        'Contagion analogs spread by VULNERABILITY PROFILE, not geography. The '
        'question is not "who is near the stressed market" but "who shares its '
        'funding structure" -- external deficit, dollar-funded domestic lending, '
        'a defended peg. That is a cross-country convergence read, and it is the '
        'same logic the GPI applies to hub networks.'),
    'crash': (
        'Crash analogs are fast and mechanical -- structure and forced selling '
        'rather than fundamentals. Lead times are short and pre-signals thin.'),
    'stress_event': (
        'Stress-event analogs transmit through POSITIONING rather than '
        'fundamentals: leverage in one place forces selling somewhere unrelated. '
        'The affected market is often not the source market, so read the funding '
        'currency and the crowded trade, not the index that fell.'),
    'correction': (
        'Correction analogs resolved without structural damage. Their value is '
        'as a NEGATIVE control -- they show what elevated readings look like '
        'when nothing breaks, which is most of the time.'),
    'exogenous_shock': (
        'Exogenous analogs are NULL CASES and are in the library on purpose. '
        'Earthquakes, attacks and pandemics carry no market pre-signal. If the '
        'closest match is exogenous, the honest read is that this module has '
        'little to say and the GPI kinetic and humanitarian axes are the watch. '
        'Absence of a market warning is not absence of risk.'),
}


def _build_so_what(matches, backtest, active_features, band):
    """The 'so what' a desk officer needs, built from matched analogs.

    Returns a dict, not a string -- the frontend renders the pieces separately
    and the GPI can consume `headline` alone.
    """
    if not matches:
        return None
    top = matches[0]
    leads = {e['id']: e for e in (backtest or {}).get('episode_reads', [])}
    sim = top.get('similarity_pct', 0)

    # Below 30% overlap the "closest" analog is closest by default, not by
    # resemblance. Saying so is more useful than naming it.
    if sim < 30:
        return {
            'headline': 'No close historical analog this cycle.',
            'body': (f'The nearest match ({top.get("label")}) shares only '
                     f'{sim:.0f}% of active features -- closest by default '
                     f'rather than by resemblance. Present conditions are not '
                     f'well described by anything in a ~100-year library, which '
                     f'is itself worth noting rather than smoothing over.'),
            'mechanism': None, 'watch': None, 'confidence': 'no_analog',
        }

    parts = []

    # 1. WHAT THIS PATTERN IS -- type-level meaning.
    type_txt = _TYPE_SO_WHAT.get(top.get('type'))
    if type_txt:
        parts.append(type_txt)

    # 2. THE MECHANISM -- the causal chain of the matched episode. This is the
    #    single most useful sentence and most analog readouts omit it.
    mech = top.get('mechanism')
    if mech:
        parts.append(f'In {top.get("label")} the chain ran: {mech}.')

    # 3. WHAT HAPPENED NEXT -- historical fact, stated as history.
    lead = leads.get(top.get('id'), {}).get('lead_months_at_elevated_plus')
    if lead:
        parts.append(f'In that episode, comparable readings appeared about '
                     f'{lead} months before the event ({top.get("drawdown")}). '
                     f'That is what happened THEN, not a projection.')
    elif top.get('drawdown'):
        parts.append(f'That episode resolved as {top.get("drawdown")}.')

    # 4. THE HONESTY CAVEAT -- partial-spine episodes are weaker evidence.
    if top.get('data_spine') == 'partial':
        parts.append('Note: this episode is scored on PARTIAL features -- the '
                     'series behind this detector are US, so a non-US analog '
                     'matches on fewer dimensions and is weaker evidence than '
                     'the percentage alone suggests.')

    # 5. WHAT WOULD CONFIRM OR DENY -- turns a read into something checkable.
    watch = _analog_watch(top.get('type'), top.get('id'))

    return {
        'headline': (f'Closest analog: {top.get("label")} '
                     f'({sim:.0f}% feature overlap, {top.get("type", "").replace("_", " ")}).'),
        'body': ' '.join(parts),
        'mechanism': mech,
        'watch': watch,
        'confidence': ('partial_spine' if top.get('data_spine') == 'partial'
                       else 'full_spine'),
        'analog_id': top.get('id'),
        'similarity_pct': sim,
    }


def _analog_watch(ep_type, ep_id):
    """Confirm/deny indicators per analog type. A read the reader cannot check
    is a claim, not an assessment."""
    by_id = {
        'plaza_1985': ('CONFIRM: coordinated intervention language from G7/G20 '
                       'finance channels, a central bank easing INTO currency '
                       'strength, or an official discount rate cut framed as '
                       'export defence. DENY: tightening into the currency move, '
                       'or intervention discussed and declined.'),
        'asia_crisis_1997': ('CONFIRM: reserve drawdown at a pegged central bank, '
                             'external deficit past ~6% of GDP, or a second '
                             'economy with the same funding profile repricing. '
                             'DENY: reserves rebuilding, or the stressed currency '
                             'floating without regional follow-through.'),
        'carry_unwind_2024': ('CONFIRM: funding-currency strength alongside '
                              'falling equities in UNRELATED markets -- the '
                              'positioning tell. DENY: currency strength with '
                              'equities holding, which is ordinary repricing.'),
        'nikkei_1989': ('CONFIRM: tightening into a late-stage asset move plus '
                        'credit growth already rolling over. DENY: policy holding '
                        'while valuations mean-revert on their own.'),
    }
    if ep_id in by_id:
        return by_id[ep_id]
    by_type = {
        'bubble_burst': ('CONFIRM: breadth narrowing while the index holds, and '
                         'leadership rolling over. DENY: breadth broadening, or '
                         'earnings catching up to price.'),
        'exogenous_shock': ('Nothing in this module confirms or denies an '
                            'exogenous event. The GPI kinetic and humanitarian '
                            'axes are the watch.'),
        'correction': ('CONFIRM: stress spreading to funding markets. DENY: '
                       'spreads staying tight -- the ordinary path for a '
                       'correction analog.'),
        'contagion': ('CONFIRM: a second economy with a similar funding profile '
                      'repricing. DENY: stress staying local.'),
        'stress_event': ('CONFIRM: forced selling in assets unrelated to the '
                         'source. DENY: the move staying inside its own market.'),
    }
    return by_type.get(ep_type)


# ------------------------------------------------------------
# GLOBAL MAJORS (Jul 26 2026)
# ------------------------------------------------------------
# The detector has fetched ^N225, ^GDAXI, ^FTSE and ^BSESN since launch, but
# consumed them ONLY as feature F10 (global_sync) and never exposed them. The
# Market Watch frontend already had injectDetectorMajors() waiting on a
# `global_majors` key that nothing emitted -- so four major indices were pulled
# every cycle and rendered nowhere.
#
# Surfacing them here rather than adding a second fetcher keeps ONE source of
# truth: the board and the global_sync feature now read the same numbers, so
# the board cannot disagree with the engine that scores it.

_MAJOR_META = {
    'n225':   {'name': 'Nikkei 225',  'ticker': '^N225',   'region': 'apac',
               'note': 'Tokyo. Exporter-heavy -- a weaker yen mechanically lifts it, '
                       'so read against USD/JPY rather than alone.'},
    'sensex': {'name': 'BSE Sensex',  'ticker': '^BSESN',  'region': 'apac',
               'note': 'Mumbai. India\'s domestic-demand benchmark; less '
                       'export-levered than the other Asian majors.'},
    'dax':    {'name': 'DAX',         'ticker': '^GDAXI',  'region': 'europe',
               'note': 'Frankfurt. Industrial and export weighted -- energy input '
                       'costs and China demand both transmit here first.'},
    'ftse':   {'name': 'FTSE 100',    'ticker': '^FTSE',   'region': 'europe',
               'note': 'London. Heavily commodity and overseas-earnings weighted, '
                       'so it often tracks global rather than UK conditions.'},
}


def _build_global_majors(data):
    """Expose the four majors the detector already fetches.

    Monthly series only -- these feed a monthly feature engine, so the change
    figures are month-over-month and 12-month, NOT daily. Labelled as such:
    presenting a monthly delta as a daily one would be a quiet lie.
    """
    out = {}
    for key, meta in _MAJOR_META.items():
        series = data.get(key)
        if not series:
            continue
        months = sorted(series.keys())
        if len(months) < 2:
            continue
        last, prev = series[months[-1]], series[months[-2]]
        yr_ago = series.get(months[-13]) if len(months) >= 13 else None
        spark = [round(float(series[m]), 2) for m in months[-24:]]
        peak24 = max(spark) if spark else None
        out[key] = {
            'name': meta['name'], 'ticker': meta['ticker'], 'region': meta['region'],
            'note': meta['note'],
            'value': round(float(last), 2),
            'change_pct_1m': round(((last - prev) / prev) * 100, 2) if prev else None,
            'change_pct_12m': (round(((last - yr_ago) / yr_ago) * 100, 2)
                               if yr_ago else None),
            # Distance from the 24-month high is what F10 global_sync keys on --
            # surfacing it lets the reader see the feature, not just its output.
            'pct_from_24m_high': (round(((last - peak24) / peak24) * 100, 2)
                                  if peak24 else None),
            'within_5pct_of_24m_high': (bool(peak24 and ((peak24 - last) / peak24) <= 0.05)),
            'sparkline': spark,
            'cadence': 'monthly',
            'as_of': months[-1],
        }
    if out:
        near = [v['name'] for v in out.values() if v['within_5pct_of_24m_high']]
        out['_sync'] = {
            'count_near_high': len(near),
            'near_high': near,
            'note': ('F10 global_sync fires when 3+ majors sit within 5% of their '
                     '24-month high -- synchronised global positioning, which '
                     'historically leaves less room for one market to absorb a '
                     'shock for the others.'),
        }
    return out


# ------------------------------------------------------------
# CURRENT SCAN
# ------------------------------------------------------------
def run_scan():
    data = _gather_all_series()
    if not data.get('spx'):
        return None
    latest = _months_range(data['spx'])[-1]
    feats, detail = compute_features(data, latest)
    mults = compute_multipliers(data, latest)
    score, band = compute_composite(feats, mults)
    active = _active_set(feats)

    lib_payload = _redis_get(LIBRARY_KEY)
    library = (lib_payload or {}).get('episodes')
    if not library:
        library = seed_episode_library(data)
    matches = similarity_matches(active, library)
    backtest = _redis_get(BACKTEST_KEY)

    sources_ok = {k: bool(v) for k, v in data.items()}
    payload = {
        'success': True,
        'module': 'market_blackswan_detector',
        'version': VERSION,
        'as_of_month': latest,
        'composite': score,
        'band': band,
        'active_features': [
            {'name': k, 'weight': FEATURE_WEIGHTS[k],
             'precedent': FEATURE_PRECEDENTS[k],
             'detail': detail.get(k)} for k in active],
        'quiet_features': sorted(k for k, v in feats.items() if v is False),
        'features_unavailable': sorted(k for k, v in feats.items() if v is None),
        'multipliers': mults,
        'similarity_matches': matches,
        'historical_lag_read': _lag_prose(matches, backtest),
        # Four majors the detector already fetched but never exposed. The
        # Market Watch board consumes this via injectDetectorMajors().
        'global_majors': _build_global_majors(data),
        # SO-WHAT layer (Jul 26 2026): mechanism + what-happened-next + what
        # would confirm or deny. The frontend renders the pieces separately and
        # the GPI can consume `headline` alone.
        'so_what': _build_so_what(matches, backtest, active, band),
        'ai_thematic_read': detail.get('thematic_fever'),
        'data_honesty': {
            'sources': sources_ok,
            'fred_key_present': bool(FRED_API_KEY),
            'cape_method': CAPE_DATA_AS_OF,
            'resolution': 'monthly closes',
        },
        'analytical_frame': ('Fragility, not prophecy: this module measures how '
                             'dry the forest is. The GPI kinetic and diplomatic '
                             'axes watch for lightning. Compound reads surface '
                             'at GPI altitude.'),
        'disclaimer': DISCLAIMER,
        'last_updated': datetime.now(timezone.utc).isoformat(),
    }

    # Auto-snapshot at elevated+ (pattern-memory law)
    if band != 'normal':
        snaps = _redis_get(SNAPSHOT_KEY) or []
        snaps = [s for s in snaps if s.get('as_of_month') != latest]
        snaps.append({'as_of_month': latest, 'composite': score, 'band': band,
                      'active_features': active,
                      'snapped_at': payload['last_updated']})
        _redis_set(SNAPSHOT_KEY, snaps[-200:])

    # ---- Compact GPI bundle (Slice 3, Jun 13 2026) --------------------
    # The GPI economic axis + the fragility compound read consume this.
    # Kept small and stable so the GPI detector never parses the full scan.
    # ai_thematic_active flags the AI/data-center/semiconductor fever that
    # makes a Taiwan-semiconductor disruption a high-stakes compound read.
    ai = payload.get('ai_thematic_read') or {}
    ai_active = bool(ai and ai.get('z') is not None and ai.get('z') > 2.0)
    _redis_set(GPI_BUNDLE_KEY, {
        'band': band,
        'composite': score,
        'as_of_month': latest,
        'active_features': active,
        'ai_thematic_active': ai_active,
        'ai_thematic_z': (ai or {}).get('z'),
        'historical_lag_read': payload.get('historical_lag_read'),
        'top_analog': (payload.get('similarity_matches') or [{}])[0].get('label'),
        'disclaimer': DISCLAIMER,
        'updated_at': payload['last_updated'],
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
def register_market_blackswan_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/market-blackswan', methods=['GET', 'OPTIONS'])
    def api_market_blackswan():
        if request.method == 'OPTIONS':
            return '', 200
        force = request.args.get('force', 'false').lower() == 'true'
        if not force:
            cached = _redis_get(CACHE_KEY)
            if cached and _is_fresh(cached, CACHE_TTL_HOURS):
                cached['cached'] = True
                return jsonify(cached)
        payload = run_scan()
        if payload:
            payload['cached'] = False
            _redis_set(CACHE_KEY, payload)
            return jsonify(payload)
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached['cached'] = True
            cached['stale'] = True
            return jsonify(cached)
        return jsonify({'success': False,
                        'error': 'Scan failed (Yahoo unreachable, no cache)',
                        'version': VERSION}), 503

    @app.route('/api/market-blackswan/backtest', methods=['GET'])
    def api_market_blackswan_backtest():
        force = request.args.get('force', 'false').lower() == 'true'
        slim = request.args.get('slim', 'true').lower() == 'true'
        if not force:
            cached = _redis_get(BACKTEST_KEY)
            if cached and _is_fresh(cached, BACKTEST_TTL_HOURS):
                out = dict(cached)
                if slim:
                    out.pop('timeline', None)
                out['cached'] = True
                return jsonify(out)
        data = _gather_all_series()
        if not data.get('spx'):
            return jsonify({'success': False,
                            'error': 'Yahoo unreachable'}), 503
        bt = run_backtest(data, start=request.args.get('start', '1992-01'))
        seed_episode_library(data)  # refresh library while data is hot
        _redis_set(BACKTEST_KEY, bt)
        out = dict(bt)
        if slim:
            out.pop('timeline', None)
        out['cached'] = False
        return jsonify(out)

    @app.route('/api/market-blackswan/debug', methods=['GET'])
    def api_market_blackswan_debug():
        cached = _redis_get(CACHE_KEY)
        lib = _redis_get(LIBRARY_KEY)
        bt = _redis_get(BACKTEST_KEY)
        return jsonify({
            'module': 'market_blackswan_detector', 'version': VERSION,
            'redis_configured': bool(REDIS_URL and REDIS_TOKEN),
            'fred_key_present': bool(FRED_API_KEY),
            'scan_cached': bool(cached),
            'library_seeded': bool(lib),
            'library_episodes': len((lib or {}).get('episodes', [])),
            'backtest_cached': bool(bt),
            'tickers': TICKERS, 'fred_series': FRED_SERIES,
            'cape_anchors_through': max(CAPE_ANCHORS.keys()),
        })

    print(f'[Market BlackSwan] Endpoints registered (v{VERSION})')
