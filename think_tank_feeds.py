"""
think_tank_feeds.py — Asifah Analytics v2.0.0
==============================================
Curated analysis + commentary feeds (ME backend).

TWO LANES, ONE FILE
  1. THINK TANKS (v1.x, unchanged endpoints): long-form regional analysis,
     tagged by country, shown on stability pages.
       /api/think-tank/all, /api/think-tank/<country>
  2. COMMENTARY (v2.0.0, Nov 5 2026): newsletters (Substack and similar),
     opinion outlets, institutes and YouTube channels from across the
     political spectrum. Each carries a LEAN label. Never scored.
       /api/commentary/all, /api/commentary/<country>,
       /api/commentary/balance, /api/commentary/debug
     Sources live in commentary_sources.py -- the only file to edit.

WHY THIS FILE AND NOT rss_monitor.py (Rachel asked, Nov 5 2026)
  rss_monitor.py feeds the SCORING pipeline (leadership quotes, threat
  language). Commentary must never lift a level on its own, so it stays out
  of that pipe. This file was already the "people who write analysis" reader
  with display-only endpoints -- the right home for opinions.

v2.0.0 (Nov 5 2026)
  * BUG FIX -- every RSS article was being dropped. fetch_source() used
    `item.find('title') or item.find(<atom title>)`. An XML element with no
    children counts as FALSE in Python, so a found RSS <title> was thrown
    away and the Atom lookup (None) used instead -> "continue". Since v1.0
    the think-tank cards have shown nothing from RSS feeds. Now explicit
    `is None` checks everywhere.
  * Commentary lane: 28 sources (left 4 / center-left 4 / center 8 /
    center-right 3 / right 6 / nonpartisan 3), global country tagger with
    word-boundary matching, US-politics tag, lean buckets.
  * YouTube WITHOUT a key: each channel's public feed
    (youtube.com/feeds/videos.xml?channel_id=...) gives the latest 15 video
    titles + descriptions. A handle ('@Perun') is resolved to its channel id
    once and cached for 30 days. Comments need the Data API key (later).
  * Cross-Spectrum Balance: /api/commentary/balance counts the last 7 days
    by lean -- overall, per leg (newsletters+outlets, video, Reddit = unread)
    and per country, with a plain sentence when one side's attention on a
    country outweighs the other's 3 to 1 (min. 4 pieces).
  * Every feed reports to feed_health (dead feeds announce themselves) and
    to /api/commentary/debug.

v2.1.0 (Nov 5 2026) -- ATTENTION HISTORY
  * Country ids are canonical (country_ids.canonical): 'usa', 'united_kingdom',
    'dprk' -- the same ids the GPI and attention_layer.py use. The endpoint
    accepts page slugs ('us', 'uk', 'north_korea') and canonicalises them.
  * commentary:history -- per published day, per country, per lean: counts,
    60 days. Each scan merges what it can see (max per day, so a feed rolling
    old items off never shrinks a past day).
  * payload['attention'][country] = this week's pieces vs a usual week
    (average of the previous 4 weeks), ratio, spike flag (>= 2.5x and >= 6
    pieces), and baseline_days -- "baseline building" until 14 days exist.
    Read by attention_layer.py; never scored.

v2.2.0 (Nov 5 2026) -- SOURCE CENSUS
  * One source = at most 2 pieces per country per week in the balance (and
    per day in the history). Megyn Kelly posted four clips about Iran in an
    hour and counted as four voices; a prolific channel could tip a country
    into "lopsided" on its own.
  * ISS Africa (XML error) and Africa Center (200 but never an item) now read
    through Google News 'site:' queries; ISW and Chatham House likewise in
    commentary_sources.py (both 403 to Render).

v2.3.0 (Nov 5 2026) -- PODCASTS
  * New kind 'podcast'. A source names the show ('podcast': 'Pod Save America',
    optional 'by': a word from the publisher). The feed address is looked up
    ONCE in Apple's public podcast directory (itunes.apple.com/search, no key),
    matched on the show title (+ publisher when given), and cached 30 days
    with the matched title and publisher -- /api/commentary/debug shows both,
    so a wrong match is visible, never silent. 'feed' still overrides.
  * Balance gets a 'podcasts' leg.
  * Hebrew keywords in the country tagger (Haaretz's HaShavua is in Hebrew).

v2.3.1 (Nov 5 2026) -- the baseline counts from the day WE STARTED WATCHING
  * Bug: "baseline_days" was measured from the oldest item any feed still
    carried (~53 days), but a feed only holds its last ~20 items, so weeks
    before we started were near-empty. "Usual week" came out ~0 and every
    country read as a spike (US 28x, Iran 35x). Now the baseline starts on
    the first scan (commentary:history_started) and only counts days from
    then on; until 14 days have passed every country says baseline_building.
"""

import os
import re
import json
import time
import requests
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

try:
    from commentary_sources import COMMENTARY_SOURCES
except Exception as _e:   # never take the backend down over a bad edit
    print(f'[ThinkTank] commentary_sources failed to load: {_e}')
    COMMENTARY_SOURCES = []

try:
    from feed_health import record_fetch as _feed_record
except ImportError:
    _feed_record = None

# ============================================================
# CONFIG
# ============================================================

VERSION = '2.3.1'
CACHE_TTL_HOURS = 6           # Refresh every 6 hours
BACKGROUND_REFRESH_HOURS = 6
REQUEST_TIMEOUT = (5, 15)
USER_AGENT = 'Mozilla/5.0 (compatible; AsifahAnalytics-ThinkTank/2.0; +https://www.asifahanalytics.com)'

