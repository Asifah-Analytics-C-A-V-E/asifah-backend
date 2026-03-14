"""
Asifah Analytics — Rhetoric & Pattern Recognition Tracker v1.1.0
February 26, 2026

print(f"[Rhetoric Cache DEBUG] UPSTASH_URL={'SET' if UPSTASH_REDIS_URL else 'MISSING'}, UPSTASH_TOKEN={'SET' if UPSTASH_REDIS_TOKEN else 'MISSING'}, REDIS_URL={'SET' if REDIS_URL else 'MISSING'}")

Tracks rhetorical patterns, spokesperson changes, escalation ladders,
and coordination signals across actors in a given theatre.

INITIAL DEPLOYMENT: Lebanon theatre
  Actors tracked:
    - Hezbollah (political wing: statements, press conferences)
    - Hezbollah (military wing: operational language, threats)
    - Iran re: Lebanon (IRGC, Supreme Leader, FM statements about Lebanon)
    - Israel re: Lebanon (IDF, PM, defense minister statements about Lebanon)
    - Lebanese Government (PM, President, parliament)
    - UNIFIL (peacekeeping signals)

CAPABILITIES:
  1. Rhetoric Escalation Index — per-actor severity ladder over time
  2. Voice/Spokesperson Tracking — who is speaking, new voices, silence
  3. Silence Detector — flags when an actor goes quiet vs their baseline
  4. Coordination Detector — temporal clustering of aligned statements
  5. Topic Shift Detection — tracks what actors are talking ABOUT

DATA SOURCES (pre-Telegram):
  - Al-Manar RSS (Hezbollah's own outlet)
  - MEMRI (translated leadership statements)
  - Iran Wire (English + Farsi)
  - GDELT (Arabic, Hebrew, Farsi, English)
  - NewsAPI (English)
  - Reddit (supplementary)

CACHING:
  - Redis-backed (Upstash REST API or redis-py, auto-detected)
  - 12-hour scan cycle (background thread)
  - Endpoint serves cached data, never blocks on scan
  - Daily snapshots stored for trend analysis (90-day rolling window)

OUTPUTS:
  - /api/rhetoric/lebanon — full rhetoric analysis for Lebanon page
  - /api/rhetoric/lebanon/summary — compact summary for country card
  - /api/rhetoric/lebanon/trends — historical trend data for sparklines
  - Feeds rhetoric_alert into Lebanon Stability Index

CHANGELOG:
  v1.1.0 (2026-02-26):
    - BROADENED actor keywords across all 6 actors to fix false silence alerts
    - Added standalone 'hezbollah' as keyword (was requiring 2-word phrases)
    - Added 'حزب الله' standalone (was requiring following Arabic word)
    - Added 'المقاومة' standalone for hezbollah_military (Al-Manar's term)
    - Added 'al-manar', 'almanar' as hezbollah_military keywords
    - Added 'the resistance', 'resistance forces' for military wing
    - Broadened israel_lebanon: 'northern front', 'idf north', standalone Hebrew
    - Broadened lebanese_government: 'beirut', 'lebanese', 'lebanon' as catch-all
    - Added 'axis of resistance', 'iranian-backed', 'iran-backed' for iran_lebanon
    - Added 'un peacekeeping lebanon', 'un forces lebanon', '1701' for unifil
    - Raised baseline_statements_per_week to match real article volumes
    - Added GDELT retry with 60s timeout (was 30s, matching military_tracker fix)
    - Added classification debug logging per actor
    - Added 'tensions', 'escalation', 'concern' to level 2 escalation phrases
    - Added 'said', 'announced', 'noted', 'reported' to level 1 phrases

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

# Redis — auto-detect which pattern is available
REDIS_URL = os.environ.get('REDIS_URL', os.environ.get('REDIS_TOKEN', None))
UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

# Cache keys
RHETORIC_CACHE_KEY = 'rhetoric:lebanon:latest'
RHETORIC_HISTORY_KEY = 'rhetoric:lebanon:history'

# Scan interval
SCAN_INTERVAL_HOURS = 12
SCAN_INTERVAL_SECONDS = SCAN_INTERVAL_HOURS * 3600

# Background scan lock
_scan_running = False
_scan_lock = threading.Lock()


# ========================================
# REDIS HELPERS (dual-mode: redis-py or Upstash REST)
# ========================================

_redis_client = None

def _init_redis():
    """Initialize redis-py client if REDIS_URL is available."""
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


def cache_get(key):
    """Get a value from Redis (tries redis-py first, then Upstash REST)."""
    # Try redis-py
    client = _init_redis()
    if client:
        try:
            data = client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            print(f"[Rhetoric Cache] redis-py get error: {e}")

    # Try Upstash REST
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{key}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get("result"):
                return json.loads(data["result"])
        except Exception as e:
            print(f"[Rhetoric Cache] Upstash get error: {e}")

    return None


def cache_set(key, value, ttl_hours=24):
    """Set a value in Redis (writes to both redis-py and Upstash if available)."""
    payload = json.dumps(value, default=str)
    ttl_seconds = int(ttl_hours * 3600)

    # Try redis-py
    client = _init_redis()
    if client:
        try:
            client.setex(key, ttl_seconds, payload)
        except Exception as e:
            print(f"[Rhetoric Cache] redis-py set error: {e}")

    # Try Upstash REST
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            import urllib.parse
            encoded_payload = urllib.parse.quote(payload, safe='')
            requests.post(
                f"{UPSTASH_REDIS_URL}/set/{key}/{encoded_payload}?EX={ttl_seconds}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                },
                timeout=10
            )
        except Exception as e:
            print(f"[Rhetoric Cache] Upstash set error: {e}")


def is_cache_fresh(cached_data, max_age_hours=12):
    """Check if cached data is still within TTL."""
    if not cached_data or 'scanned_at' not in cached_data:
        return False
    try:
        scanned = datetime.fromisoformat(cached_data['scanned_at'])
        age = datetime.now(timezone.utc) - scanned
        return age.total_seconds() < (max_age_hours * 3600)
    except:
        return False


# ========================================
# ACTOR DEFINITIONS — LEBANON THEATRE
# v1.1.0: Broadened keywords to reduce false silence alerts
# ========================================

LEBANON_ACTORS = {
    'hezbollah_political': {
        'name': 'Hezbollah (Political)',
        'flag': '🇱🇧',
        'icon': '🏛️',
        'description': 'Political wing statements, press conferences, parliamentary bloc',
        'spokespersons': [
            'naim qassem', 'mohammad raad', 'hassan fadlallah',
            'ibrahim amin al-sayyed', 'ali ammar', 'hussein hajj hassan',
            'hezbollah parliamentary', 'loyalty to resistance bloc',
            'hezbollah political bureau', 'hezbollah media office',
            'hezbollah statement', 'hezbollah press conference',
            # Arabic
            'نعيم قاسم', 'محمد رعد', 'حسن فضل الله',
            'كتلة الوفاء للمقاومة',
        ],
        'keywords': [
            # v1.1.0: Core identifiers — standalone catch-all
            'hezbollah', 'hezballah', 'hizballah', 'hizbollah', 'hizb allah',
            # Political-specific (kept for precision scoring later)
            'hezbollah statement', 'hezbollah says', 'hezbollah declares',
            'hezbollah political', 'hezbollah parliament', 'hezbollah demands',
            'hezbollah condemns', 'hezbollah calls for', 'hezbollah rejects',
            'hezbollah press conference', 'hezbollah media relations',
            'naim qassem', 'qassem says', 'qassem warns',
            'loyalty to resistance', 'resistance bloc',
            'hezbollah leader', 'hezbollah chief', 'hezbollah secretary',
            # Arabic — standalone حزب الله catches all Hezbollah articles
            'حزب الله', 'حزب اللـه', 'حزبالله',
            'نعيم قاسم', 'كتلة الوفاء للمقاومة',
            'حزب الله بيان', 'حزب الله يدين', 'حزب الله يرفض',
            'حزب الله يطالب',
        ],
        # v1.1.0: Raised from 5 — with broadened keywords we'll catch more
        'baseline_statements_per_week': 12,
    },
    'hezbollah_military': {
        'name': 'Hezbollah (Military)',
        'flag': '🇱🇧',
        'icon': '⚔️',
        'description': 'Military wing: operational claims, threats, battle reports',
        'spokespersons': [
            'islamic resistance in lebanon', 'islamic resistance operations',
            'hezbollah military media', 'hezbollah combat media',
            'war media', 'al-manar military',
            # Arabic
            'المقاومة الإسلامية في لبنان', 'الإعلام الحربي',
        ],
        'keywords': [
            # Operational language
            'hezbollah fires', 'hezbollah launches', 'hezbollah strikes',
            'hezbollah rockets', 'hezbollah missile', 'hezbollah drone',
            'hezbollah attack', 'hezbollah targets', 'hezbollah claims',
            'hezbollah operation', 'hezbollah retaliation',
            'hezbollah military', 'hezbollah forces', 'hezbollah arms',
            'hezbollah weapons', 'hezbollah arsenal', 'hezbollah tunnel',
            'radwan force', 'hezbollah fighters', 'hezbollah martyrs',
            'hezbollah combat', 'hezbollah war',
            # v1.1.0: "The resistance" — how Al-Manar refers to Hezbollah
            'islamic resistance', 'resistance operation',
            'the resistance', 'resistance forces', 'resistance fighters',
            'al-manar', 'almanar',
            # v1.1.0: Arabic — standalone المقاومة catches Al-Manar content
            'المقاومة الإسلامية', 'المقاومة', 'مقاومة',
            'عملية نوعية', 'صواريخ حزب الله',
            'استهداف مواقع', 'قوة الرضوان',
            'المنار', 'الإعلام الحربي',
        ],
        # v1.1.0: Raised from 3
        'baseline_statements_per_week': 8,
    },
    'iran_lebanon': {
        'name': 'Iran (re: Lebanon)',
        'flag': '🇮🇷',
        'icon': '🕌',
        'description': 'Iranian leadership statements about Lebanon/Hezbollah',
        'spokespersons': [
            'khamenei', 'supreme leader', 'raisi', 'pezeshkian',
            'zarif', 'abdollahian', 'araghchi', 'bagheri',
            'irgc commander', 'quds force',
            # Farsi
            'خامنه‌ای', 'رهبر معظم', 'سپاه قدس',
        ],
        'keywords': [
            # Direct references
            'iran hezbollah', 'iran lebanon', 'iran supports hezbollah',
            'iran arms hezbollah', 'iran weapons lebanon',
            'tehran hezbollah', 'tehran lebanon',
            'iran warns israel lebanon', 'iran threatens',
            'quds force lebanon', 'irgc hezbollah',
            'khamenei hezbollah', 'khamenei resistance', 'khamenei lebanon',
            # v1.1.0: Axis of resistance framing
            'iran resistance axis', 'axis of resistance',
            'resistance axis', 'iranian proxy', 'iran proxy',
            'iranian-backed', 'iran-backed',
            'iranian support', 'tehran support',
            # Farsi
            'ایران حزب‌الله', 'محور مقاومت', 'لبنان ایران',
            # Arabic
            'إيران حزب الله', 'محور المقاومة', 'إيران لبنان',
            'الدعم الإيراني', 'طهران حزب الله',
        ],
        # v1.1.0: Raised from 2
        'baseline_statements_per_week': 5,
    },
    'israel_lebanon': {
        'name': 'Israel (re: Lebanon)',
        'flag': '🇮🇱',
        'icon': '🔷',
        'description': 'Israeli leadership statements about Lebanon/Hezbollah',
        'spokespersons': [
            'netanyahu', 'gallant', 'katz', 'gantz', 'eisenkot',
            'idf spokesperson', 'idf northern command',
            'israeli defense minister', 'israeli prime minister',
            'daniel hagari', 'herzi halevi', 'sa\'ar',
            # Hebrew
            'נתניהו', 'גלנט', 'כץ', 'הלוי', 'דובר צה"ל', 'סער',
        ],
        'keywords': [
            # Direct references
            'israel hezbollah', 'israel lebanon', 'israel warns hezbollah',
            'israel threatens lebanon', 'idf lebanon', 'idf hezbollah',
            'israel northern border', 'israel strike lebanon',
            # v1.1.0: Broader northern front terms
            'israel northern front', 'northern front',
            'idf northern', 'idf north', 'northern command',
            # Leaders + Lebanon context
            'netanyahu hezbollah', 'netanyahu lebanon',
            'gallant hezbollah', 'gallant warns', 'gallant lebanon',
            'katz hezbollah', 'katz lebanon',
            'israel red line', 'israel will not tolerate',
            # v1.1.0: Israeli operations near Lebanon
            'israeli airstrike lebanon', 'israeli strike lebanon',
            'israeli operation lebanon', 'idf operation lebanon',
            'south lebanon israel', 'litani river',
            'israeli incursion lebanon', 'ground operation lebanon',
            # v1.1.0: Hebrew — broadened with standalone terms
            'ישראל חיזבאללה', 'ישראל לבנון', 'צה"ל לבנון',
            'גבול צפון', 'פיקוד צפון', 'חזית צפון',
            'לבנון', 'חיזבאללה',
        ],
        # v1.1.0: Raised from 4
        'baseline_statements_per_week': 10,
    },
    'lebanese_government': {
        'name': 'Lebanese Government',
        'flag': '🇱🇧',
        'icon': '🏢',
        'description': 'PM, President, parliament, LAF',
        'spokespersons': [
            'joseph aoun', 'nawaf salam', 'nabih berri',
            'lebanese armed forces', 'laf', 'lebanese army',
            'lebanese parliament', 'lebanese cabinet',
            'lebanese prime minister', 'lebanese president',
            # Arabic
            'جوزيف عون', 'نواف سلام', 'نبيه بري',
            'الجيش اللبناني', 'مجلس النواب',
        ],
        'keywords': [
            # Governance
            'lebanon government', 'lebanese government',
            'lebanon parliament', 'lebanese parliament',
            'lebanese president', 'lebanese prime minister',
            'lebanon cabinet', 'lebanese cabinet',
            'lebanon army', 'lebanese army', 'lebanese armed forces',
            'laf deployment', 'lebanese forces',
            # Leaders
            'joseph aoun', 'aoun statement', 'aoun says',
            'nawaf salam', 'salam statement', 'salam says',
            'nabih berri', 'berri statement', 'berri says',
            # v1.1.0: Broad catch — any article mentioning Lebanon governance
            'lebanon sovereignty', 'lebanon 1701',
            'beirut', 'lebanese', 'lebanon crisis',
            'lebanon economy', 'lebanon reconstruction',
            'lebanon ceasefire', 'lebanon peace',
            # Arabic — broadened
            'الحكومة اللبنانية', 'مجلس الوزراء', 'القرار 1701',
            'لبنان', 'بيروت', 'الجيش اللبناني',
            'مجلس النواب اللبناني',
        ],
        # v1.1.0: Raised from 3
        'baseline_statements_per_week': 10,
    },
    'unifil': {
        'name': 'UN / UNIFIL',
        'flag': '🇺🇳',
        'icon': '🕊️',
        'description': 'UN system statements on Lebanon conflict (UNIFIL, OCHA, SG, SC)',
        'spokespersons': [
            'unifil', 'unifil spokesperson', 'unifil statement',
            'un interim force', 'andrea tenenti',
            'unifil head of mission',
            'antonio guterres', 'un secretary general',
            'un security council', 'un spokesman', 'stephane dujarric',
            'ocha lebanon', 'un humanitarian', 'united nations lebanon',
            'un special coordinator', 'unscol',
        ],
        'keywords': [
            # UNIFIL core
            'unifil', 'unifil report', 'unifil statement',
            'unifil patrol', 'unifil incident', 'unifil attack',
            'unifil withdrawal', 'unifil mandate', 'resolution 1701',
            'blue line', 'blue line violation', 'blue line incident',
            'south lebanon peacekeeping', 'un peacekeeping lebanon',
            'un forces lebanon', '1701',
            # UN system — Lebanon conflict
            'united nations lebanon', 'un secretary general lebanon',
            'antonio guterres lebanon', 'guterres lebanon',
            'un security council lebanon', 'unsc lebanon',
            'un condemns lebanon', 'un calls lebanon',
            'stephane dujarric lebanon', 'un spokesman lebanon',
            'ocha lebanon', 'un humanitarian lebanon',
            'unscol', 'un special coordinator lebanon',
            'peacekeepers killed lebanon', 'peacekeepers attacked lebanon',
            'ghana peacekeepers', 'un peacekeepers wounded',
            'macron condemns peacekeepers',
        ],
        'baseline_statements_per_week': 5,
    },
}


# ========================================
# RHETORIC ESCALATION LADDER
# Per-actor phrase severity scoring
# ========================================

ESCALATION_LEVELS = {
    0: {'label': 'Silent', 'color': '#6b7280', 'description': 'No statements detected'},
    1: {'label': 'Routine', 'color': '#10b981', 'description': 'Standard political/diplomatic language'},
    2: {'label': 'Cautionary', 'color': '#f59e0b', 'description': 'Warnings, expressions of concern'},
    3: {'label': 'Threatening', 'color': '#f97316', 'description': 'Explicit threats, red lines invoked'},
    4: {'label': 'Operational', 'color': '#ef4444', 'description': 'Military/operational language, action imminent'},
    5: {'label': 'Active', 'color': '#991b1b', 'description': 'Claims of ongoing operations or strikes'},
}

# Phrases mapped to escalation levels (checked in descending order)
ESCALATION_PHRASES = {
    5: [
        'we have struck', 'we attacked', 'operation underway',
        'forces engaged', 'launched operation', 'targeted and destroyed',
        'our forces struck', 'successful operation', 'missiles launched',
        'rockets fired at', 'drones launched against',
        # Rocket volley / barrage signals (v1.2.0)
        'volley of rockets', 'rocket volley', 'rocket barrage',
        'barrage of rockets', 'rockets toward', 'rockets into israel',
        'rockets fired into', 'salvo of rockets', 'rocket salvo',
        'projectiles fired', 'anti-tank missile fired',
        'hezbollah fired', 'hezbollah launched', 'hezbollah bombarded',
        'hezbollah barrage', 'hezbollah volley',
        '100 rockets', '50 rockets', '30 rockets', 'dozens of rockets',
        'wave of rockets', 'rocket attack on', 'missile attack on',
        'katyusha', 'falaq rocket', 'burkan missile', 'kornet missile',
        'kiryat shmona', 'metula', 'upper galilee', 'safed rockets',
        'nahariya rockets', 'galilee rockets',
        # Arabic
        'نفذنا عملية', 'استهدفنا', 'أطلقنا صواريخ',
        'عملية ناجحة', 'قواتنا هاجمت',
        'صواريخ نحو', 'رشقة صاروخية', 'وابل صواريخ',
        'أطلقنا رشقة', 'حزب الله أطلق',
    ],
    4: [
        'will strike', 'will attack', 'will target',
        'preparing to strike', 'forces are ready', 'ordered to prepare',
        'all options are on the table', 'decisive action',
        'military operation is inevitable', 'our patience has run out',
        'the decision has been made', 'point of no return',
        'readiness orders issued', 'mobilization ordered',
        # Infrastructure threat signals (v1.2.0)
        'strike infrastructure', 'target infrastructure',
        'infrastructure will be targeted', 'infrastructure strikes',
        'power grid', 'strike power grid', 'target power grid',
        'beirut port', 'strike beirut', 'target beirut',
        'bridges will be targeted', 'roads will be targeted',
        'change posture', 'change our posture', 'change posture in lebanon',
        'severely change', 'dramatically expand', 'expand operations',
        'expand strikes', 'widen offensive', 'broaden offensive',
        'if lebanon does not', 'if beirut does not',
        'government must act', 'government fails to act',
        'hold beirut responsible', 'beirut will bear responsibility',
        'lebanese state responsible', 'lebanon responsible',
        'last chance', 'final warning', 'last warning',
        'ultimatum', 'deadline to act',
    ],
    3: [
        'will not tolerate', 'red line', 'will pay the price',
        'severe consequences', 'devastating response', 'crushing response',
        'warns of retaliation', 'threatens retaliation', 'will retaliate',
        'will respond forcefully', 'will not go unanswered',
        'crossing a line', 'an act of war', 'declaration of war',
        'any aggression will be met', 'playing with fire',
        # Lebanese govt failure / accountability signals (v1.2.0)
        'failed to act', 'refuses to act', 'unwilling to act',
        'has not acted', 'government inaction', 'state failure',
        'must contain hezbollah', 'must rein in hezbollah',
        'must disarm hezbollah', 'disarm hezbollah',
        'must implement 1701', 'failure to implement',
        'ceasefire violations', 'violation of ceasefire',
        'repeated violations', 'daily violations',
        'hold lebanon accountable', 'lebanon must answer',
        'beirut accountable', 'lebanese state accountability',
        'idf reserves right', 'right to self defense lebanon',
        'northern communities', 'residents of the north',
        'evacuees will not return', 'displaced northerners',
    ],
    2: [
        'warns', 'cautioned', 'expressed concern', 'growing tensions',
        'monitoring the situation', 'calls for restraint',
        'urges de-escalation', 'deeply concerned',
        'unacceptable', 'provocative', 'destabilizing',
        'escalation risks', 'dangerous path', 'miscalculation',
        # v1.1.0: Broader cautionary language
        'tensions', 'escalation', 'concern',
        # Arabic
        'يحذر', 'قلق بالغ', 'تصعيد خطير', 'استفزازي',
    ],
    1: [
        'statement', 'press conference', 'remarks', 'speech',
        'meeting', 'discussed', 'agreed', 'cooperation',
        'commitment', 'reiterated', 'affirmed', 'emphasized',
        # v1.1.0: Broader routine language
        'said', 'announced', 'noted', 'reported',
        # Arabic
        'بيان', 'مؤتمر صحفي', 'تصريح', 'اجتماع',
    ],
}


# ========================================
# DATA FETCHING FUNCTIONS
# ========================================

def _fetch_rss(feed_url, source_name, max_items=20):
    """Fetch and parse an RSS feed."""
    articles = []
    try:
        response = requests.get(feed_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code != 200:
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:max_items]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pub_elem = item.find('pubDate')
            desc_elem = item.find('description')

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
    """
    Fetch articles relevant to Lebanon theatre from all available sources.
    Uses a shorter window (3 days) for rhetoric analysis — we want recency.
    """
    all_articles = []

    # --- RSS Feeds ---
    rss_feeds = {
        'Al-Manar (EN)': 'https://english.almanar.com.lb/rss',
        'UN News (Lebanon)': 'https://news.un.org/feed/subscribe/en/news/region/middle-east/feed/rss.xml',
        'OCHA Lebanon': 'https://www.unocha.org/rss.xml',
        'Al-Manar (AR)': 'https://almanar.com.lb/rss',
        'MEMRI': 'https://www.memri.org/rss.xml',
        'Iran Wire (EN)': 'https://iranwire.com/en/feed/',
        'Iran Wire (FA)': 'https://iranwire.com/fa/feed/',
        'Times of Israel': 'https://www.timesofisrael.com/feed/',
        'i24NEWS': 'https://www.i24news.tv/en/rss',
        'Jerusalem Post': 'https://www.jpost.com/rss/rssfeedsfrontpage.aspx',
    }

    for name, url in rss_feeds.items():
        articles = _fetch_rss(url, name)
        all_articles.extend(articles)
        time.sleep(0.3)

    print(f"[Rhetoric] RSS: {len(all_articles)} articles from {len(rss_feeds)} feeds")

    # --- GDELT (v1.1.0: increased timeout to 60s, added retry) ---
    gdelt_queries = {
        'eng': [
            'hezbollah OR lebanon OR \"southern lebanon\"',
            'hezbollah OR nasrallah OR naim qassem',
            'israel hezbollah OR idf lebanon',
            'unifil OR \\\"resolution 1701\\\"',
            'united nations lebanon OR guterres lebanon OR \\\"security council\\\" lebanon',
            'peacekeepers killed lebanon OR un condemns lebanon',
            # v1.2.0 — escalation-specific queries
            'hezbollah rockets volley barrage israel',
            'israel infrastructure strike lebanon threat',
            'israel warns lebanon government posture',
            'lebanon ceasefire violation rockets',
            'israel northern border rockets galilee',
            'beirut strike israel warns',
            'hezbollah fired rockets israel today',
            'israel change posture lebanon',
        ],
        'ara': [
            'حزب الله OR لبنان',
            'المقاومة الإسلامية لبنان',
        ],
        'heb': [
            'חיזבאללה OR לבנון',
            'גבול צפון OR פיקוד צפון',
        ],
        'fas': [
            'حزب‌الله OR لبنان',
        ],
    }

    gdelt_count = 0
    for lang, queries in gdelt_queries.items():
        for query in queries:
            try:
                params = {
                    'query': query,
                    'mode': 'artlist',
                    'maxrecords': 30,
                    'timespan': f'{days}d',
                    'format': 'json',
                    'sourcelang': lang,
                }
                # v1.1.0: retry with 60s timeout (was 30s single attempt)
                resp = None
                for attempt in range(2):
                    try:
                        resp = requests.get(GDELT_BASE_URL, params=params, timeout=60)
                        if resp.status_code == 200:
                            break
                    except requests.Timeout:
                        if attempt == 0:
                            print(f"[Rhetoric GDELT] {lang}: Retry after timeout...")
                            time.sleep(2)
                            continue
                        raise

                if resp and resp.status_code == 200:
                    # v1.1.0: Handle non-JSON responses gracefully
                    try:
                        data = resp.json()
                    except (json.JSONDecodeError, ValueError):
                        print(f"[Rhetoric GDELT] {lang}: Non-JSON response, skipping")
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

    # --- NewsAPI ---
    if NEWSAPI_KEY:
        newsapi_queries = [
            'hezbollah OR "southern lebanon" OR "Naim Qassem"',
            'Israel Lebanon border OR IDF Lebanon',
            'UNIFIL Lebanon OR "resolution 1701"',
        ]
        from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        newsapi_count = 0

        for query in newsapi_queries:
            try:
                resp = requests.get('https://newsapi.org/v2/everything', params={
                    'q': query,
                    'from': from_date,
                    'sortBy': 'publishedAt',
                    'language': 'en',
                    'apiKey': NEWSAPI_KEY,
                    'pageSize': 30,
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

    # --- Telegram Signals ---
    if TELEGRAM_AVAILABLE:
        try:
            telegram_msgs = fetch_telegram_signals(hours_back=72, include_extended=True)
            if telegram_msgs:
                for msg in telegram_msgs:
                    all_articles.append({
                        'title': msg.get('title', '')[:200],
                        'description': msg.get('title', '')[:500],
                        'url': msg.get('url', ''),
                        'publishedAt': msg.get('published', ''),
                        'source': msg.get('source', 'Telegram'),
                        'content': msg.get('title', '')[:500],
                    })
                print(f"[Rhetoric] Telegram: {len(telegram_msgs)} messages")
            else:
                print(f"[Rhetoric] Telegram: 0 messages returned")
        except Exception as e:
            print(f"[Rhetoric] Telegram error: {str(e)[:100]}")
    else:
        print(f"[Rhetoric] Telegram not available — skipping")

    print(f"[Rhetoric] Total articles fetched: {len(all_articles)}")
    return all_articles


# ========================================
# ANALYSIS ENGINE
# ========================================

def classify_actor(article):
    """Determine which Lebanon-theatre actor(s) an article relates to."""
    title = (article.get('title') or '').lower()
    desc = (article.get('description') or '').lower()
    content = (article.get('content') or '').lower()
    text = f"{title} {desc} {content}"

    matched_actors = []

    for actor_id, actor_data in LEBANON_ACTORS.items():
        for kw in actor_data['keywords']:
            if kw in text:
                matched_actors.append(actor_id)
                break

    return matched_actors


def detect_spokesperson(article, actor_id):
    """Identify which spokesperson is speaking in an article."""
    title = (article.get('title') or '').lower()
    desc = (article.get('description') or '').lower()
    text = f"{title} {desc}"

    actor_data = LEBANON_ACTORS.get(actor_id, {})
    for person in actor_data.get('spokespersons', []):
        if person.lower() in text:
            return person

    return None


def score_escalation(article):
    """Score an article's rhetoric on the escalation ladder (0-5)."""
    title = (article.get('title') or '').lower()
    desc = (article.get('description') or '').lower()
    content = (article.get('content') or '').lower()
    text = f"{title} {desc} {content}"

    # Check from highest to lowest — return first match
    for level in sorted(ESCALATION_PHRASES.keys(), reverse=True):
        for phrase in ESCALATION_PHRASES[level]:
            if phrase in text:
                return level, phrase

    # If article matched an actor but no escalation phrase, it's routine
    return 1, None


