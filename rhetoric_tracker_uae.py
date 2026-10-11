"""
rhetoric_tracker_uae.py -- Asifah Analytics ME Backend -- v2.0.0 Oct 11 2026
  (v1.0.0 Jul 2026. v2.0.0 = residue purge + live L5 gate + PURCHASING RIM.)

WHICH BACKEND READS THIS: me_regional_bluf.py. TRACKER_KEYS carries
  'uae': ('rhetoric:uae:latest', None)
and _read_history_snapshot() reads rhetoric:uae:history for its up/down/steady
read. Every comment in v1.0.0 naming the WHA backend, commodity_proxy_wha, or
wha_regional_bluf.prose_v2 was clone residue from the Peru/Cuba build and has
been corrected. A comment is evidence about the past; a log is evidence about
now -- and these comments were evidence about a different country.

NEW IN v2.0.0 -- THE PURCHASING RIM (the UAE mini-spoke)
  The UAE is the platform's first COMMERCIAL hub. Russia projects with troops,
  Turkey with drones and basing, China with debt. The UAE projects with
  PURCHASE: it is the buyer of last resort for production whose other buyers
  have walked away. Burkina after the coups, Sudan through a war economy.
  THE QUESTION: when a state loses its other buyers, how completely does the
  UAE become the only one -- and is that happening in several places at once?
  This block is a READER. Country trackers own their own gold numbers; the rim
  aggregates what they already write. One writer per leg.
  CONVERGENCE IS NOT LIT-COUNT: two lit spokes are two trade relationships.
  The finding is two spokes where the UAE is the DOMINANT counterparty.

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

# Cross-tracker commodity fingerprints.
# v2.0.0 CORRECTION: this tracker and commodity_tracker.py BOTH live on the ME
# backend. The v1.0.0 comment here described the WHA topology it was cloned
# from and sent every future reader looking for a commodity_proxy_wha.py that
# this backend does not have. The call below is an in-process hit on the ME
# backend's own /api/commodity-pressure/<country> route.
ME_BACKEND_SELF_URL = os.environ.get(
    'ME_BACKEND_SELF_URL',
    'http://localhost:10000'  # default Render port for in-process calls
)
COMMODITY_FINGERPRINT_AVAILABLE = True  # always — we use HTTP proxy, not import

# ── Shared spoke-and-wheel reader (v1.5.0+) ─────────────────────────
# Byte-identical on every backend -- library code, not proxied data. Supplies
# the UAE's own rim: read_wheel('uae') returns every spoke feeding this hub.
# Optional: absent file = no rim, tracker still scans.
try:
    from spoke_wheel_reader import read_wheel as _read_wheel
    WHEEL_READER_AVAILABLE = True
except ImportError:
    WHEEL_READER_AVAILABLE = False
    print("[UAE Rhetoric] spoke_wheel_reader unavailable -- purchasing rim disabled")

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

# ONE version string, read by the payload and the debug route. Three
# hand-maintained copies is how a module spends weeks reporting one version
# in /debug while the payload claims another.
MODULE_VERSION = '2.0.0'

CACHE_TTL_HOURS                = 12
BACKGROUND_REFRESH_HOURS       = 12
INITIAL_SCAN_DELAY_SECONDS     = 90
CROSSTHEATER_FINGERPRINT_TTL_HOURS = 13   # 12h refresh + 1h buffer

REDIS_KEY_LATEST       = 'rhetoric:uae:latest'
HISTORY_KEY            = 'rhetoric:uae:history'
# ^ LIVE CONSUMER: me_regional_bluf._read_history_snapshot() -> _compute_direction(),
#   which produces the up/down/steady read. The v1.0.0 comment credited
#   wha_regional_bluf.prose_v2, which does not read this key. The three
#   universal field names written into it (theatre_level, theatre_score,
#   scanned_at) MUST keep their spelling -- something live reads them.
# v2.0.0: three fingerprint-key constants removed here. They were
# 'rhetoric:uae:china_axis_active', 'rhetoric:uae:chancay_pressure' and
# 'rhetoric:uae:mining_disruption' -- Chancay is a PERUVIAN port. All three
# were declared and never read or written by any line in this file.

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
# ── L5 CAPABILITY (v2.0.0) ──────────────────────────────────────────────
# A tripwire can promote the theatre to L5 ONLY if it is BOTH severity
# 'surge' AND carries an 'l5_axis'. Severity alone is not enough: L5 is
# ACTIVE CRISIS, and a high-tempo news week is not active crisis.
#
# TODAY ONLY THE KINETIC AXIS HAS A TRIGGER. The economic, humanitarian and
# diplomatic axes have no L5-class tripwire in this file, and this comment
# says so rather than letting a reader assume four live axes. The honest
# economic candidate is a dirham-peg event; it is NOT added here because no
# keyword list for it has been validated against published headlines, and an
# unvalidated L5 trigger is worse than a missing one.
TRIPWIRES = {
    'homeland_attack': {
        'patterns': ['abu dhabi attacked','dubai attacked','missiles abu dhabi','drone strike dubai',
                     'attack on uae soil','strikes uae territory'],
        'severity': 'surge',
        'l5_axis': 'kinetic',
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
        'l5_axis': 'kinetic',
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
# v2.0.0: renamed from GDELT_QUERIES_ES. These are ARABIC queries fetched with
# sourcelang:ara; 'ES' was Spanish-language residue from the Peru clone.
GDELT_QUERIES_AR = [
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
    # Scheme guard (learned on the Africa backend, Jul 23 2026): if the env var
    # ever holds a redis:// connection string instead of the https REST
    # endpoint, requests.post raises before reaching Upstash and EVERY write
    # silently returns False. Fail loudly instead of writing nothing quietly.
    if not UPSTASH_REDIS_URL.startswith('http'):
        print("[UAE Rhetoric] Redis SET ABORT -- UPSTASH_REDIS_URL is not an "
              "https REST URL (starts with '%s...')" % UPSTASH_REDIS_URL[:10])
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
    Canonical helper added May 22 2026 — mirrors the Cuba pattern. The list it
    maintains is read by me_regional_bluf._read_history_snapshot(), NOT by
    wha_regional_bluf.prose_v2 as v1.0.0 claimed.
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
    for q in GDELT_QUERIES_AR:
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
    for all matching actors. Multi-actor matching is allowed -- an "Israel and the
    UAE sign air-defence deal" headline legitimately hits both israel_uae_axis and
    uae_mod_airdefense.

    (v1.0.0's example here was "Boluarte visits Las Bambas" -- Peruvian politics,
    in a UAE tracker, describing actors that do not exist in this file.)
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
    from this backend's own commodity route (ME backend, in-process).

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
    Read the composite pressure STORY from this backend's commodity route
    (/api/commodity-pressure/uae, ME backend). This is the SAME payload the UAE stability
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
    ME BLUF always have something honest to render. Estimative voice only."""
    sigs = []
    # tripwire hits first
    for tw in (tripwires_global or [])[:3]:
        name = tw.get('tripwire', tw.get('id', 'tripwire')) if isinstance(tw, dict) else str(tw)
        sev  = tw.get('severity', 'high') if isinstance(tw, dict) else 'high'
        sigs.append({'level': sev, 'type': 'tripwire', 'priority': 10,
                     'category': 'tripwire', 'theatre': 'uae',
                     'pressure_type': 'kinetic',
                     'short_text': f"\U0001f1e6\U0001f1ea UAE tripwire: {str(name).replace('_',' ')}",
                     'long_text':  f"UAE tripwire fired: {str(name).replace('_',' ')} -- "
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
                         'short_text': f"\U0001f1e6\U0001f1ea {akey.replace('_',' ').title()} at {lvl.upper()}",
                         'long_text':  f"UAE actor {ACTORS.get(akey, {}).get('name', akey)} scanning at {lvl} -- "
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
        'kinetic_inbound': "Kinetic-inbound at {lvl}. What it means: intercept/threat tempo at this level reads against the Jan 2022 Abu Dhabi precedent -- strikes on UAE soil historically reprice aviation routings, tourism-sector risk, and war-risk premiums at Fujairah within days. Who feels it: Gulf carriers, hull insurers, Dubai's services economy. Confirmation gauges: air-defense activation reporting, Fujairah anchorage advisories, the DFM/ADX tiles.",
        'israel_axis': "Israel-axis at {lvl}. What it means: defense-cooperation tempo (the EDGE-Rafael channel, air-defense transfers, training) at this level is the Accords-goes-kinetic story deepening -- it integrates Gulf air defense with Israeli systems and reprices the regional deterrence read against Iran. Who feels it: Tehran's targeting calculus, Gulf procurement pipelines, the normalization file region-wide. Confirmation gauges: deal announcements, joint-exercise reporting, the MIL tracker's israel_uae_defense amplifier.",
        'iran_dual': "Iran dual-track at {lvl}. What it means: this spoke carries friction and lifeline simultaneously -- the analyst question is WHICH track drives the tempo. Lifeline holding (Dubai trade, flights, diaspora finance) while kinetics spike has historically read as contained; commercial rupture alongside kinetic escalation is the confirmation-via-commerce pattern that precedes broader break. Who feels it: Dubai's re-export economy, Iranian consumer markets, sanctions desks. Confirmation gauges: flight-schedule signals, trade-volume reporting, divergence between kinetic and commercial story counts.",
        'economic_hub': "Economic-hub at {lvl}. What it means: Jebel Ali is the region's largest port on a DP World network spanning six continents -- disruption signals here transmit into global logistics costs, not just Gulf ones. War-risk premiums on UAE port calls are the fastest repricing channel; DMCC gold flows double as sanctions-pressure weather. Who feels it: global shippers, gold markets, ADNOC crude buyers. Confirmation gauges: war-risk premium reporting, Jebel Ali operations statements, the Gold x Transit Hub card.",
    }
    for _vec, _lvl in (vector_levels or {}).items():
        if _lvl in _esc and _vec in _sw:
            so_what.append({'weight': 0.9, 'bullet': _sw[_vec].format(lvl=str(_lvl).upper())})
    if not so_what:
        so_what.append({'weight': 0.3, 'bullet':
            "All four vectors at baseline this scan. Baseline for the aligned hub still means both Iran tracks running simultaneously -- friction and lifeline -- and the Israel defense axis compounding quietly. Divergence between kinetic and commercial rhetoric remains the standing tell."})
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
        # v2.0.0: 'country' added. spoke_wheel_reader._infer_hubs_from_payload
        # discards a payload's own name so a hub cannot become its own spoke.
        # It read 'country'; this payload only wrote 'theatre', so once 'uae'
        # joined _KNOWN_HUBS the dp_world_ports field below would have made the
        # UAE a spoke of itself. The reader was hardened too -- belt and braces,
        # because this is the kind of bug that returns.
        'country':         'uae',
        'node_class':      'aligned_hub',
        'hub_presence':    hub_presence,
        'slices_active':   slices_active,
        'israel_axis':     vector_scores.get('israel_axis', 0),
        'iran_dual':       vector_scores.get('iran_dual', 0),
        'kinetic_inbound': vector_scores.get('kinetic_inbound', 0),
        'tripwires':       tripwires_global[:5] if isinstance(tripwires_global, list) else [],
    }
    _redis_set('crosstheater:uae:fingerprint', slice_payload,
               ttl_hours=CROSSTHEATER_FINGERPRINT_TTL_HOURS)
    print(f"[UAE Rhetoric] Crosstheater slice written -- slices_active={slices_active}")

