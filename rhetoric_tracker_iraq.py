"""
Iraq Rhetoric Tracker — Asifah Analytics
v1.0.0 — March 2026

Tracks escalation rhetoric across Iraq's multi-faction landscape
during the active Iran-US war (March 2026):

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

Sources: Google News RSS (EN/AR/KU) + Rudaw + Kurdistan24
         + Telegram (IRAQ_CHANNELS) + Reddit
         + Iran International + CENTCOM

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

RHETORIC_CACHE_KEY = 'iraq_rhetoric_cache'
RHETORIC_CACHE_TTL = 6 * 3600  # 6 hours
SCAN_INTERVAL_HOURS = 6

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ESCALATION LEVELS — Gold Standard
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
            # Direct strike keywords
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
# THREAT VECTORS — Five-dimension analysis
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

# VECTOR 2: IRAN DIRECT STRIKES (on Iraq soil — Embassy/Consulate/US facilities)
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

# VECTOR 3: US BASE STRIKES (PMF/Kata'ib attacks on US military facilities)
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
# ACTOR → KEYWORD MAPPING (article routing)
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


# ============================================
# COORDINATION SIGNAL DETECTION
# ============================================
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
# RSS FEEDS
# ============================================
RHETORIC_RSS_FEEDS = [
    # English — PMF / Iran-Iraq nexus
    ("https://news.google.com/rss/search?q=PMF+Iraq+Iran+militia+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Hashd+al-Shaabi+Iraq&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Kataib+Hezbollah+Iraq&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iraq+US+embassy+Baghdad+attack&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=US+consulate+Erbil+attack+Iran&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iran+missile+drone+Iraq+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=al+Asad+airbase+attack+Iraq&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=CENTCOM+Iraq+strike+2026&hl=en&gl=US&ceid=US:en", 0.95),
    # Kurdish / KRG
    ("https://news.google.com/rss/search?q=Kirkuk+Peshmerga+PMF+2026&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=KRG+Erbil+security+2026&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://www.rudaw.net/english/feed", 1.0),
    ("https://www.kurdistan24.net/en/rss.xml", 0.95),
    # ISIS
    ("https://news.google.com/rss/search?q=ISIS+Iraq+attack+Anbar+Diyala+2026&hl=en&gl=US&ceid=US:en", 0.9),
    # Sadr
    ("https://news.google.com/rss/search?q=Muqtada+al-Sadr+Iraq+2026&hl=en&gl=US&ceid=US:en", 0.9),
    # Broader Iraq security
    ("https://news.google.com/rss/search?q=Iraq+war+Iran+2026+militia&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Iraq+security+2026+attack&hl=en&gl=US&ceid=US:en", 0.85),
    # Arabic — Iraq
    ("https://news.google.com/rss/search?q=الحشد+الشعبي+العراق+2026&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=كتائب+حزب+الله+العراق&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=إيران+العراق+ضربة+2026&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=السفارة+الأمريكية+بغداد+هجوم&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=داعش+العراق+هجوم+2026&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=مقتدى+الصدر+العراق&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=كركوك+البيشمركة+2026&hl=ar&gl=SA&ceid=SA:ar", 0.85),
    # Farsi — Iran directing Iraq operations
    ("https://news.google.com/rss/search?q=سپاه+عراق+عملیات&hl=fa&gl=IR&ceid=IR:fa", 0.95),
    ("https://news.google.com/rss/search?q=ایران+عراق+موشک&hl=fa&gl=IR&ceid=IR:fa", 0.95),
    # Hebrew — Israeli intel on Iran-Iraq
    ("https://news.google.com/rss/search?q=עיראק+איראן+מיליציה&hl=iw&gl=IL&ceid=IL:iw", 0.85),
]


# ============================================
# REDDIT CONFIG
# ============================================
REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

IRAQ_SUBREDDITS = [
    'CredibleDefense',
    'geopolitics',
    'worldnews',
    'iraq',
    'IRG',
]

IRAQ_REDDIT_KEYWORDS = [
    'pmf iraq', 'kataib', 'hashd', 'us embassy baghdad',
    'us consulate erbil', 'iran iraq missile', 'al asad attack',
    'sadr iraq', 'peshmerga kirkuk', 'isis iraq 2026',
]


def fetch_reddit_iraq(days=3):
    """Fetch Reddit posts from Iraq-relevant subreddits."""
    time_filter = 'day' if days <= 1 else 'week' if days <= 7 else 'month'
    query = ' OR '.join(IRAQ_REDDIT_KEYWORDS[:4])
    posts = []

    for subreddit in IRAQ_SUBREDDITS:
        try:
            time.sleep(2)
            url = f'https://www.reddit.com/r/{subreddit}/search.json'
            params = {
                'q': query,
                'restrict_sr': 'true',
                'sort': 'new',
                't': time_filter,
                'limit': 25
            }
            resp = requests.get(url, params=params,
                                headers={'User-Agent': REDDIT_USER_AGENT},
                                timeout=10)
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
                        pd.get('created_utc', 0), tz=timezone.utc
                    ).isoformat(),
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
    """Fetch articles from RSS + dedicated Iraq RSS + Telegram + Reddit."""
    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # ── Core RSS ──
    for feed_url, weight in RHETORIC_RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=12,
                                headers={"User-Agent": "Mozilla/5.0"})
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

    rss_count = len(articles)
    print(f"[Iraq Rhetoric] Core RSS: {rss_count} articles")

    # ── Dedicated Iraq RSS monitor feeds ──
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
            print(f"[Iraq Rhetoric] RSS monitor: {added} Iraq-specific articles")
        except Exception as e:
            print(f"[Iraq Rhetoric] RSS monitor error: {e}")

    # ── Telegram ──
    if TELEGRAM_AVAILABLE:
        try:
            hours_back = days * 24
            tg_messages = fetch_telegram_signals_iraq(hours_back=hours_back)
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
                    'weight': 1.2,  # Telegram gets slight boost — real-time
                    'views': msg.get('views', 0),
                    'forwards': msg.get('forwards', 0),
                })
                tg_count += 1
            print(f"[Iraq Rhetoric] Telegram: {tg_count} messages")
        except Exception as e:
            print(f"[Iraq Rhetoric] Telegram error: {e}")

    # ── Reddit ──
    try:
        reddit_posts = fetch_reddit_iraq(days=days)
        for post in reddit_posts:
            articles.append(post)
        print(f"[Iraq Rhetoric] Reddit: {len(reddit_posts)} posts")
    except Exception as e:
        print(f"[Iraq Rhetoric] Reddit error: {e}")

    # Deduplicate by URL
    seen = set()
    unique = []
    for a in articles:
        u = a.get('url', '')
        if u and u not in seen:
            seen.add(u)
            unique.append(a)

    tg_c   = sum(1 for a in unique if 'Telegram' in a.get('source', ''))
    red_c  = sum(1 for a in unique if a.get('source', '').startswith('r/'))
    rss_c  = len(unique) - tg_c - red_c
    print(f"[Iraq Rhetoric] Total unique: {len(unique)} ({rss_c} RSS + {tg_c} TG + {red_c} Reddit)")
    return unique


# ============================================
# CLASSIFY ARTICLES
# ============================================
def classify_articles(articles):
    """Classify articles by actor and threat vector."""

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
    }

    actor_timestamps = {a: [] for a in ACTORS}

    for article in articles:
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        pub_date = article.get('published', '')

        # ── Route article to actors ──
        matched_actors = []
        for actor_id, keywords in ACTOR_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                matched_actors.append(actor_id)
                actor_results[actor_id]['statement_count'] += 1
                if pub_date:
                    actor_timestamps[actor_id].append(pub_date)

                # Store top articles (cap at 5)
                if len(actor_results[actor_id]['top_articles']) < 5:
                    actor_results[actor_id]['top_articles'].append({
                        'title': article.get('title', '')[:150],
                        'url': article.get('url', ''),
                        'source': article.get('source', ''),
                        'published': pub_date if isinstance(pub_date, str) else '',
                    })

        # ── Score vectors ──
        for level in range(5, 0, -1):
            # PMF mobilization
            for kw in PMF_MOBILIZATION_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        if level > actor_results[actor_id]['pmf_score']:
                            actor_results[actor_id]['pmf_score'] = level
                    if level > theatre_summary['pmf_max_level']:
                        theatre_summary['pmf_max_level'] = level
                    break

            # Iran direct strikes
            for kw in IRAN_STRIKE_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        if level > actor_results[actor_id]['iran_strike_score']:
                            actor_results[actor_id]['iran_strike_score'] = level
                    if level > theatre_summary['iran_strike_max_level']:
                        theatre_summary['iran_strike_max_level'] = level
                    break

            # US base strikes
            for kw in US_BASE_STRIKE_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        if level > actor_results[actor_id]['us_base_score']:
                            actor_results[actor_id]['us_base_score'] = level
                    if level > theatre_summary['us_base_max_level']:
                        theatre_summary['us_base_max_level'] = level
                    break

            # Kurdish tensions
            for kw in KURDISH_TENSION_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        if level > actor_results[actor_id]['kurdish_score']:
                            actor_results[actor_id]['kurdish_score'] = level
                    if level > theatre_summary['kurdish_max_level']:
                        theatre_summary['kurdish_max_level'] = level
                    break

            # ISIS resurgence
            for kw in ISIS_RESURGENCE_TRIGGERS.get(level, []):
                if kw in text:
                    for actor_id in matched_actors:
                        if level > actor_results[actor_id]['isis_score']:
                            actor_results[actor_id]['isis_score'] = level
                    if level > theatre_summary['isis_max_level']:
                        theatre_summary['isis_max_level'] = level
                    break

    # ── Per-actor max level + silence detection ──
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

    # ── Coordination signal detection ──
    window_hours = 48
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
# RHETORIC SCORE CALCULATION
# ============================================
def _calculate_rhetoric_score(actor_results, theatre_summary):
    """Calculate 0–100 composite rhetoric score."""
    # Vector maximums (weighted by strategic importance)
    pmf_score    = theatre_summary['pmf_max_level']        # weight 2.0 — primary driver
    iran_score   = theatre_summary['iran_strike_max_level'] # weight 2.5 — highest strategic weight
    base_score   = theatre_summary['us_base_max_level']     # weight 2.0
    kurd_score   = theatre_summary['kurdish_max_level']     # weight 1.0
    isis_score   = theatre_summary['isis_max_level']        # weight 1.0

    weighted = (
        pmf_score  * 2.0 +
        iran_score * 2.5 +
        base_score * 2.0 +
        kurd_score * 1.0 +
        isis_score * 1.0
    )
    max_possible = 5 * (2.0 + 2.5 + 2.0 + 1.0 + 1.0)  # = 42.5
    base = (weighted / max_possible) * 85

    # Coordination bonus
    coord_bonus = min(len(theatre_summary['coordination_signals']) * 5, 15)

    score = min(100, int(base + coord_bonus))
    return score


# ============================================
# MAIN SCAN
# ============================================
def run_iraq_rhetoric_scan(days=3):
    """Full Iraq rhetoric scan. Returns result dict."""
    print(f"\n[Iraq Rhetoric] ═══ Starting scan (days={days}) ═══")
    start = datetime.now(timezone.utc)

    articles = fetch_rhetoric_articles(days=days)
    actor_results, theatre_summary = classify_articles(articles)
    rhetoric_score = _calculate_rhetoric_score(actor_results, theatre_summary)

    max_pmf    = theatre_summary['pmf_max_level']
    max_iran   = theatre_summary['iran_strike_max_level']
    max_base   = theatre_summary['us_base_max_level']
    max_kurd   = theatre_summary['kurdish_max_level']
    max_isis   = theatre_summary['isis_max_level']
    max_level  = max(max_pmf, max_iran, max_base, max_kurd, max_isis)

    scan_time = round((datetime.now(timezone.utc) - start).total_seconds(), 1)

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'days_analyzed': days,
        'total_articles': len(articles),
        'theatre': 'Iraq',
        'theatre_score': rhetoric_score,
        'theatre_escalation_level': max_level,
        'theatre_escalation_label': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Baseline'),
        'theatre_escalation_color': ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
        'theatre_escalation_description': ESCALATION_LEVELS.get(max_level, {}).get('description', ''),
        # Per-vector levels
        'pmf_level':        max_pmf,
        'pmf_label':        ESCALATION_LEVELS.get(max_pmf, {}).get('label', 'Baseline'),
        'iran_strike_level': max_iran,
        'iran_strike_label': ESCALATION_LEVELS.get(max_iran, {}).get('label', 'Baseline'),
        'us_base_level':    max_base,
        'us_base_label':    ESCALATION_LEVELS.get(max_base, {}).get('label', 'Baseline'),
        'kurdish_level':    max_kurd,
        'kurdish_label':    ESCALATION_LEVELS.get(max_kurd, {}).get('label', 'Baseline'),
        'isis_level':       max_isis,
        'isis_label':       ESCALATION_LEVELS.get(max_isis, {}).get('label', 'Baseline'),
        # Actors and signals
        'actors': actor_results,
        'coordination_signals': theatre_summary['coordination_signals'][:5],
        'scan_time_seconds': scan_time,
        'version': '1.0.0-iraq-rhetoric',
    }

    _redis_set(RHETORIC_CACHE_KEY, result)

    # ── HISTORY SNAPSHOT (gold standard v1.1.0) ──
    try:
        import urllib.parse
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
        })
        HISTORY_KEY = 'rhetoric:iraq:history'
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

    print(f"[Iraq Rhetoric] ✅ Complete in {scan_time}s — "
          f"Level: {result['theatre_escalation_label']} | Score: {rhetoric_score}/100")
    return result


def _bg_rhetoric_scan():
    global _rhetoric_running
    try:
        run_iraq_rhetoric_scan()
    except Exception as e:
        print(f"[Iraq Rhetoric] Background scan error: {e}")
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


# ============================================
# ROUTE REGISTRATION
# ============================================
def register_iraq_rhetoric_routes(app):
    """Register all Iraq rhetoric endpoints on the Flask app."""

    @app.route('/api/rhetoric/iraq', methods=['GET'])
    def iraq_rhetoric():
        """Main Iraq rhetoric endpoint."""
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        if force:
            print("[Iraq Rhetoric] Force refresh requested")
            try:
                result = run_iraq_rhetoric_scan()
                return jsonify(result)
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)[:200]}), 500

        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            cached['cached'] = True
            return jsonify(cached)

        # No cache — trigger background scan, return placeholder
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
        """Lightweight summary for stability page badge."""
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            return jsonify({
                'success': True,
                'theatre_score': cached.get('theatre_score', 0),
                'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
                'theatre_escalation_label': cached.get('theatre_escalation_label', 'Baseline'),
                'theatre_escalation_color': cached.get('theatre_escalation_color', '#6b7280'),
                'pmf_level':         cached.get('pmf_level', 0),
                'iran_strike_level': cached.get('iran_strike_level', 0),
                'us_base_level':     cached.get('us_base_level', 0),
                'kurdish_level':     cached.get('kurdish_level', 0),
                'isis_level':        cached.get('isis_level', 0),
                'timestamp': cached.get('timestamp'),
                'cached': True,
            })
        return jsonify({'success': False, 'message': 'No cached data yet — scan in progress'})

    @app.route('/api/rhetoric/iraq/history', methods=['GET'])
    def iraq_rhetoric_history():
        """Rolling history — last 120 snapshots (~30 days). Used by trend chart."""
        try:
            limit = int(request.args.get('limit', 120))
            limit = max(1, min(limit, 120))
            HISTORY_KEY = 'rhetoric:iraq:history'
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
            entries.reverse()  # oldest first for chart
            return jsonify({
                'success': True,
                'theatre': 'Iraq',
                'history_key': HISTORY_KEY,
                'count': len(entries),
                'entries': entries,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # Background scan thread (every 6 hours)
    def _periodic_scan():
        time.sleep(120)  # Boot delay
        print("[Iraq Rhetoric] Starting initial scan...")
        _bg_rhetoric_scan()
        while True:
            print(f"[Iraq Rhetoric] Sleeping {SCAN_INTERVAL_HOURS}h until next scan...")
            time.sleep(SCAN_INTERVAL_HOURS * 3600)
            _bg_rhetoric_scan()

    thread = threading.Thread(target=_periodic_scan, daemon=True)
    thread.start()

    print("[Iraq Rhetoric] ✅ Routes registered: "
          "/api/rhetoric/iraq, /api/rhetoric/iraq/summary, /api/rhetoric/iraq/history")
