"""
Asifah Analytics — Lebanon Rhetoric & Escalation Tracker v2.0.0
March 2026

Re-architected to match Yemen gold standard (v2.0.0):
  - Multi-vector threat scoring (Ground Ops, Rockets, Ceasefire/Diplomacy, Cross-border)
  - Delta calculation vs prior scan history
  - Specificity scoring (0-10) — named targets, time-bounded language, operational framing
  - Actor baselines in Redis (exponential moving average)
  - Silence anomaly detection (Redis-backed, not static)
  - Cross-theater coordination fingerprints (shared Redis key with Yemen/Iraq/Syria)
  - Conditional threat parsing ("if X then Y" tripwire language)
  - Syria border buildup vector under Ground Operations
  - France + Cyprus tracked under Ceasefire/Diplomacy

ACTORS:
  - Hezbollah (Political)
  - Hezbollah (Military)
  - Iran (re: Lebanon)
  - Israel (re: Lebanon)
  - Lebanese Government
  - UNIFIL
  - France (diplomatic actor)
  - Cyprus (diplomatic host)
  - Syria (border buildup watch)

THREAT VECTORS:
  1. GROUND OPERATIONS — IDF incursions, UNIFIL incidents, Syria border buildup
  2. ROCKETS / MISSILES — Hezbollah fire into Israel, IDF strikes Lebanon
  3. CEASEFIRE / DIPLOMACY — 1701 compliance, France/Cyprus talks, negotiations
  4. CROSS-BORDER ESCALATION — Catch-all for escalatory cross-border signals

CACHING:
  - Upstash Redis (REST API) — same instance as all other backends
  - 12-hour scan cycle (background thread)
  - Endpoint serves cached data, never blocks on scan
  - History: rhetoric:lebanon:history (lpush pattern, 120-entry rolling)
  - Baselines: rhetoric_baseline:lebanon (30-day TTL)
  - Cross-theater: rhetoric:crosstheater:fingerprints (shared with Yemen/Iraq/Syria)

ENDPOINTS:
  - /api/rhetoric/lebanon — full analysis
  - /api/rhetoric/lebanon/summary — compact for card/index integration
  - /api/rhetoric/lebanon/trends — historical trend data
  - /api/rhetoric/lebanon/history — rolling history for chart rendering

CHANGELOG:
  v2.0.0 (2026-03-20):
    - Full re-architecture to Yemen gold standard
    - Added 4 threat vectors replacing single escalation score
    - Added delta, specificity, baselines, silence detection, cross-theater
    - Added Syria border buildup under Ground Operations
    - Added France and Cyprus as diplomatic actors
    - Unified Redis key pattern with other trackers
  v1.1.0 (2026-02-26):
    - Broadened actor keywords, added GDELT retry, silence alert fixes

COPYRIGHT © 2025-2026 Asifah Analytics. All rights reserved.
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

# Signal interpreter -- So What, Red Lines, Historical Patterns
try:
    from lebanon_signal_interpreter import interpret_signals as lebanon_interpret_signals
    INTERPRETER_AVAILABLE = True
    print("[Lebanon Rhetoric] Signal interpreter loaded")
except ImportError:
    INTERPRETER_AVAILABLE = False
    print("[Lebanon Rhetoric] Warning: Signal interpreter not available")

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
RHETORIC_CACHE_KEY    = 'rhetoric:lebanon:latest'
RHETORIC_HISTORY_KEY  = 'rhetoric:lebanon:history'       # lpush rolling list (120 entries)
RHETORIC_LEGACY_HISTORY_KEY = 'rhetoric:lebanon:history:intraday'  # old key, kept for compat
BASELINE_KEY          = 'rhetoric_baseline:lebanon'
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
# ACTOR DEFINITIONS — LEBANON THEATRE v2.0
# ========================================

LEBANON_ACTORS = {
    'hezbollah_political': {
        'name': 'Hezbollah (Political)',
        'flag': '🇱🇧',
        'icon': '🏛️',
        'color': '#16a34a',
        'role': 'Threat Actor — Political Wing',
        'keywords': [
            'hezbollah', 'hezballah', 'hizballah', 'hizbollah', 'hizb allah',
            'hezbollah statement', 'hezbollah says', 'hezbollah declares',
            'hezbollah political', 'hezbollah parliament', 'hezbollah demands',
            'hezbollah condemns', 'hezbollah calls for', 'hezbollah rejects',
            'naim qassem', 'qassem says', 'qassem warns',
            'loyalty to resistance', 'resistance bloc',
            'hezbollah leader', 'hezbollah chief', 'hezbollah secretary',
            'حزب الله', 'حزب اللـه', 'حزبالله',
            'نعيم قاسم', 'كتلة الوفاء للمقاومة',
        ],
        'baseline_statements_per_week': 12,
    },
    'hezbollah_military': {
        'name': 'Hezbollah (Military)',
        'flag': '🇱🇧',
        'icon': '⚔️',
        'color': '#dc2626',
        'role': 'Threat Actor — Military Wing',
        'keywords': [
            'hezbollah fires', 'hezbollah launches', 'hezbollah strikes',
            'hezbollah rockets', 'hezbollah missile', 'hezbollah drone',
            'hezbollah attack', 'hezbollah targets', 'hezbollah claims',
            'hezbollah operation', 'hezbollah retaliation',
            'hezbollah military', 'hezbollah forces', 'hezbollah arms',
            'hezbollah weapons', 'hezbollah arsenal', 'hezbollah tunnel',
            'radwan force', 'hezbollah fighters', 'hezbollah martyrs',
            'hezbollah combat', 'hezbollah war',
            'islamic resistance', 'resistance operation',
            'the resistance', 'resistance forces', 'resistance fighters',
            'al-manar', 'almanar',
            'المقاومة الإسلامية', 'المقاومة', 'مقاومة',
            'عملية نوعية', 'صواريخ حزب الله',
            'استهداف مواقع', 'قوة الرضوان',
            'المنار', 'الإعلام الحربي',
        ],
        'baseline_statements_per_week': 8,
    },
    'iran_lebanon': {
        'name': 'Iran (re: Lebanon)',
        'flag': '🇮🇷',
        'icon': '🕌',
        'color': '#b91c1c',
        'role': 'Hezbollah Patron / IRGC Director',
        'keywords': [
            # Core Iran-Hezbollah relationship
            'iran hezbollah', 'iran lebanon', 'iran supports hezbollah',
            'iran arms hezbollah', 'iran weapons lebanon',
            'tehran hezbollah', 'tehran lebanon',
            'quds force lebanon', 'irgc hezbollah', 'irgc lebanon',
            'khamenei hezbollah', 'khamenei resistance', 'khamenei lebanon',
            'axis of resistance', 'resistance axis',
            'iranian proxy', 'iran proxy', 'iranian-backed', 'iran-backed',
            # v2.2: IRGC directing Hezbollah — current analytical reality
            'irgc directing hezbollah', 'irgc commands hezbollah',
            'iran directing hezbollah', 'iran ordered hezbollah',
            'quds force directing', 'quds force commands',
            'irgc calling shots', 'iran calling shots lebanon',
            'irgc officers lebanon', 'quds force officers beirut',
            'irgc adviser hezbollah', 'iran adviser hezbollah',
            # v2.2: IRGC personnel killed in Lebanon (IDF targeting)
            'irgc killed beirut', 'quds force killed lebanon',
            'irgc commander killed', 'quds force commander killed',
            'iran commander beirut', 'irgc officer killed',
            # v2.2: Lebanese government expelling Iran
            'iran ambassador expelled lebanon', 'persona non grata iran',
            'lebanon expels iran', 'iranian ambassador beirut',
            'nawaf salam irgc', 'salam iran hezbollah',
            # v2.2: Ceasefire / Iran-US deal Lebanon dimension
            'iran ceasefire lebanon', 'iran demands ceasefire lebanon',
            'tehran ceasefire hezbollah', 'iran us ceasefire lebanon',
            'pezeshkian lebanon', 'iran parliament lebanon',
            # v2.2: Resupply signals
            'iran resupply hezbollah', 'weapons transfer hezbollah iran',
            'iran rearming hezbollah', 'bekaa valley weapons iran',
            # Farsi
            'ایران حزب‌الله', 'محور مقاومت',
            'سپاه قدس لبنان', 'فرماندهی ایران لبنان',
            'دستور ایران حزب‌الله',
            # Arabic
            'إيران حزب الله', 'محور المقاومة',
            'الحرس الثوري لبنان', 'فيلق القدس لبنان',
            'إيران تأمر حزب الله', 'الحرس الثوري يوجه',
            'ضباط إيرانيون بيروت', 'مستشارو الحرس الثوري',
        ],
        'baseline_statements_per_week': 5,
    },
    'israel_lebanon': {
        'name': 'Israel (re: Lebanon)',
        'flag': '🇮🇱',
        'icon': '🔷',
        'color': '#2563eb',
        'role': 'Counter-Hezbollah',
        'keywords': [
            'israel hezbollah', 'israel lebanon', 'israel warns hezbollah',
            'israel threatens lebanon', 'idf lebanon', 'idf hezbollah',
            'israel northern border', 'israel strike lebanon',
            'israel northern front', 'northern front',
            'idf northern', 'idf north', 'northern command',
            'netanyahu hezbollah', 'netanyahu lebanon',
            'gallant hezbollah', 'gallant warns', 'gallant lebanon',
            'katz hezbollah', 'katz lebanon',
            'israel red line', 'israel will not tolerate',
            'israeli airstrike lebanon', 'israeli strike lebanon',
            'israeli operation lebanon', 'idf operation lebanon',
            'south lebanon israel', 'litani river',
            'israeli incursion lebanon', 'ground operation lebanon',
            'ישראל חיזבאללה', 'ישראל לבנון', 'צה"ל לבנון',
            'גבול צפון', 'פיקוד צפון', 'חזית צפון',
            'לבנון', 'חיזבאללה',
            # v2.2: Beirut strikes + casualties (Hebrew)
            'תקיפה בביירות', 'הפצצה בביירות', 'ביירות',
            'פגיעה בביירות', 'תקיפה ישראלית ביירות',
            'הרוגים בלבנון', 'נפגעים בלבנון',
            'צה"ל תקף', 'צה"ל הפציץ', 'מטוסי קרב לבנון',
            'דהיה', 'הדהיה', 'פרברי ביירות',
            # v2.2: IDF strike on central Beirut (April 8 event keywords)
            'ביירות מרכז', 'לב ביירות', 'רובע ביירות',
            # v2.2: IDF ground + Bint Jbeil
            'בנת ג\'בייל', 'בינת ג\'בייל', 'דרום לבנון קרקעי',
            'כוחות צה"ל חדרו', 'כניסה לאדמות לבנון',
            # v2.2: Negotiations / ceasefire (Israeli side)
            'שיחות ישירות לבנון', 'הסכם לבנון', 'הפסקת אש לבנון',
            'תנאים ישראל לבנון', 'נסיגה מלבנון',
            # v2.2: Hezbollah military confirmed via Hebrew
            'פגיעה בחיזבאללה', 'חיסול מפקד', 'סגן מזכ"ל',
            'רקטות מלבנון', 'ירי רקטות', 'כיפת ברזל',
            'קריית שמונה', 'מטולה', 'גליל עליון',
        ],
        'baseline_statements_per_week': 10,
    },
    'lebanese_government': {
        'name': 'Lebanese Government',
        'flag': '🇱🇧',
        'icon': '🏢',
        'color': '#0369a1',
        'role': 'Host State',
        'keywords': [
            'lebanon government', 'lebanese government',
            'lebanese president', 'lebanese prime minister',
            'lebanon cabinet', 'lebanese cabinet',
            'lebanon army', 'lebanese army', 'lebanese armed forces',
            'laf deployment', 'lebanese forces',
            'joseph aoun', 'nawaf salam', 'nabih berri',
            'سيادة لبنان', 'الحكومة اللبنانية', 'الجيش اللبناني',
            'beirut', 'lebanese', 'lebanon',
        ],
        'baseline_statements_per_week': 8,
    },
    'unifil': {
        'name': 'UNIFIL / UN',
        'flag': '🇺🇳',
        'icon': '☮️',
        'color': '#0ea5e9',
        'role': 'Peacekeeping Force',
        'keywords': [
            'unifil', 'un peacekeepers', 'peacekeepers lebanon',
            'resolution 1701', 'unscr 1701', '1701',
            'blue line', 'interim force lebanon',
            'peacekeepers attacked', 'peacekeepers killed',
            'guterres lebanon', 'security council lebanon',
            'un special coordinator', 'unscol',
            'un peacekeeping lebanon', 'un forces lebanon',
            'stephane dujarric lebanon',
            'ocha lebanon', 'un humanitarian lebanon',
        ],
        'baseline_statements_per_week': 5,
    },
    'france': {
        'name': 'France',
        'flag': '🇫🇷',
        'icon': '🏛️',
        'color': '#7c3aed',
        'role': 'Diplomatic Actor',
        'keywords': [
            'france lebanon', 'french lebanon', 'macron lebanon',
            'paris lebanon', 'france hezbollah', 'french envoy lebanon',
            'france mediates lebanon', 'france ceasefire lebanon',
            'french troops unifil', 'france 1701',
            'france diplomatic lebanon', 'french initiative lebanon',
            'barrot lebanon', 'french foreign minister lebanon',
            'france wants lebanon', 'france role lebanon',
            'france push ceasefire', 'france broker lebanon',
            'france israel hezbollah', 'paris talks lebanon',
            'فرنسا لبنان', 'ماكرون لبنان',
        ],
        'baseline_statements_per_week': 4,
    },
    'cyprus': {
        'name': 'Cyprus',
        'flag': '🇨🇾',
        'icon': '🏝️',
        'color': '#d97706',
        'role': 'Diplomatic Host',
        'keywords': [
            'cyprus lebanon', 'nicosia lebanon', 'cyprus talks',
            'cyprus host talks', 'cyprus negotiations lebanon',
            'cyprus mediates', 'cyprus peace talks',
            'cyprus israel hezbollah', 'cyprus diplomatic',
            'anastasiadis lebanon', 'christodoulides lebanon',
            'cyprus foreign minister lebanon',
            'talks in cyprus', 'negotiations in nicosia',
            'cyprus ceasefire', 'cyprus peace initiative',
            'κύπρος λίβανος',
            'قبرص لبنان', 'قبرص مفاوضات',
        ],
        'baseline_statements_per_week': 2,
    },
    'syria_border': {
        'name': 'Syria (Border Watch)',
        'flag': '🇸🇾',
        'icon': '⚠️',
        'color': '#f59e0b',
        'role': 'Border Threat / Buildup Watch',
        'keywords': [
            # Syrian forces / HTS near Lebanon border
            'syria lebanon border', 'syrian forces lebanon',
            'hts lebanon border', 'hts advance lebanon',
            'syrian army lebanon', 'syrian troops border',
            'bekaa valley syria', 'hermon mountain syria',
            'qalamoun border', 'anti-lebanon mountains',
            'syrian buildup lebanon', 'syria military buildup',
            'hts approaching', 'hts pushes toward',
            # Weapons smuggling / corridor
            'weapons corridor lebanon', 'arms smuggling lebanon syria',
            'syria weapons hezbollah', 'iran weapons syria lebanon',
            'smuggling route bekaa', 'weapons transfer hezbollah',
            # Refugee / border crossing
            'syria border crossing lebanon', 'masna crossing',
            'lebanese refugees syria', 'displaced syria lebanon',
            # Post-Assad dynamics
            'post-assad lebanon', 'hts control border',
            'new syrian government lebanon', 'damascus beirut',
            # Arabic
            'سوريا لبنان حدود', 'قوات سورية لبنان',
            'هيئة تحرير الشام لبنان', 'تهريب أسلحة لبنان',
            'البقاع سوريا', 'معبر المصنع',
        ],
        'baseline_statements_per_week': 3,
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

# Vector 1: Ground Operations (IDF incursions, UNIFIL, Syria border buildup)
GROUND_OPS_TRIGGERS = {
    5: [
        # Original
        'idf enters lebanon', 'ground invasion lebanon', 'troops cross border',
        'idf ground operation', 'ground forces inside lebanon',
        'unifil attacked', 'peacekeepers killed', 'peacekeepers shot',
        'hts seizes border', 'syrian forces cross into lebanon',
        # v2.1: Current reality — IDF stationed/present inside Lebanon
        'israeli forces inside lebanon', 'idf inside lebanon',
        'israeli troops inside lebanon', 'israeli soldiers in lebanon',
        'idf stationed in lebanon', 'israeli positions in lebanon',
        'idf positions in southern lebanon', 'israel occupies',
        'israeli military presence in lebanon', 'idf remain in lebanon',
        'israeli forces remain', 'troops remain in lebanon',
        'israeli occupation southern lebanon', 'idf holds positions',
        'idf withdrawal from lebanon', 'israeli withdrawal lebanon',
        # Hebrew transliterated / English reporting on Hebrew sources
        'nekudot amida', 'standing positions lebanon',
        # Arabic reporting phrases
        'قوات إسرائيلية داخل لبنان', 'جنود إسرائيليون داخل لبنان',
        'الاحتلال الإسرائيلي جنوب لبنان', 'تمركز قوات إسرائيلية',
        'نقاط إسرائيلية في لبنان',
    ],
    4: [
        'preparing ground operation', 'ground incursion imminent',
        'troops massing border', 'armored vehicles border',
        'idf readying ground', 'ground operation authorized',
        'syria buildup border', 'hts advancing toward lebanon',
        'weapons convoy detected', 'transfer hezbollah weapons',
        # v2.1: Expansion / reinforcement signals
        'idf expands presence', 'additional troops lebanon',
        'reinforcements southern lebanon', 'idf reinforces positions',
        'expanding positions in lebanon', 'new idf position',
    ],
    3: [
        'will enter lebanon', 'ground operation option', 'idf prepares incursion',
        'troops deployed north', 'infantry brigade border',
        'unifil harassed', 'peacekeepers blocked', 'un forces obstructed',
        'syria border tension', 'hts near border', 'syrian forces buildup',
        'weapons smuggling route', 'arms corridor active',
        'bekaa valley weapons', 'iran weapons route',
    ],
    2: [
        'border incident', 'blue line violation', 'crossing blue line',
        'idf activity border', 'military movement border',
        'unifil concerned', 'un monitors border',
        'syria troop movement', 'hts forces near',
        'bekaa valley activity', 'qalamoun activity',
    ],
    1: [
        'southern lebanon', 'litani river', 'blue line',
        'ground operation', 'incursion', 'border crossing',
        'unifil', 'peacekeepers', 'un forces',
        'syria border', 'bekaa valley', 'hts border',
        'weapons transfer', 'smuggling',
    ],
}

# Vector 2: Rockets / Missiles
ROCKETS_TRIGGERS = {
    5: [
        'rockets hit israel', 'missiles hit israel', 'hezbollah barrage',
        'rocket volley', 'rocket salvo', 'dozens of rockets',
        'hezbollah fired', 'hezbollah launched rockets',
        'idf strikes beirut', 'airstrikes beirut',
        'katyusha', 'falaq rocket', 'burkan missile', 'kornet missile',
        'kiryat shmona', 'nahariya', 'upper galilee rockets',
    ],
    4: [
        'launching rockets at israel', 'firing missiles at israel',
        'hezbollah fires toward', 'rockets toward israel',
        'idf strikes hezbollah', 'airstrikes southern lebanon',
        'anti-ship missile fired', 'drone attack israel',
        'precision missile', 'long-range missile',
    ],
    3: [
        'will fire rockets', 'will launch missiles', 'will strike israel',
        'rocket threat', 'missile threat', 'threatens rocket fire',
        'resume rocket fire', 'escalate rocket attacks',
        'expand strikes', 'widen attacks',
    ],
    2: [
        'rocket incident', 'projectiles fired', 'stray fire',
        'idf artillery', 'idf airstrikes', 'airstrikes resume',
        'rocket alarm', 'red alert north',
    ],
    1: [
        'rockets', 'missiles', 'projectiles', 'drone',
        'airstrikes', 'strikes', 'bombardment',
        'صواريخ', 'رشقة', 'غارة',
        'רקטות', 'טילים', 'תקיפות',
    ],
}

# Vector 3: Ceasefire / Diplomacy
CEASEFIRE_TRIGGERS = {
    5: [
        'ceasefire agreement signed', 'peace deal signed',
        'hezbollah agrees ceasefire', 'israel accepts ceasefire',
        'ceasefire takes effect', 'ceasefire implemented',
    ],
    4: [
        'ceasefire framework agreed', 'deal reached lebanon',
        'france broker deal', 'cyprus talks successful',
        'us mediates ceasefire', 'ceasefire terms agreed',
        'withdrawal agreement', 'hezbollah withdrawal',
    ],
    3: [
        'ceasefire proposal', 'ceasefire offer', 'france proposes',
        'cyprus hosts talks', 'talks in nicosia', 'paris initiative',
        'macron proposes ceasefire', 'french ceasefire plan',
        'us envoy ceasefire', 'envoy visits beirut',
        'negotiate ceasefire', 'diplomatic solution',
    ],
    2: [
        'ceasefire talks', 'peace negotiations', 'diplomatic push',
        'france envoy', 'cyprus meeting', 'paris meeting',
        'de-escalation talks', 'back-channel talks',
        'france calls for ceasefire', 'eu calls for ceasefire',
    ],
    1: [
        'ceasefire', 'peace talks', 'negotiations', 'diplomacy',
        'envoy', 'mediator', 'resolution 1701', 'implementation',
        'وقف إطلاق النار', 'مفاوضات', 'دبلوماسية',
        'הפסקת אש', 'משא ומתן',
    ],
}

# Vector 4: Cross-border Escalation (catch-all escalatory signals)
CROSSBORDER_TRIGGERS = {
    5: [
        'all-out war lebanon', 'full scale war', 'war declared lebanon',
        'lebanon war', 'war has begun', 'war erupts',
    ],
    4: [
        'point of no return', 'decision has been made', 'war inevitable',
        'expand war to lebanon', 'open new front lebanon',
        'second front lebanon', 'multi-front war',
    ],
    3: [
        'will not tolerate', 'red line crossed', 'will pay price',
        'devastating response', 'crushing response',
        'declaration of war', 'act of war',
        'any aggression will be met', 'playing with fire',
        'last warning', 'final warning', 'ultimatum',
    ],
    2: [
        'growing tensions', 'escalation risk', 'dangerous path',
        'miscalculation risk', 'spiral of violence',
        'deeply concerned', 'urges restraint',
    ],
    1: [
        'tensions', 'escalation', 'confrontation', 'crisis',
        'instability', 'conflict risk',
    ],
}

# Conditional Threats — "if X then Y" tripwire language
CONDITIONAL_TRIGGERS = {
    3: [
        'if hezbollah fires', 'if rockets continue', 'if attacks continue',
        'if israel attacks', 'if the ceasefire fails', 'if 1701 is violated',
        'should hezbollah', 'should israel', 'if beirut does not',
        'if the government fails', 'any attack on israel will',
        'if weapons transfer continues', 'if syria border is not secured',
    ],
    2: [
        'we reserve the right', 'all options on the table',
        'prepared to respond', 'will not hesitate',
        'conditional ceasefire', 'unless hezbollah withdraws',
        'if demands are not met', 'if negotiations fail',
    ],
    1: [
        'unless', 'provided that', 'on condition',
        'in response to', 'should the situation',
    ],
}


# ========================================
# SPECIFICITY SCORER
# ========================================

SPECIFIC_GEOGRAPHIES = [
    'beirut', 'south beirut', 'dahieh', 'southern suburb',
    'southern lebanon', 'south lebanon', 'litani', 'sidon', 'tyre',
    'bint jbeil', 'khiam', 'marjayoun', 'nabatieh',
    'kiryat shmona', 'metula', 'nahariya', 'upper galilee', 'haifa',
    'bekaa valley', 'baalbek', 'hermel', 'qalamoun',
    'blue line', 'border crossing', 'masna crossing',
    'hermon mountain', 'anti-lebanon mountains',
]

SPECIFIC_ASSETS = [
    'radwan force', 'anti-tank missile', 'precision missile',
    'drone swarm', 'rocket battery', 'missile battery',
    'weapons depot', 'ammunition depot', 'tunnel network',
    'iron dome', 'david sling', 'arrow missile',
    'french troops', 'italian peacekeepers', 'spanish peacekeepers',
    'us embassy beirut', 'embassy compound',
]

TIME_BOUNDED = [
    'within 24 hours', 'within 48 hours', 'within 72 hours',
    'by tomorrow', 'before the end of', 'in the coming hours',
    'imminent', 'within days', 'tonight', 'this week',
    'before friday', 'deadline',
]

OPERATIONAL_FRAMING = [
    'preparing to launch', 'positioned to strike', 'ready to fire',
    'forces deployed', 'troops massing', 'coordinated attack',
    'multi-front', 'simultaneous strike', 'saturation attack',
    'ground operation imminent', 'incursion planned',
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
        print(f"[Lebanon Rhetoric] Delta compute error: {e}")
        return None


# ========================================
# ACTOR BASELINE TRACKING
# ========================================

def _update_actor_baselines(actor_results):
    """
    Exponential moving average of statement_count and max_level per actor.
    Stored in Redis as rhetoric_baseline:lebanon. 30-day TTL.
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
        print(f"[Lebanon Rhetoric] ✅ Actor baselines updated")
        return updated
    except Exception as e:
        print(f"[Lebanon Rhetoric] Baseline update error: {e}")
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
                actor_info = LEBANON_ACTORS.get(actor_id, {})
                anomalies.append({
                    'actor_id': actor_id,
                    'actor_name': actor_info.get('name', actor_id),
                    'actor_flag': actor_info.get('flag', ''),
                    'expected_statements': round(avg_statements),
                    'actual_statements': actual,
                    'deviation': f'{pct_below}% below baseline',
                    'signal': 'Unusual quiet — possible operational security or patron direction',
                })
                print(f"[Lebanon Rhetoric] 🔇 Silence anomaly: {actor_id} ({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Lebanon Rhetoric] Silence detection error: {e}")
    return anomalies


