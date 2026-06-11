"""
Syria Rhetoric Tracker — Asifah Analytics
v2.0.0 — April 4, 2026

Upgraded to Yemen/Lebanon/Iraq gold standard:
  - Multi-actor matching (was single first-match)
  - Delta calculation vs prior scan history
  - Specificity scoring (0-10)
  - Actor baselines (Redis EMA)
  - Silence anomaly detection (Redis-backed)
  - Cross-theater coordination fingerprints (shared key)
  - Reporting actor downgrade (iran_proxies capped when reporting context)
  - Hezbollah cross-pollination coordination signal
  - Israel-Hezbollah-Syria nexus tracking

Actors monitored:
- HTS (Hay'at Tahrir al-Sham) — governing authority, Idlib/Damascus
- SDF (Syrian Democratic Forces) — Kurdish-led, northeast Syria
- SNA (Syrian National Army) — Turkish-backed, northern Syria
- Israel — active airstrikes southern Syria, Golan proximity
- ISIS — desert resurgence signals, Badia/Deir ez-Zor
- Iran Proxies — degraded but persistent, Deir ez-Zor corridor
- Turkey — diplomatic + military pressure on SDF/Rojava

Special monitoring:
- Druze / Suwayda — independent community signals + Israel coordination
- Hezbollah (Lebanon) cross-pollination — Israel strikes Syria while
  Hezbollah rhetoric spikes = coordinated pressure signal

Three threat vectors:
1. FACTIONAL CONFLICT — HTS vs SNA vs SDF territorial friction
2. ISRAELI STRIKE ACTIVITY — southern Syria, Golan, Hezbollah arms
3. ISIS RESURGENCE — Badia desert attack signals, sleeper cells

CHANGELOG:
  v2.0.0 (2026-03-21):
    - Multi-actor matching
    - Delta, specificity, baselines, silence anomalies, cross-theater
    - Reporting downgrade (iran_proxies)
    - Hezbollah cross-pollination signal
    - Unified Redis key pattern (rhetoric:syria:latest)
    - Summary endpoint v2.0 fields
  v1.0.0 (2026-03): Initial Syria rhetoric tracker

Registers on ME backend (asifah-backend.onrender.com)
Endpoints: GET /api/rhetoric/syria
           GET /api/rhetoric/syria/summary
           GET /api/rhetoric/syria/history
"""

import os
import json
import threading
import time
import requests
import xml.etree.ElementTree as ET
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from flask import jsonify, request

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

try:
    from telegram_signals import fetch_telegram_signals_syria
    TELEGRAM_AVAILABLE = True
    print("[Syria Rhetoric] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Syria Rhetoric] ⚠️ Telegram signals not available — RSS only")

# Signal interpreter -- So What, Red Lines, Historical Patterns
try:
    from syria_signal_interpreter import (
        interpret_signals as syria_interpret_signals,
        build_top_signals as syria_build_top_signals,
    )
    INTERPRETER_AVAILABLE = True
    print("[Syria Rhetoric] Signal interpreter loaded (incl. build_top_signals v2.0)")
except ImportError as e:
    INTERPRETER_AVAILABLE = False
    syria_build_top_signals = None
    print(f"[Syria Rhetoric] Warning: Signal interpreter not available: {e}")

RHETORIC_CACHE_KEY        = 'rhetoric:syria:latest'      # v2.0 unified key
RHETORIC_CACHE_KEY_LEGACY = 'syria_rhetoric_cache'        # backward compat
HISTORY_KEY               = 'rhetoric:syria:history'
BASELINE_KEY              = 'rhetoric_baseline:syria'
CROSSTHEATER_KEY          = 'rhetoric:crosstheater:fingerprints'  # shared

RHETORIC_CACHE_TTL = 13 * 3600  # 13h -- covers 12h scan cycle + 1h buffer

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ESCALATION LEVELS
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Baseline',       'color': '#6b7280', 'description': 'No significant signals'},
    1: {'label': 'Rhetoric',       'color': '#3b82f6', 'description': 'Standard factional statements'},
    2: {'label': 'Tension',        'color': '#f59e0b', 'description': 'Warnings, territorial disputes'},
    3: {'label': 'Confrontation',  'color': '#f97316', 'description': 'Direct threats, troop movements'},
    4: {'label': 'Incident',       'color': '#ef4444', 'description': 'Clashes confirmed, strikes reported'},
    5: {'label': 'Active Conflict','color': '#991b1b', 'description': 'Ongoing operations, multiple fronts'},
}


