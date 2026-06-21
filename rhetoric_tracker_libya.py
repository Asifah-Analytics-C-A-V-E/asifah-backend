"""
Asifah Analytics — Libya Rhetoric & Escalation Tracker v1.0.0
June 2026

Cloned from the Lebanon gold-standard tracker (v2.0.0 architecture) and
transformed for the Libya theatre. Keeps the full machinery: multi-vector
threat scoring, delta vs prior scan, specificity scoring (0-10), EMA actor
baselines, silence-anomaly detection, cross-theater fingerprints, conditional
("if X then Y") tripwire parsing, and the diplomatic-track modifier.

ACTORS (7):
  - GNU / Tripoli (Dbeibah)        western, UN-recognized government
  - LNA / HoR / Tobruk (Haftar)    eastern military / parliament
  - UNSMIL / UN                    mediation / diplomatic off-ramp
  - Russia / Africa Corps          external patron, Sahel linchpin
  - Turkey                         GNU backer (drones / East Med) -- Projection-Node spoke
  - Egypt + UAE                    LNA external backers
  - Italy / EU                     migration + energy (ENI) leverage

VECTORS (code keys kept stable from the Lebanon clone; see VECTOR_LABELS):
  ground_ops        -> Militia & Ground Clashes
  rockets           -> Oil & Economic Leverage   (most-acute weight x7)
  ceasefire         -> Diplomacy & Elections      (drives diplomatic modifier)
  crossborder       -> Foreign Force & Cross-theater
  internal_fracture -> East–West Institutional Fracture
  + CONDITIONAL tripwire vector

SOURCES:
  - RSS: Libya Herald/Observer/Update/Address, Al-Marsad, Al-Wasat (AR),
    ANSAMed + Agenzia Nova (IT -- migration/ENI/Mattei angle), UN News,
    AllAfrica, Reuters/Al Jazeera (Google-News routed)
  - GDELT multi-language: English + Arabic + Italian (ita)
  - Telegram (Libya channel subset), Nitter (institutional, fails soft)

CACHING:
  - Upstash Redis (REST) -- same instance as all backends
  - 12-hour background scan cycle; endpoint serves cache, never blocks
  - History: rhetoric:libya:history (rolling)
  - Baselines: rhetoric_baseline:libya (30-day TTL)
  - Cross-theater: rhetoric:crosstheater:fingerprints (READS + WRITES 'libya')

ENDPOINTS:
  - /api/rhetoric/libya          full analysis
  - /api/rhetoric/libya/summary  compact for card/index integration
  - /api/rhetoric/libya/trends   historical trend data
  - /api/rhetoric/libya/history  rolling history for chart rendering

NOTE: Sensor reads (Oil Pulse + displacement modifiers) and the
turkey:theater_footprints['libya'] Projection-Node emit are added in Slice 2.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""
print("[Rhetoric Tracker] Module loading...")

# ========================================
# IMPORTS
# ========================================
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import re
import json
import time
import os
import threading
from collections import defaultdict

# Signal interpreter -- So What, Red Lines, Historical Patterns + canonical top_signals
try:
    from libya_signal_interpreter import (
        interpret_signals as libya_interpret_signals,
        build_top_signals as libya_build_top_signals,
    )
    INTERPRETER_AVAILABLE = True
    print("[Libya Rhetoric] Signal interpreter loaded (incl. build_top_signals v2.0)")
except Exception as e:
    import traceback as _tb
    INTERPRETER_AVAILABLE = False
    libya_build_top_signals = None
    print(f"[Libya Rhetoric] Warning: Signal interpreter not available: {e}")
    _tb.print_exc()

# Telegram signal source
try:
    from telegram_signals import fetch_telegram_signals
    TELEGRAM_AVAILABLE = True
    print("[Rhetoric Tracker] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Rhetoric Tracker] ⚠️ Telegram signals not available")

# ========================================
# CONFIGURATION
# ========================================

NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY')
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Upstash Redis — REST API pattern (matches Yemen/Iraq/Syria)
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

# Legacy redis-py fallback (kept for backward compat)
REDIS_URL = os.environ.get('REDIS_URL', os.environ.get('REDIS_TOKEN', None))

# Cache keys — unified pattern
RHETORIC_CACHE_KEY    = 'rhetoric:libya:latest'
RHETORIC_HISTORY_KEY  = 'rhetoric:libya:history'       # lpush rolling list (120 entries)
RHETORIC_LEGACY_HISTORY_KEY = 'rhetoric:libya:history:intraday'  # old key, kept for compat
BASELINE_KEY          = 'rhetoric_baseline:libya'
CROSSTHEATER_KEY      = 'rhetoric:crosstheater:fingerprints'  # shared with Yemen/Iraq/Syria

SCAN_INTERVAL_HOURS   = 12
SCAN_INTERVAL_SECONDS = SCAN_INTERVAL_HOURS * 3600

_scan_running = False
_scan_lock    = threading.Lock()


# ========================================
# REDIS HELPERS — Upstash REST (primary) + redis-py fallback
# ========================================

_redis_client = None

def _init_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if REDIS_URL:
        try:
            import redis
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5)
            _redis_client.ping()
            print("[Rhetoric Cache] ✅ redis-py connected")
            return _redis_client
        except Exception as e:
            print(f"[Rhetoric Cache] redis-py failed: {e}")
            _redis_client = None
    return None


def _redis_get(key):
    """Get from Redis — Upstash REST primary, redis-py fallback."""
    # Upstash REST first
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{key}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get('result'):
                return json.loads(data['result'])
        except Exception as e:
            print(f"[Rhetoric Cache] Upstash GET error: {e}")

    # redis-py fallback
    client = _init_redis()
    if client:
        try:
            data = client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            print(f"[Rhetoric Cache] redis-py GET error: {e}")

    return None


def _redis_set(key, value, ttl=43200):
    """Set in Redis — Upstash REST primary, redis-py fallback. ttl in seconds."""
    payload = json.dumps(value, default=str)

    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.post(
                f"{UPSTASH_REDIS_URL}/set/{key}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                data=payload,
                params={"EX": ttl},
                timeout=5
            )
            return resp.json().get('result') == 'OK'
        except Exception as e:
            print(f"[Rhetoric Cache] Upstash SET error: {e}")

    client = _init_redis()
    if client:
        try:
            client.setex(key, ttl, payload)
            return True
        except Exception as e:
            print(f"[Rhetoric Cache] redis-py SET error: {e}")

    return False


# Keep legacy cache_get/cache_set aliases for any remaining internal calls
def cache_get(key):
    return _redis_get(key)

def cache_set(key, value, ttl_hours=24):
    return _redis_set(key, value, ttl=int(ttl_hours * 3600))


def is_cache_fresh(cached_data, max_age_hours=12):
    if not cached_data:
        return False
    ts = cached_data.get('scanned_at') or cached_data.get('timestamp')
    if not ts:
        return False
    try:
        scanned = datetime.fromisoformat(ts)
        if scanned.tzinfo is None:
            scanned = scanned.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - scanned
        return age.total_seconds() < (max_age_hours * 3600)
    except:
        return False


# ========================================
# ACTOR DEFINITIONS — LIBYA THEATRE v1.0
# ========================================

LIBYA_ACTORS = {
    'gnu_tripoli': {
        'name': 'GNU / Tripoli (Dbeibah)',
        'flag': '🇱🇾',
        'icon': '🏛️',
        'color': '#16a34a',
        'role': 'Western Government — UN-recognized',
        'keywords': [
            'dbeibah', 'dabaiba', 'dbeiba', 'abdul hamid dbeibah',
            'government of national unity', 'gnu libya', 'tripoli government',
            'presidential council libya', 'mohamed al-menfi', 'al-menfi', 'menfi',
            'misrata', 'tripoli', 'western libya', 'gna successor',
            'rada force', 'special deterrence force', '444 brigade', '444th brigade',
            'tripoli militias', 'interior ministry tripoli', 'gnu forces',
            'stability support apparatus', 'ssa libya',
            'حكومة الوحدة الوطنية', 'الدبيبة',
            'طرابلس', 'المجلس الرئاسي', 'المنفي', 'مصراتة',
            'governo di tripoli', 'governo dbeibah',
        ],
        'baseline_statements_per_week': 10,
    },
    'lna_hor': {
        'name': 'LNA / HoR / Tobruk (Haftar)',
        'flag': '🇱🇾',
        'icon': '⚔️',
        'color': '#dc2626',
        'role': 'Eastern Military / Parliament',
        'keywords': [
            'haftar', 'khalifa haftar', 'field marshal haftar',
            'lna libya', 'libyan national army', 'libyan arab armed forces', 'laaf',
            'saddam haftar', 'khaled haftar', 'belqasim haftar',
            'aguila saleh', 'agila saleh', 'house of representatives libya',
            'tobruk', 'benghazi', 'cyrenaica', 'eastern libya', 'sirte',
            'eastern government libya', 'parallel government libya',
            'haftar forces', 'lna offensive', 'lna advance', 'lna deployment',
            'حفتر', 'الجيش الوطني الليبي', 'مجلس النواب',
            'طبرق', 'بنغازي', 'صدام حفتر', 'عقيلة صالح', 'سرت',
            'esercito di haftar', 'haftar libia',
        ],
        'baseline_statements_per_week': 10,
    },
    'unsmil': {
        'name': 'UNSMIL / UN',
        'flag': '🇺🇳',
        'icon': '☮️',
        'color': '#0ea5e9',
        'role': 'UN Mediation / Off-ramp',
        'keywords': [
            'unsmil', 'un support mission libya', 'un mission libya',
            'un envoy libya', 'special representative libya', 'srsg libya',
            'hanna tetteh', 'abdoulaye bathily', 'stephanie williams',
            'security council libya', 'ceasefire committee libya',
            '5+5 joint military commission', '5+5 committee', 'joint military commission',
            'libyan political dialogue', 'elections roadmap libya', 'libya elections',
            'unified government libya', 'libya political process',
            'البعثة الأممية ليبيا', 'المبعوث الأممي ليبيا',
            'مجلس الأمن ليبيا', 'اللجنة العسكرية',
        ],
        'baseline_statements_per_week': 5,
    },
    'russia_africacorps': {
        'name': 'Russia / Africa Corps',
        'flag': '🇷🇺',
        'icon': '🐻',
        'color': '#b91c1c',
        'role': 'External Patron — LNA / Sahel Linchpin',
        'keywords': [
            'wagner libya', 'africa corps libya', 'africa corps', 'russia libya',
            'russian forces libya', 'russian mercenaries libya', 'russian deployment libya',
            'al-khadim airbase', 'al-jufra airbase', 'jufra', 'brak al-shati',
            'russia haftar', 'moscow haftar', 'kremlin libya', 'russian weapons libya',
            'russian aircraft libya', 's-300 libya', 'russian buildup libya',
            'russian base libya', 'maaten al-sarra',
            'فاغنر ليبيا', 'الفيلق الأفريقي', 'روسيا ليبيا',
            'القوات الروسية ليبيا', 'قاعدة الجفرة',
        ],
        'baseline_statements_per_week': 4,
    },
    'turkey_libya': {
        'name': 'Turkey',
        'flag': '🇹🇷',
        'icon': '🌙',
        'color': '#ea580c',
        'role': 'GNU Backer — East Med / Drones',
        'keywords': [
            'turkey libya', 'turkish drones libya', 'bayraktar libya', 'tb2 libya',
            'ankara tripoli', 'turkey gnu', 'turkey-libya maritime', 'maritime mou libya',
            'turkey libya maritime deal', 'hydrocarbon mou libya',
            'turkish forces libya', 'turkish base libya', 'al-watiya airbase', 'watiya',
            'sadat libya', 'syrian mercenaries libya', 'erdogan libya',
            'turkish military libya', 'turkey eastern mediterranean', 'turkey energy libya',
            'turkey naval libya', 'mhirisi', 'turkey defense libya',
            'تركيا ليبيا', 'الطائرات التركية ليبيا', 'أنقرة طرابلس',
            'مذكرة التفاهم البحرية', 'أردوغان ليبيا',
            'turchia libia', 'droni turchi libia', 'erdogan libia',
        ],
        'baseline_statements_per_week': 6,
    },
    'egypt_uae_libya': {
        'name': 'Egypt + UAE',
        'flag': '🇪🇬',
        'icon': '🤝',
        'color': '#a16207',
        'role': 'LNA External Backers',
        'keywords': [
            'egypt libya', 'egypt haftar', 'sisi libya', 'cairo haftar',
            'egyptian border libya', 'egyptian military libya', 'egypt border security libya',
            'uae libya', 'emirates libya', 'abu dhabi haftar', 'uae drones libya',
            'uae support haftar', 'emirati support libya', 'egypt uae haftar',
            'egypt red line sirte', 'sirte jufra red line',
            'مصر ليبيا', 'السيسي ليبيا', 'الإمارات ليبيا',
            'أبوظبي حفتر', 'القاهرة حفتر',
        ],
        'baseline_statements_per_week': 5,
    },
    'italy_eu_libya': {
        'name': 'Italy / EU',
        'flag': '🇮🇹',
        'icon': '🛟',
        'color': '#7c3aed',
        'role': 'Migration + Energy Leverage',
        'keywords': [
            'italy libya', 'eu libya', 'meloni libya', 'rome libya',
            'mattei plan libya', 'eni libya', 'mellitah', 'italian coast guard libya',
            'italy migration libya', 'lampedusa', 'central mediterranean migration',
            'libyan coast guard', 'frontex libya', 'eu migration deal libya',
            'eu border libya', 'eu funding libya coast guard', 'migrant boat libya',
            'european union libya', 'piantedosi libya',
            'إيطاليا ليبيا', 'الاتحاد الأوروبي ليبيا', 'خفر السواحل الليبي',
            'الهجرة ليبيا', 'لامبيدوزا',
            'italia libia', 'piano mattei', 'guardia costiera libica', 'eni libia',
            'migranti libia', 'meloni libia', 'lampedusa libia',
        ],
        'baseline_statements_per_week': 5,
    },
}


# ========================================
# ESCALATION LADDER
# ========================================

ESCALATION_LEVELS = {
    0: {'label': 'Monitoring',    'color': '#6b7280'},
    1: {'label': 'Rhetoric',      'color': '#3b82f6'},
    2: {'label': 'Warning',       'color': '#f59e0b'},
    3: {'label': 'Direct Threat', 'color': '#f97316'},
    4: {'label': 'Incident',      'color': '#ef4444'},
    5: {'label': 'Active Conflict','color': '#dc2626'},
}


# ========================================
# VECTOR TRIGGER KEYWORDS
# ========================================

# Vector display labels (code keys kept stable; Libya-meaningful display names)
VECTOR_LABELS = {
    'ground_ops':        'Militia & Ground Clashes',
    'rockets':           'Oil & Economic Leverage',
    'ceasefire':         'Diplomacy & Elections',
    'crossborder':       'Foreign Force & Cross-theater',
    'internal_fracture': 'East\u2013West Institutional Fracture',
}

# Vector 1: MILITIA & GROUND CLASHES (Tripoli militias, LNA offensives, force movement)
GROUND_OPS_TRIGGERS = {
    5: [
        'march on tripoli', 'assault on tripoli', 'battle for tripoli',
        'lna offensive tripoli', 'full-scale militia war', 'storming tripoli',
        'forces enter tripoli', 'all-out fighting tripoli',
    ],
    4: [
        'armed clashes', 'militia clashes', 'heavy fighting', 'forces massing',
        'lna buildup', 'military buildup tripoli', 'mobilization libya',
        'convoy advancing', 'reinforcements deployed', 'clashes erupt',
        'gun battle', 'shelling', 'artillery exchange',
    ],
    3: [
        'militia standoff', 'forces deploy', 'heavy weapons deploy',
        'brigade clash', 'reinforcements sent', 'security operation libya',
        'armed mobilization', 'troops advance',
    ],
    2: [
        'militia tension', 'security incident', 'sporadic gunfire',
        'armed group tension', 'rival militias', 'checkpoint clash',
    ],
    1: [
        'militia', 'armed group', 'clashes', 'gunfire',
        '\u0627\u0634\u062a\u0628\u0627\u0643\u0627\u062a', '\u0645\u064a\u0644\u064a\u0634\u064a\u0627',
    ],
}

# Vector 2: OIL & ECONOMIC LEVERAGE (blockades, force majeure, NOC/CBL disputes) -- most acute
ROCKETS_TRIGGERS = {
    5: [
        'all oil exports halted', 'national oil shutdown', 'oil blockade nationwide',
        'force majeure all ports', 'total oil shutdown libya',
    ],
    4: [
        'force majeure', 'oil port blockade', 'oil field shutdown', 'production halt',
        'oil ports closed', 'blockade of oil', 'shut down oil', 'halt oil exports',
        'central bank split', 'parallel central bank', 'revenue freeze',
        'el sharara shutdown', 'es sider closed', 'ras lanuf shut',
    ],
    3: [
        'threat to close oil', 'oil blockade threat', 'noc dispute', 'budget standoff',
        'oil revenue dispute', 'blockade threat', 'cut oil production',
        'central bank dispute', 'oil revenue freeze threat', 'fuel crisis',
    ],
    2: [
        'oil tension', 'production dispute', 'export disruption', 'currency pressure',
        'oil output drop', 'noc warning', 'revenue dispute',
    ],
    1: [
        'oil production', 'noc', 'central bank libya', 'oil revenue', 'oil exports',
        '\u0627\u0644\u0646\u0641\u0637 \u0644\u064a\u0628\u064a\u0627', '\u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u0646\u0641\u0637', '\u0627\u0644\u0645\u0624\u0633\u0633\u0629 \u0627\u0644\u0648\u0637\u0646\u064a\u0629 \u0644\u0644\u0646\u0641\u0637',
    ],
}

# Vector 3: DIPLOMACY & ELECTIONS (UNSMIL track, election freeze, reconciliation)
CEASEFIRE_TRIGGERS = {
    5: [
        'ceasefire agreement libya', 'unified government formed', 'elections held libya',
        'power-sharing deal signed', 'peace agreement libya', 'unity government sworn',
    ],
    4: [
        'direct talks libya', 'unsmil negotiations', '5+5 agreement', 'roadmap agreed',
        'power-sharing deal', 'election date set', 'unified government deal',
        'haftar dbeibah talks', 'east west agreement',
    ],
    3: [
        'unsmil mediation', 'un envoy visit', 'dialogue resumes', 'election roadmap',
        'reconciliation talks', 'political dialogue libya', 'geneva talks libya',
        'cairo talks libya', 'morocco talks libya', 'ceasefire committee meets',
        '\u0645\u0641\u0627\u0648\u0636\u0627\u062a \u0645\u0628\u0627\u0634\u0631\u0629 \u0644\u064a\u0628\u064a\u0627', '\u062d\u0648\u0627\u0631 \u0644\u064a\u0628\u064a',
    ],
    2: [
        'diplomatic push libya', 'peace talks libya', 'de-escalation libya',
        'un initiative libya', 'back-channel libya', 'eu calls dialogue libya',
    ],
    1: [
        'ceasefire', 'negotiations', 'dialogue', 'elections', 'reconciliation',
        '\u0648\u0642\u0641 \u0625\u0637\u0644\u0627\u0642 \u0627\u0644\u0646\u0627\u0631', '\u0645\u0641\u0627\u0648\u0636\u0627\u062a', '\u0627\u0646\u062a\u062e\u0627\u0628\u0627\u062a',
    ],
}

# Vector 4: FOREIGN FORCE & CROSS-THEATER (Africa Corps, Turkish forces, Sahel/Sudan spillover)
CROSSBORDER_TRIGGERS = {
    5: [
        'foreign military intervention libya', 'turkish russian forces clash',
        'foreign war in libya', 'proxy war libya erupts',
    ],
    4: [
        'mercenary surge', 'foreign troop buildup', 'africa corps reinforcement',
        'turkish deployment libya', 'russian buildup libya', 'sudan spillover libya',
        'mercenaries pour in', 'foreign fighters surge',
    ],
    3: [
        'foreign interference libya', 'mercenary flows', 'proxy escalation libya',
        'arms embargo violation', 'sahel linkage', 'weapons shipment libya',
        'drone strike libya', 'foreign airstrike libya',
    ],
    2: [
        'foreign involvement libya', 'external backing libya', 'regional tension libya',
        'foreign meddling libya', 'proxy tension libya',
    ],
    1: [
        'foreign forces', 'mercenaries', 'intervention libya', 'proxy',
        '\u0627\u0644\u0645\u0631\u062a\u0632\u0642\u0629 \u0644\u064a\u0628\u064a\u0627', '\u062a\u062f\u062e\u0644 \u0623\u062c\u0646\u0628\u064a \u0644\u064a\u0628\u064a\u0627',
    ],
}

# Vector 5: EAST-WEST INSTITUTIONAL FRACTURE (rival govts, parallel institutions)
INTERNAL_FRACTURE_TRIGGERS = {
    5: [
        'rival governments at war', 'country splits', 'institutional collapse libya',
        'libya partition', 'two governments fighting',
    ],
    4: [
        'parallel government declared', 'rival cabinet', 'hor vs gnu showdown',
        'government seizure attempt', 'budget war libya', 'parallel central bank',
        'rival administration libya', 'coup attempt libya',
    ],
    3: [
        'east west standoff', 'institutional dispute libya', 'legitimacy crisis libya',
        'blockade of institutions', 'contested government libya', 'dual authority libya',
        'parallel institutions', 'rival prime minister',
    ],
    2: [
        'political deadlock libya', 'divided institutions', 'contested legitimacy',
        'governance crisis libya', 'split institutions',
    ],
    1: [
        'division libya', 'fracture', 'rival libya', 'parallel libya',
        '\u0627\u0646\u0642\u0633\u0627\u0645 \u0644\u064a\u0628\u064a\u0627', '\u062d\u0643\u0648\u0645\u062a\u064a\u0646',
    ],
}

# Conditional Threats -- "if X then Y" tripwire language
CONDITIONAL_TRIGGERS = {
    3: [
        'if elections are delayed', 'if oil stays blockaded', 'if oil blockade continues',
        'if foreign forces do not withdraw', 'should haftar advance', 'if tripoli is attacked',
        'if the ceasefire fails', 'any move on tripoli will', 'if mercenaries remain',
    ],
    2: [
        'we reserve the right', 'all options on the table', 'prepared to respond',
        'will not hesitate', 'unless forces withdraw', 'if demands are not met',
        'if negotiations fail',
    ],
    1: [
        'unless', 'provided that', 'on condition', 'in response to', 'should the situation',
    ],
}


# ========================================
# SPECIFICITY SCORER
# ========================================

SPECIFIC_GEOGRAPHIES = [
    'tripoli', 'benghazi', 'sirte', 'misrata', 'sabha', 'sebha', 'tobruk', 'derna',
    'zawiya', 'zawiyah', 'bani walid', 'tarhuna', 'kufra', 'fezzan',
    'cyrenaica', 'tripolitania', 'gulf of sidra', 'oil crescent',
    'ras lanuf', 'es sider', 'sidra', 'brega', 'zueitina', 'hariga', 'tobruk port',
    'sharara', 'el sharara', 'el feel', 'waha', 'jufra', 'al-jufra',
    'mitiga', 'watiya', 'al-watiya', 'maaten al-sarra', 'al-khadim',
]

SPECIFIC_ASSETS = [
    'bayraktar', 'tb2', 'drone swarm', 'grad rocket', 's-300', 'pantsir',
    'oil terminal', 'oil field', 'oil port', 'refinery', 'pipeline',
    'mitiga airport', 'watiya airbase', 'jufra airbase', 'khadim airbase',
    'wagner fighters', 'syrian fighters', 'mercenaries', 'naval blockade',
    'frigate', 'armored convoy',
]

TIME_BOUNDED = [
    'within 24 hours', 'within 48 hours', 'within 72 hours',
    'by tomorrow', 'before the end of', 'in the coming hours',
    'imminent', 'within days', 'tonight', 'this week',
    'before friday', 'deadline',
]

OPERATIONAL_FRAMING = [
    'preparing to launch', 'positioned to strike', 'ready to advance',
    'forces deployed', 'troops massing', 'coordinated assault',
    'multi-front', 'simultaneous advance', 'convoy moving toward',
    'offensive imminent', 'advancing on', 'massing near',
]


def _score_specificity(text):
    """
    Score 0-10 how operationally specific the rhetoric is.
    Returns (score, breakdown_dict).
    """
    score = 0
    breakdown = {
        'named_geographies': [],
        'named_assets': [],
        'time_bounded': [],
        'operational_framing': [],
        'conditional_threats': [],
    }

    for geo in SPECIFIC_GEOGRAPHIES:
        if geo in text:
            breakdown['named_geographies'].append(geo)
            score += 1

    for asset in SPECIFIC_ASSETS:
        if asset in text:
            breakdown['named_assets'].append(asset)
            score += 1

    for tb in TIME_BOUNDED:
        if tb in text:
            breakdown['time_bounded'].append(tb)
            score += 2

    for op in OPERATIONAL_FRAMING:
        if op in text:
            breakdown['operational_framing'].append(op)
            score += 2

    for kw in CONDITIONAL_TRIGGERS.get(3, []):
        if kw in text:
            breakdown['conditional_threats'].append(kw)
            score += 2

    return min(score, 10), breakdown


# ========================================
# DELTA CALCULATION
# ========================================

def _compute_delta():
    """
    Read last 14 history entries, compare most recent to prior average.
    Returns delta dict.
    """
    try:
        if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
            return None
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/lrange/{RHETORIC_HISTORY_KEY}/0/13",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5
        )
        raw = resp.json().get('result', [])
        entries = []
        for item in raw:
            try:
                entries.append(json.loads(item))
            except Exception:
                pass

        if len(entries) < 3:
            return {'direction': 'insufficient_data', 'entries_available': len(entries)}

        current = entries[0]
        prior = entries[1:]
        prior_scores = [e.get('score', 0) for e in prior]
        prior_levels = [e.get('level', 0) for e in prior]
        prior_avg_score = round(sum(prior_scores) / len(prior_scores), 1)
        prior_avg_level = round(sum(prior_levels) / len(prior_levels), 2)

        score_change = (current.get('score', 0)) - prior_avg_score
        level_change = round((current.get('level', 0)) - prior_avg_level, 2)

        if score_change > 10:
            direction = 'rising'
        elif score_change < -10:
            direction = 'falling'
        else:
            direction = 'stable'

        return {
            'direction': direction,
            'score_change': round(score_change, 1),
            'level_change': level_change,
            'current_score': current.get('score', 0),
            'prior_avg_score': prior_avg_score,
            'prior_avg_level': prior_avg_level,
            'vs_period': f'{len(prior)}-scan average',
        }
    except Exception as e:
        print(f"[Libya Rhetoric] Delta compute error: {e}")
        return None


# ========================================
# ACTOR BASELINE TRACKING
# ========================================

def _update_actor_baselines(actor_results):
    """
    Exponential moving average of statement_count and max_level per actor.
    Stored in Redis as rhetoric_baseline:libya. 30-day TTL.
    """
    try:
        existing = _redis_get(BASELINE_KEY) or {}
        updated = {}
        alpha = 0.2

        for actor_id, ar in actor_results.items():
            current_statements = ar.get('statement_count', 0)
            current_level = ar.get('max_escalation_level', 0)
            prev = existing.get(actor_id, {})

            if not prev:
                updated[actor_id] = {
                    'avg_statements': current_statements,
                    'avg_level': current_level,
                    'scans': 1,
                }
            else:
                scans = prev.get('scans', 1)
                updated[actor_id] = {
                    'avg_statements': round(
                        alpha * current_statements + (1 - alpha) * prev.get('avg_statements', current_statements), 2
                    ),
                    'avg_level': round(
                        alpha * current_level + (1 - alpha) * prev.get('avg_level', current_level), 3
                    ),
                    'scans': min(scans + 1, 999),
                }

        _redis_set(BASELINE_KEY, updated, ttl=30 * 24 * 3600)
        print(f"[Libya Rhetoric] ✅ Actor baselines updated")
        return updated
    except Exception as e:
        print(f"[Libya Rhetoric] Baseline update error: {e}")
        return {}


def _detect_silence_anomalies(actor_results, baselines):
    """
    Flag actors whose current statement count is significantly below baseline.
    Needs at least 5 scans of history before flagging.
    """
    anomalies = []
    try:
        for actor_id, ar in actor_results.items():
            baseline = baselines.get(actor_id, {})
            avg_statements = baseline.get('avg_statements', 0)
            scans = baseline.get('scans', 0)

            if scans < 5 or avg_statements < 3:
                continue

            actual = ar.get('statement_count', 0)
            if actual < avg_statements * 0.30:
                pct_below = round((1 - actual / avg_statements) * 100)
                actor_info = LIBYA_ACTORS.get(actor_id, {})
                anomalies.append({
                    'actor_id': actor_id,
                    'actor_name': actor_info.get('name', actor_id),
                    'actor_flag': actor_info.get('flag', ''),
                    'expected_statements': round(avg_statements),
                    'actual_statements': actual,
                    'deviation': f'{pct_below}% below baseline',
                    'signal': 'Unusual quiet — possible operational security or patron direction',
                })
                print(f"[Libya Rhetoric] 🔇 Silence anomaly: {actor_id} ({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Libya Rhetoric] Silence detection error: {e}")
    return anomalies


# ========================================
# CROSS-THEATER COORDINATION
# ========================================

# ============================================================
# SLICE 2 -- CONVERGENCE LAYER (sensor reads + migration + Turkey emit)
# ============================================================
# Doctrine: the Libya stability-page sensors are the DIAL; this rhetoric
# tracker (analyst) READS the dial and nudges its score. Every read fails
# soft -- a missing/unparseable sensor yields modifier 0, never an error.

OIL_PULSE_KEY         = 'libya_oil_pulse:latest'
UNHCR_LIBYA_KEY       = 'unhcr:libya:latest'
HUMANITARIAN_KEY      = 'libya_humanitarian:latest'
TURKEY_FOOTPRINTS_KEY = 'turkey:theater_footprints'


def _read_oil_pulse_modifier():
    """
    Read the Libya Oil Pulse sensor; map production-status band to a bounded
    upward modifier. Oil is Libya's most acute economic lever -- a national
    shutdown is a major escalation signal.
      flowing -> 0 | disrupted -> +4 | force_majeure -> +8 | shutdown -> +12
    NOTE (confirm against live payload): probes status under several field
    names. Lock the accessor once the real libya_oil_pulse:latest is shared.
    """
    try:
        pulse = _redis_get(OIL_PULSE_KEY) or {}
        if not pulse:
            return 0, {'status': 'no_data', 'modifier': 0}
        status = (pulse.get('status') or pulse.get('band')
                  or pulse.get('pulse_status') or pulse.get('oil_status')
                  or pulse.get('overall_status') or '')
        status = str(status).lower().replace(' ', '_')
        band_map = {
            'flowing': 0, 'normal': 0, 'stable': 0,
            'disrupted': 4, 'partial': 4, 'reduced': 4,
            'force_majeure': 8,
            'shutdown': 12, 'halted': 12, 'closed': 12,
        }
        mod = band_map.get(status, 0)
        return mod, {'status': status or 'unknown', 'modifier': mod}
    except Exception as e:
        print(f"[Libya Rhetoric] Oil pulse read error: {e}")
        return 0, {'status': 'error', 'modifier': 0}


def _read_displacement_modifier():
    """
    Read UNHCR/DTM displacement sensors. A surge in refugee inflow (Libya hosts
    ~658k, mostly Sudanese) or IDP displacement is upward CONTEXT pressure --
    modest weight, since displacement is context, not the headline.
      stable -> 0 | elevated -> +2 | high/surge -> +4
    NOTE (confirm against live payload): probes surge/trend under several field
    names across unhcr:libya:latest and libya_humanitarian:latest.
    """
    try:
        unhcr = _redis_get(UNHCR_LIBYA_KEY) or {}
        hum   = _redis_get(HUMANITARIAN_KEY) or {}
        surge = ''
        for src in (unhcr, hum):
            cand = (src.get('surge_band') or src.get('trend')
                    or src.get('alert_level') or src.get('status') or '')
            if cand:
                surge = str(cand).lower()
                break
        band_map = {
            'stable': 0, 'normal': 0, 'baseline': 0,
            'elevated': 2, 'rising': 2,
            'high': 4, 'surge': 4, 'critical': 4,
        }
        mod = band_map.get(surge, 0)
        return mod, {'status': surge or 'unknown', 'modifier': mod}
    except Exception as e:
        print(f"[Libya Rhetoric] Displacement read error: {e}")
        return 0, {'status': 'error', 'modifier': 0}


# Bidirectional migration model (central-Mediterranean departure dynamic).
# OUT = exodus/departures surging (instability push) -> escalatory (+).
# RETURN = repatriation / voluntary return / reduced crossings -> de-escalatory (-).
MIGRATION_OUT_TRIGGERS = {
    8: ['mass exodus libya', 'record crossings libya', 'migrant surge central mediterranean'],
    5: ['departures surge', 'boats leaving libya surge', 'lampedusa overwhelmed',
        'smuggling networks active', 'migrant boats surge'],
    3: ['migrant departures rise', 'crossings increase', 'central mediterranean route active',
        'smuggling resumes'],
    1: ['migrant departures', 'central mediterranean crossings', 'libya departures'],
}
MIGRATION_RETURN_TRIGGERS = {
    8: ['mass voluntary return libya', 'large-scale repatriation libya'],
    5: ['voluntary return program', 'iom return libya', 'repatriation flights libya',
        'returns surge'],
    3: ['migrants return', 'crossings drop', 'departures fall', 'reduced crossings'],
    1: ['voluntary return', 'repatriation libya', 'returnees libya'],
}


def _score_migration_flows(articles):
    """
    Bidirectional migration: OUT flows (escalatory +) net against RETURN flows
    (de-escalatory -). Net capped to +/-8. Both flows tracked independently so
    the frontend can show 'Mixed Flows'.
    """
    out_level, return_level = 0, 0
    for art in articles:
        text = f"{art.get('title','')} {art.get('description','')}".lower()
        for lvl in (8, 5, 3, 1):
            if out_level < lvl and any(k in text for k in MIGRATION_OUT_TRIGGERS[lvl]):
                out_level = lvl
            if return_level < lvl and any(k in text for k in MIGRATION_RETURN_TRIGGERS[lvl]):
                return_level = lvl
    net = max(-8, min(8, out_level - return_level))
    return net, {'out_level': out_level, 'return_level': return_level, 'net': net,
                 'mixed_flows': out_level > 0 and return_level > 0}


# Turkey OBJECTIVE-tag keyword map (what Turkey is DOING in Libya). Posture tags
# (neo_ottoman / sunni_leadership / anti_israel / strategic_autonomy) are read
# from Turkey's OWN tracker in Slice 3 -- Libya emits objective tags + mode.
TURKEY_OBJECTIVE_TAGS = {
    'gnu_backing':          ['turkey gnu', 'ankara tripoli', 'turkey backs tripoli',
                             'turkish support tripoli', 'turkey libya government'],
    'drone_export':         ['bayraktar', 'tb2', 'turkish drones', 'akinci libya'],
    'naval_mou':            ['maritime mou', 'maritime deal', 'turkey libya maritime',
                             'maritime memorandum'],
    'energy_claim_eastmed': ['eez', 'exclusive economic zone', 'eastern mediterranean',
                             'gas fields', 'hydrocarbon mou', 'east med energy'],
    'mercenary_flow':       ['syrian mercenaries', 'syrian fighters libya', 'sadat'],
    'base_access':          ['al-watiya', 'watiya airbase', 'turkish base libya', 'mitiga turkish'],
}
TURKEY_MODE_BY_TAG = {
    'drone_export': 'hard_power', 'base_access': 'hard_power', 'mercenary_flow': 'hard_power',
    'naval_mou': 'economic', 'energy_claim_eastmed': 'economic',
    'gnu_backing': 'diplomatic',
}


def _write_turkey_footprint(result, articles):
    """
    PROJECTION NODE -- spoke #1. Write Turkey's Libya footprint to the shared
    `turkey:theater_footprints` key so the Turkey tracker (Slice 3) can read it
    across theaters to answer 'what is Erdogan up to?'.

    DISTINCT from `fingerprint:turkey:*` (Turkey writing ABOUT itself). This is
    a theater tracker writing what Turkey is DOING IN this theater.
    Schema: { ts, theater, level, top_phrases[], objective_tags[], mode }
    """
    try:
        actors = result.get('actors', {})
        tk = actors.get('turkey_libya', {})
        level = tk.get('max_escalation_level', 0)

        tk_text = ''
        for art in tk.get('top_articles', [])[:8]:
            tk_text += ' ' + (art.get('title', '') + ' ' + art.get('description', '')).lower()
        if not tk_text.strip():
            for art in articles:
                t = f"{art.get('title','')} {art.get('description','')}".lower()
                if any(w in t for w in ('turkey', 'turkish', 'ankara', 'erdogan')):
                    tk_text += ' ' + t

        objective_tags = [tag for tag, kws in TURKEY_OBJECTIVE_TAGS.items()
                          if any(k in tk_text for k in kws)]

        mode = 'dormant'
        for pref in ('hard_power', 'economic', 'diplomatic'):
            if any(TURKEY_MODE_BY_TAG.get(t) == pref for t in objective_tags):
                mode = pref
                break

        top_phrases = []
        for art in tk.get('top_articles', [])[:3]:
            ttl = art.get('title', '')
            if ttl:
                top_phrases.append(ttl[:80])

        existing = _redis_get(TURKEY_FOOTPRINTS_KEY) or {}
        existing['libya'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theater': 'libya',
            'level': level,
            'top_phrases': top_phrases,
            'objective_tags': objective_tags,
            'mode': mode,
        }
        _redis_set(TURKEY_FOOTPRINTS_KEY, existing, ttl=24 * 3600)
        print(f"[Libya Rhetoric] \u2705 Turkey footprint written "
              f"(level {level}, mode {mode}, tags {objective_tags})")
    except Exception as e:
        print(f"[Libya Rhetoric] Turkey footprint write error: {e}")


def _write_crosstheater_signal(result):
    """
    Write Libya's fingerprint to the shared cross-theater Redis key.
    All trackers read/write this key.
    """
    try:
        existing = _redis_get(CROSSTHEATER_KEY) or {}

        top_phrases = []
        for sig in result.get('coordination_alerts', [])[:3]:
            msg = sig.get('message', '')
            if msg:
                top_phrases.append(msg[:60])
        for ct in result.get('conditional_threats', [])[:3]:
            if ct.get('phrase'):
                top_phrases.append(ct['phrase'])

        named_targets = []
        actors = result.get('actors', {})
        for actor_id in ['lna_hor', 'gnu_tripoli', 'russia_africacorps']:
            for art in actors.get(actor_id, {}).get('top_articles', [])[:3]:
                title_lower = art.get('title', '').lower()
                for geo in SPECIFIC_GEOGRAPHIES:
                    if geo in title_lower and geo not in named_targets:
                        named_targets.append(geo)

        existing['libya'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Libya',
            'level': result.get('theatre_escalation_level', 0),
            'score': result.get('rhetoric_score', 0),
            'theatre_score': result.get('rhetoric_score', 0),
            'ground_ops_level': result.get('ground_ops_level', 0),
            'rockets_level': result.get('rockets_level', 0),
            'top_phrases': top_phrases[:5],
            'named_targets': named_targets[:8],
            'actor_levels': {
                aid: actors.get(aid, {}).get('max_escalation_level', 0)
                for aid in ['gnu_tripoli', 'lna_hor', 'russia_africacorps', 'turkey_libya']
            },
            'specificity_score': result.get('specificity_score', 0),
            # ── DIPLOMATIC TRACK FINGERPRINT ──
            # Other trackers (ME BLUF, Turkey node) read this to factor Libya's
            # diplomatic posture into their own scores.
            'diplomatic_active': result.get('diplomatic_track_active', False),
            'ceasefire_level': result.get('ceasefire_level', 0),
            'diplomatic_modifier': result.get('diplomatic_modifier', 0),
            'diplomatic_label': result.get('diplomatic_label_detailed', 'Quiet'),
        }

        _redis_set(CROSSTHEATER_KEY, existing, ttl=8 * 3600)
        print(f"[Libya Rhetoric] ✅ Cross-theater fingerprint written")
    except Exception as e:
        print(f"[Libya Rhetoric] Cross-theater write error: {e}")


def _detect_crosstheater_coordination():
    """
    Read all theater fingerprints and detect simultaneous elevation,
    target convergence, and phrase synchronization.
    Gracefully handles missing theaters.
    """
    findings = []
    try:
        fingerprints = _redis_get(CROSSTHEATER_KEY) or {}

        if len(fingerprints) < 2:
            return []

        now = datetime.now(timezone.utc)
        fresh = {}
        for name, fp in fingerprints.items():
            try:
                fp_age = (now - datetime.fromisoformat(fp['ts'])).total_seconds() / 3600
                if fp_age <= 14:
                    fresh[name] = fp
            except Exception:
                pass

        if len(fresh) < 2:
            return []

        expected = ['yemen', 'iraq', 'libya', 'iran', 'israel']
        missing = [t for t in expected if t not in fresh]
        if missing:
            print(f"[CrossTheater] Note: {missing} fingerprints not yet available")

        # Check 1: Simultaneous elevation across proxy theaters
        proxy_theaters = {k: v for k, v in fresh.items() if k in ['yemen', 'iraq', 'libya']}
        if len(proxy_theaters) >= 2:
            elevated = {k: v for k, v in proxy_theaters.items() if v.get('level', 0) >= 2}
            if len(elevated) >= 2:
                avg_level = round(sum(v['level'] for v in elevated.values()) / len(elevated), 1)
                findings.append({
                    'type': 'simultaneous_elevation',
                    'message': f"Simultaneous elevated rhetoric across {len(elevated)} Iran-aligned theaters",
                    'theaters': list(elevated.keys()),
                    'avg_level': avg_level,
                    'confidence': min(len(elevated) * 30, 90),
                    'signal': 'Multi-theater coordination possible — watch for synchronized operations',
                    'missing_theaters': missing,
                })

        # Check 2: Named target convergence
        all_targets = {}
        for name, fp in fresh.items():
            for target in fp.get('named_targets', []):
                all_targets.setdefault(target, []).append(name)
        shared_targets = {t: ts for t, ts in all_targets.items() if len(ts) >= 2}
        if shared_targets:
            findings.append({
                'type': 'target_convergence',
                'message': 'Shared target references across multiple theaters',
                'shared_targets': shared_targets,
                'confidence': min(len(shared_targets) * 25, 85),
                'signal': 'Multiple theaters referencing same targets — possible coordinated targeting',
                'missing_theaters': missing,
            })

        # Check 3: Phrase synchronization
        all_phrases = {}
        for name, fp in fresh.items():
            for phrase in fp.get('top_phrases', []):
                phrase_key = phrase[:30].lower()
                all_phrases.setdefault(phrase_key, []).append(name)
        shared_phrases = {p: t for p, t in all_phrases.items() if len(t) >= 2}
        if shared_phrases:
            findings.append({
                'type': 'phrase_synchronization',
                'message': f"Synchronized language across {len(set(t for ts in shared_phrases.values() for t in ts))} theaters",
                'shared_phrases': list(shared_phrases.keys())[:5],
                'confidence': min(len(shared_phrases) * 20, 80),
                'signal': 'Similar framing across theaters within 14h — narrative coordination signal',
                'missing_theaters': missing,
            })

    except Exception as e:
        print(f"[Libya Rhetoric] Cross-theater detection error: {e}")

    return findings


# ========================================
# DATA FETCHING
# ========================================

def _fetch_rss(feed_url, source_name, max_items=20):
    articles = []
    try:
        response = requests.get(feed_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, application/atom+xml, */*',
            'Accept-Language': 'en-US,en;q=0.9,ar;q=0.7,he;q=0.5,fa;q=0.3',
            'Cache-Control': 'no-cache',
        })
        if response.status_code != 200:
            return []
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            # When response isn't valid XML, peek at the first bytes to
            # distinguish "feed returned HTML" (block/challenge/wrong path)
            # from "feed returned malformed XML" — different remediation.
            preview = response.text[:120].replace('\n', ' ').strip()
            if '<html' in preview.lower() or '<!doctype' in preview.lower():
                print(f"[Rhetoric RSS] {source_name}: returned HTML not RSS (likely blocked/wrong path) — preview: {preview[:80]}")
            else:
                print(f"[Rhetoric RSS] {source_name}: XML parse error: {e}")
            return []
        for item in root.findall('.//item')[:max_items]:
            title_elem = item.find('title')
            link_elem  = item.find('link')
            pub_elem   = item.find('pubDate')
            desc_elem  = item.find('description')
            if title_elem is None:
                continue
            pub_date = ''
            if pub_elem is not None and pub_elem.text:
                try:
                    pub_date = parsedate_to_datetime(pub_elem.text).isoformat()
                except:
                    pub_date = datetime.now(timezone.utc).isoformat()
            desc = ''
            if desc_elem is not None and desc_elem.text:
                desc = re.sub(r'<[^>]+>', '', desc_elem.text)[:500]
            articles.append({
                'title': title_elem.text or '',
                'description': desc,
                'url': link_elem.text if link_elem is not None else '',
                'publishedAt': pub_date,
                'source': source_name,
                'content': desc,
            })
    except Exception as e:
        print(f"[Rhetoric RSS] {source_name} error: {str(e)[:100]}")
    return articles


def fetch_libya_articles(days=3):
    all_articles = []

    # RSS Feeds — expanded for France, Cyprus, Syria border
    rss_feeds = {
        # -- Libyan domestic sources (Google News routed for reliability) --
        'Libya Herald':        'https://libyaherald.com/feed/',
        'Libya Observer':      'https://news.google.com/rss/search?q=site:libyaobserver.ly&hl=en&gl=US&ceid=US:en',
        'Libya Update':        'https://news.google.com/rss/search?q=site:libyaupdate.com&hl=en&gl=US&ceid=US:en',
        'Address Libya':       'https://news.google.com/rss/search?q=site:addresslibya.com&hl=en&gl=US&ceid=US:en',
        'Al-Marsad (AR)':      'https://news.google.com/rss/search?q=site:almarsad.co+%D9%84%D9%8A%D8%A8%D9%8A%D8%A7&hl=ar&gl=LY&ceid=LY:ar',
        'Al-Wasat Libya (AR)': 'https://news.google.com/rss/search?q=site:alwasat.ly&hl=ar&gl=LY&ceid=LY:ar',
        # -- Italian-angle: migration + ENI energy + Mattei-Plan diplomacy --
        'ANSAMed \u2014 Libia (IT)':    'https://news.google.com/rss/search?q=site:ansamed.info+Libia&hl=it&gl=IT&ceid=IT:it',
        'Agenzia Nova \u2014 Libia (IT)':'https://news.google.com/rss/search?q=site:agenzianova.com+Libia&hl=it&gl=IT&ceid=IT:it',
        # -- International / institutional --
        'UN News (Africa)':    'https://news.un.org/feed/subscribe/en/news/region/africa/feed/rss.xml',
        'AllAfrica \u2014 Libya':       'https://allafrica.com/tools/headlines/rdf/libya/headlines.rdf',
        'Reuters \u2014 Libya':         'https://news.google.com/rss/search?q=Libya+Reuters&hl=en&gl=US&ceid=US:en',
        'Al Jazeera \u2014 Libya':      'https://news.google.com/rss/search?q=site:aljazeera.com+Libya&hl=en&gl=US&ceid=US:en',
    }

    for name, url in rss_feeds.items():
        articles = _fetch_rss(url, name)
        all_articles.extend(articles)
        time.sleep(0.3)

    print(f"[Rhetoric] RSS: {len(all_articles)} articles from {len(rss_feeds)} feeds")

    # GDELT — expanded with Syria border + France + Cyprus queries
    gdelt_queries = {
        'eng': [
            'libya OR tripoli OR benghazi',
            'haftar OR lna OR "libyan national army"',
            'dbeibah OR "government of national unity"',
            'libya oil OR "national oil corporation" OR "force majeure"',
            'libya militia clashes OR tripoli fighting',
            'unsmil OR "libya ceasefire" OR "libya elections"',
            'wagner OR "africa corps" libya',
            'turkey libya drones OR bayraktar libya',
            'libya migration OR lampedusa OR "central mediterranean"',
            'egypt libya OR uae libya haftar',
            'libya central bank OR "oil blockade"',
            'eni libya OR "mattei plan"',
        ],
        'ara': [
            '\u0644\u064a\u0628\u064a\u0627 OR \u0637\u0631\u0627\u0628\u0644\u0633 OR \u0628\u0646\u063a\u0627\u0632\u064a',
            '\u062d\u0641\u062a\u0631 OR \u0627\u0644\u062c\u064a\u0634 \u0627\u0644\u0648\u0637\u0646\u064a \u0627\u0644\u0644\u064a\u0628\u064a',
            '\u0627\u0644\u062f\u0628\u064a\u0628\u0629 OR \u062d\u0643\u0648\u0645\u0629 \u0627\u0644\u0648\u062d\u062f\u0629',
            '\u0627\u0644\u0646\u0641\u0637 \u0627\u0644\u0644\u064a\u0628\u064a OR \u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u0646\u0641\u0637 OR \u0627\u0644\u0642\u0648\u0629 \u0627\u0644\u0642\u0627\u0647\u0631\u0629',
            '\u0627\u0634\u062a\u0628\u0627\u0643\u0627\u062a \u0637\u0631\u0627\u0628\u0644\u0633 OR \u0645\u064a\u0644\u064a\u0634\u064a\u0627\u062a \u0644\u064a\u0628\u064a\u0627',
            '\u0627\u0644\u0628\u0639\u062b\u0629 \u0627\u0644\u0623\u0645\u0645\u064a\u0629 \u0644\u064a\u0628\u064a\u0627 OR \u0627\u0646\u062a\u062e\u0627\u0628\u0627\u062a \u0644\u064a\u0628\u064a\u0627',
            '\u0641\u0627\u063a\u0646\u0631 \u0644\u064a\u0628\u064a\u0627 OR \u0627\u0644\u0641\u064a\u0644\u0642 \u0627\u0644\u0623\u0641\u0631\u064a\u0642\u064a',
            '\u0627\u0644\u0647\u062c\u0631\u0629 \u0644\u064a\u0628\u064a\u0627 OR \u062e\u0641\u0631 \u0627\u0644\u0633\u0648\u0627\u062d\u0644 \u0627\u0644\u0644\u064a\u0628\u064a',
        ],
        'ita': [
            'Libia Tripoli OR Bengasi',
            'Haftar OR esercito nazionale libico',
            'Dbeibah OR governo unit\u00e0 nazionale Libia',
            'petrolio Libia OR blocco petrolifero',
            'migranti Libia OR Lampedusa OR Mediterraneo centrale',
            'piano Mattei OR ENI Libia',
            'guardia costiera libica OR Frontex Libia',
            'droni turchi Libia OR Turchia Libia',
        ],
    }

    gdelt_count = 0
    for lang, queries in gdelt_queries.items():
        for query in queries:
            try:
                params = {
                    'query': query, 'mode': 'artlist', 'maxrecords': 30,
                    'timespan': f'{days}d', 'format': 'json', 'sourcelang': lang,
                }
                resp = None
                for attempt in range(2):
                    try:
                        resp = requests.get(GDELT_BASE_URL, params=params, timeout=60)
                        if resp.status_code == 200:
                            break
                    except requests.Timeout:
                        if attempt == 0:
                            time.sleep(2)
                            continue
                        raise
                if resp and resp.status_code == 200:
                    try:
                        data = resp.json()
                    except (json.JSONDecodeError, ValueError):
                        continue
                    for art in data.get('articles', []):
                        all_articles.append({
                            'title': art.get('title', ''),
                            'description': art.get('title', ''),
                            'url': art.get('url', ''),
                            'publishedAt': art.get('seendate', ''),
                            'source': f'GDELT ({lang})',
                            'content': art.get('title', ''),
                        })
                        gdelt_count += 1
            except Exception as e:
                print(f"[Rhetoric GDELT] {lang} error: {str(e)[:80]}")
            time.sleep(0.5)

    print(f"[Rhetoric] GDELT: {gdelt_count} articles")

    # NewsAPI
    if NEWSAPI_KEY:
        newsapi_queries = [
            'Libya Haftar OR Dbeibah OR Tripoli',
            'Libya oil OR "National Oil Corporation" OR "force majeure"',
            'Libya militia clashes OR Tripoli fighting',
            'Libya UNSMIL OR ceasefire OR elections',
            'Libya migration OR Lampedusa OR mercenaries',
        ]
        from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        newsapi_count = 0
        for query in newsapi_queries:
            try:
                resp = requests.get('https://newsapi.org/v2/everything', params={
                    'q': query, 'from': from_date, 'sortBy': 'publishedAt',
                    'language': 'en', 'apiKey': NEWSAPI_KEY, 'pageSize': 30,
                }, timeout=10)
                if resp.status_code == 200:
                    for art in resp.json().get('articles', []):
                        all_articles.append({
                            'title': art.get('title', ''),
                            'description': art.get('description', ''),
                            'url': art.get('url', ''),
                            'publishedAt': art.get('publishedAt', ''),
                            'source': art.get('source', {}).get('name', 'NewsAPI'),
                            'content': art.get('content', ''),
                        })
                        newsapi_count += 1
            except:
                pass
            time.sleep(0.3)
        print(f"[Rhetoric] NewsAPI: {newsapi_count} articles")

    # Telegram
    if TELEGRAM_AVAILABLE:
        try:
            telegram_msgs = fetch_telegram_signals(hours_back=72, include_extended=True)
            if telegram_msgs:
                for msg in telegram_msgs:
                    all_articles.append({
                        'title': msg.get('title', '')[:300],
                        'description': msg.get('body', msg.get('title', ''))[:500],
                        'url': msg.get('url', ''),
                        'publishedAt': msg.get('published', ''),
                        'source': msg.get('source', 'Telegram'),
                        'content': msg.get('body', msg.get('title', ''))[:500],
                        'views': msg.get('views', 0),
                        'forwards': msg.get('forwards', 0),
                    })
                print(f"[Rhetoric] Telegram: {len(telegram_msgs)} messages")
        except Exception as e:
            print(f"[Rhetoric] Telegram error: {str(e)[:100]}")

    # Deduplicate by URL
    seen = set()
    unique = []
    for a in all_articles:
        if a.get('url') and a['url'] not in seen:
            seen.add(a['url'])
            unique.append(a)

    # Nitter -- primary source accounts
    try:
        nitter_posts = fetch_nitter_libya(days=days)
        for p in nitter_posts:
            u = p.get('url', '')
            if u and u not in seen:
                seen.add(u)
                unique.append(p)
    except Exception as e:
        print(f"[Libya Rhetoric] Nitter error: {e}")

    tg_c  = sum(1 for a in unique if 'Telegram' in str(a.get('source', '')))
    nit_c = sum(1 for a in unique if 'Nitter' in str(a.get('source', '')))
    rss_c = len(unique) - tg_c - nit_c
    print(f"[Rhetoric] Total unique articles: {len(unique)} ({rss_c} RSS + {tg_c} TG + {nit_c} Nitter)")
    return unique


# ========================================
# CLASSIFICATION ENGINE
# ========================================

def classify_actor(article):
    """Determine which Libya-theatre actor(s) an article relates to — multi-match."""
    title   = (article.get('title') or '').lower()
    desc    = (article.get('description') or '').lower()
    content = (article.get('content') or '').lower()
    text    = f"{title} {desc} {content}"

    matched = []
    for actor_id, actor_data in LIBYA_ACTORS.items():
        for kw in actor_data['keywords']:
            if kw in text:
                matched.append(actor_id)
                break
    return matched


def score_vectors(text):
    """
    Score article against all 4 vectors.
    Returns dict of {vector: (level, trigger_phrase)}.
    """
    results = {}
    for vector, triggers in [
        ('ground_ops',   GROUND_OPS_TRIGGERS),
        ('rockets',      ROCKETS_TRIGGERS),
        ('ceasefire',    CEASEFIRE_TRIGGERS),
        ('crossborder',  CROSSBORDER_TRIGGERS),
        ('internal_fracture', INTERNAL_FRACTURE_TRIGGERS),
    ]:
        for level in range(5, 0, -1):
            found = False
            for kw in triggers.get(level, []):
                if kw in text:
                    results[vector] = (level, kw)
                    found = True
                    break
            if found:
                break
        if vector not in results:
            results[vector] = (0, None)
    return results


# Actors that primarily REPORT ON or COMMENT ON events.
# Their escalation score is downgraded if reporting language is detected.
# Cap is NOT applied if they use their own genuinely threatening language
# (e.g. UNSMIL pressing for elections, or Italy/EU issuing a migration ultimatum).
REPORTING_ACTORS = {
    'unsmil', 'italy_eu_libya'
}

# Phrases that indicate an actor is reporting, condemning, or mourning —
# not threatening. Presence + reporting actor = cap at level 2 (Warning).
REPORTING_LANGUAGE = [
    # Condemning / denouncing
    'condemns', 'condemned', 'denounces', 'denounced',
    'rejects the attack', 'rejects the strike',
    'protests the', 'protested the',
    # Mourning / victim language
    'mourns', 'mourning', 'mourned', 'condolences',
    'victims of', 'casualties in', 'killed in the attack',
    'civilian casualties', 'civilian deaths',
    # Calling on others to act
    'calls on', 'calls for', 'urges', 'urged',
    'demands ceasefire', 'demands halt', 'demands end to',
    'international community must', 'must stop the',
    'calls for investigation', 'calls for restraint',
    'calls for de-escalation',
    # Reporting framing
    'in response to the attack', 'following the attack',
    'after the strike', 'following the strike',
    'in the wake of', 'following the bombardment',
    'reports that israeli', 'confirmed that israeli',
    'acknowledges the attack',
    # Expressing concern
    'expressed concern', 'deeply concerned about the',
    'expresses condemnation', 'condemns israeli',
    'condemns the strike',
    # Arabic equivalents
    'يستنكر', 'استنكر', 'يدين', 'أدان',
    'يطالب بوقف', 'يطالب بإنهاء',
    'يعزي', 'ضحايا الهجوم', 'في أعقاب',
    # Hebrew equivalents
    'מגנה', 'גינה', 'קורא ל', 'דורש הפסקה',
    'קורבנות', 'בעקבות התקיפה',
]


def score_escalation(article, actor_id=None):
    """
    Single-score escalation for per-actor escalation_level field.
    Reporting actors (UNSMIL, Italy/EU) get capped
    at level 2 if reporting/condemning language is detected --
    prevents UNSMIL from scoring Active Conflict just from reporting
    on a militia clash. Cap does NOT apply if they use their own
    genuinely escalatory language without reporting context.
    """
    title   = (article.get('title') or '').lower()
    desc    = (article.get('description') or '').lower()
    content = (article.get('content') or '').lower()
    text    = f"{title} {desc} {content}"

    # Score normally first
    raw_level = 1
    trigger = None
    for level in range(5, 0, -1):
        for kw_dict in [ROCKETS_TRIGGERS, GROUND_OPS_TRIGGERS, CROSSBORDER_TRIGGERS]:
            for kw in kw_dict.get(level, []):
                if kw in text:
                    raw_level = level
                    trigger = kw
                    break
            if trigger:
                break
        if trigger:
            break

    # Reporting language downgrade — only for reporting actors at level 3+
    if actor_id in REPORTING_ACTORS and raw_level >= 3:
        is_reporting = any(phrase in text for phrase in REPORTING_LANGUAGE)
        if is_reporting:
            print(f"[Rhetoric] 📰 Reporting downgrade: {actor_id} "
                  f"capped at L2 (was L{raw_level}, trigger: '{trigger}')")
            return 2, trigger

    return raw_level, trigger


def detect_spokesperson(article, actor_id):
    title = (article.get('title') or '').lower()
    desc  = (article.get('description') or '').lower()
    text  = f"{title} {desc}"
    actor_data = LIBYA_ACTORS.get(actor_id, {})
    for person in actor_data.get('spokespersons', []):
        if person.lower() in text:
            return person
    return None


def extract_topics(article):
    title = (article.get('title') or '').lower()
    desc  = (article.get('description') or '').lower()
    text  = f"{title} {desc}"

    topic_keywords = {
        'ceasefire':      ['ceasefire', 'cease-fire', 'truce', 'وقف إطلاق النار'],
        'oil':            ['oil', 'noc', 'force majeure', 'blockade', 'النفط'],
        'militia_clash':  ['militia', 'clashes', 'fighting', 'اشتباكات'],
        'elections':      ['election', 'vote', 'roadmap', 'انتخابات'],
        'foreign_force':  ['wagner', 'africa corps', 'turkish', 'mercenaries', 'مرتزقة'],
        'migration':      ['migrant', 'migration', 'lampedusa', 'coast guard', 'هجرة'],
        'east_west':      ['parallel', 'rival government', 'central bank', 'انقسام'],
        'diplomacy':      ['unsmil', 'talks', 'dialogue', 'mediation', 'مفاوضات'],
        'displacement':   ['displaced', 'refugees', 'idp', 'نازحين'],
        'humanitarian':   ['humanitarian', 'aid', 'relief', 'إنساني'],
    }

    topics = []
    for topic, keywords in topic_keywords.items():
        if any(kw in text for kw in keywords):
            topics.append(topic)
    return topics


# ========================================
# COORDINATION DETECTION
# ========================================

def _detect_coordination(coordination_timeline):
    """Detect temporal clustering of threatening statements across resistance axis actors."""
    alerts = []
    axis_actors = {'lna_hor', 'russia_africacorps', 'egypt_uae_libya'}

    axis_statements = [
        e for e in coordination_timeline
        if e['actor'] in axis_actors and e['level'] >= 3
    ]

    if len(axis_statements) < 2:
        return alerts

    for i, stmt_a in enumerate(axis_statements):
        for stmt_b in axis_statements[i+1:]:
            if stmt_a['actor'] == stmt_b['actor']:
                continue
            try:
                time_a = datetime.fromisoformat(str(stmt_a['timestamp']).replace('Z', '+00:00'))
                time_b = datetime.fromisoformat(str(stmt_b['timestamp']).replace('Z', '+00:00'))
                gap = abs((time_b - time_a).total_seconds()) / 3600
                if gap <= 48:
                    alert = {
                        'type': 'coordination',
                        'severity': 'high',
                        'actors': [stmt_a['actor'], stmt_b['actor']],
                        'time_gap_hours': round(gap, 1),
                        'message': (
                            f"Coordinated escalation: "
                            f"{LIBYA_ACTORS[stmt_a['actor']]['name']} and "
                            f"{LIBYA_ACTORS[stmt_b['actor']]['name']} "
                            f"issued threatening statements within {gap:.0f}h"
                        ),
                    }
                    actor_set = frozenset(alert['actors'])
                    if not any(frozenset(a['actors']) == actor_set for a in alerts):
                        alerts.append(alert)
            except:
                continue

    return alerts


# ========================================
# SCORING
# ========================================

def _calculate_rhetoric_score(actor_results, coordination_alerts,
                               ground_ops_level, rockets_level,
                               ceasefire_level, crossborder_level):
    """
    0-100 rhetoric tension score.
    Weighted combination of vector scores + actor escalation + coordination,
    minus diplomatic track modifier (active negotiations REDUCE pressure).
    """
    score = 0

    # Vector contributions (max 75) — threat-only vectors
    score += ground_ops_level * 5    # max 25
    score += rockets_level * 7       # max 35 — rockets are the most acute signal
    score += crossborder_level * 3   # max 15

    # Cap threat vector contribution at 75
    score = min(score, 75)

    # Actors at level 3+: 5 pts each (max 20)
    hot_actors = sum(
        1 for ar in actor_results.values()
        if ar.get('max_escalation_level', 0) >= 3
    )
    score += min(hot_actors * 5, 20)

    # Coordination: 10 pts per alert (max 15)
    score += min(len(coordination_alerts) * 10, 15)

    # Silence bonus (ominous): 5 pts each (max 5)
    silence_count = sum(
        1 for ar in actor_results.values()
        if ar.get('silence_alert', False)
    )
    score += min(silence_count * 5, 5)

    # ── DIPLOMATIC TRACK MODIFIER ──
    # Active negotiations reduce the threat score. Agreements reduce it more.
    # Floor at 0 — we never go negative even during full ceasefire signing.
    diplomatic_modifier_map = {
        0: 0,    # Quiet
        1: -1,   # Background diplomatic mentions
        2: -3,   # Diplomatic push
        3: -6,   # Mediator activity / envoy visits
        4: -10,  # Active negotiations / direct talks
        5: -15,  # Agreement reached / signed
    }
    diplomatic_modifier = diplomatic_modifier_map.get(ceasefire_level, 0)
    score += diplomatic_modifier

    return max(0, min(score, 100))


def _build_alerts(actor_results, coordination_alerts):
    alerts = []

    for actor_id, ar in actor_results.items():
        level = ar.get('max_escalation_level', 0)
        if level >= 4:
            alerts.append({
                'type': 'escalation', 'severity': 'critical',
                'actor': ar['name'],
                'message': f"🔴 {ar['name']}: Operational language — \"{ar.get('max_escalation_phrase','')}\"",
            })
        elif level >= 3:
            alerts.append({
                'type': 'escalation', 'severity': 'high',
                'actor': ar['name'],
                'message': f"🟠 {ar['name']}: Threatening rhetoric — \"{ar.get('max_escalation_phrase','')}\"",
            })

    for actor_id, ar in actor_results.items():
        if ar.get('silence_alert'):
            alerts.append({
                'type': 'silence', 'severity': 'warning',
                'actor': ar['name'],
                'message': f"⚠️ {ar['name']}: Unusual silence ({ar.get('statement_count',0)} statements, below baseline)",
            })

    for coord in coordination_alerts:
        alerts.append({
            'type': 'coordination', 'severity': coord['severity'],
            'message': f"🔗 {coord['message']}",
        })

    severity_order = {'critical': 0, 'high': 1, 'warning': 2}
    alerts.sort(key=lambda a: severity_order.get(a['severity'], 3))
    return alerts


def _build_empty_result():
    return {
        'success': True,
        'theatre': 'Libya',
        'scanned_at': datetime.now(timezone.utc).isoformat(),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_articles': 0,
        'articles_classified': 0,
        'theatre_escalation_level': 0,
        'theatre_escalation_label': 'Monitoring',
        'theatre_escalation_color': '#6b7280',
        'theatre_level': 0,
        'theatre_score': 0,
        'rhetoric_score': 0,
        'ground_ops_level': 0, 'ground_ops_label': 'Monitoring',
        'rockets_level': 0, 'rockets_label': 'Monitoring',
        'ceasefire_level': 0, 'ceasefire_label': 'Monitoring',
        'crossborder_level': 0, 'crossborder_label': 'Monitoring',
        'specificity_score': 0,
        'delta': None,
        'silence_anomalies': [],
        'conditional_threats': [],
        'crosstheater_coordination': [],
        'actors': {
            actor_id: {
                'name': data['name'], 'flag': data['flag'],
                'icon': data['icon'], 'color': data.get('color','#6b7280'),
                'role': data.get('role',''),
                'statement_count': 0, 'max_escalation_level': 0,
                'escalation_level': 0, 'escalation_label': 'Monitoring',
                'escalation_color': '#6b7280', 'escalation_phrase': None,
                'silence_alert': False, 'top_articles': [], 'topics': {},
            }
            for actor_id, data in LIBYA_ACTORS.items()
        },
        'coordination_alerts': [],
        'alerts': [],
        'awaiting_scan': True,
        'message': 'No data yet — scan in progress',
        'version': '2.0.0',
    }


# ========================================
# NITTER -- Primary source accounts (institutional + OSINT; Nitter is flaky, fails soft)
# Libya: UNSMIL, EU/Italy missions, English OSINT outlets, eastern + western voices.
# Real social-signal heavy lifting is the Telegram layer; Nitter is supplementary.
NITTER_ACCOUNTS_LIBYA = [
    ("UNSMILibya",     1.1, "UNSMIL -- UN mission, ceasefire / elections / 5+5 signals"),
    ("LibyaReview",    1.0, "Libya Review -- English OSINT aggregator"),
    ("Libya_Observer", 1.0, "Libya Observer -- Tripoli-aligned outlet"),
    ("AddressLibya",   0.9, "Address Libya -- eastern-aligned outlet"),
    ("LibyanExpress",  0.9, "Libyan Express -- English news"),
    ("ReadLibya",      0.9, "Read Libya -- analysis"),
    ("EUinLibya",      0.9, "EU Delegation Libya -- migration / energy signals"),
    ("ItalyinLibya",   0.9, "Italy in Libya -- Mattei Plan / migration"),
    ("StateDept",      0.8, "State Dept -- Libya diplomatic signals"),
    ("Almarsad_En",    0.8, "Al-Marsad English -- eastern outlet"),
]


def _fetch_nitter_libya(username, weight=1.0, timeout=8):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AsifahAnalytics/1.0)"}
    for mirror in NITTER_MIRRORS:
        url = f"https://{mirror}/{username}/rss"
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            posts = []
            for item in root.findall(".//item")[:20]:
                title_el   = item.find("title")
                link_el    = item.find("link")
                pubdate_el = item.find("pubDate")
                if title_el is None:
                    continue
                title = title_el.text or ""
                link  = link_el.text if link_el is not None else ""
                pub   = ""
                if pubdate_el is not None and pubdate_el.text:
                    try:
                        pub = parsedate_to_datetime(pubdate_el.text).isoformat()
                    except Exception:
                        pub = pubdate_el.text
                posts.append({
                    "title":     title,
                    "url":       link,
                    "published": pub,
                    "source":    f"Nitter @{username}",
                    "weight":    weight,
                })
            if posts:
                print(f"[Libya Rhetoric/Nitter] @{username}: {len(posts)} posts via {mirror}")
                return posts
        except Exception as e:
            print(f"[Libya Rhetoric/Nitter] @{username} {mirror} failed: {str(e)[:60]}")
            continue
    print(f"[Libya Rhetoric/Nitter] @{username}: all mirrors failed")
    return []


def fetch_nitter_libya(days=3):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen = set()
    for username, weight, desc in NITTER_ACCOUNTS_LIBYA:
        posts = _fetch_nitter_libya(username, weight=weight)
        for p in posts:
            if p["url"] in seen:
                continue
            try:
                pub = datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
            except Exception:
                pass
            seen.add(p["url"])
            all_posts.append(p)
        time.sleep(0.3)
    print(f"[Libya Rhetoric/Nitter] Total: {len(all_posts)} posts")
    return all_posts


# ========================================
# CORE SCAN FUNCTION
# ========================================

def run_rhetoric_scan(days=3):
    """
    Execute full Libya rhetoric scan.
    Returns structured v2.0 analysis data with vectors, delta, specificity,
    baselines, silence anomalies, conditional threats, cross-theater coordination.
    """
    print(f"\n[Rhetoric Scan] Starting Libya theatre scan ({days}-day window)...")
    scan_start = time.time()

    articles = fetch_libya_articles(days)

    if not articles:
        print("[Rhetoric Scan] No articles fetched, returning empty result")
        return _build_empty_result()

    # Per-actor analysis state
    actor_results = {}
    for actor_id, actor_data in LIBYA_ACTORS.items():
        actor_results[actor_id] = {
            'name': actor_data['name'],
            'flag': actor_data['flag'],
            'icon': actor_data['icon'],
            'color': actor_data.get('color', '#6b7280'),
            'role': actor_data.get('role', ''),
            'statement_count': 0,
            'max_escalation_level': 0,
            'max_escalation_phrase': None,
            'escalation_label': 'Monitoring',
            'escalation_color': ESCALATION_LEVELS[0]['color'],
            'silence_alert': False,
            'topics': defaultdict(int),
            'top_articles': [],
            'escalation_history': [],
        }

    # Theatre vector accumulators
    theatre_vectors = {
        'ground_ops_max': 0,
        'rockets_max': 0,
        'ceasefire_max': 0,
        'crossborder_max': 0,
        'internal_fracture_max': 0,
        'coordination_signals': [],
        'conditional_threats': [],
        'specificity_scores': [],
    }

    total_classified = 0
    coordination_timeline = []

    for article in articles:
        actors = classify_actor(article)
        if not actors:
            continue
        total_classified += 1

        title   = (article.get('title') or '').lower()
        desc    = (article.get('description') or '').lower()
        content = (article.get('content') or '').lower()
        text    = f"{title} {desc} {content}"

        # Score vectors
        vectors = score_vectors(text)

        # Update theatre vector maxes
        if vectors['ground_ops'][0] > theatre_vectors['ground_ops_max']:
            theatre_vectors['ground_ops_max'] = vectors['ground_ops'][0]
        if vectors['rockets'][0] > theatre_vectors['rockets_max']:
            theatre_vectors['rockets_max'] = vectors['rockets'][0]
        if vectors['ceasefire'][0] > theatre_vectors['ceasefire_max']:
            theatre_vectors['ceasefire_max'] = vectors['ceasefire'][0]
        if vectors['crossborder'][0] > theatre_vectors['crossborder_max']:
            theatre_vectors['crossborder_max'] = vectors['crossborder'][0]
        if vectors['internal_fracture'][0] > theatre_vectors['internal_fracture_max']:
            theatre_vectors['internal_fracture_max'] = vectors['internal_fracture'][0]

        # Specificity score (once per article, on first matched actor)
        if actors[0] == actors[0]:  # Always runs — explicit for clarity
            spec_score, spec_breakdown = _score_specificity(text)
            article['_specificity_score'] = spec_score
            if spec_score > 0:
                theatre_vectors['specificity_scores'].append(spec_score)

        # Conditional threat detection
        for level in range(3, 0, -1):
            for kw in CONDITIONAL_TRIGGERS.get(level, []):
                if kw in text:
                    theatre_vectors['conditional_threats'].append({
                        'phrase': kw,
                        'level': level,
                        'article': article.get('title', '')[:100],
                        'published': article.get('publishedAt', ''),
                        'specificity': article.get('_specificity_score', 0),
                    })
                    break

        # Per-actor scoring — each actor scored individually so
        # reporting actors get their own downgraded score
        topics = extract_topics(article)
        pub_date = article.get('publishedAt', '')

        for actor_id in actors:
            ar = actor_results[actor_id]
            ar['statement_count'] += 1

            # Score with actor context (v2.1 reporting downgrade)
            escalation_level, trigger_phrase = score_escalation(article, actor_id)

            if escalation_level > ar['max_escalation_level']:
                ar['max_escalation_level'] = escalation_level
                ar['max_escalation_phrase'] = trigger_phrase
                ar['escalation_label'] = ESCALATION_LEVELS[escalation_level]['label']
                ar['escalation_color'] = ESCALATION_LEVELS[escalation_level]['color']

            ar['escalation_history'].append({
                'timestamp': pub_date,
                'level': escalation_level,
                'phrase': trigger_phrase,
            })

            for topic in topics:
                ar['topics'][topic] += 1

            spec_score = article.get('_specificity_score', 0)
            if len(ar['top_articles']) < 5 or escalation_level >= 3:
                ar['top_articles'].append({
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', 'Unknown'),
                    'published': pub_date,
                    'escalation_level': escalation_level,
                    'escalation_label': ESCALATION_LEVELS[escalation_level]['label'],
                    'trigger_phrase': trigger_phrase,
                    'specificity_score': spec_score,
                    # v2.0 vector scores
                    'ground_ops_level': vectors['ground_ops'][0],
                    'rockets_level': vectors['rockets'][0],
                    'ceasefire_level': vectors['ceasefire'][0],
                })

            coordination_timeline.append({
                'timestamp': pub_date,
                'actor': actor_id,
                'level': escalation_level,
            })

        # Coordination signal: LNA + Russia/Africa Corps in same article (eastern bloc)
        if 'lna_hor' in actors and 'russia_africacorps' in actors:
            theatre_vectors['coordination_signals'].append({
                'message': 'LNA\u2013Africa Corps coordination signal detected',
                'article': article.get('title', '')[:100],
                'published': pub_date,
            })

    # Post-processing
    print(f"[Rhetoric] Classification: {total_classified}/{len(articles)} articles matched")
    for actor_id, ar in actor_results.items():
        # Silence detection (static baseline, Redis-backed in future scans)
        baseline = LIBYA_ACTORS[actor_id].get('baseline_statements_per_week', 3)
        expected = baseline * (days / 7.0)
        if ar['statement_count'] < (expected * 0.25) and expected > 0:
            ar['silence_alert'] = True
            print(f"[Rhetoric] ⚠️ SILENCE: {ar['name']} — {ar['statement_count']} vs {expected:.1f} expected")

        # Sort top articles
        ar['top_articles'] = sorted(
            ar['top_articles'], key=lambda x: x['escalation_level'], reverse=True
        )[:5]

        ar['topics'] = dict(ar['topics'])

        print(f"[Rhetoric]   {ar['name']}: {ar['statement_count']} articles, "
              f"max level: {ar['max_escalation_level']} ({ar['escalation_label']})")

    # Coordination detection
    coordination_alerts = _detect_coordination(coordination_timeline)

    # Vector levels
    ground_ops_level  = theatre_vectors['ground_ops_max']
    rockets_level     = theatre_vectors['rockets_max']
    ceasefire_level   = theatre_vectors['ceasefire_max']
    crossborder_level = theatre_vectors['crossborder_max']
    internal_fracture_level = theatre_vectors['internal_fracture_max']

    # Overall theatre level = max of non-ceasefire vectors
    max_actor_level = max(
        (ar['max_escalation_level'] for ar in actor_results.values()), default=0
    )
    theatre_level = max(ground_ops_level, rockets_level, crossborder_level, max_actor_level)
    theatre_level = min(theatre_level, 5)
    theatre_info  = ESCALATION_LEVELS[theatre_level]

    # Rhetoric score
    rhetoric_score = _calculate_rhetoric_score(
        actor_results, coordination_alerts,
        ground_ops_level, rockets_level, ceasefire_level, crossborder_level
    )

    # -- Slice 2: convergence-layer modifiers (sensor reads + migration) --
    # Sensors are the dial; the analyst reads the dial and nudges the score.
    oil_mod, oil_detail   = _read_oil_pulse_modifier()
    disp_mod, disp_detail = _read_displacement_modifier()
    mig_net, mig_detail   = _score_migration_flows(articles)
    convergence_modifier  = oil_mod + disp_mod + mig_net
    rhetoric_score = max(0, min(100, rhetoric_score + convergence_modifier))

    # Theatre specificity
    spec_scores = theatre_vectors['specificity_scores']
    theatre_specificity = round(sum(spec_scores) / len(spec_scores), 1) if spec_scores else 0

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success': True,
        'theatre': 'Libya',
        'scanned_at': datetime.now(timezone.utc).isoformat(),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'scan_time_seconds': scan_time,
        'days_analyzed': days,
        'total_articles': len(articles),
        'articles_classified': total_classified,

# Theatre-level summary — dual field names for backward compat
        'theatre_escalation_level': theatre_level,
        'theatre_escalation_label': theatre_info['label'],
        'theatre_escalation_color': theatre_info['color'],
        'theatre_level': theatre_level,          # for index page
        'theatre_score': rhetoric_score,         # for index page (mirrors Yemen)
        'theatre_color': theatre_info['color'],  # for index page
        'rhetoric_score': rhetoric_score,
        # Vectors
        'ground_ops_level':  ground_ops_level,
        'ground_ops_label':  ESCALATION_LEVELS[ground_ops_level]['label'],
        'rockets_level':     rockets_level,
        'rockets_label':     ESCALATION_LEVELS[rockets_level]['label'],
        'ceasefire_level':   ceasefire_level,
        'ceasefire_label':   ESCALATION_LEVELS[ceasefire_level]['label'],
        'crossborder_level': crossborder_level,
        'crossborder_label': ESCALATION_LEVELS[crossborder_level]['label'],
        # ── INTERNAL FRACTURE / CIVIL WAR PRESSURE (Slice 1) ──
        'internal_fracture_level': internal_fracture_level,
        'internal_fracture_label': ESCALATION_LEVELS[internal_fracture_level]['label'],
        # -- CONVERGENCE LAYER (Slice 2): sensor + migration modifiers --
        'oil_pulse_modifier':     oil_mod,
        'oil_pulse_status':       oil_detail.get('status', 'unknown'),
        'displacement_modifier':  disp_mod,
        'displacement_status':    disp_detail.get('status', 'unknown'),
        'migration_out_level':    mig_detail.get('out_level', 0),
        'migration_return_level': mig_detail.get('return_level', 0),
        'migration_net_modifier': mig_net,
        'migration_mixed_flows':  mig_detail.get('mixed_flows', False),
        'convergence_modifier':   convergence_modifier,
        # ── DIPLOMATIC TRACK FIELDS ──
        # Active negotiations REDUCE the threat score (see _calculate_rhetoric_score).
        # These fields expose the diplomatic posture to the frontend sidebar
        # and to other trackers via the cross-theater fingerprint.
        'diplomatic_track_active':   ceasefire_level >= 2,
        'diplomatic_modifier':       {0:0, 1:-1, 2:-3, 3:-6, 4:-10, 5:-15}.get(ceasefire_level, 0),
        'diplomatic_label_detailed': {
            0: 'Quiet',
            1: 'Background Mentions',
            2: 'Diplomatic Push',
            3: 'Mediator Activity',
            4: 'Active Negotiations',
            5: 'Agreement Reached',
        }.get(ceasefire_level, 'Quiet'),

        # v2.0 enriched fields
        'specificity_score': theatre_specificity,
        'conditional_threats': theatre_vectors['conditional_threats'][:8],
        'coordination_signals': theatre_vectors['coordination_signals'][:5],

        # Per-actor breakdown
        'actors': {
            actor_id: {
                'name': ar['name'],
                'flag': ar['flag'],
                'icon': ar['icon'],
                'color': ar['color'],
                'role': ar['role'],
                'statement_count': ar['statement_count'],
                'escalation_level': ar['max_escalation_level'],
                'max_escalation_level': ar['max_escalation_level'],
                'escalation_label': ar['escalation_label'],
                'escalation_color': ar['escalation_color'],
                'escalation_phrase': ar['max_escalation_phrase'],
                'silence_alert': ar['silence_alert'],
                'topics': ar['topics'],
                'top_articles': ar['top_articles'],
            }
            for actor_id, ar in actor_results.items()
        },

        'coordination_alerts': coordination_alerts,
        'alerts': _build_alerts(actor_results, coordination_alerts),
        'version': '2.0.0',
    }

    # ── Save to Redis cache ──
    _redis_set(RHETORIC_CACHE_KEY, result, ttl=24 * 3600)

    # ── History snapshot (lpush pattern matching Yemen/Iraq/Syria) ──
    try:
        import urllib.parse as _urlparse
        snapshot = json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'score': rhetoric_score,
            'level': theatre_level,
            'label': theatre_info['label'],
            'ground_ops': ground_ops_level,
            'rockets': rockets_level,
            'ceasefire': ceasefire_level,
            'specificity': theatre_specificity,
        }, default=str)

        if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
            enc = _urlparse.quote(snapshot, safe='')
            requests.post(
                f"{UPSTASH_REDIS_URL}/lpush/{RHETORIC_HISTORY_KEY}/{enc}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            requests.post(
                f"{UPSTASH_REDIS_URL}/ltrim/{RHETORIC_HISTORY_KEY}/0/119",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            # Also write to legacy intraday key for backward compat
            requests.post(
                f"{UPSTASH_REDIS_URL}/lpush/{RHETORIC_LEGACY_HISTORY_KEY}/{enc}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            requests.post(
                f"{UPSTASH_REDIS_URL}/ltrim/{RHETORIC_LEGACY_HISTORY_KEY}/0/119",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            print(f"[Libya Rhetoric] 📈 History snapshot saved")
    except Exception as e:
        print(f"[Libya Rhetoric] History append error (non-fatal): {e}")

    # ── Daily snapshot (legacy trend system — kept for backward compat) ──
    _save_daily_snapshot(result)

    # ── Actor baselines + silence anomalies ──
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # ── Delta ──
    result['delta'] = _compute_delta()

    # ── Cross-theater coordination ──
    _write_crosstheater_signal(result)
    _write_turkey_footprint(result, articles)   # Slice 2: Projection-Node spoke #1
    result['crosstheater_coordination'] = _detect_crosstheater_coordination()

    # -- Turkey read (Slice 1 stub): Libya is the first new spoke of the
    # Turkey Projection Node. In Slice 2 this tracker will EMIT
    # turkey:theater_footprints['libya']; for now we surface Turkey's general
    # east-alignment posture from its fingerprint (informational, fails soft).
    try:
        _tk = (_redis_get(CROSSTHEATER_KEY) or {}).get('turkey', {})
        result['turkey_east_alignment']   = _tk.get('turkey_east_alignment', 'normal')
        result['turkey_mediation_active'] = _tk.get('mediation_active', False)
    except Exception:
        result['turkey_east_alignment']   = 'normal'
        result['turkey_mediation_active'] = False

    # Signal interpretation -- So What, Red Lines, Historical Patterns
    if INTERPRETER_AVAILABLE:
        try:
            result['interpretation'] = libya_interpret_signals(result)
            best = result['interpretation']['historical_matches']
            best_pct = best[0]['similarity'] if best else 'none'
            laf_gap = result['interpretation']['so_what'].get('laf_enforcement_gap', False)
            iran_dir = result['interpretation']['so_what'].get('iran_directing', False)
            print(f"[Libya Rhetoric] Interpreter: {result['interpretation']['red_lines']['breached_count']} red lines breached, best match: {best_pct}%"
                  f"{' | LAF GAP' if laf_gap else ''}{' | IRAN DIRECTING' if iran_dir else ''}")
        except Exception as e:
            print(f"[Libya Rhetoric] Warning: Interpreter error (non-fatal): {e}")

    # Canonical top_signals[] for regional BLUF + GPI consumption
    if libya_build_top_signals:
        try:
            result['top_signals'] = libya_build_top_signals(result)
            print(f"[Libya Rhetoric] Built {len(result['top_signals'])} top_signals for BLUF/GPI")
        except Exception as e:
            print(f"[Libya Rhetoric] build_top_signals error: {str(e)[:120]}")
            result['top_signals'] = []
    else:
        result['top_signals'] = []

    # ── Re-save with all enriched fields ──
    _redis_set(RHETORIC_CACHE_KEY, result, ttl=24 * 3600)

    print(f"[Rhetoric Scan] Complete in {scan_time}s -- "
          f"level: {theatre_info['label']} ({theatre_level}), "
          f"score: {rhetoric_score}, specificity: {theatre_specificity}/10, "
          f"delta: {result.get('delta', {}).get('direction', 'n/a') if result.get('delta') else 'n/a'}")

    return result


# ========================================
# DAILY SNAPSHOT (legacy trend system — backward compat)
# ========================================

def _save_daily_snapshot(result):
    try:
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        snapshot = {
            'date': today,
            'rhetoric_score': result.get('rhetoric_score', 0),
            'theatre_level': result.get('theatre_level', 0),
            'actors': {}
        }
        for actor_id, actor_data in result.get('actors', {}).items():
            snapshot['actors'][actor_id] = {
                'escalation_level': actor_data.get('escalation_level', 0),
                'statement_count': actor_data.get('statement_count', 0),
                'silence_alert': actor_data.get('silence_alert', False),
            }

        history = _redis_get('rhetoric:libya:history:daily') or {}
        if 'snapshots' not in history:
            history['snapshots'] = {}
        history['snapshots'][today] = snapshot

        all_dates = sorted(history['snapshots'].keys())
        if len(all_dates) > 90:
            for old_date in all_dates[:-90]:
                del history['snapshots'][old_date]

        history['last_updated'] = datetime.now(timezone.utc).isoformat()
        _redis_set('rhetoric:libya:history:daily', history, ttl=24 * 91 * 3600)
        print(f"[Rhetoric] Saved daily snapshot for {today}")
    except Exception as e:
        print(f"[Rhetoric] Snapshot save error: {e}")


def get_rhetoric_trends(days=30):
    try:
        history = _redis_get('rhetoric:libya:history:daily')
        if not history or 'snapshots' not in history:
            return {'success': False, 'message': 'No trend data yet', 'days_collected': 0}

        snapshots = history['snapshots']
        sorted_dates = sorted(snapshots.keys())[-days:]

        trends = {
            'dates': [], 'rhetoric_score': [], 'theatre_level': [],
            'actors': {actor_id: [] for actor_id in LIBYA_ACTORS},
        }

        for date in sorted_dates:
            snap = snapshots[date]
            trends['dates'].append(date)
            trends['rhetoric_score'].append(snap.get('rhetoric_score', 0))
            trends['theatre_level'].append(snap.get('theatre_level', 0))
            for actor_id in LIBYA_ACTORS:
                actor_snap = snap.get('actors', {}).get(actor_id, {})
                trends['actors'][actor_id].append(actor_snap.get('escalation_level', 0))

        return {'success': True, 'days_collected': len(sorted_dates), 'trends': trends}
    except Exception as e:
        return {'success': False, 'message': str(e), 'days_collected': 0}


# ========================================
# FLASK ENDPOINT REGISTRATION
# ========================================

def register_libya_rhetoric_endpoints(app):
    from flask import request as flask_request, jsonify, make_response

    def _cors_response(data, status=200):
        resp = make_response(jsonify(data), status)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    @app.route('/api/rhetoric/libya', methods=['GET'])
    def api_rhetoric_libya():
        try:
            refresh = flask_request.args.get('refresh', 'false').lower() == 'true'
            force   = flask_request.args.get('force', 'false').lower() == 'true'

            if not refresh and not force:
                cached = _redis_get(RHETORIC_CACHE_KEY)
                if cached and is_cache_fresh(cached, max_age_hours=12):
                    cached['cached'] = True
                    return _cors_response(cached)

                if cached:
                    cached['cached'] = True
                    cached['stale'] = True
                    _trigger_rhetoric_scan()
                    return _cors_response(cached)

                print("[Rhetoric] Cold start — running synchronous scan")
                try:
                    result = run_rhetoric_scan(days=3)
                    return _cors_response(result)
                except Exception as e:
                    print(f"[Rhetoric] Cold start scan failed: {e}")
                    _trigger_rhetoric_scan()
                    return _cors_response(_build_empty_result())

            _trigger_rhetoric_scan()
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['refresh_triggered'] = True
                return _cors_response(cached)
            return _cors_response(_build_empty_result())

        except Exception as e:
            print(f"[Rhetoric API] Error: {e}")
            return _cors_response({'success': False, 'error': str(e)[:200]}, 500)

    @app.route('/api/rhetoric/libya/summary', methods=['GET'])
    def api_rhetoric_libya_summary():
        """
        Compact summary — includes v2.0 fields (theatre_score, delta, specificity)
        for rhetoric-index.html and stability page card.
        """
        try:
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if not cached:
                return _cors_response({
                    'success': False,
                    'rhetoric_score': 0,
                    'theatre_score': 0,
                    'theatre_level': 0,
                    'theatre_label': 'Awaiting scan',
                    'theatre_color': '#6b7280',
                    'theatre_escalation_level': 0,
                    'theatre_escalation_label': 'Awaiting scan',
                    'theatre_escalation_color': '#6b7280',
                    'alerts': [],
                    'awaiting_scan': True,
                })

            return _cors_response({
                'success': True,
                # Legacy fields (backward compat)
                'rhetoric_score':          cached.get('rhetoric_score', 0),
                'theatre_escalation_level':cached.get('theatre_escalation_level', 0),
                'theatre_escalation_label':cached.get('theatre_escalation_label', 'Monitoring'),
                'theatre_escalation_color':cached.get('theatre_escalation_color', '#6b7280'),
                # v2.0 unified fields (matches Yemen/Iraq/Syria pattern)
                'theatre_score':  cached.get('rhetoric_score', 0),
                'theatre_level':  cached.get('theatre_level', 0),
                'theatre_label':  cached.get('theatre_escalation_label', 'Monitoring'),
                'theatre_color':  cached.get('theatre_color', cached.get('theatre_escalation_color', '#6b7280')),
                # Vectors
                'ground_ops_level':  cached.get('ground_ops_level', 0),
                'rockets_level':     cached.get('rockets_level', 0),
                'ceasefire_level':   cached.get('ceasefire_level', 0),
                'crossborder_level': cached.get('crossborder_level', 0),
                'internal_fracture_level': cached.get('internal_fracture_level', 0),
                # v2.0 enriched
                'specificity_score': cached.get('specificity_score', 0),
                'delta':             cached.get('delta'),
                'silence_anomalies': cached.get('silence_anomalies', []),
                'total_articles':    cached.get('total_articles', 0),
                # ── DIPLOMATIC TRACK (v2.3) ──
                # Active negotiations reduce the threat score; these fields
                # expose the modifier and label to the frontend sidebar.
                'diplomatic_track_active':   cached.get('diplomatic_track_active', False),
                'diplomatic_modifier':       cached.get('diplomatic_modifier', 0),
                'diplomatic_label_detailed': cached.get('diplomatic_label_detailed', 'Quiet'),
                # Alerts
                'alerts':      cached.get('alerts', [])[:3],
                'scanned_at':  cached.get('scanned_at', ''),
                'timestamp':   cached.get('timestamp', cached.get('scanned_at', '')),
            })

        except Exception as e:
            return _cors_response({'error': str(e)[:200]}, 500)

    @app.route('/api/rhetoric/libya/trends', methods=['GET'])
    def api_rhetoric_libya_trends():
        try:
            days = int(flask_request.args.get('days', 30))
            days = min(days, 90)
            return _cors_response(get_rhetoric_trends(days))
        except Exception as e:
            return _cors_response({'success': False, 'error': str(e)[:200]}, 500)

    @app.route('/api/rhetoric/libya/history', methods=['GET'])
    def api_rhetoric_libya_history():
        """
        Rolling history normalized to match Yemen/Syria/Iraq /history shape.
        Reads from lpush key (rhetoric:libya:history) first,
        falls back to daily snapshot system.
        """
        try:
            limit = int(flask_request.args.get('limit', 120))
            limit = max(1, min(limit, 120))
            entries = []

            # Try lpush history first (v2.0 pattern)
            if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
                resp = requests.get(
                    f"{UPSTASH_REDIS_URL}/lrange/{RHETORIC_HISTORY_KEY}/0/{limit - 1}",
                    headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                    timeout=5
                )
                raw = resp.json().get('result', [])
                for item in raw:
                    try:
                        entries.append(json.loads(item))
                    except Exception:
                        pass

            # If lpush history is empty, fall back to daily snapshots
            if not entries:
                days = min(30, limit)
                trends = get_rhetoric_trends(days)
                if trends.get('success') and trends.get('trends'):
                    t = trends['trends']
                    dates  = t.get('dates', [])
                    scores = t.get('rhetoric_score', [])
                    levels = t.get('theatre_level', [])
                    level_labels = {
                        0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning',
                        3: 'Direct Threat', 4: 'Incident', 5: 'Active Conflict'
                    }
                    for i, date in enumerate(dates):
                        score = scores[i] if i < len(scores) else 0
                        level = levels[i] if i < len(levels) else 0
                        entries.append({
                            'ts':    date + 'T12:00:00+00:00',
                            'score': score,
                            'level': level,
                            'label': level_labels.get(level, 'Unknown'),
                        })

            entries.reverse()  # oldest first for chart rendering
            return _cors_response({
                'success': True,
                'theatre': 'Libya',
                'history_key': RHETORIC_HISTORY_KEY,
                'count': len(entries),
                'entries': entries,
            })
        except Exception as e:
            return _cors_response({'success': False, 'error': str(e)[:200]}, 500)

    print("[Rhetoric Tracker] ✅ Endpoints registered: "
          "/api/rhetoric/libya, /api/rhetoric/libya/summary, "
          "/api/rhetoric/libya/trends, /api/rhetoric/libya/history")

    if os.environ.get('RHETORIC_SCAN_DISABLED'):
        print("[Rhetoric Tracker] ✅ Cache-read only mode (scan disabled)")
        return

    def _periodic_rhetoric_scan():
        time.sleep(180)
        print("[Rhetoric Tracker] Starting initial scan...")
        _run_rhetoric_scan_safe()
        while True:
            print(f"[Rhetoric Tracker] Sleeping {SCAN_INTERVAL_HOURS}h until next scan...")
            time.sleep(SCAN_INTERVAL_SECONDS)
            print("[Rhetoric Tracker] Periodic scan starting...")
            _run_rhetoric_scan_safe()

    thread = threading.Thread(target=_periodic_rhetoric_scan, daemon=True)
    thread.start()
    print(f"[Rhetoric Tracker] ✅ Periodic scan thread started ({SCAN_INTERVAL_HOURS}h cycle)")


def _trigger_rhetoric_scan():
    global _scan_running
    with _scan_lock:
        if _scan_running:
            print("[Rhetoric] Scan already in progress, skipping")
            return
        _scan_running = True

    def _do_scan():
        global _scan_running
        try:
            run_rhetoric_scan(days=3)
        except Exception as e:
            print(f"[Rhetoric] Background scan error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            with _scan_lock:
                _scan_running = False

    thread = threading.Thread(target=_do_scan, daemon=True)
    thread.start()


def _run_rhetoric_scan_safe():
    global _scan_running
    with _scan_lock:
        if _scan_running:
            return
        _scan_running = True
    try:
        run_rhetoric_scan(days=3)
    except Exception as e:
        print(f"[Rhetoric] Periodic scan error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        with _scan_lock:
            _scan_running = False