COMMENTARY_KEY = 'commentary:latest'
YT_IDS_KEY = 'commentary:yt_ids'
YT_IDS_TTL = 30 * 24 * 3600
BALANCE_DAYS = 7
HISTORY_KEY = 'commentary:history'
HISTORY_STARTED_KEY = 'commentary:history_started'
HISTORY_DAYS = 60
SPIKE_RATIO = 2.5
SPIKE_MIN = 6
BASELINE_MIN_DAYS = 14
LOPSIDED_RATIO = 3.0
LOPSIDED_MIN = 4
PER_SOURCE_CAP = 2      # pieces per source per country per window (v2.2.0)

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

ATOM = '{http://www.w3.org/2005/Atom}'
MEDIA = '{http://search.yahoo.com/mrss/}'
YT = '{http://www.youtube.com/xml/schemas/2015}'
CONTENT = '{http://purl.org/rss/1.0/modules/content/}'

_MEM = {}   # fallback store when Redis is not configured (tests)


# ============================================================
# THINK TANK SOURCES (v1.x -- unchanged)
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


# ── Africa classifier (shared by ISS / ACSS / Crisis Group) ──
# All three cover the same African conflict set, so they share one tagger.
# Tokens chosen to avoid known substring collisions:
#   'mali' lives inside 'somali' → Mali uses Bamako/Azawad/Goita etc., never bare 'mali'
#   'niger' lives inside 'nigeria' → Niger uses Niamey/Nigerien/Tchiani, never bare 'niger'
#   'sudan' lives inside 'south sudan' → Sudan uses Khartoum/RSF/Darfur/Burhan; South Sudan its own
_AFRICA_KEYWORDS = {
    'libya':        ['libya', 'libyan', 'tripoli', 'benghazi', 'haftar', 'dbeibah',
                     'misrata', 'sirte', 'fezzan', 'tobruk', 'gnu', 'lna'],
    'sudan':        ['khartoum', 'rsf', 'rapid support', 'hemedti', 'hemeti',
                     'al-burhan', 'burhan', 'darfur', 'omdurman', 'el fasher',
                     'el-fasher'],
    'south_sudan':  ['south sudan', 'juba', 'salva kiir', 'riek machar',
                     'splm', 'unmiss'],
    'somalia':      ['somalia', 'somali', 'mogadishu', 'al-shabaab', 'al shabaab',
                     'shabaab', 'puntland', 'somaliland', 'hassan sheikh'],
    'ethiopia':     ['ethiopia', 'ethiopian', 'addis ababa', 'abiy', 'tigray',
                     'tplf', 'amhara', 'oromia', 'fano'],
    'mali':         ['bamako', 'azawad', 'goita', 'goïta', 'kidal', 'mopti',
                     'timbuktu', 'tombouctou'],
    'niger':        ['niamey', 'nigerien', 'tchiani', 'cnsp', 'tillaberi', 'tillabéri'],
    'burkina_faso': ['burkina', 'burkinabe', 'burkinabè', 'ouagadougou',
                     'traore', 'traoré'],
    'chad':         ['chad', 'chadian', "n'djamena", 'ndjamena', 'deby', 'déby'],
    'drc':          ['dr congo', 'drc', 'democratic republic of congo', 'kinshasa',
                     'm23', 'tshisekedi', 'goma', 'kivu', 'congolese', 'fardc',
                     'wazalendo'],
    'zimbabwe':     ['zimbabwe', 'zimbabwean', 'harare', 'mnangagwa', 'zanu-pf',
                     'chiwenga'],
    'morocco':      ['morocco', 'moroccan', 'rabat', 'western sahara', 'polisario',
                     'sahrawi', 'sahraoui', 'el guerguerat'],
    'algeria':      ['algeria', 'algerian', 'algiers', 'tebboune', 'tindouf'],
    'tunisia':      ['tunisia', 'tunisian', 'kais saied', 'saied', 'lampedusa', 'sfax'],
    'egypt':        ['egypt', 'egyptian', 'cairo', 'sisi', 'el-sisi'],
    'mauritania':   ['mauritania', 'mauritanian', 'nouakchott'],
    'uganda':       ['uganda', 'ugandan', 'kampala', 'museveni'],
}

AFRICA_COUNTRY_IDS = list(_AFRICA_KEYWORDS.keys())


def _africa_country_tags(title, description):
    """Tag an article by African country mention. Shared by ISS / ACSS / Crisis Group."""
    text = f"{title} {description}".lower()
    tags = []
    for country, kws in _AFRICA_KEYWORDS.items():
        if any(k in text for k in kws):
            tags.append(country)
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
    {
        'id': 'iss_africa',
        'name': 'ISS Africa',
        'subtitle': 'Institute for Security Studies',
        'site': 'https://issafrica.org',
        'feed_url': 'https://news.google.com/rss/search?q=site:issafrica.org&hl=en&gl=US&ceid=US:en',   # census Nov 5: own feed = XML error
        'countries': AFRICA_COUNTRY_IDS,
        'tag_logic': _africa_country_tags,
        'description': 'Pan-African human-security institute (Pretoria). Migration, Sahel, Horn of Africa, terrorism, governance, coups.',
    },
    {
        'id': 'acss',
        'name': 'Africa Center',
        'subtitle': 'Africa Center for Strategic Studies (US NDU)',
        'site': 'https://africacenter.org',
        'feed_url': 'https://news.google.com/rss/search?q=site:africacenter.org&hl=en&gl=US&ceid=US:en',   # census Nov 5: own feed never delivered an item
        'countries': AFRICA_COUNTRY_IDS,
        'tag_logic': _africa_country_tags,
        'description': 'US National Defense University Africa security institute. Strong on Wagner/Africa Corps, Sahel coups, militant Islamist groups.',
    },
    {
        'id': 'crisis_group_africa',
        'name': 'Crisis Group',
        'subtitle': 'International Crisis Group',
        'site': 'https://www.crisisgroup.org',
        'feed_url': 'https://www.crisisgroup.org/rss',   # global feed; Africa classifier filters to African items
        'countries': AFRICA_COUNTRY_IDS,
        'tag_logic': _africa_country_tags,
        'description': 'Global conflict-prevention institute, Africa coverage filtered from the main feed (Sudan, Sahel, Libya, DRC, Horn).',
    },
    # Future sources will slot in here.
]


