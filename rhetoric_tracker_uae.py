"""
rhetoric_tracker_uae.py -- Asifah Analytics ME Backend -- v1.0.0 Jul 2026
ALIGNED-HUB TRACKER: the UAE is a hub in its own right (finance/logistics/ports)
with the Gulf's most forward-leaning Israel alignment and a DUAL-POLARITY Iran
spoke (friction + economic lifeline simultaneously -- divergence between kinetic
and commercial rhetoric is itself the tell).
SLICES: israel (alliance -- Accords first-mover, EDGE-Rafael channel),
iran (dual: friction+lifeline), us (ally), houthi/kinetic (inbound).
ACTORS (8) / VECTORS (4 -- the uae-stability.html gauge contract):
  kinetic_inbound, israel_axis, iran_dual, economic_hub
EMITS: rhetoric:uae:latest + crosstheater:uae:fingerprint
ENDPOINTS: /api/rhetoric/uae (+ /debug). Convergence, not prediction.
"""

import os
import re
import json
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta

import requests

# Optional dependencies — degrade gracefully if missing
try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    print("[UAE Rhetoric] ⚠️  feedparser unavailable — RSS disabled")

# Cross-tracker commodity fingerprints — read via local WHA proxy.
# Architecture note: rhetoric_tracker_uae lives on the WHA backend, but
# commodity_tracker.py lives on the ME backend. We don't import across
# backends — instead, the WHA backend has commodity_proxy_wha.py which
# caches commodity fingerprints in WHA-local Redis with a 1-hour TTL.
# This tracker calls the WHA-local proxy endpoint (same Flask app —
# resolves over localhost or the public URL with negligible overhead).
ME_BACKEND_SELF_URL = os.environ.get(
    'ME_BACKEND_SELF_URL',
    'http://localhost:10000'  # default Render port for in-process calls
)
COMMODITY_FINGERPRINT_AVAILABLE = True  # always — we use HTTP proxy, not import

print("[UAE Rhetoric] Module loading...")

# Try to import signal interpreter for prose generation
try:
    from uae_signal_interpreter import (
        build_top_signals,
        build_executive_summary,
        build_so_what_factor,
        score_alignment_drift,
        build_alignment_drift_top_signal,
    )
    UAE_INTERPRETER_AVAILABLE = True
    print("[UAE Rhetoric] ✅ Signal interpreter loaded")
except ImportError:
    UAE_INTERPRETER_AVAILABLE = False
    print("[UAE Rhetoric] ⚠️  uae_signal_interpreter unavailable (will ship in shipment 2)")

# ============================================
# CONFIGURATION
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY       = os.environ.get('BRAVE_API_KEY')

CACHE_TTL_HOURS                = 12
BACKGROUND_REFRESH_HOURS       = 12
INITIAL_SCAN_DELAY_SECONDS     = 90
CROSSTHEATER_FINGERPRINT_TTL_HOURS = 13   # 12h refresh + 1h buffer

REDIS_KEY_LATEST       = 'rhetoric:uae:latest'
HISTORY_KEY            = 'rhetoric:uae:history'   # canonical snapshot index (May 22 2026 — read by wha_regional_bluf.prose_v2)
REDIS_KEY_FINGERPRINT_AXIS         = 'rhetoric:uae:china_axis_active'
REDIS_KEY_FINGERPRINT_CHANCAY      = 'rhetoric:uae:chancay_pressure'
REDIS_KEY_FINGERPRINT_MINING       = 'rhetoric:uae:mining_disruption'

GDELT_BASE_URL   = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL   = 'https://api.search.brave.com/res/v1/news/search'


# ============================================
# ALERT-LEVEL THRESHOLDS (per actor)
# ============================================
# Score → alert level mapping. These are tuned for an 8-actor 4-vector model
# at typical UAE news volume (~50-150 articles/scan). Compare to baseline
# statements_per_week in each actor definition to detect surge conditions.
def actor_alert_level(score, baseline):
    """Map a numeric actor-score to a discrete alert level using the actor's baseline."""
    if score < baseline * 0.5:
        return 'low'
    if score < baseline * 1.0:
        return 'normal'
    if score < baseline * 1.8:
        return 'elevated'
    if score < baseline * 2.8:
        return 'high'
    return 'surge'


# ============================================
# ACTOR DEFINITIONS — 8 actors total
# ============================================
ACTORS = {
    'uae_leadership_mbz': {
        'name': 'Leadership / MBZ', 'flag': '🇦🇪', 'icon': '👑', 'color': '#e2e8f0',
        'role': 'Presidential statements -- strategic posture, federation signals',
        'description': 'MBZ and senior-leadership statements: foreign-policy declarations, sovereign-wealth direction, Abu Dhabi-Dubai federation signals.',
        'vector': 'economic_hub',
        'keywords': ['mohammed bin zayed','mbz uae','uae president','sheikh mohamed uae','abu dhabi crown prince',
                     'uae leadership','محمد بن زايد'],
        'baseline_statements_per_week': 6,
    },
    'uae_mod_airdefense': {
        'name': 'UAE MOD / Air Defense', 'flag': '🇦🇪', 'icon': '🛡️', 'color': '#f97316',
        'role': 'Kinetic-inbound posture -- intercepts, scrambles, defense ops',
        'description': 'UAE military statements: drone/missile intercepts over Abu Dhabi and Dubai, air-defense activations, coalition operations. Intercept tempo tracks the inbound-threat cycle.',
        'vector': 'kinetic_inbound',
        'keywords': ['uae air defense','uae intercepts','uae shoots down','uae military','uae armed forces',
                     'uae scrambles','abu dhabi attack','dubai attack','uae patriot','uae thaad',
                     'الدفاع الجوي الإماراتي'],
        'baseline_statements_per_week': 5,
    },
    'houthi_uae': {
        'name': 'Houthi / Inbound Threats', 'flag': '🇾🇪', 'icon': '🚀', 'color': '#dc2626',
        'role': 'Kinetic-inbound driver -- claims and attacks toward UAE territory',
        'description': 'Houthi claims targeting the UAE (the Jan 2022 Abu Dhabi strikes = precedent) plus Red Sea/maritime threat signals touching UAE shipping.',
        'vector': 'kinetic_inbound',
        'keywords': ['houthi uae','houthi attack uae','houthi abu dhabi','houthi dubai','houthi claim uae',
                     'drone attack uae','missile uae','الحوثي الإمارات'],
        'baseline_statements_per_week': 4,
    },
    'israel_uae_axis': {
        'name': 'Israel Axis', 'flag': '🤝', 'icon': '🛡️', 'color': '#38bdf8',
        'role': 'The Accords-goes-kinetic vector -- defense cooperation, training, transfers',
        'description': 'Israel-UAE signals: defense deals, Israeli training and air-defense transfers (current conflict), the EDGE-Rafael industrial channel, joint exercises. The Gulf\'s most forward-leaning Israeli alignment.',
        'vector': 'israel_axis',
        'keywords': ['israel uae defense','uae israeli weapons','israel uae cooperation','edge rafael',
                     'uae israel exercise','israel trains uae','uae barak','israel uae deal',
                     'abraham accords uae','uae israel trade'],
        'baseline_statements_per_week': 4,
    },
    'iran_uae_dual': {
        'name': 'Iran (Dual Track)', 'flag': '🇮🇷', 'icon': '⚖️', 'color': '#0ea5e9',
        'role': 'MIXED POLARITY: friction (drones, threats) + lifeline (Dubai trade lung)',
        'description': 'Iran-UAE signals both polarities at once: kinetic threats and intercepts alongside re-export trade, flights, and diaspora finance. Divergence between the kinetic and commercial tracks is itself the tell.',
        'vector': 'iran_dual',
        'keywords': ['iran uae','uae iran relations','iran dubai trade','iran uae flights','iran threatens uae',
                     'iranian drone uae','iran uae talks','dubai iran business','إيران الإمارات'],
        'baseline_statements_per_week': 5,
    },
    'adnoc_energy': {
        'name': 'ADNOC / Energy', 'flag': '🛢️', 'icon': '⚡', 'color': '#fb923c',
        'role': 'Energy signals -- production, Fujairah bypass, Barakah, OPEC+ friction',
        'description': 'ADNOC operations: production guidance, Habshan-Fujairah bypass throughput, Barakah nuclear status, OPEC+ quota friction with Riyadh.',
        'vector': 'economic_hub',
        'keywords': ['adnoc','uae oil production','fujairah pipeline','habshan','barakah nuclear',
                     'uae opec','uae oil exports','fujairah terminal'],
        'baseline_statements_per_week': 5,
    },
    'dp_world_ports': {
        'name': 'DP World / Ports Hub', 'flag': '⚓', 'icon': '🚢', 'color': '#84cc16',
        'role': 'Logistics-as-statecraft signals -- Jebel Ali, Fujairah anchorage, expansion',
        'description': 'DP World and ports-network signals: Jebel Ali operations, Fujairah anchorage incidents (2019 precedent), terminal expansions, war-risk insurance news.',
        'vector': 'economic_hub',
        'keywords': ['dp world','jebel ali','fujairah port','uae ports','fujairah anchorage',
                     'uae shipping','war risk premium uae','tanker uae'],
        'baseline_statements_per_week': 4,
    },
    'us_uae': {
        'name': 'US-UAE Track', 'flag': '🇺🇸', 'icon': '🛡️', 'color': '#64748b',
        'role': 'Ally anchor -- Al Dhafra, arms packages, strategic agreements',
        'description': 'US-UAE defense statements: Al Dhafra operations, arms deals (the F-35 saga), security agreements.',
        'vector': 'israel_axis',
        'keywords': ['us uae','uae arms deal us','al dhafra','us forces uae','uae f-35',
                     'us uae defense','american troops uae'],
        'baseline_statements_per_week': 4,
    },
}

