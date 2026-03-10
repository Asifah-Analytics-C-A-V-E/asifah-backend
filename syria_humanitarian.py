"""
Syria Humanitarian Data Module v1.0.0
March 2026

Fetches humanitarian crisis data from:
  - IOM DTM API v3 (displacement/IDP tracking - DYNAMIC)
  - ReliefWeb API (OCHA reports - DYNAMIC)
  - Static reference data (casualties, camps, returns - updated manually)

Provides /api/syria/humanitarian endpoint for the Syria stability page.

Env vars required (already set on ME backend):
  - DTM_API_KEY: IOM DTM API v3 subscription key
  - UPSTASH_REDIS_URL: Redis cache URL
  - UPSTASH_REDIS_TOKEN: Redis cache token

Pattern: Redis-first caching with 6-hour TTL + background refresh.
"""

import os
import json
import requests
import threading
import time
from flask import request, jsonify
from datetime import datetime, timezone, timedelta

# ========================================
# CONFIGURATION
# ========================================

DTM_API_KEY = os.environ.get('DTM_API_KEY')
DTM_BASE_URL = 'https://dtmapi.iom.int/v3'

# ReliefWeb API (open, no key needed)
RELIEFWEB_API_URL = 'https://api.reliefweb.int/v1'

# Redis (same env vars as ME backend app.py)
UPSTASH_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
CACHE_KEY = 'syria_humanitarian'

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
        print(f"[Syria Redis] GET error: {str(e)[:100]}")
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
            print(f"[Syria Redis] Saved key: {key}")
            return True
        return False
    except Exception as e:
        print(f"[Syria Redis] SET error: {str(e)[:100]}")
        return False


# ========================================
# DTM API — IDP DISPLACEMENT DATA
# ========================================

