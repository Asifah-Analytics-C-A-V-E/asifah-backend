# -*- coding: utf-8 -*-
"""
FOOD PRICE PULSE v1.0.0 (Slice 1) -- Asifah Analytics
======================================================
Coverage-first domestic staple food price monitor. The economic-axis
sibling of kinetic_activity_gatherer.py: instead of tracking only the
countries we have hand-built, it ingests the FULL WFP price database
(roughly 98 countries, 3000 markets) so the commodity tracker, cascade
detector, and GPI economic axis read ground truth for the whole world.

DATA SOURCE
-----------
WFP Vulnerability Analysis and Mapping (VAM) price database, published
on the Humanitarian Data Exchange (HDX). HDX rotates resource download
URLs whenever a dataset updates, so this module NEVER hardcodes a CSV
URL. It discovers the current URL at runtime through the HDX CKAN API:

    https://data.humdata.org/api/3/action/package_show?id=wfp-food-prices-jor

The response JSON carries resources[] with live download_url values.
Country dataset ids follow the pattern wfp-food-prices-{iso3 lower}.

ANALYTICAL FRAME (convergence, not prediction)
----------------------------------------------
For each country and staple family we compute the latest monthly mean
price (USD), month-over-month and year-over-year changes, and a z-score
of the latest month against that country's OWN trailing twelve-month
baseline. Bands: normal (z below 1), watch (1 to 2), elevated (2 to 3),
high (3 plus). Bands describe present conditions relative to the
country's own history. They are NOT probabilities of unrest or crisis.

CADENCE
-------
Underlying data is monthly (refreshed weekly upstream). The scheduler
re-scans every PULSE_REFRESH_DAYS days behind the canonical cross-worker
Redis lock, so only one gunicorn worker scans.
"""

import os
import csv
import json
import time
import threading
import requests
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

HDX_PACKAGE_SHOW = "https://data.humdata.org/api/3/action/package_show"
GLOBAL_DATASET_ID = "global-wfp-food-prices"
COUNTRY_DATASET_PATTERN = "wfp-food-prices-{iso3}"

# HDX shows bot detection on plain requests; use a real browser UA
# (same lesson as the Yahoo Finance fix on the US stability page).
HTTP_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/124.0.0.0 Safari/537.36'),
    'Accept': 'application/json, text/csv, */*',
}

REQUEST_TIMEOUT = (8, 45)        # (connect, read) seconds
PER_COUNTRY_SLEEP = 1.2          # throttle between country fetches
PULSE_REFRESH_DAYS = 7           # full re-scan cadence
RETENTION_DAYS = 420             # keep ~14 months of rows for baselines
STALE_DAYS = 150                 # newest data older than this -> 'stale'
MIN_BASELINE_MONTHS = 6          # months required before any anomaly claim

REDIS_BUNDLE_KEY = 'food_price_pulse_bundle'
REDIS_BUNDLE_TTL_SECONDS = 60 * 60 * 24 * 14   # 14 days

CONVERGENCE_DISCLAIMER = (
    "Bands describe present price conditions relative to each country's "
    "own trailing baseline. This is a CONVERGENCE indicator, NOT a "
    "probability of unrest, shortage, or crisis."
)

SOURCE_ATTRIBUTION = {
    'name': 'WFP VAM price database via Humanitarian Data Exchange',
    'url': 'https://data.humdata.org/dataset/global-wfp-food-prices',
    'license': 'CC BY for Intergovernmental Organisations',
}

# Staple families: row matches the FIRST family whose keyword appears in
# the commodity name (lowercased). Order matters: specific before broad.
STAPLE_FAMILIES = [
    ('rice',     ['rice']),
    ('wheat',    ['wheat flour', 'wheat']),
    ('bread',    ['bread']),
    ('maize',    ['maize flour', 'maize', 'corn']),
    ('sorghum',  ['sorghum']),
    ('millet',   ['millet']),
    ('beans',    ['beans', 'lentils', 'chickpeas', 'peas']),
    ('oil',      ['oil (vegetable', 'oil (sunflower', 'oil (palm',
                  'vegetable oil', 'cooking oil', 'oil']),
    ('sugar',    ['sugar']),
    ('potatoes', ['potatoes', 'potato', 'cassava']),
]

