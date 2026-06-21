"""
Libya Humanitarian / Displacement Data Module v1.0.0
June 2026

Cloned from syria_humanitarian.py (canonical DTM exemplar). Focused on
internal displacement (IDPs) — the page's article feed is already handled
by /api/threat/libya, so the Syria news subsystem is intentionally omitted.

Fetches:
  - IOM DTM API v3 (IDP displacement tracking - DYNAMIC, Path A)
  - ReliefWeb API (OCHA reports - DYNAMIC)
  - Static reference data (returnees, migrant-hub context - updated manually)

Provides /api/libya/humanitarian endpoint for the Libya stability page.

Env vars required (already set on ME backend):
  - DTM_API_KEY: IOM DTM API v3 subscription key
  - RELIEFWEB_APPNAME: ReliefWeb registered app name (e.g. asifah-analytics)
  - UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN: Redis cache

Pattern: Redis-first caching with 6-hour TTL + background refresh.
"""

import os
import json
import requests
import threading
import time
from flask import request, jsonify
from datetime import datetime, timezone

# ========================================
# CONFIGURATION
# ========================================

DTM_API_KEY = os.environ.get('DTM_API_KEY')
DTM_BASE_URL = 'https://dtmapi.iom.int/v3'

RELIEFWEB_API_URL = 'https://api.reliefweb.int/v1'
RELIEFWEB_APPNAME = os.environ.get('RELIEFWEB_APPNAME', 'asifah-analytics')

UPSTASH_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
CACHE_KEY = 'libya_humanitarian'

# Background refresh interval (6 hours)
REFRESH_INTERVAL_SECONDS = 6 * 3600


# ========================================
# REDIS HELPERS
# ========================================

def _redis_available():
    return bool(UPSTASH_URL and UPSTASH_TOKEN)


def _redis_get(key):
    try:
        response = requests.get(
            f"{UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            timeout=5
        )
        data = response.json()
        if data.get('result'):
            return json.loads(data['result'])
        return None
    except Exception as e:
        print(f"[Libya Redis] GET error: {str(e)[:100]}")
        return None


def _redis_set(key, value):
    try:
        response = requests.post(
            f"{UPSTASH_URL}",
            headers={
                "Authorization": f"Bearer {UPSTASH_TOKEN}",
                "Content-Type": "application/json"
            },
            json=["SET", key, json.dumps(value)],
            timeout=5
        )
        result = response.json()
        if result.get('result') == 'OK':
            print(f"[Libya Redis] Saved key: {key}")
            return True
        return False
    except Exception as e:
        print(f"[Libya Redis] SET error: {str(e)[:100]}")
        return False


# ========================================
# UNHCR REFUGEE LAYER (reads shared Redis — populated by unhcr_feeds.py scanner)
# ========================================

def _read_unhcr_layer():
    """
    Read the UNHCR refugee/asylum layer for Libya from shared Redis.

    Returns a DISTINCT 'refugees' block — deliberately NOT merged with the DTM
    'displacement' block. These are different populations:
      - DTM IDPs        = internally displaced LIBYANS (DTM owns the IDP line)
      - UNHCR hosted    = INBOUND foreign refugees/asylum-seekers IN Libya
      - DTM migrants    = transit-migrant presence (separate definition again)
    Overlapping populations on different definitions -> NOT additive.
    Fails soft: returns None if the UNHCR scanner hasn't populated yet.
    """
    try:
        u = _redis_get('unhcr:libya:latest')
        if not isinstance(u, dict):
            return None
        hosted = u.get('hosted') or {}
        originated = u.get('originated') or {}
        if not hosted and not originated:
            return None
        return {
            'hosted_total':           hosted.get('total'),
            'hosted_refugees':        hosted.get('refugees'),
            'hosted_asylum_seekers':  hosted.get('asylum_seekers'),
            'top_origins':            hosted.get('top_origins', []),
            'originated_total_fled':  originated.get('total_fled'),
            'originated_idps_unhcr':  originated.get('idps'),
            'top_destinations':       originated.get('top_destinations', []),
            'data_year':              hosted.get('data_year') or originated.get('data_year'),
            'source':                 u.get('source', 'UNHCR Refugee Data Finder'),
            'source_url':             u.get('source_url', 'https://www.unhcr.org/refugee-statistics/'),
            'data_as_of':             u.get('data_as_of'),
            'note': ('Inbound foreign refugees/asylum-seekers sheltering in Libya. '
                     'Distinct from DTM internal IDPs and DTM transit-migrant counts — '
                     'overlapping populations measured on different definitions, NOT additive.'),
        }
    except Exception as e:
        print(f"[Libya UNHCR] read error: {str(e)[:100]}")
        return None