def extract_topics(article):
    """Extract key topics from an article for topic shift detection."""
    title = (article.get('title') or '').lower()
    desc = (article.get('description') or '').lower()
    text = f"{title} {desc}"

    topics = []

    topic_keywords = {
        'ceasefire': ['ceasefire', 'cease-fire', 'truce', 'وقف إطلاق النار', 'הפסקת אש'],
        'rearmament': ['rearm', 'weapons', 'arms shipment', 'smuggling', 'تسليح', 'חימוש'],
        'border_incident': ['blue line', 'border violation', 'border incident', 'خط أزرق'],
        'hostages': ['hostage', 'prisoner', 'captive', 'أسير', 'חטוף'],
        'elections': ['election', 'parliament', 'vote', 'انتخابات', 'בחירות'],
        'reconstruction': ['reconstruction', 'rebuild', 'recovery', 'إعادة إعمار'],
        'displacement': ['displaced', 'refugees', 'return home', 'نازحين', 'פליטים'],
        'sovereignty': ['sovereignty', 'resolution 1701', 'سيادة', 'ריבונות'],
        'airstrikes': ['airstrike', 'bombing', 'strike', 'غارة', 'תקיפה'],
        'rockets': ['rocket', 'missile', 'projectile', 'صاروخ', 'רקטה'],
        'negotiations': ['negotiation', 'talks', 'diplomacy', 'مفاوضات', 'משא ומתן'],
        'sanctions': ['sanctions', 'embargo', 'عقوبات', 'סנקציות'],
        'humanitarian': ['humanitarian', 'aid', 'relief', 'إنساني', 'הומניטרי'],
    }

    for topic, keywords in topic_keywords.items():
        if any(kw in text for kw in keywords):
            topics.append(topic)

    return topics


