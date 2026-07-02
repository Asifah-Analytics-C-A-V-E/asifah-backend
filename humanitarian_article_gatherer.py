"""
humanitarian_article_gatherer.py
Asifah Analytics -- ME Backend Module
v1.4.0 -- May 23, 2026 (Health/Pandemic + Africa Expansion)
(prior: v1.0.0 May 19 2026 baseline)

GLOBAL HUMANITARIAN ARTICLE GATHERER

Canonical Asifah writer/reader pattern:
  - This module (the WRITER) fetches articles from humanitarian-focused
    sources every 12 hours, dedupes them, and writes the pool to Redis.
  - humanitarian_convergence_detector.py (the READER) reads that Redis
    key on each scan and runs keyword/country matching against it.

SOURCES:
  RSS (always-on, low cost):
    - ReliefWeb (UN OCHA -- canonical humanitarian aggregator)
    - WFP / World Food Programme
    - UNICEF press releases
    - UNHCR (refugees / displacement)
    - The New Humanitarian (formerly IRIN -- niche humanitarian beat)
    - Al Jazeera (Africa + Asia humanitarian beats)
    - Reuters Africa
    - WHO Disease Outbreak News (v1.4.0) -- official PHEIC + outbreak feed
    - WHO Regional Office for Africa (v1.4.0) -- DRC Ebola, Marburg, cholera
    - CIDRAP News (v1.4.0) -- academic-tier outbreak surveillance
    - Google News humanitarian + health queries (broad fallback)

  GDELT (medium cost, broad reach):
    - Targeted queries for known crisis countries
    - Falls back to Brave Search if GDELT returns <5 articles

  Brave Search (last-resort, quota-managed):
    - Used for sub-region queries where GDELT may lack specificity
    - (Darfur, El Fasher, Tigray, Rakhine, etc.)
    - Cached aggressively to preserve 2000/mo quota

REDIS KEYS:
  humanitarian:articles:latest  -- canonical article pool (12h TTL)
  humanitarian:gatherer:lastrun -- last run timestamp (for diagnostics)
  humanitarian:brave:<query>    -- per-query Brave cache (12h TTL)

ENDPOINTS:
  GET /api/humanitarian-gatherer/scan?force=true   Manually trigger fresh scan
  GET /api/humanitarian-gatherer/health            Health + last run + article count

SCHEDULE:
  Auto-runs every 12 hours via threading (matches rhetoric tracker pattern).

Author: RCGG / Asifah Analytics
"""

import os
import json
import time
import threading
import traceback
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests


# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
BRAVE_API_KEY       = os.environ.get('BRAVE_API_KEY', '')
GDELT_BASE_URL      = 'https://api.gdeltproject.org/api/v2/doc/doc'
BRAVE_BASE_URL      = 'https://api.search.brave.com/res/v1/news/search'

# Redis cache keys
ARTICLES_CACHE_KEY  = 'humanitarian:articles:latest'
LASTRUN_KEY         = 'humanitarian:gatherer:lastrun'
BRAVE_CACHE_PREFIX  = 'humanitarian:brave:'

# Cache TTLs
ARTICLES_CACHE_TTL  = 14 * 3600     # 14 hours -- outlasts the 12h scan interval so the pool never expires mid-cycle (cold-gap lesson, Jul 2026)
BRAVE_CACHE_TTL     = 12 * 3600     # 12 hours (preserve Brave quota)
SCAN_INTERVAL_HOURS = 12

# Scan tuning
RSS_TIMEOUT         = 12
GDELT_TIMEOUT       = 30
BRAVE_TIMEOUT       = 10
GDELT_MIN_RESULTS   = 5             # threshold below which Brave fallback kicks in
GDELT_INTER_QUERY_DELAY = 0.5       # 429-defense pacing between GDELT calls

# Global state for scheduler
_gatherer_running = False
_gatherer_lock    = threading.Lock()

# ------------------------------------------------------------
# CROSS-WORKER SCHEDULER LOCK  [Jun 2026]
# gunicorn runs --workers 2, and each worker imports this module and starts its
# own scheduler thread. The _gatherer_running flag above is per-process, so it
# only stops a worker from overlapping ITSELF -- it does NOT stop a second worker
# from gathering in parallel. Without this lock both workers gather, and every
# GDELT / Brave / RSS call fires twice (doubles quota burn + trips GDELT 429s).
# This atomic Upstash "SET ... NX EX" makes exactly ONE worker own the scan; the
# owner renews each cycle (TTL > cycle so ownership never lapses while it is
# alive); if the owner dies, the lock expires and another worker takes over.
# Fail-open: if Redis is unreachable we proceed (no worse than today).
# ------------------------------------------------------------
_SCHED_WORKER_ID = f"w{os.getpid()}"