# Fallback country list if HDX country-index discovery fails. ISO3 codes
# of WFP-monitored countries, biased toward Asifah exposure profiles.
SEED_ISO3 = [
    'JOR', 'EGY', 'LBN', 'SYR', 'IRQ', 'YEM', 'PSE', 'TUR', 'IRN',
    'SDN', 'SSD', 'NGA', 'ETH', 'SOM', 'KEN', 'MLI', 'NER', 'BFA',
    'TCD', 'CMR', 'COD', 'CAF', 'MOZ', 'ZWE', 'MWI', 'ZMB', 'UGA',
    'TZA', 'RWA', 'BDI', 'SEN', 'GIN', 'LBR', 'SLE', 'MRT', 'LBY',
    'DZA', 'MAR', 'TUN', 'AFG', 'PAK', 'BGD', 'LKA', 'MMR', 'KHM',
    'LAO', 'IDN', 'PHL', 'TLS', 'KGZ', 'TJK', 'UKR', 'MDA', 'ARM',
    'HTI', 'VEN', 'PER', 'BOL', 'COL', 'ECU', 'GTM', 'HND', 'SLV', 'NIC',
]

_SCHED_WORKER_ID = "w%d" % os.getpid()
_scan_lock = threading.Lock()      # in-process guard for force scans
_scan_in_progress = {'active': False, 'started': None}


# ------------------------------------------------------------------
# Cross-worker scheduler lock (canonical pattern, cloned from
# commodity_tracker.py -- only the lock-owning gunicorn worker scans)
# ------------------------------------------------------------------