# ========================================
# CORE SCAN FUNCTION
# ========================================

def run_rhetoric_scan(days=3):
    """
    Execute a full rhetoric scan for the Lebanon theatre.
    Returns structured analysis data.
    """
    print(f"\n[Rhetoric Scan] Starting Lebanon theatre scan ({days}-day window)...")
    scan_start = time.time()

    # Fetch all articles
    articles = fetch_lebanon_articles(days)

    if not articles:
        print("[Rhetoric Scan] No articles fetched, returning empty result")
        return _build_empty_result()

    # Per-actor analysis
    actor_results = {}

    for actor_id, actor_data in LEBANON_ACTORS.items():
        actor_results[actor_id] = {
            'name': actor_data['name'],
            'flag': actor_data['flag'],
            'icon': actor_data['icon'],
            'statement_count': 0,
            'max_escalation_level': 0,
            'max_escalation_phrase': None,
            'escalation_label': 'Silent',
            'escalation_color': ESCALATION_LEVELS[0]['color'],
            'spokespersons_detected': [],
            'new_voice': False,
            'silence_alert': False,
            'topics': defaultdict(int),
            'top_articles': [],
            'escalation_history': [],
        }

    # Analyze each article
    total_classified = 0
    coordination_timeline = []

    for article in articles:
        actors = classify_actor(article)

        if not actors:
            continue

        total_classified += 1
        escalation_level, trigger_phrase = score_escalation(article)
        topics = extract_topics(article)
        pub_date = article.get('publishedAt', '')

        for actor_id in actors:
            ar = actor_results[actor_id]
            ar['statement_count'] += 1

            # Track escalation
            if escalation_level > ar['max_escalation_level']:
                ar['max_escalation_level'] = escalation_level
                ar['max_escalation_phrase'] = trigger_phrase

            ar['escalation_label'] = ESCALATION_LEVELS[escalation_level]['label']
            ar['escalation_color'] = ESCALATION_LEVELS[escalation_level]['color']

            ar['escalation_history'].append({
                'timestamp': pub_date.isoformat() if pub_date else '',
                'level': escalation_level,
                'phrase': trigger_phrase,
            })

            # Spokesperson detection
            person = detect_spokesperson(article, actor_id)
            if person and person not in ar['spokespersons_detected']:
                ar['spokespersons_detected'].append(person)

            # Topics
            for topic in topics:
                ar['topics'][topic] += 1

            # Top articles (keep top 5 by escalation level)
            if len(ar['top_articles']) < 5 or escalation_level >= 3:
                ar['top_articles'].append({
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', 'Unknown'),
                    'published': pub_date,
                    'escalation_level': escalation_level,
                    'escalation_label': ESCALATION_LEVELS[escalation_level]['label'],
                    'trigger_phrase': trigger_phrase,
                })

            # Coordination timeline
            coordination_timeline.append({
                'timestamp': pub_date,
                'actor': actor_id,
                'level': escalation_level,
            })

    # v1.1.0: Debug logging — classification results per actor
    print(f"[Rhetoric] Classification results ({total_classified}/{len(articles)} articles matched):")
    for actor_id, ar in actor_results.items():
        status = "✅" if ar['statement_count'] > 0 else "⚠️ ZERO"
        print(f"[Rhetoric]   {ar['name']}: {ar['statement_count']} articles, "
              f"max escalation: {ar['max_escalation_level']} "
              f"({ESCALATION_LEVELS[ar['max_escalation_level']]['label']}) {status}")

    # Post-processing per actor
    for actor_id, ar in actor_results.items():
        actor_data = LEBANON_ACTORS[actor_id]

        # Update escalation label to reflect MAX level
        max_level = ar['max_escalation_level']
        ar['escalation_label'] = ESCALATION_LEVELS[max_level]['label']
        ar['escalation_color'] = ESCALATION_LEVELS[max_level]['color']

        # Silence detection
        baseline = actor_data.get('baseline_statements_per_week', 3)
        expected_in_window = baseline * (days / 7.0)
        if ar['statement_count'] < (expected_in_window * 0.25) and expected_in_window > 0:
            ar['silence_alert'] = True
            print(f"[Rhetoric] ⚠️ SILENCE ALERT: {ar['name']} — "
                  f"{ar['statement_count']} statements vs {expected_in_window:.1f} expected")

        # Sort top articles by escalation
        ar['top_articles'] = sorted(
            ar['top_articles'],
            key=lambda x: x['escalation_level'],
            reverse=True
        )[:5]

        # Convert topics defaultdict to regular dict
        ar['topics'] = dict(ar['topics'])

    # Coordination detection
    coordination_alerts = _detect_coordination(coordination_timeline)

    # Overall theatre assessment
    max_actor_level = max(
        (ar['max_escalation_level'] for ar in actor_results.values()),
        default=0
    )
    theatre_escalation = ESCALATION_LEVELS[max_actor_level]

    # Build rhetoric score (0-100) for Lebanon Stability integration
    rhetoric_score = _calculate_rhetoric_score(actor_results, coordination_alerts)

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success': True,
        'theatre': 'lebanon',
        'scanned_at': datetime.now(timezone.utc).isoformat(),
        'scan_time_seconds': scan_time,
        'days_analyzed': days,
        'total_articles': len(articles),
        'articles_classified': total_classified,

        # Theatre-level summary
        'theatre_escalation_level': max_actor_level,
        'theatre_escalation_label': theatre_escalation['label'],
        'theatre_escalation_color': theatre_escalation['color'],
        'rhetoric_score': rhetoric_score,

        # Per-actor breakdown
        'actors': {
            actor_id: {
                'name': ar['name'],
                'flag': ar['flag'],
                'icon': ar['icon'],
                'statement_count': ar['statement_count'],
                'escalation_level': ar['max_escalation_level'],
                'escalation_label': ar['escalation_label'],
                'escalation_color': ar['escalation_color'],
                'escalation_phrase': ar['max_escalation_phrase'],
                'spokespersons': ar['spokespersons_detected'],
                'new_voice': ar['new_voice'],
                'silence_alert': ar['silence_alert'],
                'topics': ar['topics'],
                'top_articles': ar['top_articles'],
            }
            for actor_id, ar in actor_results.items()
        },

        # Cross-actor analysis
        'coordination_alerts': coordination_alerts,

        # Alerts summary (for card/banner display)
        'alerts': _build_alerts(actor_results, coordination_alerts),

        'version': '1.1.0',
    }

    # Cache the result
    cache_set(RHETORIC_CACHE_KEY, result, ttl_hours=24)
    print(f"[Rhetoric Scan] ✅ Complete in {scan_time}s — "
          f"theatre level: {theatre_escalation['label']}, score: {rhetoric_score}")

    # Save daily snapshot for trend tracking
    _save_daily_snapshot(result)

    return result


