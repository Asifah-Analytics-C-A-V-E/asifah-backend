"""
Houthi Rhetoric Tracker — Asifah Analytics
'version': '2.1.1 - April 2026'

Tracks escalation rhetoric from Ansar Allah (Houthis) and responses
from KSA, UAE, US, Israel across two primary threat vectors:

1. MARITIME THREAT — Red Sea / Bab el-Mandeb / Suez
2. DIRECT STRIKE THREAT — Israel, KSA, UAE, US bases

Also monitors:
- Somaliland/Horn of Africa for ground operation precursors
- KSA-Houthi ceasefire/negotiation signals
- STC-PLC tensions

Sources: Google News RSS (EN/AR) + Telegram (Houthi media, IDF, Red Sea OSINT, Israeli channels)

Registers on ME backend (asifah-backend.onrender.com)
Endpoint: GET /api/rhetoric/yemen
"""

import os
import json
import threading
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

# ── v2.1: Signal interpreter (so_what, red_lines, historical_matches) ──
# Optional — tracker continues to function if import fails (graceful degradation).
try:
    from yemen_signal_interpreter import interpret_signals as _yemen_interpret_signals
    _INTERPRETER_AVAILABLE = True
except ImportError as _e:
    print(f"[Yemen Rhetoric] ⚠️  Signal interpreter not available: {_e}")
    _yemen_interpret_signals = None
    _INTERPRETER_AVAILABLE = False

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

# Telegram integration — graceful fallback if unavailable
try:
    from telegram_signals import fetch_telegram_signals_yemen
    TELEGRAM_AVAILABLE = True
    print("[Yemen Rhetoric] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Yemen Rhetoric] ⚠️ Telegram signals not available — RSS only")

RHETORIC_CACHE_KEY  = 'yemen_rhetoric_cache'
RHETORIC_CACHE_TTL  = 13 * 3600  # 13h -- covers 12h scan cycle + 1h buffer

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ACTORS
# ============================================
ACTORS = {
    'houthis': {
        'name': 'Ansar Allah (Houthis)',
        'flag': '🟢',
        'color': '#16a34a',
        'role': 'Threat Actor',
    },
    'usa': {
        'name': 'United States',
        'flag': '🇺🇸',
        'color': '#1d4ed8',
        'role': 'Counter-Houthi',
    },
    'israel': {
        'name': 'Israel',
        'flag': '🇮🇱',
        'color': '#2563eb',
        'role': 'Houthi Target',
    },
    'ksa': {
        'name': 'Saudi Arabia',
        'flag': '🇸🇦',
        'color': '#15803d',
        'role': 'Coalition Lead',
    },
    'uae': {
        'name': 'UAE',
        'flag': '🇦🇪',
        'color': '#0369a1',
        'role': 'Coalition Partner',
    },
    'iran': {
        'name': 'Iran',
        'flag': '🇮🇷',
        'color': '#b91c1c',
        'role': 'Houthi Patron',
    },
}


# ============================================
# ESCALATION LADDER
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Monitoring',       'color': '#6b7280'},
    1: {'label': 'Rhetoric',         'color': '#3b82f6'},
    2: {'label': 'Warning',          'color': '#f59e0b'},
    3: {'label': 'Direct Threat',    'color': '#f97316'},
    4: {'label': 'Attack Declared',  'color': '#ef4444'},
    5: {'label': 'Active Strike',    'color': '#7c3aed'},
}


# ============================================
# KEYWORD TRIGGERS
# ============================================

# Vector 1: Maritime
# Vector 1: Maritime / Bab el-Mandeb / Red Sea
# Depth-matched to Iran-Hormuz tracker. Tracks:
# - Strike actions (vessels hit/sunk/seized)
# - Mining / mine-laying language (the friction-tax escalation)
# - Closure declarations / exclusion zones
# - Specific ship/cargo classes targeted
# - Insurance market signals
MARITIME_TRIGGERS = {
    5: [  # Active Strike — vessel struck / sunk / seized
        'sank', 'ship sunk', 'tanker sunk', 'vessel sunk',
        'destroyed vessel', 'tanker destroyed', 'ship destroyed',
        'vessel seized', 'ship seized', 'crew taken', 'crew kidnapped',
        'port struck', 'hodeidah hit', 'al-hudaydah struck',
        'shipping lane closed', 'red sea closed',
        'lng carrier hit', 'container ship sunk', 'bulk carrier hit',
        'mines detonated', 'mine struck ship', 'vessel struck mine',
        'ارسلنا الصاروخ',  # "We sent the missile" Arabic
        'استهدفنا السفينة',  # "We targeted the ship"
    ],
    4: [  # Attack Declared / In Progress / Mining
        'launching attack', 'firing on', 'drone strike ship',
        'missile hits ship', 'anti-ship missile fired',
        'targeted vessel', 'attacking ship', 'engaged vessel',
        'bab el-mandeb closure', 'bab el mandab closure',
        'red sea blockade declared', 'naval blockade activated',
        'we have laid mines', 'placing mines', 'mines deployed',
        'mining the strait', 'mined shipping lane',
        'shoot and kill small boats', 'small boat threat red sea',
        'attack on us navy', 'targeting us warship',
        'سنغرق السفن',  # "We will sink ships"
        'حصار البحر الأحمر',  # "Red Sea blockade"
    ],
    3: [  # Direct Threat — named targets, time-bounded
        'will target ships', 'will sink', 'will mine',
        'threaten shipping', 'threaten to mine', 'threaten to close',
        'close the strait', 'block bab el-mandeb', 'block bab el mandab',
        'ban israeli ships', 'ban us ships', 'ban uk ships',
        'all ships warned', 'maritime exclusion zone',
        'houthi naval operation', 'houthi naval forces',
        'target lng carriers', 'target oil tankers',
        'no safe passage', 'passage denied',
        'سنستهدف السفن',  # "We will target ships"
    ],
    2: [  # Warning / Market Signal / Friction Tax
        'red sea warning', 'shipping risk elevated', 'vessels advised',
        'insurance premiums surge', 'war risk premium',
        'rerouting via cape', 'cape of good hope reroute',
        'avoid red sea', 'gulf of aden alert',
        'maersk suspends', 'hapag-lloyd suspends', 'cma cgm suspends',
        'shipping companies pause', 'cargo diverted',
        'lloyd\'s war risk', 'p&i club warning',
        'qatar lng disrupted', 'lng route disrupted',
        'oman gulf rerouting',
    ],
    1: [  # Background / Geographic Mention
        'red sea', 'bab el-mandeb', 'bab el mandab', 'suez',
        'shipping lane', 'houthi naval', 'maritime', 'vessel', 'tanker',
        'gulf of aden', 'arabian sea', 'hodeidah port',
        'البحر الأحمر',  # "Red Sea"
        'باب المندب',  # "Bab el-Mandeb"
    ],
}

