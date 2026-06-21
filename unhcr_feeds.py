"""
unhcr_feeds.py — Asifah Analytics v1.0.0
========================================
Shared UNHCR Refugee Data Finder layer (open public API — no key, no auth).

Source: UNHCR Refugee Population Statistics Database
  Base: https://api.unhcr.org/population/v1/
  Endpoint used: /population/  (refugees, asylum_seekers, idps, oip, stateless)
  Filters: coo / coa (country of origin / asylum), coo_all / coa_all,
           cf_type=ISO (so we pass standard ISO3 codes), yearFrom.

Cadence note (READ THIS): UNHCR figures are END-YEAR STOCK values (annual),
plus monthly "nowcasting" estimates. This is a STRUCTURAL BASELINE sensor, not
a live ticker. It complements DTM (live IDP/flow) — it does not replace it.

Per country we fetch TWO directions:
  - HOSTED      (coa=<ISO>, coo_all)  -> who is sheltering IN this country, by origin
  - ORIGINATED  (coo=<ISO>, coa_all)  -> people who FLED this country + its IDPs, by destination

Pattern matches the standard Asifah backend module:
  - Upstash Redis REST cache (24h TTL)
  - Background refresh thread (daily)
  - register_unhcr_endpoints(app) wiring
  - /api/unhcr/<country>, /api/unhcr/all, /api/unhcr/refresh, /debug/unhcr/<country>

DEPLOYMENT (proxy-not-clone): the SCANNER runs on ONE backend (ME, where Libya
lives). It writes unhcr:<id>:latest to the SHARED Upstash Redis. Africa-backend
pages later register this module with start_background=False (read-only) and read
the same keys — no second scanner, nothing to drift.
"""

import os
import json
import time
import requests
import threading
from datetime import datetime, timezone

VERSION = '1.0.0'
CACHE_TTL_HOURS = 24
BACKGROUND_REFRESH_HOURS = 24
REQUEST_TIMEOUT = (5, 20)
UNHCR_BASE = 'https://api.unhcr.org/population/v1'
USER_AGENT = 'Mozilla/5.0 (compatible; AsifahAnalytics-UNHCR/1.0; +https://www.asifahanalytics.com)'

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

# country_id (matches stability-page IDs) -> ISO3 (passed with cf_type=ISO)
COUNTRY_ISO = {
    # Africa build set
    'libya': 'LBY', 'sudan': 'SDN', 'south_sudan': 'SSD', 'somalia': 'SOM',
    'ethiopia': 'ETH', 'mali': 'MLI', 'niger': 'NER', 'burkina_faso': 'BFA',
    'chad': 'TCD', 'drc': 'COD', 'zimbabwe': 'ZWE', 'morocco': 'MAR',
    'algeria': 'DZA', 'tunisia': 'TUN', 'egypt': 'EGY', 'mauritania': 'MRT',
    'uganda': 'UGA',
    # ME (reusable — already have pages)
    'syria': 'SYR', 'lebanon': 'LBN', 'yemen': 'YEM', 'iraq': 'IRQ',
}

# Display-name fallback for common origins/destinations (used only if the API
# row has no name field). Not exhaustive — unknown codes fall back to the code.
ISO_NAME = {
    'LBY': 'Libya', 'SDN': 'Sudan', 'SSD': 'South Sudan', 'SOM': 'Somalia',
    'ETH': 'Ethiopia', 'MLI': 'Mali', 'NER': 'Niger', 'BFA': 'Burkina Faso',
    'TCD': 'Chad', 'COD': 'DR Congo', 'ZWE': 'Zimbabwe', 'MAR': 'Morocco',
    'DZA': 'Algeria', 'TUN': 'Tunisia', 'EGY': 'Egypt', 'MRT': 'Mauritania',
    'UGA': 'Uganda', 'SYR': 'Syria', 'LBN': 'Lebanon', 'YEM': 'Yemen',
    'IRQ': 'Iraq', 'ERI': 'Eritrea', 'NGA': 'Nigeria', 'CAF': 'CAR',
    'COG': 'Congo', 'CMR': 'Cameroon', 'KEN': 'Kenya', 'UGA2': 'Uganda',
    'ITA': 'Italy', 'TUR': 'Turkey', 'EGY2': 'Egypt', 'GRC': 'Greece',
    'FRA': 'France', 'DEU': 'Germany', 'AFG': 'Afghanistan', 'PSE': 'Palestine',
    'JOR': 'Jordan', 'IRN': 'Iran', 'PAK': 'Pakistan', 'RWA': 'Rwanda',
    'BDI': 'Burundi', 'AGO': 'Angola', 'ZMB': 'Zambia', 'TZA': 'Tanzania',
    'MWI': 'Malawi', 'MOZ': 'Mozambique', 'ZAF': 'South Africa',
}


# ============================================================
# REDIS HELPERS
# ============================================================

def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
    except Exception as e:
        print(f'[UNHCR Redis] GET error for {key}: {e}')
    return None