def _detect_coordination(timeline):
    """
    Detect temporal clustering of statements across resistance axis actors.
    Flag when 2+ aligned actors issue escalatory statements within 48 hours.
    """
    alerts = []

    # Resistance axis actors (would coordinate messaging from Tehran)
    axis_actors = {'hezbollah_political', 'hezbollah_military', 'iran_lebanon'}

    # Filter to axis actors with escalation >= 3
    axis_statements = [
        entry for entry in timeline
        if entry['actor'] in axis_actors and entry['level'] >= 3
    ]

    if len(axis_statements) < 2:
        return alerts

    # Check for statements from different actors within 48h
    for i, stmt_a in enumerate(axis_statements):
        for stmt_b in axis_statements[i+1:]:
            if stmt_a['actor'] == stmt_b['actor']:
                continue

            try:
                time_a = datetime.fromisoformat(stmt_a['timestamp'].replace('Z', '+00:00'))
                time_b = datetime.fromisoformat(stmt_b['timestamp'].replace('Z', '+00:00'))
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
                    # Avoid duplicate alerts
                    actor_set = frozenset(alert['actors'])
                    if not any(frozenset(a['actors']) == actor_set for a in alerts):
                        alerts.append(alert)
            except:
                continue

    return alerts


def _calculate_rhetoric_score(actor_results, coordination_alerts):
    """
    Calculate a 0-100 rhetoric tension score for Lebanon Stability integration.

    Components:
    - Highest actor escalation level (0-5) → 0-50 points
    - Number of actors at level 3+ → 0-20 points
    - Silence alerts (unusual quiet) → 0-15 points
    - Coordination alerts → 0-15 points
    """
    score = 0

    # Highest escalation: 10 points per level (max 50)
    max_level = max(
        (ar['max_escalation_level'] for ar in actor_results.values()),
        default=0
    )
    score += max_level * 10

    # Actors at threatening+ level (3+): 5 points each (max 20)
    hot_actors = sum(
        1 for ar in actor_results.values()
        if ar['max_escalation_level'] >= 3
    )
    score += min(hot_actors * 5, 20)

    # Silence alerts: 5 points each (max 15) — silence can be ominous
    silence_count = sum(
        1 for ar in actor_results.values()
        if ar['silence_alert']
    )
    score += min(silence_count * 5, 15)

    # Coordination: 10 points per alert (max 15)
    score += min(len(coordination_alerts) * 10, 15)

    return min(score, 100)