DOMESTIC_ACTORS = ['uae_leadership_mbz', 'uae_mod_airdefense', 'adnoc_energy', 'dp_world_ports']
EXTERNAL_ACTORS = ['houthi_uae', 'iran_uae_dual', 'israel_uae_axis', 'us_uae']
RESOURCE_ACTORS = ['adnoc_energy', 'dp_world_ports']
ALIGNMENT_ACTORS = {'israel_uae_axis': 'israel_axis', 'us_uae': 'israel_axis'}

# Vector groupings -- these keys ARE the uae-stability.html gauge contract
VECTOR_GROUPS = {
    'kinetic_inbound': ['uae_mod_airdefense', 'houthi_uae'],
    'israel_axis':     ['israel_uae_axis', 'us_uae'],
    'iran_dual':       ['iran_uae_dual'],
    'economic_hub':    ['adnoc_energy', 'dp_world_ports', 'uae_leadership_mbz'],
}


# ============================================
# TRIPWIRES — high-severity events that escalate alert level regardless of volume
# ============================================
TRIPWIRES = {
    'homeland_attack': {
        'patterns': ['abu dhabi attacked','dubai attacked','missiles abu dhabi','drone strike dubai',
                     'attack on uae soil','strikes uae territory'],
        'severity': 'surge',
        'note': 'Attack on UAE population/economic centers -- the Jan 2022 Abu Dhabi precedent class.',
    },
    'fujairah_maritime_incident': {
        'patterns': ['fujairah attack','tankers attacked fujairah','fujairah sabotage','fujairah anchorage incident',
                     'ships attacked uae'],
        'severity': 'high',
        'note': 'Maritime incident at the Hormuz-bypass terminus -- the May 2019 precedent.',
    },
    'israel_defense_deal': {
        'patterns': ['israel uae defense deal','uae buys israeli air defense','israel uae arms agreement',
                     'edge rafael deal','israel uae defense pact'],
        'severity': 'elevated',
        'note': 'Accords-goes-kinetic milestone -- deepens the israel_axis vector (MIL tracker amplifier pairs with this).',
    },
    'iran_trade_rupture': {
        'patterns': ['uae halts iran trade','iran uae trade suspended','dubai iran sanctions crackdown',
                     'iran uae flights suspended','uae expels iranian'],
        'severity': 'high',
        'note': 'Dual-track rupture: the lifeline polarity failing -- watch whether kinetic polarity follows.',
    },
    'barakah_threat': {
        'patterns': ['barakah attack','barakah threatened','nuclear plant uae attack','barakah targeted'],
        'severity': 'surge',
        'note': 'Threat to the first Arab nuclear plant -- escalation-class by construction.',
    },
    'jebel_ali_disruption': {
        'patterns': ['jebel ali closed','jebel ali attack','jebel ali suspended','dp world halts'],
        'severity': 'high',
        'note': 'Hub-disruption event: the region\'s largest port going dark is a global logistics signal.',
    },
}
RSS_FEEDS = {
    'gn_en':   {'url': 'https://news.google.com/rss/search?q=UAE%20(Israel%20OR%20Iran%20OR%20ADNOC%20OR%20%22Abu%20Dhabi%22)&hl=en-US&gl=US&ceid=US:en', 'name': 'GoogleNews-EN', 'weight': 0.85, 'language': 'en'},
    'gn_ar':   {'url': 'https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%A5%D9%85%D8%A7%D8%B1%D8%A7%D8%AA&hl=ar&gl=AE&ceid=AE:ar', 'name': 'GoogleNews-AR', 'weight': 0.8, 'language': 'ar'},
    'thenational': {'url': 'https://www.thenationalnews.com/rss', 'name': 'The National', 'weight': 1.0, 'language': 'en'},
    'gulfnews':    {'url': 'https://gulfnews.com/rss', 'name': 'Gulf News', 'weight': 0.95, 'language': 'en'},
    'khaleej':     {'url': 'https://www.khaleejtimes.com/rss', 'name': 'Khaleej Times', 'weight': 0.9, 'language': 'en'},
    'almonitor':   {'url': 'https://www.al-monitor.com/rss', 'name': 'Al-Monitor', 'weight': 0.95, 'language': 'en'},
}
GDELT_QUERIES_EN = [
    '"UAE" AND ("Israel" OR "defense" OR "Accords")',
    '"UAE" AND ("Iran" OR "drone" OR "intercept")',
    '"ADNOC" OR "Fujairah" OR "Jebel Ali" OR "Barakah"',
    '"Abu Dhabi" OR "Dubai" AND ("attack" OR "missile")',
]
GDELT_QUERIES_ES = [
    'الإمارات',
    'أبوظبي',
]

