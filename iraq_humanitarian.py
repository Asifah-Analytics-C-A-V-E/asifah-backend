"""
Iraq Humanitarian Data Module v1.0.0
March 2026

Fetches humanitarian crisis data from:
  - IOM DTM API v3 (displacement/IDP tracking - DYNAMIC)
  - ReliefWeb API (OCHA reports - DYNAMIC)
  - Static reference data (updated manually)

Provides /api/iraq/humanitarian endpoint for the Iraq stability page.

Env vars required (already set on ME backend):
  - DTM_API_KEY: IOM DTM API v3 subscription key
  - UPSTASH_REDIS_URL: Redis cache URL
  - UPSTASH_REDIS_TOKEN: Redis cache token

Context: Iraq faces compounding humanitarian crises —
  - Legacy displacement from 2014-2017 ISIS war (>1.2M still displaced)
  - New displacement from Iran-US war spillover (March 2026)
  - PMF/US airstrikes displacing civilians in western Iraq (Al-Qaim, Anbar)
  - US Embassy/Consulate attacks creating security displacement in Baghdad/Erbil
  - Ongoing ISIS insurgency in Diyala/Anbar/Nineveh

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

DTM_API_KEY    = os.environ.get('DTM_API_KEY')
DTM_BASE_URL   = 'https://dtmapi.iom.int/v3'

RELIEFWEB_API_URL = 'https://api.reliefweb.int/v1'

UPSTASH_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
CACHE_KEY     = 'iraq_humanitarian'

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
        print(f"[Iraq Redis] GET error: {str(e)[:100]}")
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
            print(f"[Iraq Redis] Saved key: {key}")
            return True
        return False
    except Exception as e:
        print(f"[Iraq Redis] SET error: {str(e)[:100]}")
        return False


# ========================================
# DTM API — IDP DISPLACEMENT DATA
# ========================================

def fetch_dtm_displacement():
    """
    Fetch Iraq IDP data from IOM DTM API v3.
    Iraq DTM tracks legacy ISIS-era displacement + ongoing conflict IDPs.
    """
    if not DTM_API_KEY:
        print("[Iraq DTM] No DTM_API_KEY configured")
        return None

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json'
    }

    result = {
        'source': 'IOM DTM API v3',
        'source_url': 'https://dtm.iom.int/iraq',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'country_level': None,
        'governorate_level': [],
        'error': None
    }

    # Country-level (Admin 0)
    try:
        print("[Iraq DTM] Fetching country-level IDP data...")
        params = {
            'CountryName': 'Iraq',
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
                    print(f"[Iraq DTM] Country-level: {most_recent.get('numPresentIdpInd', 0):,} IDPs")
            else:
                print("[Iraq DTM] Country-level: No data returned")
                # Try ISO code
                params['CountryName'] = 'Republic of Iraq'
                alt = requests.get(f'{DTM_BASE_URL}/displacement/admin0', headers=headers, params=params, timeout=15)
                if alt.status_code == 200:
                    data = alt.json()
                    if data and len(data) > 0:
                        latest = sorted(data, key=lambda x: x.get('reportingDate', ''), reverse=True)
                        if latest:
                            m = latest[0]
                            result['country_level'] = {
                                'total_idps': m.get('numPresentIdpInd', 0),
                                'reporting_date': m.get('reportingDate', ''),
                                'round_number': m.get('roundNumber', ''),
                                'operation': m.get('operation', ''),
                            }
                            print(f"[Iraq DTM] Alt name: {m.get('numPresentIdpInd', 0):,} IDPs")
        else:
            print(f"[Iraq DTM] Country-level: HTTP {response.status_code}")
            result['error'] = f"HTTP {response.status_code}"

    except Exception as e:
        result['error'] = f"DTM country-level error: {str(e)[:200]}"
        print(f"[Iraq DTM] Country error: {str(e)[:200]}")

    # Governorate-level (Admin 1)
    try:
        print("[Iraq DTM] Fetching governorate-level IDP data...")
        params = {
            'CountryName': 'Iraq',
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
                print(f"[Iraq DTM] Governorate-level: {len(result['governorate_level'])} governorates, {total_gov:,} total")
        else:
            print(f"[Iraq DTM] Governorate-level: HTTP {response.status_code}")

    except Exception as e:
        print(f"[Iraq DTM] Governorate error: {str(e)[:200]}")

    return result


# ========================================
# RELIEFWEB API — OCHA/UN REPORTS
# ========================================

def fetch_reliefweb_updates():
    """Fetch latest OCHA/UN reports for Iraq from ReliefWeb."""
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/irq',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None
    }

    try:
        print("[Iraq ReliefWeb] Fetching reports...")
        params = {
            'appname': 'asifah-analytics',
            'query[value]': 'Iraq displacement IDP humanitarian PMF conflict',
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
            print(f"[Iraq ReliefWeb] Found {len(result['reports'])} reports")
        else:
            result['error'] = f"HTTP {response.status_code}"

    except Exception as e:
        result['error'] = str(e)[:200]
        print(f"[Iraq ReliefWeb] Error: {str(e)[:200]}")

    return result


# ========================================
# STATIC HUMANITARIAN DATA
# ========================================
# Sources: IOM DTM Iraq, OCHA Iraq, UNHCR, NRC
# Reflects legacy ISIS-era displacement + March 2026 Iran-US war spillover

STATIC_HUMANITARIAN = {
    'last_manual_update': '2026-03-16',
    'data_period': 'Legacy displacement 2014-2026; active conflict tracking Mar 2026',
    'note': 'Static baseline from IOM DTM Iraq assessments + OCHA situation reports. Dynamic figures from DTM API.',

    'displacement': {
        'total_idps': 1200000,
        'conflict_idps': 950000,
        'isis_era_unresolved': 250000,
        'new_conflict_2026': 85000,  # estimate — Iran-US war spillover, PMF/US airstrikes
        'returnees_since_2017': 4800000,  # returned after ISIS defeat
        'still_displaced': 1200000,
        'resident_population': 42300000,
        'source': 'IOM DTM Iraq (baseline) + OCHA Iraq 2026',
        'source_url': 'https://dtm.iom.int/iraq',
        'as_of': '2026-03',
        'note': 'ISIS defeat (2017) enabled ~4.8M returns. ~1.2M remain displaced, concentrated in Sinjar (Yazidi), Diyala, Anbar, Nineveh. March 2026 Iran-US war generating new displacement in western Iraq.'
    },

    'sinjar_yazidi': {
        'status': 'ONGOING CRISIS',
        'estimated_displaced': 200000,
        'returnees': 90000,
        'blockers': 'Landmines, destroyed infrastructure, competing PKK/PMF/KRG authority, lack of services',
        'source': 'UNHCR / IOM DTM Sinjar Assessment',
        'source_url': 'https://dtm.iom.int/iraq',
        'as_of': '2025-12',
        'note': 'Yazidi genocide (2014) survivors — mass displacement to KRI camps. Political agreement blocking full returns. High trauma, missing persons still being identified.'
    },

    'march_2026_emergency': {
        'active': True,
        'trigger': 'Iran-US war spillover — US airstrikes on PMF bases (Al-Qaim, Anbar, western Iraq) + PMF attacks on US Embassy Baghdad, Consulate Erbil',
        'estimated_new_displacement': 85000,
        'hotspots': ['Al-Qaim (Anbar)', 'Jurf al-Sakhr (Babylon)', 'Balad (Salah al-Din)', 'Baghdad Green Zone perimeter'],
        'embassy_security_displacement': 'Residential areas near US Embassy Baghdad under active attack',
        'source': 'OCHA Iraq Flash Updates + IOM DTM Emergency Tracking',
        'source_url': 'https://reliefweb.int/country/irq',
        'as_of': '2026-03-16',
        'note': 'Rapidly evolving. PMF bases being targeted, civilian areas in western Iraq and Baghdad under fire. IOM emergency tracking activated.'
    },

    'camp_overview': {
        'camps_active': 26,
        'camp_population': 210000,
        'main_camps': [
            'Debaga Camp (Erbil) — former ISIS frontline displacement',
            'Laylan Camp (Sulaymaniyah) — Kirkuk displacement',
            'Anbar IDP sites — ongoing conflict displacement',
        ],
        'source': 'IOM DTM Iraq Round 128',
        'source_url': 'https://dtm.iom.int/iraq',
        'as_of': '2025-12',
    },

    'source_links': [
        {'name': 'IOM DTM Iraq',          'url': 'https://dtm.iom.int/iraq'},
        {'name': 'OCHA Iraq',             'url': 'https://www.unocha.org/iraq'},
        {'name': 'UNHCR Iraq',            'url': 'https://www.unhcr.org/countries/iraq'},
        {'name': 'ReliefWeb Iraq',        'url': 'https://reliefweb.int/country/irq'},
        {'name': 'NRC Iraq',              'url': 'https://www.nrc.no/countries/middle-east/iraq/'},
        {'name': 'Iraq Health Cluster',   'url': 'https://www.who.int/iraq'},
        {'name': 'WFP Iraq',              'url': 'https://www.wfp.org/countries/iraq'},
        {'name': 'Rudaw Humanitarian',    'url': 'https://www.rudaw.net/english/kurdistan'},
    ]
}


# ========================================
# MAIN FETCH — assembles full response
# ========================================

def _fetch_all_humanitarian():
    """Fetch all Iraq humanitarian data and assemble response."""
    print("[Iraq Humanitarian] Fetching all humanitarian data...")

    dtm_data     = fetch_dtm_displacement()
    reliefweb    = fetch_reliefweb_updates()

    # Merge DTM dynamic data over static baseline
    displacement = STATIC_HUMANITARIAN['displacement'].copy()
    if dtm_data and dtm_data.get('country_level'):
        cl = dtm_data['country_level']
        if cl.get('total_idps') and cl['total_idps'] > 0:
            displacement['dtm_api_idps']   = cl['total_idps']
            displacement['dtm_round']      = cl.get('round_number', '')
            displacement['dtm_as_of']      = cl.get('reporting_date', '')
            displacement['dtm_reason']     = cl.get('displacement_reason', '')

    result = {
        'success': True,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'from_cache': False,
        'country': 'Iraq',

        # Core displacement
        'displacement': displacement,

        # Active emergency (Iran-US war spillover)
        'march_2026_emergency': STATIC_HUMANITARIAN['march_2026_emergency'],

        # Sinjar / Yazidi
        'sinjar_yazidi': STATIC_HUMANITARIAN['sinjar_yazidi'],

        # Camp overview
        'camp_overview': STATIC_HUMANITARIAN['camp_overview'],

        # DTM governorate breakdown
        'dtm_governorate_level': dtm_data.get('governorate_level', []) if dtm_data else [],
        'dtm_source_info': {
            'source': dtm_data.get('source', 'IOM DTM API v3') if dtm_data else 'IOM DTM API v3',
            'source_url': dtm_data.get('source_url', 'https://dtm.iom.int/iraq') if dtm_data else 'https://dtm.iom.int/iraq',
            'error': dtm_data.get('error') if dtm_data else 'DTM_API_KEY not configured',
        },

        # ReliefWeb OCHA reports
        'reliefweb_reports': reliefweb.get('reports', []),
        'reliefweb_source': reliefweb.get('source_url', 'https://reliefweb.int/country/irq'),

        # Source links
        'source_links': STATIC_HUMANITARIAN['source_links'],

        'note': STATIC_HUMANITARIAN['note'],
        'last_manual_update': STATIC_HUMANITARIAN['last_manual_update'],
    }

    # Cache it
    if _redis_available():
        _redis_set(CACHE_KEY, result)

    return result


def get_humanitarian_data(force_refresh=False):
    """Get Iraq humanitarian data — Redis-first with 6-hour TTL."""
    if not force_refresh and _redis_available():
        cached = _redis_get(CACHE_KEY)
        if cached:
            cached_at = cached.get('fetched_at', '')
            if cached_at:
                try:
                    cached_time = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now(timezone.utc) - cached_time).total_seconds() / 3600
                    if age_hours < 6:
                        print(f"[Iraq Humanitarian] Using cached data ({age_hours:.1f}h old)")
                        cached['from_cache'] = True
                        cached['cache_age_hours'] = round(age_hours, 1)
                        return cached
                except Exception:
                    pass

    return _fetch_all_humanitarian()


# ========================================
# BACKGROUND REFRESH THREAD
# ========================================

def _background_humanitarian_refresh():
    """Background thread: refresh Iraq humanitarian data every 6 hours."""
    print("[Iraq Humanitarian] Background refresh thread started (6h cycle)")
    time.sleep(90)  # Boot delay
    while True:
        try:
            print("[Iraq Humanitarian] Running background refresh...")
            _fetch_all_humanitarian()
            print("[Iraq Humanitarian] Background refresh complete")
        except Exception as e:
            print(f"[Iraq Humanitarian] Background refresh error: {str(e)[:200]}")
        time.sleep(REFRESH_INTERVAL_SECONDS)


# ========================================
# REGISTER FLASK ENDPOINTS
# ========================================

def register_iraq_humanitarian_endpoints(app):
    """Register Iraq humanitarian endpoints on the Flask app."""

    @app.route('/api/iraq/humanitarian', methods=['GET'])
    def api_iraq_humanitarian():
        """
        Iraq humanitarian crisis data — IOM DTM + ReliefWeb + static baseline.
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
                    'march_2026_emergency': STATIC_HUMANITARIAN['march_2026_emergency'],
                    'source_links': STATIC_HUMANITARIAN['source_links'],
                }
            }), 200

    @app.route('/api/iraq/humanitarian/sources', methods=['GET'])
    def api_iraq_humanitarian_sources():
        """Return all Iraq humanitarian data source links."""
        return jsonify({
            'success': True,
            'sources': STATIC_HUMANITARIAN['source_links'],
        })

    @app.route('/debug/iraq-dtm', methods=['GET'])
    def debug_iraq_dtm():
        """Debug: test DTM API connection for Iraq."""
        dtm_data = fetch_dtm_displacement()
        return jsonify({
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_base_url': DTM_BASE_URL,
            'result': dtm_data
        })

    # Start background refresh thread
    bg_thread = threading.Thread(target=_background_humanitarian_refresh, daemon=True)
    bg_thread.start()

    print("[Iraq Humanitarian] ✅ Routes registered: "
          "/api/iraq/humanitarian, /api/iraq/humanitarian/sources, /debug/iraq-dtm")