# ========================================
# CROSS-THEATER COORDINATION
# ========================================

def _write_crosstheater_signal(result):
    """
    Write Lebanon's fingerprint to the shared cross-theater Redis key.
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
        for actor_id in ['hezbollah_military', 'hezbollah_political']:
            for art in actors.get(actor_id, {}).get('top_articles', [])[:3]:
                title_lower = art.get('title', '').lower()
                for geo in SPECIFIC_GEOGRAPHIES:
                    if geo in title_lower and geo not in named_targets:
                        named_targets.append(geo)

        existing['lebanon'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Lebanon',
            'level': result.get('theatre_escalation_level', 0),
            'score': result.get('rhetoric_score', 0),
            'theatre_score': result.get('rhetoric_score', 0),
            'ground_ops_level': result.get('ground_ops_level', 0),
            'rockets_level': result.get('rockets_level', 0),
            'top_phrases': top_phrases[:5],
            'named_targets': named_targets[:8],
            'actor_levels': {
                aid: actors.get(aid, {}).get('max_escalation_level', 0)
                for aid in ['hezbollah_political', 'hezbollah_military', 'iran_lebanon']
            },
            'specificity_score': result.get('specificity_score', 0),
        }

        _redis_set(CROSSTHEATER_KEY, existing, ttl=8 * 3600)
        print(f"[Lebanon Rhetoric] ✅ Cross-theater fingerprint written")
    except Exception as e:
        print(f"[Lebanon Rhetoric] Cross-theater write error: {e}")


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

        expected = ['yemen', 'iraq', 'lebanon', 'iran', 'israel']
        missing = [t for t in expected if t not in fresh]
        if missing:
            print(f"[CrossTheater] Note: {missing} fingerprints not yet available")

        # Check 1: Simultaneous elevation across proxy theaters
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
        print(f"[Lebanon Rhetoric] Cross-theater detection error: {e}")

    return findings


# ========================================
# DATA FETCHING
# ========================================

def _fetch_rss(feed_url, source_name, max_items=20):
    articles = []
    try:
        response = requests.get(feed_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code != 200:
            return []
        root = ET.fromstring(response.content)
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


def fetch_lebanon_articles(days=3):
    all_articles = []

    # RSS Feeds — expanded for France, Cyprus, Syria border
    rss_feeds = {
        # ── Lebanese domestic sources (NEW) ──────────────────────
        'Naharnet':           'https://www.naharnet.com/stories/en/rss',
        'LBCI (EN)':          'https://www.lbcgroup.tv/rss/en',
        'MTV Lebanon':        'https://www.mtv.com.lb/en/rss',
        'L\'Orient Today':    'https://today.lorientlejour.com/rss',
        'The961':             'https://www.the961.com/feed/',
        'An-Nahar (AR)':      'https://www.annahar.com/rss',
        # ── Regional Arabic (NEW) ─────────────────────────────────
        'Lebanon24 (AR)':     'https://www.lebanon24.com/rss',
        'NNA Lebanon':        'https://www.nna-leb.gov.lb/en/rss',
        # ── Existing sources ──────────────────────────────────────
        'Al-Manar (EN)':      'https://english.almanar.com.lb/rss',
        'Al-Manar (AR)':      'https://almanar.com.lb/rss',
        'UN News (Lebanon)':  'https://news.un.org/feed/subscribe/en/news/region/middle-east/feed/rss.xml',
        'MEMRI':              'https://www.memri.org/rss.xml',
        'Iran Wire (EN)':     'https://iranwire.com/en/feed/',
        'Times of Israel':    'https://www.timesofisrael.com/feed/',
        'i24NEWS':            'https://www.i24news.tv/en/rss',
        'Jerusalem Post':     'https://www.jpost.com/rss/rssfeedsfrontpage.aspx',
        'Le Monde (FR)':      'https://www.lemonde.fr/rss/une.xml',
        'France24 (EN)':      'https://www.france24.com/en/rss',
    }

    for name, url in rss_feeds.items():
        articles = _fetch_rss(url, name)
        all_articles.extend(articles)
        time.sleep(0.3)

    print(f"[Rhetoric] RSS: {len(all_articles)} articles from {len(rss_feeds)} feeds")

    # GDELT — expanded with Syria border + France + Cyprus queries
    gdelt_queries = {
        'eng': [
            'hezbollah OR lebanon OR "southern lebanon"',
            'hezbollah OR nasrallah OR "naim qassem"',
            'israel hezbollah OR idf lebanon',
            'unifil OR "resolution 1701"',
            'hezbollah rockets volley barrage israel',
            'israel infrastructure strike lebanon threat',
            'israel warns lebanon government posture',
            'lebanon ceasefire violation rockets',
            'israel northern border rockets galilee',
            'beirut strike israel warns',
            # v2.0: Syria border
            'syria border lebanon buildup hts',
            'weapons smuggling hezbollah syria lebanon',
            'hts advance lebanon border',
            'bekaa valley weapons transfer',
            # v2.0: France + Cyprus diplomacy
            'france lebanon ceasefire macron',
            'cyprus talks lebanon negotiations',
            'france mediates hezbollah israel',
            'paris initiative lebanon peace',
        ],
        'ara': [
            'حزب الله OR لبنان',
            'المقاومة الإسلامية لبنان',
            'سوريا لبنان حدود',
            'فرنسا لبنان',
            # v2.1: Arabic ground ops — Israeli forces in south Lebanon
            'قوات إسرائيلية جنوب لبنان',
            'توغل إسرائيلي لبنان',
            'جنود إسرائيليون لبنان',
            'اجتياح إسرائيلي لبنان',
            'تمركز إسرائيلي لبنان',
            'نقاط إسرائيلية جنوب لبنان',
            'قوات الاحتلال لبنان',
            'الجيش الإسرائيلي داخل لبنان',
            # v2.2: Internal security / coup plot signals (NEW)
            'انقلاب لبنان حزب الله',
            'السراي الحكومي بيروت حصار',
            'نواف سلام اغتيال OR اعتقال',
            'الحرس الثوري بيروت',
            'حزب الله بيروت احتلال',
            'أمن الدولة لبنان تواطؤ',
            'جوزيف عون استقالة OR اغتيال',
            'انتفاضة شيعية لبنان',
            'فرنجية الحرس الثوري رئاسة',
        ],
        'heb': [
            'חיזבאללה OR לבנון',
            'גבול צפון OR פיקוד צפון',
            # v2.1: Hebrew ground ops — IDF positions/presence in Lebanon
            'כוחות צה"ל בלבנון',
            'חיילים בלבנון',
            'נקודות עמידה לבנון',
            'כוחות בדרום לבנון',
            'התמקמות בלבנון',
            'עמדות בלבנון',
            'פעילות קרקעית לבנון',
            'כיבוש דרום לבנון',
            'נוכחות צבאית לבנון',
            'צה"ל שוהה בלבנון',
            # v2.2: Beirut strikes — IDF airstrikes on Beirut/Dahiyeh
            'תקיפה בביירות',
            'ביירות הפצצה',
            'צה"ל תקף ביירות',
            'פגיעה בדהיה',
            'ביירות מרכז תקיפה',
            # v2.2: Casualties + healthcare (Hebrew MoPH reporting via Hebrew OSINT)
            'הרוגים ופצועים לבנון',
            'קורבנות לבנון',
            'בית חולים לבנון תקיפה',
            'עובדי בריאות נהרגו',
            # v2.2: Ceasefire / negotiations Hebrew signals
            'הפסקת אש לבנון',
            'שיחות ישירות ישראל לבנון',
            'הסכם לבנון ישראל',
            'נסיגת צה"ל לבנון',
            # v2.2: Hezbollah rockets into Israel (Hebrew alert sources)
            'רקטות מלבנון לישראל',
            'ירי מלבנון',
            'קריית שמונה רקטות',
            'אזעקות בצפון',
        ],
        'fas': [
            # v2.0: original
            'حزب‌الله OR لبنان',
            # v2.2: IRGC direction + Quds Force Lebanon signals
            'سپاه قدس لبنان',           # Quds Force Lebanon
            'سپاه پاسداران لبنان',      # IRGC Lebanon
            'فرماندهی حزب‌الله',         # Hezbollah command
            'محور مقاومت لبنان',         # Axis of Resistance Lebanon
            # v2.2: Operational direction signals
            'دستور ایران حزب‌الله',      # Iran orders Hezbollah
            'هدایت ایران لبنان',          # Iran directing Lebanon
            'عملیات لبنان ایران',         # Lebanon Iran operations
            'پشتیبانی ایران مقاومت',     # Iran support resistance
            # v2.2: Martyrdom / commander killed signals (IDF kills IRGC in Lebanon)
            'شهادت فرمانده قدس',         # Martyrdom Quds commander
            'فرمانده سپاه لبنان',         # IRGC commander Lebanon
            'شهید لبنان سپاه',            # Martyr Lebanon IRGC
            # v2.2: Ceasefire / negotiations Iranian framing
            'آتش‌بس لبنان',              # Lebanon ceasefire
            'مذاکرات لبنان ایران',        # Lebanon Iran negotiations
            'حمایت ایران لبنان',          # Iran support Lebanon
            # v2.2: Hezbollah rearmament / resupply signals
            'تسلیح حزب‌الله',            # Hezbollah arming
            'تجهیز مقاومت لبنان',        # Equipping Lebanon resistance
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
            'hezbollah OR "southern lebanon" OR "Naim Qassem"',
            'Israel Lebanon border OR IDF Lebanon',
            'UNIFIL Lebanon OR "resolution 1701"',
            'France Lebanon ceasefire OR Cyprus Lebanon talks',
            'Syria Lebanon border HTS weapons',
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
        nitter_posts = fetch_nitter_lebanon(days=days)
        for p in nitter_posts:
            u = p.get('url', '')
            if u and u not in seen:
                seen.add(u)
                unique.append(p)
    except Exception as e:
        print(f"[Lebanon Rhetoric] Nitter error: {e}")

    tg_c  = sum(1 for a in unique if 'Telegram' in str(a.get('source', '')))
    nit_c = sum(1 for a in unique if 'Nitter' in str(a.get('source', '')))
    rss_c = len(unique) - tg_c - nit_c
    print(f"[Rhetoric] Total unique articles: {len(unique)} ({rss_c} RSS + {tg_c} TG + {nit_c} Nitter)")
    return unique


# ========================================
# CLASSIFICATION ENGINE
# ========================================

def classify_actor(article):
    """Determine which Lebanon-theatre actor(s) an article relates to — multi-match."""
    title   = (article.get('title') or '').lower()
    desc    = (article.get('description') or '').lower()
    content = (article.get('content') or '').lower()
    text    = f"{title} {desc} {content}"

    matched = []
    for actor_id, actor_data in LEBANON_ACTORS.items():
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
# (e.g. LAF deploying, GOL issuing ultimatum to Hezbollah).
REPORTING_ACTORS = {
    'lebanese_government', 'unifil', 'france', 'cyprus'
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
    'condemns hezbollah',
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
    v2.1: Reporting actors (GOL, UNIFIL, France, Cyprus) get capped
    at level 2 if reporting/condemning language is detected —
    prevents GOL from scoring Active Conflict just from reporting
    on Kiryat Shmona. Cap does NOT apply if they use their own
    genuinely threatening language without reporting context.
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
    actor_data = LEBANON_ACTORS.get(actor_id, {})
    for person in actor_data.get('spokespersons', []):
        if person.lower() in text:
            return person
    return None


def extract_topics(article):
    title = (article.get('title') or '').lower()
    desc  = (article.get('description') or '').lower()
    text  = f"{title} {desc}"

    topic_keywords = {
        'ceasefire':      ['ceasefire', 'cease-fire', 'truce', 'وقف إطلاق النار', 'הפסקת אש'],
        'rearmament':     ['rearm', 'weapons', 'arms shipment', 'smuggling', 'تسليح', 'חימוש'],
        'border_incident':['blue line', 'border violation', 'border incident', 'خط أزرق'],
        'rockets':        ['rocket', 'missile', 'projectile', 'صاروخ', 'רקטה'],
        'negotiations':   ['negotiation', 'talks', 'diplomacy', 'france', 'cyprus', 'مفاوضات'],
        'ground_ops':     ['incursion', 'ground operation', 'troops', 'invasion'],
        'syria_border':   ['syria border', 'hts', 'bekaa', 'weapons transfer', 'smuggling'],
        'displacement':   ['displaced', 'refugees', 'return home', 'نازحين', 'פליטים'],
        'sovereignty':    ['sovereignty', 'resolution 1701', 'سيادة', 'ריבונות'],
        'humanitarian':   ['humanitarian', 'aid', 'relief', 'إنساني', 'הומניטרי'],
        'reconstruction': ['reconstruction', 'rebuild', 'recovery', 'إعادة إعمار'],
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
    axis_actors = {'hezbollah_political', 'hezbollah_military', 'iran_lebanon'}

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
                            f"{LEBANON_ACTORS[stmt_a['actor']]['name']} and "
                            f"{LEBANON_ACTORS[stmt_b['actor']]['name']} "
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
    Weighted combination of vector scores + actor escalation + coordination.
    """
    score = 0

    # Vector contributions (max 60)
    score += ground_ops_level * 5    # max 25
    score += rockets_level * 7       # max 35 — rockets are the most acute signal
    score += crossborder_level * 3   # max 15
    # Ceasefire is inverse — higher ceasefire signal = de-escalatory, small positive contribution
    score += ceasefire_level * 1     # max 5

    # Cap vector contribution at 60
    score = min(score, 60)

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

    return min(score, 100)


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
        'theatre': 'Lebanon',
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
            for actor_id, data in LEBANON_ACTORS.items()
        },
        'coordination_alerts': [],
        'alerts': [],
        'awaiting_scan': True,
        'message': 'No data yet — scan in progress',
        'version': '2.0.0',
    }


