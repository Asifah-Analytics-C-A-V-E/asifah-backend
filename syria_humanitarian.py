"""
Syria Humanitarian Data Module v1.2.0
October 4, 2026

Fetches humanitarian crisis data from:
  - IOM DTM API v3 (displacement/IDP tracking - DYNAMIC)
  - ReliefWeb API (OCHA reports - DYNAMIC)
  - FEWS NET shared food-security layer (via fews_net module)
  - Static reference data (casualties, camps, returns - updated manually, now DATE-STAMPED)

Provides /api/syria/humanitarian and /api/syria/news for the Syria stability page.

Env vars required (already set on ME backend):
  - DTM_API_KEY: IOM DTM API v3 subscription key
  - RELIEFWEB_APPNAME: ReliefWeb registered app name (e.g. asifah-analytics)
  - UPSTASH_REDIS_URL: Redis cache URL
  - UPSTASH_REDIS_TOKEN: Redis cache token

Pattern: Redis-first caching with 6-hour TTL (news: 4-hour) + background refresh.

-------------------------------------------------------------------------------
CHANGELOG
-------------------------------------------------------------------------------
v1.2.0 -- 2026-10-04
  1. GDELT NOW ROUTES THROUGH gdelt_gateway.
     v1.1.0 called http://api.gdeltproject.org directly -- over PLAIN HTTP,
     with no shared rate limiting, no backoff, and no 429 escalation. It was
     the last module on any backend still doing this. Now: soft-import
     gdelt_fetch_probed() from gdelt_gateway; three-tier call (kwargs ->
     positional -> direct HTTPS fallback) so a gateway signature change
     degrades loudly instead of crashing the news feed.

  2. USER-AGENTS ARE NOW IDENTIFIABLE, NOT HALF-SPOOFED.
     v1.1.0 sent 'Mozilla/5.0 AsifahAnalytics/3.0' on RSS (a half-spoof) and
     a bare 'AsifahAnalytics/3.0 (Syria Stability Tracker)' to Reddit. The
     measured lesson from the Europe backend: the dividing line is not
     honest-vs-spoofed, it is IDENTIFIABLE-vs-bare. Reddit 403s a bare UA and
     serves a UA carrying product/version + descriptive parenthetical +
     contact URL from the same IP in the same cycle. Both now use that shape.

  3. ABSENCE IS NOW HONEST. A 'sensing' block is attached to both payloads.
     v1.1.0 could not tell the difference between "DTM says the caseload is
     stable" and "DTM never answered". fetch_dtm_displacement() returned
     country_level: None on a missing API key, on an HTTP error, AND on a
     genuine empty result -- three different states collapsed into one.
     Those are now separated: blind / reached_no_data / sensed.
     Same for ReliefWeb, each RSS feed, each GDELT language, and Reddit.

  4. STATIC FIGURES ARE NOW DATE-STAMPED AND SELF-AGING.
     v1.1.0 presented a last_manual_update of 2026-06-19 with Al-Hol at Feb
     2026, Aleppo at Mar 2026 and the SDF agreement at Jan 2026 -- with no
     visible age. The page rendered four-month-old manual figures as current.
     Every static sub-block now carries as_of_age_days, freshness and
     review_due, COMPUTED AT REQUEST TIME from its own as_of date. Nothing is
     hardcoded as "current" any more; the numbers themselves are unchanged
     because no newer sourced figures have been verified.

  5. RSS ZOMBIE GUARD. An HTTP 200 carrying under 200 bytes is an empty or
     challenge-page response, not quiet news. Ported from the Belarus
     tracker, where four feeds were returning exactly that.

  NOT CHANGED (deliberately): the Redis-first caching and TTLs (6h / 4h) are
  sound. Every key the Syria page already reads is still present and still has
  the same type -- v1.2.0 only ADDS keys.

v1.1.0 -- March 2026: initial DTM v3 + ReliefWeb + static reference build.
-------------------------------------------------------------------------------
"""

import os
import json
import requests
import threading
import time
from flask import request, jsonify
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

MODULE_VERSION = '1.2.0'

# Shared FEWS NET food-security layer (fail-open if not yet deployed)
try:
    import fews_net
    _FEWS_AVAILABLE = True
except ImportError:
    fews_net = None
    _FEWS_AVAILABLE = False

# Shared GDELT gateway (rate limiting, backoff, 429 escalation, shared across
# every tracker on this backend). Fail-open: if it is not deployed here we fall
# back to a direct HTTPS call rather than killing the news feed.
try:
    from gdelt_gateway import gdelt_fetch_probed as _gw_fetch_probed
    GDELT_GATEWAY = True
except ImportError:
    _gw_fetch_probed = None
    GDELT_GATEWAY = False
except Exception as _e:  # gateway present but broken on import
    _gw_fetch_probed = None
    GDELT_GATEWAY = False
    print(f"[Syria News] gdelt_gateway import failed: {str(_e)[:160]}")


# ========================================
# CONFIGURATION
# ========================================

DTM_API_KEY = os.environ.get('DTM_API_KEY')
DTM_BASE_URL = 'https://dtmapi.iom.int/v3'

# ReliefWeb API (open, but registered appname required)
RELIEFWEB_API_URL = 'https://api.reliefweb.int/v1'
RELIEFWEB_APPNAME = os.environ.get('RELIEFWEB_APPNAME', 'asifah-analytics')

# Redis (same env vars as ME backend app.py)
UPSTASH_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
CACHE_KEY = 'syria_humanitarian'

# Background refresh interval (6 hours)
REFRESH_INTERVAL_SECONDS = 6 * 3600