def _acquire_scheduler_lock(name, ttl_seconds):
    """Return True if THIS worker owns the scheduler lock for `name`."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return True  # no Redis -> assume single process
    key = "sched_lock:%s" % name
    hdr = {"Authorization": "Bearer %s" % UPSTASH_REDIS_TOKEN}
    try:
        r = requests.post(UPSTASH_REDIS_URL, headers=hdr,
                          json=["SET", key, _SCHED_WORKER_ID, "NX", "EX", str(ttl_seconds)],
                          timeout=8)
        if r.ok and (r.json() or {}).get('result') == 'OK':
            return True
        g = requests.get("%s/get/%s" % (UPSTASH_REDIS_URL, key), headers=hdr, timeout=8)
        owner = (g.json() or {}).get('result') if g.ok else None
        if owner == _SCHED_WORKER_ID:
            requests.post(UPSTASH_REDIS_URL, headers=hdr,
                          json=["SET", key, _SCHED_WORKER_ID, "EX", str(ttl_seconds)],
                          timeout=8)
            return True
        return False
    except Exception as e:
        print("[FoodPulse] lock check failed (%s); proceeding fail-open" % e)
        return True


# ------------------------------------------------------------------
# Redis helpers
# ------------------------------------------------------------------

def _redis_set_bundle(bundle):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    hdr = {"Authorization": "Bearer %s" % UPSTASH_REDIS_TOKEN}
    try:
        r = requests.post(UPSTASH_REDIS_URL, headers=hdr,
                          json=["SET", REDIS_BUNDLE_KEY, json.dumps(bundle),
                                "EX", str(REDIS_BUNDLE_TTL_SECONDS)],
                          timeout=15)
        return bool(r.ok)
    except Exception as e:
        print("[FoodPulse] Redis SET failed: %s" % e)
        return False


def _redis_get_bundle():
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    hdr = {"Authorization": "Bearer %s" % UPSTASH_REDIS_TOKEN}
    try:
        r = requests.get("%s/get/%s" % (UPSTASH_REDIS_URL, REDIS_BUNDLE_KEY),
                         headers=hdr, timeout=10)
        if r.ok:
            raw = (r.json() or {}).get('result')
            if raw:
                return json.loads(raw)
    except Exception as e:
        print("[FoodPulse] Redis GET failed: %s" % e)
    return None


# ------------------------------------------------------------------
# HDX discovery layer (CKAN API -- never hardcode resource URLs)
# ------------------------------------------------------------------

def _hdx_package_show(dataset_id):
    """Fetch dataset metadata from the HDX CKAN API. Returns dict or None."""
    try:
        r = requests.get(HDX_PACKAGE_SHOW, params={'id': dataset_id},
                         headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        body = r.json()
        if not body.get('success'):
            return None
        return body.get('result') or None
    except Exception as e:
        print("[FoodPulse] package_show(%s) failed: %s" % (dataset_id, e))
        return None


def _pick_csv_resource(package, name_hint=None):
    """Return (download_url, resource_name, last_modified) for the best CSV
    resource in a CKAN package, optionally preferring a name substring."""
    if not package:
        return None, None, None
    resources = package.get('resources') or []
    csvs = [res for res in resources
            if str(res.get('format', '')).upper() == 'CSV'
            and (res.get('download_url') or res.get('url'))]
    if not csvs:
        return None, None, None
    if name_hint:
        for res in csvs:
            if name_hint.lower() in str(res.get('name', '')).lower():
                return (res.get('download_url') or res.get('url'),
                        res.get('name'), res.get('last_modified'))
    res = csvs[0]
    return (res.get('download_url') or res.get('url'),
            res.get('name'), res.get('last_modified'))


def discover_country_list():
    """Discover the WFP country list from the global index dataset.
    Returns list of ISO3 codes (uppercase). Falls back to SEED_ISO3."""
    package = _hdx_package_show(GLOBAL_DATASET_ID)
    url, name, _mod = _pick_csv_resource(package, name_hint='countries')
    if not url:
        print("[FoodPulse] country index unavailable; using seed list (%d)" % len(SEED_ISO3))
        return list(SEED_ISO3)
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            print("[FoodPulse] country index HTTP %s; using seed list" % r.status_code)
            return list(SEED_ISO3)
        iso3s = []
        reader = csv.reader(r.text.splitlines())
        header = next(reader, [])
        cols = [h.strip().lower() for h in header]
        iso_idx = None
        for candidate in ('countryiso3', 'iso3', 'country_iso3'):
            if candidate in cols:
                iso_idx = cols.index(candidate)
                break
        if iso_idx is None:
            print("[FoodPulse] country index schema unrecognized; using seed list")
            return list(SEED_ISO3)
        for row in reader:
            if not row or row[0].startswith('#'):
                continue  # HXL tag row
            if iso_idx < len(row):
                code = row[iso_idx].strip().upper()
                if len(code) == 3 and code.isalpha():
                    iso3s.append(code)
        iso3s = sorted(set(iso3s))
        if len(iso3s) < 10:
            print("[FoodPulse] country index suspiciously small (%d); using seed list" % len(iso3s))
            return list(SEED_ISO3)
        print("[FoodPulse] discovered %d countries from HDX index" % len(iso3s))
        return iso3s
    except Exception as e:
        print("[FoodPulse] country index parse failed (%s); using seed list" % e)
        return list(SEED_ISO3)


# ------------------------------------------------------------------
# Per-country CSV parsing (streamed -- files can be decades long)
# ------------------------------------------------------------------

def _classify_staple(commodity_name):
    cname = (commodity_name or '').lower()
    for family, keywords in STAPLE_FAMILIES:
        for kw in keywords:
            if kw in cname:
                return family
    return None


def _parse_country_csv(url, cutoff_date):
    """Stream-parse a WFP country price CSV. Returns:
    { staple: { 'YYYY-MM': {'retail': [usd...], 'wholesale': [usd...]} } }
    Only rows newer than cutoff_date and matching a staple family are kept,
    so memory stays bounded no matter how long the file's history is."""
    monthly = {}
    rows_seen = 0
    rows_kept = 0
    try:
        with requests.get(url, headers=HTTP_HEADERS, stream=True,
                          timeout=REQUEST_TIMEOUT) as r:
            if r.status_code != 200:
                return None, "HTTP %s" % r.status_code
            r.encoding = 'utf-8'
            lines = r.iter_lines(decode_unicode=True)
            reader = csv.reader(line for line in lines if line is not None)
            header = next(reader, [])
            if header and header[0].startswith('\ufeff'):
                header[0] = header[0].lstrip('\ufeff')
            cols = [h.strip().lower() for h in header]
            try:
                i_date = cols.index('date')
                i_commodity = cols.index('commodity')
                i_pricetype = cols.index('pricetype')
                i_usd = cols.index('usdprice')
            except ValueError:
                return None, "schema mismatch: %s" % cols[:8]
            for row in reader:
                rows_seen += 1
                if not row or row[0].startswith('#'):
                    continue  # HXL tag row
                if len(row) <= max(i_date, i_commodity, i_pricetype, i_usd):
                    continue
                date_str = row[i_date].strip()
                if len(date_str) < 7:
                    continue
                month_key = date_str[:7]          # YYYY-MM
                if date_str[:10] < cutoff_date:
                    continue
                family = _classify_staple(row[i_commodity])
                if not family:
                    continue
                try:
                    usd = float(row[i_usd])
                except (ValueError, TypeError):
                    continue
                if usd <= 0:
                    continue
                ptype = row[i_pricetype].strip().lower()
                if ptype not in ('retail', 'wholesale'):
                    continue
                bucket = monthly.setdefault(family, {}).setdefault(
                    month_key, {'retail': [], 'wholesale': []})
                bucket[ptype].append(usd)
                rows_kept += 1
        return monthly, "ok (%d rows scanned, %d kept)" % (rows_seen, rows_kept)
    except Exception as e:
        return None, "fetch/parse error: %s" % e


