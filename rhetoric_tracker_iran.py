"""
Asifah Analytics — Iran Rhetoric & Command Node Tracker
v1.0.0 — April 4, 2026
ANALYTICAL FRAME:
Iran is not just an actor — it is the COMMAND NODE of the resistance axis.
This tracker answers two questions:
  1. Is Iran activating or directing its proxy network?
  2. Is Iran preparing to launch new or different strikes itself?

Unlike other trackers that detect what actors SAY, this tracker detects
COMMAND SIGNALS — the patterns that precede proxy activation or direct
Iranian military operations.

KEY INNOVATION — PROXY COORDINATION INDEX:
Reads the shared `rhetoric:crosstheater:fingerprints` Redis key (written by
Yemen, Lebanon, Iraq, Syria trackers) and uses simultaneous proxy elevation
as a direct INPUT to Iran's own score. High cross-theater coordination =
Iran command node likely active.

Iran writes `is_command_node: True` in its own fingerprint so other
trackers can distinguish Iran elevation from proxy elevation.

ACTORS:
- Khamenei / Supreme Leader Office — directive language, fatwa signals
- IRGC / Quds Force — operation announcements, numbered waves, proxy direction
- Iranian Government (Pezeshkian / MFA) — diplomatic cover, escalation framing
- Iranian People / Civil Signals — domestic pressure, protest, economic collapse
- Hezbollah (Iran-directed) — Lebanon proxy activation signals
- Houthi / Ansar Allah (Iran-directed) — Yemen proxy activation signals
- PMF Iraq (Iran-directed) — Iraq proxy activation signals
- Israel (re: Iran) — Israeli strike posture, rhetoric about Iran
- US / CENTCOM (re: Iran) — US strike posture, force movements

FIVE THREAT VECTORS:
1. IRGC DIRECT — IRGC/Quds Force statements, numbered operations, direct strikes
2. PROXY ACTIVATION — Cross-theater coordination index (reads Redis live)
3. NUCLEAR ESCALATION — Natanz, Fordow, enrichment, red lines, ambiguity signals
4. DOMESTIC PRESSURE — Protests, economic collapse, regime stability signals
5. REGIONAL RETALIATION — Hormuz, Gulf states, energy infrastructure threats

SCORING:
  IRGC Direct         weight 3.0 (max 15 pts per level)
  Proxy Activation    weight 2.5 (reads cross-theater Redis — novel input)
  Nuclear Escalation  weight 2.0
  Domestic Pressure   weight 1.0
  Regional Retaliation weight 1.5
  Coordination bonus: +15 if 3+ proxies simultaneously elevated
  Command node bonus: +10 if Iran level >= 4 AND any proxy >= 3

SOURCE STRATEGY:
  Primary:   Telegram (IRAN_CHANNELS — Persian + Arabic + OSINT)
  Secondary: RSS (EN/AR — Iranian state media, opposition, CENTCOM)
  Tertiary:  GDELT (fas: 2-3 focused queries only — GDELT Farsi errors under load)
             GDELT (ara: 3-4 queries), GDELT (eng: standard)
  Reddit:    r/iran (domestic pressure), r/geopolitics, r/CredibleDefense

REDIS KEYS:
  Cache:      rhetoric:iran:latest
  Legacy:     iran_rhetoric_cache
  History:    rhetoric:iran:history
  Baselines:  rhetoric_baseline:iran
  Cross-theater: rhetoric:crosstheater:fingerprints (READS + WRITES)

ENDPOINTS:
  GET /api/rhetoric/iran
  GET /api/rhetoric/iran/summary
  GET /api/rhetoric/iran/history

CHANGELOG:
  v1.0.0 (2026-03-21): Initial build — command node architecture

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
    from iran_signal_interpreter import interpret_signals as iran_interpret_signals
    INTERPRETER_AVAILABLE = True
    print("[Iran Rhetoric] ✅ Signal interpreter loaded")
except ImportError:
    INTERPRETER_AVAILABLE = False
    print("[Iran Rhetoric] ⚠️ Signal interpreter not available")

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
GDELT_BASE_URL      = 'https://api.gdeltproject.org/api/v2/doc/doc'

try:
    from telegram_signals import fetch_telegram_signals_iran
    TELEGRAM_AVAILABLE = True
    print("[Iran Rhetoric] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Iran Rhetoric] ⚠️ Telegram signals not available — RSS/GDELT only")

RHETORIC_CACHE_KEY        = 'rhetoric:iran:latest'
RHETORIC_CACHE_KEY_LEGACY = 'iran_rhetoric_cache'
HISTORY_KEY               = 'rhetoric:iran:history'
BASELINE_KEY              = 'rhetoric_baseline:iran'
CROSSTHEATER_KEY          = 'rhetoric:crosstheater:fingerprints'

RHETORIC_CACHE_TTL  = 6 * 3600
SCAN_INTERVAL_HOURS = 6

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ESCALATION LEVELS
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Baseline',       'color': '#6b7280', 'description': 'No significant signals'},
    1: {'label': 'Rhetoric',       'color': '#3b82f6', 'description': 'Standard state/IRGC statements'},
    2: {'label': 'Warning',        'color': '#f59e0b', 'description': 'Escalatory language, proxy warnings'},
    3: {'label': 'Directive',      'color': '#f97316', 'description': 'Command signals, proxy activation language'},
    4: {'label': 'Operational',    'color': '#ef4444', 'description': 'Strike posture, imminent action signals'},
    5: {'label': 'Active Command', 'color': '#dc2626', 'description': 'Confirmed operations, numbered waves'},
}


# ============================================
# ACTORS
# ============================================
ACTORS = {
    'khamenei': {
        'name': 'Khamenei / Supreme Leader',
        'flag': '🇮🇷',
        'icon': '👁️',
        'color': '#dc2626',
        'role': 'Supreme Command Authority',
        'description': 'Supreme Leader — final authority on IRGC operations and proxy activation',
        'keywords': [
            'khamenei', 'supreme leader', 'rahbar', 'khamenei says',
            'khamenei warns', 'khamenei orders', 'khamenei statement',
            'office of the supreme leader', 'leader of the revolution',
            'ayatollah khamenei', 'ali khamenei',
            'خامنه‌ای', 'رهبر انقلاب', 'مقام معظم رهبری',
            'بیانات رهبری', 'فرمان رهبری',
            'خامنئي', 'المرشد الأعلى', 'ولي الفقيه',
        ],
        'baseline_statements_per_week': 5,
    },
    'irgc': {
        'name': 'IRGC / Quds Force',
        'flag': '🇮🇷',
        'icon': '⚔️',
        'color': '#b91c1c',
        'role': 'Military Command / Proxy Director',
        'description': 'Islamic Revolutionary Guard Corps — conducts direct strikes and directs proxy network',
        'keywords': [
            'irgc', 'revolutionary guard', 'quds force', 'pasdaran',
            'irgc statement', 'irgc announces', 'irgc launches',
            'irgc strikes', 'irgc missile', 'irgc drone',
            'operation true promise', 'true promise', 'wave of attacks',
            'irgc aerospace force', 'irgc navy',
            'esmail qaani', 'qaani', 'irgc commander',
            'sepah', 'سپاه پاسداران', 'نیروی قدس', 'قاسم سلیمانی',
            'عملیات وعده صادق', 'موشک سپاه', 'پهپاد سپاه',
            'حرس الثوري', 'فيلق القدس', 'عملية الوعد الصادق',
            'صواريخ الحرس الثوري',
        ],
        'baseline_statements_per_week': 12,
    },
    'iran_gov': {
        'name': 'Iranian Government / MFA',
        'flag': '🇮🇷',
        'icon': '🏛️',
        'color': '#7c3aed',
        'role': 'Diplomatic Cover / Escalation Framing',
        'description': 'Pezeshkian government and MFA — diplomatic framing, often lags behind IRGC action',
        'keywords': [
            'iran foreign ministry', 'iranian foreign minister',
            'pezeshkian', 'araghchi', 'iran government',
            'tehran says', 'tehran warns', 'tehran threatens',
            'iran official', 'iran state', 'iran president',
            'iran nuclear talks', 'iran diplomacy',
            'وزارت خارجه ایران', 'پزشکیان', 'عراقچی',
            'وزارة الخارجية الإيرانية', 'الحكومة الإيرانية',
            'طهران تحذر', 'إيران الرسمية',
        ],
        'baseline_statements_per_week': 8,
    },
    'iran_people': {
        'name': 'Iranian People / Civil Signals',
        'flag': '🇮🇷',
        'icon': '✊',
        'color': '#0ea5e9',
        'role': 'Domestic Pressure Signal',
        'description': 'Street-level sentiment, protest activity, economic pressure — regime stability indicators',
        'keywords': [
            'iran protests', 'iran protest', 'iranians protest',
            'tehran protest', 'iran demonstrations', 'iran unrest',
            'iran economy', 'iran rial', 'iran inflation',
            'iran sanctions impact', 'iran fuel prices',
            'iran internet shutdown', 'iran dissent',
            'woman life freedom', 'mahsa amini',
            'iran opposition', 'mek iran', 'zan zendegi azadi',
            'اعتراضات ایران', 'اعتراض مردم', 'بحران اقتصادی ایران',
            'تورم ایران', 'احتجاجات إيران', 'الشعب الإيراني',
        ],
        'baseline_statements_per_week': 4,
    },
    'hezbollah_iran': {
        'name': 'Hezbollah (Iran-directed)',
        'flag': '🇱🇧',
        'icon': '🔗',
        'color': '#16a34a',
        'role': 'Lebanon Proxy — Activation Signal',
        'description': 'Hezbollah as Iran proxy — when Hezbollah escalates, Iran likely directed it',
        'keywords': [
            'hezbollah iran', 'iran hezbollah', 'iran directs hezbollah',
            'iran orders hezbollah', 'hezbollah on orders',
            'hezbollah coordination iran', 'nasrallah iran',
            'naim qassem iran', 'iran resistance lebanon',
            'hezbollah operation', 'hezbollah launches', 'hezbollah fires',
            'islamic resistance lebanon', 'resistance axis lebanon',
            'حزب الله وإيران', 'توجيهات إيران لحزب الله',
            'المقاومة الإسلامية لبنان بأوامر إيرانية',
        ],
        'baseline_statements_per_week': 10,
    },
    'houthi_iran': {
        'name': 'Houthi / Ansar Allah (Iran-directed)',
        'flag': '🇾🇪',
        'icon': '🔗',
        'color': '#f59e0b',
        'role': 'Yemen Proxy — Activation Signal',
        'description': 'Houthis as Iran proxy — escalation signals coordinated with IRGC',
        'keywords': [
            # Iran-Houthi coordination
            'houthi iran', 'iran houthi', 'iran directs houthi',
            'iran ansar allah', 'houthi coordination iran',
            'iran red sea', 'iran shipping attacks',
            'houthi missile iran', 'houthi drone iran',
            'iran proxy yemen', 'houthi operation',
            'ansar allah iran coordination',
            # Standalone Houthi operational signals
            'houthi missile', 'houthi ballistic', 'houthi attack',
            'houthi launches', 'houthi fired', 'houthi strike',
            'houthi drone attack', 'houthi targets israel',
            'houthi targets red sea', 'houthi ship attack',
            'ansar allah missile', 'ansar allah attack',
            'ansar allah launches', 'ansar allah strike',
            'houthi israel', 'houthi tel aviv', 'houthi ben gurion',
            'houthi hypersonic', 'houthi ballistic missile israel',
            'true promise', 'wave 84', 'operation yemen',
            'yemen missile israel', 'yemen attack israel',
            'red sea attack', 'bab el-mandeb attack',
            'houthi navy', 'houthi naval', 'houthi blockade',
            # Arabic
            'الحوثيون وإيران', 'توجيهات إيران للحوثيين',
            'إيران والبحر الأحمر', 'عمليات الحوثيين بدعم إيراني',
            'الحوثيون يطلقون', 'صاروخ الحوثيين',
            'هجوم الحوثيين', 'أنصار الله يهاجم',
        ],
        'baseline_statements_per_week': 8,
        'tripwires': [
            'houthi ballistic missile israel',
            'houthi targets tel aviv',
            'houthi hypersonic missile',
            'ansar allah declares war',
            'wave 84',
            'true promise 4',
        ],
    },
    'pmf_iran': {
        'name': 'PMF Iraq (Iran-directed)',
        'flag': '🇮🇶',
        'icon': '🔗',
        'color': '#f97316',
        'role': 'Iraq Proxy — Activation Signal',
        'description': 'PMF/Hashd as Iran proxy — IRGC Quds Force directing Iraq militia operations',
        'keywords': [
            'pmf iran', 'iran pmf', 'iran hashd',
            'iran directs pmf', 'irgc pmf coordination',
            'quds force iraq', 'iran militia iraq',
            'kataib iran', 'iran proxy iraq',
            'islamic resistance iraq iran',
            'الحشد الشعبي وإيران', 'توجيه إيران للحشد',
            'فيلق القدس يوجه الفصائل العراقية',
            'المقاومة الإسلامية في العراق بدعم إيراني',
        ],
        'baseline_statements_per_week': 8,
    },
    # ============================================
    # v1.2.0 (April 2026) — Axis actors SPLIT.
    # Previous single 'china_russia_axis' actor has been split
    # into two dedicated actors because China and Russia play
    # architecturally different roles in supporting Iran:
    #   - China: ISR/logistics enabler (satellites, ground stations,
    #     dual-use components). More covert, harder to detect.
    #   - Russia: Strategic partner (satellite launches, arms,
    #     military coordination). More overt, publicly signaled.
    # Splitting allows accurate attribution and separate
    # cross-theater fingerprint fields per partner.
    # ============================================
    'china_iran_axis': {
        'name': 'China → Iran (Axis Support)',
        'flag': '🇨🇳',
        'icon': '🛰️',
        'color': '#dc2626',
        'role': 'External Military Supporter — China (ISR / Logistics)',
        'description': (
            'China as active supporter of Iran. Sub-categorized across '
            'four dimensions: weapons transfer, ISR/satellite cooperation, '
            'dual-use components, and diplomatic cover. The ISR dimension '
            '(e.g. TEE-01B satellite, Emposat ground stations — FT Apr 2026) '
            'is particularly consequential as it enables kinetic targeting.'
        ),
        'keywords': [
            # China → Iran — weapons / hardware
            'china iran missiles', 'china ships missiles iran',
            'china manpads iran', 'chinese missiles iran',
            'china arms iran', 'china weapons iran',
            'china military aid iran', 'china supplies iran war',
            'china iran shipment', 'chinese shoulder fired iran',
            # China → Iran — ISR / satellite / space cooperation
            'china satellite iran', 'chinese satellite iran',
            'tee-01b', 'emposat', 'earth eye co',
            'chinese spy satellite iran', 'china ground station iran',
            'irgc chinese satellite', 'chinese imagery iran',
            'china targeting data iran', 'chinese isr iran',
            'china space cooperation iran', 'in-orbit transfer iran',
            'chinese satellite irgc', 'belt and road iran space',
            # China → Iran — dual-use
            'china dual use iran', 'china components iran',
            'china chemicals iran military', 'china fuel iran military',
            'china electronics iran', 'china semiconductor iran military',
            # China → Iran — diplomatic cover
            'china intelligence iran', 'beijing tehran military',
            'china iran military cooperation', 'china iran axis',
            'china backs iran', 'beijing backs tehran',
            'china shields iran un', 'china blocks iran sanctions',
            # Arabic / Farsi
            'الصين تسلح إيران', 'الصين تدعم إيران',
            'چین ایران موشک', 'چین ماهواره ایران',
        ],
        'baseline_statements_per_week': 3,
    },

    'russia_iran_axis': {
        'name': 'Russia → Iran (Axis Support)',
        'flag': '🇷🇺',
        'icon': '🚀',
        'color': '#dc2626',
        'role': 'External Military Supporter — Russia (Launch / Arms / Coordination)',
        'description': (
            'Russia as active supporter of Iran. Sub-categorized across '
            'four dimensions: launch partnership (Russian rockets carrying '
            'Iranian satellites), arms/hardware, intelligence sharing, '
            'and strategic coordination. Russia has launched several '
            'Iranian satellites in recent years and provides targeting '
            'data for IRGC strikes on US installations.'
        ),
        'keywords': [
            # Russia → Iran — launch partnership / space
            'russia launches iranian satellite', 'russian rocket iran',
            'russia iran satellite launch', 'soyuz iran satellite',
            'iranian satellite russian launch', 'noor russia launch',
            # Russia → Iran — intelligence / targeting
            'russia satellite iran', 'russia targeting iran',
            'russia intelligence iran', 'russia helps iran',
            'russia iran targeting us ships', 'russia satellite irgc',
            'russia targets us iran', 'russian targeting data iran',
            # Russia → Iran — arms / hardware
            'russia arms iran', 'russia weapons iran',
            'russia supplies iran', 'russia iran military supplies',
            'russia air defense iran', 'russian s-400 iran',
            'russian jets iran', 'sukhoi iran',
            # Russia → Iran — strategic coordination
            'moscow tehran military', 'russia iran military coordination',
            'russia backs iran war', 'russia iran cooperation war',
            'russia food aid iran', 'russia nonlethal iran',
            'russia iran defense pact', 'comprehensive partnership iran russia',
            # Arabic / Farsi
            'روسيا تدعم إيران', 'روسیه ایران حمایت',
            'پرتاب ماهواره ایرانی روسیه',
        ],
        'baseline_statements_per_week': 3,
    },

    'israel_iran': {
        'name': 'Israel (re: Iran)',
        'flag': '🇮🇱',
        'icon': '🔷',
        'color': '#3b82f6',
        'role': 'Adversary / Strike Actor',
        'description': 'Israeli government and IDF — strike posture, shadow war ops, nuclear red lines',
        'keywords': [
            # Direct kinetic / strike language
            'israel iran', 'israel strikes iran', 'idf iran',
            'netanyahu iran', 'israel nuclear iran', 'israel attack iran',
            'israel warns iran', 'israel threatens iran',
            'israel operation iran', 'f-35 iran', 'israeli jets iran',
            'dimona', 'natanz israel', 'israel iran nuclear',
            'israel operation rising lion',
            # Shadow war / covert operations (v2.1)
            'mossad iran', 'mossad operation iran',
            'israel sabotage iran', 'explosion iran israel',
            'iran scientist killed', 'iran nuclear scientist assassinated',
            'israel all options iran', 'israel red line iran',
            'israel preemptive iran', 'israel strike capability iran',
            'iran enrichment israel', 'israel 90 percent iran',
            'israel weapons grade iran', 'israel prevent iran bomb',
            'gallant iran', 'katz iran', 'israel defense minister iran',
            'israel will not allow iran nuclear',
            'israel iran deal opposition', 'israel opposes iran deal',
            'iran deal bad for israel', 'israel nuclear threshold iran',
            # Hebrew
            'מוסד איראן', 'ישראל קו אדום', 'ישראל מניעה איראן',
            'ישראל איראן', 'צה"ל איראן', 'ישראל תוקפת',
            # Arabic
            'إسرائيل إيران', 'الغارات الإسرائيلية على إيران',
            'إسرائيل تضرب إيران', 'الموساد إيران',
            'إسرائيل الخط الأحمر النووي', 'إسرائيل تعارض الاتفاق',
        ],
        'baseline_statements_per_week': 12,
    },
    'us_iran': {
        'name': 'US / CENTCOM (re: Iran)',
        'flag': '🇺🇸',
        'icon': '🛡️',
        'color': '#2563eb',
        'role': 'Adversary / Strike Actor',
        'description': 'US military, Trump, and government — strike posture, deal signals, Iran pressure',
        'keywords': [
            # Military / CENTCOM
            'us strikes iran', 'us attack iran', 'centcom iran',
            'us iran war', 'pentagon iran', 'us military iran',
            'us iran operation', 'us forces iran', 'b-2 iran',
            'carrier iran', 'b-52 iran', 'us bombers iran',
            'us carrier strike group iran', 'us destroys iran',
            # Trump direct statements (v2.1)
            'trump iran', 'trump warns iran', 'trump threatens iran',
            'trump iran deal', 'trump maximum pressure iran',
            'trump bomb iran', 'trump attack iran',
            'trump iran nuclear', 'trump iran sanctions',
            'trump iran 60 days', 'trump iran ultimatum',
            'trump iran letter', 'trump envoy iran',
            'steve witkoff iran', 'witkoff iran deal',
            'rubio iran', 'rubio iran deal', 'rubio iran sanctions',
            # Deal / diplomatic pressure
            'us iran deal', 'us iran nuclear deal', 'us iran talks',
            'us iran negotiations', 'us iran agreement',
            'us iran sanctions', 'snapback iran',
            # Arabic
            'القوات الأمريكية في إيران', 'سنتكوم إيران',
            'الضربات الأمريكية على إيران', 'ترامب إيران',
            'ترامب يهدد إيران', 'أمريكا إيران نووي',
        ],
        'baseline_statements_per_week': 10,
    },
}


# ============================================
# REPORTING ACTOR DOWNGRADE
# ============================================
# iran_gov and iran_people report ON events more than threaten.
# israel_iran and us_iran are adversaries — their language about
# Iran is reporting/analysis, not Iran-directed threats.
REPORTING_ACTORS = {'iran_gov', 'iran_people', 'israel_iran', 'us_iran'}

REPORTING_LANGUAGE = [
    'condemns', 'condemned', 'denounces', 'denounced',
    'calls on', 'calls for', 'urges', 'urged',
    'protests', 'mourns', 'condolences',
    'in response to', 'following the attack',
    'expressed concern', 'deeply concerned',
    'according to', 'reports that', 'confirms that',
    'iran says it will', 'iran claims', 'iran denies',
    'يستنكر', 'استنكر', 'يدين', 'أدان',
    'في أعقاب', 'بعد الهجوم',
    'محکوم می‌کند', 'واکنش نشان داد',
]


# ============================================
# THREAT VECTORS
# ============================================

# Vector 1: IRGC Direct (operation announcements, numbered waves, direct strikes)
IRGC_DIRECT_TRIGGERS = {
    5: [
        'operation true promise', 'wave of attacks iran',
        'irgc launches missiles', 'irgc fires ballistic',
        'iran ballistic missile strike', 'iran drone swarm',
        'iran direct attack', 'iran strikes israel',
        'iran strikes us', 'iran strikes base',
        'عملية الوعد الصادق', 'الموجة', 'سپاه موشک شلیک',
        'حمله مستقیم ایران',
    ],
    4: [
        'irgc operation announced', 'irgc on full alert',
        'quds force deployed', 'iran readying strike',
        'iran strike imminent', 'iran military exercise',
        'iran missile test', 'iran threatens direct attack',
        'iran warns of consequences', 'iran prepares response',
        'سپاه آماده', 'فيلق القدس ينتشر',
        'إيران تستعد للرد',
    ],
    3: [
        'irgc warns', 'quds force warns', 'iran will respond',
        'iran retaliation', 'iran red line crossed',
        'iran will not tolerate', 'we will strike',
        'resistance axis will respond',
        'سپاه هشدار داد', 'الحرس الثوري يحذر',
        'إيران ستنتقم', 'محور المقاومة سيرد',
    ],
    2: [
        'irgc statement', 'iran military statement',
        'iran military drill', 'iran defense posture',
        'iran arms shipment', 'iran weapons transfer',
        'بیانیه سپاه', 'بیانیه نظامی ایران',
        'بيان الحرس الثوري',
    ],
    1: [
        'irgc', 'quds force', 'revolutionary guard',
        'iran military', 'iran missile', 'iran drone',
        'سپاه', 'فيلق القدس', 'حرس الثوري',
    ],
}

# Vector 2: Proxy Activation (computed from Redis cross-theater data — see function below)
# Trigger levels computed dynamically in _compute_proxy_activation_index()

# Vector 3: Nuclear Escalation
NUCLEAR_TRIGGERS = {
    5: [
        'iran nuclear bomb', 'iran nuclear weapon ready',
        'iran weaponizes uranium', 'iran nuclear breakout',
        'iran has nuclear weapon', 'iran detonates',
        'ایران بمب هسته‌ای', 'إيران تمتلك قنبلة نووية',
    ],
    4: [
        'natanz attacked', 'fordow attacked', 'iran nuclear facility struck',
        'iran nuclear program destroyed', 'iran enrichment halted',
        'iran 90 percent enrichment', 'iran weapons grade',
        'نطنز تعرض لهجوم', 'فردو تعرض لهجوم',
        'تأسیسات هسته‌ای ایران مورد حمله',
    ],
    3: [
        'iran enriches uranium', 'iran nuclear threshold',
        'iran breakout timeline', 'iran nuclear red line',
        'iran expels inspectors', 'iran iaea',
        'iran nuclear deal collapsed', 'iran nuclear ambiguity',
        'غنی‌سازی اورانیوم', 'آستانه هسته‌ای ایران',
        'إيران تخصب اليورانيوم', 'الخط الأحمر النووي',
    ],
    2: [
        'iran nuclear talks', 'iran nuclear negotiations',
        'iran nuclear deal', 'jcpoa', 'iran centrifuges',
        'iran nuclear program', 'iran uranium',
        'مذاکرات هسته‌ای', 'برنامه هسته‌ای ایران',
        'مفاوضات نووية إيران', 'البرنامج النووي الإيراني',
    ],
    1: [
        'nuclear iran', 'iran nuclear', 'natanz', 'fordow',
        'arak reactor', 'iran enrichment',
        'هسته‌ای ایران', 'نووي إيران',
    ],
}

# Vector 4: Domestic Pressure (regime stability signals)
DOMESTIC_TRIGGERS = {
    5: [
        'iran regime collapse', 'iran revolution',
        'iran government falls', 'iran uprising',
        'سقوط رژیم', 'انقلاب ایران',
        'انهيار النظام الإيراني',
    ],
    4: [
        'iran massive protests', 'iran widespread unrest',
        'iran security forces open fire', 'iran crackdown',
        'iran internet blackout', 'iran generals arrested',
        'اعتراضات گسترده ایران', 'سرکوب ایران',
        'احتجاجات واسعة في إيران',
    ],
    3: [
        'iran protests', 'iran demonstrations',
        'iran economic crisis', 'iran rial collapse',
        'iran fuel shortage', 'iran power cuts',
        'iran dissent', 'iran opposition',
        'اعتراض ایران', 'بحران اقتصادی',
        'احتجاجات إيران', 'الأزمة الاقتصادية الإيرانية',
    ],
    2: [
        'iran inflation', 'iran sanctions', 'iran economy',
        'iran currency', 'iran unemployment',
        'تورم ایران', 'تحریم‌های ایران',
        'اقتصاد إيران', 'العقوبات على إيران',
    ],
    1: [
        'iran economy', 'iran people', 'iran society',
        'iran civil', 'iran domestic',
        'مردم ایران', 'الشعب الإيراني',
    ],
}

# Vector 5: Regional Retaliation (Hormuz, Gulf states, energy infrastructure)
# Vector 6: Diplomatic Track (de-escalation signals — REDUCES pressure)
# Catches Araghchi shuttles, Pakistan/Oman/Russia mediation, Trump waivers,
# Witkoff envoy activity, JCPOA / nuclear deal language.
DIPLOMATIC_TRIGGERS = {
    5: [
        # Active deal / agreement
        'iran us deal signed', 'iran nuclear deal signed',
        'iran ceasefire signed', 'jcpoa restored',
        'iran agreement reached', 'iran us framework agreed',
        'توافق ایران آمریکا', 'اتفاق نووي إيران أمريكا',
    ],
    4: [
        # Active negotiations / direct talks
        'araghchi pakistan', 'araghchi oman', 'araghchi russia',
        'iran second round talks', 'iran direct talks us',
        'iran nuclear deal talks', 'iran us negotiations',
        'witkoff iran', 'witkoff tehran', 'witkoff araghchi',
        'iran ceasefire negotiations', 'iran us second round',
        'us iran ceasefire talks', 'iran us framework',
        'pakistan iran us mediator', 'oman iran us mediator',
        'مذاکرات ایران آمریکا', 'مفاوضات إيران أمريكا',
    ],
    3: [
        # Mediator activity
        'pakistan mediates iran', 'oman mediates iran',
        'russia mediates iran', 'pakistan brokers iran',
        'envoy visits tehran', 'us envoy iran', 'iran nuclear envoy',
        'islamabad iran us', 'oman shuttle iran',
        'iran nuclear talks resume', 'iran nuclear talks restart',
        'trump extends iran ceasefire', 'trump 90-day waiver',
        'trump iran ceasefire extension', 'jones act waiver',
        'us extends iran ceasefire', 'iran ceasefire extension',
        'iran nuclear envoy', 'special envoy iran',
        'پاکستان وساطت', 'وساطة باكستانية',
    ],
    2: [
        # Diplomatic push
        'iran nuclear talks', 'iran nuclear negotiations',
        'iran us diplomacy', 'iran nuclear diplomacy',
        'iran diplomatic outreach', 'iran ceasefire offer',
        'pakistan iran diplomacy', 'oman iran diplomacy',
        'tehran offers talks', 'iran open to talks',
        'مذاکرات هسته‌ای ایران', 'دبلوماسية إيرانية',
    ],
    1: [
        # Background diplomatic mentions
        'iran diplomacy', 'jcpoa', 'iran deal',
        'iran nuclear program negotiation',
        'دیپلماسی ایران', 'دبلوماسية إيران',
    ],
}


REGIONAL_TRIGGERS = {
    5: [
        'iran closes hormuz', 'iran blockades hormuz',
        'iran attacks saudi', 'iran attacks uae',
        'iran gulf state attack', 'iran oil field attack',
        'iran attacks qatar', 'iran gulf war',
        'ایران تنگه هرمز را می‌بندد',
        'إيران تغلق مضيق هرمز',
    ],
    4: [
        'iran threatens hormuz', 'iran mining hormuz',
        'iran threatens gulf', 'iran threatens saudi',
        'iran oil embargo', 'iran energy attack',
        'iran attacks tanker', 'iran seizes ship',
        'ایران تهدید هرمز', 'إيران تهدد بإغلاق هرمز',
        'إيران تهاجم ناقلة',
    ],
    3: [
        'iran hormuz warning', 'iran gulf tension',
        'iran saudi tension', 'iran uae tension',
        'iran energy weapon', 'iran oil threat',
        'iran shipping disruption',
        'هشدار هرمز', 'تنش خلیج فارس',
        'تحذير مضيق هرمز', 'توتر الخليج',
    ],
    2: [
        'hormuz tension', 'gulf iran', 'iran gulf',
        'iran shipping', 'iran tanker',
        'هرمز', 'خلیج فارس', 'مضيق هرمز',
    ],
    1: [
        'strait of hormuz', 'persian gulf', 'gulf',
        'hormuz', 'iran energy', 'iran oil',
        'تنگه هرمز', 'خلیج', 'النفط الإيراني',
    ],
}

# Operation True Promise detection — numbered wave language
OPERATION_TRUE_PROMISE_PATTERNS = [
    'operation true promise', 'true promise', 'وعده صادق',
    'wave 1', 'wave 2', 'wave 3', 'wave 4', 'wave 5',
    'wave 6', 'wave 7', 'wave 8', 'wave 9', 'wave 10',
    'wave 11', 'wave 12', 'wave 15', 'wave 20', 'wave 25',
    'wave 30', 'wave 40', 'wave 50', 'wave 60', 'wave 70',
    'wave 71', 'wave 72', 'wave 73', 'wave 74', 'wave 75',
    'موجة', 'الموجة', 'عملية الوعد الصادق',
    'موج', 'حمله موج',
]

# Proxy activation language — Iran directing proxies
PROXY_DIRECTIVE_LANGUAGE = [
    'on orders from iran', 'directed by iran', 'iran ordered',
    'at iran direction', 'iran commanded', 'quds force ordered',
    'irgc directed', 'iran activated', 'iran green light',
    'resistance axis coordinated', 'axis of resistance activates',
    'بأوامر إيران', 'بتوجيه إيران', 'الحرس الثوري وجّه',
    'تنسيق المحور', 'به دستور ایران', 'با هماهنگی سپاه',
]

SOFT_POWER_KEYWORDS = {
    4: [
        'iran lego', 'iran rap video', 'iran music video',
        'iranian soft power', 'iran viral video', 'iran meme',
        'iran propaganda video', 'iran influence operation',
        'anti-war iran video', 'iran creative campaign',
    ],
    3: [
        'resistance narrative', 'iran western audience',
        'presstv viral', 'iran social media campaign',
        'iran information war', 'iran narrative control',
        'us aggressor iran', 'iran war crimes us',
        'american imperialism iran', 'iran self defense',
    ],
    2: [
        'resistance framing', 'zionist aggressor',
        'us war criminal', 'martyred iran',
        'iran innocent victims', 'iran civilians',
        'axis of resistance message', 'iran anti-war',
    ],
    1: [
        'resistance', 'oppressor', 'arrogance',
        'great satan', 'zionist entity',
        'iranian people resilient',
    ],
}

# ============================================
# SPECIFICITY SCORER
# ============================================
SPECIFIC_GEOGRAPHIES_IRAN = [
    # Iranian nuclear sites
    'natanz', 'fordow', 'arak', 'isfahan', 'bushehr',
    'parchin', 'khondab',
    # Iranian cities / military
    'tehran', 'mashhad', 'isfahan', 'shiraz', 'tabriz',
    'kharg island', 'bandar abbas', 'chabahar',
    # Proxy theater geographies (when Iran mentions these it's directive)
    'strait of hormuz', 'persian gulf', 'red sea',
    'bab el-mandeb', 'gulf of aden',
    # Israeli targets Iran mentions
    'dimona', 'tel aviv', 'haifa', 'eilat',
    'nevatim', 'ramon airbase',
    # US targets Iran mentions
    'al asad', 'ain al-asad', 'us embassy baghdad',
    'diego garcia', 'us carrier',
    # Omani targets — added v2.4 for cross-theater Oman tracker
    'salalah', 'duqm', 'muscat', 'dhofar', 'sohar',
]

SPECIFIC_ASSETS_IRAN = [
    'ballistic missile', 'hypersonic missile', 'shahab',
    'fateh', 'emad', 'ghadr', 'kheibar shekan',
    'shahed drone', 'shahed-136', 'shahed-238',
    'suicide drone', 'loitering munition',
    'cruise missile iran', 'iran f-14', 'iran navy',
    'ir-6 centrifuge', 'ir-8 centrifuge', '60 percent enriched',
    '90 percent enriched', 'weapons grade uranium',
]

TIME_BOUNDED_IRAN = [
    'within 24 hours', 'within 48 hours', 'within 72 hours',
    'by tomorrow', 'imminent', 'tonight', 'this week',
    'in the coming hours', 'before the end of',
    'ultimatum expires', 'deadline',
    'در ساعات آینده', 'به زودی',
    'خلال ساعات', 'قريباً',
]

OPERATIONAL_FRAMING_IRAN = [
    'preparing to launch', 'positioned to strike', 'ready to fire',
    'forces deployed', 'on combat footing', 'full readiness',
    'ordered to strike', 'strike authorized',
    'all options on the table iran', 'iran will act',
    'آماده حمله', 'دستور حمله صادر شد',
    'مستعد للضرب', 'الأمر صدر بالضرب',
]


def _score_specificity(text):
    score = 0
    breakdown = {'named_geographies': [], 'named_assets': [],
                 'time_bounded': [], 'operational_framing': []}
    for geo in SPECIFIC_GEOGRAPHIES_IRAN:
        if geo in text:
            breakdown['named_geographies'].append(geo)
            score += 1
    for asset in SPECIFIC_ASSETS_IRAN:
        if asset in text:
            breakdown['named_assets'].append(asset)
            score += 1
    for tb in TIME_BOUNDED_IRAN:
        if tb in text:
            breakdown['time_bounded'].append(tb)
            score += 2
    for op in OPERATIONAL_FRAMING_IRAN:
        if op in text:
            breakdown['operational_framing'].append(op)
            score += 2
    return min(score, 10), breakdown


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
        print(f"[Iran Rhetoric Redis] GET error: {e}")
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
        print(f"[Iran Rhetoric Redis] SET error: {e}")
    return False


# ============================================
# PROXY ACTIVATION INDEX — reads cross-theater Redis live
# ============================================
def _compute_proxy_activation_index():
    """
    THE CORE INNOVATION — reads shared cross-theater fingerprints
    and computes a 0-5 proxy activation index.

    1 proxy elevated at L2+ = 1
    2 proxies elevated       = 2
    3 proxies elevated       = 4  (non-linear — very significant)
    4 proxies elevated       = 5  (full activation signal)

    Also detects synchronized language across proxies.
    Returns (level, detail_dict).
    """
    try:
        fingerprints = _redis_get(CROSSTHEATER_KEY) or {}
        if not fingerprints:
            return 0, {'reason': 'No cross-theater data available', 'proxies': {}}

        now = datetime.now(timezone.utc)
        proxy_theaters = ['yemen', 'lebanon', 'iraq', 'syria']
        fresh_proxies = {}

        for name in proxy_theaters:
            fp = fingerprints.get(name, {})
            if not fp:
                continue
            try:
                age = (now - datetime.fromisoformat(fp['ts'])).total_seconds() / 3600
                if age <= 24:  # Fresh within 24 hours — covers all proxy scan cycles
                    fresh_proxies[name] = fp
            except Exception:
                pass

        if not fresh_proxies:
            return 0, {'reason': 'No fresh proxy theater data', 'proxies': {}}

        elevated_proxies = {
            k: v for k, v in fresh_proxies.items()
            if v.get('level', 0) >= 2
        }

        n = len(elevated_proxies)
        if n == 0:
            level = 0
        elif n == 1:
            level = 1
        elif n == 2:
            level = 2
        elif n == 3:
            level = 4  # Non-linear jump — 3 simultaneous is very significant
        else:
            level = 5  # Full activation signal

        # Check for synchronized language across proxies
        all_phrases = {}
        for name, fp in fresh_proxies.items():
            for phrase in fp.get('top_phrases', []):
                phrase_key = phrase[:30].lower()
                all_phrases.setdefault(phrase_key, []).append(name)
        shared_phrases = {p: t for p, t in all_phrases.items() if len(t) >= 2}

        # Check for shared targets (very significant)
        all_targets = {}
        for name, fp in fresh_proxies.items():
            for target in fp.get('named_targets', []):
                all_targets.setdefault(target, []).append(name)
        shared_targets = {t: ts for t, ts in all_targets.items() if len(ts) >= 2}

        # Boost level if shared phrases or targets detected
        if shared_phrases and level < 5:
            level = min(level + 1, 5)
        if shared_targets and level < 5:
            level = min(level + 1, 5)

        detail = {
            'elevated_proxies': {k: v.get('level', 0) for k, v in elevated_proxies.items()},
            'fresh_proxies': list(fresh_proxies.keys()),
            'missing_proxies': [p for p in proxy_theaters if p not in fresh_proxies],
            'shared_phrases': list(shared_phrases.keys())[:5],
            'shared_targets': list(shared_targets.keys())[:5],
            'synchronized_language': len(shared_phrases) > 0,
            'shared_target_convergence': len(shared_targets) > 0,
            'n_elevated': n,
        }

        print(f"[Iran Rhetoric] 🔗 Proxy Activation Index: L{level} "
              f"({n} proxies elevated: {list(elevated_proxies.keys())})")
        return level, detail

    except Exception as e:
        print(f"[Iran Rhetoric] Proxy activation index error: {e}")
        return 0, {'reason': str(e), 'proxies': {}}


# ============================================
# DELTA CALCULATION
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
        prior_avg_score = round(sum(e.get('score', 0) for e in prior) / len(prior), 1)
        prior_avg_level = round(sum(e.get('level', 0) for e in prior) / len(prior), 2)
        score_change = current.get('score', 0) - prior_avg_score
        return {
            'direction': 'rising' if score_change > 10 else 'falling' if score_change < -10 else 'stable',
            'score_change': round(score_change, 1),
            'level_change': round(current.get('level', 0) - prior_avg_level, 2),
            'current_score': current.get('score', 0),
            'prior_avg_score': prior_avg_score,
            'prior_avg_level': prior_avg_level,
            'vs_period': f'{len(prior)}-scan average',
        }
    except Exception as e:
        print(f"[Iran Rhetoric] Delta error: {e}")
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
            current_statements = ar.get('statement_count', 0)
            current_level = ar.get('max_level', 0)
            prev = existing.get(actor_id, {})
            if not prev:
                updated[actor_id] = {'avg_statements': current_statements,
                                     'avg_level': current_level, 'scans': 1}
            else:
                updated[actor_id] = {
                    'avg_statements': round(alpha * current_statements + (1 - alpha) * prev.get('avg_statements', current_statements), 2),
                    'avg_level': round(alpha * current_level + (1 - alpha) * prev.get('avg_level', current_level), 3),
                    'scans': min(prev.get('scans', 1) + 1, 999),
                }
        _redis_set(BASELINE_KEY, updated, ttl=30 * 24 * 3600)
        print(f"[Iran Rhetoric] ✅ Actor baselines updated")
        return updated
    except Exception as e:
        print(f"[Iran Rhetoric] Baseline error: {e}")
        return {}


def _detect_silence_anomalies(actor_results, baselines):
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
                # IRGC silence is especially significant
                if actor_id == 'irgc':
                    print(f"[Iran Rhetoric] 🔇 IRGC SILENCE ANOMALY — {actual} vs avg {avg_statements:.1f}")
                else:
                    print(f"[Iran Rhetoric] 🔇 Silence: {actor_id} ({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Iran Rhetoric] Silence detection error: {e}")
    return anomalies


# ============================================
# CROSS-THEATER — Iran writes as command node
# ============================================
def _write_crosstheater_signal(result):
    """
    Iran writes to shared fingerprints with is_command_node: True.
    Other trackers will detect this and display differently.
    """
    try:
        existing = _redis_get(CROSSTHEATER_KEY) or {}

        actors = result.get('actors', {})
        top_phrases = []
        for sig in result.get('operation_true_promise_signals', [])[:3]:
            top_phrases.append(sig.get('phrase', '')[:60])
        for actor_id in ['irgc', 'khamenei']:
            for art in actors.get(actor_id, {}).get('top_articles', [])[:2]:
                title = art.get('title', '')[:60]
                if title:
                    top_phrases.append(title)

        named_targets = []
        for actor_id in ['irgc', 'khamenei']:
            for art in actors.get(actor_id, {}).get('top_articles', [])[:3]:
                title_lower = art.get('title', '').lower()
                for geo in SPECIFIC_GEOGRAPHIES_IRAN:
                    if geo in title_lower and geo not in named_targets:
                        named_targets.append(geo)

        # Axis levels — split into per-partner fields (v1.2.0, April 2026)
        china_iran_level  = actors.get('china_iran_axis',  {}).get('max_level', 0)
        russia_iran_level = actors.get('russia_iran_axis', {}).get('max_level', 0)
        # Combined level for readers that want aggregate (highest wins)
        axis_level = max(china_iran_level, russia_iran_level)

        # ── v2.4: Oman-specific signal extraction (for Oman tracker reads) ──
        # Detect Iran rhetoric specifically targeting Omani territory/logistics.
        # Salalah = US/UK logistics hub on Indian Ocean coast.
        # Duqm = expanding UK base + dry dock + outside Hormuz, strategically critical.
        # Muscat = capital, MOFA hosts US-Iran back-channel.
        salalah_targeted = False
        duqm_logistics_active = False
        oman_diplomatic_active = False
        for actor_id in ['khamenei', 'irgc', 'iran_gov']:
            for art in actors.get(actor_id, {}).get('top_articles', [])[:5]:
                title_lower = art.get('title', '').lower()
                desc_lower = art.get('description', '').lower()
                full_text = f"{title_lower} {desc_lower}"
                # Hostile signals toward Omani territory
                if 'salalah' in full_text and any(kw in full_text for kw in
                        ['threat', 'strike', 'target', 'missile', 'attack', 'mining', 'mine',
                         'تهديد', 'استهداف', 'ضربة', 'تهدید', 'هدف', 'حمله']):
                    salalah_targeted = True
                if 'duqm' in full_text and any(kw in full_text for kw in
                        ['british', 'uk', 'logistics', 'base', 'naval',
                         'بريطاني', 'بریتانیا', 'لوجستي', 'قاعدة']):
                    duqm_logistics_active = True
                # Oman as diplomatic channel signal (de-escalatory)
                if 'muscat' in full_text and any(kw in full_text for kw in
                        ['talks', 'mediation', 'channel', 'back-channel', 'witkoff',
                         'محادثات', 'وساطة', 'مفاوضات', 'گفتگو']):
                    oman_diplomatic_active = True

        existing['iran'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Iran',
            'is_command_node': True,               # ← Key flag for other trackers
            'level': result.get('theatre_escalation_level', 0),
            'score': result.get('theatre_score', 0),
            'theatre_score': result.get('theatre_score', 0),
            'irgc_level': result.get('irgc_direct_level', 0),
            'proxy_activation_level': result.get('proxy_activation_level', 0),
            'nuclear_level': result.get('nuclear_level', 0),
            'operation_true_promise_active': result.get('operation_true_promise_count', 0) > 0,
            'top_phrases': top_phrases[:5],
            'named_targets': named_targets[:8],
            'actor_levels': {
                aid: actors.get(aid, {}).get('max_level', 0)
                for aid in ['khamenei', 'irgc', 'iran_gov']
            },
            'specificity_score': result.get('specificity_score', 0),
            'proxy_detail': result.get('proxy_activation_detail', {}),
            # ── v1.2.0 Axis fingerprint (SPLIT — April 2026) ──
            # Written from Iran's perspective: what Iran is RECEIVING.
            # Severity levels (0-5) per partner:
            'china_iran_perspective_level':  china_iran_level,
            'russia_iran_perspective_level': russia_iran_level,
            # Binary flags preserved for backwards-compat with existing consumers:
            'china_iran_active':  china_iran_level >= 2,
            'russia_iran_active': russia_iran_level >= 2,
            'axis_support_level': axis_level,  # combined MAX — legacy consumers
            # ── v1.1: Diplomatic Track Fingerprint ──
            # Israel's tracker reads these to factor Iran's diplomatic posture
            # into its inbound score (mirrors Lebanon pattern).
            'diplomatic_active':   result.get('diplomatic_track_active', False),
            'ceasefire_level':     result.get('ceasefire_level', 0),
            'diplomatic_modifier': result.get('diplomatic_modifier', 0),
            'diplomatic_label':    result.get('diplomatic_label_detailed', 'Quiet'),
            # ── v2.4 Oman cross-theater signals ──
            'salalah_targeted':       salalah_targeted,
            'duqm_logistics_active':  duqm_logistics_active,
            'oman_diplomatic_active': oman_diplomatic_active,
        }

        _redis_set(CROSSTHEATER_KEY, existing, ttl=8 * 3600)
        print(f"[Iran Rhetoric] ✅ Command node fingerprint written (is_command_node: True)")
        if salalah_targeted or duqm_logistics_active or oman_diplomatic_active:
            print(f"[Iran Rhetoric] 🇴🇲 Oman signals: salalah={salalah_targeted}, "
                  f"duqm={duqm_logistics_active}, diplomatic={oman_diplomatic_active}")
    except Exception as e:
        print(f"[Iran Rhetoric] Cross-theater write error: {e}")


def _detect_crosstheater_coordination(proxy_activation_level, proxy_detail):
    """
    Iran's cross-theater view — it looks at proxy data as signals
    of its own command effectiveness, not just coordination.
    """
    findings = []
    try:
        elevated_proxies = proxy_detail.get('elevated_proxies', {})
        n_elevated = proxy_detail.get('n_elevated', 0)

        if n_elevated >= 2:
            findings.append({
                'type': 'proxy_activation',
                'message': f"Iran proxy network activation — {n_elevated} theater(s) simultaneously elevated",
                'elevated_proxies': elevated_proxies,
                'proxy_activation_level': proxy_activation_level,
                'confidence': min(n_elevated * 25 + proxy_activation_level * 5, 95),
                'signal': 'Multiple Iran-directed theaters elevated simultaneously — possible coordinated command signal',
                'is_command_node': True,
            })

        if proxy_detail.get('synchronized_language'):
            findings.append({
                'type': 'proxy_language_sync',
                'message': 'Synchronized language detected across proxy theaters',
                'shared_phrases': proxy_detail.get('shared_phrases', []),
                'confidence': 75,
                'signal': 'Proxies using similar framing within 14h — narrative coordination from Iran likely',
                'is_command_node': True,
            })

        if proxy_detail.get('shared_target_convergence'):
            findings.append({
                'type': 'proxy_target_convergence',
                'message': 'Proxies converging on same target sets',
                'shared_targets': proxy_detail.get('shared_targets', []),
                'confidence': 80,
                'signal': 'Multiple proxy theaters referencing same targets — possible coordinated targeting directive',
                'is_command_node': True,
            })

    except Exception as e:
        print(f"[Iran Rhetoric] Cross-theater detection error: {e}")

    return findings


# ============================================
# RSS FEEDS
# ============================================
RHETORIC_RSS_FEEDS = [
    # Iranian state media (English)
    ("https://www.presstv.ir/rss.xml", 1.0),
    ("https://en.mehrnews.com/rss", 1.0),
    ("https://news.google.com/rss/search?q=IRGC+Iran+missile+drone+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Khamenei+statement+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iran+Quds+Force+proxy+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Operation+True+Promise+Iran&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iran+nuclear+natanz+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Iran+strait+hormuz+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Iran+protests+economy+2026&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Iran+US+war+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Iran+Israel+war+2026&hl=en&gl=US&ceid=US:en", 1.0),
    # Iran International (opposition — domestic pressure signals)
    ("https://www.iranintl.com/en/rss", 0.95),
    # CENTCOM
    ("https://news.google.com/rss/search?q=CENTCOM+Iran+strikes+2026&hl=en&gl=US&ceid=US:en", 0.95),
    # Arabic — Iranian state/proxy framing
    ("https://news.google.com/rss/search?q=إيران+الحرس+الثوري+2026&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=خامنئي+بيان+2026&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=عملية+الوعد+الصادق+إيران&hl=ar&gl=SA&ceid=SA:ar", 1.0),
    ("https://news.google.com/rss/search?q=إيران+محور+المقاومة+2026&hl=ar&gl=SA&ceid=SA:ar", 0.95),
    # Farsi — 2-3 focused queries only (GDELT Farsi errors under load)
    ("https://news.google.com/rss/search?q=سپاه+پاسداران+عملیات+2026&hl=fa&gl=IR&ceid=IR:fa", 0.95),
    ("https://news.google.com/rss/search?q=خامنه‌ای+بیانیه+2026&hl=fa&gl=IR&ceid=IR:fa", 0.95),
    # Hebrew — Israeli perspective on Iran
    ("https://news.google.com/rss/search?q=איראן+תקיפה+2026&hl=iw&gl=IL&ceid=IL:iw", 0.9),
    # Israeli shadow war / nuclear red line signals (v2.1)
    ("https://news.google.com/rss/search?q=Israel+Iran+nuclear+red+line+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Mossad+Iran+operation+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Israel+Iran+deal+opposition+2026&hl=en&gl=US&ceid=US:en", 0.9),
    # Trump / US Iran pressure signals (v2.1)
    ("https://news.google.com/rss/search?q=Trump+Iran+nuclear+deal+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Trump+warns+Iran+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Trump+maximum+pressure+Iran+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Witkoff+Iran+deal+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Rubio+Iran+sanctions+2026&hl=en&gl=US&ceid=US:en", 0.9),
    # Truth Social — Trump direct statements (public RSS, no auth required)
    ("https://truthsocial.com/@realDonaldTrump.rss", 1.1),
    # Nitter deprecated platform-wide. Trump direct still captured via
    # Truth Social RSS (above, weight 1.1). Leaving this commented out
    # as a marker — replace with Bluesky mirror (@realdonaldtrump.govmirrors.com)
    # in a future session when we port Bluesky to the ME backend.
    # ("https://nitter.poast.org/realDonaldTrump/rss", 1.0),
    # ============================================
    # v2.2.0 (April 2026) — Israeli + ME investigative feeds
    # Same augmentation as China/Taiwan trackers. Catches stories
    # like FT TEE-01B satellite fusion story that Iranian state
    # media will NEVER break but IDF-adjacent press and premier
    # investigative outlets surface first.
    # ============================================
    # Israeli press — breaks China/Russia-Iran cooperation stories first
    ("https://rss.jpost.com/rss/rssfeedsheadlines.aspx", 0.95),
    ("https://www.timesofisrael.com/feed/", 0.95),
    # ME regional analysis — China/Russia engagement in Gulf & Levant
    ("https://www.al-monitor.com/rss", 0.90),
    ("https://www.middleeasteye.net/rss.xml", 0.85),
    # Premier investigative — intelligence/finance scoops (FT, Reuters)
    ("https://www.ft.com/world?format=rss", 1.0),
    ("https://feeds.reuters.com/Reuters/worldNews", 1.0),
    # Targeted queries for China-Iran axis specifically
    ("https://news.google.com/rss/search?q=China+Iran+military+OR+satellite+OR+MANPADS+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=IRGC+Chinese+satellite+OR+IRGC+Chinese+weapons+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Russia+satellite+Iran+targeting+2026&hl=en&gl=US&ceid=US:en", 1.0),
    # Barak Ravid — first-mover Israel/Iran OSINT journalist (v2.3)
    # 2 queries — Ravid covers Iran less centrally than Israel/Lebanon
    # but his US-Iran ceasefire + nuclear deal scoops are high-value
    ('https://news.google.com/rss/search?q=%22Barak+Ravid%22+Iran&hl=en&gl=US&ceid=US:en', 1.2),
    ('https://news.google.com/rss/search?q=%22%D7%91%D7%A8%D7%A7+%D7%A8%D7%91%D7%99%D7%93%22+%D7%90%D7%99%D7%A8%D7%90%D7%9F&hl=iw&gl=IL&ceid=IL:iw', 1.2),
]

# ============================================
# NITTER -- Primary source Twitter/X accounts
# Iran-specific: Trump, Rubio, CENTCOM, IDF, Witkoff
# Mirror fallback — no API key required.
# ============================================
NITTER_MIRRORS = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

NITTER_ACCOUNTS_IRAN = [
    ("realDonaldTrump", 1.3, "Trump — Iran ultimatum, deal, maximum pressure direct statements"),
    ("SecRubio",        1.2, "US SecState — Iran sanctions, deal signals, red lines"),
    ("CENTCOM",         1.1, "CENTCOM — force posture, Houthi strikes, carrier deployments"),
    ("POTUS",           1.0, "White House — executive Iran policy"),
    ("StateDept",       1.0, "State Dept — diplomatic signals, sanctions"),
    ("Witkoff",         1.1, "Steve Witkoff — Iran nuclear deal envoy"),
    ("IDF",             1.1, "IDF — strike posture, Iran targeting language"),
    ("AvichayAdraee",   1.0, "IDF Arabic spokesperson — strike claims vs Iran/proxies"),
    ("IsraeliPM",       1.1, "Israeli PM — Iran red line statements"),
    ("IranIntl",        1.0, "Iran International — opposition, domestic signals"),
    ("AlinejadMasih",   0.9, "Iranian activist — domestic pressure signals"),
    ("ElintNews",       0.9, "ELINT News — Iran missile/nuclear OSINT"),
    ("LongWarJournal",  0.9, "Long War Journal — proxy network analysis"),
]


def _fetch_nitter_iran(username, weight=1.0, timeout=8):
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
                print(f"[Iran Rhetoric/Nitter] @{username}: {len(posts)} posts via {mirror}")
                return posts
        except Exception as e:
            print(f"[Iran Rhetoric/Nitter] @{username} {mirror} failed: {str(e)[:60]}")
            continue
    print(f"[Iran Rhetoric/Nitter] @{username}: all mirrors failed")
    return []


def fetch_nitter_iran(days=3):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen = set()
    for username, weight, desc in NITTER_ACCOUNTS_IRAN:
        posts = _fetch_nitter_iran(username, weight=weight)
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
    print(f"[Iran Rhetoric/Nitter] Total: {len(all_posts)} posts")
    return all_posts


REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
IRAN_SUBREDDITS = ['iran', 'geopolitics', 'CredibleDefense', 'worldnews', 'IRG']
IRAN_REDDIT_KEYWORDS = [
    'irgc', 'iran missile', 'iran strike', 'khamenei',
    'iran nuclear', 'iran protests', 'iran war', 'quds force',
    'operation true promise', 'iran proxy', 'iran hezbollah',
]

ACTOR_KEYWORDS = {
    'khamenei':     ['khamenei', 'supreme leader', 'خامنه‌ای', 'المرشد', 'خامنئي'],
    'irgc':         ['irgc', 'revolutionary guard', 'quds force', 'pasdaran',
                     'سپاه', 'فيلق القدس', 'حرس الثوري', 'operation true promise'],
    'iran_gov':     ['iran foreign ministry', 'pezeshkian', 'araghchi',
                     'tehran says', 'iran official', 'وزارت خارجه', 'وزارة الخارجية الإيرانية'],
    'iran_people':  ['iran protests', 'iran demonstrations', 'iran economy',
                     'iran rial', 'iran unrest', 'اعتراضات ایران', 'احتجاجات إيران'],
    'hezbollah_iran': ['hezbollah iran', 'iran hezbollah', 'iran directs hezbollah',
                       'حزب الله وإيران', 'resistance axis lebanon'],
    'houthi_iran':  ['houthi iran', 'iran houthi', 'iran ansar allah',
                     'الحوثيون وإيران', 'iran red sea'],
    'pmf_iran':     ['pmf iran', 'iran pmf', 'quds force iraq', 'iran militia iraq',
                     'الحشد الشعبي وإيران', 'فيلق القدس يوجه'],
    # v1.2.0 — Axis actors split into China and Russia tracks
    'china_iran_axis': [
        # Direct mentions (both orders)
        'china iran', 'iran china', 'chinese iran', 'iran chinese',
        'beijing tehran', 'tehran beijing', 'china tehran', 'beijing iran',
        # Material/capability transfers
        'china arms iran', 'china backs iran', 'china supplies iran',
        'china military aid iran', 'china iran axis',
        # ISR / satellite (multiple word orders for FT-style headlines)
        'chinese satellite', 'chinese spy satellite', 'china satellite iran',
        'chinese satellite iran', 'iran chinese satellite',
        'irgc chinese', 'chinese isr', 'china ground station iran',
        # Named entities from TEE-01B story
        'tee-01b', 'tee01b', 'emposat', 'earth eye co', 'earth eye',
        # Cross-language
        'چین ایران', 'ایران چین',
        'الصين إيران', 'إيران الصين',
    ],
    'russia_iran_axis': ['russia iran', 'moscow tehran', 'russian iran',
                         'russia arms iran', 'russia backs iran',
                         'russian satellite iran', 'russia launches iran',
                         'russia supplies iran', 'russia iran military',
                         'russian targeting iran', 'russian rocket iran',
                         'روسیه ایران', 'روسيا إيران'],
    'israel_iran':  ['israel iran', 'israel strikes iran', 'idf iran',
                     'netanyahu iran', 'mossad iran', 'israel red line iran',
                     'israel nuclear iran', 'israel sabotage iran',
                     'ישראל איראן', 'מוסד איראן', 'إسرائيل إيران', 'الموساد إيران'],
    'us_iran':      ['us strikes iran', 'centcom iran', 'us iran war',
                     'pentagon iran', 'trump iran', 'trump warns iran',
                     'trump threatens iran', 'trump maximum pressure',
                     'witkoff iran', 'rubio iran',
                     'القوات الأمريكية إيران', 'ترامب إيران'],
}


def fetch_reddit_iran(days=3):
    time_filter = 'day' if days <= 1 else 'week' if days <= 7 else 'month'
    query = ' OR '.join(IRAN_REDDIT_KEYWORDS[:4])
    posts = []
    for subreddit in IRAN_SUBREDDITS:
        try:
            time.sleep(2)
            url = f'https://www.reddit.com/r/{subreddit}/search.json'
            params = {'q': query, 'restrict_sr': 'true', 'sort': 'new',
                      't': time_filter, 'limit': 25}
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
                if not any(kw in text_lower for kw in IRAN_REDDIT_KEYWORDS):
                    continue
                posts.append({
                    'title': title[:200],
                    'url': f"https://www.reddit.com{pd.get('permalink','')}",
                    'published': datetime.fromtimestamp(
                        pd.get('created_utc', 0), tz=timezone.utc).isoformat(),
                    'description': pd.get('selftext', '')[:300],
                    'source': f'r/{subreddit}',
                    'weight': 0.9,
                })
                count += 1
            print(f"[Iran Rhetoric/Reddit] r/{subreddit}: {count} posts")
        except Exception as e:
            print(f"[Iran Rhetoric/Reddit] r/{subreddit} error: {e}")
    return posts


# ============================================
# ARTICLE FETCHING
# ============================================
def fetch_rhetoric_articles(days=3):
    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # RSS
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
            print(f"[Iran Rhetoric RSS] Error: {str(e)[:80]}")

    print(f"[Iran Rhetoric] RSS: {len(articles)} articles")

    # Telegram — primary Persian/Arabic signal source
    if TELEGRAM_AVAILABLE:
        try:
            tg_messages = fetch_telegram_signals_iran(hours_back=days * 24)
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
                    'weight': 1.3,  # Telegram gets highest boost — real-time Persian/Arabic
                    'views': msg.get('views', 0),
                    'forwards': msg.get('forwards', 0),
                })
                tg_count += 1
            print(f"[Iran Rhetoric] Telegram: {tg_count} messages (primary Persian/Arabic source)")
        except Exception as e:
            print(f"[Iran Rhetoric] Telegram error: {e}")

    # Reddit — domestic pressure signals
    try:
        reddit_posts = fetch_reddit_iran(days=days)
        articles.extend(reddit_posts)
        print(f"[Iran Rhetoric] Reddit: {len(reddit_posts)} posts")
    except Exception as e:
        print(f"[Iran Rhetoric] Reddit error: {e}")

    # GDELT — balanced, Farsi limited to avoid overload
    gdelt_queries = {
        'eng': [
            'IRGC Iran missile strike 2026',
            'Khamenei statement warns',
            'Iran proxy coordination hezbollah houthi',
            'Operation True Promise Iran wave',
            'Iran nuclear natanz enrichment',
            'Iran strait hormuz threat',
        ],
        'ara': [
            'إيران الحرس الثوري عملية',
            'خامنئي بيان تحذير',
            'محور المقاومة إيران تنسيق',
            'عملية الوعد الصادق',
        ],
        'fas': [
            # Only 2 focused Farsi queries — GDELT Farsi errors under load
            'سپاه پاسداران عملیات موشکی',
            'خامنه‌ای بیانیه هشدار',
        ],
    }

    gdelt_count = 0
    for lang, queries in gdelt_queries.items():
        for query in queries:
            try:
                params = {
                    'query': query, 'mode': 'artlist', 'maxrecords': 25,
                    'timespan': f'{days}d', 'format': 'json', 'sourcelang': lang,
                }
                resp = None
                for attempt in range(2):
                    try:
                        resp = requests.get(GDELT_BASE_URL, params=params, timeout=45)
                        if resp.status_code == 200:
                            break
                    except requests.Timeout:
                        if attempt == 0:
                            time.sleep(3)
                            continue
                        raise
                if resp and resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        continue
                    for art in data.get('articles', []):
                        articles.append({
                            'title': art.get('title', ''),
                            'url': art.get('url', ''),
                            'published': art.get('seendate', ''),
                            'description': art.get('title', ''),
                            'source': f'GDELT ({lang})',
                            'weight': 0.9,
                        })
                        gdelt_count += 1
            except Exception as e:
                print(f"[Iran Rhetoric GDELT] {lang} error: {str(e)[:60]}")
            time.sleep(0.8)  # Slightly longer delay — GDELT is under load

    print(f"[Iran Rhetoric] GDELT: {gdelt_count} articles")

    # Deduplicate
    seen = set()
    unique = []
    for a in articles:
        u = a.get('url', '')
        if u and u not in seen:
            seen.add(u)
            unique.append(a)

    # Nitter — primary source accounts (v2.1)
    try:
        nitter_posts = fetch_nitter_iran(days=days)
        for p in nitter_posts:
            u = p.get('url', '')
            if u and u not in seen:
                seen.add(u)
                unique.append(p)
    except Exception as e:
        print(f"[Iran Rhetoric] Nitter error: {e}")

    tg_c  = sum(1 for a in unique if 'Telegram' in str(a.get('source', '')))
    nit_c = sum(1 for a in unique if 'Nitter' in str(a.get('source', '')))
    red_c = sum(1 for a in unique if str(a.get('source', '')).startswith('r/'))
    rss_c = len(unique) - tg_c - nit_c - red_c
    print(f"[Iran Rhetoric] Total unique: {len(unique)} ({rss_c} RSS/GDELT + {tg_c} TG + {nit_c} Nitter + {red_c} Reddit)")
    return unique


# ============================================
# CLASSIFY ARTICLES
# ============================================
def classify_articles(articles, proxy_activation_level):
    """
    Classify articles. Reporting actors get downgraded.
    Operation True Promise patterns detected separately.
    Proxy directive language tracked as coordination signal.
    """
    actor_results = {
        actor_id: {
            'name': info['name'],
            'flag': info['flag'],
            'icon': info['icon'],
            'color': info['color'],
            'role': info['role'],
            'statement_count': 0,
            'irgc_direct_score': 0,
            'nuclear_score': 0,
            'domestic_score': 0,
            'regional_score': 0,
            'soft_power_score': 0,
            'max_level': 0,
            'top_articles': [],
            'silence_alert': False,
            'specificity_scores': [],
        }
        for actor_id, info in ACTORS.items()
    }

    theatre_summary = {
        'irgc_direct_max': 0,
        'nuclear_max': 0,
        'domestic_max': 0,
        'regional_max': 0,
        'soft_power_max': 0,
        'diplomatic_max': 0,   # v1.1: De-escalation signals
        'total_articles': len(articles),
        'operation_true_promise_signals': [],
        'proxy_directive_signals': [],
        'all_specificity_scores': [],
    }

    for article in articles:
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        pub_date = article.get('published', '')

        # Operation True Promise detection
        otp_hits = [p for p in OPERATION_TRUE_PROMISE_PATTERNS if p in text]
        if otp_hits:
            theatre_summary['operation_true_promise_signals'].append({
                'phrase': otp_hits[0],
                'article': article.get('title', '')[:100],
                'published': pub_date,
                'source': article.get('source', ''),
            })

        # Proxy directive language
        directive_hits = [p for p in PROXY_DIRECTIVE_LANGUAGE if p in text]
        if directive_hits:
            theatre_summary['proxy_directive_signals'].append({
                'phrase': directive_hits[0],
                'article': article.get('title', '')[:100],
                'published': pub_date,
            })

        # Specificity
        spec_score, _ = _score_specificity(text)
        if spec_score > 0:
            theatre_summary['all_specificity_scores'].append(spec_score)

        # Reporting language check
        is_reporting_context = any(phrase in text for phrase in REPORTING_LANGUAGE)

        # Multi-actor matching
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

            if len(ar['top_articles']) < 5:
                ar['top_articles'].append({
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', ''),
                    'published': pub_date,
                    'specificity_score': spec_score,
                })

            # Score vectors with reporting downgrade
            for level in range(5, 0, -1):
                # IRGC Direct
                for kw in IRGC_DIRECT_TRIGGERS.get(level, []):
                    if kw in text:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > ar['irgc_direct_score']:
                            ar['irgc_direct_score'] = effective_level
                        if level > theatre_summary['irgc_direct_max']:
                            theatre_summary['irgc_direct_max'] = level
                        break

                # Nuclear
                for kw in NUCLEAR_TRIGGERS.get(level, []):
                    if kw in text:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 4 and is_reporting_context:
                            effective_level = 3
                        if effective_level > ar['nuclear_score']:
                            ar['nuclear_score'] = effective_level
                        if level > theatre_summary['nuclear_max']:
                            theatre_summary['nuclear_max'] = level
                        break

                # Domestic
                for kw in DOMESTIC_TRIGGERS.get(level, []):
                    if kw in text:
                        if level > ar['domestic_score']:
                            ar['domestic_score'] = level
                        if level > theatre_summary['domestic_max']:
                            theatre_summary['domestic_max'] = level
                        break

                # Regional
                for kw in REGIONAL_TRIGGERS.get(level, []):
                    if kw in text:
                        effective_level = level
                        if actor_id in REPORTING_ACTORS and level >= 3 and is_reporting_context:
                            effective_level = 2
                        if effective_level > ar['regional_score']:
                            ar['regional_score'] = effective_level
                        if level > theatre_summary['regional_max']:
                            theatre_summary['regional_max'] = level
                        break

                # Soft Power / Influence Operations
                for kw in SOFT_POWER_KEYWORDS.get(level, []):
                    if kw in text:
                        if level > ar['soft_power_score']:
                            ar['soft_power_score'] = level
                        if level > theatre_summary['soft_power_max']:
                            theatre_summary['soft_power_max'] = level
                        break

                # ── v1.1: Diplomatic Track (de-escalation, REDUCES pressure) ──
                for kw in DIPLOMATIC_TRIGGERS.get(level, []):
                    if kw in text:
                        if level > theatre_summary['diplomatic_max']:
                            theatre_summary['diplomatic_max'] = level
                        break

    # Per-actor finalization
    for actor_id, ar in actor_results.items():
        ar['max_level'] = max(
            ar['irgc_direct_score'], ar['nuclear_score'],
            ar['domestic_score'], ar['regional_score'],
            ar['soft_power_score']
        )
        ar['escalation_level'] = ar['max_level']
        ar['escalation_label'] = ESCALATION_LEVELS.get(ar['max_level'], {}).get('label', 'Baseline')
        ar['escalation_color'] = ESCALATION_LEVELS.get(ar['max_level'], {}).get('color', '#6b7280')

        baseline = ACTORS[actor_id].get('baseline_statements_per_week', 3)
        expected = baseline * (3 / 7.0)
        ar['silence_alert'] = ar['statement_count'] == 0 and expected >= 2

        specs = ar.pop('specificity_scores', [])
        ar['specificity_score'] = round(sum(specs) / len(specs), 1) if specs else 0

    return actor_results, theatre_summary


# ============================================
# SCORING — Proxy Activation is a weighted input
# ============================================
def _calculate_rhetoric_score(theatre_summary, proxy_activation_level,
                               actor_results, operation_true_promise_count):
    """
    Weighted score with proxy activation as a direct input.
    """
    irgc    = theatre_summary['irgc_direct_max']
    nuclear = theatre_summary['nuclear_max']
    domestic = theatre_summary['domestic_max']
    regional = theatre_summary['regional_max']
    proxy   = proxy_activation_level

    weighted = (
        irgc    * 3.0 +
        proxy   * 2.5 +   # ← Cross-theater Redis input
        nuclear * 2.0 +
        regional * 1.5 +
        domestic * 1.0
    )
    max_possible = 5 * (3.0 + 2.5 + 2.0 + 1.5 + 1.0)
    base = (weighted / max_possible) * 75

    # Coordination bonus
    if proxy >= 3:
        base += 15  # 3+ proxies simultaneously elevated
    elif proxy >= 2:
        base += 8

    # Command node bonus
    max_actor_level = max((ar['max_level'] for ar in actor_results.values()), default=0)
    if max_actor_level >= 4 and proxy >= 3:
        base += 10  # Iran at Operational + 3+ proxies = clear command signal

    # Operation True Promise bonus
    if operation_true_promise_count > 0:
        base += min(operation_true_promise_count * 3, 12)

    # ── v1.1: Diplomatic Track Modifier (active negotiations REDUCE pressure) ──
    diplomatic_level = theatre_summary.get('diplomatic_max', 0)
    diplomatic_modifier_map = {
        0: 0,    # Quiet
        1: -1,   # Background diplomatic mentions
        2: -3,   # Diplomatic push
        3: -6,   # Mediator activity (Pakistan/Oman/Russia shuttle)
        4: -10,  # Active negotiations / direct talks
        5: -15,  # Agreement reached / signed
    }
    base += diplomatic_modifier_map.get(diplomatic_level, 0)

    return max(0, min(100, int(base)))


# ============================================
# MAIN SCAN
# ============================================
def run_iran_rhetoric_scan(days=3):
    """
    Full Iran command node scan.
    Reads proxy theater data from Redis as INPUT to scoring.
    """
    print(f"\n[Iran Rhetoric] ═══ Starting command node scan v1.0 (days={days}) ═══")
    start = datetime.now(timezone.utc)

    # ── Step 1: Read proxy activation BEFORE fetching articles ──
    print(f"[Iran Rhetoric] 🔗 Reading cross-theater proxy data...")
    proxy_activation_level, proxy_detail = _compute_proxy_activation_index()
    print(f"[Iran Rhetoric] 🔗 Proxy Activation Index: L{proxy_activation_level}")

    # ── Step 2: Fetch and classify articles ──
    articles = fetch_rhetoric_articles(days)
    actor_results, theatre_summary = classify_articles(articles, proxy_activation_level)

    # ── Step 3: Compute theatre levels ──
    max_irgc     = theatre_summary['irgc_direct_max']
    max_nuclear  = theatre_summary['nuclear_max']
    max_domestic = theatre_summary['domestic_max']
    max_regional = theatre_summary['regional_max']

    otp_count = len(theatre_summary['operation_true_promise_signals'])

    # Overall level = max of all vectors including proxy activation
    max_level = max(max_irgc, max_nuclear, max_domestic, max_regional, proxy_activation_level)
    max_level = min(max_level, 5)

    rhetoric_score = _calculate_rhetoric_score(
        theatre_summary, proxy_activation_level, actor_results, otp_count
    )

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
        'theatre': 'Iran',
        'is_command_node': True,

        # Theatre summary
        'theatre_score': rhetoric_score,
        'theatre_level': max_level,
        'theatre_escalation_level': max_level,
        'theatre_escalation_label': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Baseline'),
        'theatre_escalation_color': ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
        'theatre_escalation_description': ESCALATION_LEVELS.get(max_level, {}).get('description', ''),

        # Vectors
        'irgc_direct_level':      max_irgc,
        'irgc_direct_label':      ESCALATION_LEVELS.get(max_irgc, {}).get('label', 'Baseline'),
        'proxy_activation_level': proxy_activation_level,
        'proxy_activation_label': ESCALATION_LEVELS.get(proxy_activation_level, {}).get('label', 'Baseline'),
        'proxy_activation_detail': proxy_detail,
        'nuclear_level':          max_nuclear,
        'nuclear_label':          ESCALATION_LEVELS.get(max_nuclear, {}).get('label', 'Baseline'),
        'domestic_level':         max_domestic,
        'domestic_label':         ESCALATION_LEVELS.get(max_domestic, {}).get('label', 'Baseline'),
        'regional_level':         max_regional,
        'regional_label':         ESCALATION_LEVELS.get(max_regional, {}).get('label', 'Baseline'),
        'soft_power_level':       theatre_summary['soft_power_max'],
        'soft_power_label':       ESCALATION_LEVELS.get(theatre_summary['soft_power_max'], {}).get('label', 'Baseline'),

        # ── v1.1: Diplomatic Track (de-escalation signals) ──
        'ceasefire_level':           theatre_summary['diplomatic_max'],
        'ceasefire_label':           ESCALATION_LEVELS.get(theatre_summary['diplomatic_max'], {}).get('label', 'Baseline'),
        'diplomatic_track_active':   theatre_summary['diplomatic_max'] >= 2,
        'diplomatic_modifier':       {0:0, 1:-1, 2:-3, 3:-6, 4:-10, 5:-15}.get(theatre_summary['diplomatic_max'], 0),
        'diplomatic_label_detailed': {
            0: 'Quiet',
            1: 'Background Mentions',
            2: 'Diplomatic Push',
            3: 'Mediator Activity',
            4: 'Active Negotiations',
            5: 'Agreement Reached',
        }.get(theatre_summary['diplomatic_max'], 'Quiet'),

        # Special signals
        'operation_true_promise_count': otp_count,
        'operation_true_promise_signals': theatre_summary['operation_true_promise_signals'][:5],
        'proxy_directive_signals': theatre_summary['proxy_directive_signals'][:5],

        # v2.0 enriched
        'specificity_score': theatre_specificity,
        'delta': None,
        'silence_anomalies': [],
        'crosstheater_coordination': [],

        # Actors
        'actors': actor_results,
        'scan_time_seconds': scan_time,
        'version': '1.0.0-iran-command-node',
    }

    # Save initial cache
    _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(RHETORIC_CACHE_KEY_LEGACY, result)

    # History snapshot
    try:
        snapshot = json.dumps({
            'ts':         datetime.now(timezone.utc).isoformat(),
            'score':      rhetoric_score,
            'level':      max_level,
            'label':      ESCALATION_LEVELS.get(max_level, {}).get('label', 'Baseline'),
            'irgc':       max_irgc,
            'proxy':      proxy_activation_level,
            'nuclear':    max_nuclear,
            'regional':   max_regional,
            'domestic':   max_domestic,
            'otp_count':  otp_count,
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
            print(f"[Iran Rhetoric] 📈 History snapshot saved")
    except Exception as e:
        print(f"[Iran Rhetoric] History error (non-fatal): {e}")

    # Baselines + silence anomalies
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # Delta
    result['delta'] = _compute_delta()

    # Write command node fingerprint THEN detect coordination
    _write_crosstheater_signal(result)
    result['crosstheater_coordination'] = _detect_crosstheater_coordination(
        proxy_activation_level, proxy_detail
    )

    # Signal interpretation — So What, Red Lines, Historical Patterns
    if INTERPRETER_AVAILABLE:
        try:
            result['interpretation'] = iran_interpret_signals(result)
            best = result['interpretation']['historical_matches']
            best_pct = best[0]['similarity'] if best else 'none'
            print(f"[Iran Rhetoric] ✅ Interpreter: {result['interpretation']['red_lines']['breached_count']} red lines breached, best match: {best_pct}%")
        except Exception as e:
            print(f"[Iran Rhetoric] ⚠️ Interpreter error (non-fatal): {e}")

    # Re-save with all enriched fields
    _redis_set(RHETORIC_CACHE_KEY, result)
    _redis_set(RHETORIC_CACHE_KEY_LEGACY, result)

    print(f"[Iran Rhetoric] ✅ Command node scan complete in {scan_time}s")
    print(f"[Iran Rhetoric]    Level: {result['theatre_escalation_label']} ({max_level})")
    print(f"[Iran Rhetoric]    Score: {rhetoric_score}/100")
    print(f"[Iran Rhetoric]    IRGC Direct: L{max_irgc} | Proxy Activation: L{proxy_activation_level}")
    print(f"[Iran Rhetoric]    Nuclear: L{max_nuclear} | Regional: L{max_regional}")
    print(f"[Iran Rhetoric]    Operation True Promise signals: {otp_count}")
    print(f"[Iran Rhetoric]    Specificity: {theatre_specificity}/10")
    return result


def _bg_scan():
    global _rhetoric_running
    try:
        run_iran_rhetoric_scan()
    except Exception as e:
        print(f"[Iran Rhetoric] Background scan error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


# ============================================
# ROUTE REGISTRATION
# ============================================
def register_iran_rhetoric_routes(app):

    # Periodic scan thread
    def _periodic_scan():
        time.sleep(90)  # Stagger startup
        print("[Iran Rhetoric] Starting initial scan...")
        _bg_scan()
        while True:
            print(f"[Iran Rhetoric] Sleeping {SCAN_INTERVAL_HOURS}h until next scan...")
            time.sleep(SCAN_INTERVAL_HOURS * 3600)
            _bg_scan()

    thread = threading.Thread(target=_periodic_scan, daemon=True)
    thread.start()
    print(f"[Iran Rhetoric] ✅ Periodic scan thread started ({SCAN_INTERVAL_HOURS}h cycle)")

    @app.route('/api/rhetoric/iran', methods=['GET'])
    def iran_rhetoric():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        if force:
            print("[Iran Rhetoric] Force refresh requested")
            try:
                result = run_iran_rhetoric_scan()
                return jsonify(result)
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
                t = threading.Thread(target=_bg_scan, daemon=True)
                t.start()

        return jsonify({
            'success': True,
            'awaiting_scan': True,
            'theatre': 'Iran',
            'is_command_node': True,
            'theatre_score': 0,
            'theatre_escalation_level': 0,
            'theatre_escalation_label': 'Scanning...',
            'theatre_escalation_color': '#6b7280',
            'actors': {},
            'message': 'First scan in progress — check back in 3-4 minutes',
            'version': '1.0.0-iran-command-node',
        })

    @app.route('/api/rhetoric/iran/summary', methods=['GET'])
    def iran_rhetoric_summary():
        """Lightweight summary — includes all v2.0 fields + Iran-specific signals."""
        cached = _redis_get(RHETORIC_CACHE_KEY) or _redis_get(RHETORIC_CACHE_KEY_LEGACY)
        if cached:
            return jsonify({
                'success': True,
                'is_command_node': True,
                # Core
                'theatre_score':            cached.get('theatre_score', 0),
                'theatre_level':            cached.get('theatre_level', 0),
                'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
                'theatre_escalation_label': cached.get('theatre_escalation_label', 'Baseline'),
                'theatre_escalation_color': cached.get('theatre_escalation_color', '#6b7280'),
                'theatre_label':            cached.get('theatre_escalation_label', 'Baseline'),
                'theatre_color':            cached.get('theatre_escalation_color', '#6b7280'),
                # Vectors
                'irgc_direct_level':      cached.get('irgc_direct_level', 0),
                'irgc_direct_label':      cached.get('irgc_direct_label', 'Baseline'),
                'proxy_activation_level': cached.get('proxy_activation_level', 0),
                'proxy_activation_label': cached.get('proxy_activation_label', 'Baseline'),
                'proxy_activation_detail': cached.get('proxy_activation_detail', {}),
                'nuclear_level':          cached.get('nuclear_level', 0),
                'nuclear_label':          cached.get('nuclear_label', 'Baseline'),
                'domestic_level':         cached.get('domestic_level', 0),
                'domestic_label':         cached.get('domestic_label', 'Baseline'),
                'regional_level':         cached.get('regional_level', 0),
                'regional_label':         cached.get('regional_label', 'Baseline'),
                # ── v1.1: Diplomatic Track ──
                'ceasefire_level':           cached.get('ceasefire_level', 0),
                'ceasefire_label':           cached.get('ceasefire_label', 'Baseline'),
                'diplomatic_track_active':   cached.get('diplomatic_track_active', False),
                'diplomatic_modifier':       cached.get('diplomatic_modifier', 0),
                'diplomatic_label_detailed': cached.get('diplomatic_label_detailed', 'Quiet'),
                # Iran-specific
                'operation_true_promise_count':   cached.get('operation_true_promise_count', 0),
                'operation_true_promise_signals': cached.get('operation_true_promise_signals', [])[:3],
                'proxy_directive_signals':        cached.get('proxy_directive_signals', [])[:3],
                # v2.0
                'specificity_score':  cached.get('specificity_score', 0),
                'delta':              cached.get('delta'),
                'silence_anomalies':  cached.get('silence_anomalies', []),
                'total_articles':     cached.get('total_articles', 0),
                'timestamp':  cached.get('timestamp'),
                'scanned_at': cached.get('scanned_at', cached.get('timestamp', '')),
                'cached': True,
            })
        return jsonify({
            'success': False,
            'message': 'No cached data yet — scan in progress',
            'awaiting_scan': True,
            'is_command_node': True,
        })

    @app.route('/api/rhetoric/iran/history', methods=['GET'])
    def iran_rhetoric_history():
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
                'theatre': 'Iran',
                'is_command_node': True,
                'history_key': HISTORY_KEY,
                'count': len(entries),
                'entries': entries,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    print("[Iran Rhetoric] ✅ Command node routes registered: "
          "/api/rhetoric/iran, /api/rhetoric/iran/summary, /api/rhetoric/iran/history")