# Vector 2: Direct Strike
DIRECT_STRIKE_TRIGGERS = {
    5: [  # Active Strike
        'missile hits tel aviv', 'strike on eilat', 'attack on riyadh',
        'hit abu dhabi', 'us base struck', 'carrier attacked',
        'ballistic missile hits', 'drone hits israel',
    ],
    4: [  # Attack Declared
        'launching missiles at israel', 'firing at saudi', 'targeting uae',
        'attack on us forces', 'strike us base', 'houthi fires ballistic',
        'ansar allah launches', 'houthi operation against',
    ],
    3: [  # Direct Threat
        'will strike israel', 'threatens tel aviv', 'target eilat',
        'target riyadh', 'threaten abu dhabi', 'us bases in range',
        'carrier in crosshairs', 'attack is coming',
    ],
    2: [  # Warning
        'ready to strike', 'on standby', 'prepared to attack',
        'military option', 'escalation warning', 'final warning',
        'houthi ultimatum',
    ],
    1: [  # Rhetoric
        'resistance', 'axis of resistance', 'solidarity with iran',
        'support palestine', 'down with america', 'death to israel',
    ],
}

# Somaliland/Ground Operation Precursor
SOMALILAND_TRIGGERS = {
    3: [
        'israeli troops somaliland', 'us forces somaliland',
        'military base berbera', 'idf horn of africa',
        'socotra military', 'perim island troops',
    ],
    2: [
        'somaliland israel', 'israel berbera', 'us somaliland',
        'socotra deployment', 'djibouti expansion',
        'camp lemonnier buildup',
    ],
    1: [
        'somaliland', 'berbera', 'socotra', 'perim island',
        'horn of africa', 'djibouti',
    ],
}

# Conditional Threats — "if X then Y" tripwire language
# Vector: Migration / Population Movement
# Yemenis moving INTO Oman = humanitarian / safety pressure (people fleeing)
# Yemenis moving OUT of Oman = potentially concerning (return to Yemen,
#   or onward movement signaling something changed)
# Tracks the Oman corridor as a stability pressure indicator.
MIGRATION_TRIGGERS = {
    5: [  # Major surge / forced mass movement
        'mass exodus yemen', 'yemenis flee in thousands',
        'oman closes border yemen', 'yemen-oman border crisis',
        'humanitarian corridor collapsed',
    ],
    4: [  # Significant flow / crisis indicator
        'yemenis cross into oman', 'yemenis fleeing to oman',
        'yemen refugees oman surge', 'mhd al-mazyunah influx',
        'al-ghaydah border crossing surge', 'yemenis seeking refuge oman',
        'yemen humanitarian collapse',
    ],
    3: [  # Notable movement / pattern shift
        'yemenis arriving oman', 'oman receives yemeni refugees',
        'yemen displacement increase', 'idp surge yemen',
        'yemenis return from oman', 'reverse migration yemen',
        'yemen-oman migration', 'salalah yemen refugees',
    ],
    2: [  # Awareness / monitoring
        'yemen displacement', 'yemen refugee', 'yemeni refugees',
        'oman yemeni population', 'humanitarian situation yemen',
        'yemen idp', 'displaced yemenis',
        'لاجئين يمنيين',  # "Yemeni refugees"
        'النازحين اليمنيين',  # "Displaced Yemenis"
    ],
    1: [  # Background mention
        'yemen oman border', 'oman yemen', 'al-mazyunah',
        'al-ghaydah', 'mahra governorate', 'salalah',
    ],
}


# Vector: Migration / Population Movement (BIDIRECTIONAL)
# Yemen has two opposing migration pressures:
#   OUTBOUND  (Yemen → Oman/Saudi) = escalatory — people fleeing instability
#   RETURNING (Oman/Saudi → Yemen) = de-escalatory — confidence in stability returning
# Net effect contributes to rhetoric score. Same pattern can be applied to Syria,
# Sudan, Lebanon, and other unstable theaters.

MIGRATION_OUT_TRIGGERS = {
    5: [  # Mass exodus / forced movement
        'mass exodus yemen', 'yemenis flee in thousands',
        'oman closes border yemen', 'yemen-oman border crisis',
        'humanitarian corridor collapsed', 'yemenis trapped at border',
        'saudi yemen border surge',
        'هروب جماعي من اليمن',  # "Mass flight from Yemen"
    ],
    4: [  # Significant outbound flow
        'yemenis cross into oman', 'yemenis fleeing to oman',
        'yemen refugees oman surge', 'al-mazyunah influx',
        'al-ghaydah border crossing surge', 'yemenis seeking refuge oman',
        'yemen humanitarian collapse', 'yemenis flee to saudi',
        'idp surge yemen', 'displacement spike yemen',
        'يمنيون يفرون',  # "Yemenis flee"
        'نزوح جماعي',  # "Mass displacement"
    ],
    3: [  # Notable outbound movement
        'yemenis arriving oman', 'oman receives yemeni refugees',
        'yemen displacement increase', 'yemenis seek asylum oman',
        'yemen idp camps growing', 'yemenis cross border',
        'salalah yemen refugees',
        'لاجئون يمنيون جدد',  # "New Yemeni refugees"
    ],
    2: [  # Awareness / monitoring (outbound)
        'yemen displacement', 'yemen refugee', 'yemeni refugees',
        'oman yemeni population', 'humanitarian situation yemen worsens',
        'yemen idp', 'displaced yemenis',
        'لاجئين يمنيين',  # "Yemeni refugees"
        'النازحين اليمنيين',  # "Displaced Yemenis"
    ],
    1: [  # Background outbound mention
        'yemen oman border', 'oman yemen border', 'al-mazyunah',
        'al-ghaydah', 'mahra governorate', 'salalah refugees',
    ],
}

MIGRATION_RETURN_TRIGGERS = {
    5: [  # Mass return / large-scale repatriation
        'mass return yemen', 'yemenis return in thousands',
        'large-scale repatriation yemen', 'yemenis go home',
        'refugees return yemen', 'organized return yemen',
        'عودة جماعية لليمن',  # "Mass return to Yemen"
    ],
    4: [  # Significant return flow
        'yemenis return from oman', 'reverse migration yemen',
        'yemenis return from saudi', 'unhcr facilitates return yemen',
        'iom yemen return', 'voluntary return yemen',
        'displaced yemenis return home',
        'يمنيون يعودون',  # "Yemenis return"
    ],
    3: [  # Notable return / pattern shift
        'yemen returnees increase', 'yemenis returning home',
        'oman yemenis go back', 'pilot return yemen',
        'idp return yemen', 'returnee assistance yemen',
        'يمنيون يرجعون',  # "Yemenis return back"
    ],
    2: [  # Awareness / early signals
        'yemen return planning', 'return assessment yemen',
        'conditions for return yemen', 'yemen reconstruction',
        'reintegration yemen',
    ],
    1: [  # Background return mention
        'yemen return', 'returnees yemen', 'home yemen',
    ],
}


CONDITIONAL_TRIGGERS = {
    3: [
        'if the strikes continue', 'if israel attacks', 'if us forces',
        'should the aggression', 'any attack on iran will', 'if the blockade',
        'we will respond if', 'in the event of', 'if they dare',
        'should they attempt', 'if hodeida is struck', 'if yemen is targeted',
    ],
    2: [
        'we reserve the right', 'all options on the table',
        'prepared to respond', 'will not hesitate', 'if provoked',
        'conditional ceasefire', 'unless the bombing stops',
        'if negotiations fail', 'if demands are not met',
    ],
    1: [
        'unless', 'provided that', 'on condition',
        'should the situation', 'in response to',
    ],
}

