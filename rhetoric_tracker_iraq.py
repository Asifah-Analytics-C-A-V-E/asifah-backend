"""
Iraq Rhetoric Tracker — Asifah Analytics
v2.0.0 — March 2026

Upgraded to Yemen/Lebanon gold standard:
  - Delta calculation vs prior scan history
  - Specificity scoring (0-10)
  - Actor baselines (Redis EMA)
  - Silence anomaly detection (Redis-backed)
  - Cross-theater coordination fingerprints (shared key with Yemen/Lebanon/Syria)
  - Reporting actor downgrade (iraqi_gov, us_centcom capped when reporting context detected)

Actors monitored:
- PMF / Hashd al-Shaabi — Iran-directed Shi'a militia umbrella
- Kata'ib Hezbollah — most lethal PMF faction, anti-US operations
- Muqtada al-Sadr — political wildcard, Saraya al-Salam militia
- KRG / Peshmerga — Kurdish autonomous region, Kirkuk tensions
- Iran (re: Iraq) — IRGC Quds Force, direct strikes on US facilities
- US Forces / CENTCOM — force protection posture, base strike responses
- Iraqi Government (ISF) — Baghdad's balancing act
- ISIS Resurgence — Anbar/Diyala desert pockets

Five threat vectors:
1. PMF MOBILIZATION — militia rhetoric, mobilization orders, anti-US statements
2. IRAN DIRECT STRIKES — ballistic missiles/drones vs Embassy Baghdad, Consulate Erbil
3. US BASE STRIKES — drone/rocket attacks on Al Asad, Ain al-Asad, Erbil airbase
4. KURDISH TENSIONS — Kirkuk standoffs, Peshmerga-PMF friction, PKK/Turkey spillover
5. ISIS RESURGENCE — Anbar/Diyala sleeper cells exploiting security vacuum

CHANGELOG:
  v2.0.0 (2026-03-21):
    - Delta, specificity, baselines, silence anomalies, cross-theater
    - Reporting actor downgrade (iraqi_gov, us_centcom)
    - Unified Redis key pattern (rhetoric:iraq:latest)
    - Summary endpoint upgraded with v2.0 fields
  v1.0.0 (2026-03):
    - Initial Iraq rhetoric tracker

Registers on ME backend (asifah-backend.onrender.com)
Endpoints: GET /api/rhetoric/iraq
           GET /api/rhetoric/iraq/summary
           GET /api/rhetoric/iraq/history
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
    from telegram_signals import fetch_telegram_signals_iraq
    TELEGRAM_AVAILABLE = True
    print("[Iraq Rhetoric] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Iraq Rhetoric] ⚠️ Telegram signals not available — RSS only")

try:
    from rss_monitor import fetch_iraq_rss
    RSS_MONITOR_AVAILABLE = True
    print("[Iraq Rhetoric] ✅ RSS monitor available")
except ImportError:
    RSS_MONITOR_AVAILABLE = False
    print("[Iraq Rhetoric] ⚠️ RSS monitor not available")

RHETORIC_CACHE_KEY  = 'rhetoric:iraq:latest'       # v2.0 unified key
RHETORIC_CACHE_KEY_LEGACY = 'iraq_rhetoric_cache'  # keep writing for backward compat
HISTORY_KEY         = 'rhetoric:iraq:history'
BASELINE_KEY        = 'rhetoric_baseline:iraq'
CROSSTHEATER_KEY    = 'rhetoric:crosstheater:fingerprints'  # shared with Yemen/Lebanon/Syria

RHETORIC_CACHE_TTL  = 13 * 3600  # 13h -- covers scan cycle + buffer

# Signal interpreter
try:
    from iraq_signal_interpreter import interpret_signals as iraq_interpret_signals
    INTERPRETER_AVAILABLE = True
    print("[Iraq Rhetoric] Signal interpreter loaded")
except ImportError:
    INTERPRETER_AVAILABLE = False
    print("[Iraq Rhetoric] Warning: Signal interpreter not available")
SCAN_INTERVAL_HOURS = 6

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ESCALATION LEVELS
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Baseline',      'color': '#6b7280', 'description': 'No significant signals'},
    1: {'label': 'Rhetoric',      'color': '#3b82f6', 'description': 'Standard factional statements'},
    2: {'label': 'Tension',       'color': '#f59e0b', 'description': 'Warnings, mobilization language'},
    3: {'label': 'Confrontation', 'color': '#f97316', 'description': 'Direct threats, troop movements'},
    4: {'label': 'Incident',      'color': '#ef4444', 'description': 'Attacks confirmed, strikes reported'},
    5: {'label': 'Active Conflict','color': '#dc2626', 'description': 'Ongoing operations, multiple fronts'},
}


# ============================================
# ACTORS
# ============================================
ACTORS = {
    'pmf_hashd': {
        'name': 'PMF / Hashd al-Shaabi',
        'flag': '🇮🇶',
        'icon': '⚔️',
        'color': '#dc2626',
        'role': 'Iran-Directed Shi\'a Militia Umbrella',
        'description': 'Popular Mobilization Forces — umbrella of 60+ Shi\'a militias, IRGC-directed',
        'spokespersons': [
            'faleh al-fayyadh', 'hadi al-amiri', 'abu mahdi al-muhandis legacy',
            'hashd al-shaabi', 'pmf spokesperson', 'islamic resistance in iraq',
            'المقاومة الإسلامية في العراق', 'هيئة الحشد الشعبي',
            'فالح الفياض', 'هادي العامري',
        ],
        'keywords': [
            'pmf', 'hashd', 'hashd al-shaabi', 'popular mobilization',
            'islamic resistance in iraq', 'iraqi resistance factions',
            'iran-backed militia', 'iran-backed iraqi', 'iraqi militia',
            'resistance factions iraq', 'factions iraq', 'iraqi factions',
            'we will not allow', 'will target', 'will respond',
            'المقاومة الإسلامية في العراق', 'الحشد الشعبي', 'فصائل مسلحة',
            'فصائل عراقية', 'المقاومة العراقية',
        ],
        'baseline_statements_per_week': 15,
    },
    'kataib': {
        'name': 'Kata\'ib Hezbollah',
        'flag': '☪️',
        'icon': '🎯',
        'color': '#b91c1c',
        'role': 'PMF\'s Most Lethal Anti-US Faction',
        'description': 'IRGC-Quds Force direct proxy — responsible for Tower 22 and multiple US base attacks',
        'spokespersons': [
            'kataib hezbollah', 'kata\'ib hezbollah', 'abu hussein al-hamidawi',
            'kataib hezbollah media', 'kataib spokesman',
            'كتائب حزب الله', 'أبو حسين الحمداوي',
        ],
        'keywords': [
            'kataib hezbollah', 'kata\'ib hezbollah', 'kata\'ib',
            'kataib', 'hezbollah iraq', 'iraq hezbollah',
            'كتائب حزب الله', 'كتائب',
            'tower 22', 'drone attack us base', 'attacked us forces',
            'operation true promise iraq', 'islamic resistance response',
        ],
        'baseline_statements_per_week': 8,
    },
    'sadr': {
        'name': 'Muqtada al-Sadr',
        'flag': '🕌',
        'icon': '👁️',
        'color': '#7c3aed',
        'role': 'Political Wildcard / Saraya al-Salam',
        'description': 'Populist Shi\'a cleric — commands Saraya al-Salam militia, unpredictable swing factor',
        'spokespersons': [
            'muqtada al-sadr', 'sadr', 'sadr office', 'sadrist movement',
            'saraya al-salam', 'mahdi army', 'sadr city statement',
            'مقتدى الصدر', 'التيار الصدري', 'سرايا السلام',
        ],
        'keywords': [
            'muqtada', 'al-sadr', 'sadr', 'sadrist', 'saraya al-salam',
            'mahdi army', 'sadr city', 'sadr statement', 'sadr warns',
            'sadr condemns', 'sadr calls', 'sadr movement',
            'مقتدى الصدر', 'الصدر', 'التيار الصدري', 'سرايا السلام',
            'المهدي', 'الصدريون',
        ],
        'baseline_statements_per_week': 5,
    },
    'krg': {
        'name': 'KRG / Peshmerga',
        'flag': '🏔️',
        'icon': '⚙️',
        'color': '#f59e0b',
        'role': 'Kurdish Autonomous Region',
        'description': 'Kurdistan Regional Government — controls Erbil, Sulaymaniyah; Peshmerga forces; Kirkuk dispute',
        'spokespersons': [
            'masrour barzani', 'nechirvan barzani', 'krg spokesperson',
            'peshmerga command', 'kurdistan regional government',
            'masoud barzani', 'pdk', 'puk',
            'مسرور بارزاني', 'نيجيرفان بارزاني', 'البيشمركة',
            'حكومة إقليم كردستان',
        ],
        'keywords': [
            'krg', 'peshmerga', 'kurdistan regional government',
            'erbil', 'sulaymaniyah', 'duhok', 'barzani',
            'kurdish forces iraq', 'kurdish autonomous', 'kurdistan iraq',
            'kirkuk disputed', 'oil fields kirkuk', 'pkk iraq',
            'turkey strikes kurdistan', 'pdk', 'puk',
            'البيشمركة', 'إقليم كردستان', 'أربيل', 'السليمانية',
            'كركوك', 'البرزاني', 'حزب العمال الكردستاني',
        ],
        'baseline_statements_per_week': 7,
    },
    'iran_iraq': {
        'name': 'Iran (re: Iraq)',
        'flag': '🇮🇷',
        'icon': '🔱',
        'color': '#16a34a',
        'role': 'IRGC / Direct Strike Actor',
        'description': 'Iran directing PMF + conducting direct ballistic missile/drone strikes on US Embassy Baghdad, Consulate Erbil',
        'spokespersons': [
            'irgc', 'quds force', 'iranian foreign ministry',
            'khamenei iraq', 'iran foreign ministry iraq',
            'سپاه پاسداران', 'نیروی قدس', 'وزارت خارجه ایران',
            'خامنه‌ای', 'حرس الثوري', 'فيلق القدس',
        ],
        'keywords': [
            'iran iraq', 'irgc iraq', 'quds force iraq',
            'iranian backed iraq', 'iran militia iraq',
            'iran strikes iraq', 'iran missile iraq',
            'iran drone iraq', 'iranian attack iraq',
            'tehran iraq', 'iran warns iraq', 'iran threatens iraq',
            'missile baghdad', 'missile erbil', 'drone baghdad',
            'drone erbil', 'attack embassy', 'attack consulate',
            'strikes us embassy', 'hits us embassy', 'embassy attack',
            'consulate attack', 'ballistic missile iraq',
            'إيران العراق', 'الحرس الثوري العراق', 'فيلق القدس',
            'صاروخ بغداد', 'صاروخ أربيل', 'هجوم السفارة',
            'هجوم القنصلية',
        ],
        'baseline_statements_per_week': 10,
    },
    'us_centcom': {
        'name': 'US Forces / CENTCOM',
        'flag': '🇺🇸',
        'icon': '🛡️',
        'color': '#3b82f6',
        'role': 'Force Protection / Counterstrikes',
        'description': 'US forces at Al Asad, Ain al-Asad, Erbil base, Baghdad — responding to Iran/PMF attacks',
        'spokespersons': [
            'centcom', 'pentagon iraq', 'us military iraq',
            'department of defense iraq', 'us forces iraq',
            'us embassy baghdad', 'state department iraq',
            'us consul erbil',
        ],
        'keywords': [
            'centcom iraq', 'us forces iraq', 'us military iraq',
            'us troops iraq', 'american forces iraq',
            'al asad airbase', 'ain al-asad', 'us base iraq',
            'us embassy baghdad', 'us consulate erbil',
            'american embassy', 'american consulate',
            'us strike iraq', 'us retaliation iraq',
            'force protection iraq', 'us jets iraq',
            'operation inherent resolve', 'us airstrike',
            'pentagon iraq', 'department of defense',
            'القوات الأمريكية', 'السفارة الأمريكية', 'القنصلية الأمريكية',
            'القاعدة الأمريكية', 'عين الأسد', 'الأسد الجوي',
        ],
        'baseline_statements_per_week': 8,
    },
    'iraqi_gov': {
        'name': 'Iraqi Government (ISF)',
        'flag': '🏛️',
        'icon': '⚖️',
        'color': '#0ea5e9',
        'role': 'Baghdad\'s Balancing Act',
        'description': 'Shi\'a-led government navigating between Iran pressure and US partnership — ISF forces',
        'spokespersons': [
            'mohammed shia al-sudani', 'al-sudani', 'sudani',
            'iraqi government', 'iraqi prime minister',
            'iraqi foreign ministry', 'isf', 'iraqi security forces',
            'محمد شياع السوداني', 'السوداني', 'الحكومة العراقية',
            'وزارة الخارجية العراقية',
        ],
        'keywords': [
            'al-sudani', 'sudani', 'iraqi prime minister',
            'iraqi government', 'baghdad government',
            'iraqi security forces', 'isf', 'iraqi army',
            'iraq condemns', 'iraq demands', 'iraq protests',
            'iraq sovereignty', 'iraqi sovereignty',
            'iraq foreign ministry', 'iraq warns',
            'السوداني', 'الحكومة العراقية', 'القوات الأمنية العراقية',
            'الجيش العراقي', 'السيادة العراقية', 'الخارجية العراقية',
        ],
        'baseline_statements_per_week': 8,
    },
    'isis_iraq': {
        'name': 'ISIS Resurgence',
        'flag': '☠️',
        'icon': '💀',
        'color': '#374151',
        'role': 'Insurgent Threat / Security Vacuum',
        'description': 'ISIS exploiting security vacuum during Iran-US war — Anbar, Diyala, Kirkuk desert pockets',
        'spokespersons': [
            'amaq', 'islamic state iraq', 'isis claim',
            'isis statement', 'amaq news agency',
        ],
        'keywords': [
            'isis iraq', 'islamic state iraq', 'isil iraq', 'daesh iraq',
            'isis attack iraq', 'isis ambush', 'isis ied',
            'isis sleeper cell', 'isis resurgence iraq',
            'anbar isis', 'diyala isis', 'kirkuk isis',
            'nineveh isis', 'isis desert', 'isis insurgency',
            'anti-isis operation', 'counter-isis iraq',
            'داعش العراق', 'تنظيم الدولة العراق', 'عمليات ضد داعش',
            'خلايا نائمة', 'الأنبار داعش', 'ديالى داعش',
        ],
        'baseline_statements_per_week': 3,
    },
}


# ============================================
# REPORTING ACTOR DOWNGRADE (v2.0)
# ============================================
# Actors that primarily REPORT ON or COMMENT ON events rather than threaten.
# They can still reach high levels with their own genuine threatening language,
# but will be capped at level 2 if reporting/condemning context is detected.
REPORTING_ACTORS = {'iraqi_gov', 'us_centcom'}

REPORTING_LANGUAGE = [
    # English — condemning/mourning/calling on others
    'condemns', 'condemned', 'denounces', 'denounced',
    'rejects the attack', 'protests the',
    'mourns', 'mourning', 'mourned', 'condolences',
    'victims of', 'casualties in', 'killed in the attack',
    'civilian casualties', 'civilian deaths',
    'calls on', 'calls for', 'urges', 'urged',
    'demands ceasefire', 'demands halt', 'demands end to',
    'international community must', 'must stop the',
    'calls for investigation', 'calls for restraint',
    'in response to the attack', 'following the attack',
    'after the strike', 'following the strike',
    'in the wake of', 'following the bombardment',
    'expressed concern', 'deeply concerned about',
    'expresses condemnation', 'condemns the attack',
    'iraq condemns', 'condemns iranian', 'condemns militia',
    'pentagon confirms', 'centcom confirms', 'centcom reports',
    'us confirms', 'department of defense confirms',
    'according to centcom', 'centcom statement',
    # Arabic
    'يستنكر', 'استنكر', 'يدين', 'أدان',
    'يطالب بوقف', 'يعزي', 'ضحايا الهجوم',
    'في أعقاب', 'إثر الهجوم', 'بعد الضربة',
    'يطالب بالتحقيق',
]


# ============================================
# THREAT VECTORS
# ============================================

# VECTOR 1: PMF MOBILIZATION
PMF_MOBILIZATION_TRIGGERS = {
    5: [
        'full mobilization', 'general mobilization', 'all factions mobilize',
        'open war on americans', 'expel all american forces',
        'resistance ready for full escalation', 'we declare war',
        'بدء التعبئة العامة', 'التصعيد الشامل',
    ],
    4: [
        'mobilize forces', 'mobilization order', 'all factions on alert',
        'resistance factions mobilize', 'ready to strike',
        'put on combat footing', 'units deployed forward',
        'تعبئة الفصائل', 'الفصائل تستعد', 'نصب كمائن',
    ],
    3: [
        'we will respond', 'will not go unanswered', 'we will retaliate',
        'red line crossed', 'patience is running out',
        'resistance will act', 'attack imminent',
        'سنرد', 'لن يمر دون رد', 'الخط الأحمر',
    ],
    2: [
        'condemn us aggression', 'demand withdrawal',
        'resistance factions warn', 'pmf warns',
        'hashd warns', 'we reserve the right',
        'نطالب بالانسحاب', 'نحتفظ بحق الرد',
    ],
    1: [
        'pmf', 'hashd', 'islamic resistance', 'resistance factions',
        'popular mobilization', 'kataib', 'asaib',
        'الحشد الشعبي', 'المقاومة الإسلامية', 'فصائل مسلحة',
    ],
}

# VECTOR 2: IRAN DIRECT STRIKES
IRAN_STRIKE_TRIGGERS = {
    5: [
        'embassy destroyed', 'consulate destroyed', 'direct hit embassy',
        'direct hit consulate', 'massive missile strike baghdad',
        'ballistic missile embassy', 'total destruction',
        'تدمير السفارة', 'صاروخ باليستي على السفارة',
    ],
    4: [
        'missile hits embassy', 'drone hits embassy', 'strikes embassy',
        'missile hits consulate', 'drone hits consulate',
        'attack on us embassy', 'attack on us consulate',
        'us diplomatic compound struck', 'iran fires at embassy',
        'ضربة السفارة الأمريكية', 'هجوم القنصلية', 'يستهدف السفارة',
    ],
    3: [
        'rockets near embassy', 'explosion near embassy',
        'near consulate erbil', 'close to us diplomatic',
        'iran threatens embassy', 'iran warns embassy',
        'التحذير من ضرب السفارة', 'قصف قرب السفارة',
    ],
    2: [
        'iran missile iraq', 'iran drone iraq', 'iran strikes iraq',
        'ballistic missile iraq', 'iran attack iraq',
        'صاروخ إيراني', 'طائرة مسيّرة إيرانية', 'ضربة إيرانية على العراق',
    ],
    1: [
        'iran iraq', 'iranian attack', 'irgc iraq', 'quds force iraq',
        'إيران العراق', 'الحرس الثوري', 'فيلق القدس',
    ],
}

# VECTOR 3: US BASE STRIKES
US_BASE_STRIKE_TRIGGERS = {
    5: [
        'overrun us base', 'us base destroyed', 'mass casualty us forces',
        'multiple bases hit simultaneously', 'coordinated attack all bases',
    ],
    4: [
        'rockets hit al asad', 'drone hits al asad', 'strike ain al-asad',
        'attack us base iraq', 'us soldiers killed iraq',
        'us base under attack', 'us forces casualties iraq',
        'erbil airbase attack', 'baghdad airport attack',
        'ضرب قاعدة عين الأسد', 'هجوم على القاعدة الأمريكية',
    ],
    3: [
        'rockets fired at base', 'drones intercepted us base',
        'attempted attack us base', 'rockets land near base',
        'mortar us base', 'us base targeted',
        'استهداف القاعدة', 'قذائف على القاعدة',
    ],
    2: [
        'drone attack iraq', 'rocket attack iraq', 'us forces targeted',
        'militia attack us', 'irgc drone iraq',
        'هجوم بطائرة مسيّرة', 'صواريخ تستهدف',
    ],
    1: [
        'al asad', 'ain al-asad', 'us base iraq', 'us troops iraq',
        'erbil base', 'operation inherent resolve',
        'عين الأسد', 'قاعدة أمريكية', 'القوات الأمريكية',
    ],
}

# VECTOR 4: KURDISH TENSIONS
KURDISH_TENSION_TRIGGERS = {
    5: [
        'peshmerga pmf clash', 'kurdish forces under attack',
        'erbil bombed', 'krg declares emergency',
        'full kirkuk offensive',
    ],
    4: [
        'peshmerga mobilize', 'pmf advances on kirkuk',
        'armed confrontation kirkuk', 'krg forces on alert',
        'turkey strikes peshmerga', 'pkk attack erbil',
        'تقدم الحشد نحو كركوك', 'مواجهة مسلحة كركوك',
    ],
    3: [
        'kirkuk standoff', 'peshmerga pmf standoff',
        'disputed territory standoff', 'krg warns pmf',
        'turkey threatens', 'pkk attack iraq',
        'توتر كركوك', 'مواجهة البيشمركة والحشد',
    ],
    2: [
        'kirkuk tensions', 'disputed territories iraq',
        'peshmerga warning', 'krg protests', 'barzani warns',
        'turkey pkk iraq', 'pkk iraq',
        'توترات كركوك', 'الأراضي المتنازع عليها',
    ],
    1: [
        'kirkuk', 'peshmerga', 'krg', 'kurdish iraq',
        'erbil', 'sulaymaniyah', 'barzani',
        'كركوك', 'البيشمركة', 'إقليم كردستان', 'أربيل',
    ],
}

# VECTOR 5: ISIS RESURGENCE
ISIS_RESURGENCE_TRIGGERS = {
    5: [
        'isis controls territory', 'isis seizes town',
        'isis major offensive iraq', 'isis caliphate re-established',
    ],
    4: [
        'isis mass casualty attack', 'isis kills soldiers',
        'isis overruns checkpoint', 'large isis attack',
        'isis coordinated attack', 'isis complex attack',
        'داعش يستولي', 'هجوم كبير لداعش',
    ],
    3: [
        'isis ambush iraq', 'isis ied iraq', 'isis attack',
        'isis fighters iraq', 'isis operation iraq',
        'isis sleeper cell activated', 'anti-isis operation launched',
        'كمين داعش', 'عبوة داعش', 'عملية ضد داعش',
    ],
    2: [
        'isis activity iraq', 'isis presence iraq',
        'isis threat iraq', 'counter-isis', 'isis movement',
        'نشاط داعش', 'تهديد داعش', 'مكافحة الإرهاب',
    ],
    1: [
        'isis iraq', 'daesh iraq', 'islamic state iraq', 'isil iraq',
        'anbar', 'diyala', 'nineveh insurgency',
        'داعش', 'تنظيم الدولة', 'الأنبار', 'ديالى',
    ],
}


# ============================================
# ACTOR KEYWORD MAPPING
# ============================================
ACTOR_KEYWORDS = {
    'pmf_hashd':  ['pmf', 'hashd', 'popular mobilization', 'islamic resistance iraq',
                   'resistance factions', 'الحشد الشعبي', 'المقاومة الإسلامية في العراق'],
    'kataib':     ['kataib', 'kata\'ib', 'hezbollah iraq', 'كتائب حزب الله'],
    'sadr':       ['sadr', 'muqtada', 'sadrist', 'saraya al-salam',
                   'الصدر', 'مقتدى', 'سرايا السلام'],
    'krg':        ['peshmerga', 'krg', 'barzani', 'erbil', 'kirkuk', 'sulaymaniyah',
                   'البيشمركة', 'كردستان العراق', 'البرزاني'],
    'iran_iraq':  ['iran iraq', 'irgc iraq', 'quds force iraq', 'iranian',
                   'ballistic missile iraq', 'drone baghdad', 'embassy attack',
                   'consulate attack', 'إيران العراق', 'الحرس الثوري'],
    'us_centcom': ['centcom', 'us forces iraq', 'us military iraq', 'us base',
                   'al asad', 'ain al-asad', 'us embassy baghdad', 'us consulate erbil',
                   'القوات الأمريكية', 'السفارة الأمريكية'],
    'iraqi_gov':  ['al-sudani', 'iraqi government', 'iraqi prime minister',
                   'iraqi army', 'iraqi security forces',
                   'السوداني', 'الحكومة العراقية', 'الجيش العراقي'],
    'isis_iraq':  ['isis iraq', 'daesh iraq', 'islamic state iraq', 'amaq',
                   'داعش العراق', 'تنظيم الدولة'],
}

COORDINATION_PAIRS = [
    ('pmf_hashd', 'iran_iraq',  'Iran + PMF coordinated escalation — proxy axis activation'),
    ('pmf_hashd', 'kataib',     'PMF + Kata\'ib joint mobilization — most dangerous combination'),
    ('kataib',    'iran_iraq',  'Kata\'ib + Iran coordinated — direct IRGC Quds Force direction'),
    ('sadr',      'pmf_hashd',  'Sadr + PMF alignment — mass street pressure + armed militia'),
    ('iraqi_gov', 'us_centcom', 'Iraqi Government + US coordination — sovereignty response'),
    ('krg',       'us_centcom', 'KRG + US coordination — northern front consolidation'),
]

SILENCE_BASELINE = {
    'pmf_hashd':  3,
    'kataib':     2,
    'sadr':       1,
    'krg':        2,
    'iran_iraq':  2,
    'us_centcom': 2,
    'iraqi_gov':  2,
    'isis_iraq':  1,
}


# ============================================
# SPECIFICITY SCORER (v2.0)
# ============================================
SPECIFIC_GEOGRAPHIES_IRAQ = [
    # Iraqi cities / bases
    'baghdad', 'erbil', 'basra', 'mosul', 'kirkuk', 'fallujah', 'ramadi',
    'tikrit', 'najaf', 'karbala', 'samarra', 'sulaymaniyah',
    'al asad airbase', 'ain al-asad', 'baghdad airport', 'victoria base',
    'us embassy baghdad', 'us consulate erbil',
    # Regions
    'anbar province', 'diyala province', 'nineveh plains',
    'sinjar', 'tuz khurmato', 'disputed territories',
    # Borders
    'iran iraq border', 'syria iraq border', 'al qaim', 'al tanf',
]

SPECIFIC_ASSETS_IRAQ = [
    'ballistic missile', 'cruise missile', 'shahab missile',
    'shahed drone', 'suicide drone', 'kamikaze drone',
    'grad rocket', 'katyusha', '107mm rocket',
    'c-ram', 'counter-rocket', 'patriot battery',
    'f-35 iraq', 'b-52 iraq', 'ac-130',
    'peshmerga brigade', 'golden division', 'cts iraq',
    'pmf brigade', 'kataib unit',
]

TIME_BOUNDED_IRAQ = [
    'within 24 hours', 'within 48 hours', 'within 72 hours',
    'by tomorrow', 'before the end of', 'in the coming hours',
    'imminent', 'within days', 'tonight', 'this week',
    'before friday', 'deadline', 'ultimatum expires',
]

OPERATIONAL_FRAMING_IRAQ = [
    'preparing to launch', 'positioned to strike', 'ready to fire',
    'forces deployed', 'troops massing', 'coordinated attack',
    'multi-front', 'simultaneous strike', 'saturation attack',
    'operational order issued', 'combat footing',
    'all factions on alert', 'full combat readiness',
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
    for geo in SPECIFIC_GEOGRAPHIES_IRAQ:
        if geo in text:
            breakdown['named_geographies'].append(geo)
            score += 1
    for asset in SPECIFIC_ASSETS_IRAQ:
        if asset in text:
            breakdown['named_assets'].append(asset)
            score += 1
    for tb in TIME_BOUNDED_IRAQ:
        if tb in text:
            breakdown['time_bounded'].append(tb)
            score += 2
    for op in OPERATIONAL_FRAMING_IRAQ:
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
        print(f"[Iraq Rhetoric] Delta compute error: {e}")
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
            current_level = ar.get('max_level', ar.get('escalation_level', 0))
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
        print(f"[Iraq Rhetoric] ✅ Actor baselines updated")
        return updated
    except Exception as e:
        print(f"[Iraq Rhetoric] Baseline update error: {e}")
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
                    'signal': 'Unusual quiet — possible operational security or patron direction',
                })
                print(f"[Iraq Rhetoric] 🔇 Silence anomaly: {actor_id} ({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Iraq Rhetoric] Silence detection error: {e}")
    return anomalies


# ============================================
# CROSS-THEATER COORDINATION (v2.0)
# ============================================
def _write_crosstheater_signal(result):
    """Write Iraq fingerprint to shared cross-theater Redis key."""
    try:
        existing = _redis_get(CROSSTHEATER_KEY) or {}

        top_phrases = []
        for sig in result.get('coordination_signals', [])[:3]:
            msg = sig.get('message', '')
            if msg:
                top_phrases.append(msg[:60])

        named_targets = []
        actors = result.get('actors', {})
        for actor_id in ['pmf_hashd', 'kataib', 'iran_iraq']:
            for art in actors.get(actor_id, {}).get('top_articles', [])[:3]:
                title_lower = art.get('title', '').lower()
                for geo in SPECIFIC_GEOGRAPHIES_IRAQ:
                    if geo in title_lower and geo not in named_targets:
                        named_targets.append(geo)

        existing['iraq'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Iraq',
            'level': result.get('theatre_escalation_level', 0),
            'score': result.get('theatre_score', 0),
            'theatre_score': result.get('theatre_score', 0),
            'pmf_level': result.get('pmf_level', 0),
            'iran_strike_level': result.get('iran_strike_level', 0),
            'us_base_level': result.get('us_base_level', 0),
            'top_phrases': top_phrases[:5],
            'named_targets': named_targets[:8],
            'actor_levels': {
                aid: actors.get(aid, {}).get('escalation_level', 0)
                for aid in ['pmf_hashd', 'kataib', 'iran_iraq']
            },
            'specificity_score': result.get('specificity_score', 0),
        }

        _redis_set(CROSSTHEATER_KEY, existing, ttl=8 * 3600)
        print(f"[Iraq Rhetoric] ✅ Cross-theater fingerprint written")
    except Exception as e:
        print(f"[Iraq Rhetoric] Cross-theater write error: {e}")


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

        expected = ['yemen', 'iraq', 'lebanon', 'iran', 'israel']
        missing = [t for t in expected if t not in fresh]
        if missing:
            print(f"[CrossTheater/Iraq] Note: {missing} not yet active")

        # Check 1: Simultaneous elevation
        proxy_theaters = {k: v for k, v in fresh.items() if k in ['yemen', 'iraq', 'lebanon']}
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
        print(f"[Iraq Rhetoric] Cross-theater detection error: {e}")

    return findings


# ============================================
# RSS FEEDS
# ============================================
# ============================================
# NITTER -- Primary source accounts for Iraq
# ============================================
NITTER_MIRRORS = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

NITTER_ACCOUNTS_IRAQ = [
    ("CENTCOM",         1.1, "CENTCOM -- Iraq operations, base attacks, ISIS strikes"),
    ("StateDept",       1.0, "State Dept -- Iraq diplomatic signals, ceasefire"),
    ("realDonaldTrump", 1.1, "Trump -- Iran ceasefire, Iraq policy"),
    ("SecRubio",        1.0, "SecState -- Iraq/Iran diplomatic signals"),
    ("IDF",             0.9, "IDF -- Iraq-Iran corridor signals"),
    ("OSINTdefender",   0.9, "OSINT Defender -- Iraq incidents"),
    ("ElintNews",       0.9, "ELINT News -- Iraq/PMF incidents"),
    ("WarMonitors",     0.85, "War Monitors -- Iraq attack reports"),
    ("MazloumAbdi",     0.85, "SDF commander -- Kurdish Iraq/Syria coordination"),
]


def _fetch_nitter_iraq(username, weight=1.0, timeout=8):
    import xml.etree.ElementTree as _ET
    from email.utils import parsedate_to_datetime as _ptd
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AsifahAnalytics/1.0)"}
    for mirror in NITTER_MIRRORS:
        url = f"https://{mirror}/{username}/rss"
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                continue
            root = _ET.fromstring(resp.content)
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
                        pub = _ptd(pubdate_el.text).isoformat()
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
                print(f"[Iraq Rhetoric/Nitter] @{username}: {len(posts)} posts via {mirror}")
                return posts
        except Exception as e:
            print(f"[Iraq Rhetoric/Nitter] @{username} {mirror} failed: {str(e)[:60]}")
            continue
    print(f"[Iraq Rhetoric/Nitter] @{username}: all mirrors failed")
    return []


def fetch_nitter_iraq(days=3):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen = set()
    for username, weight, desc in NITTER_ACCOUNTS_IRAQ:
        posts = _fetch_nitter_iraq(username, weight=weight)
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
    print(f"[Iraq Rhetoric/Nitter] Total: {len(all_posts)} posts")
    return all_posts


RHETORIC_RSS_FEEDS = [
    ("https://news.google.com/rss/search?q=PMF+Iraq+Iran+militia+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Hashd+al-Shaabi+Iraq&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Kataib+Hezbollah+Iraq&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iraq+US+embassy+Baghdad+attack&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=US+consulate+Erbil+attack+Iran&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iran+missile+drone+Iraq+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=al+Asad+airbase+attack+Iraq&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=CENTCOM+Iraq+strike+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Kirkuk+Peshmerga+PMF+2026&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=KRG+Erbil+security+2026&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://www.rudaw.net/english/feed", 1.0),
    ("https://www.kurdistan24.net/en/rss.xml", 0.95),
    ("https://news.google.com/rss/search?q=ISIS+Iraq+attack+Anbar+Diyala+2026&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Muqtada+al-Sadr+Iraq+2026&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Iraq+war+Iran+2026+militia&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Iraq+security+2026+attack&hl=en&gl=US&ceid=US:en", 0.85),
    # Arabic
    ("https://news.google.com/rss/search?q=الحشد+الشعبي+العراق+2026&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=كتائب+حزب+الله+العراق&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=إيران+العراق+ضربة+2026&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=السفارة+الأمريكية+بغداد+هجوم&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=داعش+العراق+هجوم+2026&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=مقتدى+الصدر+العراق&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=كركوك+البيشمركة+2026&hl=ar&gl=SA&ceid=SA:ar", 0.85),
    # Farsi
    ("https://news.google.com/rss/search?q=سپاه+عراق+عملیات&hl=fa&gl=IR&ceid=IR:fa", 0.95),
    ("https://news.google.com/rss/search?q=ایران+عراق+موشک&hl=fa&gl=IR&ceid=IR:fa", 0.95),
    # Hebrew
    ("https://news.google.com/rss/search?q=עיראק+איראן+מיליציה&hl=iw&gl=IL&ceid=IL:iw", 0.85),
]

REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
IRAQ_SUBREDDITS = ['CredibleDefense', 'geopolitics', 'worldnews', 'iraq', 'IRG']
IRAQ_REDDIT_KEYWORDS = [
    'pmf iraq', 'kataib', 'hashd', 'us embassy baghdad',
    'us consulate erbil', 'iran iraq missile', 'al asad attack',
    'sadr iraq', 'peshmerga kirkuk', 'isis iraq 2026',
]


def fetch_reddit_iraq(days=3):
    time_filter = 'day' if days <= 1 else 'week' if days <= 7 else 'month'
    query = ' OR '.join(IRAQ_REDDIT_KEYWORDS[:4])
    posts = []
    for subreddit in IRAQ_SUBREDDITS:
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
                if not any(kw in text_lower for kw in IRAQ_REDDIT_KEYWORDS):
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
            print(f"[Iraq Rhetoric/Reddit] r/{subreddit}: {count} posts")
        except Exception as e:
            print(f"[Iraq Rhetoric/Reddit] r/{subreddit} error: {e}")
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
        print(f"[Iraq Rhetoric Redis] GET error: {e}")
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
        print(f"[Iraq Rhetoric Redis] SET error: {e}")
    return False


# ============================================
# ARTICLE FETCHING
# ============================================
def fetch_rhetoric_articles(days=3):
    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    for feed_url, weight in RHETORIC_RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
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
            print(f"[Iraq Rhetoric RSS] Error {feed_url[:60]}: {e}")

    print(f"[Iraq Rhetoric] Core RSS: {len(articles)} articles")

    if RSS_MONITOR_AVAILABLE:
        try:
            iraq_rss = fetch_iraq_rss()
            added = 0
            for art in iraq_rss:
                pub = art.get('published', art.get('date', ''))
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
                    'title': art.get('title', '')[:300],
                    'url': art.get('url', art.get('link', '')),
                    'published': pub_str,
                    'description': art.get('description', '')[:300],
                    'source': art.get('source', 'Iraq RSS'),
                    'weight': 1.0,
                })
                added += 1
            print(f"[Iraq Rhetoric] RSS monitor: {added} articles")
        except Exception as e:
            print(f"[Iraq Rhetoric] RSS monitor error: {e}")

    if TELEGRAM_AVAILABLE:
        try:
            tg_messages = fetch_telegram_signals_iraq(hours_back=days * 24)
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
                    'weight': 1.2,
                    'views': msg.get('views', 0),
                    'forwards': msg.get('forwards', 0),
                })
                tg_count += 1
            print(f"[Iraq Rhetoric] Telegram: {tg_count} messages")
        except Exception as e:
            print(f"[Iraq Rhetoric] Telegram error: {e}")

    try:
        reddit_posts = fetch_reddit_iraq(days=days)
        articles.extend(reddit_posts)
        print(f"[Iraq Rhetoric] Reddit: {len(reddit_posts)} posts")
    except Exception as e:
        print(f"[Iraq Rhetoric] Reddit error: {e}")

    seen = set()
    unique = []
    for a in articles:
        u = a.get('url', '')
        if u and u not in seen:
            seen.add(u)
            unique.append(a)

    tg_c  = sum(1 for a in unique if 'Telegram' in str(a.get('source', '')))
    red_c = sum(1 for a in unique if str(a.get('source', '')).startswith('r/'))
    rss_c = len(unique) - tg_c - red_c
    # Nitter
    try:
        nitter_posts = fetch_nitter_iraq(days=days)
        for p in nitter_posts:
            u = p.get('url', '')
            if u and u not in seen_urls:
                seen_urls.add(u)
                unique.append(p)
    except Exception as e:
        print(f"[Iraq Rhetoric] Nitter error: {e}")

    nit_c = sum(1 for a in unique if 'Nitter' in str(a.get('source', '')))
    print(f"[Iraq Rhetoric] Total unique: {len(unique)} ({rss_c} RSS + {tg_c} TG + {red_c} Reddit)")
    return unique


# ============================================
# CLASSIFY ARTICLES (v2.0 — per-actor scoring with reporting downgrade)
# ============================================
def classify_articles(articles):
    """Classify articles by actor and threat vector. v2.0: reporting downgrade applied."""

    actor_results = {
        actor_id: {
            'name': info['name'],
            'flag': info['flag'],
            'icon': info['icon'],
            'color': info['color'],
            'role': info['role'],
            'statement_count': 0,
            'pmf_score': 0,
            'iran_strike_score': 0,
            'us_base_score': 0,
            'kurdish_score': 0,
            'isis_score': 0,
            'max_level': 0,
            'top_articles': [],
            'silence_alert': False,
            'new_voice': False,
            'specificity_scores': [],
        }
        for actor_id, info in ACTORS.items()
    }

    theatre_summary = {
        'pmf_max_level': 0,
        'iran_strike_max_level': 0,
        'us_base_max_level': 0,
        'kurdish_max_level': 0,
        'isis_max_level': 0,
        'total_articles': len(articles),
        'coordination_signals': [],
        'all_specificity_scores': [],
    }

    actor_timestamps = {a: [] for a in ACTORS}

    for article in articles:
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        pub_date = article.get('published', '')

        # Specificity score
        spec_score, _ = _score_specificity(text)
        if spec_score > 0:
            theatre_summary['all_specificity_scores'].append(spec_score)

        # Check for reporting language (used for downgrade below)
        is_reporting_context = any(phrase in text for phrase in REPORTING_LANGUAGE)

        matched_actors = []
        for actor_id, keywords in ACTOR_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                matched_actors.append(actor_id)
                actor_results[actor_id]['statement_count'] += 1
                if pub_date:
                    actor_timestamps[actor_id].append(pub_date)
                if len(actor_results[actor_id]['top_articles']) < 5:
                    actor_results[actor_id]['top_articles'].append({
                        'title': article.get('title', '')[:150],
                        'url': article.get('url', ''),
                        'source': article.get('source', ''),
                        'published': pub_date if isinstance(pub_date, str) else '',
                        'specificity_score': spec_score,
                    })
                if spec_score > 0:
                    actor_results[actor_id]['specificity_scores'].append(spec_score)

        # Score vectors — apply reporting downgrade for reporting actors
        for level in range(5, 0, -1):

            # PMF mobilization
            for kw in PMF_MOBILIZATION_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                            print(f"[Iraq Rhetoric] 📰 Reporting downgrade: {actor_id} PMF L{level}→L2")
                        if effective_level > actor_results[actor_id]['pmf_score']:
                            actor_results[actor_id]['pmf_score'] = effective_level
                    # Theatre vector uses RAW level (not per-actor downgrade)
                    if level > theatre_summary['pmf_max_level']:
                        theatre_summary['pmf_max_level'] = level
                    break

            # Iran direct strikes
            for kw in IRAN_STRIKE_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > actor_results[actor_id]['iran_strike_score']:
                            actor_results[actor_id]['iran_strike_score'] = effective_level
                    if level > theatre_summary['iran_strike_max_level']:
                        theatre_summary['iran_strike_max_level'] = level
                    break

            # US base strikes
            for kw in US_BASE_STRIKE_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > actor_results[actor_id]['us_base_score']:
                            actor_results[actor_id]['us_base_score'] = effective_level
                    if level > theatre_summary['us_base_max_level']:
                        theatre_summary['us_base_max_level'] = level
                    break

            # Kurdish tensions
            for kw in KURDISH_TENSION_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > actor_results[actor_id]['kurdish_score']:
                            actor_results[actor_id]['kurdish_score'] = effective_level
                    if level > theatre_summary['kurdish_max_level']:
                        theatre_summary['kurdish_max_level'] = level
                    break

            # ISIS resurgence
            for kw in ISIS_RESURGENCE_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > actor_results[actor_id]['isis_score']:
                            actor_results[actor_id]['isis_score'] = effective_level
                    if level > theatre_summary['isis_max_level']:
                        theatre_summary['isis_max_level'] = level
                    break

    # Per-actor max level + silence detection
    for actor_id, ar in actor_results.items():
        ar['max_level'] = max(
            ar['pmf_score'], ar['iran_strike_score'],
            ar['us_base_score'], ar['kurdish_score'], ar['isis_score']
        )
        ar['escalation_level'] = ar['max_level']
        ar['escalation_label'] = ESCALATION_LEVELS.get(ar['max_level'], {}).get('label', 'Baseline')
        ar['escalation_color'] = ESCALATION_LEVELS.get(ar['max_level'], {}).get('color', '#6b7280')

        baseline = SILENCE_BASELINE.get(actor_id, 2)
        if ar['statement_count'] == 0 and baseline >= 2:
            ar['silence_alert'] = True

        # Actor-level specificity
        specs = ar.pop('specificity_scores', [])
        ar['specificity_score'] = round(sum(specs) / len(specs), 1) if specs else 0

    # Coordination signal detection
    for a1_id, a2_id, message in COORDINATION_PAIRS:
        a1 = actor_results[a1_id]
        a2 = actor_results[a2_id]
        if a1['max_level'] >= 2 and a2['max_level'] >= 2:
            theatre_summary['coordination_signals'].append({
                'actors': [a1_id, a2_id],
                'message': message,
                'severity': 'critical' if (a1['max_level'] + a2['max_level']) >= 8 else 'high',
                'a1_level': a1['max_level'],
                'a2_level': a2['max_level'],
            })

    return actor_results, theatre_summary


# ============================================
# RHETORIC SCORE
# ============================================
def _calculate_rhetoric_score(actor_results, theatre_summary):
    pmf_score  = theatre_summary['pmf_max_level']
    iran_score = theatre_summary['iran_strike_max_level']
    base_score = theatre_summary['us_base_max_level']
    kurd_score = theatre_summary['kurdish_max_level']
    isis_score = theatre_summary['isis_max_level']

    weighted = (
        pmf_score  * 2.0 +
        iran_score * 2.5 +
        base_score * 2.0 +
        kurd_score * 1.0 +
        isis_score * 1.0
    )
    max_possible = 5 * (2.0 + 2.5 + 2.0 + 1.0 + 1.0)
    base = (weighted / max_possible) * 85
    coord_bonus = min(len(theatre_summary['coordination_signals']) * 5, 15)
    return min(100, int(base + coord_bonus))


# ============================================
# MAIN SCAN (v2.0)
# ============================================
def run_iraq_rhetoric_scan(days=3):
    """Full Iraq rhetoric scan. v2.0: adds delta, specificity, baselines, cross-theater."""
    print(f"\n[Iraq Rhetoric] ═══ Starting scan v2.0 (days={days}) ═══")
    start = datetime.now(timezone.utc)

    articles = fetch_rhetoric_articles(days=days)
    actor_results, theatre_summary = classify_articles(articles)
    rhetoric_score = _calculate_rhetoric_score(actor_results, theatre_summary)

    max_pmf   = theatre_summary['pmf_max_level']
    max_iran  = theatre_summary['iran_strike_max_level']
    max_base  = theatre_summary['us_base_max_level']
    max_kurd  = theatre_summary['kurdish_max_level']
    max_isis  = theatre_summary['isis_max_level']
    max_level = max(max_pmf, max_iran, max_base, max_kurd, max_isis)

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
        'theatre': 'Iraq',
        'theatre_score': rhetoric_score,
        'theatre_level': max_level,
        'theatre_escalation_level': max_level,
        'theatre_escalation_label': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Baseline'),
        'theatre_escalation_color': ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
        'theatre_escalation_description': ESCALATION_LEVELS.get(max_level, {}).get('description', ''),
        # Vectors
        'pmf_level':         max_pmf,
        'pmf_label':         ESCALATION_LEVELS.get(max_pmf, {}).get('label', 'Baseline'),
        'iran_strike_level': max_iran,
        'iran_strike_label': ESCALATION_LEVELS.get(max_iran, {}).get('label', 'Baseline'),
        'us_base_level':     max_base,
        'us_base_label':     ESCALATION_LEVELS.get(max_base, {}).get('label', 'Baseline'),
        'kurdish_level':     max_kurd,
        'kurdish_label':     ESCALATION_LEVELS.get(max_kurd, {}).get('label', 'Baseline'),
        'isis_level':        max_isis,
        'isis_label':        ESCALATION_LEVELS.get(max_isis, {}).get('label', 'Baseline'),
        # v2.0 enriched fields
        'specificity_score': theatre_specificity,
        'delta': None,              # filled below
        'silence_anomalies': [],    # filled below
        'crosstheater_coordination': [],  # filled below
        # Actors and signals
        'actors': actor_results,
        'coordination_signals': theatre_summary['coordination_signals'][:5],
        'scan_time_seconds': scan_time,
        'version': '2.0.0-iraq-rhetoric',
    }

    # Save to both keys (unified + legacy)
    _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(RHETORIC_CACHE_KEY_LEGACY, result)

    # History snapshot
    try:
        snapshot = json.dumps({
            'ts':    datetime.now(timezone.utc).isoformat(),
            'score': rhetoric_score,
            'level': max_level,
            'label': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Baseline'),
            'pmf':   max_pmf,
            'iran':  max_iran,
            'base':  max_base,
            'kurd':  max_kurd,
            'isis':  max_isis,
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
            print(f"[Iraq Rhetoric] 📈 History snapshot saved")
    except Exception as e:
        print(f"[Iraq Rhetoric] History append error (non-fatal): {e}")

    # Actor baselines + silence anomalies
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # Delta
    result['delta'] = _compute_delta()

    # Cross-theater
    _write_crosstheater_signal(result)
    result['crosstheater_coordination'] = _detect_crosstheater_coordination()

    # Signal interpretation
    if INTERPRETER_AVAILABLE:
        try:
            result['interpretation'] = iraq_interpret_signals(result)
            best = result['interpretation']['historical_matches']
            best_pct = best[0]['similarity'] if best else 'none'
            sadr_s = result['interpretation']['so_what'].get('sadr_silent', False)
            katai = result['interpretation']['so_what'].get('kataib_active', False)
            print(f"[Iraq Rhetoric] Interpreter: {result['interpretation']['red_lines']['breached_count']} red lines breached, "
                  f"best match: {best_pct}%"
                  f"{' | SADR-SILENT' if sadr_s else ''}"
                  f"{' | KATAIB-ACTIVE' if katai else ''}")
        except Exception as e:
            print(f"[Iraq Rhetoric] Warning: Interpreter error (non-fatal): {e}")

    # Re-save with enriched fields
    _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(RHETORIC_CACHE_KEY_LEGACY, result)

    print(f"[Iraq Rhetoric] ✅ v2.0 complete in {scan_time}s — "
          f"Level: {result['theatre_escalation_label']} ({max_level}) | "
          f"Score: {rhetoric_score}/100 | "
          f"Specificity: {theatre_specificity}/10 | "
          f"Delta: {result.get('delta', {}).get('direction', 'n/a') if result.get('delta') else 'n/a'}")
    return result


def _bg_rhetoric_scan():
    global _rhetoric_running
    try:
        run_iraq_rhetoric_scan()
    except Exception as e:
        print(f"[Iraq Rhetoric] Background scan error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


# ============================================
# ROUTE REGISTRATION
# ============================================
def register_iraq_rhetoric_routes(app):

    @app.route('/api/rhetoric/iraq', methods=['GET'])
    def iraq_rhetoric():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        if force:
            print("[Iraq Rhetoric] Force refresh requested")
            try:
                result = run_iraq_rhetoric_scan()
                return jsonify(result)
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)[:200]}), 500

        # Try unified key first, fall back to legacy
        cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(RHETORIC_CACHE_KEY_LEGACY)
        if cached:
            cached['cached'] = True
            return jsonify(cached)

        global _rhetoric_running
        with _rhetoric_lock:
            if not _rhetoric_running:
                _rhetoric_running = True
                t = threading.Thread(target=_bg_rhetoric_scan, daemon=True)
                t.start()

        return jsonify({
            'success': True,
            'awaiting_scan': True,
            'theatre': 'Iraq',
            'theatre_score': 0,
            'theatre_escalation_level': 0,
            'theatre_escalation_label': 'Baseline',
            'theatre_escalation_color': '#6b7280',
            'actors': {},
            'coordination_signals': [],
            'message': 'First scan in progress — check back in 2-3 minutes',
        })

    @app.route('/api/rhetoric/iraq/summary', methods=['GET'])
    def iraq_rhetoric_summary():
        """Lightweight summary — v2.0: includes delta, specificity, silence_anomalies."""
        cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(RHETORIC_CACHE_KEY_LEGACY)
        if cached:
            return jsonify({
                'success': True,
                # Core fields
                'theatre_score':             cached.get('theatre_score', 0),
                'theatre_level':             cached.get('theatre_level', cached.get('theatre_escalation_level', 0)),
                'theatre_escalation_level':  cached.get('theatre_escalation_level', 0),
                'theatre_escalation_label':  cached.get('theatre_escalation_label', 'Baseline'),
                'theatre_escalation_color':  cached.get('theatre_escalation_color', '#6b7280'),
                'theatre_label':             cached.get('theatre_escalation_label', 'Baseline'),
                'theatre_color':             cached.get('theatre_escalation_color', '#6b7280'),
                # Vectors
                'pmf_level':         cached.get('pmf_level', 0),
                'pmf_label':         cached.get('pmf_label', 'Baseline'),
                'iran_strike_level': cached.get('iran_strike_level', 0),
                'iran_strike_label': cached.get('iran_strike_label', 'Baseline'),
                'us_base_level':     cached.get('us_base_level', 0),
                'us_base_label':     cached.get('us_base_label', 'Baseline'),
                'kurdish_level':     cached.get('kurdish_level', 0),
                'kurdish_label':     cached.get('kurdish_label', 'Baseline'),
                'isis_level':        cached.get('isis_level', 0),
                'isis_label':        cached.get('isis_label', 'Baseline'),
                # v2.0 enriched
                'specificity_score':  cached.get('specificity_score', 0),
                'delta':              cached.get('delta'),
                'silence_anomalies':  cached.get('silence_anomalies', []),
                'total_articles':     cached.get('total_articles', 0),
                # Meta
                'timestamp':  cached.get('timestamp'),
                'scanned_at': cached.get('scanned_at', cached.get('timestamp', '')),
                'cached': True,
            })
        return jsonify({
            'success': False,
            'message': 'No cached data yet — scan in progress',
            'awaiting_scan': True,
        })

    @app.route('/api/rhetoric/iraq/history', methods=['GET'])
    def iraq_rhetoric_history():
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
                'theatre': 'Iraq',
                'history_key': HISTORY_KEY,
                'count': len(entries),
                'entries': entries,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # Background scan thread
    def _periodic_scan():
        time.sleep(120)
        print("[Iraq Rhetoric] Starting initial scan...")
        _bg_rhetoric_scan()
        while True:
            print(f"[Iraq Rhetoric] Sleeping {SCAN_INTERVAL_HOURS}h until next scan...")
            time.sleep(SCAN_INTERVAL_HOURS * 3600)
            _bg_rhetoric_scan()

    thread = threading.Thread(target=_periodic_scan, daemon=True)
    thread.start()

    print("[Iraq Rhetoric] ✅ v2.0 routes registered: "
          "/api/rhetoric/iraq, /api/rhetoric/iraq/summary, /api/rhetoric/iraq/history")