# ========================================
# NITTER -- Primary source accounts
# Lebanon: IDF, Israeli leadership, LAF, UNIFIL, France
# ========================================
NITTER_MIRRORS = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

NITTER_ACCOUNTS_LEBANON = [
    ("IDF",                 1.3, "IDF -- Lebanon strike claims, Hezbollah warnings, GOL ultimatums"),
    ("AvichayAdraee",       1.2, "IDF Arabic spokesperson -- operational claims vs Hezbollah"),
    ("IsraeliPM",           1.1, "Israeli PM -- Lebanon red line statements"),
    ("KatzIsrael",          1.1, "Defense Minister Katz -- Hezbollah/Lebanon ultimatums"),
    ("CENTCOM",             1.0, "CENTCOM -- Lebanon/Hezbollah operations"),
    ("StateDept",           1.0, "State Dept -- Lebanon diplomatic signals"),
    ("LebarmyOfficial",     1.1, "Lebanese Armed Forces -- LAF deployment signals"),
    ("UNIFIL_Southlebanon", 1.0, "UNIFIL -- Blue Line incidents, withdrawal signals"),
    ("francediplo_EN",      0.9, "French MFA -- Lebanon diplomatic push"),
    ("LongWarJournal",      0.9, "Long War Journal -- Hezbollah/Lebanon analysis"),
    ("ElintNews",           0.9, "ELINT News -- Lebanon/Hezbollah OSINT"),
]