def _acquire_scheduler_lock(name, ttl_seconds):
    """Return True if THIS worker owns the scheduler lock for `name`.
    Atomic claim via SET NX EX; renews the TTL if we already own it."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return True  # no Redis -> assume single process, run normally
    key = f"sched_lock:{name}"
    hdr = {"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}
    try:
        # Atomic claim: succeeds only if the key is absent (NX); auto-expires (EX).
        r = requests.post(UPSTASH_REDIS_URL, headers=hdr,
                          json=["SET", key, _SCHED_WORKER_ID, "NX", "EX", str(ttl_seconds)],
                          timeout=8)
        if r.ok and (r.json() or {}).get('result') == 'OK':
            return True  # we just claimed it
        # Claim failed -> someone holds it. If it's us, renew; otherwise stand down.
        g = requests.get(f"{UPSTASH_REDIS_URL}/get/{key}", headers=hdr, timeout=8)
        owner = (g.json() or {}).get('result') if g.ok else None
        if owner == _SCHED_WORKER_ID:
            requests.post(UPSTASH_REDIS_URL, headers=hdr,
                         json=["SET", key, _SCHED_WORKER_ID, "EX", str(ttl_seconds)],
                         timeout=8)  # renew our TTL
            return True
        return False  # another worker owns the scan
    except Exception as e:
        print(f"[SchedLock] {name}: lock check failed ({e}); proceeding (fail-open)")
        return True


# ============================================================
# REDIS HELPERS (canonical Asifah Upstash REST pattern)
# ============================================================
def _redis_get(key):
    """Direct Upstash REST GET."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        if not resp.ok:
            return None
        data = resp.json()
        raw = data.get('result')
        if raw is None:
            return None
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return raw
    except Exception as e:
        print(f"[humanitarian_gatherer] Redis GET error ({key}): {str(e)[:80]}")
        return None


