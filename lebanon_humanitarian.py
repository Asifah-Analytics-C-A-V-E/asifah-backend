"""
Lebanon Humanitarian Data Module v1.1.0
March 2026

Fetches humanitarian crisis data from:
  - IOM DTM API v3 (displacement/IDP tracking - DYNAMIC)
  - ReliefWeb API (OCHA flash updates - DYNAMIC)
  - Static reference data (casualties, shelters, healthcare - updated manually)

Provides a unified /api/lebanon/humanitarian endpoint for the Lebanon
stability page humanitarian dashboard cards.

Env vars required:
  - DTM_API_KEY: IOM DTM API v3 subscription key
  - RELIEFWEB_APPNAME: ReliefWeb registered app name (e.g. asifah-analytics)
  - UPSTASH_REDIS_REST_URL: Redis cache URL
  - UPSTASH_REDIS_REST_TOKEN: Redis cache token
"""

import os
import json
import requests
from flask import request, jsonify
from datetime import datetime, timezone, timedelta

# ========================================
# CONFIGURATION
# ========================================

DTM_API_KEY = os.environ.get('DTM_API_KEY')
DTM_BASE_URL = 'https://dtmapi.iom.int/v3'

# ReliefWeb API (open, but registered appname required)
RELIEFWEB_API_URL = 'https://api.reliefweb.int/v1'
RELIEFWEB_APPNAME = os.environ.get('RELIEFWEB_APPNAME', 'asifah-analytics')

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
                    print(f"[DTM] ✅ Country-level: {most_recent.get('numPresentIdpInd', 0):,} IDPs (Round {most_recent.get('roundNumber', '?')})")
            else:
                print("[DTM] Country-level: No data returned")
        else:
            print(f"[DTM] Country-level: HTTP {response.status_code}")

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
        search_params = {
            'appname': RELIEFWEB_APPNAME,
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

# Last updated: March 24, 2026
# Sources:
#   OCHA Flash Update #10, March 19, 2026
#   OCHA Flash Update #9, March 16, 2026
#   OCHA Flash Update #8, March 12-13, 2026
#   DRM Unit / Lebanese PM Office daily report, March 21, 2026
#   MoPH via The Intercept, mid-March 2026
#   OCHA Security Council briefing (Tom Fletcher), March 10, 2026
#   OCHA Flash Appeal Lebanon March-May 2026, launched March 13, 2026
#   IOM global displacement update, March 2026

STATIC_HUMANITARIAN = {
    'last_manual_update': '2026-03-24',
    'data_period': 'March 2 – 21, 2026 (renewed hostilities)',
    'note': 'Static figures compiled from OCHA Flash Updates #1–10 and DRM Unit daily reports. Updated manually.',

    'casualties': {
        'killed': 1024,
        'injured': 2740,
        'children_killed': 118,
        'children_injured': 332,
        'women_killed': None,
        'rescue_workers_killed': 31,
        'source': 'DRM Unit / Lebanese PM Office & MoPH',
        'source_url': 'https://www.unocha.org/lebanon',
        'as_of': '2026-03-21',
        'note': 'Cumulative since renewed hostilities March 2, 2026. UNICEF: equivalent of one classroom of children killed or wounded daily. 31 healthcare workers killed since March 2.'
    },

    'displacement': {
        'total_displaced_registered': 1200000,
        'total_displaced_pct_population': 19,
        'in_government_shelters': 134439,
        'shelters_opened': 636,
        'shelters_at_capacity': 'Majority overcrowded — limited electricity, heating, and WASH',
        'cross_border_to_syria': 37000,
        'previously_displaced_2024': 65000,
        'children_displaced': 300000,
        'source': 'OCHA Flash Update #10 / DRM Unit',
        'source_urls': [
            'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-10-escalation-hostilities-lebanon-19-march-2026',
            'https://dtm.iom.int/lebanon',
        ],
        'as_of': '2026-03-19',
        'note': '1.2M+ displaced — roughly 1 in 5 people in Lebanon. Only ~12.5% in formal collective shelters; majority with host families or in informal sites. Displacement orders now cover ~14% of Lebanese territory (1,470 sq km).'
    },

    'shelters': {
        'total_shelters': 636,
        'at_full_capacity': 'Majority exceeding safe standards',
        'capacity_percentage': 98,
        'schools_as_shelters': 472,
        'children_education_affected': None,
        'school_aged_idps': None,
        'government_designated_sites': None,
        'source': 'OCHA Flash Update #10',
        'source_urls': [
            'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-10-escalation-hostilities-lebanon-19-march-2026',
        ],
        'as_of': '2026-03-19',
        'note': '472 schools (public, private, TVET) converted to shelters. Many IDPs in cars, streets, unfinished buildings. Overcrowding raising disease, fire, and GBV risks. Flash Appeal requests $308.3M for March–May 2026.'
    },

    'evacuation_orders': {
        'active_orders': True,
        'territory_covered_sqkm': 1470,
        'territory_pct_lebanon': 14,
        'areas': [
            'Entire area south of the Litani River (~850 sq km, 500,000+ people)',
            'Litani to Zahrani river zone (expanded order)',
            'Beirut Southern Suburbs (issued multiple times since March 2)',
            '110+ towns and locations near the Blue Line',
            'Tyre district including Palestinian camps (March 17)',
            'Localized building/neighborhood orders in Beirut (ongoing)'
        ],
        'source': 'OCHA Flash Update #9 / DRM Unit',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-9-escalation-hostilities-lebanon-16-march-2026',
        'as_of': '2026-03-19',
        'note': 'Displacement orders now cover ~14% of Lebanon\'s territory. Many families displaced multiple times as orders expand geographically.'
    },

    'healthcare': {
        'health_workers_killed_since_mar2': 31,
        'health_workers_injured_since_mar2': None,
        'healthcare_attacks_since_mar2': 25,
        'hospitals_closed': 5,
        'phccs_closed': 49,
        'phccs_emergency_only': None,
        'source': 'OCHA Security Council briefing / MoPH / WHO',
        'source_url': 'https://www.unocha.org/news/un-relief-chief-tells-security-council-exhausted-lebanon-not-asking-help-oxygen',
        'as_of': '2026-03-19',
        'note': '5 hospitals and 49+ PHCCs closed in South and Beirut southern suburbs. WHO recorded 25 attacks on healthcare since Feb 28. Fuel shortages threatening hospital operations and water pumping.'
    },

    'flash_appeal': {
        'amount_usd': 308300000,
        'period': 'March – May 2026',
        'target_beneficiaries': 1000000,
        'launched': '2026-03-13',
        'source': 'OCHA Flash Appeal Lebanon March-May 2026',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/flash-appeal-lebanon-march-may-2026-march-2026-enar',
        'note': 'Launched jointly with GoL by UN Secretary-General Guterres during March 13 solidarity visit to Beirut.'
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

        'casualties': STATIC_HUMANITARIAN['casualties'],
        'displacement': displacement_data,
        'shelters': STATIC_HUMANITARIAN['shelters'],
        'evacuation_orders': STATIC_HUMANITARIAN['evacuation_orders'],
        'healthcare': STATIC_HUMANITARIAN['healthcare'],
        'flash_appeal': STATIC_HUMANITARIAN['flash_appeal'],

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
            'reliefweb_appname': RELIEFWEB_APPNAME,
            'result': dtm_data
        })

    print("[Lebanon] ✅ Humanitarian endpoints registered")