# ============================================
# ACTORS
# ============================================
ACTORS = {
    'hts': {
        'name': 'HTS / Interim Government',
        'flag': '🇸🇾',
        'icon': '🏛️',
        'color': '#16a34a',
        'role': 'Governing Authority',
        'description': 'Hay\'at Tahrir al-Sham — de facto governing authority post-Assad',
        'spokespersons': [
            'ahmed al-sharaa', 'abu mohammad al-jolani', 'al-jolani',
            'hts spokesperson', 'syrian salvation government',
            'hayat tahrir al-sham', 'ministry of interior syria',
            'syrian interim government', 'hts statement',
            'أحمد الشرع', 'هيئة تحرير الشام', 'حكومة الإنقاذ السورية',
        ],
        'keywords': [
            'hts', 'hayat tahrir al-sham', 'hay\'at tahrir', 'jolani', 'al-jolani',
            'ahmed al-sharaa', 'syrian interim government', 'syrian salvation government',
            'hts government', 'hts forces', 'hts fighters', 'hts controls',
            'hts security', 'hts administration', 'hts statement',
            'idlib', 'aleppo government', 'damascus new government',
            'new syrian government', 'post-assad syria', 'transitional syria',
            'هيئة تحرير الشام', 'أبو محمد الجولاني', 'أحمد الشرع',
            'حكومة الإنقاذ', 'إدلب', 'الحكومة السورية الجديدة',
        ],
        'baseline_statements_per_week': 10,
    },
    'sdf': {
        'name': 'SDF / AANES',
        'flag': '🟡',
        'icon': '⭐',
        'color': '#f59e0b',
        'role': 'Kurdish-led Forces',
        'description': 'Syrian Democratic Forces — Kurdish-led, US-backed, NE Syria',
        'spokespersons': [
            'mazloum abdi', 'mazloum kobani', 'sdf commander',
            'sdf spokesperson', 'sdf statement',
            'autonomous administration of north and east syria', 'aanes',
            'ypg', 'ypj', 'qsd',
            'مظلوم عبدي', 'قوات سوريا الديمقراطية', 'الإدارة الذاتية',
        ],
        'keywords': [
            'sdf', 'syrian democratic forces', 'kurdish forces syria',
            'ypg', 'ypj', 'qsd', 'mazloum abdi', 'mazloum kobani',
            'aanes', 'autonomous administration', 'rojava',
            'northeast syria', 'kobane', 'qamishli', 'hasakah',
            'deir ez-zor sdf', 'manbij sdf', 'raqqa sdf',
            'sdf hts agreement', 'sdf integration', 'sdf ceasefire',
            'us-backed kurds', 'us-backed forces syria',
            'قوات سوريا الديمقراطية', 'الإدارة الذاتية لشمال',
            'وحدات حماية الشعب', 'كوباني', 'قامشلي',
        ],
        'baseline_statements_per_week': 8,
    },
    'sna': {
        'name': 'SNA / Turkish-backed Factions',
        'flag': '🇹🇷',
        'icon': '⚔️',
        'color': '#dc2626',
        'role': 'Turkish-backed Forces',
        'description': 'Syrian National Army — Turkish-backed, northern Syria operations',
        'spokespersons': [
            'sna commander', 'sna spokesperson', 'turkish-backed factions',
            'national front for liberation', 'sultan murad division',
            'hamza division', 'suleiman shah brigade',
        ],
        'keywords': [
            'syrian national army', 'sna', 'turkish-backed', 'turkey-backed',
            'turkish proxy syria', 'turkish forces syria',
            'euphrates shield', 'olive branch', 'peace spring', 'spring shield',
            'afrin', 'tal abyad', 'ras al-ayn', 'serekaniye',
            'turkish operation syria', 'turkey syria offensive',
            'sultan murad', 'hamza division', 'north syria factions',
            'turkish military syria', 'turkish troops syria',
            'turkey sdf', 'turkey kurds syria', 'turkey hts',
            'الجيش الوطني السوري', 'الفصائل المدعومة تركياً',
            'درع الفرات', 'غصن الزيتون', 'عفرين',
        ],
        'baseline_statements_per_week': 6,
    },
    'israel': {
        'name': 'Israel (re: Syria)',
        'flag': '🇮🇱',
        'icon': '🔷',
        'color': '#3b82f6',
        'role': 'Strike Actor',
        'description': 'Israeli airstrikes in southern Syria — weapons depots, Golan proximity, Hezbollah arms interdiction',
        'spokespersons': [
            'idf syria', 'idf strikes syria', 'israeli airstrike syria',
            'netanyahu syria', 'katz syria', 'idf spokesperson syria',
            'צה"ל סוריה', 'ישראל סוריה',
        ],
        'keywords': [
            'israel strikes syria', 'israeli airstrike syria', 'idf strikes syria',
            'israel syria', 'israeli operation syria', 'idf syria',
            'israel bombs syria', 'israel targets syria',
            'golan heights', 'golan buffer zone', 'golan syria',
            'israel quneitra', 'israel daraa', 'israel suwayda',
            'israel weapons depot syria', 'israel arms syria',
            'israel hezbollah syria', 'israel iran syria',
            'israel druze syria', 'druze israel coordination',
            'israeli jets syria', 'israeli aircraft syria',
            'buffer zone syria israel', 'mount hermon israel',
            'ישראל סוריה', 'צה"ל תוקף בסוריה', 'רמת הגולן',
            'إسرائيل سوريا', 'الغارات الإسرائيلية سوريا',
            'هضبة الجولان', 'درعا', 'السويداء', 'القنيطرة',
        ],
        'baseline_statements_per_week': 8,
    },
    'isis': {
        'name': 'ISIS / Remnants',
        'flag': '⚫',
        'icon': '💀',
        'color': '#374151',
        'role': 'Resurgent Threat',
        'description': 'ISIS remnants — Badia desert, Deir ez-Zor, sleeper cell activity',
        'spokespersons': [
            'isis spokesman', 'islamic state statement', 'isis claims',
            'amaq news agency', 'isis media',
        ],
        'keywords': [
            'isis syria', 'islamic state syria', 'isil syria', 'daesh syria',
            'isis attack syria', 'isis ambush syria', 'isis claims syria',
            'badia desert', 'syrian desert isis', 'palmyra isis',
            'deir ez-zor isis', 'isis resurgence', 'isis sleeper cells',
            'isis checkpoint attack', 'isis ied syria',
            'hts isis', 'sdf isis', 'counter-isis syria',
            'operation inherent resolve', 'us strikes isis syria',
            'isis comeback', 'isis revival syria',
            'داعش سوريا', 'تنظيم الدولة سوريا', 'البادية السورية',
            'داعش يهاجم', 'خلايا نائمة سوريا',
        ],
        'baseline_statements_per_week': 4,
    },
    'iran_proxies': {
        'name': 'Iran Proxies (Syria)',
        'flag': '🇮🇷',
        'icon': '🕌',
        'color': '#7c3aed',
        'role': 'Degraded Presence',
        'description': 'IRGC/proxy remnants — Deir ez-Zor corridor, degraded but monitoring',
        'spokespersons': [
            'irgc syria', 'quds force syria', 'iranian backed syria',
            'hezbollah syria', 'iranian militia syria',
        ],
        'keywords': [
            'iran syria', 'iranian forces syria', 'irgc syria',
            'quds force syria', 'iran proxies syria', 'iranian militia syria',
            'hezbollah syria', 'iranian withdrawal syria',
            'iran influence syria', 'tehran syria',
            'deir ez-zor iran', 'bukamal iran', 'abu kamal iran',
            'iranian corridor syria', 'land bridge iran',
            'iran hts', 'iran new syria government',
            'إيران سوريا', 'الحرس الثوري سوريا', 'حزب الله سوريا',
            'الميليشيات الإيرانية سوريا', 'ممر إيران',
        ],
        'baseline_statements_per_week': 5,
    },
    'turkey': {
        'name': 'Turkey',
        'flag': '🇹🇷',
        'icon': '🦅',
        'color': '#dc2626',
        'role': 'Regional Power',
        'description': 'Turkish government — diplomatic + military pressure on SDF/Rojava',
        'spokespersons': [
            'erdogan syria', 'erdogan kurds', 'turkish foreign ministry syria',
            'fidan syria', 'hakan fidan', 'turkish defense ministry',
            'turkish military spokesperson',
            'türkiye suriye', 'erdoğan suriye',
        ],
        'keywords': [
            'turkey syria', 'erdogan syria', 'turkish policy syria',
            'turkey hts', 'turkey sdf', 'turkey kurds',
            'turkish military syria', 'turkey operation syria',
            'ankara syria', 'turkish foreign policy syria',
            'turkey safe zone syria', 'turkey border syria',
            'hakan fidan syria', 'turkey pkk syria',
            'turkey new syrian government', 'turkey hts relations',
            'تركيا سوريا', 'أردوغان سوريا', 'القوات التركية سوريا',
            'السياسة التركية سوريا',
        ],
        'baseline_statements_per_week': 7,
    },
    'us_envoy': {
        'name': 'US Envoy / CENTCOM (Syria)',
        'flag': '🇺🇸',
        'icon': '🤝',
        'color': '#0369a1',
        'role': 'US Policy / Diplomatic Signal',
        'description': 'Tom Barrack (Special Envoy), CENTCOM, State Dept — US Syria policy, SDF support, HTS engagement',
        'spokespersons': [
            'tom barrack', 'barrack syria', 'us special envoy syria',
            'centcom syria', 'state department syria', 'rubio syria',
            'trump syria', 'us envoy syria',
        ],
        'keywords': [
            # Tom Barrack — Special Envoy, primary signal source
            'tom barrack', 'barrack syria', 'barrack hts', 'barrack damascus',
            'barrack jolani', 'barrack sharaa', 'barrack envoy',
            'us special envoy syria', 'trump envoy syria',
            # US policy / CENTCOM
            'centcom syria', 'us forces syria', 'us troops syria',
            'us military syria', 'operation inherent resolve',
            'us sdf syria', 'us kurds syria', 'us backed sdf',
            'us sanctions syria', 'us lift sanctions syria',
            'us recognize syria', 'us engage hts', 'us hts designation',
            'rubio syria', 'trump syria policy', 'us syria strategy',
            'state department syria', 'us embassy syria',
            'us aid syria', 'us reconstruction syria',
            # Arabic
            'توم باراك سوريا', 'المبعوث الأمريكي سوريا',
            'القوات الأمريكية سوريا', 'السياسة الأمريكية سوريا',
        ],
        'baseline_statements_per_week': 5,
    },
}



# ============================================
# DRUZE / SUWAYDA SPECIAL MONITOR
# ============================================
DRUZE_KEYWORDS = [
    'druze', 'suwayda', 'sweida', 'jabal al-arab', 'druze community syria',
    'druze leaders syria', 'druze militia', 'men of dignity',
    'druze israel', 'israel druze syria', 'druze coordination israel',
    'druze protection israel', 'israel protect druze',
    'druze flag', 'druze self-defense',
    'hts druze', 'druze hts', 'druze resist hts',
    'druze autonomy', 'druze independence',
    'السويداء', 'الدروز سوريا', 'جبل العرب',
    'رجال الكرامة', 'الدروز وإسرائيل',
]