# News feed config
NEWS_CACHE_KEY = 'syria_news'
# HTTPS, and only used when gdelt_gateway is unavailable.
GDELT_BASE_URL = 'https://api.gdeltproject.org/api/v2/doc/doc'
SYRIA_DIRECT_RSS = 'https://syriadirect.org/feed/'
SOHR_RSS = 'https://www.syriahr.com/en/homepage/feed/'
REDDIT_SUBREDDITS = ['syriancivilwar', 'syria', 'geopolitics', 'MiddleEast']

# ---------------------------------------------------------------------------
# USER-AGENT -- identifiable, not spoofed, not bare.
# Product/version + descriptive parenthetical + contact URL. This exact shape
# is served by Reddit; a bare 'AsifahAnalytics/1.0' is 403'd from the same IP.
# ---------------------------------------------------------------------------
MODULE_USER_AGENT = (
    f'AsifahAnalytics-ME-Syria/{MODULE_VERSION} '
    f'(OSINT monitoring tool; +https://asifahanalytics.com)'
)
REDDIT_USER_AGENT = MODULE_USER_AGENT

# An HTTP 200 shorter than this is an empty feed or a challenge page, not news.
RSS_MIN_BYTES = 200

# How old a manual figure may get before the page should flag it for review.
STATIC_REVIEW_INTERVAL_DAYS = 90


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
# DATE-STAMPING HELPERS
# Static figures do not get to claim they are current. They carry their own
# age, computed at request time, and say when they are due for review.
# ========================================

def _age_days(date_str):
    """Days between an ISO-ish YYYY-MM-DD string and now. None if unparseable."""
    if not date_str:
        return None
    try:
        d = datetime.strptime(str(date_str)[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - d).days)
    except Exception:
        return None


def _freshness(age):
    """Plain-language bucket for how much weight a manual figure still carries."""
    if age is None:
        return 'unknown'
    if age <= 45:
        return 'current'
    if age <= 90:
        return 'aging'
    if age <= 180:
        return 'stale'
    return 'unverified'


def _stamp_static(block):
    """
    Return a COPY of a static block with its own age attached.
    Adds: as_of_age_days, freshness, review_due, review_interval_days.
    Never mutates STATIC_HUMANITARIAN -- the module-level dict stays pristine
    so a long-running process does not accumulate stamps on stamps.
    """
    out = dict(block or {})
    age = _age_days(out.get('as_of'))
    out['as_of_age_days'] = age
    out['freshness'] = _freshness(age)
    out['review_due'] = bool(age is not None and age > STATIC_REVIEW_INTERVAL_DAYS)
    out['review_interval_days'] = STATIC_REVIEW_INTERVAL_DAYS
    return out


_FRESHNESS_RANK = {'current': 0, 'aging': 1, 'stale': 2, 'unverified': 3, 'unknown': 4}


def _worst_freshness(labels):
    """The weakest link. A payload is only as current as its oldest figure."""
    if not labels:
        return 'unknown'
    return sorted(labels, key=lambda x: _FRESHNESS_RANK.get(x, 4), reverse=True)[0]


# ========================================
# DTM API — IDP DISPLACEMENT DATA
# ========================================