def _compute_uae_l5_gate(tripwires_global, actor_summaries=None, vector_scores=None):
    """L5 is ACTIVE CRISIS. Fires only on a surge tripwire carrying an l5_axis.

    v1.0.0 WAS DEAD TWICE OVER and this is worth recording, because the same
    shape is easy to rebuild:
      (a) all four axis flags were hardcoded False and nothing ever set them;
      (b) LEVEL_TO_THEATRE_INT capped 'surge' at 4, so the `raw >= 5` branch
          that consumed the gate was unreachable even if (a) were fixed.
    Either alone kills it. Together they made the gate decoration -- it
    printed a reason string every scan and could never change an outcome.

    v2.0.0 reads TRIPWIRES[...]['l5_axis'] and the caller promotes L4 -> L5
    when the gate fires, which is how the Burkina tracker does it.

    Returns axis flags + reason. Never raises.
    """
    gate = {'kinetic': False, 'humanitarian': False, 'economic': False,
            'diplomatic': False, 'any': False, 'reason': '', 'fired': []}
    reasons = []
    for entry in (tripwires_global or []):
        tw_id = entry.get('id') if isinstance(entry, dict) else str(entry)
        tw_def = TRIPWIRES.get(tw_id) or {}
        axis = tw_def.get('l5_axis')
        if not axis or tw_def.get('severity') != 'surge':
            continue
        gate[axis] = True
        gate['fired'].append({'tripwire': tw_id, 'axis': axis})
        reasons.append('%s -> %s' % (tw_id, axis))
    gate['any'] = any(gate[k] for k in ('kinetic', 'humanitarian',
                                        'economic', 'diplomatic'))
    gate['reason'] = ('; '.join(reasons) if reasons else
                      'No L5 axis trigger fired. L5 is reserved for a sustained '
                      'campaign on Abu Dhabi/Dubai or a Barakah strike. Only the '
                      'kinetic axis currently carries an L5 trigger; economic, '
                      'humanitarian and diplomatic are UNINSTRUMENTED, not quiet.')
    gate['axes_instrumented'] = sorted({
        d.get('l5_axis') for d in TRIPWIRES.values()
        if d.get('l5_axis') and d.get('severity') == 'surge'})
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

    short = f"🇦🇪 UAE L{theatre_level} {label} — {vectors_brief}"
    if len(short) > 120:
        short = short[:117] + '...'

    long_parts = [f"🇦🇪 UAE at L{theatre_level} {label} (theatre score {theatre_score}/100)."]
    if vectors_active:
        long_parts.append(f"Active vectors: {vectors_brief}.")
    if actors_active:
        long_parts.append(f"Top actors: {actors_brief}.")
    if l5_capped:
        long_parts.append("L5 axis gate did not fire — capped at L4 ceiling per platform L5 Reservation Contract.")
    else:
        # v2.0.0: v1.0.0 described "four mixed-polarity wheels (Iran friction,
        # Pakistan kinetic, Russia normalization, China extraction)" -- none of
        # which this tracker measures. It has no Pakistan actor, no Russia
        # actor and no China actor. Replaced with what the eight actors and
        # four vectors in this file actually read.
        long_parts.append("UAE is an ALIGNED HUB: a forward-leaning Israel axis, a "
                          "DUAL-POLARITY Iran spoke carrying friction and commercial "
                          "lifeline at once, and a purchasing rim reaching into "
                          "Africa. Divergence between the kinetic and commercial "
                          "tracks is the standing tell.")

    return {'short': short, 'long': ' '.join(long_parts)}