def _fetch_nitter_lebanon(username, weight=1.0, timeout=8):
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
                print(f"[Lebanon Rhetoric/Nitter] @{username}: {len(posts)} posts via {mirror}")
                return posts
        except Exception as e:
            print(f"[Lebanon Rhetoric/Nitter] @{username} {mirror} failed: {str(e)[:60]}")
            continue
    print(f"[Lebanon Rhetoric/Nitter] @{username}: all mirrors failed")
    return []


def fetch_nitter_lebanon(days=3):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen = set()
    for username, weight, desc in NITTER_ACCOUNTS_LEBANON:
        posts = _fetch_nitter_lebanon(username, weight=weight)
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
    print(f"[Lebanon Rhetoric/Nitter] Total: {len(all_posts)} posts")
    return all_posts


# ========================================
# CORE SCAN FUNCTION
# ========================================

def run_rhetoric_scan(days=3):
    """
    Execute full Lebanon rhetoric scan.
    Returns structured v2.0 analysis data with vectors, delta, specificity,
    baselines, silence anomalies, conditional threats, cross-theater coordination.
    """
    print(f"\n[Rhetoric Scan] Starting Lebanon theatre scan ({days}-day window)...")
    scan_start = time.time()

    articles = fetch_lebanon_articles(days)

    if not articles:
        print("[Rhetoric Scan] No articles fetched, returning empty result")
        return _build_empty_result()

    # Per-actor analysis state
    actor_results = {}
    for actor_id, actor_data in LEBANON_ACTORS.items():
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

        # Coordination signal: Hezbollah + Iran in same article
        if ('hezbollah_political' in actors or 'hezbollah_military' in actors) \
                and 'iran_lebanon' in actors:
            theatre_vectors['coordination_signals'].append({
                'message': 'Iran-Hezbollah coordination signal detected',
                'article': article.get('title', '')[:100],
                'published': pub_date,
            })

    # Post-processing
    print(f"[Rhetoric] Classification: {total_classified}/{len(articles)} articles matched")
    for actor_id, ar in actor_results.items():
        # Silence detection (static baseline, Redis-backed in future scans)
        baseline = LEBANON_ACTORS[actor_id].get('baseline_statements_per_week', 3)
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

    # Theatre specificity
    spec_scores = theatre_vectors['specificity_scores']
    theatre_specificity = round(sum(spec_scores) / len(spec_scores), 1) if spec_scores else 0

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success': True,
        'theatre': 'Lebanon',
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
            print(f"[Lebanon Rhetoric] 📈 History snapshot saved")
    except Exception as e:
        print(f"[Lebanon Rhetoric] History append error (non-fatal): {e}")

    # ── Daily snapshot (legacy trend system — kept for backward compat) ──
    _save_daily_snapshot(result)

    # ── Actor baselines + silence anomalies ──
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # ── Delta ──
    result['delta'] = _compute_delta()

    # ── Cross-theater coordination ──
    _write_crosstheater_signal(result)
    result['crosstheater_coordination'] = _detect_crosstheater_coordination()

    # Signal interpretation -- So What, Red Lines, Historical Patterns
    if INTERPRETER_AVAILABLE:
        try:
            result['interpretation'] = lebanon_interpret_signals(result)
            best = result['interpretation']['historical_matches']
            best_pct = best[0]['similarity'] if best else 'none'
            laf_gap = result['interpretation']['so_what'].get('laf_enforcement_gap', False)
            iran_dir = result['interpretation']['so_what'].get('iran_directing', False)
            print(f"[Lebanon Rhetoric] Interpreter: {result['interpretation']['red_lines']['breached_count']} red lines breached, best match: {best_pct}%"
                  f"{' | LAF GAP' if laf_gap else ''}{' | IRAN DIRECTING' if iran_dir else ''}")
        except Exception as e:
            print(f"[Lebanon Rhetoric] Warning: Interpreter error (non-fatal): {e}")

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

        history = _redis_get('rhetoric:lebanon:history:daily') or {}
        if 'snapshots' not in history:
            history['snapshots'] = {}
        history['snapshots'][today] = snapshot

        all_dates = sorted(history['snapshots'].keys())
        if len(all_dates) > 90:
            for old_date in all_dates[:-90]:
                del history['snapshots'][old_date]

        history['last_updated'] = datetime.now(timezone.utc).isoformat()
        _redis_set('rhetoric:lebanon:history:daily', history, ttl=24 * 91 * 3600)
        print(f"[Rhetoric] Saved daily snapshot for {today}")
    except Exception as e:
        print(f"[Rhetoric] Snapshot save error: {e}")