def _build_alerts(actor_results, coordination_alerts):
    """Build a compact list of alerts for card/banner display."""
    alerts = []

    # Escalation alerts (level 3+)
    for actor_id, ar in actor_results.items():
        if ar['max_escalation_level'] >= 4:
            alerts.append({
                'type': 'escalation',
                'severity': 'critical',
                'actor': ar['name'],
                'message': f"🔴 {ar['name']}: Operational language detected — \"{ar['max_escalation_phrase']}\"",
            })
        elif ar['max_escalation_level'] >= 3:
            alerts.append({
                'type': 'escalation',
                'severity': 'high',
                'actor': ar['name'],
                'message': f"🟠 {ar['name']}: Threatening rhetoric — \"{ar['max_escalation_phrase']}\"",
            })

    # Silence alerts
    for actor_id, ar in actor_results.items():
        if ar['silence_alert']:
            alerts.append({
                'type': 'silence',
                'severity': 'warning',
                'actor': ar['name'],
                'message': f"⚠️ {ar['name']}: Unusual silence ({ar['statement_count']} statements, below baseline)",
            })

    # Coordination alerts
    for coord in coordination_alerts:
        alerts.append({
            'type': 'coordination',
            'severity': coord['severity'],
            'message': f"🔗 {coord['message']}",
        })

    # Sort: critical first
    severity_order = {'critical': 0, 'high': 1, 'warning': 2}
    alerts.sort(key=lambda a: severity_order.get(a['severity'], 3))

    return alerts


