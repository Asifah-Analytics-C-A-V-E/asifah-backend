"""
iran_strike_window_detector.py
================================================================
ASIFAH ANALYTICS — Iran Strike Window Detector v1.0.0
================================================================

Built May 22 2026.

PURPOSE
-------
Detects "operational window" conditions for potential US/Israel kinetic
action against Iran. Pulls signals from:
  - GDELT / RSS / News articles (passed in by caller)
  - Telegram via fetch_telegram_signals_iran() AND fetch_telegram_signals_israel()
  - Bluesky ME via fetch_bluesky_for_target('iran') and 'israel'
  - Existing military_tracker fingerprints (read from Redis)

SIGNAL CLASSES
--------------
  OSINT signals (verifiable, weight 1.0 each):
    1. Iran airspace closures (Tehran, Mehrabad, Imam Khomeini)
    2. Regional NOTAM cluster (UAE, Iraq, Jordan, Bahrain, Kuwait,
       Qatar, Israel, Saudi) — 2+ regional = high confidence
    3. Pre-strike posture — reads military_tracker iran_kinetic prose
    4. Embassy posture — reads base_evacuation signals from MIL
    5. Adversary defensive — IRGC dispersal, Iranian internal alerts,
       Iran civil defense activation (via Iranian Telegram channels)
    6. Principal-to-principal friction — Trump-Bibi calls, NSC
       activity, Israeli war cabinet meetings

  Rumored signals (weight 0.5 each, flagged):
    7. OSINT-Defender / WarTranslated / ClashReport / IntelSlava
       Iran-specific claims (from their Telegram + Bluesky channels)

  Calendar multipliers (act as amplifiers, NOT standalone signals):
    A. Market timing — US long weekend / holiday (x0.20)
    B. Religious calendar — Eid al-Adha, Hajj, Yom Kippur (x0.20)
    C. Lunar phase — new moon +/- 3 days = stealth-ops window (x0.15)
    D. POTUS location — DC vs Mar-a-Lago anomaly on weekend (x0.20)

  Final score = sum(OSINT signals) * (1.0 + sum(active multipliers))

ANALYTICAL PHILOSOPHY
---------------------
Reports WHAT signals are present, NOT WHETHER action is imminent.
Composite score is a *convergence* indicator. Frontend prose includes
explicit disclaimer.

Calendar signals are MULTIPLIERS, not standalone — otherwise we'd
generate monthly false positives.

BANDS
-----
  0.0-2.9   normal       (no convergence pattern)
  3.0-4.4   elevated     (early convergence — 2-3 weak signals)
  4.5-5.9   high         (clear convergence — 3-4 signals)
  6.0+      critical     (multi-signal convergence — 4+ OSINT signals)
================================================================
"""

import os
import json
import re
import threading
from datetime import datetime, timezone, timedelta
from math import cos, pi

try:
    import requests
except ImportError:
    requests = None

# ── Optional ingestion modules (graceful degrade) ──────────────────────
try:
    from telegram_signals import (
        fetch_telegram_signals_iran,
        fetch_telegram_signals_israel,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Strike Window] Telegram unavailable — degrading gracefully")

try:
    from bluesky_signals_me import fetch_bluesky_for_target as fetch_bluesky_me
    BLUESKY_ME_AVAILABLE = True
except ImportError:
    BLUESKY_ME_AVAILABLE = False
    print("[Strike Window] Bluesky ME unavailable — degrading gracefully")

# Optional: pattern memory module
try:
    from strike_window_history import save_snapshot, find_similar_events
    HISTORY_AVAILABLE = True
except ImportError:
    HISTORY_AVAILABLE = False


# ════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')   or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

STRIKE_WINDOW_CACHE_KEY  = 'iran_strike_window:current'
STRIKE_WINDOW_CACHE_TTL  = 6 * 3600   # 6h

DETECTOR_VERSION = '1.0.0'
DEFAULT_HOURS_BACK = 48   # 2-day look-back for environmental signals

OSINT_SIGNAL_WEIGHT  = 1.0
RUMORED_SIGNAL_WEIGHT = 0.5

BAND_THRESHOLDS = {
    'normal':   0.0,
    'elevated': 3.0,
    'high':     4.5,
    'critical': 6.0,
}


# ════════════════════════════════════════════════════════════════════════
# IRAN AIRSPACE KEYWORDS
# ════════════════════════════════════════════════════════════════════════
IRAN_AIRSPACE_KEYWORDS = [
    'tehran airspace closed', 'iran airspace closed', 'iranian airspace closed',
    'closed airspace over tehran', 'closed airspace iran',
    'tehran airport closed', 'imam khomeini airport closed',
    'mehrabad airport closed', 'mehrabad closed',
    'iran flight ban', 'iran no-fly', 'iranian flight ban',
    'iran airspace notam', 'tehran notam',
    'flights diverted iran', 'flights cancelled iran',
    'air corridor closed iran',
]