# ------------------------------------------------------------------
# Anomaly computation (z-score against the country's own baseline)
# ------------------------------------------------------------------

def _band_from_z(z):
    if z is None:
        return 'normal'
    if z >= 3.0:
        return 'high'
    if z >= 2.0:
        return 'elevated'
    if z >= 1.0:
        return 'watch'
    return 'normal'


BAND_ORDER = ['normal', 'watch', 'elevated', 'high']


def _summarize_staple(family, month_buckets, today_str):
    """Reduce one staple's monthly buckets to an analytical summary."""
    series = []
    for month_key in sorted(month_buckets.keys()):
        bucket = month_buckets[month_key]
        vals = bucket['retail'] if bucket['retail'] else bucket['wholesale']
        if not vals:
            continue
        series.append((month_key, sum(vals) / len(vals), len(vals)))
    if not series:
        return None
    latest_month, latest_avg, latest_n = series[-1]
    baseline = [avg for (_m, avg, _n) in series[:-1]][-12:]
    mom_pct = None
    if len(series) >= 2 and series[-2][1] > 0:
        mom_pct = round((latest_avg - series[-2][1]) / series[-2][1] * 100.0, 1)
    yoy_pct = None
    target_yoy = "%04d-%02d" % (int(latest_month[:4]) - 1, int(latest_month[5:7]))
    for (m, avg, _n) in series:
        if m == target_yoy and avg > 0:
            yoy_pct = round((latest_avg - avg) / avg * 100.0, 1)
            break
    z = None
    dev_pct = None
    band = 'normal'
    baseline_note = None
    if len(baseline) >= MIN_BASELINE_MONTHS:
        mean = sum(baseline) / len(baseline)
        var = sum((v - mean) ** 2 for v in baseline) / len(baseline)
        std = var ** 0.5
        if mean > 0:
            dev_pct = round((latest_avg - mean) / mean * 100.0, 1)
        if std > 0:
            z = round((latest_avg - mean) / std, 2)
        # Band on the STRONGER of two reads. The z-score handles volatile
        # series; the percent-deviation read handles flat/administered
        # series (subsidized bread is flat for years, then jumps -- the
        # politically loudest case, and z cannot see it when std is 0).
        z_band = _band_from_z(z)
        if dev_pct is None:
            pct_band = 'normal'
        elif dev_pct >= 50.0:
            pct_band = 'high'
        elif dev_pct >= 25.0:
            pct_band = 'elevated'
        elif dev_pct >= 10.0:
            pct_band = 'watch'
        else:
            pct_band = 'normal'
        band = max(z_band, pct_band, key=BAND_ORDER.index)
        if std == 0:
            baseline_note = 'flat baseline (administered/subsidized price pattern)'
    else:
        baseline_note = 'insufficient baseline (%d months)' % len(baseline)
    # Staleness: newest month too old means this staple is reporting history
    latest_dt = datetime.strptime(latest_month + "-15", "%Y-%m-%d")
    is_stale = (datetime.utcnow() - latest_dt).days > STALE_DAYS
    out = {
        'staple': family,
        'latest_month': latest_month,
        'latest_avg_usd': round(latest_avg, 4),
        'observations': latest_n,
        'mom_pct': mom_pct,
        'yoy_pct': yoy_pct,
        'z_score': z,
        'baseline_dev_pct': dev_pct,
        'band': 'stale' if is_stale else band,
        'months_in_series': len(series),
    }
    if baseline_note:
        out['note'] = baseline_note
    return out