# Hezbollah-Syria nexus keywords — Israeli strikes on Hezbollah arms in Syria
HEZBOLLAH_SYRIA_NEXUS = [
    'hezbollah weapons syria', 'hezbollah arms depot syria',
    'hezbollah transfer syria', 'hezbollah corridor syria',
    'israel hezbollah syria', 'idf hezbollah syria',
    'hezbollah smuggling syria', 'hezbollah syria strike',
    'arms for hezbollah', 'weapons for hezbollah syria',
    'حزب الله سوريا أسلحة', 'ضربات إسرائيل حزب الله سوريا',
]


# ============================================
# REPORTING ACTOR DOWNGRADE (v2.0)
# ============================================
# iran_proxies is the primary reporting actor — they report on Israel strikes
# rather than threatening them. HTS is NOT in this list — they govern and can
# genuinely threaten. Turkey is NOT in this list — they issue real threats.
REPORTING_ACTORS = {'iran_proxies'}

REPORTING_LANGUAGE = [
    'condemns', 'condemned', 'denounces', 'denounced',
    'rejects the strike', 'protests the',
    'mourns', 'condolences', 'victims of',
    'calls on', 'calls for', 'urges', 'urged',
    'in response to the strike', 'following the airstrike',
    'after the bombing', 'in the wake of',
    'expressed concern', 'deeply concerned',
    'iran condemns', 'condemns israeli',
    'يستنكر', 'استنكر', 'يدين', 'أدان',
    'يطالب', 'في أعقاب الغارة',
]


# ============================================
# THREAT VECTORS
# ============================================

# Vector 1: Factional Conflict
FACTIONAL_TRIGGERS = {
    5: [
        'hts attacks sdf', 'sna offensive', 'hts sdf clashes',
        'full-scale offensive', 'multi-front attack',
        'hts advances on', 'sna captures', 'sdf overrun',
        'factional war', 'inter-faction fighting',
    ],
    4: [
        'hts sdf clashes', 'sna sdf fighting', 'hts moves on',
        'troops massing', 'forces deployed', 'military buildup',
        'ultimatum issued', 'deadline to withdraw',
        'hts arrests sdf', 'sdf detained', 'forces surrounded',
        'sna pushes into', 'crossing into territory',
    ],
    3: [
        'hts warns sdf', 'turkey threatens sdf', 'hts demands',
        'red line', 'will not tolerate', 'must withdraw',
        'territorial dispute', 'border friction', 'incident reported',
        'troops at border', 'forces on alert', 'heightened tensions',
        'hts sna coordination', 'joint operation planned',
    ],
    2: [
        'hts sdf tensions', 'factional tensions', 'disagreement',
        'rival factions', 'competing claims', 'disputed territory',
        'negotiations stalled', 'talks broke down',
        'integration rejected', 'autonomy dispute',
    ],
    1: [
        'hts', 'sdf', 'sna', 'factional', 'factions',
        'syrian forces', 'armed groups', 'militia',
    ],
}

# Vector 2: Israeli Strike Activity (includes Hezbollah arms interdiction)
ISRAELI_STRIKE_TRIGGERS = {
    5: [
        'israel strikes damascus', 'israel bombs aleppo',
        'massive israeli strike', 'idf ground operation syria',
        'israel targets multiple sites', 'wave of airstrikes syria',
        'israel expands operations syria',
    ],
    4: [
        'israeli airstrike confirmed', 'idf strikes', 'israel bombs',
        'israel targets weapons', 'israel hits depot',
        'israel strikes near golan', 'israel strikes quneitra',
        'israel strikes daraa', 'israel strikes suwayda',
        'israel hits hezbollah syria', 'israel destroys arms',
        'israel hezbollah weapons', 'israel interdicts arms',
        'israel destroys hezbollah depot', 'idf hezbollah syria',
    ],
    3: [
        'israel warns syria', 'israel threatens strike',
        'israel monitoring', 'idf on alert syria',
        'golan incursion', 'buffer zone violation',
        'weapons transfer warning', 'arms smuggling warning',
        'israel will act', 'israel right to strike',
        'hezbollah arms route', 'weapons pipeline syria',
    ],
    2: [
        'israel watching syria', 'golan tensions', 'buffer zone',
        'weapons smuggling syria', 'arms transfer concern',
        'iranian weapons syria', 'hezbollah arms syria',
        'hezbollah corridor', 'arms for hezbollah',
    ],
    1: [
        'israel syria', 'golan', 'israeli', 'idf',
        'airspace violation', 'overflight syria',
        'hezbollah syria', 'arms depot',
    ],
}

# Vector 3: ISIS Resurgence
ISIS_RESURGENCE_TRIGGERS = {
    5: [
        'isis controls territory', 'isis captures town',
        'isis overruns checkpoint', 'isis mass attack',
        'isis offensive launched', 'isis takes over',
    ],
    4: [
        'isis ambush kills', 'isis attack kills',
        'isis ied kills', 'isis claims attack',
        'isis executes', 'isis massacre',
        'large isis cell', 'isis complex attack',
    ],
    3: [
        'isis attack', 'isis strikes', 'isis claims',
        'isis threat', 'isis active', 'isis resurgent',
        'sleeper cell activated', 'isis checkpoint',
        'isis ambush', 'isis ied', 'isis kidnapping',
    ],
    2: [
        'isis activity', 'isis presence', 'isis spotted',
        'isis movement', 'counter-isis operation',
        'isis threat elevated', 'badia attacks',
        'desert insurgency', 'isis financing',
    ],
    1: [
        'isis', 'islamic state', 'isil', 'daesh',
        'badia', 'palmyra', 'deir ez-zor',
    ],
}


# ============================================
# ACTOR KEYWORD MAPPING
# ============================================
ACTOR_KEYWORDS = {
    'hts': [
        'hts', 'hayat tahrir', 'jolani', 'al-sharaa', 'ahmed al-sharaa',
        'syrian interim government', 'syrian salvation', 'idlib',
        'هيئة تحرير الشام', 'الحكومة السورية الجديدة',
    ],
    'sdf': [
        'sdf', 'syrian democratic forces', 'ypg', 'ypj', 'mazloum',
        'aanes', 'rojava', 'kobane', 'qamishli', 'hasakah',
        'قوات سوريا الديمقراطية', 'الإدارة الذاتية',
    ],
    'sna': [
        'syrian national army', 'sna', 'turkish-backed', 'euphrates shield',
        'olive branch', 'afrin', 'sultan murad', 'hamza division',
        'الجيش الوطني السوري', 'درع الفرات',
    ],
    'israel': [
        'israel', 'idf', 'israeli', 'golan', 'netanyahu syria',
        'ישראל', 'צה"ל', 'إسرائيل سوريا',
    ],
    'isis': [
        'isis', 'islamic state', 'isil', 'daesh', 'amaq',
        'badia', 'داعش', 'تنظيم الدولة',
    ],
    'iran_proxies': [
        'iran syria', 'irgc syria', 'iranian militia', 'hezbollah syria',
        'quds force syria', 'iranian backed', 'إيران سوريا', 'الحرس الثوري سوريا',
    ],
    'turkey': [
        'turkey syria', 'erdogan syria', 'turkish', 'ankara syria',
        'hakan fidan', 'تركيا سوريا', 'أردوغان',
    ],
    'us_envoy': [
        'tom barrack', 'barrack syria', 'us special envoy syria',
        'centcom syria', 'us forces syria', 'rubio syria',
        'trump syria', 'us sdf', 'us sanctions syria',
        'us hts', 'توم باراك', 'المبعوث الأمريكي سوريا',
    ],
}


# ============================================
# SPECIFICITY SCORER (v2.0)
# ============================================
SPECIFIC_GEOGRAPHIES_SYRIA = [
    # Cities / regions
    'damascus', 'aleppo', 'idlib', 'homs', 'hama', 'deir ez-zor',
    'raqqa', 'hasakah', 'qamishli', 'kobane', 'manbij', 'afrin',
    'daraa', 'suwayda', 'quneitra', 'palmyra',
    # Southern Syria / Golan
    'golan heights', 'mount hermon', 'buffer zone', 'blue line syria',
    # Hezbollah corridor
    'bukamal', 'abu kamal', 'deir ez-zor corridor', 'al-tanf',
    # Druze areas
    'jabal al-arab', 'sweida', 'suwayda',
    # Badia desert
    'badia desert', 'syrian desert', 'tadmur',
]