def get_rhetoric_trends(days=30):
    try:
        history = _redis_get('rhetoric:lebanon:history:daily')
        if not history or 'snapshots' not in history:
            return {'success': False, 'message': 'No trend data yet', 'days_collected': 0}

        snapshots = history['snapshots']
        sorted_dates = sorted(snapshots.keys())[-days:]

        trends = {
            'dates': [], 'rhetoric_score': [], 'theatre_level': [],
            'actors': {actor_id: [] for actor_id in LEBANON_ACTORS},
        }

        for date in sorted_dates:
            snap = snapshots[date]
            trends['dates'].append(date)
            trends['rhetoric_score'].append(snap.get('rhetoric_score', 0))
            trends['theatre_level'].append(snap.get('theatre_level', 0))
            for actor_id in LEBANON_ACTORS:
                actor_snap = snap.get('actors', {}).get(actor_id, {})
                trends['actors'][actor_id].append(actor_snap.get('escalation_level', 0))

        return {'success': True, 'days_collected': len(sorted_dates), 'trends': trends}
    except Exception as e:
        return {'success': False, 'message': str(e), 'days_collected': 0}


# ========================================
# FLASK ENDPOINT REGISTRATION
# ========================================

def register_rhetoric_endpoints(app):
    from flask import request as flask_request, jsonify, make_response

    def _cors_response(data, status=200):
        resp = make_response(jsonify(data), status)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    @app.route('/api/rhetoric/lebanon', methods=['GET'])
    def api_rhetoric_lebanon():
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

    @app.route('/api/rhetoric/lebanon/summary', methods=['GET'])
    def api_rhetoric_lebanon_summary():
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
                # v2.0 enriched
                'specificity_score': cached.get('specificity_score', 0),
                'delta':             cached.get('delta'),
                'silence_anomalies': cached.get('silence_anomalies', []),
                'total_articles':    cached.get('total_articles', 0),
                # Alerts
                'alerts':      cached.get('alerts', [])[:3],
                'scanned_at':  cached.get('scanned_at', ''),
                'timestamp':   cached.get('timestamp', cached.get('scanned_at', '')),
            })

        except Exception as e:
            return _cors_response({'error': str(e)[:200]}, 500)

    @app.route('/api/rhetoric/lebanon/trends', methods=['GET'])
    def api_rhetoric_lebanon_trends():
        try:
            days = int(flask_request.args.get('days', 30))
            days = min(days, 90)
            return _cors_response(get_rhetoric_trends(days))
        except Exception as e:
            return _cors_response({'success': False, 'error': str(e)[:200]}, 500)

    @app.route('/api/rhetoric/lebanon/history', methods=['GET'])
    def api_rhetoric_lebanon_history():
        """
        Rolling history normalized to match Yemen/Syria/Iraq /history shape.
        Reads from lpush key (rhetoric:lebanon:history) first,
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
                'theatre': 'Lebanon',
                'history_key': RHETORIC_HISTORY_KEY,
                'count': len(entries),
                'entries': entries,
            })
        except Exception as e:
            return _cors_response({'success': False, 'error': str(e)[:200]}, 500)

    print("[Rhetoric Tracker] ✅ Endpoints registered: "
          "/api/rhetoric/lebanon, /api/rhetoric/lebanon/summary, "
          "/api/rhetoric/lebanon/trends, /api/rhetoric/lebanon/history")

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
