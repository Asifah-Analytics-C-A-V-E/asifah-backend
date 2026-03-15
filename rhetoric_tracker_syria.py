"""
Syria Rhetoric Tracker — Asifah Analytics
v1.0.0 — March 2026

Tracks escalation rhetoric across Syria's post-Assad factional landscape:

Actors monitored:
- HTS (Hay'at Tahrir al-Sham) — governing authority, Idlib/Damascus
- SDF (Syrian Democratic Forces) — Kurdish-led, northeast Syria
- SNA (Syrian National Army) — Turkish-backed, northern Syria
- Israel — active airstrikes southern Syria, Golan proximity
- ISIS — desert resurgence signals, Badia/Deir ez-Zor
- Iran Proxies — degraded but persistent, Deir ez-Zor corridor
- Turkey — diplomatic + military pressure on SDF/Rojava

Special monitoring:
- Druze / Suwayda — independent community signals + Israel coordination watch
- Israeli strike activity in southern Syria (Quneitra, Daraa, Suwayda)

Three threat vectors:
1. FACTIONAL CONFLICT — HTS vs SNA vs SDF territorial friction
2. ISRAELI STRIKE ACTIVITY — southern Syria weapons depots, Golan proximity
3. ISIS RESURGENCE — Badia desert attack signals, sleeper cell activity

Sources: Google News RSS (EN/AR) + Telegram (Syria OSINT, Kurdish media,
         IDF channels, regional Arabic) + Reddit

Registers on ME backend (asifah-backend.onrender.com)
Endpoints: GET /api/rhetoric/syria
           GET /api/rhetoric/syria/summary
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
    from telegram_signals import fetch_telegram_signals_syria
    TELEGRAM_AVAILABLE = True
    print("[Syria Rhetoric] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Syria Rhetoric] ⚠️ Telegram signals not available — RSS only")

RHETORIC_CACHE_KEY = 'syria_rhetoric_cache'
RHETORIC_CACHE_TTL = 6 * 3600  # 6 hours

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


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
            # Arabic
            'أحمد الشرع', 'هيئة تحرير الشام', 'حكومة الإنقاذ السورية',
        ],
        'keywords': [
            'hts', 'hayat tahrir al-sham', 'hay\'at tahrir', 'jolani', 'al-jolani',
            'ahmed al-sharaa', 'syrian interim government', 'syrian salvation government',
            'hts government', 'hts forces', 'hts fighters', 'hts controls',
            'hts security', 'hts administration', 'hts statement',
            'idlib', 'aleppo government', 'damascus new government',
            'new syrian government', 'post-assad syria', 'transitional syria',
            # Arabic
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
            # Kurdish/Arabic
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
            # Arabic/Kurdish
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
            # Arabic
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
        'description': 'Israeli airstrikes in southern Syria — weapons depots, Golan proximity',
        'spokespersons': [
            'idf syria', 'idf strikes syria', 'israeli airstrike syria',
            'netanyahu syria', 'katz syria', 'idf spokesperson syria',
            # Hebrew
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
            # Hebrew
            'ישראל סוריה', 'צה"ל תוקף בסוריה', 'רמת הגולן',
            # Arabic
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
            # Arabic
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
            # Arabic/Farsi
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
            # Turkish
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
            # Turkish/Arabic
            'تركيا سوريا', 'أردوغان سوريا', 'القوات التركية سوريا',
            'السياسة التركية سوريا',
        ],
        'baseline_statements_per_week': 7,
    },
}


# ============================================
# DRUZE / SUWAYDA SPECIAL MONITOR
# (Not a full actor — signal layer under Israel/HTS vectors)
# ============================================
DRUZE_KEYWORDS = [
    # Community references
    'druze', 'suwayda', 'sweida', 'jabal al-arab', 'druze community syria',
    'druze leaders syria', 'druze militia', 'men of dignity',
    # Israel-Druze coordination signals
    'druze israel', 'israel druze syria', 'druze coordination israel',
    'druze protection israel', 'israel protect druze',
    'druze flag', 'druze self-defense',
    # HTS-Druze tensions
    'hts druze', 'druze hts', 'druze resist hts',
    'druze autonomy', 'druze independence',
    # Arabic
    'السويداء', 'الدروز سوريا', 'جبل العرب',
    'رجال الكرامة', 'الدروز وإسرائيل',
]


# ============================================
# ESCALATION LADDER
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Baseline',      'color': '#6b7280', 'description': 'No significant signals'},
    1: {'label': 'Rhetoric',      'color': '#3b82f6', 'description': 'Standard factional statements'},
    2: {'label': 'Tension',       'color': '#f59e0b', 'description': 'Warnings, territorial disputes'},
    3: {'label': 'Confrontation', 'color': '#f97316', 'description': 'Direct threats, troop movements'},
    4: {'label': 'Incident',      'color': '#ef4444', 'description': 'Clashes confirmed, strikes reported'},
    5: {'label': 'Active Conflict','color': '#991b1b', 'description': 'Ongoing operations, multiple fronts'},
}


# ============================================
# THREAT VECTORS
# ============================================

# Vector 1: Factional Conflict (HTS vs SNA vs SDF)
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

# Vector 2: Israeli Strike Activity
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
    ],
    3: [
        'israel warns syria', 'israel threatens strike',
        'israel monitoring', 'idf on alert syria',
        'golan incursion', 'buffer zone violation',
        'weapons transfer warning', 'arms smuggling warning',
        'israel will act', 'israel right to strike',
    ],
    2: [
        'israel watching syria', 'golan tensions', 'buffer zone',
        'weapons smuggling syria', 'arms transfer concern',
        'iranian weapons syria', 'hezbollah arms syria',
    ],
    1: [
        'israel syria', 'golan', 'israeli', 'idf',
        'airspace violation', 'overflight syria',
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
}


# ============================================
# REDDIT CONFIG
# ============================================
REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

SYRIA_SUBREDDITS = [
    'syriancivilwar',
    'geopolitics',
    'CredibleDefense',
    'worldnews',
    'Syria',
]

SYRIA_REDDIT_KEYWORDS = [
    'hts', 'hayat tahrir', 'sdf syria', 'sna syria',
    'israel strikes syria', 'isis syria', 'druze suwayda',
    'syria conflict', 'jolani', 'rojava',
]


def fetch_reddit_syria(days=3):
    """Fetch Reddit posts from Syria-relevant subreddits."""
    time_filter = 'day' if days <= 1 else 'week' if days <= 7 else 'month'
    query = ' OR '.join(SYRIA_REDDIT_KEYWORDS[:4])
    posts = []

    for subreddit in SYRIA_SUBREDDITS:
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
                if not any(kw in text_lower for kw in SYRIA_REDDIT_KEYWORDS):
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
            print(f"[Syria Rhetoric/Reddit] r/{subreddit}: {count} posts")
        except Exception as e:
            print(f"[Syria Rhetoric/Reddit] r/{subreddit} error: {e}")

    return posts


# ============================================
# RSS SOURCES
# ============================================
RHETORIC_RSS_FEEDS = [
    # English — Syria conflict / HTS / factions
    ("https://news.google.com/rss/search?q=HTS+Syria+conflict+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Syria+SDF+HTS+factions&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Israel+strikes+Syria+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=ISIS+Syria+resurgence+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Druze+Suwayda+Syria&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Turkey+SDF+Syria+Rojava&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=Syria+Kurdish+forces+2026&hl=en&gl=US&ceid=US:en", 0.85),
    ("https://news.google.com/rss/search?q=Syria+war+2026+factions&hl=en&gl=US&ceid=US:en", 0.85),
    # Arabic — Syria coverage
    ("https://news.google.com/rss/search?q=هيئة+تحرير+الشام+سوريا&hl=ar&gl=SA&ceid=SA:ar", 0.95),
    ("https://news.google.com/rss/search?q=داعش+سوريا+2026&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    ("https://news.google.com/rss/search?q=إسرائيل+غارات+سوريا&hl=ar&gl=SA&ceid=SA:ar", 0.95),
    ("https://news.google.com/rss/search?q=السويداء+الدروز+سوريا&hl=ar&gl=SA&ceid=SA:ar", 0.9),
    # Hebrew — Israeli strikes in Syria
    ("https://news.google.com/rss/search?q=ישראל+סוריה+תקיפה&hl=iw&gl=IL&ceid=IL:iw", 0.95),
]


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
    """Fetch articles from RSS + Telegram + Reddit."""
    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # ── RSS ──
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
                    'weight': weight,
                })
        except Exception as e:
            print(f"[Syria Rhetoric RSS] Error: {e}")

    rss_count = len(articles)
    print(f"[Syria Rhetoric] RSS: {rss_count} articles")

    # ── Telegram ──
    if TELEGRAM_AVAILABLE:
        try:
            hours_back = days * 24
            tg_messages = fetch_telegram_signals_syria(hours_back=hours_back)
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
            print(f"[Syria Rhetoric] Telegram: {tg_count} messages added")
        except Exception as e:
            print(f"[Syria Rhetoric] Telegram fetch error: {e}")

    # ── Reddit ──
    try:
        reddit_posts = fetch_reddit_syria(days=days)
        for post in reddit_posts:
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
        print(f"[Syria Rhetoric] Reddit: {len(reddit_posts)} posts added")
    except Exception as e:
        print(f"[Syria Rhetoric] Reddit fetch error: {e}")

    # Deduplicate by URL
    seen = set()
    unique = []
    for a in articles:
        if a['url'] not in seen:
            seen.add(a['url'])
            unique.append(a)

    tg_count   = sum(1 for a in unique if 'Telegram' in a.get('source', ''))
    reddit_count = sum(1 for a in unique if a.get('source', '').startswith('r/'))
    rss_final  = len(unique) - tg_count - reddit_count
    print(f"[Syria Rhetoric] Total unique: {len(unique)} ({rss_final} RSS + {tg_count} Telegram + {reddit_count} Reddit)")
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
            'factional_score': 0,
            'israeli_strike_score': 0,
            'isis_score': 0,
            'top_articles': [],
            'escalation_history': [],
            'spokespersons': [],
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
    }

    for article in articles:
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        pub_date = article.get('published', '')

        # ── Druze / Suwayda signal detection ──
        druze_hits = [kw for kw in DRUZE_KEYWORDS if kw in text]
        if druze_hits:
            theatre_summary['druze_signals'].append({
                'message': f"Druze/Suwayda signal: {druze_hits[0]}",
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

        # ── Identify actor ──
        actor_id = None
        for aid in ACTORS:
            for kw in ACTOR_KEYWORDS.get(aid, []):
                if kw.lower() in text:
                    actor_id = aid
                    break
            if actor_id:
                break

        if not actor_id:
            continue

        ar = actor_results[actor_id]
        ar['statement_count'] += 1

        # ── Score each vector ──
        for level in range(5, 0, -1):
            # Factional
            for kw in FACTIONAL_TRIGGERS.get(level, []):
                if kw in text:
                    if level > ar['factional_score']:
                        ar['factional_score'] = level
                        ar['escalation_history'].append({
                            'timestamp': pub_date if isinstance(pub_date, str) else '',
                            'level': level,
                            'vector': 'factional',
                            'phrase': kw,
                        })
                    if level > theatre_summary['factional_max_level']:
                        theatre_summary['factional_max_level'] = level
                    break

            # Israeli strikes
            for kw in ISRAELI_STRIKE_TRIGGERS.get(level, []):
                if kw in text:
                    if level > ar['israeli_strike_score']:
                        ar['israeli_strike_score'] = level
                    if level > theatre_summary['israeli_strike_max_level']:
                        theatre_summary['israeli_strike_max_level'] = level
                    break

            # ISIS resurgence
            for kw in ISIS_RESURGENCE_TRIGGERS.get(level, []):
                if kw in text:
                    if level > ar['isis_score']:
                        ar['isis_score'] = level
                    if level > theatre_summary['isis_max_level']:
                        theatre_summary['isis_max_level'] = level
                    break

        # ── Coordination signals ──
        # HTS + SNA coordinated against SDF
        if actor_id == 'hts' and any(kw in text for kw in ACTOR_KEYWORDS['sna']):
            theatre_summary['coordination_signals'].append({
                'type': 'coordination',
                'message': 'HTS-SNA coordination signal detected — joint pressure on SDF',
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

        # Iran proxies + ISIS unusual co-occurrence (both active simultaneously)
        if actor_id == 'iran_proxies' and any(kw in text for kw in ACTOR_KEYWORDS['isis']):
            theatre_summary['coordination_signals'].append({
                'type': 'warning',
                'message': 'Iran proxy + ISIS co-occurrence detected — contested Deir ez-Zor',
                'article': article.get('title', '')[:100],
                'published': pub_date if isinstance(pub_date, str) else '',
            })

        # Israel strike + HTS silence signal (Israel acts but HTS doesn't respond)
        if actor_id == 'israel' and ar['israeli_strike_score'] >= 4:
            hts_count = actor_results['hts']['statement_count']
            if hts_count == 0:
                theatre_summary['coordination_signals'].append({
                    'type': 'silence',
                    'message': 'Israeli strike activity with HTS silence — possible tacit acceptance signal',
                    'article': article.get('title', '')[:100],
                    'published': pub_date if isinstance(pub_date, str) else '',
                })

        # Spokesperson detection
        actor_info = ACTORS.get(actor_id, {})
        for sp in actor_info.get('spokespersons', []):
            if sp.lower() in text and sp not in ar['spokespersons']:
                ar['spokespersons'].append(sp)

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
            })

    # ── Silence detection ──
    for actor_id, ar in actor_results.items():
        actor_info = ACTORS[actor_id]
        baseline = actor_info.get('baseline_statements_per_week', 3)
        expected = baseline * (3 / 7.0)  # 3-day window
        ar['silence_alert'] = ar['statement_count'] == 0 and expected >= 2

    return actor_results, theatre_summary


# ============================================
# RHETORIC SCORE CALCULATOR
# ============================================
def _calculate_rhetoric_score(actor_results, theatre_summary):
    """Calculate 0-100 rhetoric score from actor levels and signals."""
    factional = theatre_summary['factional_max_level']
    strikes   = theatre_summary['israeli_strike_max_level']
    isis      = theatre_summary['isis_max_level']

    # Weighted: factional most important for Syria stability
    raw = (factional * 14) + (strikes * 12) + (isis * 10)

    # Coordination bonus
    coord_count = len(theatre_summary['coordination_signals'])
    raw += min(coord_count * 3, 12)

    # Druze signal bonus (unusual activity indicator)
    druze_count = len(theatre_summary['druze_signals'])
    raw += min(druze_count * 2, 8)

    # Silence penalty for key actors
    silence_actors = [aid for aid, ar in actor_results.items() if ar.get('silence_alert')]
    if 'hts' in silence_actors:
        raw += 5  # HTS going silent is a warning signal

    return min(raw, 100)


# ============================================
# MAIN SCAN
# ============================================
def run_syria_rhetoric_scan(days=3):
    """Full Syria rhetoric scan."""
    print(f"[Syria Rhetoric Scan] Starting Syria theatre scan ({days}-day window)...")

    articles = fetch_rhetoric_articles(days)
    actor_results, theatre_summary = classify_articles(articles)

    # Overall escalation — max of all vectors
    max_factional = theatre_summary['factional_max_level']
    max_strikes   = theatre_summary['israeli_strike_max_level']
    max_isis      = theatre_summary['isis_max_level']
    max_level     = max(max_factional, max_strikes, max_isis)

    rhetoric_score = _calculate_rhetoric_score(actor_results, theatre_summary)

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'days_analyzed': days,
        'total_articles': len(articles),
        'theatre': 'Syria',
        'theatre_score': rhetoric_score,
        'theatre_escalation_level': max_level,
        'theatre_escalation_label': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Unknown'),
        'theatre_escalation_color': ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
        'theatre_escalation_description': ESCALATION_LEVELS.get(max_level, {}).get('description', ''),
        # Per-vector levels
        'factional_level': max_factional,
        'factional_label': ESCALATION_LEVELS.get(max_factional, {}).get('label', 'Baseline'),
        'israeli_strike_level': max_strikes,
        'israeli_strike_label': ESCALATION_LEVELS.get(max_strikes, {}).get('label', 'Baseline'),
        'isis_level': max_isis,
        'isis_label': ESCALATION_LEVELS.get(max_isis, {}).get('label', 'Baseline'),
        # Actors and signals
        'actors': actor_results,
        'coordination_signals': theatre_summary['coordination_signals'][:5],
        'druze_signals': theatre_summary['druze_signals'][:5],
        'version': '1.0.0-syria-rhetoric',
    }

    _redis_set(RHETORIC_CACHE_KEY, result)
    print(f"[Syria Rhetoric] ✅ Complete. Level: {result['theatre_escalation_label']} | Score: {rhetoric_score}/100")
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
        time.sleep(45)  # Stagger startup vs Lebanon/Yemen
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
    """Register Syria rhetoric endpoints on ME Flask app."""

    _start_periodic_scan(interval_hours=12)

    @app.route('/api/rhetoric/syria', methods=['GET'])
    def syria_rhetoric():
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
                'message': 'Syria rhetoric scan in progress. Refresh in 60 seconds.',
                'theatre': 'Syria',
                'theatre_score': 0,
                'theatre_escalation_level': 0,
                'theatre_escalation_label': 'Scanning...',
                'version': '1.0.0-syria-rhetoric',
            })

        result = run_syria_rhetoric_scan(days=days)
        return jsonify(result)

    @app.route('/api/rhetoric/syria/summary', methods=['GET'])
    def syria_rhetoric_summary():
        """Lightweight summary endpoint for stability page badge."""
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            return jsonify({
                'success': True,
                'theatre_score': cached.get('theatre_score', 0),
                'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
                'theatre_escalation_label': cached.get('theatre_escalation_label', 'Unknown'),
                'theatre_escalation_color': cached.get('theatre_escalation_color', '#6b7280'),
                'factional_level': cached.get('factional_level', 0),
                'israeli_strike_level': cached.get('israeli_strike_level', 0),
                'isis_level': cached.get('isis_level', 0),
                'druze_signals_count': len(cached.get('druze_signals', [])),
                'timestamp': cached.get('timestamp'),
                'cached': True,
            })
        return jsonify({'success': False, 'message': 'No cached data yet — scan in progress'})

    print("[Syria Rhetoric] ✅ Routes registered: /api/rhetoric/syria, /api/rhetoric/syria/summary")
