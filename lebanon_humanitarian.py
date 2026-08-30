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
    'last_manual_update': '2026-08-30',
    'data_period': 'March 2 – August 2026 (ceasefire nominally holding since Apr 17; near-daily Israeli strikes and airspace violations continue)',
    'note': 'Static figures compiled from OCHA Flash Update #22 (30 April 2026), Lebanese MoPH, WHO, IOM DTM, UN Women, UNIFIL, French MoD reporting. Ceasefire effective April 17 has held but UNIFIL peacekeeper attacks continue (April 18 Hezbollah-attributed ambush killed 2 French peacekeepers; April 24 Indonesian death from March wounds). Updated manually.',

    'casualties': {
        'killed': 4319,                      # MoPH via OCHA Flash Update #41, 6 July 2026
        'injured': 12203,
        'children_killed': 253,
        'children_injured': 1036,
        'women_killed': 392,
        'women_injured': 1450,
        'rescue_workers_killed': 135,        # health care professionals killed ON DUTY since 2 March
        'rescue_workers_injured': 406,
        'april8_single_day_killed': 203,
        'april8_single_day_wounded': 1150,
        'idf_soldiers_killed_in_lebanon': 16,
        'civilians_killed_in_israel': 2,
        'source': 'Lebanese Ministry of Public Health / OCHA Flash Update #41 (6 July 2026)',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
        'as_of': '2026-04-30',
        'note': 'Cumulative since March 2, 2026. April 8 was the deadliest single day of the war — 203 killed, 1,150+ wounded in strikes on central Beirut without warning. April 29: 3 civil defence rescue workers killed in Tyre District (consecutive strikes on same building during rescue operation). 28 March: 9 rescue workers killed in single ambulance strike in Bint Jbeil; 3 journalists killed in Jezzine same day. Two civilians killed in Israel by Hezbollah attacks; 16 IDF soldiers died in Lebanon per Israel.'
    },

    'displacement': {
        'total_displaced_registered': 1000000,        # PEAK figure — retained as the crisis high-water mark
        'currently_displaced': 360000,                # UNHCR, mid-August 2026
        'returned_to_areas_of_origin': 860000,        # UNHCR/UN News, mid-August 2026
        'total_displaced_pct_population': 20,          # at peak
        'in_government_shelters': 22000,              # mid-Aug — collapsed from 119K in April
        'shelters_opened': 430,                       # OCHA FU#41, 6 July
        'shelters_at_capacity': 'Operating at limits — fluid as ceasefire enables tentative returns',
        'cross_border_to_syria': 147823,              # IOM — since 1 March (latest IOM aggregate)
        'cross_border_to_jordan': 1800,               # unchanged from prior
        'previously_displaced_2024': 65000,
        'children_displaced': 300000,                  # initial appeal estimate; ~nearly 300K registered
        'pct_idps_outside_formal_shelter': 94,        # 22K of ~360K in collective shelters, mid-Aug
        'returns_since_ceasefire': '860,000 returned to areas of origin by mid-August; returns decelerating',
        'return_quality_caveat': (
            'RETURN IS NOT RECOVERY. UXO contamination affects homes, agricultural land and public '
            'infrastructure and is cited by OCHA as a major impediment to safe, voluntary and '
            'sustainable return. A returnee counted as no-longer-displaced may be living on their '
            'land rather than in their house. The return figure measures location, not shelter.'),
        'source': 'UNHCR / UN News (mid-Aug 2026) / OCHA Flash Update #41-42 / IOM DTM',
        'source_urls': [
            'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
            'https://dtm.iom.int/lebanon',
            'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-19-escalation-hostilities-lebanon-20-april-2026',
        ],
        'as_of': '2026-08-18',
        'note': (
            'Peak displacement exceeded 1M (~20% of population). By mid-August ~860,000 had returned '
            'to areas of origin and ~360,000 remained displaced, of whom only ~22,000 are in collective '
            'shelters — meaning roughly 94% of the still-displaced are outside formal shelter, absorbed '
            'by host families, in unfinished buildings, or in informal sites. That absorption is invisible '
            'in shelter statistics and is a deteriorating rather than stable arrangement. '
            'CRITICALLY: the return figure counts people back on their land, not people back in housing. '
            'OCHA identifies UXO contamination of homes, agricultural land and public infrastructure as a '
            'major impediment to safe and sustainable return; damage to health facilities, water systems '
            'and electricity networks continues to constrain basic services in return areas. '
            'Returns decelerated through July.')
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
        'unifil_peacekeepers_killed': 6,                # 4 Indonesian + 2 French (as of late April 2026)
        'unifil_peacekeepers_killed_indonesian': 4,
        'unifil_peacekeepers_killed_french': 2,
        'unifil_peacekeepers_wounded_recent': 5,        # 3 Ghanaian (early March) + 2 French still wounded post-April 18
        'unifil_breakdown': (
            '4 Indonesian peacekeepers killed in late March (Ett-Taibe + Bani Hayyan IED + Israeli tank fire); '
            'one Indonesian (Cpl. Rico Pramudia) died April 24 from March 29 wounds. '
            '2 French peacekeepers killed in April 18 Ghandouriyeh ambush attributed to Hezbollah '
            '(SSgt Florian Montorio at scene; Cpl Anicet Girardin died April 22 in Paris). '
            'Multiple Ghanaian peacekeepers wounded by Israeli missile strikes in early March.'
        ),
        'source': 'WHO / Lebanese MoPH / OCHA Flash Update #22 / UNIFIL / French MoD',
        'source_url': 'https://www.unocha.org/publications/report/lebanon/lebanon-flash-update-22-escalation-hostilities-lebanon-30-april-2026',
        'as_of': '2026-04-30',
        'note': (
            'WHO has documented 131+ attacks on healthcare since March 2: 103 health workers killed, 234 injured. '
            'Six hospitals closed and 15 damaged; 51 PHCCs closed and 7 damaged. '
            'SIX UNIFIL peacekeepers killed in 2026 (4 Indonesian + 2 French) — '
            'highest-level diplomatic incident given France contributes ~600 of UNIFIL\'s 7,505 troops '
            'and Macron declared April 22 that France will maintain Lebanon ground commitment after UNIFIL departs end of 2026. '
            'Hezbollah blamed by France/UNIFIL/Israel for April 18 ambush; Hezbollah denies. '
            'Three Ghanaian peacekeepers wounded by Israeli missile strikes early March. '
            'IOM emergency transportation funding exhausted — critical service gap. '
            'The April 8 mass casualty event (203 killed, 1,150+ wounded in central Beirut) overwhelmed surviving facilities.'
        )
    },

    'food_security': {
        'people_in_ipc_phase3_or_above': 1240000,
        'people_ipc_phase3': 1140000,
        'people_ipc_phase4': 101000,
        'people_ipc_phase5': 0,
        'pct_population_food_insecure': 24,
        'period': 'April – August 2026 projection',
        'projection_expires': '2026-08-31',           # ⚠️ see projection_expiry_warning
        'worst_districts': ['Bent Jbeil', 'Marjaayoun', 'El Nabatieh', 'Sour'],
        'worst_district_pct': '55–65%',
        'fuel_price_change': 'diesel +83%, gasoline +41%, cooking gas +27% (mid-Feb to mid-Apr 2026)',
        'driver': 'Escalation since March, displacement, livelihood disruption, affordability collapse, aid reduction',
        'source': 'IPC Acute Food Insecurity Updated Projection Analysis (MoA/FAO/WFP), 29 April 2026',
        'source_url': 'https://www.ipcinfo.org/ipc-country-analysis/details-map/en/c/1163301/',
        'as_of': '2026-04-29',
        'projection_expiry_warning': (
            'THIS PROJECTION WINDOW CLOSES 31 AUGUST 2026. After that date the 1.24M figure is a '
            'LAPSED PROJECTION, not a current measurement, and must not be reported as present-tense '
            'until a successor IPC analysis is published. Absence of a successor is itself a gap to '
            'surface, not a reason to keep quoting the old number.'),
        'note': (
            '1.24M people (~24% of the analysed population) projected at IPC Phase 3 (Crisis) or above '
            'for April–August 2026: 1.14M in Phase 3 and 101,000 in Phase 4 (Emergency); none in Phase 5. '
            'Up from 874,000 (~17%) in Nov 2025–Mar 2026. Worst in the southern governorates — Bent Jbeil, '
            'Marjaayoun, El Nabatieh and Sour — where 55–65% of the population is affected. '
            'The constraint is AFFORDABILITY, not national availability: food is broadly present but '
            'households cannot buy it, with diesel up 83% and cooking gas up 27% in two months. '
            'FORWARD RISK: the spring planting window closed with farmland damaged, farming households '
            'displaced and agricultural areas access-restricted, so missed planting converts into '
            'production losses in the autumn and winter that follow — a deterioration already in train '
            'and not yet reflected in any published figure. Funding-driven pipeline breaks in the Food '
            'Security and Agriculture sector were flagged from 1 July.')
    },

    'flash_appeal': {
        'amount_usd':              639900000,           # REVISED appeal, launched 5 June 2026
        'period':                  'March – August 2026 (revised)',
        'period_expires':          '2026-08-31',
        'original_amount_usd':     308300000,           # superseded March–May appeal
        'target_beneficiaries':    1000000,
        'launched':                '2026-06-05',
        'received_usd':            307000000,           # ~48% of 639.9M, mid-Aug
        'funded_pct':              48,
        'unfunded_usd':            332900000,
        'unhcr_operation_funded_pct': 24,               # of $472.3M for 2026
        'source':                  'UNHCR / UN News (mid-Aug 2026); revised Flash Appeal launched 5 June 2026',
        'source_url':              'https://www.unhcr.org/news/briefing-notes/lebanon-more-850-000-displaced-return-areas-origin-crisis-remains-far-over',
        'note':                    ('The March–May appeal ($308.3M) was superseded on 5 June by a revised appeal of '
                                    '$639.9M covering March–August 2026 — the requirement roughly DOUBLED while the '
                                    'funded share moved from 38% to 48%, so the absolute shortfall widened from $191M '
                                    'to ~$333M even as the percentage improved. Reporting the percentage alone '
                                    'understates the gap. UNHCR\'s own Lebanon operation is 24% funded against $472.3M. '
                                    'Funding-driven pipeline breaks were flagged in WASH, Health, and Food Security '
                                    'and Agriculture from 1 July. THE APPEAL PERIOD ENDS 31 AUGUST 2026.')
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

# ========================================
# STALENESS GUARD  (Aug 2026)
# ========================================
# STATIC_HUMANITARIAN is hand-maintained. It sat at 2026-05-03 for nearly four
# months while the ME BLUF published its figures at priority 12 -- leading the
# regional brief every cycle with April numbers, and nothing anywhere said so.
# The block was working exactly as designed; the design had no way to notice.
#
# Absence-honest fix: the module reports its own age and degrades its own
# confidence. Stale data is still served -- April figures beat no figures -- but
# it is served WITH its age attached so consumers can rank it accordingly.

STALENESS_FRESH_DAYS = 30      # normal manual-update cadence
STALENESS_AGING_DAYS = 60      # flag, keep publishing at full weight
STALENESS_STALE_DAYS = 90      # consumers should de-rank


def humanitarian_staleness():
    """How old is the hand-maintained block, and what should a consumer do?"""
    try:
        upd = datetime.strptime(STATIC_HUMANITARIAN['last_manual_update'], '%Y-%m-%d')
        upd = upd.replace(tzinfo=timezone.utc)
    except Exception:
        return {'age_days': None, 'tier': 'unknown', 'confidence': 0.5,
                'warning': 'last_manual_update unparseable -- treat figures as undated.',
                'lapsed_windows': []}

    age = (datetime.now(timezone.utc) - upd).days
    if age <= STALENESS_FRESH_DAYS:
        tier, conf, warn = 'fresh', 1.0, ''
    elif age <= STALENESS_AGING_DAYS:
        tier, conf = 'aging', 0.85
        warn = ('Humanitarian figures are %d days old. Still within a usable window, but a '
                'refresh from the latest OCHA Flash Update is due.' % age)
    elif age <= STALENESS_STALE_DAYS:
        tier, conf = 'stale', 0.6
        warn = ('Humanitarian figures are %d days old and should be read as INDICATIVE OF '
                'DIRECTION, not current magnitude. Casualty and displacement counts move '
                'materially over this interval.' % age)
    else:
        tier, conf = 'expired', 0.35
        warn = ('Humanitarian figures are %d days old. These are HISTORICAL, not current. '
                'Consumers should de-rank this signal rather than lead with it, and the block '
                'requires manual refresh from OCHA before it is quoted again.' % age)

    # Separate check: projection windows that have simply run out.
    lapsed = []
    for blk, key in (('food_security', 'projection_expires'),
                     ('flash_appeal', 'period_expires')):
        exp = (STATIC_HUMANITARIAN.get(blk) or {}).get(key)
        if not exp:
            continue
        try:
            if datetime.strptime(exp, '%Y-%m-%d').replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                lapsed.append('%s (window ended %s)' % (blk, exp))
        except Exception:
            continue
    if lapsed:
        warn += (' LAPSED PROJECTION WINDOW: ' + '; '.join(lapsed) + '. These figures are no '
                 'longer forward-looking and must not be reported present-tense until a '
                 'successor analysis is published.')

    return {'age_days': age, 'tier': tier, 'confidence': conf, 'warning': warn,
            'lapsed_windows': lapsed,
            'last_manual_update': STATIC_HUMANITARIAN['last_manual_update']}


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
        'staleness': humanitarian_staleness(),   # consumers de-rank on this

        'casualties': STATIC_HUMANITARIAN['casualties'],
        'displacement': displacement_data,
        'shelters': STATIC_HUMANITARIAN['shelters'],
        'evacuation_orders': STATIC_HUMANITARIAN['evacuation_orders'],
        'healthcare': STATIC_HUMANITARIAN['healthcare'],
        'flash_appeal': STATIC_HUMANITARIAN['flash_appeal'],
        'food_security': STATIC_HUMANITARIAN.get('food_security', {}),
        'ceasefire': STATIC_HUMANITARIAN.get('ceasefire', {}),

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