# ============================================================
# GLOBAL COUNTRY TAGGER (v2.0.0 -- commentary lane)
# ============================================================
# Word-boundary matched, so 'oman' never fires inside 'woman', 'iran'
# never inside 'tirana', 'niger' never inside 'nigeria'. Demonyms and
# capitals are listed because commentary rarely says "Iran" when it can
# say "Tehran".
_GLOBAL_EXTRA = {
    'iran':        ['iran', 'iranian', 'tehran', 'khamenei', 'irgc', 'pezeshkian', 'araghchi',
                    'איראן', 'טהרן', 'חמינאי'],
    'israel':      ['israel', 'israeli', 'netanyahu', 'idf', 'knesset', 'tel aviv',
                    'ישראל', 'נתניהו', 'צה"ל', 'הכנסת'],
    'gaza':        ['gaza', 'hamas', 'rafah', 'khan younis', 'עזה', 'חמאס'],
    'lebanon':     ['lebanon', 'lebanese', 'beirut', 'hezbollah', 'hizballah', 'hizbullah',
                    'לבנון', 'חיזבאללה', 'ביירות'],
    'syria':       ['syria', 'syrian', 'damascus', 'sharaa', 'aleppo', 'idlib', 'סוריה'],
    'iraq':        ['iraq', 'iraqi', 'baghdad', 'erbil', 'kurdistan region'],
    'yemen':       ['yemen', 'yemeni', 'houthi', 'houthis', 'sanaa', 'aden'],
    'saudi_arabia': ['saudi', 'riyadh', 'mbs', 'mohammed bin salman'],
    'uae':         ['uae', 'emirati', 'abu dhabi', 'dubai', 'united arab emirates'],
    'qatar':       ['qatar', 'qatari', 'doha'],
    'oman':        ['oman', 'omani', 'muscat'],
    'jordan':      ['jordanian', 'amman', 'king abdullah'],
    'turkey':      ['turkey', 'turkish', 'türkiye', 'ankara', 'erdogan', 'erdoğan'],
    'russia':      ['russia', 'russian', 'kremlin', 'moscow', 'putin'],
    'ukraine':     ['ukraine', 'ukrainian', 'kyiv', 'kiev', 'zelensky', 'zelenskyy', 'donbas'],
    'belarus':     ['belarus', 'belarusian', 'minsk', 'lukashenko'],
    'poland':      ['poland', 'polish', 'warsaw'],
    'hungary':     ['hungary', 'hungarian', 'budapest', 'orban', 'orbán'],
    'uk':          ['britain', 'british', 'starmer', 'downing street', 'united kingdom'],
    'greenland':   ['greenland'],
    'china':       ['china', 'chinese', 'beijing', 'xi jinping', 'ccp', 'pla'],
    'taiwan':      ['taiwan', 'taiwanese', 'taipei'],
    'japan':       ['japan', 'japanese', 'tokyo'],
    'north_korea': ['north korea', 'pyongyang', 'kim jong un', 'dprk'],
    'south_korea': ['south korea', 'seoul'],
    'india':       ['india', 'indian', 'new delhi', 'modi'],
    'pakistan':    ['pakistan', 'pakistani', 'islamabad'],
    'afghanistan': ['afghanistan', 'afghan', 'kabul', 'taliban'],
    'philippines': ['philippines', 'philippine', 'manila', 'marcos'],
    'vietnam':     ['vietnam', 'vietnamese', 'hanoi'],
    'venezuela':   ['venezuela', 'venezuelan', 'caracas', 'maduro'],
    'cuba':        ['cuba', 'cuban', 'havana'],
    'mexico':      ['mexico', 'mexican', 'sheinbaum', 'sinaloa', 'cjng'],
    'colombia':    ['colombia', 'colombian', 'bogota', 'bogotá', 'gustavo petro'],
    'argentina':   ['argentina', 'argentine', 'buenos aires', 'milei'],
    'brazil':      ['brazil', 'brazilian', 'lula'],
    'canada':      ['canada', 'canadian', 'ottawa', 'carney'],
    'panama':      ['panama canal', 'panamanian'],
    'haiti':       ['haiti', 'haitian', 'port-au-prince'],
    'nigeria':     ['nigeria', 'nigerian', 'abuja', 'lagos'],
    'kenya':       ['kenya', 'kenyan', 'nairobi'],
    'us':          ['trump', 'white house', 'congress', 'senate', 'pentagon', 'טראמפ',
                    'democrats', 'republicans', 'gop', 'supreme court', 'state department'],
}
_GLOBAL_KEYWORDS = {}
for _c, _kws in list(_AFRICA_KEYWORDS.items()) + list(_GLOBAL_EXTRA.items()):
    _GLOBAL_KEYWORDS.setdefault(_c, [])
    for _k in _kws:
        if _k not in _GLOBAL_KEYWORDS[_c]:
            _GLOBAL_KEYWORDS[_c].append(_k)