def _redis_set(key, value, ttl=ARTICLES_CACHE_TTL):
    """Direct Upstash REST SET with EX param."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str) if not isinstance(value, str) else value
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/set/{key}",
            headers={
                "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                "Content-Type":  "application/json",
            },
            data=payload,
            params={"EX": ttl} if ttl else {},
            timeout=5,
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f"[humanitarian_gatherer] Redis SET error ({key}): {str(e)[:80]}")
        return False


# ============================================================
# RSS FEED CONFIG
# ============================================================
# Tier 1: Canonical humanitarian aggregators (highest weight)
# Tier 2: Specialized agencies (high weight)
# Tier 3: Generalist outlets with strong humanitarian beats (medium weight)
# Tier 4: Broad Google News queries (low weight, broadest coverage)

HUMANITARIAN_RSS_FEEDS = [
    # ── Tier 1: Canonical humanitarian aggregators ──
    ("https://reliefweb.int/updates/rss.xml",                              1.2),  # UN OCHA -- THE aggregator
    ("https://www.thenewhumanitarian.org/rss/all",                         1.1),  # Niche humanitarian beat
    # ── Tier 2: UN agency specialists ──
    ("https://www.wfp.org/rss/news",                                       1.1),  # World Food Programme
    ("https://www.unicef.org/press-releases/rss.xml",                      1.0),  # UNICEF
    ("https://www.unhcr.org/rss/news.xml",                                 1.0),  # UNHCR refugees
    # ── Tier 3: Generalist regional outlets with humanitarian beats ──
    ("https://www.aljazeera.com/xml/rss/all.xml",                          0.95), # Al Jazeera (Africa/Asia)
    ("https://feeds.reuters.com/reuters/africaNews",                       0.95), # Reuters Africa
    # ── Tier 4: Broader Google News humanitarian queries ──
    ("https://news.google.com/rss/search?q=famine+OR+%22food+crisis%22+OR+%22acute+food+insecurity%22&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=%22mass+displacement%22+OR+%22refugee+surge%22+OR+%22IDP+camps%22&hl=en&gl=US&ceid=US:en", 0.9),
    ("https://news.google.com/rss/search?q=%22humanitarian+crisis%22+OR+%22humanitarian+emergency%22&hl=en&gl=US&ceid=US:en", 0.85),
    ("https://news.google.com/rss/search?q=Sudan+Darfur+famine+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Yemen+humanitarian+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Myanmar+Rakhine+crisis+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=DRC+Congo+displacement+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Tigray+Ethiopia+famine+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=Afghanistan+humanitarian+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=Haiti+humanitarian+gang+violence+2026&hl=en&gl=US&ceid=US:en", 0.95),
    # World Vision + Feed the Children -- direct INGO RSS where available
    # (Note: Some INGOs publish via Google News rather than direct RSS;
    #  worldvision/feedthechildren RSS feeds may not exist or may be limited)
    ("https://news.google.com/rss/search?q=%22World+Vision%22+humanitarian&hl=en&gl=US&ceid=US:en", 0.85),
    ("https://news.google.com/rss/search?q=%22Feed+the+Children%22+OR+%22Mercy+Corps%22+OR+%22IRC+International%22&hl=en&gl=US&ceid=US:en", 0.85),
    # ─── v1.4.0 (May 23, 2026) HEALTH/PANDEMIC FEEDS ───
    # WHO official outbreak surveillance — canonical health emergency source
    # Note: WHO does not publish a /feed.xml route; we use Google News queries
    # targeted at WHO Disease Outbreak News content + WHO press releases.
    ("https://news.google.com/rss/search?q=site%3Awho.int+%22Disease+Outbreak+News%22&hl=en&gl=US&ceid=US:en", 1.15),  # WHO DON
    ("https://news.google.com/rss/search?q=%22WHO+Africa%22+OR+%22WHO+AFRO%22+outbreak&hl=en&gl=US&ceid=US:en", 1.1),   # WHO Africa Region
    ("https://news.google.com/rss/search?q=%22Public+Health+Emergency+of+International+Concern%22+OR+PHEIC&hl=en&gl=US&ceid=US:en", 1.1),
    # CIDRAP -- academic-tier outbreak surveillance (Univ of Minnesota)
    ("https://www.cidrap.umn.edu/news/feed", 1.05),
    # Named-disease watchlist queries — Africa-heavy outbreak coverage
    ("https://news.google.com/rss/search?q=Ebola+outbreak+DRC+OR+Uganda+OR+Sudan+2026&hl=en&gl=US&ceid=US:en", 1.05),
    ("https://news.google.com/rss/search?q=Marburg+outbreak+Rwanda+OR+Tanzania+OR+Kenya+2026&hl=en&gl=US&ceid=US:en", 1.05),
    ("https://news.google.com/rss/search?q=cholera+outbreak+Sudan+OR+Yemen+OR+Haiti+OR+Lebanon+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=mpox+outbreak+clade+DRC+OR+Burundi+OR+Uganda+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=%22H5N1%22+OR+%22avian+flu%22+human+cases+2026&hl=en&gl=US&ceid=US:en", 1.0),
    # Pandemic-prep + "disease X" + spillover watch
    ("https://news.google.com/rss/search?q=%22disease+X%22+OR+%22pandemic+preparedness%22+OR+%22zoonotic+spillover%22&hl=en&gl=US&ceid=US:en", 0.95),
    # Africa health system + vaccine cold-chain (Phase 2 readiness)
    ("https://news.google.com/rss/search?q=%22health+system%22+collapse+Africa+OR+%22vaccine+shortage%22+Africa&hl=en&gl=US&ceid=US:en", 0.95),
    # ─── v1.5.0 (Jul 1, 2026) NATURAL DISASTER FEEDS ───
    # GDACS -- UN/EC Global Disaster Alert & Coordination System. THE canonical
    # multi-hazard alert feed (earthquakes, tsunamis, floods, cyclones, volcanoes,
    # droughts). Standard RSS <item> structure; alert color is in title/description.
    ("https://www.gdacs.org/xml/rss.xml", 1.2),
    # ReliefWeb DISASTERS feed (distinct from the general /updates feed above --
    # this one is disaster-typed: EQ, FL, TC, VO, etc.)
    ("https://reliefweb.int/disasters/rss.xml", 1.15),
    # IFRC / Red Cross disaster-response coverage (DREF + emergency appeals)
    ("https://news.google.com/rss/search?q=IFRC+OR+%22Red+Cross%22+disaster+response+emergency+appeal&hl=en&gl=US&ceid=US:en", 0.95),
    # Named-hazard watch queries (broad backstop for events USGS/GDACS lead on)
    ("https://news.google.com/rss/search?q=earthquake+OR+tsunami+magnitude+2026&hl=en&gl=US&ceid=US:en", 1.0),
    ("https://news.google.com/rss/search?q=flooding+OR+cyclone+OR+typhoon+OR+hurricane+disaster+2026&hl=en&gl=US&ceid=US:en", 0.95),
    ("https://news.google.com/rss/search?q=%22volcanic+eruption%22+OR+landslide+disaster+2026&hl=en&gl=US&ceid=US:en", 0.9),
]


# ============================================================
# GDELT QUERY CONFIG
# ============================================================
# Each query covers a humanitarian theme + geographic focus.
# Queries kept short (GDELT errors on long queries).
# Languages limited to English + Arabic to avoid Farsi/load issues
# experienced elsewhere on the platform.

GDELT_HUMANITARIAN_QUERIES = [
    # ── Africa-focused (heavy humanitarian load) ──
    ("Sudan famine displacement 2026",          'eng'),
    ("Darfur El Fasher crisis 2026",            'eng'),
    ("Ethiopia Tigray food insecurity 2026",    'eng'),
    ("South Sudan humanitarian 2026",           'eng'),
    ("DRC Congo displacement crisis 2026",      'eng'),
    ("Somalia drought famine 2026",             'eng'),
    ("Nigeria Niger Mali humanitarian 2026",    'eng'),
    # ── Middle East humanitarian (non-conflict-dominated framing) ──
    ("Yemen humanitarian aid 2026",             'eng'),
    ("Gaza humanitarian crisis 2026",           'eng'),
    ("Syria humanitarian 2026",                 'eng'),
    # ── Asia humanitarian ──
    ("Myanmar Rakhine displacement 2026",       'eng'),
    ("Afghanistan humanitarian Taliban 2026",   'eng'),
    ("Bangladesh Rohingya refugees 2026",       'eng'),
    ("Sri Lanka economic crisis 2026",          'eng'),
    # ── Americas humanitarian ──
    ("Haiti gang violence displacement 2026",   'eng'),
    ("Venezuela humanitarian crisis 2026",      'eng'),
    # ── Arabic-language coverage ──
    ("السودان دارفور أزمة إنسانية 2026",        'ara'),
    ("اليمن أزمة إنسانية 2026",                 'ara'),
    ("غزة أزمة إنسانية 2026",                   'ara'),
    # ─── v1.4.0 (May 23, 2026) HEALTH/PANDEMIC GDELT QUERIES ───
    # Disease-specific watchlist with Africa concentration. Kept short
    # to avoid GDELT query-length errors. English-only — most outbreak
    # journalism is English-dominant via WHO + CIDRAP + Reuters.
    ("Ebola outbreak DRC Uganda 2026",           'eng'),
    ("Marburg outbreak Rwanda Tanzania 2026",    'eng'),
    ("cholera outbreak Sudan Yemen 2026",        'eng'),
    ("mpox outbreak Africa 2026",                'eng'),
    ("H5N1 human cases outbreak 2026",           'eng'),
    ("WHO PHEIC declared 2026",                  'eng'),
    ("disease outbreak Africa 2026",             'eng'),
    ("vaccine shortage Africa cholera 2026",     'eng'),
    # Pandemic-prep + spillover watch
    ("disease X pandemic preparedness 2026",     'eng'),
    ("zoonotic spillover outbreak 2026",         'eng'),
    # ─── v1.5.0 (Jul 1, 2026) NATURAL DISASTER GDELT QUERIES ───
    ("earthquake tsunami disaster 2026",         'eng'),
    ("flooding cyclone typhoon disaster 2026",   'eng'),
    ("volcanic eruption landslide disaster 2026",'eng'),
    ("Venezuela earthquake disaster 2026",       'eng'),
]


# ============================================================
# BRAVE SEARCH CONFIG -- sub-region queries (Brave > GDELT for named places)
# ============================================================
BRAVE_SUBREGION_QUERIES = [
    "El Fasher siege famine",
    "Darfur RSF Janjaweed",
    "Tigray Eritrea Amhara crisis",
    "Rakhine Rohingya Myanmar",
    "Goma Eastern DRC M23",
    "Cap-Haitien gang violence",
    "Khan Younis Rafah Gaza humanitarian",
    "Hodeidah Sanaa Yemen aid",
    # ─── v1.4.0 (May 23, 2026) Africa outbreak + crisis hotspots ───
    "Beni Butembo DRC Ebola",                # DRC Ebola epicenters
    "Kampala Uganda Ebola Sudan strain",     # Uganda Ebola history
    "Kigali Rwanda Marburg outbreak",        # Rwanda Marburg 2024
    "Kasai DRC mpox clade",                   # Mpox clade Ib origin
    "Lake Chad basin Boko Haram displacement", # Lake Chad humanitarian
    "Sahel coup belt displacement",           # Mali/Burkina/Niger
    "Bangui CAR humanitarian",                # Central African Republic
    "Cabo Delgado Mozambique insurgency",    # Cabo Delgado crisis
    "Sudan cholera vaccine shortage",         # Sudan cholera crisis
    "Cox's Bazar Rohingya health",            # Bangladesh Rohingya health
]


# ============================================================
# RSS FETCH
# ============================================================
def _fetch_rss_feed(feed_url, weight, days_back=7):
    """
    Fetch one RSS feed. Returns list of article dicts.
    Uses 7-day lookback to catch slow-burn humanitarian stories.
    """
    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days_back)

    try:
        resp = requests.get(
            feed_url,
            timeout=RSS_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AsifahAnalytics/1.0)"},
        )
        if resp.status_code != 200:
            return articles

        root = ET.fromstring(resp.content)
        for item in root.findall('.//item'):
            title = item.findtext('title', '') or ''
            link  = item.findtext('link', '') or ''
            pub   = item.findtext('pubDate', '') or ''
            desc  = item.findtext('description', '') or ''

            # Strip HTML from description
            if '<' in desc:
                # crude HTML strip (good enough for keyword scanning)
                import re
                desc = re.sub(r'<[^>]+>', '', desc)

            # Date filter
            try:
                pub_dt = parsedate_to_datetime(pub) if pub else datetime.now(timezone.utc)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < since:
                    continue
                pub_str = pub_dt.isoformat()
            except Exception:
                pub_str = pub

            articles.append({
                'title':       title[:300],
                'url':         link,
                'published':   pub_str if isinstance(pub_str, str) else '',
                'description': desc[:500],
                'source':      _short_source_name(feed_url),
                'weight':      weight,
            })

    except Exception as e:
        print(f"[humanitarian_gatherer] RSS error ({feed_url[:60]}...): {str(e)[:80]}")

    return articles


def _short_source_name(url):
    """Extract a short label from a feed URL for source display."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or 'rss'
        # If it's a Google News query, extract the search term as identifier
        if 'news.google.com' in host:
            qs = urllib.parse.parse_qs(parsed.query)
            q = qs.get('q', ['rss'])[0]
            return f"GoogleNews: {q[:40]}"
        # Otherwise just use the hostname stub
        if host.startswith('www.'):
            host = host[4:]
        return host.split('.')[0]
    except Exception:
        return 'rss'