# ════════════════════════════════════════════════════════════════════════
# REGIONAL NOTAM KEYWORDS
# ════════════════════════════════════════════════════════════════════════
REGIONAL_NOTAM_KEYWORDS = {
    'uae': [
        'uae airspace closed', 'uae closes airspace', 'dubai airspace closed',
        'abu dhabi airspace closed', 'dubai airport closed', 'dxb closed',
        'uae notam', 'uae flight ban', 'emirates flights suspended',
    ],
    'iraq': [
        'iraq airspace closed', 'baghdad airspace closed', 'baghdad airport closed',
        'iraq closes airspace', 'iraq notam', 'iraq flight ban',
        'iraqi airspace closed', 'erbil airspace closed',
    ],
    'jordan': [
        'jordan airspace closed', 'amman airspace closed', 'jordanian airspace closed',
        'jordan closes airspace', 'jordan notam', 'queen alia airport closed',
    ],
    'bahrain': [
        'bahrain airspace closed', 'bahrain closes airspace', 'manama airspace',
        'bahrain notam', 'bahrain flight ban',
    ],
    'kuwait': [
        'kuwait airspace closed', 'kuwait closes airspace', 'kuwait notam',
        'kuwait flight ban', 'kuwait airport closed',
    ],
    'qatar': [
        'qatar airspace closed', 'qatar closes airspace', 'doha airspace closed',
        'qatar notam', 'qatar airways suspended', 'doha airport closed',
    ],
    'israel': [
        'israel airspace closed', 'ben gurion closed', 'ben gurion airport closed',
        'israel notam', 'tel aviv airspace closed', 'israeli flight ban',
    ],
    'saudi_arabia': [
        'saudi airspace closed', 'saudi arabia closes airspace', 'riyadh airspace closed',
        'jeddah airspace closed', 'saudi notam',
    ],
}


# ════════════════════════════════════════════════════════════════════════
# ADVERSARY DEFENSIVE KEYWORDS
# ════════════════════════════════════════════════════════════════════════
ADVERSARY_DEFENSIVE_KEYWORDS = [
    # IRGC mobilization
    'irgc dispersal', 'irgc mobilization', 'irgc forces mobilized',
    'sepah mobilized', 'sepah dispersal', 'sepah pasdaran alert',
    'basij mobilization', 'basij activated',
    # Air defense
    'iranian air defense activated', 'iranian air defense alert',
    'iran air defense scrambled', 'bavar 373 activated',
    'iran tor m1 deployed', 'iranian s-300 active',
    'khordad 15 active', '15 khordad active',
    # Internal/civil defense
    'iran internal alert', 'iran nationwide alert',
    'iran civil defense', 'iranian civil defense drill',
    'iran shelter drill', 'iran preparedness',
    # Comms/cyber
    'iranian military communications', 'iranian military blackout',
    'iran cyber blackout', 'iran internet shutdown',
    'iran communications jammed',
    # Nuclear sites
    'iranian missile bases dispersed', 'iran hardened sites alert',
    'fordow active', 'fordow alert', 'natanz alert', 'parchin alert',
    'iran nuclear facility lockdown', 'isfahan facility alert',
    'arak alert', 'bushehr alert',
    # General
    'iran forces dispersal', 'iran military prepositioning',
    'iran combat readiness', 'iran armed forces alert',
]


# ════════════════════════════════════════════════════════════════════════
# PRINCIPAL FRICTION KEYWORDS
# ════════════════════════════════════════════════════════════════════════
PRINCIPAL_FRICTION_KEYWORDS = [
    # Trump-Netanyahu direct
    'trump bibi call', 'trump netanyahu call', 'trump-netanyahu call',
    'trump-bibi call', 'trump calls bibi', 'trump calls netanyahu',
    'trump bibi heated', 'trump netanyahu heated',
    'trump netanyahu disagree', 'trump bibi disagree',
    'trump netanyahu argument', 'trump bibi argument',
    'trump rebuffs netanyahu', 'trump pushes back netanyahu',
    'netanyahu pushes trump', 'bibi pushes trump',
    'trump israel friction', 'trump israel disagree',
    'trump warns netanyahu', 'trump warns bibi',
    # NSC / Situation Room
    'nsc meeting iran', 'national security council iran',
    'situation room iran', 'sit room iran',
    'principals committee iran', 'deputies committee iran',
    'oval office iran meeting',
    'emergency nsc meeting', 'urgent nsc meeting',
    'urgent national security meeting',
    # Cabinet movement
    'secdef pentagon late', 'cabinet officials gather',
    'cabinet meeting iran', 'urgent cabinet meeting',
    # Israeli war cabinet
    'netanyahu war cabinet', 'israeli war cabinet meeting',
    'idf chief of staff statement', 'mossad chief meeting',
    'gallant emergency meeting',
    # Intelligence
    'cia director iran briefing', 'dni iran briefing',
]