def _redis_set(key, value, ttl_seconds=None):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    if ttl_seconds is None:
        ttl_seconds = CACHE_TTL_HOURS * 3600
    try:
        payload = json.dumps(value, default=str)
        resp = requests.post(
            f'{UPSTASH_REDIS_URL}/set/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json',
            },
            data=payload,
            params={'EX': ttl_seconds},
            timeout=5,
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f'[UNHCR Redis] SET error for {key}: {e}')
    return False


# ============================================================
# UNHCR FETCH
# ============================================================

def _int(v):
    """Coerce UNHCR numeric fields (may be str, None, '-') to int."""
    try:
        if v in (None, '', '-'):
            return 0
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _fetch_pages(endpoint, params, max_pages=8):
    """GET a UNHCR endpoint, following pagination. Returns list of row dicts.
    Response wrapper is expected to be {'items': [...], 'maxPages': N, ...}.
    """
    rows = []
    page = 1
    while page <= max_pages:
        p = dict(params)
        p['page'] = page
        p.setdefault('limit', 1000)
        try:
            r = requests.get(
                f'{UNHCR_BASE}/{endpoint}/',
                params=p,
                headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'},
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                print(f'[UNHCR] {endpoint} HTTP {r.status_code} (params={params})')
                break
            j = r.json()
            items = j.get('items')
            if items is None:
                items = j.get('data') or []
            rows.extend(items)
            max_p = j.get('maxPages') or j.get('totalPages') or 1
            if page >= max_p or not items:
                break
            page += 1
        except Exception as e:
            print(f'[UNHCR] {endpoint} fetch error: {str(e)[:120]}')
            break
    return rows


def _latest_year(rows):
    yrs = [_int(r.get('year')) for r in rows if r.get('year') not in (None, '')]
    return max(yrs) if yrs else None


def _top_groups(rows, code_field, name_field, n=6):
    """Group rows by origin/destination, sum (refugees + asylum_seekers), top N."""
    agg = {}
    for r in rows:
        code = r.get(code_field) or '?'
        name = r.get(name_field) or ISO_NAME.get(code) or code
        total = _int(r.get('refugees')) + _int(r.get('asylum_seekers'))
        if code not in agg:
            agg[code] = {'iso': code, 'name': name, 'total': 0}
        agg[code]['total'] += total
    out = sorted(agg.values(), key=lambda x: x['total'], reverse=True)
    return [g for g in out if g['total'] > 0][:n]


def fetch_country_unhcr(country_id):
    """Fetch hosted + originated UNHCR figures for one country."""
    iso = COUNTRY_ISO.get(country_id)
    if not iso:
        return None

    year_from = datetime.now(timezone.utc).year - 2

    hosted_rows = _fetch_pages('population', {
        'coa': iso, 'coo_all': 'true', 'cf_type': 'ISO', 'yearFrom': year_from,
    })
    orig_rows = _fetch_pages('population', {
        'coo': iso, 'coa_all': 'true', 'cf_type': 'ISO', 'yearFrom': year_from,
    })

    # Restrict each direction to its latest available year
    hy = _latest_year(hosted_rows)
    oy = _latest_year(orig_rows)
    hosted_rows = [r for r in hosted_rows if _int(r.get('year')) == hy] if hy else []
    orig_rows = [r for r in orig_rows if _int(r.get('year')) == oy] if oy else []

    hosted = {
        'refugees': sum(_int(r.get('refugees')) for r in hosted_rows),
        'asylum_seekers': sum(_int(r.get('asylum_seekers')) for r in hosted_rows),
        'data_year': hy,
        'top_origins': _top_groups(hosted_rows, 'coo', 'coo_name'),
    }
    hosted['total'] = hosted['refugees'] + hosted['asylum_seekers']

    originated = {
        'refugees': sum(_int(r.get('refugees')) for r in orig_rows),
        'asylum_seekers': sum(_int(r.get('asylum_seekers')) for r in orig_rows),
        'idps': sum(_int(r.get('idps')) for r in orig_rows),
        'data_year': oy,
        'top_destinations': _top_groups(orig_rows, 'coa', 'coa_name'),
    }
    originated['total_fled'] = originated['refugees'] + originated['asylum_seekers']

    return {
        'version': VERSION,
        'country_id': country_id,
        'iso3': iso,
        'hosted': hosted,
        'originated': originated,
        'source': 'UNHCR Refugee Data Finder',
        'source_url': 'https://www.unhcr.org/refugee-statistics/',
        'data_as_of': f'End-year {hy or oy} (UNHCR annual stock)',
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'note': 'Annual end-year stock figures. Structural baseline; complements live DTM flow data.',
    }


# ============================================================
# AGGREGATE & CACHE
# ============================================================

def scan_all_unhcr():
    print(f'[UNHCR] Scan start (v{VERSION})...')
    t0 = time.time()
    results = {}
    for cid in COUNTRY_ISO:
        try:
            data = fetch_country_unhcr(cid)
            if data:
                results[cid] = data
                _redis_set(f'unhcr:{cid}:latest', data)
                h = data['hosted']['total']
                o = data['originated']['total_fled']
                print(f'[UNHCR] {cid} ({data["iso3"]}): hosts {h:,} / {o:,} fled')
        except Exception as e:
            print(f'[UNHCR] {cid} error: {str(e)[:120]}')
        time.sleep(1.0)  # be kind to the API

    payload = {
        'version': VERSION,
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'scan_seconds': round(time.time() - t0, 2),
        'countries': list(results.keys()),
        'by_country': results,
        'source': 'UNHCR Refugee Data Finder',
    }
    _redis_set('unhcr:all:latest', payload)
    print(f'[UNHCR] Scan done in {payload["scan_seconds"]}s — {len(results)} countries')
    return payload


def get_country_unhcr(country_id):
    cached = _redis_get(f'unhcr:{country_id}:latest')
    if cached:
        return cached
    return {
        'version': VERSION,
        'country_id': country_id,
        'iso3': COUNTRY_ISO.get(country_id),
        'hosted': None,
        'originated': None,
        'note': 'Cache cold — scan in progress. Refresh in 30-60s.',
    }


def get_all_unhcr():
    cached = _redis_get('unhcr:all:latest')
    if cached:
        return cached
    return {
        'version': VERSION, 'last_updated': None, 'countries': [],
        'by_country': {}, 'note': 'Cache cold — scan in progress.',
    }


# ============================================================
# BACKGROUND REFRESH
# ============================================================

_refresh_started = False
_refresh_lock = threading.Lock()


def _background_refresh_loop():
    while True:
        try:
            scan_all_unhcr()
        except Exception as e:
            print(f'[UNHCR] Background scan error: {e}')
        time.sleep(BACKGROUND_REFRESH_HOURS * 3600)


def start_background_refresh():
    global _refresh_started
    with _refresh_lock:
        if _refresh_started:
            return
        _refresh_started = True

    def _delayed_start():
        time.sleep(90)  # boot delay
        _background_refresh_loop()

    threading.Thread(target=_delayed_start, daemon=True).start()
    print(f'[UNHCR] Background refresh thread started (every {BACKGROUND_REFRESH_HOURS}h)')


# ============================================================
# FLASK ENDPOINTS
# ============================================================

def register_unhcr_endpoints(app, start_background=True):
    """Register /api/unhcr/* endpoints.

    On the SCANNER backend (ME): start_background=True (default).
    On a read-only proxy backend (Africa): start_background=False.
    """
    from flask import jsonify, request

    @app.route('/api/unhcr/all', methods=['GET', 'OPTIONS'])
    def unhcr_all():
        if request.method == 'OPTIONS':
            return ('', 204)
        return jsonify(get_all_unhcr())

    @app.route('/api/unhcr/<country>', methods=['GET', 'OPTIONS'])
    def unhcr_by_country(country):
        if request.method == 'OPTIONS':
            return ('', 204)
        cid = (country or '').lower().strip()
        if cid not in COUNTRY_ISO:
            return jsonify({'error': 'Unknown country', 'valid': sorted(COUNTRY_ISO)}), 400
        return jsonify(get_country_unhcr(cid))

    @app.route('/api/unhcr/refresh', methods=['POST', 'GET'])
    def unhcr_refresh():
        admin_key = os.environ.get('ADMIN_REFRESH_KEY')
        if admin_key:
            provided = request.args.get('key') or request.headers.get('X-Admin-Key')
            if provided != admin_key:
                return jsonify({'error': 'unauthorized'}), 401
        payload = scan_all_unhcr()
        return jsonify({'success': True, 'countries': len(payload['countries']),
                        'scan_seconds': payload['scan_seconds']})

    @app.route('/debug/unhcr/<country>', methods=['GET'])
    def unhcr_debug(country):
        # Live, uncached single-country fetch — used to verify field names on deploy.
        cid = (country or '').lower().strip()
        if cid not in COUNTRY_ISO:
            return jsonify({'error': 'Unknown country', 'valid': sorted(COUNTRY_ISO)}), 400
        iso = COUNTRY_ISO[cid]
        year_from = datetime.now(timezone.utc).year - 2
        raw = _fetch_pages('population', {
            'coa': iso, 'coo_all': 'true', 'cf_type': 'ISO', 'yearFrom': year_from,
        }, max_pages=1)
        return jsonify({
            'country_id': cid, 'iso3': iso,
            'rows_returned': len(raw),
            'first_row_keys': sorted(raw[0].keys()) if raw else [],
            'first_row_sample': raw[0] if raw else None,
            'parsed': fetch_country_unhcr(cid),
        })

    if start_background:
        start_background_refresh()

    print(f'[UNHCR] Endpoints registered (v{VERSION})')


if __name__ == '__main__':
    print(f'unhcr_feeds.py v{VERSION} — manual scan')
    payload = scan_all_unhcr()
    print(json.dumps({'countries': payload['countries'],
                      'scan_seconds': payload['scan_seconds']}, indent=2))