# ========================================
# DTM API — IDP DISPLACEMENT DATA (Path A, live)
# ========================================

def fetch_dtm_displacement():
    """
    Fetch Libya IDP data from IOM DTM API v3.
    Returns country-level (Admin 0) and region-level (Admin 1) displacement figures.
    """
    if not DTM_API_KEY:
        print("[Libya DTM] No DTM_API_KEY configured")
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json'
    }

    result = {
        'source': 'IOM DTM API v3',
        'source_url': 'https://dtm.iom.int/libya',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'country_level': None,
        'region_level': [],
        'error': None
    }

    # Country-level (Admin 0)
    try:
        print("[Libya DTM] Fetching country-level IDP data...")
        params = {
            'CountryName': 'Libya',
            'FromReportingDate': '2023-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d')
        }
        response = requests.get(
            f'{DTM_BASE_URL}/displacement/admin0',
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
                if latest:
                    most_recent = latest[0]
                    result['country_level'] = {
                        'total_idps': most_recent.get('numPresentIdpInd', 0),
                        'reporting_date': most_recent.get('reportingDate', ''),
                        'round_number': most_recent.get('roundNumber', ''),
                        'operation': most_recent.get('operation', ''),
                        'displacement_reason': most_recent.get('displacementReason', ''),
                        'males': most_recent.get('numberMales', 0),
                        'females': most_recent.get('numberFemales', 0),
                    }
                    print(f"[Libya DTM] Country-level: {most_recent.get('numPresentIdpInd', 0):,} IDPs")
            else:
                print("[Libya DTM] Country-level: No data returned")
        else:
            print(f"[Libya DTM] Country-level: HTTP {response.status_code}")
            result['error'] = f"HTTP {response.status_code}"

    except Exception as e:
        result['error'] = f"DTM country-level error: {str(e)[:200]}"
        print(f"[Libya DTM] Country error: {str(e)[:200]}")

    # Region-level (Admin 1)
    try:
        print("[Libya DTM] Fetching region-level IDP data...")
        params = {
            'CountryName': 'Libya',
            'FromReportingDate': '2023-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d')
        }
        response = requests.get(
            f'{DTM_BASE_URL}/displacement/admin1',
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                admin1_latest = {}
                for entry in data:
                    admin1 = entry.get('admin1Name', 'Unknown')
                    date = entry.get('reportingDate', '')
                    if admin1 not in admin1_latest or date > admin1_latest[admin1].get('reportingDate', ''):
                        admin1_latest[admin1] = entry

                for admin1, entry in sorted(admin1_latest.items()):
                    result['region_level'].append({
                        'region': admin1,
                        'idps': entry.get('numPresentIdpInd', 0),
                        'reporting_date': entry.get('reportingDate', ''),
                        'round': entry.get('roundNumber', ''),
                    })

                total_reg = sum(r['idps'] for r in result['region_level'])
                print(f"[Libya DTM] Region-level: {len(result['region_level'])} regions, {total_reg:,} total")
        else:
            print(f"[Libya DTM] Region-level: HTTP {response.status_code}")

    except Exception as e:
        print(f"[Libya DTM] Region error: {str(e)[:200]}")

    return result


# ========================================
# RELIEFWEB API — OCHA/UN REPORTS
# ========================================

def fetch_reliefweb_updates():
    """Fetch latest OCHA/UN reports for Libya from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/lby',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None
    }

    try:
        print("[Libya ReliefWeb] Fetching reports...")
        params = {
            'appname': RELIEFWEB_APPNAME,
            'query[value]': 'Libya displacement IDP migration humanitarian returns',
            'query[operator]': 'AND',
            'sort[]': 'date:desc',
            'limit': 8,
            'fields[include][]': ['title', 'date.created', 'url_alias', 'source.name'],
        }

        response = requests.get(
            f'{RELIEFWEB_API_URL}/reports',
            params=params,
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            reports = data.get('data', [])
            for report in reports[:8]:
                fields = report.get('fields', {})
                result['reports'].append({
                    'title': fields.get('title', ''),
                    'date': fields.get('date', {}).get('created', ''),
                    'url': f"https://reliefweb.int{fields.get('url_alias', '')}",
                    'source': fields.get('source', [{}])[0].get('name', 'OCHA') if fields.get('source') else 'OCHA',
                })
            print(f"[Libya ReliefWeb] Found {len(result['reports'])} reports")
        else:
            result['error'] = f"HTTP {response.status_code}"
            print(f"[Libya ReliefWeb] HTTP {response.status_code}")

    except Exception as e:
        result['error'] = str(e)[:200]
        print(f"[Libya ReliefWeb] Error: {str(e)[:200]}")

    return result


# ========================================
# STATIC HUMANITARIAN DATA (fallback + context)
# ========================================
# NOTE (for Rachel): the live DTM API supersedes 'total_idps' whenever it
# returns data. The static IDP figure below is a last-known baseline —
# verify/update before citing. Migrant figures are well-sourced (DTM R61).

STATIC_HUMANITARIAN = {
    'last_manual_update': '2026-06-21',
    'data_period': 'Post-2011 fragmentation; east-west split since 2014; primary central-Med migrant transit hub',
    'note': 'Static figures from IOM DTM assessments and OCHA reports, updated manually. Live DTM API supersedes IDP figures when available.',

    'displacement': {
        'total_idps': 125000,
        'idp_returnees': 670000,
        'migrants_present': 936134,
        'resident_population': 7000000,
        'source': 'IOM DTM Libya (Mobility Tracking baseline + Migrant Report Round 61)',
        'source_url': 'https://dtm.iom.int/libya',
        'as_of': '2026-02-28',
        'note': 'IDP figure is an approximate last-known DTM baseline (VERIFY) — live API supersedes. Returnees per DTM mobility tracking. Migrants-present (936,134) from DTM Migrant Report Round 61 (Jan-Feb 2026).'
    },

    'migration_hub': {
        'role': 'Primary central-Mediterranean departure point toward Europe',
        'migrants_present': 936134,
        'top_nationalities': ['Sudan (36%)', 'Niger (20%)', 'Egypt (19%)', 'Chad (9%)', 'Nigeria (3%)'],
        'main_hubs': ['Tripoli', 'Benghazi', 'Misrata'],
        'border_flows_q1_2026': 'Cross-border inflows down 8%, outflows down 17% (DTM, Q1 2026)',
        'sudan_spillover': 'Sudanese now the largest group (36%) — arrivals via Alkufra driven by the Sudan war since April 2023',
        'source': 'IOM DTM Libya Migrant Report Round 61 (Jan-Feb 2026)',
        'source_url': 'https://dtm.iom.int/libya',
        'as_of': '2026-02-28'
    },

    'source_links': {
        'iom_dtm': {
            'label': 'IOM DTM Libya',
            'url': 'https://dtm.iom.int/libya',
            'icon': '📊'
        },
        'iom_libya': {
            'label': 'IOM Libya',
            'url': 'https://libya.iom.int/',
            'icon': '🌐'
        },
        'ocha': {
            'label': 'OCHA Libya',
            'url': 'https://www.unocha.org/libya',
            'icon': '🏛️'
        },
        'reliefweb': {
            'label': 'ReliefWeb Libya',
            'url': 'https://reliefweb.int/country/lby',
            'icon': '📰'
        },
        'unhcr': {
            'label': 'UNHCR Libya',
            'url': 'https://www.unhcr.org/libya',
            'icon': '🛡️'
        },
        'unhcr_data': {
            'label': 'UNHCR Data Portal',
            'url': 'https://data.unhcr.org/en/country/lby',
            'icon': '📈'
        }
    }
}


# ========================================
# COMBINED HUMANITARIAN FETCH
# ========================================

def _fetch_all_humanitarian():
    """Fetch all humanitarian data, combine DTM + ReliefWeb + static."""
    print("[Libya Humanitarian] Fetching fresh data...")

    dtm_data = fetch_dtm_displacement()
    reliefweb_data = fetch_reliefweb_updates()

    # If DTM returned fresh IDP numbers, overlay on static displacement card
    displacement_data = dict(STATIC_HUMANITARIAN['displacement'])
    if dtm_data and dtm_data.get('country_level'):
        dtm_idps = dtm_data['country_level'].get('total_idps', 0)
        if dtm_idps and dtm_idps > 0:
            displacement_data['dtm_api_idps'] = dtm_idps
            displacement_data['dtm_reporting_date'] = dtm_data['country_level'].get('reporting_date', '')
            displacement_data['dtm_round'] = dtm_data['country_level'].get('round_number', '')
            displacement_data['dtm_source'] = 'IOM DTM API v3 (live)'

    result = {
        'success': True,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'from_cache': False,
        'data_period': STATIC_HUMANITARIAN['data_period'],
        'last_manual_update': STATIC_HUMANITARIAN['last_manual_update'],

        'displacement': displacement_data,
        'migration_hub': STATIC_HUMANITARIAN['migration_hub'],

        'dtm_raw': dtm_data,
        'reliefweb_reports': reliefweb_data.get('reports', []) if reliefweb_data else [],
        'reliefweb_appname': RELIEFWEB_APPNAME,

        'source_links': STATIC_HUMANITARIAN['source_links'],
    }

    # UNHCR refugee/asylum layer (inbound foreign refugees — distinct from DTM IDPs)
    unhcr_layer = _read_unhcr_layer()
    if unhcr_layer:
        result['refugees'] = unhcr_layer

    if _redis_available():
        _redis_set(CACHE_KEY, result)
        print("[Libya Humanitarian] Cached to Redis")

    return result


def get_humanitarian_data(force_refresh=False):
    """Get Libya humanitarian data — Redis-first with 6-hour TTL."""
    if not force_refresh and _redis_available():
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached_at = cached.get('fetched_at', '')
            if cached_at:
                try:
                    cached_time = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now(timezone.utc) - cached_time).total_seconds() / 3600
                    if age_hours < 6:
                        print(f"[Libya Humanitarian] Using cached data ({age_hours:.1f}h old)")
                        cached['from_cache'] = True
                        cached['cache_age_hours'] = round(age_hours, 1)
                        return cached
                except:
                    pass

    return _fetch_all_humanitarian()


# ========================================
# BACKGROUND REFRESH THREAD
# ========================================

def _background_humanitarian_refresh():
    """Background thread: refresh Libya humanitarian data every 6 hours."""
    print("[Libya Humanitarian] Background refresh thread started (6h cycle)")
    time.sleep(90)  # Boot delay
    while True:
        try:
            print("[Libya Humanitarian] Running background refresh...")
            _fetch_all_humanitarian()
            print("[Libya Humanitarian] Background refresh complete")
        except Exception as e:
            print(f"[Libya Humanitarian] Background refresh error: {str(e)[:200]}")
        time.sleep(REFRESH_INTERVAL_SECONDS)


# ========================================
# REGISTER FLASK ENDPOINTS
# ========================================

def register_libya_humanitarian_endpoints(app):
    """Register Libya humanitarian endpoints on the Flask app."""

    @app.route('/api/libya/humanitarian', methods=['GET'])
    def api_libya_humanitarian():
        """
        Libya displacement / migration data (live DTM IDPs + static context).
        Query params: ?force=true to bypass cache.
        """
        force = request.args.get('force', 'false').lower() == 'true'
        try:
            data = get_humanitarian_data(force_refresh=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)[:200],
                'static_fallback': {
                    'displacement': STATIC_HUMANITARIAN['displacement'],
                    'migration_hub': STATIC_HUMANITARIAN['migration_hub'],
                    'source_links': STATIC_HUMANITARIAN['source_links'],
                }
            }), 200

    @app.route('/api/libya/humanitarian/sources', methods=['GET'])
    def api_libya_humanitarian_sources():
        """Return all Libya humanitarian data source links."""
        return jsonify({
            'success': True,
            'sources': STATIC_HUMANITARIAN['source_links'],
        })

    @app.route('/debug/libya-dtm', methods=['GET'])
    def debug_libya_dtm():
        """Debug: test DTM API connection for Libya."""
        dtm_data = fetch_dtm_displacement()
        return jsonify({
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_base_url': DTM_BASE_URL,
            'reliefweb_appname': RELIEFWEB_APPNAME,
            'result': dtm_data
        })

    # Start background refresh thread
    thread = threading.Thread(target=_background_humanitarian_refresh, daemon=True)
    thread.start()

    print("[Libya Humanitarian] Endpoints registered + background refresh started")