# Words that collide in general commentary (fine inside the Africa-only
# think-tank tagger): GNU software, a man named Chad, RSF = Reporters
# Without Borders, OPEC "the cartel".
for _c, _bad in (('libya', ['gnu', 'lna']), ('chad', ['chad']), ('sudan', ['rsf'])):
    _GLOBAL_KEYWORDS[_c] = [k for k in _GLOBAL_KEYWORDS[_c] if k not in _bad]
# Latin words are word-bounded; Hebrew words may carry a one-letter prefix
# (ב / ל / ה / ו / מ / ש) glued on, so they are matched with that allowance.
def _kw_rx(k):
    if re.search('[\u0590-\u05ff]', k):
        return r'(?<![\u0590-\u05ff])[בלהומש]?' + re.escape(k) + r'(?![\u0590-\u05ff])'
    return r'(?<![a-z0-9])' + re.escape(k) + r'(?![a-z0-9])'


_GLOBAL_RX = {c: re.compile('|'.join(_kw_rx(k) for k in kws)) for c, kws in _GLOBAL_KEYWORDS.items()}


try:
    from country_ids import canonical as _canonical
except Exception:
    _canonical = None


def canon(c):
    """One id per country across Asifah ('us' -> 'usa', 'north_korea' -> 'dprk')."""
    if not c:
        return c
    if _canonical:
        try:
            return _canonical(c) or c
        except Exception:
            return c
    return {'us': 'usa', 'uk': 'united_kingdom', 'north_korea': 'dprk'}.get(c, c)


def global_country_tags(title, description=''):
    text = f"{title} {description}".lower()
    out = []
    for c, rx in _GLOBAL_RX.items():
        if rx.search(text):
            cc = canon(c)
            if cc not in out:
                out.append(cc)
    return out


LEAN_BUCKET = {'left': 'left', 'center-left': 'left', 'center': 'center',
               'center-right': 'right', 'right': 'right', 'nonpartisan': 'nonpartisan'}


# ============================================================
# REDIS HELPERS
# ============================================================

def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return _MEM.get(key)
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
    if ttl_seconds is None:
        ttl_seconds = CACHE_TTL_HOURS * 3600
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        _MEM[key] = json.loads(json.dumps(value, default=str))
        return True
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
# RSS / ATOM PARSING
# ============================================================

def _parse_pub_date(raw):
    """Best-effort RFC822 / ISO date parse → ISO 8601 string."""
    if not raw:
        return ''
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    return raw  # fallback to raw string


def _strip_html(text):
    """Strip basic HTML tags from RSS description."""
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;|&#160;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _first(item, *tags):
    """First child that EXISTS. Never `a or b` on XML elements: an element
    with no children is falsy, which silently dropped every RSS article
    before v2.0.0."""
    for t in tags:
        el = item.find(t)
        if el is not None:
            return el
    return None


def _parse_items(content, max_items=20):
    """RSS 2.0 or Atom (incl. YouTube) -> list of {title, url, description, published}."""
    root = ET.fromstring(content)
    # a block page can be well-formed XML/XHTML: only rss / feed / RDF count
    tag = root.tag.split('}')[-1].lower()
    if tag not in ('rss', 'feed', 'rdf'):
        raise ET.ParseError('not a feed (root <%s>)' % tag)
    items = root.findall('.//item')
    if not items:
        items = root.findall(f'.//{ATOM}entry')
    out = []
    for item in items[:max_items]:
        title_el = _first(item, 'title', f'{ATOM}title')
        if title_el is None:
            continue
        title = (title_el.text or '').strip()
        url = ''
        link_el = item.find('link')
        if link_el is not None and (link_el.text or '').strip():
            url = link_el.text.strip()
        else:
            for l in item.findall(f'{ATOM}link'):
                if l.get('rel', 'alternate') == 'alternate' and l.get('href'):
                    url = l.get('href').strip()
                    break
        if not url:   # podcasts: many episodes carry no <link>, only the audio file
            enc = item.find('enclosure')
            guid = item.find('guid')
            if enc is not None and enc.get('url'):
                url = enc.get('url').strip()
            elif guid is not None and (guid.text or '').strip().startswith('http'):
                url = guid.text.strip()
        desc_el = _first(item, 'description', f'{ATOM}summary', f'{MEDIA}group/{MEDIA}description',
                         f'{CONTENT}encoded', f'{ATOM}content',
                         '{http://www.itunes.com/dtds/podcast-1.0.dtd}summary')
        description = _strip_html(desc_el.text or '') if desc_el is not None else ''
        pub_el = _first(item, 'pubDate', f'{ATOM}published', f'{ATOM}updated',
                        '{http://purl.org/dc/elements/1.1/}date')
        published = _parse_pub_date(pub_el.text if pub_el is not None else '')
        if title and url:
            out.append({'title': title, 'url': url, 'description': description,
                        'published': published})
    return out


def _record(feed_url, label, items=0, status=None, error=None, t0=None):
    if not _feed_record:
        return
    try:
        _feed_record('me', feed_url, items=items, label=label, http_status=status,
                     error=error, duration_ms=((time.time() - t0) * 1000) if t0 else None)
    except Exception:
        pass