def fetch_all_rss():
    """Fetch all configured RSS feeds, return combined article list."""
    all_articles = []
    for feed_url, weight in HUMANITARIAN_RSS_FEEDS:
        articles = _fetch_rss_feed(feed_url, weight)
        if articles:
            all_articles.extend(articles)
            print(f"[humanitarian_gatherer] RSS {_short_source_name(feed_url)[:30]}: {len(articles)} articles")
        time.sleep(0.2)  # gentle pacing between feed fetches
    print(f"[humanitarian_gatherer] RSS total: {len(all_articles)} articles")
    return all_articles


# ============================================================
# GDELT FETCH
# ============================================================
def _fetch_gdelt_query(query, lang='eng', days=7):
    """Fetch one GDELT query. Returns list of article dicts."""
    articles = []
    try:
        params = {
            'query':      query,
            'mode':       'artlist',
            'maxrecords': 30,
            'timespan':   f'{days}d',
            'format':     'json',
            'sourcelang': lang,
        }
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=GDELT_TIMEOUT)
        if resp.status_code == 429:
            # Rate-limited; return empty rather than retry to avoid blocking
            print(f"[humanitarian_gatherer] GDELT 429 on '{query[:40]}'")
            return articles
        if resp.status_code != 200:
            return articles

        try:
            payload = resp.json()
        except Exception:
            # GDELT sometimes returns HTML error pages
            return articles

        for art in payload.get('articles', []):
            articles.append({
                'title':       (art.get('title') or '')[:300],
                'url':         art.get('url') or '',
                'published':   art.get('seendate') or '',
                'description': (art.get('snippet') or art.get('title') or '')[:500],
                'source':      f"GDELT/{lang}: {query[:30]}",
                'weight':      0.95,
            })
    except Exception as e:
        print(f"[humanitarian_gatherer] GDELT error '{query[:40]}': {str(e)[:80]}")

    return articles


