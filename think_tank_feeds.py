"""
think_tank_feeds.py — Asifah Analytics v1.0.0
==============================================
Curated regional think-tank analysis feed.

Fetches RSS-based long-form analytical content from think tanks and
policy institutes covering Lebanon, Syria, and Israel. Tagged by country
so each stability page can pull the relevant subset.

v1.0 sources:
  - Badil (thebadil.com) — Lebanese policy institute, covers LB/SY/IL

Future sources (file as backlog):
  - International Crisis Group (ICG)
  - Carnegie Middle East Center
  - Chatham House MENA
  - Al-Monitor analysis section
  - Middle East Institute (MEI)

Pattern matches the standard Asifah backend module:
  - Upstash Redis REST cache (12hr TTL)
  - Background refresh thread
  - register_think_tank_endpoints(app) wiring
  - /api/think-tank/<country> + /api/think-tank/all endpoints
"""

import os
import json
import time
import requests
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# ============================================================
# CONFIG
# ============================================================

VERSION = '1.0.0'
CACHE_TTL_HOURS = 6           # Refresh every 6 hours
BACKGROUND_REFRESH_HOURS = 6
REQUEST_TIMEOUT = (5, 15)
USER_AGENT = 'Mozilla/5.0 (compatible; AsifahAnalytics-ThinkTank/1.0; +https://www.asifahanalytics.com)'

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')


# ============================================================
# THINK TANK SOURCES
# ============================================================
# Each source defines:
#   feed_url   — RSS URL
#   name       — display label
#   site       — homepage for source pill linking
#   countries  — list of country tags this source is relevant for
#   tag_logic  — function (title, description) -> list of country tags
#                Returns subset of countries actually mentioned.
#                If empty list returned, article is dropped.

def _badil_country_tags(title, description):
    """Tag Badil articles by country mention."""
    text = f"{title} {description}".lower()
    tags = []
    # Lebanon — almost everything Badil writes touches Lebanon
    if any(k in text for k in ['lebanon', 'lebanese', 'beirut', 'hezbollah',
                                'hizbullah', 'laf', 'litani', 'unifil',
                                'amal', 'shia', 'maronite', 'salam', 'aoun',
                                'nasrallah', 'qassem', 'baabda']):
        tags.append('lebanon')
    # Syria
    if any(k in text for k in ['syria', 'syrian', 'damascus', 'sharaa',
                                'hts', 'assad', 'sdf', 'kurdish', 'aleppo',
                                'idlib', 'homs', 'rojava']):
        tags.append('syria')
    # Israel
    if any(k in text for k in ['israel', 'israeli', 'idf', 'netanyahu',
                                'tel aviv', 'jerusalem', 'gaza', 'katz',
                                'mossad', 'shin bet', 'knesset']):
        tags.append('israel')
    return tags


THINK_TANK_SOURCES = [
    {
        'id': 'badil',
        'name': 'Badil',
        'subtitle': 'The Alternative Policy Institute',
        'site': 'https://thebadil.com',
        'feed_url': 'https://thebadil.com/feed/',
        'countries': ['lebanon', 'syria', 'israel'],
        'tag_logic': _badil_country_tags,
        'description': 'Lebanese policy institute publishing long-form analysis on Lebanon, Syria, and regional dynamics.',
    },
    # Future sources will slot in here.
]


# ============================================================
# REDIS HELPERS
# ============================================================

def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
    except Exception as e:
        print(f'[ThinkTank Redis] GET error for {key}: {e}')
    return None


def _redis_set(key, value, ttl_seconds=None):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    if ttl_seconds is None:
        ttl_seconds = CACHE_TTL_HOURS * 3600
    try:
        payload = json.dumps(value, default=str)
        resp = requests.post(
            f'{UPSTASH_REDIS_URL}/set/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json'
            },
            data=payload,
            params={'EX': ttl_seconds},
            timeout=5
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f'[ThinkTank Redis] SET error for {key}: {e}')
    return False


# ============================================================
# RSS FETCH
# ============================================================

def _parse_pub_date(raw):
    """Best-effort RFC822 / ISO date parse → ISO 8601 string."""
    if not raw:
        return ''
    try:
        dt = parsedate_to_datetime(raw)
        if dt:
            return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    return raw  # fallback to raw string


