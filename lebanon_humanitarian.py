"""
Lebanon Humanitarian Data Module v1.0.0
March 2026

Fetches humanitarian crisis data from:
  - IOM DTM API v3 (displacement/IDP tracking - DYNAMIC)
  - ReliefWeb API (OCHA flash updates - DYNAMIC)
  - Static reference data (casualties, shelters, healthcare - updated manually)

Provides a unified /api/lebanon/humanitarian endpoint for the Lebanon
stability page humanitarian dashboard cards.

Env vars required:
  - DTM_API_KEY: IOM DTM API v3 subscription key
  - UPSTASH_REDIS_REST_URL: Redis cache URL
  - UPSTASH_REDIS_REST_TOKEN: Redis cache token
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta

# ========================================
# CONFIGURATION
# ========================================

DTM_API_KEY = os.environ.get('DTM_API_KEY')
DTM_BASE_URL = 'https://dtmapi.iom.int/api/v3'

# ReliefWeb API (open, no key needed)
RELIEFWEB_API_URL = 'https://api.reliefweb.int/v1'

# Redis (shared with main lebanon_stability.py)
UPSTASH_URL = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')
HUMANITARIAN_CACHE_KEY = 'lebanon_humanitarian'

# ========================================
# DTM API — IDP DISPLACEMENT DATA
# ========================================

def fetch_dtm_displacement():
    """
    Fetch Lebanon IDP data from IOM DTM API v3.
    Returns country-level and governorate-level displacement figures.
    """
    if not DTM_API_KEY:
        print("[DTM] ⚠️ No DTM_API_KEY configured")
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json'
    }

    result = {
        'source': 'IOM DTM API v3',
        'source_url': 'https://dtm.iom.int/lebanon',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'country_level': None,
        'governorate_level': [],
        'error': None
    }

    # Try country-level (Admin 0) data
    try:
        print("[DTM] Fetching Lebanon country-level IDP data...")
        params = {
            'CountryName': 'Lebanon',
            'FromReportingDate': '2025-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d')
        }
        response = requests.get(
            f'{DTM_BASE_URL}/idp-admin0-data',
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                # Get the most recent round
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
                    print(f"[DTM] ✅ Country-level: {most_recent.get('numPresentIdpInd', 0):,} IDPs (Round {most_recent.get('roundNumber', '?')})")
            else:
                print("[DTM] Country-level: No data returned")
        else:
            print(f"[DTM] Country-level: HTTP {response.status_code}")
            # Try alternate endpoint format
            try:
                alt_response = requests.get(
                    f'{DTM_BASE_URL}/IdpAdmin0Data',
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
                            print(f"[DTM] ✅ Alt endpoint: {most_recent.get('numPresentIdpInd', 0):,} IDPs")
            except Exception as e:
                print(f"[DTM] Alt endpoint error: {str(e)[:100]}")

    except Exception as e:
        result['error'] = f"DTM country-level error: {str(e)[:200]}"
        print(f"[DTM] ❌ Country-level error: {str(e)[:200]}")

    # Try governorate-level (Admin 1) data
    try:
        print("[DTM] Fetching Lebanon governorate-level IDP data...")
        params = {
            'CountryName': 'Lebanon',
            'FromReportingDate': '2025-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d')
        }
        response = requests.get(
            f'{DTM_BASE_URL}/idp-admin1-data',
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                # Group by admin1 and get latest round for each
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
                print(f"[DTM] ✅ Governorate-level: {len(result['governorate_level'])} governorates, {total_gov:,} total IDPs")
        else:
            print(f"[DTM] Governorate-level: HTTP {response.status_code}")

    except Exception as e:
        print(f"[DTM] Governorate-level error: {str(e)[:200]}")

    return result


# ========================================
# RELIEFWEB API — OCHA FLASH UPDATES
# ========================================

def fetch_reliefweb_updates():
    """
    Fetch latest OCHA Flash Updates for Lebanon from ReliefWeb API.
    Returns the most recent reports with key humanitarian data.
    """
    result = {
        'source': 'ReliefWeb API (OCHA)',
        'source_url': 'https://reliefweb.int/country/lbn',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None
    }

    try:
        print("[ReliefWeb] Fetching Lebanon flash updates...")
        params = {
            'appname': 'asifah-analytics',
            'filter[field]': 'country.iso3',
            'filter[value]': 'LBN',
            'filter[operator]': 'AND',
            'sort[]': 'date:desc',
            'limit': 10,
            'fields[include][]': ['title', 'date.created', 'url_alias', 'source.name', 'body-html'],
        }

        # Search for flash updates specifically
        search_params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Lebanon flash update escalation hostilities',
            'query[operator]': 'AND',
            'sort[]': 'date:desc',
            'limit': 5,
            'fields[include][]': ['title', 'date.created', 'url_alias', 'source.name'],
        }

        response = requests.get(
            f'{RELIEFWEB_API_URL}/reports',
            params=search_params,
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            reports = data.get('data', [])

            for report in reports[:5]:
                fields = report.get('fields', {})
                result['reports'].append({
                    'title': fields.get('title', ''),
                    'date': fields.get('date', {}).get('created', ''),
                    'url': f"https://reliefweb.int{fields.get('url_alias', '')}",
                    'source': fields.get('source', [{}])[0].get('name', 'OCHA') if fields.get('source') else 'OCHA',
                })

            print(f"[ReliefWeb] ✅ Found {len(result['reports'])} reports")
        else:
            print(f"[ReliefWeb] HTTP {response.status_code}")
            result['error'] = f"HTTP {response.status_code}"

    except Exception as e:
        result['error'] = str(e)[:200]
        print(f"[ReliefWeb] ❌ Error: {str(e)[:200]}")

    return result


# ========================================
# STATIC HUMANITARIAN DATA
# (Updated manually from OCHA Flash Updates)
# ========================================

# Last updated from: OCHA Flash Update #3, March 7, 2026
# + UN News reporting, March 9, 2026
# + UNRWA Situation Report #1, March 6, 2026
# + UNFPA Flash Update, March 5, 2026

STATIC_HUMANITARIAN = {
    'last_manual_update': '2026-03-09',
    'data_period': 'March 2-9, 2026 (renewed hostilities)',
    'note': 'Static figures from OCHA/UNRWA/UNFPA reports. Updated manually.',

    'casualties': {
        'killed': 394,
        'injured': 1000,
        'children_killed': 83,
        'women_killed': 42,
        'rescue_workers_killed': 9,
        'source': 'Lebanese Ministry of Public Health via OCHA',
        'source_url': 'https://www.unocha.org/lebanon',
        'as_of': '2026-03-08',
        'note': 'Cumulative since renewed hostilities March 2, 2026'
    },

    'displacement': {
        'total_displaced_registered': 517000,
        'in_government_shelters': 117228,
        'shelters_opened': 399,
        'shelters_at_capacity': 357,
        'cross_border_to_syria': 37000,
        'cross_border_single_day_peak': 11000,
        'previously_displaced_2024': 65000,
        'source': 'IOM DTM / Ministry of Social Affairs / UNHCR',
        'source_urls': [
            'https://dtm.iom.int/lebanon',
            'https://www.unhcr.org/lb/',
        ],
        'as_of': '2026-03-08',
        'note': 'New displacement wave on top of 65,000 still displaced from 2024 conflict'
    },

    'shelters': {
        'total_shelters': 399,
        'at_full_capacity': 357,
        'capacity_percentage': 89.5,
        'unrwa_shelters': 2,
        'unrwa_registered': 1300,
        'unrwa_locations': ['Siblin Training Centre (Saida)', 'Nahr el-Bared (North Tripoli)'],
        'source': 'DRM / UNRWA',
        'source_urls': [
            'https://www.unrwa.org/resources/reports/unrwa-situation-report-1-lebanon-emergency-response-2026',
        ],
        'as_of': '2026-03-06'
    },

    'evacuation_orders': {
        'active_orders': True,
        'areas': [
            'Entire area south of the Litani River (~850 sq km, 500,000+ people)',
            'Beirut Southern Suburbs (issued 3 times since March 2)',
            '110+ towns and locations near the Blue Line',
            '50+ villages (forced evacuation orders March 3)'
        ],
        'hostile_incidents_drm': 694,
        'source': 'OCHA Flash Update #1-3',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-1-escalation-hostilities-lebanon-5-march-2026',
        'as_of': '2026-03-07'
    },

    'healthcare': {
        'facilities_attacked_since_oct_2023': 158,
        'health_workers_killed_since_oct_2023': 241,
        'health_workers_injured_since_oct_2023': 292,
        'source': 'WHO via OCHA',
        'source_url': 'https://www.who.int/countries/lbn',
        'as_of': '2026-03-07',
        'note': 'Cumulative since October 8, 2023'
    },

    'source_links': {
        'ocha': {
            'label': 'OCHA Lebanon',
            'url': 'https://www.unocha.org/lebanon',
            'icon': '🏛️'
        },
        'iom_dtm': {
            'label': 'IOM DTM Lebanon',
            'url': 'https://dtm.iom.int/lebanon',
            'icon': '📊'
        },
        'reliefweb': {
            'label': 'ReliefWeb Lebanon',
            'url': 'https://reliefweb.int/country/lbn',
            'icon': '📰'
        },
        'unrwa': {
            'label': 'UNRWA Emergency',
            'url': 'https://www.unrwa.org/resources/reports/unrwa-situation-report-1-lebanon-emergency-response-2026',
            'icon': '🏥'
        },
        'unhcr': {
            'label': 'UNHCR Lebanon',
            'url': 'https://www.unhcr.org/lb/',
            'icon': '🛡️'
        },
        'icrc': {
            'label': 'ICRC Near East',
            'url': 'https://www.icrc.org/en/where-we-work/middle-east',
            'icon': '🔴'
        },
        'unfpa': {
            'label': 'UNFPA Lebanon Crisis',
            'url': 'https://www.unfpa.org/resources/lebanon-crisis-regional-crisis-flash-update',
            'icon': '👩'
        },
        'who': {
            'label': 'WHO Lebanon',
            'url': 'https://www.who.int/countries/lbn',
            'icon': '🏥'
        },
        'moph': {
            'label': 'Lebanese MoPH',
            'url': 'https://www.moph.gov.lb/',
            'icon': '🇱🇧'
        }
    }
}


# ========================================
# COMBINED HUMANITARIAN ENDPOINT
# ========================================

def get_humanitarian_data(force_refresh=False):
    """
    Fetch all humanitarian data, combining DTM API + ReliefWeb + static.
    Uses Redis cache with 6-hour TTL.
    """
    cache_key = HUMANITARIAN_CACHE_KEY

    # Check Redis cache first (unless force refresh)
    if not force_refresh and UPSTASH_URL and UPSTASH_TOKEN:
        try:
            response = requests.get(
                f"{UPSTASH_URL}/get/{cache_key}",
                headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                timeout=5
            )
            data = response.json()
            if data.get('result'):
                cached = json.loads(data['result'])
                cached_at = cached.get('fetched_at', '')
                if cached_at:
                    try:
                        cached_time = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
                        age_hours = (datetime.now(timezone.utc) - cached_time).total_seconds() / 3600
                        if age_hours < 6:
                            print(f"[Humanitarian] Using cached data ({age_hours:.1f}h old)")
                            cached['from_cache'] = True
                            cached['cache_age_hours'] = round(age_hours, 1)
                            return cached
                    except:
                        pass
        except Exception as e:
            print(f"[Humanitarian] Cache read error: {str(e)[:100]}")

    # Fetch fresh data
    print("[Humanitarian] Fetching fresh data...")

    dtm_data = fetch_dtm_displacement()
    reliefweb_data = fetch_reliefweb_updates()

    # If DTM returned fresh IDP numbers, update the displacement card
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

        'casualties': STATIC_HUMANITARIAN['casualties'],
        'displacement': displacement_data,
        'shelters': STATIC_HUMANITARIAN['shelters'],
        'evacuation_orders': STATIC_HUMANITARIAN['evacuation_orders'],
        'healthcare': STATIC_HUMANITARIAN['healthcare'],

        'dtm_raw': dtm_data,
        'reliefweb_reports': reliefweb_data.get('reports', []) if reliefweb_data else [],

        'source_links': STATIC_HUMANITARIAN['source_links'],
    }

    # Cache to Redis
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            requests.post(
                f"{UPSTASH_URL}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_TOKEN}",
                    "Content-Type": "application/json"
                },
                json=["SET", cache_key, json.dumps(result)],
                timeout=5
            )
            print("[Humanitarian] ✅ Cached to Redis")
        except Exception as e:
            print(f"[Humanitarian] Cache write error: {str(e)[:100]}")

    return result


# ========================================
# REGISTER FLASK ENDPOINTS
# ========================================

def register_humanitarian_endpoints(app):
    """Register humanitarian endpoints on the Flask app."""

    @app.route('/api/lebanon/humanitarian', methods=['GET'])
    def api_humanitarian():
        """
        Get Lebanon humanitarian crisis data.
        Returns displacement, casualties, shelter, evacuation, and healthcare data.
        Query params:
          ?force=true — bypass cache and fetch fresh data
        """
        force = request.args.get('force', 'false').lower() == 'true'

        try:
            data = get_humanitarian_data(force_refresh=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)[:200],
                'static_fallback': STATIC_HUMANITARIAN
            }), 200

    @app.route('/api/lebanon/humanitarian/sources', methods=['GET'])
    def api_humanitarian_sources():
        """Return all humanitarian data source links."""
        return jsonify({
            'success': True,
            'sources': STATIC_HUMANITARIAN['source_links'],
            'note': 'These sources provide the latest humanitarian data for Lebanon. Visit them for the most current figures.'
        })

    @app.route('/debug/dtm', methods=['GET'])
    def debug_dtm():
        """Debug endpoint to test DTM API connection."""
        dtm_data = fetch_dtm_displacement()
        return jsonify({
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_base_url': DTM_BASE_URL,
            'result': dtm_data
        })

    print("[Lebanon] ✅ Humanitarian endpoints registered")