def fetch_all_gdelt():
    """
    Fetch all configured GDELT queries.
    Tags queries returning <5 articles for Brave fallback.
    """
    all_articles = []
    fallback_needed = []   # list of (query, lang) tuples that need Brave backup

    for query, lang in GDELT_HUMANITARIAN_QUERIES:
        articles = _fetch_gdelt_query(query, lang=lang)
        if len(articles) < GDELT_MIN_RESULTS:
            fallback_needed.append((query, lang))
        all_articles.extend(articles)
        print(f"[humanitarian_gatherer] GDELT '{query[:35]}' ({lang}): {len(articles)} articles")
        time.sleep(GDELT_INTER_QUERY_DELAY)   # 429-defense pacing

    print(f"[humanitarian_gatherer] GDELT total: {len(all_articles)} articles, "
          f"{len(fallback_needed)} queries need Brave fallback")
    return all_articles, fallback_needed


# ============================================================
# USGS EARTHQUAKE FETCH (structured GeoJSON -> article-shaped)  [v1.5.0]
# ============================================================
# USGS is the canonical global seismic authority. We pull the "significant"
# earthquakes GeoJSON (magnitude + felt + PAGER-impact weighted) plus the M4.5+
# weekly feed, and convert each event into an article-shaped dict so the
# convergence detector classifies it exactly like any other source. Rich fields
# -- magnitude, USGS PAGER alert (green/yellow/orange/red), tsunami flag, place --
# are baked into the title + description so the natural_disaster keyword + high-
# intensity markers fire correctly (e.g. 'magnitude 6', 'tsunami warning',
# 'pager orange'). The place string usually carries the country name, which the
# detector's country matcher needs; mid-ocean events without a country drop out.
USGS_FEEDS = [
    ('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson', 'significant'),
    ('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson',          'M4.5+week'),
]
USGS_MIN_MAG = 5.0   # humanitarian relevance starts ~M5-6; ignore minor events