def build_country_pulse(iso3, today_str=None):
    """Fetch and analyze one country. Returns summary dict or None."""
    today_str = today_str or datetime.utcnow().strftime('%Y-%m-%d')
    cutoff = (datetime.utcnow() - timedelta(days=RETENTION_DAYS)).strftime('%Y-%m-%d')
    dataset_id = COUNTRY_DATASET_PATTERN.format(iso3=iso3.lower())
    package = _hdx_package_show(dataset_id)
    if not package:
        return {'iso3': iso3, 'status': 'no_dataset'}
    url, res_name, last_modified = _pick_csv_resource(package)
    if not url:
        return {'iso3': iso3, 'status': 'no_csv_resource'}
    monthly, parse_note = _parse_country_csv(url, cutoff)
    if monthly is None:
        return {'iso3': iso3, 'status': 'parse_failed', 'detail': parse_note}
    staples = {}
    for family, buckets in monthly.items():
        summary = _summarize_staple(family, buckets, today_str)
        if summary:
            staples[family] = summary
    if not staples:
        return {'iso3': iso3, 'status': 'no_recent_staple_rows', 'detail': parse_note}
    live = {k: v for k, v in staples.items() if v['band'] != 'stale'}
    bands_present = [v['band'] for v in live.values()]
    country_band = 'normal'
    for band in BAND_ORDER:
        if band in bands_present:
            country_band = band
    anomalous = sorted([k for k, v in live.items()
                        if v['band'] in ('watch', 'elevated', 'high')])
    newest_month = max(v['latest_month'] for v in staples.values())
    return {
        'iso3': iso3,
        'status': 'ok' if live else 'stale',
        'band': country_band if live else 'stale',
        'anomalous_staples': anomalous,
        'staples': staples,
        'data_as_of': newest_month,
        'hdx_resource': res_name,
        'hdx_last_modified': last_modified,
        'parse': parse_note,
    }


# ------------------------------------------------------------------
# Full scan + scheduler
# ------------------------------------------------------------------

def run_full_scan():
    """Scan every discoverable country. Returns the bundle written to Redis."""
    started = datetime.utcnow()
    print("[FoodPulse] full scan starting")
    countries = discover_country_list()
    results = {}
    failures = {}
    for i, iso3 in enumerate(countries):
        pulse = build_country_pulse(iso3)
        if pulse and pulse.get('status') == 'ok':
            results[iso3] = pulse
        elif pulse:
            failures[iso3] = pulse.get('status')
        if i < len(countries) - 1:
            time.sleep(PER_COUNTRY_SLEEP)
    anomalous_countries = sorted(
        [c for c, p in results.items() if p['band'] in ('watch', 'elevated', 'high')],
        key=lambda c: BAND_ORDER.index(results[c]['band']), reverse=True)
    bundle = {
        'module': 'food_price_pulse',
        'version': '1.0.0',
        'generated_at': started.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'scan_seconds': int((datetime.utcnow() - started).total_seconds()),
        'coverage': {
            'countries_attempted': len(countries),
            'countries_with_data': len(results),
            'countries_anomalous': len(anomalous_countries),
            'failures': failures,
        },
        'anomalous_countries': anomalous_countries,
        'countries': results,
        'source': SOURCE_ATTRIBUTION,
        'disclaimer': CONVERGENCE_DISCLAIMER,
    }
    ok = _redis_set_bundle(bundle)
    print("[FoodPulse] full scan complete: %d/%d countries, %d anomalous, redis=%s, %ds"
          % (len(results), len(countries), len(anomalous_countries), ok,
             bundle['scan_seconds']))
    return bundle


def _bundle_is_fresh(bundle):
    if not bundle:
        return False
    try:
        gen = datetime.strptime(bundle['generated_at'], '%Y-%m-%dT%H:%M:%SZ')
        return (datetime.utcnow() - gen) < timedelta(days=PULSE_REFRESH_DAYS)
    except Exception:
        return False


def _scheduler_loop():
    time.sleep(180)  # boot delay: let the app settle before first heavy scan
    while True:
        try:
            if _acquire_scheduler_lock('food_price_pulse', 3 * 3600):
                bundle = _redis_get_bundle()
                if not _bundle_is_fresh(bundle):
                    with _scan_lock:
                        _scan_in_progress['active'] = True
                        _scan_in_progress['started'] = datetime.utcnow().isoformat()
                    try:
                        run_full_scan()
                    finally:
                        _scan_in_progress['active'] = False
                else:
                    print("[FoodPulse] bundle fresh; scheduler sleeping")
            else:
                print("[FoodPulse] another worker owns the scan lock; standing down")
        except Exception as e:
            print("[FoodPulse] scheduler error: %s" % e)
        time.sleep(6 * 3600)  # re-check every 6 hours


def _start_background_scan():
    """Kick a full scan on a daemon thread (used by ?force=true)."""
    if _scan_in_progress['active']:
        return False
    def _job():
        with _scan_lock:
            _scan_in_progress['active'] = True
            _scan_in_progress['started'] = datetime.utcnow().isoformat()
        try:
            run_full_scan()
        finally:
            _scan_in_progress['active'] = False
    threading.Thread(target=_job, daemon=True).start()
    return True