def _build_empty_result():
    """Return a valid but empty rhetoric analysis."""
    return {
        'success': True,
        'theatre': 'lebanon',
        'scanned_at': datetime.now(timezone.utc).isoformat(),
        'total_articles': 0,
        'articles_classified': 0,
        'theatre_escalation_level': 0,
        'theatre_escalation_label': 'Silent',
        'theatre_escalation_color': '#6b7280',
        'rhetoric_score': 0,
        'actors': {
            actor_id: {
                'name': data['name'],
                'flag': data['flag'],
                'icon': data['icon'],
                'statement_count': 0,
                'escalation_level': 0,
                'escalation_label': 'Silent',
                'escalation_color': '#6b7280',
                'escalation_phrase': None,
                'spokespersons': [],
                'new_voice': False,
                'silence_alert': False,
                'topics': {},
                'top_articles': [],
            }
            for actor_id, data in LEBANON_ACTORS.items()
        },
        'coordination_alerts': [],
        'alerts': [],
        'awaiting_scan': True,
        'message': 'No data yet — scan in progress',
        'version': '1.1.0',
    }


# ========================================
# DAILY SNAPSHOT STORAGE (for trend sparklines)
# ========================================

def _save_daily_snapshot(result):
    """Save today's rhetoric data as a daily snapshot for trend analysis."""
    try:
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        snapshot = {
            'date': today,
            'rhetoric_score': result.get('rhetoric_score', 0),
            'theatre_level': result.get('theatre_escalation_level', 0),
            'actors': {}
        }

        for actor_id, actor_data in result.get('actors', {}).items():
            snapshot['actors'][actor_id] = {
                'escalation_level': actor_data.get('escalation_level', 0),
                'statement_count': actor_data.get('statement_count', 0),
                'silence_alert': actor_data.get('silence_alert', False),
            }

        # Load existing history
        history = cache_get(RHETORIC_HISTORY_KEY) or {}
        if 'snapshots' not in history:
            history['snapshots'] = {}

        # Add today's snapshot
        history['snapshots'][today] = snapshot

        # Keep only last 90 days
        all_dates = sorted(history['snapshots'].keys())
        if len(all_dates) > 90:
            for old_date in all_dates[:-90]:
                del history['snapshots'][old_date]

        history['last_updated'] = datetime.now(timezone.utc).isoformat()

        # Save back
        cache_set(RHETORIC_HISTORY_KEY, history, ttl_hours=24 * 91)
        print(f"[Rhetoric] Saved daily snapshot for {today} ({len(history['snapshots'])} days in history)")

    except Exception as e:
        print(f"[Rhetoric] Snapshot save error: {e}")