# ════════════════════════════════════════════════════════════
# THE PURCHASING RIM  (v2.0.0 -- the UAE mini-spoke)
#
# THE QUESTION: when a state loses its other buyers, how completely does the
# UAE become the only one -- and is that happening in several places at once?
#
# A single spoke cannot answer that. Burkina knows the UAE is its dominant
# gold counterparty; Sudan knows the UAE is a party to its war; neither knows
# the other exists. Only the rim can see a pattern across them.
#
# THIS IS A READER, NOT A SCANNER. The country trackers own their own gold
# numbers and their own commercial axes. Re-deriving them here would make two
# writers for one fact, which is how numbers drift apart quietly. One writer
# per leg; the hub reads.
# ════════════════════════════════════════════════════════════
AXIS_STATES = ('capture', 'refusal', 'unread')
RIM_CONVERGENCE_MIN = 2   # dominant counterparty in N countries = a position


def _rim_note(r):
    """Absence-honest prose for the rim. Says which KIND of nothing, and names
    the falsifier whenever one is present."""
    if r['reporting'] == 0:
        return ('No UAE spoke is reporting this cycle. The rim is SILENT, not '
                'quiet -- %d of %d spokes carry no UAE sensor, which is a '
                'coverage gap rather than a finding about UAE purchasing.'
                % (r['not_reporting'], r['rim_instrumented']))
    parts = []
    dom = sorted(r['sole_counterparty'])
    if r['converged']:
        parts.append(
            'The UAE is the dominant commercial counterparty in %d countries at '
            'once (%s). One country is a trade relationship; %d is a purchasing '
            'position. CONVERGENCE indicator, NOT a probability of action.'
            % (len(dom), ', '.join(dom), len(dom)))
    elif len(dom) == 1:
        parts.append(
            'The UAE is the dominant counterparty in one country (%s). A single '
            'dominant leg is commerce; convergence fires only when the same '
            'dominance appears in two or more at once.' % dom[0])
    else:
        parts.append('No spoke on this rim reports the UAE as its dominant '
                     'commercial counterparty this cycle.')
    # THE FALSIFIER. A rim that can only report capture can only confirm itself.
    if r['refusals']:
        parts.append(
            'REFUSAL registered in %s. Refusal is this axis\'s falsifier: if a '
            'state refuses UAE terms and no pressure follows, the leverage read '
            'is WEAK and should be reported as weak. Refusal is not low capture.'
            % ', '.join(sorted(r['refusals'])))
    if r['axis_instrumented'] < r['reporting']:
        parts.append(
            'Commercial axis instrumented on %d of %d reporting spokes; the rest '
            'carry a UAE presence reading but no capture/refusal sensor, so they '
            'are absent from the state mix rather than counted as unread.'
            % (r['axis_instrumented'], r['reporting']))
    if r['no_hub_block']:
        parts.append(
            '%d spoke(s) run a live tracker with no UAE sensor at all -- a '
            'missing vector, not a missing tracker. Build to-do, not a quiet '
            'theatre.' % r['no_hub_block'])
    if r['span'] >= 2:
        parts.append('Rim lit across %d regions -- breadth beyond a single '
                     'neighbourhood.' % r['span'])
    return ' '.join(parts)