def _strip_html(text):
    """Strip basic HTML tags from RSS description."""
    import re
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fetch_source(source, max_items=20):
    """Fetch one think tank's RSS feed and return tagged articles."""
    feed_url = source['feed_url']
    name = source['name']

    try:
        headers = {'User-Agent': USER_AGENT}
        resp = requests.get(feed_url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f'[ThinkTank] {name}: HTTP {resp.status_code}')
            return []

        # Parse XML — RSS 2.0 or Atom
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            print(f'[ThinkTank] {name}: XML parse error — {str(e)[:80]}')
            return []

        # RSS 2.0: //item; Atom: //entry
        items = root.findall('.//item') or root.findall(
            './/{http://www.w3.org/2005/Atom}entry'
        )
        if not items:
            print(f'[ThinkTank] {name}: no items found in feed')
            return []

        articles = []
        for item in items[:max_items]:
            # RSS 2.0 fields
            title_el = item.find('title') or item.find(
                '{http://www.w3.org/2005/Atom}title'
            )
            link_el = item.find('link')
            if link_el is None or not (link_el.text or '').strip():
                # Atom: <link href="..."/>
                link_el = item.find('{http://www.w3.org/2005/Atom}link')

            desc_el = item.find('description') or item.find(
                '{http://www.w3.org/2005/Atom}summary'
            )
            pub_el = item.find('pubDate') or item.find(
                '{http://www.w3.org/2005/Atom}published'
            ) or item.find('{http://www.w3.org/2005/Atom}updated')

            if title_el is None:
                continue

            title = (title_el.text or '').strip()
            url = ''
            if link_el is not None:
                url = (link_el.text or link_el.get('href', '') or '').strip()
            description = _strip_html(desc_el.text or '') if desc_el is not None else ''
            published = _parse_pub_date(pub_el.text if pub_el is not None else '')

            if not title or not url:
                continue

            # Tag by country
            country_tags = source['tag_logic'](title, description)
            if not country_tags:
                # Article doesn't match any tracked country — skip
                continue

            articles.append({
                'title': title,
                'url': url,
                'description': description[:300],  # truncate for payload size
                'published': published,
                'source': name,
                'source_id': source['id'],
                'source_site': source['site'],
                'countries': country_tags,
            })

        print(f'[ThinkTank] {name}: {len(articles)} country-tagged articles fetched')
        return articles

    except Exception as e:
        print(f'[ThinkTank] {name}: fetch error — {str(e)[:120]}')
        return []


# ============================================================
# AGGREGATE & CACHE
# ============================================================

def scan_all_think_tanks():
    """Fetch all sources, deduplicate, cache by country."""
    print(f'[ThinkTank] Scan start (v{VERSION})...')
    t0 = time.time()

    all_articles = []
    for source in THINK_TANK_SOURCES:
        articles = fetch_source(source)
        all_articles.extend(articles)
        time.sleep(1.0)  # be kind to source servers

    # Deduplicate by URL
    seen = set()
    unique = []
    for a in all_articles:
        if a['url'] in seen:
            continue
        seen.add(a['url'])
        unique.append(a)

    # Sort by published date desc (most recent first)
    def _sort_key(art):
        return art.get('published') or ''
    unique.sort(key=_sort_key, reverse=True)

    # Build per-country buckets
    countries_seen = set()
    for a in unique:
        for c in a.get('countries', []):
            countries_seen.add(c)

    payload = {
        'version': VERSION,
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'scan_seconds': round(time.time() - t0, 2),
        'total_articles': len(unique),
        'sources': [
            {'id': s['id'], 'name': s['name'], 'site': s['site'],
             'description': s.get('description', '')}
            for s in THINK_TANK_SOURCES
        ],
        'all_articles': unique,
        'by_country': {
            country: [a for a in unique if country in a.get('countries', [])]
            for country in countries_seen
        },
    }

    # Cache full payload
    _redis_set('think_tank:all:latest', payload)
    # Cache per-country slices for fast lookup
    for country, arts in payload['by_country'].items():
        _redis_set(f'think_tank:{country}:latest', {
            'version': VERSION,
            'last_updated': payload['last_updated'],
            'country': country,
            'articles': arts,
            'count': len(arts),
        })

    print(f'[ThinkTank] Scan done in {payload["scan_seconds"]}s — '
          f'{len(unique)} articles across {len(countries_seen)} countries')
    return payload