SPECIFIC_ASSETS_SYRIA = [
    'weapons depot', 'arms depot', 'missile depot', 'ammunition depot',
    'hezbollah convoy', 'arms shipment', 'weapons transfer',
    'airbase syria', 'tiyas airbase', 't4 airbase',
    'radwan force syria', 'quds force position',
    'isis sleeper cell', 'isis checkpoint',
]

TIME_BOUNDED_SYRIA = [
    'within 24 hours', 'within 48 hours', 'within 72 hours',
    'by tomorrow', 'imminent', 'tonight', 'this week',
    'in the coming hours', 'before the end of',
    'ultimatum expires', 'deadline',
]

OPERATIONAL_FRAMING_SYRIA = [
    'preparing to launch', 'positioned to strike', 'ready to fire',
    'forces massing', 'troops deploying', 'multi-front',
    'joint operation', 'coordinated attack',
    'saturation strike', 'ground operation imminent',
]


def _score_specificity(text):
    """Score 0-10 operational specificity. Returns (score, breakdown)."""
    score = 0
    breakdown = {
        'named_geographies': [],
        'named_assets': [],
        'time_bounded': [],
        'operational_framing': [],
    }
    for geo in SPECIFIC_GEOGRAPHIES_SYRIA:
        if geo in text:
            breakdown['named_geographies'].append(geo)
            score += 1
    for asset in SPECIFIC_ASSETS_SYRIA:
        if asset in text:
            breakdown['named_assets'].append(asset)
            score += 1
    for tb in TIME_BOUNDED_SYRIA:
        if tb in text:
            breakdown['time_bounded'].append(tb)
            score += 2
    for op in OPERATIONAL_FRAMING_SYRIA:
        if op in text:
            breakdown['operational_framing'].append(op)
            score += 2
    return min(score, 10), breakdown


# ============================================
# DELTA CALCULATION (v2.0)
# ============================================
def _compute_delta():
    """Compare most recent history entry to prior average."""
    try:
        if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
            return None
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/lrange/{HISTORY_KEY}/0/13",
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
        score_change = current.get('score', 0) - prior_avg_score
        level_change = round(current.get('level', 0) - prior_avg_level, 2)

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
        print(f"[Syria Rhetoric] Delta compute error: {e}")
        return None


# ============================================
# ACTOR BASELINES (v2.0)
# ============================================
def _update_actor_baselines(actor_results):
    """EMA of statement_count and max_level per actor. 30-day TTL."""
    try:
        existing = _redis_get(BASELINE_KEY) or {}
        updated = {}
        alpha = 0.2
        for actor_id, ar in actor_results.items():
            current_statements = ar.get('statement_count', 0)
            current_level = ar.get('max_level', 0)
            prev = existing.get(actor_id, {})
            if not prev:
                updated[actor_id] = {
                    'avg_statements': current_statements,
                    'avg_level': current_level,
                    'scans': 1,
                }
            else:
                updated[actor_id] = {
                    'avg_statements': round(
                        alpha * current_statements + (1 - alpha) * prev.get('avg_statements', current_statements), 2
                    ),
                    'avg_level': round(
                        alpha * current_level + (1 - alpha) * prev.get('avg_level', current_level), 3
                    ),
                    'scans': min(prev.get('scans', 1) + 1, 999),
                }
        _redis_set(BASELINE_KEY, updated, ttl=30 * 24 * 3600)
        print(f"[Syria Rhetoric] ✅ Actor baselines updated")
        return updated
    except Exception as e:
        print(f"[Syria Rhetoric] Baseline update error: {e}")
        return {}


def _detect_silence_anomalies(actor_results, baselines):
    """Flag actors significantly below their Redis baseline. Needs 5+ scans."""
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
                actor_info = ACTORS.get(actor_id, {})
                anomalies.append({
                    'actor_id': actor_id,
                    'actor_name': actor_info.get('name', actor_id),
                    'actor_flag': actor_info.get('flag', ''),
                    'expected_statements': round(avg_statements),
                    'actual_statements': actual,
                    'deviation': f'{pct_below}% below baseline',
                    'signal': 'Unusual quiet — possible operational security',
                })
                print(f"[Syria Rhetoric] 🔇 Silence anomaly: {actor_id} ({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Syria Rhetoric] Silence detection error: {e}")
    return anomalies


# ============================================
# CROSS-THEATER COORDINATION (v2.0)
# ============================================
def _write_crosstheater_signal(result):
    """Write Syria fingerprint to shared cross-theater Redis key."""
    try:
        existing = _redis_get(CROSSTHEATER_KEY) or {}

        top_phrases = []
        for sig in result.get('coordination_signals', [])[:3]:
            msg = sig.get('message', '')
            if msg:
                top_phrases.append(msg[:60])

        named_targets = []
        actors = result.get('actors', {})
        for actor_id in ['israel', 'hts', 'isis']:
            for art in actors.get(actor_id, {}).get('top_articles', [])[:3]:
                title_lower = art.get('title', '').lower()
                for geo in SPECIFIC_GEOGRAPHIES_SYRIA:
                    if geo in title_lower and geo not in named_targets:
                        named_targets.append(geo)

        existing['syria'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Syria',
            'level': result.get('theatre_escalation_level', 0),
            'score': result.get('theatre_score', 0),
            'theatre_score': result.get('theatre_score', 0),
            'israeli_strike_level': result.get('israeli_strike_level', 0),
            'factional_level': result.get('factional_level', 0),
            'isis_level': result.get('isis_level', 0),
            'druze_signals_count': len(result.get('druze_signals', [])),
            'hezbollah_nexus_count': result.get('hezbollah_nexus_count', 0),
            'top_phrases': top_phrases[:5],
            'named_targets': named_targets[:8],
            'actor_levels': {
                aid: actors.get(aid, {}).get('max_level', 0)
                for aid in ['israel', 'hts', 'iran_proxies', 'isis']
            },
            'specificity_score': result.get('specificity_score', 0),
        }

        _redis_set(CROSSTHEATER_KEY, existing, ttl=8 * 3600)
        print(f"[Syria Rhetoric] ✅ Cross-theater fingerprint written")
    except Exception as e:
        print(f"[Syria Rhetoric] Cross-theater write error: {e}")


def _detect_crosstheater_coordination():
    """Read all theater fingerprints and detect coordination signals."""
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

        expected = ['yemen', 'iraq', 'lebanon', 'syria', 'iran', 'israel']
        missing = [t for t in expected if t not in fresh]
        if missing:
            print(f"[CrossTheater/Syria] Note: {missing} not yet active")

        # Check 1: Simultaneous elevation across proxy theaters
        proxy_theaters = {k: v for k, v in fresh.items() if k in ['yemen', 'iraq', 'lebanon', 'syria']}
        if len(proxy_theaters) >= 2:
            elevated = {k: v for k, v in proxy_theaters.items() if v.get('level', 0) >= 2}
            if len(elevated) >= 2:
                avg_level = round(sum(v['level'] for v in elevated.values()) / len(elevated), 1)
                findings.append({
                    'type': 'simultaneous_elevation',
                    'message': f"Simultaneous elevated rhetoric across {len(elevated)} theaters",
                    'theaters': list(elevated.keys()),
                    'avg_level': avg_level,
                    'confidence': min(len(elevated) * 25, 90),
                    'signal': 'Multi-theater elevation — watch for coordinated operations',
                    'missing_theaters': missing,
                })

        # Check 2: Israel-Hezbollah nexus — Syria strikes coincide with Lebanon elevation
        if 'syria' in fresh and 'lebanon' in fresh:
            syria_strike_level = fresh['syria'].get('israeli_strike_level', 0)
            leb_level = fresh['lebanon'].get('level', 0)
            if syria_strike_level >= 3 and leb_level >= 3:
                findings.append({
                    'type': 'israel_hezbollah_nexus',
                    'message': 'Israel-Hezbollah cross-theater pressure — Syria strikes + Lebanon elevation simultaneous',
                    'syria_strike_level': syria_strike_level,
                    'lebanon_level': leb_level,
                    'confidence': min((syria_strike_level + leb_level) * 10, 85),
                    'signal': 'Israeli strikes on Hezbollah arms in Syria coincide with Lebanon rhetoric spike — possible coordinated pressure campaign',
                    'missing_theaters': missing,
                })

        # Check 3: Named target convergence
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
                'signal': 'Multiple theaters referencing same targets',
                'missing_theaters': missing,
            })

    except Exception as e:
        print(f"[Syria Rhetoric] Cross-theater detection error: {e}")

    return findings