def _default_spoke_axis_reader(country):
    """Read a spoke's OWN commercial-axis call from its crosstheater fingerprint.

    This is the half that keeps the rim a reader rather than a second scanner.
    Burkina computes capture/refusal/unread with its own country-gated corpus
    and publishes the verdict; we read the verdict. If this function ever
    starts DERIVING a state instead of reading one, there are two writers for
    one fact and they will drift.

    Returns {'state': <axis state>, 'dominant': bool} or None when that spoke
    carries no commercial axis -- which is NOT the same as reading 'unread' on
    an axis that exists, and the rim counts them separately.
    """
    fp = _redis_get('crosstheater:%s:fingerprint' % country)
    if not isinstance(fp, dict):
        return None
    sub_block = fp.get('uae_spoke') if isinstance(fp.get('uae_spoke'), dict) else {}
    state = sub_block.get('axis_state') or fp.get('commercial_axis_state')
    if state not in AXIS_STATES:
        return None            # no axis here -- uninstrumented, not calm
    dominant = sub_block.get('uae_dominant')
    if dominant is None:
        # Fall back to the spoke's own dominance flag. Burkina's
        # dominant_actor_on_wheel went True on 11 Oct 2026 when this hub
        # shipped; before that it meant the opposite, so a stale fingerprint
        # written by an older tracker is read conservatively as not-dominant.
        dominant = bool(sub_block) and bool(fp.get('dominant_actor_on_wheel'))
    return {'state': state, 'dominant': bool(dominant)}