def fetch_dtm_displacement():
    """
    Fetch Syria IDP data from IOM DTM API v3.

    Returns country-level and governorate-level displacement figures PLUS a
    probe. The probe is the point: v1.1.0 returned country_level: None for a
    missing API key, an HTTP 500, and a genuinely empty result set, so the page
    could not tell "no new displacement" from "we never asked".

    probe['state'] is one of:
      'blind'            -- no key, or every request failed. Figures UNKNOWN.
      'reached_no_data'  -- DTM answered, and the answer was empty. A real zero.
      'sensed'           -- DTM answered with data.
    """
    result = {
        'source': 'IOM DTM API v3',
        'source_url': 'https://dtm.iom.int/syrian-arab-republic',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'country_level': None,
        'governorate_level': [],
        'error': None,
        'probe': {
            'attempted': 0,
            'reached': 0,
            'failed': 0,
            'failures': [],
            'sensed': False,
            'state': 'blind',
            'key_configured': bool(DTM_API_KEY),
            'country_level_state': 'blind',
            'governorate_level_state': 'blind',
        },
    }
    probe = result['probe']

    if not DTM_API_KEY:
        print("[Syria DTM] No DTM_API_KEY configured -- DTM is BLIND, not quiet")
        probe['failures'].append('DTM_API_KEY not configured')
        result['error'] = 'DTM_API_KEY not configured'
        return result

    headers = {
        'Ocp-Apim-Subscription-Key': DTM_API_KEY,
        'Accept': 'application/json',
        'User-Agent': MODULE_USER_AGENT,
    }

    # ---------- Country-level (Admin 0) ----------
    try:
        print("[Syria DTM] Fetching country-level IDP data...")
        params = {
            'CountryName': 'Syrian Arab Republic',
            'FromReportingDate': '2024-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d')
        }
        probe['attempted'] += 1
        response = requests.get(
            f'{DTM_BASE_URL}/displacement/admin0',
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code == 200:
            # We got a parseable answer from DTM. Only NOW is a zero a real zero.
            probe['reached'] += 1
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
                    probe['country_level_state'] = 'sensed'
                    print(f"[Syria DTM] Country-level: {most_recent.get('numPresentIdpInd', 0):,} IDPs")
            else:
                print("[Syria DTM] Country-level: No data returned — trying alt name...")
                params['CountryName'] = 'Syria'
                probe['attempted'] += 1
                alt_response = requests.get(
                    f'{DTM_BASE_URL}/displacement/admin0',
                    headers=headers,
                    params=params,
                    timeout=15
                )
                if alt_response.status_code == 200:
                    probe['reached'] += 1
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
                            probe['country_level_state'] = 'sensed'
                            print(f"[Syria DTM] Alt name: {most_recent.get('numPresentIdpInd', 0):,} IDPs")
                    else:
                        probe['country_level_state'] = 'reached_no_data'
                        print("[Syria DTM] Country-level: reached, genuinely empty (both names)")
                else:
                    probe['failed'] += 1
                    probe['failures'].append(f"admin0 alt-name HTTP {alt_response.status_code}")
                    print(f"[Syria DTM] Country-level alt name: HTTP {alt_response.status_code}")
        else:
            probe['failed'] += 1
            probe['failures'].append(f"admin0 HTTP {response.status_code}")
            print(f"[Syria DTM] Country-level: HTTP {response.status_code}")
            result['error'] = f"HTTP {response.status_code}"

    except Exception as e:
        probe['failed'] += 1
        probe['failures'].append(f"admin0 {type(e).__name__}: {str(e)[:120]}")
        result['error'] = f"DTM country-level error: {str(e)[:200]}"
        print(f"[Syria DTM] Country error: {str(e)[:200]}")

    # ---------- Governorate-level (Admin 1) ----------
    try:
        print("[Syria DTM] Fetching governorate-level IDP data...")
        params = {
            'CountryName': 'Syrian Arab Republic',
            'FromReportingDate': '2024-01-01',
            'ToReportingDate': datetime.now().strftime('%Y-%m-%d')
        }
        probe['attempted'] += 1
        response = requests.get(
            f'{DTM_BASE_URL}/displacement/admin1',
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code == 200:
            probe['reached'] += 1
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
                probe['governorate_level_state'] = 'sensed'
                print(f"[Syria DTM] Governorate-level: {len(result['governorate_level'])} governorates, {total_gov:,} total")
            else:
                probe['governorate_level_state'] = 'reached_no_data'
                print("[Syria DTM] Governorate-level: reached, genuinely empty")
        else:
            probe['failed'] += 1
            probe['failures'].append(f"admin1 HTTP {response.status_code}")
            print(f"[Syria DTM] Governorate-level: HTTP {response.status_code}")

    except Exception as e:
        probe['failed'] += 1
        probe['failures'].append(f"admin1 {type(e).__name__}: {str(e)[:120]}")
        print(f"[Syria DTM] Governorate error: {str(e)[:200]}")

    # ---------- Roll the probe up ----------
    probe['sensed'] = bool(result['country_level']) or bool(result['governorate_level'])
    if probe['sensed']:
        probe['state'] = 'sensed'
    elif probe['reached'] > 0:
        probe['state'] = 'reached_no_data'
    else:
        probe['state'] = 'blind'

    print(f"[Syria DTM] Probe: state={probe['state']} "
          f"attempted={probe['attempted']} reached={probe['reached']} failed={probe['failed']}")

    return result


# ========================================
# RELIEFWEB API — OCHA/UN REPORTS
# ========================================

def fetch_reliefweb_updates():
    """
    Fetch latest OCHA/UN reports for Syria from ReliefWeb.

    Also returns a probe. An empty report list after an HTTP 200 means OCHA
    genuinely published nothing matching the query; an empty list after a 403
    means we are blind. v1.1.0 rendered both as "no recent reports".
    """
    result = {
        'source': 'ReliefWeb API',
        'source_url': 'https://reliefweb.int/country/syr',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'reports': [],
        'error': None,
        'probe': {
            'attempted': 0,
            'reached': 0,
            'failed': 0,
            'failures': [],
            'sensed': False,
            'state': 'blind',
            'http_status': None,
            'appname': RELIEFWEB_APPNAME,
        },
    }
    probe = result['probe']

    try:
        print("[Syria ReliefWeb] Fetching reports...")
        params = {
            'appname': RELIEFWEB_APPNAME,
            'query[value]': 'Syria displacement IDP humanitarian returns',
            'query[operator]': 'AND',
            'sort[]': 'date:desc',
            'limit': 8,
            'fields[include][]': ['title', 'date.created', 'url_alias', 'source.name'],
        }

        probe['attempted'] += 1
        response = requests.get(
            f'{RELIEFWEB_API_URL}/reports',
            params=params,
            timeout=15,
            headers={'User-Agent': MODULE_USER_AGENT}
        )
        probe['http_status'] = response.status_code

        if response.status_code == 200:
            probe['reached'] += 1
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
            probe['failed'] += 1
            probe['failures'].append(f"HTTP {response.status_code}")
            result['error'] = f"HTTP {response.status_code}"
            print(f"[Syria ReliefWeb] HTTP {response.status_code}")

    except Exception as e:
        probe['failed'] += 1
        probe['failures'].append(f"{type(e).__name__}: {str(e)[:120]}")
        result['error'] = str(e)[:200]
        print(f"[Syria ReliefWeb] Error: {str(e)[:200]}")

    probe['sensed'] = len(result['reports']) > 0
    if probe['sensed']:
        probe['state'] = 'sensed'
    elif probe['reached'] > 0:
        probe['state'] = 'reached_no_data'
    else:
        probe['state'] = 'blind'

    print(f"[Syria ReliefWeb] Probe: state={probe['state']} reports={len(result['reports'])}")

    return result


# ========================================
# STATIC HUMANITARIAN DATA
# ========================================

# Sources: IOM DTM Baseline Assessments, OCHA, UNHCR
# These are MANUAL figures. None of them is presented to the page as "current" --
# _stamp_static() attaches each block's real age at request time. If a block
# reads 'stale' or 'unverified' on the page, that is the module telling the
# truth about itself, not a bug.
#
# When you refresh a figure, update BOTH the number and its 'as_of'. The
# freshness label is derived, never typed.

STATIC_HUMANITARIAN = {
    'last_manual_update': '2026-06-19',
    'data_period': 'Ongoing since 2011; post-Assad transition Dec 2024; Aleppo/NES emergency Jan-Mar 2026',
    'note': 'Static figures from IOM DTM baseline assessments and OCHA reports. Updated manually; each block carries its own computed age.',

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
        'as_of': '2026-02-22',
        # A closure is a dated EVENT, not a condition that needs re-measuring.
        # It does not decay the way a caseload does.
        'assertion_type': 'event',
    },

    'aleppo_emergency': {
        'active': False,
        'status': 'Stabilized',
        'tracking_rounds': 14,
        'start_date': '2026-01-06',
        'trigger': 'Escalation of hostilities in Sheikh Maqsoud, Ashrafiyah, and Bani Zaid, Aleppo City',
        'peak_displacement': 148053,
        'peak_date': '2026-01-09',
        'current_estimate': 'Stabilized -- returns largely complete; Jan-Mar 2026 emergency phase closed, SDF integration holding',
        'sdf_ceasefire': 'Ceasefire and integration agreement announced Jan 30, 2026 — holding as of Mar 2026',
        'priority_needs': ['Cash assistance', 'Food', 'Non-food items', 'Shelter', 'Health services'],
        'source': 'IOM DTM Emergency Mobility Tracking Rounds 1-14',
        'source_url': 'https://dtm.iom.int/syrian-arab-republic',
        'as_of': '2026-03-04',
        # 'active': False is an ONGOING-CONDITION claim, and it has not been
        # re-measured since its as_of. Flagged so the page can say "asserted
        # stabilized as of March, not verified since" rather than "Stabilized".
        'assertion_type': 'condition',
        'status_is_asserted_not_sensed': True,
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
        'as_of': '2026-03-10',
        'assertion_type': 'condition',
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
# NEWS FEED — CACHED ARTICLE AGGREGATION
# ========================================

def _fetch_rss(url, source_name, max_items=15):
    """
    Fetch and parse an RSS feed.

    Returns (articles, probe). The probe separates a quiet feed from a dead
    one: HTTP 403/404 is blind, an HTTP 200 under RSS_MIN_BYTES is a zombie
    (empty or challenge page), and a parsed feed with zero <item> elements is
    a real zero.
    """
    articles = []
    probe = {
        'source': source_name,
        'url': url,
        'attempted': 1,
        'http_status': None,
        'bytes': 0,
        'state': 'blind',
        'sensed': False,
        'error': None,
    }
    try:
        response = requests.get(url, timeout=12, headers={
            'User-Agent': MODULE_USER_AGENT
        })
        probe['http_status'] = response.status_code
        probe['bytes'] = len(response.content or b'')

        if response.status_code == 200:
            if probe['bytes'] < RSS_MIN_BYTES:
                # Zombie: a 200 with no body. Not quiet news.
                probe['state'] = 'zombie_200'
                probe['error'] = f"HTTP 200 but only {probe['bytes']} bytes"
                print(f"[Syria News] RSS {source_name}: HTTP 200 but only "
                      f"{probe['bytes']} bytes -- empty feed, NOT quiet news")
                return articles, probe

            root = ET.fromstring(response.content)
            items = root.findall('.//item')
            for item in items[:max_items]:
                title = item.find('title')
                link = item.find('link')
                desc = item.find('description')
                pub = item.find('pubDate')
                pub_date = ''
                if pub is not None and pub.text:
                    try:
                        pub_date = parsedate_to_datetime(pub.text).isoformat()
                    except Exception:
                        pub_date = pub.text
                articles.append({
                    'title': title.text if title is not None else '',
                    'url': link.text if link is not None else '',
                    'description': (desc.text or '')[:500] if desc is not None else '',
                    'publishedAt': pub_date,
                    'source': {'name': source_name},
                    'language': 'en'
                })
            probe['state'] = 'sensed' if articles else 'reached_no_data'
            probe['sensed'] = bool(articles)
            print(f"[Syria News] RSS {source_name}: {len(articles)} articles "
                  f"({probe['bytes']} bytes)")
        else:
            probe['state'] = 'blind'
            probe['error'] = f"HTTP {response.status_code}"
            print(f"[Syria News] RSS {source_name}: HTTP {response.status_code}")
    except ET.ParseError as e:
        probe['state'] = 'parse_error'
        probe['error'] = f"ParseError: {str(e)[:120]}"
        print(f"[Syria News] RSS {source_name} parse error ({probe['bytes']} bytes): {str(e)[:100]}")
    except Exception as e:
        probe['state'] = 'blind'
        probe['error'] = f"{type(e).__name__}: {str(e)[:120]}"
        print(f"[Syria News] RSS {source_name} error: {str(e)[:100]}")
    return articles, probe


def _gdelt_direct(query, sourcelang, max_items):
    """
    Last-resort direct GDELT call over HTTPS. Only reached when gdelt_gateway
    is absent or its signature has moved. Returns (raw_articles, http_status).
    raw_articles is None on failure -- an empty list means GDELT answered and
    had nothing, which is a different thing entirely.
    """
    params = {
        'query': query,
        'mode': 'artlist',
        'maxrecords': max_items,
        'timespan': '7d',
        'format': 'json',
        'sourcelang': sourcelang
    }
    response = requests.get(
        GDELT_BASE_URL, params=params, timeout=15,
        headers={'User-Agent': MODULE_USER_AGENT}
    )
    if response.status_code != 200:
        return None, response.status_code
    try:
        return response.json().get('articles', []) or [], 200
    except Exception:
        # A 200 that is not JSON is GDELT refusing, not GDELT answering empty.
        return None, 200


def _fetch_gdelt(query, sourcelang, exclude_domains=None, max_items=20):
    """
    Fetch articles from GDELT -- THROUGH THE SHARED GATEWAY where available.

    Three tiers, each logged:
      1. gdelt_gateway.gdelt_fetch_probed() with keyword args
      2. the same, positional (survives a kwarg rename in the gateway)
      3. direct HTTPS (survives the gateway being absent entirely)

    Returns (articles, probe). probe['sensed'] False with route 'none' means we
    never got an answer -- do NOT render that as "no Syria coverage this week".
    """
    articles = []
    probe = {
        'sourcelang': sourcelang,
        'route': 'none',
        'gateway_available': GDELT_GATEWAY,
        'attempted': 0,
        'raw_count': 0,
        'kept': 0,
        'excluded': 0,
        'http_status': None,
        'state': 'blind',
        'sensed': False,
        'error': None,
    }
    raw = None

    # ---- Tier 1 / 2: the shared gateway ----
    if GDELT_GATEWAY and _gw_fetch_probed is not None:
        probe['attempted'] += 1
        try:
            raw, gw_probe = _gw_fetch_probed(
                query, sourcelang=sourcelang,
                maxrecords=max_items, timespan='7d'
            )
            probe['route'] = 'gateway'
            if isinstance(gw_probe, dict):
                probe['gateway_probe'] = gw_probe
                if 'sensed' in gw_probe and not gw_probe.get('sensed'):
                    raw = None
                    probe['error'] = 'gateway reported not sensed'
        except TypeError as e:
            # The gateway is here but not with the kwargs we expect. Retry
            # positionally before giving up on it.
            print(f"[Syria News] GDELT gateway kwargs rejected ({str(e)[:120]}) -- retrying positional")
            try:
                probe['attempted'] += 1
                raw, gw_probe = _gw_fetch_probed(query, sourcelang)
                probe['route'] = 'gateway_positional'
                if isinstance(gw_probe, dict):
                    probe['gateway_probe'] = gw_probe
                    if 'sensed' in gw_probe and not gw_probe.get('sensed'):
                        raw = None
            except Exception as e2:
                raw = None
                probe['error'] = f'gateway signature mismatch: {str(e2)[:120]}'
                print(f"[Syria News] GDELT gateway UNUSABLE ({str(e2)[:120]}) -- falling back to direct")
        except Exception as e:
            raw = None
            probe['error'] = f'gateway error: {str(e)[:120]}'
            print(f"[Syria News] GDELT gateway error {sourcelang}: {str(e)[:120]}")

    # ---- Tier 3: direct HTTPS fallback ----
    if raw is None:
        try:
            probe['attempted'] += 1
            raw, status = _gdelt_direct(query, sourcelang, max_items)
            probe['http_status'] = status
            probe['route'] = 'direct' if probe['route'] in ('none',) else probe['route'] + '+direct'
            if raw is None:
                probe['error'] = (probe['error'] or '') + f' direct HTTP {status}'
                print(f"[Syria News] GDELT {sourcelang}: direct HTTP {status}")
        except Exception as e:
            raw = None
            probe['error'] = (probe['error'] or '') + f' direct {type(e).__name__}: {str(e)[:100]}'
            print(f"[Syria News] GDELT {sourcelang} direct error: {str(e)[:100]}")

    # ---- Shape whatever we got ----
    if raw is None:
        probe['state'] = 'blind'
        print(f"[Syria News] GDELT {sourcelang}: BLIND (route={probe['route']})")
        return articles, probe

    probe['raw_count'] = len(raw)
    lang_code = {'eng': 'en', 'ara': 'ar', 'heb': 'he', 'fas': 'fa'}.get(sourcelang, 'en')
    for a in raw:
        domain = a.get('domain', '')
        if exclude_domains and any(d in domain for d in exclude_domains):
            probe['excluded'] += 1
            continue
        articles.append({
            'title': a.get('title', ''),
            'url': a.get('url', ''),
            'description': a.get('title', ''),
            'publishedAt': a.get('seendate', ''),
            'source': {'name': domain},
            'language': lang_code
        })

    probe['kept'] = len(articles)
    probe['sensed'] = True          # GDELT answered. Zero is now a real zero.
    probe['state'] = 'sensed' if articles else 'reached_no_data'
    print(f"[Syria News] GDELT {sourcelang}: {len(articles)} articles "
          f"(raw {probe['raw_count']}, excluded {probe['excluded']}, route={probe['route']})")
    return articles, probe


def _fetch_reddit(subreddits, max_per_sub=10):
    """
    Fetch posts from Reddit.

    Returns (articles, probe). The UA is the identifiable shape; a bare one
    gets 403'd on every sub, which v1.1.0 would have reported as silence.
    """
    articles = []
    probe = {
        'attempted': 0,
        'reached': 0,
        'failed': 0,
        'failures': [],
        'per_sub': {},
        'sensed': False,
        'state': 'blind',
    }
    for sub in subreddits:
        probe['attempted'] += 1
        try:
            url = (f'https://www.reddit.com/r/{sub}/search.json'
                   f'?q=Syria&sort=new&t=week&limit={max_per_sub}')
            response = requests.get(url, timeout=10, headers={'User-Agent': REDDIT_USER_AGENT})
            if response.status_code == 200:
                probe['reached'] += 1
                data = response.json()
                posts = data.get('data', {}).get('children', [])
                found = 0
                for post in posts:
                    p = post.get('data', {})
                    articles.append({
                        'title': p.get('title', ''),
                        'url': f"https://reddit.com{p.get('permalink', '')}",
                        'description': (p.get('selftext', '') or '')[:300],
                        'publishedAt': datetime.fromtimestamp(p.get('created_utc', 0), tz=timezone.utc).isoformat() if p.get('created_utc') else '',
                        'source': {'name': f'r/{sub}'},
                        'language': 'en'
                    })
                    found += 1
                probe['per_sub'][sub] = {'status': 200, 'posts': found}
                print(f"[Syria News] Reddit r/{sub}: {found} posts")
            else:
                probe['failed'] += 1
                probe['failures'].append(f"r/{sub} HTTP {response.status_code}")
                probe['per_sub'][sub] = {'status': response.status_code, 'posts': 0}
                print(f"[Syria News] Reddit r/{sub}: HTTP {response.status_code}")
        except Exception as e:
            probe['failed'] += 1
            probe['failures'].append(f"r/{sub} {type(e).__name__}: {str(e)[:100]}")
            probe['per_sub'][sub] = {'status': None, 'posts': 0, 'error': str(e)[:100]}
            print(f"[Syria News] Reddit r/{sub} error: {str(e)[:100]}")
        finally:
            # Was inside the try in v1.1.0, so a failing sub skipped its own
            # pacing and hammered the next one.
            time.sleep(1)

    probe['sensed'] = probe['reached'] > 0
    if len(articles) > 0:
        probe['state'] = 'sensed'
    elif probe['reached'] > 0:
        probe['state'] = 'reached_no_data'
    else:
        probe['state'] = 'blind'

    print(f"[Syria News] Reddit: {len(articles)} posts from {probe['reached']}/{len(subreddits)} subs "
          f"(state={probe['state']})")
    return articles, probe


def fetch_all_news():
    """Fetch all Syria news from all sources, with a sensing block attached."""
    print(f"[Syria News] v{MODULE_VERSION} fetching all news sources...")

    syria_direct, p_sd = _fetch_rss(SYRIA_DIRECT_RSS, 'Syria Direct')
    sohr, p_sohr = _fetch_rss(SOHR_RSS, 'SOHR')

    en_articles, p_en = _fetch_gdelt(
        'Syria conflict displacement HTS SDF Aleppo Damascus', 'eng',
        exclude_domains=['syriadirect.org'])
    ar_articles, p_ar = _fetch_gdelt('سوريا نزوح حلب دمشق قسد هيئة تحرير الشام', 'ara')
    he_articles, p_he = _fetch_gdelt('סוריה דמשק חאלב כורדים דאעש', 'heb')
    fa_articles, p_fa = _fetch_gdelt('سوریه دمشق حلب کردها داعش', 'fas')

    reddit, p_reddit = _fetch_reddit(REDDIT_SUBREDDITS)

    rss_probes = {'syria_direct': p_sd, 'sohr': p_sohr}
    gdelt_probes = {'en': p_en, 'ar': p_ar, 'he': p_he, 'fa': p_fa}

    rss_reached = sum(1 for p in rss_probes.values() if p['http_status'] == 200
                      and p['state'] not in ('zombie_200', 'parse_error'))
    gdelt_reached = sum(1 for p in gdelt_probes.values() if p['sensed'])

    sensing = {
        'module_version': MODULE_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'rss': {
            'attempted': len(rss_probes),
            'reached': rss_reached,
            'blind': len(rss_probes) - rss_reached,
            'per_feed': rss_probes,
        },
        'gdelt': {
            'gateway_available': GDELT_GATEWAY,
            'attempted': len(gdelt_probes),
            'reached': gdelt_reached,
            'blind': len(gdelt_probes) - gdelt_reached,
            'per_lang': gdelt_probes,
        },
        'reddit': p_reddit,
    }
    sensing['any_sensed'] = bool(rss_reached or gdelt_reached or p_reddit['sensed'])
    sensing['degraded'] = bool(
        (len(rss_probes) - rss_reached) or
        (len(gdelt_probes) - gdelt_reached) or
        not p_reddit['sensed']
    )

    result = {
        'success': True,
        'module_version': MODULE_VERSION,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'articles_syria_direct': syria_direct,
        'articles_sohr': sohr,
        'articles_en': en_articles,
        'articles_ar': ar_articles,
        'articles_he': he_articles,
        'articles_fa': fa_articles,
        'articles_reddit': reddit,
        'counts': {
            'syria_direct': len(syria_direct),
            'sohr': len(sohr),
            'en': len(en_articles),
            'ar': len(ar_articles),
            'he': len(he_articles),
            'fa': len(fa_articles),
            'reddit': len(reddit),
        },
        # Per-source: did we actually read this, or is the count above a zero
        # we never earned? The page should grey out a source that is False.
        'counts_sensed': {
            'syria_direct': p_sd['sensed'],
            'sohr': p_sohr['sensed'],
            'en': p_en['sensed'],
            'ar': p_ar['sensed'],
            'he': p_he['sensed'],
            'fa': p_fa['sensed'],
            'reddit': p_reddit['sensed'],
        },
        'sensing': sensing,
    }

    if _redis_available():
        _redis_set(NEWS_CACHE_KEY, result)
        print(f"[Syria News] Cached to Redis (total: {sum(result['counts'].values())} articles, "
              f"degraded={sensing['degraded']})")

    return result


def get_news_data(force_refresh=False):
    """Get Syria news — Redis-first with 4-hour TTL."""
    if not force_refresh and _redis_available():
        cached = _redis_get(NEWS_CACHE_KEY)
        if cached:
            cached_at = cached.get('fetched_at', '')
            if cached_at:
                try:
                    cached_time = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now(timezone.utc) - cached_time).total_seconds() / 3600
                    if age_hours < 4:
                        print(f"[Syria News] Using cached data ({age_hours:.1f}h old)")
                        cached['from_cache'] = True
                        cached['cache_age_hours'] = round(age_hours, 1)
                        return cached
                except Exception:
                    pass
    return fetch_all_news()


# ========================================
# COMBINED HUMANITARIAN FETCH
# ========================================

def _fetch_all_humanitarian():
    """Fetch all humanitarian data, combine DTM + ReliefWeb + FEWS + static."""
    print(f"[Syria Humanitarian] v{MODULE_VERSION} fetching fresh data...")

    dtm_data = fetch_dtm_displacement()
    reliefweb_data = fetch_reliefweb_updates()

    dtm_probe = (dtm_data or {}).get('probe', {}) or {}
    rw_probe = (reliefweb_data or {}).get('probe', {}) or {}

    # ---- Displacement card: static baseline, DTM overlay where sensed ----
    displacement_data = _stamp_static(STATIC_HUMANITARIAN['displacement'])
    displacement_data['dtm_state'] = dtm_probe.get('state', 'blind')
    displacement_data['dtm_sensed'] = bool(dtm_probe.get('sensed'))

    if dtm_data and dtm_data.get('country_level'):
        dtm_idps = dtm_data['country_level'].get('total_idps', 0)
        if dtm_idps > 0:
            displacement_data['dtm_api_idps'] = dtm_idps
            displacement_data['dtm_reporting_date'] = dtm_data['country_level'].get('reporting_date', '')
            displacement_data['dtm_round'] = dtm_data['country_level'].get('round_number', '')
            displacement_data['dtm_source'] = 'IOM DTM API v3 (live)'
            displacement_data['dtm_reporting_age_days'] = _age_days(
                dtm_data['country_level'].get('reporting_date', ''))

    # ---- FEWS NET food-security panel (shared module, one writer) ----
    food_security = fews_net.get_panel('syria') if _FEWS_AVAILABLE else None

    # ---- Stamp every static block with its own real age ----
    al_hol = _stamp_static(STATIC_HUMANITARIAN['al_hol_camp'])
    aleppo = _stamp_static(STATIC_HUMANITARIAN['aleppo_emergency'])
    returns = _stamp_static(STATIC_HUMANITARIAN['cross_border_returns'])
    governance = _stamp_static(STATIC_HUMANITARIAN['governance_transition'])

    manual_age = _age_days(STATIC_HUMANITARIAN['last_manual_update'])

    # Condition claims decay; dated events do not. Only the conditions count
    # toward the payload's overall freshness.
    condition_blocks = [displacement_data, aleppo, returns, governance]
    static_freshness = _worst_freshness([b.get('freshness') for b in condition_blocks])

    sensing = {
        'module_version': MODULE_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'dtm': {
            'state': dtm_probe.get('state', 'blind'),
            'sensed': bool(dtm_probe.get('sensed')),
            'attempted': dtm_probe.get('attempted', 0),
            'reached': dtm_probe.get('reached', 0),
            'failed': dtm_probe.get('failed', 0),
            'failures': dtm_probe.get('failures', []),
            'key_configured': dtm_probe.get('key_configured', False),
            'country_level_state': dtm_probe.get('country_level_state', 'blind'),
            'governorate_level_state': dtm_probe.get('governorate_level_state', 'blind'),
        },
        'reliefweb': {
            'state': rw_probe.get('state', 'blind'),
            'sensed': bool(rw_probe.get('sensed')),
            'http_status': rw_probe.get('http_status'),
            'failures': rw_probe.get('failures', []),
            'reports': len((reliefweb_data or {}).get('reports', []) or []),
        },
        'food_security': {
            'module_available': _FEWS_AVAILABLE,
            'sensed': bool(food_security),
            'state': 'sensed' if food_security else ('blind' if not _FEWS_AVAILABLE else 'reached_no_data'),
        },
        'static': {
            'last_manual_update': STATIC_HUMANITARIAN['last_manual_update'],
            'last_manual_update_age_days': manual_age,
            'review_interval_days': STATIC_REVIEW_INTERVAL_DAYS,
            'manual_review_due': bool(manual_age is not None and manual_age > STATIC_REVIEW_INTERVAL_DAYS),
            'freshness': static_freshness,
            'blocks': {
                'displacement': displacement_data.get('freshness'),
                'al_hol_camp': al_hol.get('freshness'),
                'aleppo_emergency': aleppo.get('freshness'),
                'cross_border_returns': returns.get('freshness'),
                'governance_transition': governance.get('freshness'),
            },
        },
    }
    sensing['any_sensed'] = bool(
        sensing['dtm']['sensed'] or sensing['reliefweb']['sensed'] or sensing['food_security']['sensed']
    )
    sensing['degraded'] = bool(
        not sensing['dtm']['sensed'] or
        not sensing['reliefweb']['sensed'] or
        not sensing['food_security']['sensed'] or
        sensing['static']['manual_review_due']
    )

    result = {
        'success': True,
        'module_version': MODULE_VERSION,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'from_cache': False,
        'data_period': STATIC_HUMANITARIAN['data_period'],
        'last_manual_update': STATIC_HUMANITARIAN['last_manual_update'],
        'last_manual_update_age_days': manual_age,
        'manual_review_due': sensing['static']['manual_review_due'],
        'static_freshness': static_freshness,

        'food_security': food_security,
        'displacement': displacement_data,
        'al_hol_camp': al_hol,
        'aleppo_emergency': aleppo,
        'cross_border_returns': returns,
        'governance_transition': governance,

        'dtm_raw': dtm_data,
        'reliefweb_reports': reliefweb_data.get('reports', []) if reliefweb_data else [],
        'reliefweb_appname': RELIEFWEB_APPNAME,

        'source_links': STATIC_HUMANITARIAN['source_links'],
        'sensing': sensing,
    }

    if _redis_available():
        _redis_set(CACHE_KEY, result)
        print(f"[Syria Humanitarian] Cached to Redis "
              f"(dtm={sensing['dtm']['state']} reliefweb={sensing['reliefweb']['state']} "
              f"static={static_freshness} degraded={sensing['degraded']})")

    return result


def _restamp_cached(cached):
    """
    A cached payload carries ages computed when it was WRITTEN. Six hours later
    those are off by six hours, and after a Redis key survives a quiet weekend
    they can be off by days. Recompute the static ages on the way out so the
    page never shows a frozen 'as_of_age_days'.
    """
    try:
        for key in ('displacement', 'al_hol_camp', 'aleppo_emergency',
                    'cross_border_returns', 'governance_transition'):
            if isinstance(cached.get(key), dict):
                age = _age_days(cached[key].get('as_of'))
                cached[key]['as_of_age_days'] = age
                cached[key]['freshness'] = _freshness(age)
                cached[key]['review_due'] = bool(
                    age is not None and age > STATIC_REVIEW_INTERVAL_DAYS)

        manual_age = _age_days(cached.get('last_manual_update'))
        cached['last_manual_update_age_days'] = manual_age
        cached['manual_review_due'] = bool(
            manual_age is not None and manual_age > STATIC_REVIEW_INTERVAL_DAYS)
        cached['static_freshness'] = _worst_freshness([
            (cached.get(k) or {}).get('freshness')
            for k in ('displacement', 'aleppo_emergency',
                      'cross_border_returns', 'governance_transition')
            if isinstance(cached.get(k), dict)
        ])
        cached['restamped_at'] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        print(f"[Syria Humanitarian] Restamp error (serving cache as-is): {str(e)[:120]}")
    return cached


def get_humanitarian_data(force_refresh=False):
    """Get Syria humanitarian data — Redis-first with 6-hour TTL."""
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
                        return _restamp_cached(cached)
                except Exception:
                    pass

    return _fetch_all_humanitarian()


# ========================================
# BACKGROUND REFRESH THREAD
# ========================================

def _background_humanitarian_refresh():
    """Background thread: refresh Syria humanitarian data every 6 hours."""
    print(f"[Syria Humanitarian] v{MODULE_VERSION} background refresh thread started (6h cycle)")
    time.sleep(60)  # Boot delay
    while True:
        try:
            print("[Syria Humanitarian] Running background refresh...")
            _fetch_all_humanitarian()
            fetch_all_news()
            print("[Syria Humanitarian] Background refresh complete (humanitarian + news)")
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
                'module_version': MODULE_VERSION,
                'error': str(e)[:200],
                'sensing': {
                    'any_sensed': False,
                    'degraded': True,
                    'state': 'module_error',
                    'generated_at': datetime.now(timezone.utc).isoformat(),
                },
                'static_fallback': {
                    'displacement': _stamp_static(STATIC_HUMANITARIAN['displacement']),
                    'al_hol_camp': _stamp_static(STATIC_HUMANITARIAN['al_hol_camp']),
                    'source_links': STATIC_HUMANITARIAN['source_links'],
                }
            }), 200

    @app.route('/api/syria/humanitarian/sources', methods=['GET'])
    def api_syria_humanitarian_sources():
        """Return all Syria humanitarian data source links."""
        return jsonify({
            'success': True,
            'module_version': MODULE_VERSION,
            'sources': STATIC_HUMANITARIAN['source_links'],
        })

    @app.route('/api/syria/news', methods=['GET'])
    def api_syria_news():
        """Syria news from all sources — cached."""
        force = request.args.get('force', 'false').lower() == 'true'
        try:
            data = get_news_data(force_refresh=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'success': False,
                'module_version': MODULE_VERSION,
                'error': str(e)[:200],
                'sensing': {'any_sensed': False, 'degraded': True, 'state': 'module_error'},
            }), 200

    @app.route('/debug/syria-dtm', methods=['GET'])
    def debug_syria_dtm():
        """Debug: test DTM API connection for Syria."""
        dtm_data = fetch_dtm_displacement()
        return jsonify({
            'module_version': MODULE_VERSION,
            'dtm_api_key_set': bool(DTM_API_KEY),
            'dtm_base_url': DTM_BASE_URL,
            'reliefweb_appname': RELIEFWEB_APPNAME,
            'result': dtm_data
        })

    @app.route('/debug/syria-sensing', methods=['GET'])
    def debug_syria_sensing():
        """
        Debug: what can this module actually see right now, and how old are the
        manual figures? Live probes -- bypasses cache, so use it sparingly.
        """
        hum = _fetch_all_humanitarian()
        return jsonify({
            'module_version': MODULE_VERSION,
            'user_agent': MODULE_USER_AGENT,
            'gdelt_gateway_available': GDELT_GATEWAY,
            'fews_net_available': _FEWS_AVAILABLE,
            'redis_available': _redis_available(),
            'humanitarian_sensing': hum.get('sensing'),
            'static_ages': {
                'last_manual_update': hum.get('last_manual_update'),
                'last_manual_update_age_days': hum.get('last_manual_update_age_days'),
                'static_freshness': hum.get('static_freshness'),
                'blocks': (hum.get('sensing') or {}).get('static', {}).get('blocks'),
            },
        })

    # Start background refresh thread
    thread = threading.Thread(target=_background_humanitarian_refresh, daemon=True)
    thread.start()

    print(f"[Syria Humanitarian] v{MODULE_VERSION} endpoints registered "
          f"(gdelt_gateway={GDELT_GATEWAY}, fews_net={_FEWS_AVAILABLE}) + background refresh started")