# ------------------------------------------------------------------
# Flask registration
# ------------------------------------------------------------------

def register_food_price_pulse_endpoints(app, start_scheduler=True):
    from flask import jsonify, request

    @app.route('/api/food-price-pulse')
    def api_food_price_pulse():
        force = request.args.get('force', '').lower() == 'true'
        full = request.args.get('full', '').lower() == 'true'
        if force:
            started = _start_background_scan()
            return jsonify({
                'status': 'scan_started' if started else 'scan_already_running',
                'note': 'Full scan covers roughly 98 countries and takes several minutes. Poll this endpoint without force=true.',
            }), 202
        bundle = _redis_get_bundle()
        if not bundle:
            return jsonify({
                'status': 'warming',
                'note': 'No bundle in cache yet. Trigger with ?force=true or wait for the weekly scheduler.',
                'scan_in_progress': _scan_in_progress['active'],
                'disclaimer': CONVERGENCE_DISCLAIMER,
            })
        if full:
            return jsonify(bundle)
        compact = {k: v for k, v in bundle.items() if k != 'countries'}
        compact['countries_anomalous_detail'] = {
            c: {
                'band': bundle['countries'][c]['band'],
                'anomalous_staples': bundle['countries'][c]['anomalous_staples'],
                'data_as_of': bundle['countries'][c]['data_as_of'],
            }
            for c in bundle.get('anomalous_countries', [])
            if c in bundle.get('countries', {})
        }
        compact['note'] = 'Use ?full=true for all country detail, or /api/food-price-pulse/<iso3>.'
        return jsonify(compact)

    @app.route('/api/food-price-pulse/<iso3>')
    def api_food_price_pulse_country(iso3):
        iso3 = iso3.strip().upper()
        force = request.args.get('force', '').lower() == 'true'
        if not force:
            bundle = _redis_get_bundle()
            if bundle and iso3 in (bundle.get('countries') or {}):
                out = dict(bundle['countries'][iso3])
                out['source'] = SOURCE_ATTRIBUTION
                out['disclaimer'] = CONVERGENCE_DISCLAIMER
                out['from_cache'] = True
                return jsonify(out)
        pulse = build_country_pulse(iso3) or {'iso3': iso3, 'status': 'error'}
        pulse['source'] = SOURCE_ATTRIBUTION
        pulse['disclaimer'] = CONVERGENCE_DISCLAIMER
        pulse['from_cache'] = False
        return jsonify(pulse)

    @app.route('/api/food-price-pulse/recon')
    def api_food_price_pulse_recon():
        """Live source-discovery smoke test. Cheap: two CKAN calls, no scan."""
        report = {'checks': {}, 'disclaimer': CONVERGENCE_DISCLAIMER}
        pkg = _hdx_package_show(GLOBAL_DATASET_ID)
        url, name, mod = _pick_csv_resource(pkg, name_hint='countries')
        report['checks']['global_index'] = {
            'dataset_reachable': bool(pkg),
            'countries_csv_found': bool(url),
            'resource_name': name,
            'last_modified': mod,
        }
        pkg_jor = _hdx_package_show(COUNTRY_DATASET_PATTERN.format(iso3='jor'))
        url_j, name_j, mod_j = _pick_csv_resource(pkg_jor)
        report['checks']['jordan_dataset'] = {
            'dataset_reachable': bool(pkg_jor),
            'csv_found': bool(url_j),
            'resource_name': name_j,
            'last_modified': mod_j,
        }
        report['verdict'] = ('ok' if (url and url_j) else 'degraded')
        return jsonify(report)

    @app.route('/debug/food-price-pulse')
    def debug_food_price_pulse():
        bundle = _redis_get_bundle()
        return jsonify({
            'bundle_present': bool(bundle),
            'bundle_generated_at': (bundle or {}).get('generated_at'),
            'bundle_fresh': _bundle_is_fresh(bundle),
            'coverage': (bundle or {}).get('coverage'),
            'scan_in_progress': _scan_in_progress,
            'refresh_days': PULSE_REFRESH_DAYS,
            'worker': _SCHED_WORKER_ID,
        })

    if start_scheduler:
        threading.Thread(target=_scheduler_loop, daemon=True).start()
        print("[FoodPulse] weekly scheduler thread started (cross-worker lock)")

    print("[FoodPulse] endpoints registered: /api/food-price-pulse, /<iso3>, /recon, /debug")