def get_country_feed(country_id):
    """Return cached country-specific feed; trigger background scan if empty."""
    cached = _redis_get(f'think_tank:{country_id}:latest')
    if cached:
        return cached

    # No cache — return empty shell, scan will populate next cycle
    return {
        'version': VERSION,
        'last_updated': None,
        'country': country_id,
        'articles': [],
        'count': 0,
        'note': 'Cache cold — scan in progress. Refresh in 30-60s.',
    }


def get_all_feeds():
    """Return full payload from cache."""
    cached = _redis_get('think_tank:all:latest')
    if cached:
        return cached
    return {
        'version': VERSION,
        'last_updated': None,
        'total_articles': 0,
        'sources': [
            {'id': s['id'], 'name': s['name'], 'site': s['site']}
            for s in THINK_TANK_SOURCES
        ],
        'all_articles': [],
        'by_country': {},
        'note': 'Cache cold — scan in progress. Refresh in 30-60s.',
    }


# ============================================================
# BACKGROUND REFRESH
# ============================================================

_refresh_started = False
_refresh_lock = threading.Lock()


def _background_refresh_loop():
    while True:
        try:
            scan_all_think_tanks()
        except Exception as e:
            print(f'[ThinkTank] Background scan error: {e}')
        time.sleep(BACKGROUND_REFRESH_HOURS * 3600)


def start_background_refresh():
    """Start background refresh thread; idempotent."""
    global _refresh_started
    with _refresh_lock:
        if _refresh_started:
            return
        _refresh_started = True

    # Boot delay — give app a moment to start before first scan
    def _delayed_start():
        time.sleep(60)
        _background_refresh_loop()

    thread = threading.Thread(target=_delayed_start, daemon=True)
    thread.start()
    print(f'[ThinkTank] Background refresh thread started (every {BACKGROUND_REFRESH_HOURS}h)')


# ============================================================
# FLASK ENDPOINTS
# ============================================================

def register_think_tank_endpoints(app, start_background=True):
    """Register /api/think-tank/* endpoints on the given Flask app.

    Endpoints:
        GET /api/think-tank/all
            → full payload, all sources, all countries
        GET /api/think-tank/<country>
            → articles tagged for that country only
        GET /api/think-tank/refresh?key=...
            → force refresh (admin only)
    """
    from flask import jsonify, request

    @app.route('/api/think-tank/all', methods=['GET', 'OPTIONS'])
    def think_tank_all():
        if request.method == 'OPTIONS':
            return ('', 204)
        return jsonify(get_all_feeds())

    @app.route('/api/think-tank/<country>', methods=['GET', 'OPTIONS'])
    def think_tank_by_country(country):
        if request.method == 'OPTIONS':
            return ('', 204)
        country = (country or '').lower().strip()
        valid = {'lebanon', 'syria', 'israel'}
        if country not in valid:
            return jsonify({
                'error': 'Unknown country',
                'valid': sorted(valid),
            }), 400
        return jsonify(get_country_feed(country))

    @app.route('/api/think-tank/refresh', methods=['POST', 'GET'])
    def think_tank_refresh():
        # Optional admin guard via env var
        admin_key = os.environ.get('ADMIN_REFRESH_KEY')
        if admin_key:
            provided = request.args.get('key') or request.headers.get('X-Admin-Key')
            if provided != admin_key:
                return jsonify({'error': 'unauthorized'}), 401
        # Run synchronously — typically called manually after deploy
        payload = scan_all_think_tanks()
        return jsonify({
            'success': True,
            'total_articles': payload['total_articles'],
            'scan_seconds': payload['scan_seconds'],
        })

    if start_background:
        start_background_refresh()

    print(f'[ThinkTank] Endpoints registered (v{VERSION})')


# ============================================================
# CLI / DIRECT INVOCATION (for local testing)
# ============================================================

if __name__ == '__main__':
    print(f'think_tank_feeds.py v{VERSION} — manual scan')
    payload = scan_all_think_tanks()
    print(json.dumps({
        'total': payload['total_articles'],
        'by_country': {k: len(v) for k, v in payload['by_country'].items()},
        'first_3': [
            {'title': a['title'][:80], 'countries': a['countries'],
             'published': a['published']}
            for a in payload['all_articles'][:3]
        ],
    }, indent=2))
