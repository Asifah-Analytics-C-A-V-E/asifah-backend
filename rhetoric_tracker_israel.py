"""
Asifah Analytics — Israel Rhetoric & Strike Actor Tracker
v1.0.0 — March 2026

ANALYTICAL FRAME — Two questions for the analyst:

  Q1: Is Iran or one of its proxies going to strike Israel?
      → INBOUND THREAT DASHBOARD
      Reads cross-theater fingerprints from Iran, Lebanon, Yemen, Syria, Iraq
      + Pikud HaOref (Tzeva Adom) real-time alert counts
      + Named Israeli targets in adversary rhetoric

  Q2: Is Israel gearing up to strike, invade, or annex?
      → OUTBOUND POSTURE DASHBOARD
      IDF mobilization language, War Cabinet authorization,
      Smotrich/Ben Gvir annexation rhetoric, settlement expansion signals,
      Gaza continuation posture, West Bank agitation

  US/EU = Coordination Signals only (greenlight vs brake)
  Tzeva Adom alerts = Ground truth for Q1 "when" signal

THREE-LAYER PIKUD HAOREF ALERT SYSTEM:
  Layer 1 — Telegram @tzevaadom_en / @tzevaadom (always available, no geo-block)
  Layer 2 — GCP me-west1 relay (OREF_RELAY_URL env var, Israeli IP)
  Layer 3 — Direct oref.org.il API (works if caller has Israeli IP or VPN)
  Fallback gracefully through layers, cache alert counts in Redis

INBOUND VECTORS (reads cross-theater fingerprints as PRIMARY input):
  1. BALLISTIC THREAT  — Iran missiles, OTP waves, named Israeli targets
  2. NORTHERN FRONT    — Hezbollah/Lebanon active conflict level
  3. ASYMMETRIC THREAT — Hamas/Gaza, Houthi, West Bank, Syria

OUTBOUND VECTORS (Israel as actor — own article scanning):
  4. STRIKE POSTURE    — IDF mobilization, War Cabinet, target language
  5. ANNEXATION/EXPANSION — Smotrich, Ben Gvir, settlers, West Bank

CROSS-THEATER:
  Writes is_strike_actor: True to shared fingerprint
  Reads Iran (command node), Lebanon, Yemen, Syria, Iraq fingerprints
  Threat Convergence Index: Iran L5 + Lebanon L5 + Yemen elevated = max signal

ACTORS:
  Inbound:  iran_threat, hezbollah_threat, houthi_threat,
            hamas_gaza, west_bank_civil, syria_threat
  Outbound: idf_military, war_cabinet, annexation_bloc,
            us_coordination, domestic_opposition

REDIS KEYS:
  Cache:        rhetoric:israel:latest
  Legacy:       israel_rhetoric_cache
  History:      rhetoric:israel:history
  Baselines:    rhetoric_baseline:israel
  Alert cache:  rhetoric:israel:alerts_24h
  Cross-theater: rhetoric:crosstheater:fingerprints (READ + WRITE)

ENDPOINTS:
  GET /api/rhetoric/israel
  GET /api/rhetoric/israel/summary
  GET /api/rhetoric/israel/history
  GET /api/rhetoric/israel/alerts     (Pikud HaOref alert counts)

CHANGELOG:
  v1.0.0 (2026-03-21): Initial build — dual dashboard + three-layer alert system

COPYRIGHT © 2025-2026 Asifah Analytics. All rights reserved.
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

# Signal interpreter — So What, Red Lines, Historical Patterns
try:
    from israel_signal_interpreter import interpret_signals
    INTERPRETER_AVAILABLE = True
    print("[Israel Rhetoric] ✅ Signal interpreter loaded")
except ImportError:
    INTERPRETER_AVAILABLE = False
    print("[Israel Rhetoric] ⚠️ Signal interpreter not available")

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

# Pikud HaOref relay — optional GCP me-west1 VM
# If set, enables Layer 2 direct API access via Israeli IP relay
# Format: http://YOUR_RELAY_IP:PORT
OREF_RELAY_URL = os.environ.get('OREF_RELAY_URL', '').rstrip('/')

# Direct Pikud HaOref endpoints (Layer 3 — Israeli IP or VPN only)
OREF_CURRENT_URL = 'https://www.oref.org.il/WarningMessages/alert/alerts.json'
OREF_HISTORY_URL = 'https://www.oref.org.il/WarningMessages/alert/History/AlertsHistory.json'
OREF_HEADERS = {
    'Referer': 'https://www.oref.org.il/',
    'X-Requested-With': 'XMLHttpRequest',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
}

# Tzeva Adom English Telegram channel — Layer 1 fallback (no geo-block)
TZEVA_ADOM_CHANNELS = ['tzevaadom_en']  # tzevaadom (bare) invalid — removed

try:
    from telegram_signals import fetch_telegram_signals_israel
    TELEGRAM_AVAILABLE = True
    print("[Israel Rhetoric] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Israel Rhetoric] ⚠️ Telegram signals not available — RSS only")

RHETORIC_CACHE_KEY        = 'rhetoric:israel:latest'
RHETORIC_CACHE_KEY_LEGACY = 'israel_rhetoric_cache'
HISTORY_KEY               = 'rhetoric:israel:history'
BASELINE_KEY              = 'rhetoric_baseline:israel'
CROSSTHEATER_KEY          = 'rhetoric:crosstheater:fingerprints'
ALERTS_CACHE_KEY          = 'rhetoric:israel:alerts_24h'

RHETORIC_CACHE_TTL  = 6 * 3600
SCAN_INTERVAL_HOURS = 6

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ESCALATION LEVELS
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Baseline',       'color': '#6b7280', 'description': 'No significant signals'},
    1: {'label': 'Rhetoric',       'color': '#3b82f6', 'description': 'Standard statements'},
    2: {'label': 'Warning',        'color': '#f59e0b', 'description': 'Escalatory language'},
    3: {'label': 'Directive',      'color': '#f97316', 'description': 'Threat signals, positioning'},
    4: {'label': 'Operational',    'color': '#ef4444', 'description': 'Strike posture, imminent signals'},
    5: {'label': 'Active Conflict','color': '#dc2626', 'description': 'Confirmed strikes/operations'},
}


# ============================================
# ACTORS
# ============================================
ACTORS = {
    # ── INBOUND — threats TO Israel ──
    'iran_threat': {
        'name': 'Iran (Inbound Threat)',
        'flag': '🇮🇷', 'icon': '🚀',
        'color': '#dc2626',
        'role': 'Ballistic / Nuclear Threat',
        'description': 'IRGC ballistic missiles, Operation True Promise waves, Dimona/Haifa targeting',
        'keywords': [
            'iran strikes israel', 'iran missile israel', 'iran attack israel',
            'irgc targets israel', 'operation true promise', 'wave of attacks israel',
            'iran ballistic missile', 'iran fires at israel',
            'dimona attack', 'dimona strike', 'haifa attack',
            'iran hits israel', 'iranian missile hit',
            'מתקפה איראנית', 'טיל איראני', 'צבא איראן תוקף',
            'إيران تضرب إسرائيل', 'صاروخ إيراني',
        ],
        'baseline_statements_per_week': 15,
    },
    'hezbollah_threat': {
        'name': 'Hezbollah (Northern Threat)',
        'flag': '🇱🇧', 'icon': '🔗',
        'color': '#16a34a',
        'role': 'Northern Front Inbound',
        'description': 'Hezbollah rockets, missiles, drones targeting northern Israel — daily operational claims',
        'keywords': [
            # Direct attack language
            'hezbollah fires at israel', 'hezbollah rockets israel',
            'hezbollah missiles israel', 'hezbollah targets israel',
            'hezbollah attack haifa', 'hezbollah attack north',
            'hezbollah drones israel', 'katyusha north israel',
            'hezbollah claims attack israel',
            # Al-Manar / operational claim language (v2.2)
            'rocket salvo israel', 'rocket salvo kiryat',
            'rocket salvo kfar', 'targeted gathering iof',
            'targeted iof vehicles', 'targeted israeli soldiers',
            'hezbollah fighters targeted', 'islamic resistance fighters',
            'hezbollah operation', 'hezbollah operation israel',
            'kiryat shmona', 'kfar yuval', 'metula', 'nahariya',
            'northern israel attack', 'northern command israel',
            'hezbollah daily', 'hezbollah salvo',
            'al-bayyada', 'avivim', 'beit hillel',
            # Hebrew
            'צפון ישראל ירי', 'חיזבאללה תוקף', 'קריית שמונה',
            'כפר יובל', 'סלבו רקטות', 'כפר בלום',
            # Arabic
            'حزب الله يقصف إسرائيل', 'صاروخ على إسرائيل',
            'المقاومة الإسلامية تستهدف', 'قصف شمال إسرائيل',
        ],
        'baseline_statements_per_week': 25,
    },
    'houthi_threat': {
        'name': 'Houthi (Southern Threat)',
        'flag': '🇾🇪', 'icon': '🔗',
        'color': '#f59e0b',
        'role': 'Long-Range Inbound',
        'description': 'Houthi ballistic missiles and drones targeting Israel — entered conflict in solidarity with Gaza',
        'keywords': [
            # Direct attack language
            'houthi fires at israel', 'houthi missile israel',
            'houthi drone israel', 'houthi attack israel',
            'houthi targets tel aviv', 'houthi targets eilat',
            'ansar allah missile israel', 'houthi ballistic israel',
            'houthi hypersonic israel', 'houthi cruise missile israel',
            # Conflict entry / solidarity language (v2.2)
            'houthi entered conflict', 'houthi joins war israel',
            'houthi support gaza', 'houthi in solidarity',
            'houthi operation al-aqsa', 'houthi flood',
            'ansar allah entered', 'ansar allah joins',
            'yemen enters war', 'yemen conflict israel',
            'houthi red sea israel', 'houthi bab el-mandeb israel',
            'houthi military operation israel',
            'houthi fifth military operation',
            'houthi operation number', 'houthi announces operation',
            # Hebrew
            "חות'י ישראל", "חות'ים תוקפים", 'טיל חות"י',
            # Arabic
            'الحوثيون يقصفون إسرائيل', 'أنصار الله يستهدف',
            'اليمن يدخل المعركة', 'عملية أنصار الله',
            'الحوثيون يعلنون عملية', 'دعماً لغزة',
        ],
        'baseline_statements_per_week': 12,
    },
    'hamas_gaza': {
        'name': 'Hamas / Gaza',
        'flag': '🇵🇸', 'icon': '💥',
        'color': '#7c3aed',
        'role': 'Southern Asymmetric Threat',
        'description': 'Hamas military wing, Gaza rockets, hostage situation, Gulf-based political signals',
        'keywords': [
            'hamas fires rockets', 'hamas attack israel',
            'al-qassam brigade', 'hamas military wing',
            'rockets from gaza', 'mortar fire israel',
            'hamas demands', 'hamas hostage', 'hamas ceasefire',
            'hamas political bureau', 'haniyeh', 'sinwar',
            'חמאס', 'קסאם', 'עזה ירי',
            'حماس تطلق', 'كتائب القسام',
        ],
        'baseline_statements_per_week': 10,
    },
    'west_bank_civil': {
        'name': 'West Bank / Palestinian Civil',
        'flag': '🇵🇸', 'icon': '✊',
        'color': '#0ea5e9',
        'role': 'Occupied Territory Signals',
        'description': 'Palestinian civil unrest, settler violence, annexation resistance, non-Hamas agitation',
        'keywords': [
            'west bank protest', 'west bank unrest', 'settler violence',
            'west bank raid', 'jenin raid', 'nablus raid',
            'palestinian killed west bank', 'idf west bank',
            'west bank annexation protest', 'settler attack',
            'ramallah protest', 'hebron tension',
            'גדה המערבית מחאה', 'מתנחלים אלימות',
            'الضفة الغربية احتجاجات', 'مستوطنون عنف',
        ],
        'baseline_statements_per_week': 8,
    },
    'syria_threat': {
        'name': 'Syria (Cross-Border)',
        'flag': '🇸🇾', 'icon': '⚠️',
        'color': '#d4943f',
        'role': 'Low-Level Border Threat',
        'description': 'Syria cross-border signals — lower weight, monitoring only',
        'keywords': [
            'syria fires at israel', 'golan attack',
            'syria cross border', 'israel syria exchange',
            'anti-tank fire golan', 'explosion near golan',
        ],
        'baseline_statements_per_week': 3,
    },
    # ── OUTBOUND — Israel as actor ──
    'idf_military': {
        'name': 'IDF / Military Command',
        'flag': '🇮🇱', 'icon': '⚔️',
        'color': '#1d4ed8',
        'role': 'Strike Actor — Military',
        'description': 'IDF operational posture, mobilization, strike authorizations, target language',
        'keywords': [
            'idf strikes', 'idf operation', 'idf mobilizes',
            'idf ground operation', 'idf air strike',
            'idf targets', 'israel strikes', 'israeli airstrike',
            'idf advancing', 'idf forces enter',
            'idf reservists called', 'idf prepares',
            'israeli navy', 'israel air force',
            # Lebanon ground operation / buffer zone (v2.1)
            'idf lebanon', 'idf southern lebanon', 'idf buffer zone',
            'idf security zone lebanon', 'idf ground forces lebanon',
            'israel occupation lebanon', 'israel buffer lebanon',
            'idf litani', 'litani river idf', 'south lebanon idf',
            'israeli troops lebanon', 'idf withdrawal lebanon',
            'israel security corridor lebanon', 'idf hold lebanon',
            'idf remain lebanon', 'idf stays lebanon',
            # Named target: Naim Qassem (Hezbollah SG since Nasrallah)
            'naim qassem', 'naim kassem', 'قاسم حزب الله',
            'hezbollah secretary general target', 'qassem targeted',
            'israel targets qassem', 'idf qassem', 'qassem assassination',
            'נעים קאסם', 'חיזבאללה מנהיג',
            'צה"ל תוקף', 'צה"ל מבצע', 'כוחות צה"ל',
            'الجيش الإسرائيلي يشن', 'غارة إسرائيلية',
        ],
        'baseline_statements_per_week': 20,
    },
    'war_cabinet': {
        'name': 'War Cabinet / Netanyahu',
        'flag': '🇮🇱', 'icon': '🏛️',
        'color': '#1e40af',
        'role': 'Strike Actor — Political Authorization',
        'description': 'Netanyahu, Gallant, Katz, war cabinet decisions, strike authorizations, diplomatic cover',
        'keywords': [
            'netanyahu orders', 'netanyahu authorizes', 'war cabinet decides',
            'netanyahu warns', 'israel will strike', 'israel has right',
            'netanyahu iran', 'netanyahu hezbollah', 'war cabinet approves',
            'israel cabinet votes', 'security cabinet israel',
            # Israel Katz — Defense Minister Lebanon occupation signals (v2.1)
            'israel katz', 'katz lebanon', 'katz occupation',
            'katz security zone', 'katz buffer zone lebanon',
            'katz hezbollah', 'katz southern lebanon',
            'defense minister lebanon', 'israeli defense minister occupation',
            'israel long term lebanon', 'israel permanent presence lebanon',
            'israel control lebanon', 'israel hold territory lebanon',
            'ישראל כץ', 'כץ לבנון', 'שר הביטחון לבנון',
            'وزير الدفاع الإسرائيلي لبنان', 'كاتس لبنان',
            'כנסת מלחמה', 'נתניהו מאשר', 'קבינט הביטחון',
            'نتنياهو يأمر', 'مجلس الحرب الإسرائيلي',
        ],
        'baseline_statements_per_week': 10,
    },
    'annexation_bloc': {
        'name': 'Annexation Bloc (Smotrich/Ben Gvir/Katz)',
        'flag': '🇮🇱', 'icon': '🗺️',
        'color': '#b45309',
        'role': 'Outbound — Expansion Posture',
        'description': 'Smotrich, Ben Gvir, settler rhetoric, West Bank annexation + Lebanon occupation/buffer zone expansion language',
        'keywords': [
            'smotrich', 'ben gvir', 'annexation west bank',
            'annex west bank', 'greater israel', 'sovereignty west bank',
            'settlement expansion', 'new settlement', 'outpost legalized',
            'smotrich annexation', 'ben gvir west bank',
            'israel apply sovereignty', 'apply israeli law',
            # Lebanon territorial expansion / long-term occupation (v2.1)
            'israel occupy lebanon', 'israel annexe lebanon',
            'israel security zone lebanon permanent',
            'greater israel lebanon', 'israel expand lebanon',
            'israel settle south lebanon', 'settlers south lebanon',
            'israel keep south lebanon', 'israel sovereign lebanon',
            'lebanon buffer permanent', 'israel control south lebanon',
            'כץ ריבונות לבנון', 'סיפוח דרום לבנון',
            'ضم جنوب لبنان', 'احتلال لبنان إسرائيل',
            'סמוטריץ', 'בן גביר', 'סיפוח', 'גדה המערבית ריבונות',
            'سموتريتش', 'بن غفير', 'ضم الضفة الغربية',
        ],
        'baseline_statements_per_week': 8,
    },
    'us_coordination': {
        'name': 'US / International (Coordination)',
        'flag': '🇺🇸', 'icon': '🤝',
        'color': '#0369a1',
        'role': 'Greenlight / Brake Signal',
        'description': 'US coordination signals — authorization language = greenlight, pressure = brake',
        'keywords': [
            # Classic coordination language
            'us israel coordination', 'us greenlight israel',
            'us authorizes israel', 'us backs israel strike',
            'trump netanyahu', 'us israel iran',
            'us ceasefire pressure', 'us demands israel',
            'us veto un', 'us blocks resolution',
            # Trump direct statements (v2.2)
            'trump israel', 'trump backs israel', 'trump warns israel',
            'trump iran deal israel', 'trump hezbollah',
            'trump hamas', 'trump hostages', 'trump ceasefire',
            'trump middle east', 'trump supports israel',
            'trump threatens iran israel', 'trump greenlight',
            # CENTCOM / military coordination
            'centcom israel', 'us carrier israel',
            'us forces middle east israel', 'us military israel',
            'us destroys houthi', 'us strikes houthi',
            'us iron dome', 'us patriot israel',
            'rubio israel', 'rubio iran israel',
            'witkoff israel', 'witkoff ceasefire',
            'us special envoy israel', 'us envoy hostage',
            # International brake signals
            'un security council israel', 'un ceasefire vote',
            'france israel ceasefire', 'uk israel pressure',
            'europe israel sanctions',
            # Hebrew / Arabic
            'אמריקה ישראל', 'ארה"ב מאשרת', 'טראמפ ישראל',
            'أمريكا تضوء خضراء لإسرائيل', 'ترامب إسرائيل',
            'سنتكوم إسرائيل',
        ],
        'baseline_statements_per_week': 10,
    },
    'domestic_opposition': {
        'name': 'Domestic Opposition / Hostage Families',
        'flag': '🇮🇱', 'icon': '✊',
        'color': '#64748b',
        'role': 'Domestic Pressure Signal',
        'description': 'Israeli protests, hostage family pressure, election signals, coalition fractures',
        'keywords': [
            'israel protest', 'israelis protest', 'tel aviv protest',
            'hostage families', 'bring them home', 'hostage deal',
            'gantz threatens', 'gallant threatens', 'coalition collapse',
            'israel election', 'netanyahu resign', 'protests tel aviv',
            'הפגנות ישראל', 'משפחות החטופים', 'בחירות ישראל',
            'احتجاجات إسرائيل', 'عائلات الرهائن',
        ],
        'baseline_statements_per_week': 6,
    },
}

ACTOR_KEYWORDS = {k: v['keywords'] for k, v in ACTORS.items()}

# Actor classification
INBOUND_ACTORS  = ['iran_threat', 'hezbollah_threat', 'houthi_threat',
                   'hamas_gaza', 'west_bank_civil', 'syria_threat']
OUTBOUND_ACTORS = ['idf_military', 'war_cabinet', 'annexation_bloc',
                   'us_coordination', 'domestic_opposition']


# ============================================
# REPORTING / COORDINATION ACTOR DOWNGRADE
# ============================================
# us_coordination and domestic_opposition report ON events more than threaten
REPORTING_ACTORS = {'us_coordination', 'domestic_opposition'}

REPORTING_LANGUAGE = [
    'condemns', 'condemned', 'denounces', 'calls for ceasefire',
    'urges restraint', 'demands halt', 'protests against',
    'expressed concern', 'deeply concerned', 'calls on israel',
    'pressure on israel', 'in response to', 'following the strike',
    'מגנה', 'קורא להפסקת אש',
    'يدين', 'يطالب بوقف إطلاق النار',
]

# Coordination greenlight language (boosts outbound score, not penalized)
GREENLIGHT_LANGUAGE = [
    'us authorizes', 'us backs', 'green light', 'greenlight',
    'us coordinates with israel', 'joint operation',
    'us israel joint strike', 'us approves', 'washington backs',
    'b-2 bombers deployed', 'carrier group', 'us forces support',
    'diego garcia', 'us air force israel',
]

# Brake/pressure language (coordination signal — reduces escalation probability)
BRAKE_LANGUAGE = [
    'us demands israel halt', 'us pressure israel',
    'us ceasefire pressure', 'washington warns israel',
    'us threatens sanctions israel', 'us blocks arms',
    'us withholds weapons', 'us conditions on israel',
]


# ============================================
# OUTBOUND THREAT VECTORS
# ============================================

# Vector 4: Strike Posture (IDF mobilization, target language)
STRIKE_POSTURE_TRIGGERS = {
    5: [
        'idf ground operation launched', 'israel invades',
        'israel strikes iran', 'israeli jets over iran',
        'israel begins ground offensive', 'idf enters',
        'israel bombs natanz', 'israel targets nuclear',
        'full scale invasion', 'idf crosses border',
    ],
    4: [
        'idf prepares strike', 'israel readying attack',
        'idf mobilizes reserves', 'israel on war footing',
        'war cabinet approves strike', 'netanyahu authorizes',
        'idf aircraft deployed', 'israel imminent strike',
        'target package approved', 'idf special forces',
        'aerial refueling israel', 'f-35 long range',
    ],
    3: [
        'idf warns', 'israel will strike', 'israel has right to',
        'israel will not tolerate', 'israel reserves right',
        'idf on high alert', 'israel military buildup',
        'israel forces massing', 'strike authorization',
        'war cabinet convenes', 'security cabinet emergency',
    ],
    2: [
        'idf operation', 'israel military operation',
        'israel strikes', 'israeli airstrike',
        'idf targeted strike', 'precision strike israel',
        'israel eliminates', 'israel neutralizes',
    ],
    1: [
        'idf', 'israel military', 'israeli forces',
        'israel strikes', 'iaf', 'israeli jets',
    ],
}

# Vector 5: Annexation / Expansion Posture
ANNEXATION_TRIGGERS = {
    5: [
        'israel annexes west bank', 'formal annexation',
        'israel applies sovereignty entire', 'knesset votes annexation',
        'annex west bank officially', 'apply israeli law west bank',
    ],
    4: [
        'smotrich annexation plan', 'ben gvir calls annexation',
        'israel to apply sovereignty', 'west bank annexation vote',
        'new settlement bloc approved', 'massive settlement expansion',
        'outpost retroactively legalized mass', 'settle entire west bank',
    ],
    3: [
        'smotrich settlement', 'ben gvir outpost',
        'settlement expansion west bank', 'new outpost',
        'israel sovereignty west bank', 'greater israel rhetoric',
        'legalize outpost', 'settlement approved',
        'west bank land seizure', 'palestinians expelled',
    ],
    2: [
        'settlement west bank', 'settler activity',
        'outpost west bank', 'annexation rhetoric',
        'smotrich', 'ben gvir', 'west bank sovereignty',
    ],
    1: [
        'settlement', 'settler', 'west bank',
        'annexation', 'smotrich', 'ben gvir',
    ],
}


# ============================================
# INBOUND THREAT VECTORS
# ============================================

# Vector 1: Ballistic Threat (Iran/proxy missiles targeting Israel)
BALLISTIC_TRIGGERS = {
    5: [
        'iran fires ballistic missile at israel', 'ballistic missile hits israel',
        'iran wave of missiles israel', 'operation true promise hits',
        'dimona struck', 'haifa nuclear struck',
        'iranian missile impact israel', 'iran ballistic hits',
        'mass missile attack israel',
    ],
    4: [
        'iran fires missiles at israel', 'ballistic missile israel',
        'iran launches missiles', 'missile barrage israel',
        'hypersonic missile israel', 'iran targets israel',
        'irgc fires at israel', 'missile alert tel aviv',
        'direct hit israel', 'iran missile volley',
    ],
    3: [
        'iran threatens missile attack', 'iran warns will strike',
        'missile threat israel', 'iran preparing strike',
        'iran targets dimona', 'iran targets haifa',
        'iran threatens nuclear facility',
    ],
    2: [
        'iran missile threat', 'ballistic threat israel',
        'iran warns israel', 'missile defense israel',
        'iron dome activated',
    ],
    1: [
        'iran missile', 'ballistic missile', 'iron dome',
        'missile alert', 'tzeva adom',
    ],
}

# Vector 2: Northern Front Inbound (Hezbollah)
NORTHERN_FRONT_TRIGGERS = {
    5: [
        'hezbollah mass rocket attack', 'hezbollah missile salvo',
        'hezbollah ground infiltration', 'hezbollah overruns',
        'hezbollah launches major', 'hezbollah full offensive',
        'radwan force infiltrates', 'hezbollah invades',
    ],
    4: [
        'hezbollah fires rockets north israel', 'hezbollah strikes haifa',
        'hezbollah anti-tank fire', 'hezbollah drone hit',
        'katyusha barrage north', 'hezbollah precision missile',
        'hezbollah targets idf base', 'northern israel under fire',
        'hezbollah claims kills idf',
    ],
    3: [
        'hezbollah fires at', 'rockets north israel',
        'hezbollah threatens north', 'idf northern command alert',
        'northern israel evacuation', 'hezbollah warns',
        'idf north exchange',
    ],
    2: [
        'hezbollah rocket', 'north israel tension',
        'hezbollah fires', 'northern border incident',
    ],
    1: [
        'hezbollah', 'northern front', 'north israel',
        'galilee', 'kiryat shmona',
    ],
}

# Vector 3: Asymmetric Inbound (Hamas, Houthi, West Bank)
ASYMMETRIC_TRIGGERS = {
    5: [
        'hamas mass attack israel', 'hamas invasion israel',
        'houthi hits tel aviv', 'houthi ballistic lands israel',
        'west bank uprising', 'intifada declared',
        'mass rocket fire gaza',
    ],
    4: [
        'rockets from gaza israel', 'hamas fires rockets',
        'houthi missile intercepted israel', 'houthi drone israel',
        'west bank shooting rampage', 'terror attack tel aviv',
        'major attack jerusalem', 'stabbing wave',
    ],
    3: [
        'hamas threatens attack', 'hamas warns israel',
        'rockets gaza', 'houthi targets israel',
        'west bank shooting', 'terror attack israel',
        'jenin attack', 'nablus attack',
    ],
    2: [
        'hamas rocket', 'gaza rocket', 'west bank attack',
        'terror attack', 'houthi threatens israel',
    ],
    1: [
        'hamas', 'gaza', 'houthi israel', 'west bank',
        'terror', 'rocket fire',
    ],
}


# ============================================
# COORDINATION SIGNAL PATTERNS
# ============================================
US_GREENLIGHT_PATTERNS = [
    'us coordinates with israel on iran',
    'us israel joint strike iran', 'b-2 bombers',
    'diego garcia strike', 'carrier deployed',
    'us backs israel military action',
    'us green light', 'washington authorizes',
    'joint us israel operation',
]

US_BRAKE_PATTERNS = [
    'us tells israel not to', 'us warns israel against',
    'us withhold weapons israel', 'us arms embargo israel',
    'washington ceasefire demand israel',
    'us pressure on israel to halt',
    'us conditions military aid israel',
]

EU_SANCTION_PATTERNS = [
    'eu sanctions israel', 'europe sanctions settlers',
    'icc arrest warrant netanyahu', 'icj ruling israel',
    'arms embargo israel europe', 'eu suspends israel',
]


# ============================================
# SPECIFICITY SCORER
# ============================================
SPECIFIC_TARGETS_INBOUND = [
    # Israeli cities/sites targeted by adversaries
    'dimona', 'haifa', 'tel aviv', 'jerusalem',
    'eilat', 'beersheba', 'ashkelon', 'ashdod',
    'netanya', 'ramat david airbase', 'nevatim airbase',
    'hatzerim airbase', 'kirya', 'tel nof',
    # Named weapons
    'fattah-1', 'fattah-2', 'kheibar shekan',
    'emad', 'ghadr', 'shahab', 'hypersonic',
]

SPECIFIC_TARGETS_OUTBOUND = [
    # Targets Israel may strike
    'natanz', 'fordow', 'isfahan', 'bushehr',
    'parchin', 'arak', 'kharg island',
    'dahieh', 'beirut', 'southern lebanon',
    'rafah', 'khan younis', 'jabalia',
    'jenin', 'nablus', 'ramallah',
]

TIME_BOUNDED = [
    'within 24 hours', 'within 48 hours', 'imminent',
    'tonight', 'by tomorrow', 'this week',
    'in the coming hours', 'deadline',
    'ultimatum expires', 'hours away',
    'בשעות הקרובות', 'מיידי',
    'خلال ساعات', 'وشيك',
]

OPERATIONAL_FRAMING = [
    'strike package', 'target package approved',
    'forces in position', 'aircraft airborne',
    'special forces deployed', 'readiness level',
    'authorization received', 'go order',
    'zero hour', 'h-hour', 'd-day',
    'operational readiness', 'strike authorized',
]


def _score_specificity(text):
    score = 0
    for t in SPECIFIC_TARGETS_INBOUND:
        if t in text: score += 1
    for t in SPECIFIC_TARGETS_OUTBOUND:
        if t in text: score += 1
    for tb in TIME_BOUNDED:
        if tb in text: score += 2
    for op in OPERATIONAL_FRAMING:
        if op in text: score += 2
    return min(score, 10)


# ============================================
# THREE-LAYER PIKUD HAOREF ALERT SYSTEM
# ============================================

def _fetch_oref_via_relay():
    """Layer 2: GCP me-west1 relay (Israeli IP). Returns alert data or None."""
    if not OREF_RELAY_URL:
        return None
    try:
        resp = requests.get(
            f"{OREF_RELAY_URL}/api/alerts/history",
            timeout=8
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"[Israel Rhetoric] ✅ Layer 2 (GCP relay): {len(data.get('history', []))} alerts")
            return data
    except Exception as e:
        print(f"[Israel Rhetoric] Layer 2 relay error: {str(e)[:80]}")
    return None


def _fetch_oref_direct():
    """Layer 3: Direct oref.org.il (works from Israeli IP or VPN only)."""
    try:
        resp = requests.get(OREF_HISTORY_URL, headers=OREF_HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[Israel Rhetoric] ✅ Layer 3 (direct oref): {len(data)} alert entries")
            return {'history': data, 'source': 'direct'}
    except Exception as e:
        print(f"[Israel Rhetoric] Layer 3 direct error: {str(e)[:80]}")
    return None


def _fetch_oref_current_direct():
    """Layer 3: Current active alert from oref.org.il."""
    try:
        resp = requests.get(OREF_CURRENT_URL, headers=OREF_HEADERS, timeout=5)
        if resp.status_code == 200:
            raw = resp.text.strip()
            if raw and raw != '':
                data = resp.json()
                if data.get('data'):
                    return data
    except Exception as e:
        print(f"[Israel Rhetoric] Layer 3 current alert error: {str(e)[:60]}")
    return None


def _parse_alert_counts_from_oref(data, hours_back=24):
    """
    Parse Pikud HaOref history data into alert counts by type.
    Returns: {total, rockets, drones, ballistic, by_city, recent_hours}
    """
    counts = {
        'total': 0, 'rockets': 0, 'drones': 0,
        'ballistic': 0, 'other': 0,
        'by_city': {}, 'recent_1h': 0, 'recent_6h': 0,
        'source': data.get('source', 'unknown'),
    }
    history = data.get('history', data if isinstance(data, list) else [])
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_back)

    for alert in history:
        # Parse date
        alert_dt = None
        for date_field in ['alertDate', 'datetime', 'date']:
            val = alert.get(date_field, '')
            if val:
                try:
                    alert_dt = datetime.fromisoformat(str(val).replace(' ', 'T'))
                    if alert_dt.tzinfo is None:
                        alert_dt = alert_dt.replace(tzinfo=timezone.utc)
                    break
                except Exception:
                    pass

        if not alert_dt or alert_dt < cutoff:
            continue

        counts['total'] += 1
        age_hours = (now - alert_dt).total_seconds() / 3600
        if age_hours <= 1:  counts['recent_1h'] += 1
        if age_hours <= 6:  counts['recent_6h'] += 1

        # Categorize by type
        cat = alert.get('category', alert.get('cat', 1))
        title = str(alert.get('title', '')).lower()
        if cat == 1 or 'rocket' in title or 'ירי' in title:
            counts['rockets'] += 1
        elif cat == 2 or 'uav' in title or 'drone' in title or 'כלי טיס' in title:
            counts['drones'] += 1
        elif 'ballistic' in title or 'טיל בליסטי' in title:
            counts['ballistic'] += 1
        else:
            counts['other'] += 1

        # City tracking
        city = alert.get('data', alert.get('city', ''))
        if city:
            city_str = str(city)
            counts['by_city'][city_str] = counts['by_city'].get(city_str, 0) + 1

    return counts


def _parse_alert_counts_from_telegram(telegram_messages, hours_back=24):
    """
    Layer 1: Parse Tzeva Adom alerts from Telegram messages.
    Counts alert-type messages within the time window.
    """
    counts = {
        'total': 0, 'rockets': 0, 'drones': 0,
        'ballistic': 0, 'other': 0,
        'by_city': {}, 'recent_1h': 0, 'recent_6h': 0,
        'source': 'telegram',
    }

    alert_keywords = [
        'rocket alert', 'missile alert', 'tzeva adom', 'red alert',
        'צבע אדום', 'התרעה', 'ירי טילים', 'ירי רקטות',
        'ballistic missile', 'uav alert', 'drone alert',
        'shelter', 'immediate shelter', 'secure space',
    ]

    drone_keywords = ['uav', 'drone', 'כלי טיס עוין', 'חפ"ז', 'drone alert']
    ballistic_keywords = ['ballistic', 'טיל בליסטי', 'ballistic missile']

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_back)

    # City extraction patterns — common Israeli cities
    known_cities = [
        'tel aviv', 'haifa', 'jerusalem', 'eilat', 'ashdod', 'ashkelon',
        'beersheba', 'netanya', 'rishon', 'petah tikva', 'nazareth',
        'tiberias', 'safed', 'kiryat shmona', 'nahariya', 'acre',
        'dimona', 'arad', 'sderot', 'kibbutz', 'moshav',
        # Hebrew common
        'תל אביב', 'חיפה', 'ירושלים', 'אשדוד', 'אשקלון',
        'באר שבע', 'נתניה', 'קריית שמונה', 'נהריה',
    ]

    for msg in telegram_messages:
        pub = msg.get('published', '')
        try:
            pub_dt = datetime.fromisoformat(pub)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue
        except Exception:
            continue

        text = f"{msg.get('title', '')} {msg.get('body', '')}".lower()
        if not any(kw in text for kw in alert_keywords):
            continue

        counts['total'] += 1
        age_hours = (now - pub_dt).total_seconds() / 3600
        if age_hours <= 1: counts['recent_1h'] += 1
        if age_hours <= 6: counts['recent_6h'] += 1

        if any(kw in text for kw in ballistic_keywords):
            counts['ballistic'] += 1
        elif any(kw in text for kw in drone_keywords):
            counts['drones'] += 1
        else:
            counts['rockets'] += 1

        for city in known_cities:
            if city in text:
                counts['by_city'][city] = counts['by_city'].get(city, 0) + 1

    return counts


def fetch_pikud_haoref_alerts(telegram_messages=None, hours_back=24):
    """
    Three-layer Pikud HaOref alert fetch.
    Returns normalized alert counts dict.
    """
    # Check cache first
    cached = _redis_get(ALERTS_CACHE_KEY)
    if cached:
        cache_age = (datetime.now(timezone.utc) -
                     datetime.fromisoformat(cached.get('cached_at', '2000-01-01'))).total_seconds()
        if cache_age < 1800:  # 30-minute cache on alerts
            print(f"[Israel Rhetoric] Using cached alert counts (age: {int(cache_age/60)}m)")
            return cached

    alert_data = None
    alert_counts = None

    # Layer 2: GCP relay (Israeli IP)
    if not alert_data:
        alert_data = _fetch_oref_via_relay()
        if alert_data:
            alert_counts = _parse_alert_counts_from_oref(alert_data, hours_back)

    # Layer 3: Direct (Israeli IP / VPN)
    if not alert_data:
        alert_data = _fetch_oref_direct()
        if alert_data:
            alert_counts = _parse_alert_counts_from_oref(alert_data, hours_back)

    # Layer 1: Telegram fallback (always available, no geo-block)
    if not alert_counts and telegram_messages:
        print(f"[Israel Rhetoric] Using Layer 1 (Telegram) for alert counts")
        alert_counts = _parse_alert_counts_from_telegram(telegram_messages, hours_back)

    if not alert_counts:
        alert_counts = {
            'total': 0, 'rockets': 0, 'drones': 0, 'ballistic': 0,
            'other': 0, 'by_city': {}, 'recent_1h': 0, 'recent_6h': 0,
            'source': 'unavailable',
        }

    alert_counts['cached_at'] = datetime.now(timezone.utc).isoformat()
    alert_counts['hours_back'] = hours_back

    # Cache alert counts
    _redis_set(ALERTS_CACHE_KEY, alert_counts, ttl=1800)

    total = alert_counts['total']
    print(f"[Israel Rhetoric] 🚨 Pikud HaOref: {total} alerts in {hours_back}h "
          f"(rockets={alert_counts['rockets']}, drones={alert_counts['drones']}, "
          f"ballistic={alert_counts['ballistic']}, source={alert_counts['source']})")

    return alert_counts


def _score_inbound_from_alerts(alert_counts):
    """
    Convert alert counts to escalation level for inbound dashboard.
    Ballistic > drone > rocket in severity weighting.
    """
    if not alert_counts:
        return 0

    total = alert_counts.get('total', 0)
    ballistic = alert_counts.get('ballistic', 0)
    drones = alert_counts.get('drones', 0)
    recent_1h = alert_counts.get('recent_1h', 0)

    if ballistic >= 3 or total >= 50 or recent_1h >= 10:
        return 5
    elif ballistic >= 1 or total >= 20 or drones >= 5:
        return 4
    elif total >= 10 or drones >= 2 or recent_1h >= 3:
        return 3
    elif total >= 3:
        return 2
    elif total >= 1:
        return 1
    return 0


# ============================================
# CROSS-THEATER INBOUND THREAT AGGREGATION
# ============================================
def _compute_inbound_threat_from_fingerprints():
    """
    Reads cross-theater fingerprints to build the inbound threat picture.
    Returns per-actor inbound levels + threat convergence index.
    """
    result = {
        'iran_level': 0,
        'lebanon_level': 0,
        'yemen_level': 0,
        'syria_level': 0,
        'iraq_level': 0,
        'iran_is_command_node': False,
        'threat_convergence_index': 0,
        'convergence_signal': '',
        'fingerprints_age': {},
    }
    try:
        fingerprints = _redis_get(CROSSTHEATER_KEY) or {}
        if not fingerprints:
            return result

        now = datetime.now(timezone.utc)
        theater_map = {
            'iran':    'iran_level',
            'lebanon': 'lebanon_level',
            'yemen':   'yemen_level',
            'syria':   'syria_level',
            'iraq':    'iraq_level',
        }

        for theater, key in theater_map.items():
            fp = fingerprints.get(theater, {})
            if not fp:
                continue
            try:
                age_h = (now - datetime.fromisoformat(fp['ts'])).total_seconds() / 3600
                if age_h <= 24:
                    result[key] = fp.get('level', 0)
                    result['fingerprints_age'][theater] = round(age_h, 1)
                    if theater == 'iran' and fp.get('is_command_node'):
                        result['iran_is_command_node'] = True
            except Exception:
                pass

        # Threat convergence index — how many Iran-controlled theaters
        # are simultaneously elevated against Israel
        iran_lv    = result['iran_level']
        lebanon_lv = result['lebanon_level']
        yemen_lv   = result['yemen_level']
        syria_lv   = result['syria_level']
        iraq_lv    = result['iraq_level']

        # Primary threats: Iran + Lebanon (active war) + Yemen (ballistic)
        primary_elevated = sum(1 for lv in [iran_lv, lebanon_lv, yemen_lv] if lv >= 3)
        # Secondary: Syria, Iraq (lower weight)
        secondary_elevated = sum(1 for lv in [syria_lv, iraq_lv] if lv >= 2)

        if primary_elevated >= 3:
            tci = 5
            result['convergence_signal'] = 'Full axis activation — Iran + Lebanon + Yemen all elevated against Israel'
        elif primary_elevated == 2 and secondary_elevated >= 1:
            tci = 4
            result['convergence_signal'] = 'Multi-front convergence — primary + secondary theaters active'
        elif primary_elevated == 2:
            tci = 3
            result['convergence_signal'] = 'Dual primary threat — two major Iran-axis theaters elevated'
        elif primary_elevated == 1 and secondary_elevated >= 1:
            tci = 2
            result['convergence_signal'] = 'Elevated primary + secondary threat signals'
        elif primary_elevated == 1 or secondary_elevated >= 1:
            tci = 1
            result['convergence_signal'] = 'Single theater elevated'
        else:
            tci = 0

        result['threat_convergence_index'] = tci
        print(f"[Israel Rhetoric] 🎯 Threat Convergence Index: {tci} "
              f"(Iran L{iran_lv}, Lebanon L{lebanon_lv}, Yemen L{yemen_lv})")

    except Exception as e:
        print(f"[Israel Rhetoric] Fingerprint read error: {e}")

    return result


# ============================================
# DELTA
# ============================================
def _compute_delta():
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
        prior_avg = round(sum(e.get('score', 0) for e in prior) / len(prior), 1)
        sc = round(current.get('score', 0) - prior_avg, 1)
        return {
            'direction': 'rising' if sc > 10 else 'falling' if sc < -10 else 'stable',
            'score_change': sc,
            'current_score': current.get('score', 0),
            'prior_avg_score': prior_avg,
            'vs_period': f'{len(prior)}-scan average',
        }
    except Exception as e:
        print(f"[Israel Rhetoric] Delta error: {e}")
        return None


# ============================================
# ACTOR BASELINES
# ============================================
def _update_actor_baselines(actor_results):
    try:
        existing = _redis_get(BASELINE_KEY) or {}
        updated = {}
        alpha = 0.2
        for actor_id, ar in actor_results.items():
            prev = existing.get(actor_id, {})
            cs = ar.get('statement_count', 0)
            cl = ar.get('max_level', 0)
            if not prev:
                updated[actor_id] = {'avg_statements': cs, 'avg_level': cl, 'scans': 1}
            else:
                updated[actor_id] = {
                    'avg_statements': round(alpha * cs + (1-alpha) * prev.get('avg_statements', cs), 2),
                    'avg_level': round(alpha * cl + (1-alpha) * prev.get('avg_level', cl), 3),
                    'scans': min(prev.get('scans', 1) + 1, 999),
                }
        _redis_set(BASELINE_KEY, updated, ttl=30*24*3600)
        return updated
    except Exception as e:
        print(f"[Israel Rhetoric] Baseline error: {e}")
        return {}


def _detect_silence_anomalies(actor_results, baselines):
    anomalies = []
    for actor_id, ar in actor_results.items():
        baseline = baselines.get(actor_id, {})
        avg = baseline.get('avg_statements', 0)
        scans = baseline.get('scans', 0)
        if scans < 5 or avg < 3:
            continue
        actual = ar.get('statement_count', 0)
        if actual < avg * 0.30:
            pct = round((1 - actual / avg) * 100)
            actor_info = ACTORS.get(actor_id, {})
            anomalies.append({
                'actor_id': actor_id,
                'actor_name': actor_info.get('name', actor_id),
                'actor_flag': actor_info.get('flag', ''),
                'deviation': f'{pct}% below baseline',
                'signal': 'Unusual quiet — possible operational security',
            })
    return anomalies


# ============================================
# CROSS-THEATER — Israel writes as strike actor
# ============================================
def _write_crosstheater_signal(result):
    """Israel writes is_strike_actor: True to shared fingerprint."""
    try:
        existing = _redis_get(CROSSTHEATER_KEY) or {}

        actors = result.get('actors', {})
        top_phrases = []
        for actor_id in ['idf_military', 'war_cabinet', 'annexation_bloc']:
            for art in actors.get(actor_id, {}).get('top_articles', [])[:2]:
                t = art.get('title', '')[:60]
                if t: top_phrases.append(t)

        named_targets = []
        for art in actors.get('idf_military', {}).get('top_articles', [])[:3]:
            text = art.get('title', '').lower()
            for tgt in SPECIFIC_TARGETS_OUTBOUND:
                if tgt in text and tgt not in named_targets:
                    named_targets.append(tgt)

        existing['israel'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Israel',
            'is_strike_actor': True,
            'level': result.get('theatre_escalation_level', 0),
            'score': result.get('theatre_score', 0),
            'theatre_score': result.get('theatre_score', 0),
            'inbound_level': result.get('inbound_max_level', 0),
            'outbound_level': result.get('outbound_max_level', 0),
            'threat_convergence_index': result.get('threat_convergence_index', 0),
            'strike_posture_level': result.get('strike_posture_level', 0),
            'annexation_level': result.get('annexation_level', 0),
            'alerts_24h': result.get('alerts_24h', {}).get('total', 0),
            'top_phrases': top_phrases[:5],
            'named_targets': named_targets[:6],
            'specificity_score': result.get('specificity_score', 0),
        }

        _redis_set(CROSSTHEATER_KEY, existing, ttl=8*3600)
        print(f"[Israel Rhetoric] ✅ Strike actor fingerprint written (is_strike_actor: True)")
    except Exception as e:
        print(f"[Israel Rhetoric] Cross-theater write error: {e}")


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
        print(f"[Israel Rhetoric Redis] GET error: {e}")
    return None


def _redis_set(key, value, ttl=RHETORIC_CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str)
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/set/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                     "Content-Type": "application/json"},
            data=payload,
            params={"EX": ttl},
            timeout=5
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f"[Israel Rhetoric Redis] SET error: {e}")
    return False


# ============================================
# RSS FEEDS
# ============================================
RHETORIC_RSS_FEEDS = [
    # IDF / Israeli official
    ("https://www.idf.il/en/rss/", 1.0),
    # Israeli news — outbound posture
    ("https://news.google.com/rss/search?q=IDF+strikes+operation+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Israel+Iran+strike+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Netanyahu+war+cabinet+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Smotrich+annexation+West+Bank+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Ben+Gvir+settlement+West+Bank&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=IDF+ground+operation+Lebanon+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Israel+Gaza+operation+2026&hl=en&gl=US&ceid=US:en", 0.9),
    # Inbound threat — adversary rhetoric
    ("https://news.google.com/rss/search?q=Hezbollah+fires+Israel+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iran+missile+Israel+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Houthi+missile+Israel+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Hamas+rockets+Israel+2026&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=West+Bank+settler+violence+2026&hl=en&gl=US&ceid=US:en", 0.9),
    # US coordination
    ("https://news.google.com/rss/search?q=US+Israel+Iran+coordination+2026&hl=en&gl=US&ceid=US:en", 0.95),
    # Hebrew
    ("https://news.google.com/rss/search?q=צה\"ל+מבצע+2026&hl=iw&gl=IL&ceid=IL:iw", 1.0),
    ("https://news.google.com/rss/search?q=סמוטריץ+סיפוח+גדה&hl=iw&gl=IL&ceid=IL:iw", 1.0),
    ("https://news.google.com/rss/search?q=ישראל+איראן+תקיפה+2026&hl=iw&gl=IL&ceid=IL:iw", 1.0),
    # Arabic
    ("https://news.google.com/rss/search?q=إسرائيل+عملية+2026&hl=ar&gl=SA&ceid=SA:ar", 0.95),
    ("https://news.google.com/rss/search?q=الضفة+الغربية+ضم+مستوطنات&hl=ar&gl=SA&ceid=SA:ar", 0.95),
]

# Additional RSS feeds (v2.2)
RHETORIC_RSS_FEEDS += [
    # Hezbollah daily operational claims
    ("https://news.google.com/rss/search?q=Hezbollah+rocket+salvo+Israel+2026&hl=en&gl=US&ceid=US:en", 1.1),
    ("https://news.google.com/rss/search?q=Hezbollah+targets+northern+Israel+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Kiryat+Shmona+rocket+Hezbollah&hl=en&gl=US&ceid=US:en", 1.0),
    # Houthi conflict entry / solidarity signals
    ("https://news.google.com/rss/search?q=Houthi+operation+Israel+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Ansar+Allah+missile+Israel+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Yemen+enters+war+Israel+Gaza&hl=en&gl=US&ceid=US:en", 0.95),
    # Israel Katz / Lebanon occupation
    ("https://news.google.com/rss/search?q=Israel+Katz+Lebanon+occupation+2026&hl=en&gl=US&ceid=US:en", 1.1),
    ("https://news.google.com/rss/search?q=Israel+south+Lebanon+buffer+zone+2026&hl=en&gl=US&ceid=US:en", 1.0),
    # Trump / US coordination
    ("https://news.google.com/rss/search?q=Trump+Israel+Iran+2026&hl=en&gl=US&ceid=US:en", 1.1),
    ("https://news.google.com/rss/search?q=Trump+Israel+ceasefire+hostages+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=CENTCOM+Israel+Middle+East+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Rubio+Israel+Iran+2026&hl=en&gl=US&ceid=US:en", 0.95),
    # Truth Social / Trump direct
    ("https://truthsocial.com/@realDonaldTrump.rss", 1.2),
]

# ============================================
# NITTER -- Primary source Twitter/X accounts
# ============================================
NITTER_MIRRORS = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.tiekoetter.com",
]

NITTER_ACCOUNTS_ISRAEL = [
    # US policy — greenlight/brake signals
    ("realDonaldTrump", 1.2, "Trump — Israel/Iran/ceasefire direct statements"),
    ("SecRubio",        1.1, "US SecState — Israel policy, Iran deal signals"),
    ("CENTCOM",         1.0, "CENTCOM — regional force posture, Houthi strikes"),
    ("StateDept",       1.0, "State Dept — ceasefire pressure, diplomatic signals"),
    ("POTUS",           1.0, "White House — executive Israel statements"),
    ("Witkoff",         1.1, "Steve Witkoff — hostage/ceasefire envoy"),
    # IDF / Israeli official
    ("IDF",             1.2, "IDF official — strike claims, operational language"),
    ("AvichayAdraee",   1.1, "IDF Arabic spokesperson — Arabic-language claims"),
    ("IsraeliPM",       1.1, "Israeli PM office — Netanyahu statements"),
    # Hezbollah / inbound monitoring
    ("ManarNewsEN",     1.1, "Al-Manar English — Hezbollah operational claims"),
    ("AlMayadeenEng",   1.0, "Al Mayadeen — Hezbollah/resistance claims"),
    # Houthi monitoring
    ("YemenArmy1",      1.0, "Houthi military — operation announcements"),
    ("AnsarAllahPK",    1.0, "Ansar Allah — conflict entry/operation claims"),
    # Analysis
    ("LongWarJournal",  0.9, "Long War Journal — operational analysis"),
]


def _fetch_nitter_israel(username, weight=1.0, timeout=8):
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
                print(f"[Israel Rhetoric/Nitter] @{username}: {len(posts)} posts via {mirror}")
                return posts
        except Exception as e:
            print(f"[Israel Rhetoric/Nitter] @{username} {mirror} failed: {str(e)[:60]}")
            continue
    print(f"[Israel Rhetoric/Nitter] @{username}: all mirrors failed")
    return []


def fetch_nitter_israel(days=3):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen = set()
    for username, weight, desc in NITTER_ACCOUNTS_ISRAEL:
        posts = _fetch_nitter_israel(username, weight=weight)
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
    print(f"[Israel Rhetoric/Nitter] Total: {len(all_posts)} posts")
    return all_posts

REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
ISRAEL_SUBREDDITS = ['IsraelPalestine', 'geopolitics', 'CredibleDefense',
                     'worldnews', 'Israel', 'Palestine']
ISRAEL_REDDIT_KEYWORDS = [
    'idf strike', 'israel iran', 'annexation west bank', 'smotrich',
    'hezbollah israel', 'hamas attack', 'west bank settler',
    'netanyahu war', 'israel operation',
]


def fetch_reddit_israel(days=3):
    time_filter = 'day' if days <= 1 else 'week' if days <= 7 else 'month'
    query = ' OR '.join(ISRAEL_REDDIT_KEYWORDS[:4])
    posts = []
    for subreddit in ISRAEL_SUBREDDITS:
        try:
            time.sleep(2)
            resp = requests.get(
                f'https://www.reddit.com/r/{subreddit}/search.json',
                params={'q': query, 'restrict_sr': 'true', 'sort': 'new',
                        't': time_filter, 'limit': 25},
                headers={'User-Agent': REDDIT_USER_AGENT}, timeout=10
            )
            if resp.status_code != 200:
                continue
            for post in resp.json().get('data', {}).get('children', []):
                pd = post.get('data', {})
                title = pd.get('title', '')
                if not any(kw in f"{title} {pd.get('selftext','')}".lower()
                           for kw in ISRAEL_REDDIT_KEYWORDS):
                    continue
                posts.append({
                    'title': title[:200],
                    'url': f"https://www.reddit.com{pd.get('permalink','')}",
                    'published': datetime.fromtimestamp(
                        pd.get('created_utc', 0), tz=timezone.utc).isoformat(),
                    'description': pd.get('selftext', '')[:300],
                    'source': f'r/{subreddit}', 'weight': 0.9,
                })
            print(f"[Israel Rhetoric/Reddit] r/{subreddit}: {len(posts)} posts")
        except Exception as e:
            print(f"[Israel Rhetoric/Reddit] r/{subreddit} error: {e}")
    return posts


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
                    'title': title, 'url': url,
                    'published': pub_str if isinstance(pub_str, str) else '',
                    'description': desc[:300],
                    'source': feed_url.split('q=')[1].split('&')[0] if 'q=' in feed_url else 'RSS',
                    'weight': weight,
                })
        except Exception as e:
            print(f"[Israel Rhetoric RSS] Error: {str(e)[:80]}")

    print(f"[Israel Rhetoric] RSS: {len(articles)} articles")

    tg_messages = []
    if TELEGRAM_AVAILABLE:
        try:
            tg_messages = fetch_telegram_signals_israel(hours_back=days * 24)
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
                    'description': msg.get('body', msg.get('title', ''))[:500],
                    'source': msg.get('source', 'Telegram'),
                    'weight': 1.2,
                    'views': msg.get('views', 0),
                })
                tg_count += 1
            print(f"[Israel Rhetoric] Telegram: {tg_count} messages")
        except Exception as e:
            print(f"[Israel Rhetoric] Telegram error: {e}")

    try:
        articles.extend(fetch_reddit_israel(days=days))
    except Exception as e:
        print(f"[Israel Rhetoric] Reddit error: {e}")

    # Nitter — primary source accounts (v2.2)
    try:
        nitter_posts = fetch_nitter_israel(days=days)
        articles.extend(nitter_posts)
    except Exception as e:
        print(f"[Israel Rhetoric] Nitter error: {e}")

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
    print(f"[Israel Rhetoric] Total unique: {len(unique)} ({rss_c} RSS + {tg_c} TG + {nit_c} Nitter + {red_c} Reddit)")
    return unique, tg_messages


# ============================================
# CLASSIFY ARTICLES
# ============================================
def classify_articles(articles):
    actor_results = {
        actor_id: {
            'name': info['name'], 'flag': info['flag'],
            'icon': info['icon'], 'color': info['color'],
            'role': info['role'],
            'statement_count': 0,
            'strike_posture_score': 0,
            'annexation_score': 0,
            'ballistic_score': 0,
            'northern_score': 0,
            'asymmetric_score': 0,
            'max_level': 0,
            'top_articles': [],
            'silence_alert': False,
            'specificity_scores': [],
            'greenlight_signals': [],
            'brake_signals': [],
        }
        for actor_id, info in ACTORS.items()
    }

    theatre_summary = {
        'strike_posture_max': 0,
        'annexation_max': 0,
        'ballistic_max': 0,
        'northern_max': 0,
        'asymmetric_max': 0,
        'total_articles': len(articles),
        'coordination_signals': [],
        'all_specificity_scores': [],
    }

    for article in articles:
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        pub_date = article.get('published', '')

        spec_score = _score_specificity(text)
        if spec_score > 0:
            theatre_summary['all_specificity_scores'].append(spec_score)

        is_reporting = any(p in text for p in REPORTING_LANGUAGE)
        is_greenlight = any(p in text for p in US_GREENLIGHT_PATTERNS)
        is_brake = any(p in text for p in US_BRAKE_PATTERNS)

        # Multi-actor matching
        matched = []
        for actor_id in ACTORS:
            for kw in ACTOR_KEYWORDS.get(actor_id, []):
                if kw.lower() in text:
                    matched.append(actor_id)
                    break

        if not matched:
            continue

        for actor_id in matched:
            ar = actor_results[actor_id]
            ar['statement_count'] += 1
            if spec_score > 0:
                ar['specificity_scores'].append(spec_score)
            if is_greenlight:
                ar['greenlight_signals'].append(article.get('title', '')[:80])
            if is_brake:
                ar['brake_signals'].append(article.get('title', '')[:80])

            if len(ar['top_articles']) < 5:
                ar['top_articles'].append({
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', ''),
                    'published': pub_date,
                    'specificity_score': spec_score,
                })

            is_reporting_ctx = is_reporting and actor_id in REPORTING_ACTORS

            for level in range(5, 0, -1):
                # Outbound: Strike Posture
                for kw in STRIKE_POSTURE_TRIGGERS.get(level, []):
                    if kw in text:
                        eff = 2 if is_reporting_ctx and level >= 3 else level
                        if eff > ar['strike_posture_score']:
                            ar['strike_posture_score'] = eff
                        if level > theatre_summary['strike_posture_max']:
                            theatre_summary['strike_posture_max'] = level
                        break

                # Outbound: Annexation
                for kw in ANNEXATION_TRIGGERS.get(level, []):
                    if kw in text:
                        eff = 2 if is_reporting_ctx and level >= 3 else level
                        if eff > ar['annexation_score']:
                            ar['annexation_score'] = eff
                        if level > theatre_summary['annexation_max']:
                            theatre_summary['annexation_max'] = level
                        break

                # Inbound: Ballistic
                for kw in BALLISTIC_TRIGGERS.get(level, []):
                    if kw in text:
                        if level > ar['ballistic_score']:
                            ar['ballistic_score'] = level
                        if level > theatre_summary['ballistic_max']:
                            theatre_summary['ballistic_max'] = level
                        break

                # Inbound: Northern Front
                for kw in NORTHERN_FRONT_TRIGGERS.get(level, []):
                    if kw in text:
                        if level > ar['northern_score']:
                            ar['northern_score'] = level
                        if level > theatre_summary['northern_max']:
                            theatre_summary['northern_max'] = level
                        break

                # Inbound: Asymmetric
                for kw in ASYMMETRIC_TRIGGERS.get(level, []):
                    if kw in text:
                        if level > ar['asymmetric_score']:
                            ar['asymmetric_score'] = level
                        if level > theatre_summary['asymmetric_max']:
                            theatre_summary['asymmetric_max'] = level
                        break

        # Coordination signals
        if is_greenlight:
            theatre_summary['coordination_signals'].append({
                'type': 'greenlight',
                'message': 'US coordination greenlight signal detected',
                'article': article.get('title', '')[:100],
                'published': pub_date,
            })
        if is_brake:
            theatre_summary['coordination_signals'].append({
                'type': 'brake',
                'message': 'US/EU brake/pressure signal detected',
                'article': article.get('title', '')[:100],
                'published': pub_date,
            })

        # HTS-style: annexation bloc + IDF coordinated language
        if 'annexation_bloc' in matched and 'idf_military' in matched:
            theatre_summary['coordination_signals'].append({
                'type': 'political_military_sync',
                'message': 'Annexation rhetoric coincides with IDF operation language',
                'article': article.get('title', '')[:100],
                'published': pub_date,
            })

    # Finalize actors
    for actor_id, ar in actor_results.items():
        ar['max_level'] = max(
            ar['strike_posture_score'], ar['annexation_score'],
            ar['ballistic_score'], ar['northern_score'], ar['asymmetric_score']
        )
        ar['escalation_level'] = ar['max_level']
        ar['escalation_label'] = ESCALATION_LEVELS.get(ar['max_level'], {}).get('label', 'Baseline')
        ar['escalation_color'] = ESCALATION_LEVELS.get(ar['max_level'], {}).get('color', '#6b7280')

        baseline = ACTORS[actor_id].get('baseline_statements_per_week', 3)
        ar['silence_alert'] = ar['statement_count'] == 0 and baseline * (3/7) >= 2

        specs = ar.pop('specificity_scores', [])
        ar['specificity_score'] = round(sum(specs) / len(specs), 1) if specs else 0

    return actor_results, theatre_summary


# ============================================
# SCORING — TWO DASHBOARDS
# ============================================
def _calculate_scores(theatre_summary, inbound_from_fingerprints,
                      alert_counts, actor_results):
    """
    Compute inbound and outbound dashboard scores separately.
    Inbound: reads fingerprints + alerts as PRIMARY input
    Outbound: reads article scanning as primary input
    """
    # ── INBOUND SCORE ──
    # Fingerprints are the primary source — trust the specialist trackers
    tci = inbound_from_fingerprints.get('threat_convergence_index', 0)
    iran_lv    = inbound_from_fingerprints.get('iran_level', 0)
    lebanon_lv = inbound_from_fingerprints.get('lebanon_level', 0)
    yemen_lv   = inbound_from_fingerprints.get('yemen_level', 0)
    alert_lv   = _score_inbound_from_alerts(alert_counts)

    # Weight: Iran (25%) + Lebanon (25%) + Yemen (15%) + TCI (20%) + Alerts (15%)
    inbound_weighted = (
        iran_lv * 0.25 +
        lebanon_lv * 0.25 +
        yemen_lv * 0.15 +
        tci * 0.20 +
        alert_lv * 0.15
    )
    # Also factor in article-detected ballistic/northern signals
    ballistic_art = theatre_summary['ballistic_max']
    northern_art  = theatre_summary['northern_max']
    asymmetric_art = theatre_summary['asymmetric_max']
    inbound_weighted += (ballistic_art * 0.10 + northern_art * 0.08 + asymmetric_art * 0.05)

    inbound_score = min(100, int((inbound_weighted / 5) * 80 +
                                  min(alert_counts.get('total', 0), 50) * 0.3))
    inbound_max = max(iran_lv, lebanon_lv, yemen_lv, alert_lv,
                      ballistic_art, northern_art)

    # ── OUTBOUND SCORE ──
    strike = theatre_summary['strike_posture_max']
    annex  = theatre_summary['annexation_max']
    asymm  = theatre_summary['asymmetric_max']  # Hamas/West Bank

    # Greenlight signals boost outbound
    greenlight_count = sum(
        len(ar.get('greenlight_signals', []))
        for ar in actor_results.values()
    )
    brake_count = sum(
        len(ar.get('brake_signals', []))
        for ar in actor_results.values()
    )

    outbound_weighted = (strike * 0.45 + annex * 0.35 + asymm * 0.20)
    outbound_score = min(100, int((outbound_weighted / 5) * 75))
    outbound_score += min(greenlight_count * 5, 20)  # Greenlight boost
    outbound_score -= min(brake_count * 3, 12)         # Brake drag
    outbound_score = max(0, min(100, outbound_score))
    outbound_max = max(strike, annex)

    # ── OVERALL THEATRE SCORE ──
    # Higher of inbound/outbound, with coordination bonus
    coord_count = len(theatre_summary['coordination_signals'])
    theatre_score = max(inbound_score, outbound_score)
    theatre_score += min(coord_count * 3, 12)
    theatre_score = min(100, theatre_score)

    overall_max = max(inbound_max, outbound_max)

    return {
        'inbound_score': inbound_score,
        'inbound_max_level': inbound_max,
        'outbound_score': outbound_score,
        'outbound_max_level': outbound_max,
        'theatre_score': theatre_score,
        'overall_max': overall_max,
        'greenlight_count': greenlight_count,
        'brake_count': brake_count,
    }


# ============================================
# MAIN SCAN
# ============================================
def run_israel_rhetoric_scan(days=3):
    """
    Full Israel rhetoric scan — dual dashboard architecture.
    Reads cross-theater fingerprints + Pikud HaOref alerts as primary inbound input.
    """
    print(f"\n[Israel Rhetoric] ═══ Starting dual-dashboard scan v1.0 (days={days}) ═══")
    start = datetime.now(timezone.utc)

    # Step 1: Read inbound threat from cross-theater fingerprints
    print("[Israel Rhetoric] 🎯 Reading cross-theater inbound threat picture...")
    inbound_fp = _compute_inbound_threat_from_fingerprints()

    # Step 2: Fetch articles + Telegram (Telegram also used for alert parsing)
    articles, tg_messages = fetch_rhetoric_articles(days)

    # Step 3: Fetch Pikud HaOref alerts (3-layer)
    print("[Israel Rhetoric] 🚨 Fetching Pikud HaOref alerts...")
    alert_counts = fetch_pikud_haoref_alerts(
        telegram_messages=tg_messages, hours_back=24
    )

    # Step 4: Classify articles
    actor_results, theatre_summary = classify_articles(articles)

    # Step 5: Compute scores
    scores = _calculate_scores(theatre_summary, inbound_fp, alert_counts, actor_results)

    overall_max = scores['overall_max']
    theatre_score = scores['theatre_score']

    all_specs = theatre_summary.get('all_specificity_scores', [])
    theatre_specificity = round(sum(all_specs) / len(all_specs), 1) if all_specs else 0
    scan_time = round((datetime.now(timezone.utc) - start).total_seconds(), 1)

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'scanned_at': datetime.now(timezone.utc).isoformat(),
        'days_analyzed': days,
        'total_articles': len(articles),
        'theatre': 'Israel',
        'is_strike_actor': True,

        # Theatre summary
        'theatre_score': theatre_score,
        'theatre_level': overall_max,
        'theatre_escalation_level': overall_max,
        'theatre_escalation_label': ESCALATION_LEVELS.get(overall_max, {}).get('label', 'Baseline'),
        'theatre_escalation_color': ESCALATION_LEVELS.get(overall_max, {}).get('color', '#6b7280'),
        'theatre_escalation_description': ESCALATION_LEVELS.get(overall_max, {}).get('description', ''),

        # ── INBOUND DASHBOARD ──
        'inbound_score': scores['inbound_score'],
        'inbound_max_level': scores['inbound_max_level'],
        'threat_convergence_index': inbound_fp['threat_convergence_index'],
        'convergence_signal': inbound_fp['convergence_signal'],
        # Per-source inbound levels
        'iran_threat_level':      inbound_fp['iran_level'],
        'hezbollah_threat_level': inbound_fp['lebanon_level'],
        'houthi_threat_level':    inbound_fp['yemen_level'],
        'syria_threat_level':     inbound_fp['syria_level'],
        'iraq_threat_level':      inbound_fp['iraq_level'],
        'iran_is_command_node':   inbound_fp['iran_is_command_node'],
        'fingerprints_age':       inbound_fp['fingerprints_age'],
        # Alert vectors
        'alerts_24h': alert_counts,
        'alert_level': _score_inbound_from_alerts(alert_counts),
        # Article-detected inbound
        'ballistic_level': theatre_summary['ballistic_max'],
        'northern_front_level': theatre_summary['northern_max'],
        'asymmetric_level': theatre_summary['asymmetric_max'],

        # ── OUTBOUND DASHBOARD ──
        'outbound_score': scores['outbound_score'],
        'outbound_max_level': scores['outbound_max_level'],
        'strike_posture_level': theatre_summary['strike_posture_max'],
        'annexation_level': theatre_summary['annexation_max'],
        'greenlight_count': scores['greenlight_count'],
        'brake_count': scores['brake_count'],

        # Enriched
        'specificity_score': theatre_specificity,
        'delta': None,
        'silence_anomalies': [],
        'coordination_signals': theatre_summary['coordination_signals'][:5],
        'actors': actor_results,
        'scan_time_seconds': scan_time,
        'version': '1.0.0-israel-dual-dashboard',
    }

    # Cache
    _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(RHETORIC_CACHE_KEY_LEGACY, result)

    # History
    try:
        snapshot = json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'score': theatre_score,
            'level': overall_max,
            'label': ESCALATION_LEVELS.get(overall_max, {}).get('label', 'Baseline'),
            'inbound': scores['inbound_max_level'],
            'outbound': scores['outbound_max_level'],
            'tci': inbound_fp['threat_convergence_index'],
            'alerts_24h': alert_counts.get('total', 0),
            'specificity': theatre_specificity,
        })
        if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
            enc = urllib.parse.quote(snapshot, safe='')
            requests.post(
                f"{UPSTASH_REDIS_URL}/lpush/{HISTORY_KEY}/{enc}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
            requests.post(
                f"{UPSTASH_REDIS_URL}/ltrim/{HISTORY_KEY}/0/119",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
            print(f"[Israel Rhetoric] 📈 History snapshot saved")
    except Exception as e:
        print(f"[Israel Rhetoric] History error (non-fatal): {e}")

    # Baselines + silence
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # Delta
    result['delta'] = _compute_delta()

    # Write fingerprint
    _write_crosstheater_signal(result)

    # Signal interpretation — So What, Red Lines, Historical Patterns
    if INTERPRETER_AVAILABLE:
        try:
            result['interpretation'] = interpret_signals(result)
            best = result['interpretation']['historical_matches']
            best_pct = best[0]['similarity'] if best else 'none'
            print(f"[Israel Rhetoric] ✅ Interpreter: {result['interpretation']['red_lines']['breached_count']} red lines breached, best match: {best_pct}%")
        except Exception as e:
            print(f"[Israel Rhetoric] ⚠️ Interpreter error (non-fatal): {e}")

    # Re-save
    _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(RHETORIC_CACHE_KEY_LEGACY, result)

    print(f"\n[Israel Rhetoric] ✅ Dual-dashboard scan complete in {scan_time}s")
    print(f"[Israel Rhetoric]    Theatre: {result['theatre_escalation_label']} ({overall_max}) | Score: {theatre_score}/100")
    print(f"[Israel Rhetoric]    INBOUND:  L{scores['inbound_max_level']} | TCI: {inbound_fp['threat_convergence_index']} | Alerts 24h: {alert_counts.get('total', 0)}")
    print(f"[Israel Rhetoric]    OUTBOUND: Strike L{theatre_summary['strike_posture_max']} | Annex L{theatre_summary['annexation_max']} | Greenlight: {scores['greenlight_count']}")
    print(f"[Israel Rhetoric]    Iran L{inbound_fp['iran_level']} | Lebanon L{inbound_fp['lebanon_level']} | Yemen L{inbound_fp['yemen_level']}")
    return result


def _bg_scan():
    global _rhetoric_running
    try:
        run_israel_rhetoric_scan()
    except Exception as e:
        print(f"[Israel Rhetoric] Background scan error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


# ============================================
# ROUTE REGISTRATION
# ============================================
def register_israel_rhetoric_routes(app):

    def _periodic():
        time.sleep(120)  # Stagger startup vs other trackers
        print("[Israel Rhetoric] Starting initial scan...")
        _bg_scan()
        while True:
            print(f"[Israel Rhetoric] Sleeping {SCAN_INTERVAL_HOURS}h...")
            time.sleep(SCAN_INTERVAL_HOURS * 3600)
            _bg_scan()

    threading.Thread(target=_periodic, daemon=True).start()
    print(f"[Israel Rhetoric] ✅ Periodic scan thread started ({SCAN_INTERVAL_HOURS}h cycle)")

    @app.route('/api/rhetoric/israel', methods=['GET'])
    def israel_rhetoric_main():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        if force:
            try:
                return jsonify(run_israel_rhetoric_scan())
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)[:200]}), 500

        cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(RHETORIC_CACHE_KEY_LEGACY)
        if cached:
            cached['cached'] = True
            return jsonify(cached)

        global _rhetoric_running
        with _rhetoric_lock:
            if not _rhetoric_running:
                _rhetoric_running = True
                threading.Thread(target=_bg_scan, daemon=True).start()

        return jsonify({
            'success': True, 'awaiting_scan': True,
            'theatre': 'Israel', 'is_strike_actor': True,
            'theatre_score': 0, 'theatre_escalation_level': 0,
            'theatre_escalation_label': 'Scanning...',
            'theatre_escalation_color': '#6b7280',
            'message': 'First scan in progress — reading cross-theater fingerprints + Pikud HaOref...',
            'version': '1.0.0-israel-dual-dashboard',
        })

    @app.route('/api/rhetoric/israel/summary', methods=['GET'])
    def israel_rhetoric_summary_ep():
        cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(RHETORIC_CACHE_KEY_LEGACY)
        if cached:
            return jsonify({
                'success': True,
                'is_strike_actor': True,
                # Core
                'theatre_score':            cached.get('theatre_score', 0),
                'theatre_level':            cached.get('theatre_level', 0),
                'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
                'theatre_escalation_label': cached.get('theatre_escalation_label', 'Baseline'),
                'theatre_escalation_color': cached.get('theatre_escalation_color', '#6b7280'),
                'theatre_label':            cached.get('theatre_escalation_label', 'Baseline'),
                'theatre_color':            cached.get('theatre_escalation_color', '#6b7280'),
                # Inbound dashboard
                'inbound_score':          cached.get('inbound_score', 0),
                'inbound_max_level':      cached.get('inbound_max_level', 0),
                'threat_convergence_index': cached.get('threat_convergence_index', 0),
                'convergence_signal':     cached.get('convergence_signal', ''),
                'iran_threat_level':      cached.get('iran_threat_level', 0),
                'hezbollah_threat_level': cached.get('hezbollah_threat_level', 0),
                'houthi_threat_level':    cached.get('houthi_threat_level', 0),
                'alert_level':            cached.get('alert_level', 0),
                'alerts_24h':             cached.get('alerts_24h', {}),
                'ballistic_level':        cached.get('ballistic_level', 0),
                'northern_front_level':   cached.get('northern_front_level', 0),
                # Outbound dashboard
                'outbound_score':         cached.get('outbound_score', 0),
                'outbound_max_level':     cached.get('outbound_max_level', 0),
                'strike_posture_level':   cached.get('strike_posture_level', 0),
                'annexation_level':       cached.get('annexation_level', 0),
                'greenlight_count':       cached.get('greenlight_count', 0),
                'brake_count':            cached.get('brake_count', 0),
                # v2.0
                'specificity_score':  cached.get('specificity_score', 0),
                'delta':              cached.get('delta'),
                'silence_anomalies':  cached.get('silence_anomalies', []),
                'total_articles':     cached.get('total_articles', 0),
                'timestamp':          cached.get('timestamp'),
                'scanned_at':         cached.get('scanned_at', cached.get('timestamp', '')),
                'cached': True,
            })
        return jsonify({
            'success': False, 'message': 'No cached data — scan in progress',
            'awaiting_scan': True, 'is_strike_actor': True,
        })

    @app.route('/api/rhetoric/israel/history', methods=['GET'])
    def israel_rhetoric_history_ep():
        try:
            limit = max(1, min(int(request.args.get('limit', 120)), 120))
            entries = []
            if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
                resp = requests.get(
                    f"{UPSTASH_REDIS_URL}/lrange/{HISTORY_KEY}/0/{limit-1}",
                    headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=5)
                for item in resp.json().get('result', []):
                    try: entries.append(json.loads(item))
                    except Exception: pass
            entries.reverse()
            return jsonify({
                'success': True, 'theatre': 'Israel',
                'is_strike_actor': True,
                'history_key': HISTORY_KEY,
                'count': len(entries), 'entries': entries,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/rhetoric/israel/alerts', methods=['GET'])
    def israel_alerts_ep():
        """Pikud HaOref alert counts — current 24h window."""
        hours = int(request.args.get('hours', 24))
        force = request.args.get('force', '').lower() in ('true', '1')
        if force:
            # Clear alert cache to force fresh fetch
            _redis_set(ALERTS_CACHE_KEY, {}, ttl=1)
        counts = fetch_pikud_haoref_alerts(hours_back=hours)
        return jsonify({
            'success': True, 'theatre': 'Israel',
            'hours_back': hours,
            'alert_level': _score_inbound_from_alerts(counts),
            'alert_level_label': ESCALATION_LEVELS.get(
                _score_inbound_from_alerts(counts), {}).get('label', 'Baseline'),
            'relay_configured': bool(OREF_RELAY_URL),
            'relay_url_set': bool(OREF_RELAY_URL),
            **counts,
        })

    print("[Israel Rhetoric] ✅ Routes registered: "
          "/api/rhetoric/israel, /api/rhetoric/israel/summary, "
          "/api/rhetoric/israel/history, /api/rhetoric/israel/alerts")