def get_rhetoric_trends(days=30):
    """Get historical rhetoric trend data for sparklines."""
    try:
        history = cache_get(RHETORIC_HISTORY_KEY)

        if not history or 'snapshots' not in history:
            return {'success': False, 'message': 'No trend data yet', 'days_collected': 0}

        snapshots = history['snapshots']
        sorted_dates = sorted(snapshots.keys())[-days:]

        trends = {
            'dates': [],
            'rhetoric_score': [],
            'theatre_level': [],
            'actors': {actor_id: [] for actor_id in LEBANON_ACTORS},
        }

        for date in sorted_dates:
            snap = snapshots[date]
            trends['dates'].append(date)
            trends['rhetoric_score'].append(snap.get('rhetoric_score', 0))
            trends['theatre_level'].append(snap.get('theatre_level', 0))

            for actor_id in LEBANON_ACTORS:
                actor_snap = snap.get('actors', {}).get(actor_id, {})
                trends['actors'][actor_id].append(
                    actor_snap.get('escalation_level', 0)
                )

        return {
            'success': True,
            'days_collected': len(sorted_dates),
            'trends': trends,
        }

    except Exception as e:
        print(f"[Rhetoric Trends] Error: {e}")
        return {'success': False, 'message': str(e), 'days_collected': 0}