# KSA-Houthi Ceasefire Signals
# Vector: Diplomatic Track (de-escalation — REDUCES pressure)
# Same canonical pattern as Lebanon/Iran trackers. Tracks Yemen/Houthi-specific
# diplomatic channels: KSA-Houthi talks (Riyadh), UN mediator (Grundberg),
# Oman shuttle diplomacy, US-Houthi back channels.
DIPLOMATIC_TRIGGERS = {
    5: [  # Agreement reached / signed
        'ceasefire agreement signed yemen', 'yemen peace deal signed',
        'houthi saudi agreement signed', 'yemen war ends',
        'red sea ceasefire signed', 'houthi truce signed',
        'roadmap signed yemen', 'comprehensive ceasefire yemen',
    ],
    4: [  # Active negotiations / direct talks
        'houthi saudi direct talks', 'riyadh houthi delegation',
        'houthi saudi second round', 'saudi yemen framework',
        'us houthi back channel', 'us houthi talks',
        'oman houthi shuttle', 'oman mediates yemen',
        'grundberg meets houthi', 'un envoy houthi talks',
        'yemen ceasefire framework', 'yemen roadmap discussions',
        'houthi delegation muscat', 'houthi delegation riyadh',
        'مفاوضات مباشرة الحوثي',  # "Direct Houthi negotiations"
    ],
    3: [  # Mediator activity
        'oman mediates houthi', 'oman brokers yemen',
        'un envoy yemen', 'grundberg yemen', 'special envoy yemen',
        'saudi mediates yemen', 'kuwait mediates yemen',
        'houthi political committee saudi',
        'us envoy yemen', 'lenderking yemen',
        'extends yemen ceasefire', 'yemen ceasefire extension',
        'houthi prisoner exchange', 'prisoner swap yemen',
        'وساطة عمانية اليمن',  # "Omani mediation Yemen"
    ],
    2: [  # Diplomatic push
        'peace talks yemen', 'ceasefire negotiations yemen',
        'houthi saudi talks', 'diplomatic solution yemen',
        'yemen negotiations', 'un mediator yemen',
        'ksa yemen diplomacy', 'tehran offers yemen mediation',
        'houthi open to talks', 'saudi open to yemen talks',
        'مفاوضات اليمن',  # "Yemen negotiations"
    ],
    1: [  # Background mentions
        'ceasefire', 'truce', 'yemen dialogue', 'yemen talks',
        'yemen diplomacy', 'yemen peace', 'roadmap',
        'وقف اطلاق النار',  # "ceasefire"
    ],
}

# Actor-keyword mapping
ACTOR_KEYWORDS = {
    'houthis': [
        'houthi', 'ansar allah', 'ansarallah', 'abdulmalik al-houthi',
        'hussein al-houthi', 'houthi spokesman', 'houthi military',
        'yahya saree', 'houthi navy', 'houthi air force',
        'الحوثي', 'أنصار الله',
    ],
    'usa': [
        'centcom', 'us military', 'us navy', 'pentagon', 'us strikes yemen',
        'american forces', 'uss ', 'carrier strike group', 'us airstrike yemen',
        'operation prosperity guardian',
    ],
    'israel': [
        'israel', 'idf', 'israeli', 'tel aviv', 'eilat', 'haifa',
        'israel responds', 'israel retaliates', 'אנסאר אללה',
    ],
    'ksa': [
        'saudi', 'riyadh', 'ksa', 'kingdom of saudi', 'arab coalition',
        'saudi-led coalition', 'mbs', 'saudi airstrike',
    ],
    'uae': [
        'uae', 'abu dhabi', 'dubai', 'emirati', 'emirates',
        'uae forces', 'stc', 'southern transitional',
    ],
    'iran': [
        'iran', 'irgc', 'tehran', 'iranian', 'iranian support',
        'iran weapons', 'iran-backed', 'axis of resistance',
    ],
}


# ============================================
# REDDIT CONFIG
# ============================================
REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

YEMEN_SUBREDDITS = [
    'Yemen',
    'geopolitics',
    'CredibleDefense',
    'YemeniCrisis',
    'worldnews',
]

YEMEN_REDDIT_KEYWORDS = [
    'houthi', 'ansar allah', 'red sea', 'bab el-mandeb',
    'yemen war', 'houthi missile', 'houthi drone',
    'somaliland israel', 'shipping attack',
]


def fetch_reddit_yemen(days=3):
    """Fetch Reddit posts from Yemen/Houthi-relevant subreddits."""
    if days <= 1:
        time_filter = 'day'
    elif days <= 7:
        time_filter = 'week'
    else:
        time_filter = 'month'

    query = ' OR '.join(YEMEN_REDDIT_KEYWORDS[:4])
    posts = []

    for subreddit in YEMEN_SUBREDDITS:
        try:
            time.sleep(2)  # polite rate limit
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

            data = resp.json()
            children = data.get('data', {}).get('children', [])
            count = 0
            for post in children:
                pd = post.get('data', {})
                title = pd.get('title', '')
                # Only include if at least one Yemen keyword in title/text
                text_lower = f"{title} {pd.get('selftext','')}".lower()
                if not any(kw in text_lower for kw in YEMEN_REDDIT_KEYWORDS):
                    continue
                posts.append({
                    'title': title[:200],
                    'url': f"https://www.reddit.com{pd.get('permalink','')}",
                    'published': datetime.fromtimestamp(
                        pd.get('created_utc', 0), tz=timezone.utc
                    ).isoformat(),
                    'description': pd.get('selftext', '')[:300],
                    'source': f'r/{subreddit}',
                    'weight': 0.8,  # Reddit slightly lower weight than news
                })
                count += 1
            print(f"[Yemen Rhetoric/Reddit] r/{subreddit}: {count} posts")
        except Exception as e:
            print(f"[Yemen Rhetoric/Reddit] r/{subreddit} error: {e}")
            continue

    return posts


# ============================================
# RSS SOURCES
# ============================================
RHETORIC_RSS_FEEDS = [
    # English
    ("https://news.google.com/rss/search?q=Houthi+rhetoric+threat&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Yemen+Houthi+missile+attack&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Bab+el-Mandeb+Red+Sea+Houthi&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Somaliland+Israel+military&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Yemen+war+2026&hl=en&gl=US&ceid=US:en", 0.85),
    ("https://news.google.com/rss/search?q=Saudi+Houthi+ceasefire+talks&hl=en&gl=US&ceid=US:en", 0.85),
    # Arabic
    ("https://news.google.com/rss/search?q=الحوثيون+صواريخ&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=البحر+الأحمر+الحوثيون&hl=ar&gl=SA&ceid=SA:ar", 0.9),
]


# ============================================
# SPECIFICITY SCORER
# ============================================