def fetch_source(source, max_items=20):
    """Fetch one think tank's RSS feed and return tagged articles."""
    feed_url = source['feed_url']
    name = source['name']
    t0 = time.time()
    try:
        headers = {'User-Agent': USER_AGENT}
        resp = requests.get(feed_url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f'[ThinkTank] {name}: HTTP {resp.status_code}')
            _record(feed_url, name, status=resp.status_code, t0=t0)
            return []
        try:
            parsed = _parse_items(resp.content, max_items)
        except ET.ParseError as e:
            print(f'[ThinkTank] {name}: XML parse error — {str(e)[:80]}')
            _record(feed_url, name, status=200, error='XML parse error (HTML or block page?)', t0=t0)
            return []
        _record(feed_url, name, items=len(parsed), status=200, t0=t0)

        articles = []
        for it in parsed:
            country_tags = source['tag_logic'](it['title'], it['description'])
            if not country_tags:
                continue
            articles.append({
                'title': it['title'],
                'url': it['url'],
                'description': it['description'][:300],
                'published': it['published'],
                'source': name,
                'source_id': source['id'],
                'source_site': source['site'],
                'countries': country_tags,
            })
        print(f'[ThinkTank] {name}: {len(articles)} country-tagged articles of {len(parsed)} fetched')
        return articles
    except Exception as e:
        print(f'[ThinkTank] {name}: fetch error — {str(e)[:120]}')
        _record(feed_url, name, error=str(e)[:120], t0=t0)
        return []


# ============================================================
# AGGREGATE & CACHE -- THINK TANKS (unchanged payload shape)
# ============================================================

def scan_all_think_tanks():
    """Fetch all think-tank sources, deduplicate, cache by country."""
    print(f'[ThinkTank] Scan start (v{VERSION})...')
    t0 = time.time()

    all_articles = []
    for source in THINK_TANK_SOURCES:
        all_articles.extend(fetch_source(source))
        time.sleep(1.0)  # be kind to source servers

    seen = set()
    unique = []
    for a in all_articles:
        if a['url'] in seen:
            continue
        seen.add(a['url'])
        unique.append(a)
    unique.sort(key=lambda art: art.get('published') or '', reverse=True)

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

    _redis_set('think_tank:all:latest', payload)
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
    """Return cached country-specific feed."""
    cached = _redis_get(f'think_tank:{country_id}:latest')
    if cached:
        return cached
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
# COMMENTARY LANE (v2.0.0)
# ============================================================
_YT_ID_RX = re.compile(r'"(?:channelId|externalId)":"(UC[\w-]{22})"')
_YT_CANON_RX = re.compile(r'youtube\.com/channel/(UC[\w-]{22})')


def _resolve_youtube(handle, ids):
    """'@Perun' -> 'UC...'. Cached in Redis for 30 days."""
    h = (handle or '').strip()
    if h.startswith('UC') and len(h) == 24:
        return h, None
    if h in ids:
        return ids[h], None
    url = 'https://www.youtube.com/%s' % (h if h.startswith('@') else '@' + h)
    try:
        r = requests.get(url, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'en-US,en;q=0.9'},
                         timeout=REQUEST_TIMEOUT, cookies={'CONSENT': 'YES+1'})
        if r.status_code != 200:
            return None, 'handle lookup HTTP %s' % r.status_code
        m = _YT_CANON_RX.search(r.text) or _YT_ID_RX.search(r.text)
        if not m:
            return None, 'channel id not found on the handle page'
        ids[h] = m.group(1)
        return ids[h], None
    except Exception as e:
        return None, 'handle lookup failed: %s' % str(e)[:80]


def _norm_title(t):
    return re.sub(r'[^0-9a-z\u0590-\u05ff]+', ' ', (t or '').lower()).strip()


