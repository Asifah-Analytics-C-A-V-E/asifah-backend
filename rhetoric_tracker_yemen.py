"""
Houthi Rhetoric Tracker — Asifah Analytics
v1.0.0 — March 2026

Tracks escalation rhetoric from Ansar Allah (Houthis) and responses
from KSA, UAE, US, Israel across two primary threat vectors:

1. MARITIME THREAT — Red Sea / Bab el-Mandeb / Suez
2. DIRECT STRIKE THREAT — Israel, KSA, UAE, US bases

Also monitors:
- Somaliland/Horn of Africa for ground operation precursors
- KSA-Houthi ceasefire/negotiation signals
- STC-PLC tensions

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

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

RHETORIC_CACHE_KEY  = 'yemen_rhetoric_cache'
RHETORIC_CACHE_TTL  = 6 * 3600  # 6 hours

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
MARITIME_TRIGGERS = {
    5: [  # Active Strike
        'sank', 'destroyed vessel', 'ship sunk', 'tanker destroyed',
        'port struck', 'hodeidah hit', 'shipping lane closed',
    ],
    4: [  # Attack Declared
        'launching attack', 'firing on', 'drone strike ship',
        'missile hits ship', 'anti-ship missile fired',
        'bab el-mandeb closure', 'red sea blockade declared',
    ],
    3: [  # Direct Threat
        'will target ships', 'threaten shipping', 'close the strait',
        'ban israeli ships', 'all ships warned', 'maritime exclusion zone',
        'houthi naval operation', 'naval blockade',
    ],
    2: [  # Warning
        'red sea warning', 'shipping risk elevated', 'vessels advised',
        'insurance premiums surge', 'rerouting via cape',
        'avoid red sea', 'gulf of aden alert',
    ],
    1: [  # Rhetoric
        'red sea', 'bab el-mandeb', 'suez', 'shipping lane',
        'houthi naval', 'maritime', 'vessel', 'tanker',
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

# KSA-Houthi Ceasefire Signals
CEASEFIRE_TRIGGERS = {
    3: ['ceasefire agreement signed', 'peace deal yemen', 'houthi agrees ceasefire'],
    2: ['peace talks', 'ceasefire negotiations', 'houthi saudi talks',
        'diplomatic solution', 'yemen negotiations', 'un mediator yemen'],
    1: ['ceasefire', 'truce', 'negotiations', 'dialogue', 'talks'],
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
    """Fetch articles from RSS feeds"""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

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

    # Deduplicate
    seen = set()
    unique = []
    for a in articles:
        if a['url'] not in seen:
            seen.add(a['url'])
            unique.append(a)

    print(f"[Yemen Rhetoric] Fetched {len(unique)} unique articles")
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
        'total_articles': len(articles),
        'coordination_signals': [],
    }

    for article in articles:
        text = f"{article.get('title','')} {article.get('description','')}".lower()
        pub_date = article.get('published', '')

        # Identify actor
        actor_id = None
        for aid, info in ACTORS.items():
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

            for kw in CEASEFIRE_TRIGGERS.get(level, []):
                if kw in text:
                    if level > ar['ceasefire_score']:
                        ar['ceasefire_score'] = level
                    if level > theatre_summary['ceasefire_max_level']:
                        theatre_summary['ceasefire_max_level'] = level
                    break

        # Coordination signal: Houthis + Iran in same article
        if actor_id == 'houthis' and any(kw in text for kw in ACTOR_KEYWORDS['iran']):
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
        if len(ar['top_articles']) < 5 or max_level >= 3:
            ar['top_articles'].append({
                'title': article.get('title', '')[:120],
                'url': article.get('url', ''),
                'source': article.get('source', 'Unknown'),
                'published': pub_date if isinstance(pub_date, str) else '',
                'maritime_level': ar['maritime_score'],
                'direct_strike_level': ar['direct_strike_score'],
            })

    return actor_results, theatre_summary


# ============================================
# MAIN RHETORIC SCAN
# ============================================
def run_houthi_rhetoric_scan(days=3):
    """Full Houthi rhetoric scan"""
    print(f"[Yemen Rhetoric] Starting scan ({days}-day window)...")

    articles = fetch_rhetoric_articles(days)
    actor_results, theatre_summary = classify_articles(articles)

    # Overall escalation level (max of all vectors)
    max_maritime = theatre_summary['maritime_max_level']
    max_strike   = theatre_summary['direct_strike_max_level']
    max_level    = max(max_maritime, max_strike)

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'days_analyzed': days,
        'total_articles': len(articles),
        'theatre': 'Yemen / Red Sea',
        'theatre_score': max_level * 20,  # 0-100
        'theatre_level': ESCALATION_LEVELS.get(max_level, {}).get('label', 'Unknown'),
        'theatre_color': ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
        'maritime_level': max_maritime,
        'maritime_label': ESCALATION_LEVELS.get(max_maritime, {}).get('label', 'Monitoring'),
        'direct_strike_level': max_strike,
        'direct_strike_label': ESCALATION_LEVELS.get(max_strike, {}).get('label', 'Monitoring'),
        'somaliland_level': theatre_summary['somaliland_max_level'],
        'somaliland_label': ESCALATION_LEVELS.get(
            theatre_summary['somaliland_max_level'], {}).get('label', 'Baseline'),
        'ceasefire_level': theatre_summary['ceasefire_max_level'],
        'ceasefire_label': ESCALATION_LEVELS.get(
            theatre_summary['ceasefire_max_level'], {}).get('label', 'None'),
        'actors': actor_results,
        'coordination_signals': theatre_summary['coordination_signals'][:5],
        'version': '1.0.0-yemen-rhetoric'
    }

    _redis_set(RHETORIC_CACHE_KEY, result)
    print(f"[Yemen Rhetoric] ✅ Complete. Theatre level: {result['theatre_level']}")
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
        time.sleep(30)
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
                'version': '1.0.0-yemen-rhetoric'
            })

        result = run_houthi_rhetoric_scan(days=days)
        return jsonify(result)

    @app.route('/api/rhetoric/yemen/summary', methods=['GET'])
    def yemen_rhetoric_summary():
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            return jsonify({
                'success': True,
                'theatre_score': cached.get('theatre_score', 0),
                'theatre_level': cached.get('theatre_level', 'Unknown'),
                'theatre_color': cached.get('theatre_color', '#6b7280'),
                'maritime_level': cached.get('maritime_level', 0),
                'direct_strike_level': cached.get('direct_strike_level', 0),
                'somaliland_level': cached.get('somaliland_level', 0),
                'ceasefire_level': cached.get('ceasefire_level', 0),
                'timestamp': cached.get('timestamp'),
                'cached': True
            })
        return jsonify({'success': False, 'message': 'No cached data yet'})

    print("[Yemen Rhetoric] ✅ Routes registered: /api/rhetoric/yemen, /api/rhetoric/yemen/summary")