# ============================================
# CACHE / REDIS HELPERS
# ============================================
CACHE_FILE = '/tmp/uae_rhetoric_cache.json'
_background_scan_running = False
_background_scan_lock = threading.Lock()
_last_scan_started_at = None


def _redis_get(key):
    """Read a JSON value from Upstash Redis. Returns None if unavailable / missing."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=8
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        raw = body.get('result')
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        print(f"[UAE Rhetoric] Redis GET error ({key}): {str(e)[:120]}")
        return None


def _redis_set(key, value, ttl_hours=CACHE_TTL_HOURS):
    """Write a JSON value to Upstash Redis with TTL. Returns True on success."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        ttl_seconds = int(ttl_hours * 3600)
        url = f"{UPSTASH_REDIS_URL}/setex/{key}/{ttl_seconds}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(value, default=str),
            timeout=8
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[UAE Rhetoric] Redis SET error ({key}): {str(e)[:120]}")
        return False


def load_cache():
    """Try Redis first, fallback to /tmp file."""
    cached = _redis_get(REDIS_KEY_LATEST)
    if cached:
        return cached
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _redis_lpush_trim(key, value, max_len=336):
    """LPUSH + LTRIM to keep rolling history (336 = 14 days × 24 hourly entries).
    Canonical helper added May 22 2026 — mirrors Cuba pattern, read by wha_regional_bluf.prose_v2.
    Uses same direct-key style as _redis_set (Upstash accepts colons in keys without encoding)."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        # LPUSH the new entry
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/lpush/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(value, default=str),
            timeout=8,
        )
        if resp.status_code != 200:
            return False
        # LTRIM to bound buffer length
        requests.post(
            f"{UPSTASH_REDIS_URL}/ltrim/{key}/0/{max_len - 1}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=8,
        )
        return True
    except Exception as e:
        print(f"[UAE Rhetoric] Redis LPUSH error ({key}): {str(e)[:120]}")
        return False


def save_cache(data):
    """Save to Redis + /tmp fallback."""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    if _redis_set(REDIS_KEY_LATEST, data, ttl_hours=CACHE_TTL_HOURS):
        print("[UAE Rhetoric] ✅ Saved to Redis")
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        print(f"[UAE Rhetoric] /tmp save error: {e}")


def is_cache_fresh(data):
    """Check if cache is younger than CACHE_TTL_HOURS."""
    if not data or 'cached_at' not in data:
        return False
    try:
        cached_at = datetime.fromisoformat(data['cached_at'])
        age = datetime.now(timezone.utc) - cached_at
        return age.total_seconds() < (CACHE_TTL_HOURS * 3600)
    except Exception:
        return False


# ============================================
# DATA FETCHERS — RSS / GDELT / NewsAPI / Brave
# ============================================
def fetch_rss_articles(feed_id, feed_config, max_articles=30):
    """Fetch + parse a single RSS feed."""
    if not FEEDPARSER_AVAILABLE:
        return []
    articles = []
    try:
        feed = feedparser.parse(feed_config['url'])
        for entry in feed.entries[:max_articles]:
            articles.append({
                'title':       entry.get('title', ''),
                'description': entry.get('summary', '') or entry.get('description', ''),
                'url':         entry.get('link', ''),
                'published':   entry.get('published', ''),
                'source':      feed_config['name'],
                'feed_id':     feed_id,
                'feed_type':   'rss',
                'language':    feed_config.get('language', 'en'),
                'feed_weight': feed_config.get('weight', 1.0),
            })
    except Exception as e:
        print(f"[UAE Rhetoric] RSS fetch error ({feed_id}): {str(e)[:120]}")
    return articles


def fetch_all_rss():
    all_articles = []
    for feed_id, feed_config in RSS_FEEDS.items():
        articles = fetch_rss_articles(feed_id, feed_config)
        if articles:
            print(f"[UAE Rhetoric] RSS {feed_id}: {len(articles)} articles")
        all_articles.extend(articles)
    return all_articles


def fetch_gdelt_query(query, language='eng', days=7, max_articles=50):
    """Fetch a single GDELT query with circuit-breaker timeout."""
    params = {
        'query':       f'{query} sourcelang:{language}',
        'mode':        'artlist',
        'maxrecords':  max_articles,
        'format':      'json',
        'timespan':    f'{days}d',
    }
    try:
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 12))
        if resp.status_code == 429:
            return []  # rate limited — bail silently
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for item in data.get('articles', []):
            articles.append({
                'title':       item.get('title', ''),
                'description': '',
                'url':         item.get('url', ''),
                'published':   item.get('seendate', ''),
                'source':      item.get('domain', 'GDELT'),
                'feed_id':     'gdelt',
                'feed_type':   'gdelt',
                'language':    'ar' if language == 'ara' else 'en',
                'feed_weight': 0.85,
            })
        return articles
    except Exception:
        return []


def fetch_all_gdelt(days=7):
    all_articles = []
    for q in GDELT_QUERIES_EN:
        all_articles.extend(fetch_gdelt_query(q, language='eng', days=days))
        time.sleep(0.5)
    for q in GDELT_QUERIES_ES:
        all_articles.extend(fetch_gdelt_query(q, language='ara', days=days))
        time.sleep(0.5)
    print(f"[UAE Rhetoric] GDELT: {len(all_articles)} articles")
    return all_articles


def fetch_newsapi(query, days=7):
    """Fetch from NewsAPI."""
    if not NEWSAPI_KEY:
        return []
    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    params = {
        'q':        query,
        'from':     from_date,
        'language': 'en',
        'sortBy':   'publishedAt',
        'pageSize': 30,
        'apiKey':   NEWSAPI_KEY,
    }
    try:
        resp = requests.get(NEWSAPI_BASE_URL, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for item in data.get('articles', []):
            articles.append({
                'title':       item.get('title', ''),
                'description': item.get('description', ''),
                'url':         item.get('url', ''),
                'published':   item.get('publishedAt', ''),
                'source':      (item.get('source') or {}).get('name', 'NewsAPI'),
                'feed_id':     'newsapi',
                'feed_type':   'newsapi',
                'language':    'en',
                'feed_weight': 0.9,
            })
        return articles
    except Exception:
        return []


def fetch_all_newsapi(days=7):
    queries = [
        'UAE Israel defense cooperation',
        'UAE Iran relations trade',
        'Houthi attack UAE OR Abu Dhabi',
        'ADNOC Fujairah pipeline',
        'DP World Jebel Ali',
        'Barakah nuclear UAE',
        'Abraham Accords UAE',
    ]
    all_articles = []
    for q in queries:
        all_articles.extend(fetch_newsapi(q, days=days))
        time.sleep(0.5)
    if all_articles:
        print(f"[UAE Rhetoric] NewsAPI: {len(all_articles)} articles")
    return all_articles


def fetch_brave(query, days=7):
    """Brave Search News API — tertiary fallback."""
    if not BRAVE_API_KEY:
        return []
    params = {'q': query, 'count': 20, 'spellcheck': '0'}
    try:
        resp = requests.get(
            BRAVE_BASE_URL,
            params=params,
            headers={
                'Accept':                'application/json',
                'Accept-Encoding':       'gzip',
                'X-Subscription-Token':  BRAVE_API_KEY,
            },
            timeout=10
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for item in data.get('results', []):
            articles.append({
                'title':       item.get('title', ''),
                'description': item.get('description', ''),
                'url':         item.get('url', ''),
                'published':   item.get('age', ''),
                'source':      (item.get('source') or '') or 'Brave',
                'feed_id':     'brave',
                'feed_type':   'brave',
                'language':    'en',
                'feed_weight': 0.75,
            })
        return articles
    except Exception:
        return []


def fetch_all_brave(days=7, gdelt_count=0, newsapi_count=0):
    """Brave fallback — only fires when GDELT + NewsAPI returned <10 articles total."""
    if gdelt_count + newsapi_count >= 10:
        return []
    queries = [
        'UAE Israel defense 2026',
        'Iran UAE drone',
        'Fujairah tanker',
        'Jebel Ali port',
    ]
    all_articles = []
    for q in queries:
        all_articles.extend(fetch_brave(q, days=days))
        time.sleep(0.5)
    if all_articles:
        print(f"[UAE Rhetoric] Brave fallback: {len(all_articles)} articles")
    return all_articles


# ============================================
# CLASSIFICATION + SCORING
# ============================================
def _normalize_text(text):
    """Lowercase + strip diacritics-light for keyword matching."""
    return (text or '').lower()


def _classify_article_actor(article):
    """
    Match an article against actor keyword lists. Returns (actor_id, hit_count) tuples
    for all matching actors. Multi-actor matching is allowed (e.g., a "Boluarte visits
    Las Bambas" headline can hit both presidency AND las_bambas).
    """
    title = _normalize_text(article.get('title', ''))
    desc  = _normalize_text(article.get('description', ''))
    text  = title + ' ' + desc

    matches = []
    for actor_id, actor_data in ACTORS.items():
        hit_count = 0
        for kw in actor_data['keywords']:
            if kw.lower() in text:
                hit_count += 1
        if hit_count > 0:
            matches.append((actor_id, hit_count))
    return matches


def _check_tripwires(text):
    """Check article text against TRIPWIRES patterns. Returns list of (tripwire_id, severity)."""
    text_lower = _normalize_text(text)
    triggered = []
    for tw_id, tw_data in TRIPWIRES.items():
        for pattern in tw_data['patterns']:
            if pattern.lower() in text_lower:
                triggered.append((tw_id, tw_data['severity']))
                break  # only count each tripwire once per article
    return triggered


def _score_actor_articles(articles_for_actor, actor_id):
    """
    Compute weighted score for an actor: sum of (feed_weight × keyword-density × recency).
    Returns dict with score, article_count, language_breakdown, sources, top_articles, tripwires.
    """
    if not articles_for_actor:
        return {
            'score': 0,
            'article_count': 0,
            'language_breakdown': {},
            'sources': [],
            'top_articles': [],
            'tripwires': [],
        }

    score = 0
    lang_count = {}
    src_count = {}
    tripwires_seen = set()

    for art in articles_for_actor:
        feed_w = art.get('feed_weight', 1.0)
        kw_hits = art.get('_actor_hits', 1)  # set by classifier
        kw_factor = min(1.0 + (kw_hits - 1) * 0.15, 2.0)  # diminishing returns
        article_score = feed_w * kw_factor
        score += article_score

        lang = art.get('language', 'en')
        lang_count[lang] = lang_count.get(lang, 0) + 1
        src = art.get('source', 'Unknown')
        src_count[src] = src_count.get(src, 0) + 1

        # Tripwire check
        full_text = f"{art.get('title', '')} {art.get('description', '')}"
        for tw_id, severity in _check_tripwires(full_text):
            tripwires_seen.add((tw_id, severity))

    # Sort articles by article_score descending
    sorted_articles = sorted(
        articles_for_actor,
        key=lambda a: a.get('feed_weight', 1.0) * min(1.0 + (a.get('_actor_hits', 1) - 1) * 0.15, 2.0),
        reverse=True,
    )
    top_articles = []
    for a in sorted_articles[:8]:
        top_articles.append({
            'title':       a.get('title', ''),
            'url':         a.get('url', ''),
            'source':      a.get('source', ''),
            'language':    a.get('language', 'en'),
            'published':   a.get('published', ''),
            'feed_type':   a.get('feed_type', ''),
        })

    sources = sorted(src_count.items(), key=lambda x: -x[1])[:6]

    return {
        'score':              round(score, 2),
        'article_count':      len(articles_for_actor),
        'language_breakdown': lang_count,
        'sources':            [{'source': s, 'count': c} for s, c in sources],
        'top_articles':       top_articles,
        'tripwires':          [{'id': tw_id, 'severity': sev} for tw_id, sev in tripwires_seen],
    }


# ============================================
# CROSS-TRACKER FINGERPRINT INTEGRATION
# ============================================
def _read_commodity_pressure_for_uae():
    """
    Read commodity supply-risk fingerprints for UAE's exposed commodities
    via the WHA-local commodity proxy (commodity_proxy_wha.py).

    The proxy caches ME-backend fingerprints in WHA Redis with 1-hour TTL,
    so this call is a cheap localhost hit on the proxy — no cross-backend
    HTTP latency unless the WHA-local cache misses.

    Returns dict {commodity_id: risk_dict} for any active pressure.
    Returns {} on error / empty / proxy unavailable — graceful degradation.
    """
    try:
        url = f"{ME_BACKEND_SELF_URL}/api/commodity-pressure/uae"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        # Proxy returns {fingerprints: {commodity_id: risk_dict}, ...}
        return data.get('fingerprints', {}) or {}
    except Exception as e:
        print(f"[UAE Rhetoric] commodity proxy read error: {str(e)[:120]}")
        return {}


def _read_commodity_pressure_story_for_uae():
    """
    Read the composite pressure STORY from the WHA-local commodity proxy
    (/api/commodity-pressure/uae -- 12hr-cached pass-through of the ME backend's
    /api/commodity-pressure/uae). This is the SAME payload the UAE stability
    page renders (composite points, alert band, per-commodity global alerts),
    so the rhetoric tracker and stability page tell ONE story.

    Returns compact dict or {} on any failure (graceful degradation):
      {alert, points, profile_count, commodities: {commodity_id: global_alert_level}}
    """
    try:
        url = f"{ME_BACKEND_SELF_URL}/api/commodity-pressure/uae"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        commodities = {}
        for tile in (data.get('commodity_summaries') or []):
            cid = tile.get('commodity')
            if cid:
                commodities[cid] = tile.get('global_alert_level') or 'normal'
        return {
            'alert':         (data.get('alert_level') or 'normal').lower(),
            'points':        round(float(data.get('commodity_pressure') or 0), 1),
            'profile_count': data.get('profile_count') or len(commodities),
            'commodities':   commodities,
        }
    except Exception as e:
        print(f"[UAE Rhetoric] commodity story read error: {str(e)[:120]}")
        return {}


def _read_crosstheater_amplifiers():
    """
    Sibling-tracker fingerprints that shape UAE's analytical context
    (the wheels, read from the shared Redis -- absence-honest when missing):
      pakistan_fingerprint -- crosstheater:pakistan:fingerprint (confirmed sibling)
      iran_fingerprint     -- crosstheater:iran:fingerprint     (ME backend, attempted)
      china_fingerprint    -- crosstheater:china:fingerprint    (attempted)
    """
    amplifiers = {}
    candidate_keys = {
        'iran_fingerprint':   'crosstheater:iran:fingerprint',
        'israel_fingerprint': 'crosstheater:israel:fingerprint',
        'saudi_fingerprint':  'crosstheater:saudi_arabia:fingerprint',
    }
    for label, redis_key in candidate_keys.items():
        val = _redis_get(redis_key)
        if val:
            amplifiers[label] = val
    return amplifiers

def _builtin_fallback_signals(composite_score, composite_level, vector_scores,
                              vector_levels, actor_summaries, tripwires_global,
                              disaster_state):
    """Interpreter-absent fallback (v1 ships without a dedicated interpreter):
    compact executive summary + canonical-ish top_signals so the page and the
    Asia BLUF always have something honest to render. Estimative voice only."""
    sigs = []
    # tripwire hits first
    for tw in (tripwires_global or [])[:3]:
        name = tw.get('tripwire', tw.get('id', 'tripwire')) if isinstance(tw, dict) else str(tw)
        sev  = tw.get('severity', 'high') if isinstance(tw, dict) else 'high'
        sigs.append({'level': sev, 'type': 'tripwire', 'priority': 10,
                     'category': 'tripwire', 'theatre': 'uae',
                     'pressure_type': 'kinetic',
                     'short_text': f"\U0001f1e6\U0001f1eb UAE ARABIA tripwire: {str(name).replace('_',' ')}",
                     'long_text':  f"UAE ARABIA tripwire fired: {str(name).replace('_',' ')} -- "
                                   f"pattern-level escalation event this scan window."})
    # dual-polarity read: iran_uae_dual elevated -- name which track is driving
    _iran = (actor_summaries or {}).get('iran_uae_dual', {})
    if _iran.get('level') in ('high', 'surge'):
        sigs.append({'level': _iran['level'], 'type': 'dual_track_divergence', 'priority': 9,
                     'category': 'dual_track_divergence', 'theatre': 'uae',
                     'pressure_type': 'diplomatic',
                     'short_text': '\U0001f1e6\U0001f1ea UAE: Iran dual-track at ' + _iran['level'].upper(),
                     'long_text':  'Iran-UAE signal tempo at ' + _iran['level'] + ' on a MIXED-POLARITY spoke: '
                                   'friction (drones, threats) and lifeline (Dubai trade) run simultaneously. '
                                   'Divergence between the kinetic and commercial tracks is itself the tell -- '
                                   'lifeline holding while kinetics spike has historically read as contained.'})
    # surge/high actors
    for akey, summ in (actor_summaries or {}).items():
        lvl = summ.get('level','low') if isinstance(summ,dict) else 'low'
        if lvl in ('high','surge'):
            sigs.append({'level': lvl, 'type': 'actor_signal', 'priority': 7,
                         'category': 'actor_signal', 'theatre': 'uae',
                         'pressure_type': 'kinetic',
                         'short_text': f"\U0001f1e6\U0001f1eb {akey.replace('_',' ').title()} at {lvl.upper()}",
                         'long_text':  f"UAE ARABIA actor {akey.replace('_',' ')} scanning at {lvl} -- "
                                       f"elevated statement tempo/severity versus baseline."})
    sigs.sort(key=lambda x: -x.get('priority',0))

    vecs_hot = [k.replace('_',' ') for k,v in (vector_levels or {}).items()
                if v in ('elevated','high','surge')]
    parts = [f"UAE composite {composite_score:.1f} ({composite_level.upper()})."]
    parts.append(f"Active vectors: {', '.join(vecs_hot[:3])}." if vecs_hot
                 else "All four vectors at baseline this scan.")
    parts.append("Aligned-hub node: Israel axis + dual-polarity Iran spoke -- divergence "
                 "between kinetic and commercial tracks is the tell. Convergence read, not prediction.")
        # --- Fallback So-What bullets (v1: interpreter-less; vector-level driven) ---
    so_what = []
    _esc = ('elevated', 'high', 'surge')
    _sw = {
        'kinetic_inbound': "Kinetic-inbound vector is {lvl} -- intercept/threat signal tempo at this level reads "
                           "against the Jan 2022 Abu Dhabi precedent; watch air-defense activation reporting and "
                           "Fujairah anchorage advisories.",
        'israel_axis': "Israel-axis vector is {lvl} -- defense-cooperation signal tempo rising (EDGE-Rafael channel, "
                           "training, transfers); the Accords-goes-kinetic story deepening. The MIL tracker's "
                           "israel_uae_defense amplifier pairs with this read.",
        'iran_dual': "Iran dual-track vector is {lvl} -- on a MIXED-POLARITY spoke, the question is which track "
                           "drives it: friction (drones, threats) or lifeline (Dubai trade). Divergence between the "
                           "kinetic and commercial tracks is itself the tell.",
        'economic_hub': "Economic-hub vector is {lvl} -- ports/energy signal volume elevated; watch Jebel Ali "
                           "operations reporting, war-risk premiums on UAE calls, and ADNOC guidance.",
    }
    for _vec, _lvl in (vector_levels or {}).items():
        if _lvl in _esc and _vec in _sw:
            so_what.append({'weight': 0.9, 'bullet': _sw[_vec].format(lvl=str(_lvl).upper())})
    if not so_what:
        so_what.append({'weight': 0.3, 'bullet':
            "All four vectors at baseline this scan. Baseline for the aligned hub still means both Iran tracks "
            "running simultaneously -- friction and lifeline -- and the Israel defense axis compounding quietly. "
            "Divergence between kinetic and commercial rhetoric remains the standing tell."})
    so_what.sort(key=lambda b: -b['weight'])
    return sigs[:8], ' '.join(parts), so_what[:6]


def _write_uae_fingerprints(actor_levels, vector_scores, tripwires_global):
    """
    UAE crosstheater slice -- ALIGNED-HUB node.
    Slices: israel (alliance -- Accords first-mover, defense channel),
    iran (dual: friction+lifeline flags carried separately), us (ally),
    houthi (kinetic inbound). Consumers: ME BLUF, GPI, future US wheel,
    MIL israel_uae_defense amplifier context.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    def _slice(actor_key, role):
        lvl = actor_levels.get(actor_key, 'low')
        return {'level': lvl, 'role': role,
                'active': lvl in ('elevated', 'high', 'surge')}

    hub_presence = {
        'israel': _slice('israel_uae_axis', 'alliance'),
        'iran':   dict(_slice('iran_uae_dual', 'dual_friction_lifeline'), mixed_polarity=True),
        'us':     _slice('us_uae', 'ally'),
        'houthi': _slice('houthi_uae', 'kinetic_inbound'),
    }
    slices_active = sum(1 for w in hub_presence.values() if w.get('active'))

    slice_payload = {
        'ts':              now_iso,
        'theatre':         'uae',
        'node_class':      'aligned_hub',
        'hub_presence':    hub_presence,
        'slices_active':   slices_active,
        'israel_axis':     vector_scores.get('israel_axis', 0),
        'iran_dual':       vector_scores.get('iran_dual', 0),
        'kinetic_inbound': vector_scores.get('kinetic_inbound', 0),
        'tripwires':       tripwires_global[:5] if isinstance(tripwires_global, list) else [],
    }
    _redis_set('crosstheater:uae:fingerprint', slice_payload, ttl_hours=14)
    print(f"[UAE Rhetoric] Crosstheater slice written -- slices_active={slices_active}")

def _compute_uae_l5_gate(tripwires_global, actor_summaries, vector_scores):
    """
    Per platform L5 Reservation Contract: UAE L5 "Active Crisis" requires
    an explicit kinetic / humanitarian / economic / diplomatic L5 trigger.

    UAE is a contested-node tracker. L5 'Active Crisis' is reserved for
    crisis-class events: sustained missile campaign on Abu Dhabi/Dubai, Barakah
    strike, or Jebel Ali destruction-scale disruption. Scaffold today -- the
    weekend audit adds severity-5 tripwires per axis; until then the gate
    correctly returns any=False.

    Returns dict with axis flags + reason string.
    """
    gate = {
        'kinetic':      False,
        'humanitarian': False,
        'economic':     False,
        'diplomatic':   False,
        'reason':       '',
        'any':          False,
    }

    # Convert tripwires_global to a flat set for lookup by (actor_id, tw_id)
    fired_tws = set()
    for entry in tripwires_global or []:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            fired_tws.add(f"{entry[0]}:{entry[1]}")
        elif isinstance(entry, dict):
            actor = entry.get('actor_id', '')
            twid  = entry.get('tw_id', '')
            if actor and twid:
                fired_tws.add(f"{actor}:{twid}")

    reasons = []

    # ── KINETIC L5 (scaffold — refine in weekend audit) ──
    # Would fire on: sustained missile campaign on population centers,
    # Barakah strike with radiological dimension. No severity-5 tripwires
    # currently defined in UAE's ACTORS dict. Awaits weekend audit.
    # Today: never fires.

    # ── HUMANITARIAN L5 (scaffold — refine in weekend audit) ──
    # Would fire on: famine-scale rupture, catastrophic quake displacement,
    # deportation-wave humanitarian collapse. No severity-5 tripwires currently defined.
    # Today: never fires.

    # ── ECONOMIC L5 (scaffold — refine in weekend audit) ──
    # Would fire on: dirham-peg event, Jebel Ali dark beyond 30 days,
    # DP World network failure. No severity-5 tripwires currently defined.
    # Today: never fires.

    # ── DIPLOMATIC L5 (scaffold — refine in weekend audit) ──
    # Would fire on: recognition-cascade rupture, wheel-power embassy
    # closures, UN-mandate collapse. No severity-5 tripwires currently defined.
    # Today: never fires.

    gate['any']    = any(gate[k] for k in ('kinetic', 'humanitarian', 'economic', 'diplomatic'))
    gate['reason'] = '; '.join(reasons) if reasons else 'No L5 axis trigger fired (L5 reserved: sustained homeland campaign, Barakah strike, hub destruction)'

    return gate


def _build_uae_signal_text(theatre_level, theatre_score, vector_levels, actor_summaries, l5_capped=False):
    """
    Build short_text + long_text for UAE's theatre_high signal.
    Returns dict {'short': str, 'long': str}.
    """
    # Identify top vectors at elevated+
    vectors_active = []
    if isinstance(vector_levels, dict):
        for vec, lvl in vector_levels.items():
            if lvl in ('elevated', 'high', 'surge'):
                vectors_active.append(vec.replace('_', ' '))

    vectors_brief = ', '.join(vectors_active[:3]) if vectors_active else 'baseline'

    # Identify top actors at elevated+
    actors_active = []
    if isinstance(actor_summaries, dict):
        for actor, summary in actor_summaries.items():
            lvl = summary.get('level', 'low') if isinstance(summary, dict) else 'low'
            if lvl in ('elevated', 'high', 'surge'):
                actors_active.append(actor.replace('_', ' '))

    actors_brief = ', '.join(actors_active[:3]) if actors_active else ''

    label_map = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning',
                 3: 'Direct Threat', 4: 'Coercion', 5: 'Active Crisis'}
    label = label_map.get(theatre_level, 'Monitoring')

    short = f"🇦🇪 UAE ARABIA L{theatre_level} {label} — {vectors_brief}"
    if len(short) > 120:
        short = short[:117] + '...'

    long_parts = [f"🇦🇪 UAE ARABIA at L{theatre_level} {label} (theatre score {theatre_score}/100)."]
    if vectors_active:
        long_parts.append(f"Active vectors: {vectors_brief}.")
    if actors_active:
        long_parts.append(f"Top actors: {actors_brief}.")
    if l5_capped:
        long_parts.append("L5 axis gate did not fire — capped at L4 ceiling per platform L5 Reservation Contract.")
    else:
        long_parts.append("UAE is a contested-node tracker: four mixed-polarity wheels (Iran friction, Pakistan kinetic, Russia normalization, China extraction).")

    return {'short': short, 'long': ' '.join(long_parts)}