# ════════════════════════════════════════════════════════════════════════
# RUMORED SIGNALS
# ════════════════════════════════════════════════════════════════════════
RUMORED_OSINT_HANDLES = [
    'osintdefender', 'osint defender', 'sentdefender',
    'wartranslated', 'war translated',
    'clashreport', 'clash report',
    'intelslava', 'intel slava',
    'noelreports', 'noel reports',
]

RUMORED_IRAN_KEYWORDS = [
    'iran strike imminent', 'iran kinetic imminent',
    'iran action this weekend', 'iran strike weekend',
    'us preparing strike iran', 'israel preparing strike iran',
    'iran nuclear strike planning', 'iran target list',
    'b-2 sortie iran', 'iran kinetic operation',
    'sources iran strike', 'sources iran action',
    'aircraft positioning iran', 'naval positioning iran strike',
    'sources iran imminent', 'reports iran imminent',
    'breaking iran strike', 'iran operation imminent',
    'final preparations iran', 'final preparations israel',
]


# ════════════════════════════════════════════════════════════════════════
# REDIS HELPERS
# ════════════════════════════════════════════════════════════════════════

def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN and requests):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        data = resp.json()
        if data.get("result"):
            return json.loads(data["result"])
    except Exception as e:
        print(f"[Strike Window] Redis get error ({key}): {str(e)[:100]}")
    return None


def _redis_set(key, value, ttl=STRIKE_WINDOW_CACHE_TTL):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN and requests):
        return False
    try:
        from urllib.parse import quote
        payload = quote(json.dumps(value), safe='')
        url = f"{UPSTASH_REDIS_URL}/set/{key}/{payload}"
        if ttl:
            url += f"?EX={ttl}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Strike Window] Redis set error ({key}): {str(e)[:100]}")
        return False


# ════════════════════════════════════════════════════════════════════════
# ARTICLE TEXT HELPERS
# ════════════════════════════════════════════════════════════════════════

def _article_text(art):
    if not isinstance(art, dict):
        return ''
    pieces = [
        art.get('title') or '',
        art.get('description') or '',
        art.get('content') or '',
    ]
    return ' '.join(pieces).lower()


def _article_source(art):
    if not isinstance(art, dict):
        return ''
    src = art.get('source')
    if isinstance(src, dict):
        return (src.get('name') or '').lower()
    return str(src or '').lower()


def _scan_keywords(articles, keyword_list, max_matches=10):
    matches = []
    for art in articles or []:
        if len(matches) >= max_matches:
            break
        text = _article_text(art)
        if not text:
            continue
        for kw in keyword_list:
            if kw in text:
                matches.append({'article': art, 'keyword': kw})
                break
    return matches


# ════════════════════════════════════════════════════════════════════════
# CALENDAR MULTIPLIERS
# ════════════════════════════════════════════════════════════════════════

def _first_weekday_of_month(year, month, weekday):
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    days_forward = (weekday - d.weekday()) % 7
    return d + timedelta(days=days_forward)


def _nth_weekday_of_month(year, month, weekday, n):
    first = _first_weekday_of_month(year, month, weekday)
    return first + timedelta(days=7 * (n - 1))


def _is_us_long_weekend(now=None):
    now = now or datetime.now(timezone.utc)
    year = now.year

    may_last = datetime(year, 5, 31, tzinfo=timezone.utc)
    days_back = (may_last.weekday() - 0) % 7
    memorial_day = may_last - timedelta(days=days_back)

    holidays = [
        ('Memorial Day',     memorial_day),
        ('Independence Day', datetime(year, 7, 4, tzinfo=timezone.utc)),
        ('Labor Day',        _first_weekday_of_month(year, 9, 0)),
        ('Thanksgiving',     _nth_weekday_of_month(year, 11, 3, 4)),
        ('Christmas',        datetime(year, 12, 25, tzinfo=timezone.utc)),
        ('New Years Eve',    datetime(year, 12, 31, tzinfo=timezone.utc)),
    ]

    for name, h_date in holidays:
        days_diff = abs((now - h_date).days)
        if days_diff <= 3:
            return {
                'active': True,
                'name': f'US {name}',
                'days_offset': (h_date - now).days,
                'rationale': (
                    f'Within +/- 3 days of US {name} — markets closed/long weekend window. '
                    f'Operational discretion historically favors low-attention windows.'
                ),
            }
    return {'active': False}