def fetch_usgs_earthquakes():
    """Fetch USGS significant + M4.5+ quakes; convert to keyword-rich article dicts."""
    all_articles = []
    seen_ids = set()
    for feed_url, tag in USGS_FEEDS:
        try:
            resp = requests.get(
                feed_url, timeout=GDELT_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AsifahAnalytics/1.0)"},
            )
            if resp.status_code != 200:
                print(f"[humanitarian_gatherer] USGS {tag} HTTP {resp.status_code}")
                continue
            payload = resp.json()
            for feat in (payload.get('features') or []):
                fid = feat.get('id')
                if fid in seen_ids:
                    continue
                seen_ids.add(fid)
                props = feat.get('properties') or {}
                mag = props.get('mag')
                if mag is None:
                    continue
                # The 'significant' feed is USGS-curated for impact (a shallow M4.8
                # under a city can qualify) -- keep all of it. The raw M4.5+ feed is
                # noisier, so apply the humanitarian-relevance magnitude floor there.
                if tag != 'significant' and mag < USGS_MIN_MAG:
                    continue
                place    = props.get('place') or 'unknown location'
                alert    = (props.get('alert') or '').lower()   # PAGER: green/yellow/orange/red
                tsunami  = props.get('tsunami', 0)
                url      = props.get('url') or ''
                mag_str  = f"{mag:.1f}"

                # Keyword-rich text so the natural_disaster matcher + high-intensity
                # markers fire. We deliberately write both "M6.3" and "magnitude 6.3".
                title = f"M{mag_str} earthquake - {place}"
                parts = [f"A magnitude {mag_str} earthquake struck {place}."]
                if alert in ('orange', 'red'):
                    parts.append(f"USGS PAGER {alert} alert issued -- significant casualties and damage likely; "
                                 f"search and rescue operation expected.")
                elif alert in ('green', 'yellow'):
                    parts.append(f"USGS PAGER {alert} alert.")
                if tsunami:
                    parts.append("Tsunami warning evaluated for this event.")
                if mag >= 6.0:
                    parts.append("Major earthquake; disaster response and humanitarian assessment likely.")
                description = ' '.join(parts)

                weight = 1.0
                if mag >= 7.0 or alert == 'red':
                    weight = 1.3
                elif mag >= 6.0 or alert == 'orange':
                    weight = 1.15

                published = ''
                if props.get('time'):
                    try:
                        published = datetime.fromtimestamp(props['time'] / 1000, tz=timezone.utc).isoformat()
                    except Exception:
                        published = ''

                all_articles.append({
                    'title':       title[:300],
                    'url':         url,
                    'published':   published,
                    'description': description[:500],
                    'source':      f"USGS/{tag}",
                    'weight':      weight,
                })
        except Exception as e:
            print(f"[humanitarian_gatherer] USGS {tag} error: {str(e)[:80]}")
        time.sleep(0.3)
    print(f"[humanitarian_gatherer] USGS total: {len(all_articles)} significant quakes (>=M{USGS_MIN_MAG})")
    return all_articles


# ============================================================
# BRAVE SEARCH FETCH (with caching to preserve quota)
# ============================================================
def _fetch_brave_query(query, force_refresh=False):
    """
    Fetch one Brave Search news query.
    Returns list of article dicts. Caches result for 12h to preserve quota.
    """
    if not BRAVE_API_KEY:
        return []

    # Check Redis cache first
    cache_key = BRAVE_CACHE_PREFIX + query.replace(' ', '_')[:100]
    if not force_refresh:
        cached = _redis_get(cache_key)
        if cached and isinstance(cached, list):
            return cached

    articles = []
    try:
        resp = requests.get(
            BRAVE_BASE_URL,
            params={'q': query, 'count': 20, 'spellcheck': '0'},
            headers={
                'Accept':              'application/json',
                'X-Subscription-Token': BRAVE_API_KEY,
            },
            timeout=BRAVE_TIMEOUT,
        )
        if resp.status_code == 429:
            print(f"[humanitarian_gatherer] Brave 429 on '{query[:40]}'")
            return articles
        if resp.status_code != 200:
            print(f"[humanitarian_gatherer] Brave HTTP {resp.status_code} on '{query[:40]}'")
            return articles

        payload = resp.json()
        for art in (payload.get('results', []) or []):
            articles.append({
                'title':       (art.get('title') or '')[:300],
                'url':         art.get('url') or '',
                'published':   art.get('age') or '',
                'description': (art.get('description') or '')[:500],
                'source':      f"Brave: {query[:30]}",
                'weight':      0.9,
            })

        # Cache the result (12h TTL)
        if articles:
            _redis_set(cache_key, articles, ttl=BRAVE_CACHE_TTL)

    except Exception as e:
        print(f"[humanitarian_gatherer] Brave error '{query[:40]}': {str(e)[:80]}")

    return articles


def fetch_brave_subregions():
    """Fetch all sub-region queries via Brave. Cached aggressively for quota."""
    all_articles = []
    for query in BRAVE_SUBREGION_QUERIES:
        articles = _fetch_brave_query(query)
        all_articles.extend(articles)
        print(f"[humanitarian_gatherer] Brave '{query[:40]}': {len(articles)} articles")
        time.sleep(1.1)  # Brave is 1 req/sec
    print(f"[humanitarian_gatherer] Brave subregions total: {len(all_articles)} articles")
    return all_articles


def fetch_brave_gdelt_fallback(fallback_queries):
    """For GDELT queries that returned <5 results, try Brave as backup."""
    all_articles = []
    if not BRAVE_API_KEY:
        return all_articles
    for query, lang in fallback_queries:
        # Only English fallback for Brave (Brave's Arabic coverage less reliable)
        if lang != 'eng':
            continue
        articles = _fetch_brave_query(query)
        all_articles.extend(articles)
        time.sleep(1.1)
    print(f"[humanitarian_gatherer] Brave fallback total: {len(all_articles)} articles")
    return all_articles