# ============================================
# MAIN SCAN ORCHESTRATOR
# ============================================
def scan_uae_rhetoric(force=False, days=7):
    """
    Full scan: fetch from all sources, classify per actor, score, build summaries,
    write fingerprints, return result.
    """
    global _last_scan_started_at
    _last_scan_started_at = datetime.now(timezone.utc)
    scan_start = time.time()

    print(f"[UAE Rhetoric] === Scan start (force={force}, days={days}) ===")

    # ── Fetch all sources ──
    rss_articles = fetch_all_rss()
    print(f"[UAE Rhetoric] RSS total: {len(rss_articles)}")
    gdelt_articles = fetch_all_gdelt(days=days)
    newsapi_articles = fetch_all_newsapi(days=days)
    brave_articles = fetch_all_brave(
        days=days,
        gdelt_count=len(gdelt_articles),
        newsapi_count=len(newsapi_articles),
    )

    all_articles = rss_articles + gdelt_articles + newsapi_articles + brave_articles
    # Dedupe by URL
    seen_urls = set()
    deduped = []
    for a in all_articles:
        u = a.get('url', '')
        if u and u not in seen_urls:
            seen_urls.add(u)
            deduped.append(a)
    all_articles = deduped
    print(f"[UAE Rhetoric] Articles after dedup: {len(all_articles)}")

    # ── Classify articles by actor ──
    articles_by_actor = {actor_id: [] for actor_id in ACTORS.keys()}
    for art in all_articles:
        matches = _classify_article_actor(art)
        for actor_id, hit_count in matches:
            art_copy = dict(art)
            art_copy['_actor_hits'] = hit_count
            articles_by_actor[actor_id].append(art_copy)

    # ── Score each actor ──
    actor_summaries = {}
    actor_levels = {}
    tripwires_global = []
    for actor_id, actor_data in ACTORS.items():
        scored = _score_actor_articles(articles_by_actor[actor_id], actor_id)
        baseline = actor_data['baseline_statements_per_week']
        level = actor_alert_level(scored['score'], baseline)
        actor_levels[actor_id] = level

        actor_summaries[actor_id] = {
            'name':         actor_data['name'],
            'flag':         actor_data['flag'],
            'icon':         actor_data['icon'],
            'color':        actor_data['color'],
            'role':         actor_data['role'],
            'description':  actor_data['description'],
            'vector':       actor_data['vector'],
            'score':        scored['score'],
            'level':        level,
            'baseline':     baseline,
            'article_count':       scored['article_count'],
            'language_breakdown':  scored['language_breakdown'],
            'sources':             scored['sources'],
            'top_articles':        scored['top_articles'],
            'tripwires':           scored['tripwires'],
        }
        for tw in scored['tripwires']:
            tripwires_global.append({'actor': actor_id, **tw})

    # ── Compute 4-vector composite scores ──
    vector_scores = {}
    vector_levels = {}
    for vector_id, member_actors in VECTOR_GROUPS.items():
        total = sum(actor_summaries[a]['score'] for a in member_actors if a in actor_summaries)
        vector_scores[vector_id] = round(total, 2)
        # Level for vector = max actor level in vector
        levels_seen = [actor_summaries[a]['level'] for a in member_actors if a in actor_summaries]
        order = ['low', 'normal', 'elevated', 'high', 'surge']
        if levels_seen:
            vector_levels[vector_id] = max(levels_seen, key=lambda lv: order.index(lv))
        else:
            vector_levels[vector_id] = 'low'

    # ── Read cross-tracker context ──
    commodity_pressure = _read_commodity_pressure_for_uae()
    # Attach the composite pressure story under a reserved key -- consumers
    # iterating per-commodity fingerprints skip underscore-prefixed keys.
    _story = _read_commodity_pressure_story_for_uae()
    if _story:
        commodity_pressure['_pressure_story'] = _story
    crosstheater_amplifiers = _read_crosstheater_amplifiers()

    # ── Write UAE fingerprints for downstream consumers ──
    _write_uae_fingerprints(actor_levels, vector_scores, tripwires_global)

    # ── Compute composite UAE pressure score ──
    composite_score = round(sum(vector_scores.values()), 2)

    # (No disaster-sensor cross-read: GCC trackers are market/energy-sensored by design.)
    disaster_state = {}
    composite_level = max(
        (actor_summaries[a]['level'] for a in actor_summaries),
        key=lambda lv: ['low', 'normal', 'elevated', 'high', 'surge'].index(lv),
        default='low',
    )

    # ── Build executive summary + so-what + top signals via interpreter ──
    if UAE_INTERPRETER_AVAILABLE:
        try:
            top_signals = build_top_signals(actor_summaries, tripwires_global,
                                             commodity_pressure, crosstheater_amplifiers)
            executive_summary = build_executive_summary(actor_summaries, vector_scores,
                                                       vector_levels, tripwires_global)
            alignment_drift = score_alignment_drift(actor_summaries, tripwires_global,
                                                    commodity_pressure, crosstheater_amplifiers,
                                                    country='uae')
            so_what = build_so_what_factor(actor_summaries, vector_scores, vector_levels,
                                           tripwires_global, commodity_pressure,
                                           alignment_drift=alignment_drift)
            # Sensor + contested-node signals fire on BOTH paths (Jul 2026):
            # the interpreter owns prose; the tracker owns its cross-reads.
            try:
                _extra, _, _ = _builtin_fallback_signals(
                    composite_score, composite_level, vector_scores, vector_levels,
                    actor_summaries, [], disaster_state)
                _have = {s.get('type') for s in top_signals if isinstance(s, dict)}
                for _sig in _extra:
                    if _sig.get('type') in ('natural_disaster_strain', 'contested_node') \
                            and _sig.get('type') not in _have:
                        top_signals.append(_sig)
            except Exception as _e:
                print(f'[UAE Rhetoric] cross-read append error: {str(_e)[:100]}')
            election_watch = None   # N/A -- the Emirate rules by decree; no electoral cycle to watch
        except Exception as e:
            print(f"[UAE Rhetoric] Interpreter error: {str(e)[:200]}")
            traceback.print_exc()
            top_signals, executive_summary, so_what = _builtin_fallback_signals(
            composite_score, composite_level, vector_scores, vector_levels,
            actor_summaries, tripwires_global, disaster_state)
            election_watch = None
            alignment_drift = None
    else:
        top_signals, executive_summary, so_what = _builtin_fallback_signals(
            composite_score, composite_level, vector_scores, vector_levels,
            actor_summaries, tripwires_global, disaster_state)
        election_watch = None
        alignment_drift = None

    # ── Alignment-drift convergence signal (BRI inroad read) -> WHA BLUF / GPI ──
    if UAE_INTERPRETER_AVAILABLE and alignment_drift:
        _drift_sig = build_alignment_drift_top_signal(alignment_drift)
        if _drift_sig and not any(s.get('category') == 'alignment_drift' for s in top_signals):
            top_signals = [_drift_sig] + list(top_signals)


    # ── BLUF compatibility shim ──
    # wha_regional_bluf.py's _normalize_tracker_data() expects an integer
    # theatre_level (0-5) and a 0-100 theatre_score. UAE emits a
    # categorical composite_level + a free-running composite_score; map
    # them so the regional BLUF can ingest UAE cleanly alongside Cuba.
    LEVEL_TO_THEATRE_INT = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
    raw_theatre_level = LEVEL_TO_THEATRE_INT.get(composite_level, 0)
    # Cap theatre_score at 100 — composite_score is unbounded by design
    theatre_score = min(100, int(composite_score))

    # ── L5 RESERVATION CONTRACT (v1.0.0 May 21 2026) ──
    # Compute L5 gate; cap theatre_level at L4 if raw is L5 but gate didn't fire.
    # UAE scaffolds today — no severity-5 tripwires yet. Gate is silent until
    # weekend audit adds real L5-class triggers per axis.
    l5_gate = _compute_uae_l5_gate(tripwires_global, actor_summaries, vector_scores)
    if raw_theatre_level >= 5 and not l5_gate['any']:
        theatre_level = 4
        l5_capped = True
        print(f"[UAE Rhetoric] L5 gate enforced: raw={raw_theatre_level} capped at L4 "
              f"(reason: {l5_gate['reason']})")
    else:
        theatre_level = raw_theatre_level
        l5_capped = False

    # ── Build label + signal text for BLUF consumption ──
    label_map_uae = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning',
                      3: 'Direct Threat', 4: 'Coercion', 5: 'Active Crisis'}
    theatre_label = label_map_uae.get(theatre_level, 'Monitoring')

    signal_text = _build_uae_signal_text(
        theatre_level, theatre_score, vector_levels, actor_summaries, l5_capped,
    )

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success':               True,
        'country':               'uae',
        'composite_score':       composite_score,
        'composite_level':       composite_level,
        # BLUF compatibility shim — see definitions above
        'theatre_level':         theatre_level,
        'theatre_score':         theatre_score,

        # ── L5 Reservation Contract fields (v1.0.0 May 21 2026) ──
        'theatre_label':         theatre_label,
        'signal_text_short':     signal_text['short'],
        'signal_text_long':      signal_text['long'],
        'l5_gate':               l5_gate,
        'raw_theatre_level':     raw_theatre_level,
        'l5_capped':             l5_capped,
        'source_class':          'contested_node',  # four-wheel contested node (AZ schema)
        'vector_scores':         vector_scores,
        'vector_levels':         vector_levels,
        'actor_summaries':       actor_summaries,
        'tripwires_global':      tripwires_global,
        'commodity_pressure':    commodity_pressure,
        'crosstheater_amplifiers': crosstheater_amplifiers,
        'top_signals':           top_signals,
        'executive_summary':     executive_summary,
        'so_what':               so_what,
        'alignment_drift':       alignment_drift,
        'source_breakdown': {
            'rss':     len(rss_articles),
            'gdelt':   len(gdelt_articles),
            'newsapi': len(newsapi_articles),
            'brave':   len(brave_articles),
        },
        'total_articles_scanned': len(all_articles),
        'scan_time_seconds':      scan_time,
        'days_analyzed':          days,
        'last_updated':           datetime.now(timezone.utc).isoformat(),
        'cached':                 False,
        'version':                '1.0.0',
    }

    save_cache(result)

    # ── Canonical history snapshot (May 22 2026 reconciled schema) ──
    # Universal fields read by wha_regional_bluf.prose_v2:
    #   theatre_level, theatre_score, scanned_at, red_lines_count
    # Plus UAE-specific vector levels.
    try:
        _redis_lpush_trim(HISTORY_KEY, {
            'theatre_level':       theatre_level,
            'theatre_score':       theatre_score,
            'scanned_at':          result.get('last_updated') or datetime.now(timezone.utc).isoformat(),
            'red_lines_count':     len(tripwires_global),
            'kinetic_afpak':       vector_levels.get('kinetic_afpak'),
            'repression_rights':   vector_levels.get('repression_rights'),
            'external_friction':   vector_levels.get('external_friction'),
            'illicit_economy':     vector_levels.get('illicit_economy'),
        }, max_len=336)
    except Exception as e:
        print(f"[UAE Rhetoric] History snapshot write failed: {e}")

    print(f"[UAE Rhetoric] ✅ Scan complete in {scan_time}s — composite {composite_level} ({composite_score})")
    return result