def _is_religious_window(now=None):
    now = now or datetime.now(timezone.utc)
    religious_dates_2026 = [
        ('Eid al-Adha',       datetime(2026, 5, 27, tzinfo=timezone.utc)),
        ('Hajj (begins)',     datetime(2026, 5, 24, tzinfo=timezone.utc)),
        ('Hajj (ends)',       datetime(2026, 5, 29, tzinfo=timezone.utc)),
        ('Ashura',            datetime(2026, 7, 15, tzinfo=timezone.utc)),
        ("Tisha B'Av",        datetime(2026, 7, 23, tzinfo=timezone.utc)),
        ('Mawlid al-Nabi',    datetime(2026, 9, 23, tzinfo=timezone.utc)),
        ('Rosh Hashanah',     datetime(2026, 9, 12, tzinfo=timezone.utc)),
        ('Yom Kippur',        datetime(2026, 9, 21, tzinfo=timezone.utc)),
    ]

    for name, date in religious_dates_2026:
        days_diff = (date - now).days
        if 0 <= days_diff <= 7:
            return {
                'active': True,
                'name': name,
                'days_until': days_diff,
                'rationale': (
                    f"{name} begins in {days_diff} day(s) — "
                    f"strategic operational consideration to act before/after religious window."
                ),
            }
        if -3 <= days_diff < 0:
            return {
                'active': True,
                'name': f'{name} (just passed)',
                'days_since': abs(days_diff),
                'rationale': (
                    f"{name} ended {abs(days_diff)} day(s) ago — "
                    f"post-religious window operational consideration."
                ),
            }
    return {'active': False}


def _is_dark_lunar_window(now=None):
    now = now or datetime.now(timezone.utc)
    reference = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    synodic_month = 29.530588853

    days_since_ref = (now - reference).total_seconds() / 86400.0
    moons_since_ref = days_since_ref / synodic_month
    phase = moons_since_ref - int(moons_since_ref)

    if phase <= 0.5:
        days_from_new = phase * synodic_month
    else:
        days_from_new = (1.0 - phase) * synodic_month

    illuminated = round(0.5 * (1 - cos(phase * 2 * pi)), 2)

    if days_from_new <= 3:
        return {
            'active': True,
            'phase_days_from_new_moon': round(days_from_new, 1),
            'phase_fraction_illuminated': illuminated,
            'rationale': (
                f"Within +/- 3 days of new moon ({round(days_from_new, 1)} days). "
                f"Stealth-ops operational preference window."
            ),
        }
    return {
        'active': False,
        'phase_days_from_new_moon': round(days_from_new, 1),
        'phase_fraction_illuminated': illuminated,
    }


def _detect_potus_location_anomaly(articles):
    if not articles:
        return {'active': False, 'note': 'no articles to analyze'}

    text_combined = ' '.join(_article_text(a) for a in articles[:300])

    in_dc_signals = [
        'trump in dc', 'trump in washington', 'trump remained in washington',
        'trump stays in dc', 'trump stayed in washington',
        'potus white house weekend', 'trump white house weekend',
        'trump in d.c.', 'cabinet at white house weekend',
    ]
    mar_a_lago_signals = [
        'mar-a-lago', 'mar a lago', 'maralago',
        'trump bedminster', 'trump golf weekend',
    ]
    camp_david_signals = ['camp david']

    in_dc = any(s in text_combined for s in in_dc_signals)
    at_retreat = any(s in text_combined for s in mar_a_lago_signals)
    at_camp_david = any(s in text_combined for s in camp_david_signals)

    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() >= 5

    if in_dc and not at_retreat and is_weekend:
        return {
            'active': True,
            'location': 'Washington DC (anomalous for weekend)',
            'rationale': (
                'POTUS reported in Washington DC during weekend window — '
                'anomalous vs typical Mar-a-Lago/Bedminster retreat pattern. '
                'Decision-maker positioning indicator.'
            ),
        }
    if at_camp_david:
        return {
            'active': True,
            'location': 'Camp David',
            'rationale': (
                'POTUS at Camp David — operational retreat venue, '
                'historically associated with active national-security deliberations.'
            ),
        }
    if at_retreat:
        return {'active': False, 'location': 'Mar-a-Lago / Bedminster (typical)'}
    return {'active': False, 'note': 'no POTUS location signal in current scan'}


# ════════════════════════════════════════════════════════════════════════
# CROSS-READ FROM MILITARY_TRACKER FINGERPRINTS
# ════════════════════════════════════════════════════════════════════════

def _read_iran_kinetic_fingerprint():
    cache = _redis_get('military_tracker_cache') or {}
    interp = cache.get('interpretation') or {}
    iran_kinetic = interp.get('iran_kinetic_prose') or {}

    if iran_kinetic.get('active'):
        return {
            'present': True,
            'severity': iran_kinetic.get('severity', 'elevated'),
            'pattern': iran_kinetic.get('pattern_detected', ''),
            'matched_phrases': iran_kinetic.get('matched_phrases', [])[:5],
            'rationale': iran_kinetic.get('prose', '')[:300],
        }
    return {'present': False}


