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
    'last_manual_update': '2026-05-01',
    'data_period': 'March 2 – April 30, 2026 (10-day ceasefire effective Apr 17, extended further 3 weeks)',
    'note': 'Static figures compiled from OCHA Flash Update #22 (30 April 2026), Lebanese MoPH, WHO, IOM DTM, and UN Women reporting. Ceasefire effective April 17 has held; tentative and uneven return movements observed but limited. Updated manually.',

    'casualties': {
        'killed': 2576,
        'injured': 7962,
        'children_killed': None,            # not separately reported in #22; was 130 mid-April
        'children_injured': None,
        'women_killed': None,                # not separately reported in #22; was 102 mid-April
        'rescue_workers_killed': 103,        # WHO: health workers + first responders cumulative
        'april8_single_day_killed': 203,
        'april8_single_day_wounded': 1150,
        'idf_soldiers_killed_in_lebanon': 16,
        'civilians_killed_in_israel': 2,
        'source': 'Lebanese Ministry of Public Health / OCHA Flash Update #22',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
        'as_of': '2026-04-30',
        'note': 'Cumulative since March 2, 2026. April 8 was the deadliest single day of the war — 203 killed, 1,150+ wounded in strikes on central Beirut without warning. April 29: 3 civil defence rescue workers killed in Tyre District (consecutive strikes on same building during rescue operation). 28 March: 9 rescue workers killed in single ambulance strike in Bint Jbeil; 3 journalists killed in Jezzine same day. Two civilians killed in Israel by Hezbollah attacks; 16 IDF soldiers died in Lebanon per Israel.'
    },

    'displacement': {
        'total_displaced_registered': 1000000,
        'total_displaced_pct_population': 20,
        'in_government_shelters': 119000,           # Apr 30 — down from 136K peak; reflects partial return after Apr 17 ceasefire
        'shelters_opened': 626,                       # Apr 30 — slight consolidation from 669
        'shelters_at_capacity': 'Operating at limits — fluid as ceasefire enables tentative returns',
        'cross_border_to_syria': 147823,              # IOM — since 1 March (latest IOM aggregate)
        'cross_border_to_jordan': 1800,               # unchanged from prior
        'previously_displaced_2024': 65000,
        'children_displaced': 300000,                  # initial appeal estimate; ~nearly 300K registered
        'pct_idps_outside_formal_shelter': 87,        # UN Women 30 March (slight improvement from 90%)
        'returns_since_ceasefire': 'Tentative, uneven; 21% reduction in collective-shelter population by Apr 20 then partial re-displacement',
        'source': 'OCHA Flash Update #22 / IOM DTM / UN Women',
        'source_urls': [
            'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
            'https://dtm.iom.int/lebanon',
            'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-19-escalation-hostilities-lebanon-20-april-2026',
        ],
        'as_of': '2026-04-30',
        'note': '1M+ displaced — ~20% of Lebanon\'s population. April 17 ceasefire enabled 21% reduction in collective-shelter population by April 20 (in Baalbek-Hermel down 85%; Bekaa down 56%); some governorates (Mount Lebanon, South) saw partial re-displacement in late April. 87% of IDPs reside outside formal shelters per UN Women. 147,823 individuals crossed into Syria via 3 PoEs since 1 March. Returns restricted by UXO, military presence, damaged bridges, and official warnings against premature returns.'
    },

    'shelters': {
        'total_shelters': 626,
        'at_full_capacity': 'Operating at variable capacity post-ceasefire',
        'capacity_percentage': None,                 # variable post-ceasefire
        'schools_as_shelters': 472,
        'children_education_affected': None,
        'school_aged_idps': None,
        'government_designated_sites': None,
        'source': 'OCHA Flash Update #22',
        'source_urls': [
            'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
        ],
        'as_of': '2026-04-30',
        'note': '626 collective shelters with 119,000+ IDPs as of April 30. 472 schools converted to shelters. 87% of IDPs outside formal shelters — with relatives, in unfinished buildings, or informal sites. UN Women has flagged elevated GBV, harassment, and exploitation risks in informal/host arrangements. Flash Appeal: $308.3M for March-May 2026 — only 38% funded ($117M received).'
    },

    'evacuation_orders': {
        'active_orders': True,
        'territory_covered_sqkm': 1470,
        'territory_pct_lebanon': 14,
        'areas': [
            'Entire area south of the Litani River (~850 sq km, 500,000+ people)',
            'Litani to Zahrani river zone (expanded order)',
            'Beirut Southern Suburbs — multiple orders since March 2',
            'Central Beirut neighborhoods — April 8 orders (without warning)',
            '110+ towns and locations near the Blue Line',
            'Tyre district including Palestinian camps',
            'Masnaa Border Crossing area (April 3-8, now reopened)',
        ],
        'source': 'OCHA Flash Update #22 / Lebanese Civil Defence / IDF statements',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
        'as_of': '2026-04-30',
        'note': 'Displacement orders cover ~14% of Lebanese territory. Continued shelling, airstrikes, demolitions and movement restrictions reported particularly in southern Lebanon and parts of Nabatieh and Bekaa governorates despite April 17 ceasefire. Conditions have not enabled safe and sustained returns.'
    },

    'healthcare': {
        'health_workers_killed_since_mar2': 103,
        'health_workers_injured_since_mar2': 234,
        'healthcare_attacks_since_mar2': 131,
        'hospitals_closed': 6,
        'hospitals_damaged': 15,
        'phccs_closed': 51,
        'phccs_damaged': 7,
        'phccs_emergency_only': None,
        'iom_patients_reached': 5922,
        'iom_tb_screening': 3173,
        'unifil_peacekeepers_killed': 3,            # Indonesian contingent (29-30 March)
        'source': 'WHO / Lebanese MoPH / OCHA Flash Update #22 / UNIFIL',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
        'as_of': '2026-04-30',
        'note': 'WHO has documented 131+ attacks on healthcare since March 2: 103 health workers killed, 234 injured. Six hospitals closed and 15 damaged; 51 PHCCs closed and 7 damaged. Three Indonesian UNIFIL peacekeepers killed in late March (Ett-Taibe + Bani Hayyan incidents). IOM emergency transportation funding exhausted — critical service gap. The April 8 mass casualty event (203 killed, 1,150+ wounded in central Beirut) overwhelmed surviving facilities.'
    },

    'food_security': {
        'people_in_ipc_phase3_or_above': 1240000,
        'pct_population_food_insecure': 24,
        'period': 'April – August 2026 projection',
        'driver': 'Escalation since March, large-scale displacement, livelihood disruption, projected aid decline',
        'source': 'Lebanon Acute Food Insecurity Report (cited in OCHA Flash Update #22)',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
        'as_of': '2026-04-30',
        'note': '1.24M people (~24% of assessed population) projected to face acute food insecurity at IPC Phase 3 (Crisis) or above between April-August 2026 — significant increase from prior periods. Food remains nationally available but affordability is the primary constraint as prices rise and incomes decline.'
    },

    'flash_appeal': {
        'amount_usd':              308300000,
        'period':                  'March – May 2026',
        'target_beneficiaries':    1000000,
        'launched':                '2026-03-13',
        'received_usd':            117000000,
        'funded_pct':              38,
        'unfunded_usd':            191300000,
        'source':                  'OCHA Flash Appeal Lebanon March-May 2026 / OCHA Funding Tracker',
        'source_url':              'https://www.unocha.org/publications/report/lebanon/flash-appeal-lebanon-march-may-2026-march-2026-enar',
        'note':                    'Launched jointly with GoL by UN Secretary-General Guterres during March 13 solidarity visit to Beirut. As of late April, $117M received against $308.3M target — only 38% funded. Funding shortfall is a key driver of projected food insecurity worsening through August 2026.'
    },

    'ceasefire': {
        'in_effect':         True,
        'effective_date':    '2026-04-17',
        'initial_duration':  '10 days',
        'extension':         'Further 3 weeks (as of late April)',
        'compliance':        'Holding broadly; localized strikes in southern Lebanon, Nabatieh, Bekaa continue',
        'source':            'OCHA Flash Update #22',
        'source_url':        'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
        'as_of':             '2026-04-30',
        'note':              '10-day ceasefire took effect April 17, 2026; subsequently extended for further 3 weeks. Some return movements observed but largely limited and tentative. Continued shelling, airstrikes, demolitions reported particularly in southern Lebanon. Lebanese government has banned all Hezbollah military activities; Hezbollah has rejected demand to surrender weapons. Direct Lebanese-Israeli diplomatic engagement reportedly underway despite Hezbollah opposition.'
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