def _resolve_podcast(src, cache):
    """Show name -> feed URL via Apple's public directory (once; cached)."""
    key = 'pod:%s' % src['id']
    hit = cache.get(key)
    if isinstance(hit, dict) and hit.get('feed'):
        return hit, None
    title = src['podcast']
    bys = [b.strip() for b in (src.get('by') or '').lower().split('|') if b.strip()]
    time.sleep(3)     # Apple's directory allows ~20 lookups a minute; cached for 30 days after
    try:
        r = requests.get('https://itunes.apple.com/search',
                         params={'term': src.get('search') or title,
                                 'entity': 'podcast', 'limit': 15},
                         headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None, 'podcast directory HTTP %s' % r.status_code
        results = r.json().get('results') or []
    except Exception as e:
        return None, 'podcast directory lookup failed: %s' % str(e)[:80]
    want = _norm_title(title)
    best, best_score = None, 0
    for res in results:
        name = _norm_title(res.get('collectionName'))
        artist = (res.get('artistName') or '').lower()
        score = 3 if name == want else (2 if want and name and (want in name or name in want) else 0)
        if not score or not res.get('feedUrl'):
            continue
        if bys:  # a publisher hint is a requirement, not a bonus: "Pivot" alone matches many shows
            hay = artist + ' ' + (res.get('collectionName') or '').lower()
            if not any(b in hay for b in bys):
                continue
            score += 2
        if score > best_score:
            best, best_score = res, score
    if not best:
        return None, 'no confident match for "%s" in the podcast directory' % title
    rec = {'feed': best['feedUrl'], 'matched_title': best.get('collectionName'),
           'matched_publisher': best.get('artistName'), 'score': best_score}
    cache[key] = rec
    return rec, None


def _fetch_commentary_source(src, yt_ids):
    """One source -> (items, health)."""
    t0 = time.time()
    health = {'id': src['id'], 'name': src['name'], 'kind': src.get('kind'),
              'lean': src.get('lean'), 'verify': bool(src.get('verify'))}
    if src.get('youtube'):
        cid, err = _resolve_youtube(src['youtube'], yt_ids)
        if not cid:
            health.update(status='dead', error=err)
            _record('youtube:' + src['youtube'], src['name'], error=err, t0=t0)
            return [], health
        feed = 'https://www.youtube.com/feeds/videos.xml?channel_id=%s' % cid
        health['channel_id'] = cid
    elif src.get('podcast') and not src.get('feed'):
        rec, err = _resolve_podcast(src, yt_ids)
        if not rec:
            health.update(status='dead', error=err)
            _record('podcast:' + src['podcast'], src['name'], error=err, t0=t0)
            return [], health
        feed = rec['feed']
        health.update(matched_title=rec.get('matched_title'),
                      matched_publisher=rec.get('matched_publisher'))
    else:
        feed = src.get('feed')
    health['feed'] = feed
    try:
        r = requests.get(feed, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            health.update(status='dead', error='HTTP %s' % r.status_code)
            _record(feed, src['name'], status=r.status_code, t0=t0)
            return [], health
        try:
            parsed = _parse_items(r.content, 15 if (src.get('youtube') or src.get('podcast')) else 20)
        except ET.ParseError:
            health.update(status='dead', error='not a feed (HTML or block page?)')
            _record(feed, src['name'], status=200, error='XML parse error', t0=t0)
            return [], health
    except Exception as e:
        health.update(status='dead', error=str(e)[:100])
        _record(feed, src['name'], error=str(e)[:100], t0=t0)
        return [], health
    _record(feed, src['name'], items=len(parsed), status=200, t0=t0)
    items = []
    for it in parsed:
        tags = global_country_tags(it['title'], it['description'][:600])
        items.append({
            'title': it['title'], 'url': it['url'],
            'description': it['description'][:300], 'published': it['published'],
            'source': src['name'], 'source_id': src['id'], 'kind': src.get('kind'),
            'lean': src.get('lean'), 'lean_bucket': LEAN_BUCKET.get(src.get('lean'), 'center'),
            'countries': tags,
        })
    newest = max((i['published'] for i in items if i['published']), default=None)
    health.update(status='ok' if items else 'empty', items=len(items), newest=newest)
    return items, health


def _age_days(iso, now):
    try:
        d = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (now - d).total_seconds() / 86400
    except Exception:
        return None


def _country_label(c):
    try:
        from country_ids import display
        return display(c) or c.replace('_', ' ').title()
    except Exception:
        return {'us': 'the US', 'uk': 'the UK', 'uae': 'the UAE', 'drc': 'DR Congo'}.get(
            c, c.replace('_', ' ').title())


def build_balance(items, health, now=None):
    """Cross-Spectrum Balance from the last BALANCE_DAYS of commentary."""
    now = now or datetime.now(timezone.utc)
    def _fresh(i):
        a = _age_days(i.get('published') or '', now)
        return a is not None and a <= BALANCE_DAYS      # (a or 99) would drop age 0.0
    recent = [i for i in items if _fresh(i)]
    def counts(rows):
        c = {'left': 0, 'center': 0, 'right': 0, 'nonpartisan': 0}
        for r in rows:
            c[r.get('lean_bucket', 'center')] = c.get(r.get('lean_bucket', 'center'), 0) + 1
        return c
    def legs_of(kinds):
        hs = [h for h in health if h.get('kind') in kinds]
        return {'sources_ok': sum(1 for h in hs if h.get('status') == 'ok'), 'sources_total': len(hs)}
    written = [i for i in recent if i.get('kind') in ('newsletter', 'outlet', 'institute')]
    video = [i for i in recent if i.get('kind') == 'video']
    pods = [i for i in recent if i.get('kind') == 'podcast']
    by_country, per_src = {}, {}
    for i in recent:
        for c in i.get('countries') or []:
            k = (c, i.get('source_id') or i.get('source'))
            per_src[k] = per_src.get(k, 0) + 1
            if per_src[k] > PER_SOURCE_CAP:
                continue
            by_country.setdefault(c, []).append(i)
    topics = []
    for c, rows in by_country.items():
        k = counts(rows)
        l, r = k['left'], k['right']
        side = None
        if l + r >= LOPSIDED_MIN:
            if r >= LOPSIDED_RATIO * max(l, 1) and r > l:
                side = 'right'
            elif l >= LOPSIDED_RATIO * max(r, 1) and l > r:
                side = 'left'
        rec = {'country': c, 'total': len(rows), 'counts': k, 'lopsided': side}
        if side:
            hi, lo = (r, l) if side == 'right' else (l, r)
            rec['sentence'] = ('%s-leaning commentary on %s outnumbers %s-leaning %d to %d this week. '
                               'Lopsided attention often runs ahead of policy debate; it is a signal '
                               'about who is talking, not about what is true.'
                               % (side.capitalize(), _country_label(c),
                                  'left' if side == 'right' else 'right', hi, lo))
        topics.append(rec)
    topics.sort(key=lambda t: (-(1 if t['lopsided'] else 0), -t['total']))
    return {
        'window_days': BALANCE_DAYS,
        'overall': counts(recent),
        'total': len(recent),
        'legs': {
            'newsletters_outlets_institutes': dict(legs_of(('newsletter', 'outlet', 'institute')),
                                                   counts=counts(written), state='live'),
            'video': dict(legs_of(('video',)), counts=counts(video), state='live'),
            'podcasts': dict(legs_of(('podcast',)), counts=counts(pods), state='live'),
            'reddit': {'state': 'unread', 'counts': None,
                       'note': 'Reddit API access is pending; unread, not zero.'},
        },
        'by_country': topics[:25],
        'lopsided': [t for t in topics if t['lopsided']][:6],
        'note': ('Counts of pieces published by sources on each side of the spectrum. '
                 'Commentary is context, never scored.'),
    }


def update_history(items, history, now=None):
    """Merge this scan's per-day, per-country, per-lean counts into history."""
    now = now or datetime.now(timezone.utc)
    seen, per_src = {}, {}
    for i in items:
        day = (i.get('published') or '')[:10]
        if len(day) != 10:
            continue
        b = i.get('lean_bucket', 'center')
        for c in i.get('countries') or []:
            k = (day, c, i.get('source_id') or i.get('source'))
            per_src[k] = per_src.get(k, 0) + 1
            if per_src[k] > PER_SOURCE_CAP:      # one channel's clip burst is one voice
                continue
            d = seen.setdefault(day, {}).setdefault(c, {})
            d[b] = d.get(b, 0) + 1
    for day, by_c in seen.items():
        old = history.setdefault(day, {})
        for c, k in by_c.items():
            o = old.setdefault(c, {})
            for b, n in k.items():
                o[b] = max(o.get(b, 0), n)   # a feed rolling items off never shrinks a past day
    cutoff = (now - timedelta(days=HISTORY_DAYS)).strftime('%Y-%m-%d')
    return {d: v for d, v in history.items() if d >= cutoff}


def attention_metrics(history, now=None, started=None):
    """This week vs a usual week (previous 4 weeks), per country.
    started = the day we began watching (v2.3.1); days before it don't count."""
    now = now or datetime.now(timezone.utc)
    full = history
    if started:
        history = {d: v for d, v in history.items() if d >= started[:10]}
    days = sorted(history)
    if not days:
        return {}
    first = datetime.fromisoformat(started[:10] if started else days[0]).replace(tzinfo=timezone.utc)
    baseline_days = max(0, (now - first).days - 7)
    def total(day_from, day_to):
        t = {}
        for d in days:
            if day_from <= d < day_to:
                for c, k in history[d].items():
                    t[c] = t.get(c, 0) + sum(k.values())
        return t
    d = lambda n: (now - timedelta(days=n)).strftime('%Y-%m-%d')
    tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    this_week = {}
    for dd in full:                 # this week counts everything seen, started or not
        if d(7) <= dd < tomorrow:
            for c, k in full[dd].items():
                this_week[c] = this_week.get(c, 0) + sum(k.values())
    base_span = min(28, baseline_days)
    base = total(d(7 + base_span), d(7)) if base_span > 0 else {}
    out = {}
    for c in set(this_week) | set(base):
        tw = this_week.get(c, 0)
        usual = round(base.get(c, 0) / (base_span / 7.0), 1) if base_span >= 7 else None
        rec = {'this_week': tw, 'usual_week': usual, 'baseline_days': baseline_days}
        if baseline_days < BASELINE_MIN_DAYS or usual is None:
            rec['state'] = 'baseline_building'
        else:
            ratio = round(tw / max(usual, 1.0), 1)
            rec['ratio'] = ratio
            rec['spike'] = bool(tw >= SPIKE_MIN and ratio >= SPIKE_RATIO)
            rec['state'] = 'spike' if rec['spike'] else ('quiet' if tw < usual / 2 else 'normal')
        out[c] = rec
    return out


def scan_commentary():
    """Fetch every commentary source, tag, balance, cache."""
    t0 = time.time()
    now = datetime.now(timezone.utc)
    yt_ids = _redis_get(YT_IDS_KEY) or {}
    n_ids = len(yt_ids)
    items, health = [], []
    for src in COMMENTARY_SOURCES:
        try:
            got, h = _fetch_commentary_source(src, yt_ids)
        except Exception as e:
            got, h = [], {'id': src.get('id'), 'name': src.get('name'), 'status': 'dead',
                          'error': 'crashed: %s' % str(e)[:100]}
        items.extend(got)
        health.append(h)
        time.sleep(0.6)
    if len(yt_ids) != n_ids:
        _redis_set(YT_IDS_KEY, yt_ids, YT_IDS_TTL)
    seen, unique = set(), []
    for i in sorted(items, key=lambda x: x.get('published') or '', reverse=True):
        k = (i['url'], i['title'])     # some podcasts give every episode the show's page link
        if k in seen:
            continue
        seen.add(k)
        unique.append(i)
    by_country = {}
    for i in unique:
        for c in i.get('countries') or []:
            if len(by_country.setdefault(c, [])) < 40:
                by_country[c].append(i)
    history = update_history(unique, _redis_get(HISTORY_KEY) or {}, now)
    _redis_set(HISTORY_KEY, history, (HISTORY_DAYS + 5) * 86400)
    started = _redis_get(HISTORY_STARTED_KEY)
    if not started:
        started = '2026-11-05' if now.strftime('%Y-%m-%d') >= '2026-11-05' else now.strftime('%Y-%m-%d')
        _redis_set(HISTORY_STARTED_KEY, started, 400 * 86400)
    attention = attention_metrics(history, now, started=started)
    payload = {
        'version': VERSION,
        'last_updated': now.isoformat(),
        'scan_seconds': round(time.time() - t0, 1),
        'attention': attention,
        'history_days': len(history),
        'label': ('Commentary from across the spectrum: newsletters, opinion outlets, '
                  'institutes and YouTube channels. Context only, never scored.'),
        'total_items': len(unique),
        'items': unique[:400],
        'by_country': by_country,
        'balance': build_balance(unique, health, now),
        'health': {
            'sources': len(COMMENTARY_SOURCES),
            'ok': sum(1 for h in health if h.get('status') == 'ok'),
            'empty': [h['id'] for h in health if h.get('status') == 'empty'],
            'dead': [{'id': h['id'], 'why': h.get('error')} for h in health if h.get('status') == 'dead'],
            'per_source': health,
        },
    }
    _redis_set(COMMENTARY_KEY, payload, 26 * 3600)
    print(f'[Commentary] {len(unique)} items from {payload["health"]["ok"]}/{len(COMMENTARY_SOURCES)} '
          f'sources in {payload["scan_seconds"]}s; {len(payload["balance"]["lopsided"])} lopsided topics')
    return payload


def get_commentary():
    return _redis_get(COMMENTARY_KEY)


# ============================================================
# BACKGROUND REFRESH
# ============================================================

_refresh_started = False
_refresh_lock = threading.Lock()


def _background_refresh_loop():
    # Oct 18 2026 -- one instance runs this (instance_lock v1.1.0 leader;
    # the other Render instance serves pages and stands by).
    try:
        from instance_lock import my_turn as _my_turn
    except ImportError:
        _my_turn = lambda job: True   # no lock module: run (fail-open)
    while True:
        if not _my_turn('think_tank_refresh'):
            continue
        try:
            scan_all_think_tanks()
        except Exception as e:
            print(f'[ThinkTank] Background scan error: {e}')
        try:
            scan_commentary()
        except Exception as e:
            print(f'[Commentary] Background scan error: {e}')
        time.sleep(BACKGROUND_REFRESH_HOURS * 3600)


def start_background_refresh():
    """Start background refresh thread; idempotent."""
    global _refresh_started
    with _refresh_lock:
        if _refresh_started:
            return
        _refresh_started = True

    def _delayed_start():
        time.sleep(60)
        _background_refresh_loop()

    thread = threading.Thread(target=_delayed_start, daemon=True)
    thread.start()
    print(f'[ThinkTank] Background refresh thread started (every {BACKGROUND_REFRESH_HOURS}h)')


# ============================================================
# FLASK ENDPOINTS
# ============================================================

def _all_valid_countries():
    """Union of every country any source can tag — keeps the endpoint allow-list in sync."""
    valid = set()
    for s in THINK_TANK_SOURCES:
        valid.update(s.get('countries', []))
    return valid


_manual = {'last': 0.0}


def register_think_tank_endpoints(app, start_background=True):
    """Register /api/think-tank/* and /api/commentary/* endpoints."""
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
        valid = _all_valid_countries()
        if country not in valid:
            return jsonify({
                'error': 'Unknown country',
                'valid': sorted(valid),
            }), 400
        return jsonify(get_country_feed(country))

    @app.route('/api/think-tank/refresh', methods=['POST', 'GET'])
    def think_tank_refresh():
        admin_key = os.environ.get('ADMIN_REFRESH_KEY')
        if admin_key:
            provided = request.args.get('key') or request.headers.get('X-Admin-Key')
            if provided != admin_key:
                return jsonify({'error': 'unauthorized'}), 401
        payload = scan_all_think_tanks()
        return jsonify({
            'success': True,
            'total_articles': payload['total_articles'],
            'scan_seconds': payload['scan_seconds'],
        })

    # ── Commentary lane (v2.0.0) ──
    def _cold():
        return {'available': False, 'version': VERSION,
                'note': 'First commentary scan runs about a minute after deploy -- unread, not empty.'}

    @app.route('/api/commentary/all')
    def commentary_all():
        p = get_commentary()
        return jsonify(dict(p, available=True) if p else _cold())

    @app.route('/api/commentary/balance')
    def commentary_balance():
        p = get_commentary()
        if not p:
            return jsonify(_cold())
        return jsonify({'available': True, 'version': VERSION, 'last_updated': p.get('last_updated'),
                        'balance': p.get('balance'),
                        'sources_ok': p.get('health', {}).get('ok'),
                        'sources_total': p.get('health', {}).get('sources')})

    @app.route('/api/commentary/debug')
    def commentary_debug():
        note = None
        if request.args.get('refresh', 'false').lower() == 'true':
            if time.time() - _manual['last'] < 600:
                note = 'refresh ignored: last manual refresh was under 10 minutes ago'
            else:
                _manual['last'] = time.time()
                scan_commentary()
                note = 'refreshed'
        p = get_commentary() or {}
        return jsonify({'version': VERSION, 'last_updated': p.get('last_updated'),
                        'refresh': note, 'scan_seconds': p.get('scan_seconds'),
                        'total_items': p.get('total_items'),
                        'health': p.get('health'),
                        'lopsided': (p.get('balance') or {}).get('lopsided'),
                        'history_days': p.get('history_days'),
                        'spikes': {c: a for c, a in (p.get('attention') or {}).items() if a.get('spike')},
                        'overall': (p.get('balance') or {}).get('overall')})

    @app.route('/api/commentary/<country>')
    def commentary_country(country):
        p = get_commentary()
        if not p:
            return jsonify(_cold())
        c = canon((country or '').lower().strip())
        bal = next((t for t in (p.get('balance') or {}).get('by_country', []) if t['country'] == c), None)
        return jsonify({'available': True, 'version': VERSION, 'country': c,
                        'last_updated': p.get('last_updated'), 'label': p.get('label'),
                        'items': (p.get('by_country') or {}).get(c, []), 'balance': bal,
                        'attention': (p.get('attention') or {}).get(c)})

    if start_background:
        start_background_refresh()

    print(f'[ThinkTank] Endpoints registered (v{VERSION}): think-tank + commentary '
          f'({len(COMMENTARY_SOURCES)} commentary sources)')


# ============================================================
# CLI / DIRECT INVOCATION (for local testing)
# ============================================================

if __name__ == '__main__':
    print(f'think_tank_feeds.py v{VERSION} — manual scan')
    payload = scan_all_think_tanks()
    print(json.dumps({
        'total': payload['total_articles'],
        'by_country': {k: len(v) for k, v in payload['by_country'].items()},
    }, indent=2))
    c = scan_commentary()
    print(json.dumps({'commentary': c['total_items'], 'health_ok': c['health']['ok'],
                      'dead': c['health']['dead'], 'overall': c['balance']['overall']}, indent=2))