def _read_embassy_evacuation_fingerprint():
    cache = _redis_get('military_tracker_cache') or {}
    evac_alerts = cache.get('evacuation_alerts') or []

    me_targets = ['iran', 'iraq', 'jordan', 'bahrain', 'kuwait', 'qatar',
                  'lebanon', 'israel', 'saudi_arabia', 'uae']
    me_alerts = []
    for alert in evac_alerts:
        actor = (alert.get('actor') or '').lower()
        title = (alert.get('title') or '').lower()
        if actor in me_targets or any(t in title for t in me_targets):
            me_alerts.append(alert)

    if me_alerts:
        return {
            'present': True,
            'count': len(me_alerts),
            'top_alerts': me_alerts[:3],
            'rationale': (
                f'{len(me_alerts)} active ME embassy/evacuation alert(s) '
                f'cross-read from military_tracker fingerprints.'
            ),
        }
    return {'present': False}


# ════════════════════════════════════════════════════════════════════════
# SIGNAL DETECTORS
# ════════════════════════════════════════════════════════════════════════

def detect_iran_airspace(articles):
    matches = _scan_keywords(articles, IRAN_AIRSPACE_KEYWORDS, max_matches=5)
    if not matches:
        return {'active': False}
    return {
        'active': True,
        'confidence': 'osint',
        'weight': OSINT_SIGNAL_WEIGHT,
        'match_count': len(matches),
        'top_matches': [
            {
                'title': (m['article'].get('title') or '')[:140],
                'url':   m['article'].get('url', ''),
                'source': _article_source(m['article']),
                'keyword': m['keyword'],
            }
            for m in matches[:3]
        ],
        'rationale': (
            f'{len(matches)} signal(s) reporting Iranian airspace closures '
            f'(Tehran, Mehrabad, Imam Khomeini, or corridors).'
        ),
    }


def detect_regional_notams(articles):
    countries_with_signals = {}
    for country, keywords in REGIONAL_NOTAM_KEYWORDS.items():
        matches = _scan_keywords(articles, keywords, max_matches=3)
        if matches:
            countries_with_signals[country] = matches

    if not countries_with_signals:
        return {'active': False}

    country_list = sorted(countries_with_signals.keys())
    n = len(country_list)
    if n >= 3:
        weight_modifier = 1.3
        rationale_prefix = 'REGIONAL NOTAM CLUSTER — HIGH SIGNAL'
    elif n == 2:
        weight_modifier = 1.0
        rationale_prefix = 'Regional NOTAM cluster forming'
    else:
        weight_modifier = 0.7
        rationale_prefix = 'Single regional NOTAM'

    top_matches = []
    for country in country_list:
        m = countries_with_signals[country][0]
        top_matches.append({
            'country': country.upper(),
            'title':   (m['article'].get('title') or '')[:140],
            'url':     m['article'].get('url', ''),
            'source':  _article_source(m['article']),
            'keyword': m['keyword'],
        })

    return {
        'active': True,
        'confidence': 'osint',
        'weight': OSINT_SIGNAL_WEIGHT * weight_modifier,
        'countries_with_notams': country_list,
        'country_count': n,
        'top_matches': top_matches[:5],
        'rationale': (
            f'{rationale_prefix}: {n} regional countries reporting airspace closures '
            f'({", ".join(country_list).upper()}). UAE/Iraq/Jordan/Bahrain/Kuwait/Qatar '
            f'rarely close airspace — clustering is a high-fidelity indicator.'
        ),
    }


def detect_pre_strike_posture():
    fp = _read_iran_kinetic_fingerprint()
    if not fp.get('present'):
        return {'active': False}

    severity = fp.get('severity', 'elevated')
    weight_map = {'elevated': 0.7, 'high': 1.0, 'surge': 1.3}
    weight = OSINT_SIGNAL_WEIGHT * weight_map.get(severity, 0.7)

    return {
        'active': True,
        'confidence': 'osint',
        'weight': weight,
        'severity': severity,
        'pattern': fp.get('pattern', ''),
        'matched_phrases': fp.get('matched_phrases', []),
        'rationale': (
            f'Military tracker detecting Iran kinetic posture at {severity.upper()} severity '
            f'({fp.get("pattern", "multi-pattern")}). Cross-reads B-2/B-21 staging, '
            f'Ben Gurion launch language, troop surge, or Diego Garcia bomber signals.'
        ),
    }


def detect_embassy_posture():
    fp = _read_embassy_evacuation_fingerprint()
    if fp.get('present'):
        return {
            'active': True,
            'confidence': 'osint',
            'weight': OSINT_SIGNAL_WEIGHT,
            'count': fp.get('count', 0),
            'rationale': fp.get('rationale', 'ME embassy alerts active'),
        }
    return {'active': False}