# ============================================
# RSS FEEDS
# ============================================
RHETORIC_RSS_FEEDS = [
    # HTS / Post-Assad governance
    ("https://news.google.com/rss/search?q=HTS+Syria+governance+Sharaa+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Ahmad+al-Sharaa+Syria+Jolani+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Hayat+Tahrir+al-Sham+Syria+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=HTS+Syria+conflict+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Syria+SDF+HTS+factions&hl=en&gl=US&ceid=US:en", 0.95),
    # Israeli strikes on Syria
    ("https://news.google.com/rss/search?q=Israel+strikes+Syria+IDF+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Israel+Hezbollah+weapons+Syria&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=IDF+strikes+Syria+weapons+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Israel+Hezbollah+arms+Syria+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Golan+Heights+Israel+Syria+2026&hl=en&gl=US&ceid=US:en", 0.95),
    # Turkey / SDF / Kurdish
    ("https://news.google.com/rss/search?q=Turkey+SDF+Syria+Rojava&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Turkey+SDF+Syria+Kurdish+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Turkey+Syria+military+operation+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Syria+Kurdish+forces+2026&hl=en&gl=US&ceid=US:en", 0.85),
    ("https://news.google.com/rss/search?q=Erdogan+Syria+2026&hl=en&gl=US&ceid=US:en", 0.9),
    # ISIS resurgence
    ("https://news.google.com/rss/search?q=ISIS+Syria+resurgence+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=ISIS+Deir+ez-Zor+Syria+desert+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Syria+war+2026+factions&hl=en&gl=US&ceid=US:en", 0.85),
    # Iran expulsion / re-entry
    ("https://news.google.com/rss/search?q=Iran+Syria+IRGC+expelled+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iran+proxy+Syria+Hezbollah+corridor+2026&hl=en&gl=US&ceid=US:en", 1.0),
    # Druze / Suwayda
    ("https://news.google.com/rss/search?q=Druze+Suwayda+Syria&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Druze+Suwayda+Syria+autonomy+2026&hl=en&gl=US&ceid=US:en", 1.0),
    # Normalization / sanctions
    ("https://news.google.com/rss/search?q=Syria+Israel+normalization+recognition+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Syria+sanctions+Caesar+Act+US+2026&hl=en&gl=US&ceid=US:en", 1.0),
    # US Envoy / Barrack
    ("https://news.google.com/rss/search?q=Tom+Barrack+Syria+2026&hl=en&gl=US&ceid=US:en", 1.1),
    ("https://news.google.com/rss/search?q=US+special+envoy+Syria+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=CENTCOM+Syria+SDF+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=US+Syria+sanctions+HTS+2026&hl=en&gl=US&ceid=US:en", 0.95),
    # Arabic
    ("https://news.google.com/rss/search?q=\u0647\u064a\u0626\u0629+\u062a\u062d\u0631\u064a\u0631+\u0627\u0644\u0634\u0627\u0645+\u0633\u0648\u0631\u064a\u0627&hl=ar&gl=SA&ceid=SA:ar", 0.95),
    ("https://news.google.com/rss/search?q=\u0623\u062d\u0645\u062f+\u0627\u0644\u0634\u0631\u0639+\u0633\u0648\u0631\u064a\u0627+2026&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=\u062f\u0627\u0639\u0634+\u0633\u0648\u0631\u064a\u0627+2026&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=\u0625\u0633\u0631\u0627\u0626\u064a\u0644+\u063a\u0627\u0631\u0627\u062a+\u0633\u0648\u0631\u064a\u0627&hl=ar&gl=SA&ceid=SA:ar", 0.95),
    ("https://news.google.com/rss/search?q=\u0627\u0644\u0633\u0648\u064a\u062f\u0627\u0621+\u0627\u0644\u062f\u0631\u0648\u0632+\u0633\u0648\u0631\u064a\u0627&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=\u062d\u0632\u0628+\u0627\u0644\u0644\u0647+\u0633\u0648\u0631\u064a\u0627+\u0623\u0633\u0644\u062d\u0629&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    # Hebrew
    ("https://news.google.com/rss/search?q=\u05d9\u05e9\u05e8\u05d0\u05dc+\u05e1\u05d5\u05e8\u05d9\u05d4+\u05ea\u05e7\u05d9\u05e4\u05d4&hl=iw&gl=IL&ceid=IL:iw", 0.95),
    ("https://news.google.com/rss/search?q=\u05d7\u05d9\u05d6\u05d1\u05d0\u05dc\u05dc\u05d4+\u05e0\u05e9\u05e7+\u05e1\u05d5\u05e8\u05d9\u05d4&hl=iw&gl=IL&ceid=IL:iw", 0.95),
    # Direct sources
    ("https://syriadirect.org/feed/", 1.0),
    ("https://www.syriahr.com/en/feed/", 1.0),
]

# ============================================
# NITTER -- Primary source Twitter/X accounts
# ============================================
NITTER_MIRRORS = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

NITTER_ACCOUNTS_SYRIA = [
    ("TomBarrack",      1.3, "US Special Envoy -- primary Syria policy signal"),
    ("StateDept",       1.0, "State Dept -- Syria sanctions, HTS engagement"),
    ("CENTCOM",         1.0, "CENTCOM -- Syria force posture, SDF, ISIS strikes"),
    ("SecRubio",        1.0, "US SecState -- Syria recognition/sanctions signals"),
    ("realDonaldTrump", 1.1, "Trump -- Syria policy direction"),
    ("IDF",             1.1, "IDF official -- Syria strike announcements"),
    ("AvichayAdraee",   1.1, "IDF Arabic spokesperson -- Syria strike claims"),
    ("MazloumAbdi",     1.1, "SDF Commander -- Kurdish forces statements"),
    ("SyriaDirectNews", 0.9, "Syria Direct -- ground reporting"),
    ("SOHR_News",       0.9, "SOHR -- strike/casualty reports"),
]


def _fetch_nitter_syria(username, weight=1.0, timeout=8):
    import re as _re
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
                desc_el    = item.find("description")
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
                desc = ""
                if desc_el is not None and desc_el.text:
                    desc = _re.sub(r"<[^>]+>", "", desc_el.text)[:300]
                posts.append({
                    "title":       title,
                    "url":         link,
                    "published":   pub,
                    "description": desc,
                    "source":      f"Nitter @{username}",
                    "weight":      weight,
                })
            if posts:
                print(f"[Syria Rhetoric/Nitter] @{username}: {len(posts)} posts via {mirror}")
                return posts
        except Exception as e:
            print(f"[Syria Rhetoric/Nitter] @{username} {mirror} failed: {str(e)[:60]}")
            continue
    print(f"[Syria Rhetoric/Nitter] @{username}: all mirrors failed")
    return []


def fetch_nitter_syria(days=3):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen = set()
    for username, weight, desc in NITTER_ACCOUNTS_SYRIA:
        posts = _fetch_nitter_syria(username, weight=weight)
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
    print(f"[Syria Rhetoric/Nitter] Total: {len(all_posts)} posts")
    return all_posts

REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
SYRIA_SUBREDDITS = ['syriancivilwar', 'geopolitics', 'CredibleDefense', 'worldnews', 'Syria']
SYRIA_REDDIT_KEYWORDS = [
    'hts', 'hayat tahrir', 'sdf syria', 'sna syria',
    'israel strikes syria', 'isis syria', 'druze suwayda',
    'syria conflict', 'jolani', 'rojava',
]


def fetch_reddit_syria(days=3):
    time_filter = 'day' if days <= 1 else 'week' if days <= 7 else 'month'
    query = ' OR '.join(SYRIA_REDDIT_KEYWORDS[:4])
    posts = []
    for subreddit in SYRIA_SUBREDDITS:
        try:
            time.sleep(2)
            url = f'https://www.reddit.com/r/{subreddit}/search.json'
            params = {'q': query, 'restrict_sr': 'true', 'sort': 'new', 't': time_filter, 'limit': 25}
            resp = requests.get(url, params=params,
                                headers={'User-Agent': REDDIT_USER_AGENT}, timeout=10)
            if resp.status_code != 200:
                continue
            children = resp.json().get('data', {}).get('children', [])
            count = 0
            for post in children:
                pd = post.get('data', {})
                title = pd.get('title', '')
                text_lower = f"{title} {pd.get('selftext','')}".lower()
                if not any(kw in text_lower for kw in SYRIA_REDDIT_KEYWORDS):
                    continue
                posts.append({
                    'title': title[:200],
                    'url': f"https://www.reddit.com{pd.get('permalink','')}",
                    'published': datetime.fromtimestamp(
                        pd.get('created_utc', 0), tz=timezone.utc).isoformat(),
                    'description': pd.get('selftext', '')[:300],
                    'source': f'r/{subreddit}',
                    'weight': 0.8,
                })
                count += 1
            print(f"[Syria Rhetoric/Reddit] r/{subreddit}: {count} posts")
        except Exception as e:
            print(f"[Syria Rhetoric/Reddit] r/{subreddit} error: {e}")
    return posts


# ============================================
# REDIS HELPERS
# ============================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
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
        print(f"[Syria Rhetoric Redis] GET error: {e}")
    return None


def _redis_set(key, value, ttl=RHETORIC_CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str)
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
        print(f"[Syria Rhetoric Redis] SET error: {e}")
    return False


# ============================================
# ARTICLE FETCHING
# ============================================
def fetch_rhetoric_articles(days=3):
    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    for feed_url, weight in RHETORIC_RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item'):
                title = item.findtext('title', '')
                url   = item.findtext('link', '')
                pub   = item.findtext('pubDate', '')
                desc  = item.findtext('description', '')
                try:
                    pub_dt = parsedate_to_datetime(pub)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt < since:
                        continue
                    pub_str = pub_dt.isoformat()
                except Exception:
                    pub_str = pub
                articles.append({
                    'title': title,
                    'url': url,
                    'published': pub_str if isinstance(pub_str, str) else '',
                    'description': desc[:300],
                    'source': feed_url.split('q=')[1].split('&')[0] if 'q=' in feed_url else 'RSS',
                    'weight': weight,
                })
        except Exception as e:
            print(f"[Syria Rhetoric RSS] Error: {e}")

    print(f"[Syria Rhetoric] RSS: {len(articles)} articles")

    if TELEGRAM_AVAILABLE:
        try:
            tg_messages = fetch_telegram_signals_syria(hours_back=days * 24)
            tg_count = 0
            for msg in tg_messages:
                pub = msg.get('published', '')
                try:
                    pub_dt = datetime.fromisoformat(pub)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt < since:
                        continue
                    pub_str = pub_dt.isoformat()
                except Exception:
                    pub_str = pub
                articles.append({
                    'title': msg.get('title', '')[:300],
                    'url': msg.get('url', ''),
                    'published': pub_str if isinstance(pub_str, str) else '',
                    'description': msg.get('title', '')[:300],
                    'source': msg.get('source', 'Telegram'),
                    'weight': 1.1,
                    'views': msg.get('views', 0),
                    'forwards': msg.get('forwards', 0),
                })
                tg_count += 1
            print(f"[Syria Rhetoric] Telegram: {tg_count} messages")
        except Exception as e:
            print(f"[Syria Rhetoric] Telegram error: {e}")

    try:
        reddit_posts = fetch_reddit_syria(days=days)
        articles.extend(reddit_posts)
        print(f"[Syria Rhetoric] Reddit: {len(reddit_posts)} posts")
    except Exception as e:
        print(f"[Syria Rhetoric] Reddit error: {e}")

    # Nitter — executive & primary source accounts (v2.1)
    try:
        nitter_posts = fetch_nitter_syria(days=days)
        articles.extend(nitter_posts)
        print(f"[Syria Rhetoric] Nitter: {len(nitter_posts)} posts")
    except Exception as e:
        print(f"[Syria Rhetoric] Nitter error: {e}")

    seen = set()
    unique = []
    for a in articles:
        u = a.get('url', '')
        if u and u not in seen:
            seen.add(u)
            unique.append(a)

    tg_c  = sum(1 for a in unique if 'Telegram' in str(a.get('source', '')))
    nit_c = sum(1 for a in unique if 'Nitter' in str(a.get('source', '')))
    red_c = sum(1 for a in unique if str(a.get('source', '')).startswith('r/'))
    rss_c = len(unique) - tg_c - nit_c - red_c
    print(f"[Syria Rhetoric] Total unique: {len(unique)} ({rss_c} RSS + {tg_c} TG + {nit_c} Nitter + {red_c} Reddit)")
    return unique


# ============================================
# CLASSIFY ARTICLES (v2.0 — multi-actor + reporting downgrade)
# ============================================
def classify_articles(articles):
    """Classify articles. v2.0: multi-actor matching, reporting downgrade."""

    actor_results = {
        actor_id: {
            'name': info['name'],
            'flag': info['flag'],
            'icon': info['icon'],
            'color': info['color'],
            'role': info['role'],
            'statement_count': 0,
            'factional_score': 0,
            'israeli_strike_score': 0,
            'isis_score': 0,
            'max_level': 0,
            'top_articles': [],
            'escalation_history': [],
            'spokespersons': [],
            'silence_alert': False,
            'specificity_scores': [],
        }
        for actor_id, info in ACTORS.items()
    }

    theatre_summary = {
        'factional_max_level': 0,
        'israeli_strike_max_level': 0,
        'isis_max_level': 0,
        'total_articles': len(articles),
        'coordination_signals': [],
        'druze_signals': [],
        'hezbollah_nexus_signals': [],
        'all_specificity_scores': [],
    }

    for article in articles:
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        pub_date = article.get('published', '')

        # Druze signal detection
        druze_hits = [kw for kw in DRUZE_KEYWORDS if kw in text]
        if druze_hits:
            theatre_summary['druze_signals'].append({
                'message': f"Druze/Suwayda signal: {druze_hits[0]}",
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

        # Hezbollah-Syria nexus signal
        hezbollah_hits = [kw for kw in HEZBOLLAH_SYRIA_NEXUS if kw in text]
        if hezbollah_hits:
            theatre_summary['hezbollah_nexus_signals'].append({
                'message': f"Hezbollah arms/Syria nexus: {hezbollah_hits[0]}",
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

        # Specificity score
        spec_score, _ = _score_specificity(text)
        if spec_score > 0:
            theatre_summary['all_specificity_scores'].append(spec_score)

        # Reporting language check
        is_reporting_context = any(phrase in text for phrase in REPORTING_LANGUAGE)

        # Multi-actor matching (v2.0 — all matched actors, not just first)
        matched_actors = []
        for actor_id in ACTORS:
            for kw in ACTOR_KEYWORDS.get(actor_id, []):
                if kw.lower() in text:
                    matched_actors.append(actor_id)
                    break

        if not matched_actors:
            continue

        for actor_id in matched_actors:
            ar = actor_results[actor_id]
            ar['statement_count'] += 1

            if spec_score > 0:
                ar['specificity_scores'].append(spec_score)

            # Spokesperson detection
            actor_info = ACTORS.get(actor_id, {})
            for sp in actor_info.get('spokespersons', []):
                if sp.lower() in text and sp not in ar['spokespersons']:
                    ar['spokespersons'].append(sp)

            # Score vectors with reporting downgrade
            for level in range(5, 0, -1):

                # Factional
                for kw in FACTIONAL_TRIGGERS.get(level, []):
                    if kw in text:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > ar['factional_score']:
                            ar['factional_score'] = effective_level
                            ar['escalation_history'].append({
                                'timestamp': pub_date if isinstance(pub_date, str) else '',
                                'level': effective_level,
                                'vector': 'factional',
                                'phrase': kw,
                            })
                        if level > theatre_summary['factional_max_level']:
                            theatre_summary['factional_max_level'] = level
                        break

                # Israeli strikes
                for kw in ISRAELI_STRIKE_TRIGGERS.get(level, []):
                    if kw in text:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > ar['israeli_strike_score']:
                            ar['israeli_strike_score'] = effective_level
                        if level > theatre_summary['israeli_strike_max_level']:
                            theatre_summary['israeli_strike_max_level'] = level
                        break

                # ISIS
                for kw in ISIS_RESURGENCE_TRIGGERS.get(level, []):
                    if kw in text:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > ar['isis_score']:
                            ar['isis_score'] = effective_level
                        if level > theatre_summary['isis_max_level']:
                            theatre_summary['isis_max_level'] = level
                        break

            # Top articles
            max_level = max(ar['factional_score'], ar['israeli_strike_score'], ar['isis_score'])
            if len(ar['top_articles']) < 5 or max_level >= 3:
                ar['top_articles'].append({
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', 'Unknown'),
                    'published': pub_date if isinstance(pub_date, str) else '',
                    'factional_level': ar['factional_score'],
                    'israeli_strike_level': ar['israeli_strike_score'],
                    'isis_level': ar['isis_score'],
                    'specificity_score': spec_score,
                })

        # Coordination signals
        # HTS + SNA coordinated against SDF
        if 'hts' in matched_actors and 'sna' in matched_actors:
            theatre_summary['coordination_signals'].append({
                'type': 'coordination',
                'message': 'HTS-SNA coordination signal — joint pressure on SDF',
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

        # Iran proxies + ISIS co-occurrence
        if 'iran_proxies' in matched_actors and 'isis' in matched_actors:
            theatre_summary['coordination_signals'].append({
                'type': 'warning',
                'message': 'Iran proxy + ISIS co-occurrence — contested Deir ez-Zor',
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

        # Israel + Hezbollah nexus signal
        if 'israel' in matched_actors and hezbollah_hits:
            theatre_summary['coordination_signals'].append({
                'type': 'nexus',
                'message': 'Israel-Hezbollah arms interdiction signal in Syria',
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

    # Per-actor finalization
    for actor_id, ar in actor_results.items():
        ar['max_level'] = max(ar['factional_score'], ar['israeli_strike_score'], ar['isis_score'])
        ar['escalation_level'] = ar['max_level']
        ar['escalation_label'] = ESCALATION_LEVELS.get(ar['max_level'], {}).get('label', 'Baseline')
        ar['escalation_color'] = ESCALATION_LEVELS.get(ar['max_level'], {}).get('color', '#6b7280')

        # Static silence detection (Redis-backed in subsequent scans)
        actor_info = ACTORS[actor_id]
        baseline = actor_info.get('baseline_statements_per_week', 3)
        expected = baseline * (3 / 7.0)
        ar['silence_alert'] = ar['statement_count'] == 0 and expected >= 2

        # Actor specificity
        specs = ar.pop('specificity_scores', [])
        ar['specificity_score'] = round(sum(specs) / len(specs), 1) if specs else 0

    return actor_results, theatre_summary


# ============================================
# RHETORIC SCORE
# ============================================
def _calculate_rhetoric_score(actor_results, theatre_summary):
    factional = theatre_summary['factional_max_level']
    strikes   = theatre_summary['israeli_strike_max_level']
    isis      = theatre_summary['isis_max_level']

    raw = (factional * 14) + (strikes * 12) + (isis * 10)
    raw += min(len(theatre_summary['coordination_signals']) * 3, 12)
    raw += min(len(theatre_summary['druze_signals']) * 2, 8)
    raw += min(len(theatre_summary['hezbollah_nexus_signals']) * 2, 6)

    if actor_results.get('hts', {}).get('silence_alert'):
        raw += 5  # HTS silence = warning signal

    return min(raw, 100)


# ============================================
# MAIN SCAN (v2.0)
# ============================================
def run_syria_rhetoric_scan(days=3):
    """Full Syria rhetoric scan. v2.0: delta, specificity, baselines, cross-theater."""
    print(f"[Syria Rhetoric Scan] Starting v2.0 scan ({days}-day window)...")
    start = datetime.now(timezone.utc)

    articles = fetch_rhetoric_articles(days)
    actor_results, theatre_summary = classify_articles(articles)

    max_factional = theatre_summary['factional_max_level']
    max_strikes   = theatre_summary['israeli_strike_max_level']
    max_isis      = theatre_summary['isis_max_level']
    max_level     = max(max_factional, max_strikes, max_isis)

    rhetoric_score = _calculate_rhetoric_score(actor_results, theatre_summary)

    # Theatre specificity
    all_specs = theatre_summary.get('all_specificity_scores', [])
    theatre_specificity = round(sum(all_specs) / len(all_specs), 1) if all_specs else 0

    scan_time = round((datetime.now(timezone.utc) - start).total_seconds(), 1)

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'scanned_at': datetime.now(timezone.utc).isoformat(),
        'days_analyzed': days,
        'total_articles': len(articles),
        'theatre': 'Syria',
        'theatre_score': rhetoric_score,
        'theatre_level': max_level,
        'theatre_escalation_level': max_level,
        'theatre_escalation_label': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Unknown'),
        'theatre_escalation_color': ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
        'theatre_escalation_description': ESCALATION_LEVELS.get(max_level, {}).get('description', ''),
        # Vectors
        'factional_level': max_factional,
        'factional_label': ESCALATION_LEVELS.get(max_factional, {}).get('label', 'Baseline'),
        'israeli_strike_level': max_strikes,
        'israeli_strike_label': ESCALATION_LEVELS.get(max_strikes, {}).get('label', 'Baseline'),
        'isis_level': max_isis,
        'isis_label': ESCALATION_LEVELS.get(max_isis, {}).get('label', 'Baseline'),
        # v2.0 enriched
        'specificity_score': theatre_specificity,
        'delta': None,
        'silence_anomalies': [],
        'crosstheater_coordination': [],
        'hezbollah_nexus_count': len(theatre_summary['hezbollah_nexus_signals']),
        # Signals
        'actors': actor_results,
        'coordination_signals': theatre_summary['coordination_signals'][:5],
        'druze_signals': theatre_summary['druze_signals'][:5],
        'hezbollah_nexus_signals': theatre_summary['hezbollah_nexus_signals'][:3],
        'scan_time_seconds': scan_time,
        'version': '2.0.0-syria-rhetoric',
    }

    # Save to both keys
    _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(RHETORIC_CACHE_KEY_LEGACY, result)

    # History snapshot
    try:
        snapshot = json.dumps({
            'ts':         datetime.now(timezone.utc).isoformat(),
            'score':      rhetoric_score,
            'level':      max_level,
            'label':      ESCALATION_LEVELS.get(max_level, {}).get('label', 'Unknown'),
            'factional':  max_factional,
            'strikes':    max_strikes,
            'isis':       max_isis,
            'specificity': theatre_specificity,
        })
        if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
            enc = urllib.parse.quote(snapshot, safe='')
            requests.post(
                f"{UPSTASH_REDIS_URL}/lpush/{HISTORY_KEY}/{enc}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            requests.post(
                f"{UPSTASH_REDIS_URL}/ltrim/{HISTORY_KEY}/0/119",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            print(f"[Syria Rhetoric] 📈 History snapshot saved")
    except Exception as e:
        print(f"[Syria Rhetoric] History append error (non-fatal): {e}")

    # Actor baselines + silence anomalies
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # Delta
    result['delta'] = _compute_delta()

    # Cross-theater
    _write_crosstheater_signal(result)
    result['crosstheater_coordination'] = _detect_crosstheater_coordination()

    # -- Turkey swing-state read (Jun 11 2026): Syria is Turkey's LEAD
    # INDICATOR vector -- Turkish escalation language about Syria has
    # historically preceded broader regional ambition. Read in its own lane.
    try:
        _tk = (_redis_get(CROSSTHEATER_KEY) or {}).get('turkey', {})
        result['turkey_syria_escalation'] = _tk.get('syria_escalation', 'normal')
        result['turkey_nato_divergence']  = _tk.get('nato_divergence', 'anchored')
        result['turkey_lebanon_vector']   = _tk.get('lebanon_vector', 'dormant')
    except Exception:
        result['turkey_syria_escalation'] = 'normal'
        result['turkey_nato_divergence']  = 'anchored'
        result['turkey_lebanon_vector']   = 'dormant'

    # Signal interpretation -- So What, Red Lines, Historical Patterns
    if INTERPRETER_AVAILABLE:
        try:
            result['interpretation'] = syria_interpret_signals(result)
            best = result['interpretation']['historical_matches']
            best_pct = best[0]['similarity'] if best else 'none'
            low_sig = result['interpretation']['so_what'].get('low_signal_is_positive', False)
            iran_exp = result['interpretation']['so_what'].get('iran_expelled', False)
            print(f"[Syria Rhetoric] Interpreter: {result['interpretation']['red_lines']['breached_count']} red lines breached, "
                  f"best match: {best_pct}%"
                  f"{' | LOW-SIG-POSITIVE' if low_sig else ''}"
                  f"{' | IRAN-EXPELLED' if iran_exp else ''}")

            # v2.0: emit canonical top_signals[] for ME BLUF + GPI consumption
            if syria_build_top_signals:
                try:
                    result['top_signals'] = syria_build_top_signals(result)
                    print(f"[Syria Rhetoric] Built {len(result['top_signals'])} top_signals for BLUF/GPI")
                except Exception as e:
                    print(f"[Syria Rhetoric] build_top_signals error: {str(e)[:120]}")
                    result['top_signals'] = []
            else:
                result['top_signals'] = []
        except Exception as e:
            print(f"[Syria Rhetoric] Warning: Interpreter error (non-fatal): {e}")
            result['top_signals'] = []
    else:
        result['top_signals'] = []

    # Re-save with enriched fields
    _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(RHETORIC_CACHE_KEY_LEGACY, result)

    print(f"[Syria Rhetoric] ✅ v2.0 complete in {scan_time}s — "
          f"Level: {result['theatre_escalation_label']} ({max_level}) | "
          f"Score: {rhetoric_score}/100 | "
          f"Specificity: {theatre_specificity}/10 | "
          f"Hezbollah nexus signals: {result['hezbollah_nexus_count']}")
    return result


def _bg_rhetoric_scan():
    global _rhetoric_running
    try:
        run_syria_rhetoric_scan()
    except Exception as e:
        print(f"[Syria Rhetoric] Background scan error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


def _start_periodic_scan(interval_hours=12):
    def _loop():
        time.sleep(120)  # Stagger startup -- give backend time to stabilize
        while True:
            try:
                run_syria_rhetoric_scan()
            except Exception as e:
                print(f"[Syria Rhetoric] Periodic scan error: {e}")
            time.sleep(interval_hours * 3600)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[Syria Rhetoric] ✅ Periodic scan thread started ({interval_hours}h cycle)")


# ============================================
# ROUTE REGISTRATION
# ============================================
def register_syria_rhetoric_routes(app):

    _start_periodic_scan(interval_hours=12)

    @app.route('/api/rhetoric/syria', methods=['GET'])
    def syria_rhetoric():
        force = request.args.get('force', 'false').lower() == 'true'
        days  = int(request.args.get('days', 3))
        global _rhetoric_running

        if not force:
            # Try unified key first, fall back to legacy
            cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(RHETORIC_CACHE_KEY_LEGACY)
            if cached and cached.get('timestamp'):
                try:
                    age = (datetime.now(timezone.utc) -
                           datetime.fromisoformat(cached['timestamp'])).total_seconds()
                    if age < RHETORIC_CACHE_TTL:
                        cached['cached'] = True
                        cached['cache_age_minutes'] = round(age / 60, 1)
                        return jsonify(cached)
                except Exception:
                    pass

            with _rhetoric_lock:
                if not _rhetoric_running:
                    _rhetoric_running = True
                    t = threading.Thread(target=_bg_rhetoric_scan, daemon=True)
                    t.start()

            return jsonify({
                'success': True,
                'cached': False,
                'scan_in_progress': True,
                'message': 'Syria rhetoric scan in progress. Refresh in 60 seconds.',
                'theatre': 'Syria',
                'theatre_score': 0,
                'theatre_escalation_level': 0,
                'theatre_escalation_label': 'Scanning...',
                'version': '2.0.0-syria-rhetoric',
            })

        result = run_syria_rhetoric_scan(days=days)
        return jsonify(result)

    @app.route('/api/rhetoric/syria/summary', methods=['GET'])
    def syria_rhetoric_summary():
        """Lightweight summary — v2.0: includes delta, specificity, silence_anomalies."""
        cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(RHETORIC_CACHE_KEY_LEGACY)
        if cached:
            return jsonify({
                'success': True,
                # Core
                'theatre_score':            cached.get('theatre_score', 0),
                'theatre_level':            cached.get('theatre_level', cached.get('theatre_escalation_level', 0)),
                'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
                'theatre_escalation_label': cached.get('theatre_escalation_label', 'Unknown'),
                'theatre_escalation_color': cached.get('theatre_escalation_color', '#6b7280'),
                'theatre_label':            cached.get('theatre_escalation_label', 'Unknown'),
                'theatre_color':            cached.get('theatre_escalation_color', '#6b7280'),
                # Vectors
                'factional_level':      cached.get('factional_level', 0),
                'factional_label':      cached.get('factional_label', 'Baseline'),
                'israeli_strike_level': cached.get('israeli_strike_level', 0),
                'israeli_strike_label': cached.get('israeli_strike_label', 'Baseline'),
                'isis_level':           cached.get('isis_level', 0),
                'isis_label':           cached.get('isis_label', 'Baseline'),
                # v2.0
                'specificity_score':      cached.get('specificity_score', 0),
                'delta':                  cached.get('delta'),
                'silence_anomalies':      cached.get('silence_anomalies', []),
                'druze_signals_count':    len(cached.get('druze_signals', [])),
                'hezbollah_nexus_count':  cached.get('hezbollah_nexus_count', 0),
                'total_articles':         cached.get('total_articles', 0),
                'timestamp':  cached.get('timestamp'),
                'scanned_at': cached.get('scanned_at', cached.get('timestamp', '')),
                'cached': True,
            })
        return jsonify({
            'success': False,
            'message': 'No cached data yet — scan in progress',
            'awaiting_scan': True,
        })

    @app.route('/api/rhetoric/syria/history', methods=['GET'])
    def syria_rhetoric_history():
        try:
            limit = int(request.args.get('limit', 120))
            limit = max(1, min(limit, 120))
            entries = []
            if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
                resp = requests.get(
                    f"{UPSTASH_REDIS_URL}/lrange/{HISTORY_KEY}/0/{limit - 1}",
                    headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                    timeout=5
                )
                raw = resp.json().get('result', [])
                for item in raw:
                    try:
                        entries.append(json.loads(item))
                    except Exception:
                        pass
            entries.reverse()
            return jsonify({
                'success': True,
                'theatre': 'Syria',
                'history_key': HISTORY_KEY,
                'count': len(entries),
                'entries': entries,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    print("[Syria Rhetoric] ✅ v2.0 routes registered: "
          "/api/rhetoric/syria, /api/rhetoric/syria/summary, /api/rhetoric/syria/history")