def build_purchasing_rim(spoke_axis_reader=None, _wheel_fn=None):
    """Hub-side read of the UAE rim. Never raises.

    spoke_axis_reader -- optional callable(country) -> {'state': <axis state>,
                         'dominant': bool} or None when that spoke carries no
                         commercial axis. Injected so the rim never recomputes
                         a number a country tracker already owns.
    """
    out = {
        'schema': 'uae_purchasing_rim v1.0.0',
        'readable': False, 'converged': False,
        'rim_instrumented': 0, 'reporting': 0,
        'lit': 0, 'dark': 0, 'not_reporting': 0,
        'no_hub_block': 0, 'absent': 0, 'axis_instrumented': 0,
        'state_mix': {st: 0 for st in AXIS_STATES},
        'sole_counterparty': [], 'refusals': [],
        'depth': 0, 'depth_region': '', 'span': 0,
        'spokes': [], 'note': '',
    }
    wheel_fn = _wheel_fn or (_read_wheel if WHEEL_READER_AVAILABLE else None)
    if wheel_fn is None:
        out['note'] = ('spoke_wheel_reader not deployed on this backend -- the '
                       'UAE rim is UNREAD this cycle. No inference about '
                       'purchasing reach should be drawn from an empty panel.')
        return out
    try:
        w = wheel_fn('uae')
    except Exception as e:
        out['note'] = ('UAE rim unreadable this cycle (%s). This is an OUTAGE, '
                       'not an empty rim.' % str(e)[:90])
        return out
    if not w.get('readable'):
        out['note'] = w.get('note') or 'UAE rim unreadable this cycle.'
        return out

    out['readable'] = True
    spokes = w.get('spokes') or []
    out['rim_instrumented'] = len(spokes)
    for sp in spokes:
        st = sp.get('state')
        if st == 'lit':
            out['lit'] += 1
        elif st == 'dark':
            out['dark'] += 1
        else:
            out['not_reporting'] += 1
            # Two different build to-dos: no tracker at all, versus a live
            # tracker with no UAE vector. They must not look alike.
            if sp.get('reason') == 'no_hub_block':
                out['no_hub_block'] += 1
            else:
                out['absent'] += 1
        rec = {
            'country': sp.get('country'), 'display': sp.get('display'),
            'region': sp.get('region'), 'node_class': sp.get('node_class'),
            'level': sp.get('level', 0), 'state': st,
            'reason': sp.get('reason', ''), 'source': sp.get('source', ''),
            'trajectory': sp.get('trajectory'),
            'top_signal': sp.get('top_signal', ''),
            'axis_state': None, 'uae_dominant': None,
        }
        if spoke_axis_reader and st != 'not_reporting':
            try:
                axis = spoke_axis_reader(sp.get('country'))
            except Exception:
                axis = None
            if axis:
                state = axis.get('state')
                if state in AXIS_STATES:
                    rec['axis_state'] = state
                    out['state_mix'][state] += 1
                    out['axis_instrumented'] += 1
                rec['uae_dominant'] = bool(axis.get('dominant'))
                if rec['uae_dominant']:
                    out['sole_counterparty'].append(sp.get('country'))
                if state == 'refusal':
                    out['refusals'].append(sp.get('country'))
        out['spokes'].append(rec)

    out['reporting'] = out['lit'] + out['dark']
    b = w.get('breadth') or {}
    out['depth'] = b.get('depth', 0)
    out['depth_region'] = b.get('depth_region', '')
    out['span'] = b.get('span', 0)
    # Convergence is DOMINANCE in N places, not lit-count. Being one buyer of
    # five is commerce; being the only buyer is leverage.
    out['converged'] = len(out['sole_counterparty']) >= RIM_CONVERGENCE_MIN
    out['note'] = _rim_note(out)
    return out