def detect_adversary_defensive(articles):
    matches = _scan_keywords(articles, ADVERSARY_DEFENSIVE_KEYWORDS, max_matches=8)
    if not matches:
        return {'active': False}

    iranian_official_sources = [
        'nour_news', 'nour news', 'sepah_pasdaran', 'sepah pasdaran',
        'iribnews', 'irib news', 'khamenei_ir',
        'tasnim', 'fars news', 'press tv', 'mashregh',
    ]
    has_iranian_source = any(
        any(ir_src in _article_source(m['article']) for ir_src in iranian_official_sources)
        for m in matches
    )

    weight_modifier = 1.3 if has_iranian_source else 1.0

    return {
        'active': True,
        'confidence': 'osint',
        'weight': OSINT_SIGNAL_WEIGHT * weight_modifier,
        'match_count': len(matches),
        'iranian_sourced': has_iranian_source,
        'top_matches': [
            {
                'title': (m['article'].get('title') or '')[:140],
                'url':   m['article'].get('url', ''),
                'source': _article_source(m['article']),
                'keyword': m['keyword'],
            }
            for m in matches[:4]
        ],
        'rationale': (
            f'{len(matches)} adversary-defensive signal(s) detected'
            + (' (Iranian state/IRGC channels reporting own posture — HIGH CONFIDENCE)' if has_iranian_source else '')
            + '. Patterns include IRGC dispersal, civil defense activation, '
            'air defense alerts, or nuclear-site lockdown language.'
        ),
    }


def detect_principal_friction(articles):
    matches = _scan_keywords(articles, PRINCIPAL_FRICTION_KEYWORDS, max_matches=8)
    if not matches:
        return {'active': False}

    return {
        'active': True,
        'confidence': 'osint',
        'weight': OSINT_SIGNAL_WEIGHT,
        'match_count': len(matches),
        'top_matches': [
            {
                'title': (m['article'].get('title') or '')[:140],
                'url':   m['article'].get('url', ''),
                'source': _article_source(m['article']),
                'keyword': m['keyword'],
            }
            for m in matches[:4]
        ],
        'rationale': (
            f'{len(matches)} principal-friction signal(s) — Trump-Netanyahu communications, '
            f'NSC/Situation Room activity, or Israeli war cabinet meetings.'
        ),
    }


def detect_rumored_signals(articles):
    matches = _scan_keywords(articles, RUMORED_IRAN_KEYWORDS, max_matches=10)

    influencer_matches = []
    for art in articles or []:
        src = _article_source(art)
        if any(handle in src for handle in RUMORED_OSINT_HANDLES):
            text = _article_text(art)
            if 'iran' in text and any(w in text for w in ['strike', 'kinetic', 'imminent',
                                                          'positioning', 'staging', 'sortie']):
                influencer_matches.append({
                    'article': art,
                    'keyword': '(influencer + iran context)',
                })

    all_matches = matches + influencer_matches
    if not all_matches:
        return {'active': False}

    seen = set()
    unique = []
    for m in all_matches:
        url = m['article'].get('url', '')
        if url and url not in seen:
            seen.add(url)
            unique.append(m)

    return {
        'active': True,
        'confidence': 'rumored',
        'weight': RUMORED_SIGNAL_WEIGHT,
        'match_count': len(unique),
        'top_matches': [
            {
                'title': (m['article'].get('title') or '')[:140],
                'url':   m['article'].get('url', ''),
                'source': _article_source(m['article']),
                'keyword': m['keyword'],
            }
            for m in unique[:5]
        ],
        'rationale': (
            f'{len(unique)} rumored signal(s) from OSINT influencer accounts '
            f'(OSINTdefender, ClashReport, WarTranslated, IntelSlava). '
            f'RUMORED CONFIDENCE — flagged accordingly, weight 0.5.'
        ),
    }


# ════════════════════════════════════════════════════════════════════════
# ARTICLE INGESTION
# ════════════════════════════════════════════════════════════════════════