# ============================================================
# DEDUPLICATION + ASSEMBLY
# ============================================================
def _dedupe_articles(articles):
    """Dedupe articles by URL. Preserve order (first occurrence wins)."""
    seen_urls = set()
    deduped = []
    for art in articles:
        if not isinstance(art, dict):
            continue
        url = art.get('url') or ''
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        # Also dedupe by title prefix if URL missing (rare but happens)
        else:
            title_key = (art.get('title') or '')[:80].lower()
            if title_key and title_key in seen_urls:
                continue
            if title_key:
                seen_urls.add(title_key)
        deduped.append(art)
    return deduped


# ============================================================
# MAIN GATHER FUNCTION
# ============================================================
def run_gather():
    """
    Full gather: RSS + GDELT + Brave (subregions + GDELT fallback).
    Writes deduplicated article pool to Redis. Returns summary dict.
    """
    start_ts = datetime.now(timezone.utc)
    print(f"[humanitarian_gatherer] === SCAN START at {start_ts.isoformat()} ===")

    all_articles = []
    metrics = {
        'rss_count':              0,
        'usgs_count':             0,
        'gdelt_count':            0,
        'brave_subregion_count':  0,
        'brave_fallback_count':   0,
        'duplicate_count':        0,
    }

    # Step 1: RSS feeds (canonical humanitarian aggregators + UN agencies + queries)
    try:
        rss_articles = fetch_all_rss()
        metrics['rss_count'] = len(rss_articles)
        all_articles.extend(rss_articles)
    except Exception as e:
        print(f"[humanitarian_gatherer] RSS phase exception: {e}")

    # Step 1.5: USGS structured earthquake feed (significant + M4.5+ quakes) [v1.5.0]
    try:
        usgs_articles = fetch_usgs_earthquakes()
        metrics['usgs_count'] = len(usgs_articles)
        all_articles.extend(usgs_articles)
    except Exception as e:
        print(f"[humanitarian_gatherer] USGS phase exception: {e}")

    # Step 2: GDELT humanitarian queries
    try:
        gdelt_articles, fallback_needed = fetch_all_gdelt()
        metrics['gdelt_count'] = len(gdelt_articles)
        all_articles.extend(gdelt_articles)
    except Exception as e:
        print(f"[humanitarian_gatherer] GDELT phase exception: {e}")
        fallback_needed = []

    # Step 3: Brave for sub-regions (cached aggressively)
    try:
        brave_sub = fetch_brave_subregions()
        metrics['brave_subregion_count'] = len(brave_sub)
        all_articles.extend(brave_sub)
    except Exception as e:
        print(f"[humanitarian_gatherer] Brave subregion phase exception: {e}")

    # Step 4: Brave fallback for GDELT queries that came up short
    try:
        brave_fallback = fetch_brave_gdelt_fallback(fallback_needed)
        metrics['brave_fallback_count'] = len(brave_fallback)
        all_articles.extend(brave_fallback)
    except Exception as e:
        print(f"[humanitarian_gatherer] Brave fallback phase exception: {e}")

    # Step 5: Dedupe
    pre_dedupe_count = len(all_articles)
    deduped = _dedupe_articles(all_articles)
    metrics['duplicate_count'] = pre_dedupe_count - len(deduped)

    # Step 6: Write to Redis
    pool = {
        'articles':       deduped,
        'article_count':  len(deduped),
        'metrics':        metrics,
        'scanned_at':     start_ts.isoformat(),
        'completed_at':   datetime.now(timezone.utc).isoformat(),
        'version':        __version__,
    }
    _redis_set(ARTICLES_CACHE_KEY, pool, ttl=ARTICLES_CACHE_TTL)
    _redis_set(LASTRUN_KEY, {
        'last_run_at':   start_ts.isoformat(),
        'article_count': len(deduped),
        'metrics':       metrics,
    }, ttl=ARTICLES_CACHE_TTL * 2)

    elapsed = (datetime.now(timezone.utc) - start_ts).total_seconds()
    print(f"[humanitarian_gatherer] === SCAN COMPLETE in {elapsed:.1f}s ===")
    print(f"[humanitarian_gatherer] Total articles: {len(deduped)} "
          f"(RSS={metrics['rss_count']}, USGS={metrics['usgs_count']}, GDELT={metrics['gdelt_count']}, "
          f"BraveSub={metrics['brave_subregion_count']}, BraveFB={metrics['brave_fallback_count']}, "
          f"deduped={metrics['duplicate_count']})")

    return {
        'success':       True,
        'article_count': len(deduped),
        'metrics':       metrics,
        'elapsed_sec':   elapsed,
        'scanned_at':    start_ts.isoformat(),
    }


# ============================================================
# BACKGROUND SCHEDULER
# ============================================================
def _scheduler_loop():
    """Background thread: run gather every SCAN_INTERVAL_HOURS."""
    global _gatherer_running
    while True:
        try:
            # Cross-worker guard: only the lock-owning worker scans. TTL (13h)
            # outlasts the 12h scan interval so ownership persists between cycles;
            # a non-owner re-checks hourly so it can take over if the owner dies.
            if not _acquire_scheduler_lock('humanitarian', 46800):
                time.sleep(3600)
                continue
            with _gatherer_lock:
                if _gatherer_running:
                    # Another thread is running; skip this cycle
                    time.sleep(60)
                    continue
                _gatherer_running = True
            try:
                run_gather()
            finally:
                with _gatherer_lock:
                    _gatherer_running = False
            # Sleep until next scan
            time.sleep(SCAN_INTERVAL_HOURS * 3600)
        except Exception as e:
            print(f"[humanitarian_gatherer] Scheduler loop exception: {e}")
            print(traceback.format_exc())
            with _gatherer_lock:
                _gatherer_running = False
            time.sleep(300)  # back off 5min on unhandled exception