# Named geographies that indicate operational specificity
SPECIFIC_GEOGRAPHIES = [
    'eilat', 'tel aviv', 'haifa', 'ashkelon', 'beer sheva',
    'riyadh', 'jeddah', 'abu dhabi', 'dubai', 'manama',
    'hodeidah', 'aden', 'mukalla', 'marib',
    'strait of hormuz', 'bab el-mandeb', 'red sea', 'suez canal',
    'gulf of aden', 'arabian sea',
    'camp lemonnier', 'djibouti', 'berbera', 'socotra',
]

# Named asset classes indicating operational targeting
SPECIFIC_ASSETS = [
    'carrier strike group', 'uss ', 'aircraft carrier', 'destroyer',
    'aramco', 'oil terminal', 'oil tanker', 'lng carrier',
    'supertanker', 'bulk carrier', 'container ship',
    'patriot battery', 'thaad', 'iron dome',
    'air base', 'naval base', 'military installation',
    'us embassy', 'embassy compound',
]

# Time-bounded language
TIME_BOUNDED = [
    'within 24 hours', 'within 48 hours', 'within 72 hours',
    'by friday', 'by tomorrow', 'before the end of',
    'in the coming hours', 'imminent', 'within days',
    'before dawn', 'tonight', 'this week',
]

# Operational framing language
OPERATIONAL_FRAMING = [
    'preparing to launch', 'positioned to strike', 'ready to fire',
    'loading missiles', 'drone swarm', 'coordinated attack',
    'multi-front', 'simultaneous strike', 'saturation attack',
    'hypersonic', 'ballistic salvo', 'anti-ship missile fired',
]