def build_rim_top_signal(rim):
    """A top_signal for the rim, or None when there is nothing to report.

    The interpreter CANNOT produce this one: it never sees the rim. So the
    hub owns it, the same way Burkina's tracker owns its commercial-axis
    signal.

    CALM GUARD, and it is load-bearing. The UAE interpreter shipped with a
    guard that could never return None because it tested for a band name that
    was not in its own band table -- so it broadcast a signal every single
    cycle, including dead-calm ones, and the BLUF could not tell a finding
    from a heartbeat. The assertion below makes that failure impossible to
    reintroduce silently: if the states this guard tests ever stop being real
    states, the module refuses to load instead of going quietly chatty.
    """
    if not rim or not rim.get('readable'):
        return None
    dom = sorted(rim.get('sole_counterparty') or [])
    refusals = sorted(rim.get('refusals') or [])
    if not rim.get('converged') and not refusals:
        return None          # genuinely nothing to say -- stay quiet

    if rim.get('converged'):
        return {
            'level': 'high', 'type': 'purchasing_rim', 'priority': 12,
            'category': 'commercial_capture', 'theatre': 'uae',
            'pressure_type': 'economic',
            'short_text': ('\U0001F1E6\U0001F1EA UAE: dominant counterparty in %d '
                           'countries at once (%s)' % (len(dom), ', '.join(dom))),
            'long_text': (
                'UAE PURCHASING RIM -- the UAE is the dominant commercial '
                'counterparty in %s simultaneously. One country is a trade '
                'relationship; several at once is a purchasing position, and it '
                'is a position built on sellers who have run out of alternative '
                'buyers. This is a DIRECTIONAL read on leverage, not a volume '
                'read: dominance is the variable, tonnage is not. %s'
                'CONVERGENCE indicator, NOT a probability of action.'
                % (', '.join(dom),
                   ('A REFUSAL is also registered (%s), which cuts the other way '
                    'and should be read as weakening the leverage case. '
                    % ', '.join(refusals)) if refusals else '')),
        }
    # Refusal with no convergence is still a finding -- the falsifier firing
    # on its own is evidence AGAINST the leverage read, and suppressing it
    # would leave a rim that can only ever confirm itself.
    return {
        'level': 'elevated', 'type': 'purchasing_rim', 'priority': 8,
        'category': 'commercial_refusal', 'theatre': 'uae',
        'pressure_type': 'economic',
        'short_text': ('\U0001F1E6\U0001F1EA UAE: purchasing terms REFUSED in %s'
                       % ', '.join(refusals)),
        'long_text': (
            'UAE PURCHASING RIM -- refusal registered in %s with no offsetting '
            'dominance elsewhere on the rim this cycle. Refusal is this axis\'s '
            'falsifier: a state declining UAE terms with no consequence is '
            'evidence that the purchasing leverage read is WEAK. Reported '
            'because a rim that only surfaces capture can only confirm itself.'
            % ', '.join(refusals)),
    }


