"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — SHARED MARKET FETCHER
  v1.0.0 (Jul 12 2026) · Europe backend
═══════════════════════════════════════════════════════════════════════

One fetcher, imported by poland_financial_pulse.py and
kazakhstan_financial_pulse.py (and russia_stability.py whenever it's next
touched). Fixes the HTTP 429 that killed every ticker on both pulses.

WHY THIS EXISTS — the diagnosis:

  Jul 12 2026: /debug/poland-financial and /debug/kazakhstan-financial both
  returned resolved_count: 0 with HTTP 429 on EVERY primary ticker, even after
  a 2-second inter-request floor and exponential backoff.

  That is not pacing. That is Yahoo refusing the IP.

  The tell was BZ=F: Brent is the SAME ticker russia_stability.py has been
  fetching successfully for months. Same symbol, same box, suddenly refused.
  The symbols were never wrong. The Render IP is bot-flagged, and 429 is how
  Yahoo says so to a datacenter.

THE FIX — three layers, in order:

  1. YAHOO via curl_cffi (TLS fingerprint impersonation).
     A plain `requests` call has a Python TLS fingerprint that screams "bot"
     regardless of how convincing the User-Agent string is. curl_cffi
     impersonates a real Chrome TLS handshake. This is the same technique the
     platform already approved for RSS bot detection -- we simply never applied
     it to the market fetchers.

  2. STOOQ (keyless CSV).
     stooq.com is a POLISH financial data site: no API key, no rate limit worth
     worrying about, and native coverage of exactly the instruments Poland needs
     (wig20, pkn, usdpln). Coverage of the Kazakh GDRs is thin, so Stooq is a
     strong fallback for Poland and a weak one for Kazakhstan -- which is fine,
     because it is a FALLBACK.

  3. Plain requests (last resort, in case curl_cffi isn't installed).

ABSENCE-HONEST: if all three layers fail, we return None and the caller renders
an honest empty tile. We never invent a number, and we never disguise a
substitute instrument as the original.

REQUIREMENTS: add `curl_cffi` to requirements.txt on the Europe backend. If it
is absent this module degrades to plain requests + Stooq and says so in the
boot log -- it will not crash.
"""

import io
import csv
import time
import threading
from datetime import datetime, timezone

import requests

VERSION = '1.0.0'

# ── curl_cffi (TLS fingerprint impersonation) — soft import ──
try:
    from curl_cffi import requests as cffi_requests
    CURL_CFFI_AVAILABLE = True
    print('[Market Fetch] curl_cffi available -- Yahoo calls will impersonate Chrome TLS')
except ImportError:
    CURL_CFFI_AVAILABLE = False
    print('[Market Fetch] curl_cffi NOT available -- falling back to plain requests + Stooq. '
          'Add curl_cffi to requirements.txt to fix Yahoo 429s.')

# ── Rate discipline (kept from the pulse modules) ──
MIN_GAP_SEC = 1.5
_last_call = [0.0]
_gap_lock = threading.Lock()

# Per-ticker diagnostics, surfaced by the /debug endpoints
LAST_ERRORS = {}
THROTTLED = set()

_YF_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/124.0.0.0 Safari/537.36'),
    'Accept': 'application/json,text/plain,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}


def _throttle():
    with _gap_lock:
        elapsed = time.time() - _last_call[0]
        if elapsed < MIN_GAP_SEC:
            time.sleep(MIN_GAP_SEC - elapsed)
        _last_call[0] = time.time()


def _pack(price, prev_close, sparkline, source, ticker, currency=None):
    if price is None or prev_close in (None, 0):
        return None
    change_pct = ((float(price) - float(prev_close)) / float(prev_close)) * 100
    return {
        'value':          round(float(price), 4),
        'change_pct_24h': round(change_pct, 2),
        'sparkline':      sparkline[-30:],
        'source':         source,
        'ticker_used':    ticker,
        'currency':       currency,
        'timestamp':      datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════════
# LAYER 1 — YAHOO via curl_cffi
# ════════════════════════════════════════════════════════════

def _fetch_yahoo(ticker, log, max_429_retry=2):
    """Yahoo chart endpoint with Chrome TLS impersonation.

    '=' and '^' must be percent-encoded in the path (BZ=F -> BZ%3DF,
    ^WIG20 -> %5EWIG20) or Yahoo errors regardless of TLS."""
    enc = ticker.replace('=', '%3D').replace('^', '%5E')
    getter = cffi_requests.get if CURL_CFFI_AVAILABLE else requests.get

    for attempt in range(max_429_retry + 1):
        saw_429 = False
        for host in ('query1', 'query2'):
            url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{enc}'
            try:
                _throttle()
                kw = {'params': {'interval': '1d', 'range': '1mo'},
                      'timeout': 12, 'headers': _YF_HEADERS}
                if CURL_CFFI_AVAILABLE:
                    kw['impersonate'] = 'chrome'
                r = getter(url, **kw)

                if r.status_code == 429:
                    saw_429 = True
                    LAST_ERRORS[ticker] = f'Yahoo HTTP 429 via {host}'
                    print(f'{log} {ticker}: Yahoo 429 via {host}'
                          + ('' if CURL_CFFI_AVAILABLE else ' (no curl_cffi!)'))
                    continue
                if r.status_code != 200:
                    LAST_ERRORS[ticker] = f'Yahoo HTTP {r.status_code} via {host}'
                    continue

                data = r.json()
                result = (data.get('chart', {}).get('result') or [{}])[0]
                meta = result.get('meta', {})
                spark = []
                try:
                    ts = result.get('timestamp', []) or []
                    closes = (result.get('indicators', {}).get('quote')
                              or [{}])[0].get('close', []) or []
                    for i, t in enumerate(ts):
                        if i < len(closes) and closes[i] is not None:
                            spark.append({
                                'time': datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(),
                                'value': round(float(closes[i]), 4),
                            })
                except Exception:
                    pass

                price = meta.get('regularMarketPrice')
                if price is None and spark:
                    price = spark[-1]['value']
                prev = spark[-2]['value'] if len(spark) >= 2 else None
                if prev in (None, 0):
                    prev = meta.get('previousClose') or meta.get('chartPreviousClose')

                out = _pack(price, prev, spark, 'Yahoo Finance', ticker, meta.get('currency'))
                if out:
                    LAST_ERRORS.pop(ticker, None)
                    THROTTLED.discard(ticker)
                    return out
                LAST_ERRORS[ticker] = 'Yahoo returned no usable price'
            except Exception as e:
                LAST_ERRORS[ticker] = f'Yahoo {type(e).__name__}: {str(e)[:70]}'
                continue

        # A 429 is a THROTTLE, not a missing ticker. Back off and retry the SAME
        # symbol -- never sprint to the next candidate, which would deepen the
        # limit while learning nothing.
        if saw_429 and attempt < max_429_retry:
            backoff = 4 * (2 ** attempt)
            print(f'{log} {ticker}: rate-limited, sleeping {backoff}s')
            time.sleep(backoff)
            continue
        if saw_429:
            THROTTLED.add(ticker)
        break
    return None


# ════════════════════════════════════════════════════════════
# LAYER 2 — STOOQ (keyless CSV, Polish-native)
# ════════════════════════════════════════════════════════════

# Yahoo symbol -> Stooq symbol. Stooq is a Polish site, so its Poland coverage
# is excellent and its coverage of the Kazakh London GDRs is thin. That's fine:
# it is a fallback, and an absent mapping simply means "Stooq can't help here."
STOOQ_MAP = {
    # Poland — native coverage
    'WIG20.WA':  'wig20',
    '^WIG20':    'wig20',
    'PKN.WA':    'pkn',
    'PKN.PW':    'pkn',
    'PLN=X':     'usdpln',
    # FX / commodities (global coverage)
    'KZT=X':     'usdkzt',
    'BZ=F':      'cb.f',      # Brent continuous
    # US-listed substitutes
    'EPOL':      'epol.us',
    'EUAD':      'euad.us',
}


def _fetch_stooq(ticker, log):
    """Keyless CSV from stooq.com. Returns the last ~30 daily closes.

    Endpoint: https://stooq.com/q/d/l/?s=<symbol>&i=d
    Response: Date,Open,High,Low,Close,Volume
    """
    sym = STOOQ_MAP.get(ticker)
    if not sym:
        return None
    url = f'https://stooq.com/q/d/l/?s={sym}&i=d'
    try:
        _throttle()
        r = requests.get(url, timeout=12, headers={'User-Agent': _YF_HEADERS['User-Agent']})
        if r.status_code != 200 or not r.text or 'Date' not in r.text[:80]:
            LAST_ERRORS[ticker] = f'Stooq HTTP {r.status_code} / unparseable'
            return None

        rows = list(csv.DictReader(io.StringIO(r.text)))
        spark = []
        for row in rows[-40:]:
            try:
                close = row.get('Close')
                if close in (None, '', 'N/D'):
                    continue
                spark.append({'time': row.get('Date'), 'value': round(float(close), 4)})
            except (TypeError, ValueError):
                continue
        if len(spark) < 2:
            LAST_ERRORS[ticker] = 'Stooq returned <2 usable closes'
            return None

        out = _pack(spark[-1]['value'], spark[-2]['value'], spark,
                    'Stooq', ticker)
        if out:
            LAST_ERRORS.pop(ticker, None)
            print(f'{log} {ticker}: resolved via STOOQ ({sym}) -- Yahoo unavailable')
        return out
    except Exception as e:
        LAST_ERRORS[ticker] = f'Stooq {type(e).__name__}: {str(e)[:70]}'
        return None


# ════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════

def fetch_ticker(ticker, log='[Market Fetch]'):
    """Yahoo (curl_cffi) -> Stooq. Returns the canonical dict or None.

    ABSENCE-HONEST: None means we could not get the number. The caller renders
    an empty tile. We never invent a value."""
    out = _fetch_yahoo(ticker, log)
    if out:
        return out
    out = _fetch_stooq(ticker, log)
    if out:
        return out
    print(f'{log} {ticker}: ALL SOURCES FAILED '
          f'(last: {LAST_ERRORS.get(ticker, "unknown")})')
    return None


def fetch_chain(candidates, log='[Market Fetch]'):
    """Try each candidate in order. First hit wins and is tagged with whether it
    is a substitute.

    THROTTLE-AWARE: if a candidate was rate-limited (rather than genuinely
    missing) AND Stooq also could not help, abort the chain. A 429 tells us
    nothing about whether the next symbol exists -- only that we should slow
    down. Sprinting through the rest deepens the limit for zero information.

    A substitute instrument is LABELLED, never disguised as the original."""
    for i, tk in enumerate(candidates):
        out = fetch_ticker(tk, log)
        if out:
            out['is_substitute'] = (i > 0)
            out['chain_position'] = i
            if i > 0:
                print(f'{log} {candidates[0]} unavailable -- substitute {tk} in use')
            return out
        if tk in THROTTLED:
            print(f'{log} chain aborted at {tk}: THROTTLED, not missing. '
                  f'Skipping {candidates[i+1:]}')
            return None
    return None


def diagnostics():
    """For the /debug endpoints."""
    return {
        'fetcher_version':    VERSION,
        'curl_cffi_active':   CURL_CFFI_AVAILABLE,
        'stooq_symbols_known': sorted(STOOQ_MAP.keys()),
        'throttled':          sorted(THROTTLED),
        'last_errors':        dict(LAST_ERRORS),
    }