def fetch_dtm_displacement():
    """
    Fetch Syria IDP data from IOM DTM API v3.
    Returns country-level and governorate-level displacement figures.
    """
    if not DTM_API_KEY:
        print("[Syria DTM] No DTM_API_KEY configured")
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json'
    }

    result = {
        'source': 'IOM DTM API v3',
        'source_url': 'https://dtm.iom.int/syrian-arab-republic',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'country_level': None,
        'governorate_level': [],
        'error': None
    }

    # Country-level (Admin 0)
    try:
        print("[Syria DTM] Fetching country-level IDP data...")
        params = {
            'CountryName': 'Syrian Arab Republic',
            'FromReportingDate': '2024-01-01',
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
                    print(f"[Syria DTM] Country-level: {most_recent.get('numPresentIdpInd', 0):,} IDPs")
            else:
                print("[Syria DTM] Country-level: No data returned")

                # Try alternate country name
                params['CountryName'] = 'Syria'
                alt_response = requests.get(
                    f'{DTM_BASE_URL}/displacement/admin0',
                    headers=headers,
                    params=params,
                    timeout=15
                )
                if alt_response.status_code == 200:
                    data = alt_response.json()
                    if data and len(data) > 0:
                        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
                        if latest:
                            most_recent = latest[0]
                            result['country_level'] = {
                                'total_idps': most_recent.get('numPresentIdpInd', 0),
                                'reporting_date': most_recent.get('reportingDate', ''),
                                'round_number': most_recent.get('roundNumber', ''),
                                'operation': most_recent.get('operation', ''),
                            }
                            print(f"[Syria DTM] Alt name: {most_recent.get('numPresentIdpInd', 0):,} IDPs")
        else:
            print(f"[Syria DTM] Country-level: HTTP {response.status_code}")
            result['error'] = f"HTTP {response.status_code}"

    except Exception as e:
        result['error'] = f"DTM country-level error: {str(e)[:200]}"
        print(f"[Syria DTM] Country error: {str(e)[:200]}")

    # Governorate-level (Admin 1)
    try:
        print("[Syria DTM] Fetching governorate-level IDP data...")
        params = {
            'CountryName': 'Syrian Arab Republic',
            'FromReportingDate': '2024-01-01',
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
                    result['governorate_level'].append({
                        'governorate': admin1,
                        'idps': entry.get('numPresentIdpInd', 0),
                        'reporting_date': entry.get('reportingDate', ''),
                        'round': entry.get('roundNumber', ''),
                    })

                total_gov = sum(g['idps'] for g in result['governorate_level'])
                print(f"[Syria DTM] Governorate-level: {len(result['governorate_level'])} governorates, {total_gov:,} total")
        else:
            print(f"[Syria DTM] Governorate-level: HTTP {response.status_code}")

    except Exception as e:
        print(f"[Syria DTM] Governorate error: {str(e)[:200]}")

    return result


# ========================================
# RELIEFWEB API — OCHA/UN REPORTS
# ========================================

def fetch_reliefweb_updates():
    """Fetch latest OCHA/UN reports for Syria from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/syr',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None
    }

    try:
        print("[Syria ReliefWeb] Fetching reports...")
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Syria displacement IDP humanitarian returns',
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
            print(f"[Syria ReliefWeb] Found {len(result['reports'])} reports")
        else:
            result['error'] = f"HTTP {response.status_code}"

    except Exception as e:
        result['error'] = str(e)[:200]
        print(f"[Syria ReliefWeb] Error: {str(e)[:200]}")

    return result


# ========================================
# STATIC HUMANITARIAN DATA
# ========================================

# Sources: IOM DTM Baseline Assessments, OCHA, UNHCR
# Last updated from DTM Round 12 (Jan 2025) + March 2026 emergency tracking

STATIC_HUMANITARIAN = {
    'last_manual_update': '2026-03-10',
    'data_period': 'Ongoing since 2011; post-Assad transition Dec 2024; Aleppo/NES emergency Jan-Mar 2026',
    'note': 'Static figures from IOM DTM baseline assessments and OCHA reports. Updated manually.',

    'displacement': {
        'total_idps': 6994646,
        'idps_in_camps': 2110000,
        'idps_in_residential': 4880000,
        'idp_returnees': 1200000,
        'arrivals_from_abroad': 700000,
        'resident_population': 17700000,
        'source': 'IOM DTM Baseline Assessment (Round 12, Jan 2025)',
        'source_url': 'https://dtm.iom.int/syrian-arab-republic',
        'as_of': '2025-01-31',
        'note': 'Return trend intensified after Dec 2024 power shift. 70% of post-Jan 2026 Aleppo IDPs have returned.'
    },

    'al_hol_camp': {
        'status': 'CLOSED',
        'closure_date': '2026-02-22',
        'note': 'Al-Hol camp officially evacuated and closed Feb 22, 2026. Previously held ~50,000 residents including ISIS-affiliated families. Closure is a major security and humanitarian milestone.',
        'peak_population': 73000,
        'peak_year': 2019,
        'final_population_approx': 41000,
        'source': 'IOM DTM Emergency Mobility Tracking',
        'source_url': 'https://dtm.iom.int/syrian-arab-republic',
        'as_of': '2026-02-22'
    },

    'aleppo_emergency': {
        'active': True,
        'tracking_rounds': 14,
        'start_date': '2026-01-06',
        'trigger': 'Escalation of hostilities in Sheikh Maqsoud, Ashrafiyah, and Bani Zaid, Aleppo City',
        'peak_displacement': 148053,
        'peak_date': '2026-01-09',
        'current_estimate': 'Approx 70% have returned since peak',
        'sdf_ceasefire': 'Ceasefire and integration agreement announced Jan 30, 2026 — holding as of Mar 2026',
        'priority_needs': ['Cash assistance', 'Food', 'Non-food items', 'Shelter', 'Health services'],
        'source': 'IOM DTM Emergency Mobility Tracking Rounds 1-14',
        'source_url': 'https://dtm.iom.int/syrian-arab-republic',
        'as_of': '2026-03-04'
    },

    'cross_border_returns': {
        'total_arrivals_from_abroad': 700000,
        'main_countries_of_origin': ['Turkey', 'Lebanon', 'Jordan', 'Iraq', 'Egypt'],
        'driven_by': 'December 2024 power shift in Damascus; promises of inclusive government and recovery',
        'lattakia_aleppo_main_return_areas': True,
        'source': 'IOM DTM / UNHCR',
        'source_urls': [
            'https://dtm.iom.int/syrian-arab-republic',
            'https://www.unhcr.org/sy/',
        ],
        'as_of': '2025-03-31',
        'note': 'Return movement intensified January 2025 onward. Many returnees face destroyed homes and lack of services.'
    },

    'governance_transition': {
        'event': 'Fall of Assad regime',
        'date': '2024-12-08',
        'current_authority': 'Interim government (HTS-led transition)',
        'key_developments': [
            'Power shift in Damascus Dec 8, 2024',
            'IOM reestablished presence in Damascus Dec 15, 2024',
            'SDF-Government ceasefire and integration agreement Jan 30, 2026',
            'Al-Hol camp closed Feb 22, 2026',
            'Aleppo emergency stabilizing (70% returns)',
        ],
        'source': 'IOM / OCHA / multiple',
        'as_of': '2026-03-10'
    },

    'source_links': {
        'iom_dtm': {
            'label': 'IOM DTM Syria',
            'url': 'https://dtm.iom.int/syrian-arab-republic',
            'icon': '📊'
        },
        'iom_syria': {
            'label': 'IOM Syria',
            'url': 'https://syria.iom.int/iom-syria',
            'icon': '🌐'
        },
        'ocha': {
            'label': 'OCHA Syria',
            'url': 'https://www.unocha.org/syria',
            'icon': '🏛️'
        },
        'reliefweb': {
            'label': 'ReliefWeb Syria',
            'url': 'https://reliefweb.int/country/syr',
            'icon': '📰'
        },
        'unhcr': {
            'label': 'UNHCR Syria',
            'url': 'https://www.unhcr.org/sy/',
            'icon': '🛡️'
        },
        'unhcr_data': {
            'label': 'UNHCR Data Portal',
            'url': 'https://data.unhcr.org/en/situations/syria',
            'icon': '📈'
        },
        'acaps': {
            'label': 'ACAPS Syria',
            'url': 'https://www.acaps.org/en/countries/syria',
            'icon': '📋'
        },
        'syria_direct': {
            'label': 'Syria Direct',
            'url': 'https://syriadirect.org/',
            'icon': '📰'
        },
        'who': {
            'label': 'WHO Syria',
            'url': 'https://www.who.int/countries/syr',
            'icon': '🏥'
        }
    }
}


# ========================================
# COMBINED HUMANITARIAN FETCH
# ========================================

def _fetch_all_humanitarian():
    """Fetch all humanitarian data, combine DTM + ReliefWeb + static."""
    print("[Syria Humanitarian] Fetching fresh data...")

    dtm_data = fetch_dtm_displacement()
    reliefweb_data = fetch_reliefweb_updates()

    # If DTM returned fresh IDP numbers, overlay on static displacement card
    displacement_data = dict(STATIC_HUMANITARIAN['displacement'])
    if dtm_data and dtm_data.get('country_level'):
        dtm_idps = dtm_data['country_level'].get('total_idps', 0)
        if dtm_idps > 0:
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
        'al_hol_camp': STATIC_HUMANITARIAN['al_hol_camp'],
        'aleppo_emergency': STATIC_HUMANITARIAN['aleppo_emergency'],
        'cross_border_returns': STATIC_HUMANITARIAN['cross_border_returns'],
        'governance_transition': STATIC_HUMANITARIAN['governance_transition'],

        'dtm_raw': dtm_data,
        'reliefweb_reports': reliefweb_data.get('reports', []) if reliefweb_data else [],

        'source_links': STATIC_HUMANITARIAN['source_links'],
    }

    # Cache to Redis
    if _redis_available():
        _redis_set(CACHE_KEY, result)
        print("[Syria Humanitarian] Cached to Redis")

    return result


def get_humanitarian_data(force_refresh=False):
    """
    Get Syria humanitarian data — Redis-first with 6-hour TTL.
    """
    # Check cache (unless force refresh)
    if not force_refresh and _redis_available():
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached_at = cached.get('fetched_at', '')
            if cached_at:
                try:
                    cached_time = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now(timezone.utc) - cached_time).total_seconds() / 3600
                    if age_hours < 6:
                        print(f"[Syria Humanitarian] Using cached data ({age_hours:.1f}h old)")
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
    """Background thread: refresh Syria humanitarian data every 6 hours."""
    print("[Syria Humanitarian] Background refresh thread started (6h cycle)")
    # Initial delay — let the main app start first
    time.sleep(60)
    while True:
        try:
            print("[Syria Humanitarian] Running background refresh...")
            _fetch_all_humanitarian()
            print("[Syria Humanitarian] Background refresh complete")
        except Exception as e:
            print(f"[Syria Humanitarian] Background refresh error: {str(e)[:200]}")
        time.sleep(REFRESH_INTERVAL_SECONDS)


# ========================================
# REGISTER FLASK ENDPOINTS
# ========================================

def register_syria_humanitarian_endpoints(app):
    """Register Syria humanitarian endpoints on the Flask app."""

    @app.route('/api/syria/humanitarian', methods=['GET'])
    def api_syria_humanitarian():
        """
        Syria humanitarian crisis data.
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
                    'al_hol_camp': STATIC_HUMANITARIAN['al_hol_camp'],
                    'source_links': STATIC_HUMANITARIAN['source_links'],
                }
            }), 200

    @app.route('/api/syria/humanitarian/sources', methods=['GET'])
    def api_syria_humanitarian_sources():
        """Return all Syria humanitarian data source links."""
        return jsonify({
            'success': True,
            'sources': STATIC_HUMANITARIAN['source_links'],
        })

    @app.route('/debug/syria-dtm', methods=['GET'])
    def debug_syria_dtm():
        """Debug: test DTM API connection for Syria."""
        dtm_data = fetch_dtm_displacement()
        return jsonify({
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_base_url': DTM_BASE_URL,
            'result': dtm_data
        })

    # Start background refresh thread
    thread = threading.Thread(target=_background_humanitarian_refresh, daemon=True)
    thread.start()

    print("[Syria Humanitarian] Endpoints registered + background refresh started")