# Structural guard -- see the calm-guard note in build_rim_top_signal.
assert 'refusal' in AXIS_STATES and 'capture' in AXIS_STATES, (
    "build_rim_top_signal's calm guard tests for 'capture' and 'refusal'. If "
    "either stops being a member of AXIS_STATES the guard silently stops "
    "working and the rim broadcasts every cycle -- the exact defect that made "
    "uae_signal_interpreter's drift guard dead on arrival.")


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

    # ── THE PURCHASING RIM (v2.0.0) ──
    # The axis reader READS each spoke's own capture/refusal verdict; it never
    # derives one. Spokes with no axis are counted as axis-uninstrumented, not
    # defaulted to 'capture'.
    purchasing_rim = build_purchasing_rim(
        spoke_axis_reader=_default_spoke_axis_reader)
    print("[UAE Rhetoric] Purchasing rim: %d/%d reporting, %d dominant, converged=%s"
          % (purchasing_rim.get('reporting', 0),
             purchasing_rim.get('rim_instrumented', 0),
             len(purchasing_rim.get('sole_counterparty') or []),
             purchasing_rim.get('converged')))

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
            # v2.0.0 -- THIS BLOCK WAS DEAD. It re-ran the whole fallback
            # scorer every cycle and then filtered its output for types
            # 'natural_disaster_strain' and 'contested_node'. The fallback
            # emits exactly three types -- tripwire, dual_track_divergence,
            # actor_signal -- so the filter matched nothing, ever, and the
            # block appended nothing while doing a full redundant pass.
            #
            # Replaced with the one signal the interpreter genuinely cannot
            # produce, because it never sees the rim.
            pass
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

    # ── Alignment-drift convergence signal -> ME BLUF / GPI ──
    if UAE_INTERPRETER_AVAILABLE and alignment_drift:
        _drift_sig = build_alignment_drift_top_signal(alignment_drift)
        if _drift_sig and not any(s.get('category') == 'alignment_drift' for s in top_signals):
            top_signals = [_drift_sig] + list(top_signals)

    # ── Purchasing-rim signal (v2.0.0) -> ME BLUF / GPI ──
    # Fires on BOTH paths: the interpreter owns prose, the hub owns its rim.
    # Returns None on a calm rim, so a quiet cycle stays quiet.
    _rim_sig = build_rim_top_signal(purchasing_rim)
    if _rim_sig and not any(s.get('type') == 'purchasing_rim'
                            for s in top_signals if isinstance(s, dict)):
        top_signals = [_rim_sig] + list(top_signals)


    # ── BLUF compatibility shim ──
    # me_regional_bluf._normalize_tracker_data() expects an integer
    # theatre_level (0-5) and a 0-100 theatre_score. UAE emits a categorical
    # composite_level + a free-running composite_score; map them so the ME
    # BLUF can ingest UAE cleanly. (v1.0.0 credited wha_regional_bluf and
    # 'alongside Cuba' -- wrong backend, wrong neighbour.)
    LEVEL_TO_THEATRE_INT = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
    raw_theatre_level = LEVEL_TO_THEATRE_INT.get(composite_level, 0)
    # Cap theatre_score at 100 — composite_score is unbounded by design
    theatre_score = min(100, int(composite_score))

    # ── L5 RESERVATION CONTRACT (v1.0.0 May 21 2026) ──
    # Compute L5 gate; cap theatre_level at L4 if raw is L5 but gate didn't fire.
    # UAE scaffolds today — no severity-5 tripwires yet. Gate is silent until
    # weekend audit adds real L5-class triggers per axis.
    # v2.0.0 -- PROMOTION, not just capping. The word ladder tops out at
    # 'surge' = 4, so the old `raw >= 5` cap could never fire: nothing in this
    # file can produce a 5 to cap. The gate's real job is the other direction
    # -- promoting a surge to L5 when an L5 axis trigger actually fired. Both
    # branches are kept: the cap stays as a guard in case the ladder ever
    # grows a 'rupture' rung.
    l5_gate = _compute_uae_l5_gate(tripwires_global, actor_summaries, vector_scores)
    l5_promoted = False
    if raw_theatre_level >= 5 and not l5_gate['any']:
        theatre_level = 4
        l5_capped = True
        print(f"[UAE Rhetoric] L5 gate enforced: raw={raw_theatre_level} capped at L4 "
              f"(reason: {l5_gate['reason']})")
    elif raw_theatre_level == 4 and l5_gate['any']:
        theatre_level = 5
        l5_capped = False
        l5_promoted = True
        print(f"[UAE Rhetoric] L5 gate FIRED: surge promoted to L5 "
              f"({l5_gate['reason'][:90]})")
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
        'l5_promoted':           l5_promoted,
        # v2.0.0: was 'contested_node' here while _write_uae_fingerprints wrote
        # 'aligned_hub' -- one payload, two self-classifications. The UAE is a
        # HUB (it runs a rim) that is also a spoke of the Israel/Iran/US wheels.
        # 'aligned_hub' is the one the fingerprint publishes, so it wins.
        'source_class':          'aligned_hub',
        'vector_scores':         vector_scores,
        'vector_levels':         vector_levels,
        'actor_summaries':       actor_summaries,
        'tripwires_global':      tripwires_global,
        'commodity_pressure':    commodity_pressure,
        'crosstheater_amplifiers': crosstheater_amplifiers,
        'purchasing_rim':        purchasing_rim,
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
        'version':                MODULE_VERSION,
    }

    save_cache(result)

    # ── Canonical history snapshot ──
    # Universal fields read by me_regional_bluf._read_history_snapshot() ->
    # _compute_direction(): theatre_level, theatre_score, scanned_at,
    # red_lines_count. DO NOT RENAME THOSE FOUR -- a live consumer reads them.
    #
    # v2.0.0 FIX: the four vector fields below used to be kinetic_afpak,
    # repression_rights, external_friction and illicit_economy. Not one of
    # those is a UAE vector -- they are Afghanistan/Pakistan clone residue, and
    # vector_levels.get() returned None for all four on every scan since July.
    # Months of history rows carrying four Nones where the gauge contract
    # should be. The real four are below, and they match VECTOR_GROUPS.
    try:
        _redis_lpush_trim(HISTORY_KEY, {
            'theatre_level':       theatre_level,
            'theatre_score':       theatre_score,
            'scanned_at':          result.get('last_updated') or datetime.now(timezone.utc).isoformat(),
            'red_lines_count':     len(tripwires_global),
            'kinetic_inbound':     vector_levels.get('kinetic_inbound'),
            'israel_axis':         vector_levels.get('israel_axis'),
            'iran_dual':           vector_levels.get('iran_dual'),
            'economic_hub':        vector_levels.get('economic_hub'),
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
            'version':                  MODULE_VERSION,
            'actor_count':              len(ACTORS),
            'actors':                   list(ACTORS.keys()),
            'vector_count':             len(VECTOR_GROUPS),
            'vectors':                  list(VECTOR_GROUPS.keys()),
            'rss_feeds':                len(RSS_FEEDS),
            'gdelt_queries_en':         len(GDELT_QUERIES_EN),
            'gdelt_queries_ar':         len(GDELT_QUERIES_AR),
            'tripwires':                len(TRIPWIRES),
            'redis_configured':         bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured':       bool(NEWSAPI_KEY),
            'brave_configured':         bool(BRAVE_API_KEY),
            'commodity_fingerprint':    COMMODITY_FINGERPRINT_AVAILABLE,
            'interpreter_available':    UAE_INTERPRETER_AVAILABLE,
            # v2.0.0 rim diagnostics -- says plainly whether the hub can read
            # its own rim, and which spokes are silent versus sensor-less.
            'wheel_reader_available':   WHEEL_READER_AVAILABLE,
            'l5_axes_instrumented':     sorted({
                d.get('l5_axis') for d in TRIPWIRES.values()
                if d.get('l5_axis') and d.get('severity') == 'surge'}),
            'rim': ({'readable': (cached.get('purchasing_rim') or {}).get('readable'),
                     'reporting': (cached.get('purchasing_rim') or {}).get('reporting'),
                     'instrumented': (cached.get('purchasing_rim') or {}).get('rim_instrumented'),
                     'converged': (cached.get('purchasing_rim') or {}).get('converged'),
                     'no_hub_block': (cached.get('purchasing_rim') or {}).get('no_hub_block')}
                    if cached else None),
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