# ============================================
# BACKGROUND REFRESH LOOP
# ============================================
def _background_refresh_loop():
    """Periodic refresh — initial 90s delay, then every BACKGROUND_REFRESH_HOURS."""
    global _background_scan_running
    time.sleep(INITIAL_SCAN_DELAY_SECONDS)
    while True:
        try:
            with _background_scan_lock:
                if _background_scan_running:
                    time.sleep(60)
                    continue
                _background_scan_running = True
            try:
                print("[UAE Rhetoric] Background refresh starting...")
                scan_uae_rhetoric(force=True, days=7)
                print("[UAE Rhetoric] Background refresh complete.")
            finally:
                with _background_scan_lock:
                    _background_scan_running = False
            time.sleep(BACKGROUND_REFRESH_HOURS * 3600)
        except Exception as e:
            print(f"[UAE Rhetoric] Background loop error: {e}")
            time.sleep(600)


def _start_background_refresh():
    t = threading.Thread(target=_background_refresh_loop, daemon=True, name='UaeRhetoricBG')
    t.start()
    print(f"[UAE Rhetoric] Background refresh thread started (initial delay {INITIAL_SCAN_DELAY_SECONDS}s)")


# ============================================
# FLASK ENDPOINTS
# ============================================
def register_uae_rhetoric_routes(app, start_background=True):
    """Register UAE rhetoric endpoints on a Flask app + start background refresh."""
    from flask import jsonify, request

    @app.route('/api/rhetoric/uae', methods=['GET', 'OPTIONS'])
    def api_uae_rhetoric():
        if request.method == 'OPTIONS':
            return ('', 204)
        force = request.args.get('refresh', '').lower() in ('true', '1', 'yes')

        cached = load_cache()
        if cached and is_cache_fresh(cached) and not force:
            cached['cached'] = True
            return jsonify(cached)

        # Cache miss or force refresh — return cached (if any) and trigger background scan
        if cached and not force:
            cached['cached'] = True
            cached['stale'] = True
            # Trigger background scan if not already running
            with _background_scan_lock:
                if not _background_scan_running:
                    threading.Thread(
                        target=lambda: scan_uae_rhetoric(force=True, days=7),
                        daemon=True,
                    ).start()
            return jsonify(cached)

        # No cache at all — do synchronous scan (slow!)
        result = scan_uae_rhetoric(force=force, days=7)
        return jsonify(result)

    @app.route('/api/rhetoric/uae/debug', methods=['GET'])
    def api_uae_rhetoric_debug():
        """Diagnostic — config snapshot + cache freshness."""
        cached = load_cache()
        return jsonify({
            'version':                  '1.0.0',
            'actor_count':              len(ACTORS),
            'actors':                   list(ACTORS.keys()),
            'vector_count':             len(VECTOR_GROUPS),
            'vectors':                  list(VECTOR_GROUPS.keys()),
            'rss_feeds':                len(RSS_FEEDS),
            'gdelt_queries_en':         len(GDELT_QUERIES_EN),
            'gdelt_queries_es':         len(GDELT_QUERIES_ES),
            'tripwires':                len(TRIPWIRES),
            'redis_configured':         bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured':       bool(NEWSAPI_KEY),
            'brave_configured':         bool(BRAVE_API_KEY),
            'commodity_fingerprint':    COMMODITY_FINGERPRINT_AVAILABLE,
            'interpreter_available':    UAE_INTERPRETER_AVAILABLE,
            'cache_present':            cached is not None,
            'cache_fresh':              is_cache_fresh(cached) if cached else False,
            'cache_age_hours':          None if not cached else round(
                (datetime.now(timezone.utc) - datetime.fromisoformat(cached.get('cached_at', '2020-01-01T00:00:00+00:00'))).total_seconds() / 3600, 2
            ) if cached.get('cached_at') else None,
            'last_scan_started_at':     _last_scan_started_at.isoformat() if _last_scan_started_at else None,
            'background_running':       _background_scan_running,
        })

    print("[UAE Rhetoric] ✅ Endpoints registered:")
    print("  GET  /api/rhetoric/uae")
    print("  GET  /api/rhetoric/uae/debug")

    if start_background:
        _start_background_refresh()
    else:
        print("[UAE Rhetoric] ℹ️ Background refresh disabled on this instance")


print("[UAE Rhetoric] Module loaded.")