def _ingest_signals(hours_back=DEFAULT_HOURS_BACK, extra_articles=None):
    all_articles = list(extra_articles or [])

    if TELEGRAM_AVAILABLE:
        try:
            iran_tg = fetch_telegram_signals_iran(hours_back=hours_back) or []
            all_articles.extend(iran_tg)
            print(f"[Strike Window] Iran Telegram: {len(iran_tg)} messages")
        except Exception as e:
            print(f"[Strike Window] Iran Telegram error: {str(e)[:150]}")

        try:
            israel_tg = fetch_telegram_signals_israel(hours_back=hours_back) or []
            all_articles.extend(israel_tg)
            print(f"[Strike Window] Israel Telegram: {len(israel_tg)} messages")
        except Exception as e:
            print(f"[Strike Window] Israel Telegram error: {str(e)[:150]}")

    if BLUESKY_ME_AVAILABLE:
        try:
            iran_bsky = fetch_bluesky_me('iran', days=max(1, hours_back // 24)) or []
            all_articles.extend(iran_bsky)
            print(f"[Strike Window] Iran Bluesky: {len(iran_bsky)} posts")
        except Exception as e:
            print(f"[Strike Window] Iran Bluesky error: {str(e)[:150]}")

        try:
            israel_bsky = fetch_bluesky_me('israel', days=max(1, hours_back // 24)) or []
            all_articles.extend(israel_bsky)
            print(f"[Strike Window] Israel Bluesky: {len(israel_bsky)} posts")
        except Exception as e:
            print(f"[Strike Window] Israel Bluesky error: {str(e)[:150]}")

    seen = set()
    unique = []
    for art in all_articles:
        url = art.get('url', '') if isinstance(art, dict) else ''
        if url and url not in seen:
            seen.add(url)
            unique.append(art)
        elif not url:
            unique.append(art)

    print(f"[Strike Window] Total deduped articles: {len(unique)}")
    return unique


# ════════════════════════════════════════════════════════════════════════
# MAIN DETECTION FUNCTION
# ════════════════════════════════════════════════════════════════════════

def run_strike_window_detection(hours_back=DEFAULT_HOURS_BACK, extra_articles=None):
    print(f"[Strike Window] Running detection ({hours_back}h look-back)")
    now = datetime.now(timezone.utc)

    articles = _ingest_signals(hours_back=hours_back, extra_articles=extra_articles)

    signals = {
        'iran_airspace':       detect_iran_airspace(articles),
        'regional_notams':     detect_regional_notams(articles),
        'pre_strike_posture':  detect_pre_strike_posture(),
        'embassy_posture':     detect_embassy_posture(),
        'adversary_defensive': detect_adversary_defensive(articles),
        'principal_friction':  detect_principal_friction(articles),
        'rumored':             detect_rumored_signals(articles),
    }

    calendar_multipliers = {
        'us_long_weekend':   _is_us_long_weekend(now),
        'religious_window':  _is_religious_window(now),
        'dark_lunar_window': _is_dark_lunar_window(now),
        'potus_anomaly':     _detect_potus_location_anomaly(articles),
    }

    base_score = sum(
        s.get('weight', 0) for s in signals.values() if s.get('active')
    )

    multiplier_weights = {
        'us_long_weekend':   0.20,
        'religious_window':  0.20,
        'dark_lunar_window': 0.15,
        'potus_anomaly':     0.20,
    }
    multiplier_total = 1.0
    for k, m in calendar_multipliers.items():
        if m.get('active'):
            multiplier_total += multiplier_weights.get(k, 0.0)

    composite_score = round(base_score * multiplier_total, 2)

    if composite_score >= BAND_THRESHOLDS['critical']:
        severity = 'critical'
    elif composite_score >= BAND_THRESHOLDS['high']:
        severity = 'high'
    elif composite_score >= BAND_THRESHOLDS['elevated']:
        severity = 'elevated'
    else:
        severity = 'normal'

    active_signals = [k for k, s in signals.items() if s.get('active')]
    active_multipliers = [k for k, m in calendar_multipliers.items() if m.get('active')]

    if severity == 'critical':
        rationale = (
            f"CRITICAL CONVERGENCE — {len(active_signals)} active signals, "
            f"composite {composite_score} (base {round(base_score,2)} x "
            f"multiplier {round(multiplier_total,2)}). Multiple operational-window "
            f"indicators aligned simultaneously."
        )
    elif severity == 'high':
        rationale = (
            f"HIGH CONVERGENCE — {len(active_signals)} active signals, "
            f"composite {composite_score}. Clear convergence pattern forming."
        )
    elif severity == 'elevated':
        rationale = (
            f"ELEVATED — {len(active_signals)} active signals, "
            f"composite {composite_score}. Early convergence pattern detected."
        )
    else:
        rationale = (
            f"Normal — {len(active_signals)} active signal(s), composite {composite_score}. "
            f"No convergence pattern detected."
        )

    disclaimer = (
        "ANALYTICAL DISCLAIMER: This composite score is a CONVERGENCE indicator, "
        "NOT a probability of action. Active signals indicate that operational-window "
        "CONDITIONS are present; they do not predict whether or when kinetic action "
        "will occur. Reader should form independent judgment from underlying signals."
    )

    result = {
        'timestamp': now.isoformat(),
        'version': DETECTOR_VERSION,
        'signals': signals,
        'calendar_multipliers': calendar_multipliers,
        'base_score': round(base_score, 2),
        'multiplier_total': round(multiplier_total, 2),
        'composite_score': composite_score,
        'severity': severity,
        'active_signal_count': len(active_signals),
        'active_multiplier_count': len(active_multipliers),
        'active_signals': active_signals,
        'active_multipliers': active_multipliers,
        'rationale': rationale,
        'disclaimer': disclaimer,
        'articles_analyzed': len(articles),
    }

    _redis_set(STRIKE_WINDOW_CACHE_KEY, result, ttl=STRIKE_WINDOW_CACHE_TTL)

    if HISTORY_AVAILABLE and severity in ('elevated', 'high', 'critical'):
        try:
            save_snapshot(result)
            print(f"[Strike Window] Snapshot saved (severity: {severity})")
        except Exception as e:
            print(f"[Strike Window] Snapshot save error: {str(e)[:150]}")

    if HISTORY_AVAILABLE:
        try:
            similar = find_similar_events(active_signals, limit=5)
            result['similar_historical_events'] = similar
        except Exception as e:
            print(f"[Strike Window] Similarity search error: {str(e)[:150]}")
            result['similar_historical_events'] = []
    else:
        result['similar_historical_events'] = []

    print(f"[Strike Window] DONE. Severity: {severity.upper()}, "
          f"composite {composite_score}, {len(active_signals)} signals, "
          f"{len(active_multipliers)} multipliers active")
    return result


def get_cached_strike_window():
    return _redis_get(STRIKE_WINDOW_CACHE_KEY)


# ════════════════════════════════════════════════════════════════════════
# FLASK ENDPOINTS REGISTRATION
# ════════════════════════════════════════════════════════════════════════

_scan_running_lock = threading.Lock()
_scan_in_progress = False


def register_strike_window_endpoints(app):
    from flask import request, jsonify

    @app.route('/api/iran-strike-window', methods=['GET'])
    def iran_strike_window():
        global _scan_in_progress

        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        hours = int(request.args.get('hours_back', DEFAULT_HOURS_BACK))

        if force:
            print("[Strike Window] Force refresh requested")
            try:
                result = run_strike_window_detection(hours_back=hours)
                return jsonify(result)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return jsonify({'success': False, 'error': str(e)[:300]}), 500

        cached = get_cached_strike_window()
        if cached:
            cached['cached'] = True
            return jsonify(cached)

        with _scan_running_lock:
            if not _scan_in_progress:
                _scan_in_progress = True

                def _bg():
                    global _scan_in_progress
                    try:
                        run_strike_window_detection(hours_back=hours)
                    except Exception as e:
                        print(f"[Strike Window] BG scan error: {str(e)[:200]}")
                    finally:
                        _scan_in_progress = False

                threading.Thread(target=_bg, daemon=True).start()

        return jsonify({
            'awaiting_scan': True,
            'version': DETECTOR_VERSION,
            'message': 'First scan in progress — check back in 2-3 minutes',
            'severity': 'unknown',
            'composite_score': 0,
        })

    @app.route('/api/iran-strike-window/history', methods=['GET'])
    def iran_strike_window_history():
        if not HISTORY_AVAILABLE:
            return jsonify({
                'available': False,
                'message': 'strike_window_history module not loaded',
            })
        from strike_window_history import get_all_snapshots, get_labeled_events
        try:
            limit = int(request.args.get('limit', 20))
            return jsonify({
                'available': True,
                'snapshots': get_all_snapshots(limit=limit),
                'labeled_events': get_labeled_events(),
            })
        except Exception as e:
            return jsonify({'error': str(e)[:200]}), 500

    @app.route('/api/iran-strike-window/log-event', methods=['POST'])
    def iran_strike_window_log_event():
        if not HISTORY_AVAILABLE:
            return jsonify({
                'success': False,
                'message': 'strike_window_history module not loaded',
            }), 503
        from strike_window_history import log_labeled_event
        try:
            data = request.get_json(force=True) or {}
            event_id    = data.get('event_id')
            event_label = data.get('event_label', '')
            event_type  = data.get('event_type', 'kinetic_action')
            notes       = data.get('notes', '')

            if not event_id:
                return jsonify({'success': False, 'error': 'event_id required'}), 400

            saved = log_labeled_event(
                event_id=event_id,
                event_label=event_label,
                event_type=event_type,
                notes=notes,
            )
            return jsonify({'success': True, 'event': saved})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    print("[Strike Window] Endpoints registered: /api/iran-strike-window, /history, /log-event")


# ════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print(f"[Strike Window] Self-test running...")
    result = run_strike_window_detection(hours_back=24)
    print()
    print(f"  Severity:        {result['severity']}")
    print(f"  Composite score: {result['composite_score']}")
    print(f"  Base score:      {result['base_score']}")
    print(f"  Multiplier:      {result['multiplier_total']}")
    print(f"  Active signals:  {', '.join(result['active_signals'])}")
    print(f"  Active multipliers: {', '.join(result['active_multipliers'])}")
    print(f"  Rationale:       {result['rationale']}")