def _score_specificity(text):
    """
    Score 0-10 how operationally specific the rhetoric is.
    Higher = more concrete targeting language = stronger signal.
    Returns score and breakdown dict.
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
            score += 2  # Time-bounded = stronger weight

    for op in OPERATIONAL_FRAMING:
        if op in text:
            breakdown['operational_framing'].append(op)
            score += 2  # Operational framing = stronger weight

    # Check conditional triggers level 3 (highest specificity conditionals)
    for kw in CONDITIONAL_TRIGGERS.get(3, []):
        if kw in text:
            breakdown['conditional_threats'].append(kw)
            score += 2

    # Cap at 10
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
        print(f"[Yemen Rhetoric Redis] GET error: {e}")
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
        print(f"[Yemen Rhetoric Redis] SET error: {e}")
    return False


# ============================================
# ARTICLE FETCHING
# ============================================
def fetch_rhetoric_articles(days=3):
    """Fetch articles from RSS feeds + Telegram channels"""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # ── RSS feeds ──
    for feed_url, weight in RHETORIC_RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=10,
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
                    'weight': weight
                })
        except Exception as e:
            print(f"[Yemen Rhetoric RSS] Error: {e}")

    rss_count = len(articles)
    print(f"[Yemen Rhetoric] RSS: {rss_count} articles")

    # ── Telegram signals ──
    if TELEGRAM_AVAILABLE:
        try:
            hours_back = days * 24
            tg_messages = fetch_telegram_signals_yemen(hours_back=hours_back)
            tg_count = 0
            for msg in tg_messages:
                # Normalize to same format as RSS articles
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
                    'description': msg.get('title', '')[:300],  # Telegram msgs have no separate desc
                    'source': msg.get('source', 'Telegram'),
                    'weight': 1.1,  # Slight boost — Telegram is often faster than RSS
                    'views': msg.get('views', 0),
                    'forwards': msg.get('forwards', 0),
                })
                tg_count += 1
            print(f"[Yemen Rhetoric] Telegram: {tg_count} messages added")
        except Exception as e:
            print(f"[Yemen Rhetoric] Telegram fetch error: {e}")

    # ── Reddit posts ──
    try:
        reddit_posts = fetch_reddit_yemen(days=days)
        for post in reddit_posts:
            # Normalize published field name (Reddit uses 'published')
            pub = post.get('published', '')
            try:
                pub_dt = datetime.fromisoformat(pub)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < since:
                    continue
            except Exception:
                pass
            articles.append(post)
        print(f"[Yemen Rhetoric] Reddit: {len(reddit_posts)} posts added")
    except Exception as e:
        print(f"[Yemen Rhetoric] Reddit fetch error: {e}")

    # Deduplicate by URL
    seen = set()
    unique = []
    for a in articles:
        if a['url'] not in seen:
            seen.add(a['url'])
            unique.append(a)

    tg_count = sum(1 for a in unique if 'Telegram' in a.get('source',''))
    reddit_count = sum(1 for a in unique if a.get('source','').startswith('r/'))
    rss_final = len(unique) - tg_count - reddit_count
    print(f"[Yemen Rhetoric] Total unique: {len(unique)} ({rss_final} RSS + {tg_count} Telegram + {reddit_count} Reddit)")
    return unique


# ============================================
# CLASSIFY ARTICLES
# ============================================
def classify_articles(articles):
    """Classify articles by actor and escalation vector"""

    actor_results = {
        actor_id: {
            'name': info['name'],
            'flag': info['flag'],
            'color': info['color'],
            'role': info['role'],
            'statement_count': 0,
            'maritime_score': 0,
            'direct_strike_score': 0,
            'somaliland_score': 0,
            'ceasefire_score': 0,
            'top_articles': [],
            'escalation_history': [],
        }
        for actor_id, info in ACTORS.items()
    }

    theatre_summary = {
        'maritime_max_level': 0,
        'direct_strike_max_level': 0,
        'somaliland_max_level': 0,
        'ceasefire_max_level': 0,
        # ── v2.1: New vectors ──
        'diplomatic_max': 0,                 # canonical diplomatic level (0-5)
        'migration_out_max': 0,              # outbound flow (escalatory)
        'migration_return_max': 0,           # return flow (de-escalatory)
        'migration_out_signals': [],         # outbound article snippets
        'migration_return_signals': [],      # return article snippets
        'specificity_scores': [],
        'coordination_signals': [],
        'conditional_threats': [],
        'iran_houthi_signals': [],
    }

    for article in articles:
        text = f"{article.get('title','')} {article.get('description','')}".lower()
        pub_date = article.get('published', '')

        # Identify ALL matching actors (multi-actor match — v2.0)
        matched_actors = []
        for aid in ACTORS:
            for kw in ACTOR_KEYWORDS.get(aid, []):
                if kw.lower() in text:
                    matched_actors.append(aid)
                    break

        if not matched_actors:
            continue

        for actor_id in matched_actors:
            ar = actor_results[actor_id]
            ar['statement_count'] += 1

        # Score each vector
        for level in range(5, 0, -1):
            for kw in MARITIME_TRIGGERS.get(level, []):
                if kw in text:
                    if level > ar['maritime_score']:
                        ar['maritime_score'] = level
                        ar['escalation_history'].append({
                            'timestamp': pub_date if isinstance(pub_date, str) else '',
                            'level': level,
                            'vector': 'maritime',
                            'phrase': kw,
                        })
                    if level > theatre_summary['maritime_max_level']:
                        theatre_summary['maritime_max_level'] = level
                    break

            for kw in DIRECT_STRIKE_TRIGGERS.get(level, []):
                if kw in text:
                    if level > ar['direct_strike_score']:
                        ar['direct_strike_score'] = level
                    if level > theatre_summary['direct_strike_max_level']:
                        theatre_summary['direct_strike_max_level'] = level
                    break

            for kw in SOMALILAND_TRIGGERS.get(level, []):
                if kw in text:
                    if level > ar['somaliland_score']:
                        ar['somaliland_score'] = level
                    if level > theatre_summary['somaliland_max_level']:
                        theatre_summary['somaliland_max_level'] = level
                    break

            # ── v2.1: Diplomatic Track (canonical, REDUCES pressure) ──
            # Replaces old CEASEFIRE_TRIGGERS — same field name kept for backward compat
            for kw in DIPLOMATIC_TRIGGERS.get(level, []):
                if kw in text:
                    if level > ar['ceasefire_score']:
                        ar['ceasefire_score'] = level
                    if level > theatre_summary['ceasefire_max_level']:
                        theatre_summary['ceasefire_max_level'] = level
                    if level > theatre_summary['diplomatic_max']:
                        theatre_summary['diplomatic_max'] = level
                    break

            # ── v2.1: Migration OUT (Yemen → Oman/Saudi, escalatory) ──
            for kw in MIGRATION_OUT_TRIGGERS.get(level, []):
                if kw in text:
                    if level > theatre_summary['migration_out_max']:
                        theatre_summary['migration_out_max'] = level
                    if len(theatre_summary['migration_out_signals']) < 5:
                        theatre_summary['migration_out_signals'].append({
                            'phrase': kw,
                            'level': level,
                            'direction': 'out',
                            'article': article.get('title', '')[:100],
                            'published': pub_date if isinstance(pub_date, str) else '',
                        })
                    break

            # ── v2.1: Migration RETURN (Oman/Saudi → Yemen, de-escalatory) ──
            for kw in MIGRATION_RETURN_TRIGGERS.get(level, []):
                if kw in text:
                    if level > theatre_summary['migration_return_max']:
                        theatre_summary['migration_return_max'] = level
                    if len(theatre_summary['migration_return_signals']) < 5:
                        theatre_summary['migration_return_signals'].append({
                            'phrase': kw,
                            'level': level,
                            'direction': 'return',
                            'article': article.get('title', '')[:100],
                            'published': pub_date if isinstance(pub_date, str) else '',
                        })
                    break

        # ── Specificity scoring (runs once per article, not per actor) ──
        if actor_id == matched_actors[0]:  # Score once per article
            spec_score, spec_breakdown = _score_specificity(text)
            article['_specificity_score'] = spec_score
            article['_specificity_breakdown'] = spec_breakdown

            # Conditional threat detection
            for level in range(3, 0, -1):
                for kw in CONDITIONAL_TRIGGERS.get(level, []):
                    if kw in text:
                        theatre_summary.setdefault('conditional_threats', []).append({
                            'phrase': kw,
                            'level': level,
                            'article': article.get('title', '')[:100],
                            'published': pub_date if isinstance(pub_date, str) else '',
                            'specificity': spec_score,
                        })
                        break

        # ── Coordination signal: any Iran keyword co-occurring with Houthis ──
        if 'houthis' in matched_actors and any(kw in text for kw in ACTOR_KEYWORDS['iran']):
            theatre_summary['coordination_signals'].append({
                'message': 'Iran-Houthi coordination signal detected',
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

        # Top articles
        max_level = max(
            ar['maritime_score'],
            ar['direct_strike_score'],
            ar['somaliland_score']
        )
        spec_score = article.get('_specificity_score', 0)
        if spec_score > 0:
            theatre_summary['specificity_scores'].append(spec_score)

        if len(ar['top_articles']) < 5 or max_level >= 3:
            ar['top_articles'].append({
                'title': article.get('title', '')[:120],
                'url': article.get('url', ''),
                'source': article.get('source', 'Unknown'),
                'published': pub_date if isinstance(pub_date, str) else '',
                'maritime_level': ar['maritime_score'],
                'direct_strike_level': ar['direct_strike_score'],
                'specificity_score': spec_score,
            })

    return actor_results, theatre_summary


# ============================================
# DELTA CALCULATION
# ============================================

def _compute_delta():
    """
    Read last 14 history entries, compute 7-entry avg,
    compare to most recent entry. Returns delta dict.
    """
    try:
        HISTORY_KEY = 'rhetoric:yemen:history'
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

        # Most recent is index 0 (lpush = newest first)
        current = entries[0]
        prior = entries[1:]  # up to 13 prior entries

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
        print(f"[Yemen Rhetoric] Delta compute error: {e}")
        return None


# ============================================
# ACTOR BASELINE TRACKING
# ============================================

BASELINE_KEY = 'rhetoric_baseline:yemen'

def _update_actor_baselines(actor_results):
    """
    Rolling average of statement_count and max_level per actor.
    Stored in Redis as rhetoric_baseline:yemen.
    Uses exponential moving average (alpha=0.2) so recent scans
    have more weight without needing to store full history.
    """
    try:
        existing = _redis_get(BASELINE_KEY) or {}
        updated = {}
        alpha = 0.2  # Weight for new observation vs history

        for actor_id, ar in actor_results.items():
            current_statements = ar.get('statement_count', 0)
            current_level = max(
                ar.get('maritime_score', 0),
                ar.get('direct_strike_score', 0),
                ar.get('somaliland_score', 0),
            )
            prev = existing.get(actor_id, {})

            if not prev:
                # First scan — seed with current values
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
                    'scans': min(scans + 1, 999),  # Cap to avoid bloat
                }

        _redis_set(BASELINE_KEY, updated, ttl=30 * 24 * 3600)  # 30-day TTL
        print(f"[Yemen Rhetoric] ✅ Actor baselines updated")
        return updated
    except Exception as e:
        print(f"[Yemen Rhetoric] Baseline update error: {e}")
        return {}


def _detect_silence_anomalies(actor_results, baselines):
    """
    Flag actors whose current statement count is significantly
    below their rolling baseline. Silence after escalation = signal.
    Threshold: actual < 30% of baseline avg (and baseline avg > 3 to avoid noise).
    """
    anomalies = []
    try:
        for actor_id, ar in actor_results.items():
            baseline = baselines.get(actor_id, {})
            avg_statements = baseline.get('avg_statements', 0)
            scans = baseline.get('scans', 0)

            # Need at least 5 scans of history before flagging silence
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
                print(f"[Yemen Rhetoric] 🔇 Silence anomaly: {actor_id} ({actual} vs avg {avg_statements:.1f})")
    except Exception as e:
        print(f"[Yemen Rhetoric] Silence detection error: {e}")
    return anomalies


# ============================================
# CROSS-THEATER COORDINATION
# ============================================

CROSSTHEATER_KEY = 'rhetoric:crosstheater:fingerprints'

def _write_crosstheater_signal(result):
    """
    Write Yemen's current fingerprint to the shared cross-theater Redis key.
    All trackers (Yemen, Iraq, Lebanon, Syria, Iran when built) write here.
    Structure: {theatre_name: {ts, level, top_phrases, named_targets, actor_levels}}
    """
    try:
        # Read existing fingerprints
        existing = _redis_get(CROSSTHEATER_KEY) or {}

        # Build Yemen's fingerprint
        actors = result.get('actors', {})
        houthi_articles = actors.get('houthis', {}).get('top_articles', [])

        # Extract top phrases from coordination signals and conditional threats
        top_phrases = []
        for sig in result.get('coordination_signals', [])[:3]:
            if sig.get('article'):
                top_phrases.append(sig['article'][:60])
        for ct in result.get('conditional_threats', [])[:3]:
            if ct.get('phrase'):
                top_phrases.append(ct['phrase'])

        # Named targets from specificity breakdown
        named_targets = []
        for art in houthi_articles[:5]:
            # Pull any geography mentions from title
            title_lower = art.get('title', '').lower()
            for geo in SPECIFIC_GEOGRAPHIES:
                if geo in title_lower and geo not in named_targets:
                    named_targets.append(geo)

        existing['yemen'] = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'theatre': 'Yemen / Red Sea',
            # v2.1: level now derived from theatre_escalation_level (max threat vector),
            # not from score (which is dampened by diplomatic / migration modifiers)
            'level': result.get('theatre_escalation_level', 0),
            'score': result.get('rhetoric_score', 0),
            'theatre_score': result.get('rhetoric_score', 0),
            'maritime_level': result.get('maritime_level', 0),
            'direct_strike_level': result.get('direct_strike_level', 0),
            'top_phrases': top_phrases[:5],
            'named_targets': named_targets[:8],
            'actor_levels': {
                aid: max(
                    actors.get(aid, {}).get('maritime_score', 0),
                    actors.get(aid, {}).get('direct_strike_score', 0),
                )
                for aid in ['houthis', 'iran', 'usa']
            },
            'specificity_score': result.get('specificity_score', 0),
            # ── v2.1: Diplomatic fingerprint (Israel/Iran read this) ──
            'diplomatic_active':   result.get('diplomatic_track_active', False),
            'ceasefire_level':     result.get('ceasefire_level', 0),
            'diplomatic_modifier': result.get('diplomatic_modifier', 0),
            'diplomatic_label':    result.get('diplomatic_label_detailed', 'Quiet'),
            # ── v2.1: Maritime escalation flag (Iran/Hormuz convergence detection) ──
            # When set + Iran maritime active = global supply chain risk signal.
            'red_sea_friction_active': result.get('maritime_level', 0) >= 3,
            'bab_el_mandeb_status':    result.get('maritime_level', 0),  # 0-5
            # ── v2.1: Bidirectional migration corridor ──
            'migration_out_level':    result.get('migration_out_level', 0),
            'migration_return_level': result.get('migration_return_level', 0),
            'migration_net_modifier': result.get('migration_net_modifier', 0),
        }

        _redis_set(CROSSTHEATER_KEY, existing, ttl=14 * 3600)  # 14h TTL — covers 12h scan cycle
        print(f"[Yemen Rhetoric] ✅ Cross-theater fingerprint written")
    except Exception as e:
        print(f"[Yemen Rhetoric] Cross-theater write error: {e}")


def _detect_crosstheater_coordination():
    """
    Read all theater fingerprints and look for:
    1. Phrase overlap between theaters (same language = coordination signal)
    2. Simultaneous level spikes across Iran-proxy theaters
    3. Named target convergence (multiple theaters referencing same target)

    Gracefully handles missing theaters (Iran tracker not yet built).
    Returns list of coordination findings with confidence scores.
    """
    findings = []
    try:
        fingerprints = _redis_get(CROSSTHEATER_KEY) or {}

        if len(fingerprints) < 2:
            return []  # Need at least 2 theaters to compare

        theaters = list(fingerprints.keys())
        now = datetime.now(timezone.utc)

        # Filter to fingerprints written in last 14 hours (fresh data only)
        fresh = {}
        for name, fp in fingerprints.items():
            try:
                fp_age = (now - datetime.fromisoformat(fp['ts'])).total_seconds() / 3600
                if fp_age <= 14:
                    fresh[name] = fp
                else:
                    print(f"[CrossTheater] Skipping stale fingerprint: {name} ({fp_age:.1f}h old)")
            except Exception:
                pass

        if len(fresh) < 2:
            return []

        # Note any missing expected theaters gracefully
        expected = ['yemen', 'iraq', 'lebanon', 'iran', 'israel']
        missing = [t for t in expected if t not in fresh]
        if missing:
            print(f"[CrossTheater] Note: {missing} fingerprints not yet available (trackers pending)")

        # Check 1: Simultaneous level spikes (all proxy theaters elevated)
        proxy_theaters = {k: v for k, v in fresh.items() if k in ['yemen', 'iraq', 'lebanon']}
        if len(proxy_theaters) >= 2:
            elevated = {k: v for k, v in proxy_theaters.items() if v.get('level', 0) >= 2}
            if len(elevated) >= 2:
                avg_level = round(sum(v['level'] for v in elevated.values()) / len(elevated), 1)
                confidence = min(len(elevated) * 30, 90)
                findings.append({
                    'type': 'simultaneous_elevation',
                    'message': f"Simultaneous elevated rhetoric across {len(elevated)} Iran-aligned theaters",
                    'theaters': list(elevated.keys()),
                    'avg_level': avg_level,
                    'confidence': confidence,
                    'signal': 'Multi-theater coordination possible — watch for synchronized operations',
                    'missing_theaters': missing,
                })

        # Check 2: Named target convergence
        all_targets = {}
        for name, fp in fresh.items():
            for target in fp.get('named_targets', []):
                all_targets.setdefault(target, []).append(name)

        shared_targets = {t: theaters for t, theaters in all_targets.items() if len(theaters) >= 2}
        if shared_targets:
            findings.append({
                'type': 'target_convergence',
                'message': f"Shared target references across multiple theaters",
                'shared_targets': shared_targets,
                'confidence': min(len(shared_targets) * 25, 85),
                'signal': 'Multiple theaters referencing same targets — possible coordinated targeting',
                'missing_theaters': missing,
            })

        # Check 3: Phrase overlap
        all_phrases = {}
        for name, fp in fresh.items():
            for phrase in fp.get('top_phrases', []):
                phrase_key = phrase[:30].lower()
                all_phrases.setdefault(phrase_key, []).append(name)

        shared_phrases = {p: t for p, t in all_phrases.items() if len(t) >= 2}
        if shared_phrases:
            findings.append({
                'type': 'phrase_synchronization',
                'message': f"Synchronized language detected across {len(set(t for ts in shared_phrases.values() for t in ts))} theaters",
                'shared_phrases': list(shared_phrases.keys())[:5],
                'confidence': min(len(shared_phrases) * 20, 80),
                'signal': 'Similar framing across theaters within 14h window — narrative coordination signal',
                'missing_theaters': missing,
            })

    except Exception as e:
        print(f"[Yemen Rhetoric] Cross-theater detection error: {e}")

    return findings


# ============================================
# MAIN RHETORIC SCAN
# ============================================
def run_houthi_rhetoric_scan(days=3):
    """Full Houthi rhetoric scan"""
    print(f"[Yemen Rhetoric] Starting scan ({days}-day window)...")

    articles = fetch_rhetoric_articles(days)
    actor_results, theatre_summary = classify_articles(articles)

    # Overall escalation level (max of all THREAT vectors — diplomacy excluded)
    max_maritime   = theatre_summary['maritime_max_level']
    max_strike     = theatre_summary['direct_strike_max_level']
    max_somaliland = theatre_summary['somaliland_max_level']
    max_level      = max(max_maritime, max_strike, max_somaliland)

    # ── Compute theatre-level specificity score (avg of scored articles) ──
    spec_scores = theatre_summary.get('specificity_scores', [])
    theatre_specificity = round(sum(spec_scores) / len(spec_scores), 1) if spec_scores else 0

    # ══════════════════════════════════════════════════════════════
    # v2.1: NUANCED RHETORIC SCORE (0-100)
    # Lifted from old max_level*20 to canonical Lebanon/Iran-style scoring:
    # - Threat vectors contribute weighted points (max 75)
    # - Hot actors at L3+ add bonus (max 15)
    # - Coordination signals add bonus (max 10)
    # - Migration OUT (escalatory) adds points (max +8)
    # - Migration RETURN (de-escalatory) subtracts points (max -8)
    # - Diplomatic track REDUCES score (modifier -1 to -15)
    # - Final score floored at 0, capped at 100
    # ══════════════════════════════════════════════════════════════
    score = 0

    # Threat vectors — Maritime weighted highest (Bab el-Mandeb is THE signal)
    score += max_maritime   * 8    # max 40 — primary signal
    score += max_strike     * 6    # max 30 — direct strike on UAE/KSA/Israel
    score += max_somaliland * 1    # max 5  — peripheral signal

    # Cap threat vectors at 75
    score = min(score, 75)

    # Hot actor bonus: actors at level 3+ contribute escalation pressure
    hot_actors = sum(
        1 for ar in actor_results.values()
        if ar.get('max_escalation_level', 0) >= 3
    )
    score += min(hot_actors * 5, 15)

    # Coordination bonus (Iran-Houthi signal coupling)
    coord_count = len(theatre_summary.get('coordination_signals', []))
    score += min(coord_count * 5, 10)

    # ── BIDIRECTIONAL MIGRATION MODIFIER ──
    # Out  = people fleeing → conditions worsening → +pressure
    # Return = people coming back → confidence returning → -pressure
    # Net effect can cancel (e.g., displacement + organized return = roughly stable).
    migration_out_level    = theatre_summary.get('migration_out_max', 0)
    migration_return_level = theatre_summary.get('migration_return_max', 0)

    migration_out_modifier_map = {
        0: 0, 1: 1, 2: 2, 3: 4, 4: 6, 5: 8,    # adds pressure
    }
    migration_return_modifier_map = {
        0: 0, 1: -1, 2: -2, 3: -4, 4: -6, 5: -8,    # reduces pressure
    }

    migration_out_modifier    = migration_out_modifier_map.get(migration_out_level, 0)
    migration_return_modifier = migration_return_modifier_map.get(migration_return_level, 0)
    migration_net_modifier    = migration_out_modifier + migration_return_modifier

    score += migration_net_modifier

    # ── DIPLOMATIC TRACK MODIFIER (canonical pattern) ──
    # Active negotiations REDUCE the threat score. Floored at 0.
    diplomatic_level = theatre_summary.get('diplomatic_max', 0)
    diplomatic_modifier_map = {
        0: 0,    # Quiet
        1: -1,   # Background diplomatic mentions
        2: -3,   # Diplomatic push (peace talks language)
        3: -6,   # Mediator activity (Oman, UN envoy, Saudi brokerage)
        4: -10,  # Active negotiations / direct talks (Riyadh delegation)
        5: -15,  # Agreement reached / signed (ceasefire roadmap)
    }
    diplomatic_modifier = diplomatic_modifier_map.get(diplomatic_level, 0)
    score += diplomatic_modifier

    # Final clamp
    rhetoric_score = max(0, min(100, int(score)))

    # ── v2.1: Determine net migration label for display ──
    if migration_out_level >= 3 and migration_return_level >= 3:
        migration_net_label = 'Mixed Flows'
    elif migration_out_level >= 3:
        migration_net_label = 'Outbound Pressure'
    elif migration_return_level >= 3:
        migration_net_label = 'Return Activity'
    elif migration_out_level >= 1 or migration_return_level >= 1:
        migration_net_label = 'Background Movement'
    else:
        migration_net_label = 'Quiet'

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'days_analyzed': days,
        'total_articles': len(articles),
        'theatre': 'Yemen / Red Sea',
        # v2.1: Nuanced score (replaces max_level*20)
        'rhetoric_score': rhetoric_score,
        'theatre_score': rhetoric_score,    # backward compat field
        'theatre_level': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Unknown'),
        'theatre_escalation_level': max_level,
        'theatre_escalation_label': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Baseline'),
        'theatre_escalation_color': ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
        'theatre_color': ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
        # Threat vectors
        'maritime_level': max_maritime,
        'maritime_label': ESCALATION_LEVELS.get(max_maritime, {}).get('label', 'Monitoring'),
        'direct_strike_level': max_strike,
        'direct_strike_label': ESCALATION_LEVELS.get(max_strike, {}).get('label', 'Monitoring'),
        'somaliland_level': theatre_summary['somaliland_max_level'],
        'somaliland_label': ESCALATION_LEVELS.get(
            theatre_summary['somaliland_max_level'], {}).get('label', 'Baseline'),
        # Backward-compat ceasefire fields
        'ceasefire_level': theatre_summary['ceasefire_max_level'],
        'ceasefire_label': ESCALATION_LEVELS.get(
            theatre_summary['ceasefire_max_level'], {}).get('label', 'None'),
        # ── v2.1: Diplomatic Track (canonical) ──
        'diplomatic_track_active':   theatre_summary['diplomatic_max'] >= 2,
        'diplomatic_modifier':       diplomatic_modifier,
        'diplomatic_label_detailed': {
            0: 'Quiet',
            1: 'Background Mentions',
            2: 'Diplomatic Push',
            3: 'Mediator Activity',
            4: 'Active Negotiations',
            5: 'Agreement Reached',
        }.get(diplomatic_level, 'Quiet'),
        # ── v2.1: Bidirectional Migration ──
        'migration_out_level':       migration_out_level,
        'migration_out_label':       ESCALATION_LEVELS.get(migration_out_level, {}).get('label', 'Baseline'),
        'migration_return_level':    migration_return_level,
        'migration_return_label':    ESCALATION_LEVELS.get(migration_return_level, {}).get('label', 'Baseline'),
        'migration_out_modifier':    migration_out_modifier,
        'migration_return_modifier': migration_return_modifier,
        'migration_net_modifier':    migration_net_modifier,
        'migration_net_label':       migration_net_label,
        'migration_out_signals':     theatre_summary.get('migration_out_signals', [])[:5],
        'migration_return_signals':  theatre_summary.get('migration_return_signals', [])[:5],
        # Actors / signals / specificity
        'actors': actor_results,
        'coordination_signals': theatre_summary['coordination_signals'][:5],
        'conditional_threats': theatre_summary.get('conditional_threats', [])[:8],
        'specificity_score': theatre_specificity,
        'version': '2.1.1-yemen-interpreter-wired'
    }

    # ── Baseline + silence detection ──
    baselines = _update_actor_baselines(actor_results)
    result['silence_anomalies'] = _detect_silence_anomalies(actor_results, baselines)

    # ── v2.1: Signal interpretation (so_what, red_lines, historical_matches) ──
    # Wraps in try/except so a bad interpretation never breaks the scan.
    if _INTERPRETER_AVAILABLE and _yemen_interpret_signals:
        try:
            interpretation = _yemen_interpret_signals(result)
            result['interpretation'] = interpretation
            print(f"[Yemen Rhetoric] ✅ Interpretation generated — scenario: "
                  f"{interpretation.get('so_what', {}).get('scenario', 'unknown')}")
        except Exception as e:
            print(f"[Yemen Rhetoric] ⚠️  Interpreter failed: {e}")
            result['interpretation'] = None
    else:
        result['interpretation'] = None

    # ── Delta vs prior scans ──
    _redis_set(RHETORIC_CACHE_KEY, result)  # Save first so history is up to date

    # ── History snapshot (unchanged pattern) ──
    try:
        snapshot = json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'score': rhetoric_score,           # v2.1: nuanced score (was max_level*20)
            'level': max_level,
            'label': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Unknown'),
            'maritime': max_maritime,
            'strikes': max_strike,
            'specificity': theatre_specificity,
            # v2.1: track diplomatic + bidirectional migration in history for trend analysis
            'diplomatic_modifier':     diplomatic_modifier,
            'diplomatic_level':        diplomatic_level,
            'migration_out':           migration_out_level,
            'migration_return':        migration_return_level,
            'migration_net_modifier':  migration_net_modifier,
        })
        HISTORY_KEY = 'rhetoric:yemen:history'
        if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
            import urllib.parse
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
            print(f"[Yemen Rhetoric] History snapshot saved")
    except Exception as e:
        print(f"[Yemen Rhetoric] History append error (non-fatal): {e}")

    # ── Delta (reads history written above) ──
    result['delta'] = _compute_delta()

    # ── Cross-theater coordination ──
    _write_crosstheater_signal(result)
    result['crosstheater_coordination'] = _detect_crosstheater_coordination()

    # ── Re-save with all enriched fields ──
    _redis_set(RHETORIC_CACHE_KEY, result)

    print(f"[Yemen Rhetoric] ✅ Complete. Theatre level: {result['theatre_level']} | Specificity: {theatre_specificity}/10 | Delta: {result.get('delta', {}).get('direction', 'n/a')}")
    return result

def _bg_rhetoric_scan():
    global _rhetoric_running
    try:
        run_houthi_rhetoric_scan()
    except Exception as e:
        print(f"[Yemen Rhetoric] Background scan error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


def _start_periodic_scan(interval_hours=12):
    """Start periodic background rhetoric scan"""
    def _loop():
        time.sleep(90)  # Stagger startup -- give backend time to stabilize
        while True:
            try:
                run_houthi_rhetoric_scan()
            except Exception as e:
                print(f"[Yemen Rhetoric] Periodic scan error: {e}")
            time.sleep(interval_hours * 3600)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[Yemen Rhetoric] ✅ Periodic scan thread started ({interval_hours}h cycle)")


# ============================================
# ROUTE REGISTRATION
# ============================================
def register_houthi_rhetoric_routes(app):
    """Register Yemen rhetoric endpoints on ME Flask app"""

    _start_periodic_scan(interval_hours=12)

    @app.route('/api/rhetoric/yemen', methods=['GET'])
    def yemen_rhetoric():
        force = request.args.get('force', 'false').lower() == 'true'
        days  = int(request.args.get('days', 3))
        global _rhetoric_running

        if not force:
            cached = _redis_get(RHETORIC_CACHE_KEY)
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

            # Trigger background scan
            with _rhetoric_lock:
                if not _rhetoric_running:
                    _rhetoric_running = True
                    t = threading.Thread(target=_bg_rhetoric_scan, daemon=True)
                    t.start()

            return jsonify({
                'success': True,
                'cached': False,
                'scan_in_progress': True,
                'message': 'Yemen rhetoric scan in progress. Refresh in 60 seconds.',
                'theatre': 'Yemen / Red Sea',
                'theatre_score': 0,
                'theatre_level': 'Scanning...',
                'version': '1.2.0-yemen-rhetoric-telegram-reddit'
            })

        result = run_houthi_rhetoric_scan(days=days)
        return jsonify(result)

    @app.route('/api/rhetoric/yemen/summary', methods=['GET'])
    def yemen_rhetoric_summary():
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            return jsonify({
                'success': True,
                # v2.1: Nuanced score
                'rhetoric_score': cached.get('rhetoric_score', 0),
                'theatre_score':  cached.get('theatre_score', 0),
                'theatre_level':  cached.get('theatre_level', 'Unknown'),
                'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
                'theatre_color':  cached.get('theatre_color', '#6b7280'),
                # Threat vectors
                'maritime_level':      cached.get('maritime_level', 0),
                'direct_strike_level': cached.get('direct_strike_level', 0),
                'somaliland_level':    cached.get('somaliland_level', 0),
                # Diplomatic
                'ceasefire_level':           cached.get('ceasefire_level', 0),
                'diplomatic_track_active':   cached.get('diplomatic_track_active', False),
                'diplomatic_modifier':       cached.get('diplomatic_modifier', 0),
                'diplomatic_label_detailed': cached.get('diplomatic_label_detailed', 'Quiet'),
                # Migration (bidirectional)
                'migration_out_level':    cached.get('migration_out_level', 0),
                'migration_out_label':    cached.get('migration_out_label', 'Baseline'),
                'migration_return_level': cached.get('migration_return_level', 0),
                'migration_return_label': cached.get('migration_return_label', 'Baseline'),
                'migration_net_modifier': cached.get('migration_net_modifier', 0),
                'migration_net_label':    cached.get('migration_net_label', 'Quiet'),
                'timestamp': cached.get('timestamp'),
                'cached': True
            })
        return jsonify({'success': False, 'message': 'No cached data yet'})

    @app.route('/api/rhetoric/yemen/history', methods=['GET'])
    def yemen_rhetoric_history():
        """Rolling history of rhetoric snapshots — last 120 entries (~30 days)."""
        from flask import request as flask_request
        try:
            limit = int(flask_request.args.get('limit', 120))
            limit = max(1, min(limit, 120))
            HISTORY_KEY = 'rhetoric:yemen:history'
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
                'theatre': 'Yemen / Red Sea',
                'history_key': 'rhetoric:yemen:history',
                'count': len(entries),
                'entries': entries,   # [{ts, score, level, label, maritime, strikes}, …]
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    print("[Yemen Rhetoric] ✅ Routes registered: /api/rhetoric/yemen, /api/rhetoric/yemen/summary, /api/rhetoric/yemen/history")