# ========================================
# FLASK ENDPOINT REGISTRATION
# ========================================

def register_rhetoric_endpoints(app):
    """Register rhetoric tracker endpoints with the Flask app."""
    from flask import request as flask_request, jsonify, make_response

    def _cors_response(data, status=200):
        """Wrap jsonify with CORS headers."""
        resp = make_response(jsonify(data), status)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    @app.route('/api/rhetoric/lebanon', methods=['GET'])
    def api_rhetoric_lebanon():
        """Full rhetoric analysis for Lebanon page."""
        try:
            refresh = flask_request.args.get('refresh', 'false').lower() == 'true'

            if not refresh:
                cached = cache_get(RHETORIC_CACHE_KEY)
                if cached and is_cache_fresh(cached, max_age_hours=12):
                    cached['cached'] = True
                    print("[Rhetoric] Returning cached data")
                    return _cors_response(cached)

                # Return stale cache if available, trigger background refresh
                if cached:
                    cached['cached'] = True
                    cached['stale'] = True
                    _trigger_rhetoric_scan()
                    return _cors_response(cached)

                # No cache at all — run scan synchronously so first caller gets real data
                print("[Rhetoric] Cold start — running synchronous scan")
                try:
                    result = run_rhetoric_scan(days=3)
                    cache_set(RHETORIC_CACHE_KEY, result, ttl_hours=24)
                    return _cors_response(result)
                except Exception as e:
                    print(f"[Rhetoric] Cold start scan failed: {e}")
                    _trigger_rhetoric_scan()
                    return _cors_response(_build_empty_result())

            # Forced refresh
            _trigger_rhetoric_scan()
            cached = cache_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['refresh_triggered'] = True
                return _cors_response(cached)
            return _cors_response(_build_empty_result())

        except Exception as e:
            print(f"[Rhetoric API] Error: {e}")
            return _cors_response({'success': False, 'error': str(e)[:200]}, 500)

    @app.route('/api/rhetoric/lebanon/summary', methods=['GET'])
    def api_rhetoric_lebanon_summary():
        """Compact summary for country card integration."""
        try:
            cached = cache_get(RHETORIC_CACHE_KEY)
            if not cached:
                return _cors_response({
                    'rhetoric_score': 0,
                    'theatre_level': 0,
                    'theatre_label': 'Awaiting scan',
                    'theatre_color': '#6b7280',
                    'alerts': [],
                    'awaiting_scan': True,
                })

            return _cors_response({
                'rhetoric_score': cached.get('rhetoric_score', 0),
                'theatre_level': cached.get('theatre_escalation_level', 0),
                'theatre_label': cached.get('theatre_escalation_label', 'Silent'),
                'theatre_color': cached.get('theatre_escalation_color', '#6b7280'),
                'alerts': cached.get('alerts', [])[:3],
                'scanned_at': cached.get('scanned_at', ''),
            })

        except Exception as e:
            return _cors_response({'error': str(e)[:200]}, 500)

    @app.route('/api/rhetoric/lebanon/trends', methods=['GET'])
    def api_rhetoric_lebanon_trends():
        """Historical trend data for sparklines."""
        try:
            days = int(flask_request.args.get('days', 30))
            days = min(days, 90)
            return _cors_response(get_rhetoric_trends(days))
        except Exception as e:
            return _cors_response({'success': False, 'error': str(e)[:200]}, 500)

    print("[Rhetoric Tracker] ✅ Endpoints registered: "
          "/api/rhetoric/lebanon, /api/rhetoric/lebanon/summary, /api/rhetoric/lebanon/trends")

    # Skip scan thread if running in lightweight/cache-only mode
    if os.environ.get('RHETORIC_SCAN_DISABLED'):
        print("[Rhetoric Tracker] ✅ Cache-read only mode (scan disabled)")
        return

    # Start periodic scan thread (every 12 hours)
    def _periodic_rhetoric_scan():
        # Wait for app to boot
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
    """Start a background rhetoric scan if one isn't already running."""
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
    """Run a rhetoric scan with error handling (for periodic thread)."""
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