def start_background_scheduler():
    """Start the background scheduler thread. Idempotent."""
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name='HumanitarianGatherer')
    thread.start()
    print(f"[humanitarian_gatherer] Background scheduler started (interval: {SCAN_INTERVAL_HOURS}h)")


# ============================================================
# FLASK ROUTE REGISTRATION
# ============================================================
def register_humanitarian_gatherer_routes(app, start_scheduler=True):
    """
    Register gatherer endpoints + optionally start the background scheduler.

    Endpoints:
      GET /api/humanitarian-gatherer/scan?force=true   Manually trigger fresh scan
      GET /api/humanitarian-gatherer/health            Health + last run + diagnostics
      GET /api/humanitarian-gatherer/articles          Return current article pool

    Args:
      app:             Flask app instance.
      start_scheduler: If True (default), start background 12h scheduler thread.
    """
    from flask import jsonify, request

    @app.route('/api/humanitarian-gatherer/scan', methods=['GET', 'POST'])
    def gatherer_scan():
        """Trigger a manual scan. Returns immediately on cache hit unless ?force=true."""
        global _gatherer_running
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        # If a scan is already running, return early
        if _gatherer_running:
            return jsonify({
                'success': False,
                'message': 'A scan is already in progress; please wait',
                'in_progress': True,
            }), 200

        # If not forced, check whether cache is fresh
        if not force:
            lastrun = _redis_get(LASTRUN_KEY)
            if lastrun and isinstance(lastrun, dict):
                last_run_at = lastrun.get('last_run_at')
                try:
                    last_dt = datetime.fromisoformat(last_run_at)
                    age_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                    if age_h < SCAN_INTERVAL_HOURS:
                        return jsonify({
                            'success':       True,
                            'cached':        True,
                            'last_run_at':   last_run_at,
                            'article_count': lastrun.get('article_count', 0),
                            'metrics':       lastrun.get('metrics', {}),
                            'message':       f'Cached pool is {age_h:.1f}h old; use ?force=true to refresh',
                        }), 200
                except Exception:
                    pass

        # Run a fresh scan
        with _gatherer_lock:
            _gatherer_running = True
        try:
            result = run_gather()
            return jsonify(result), 200
        finally:
            with _gatherer_lock:
                _gatherer_running = False

    @app.route('/api/humanitarian-gatherer/health', methods=['GET'])
    def gatherer_health():
        """Health check + last-run diagnostics."""
        lastrun = _redis_get(LASTRUN_KEY) or {}
        pool = _redis_get(ARTICLES_CACHE_KEY) or {}
        return jsonify({
            'module':           __module_id__,
            'version':          __version__,
            'rss_feeds_count':  len(HUMANITARIAN_RSS_FEEDS),
            'usgs_feeds_count': len(USGS_FEEDS),
            'gdelt_queries':    len(GDELT_HUMANITARIAN_QUERIES),
            'brave_subregions': len(BRAVE_SUBREGION_QUERIES),
            'brave_configured': bool(BRAVE_API_KEY),
            'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'scan_interval_h':  SCAN_INTERVAL_HOURS,
            'currently_running': _gatherer_running,
            'last_run_at':      lastrun.get('last_run_at') if isinstance(lastrun, dict) else None,
            'last_article_count': lastrun.get('article_count', 0) if isinstance(lastrun, dict) else 0,
            'last_metrics':     lastrun.get('metrics', {}) if isinstance(lastrun, dict) else {},
            'cached_pool_size': len(pool.get('articles', [])) if isinstance(pool, dict) else 0,
            'cached_at':        pool.get('completed_at') if isinstance(pool, dict) else None,
            'status':           'operational',
        }), 200

    @app.route('/api/humanitarian-gatherer/articles', methods=['GET'])
    def gatherer_articles():
        """Return the current cached article pool (for the detector + debugging)."""
        pool = _redis_get(ARTICLES_CACHE_KEY)
        if not pool:
            return jsonify({
                'success':       False,
                'error':         'No article pool cached yet. Hit /scan?force=true to gather.',
                'articles':      [],
                'article_count': 0,
            }), 200
        return jsonify(pool), 200

    print('[humanitarian_gatherer] Routes registered: /api/humanitarian-gatherer/{scan,health,articles}')

    if start_scheduler:
        start_background_scheduler()


# ============================================================
# MODULE METADATA
# ============================================================
__version__   = '1.5.0'
__module_id__ = 'humanitarian_article_gatherer'
print(f'[Humanitarian Article Gatherer] Module loaded -- v{__version__}')
