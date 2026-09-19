"""
Asifah Analytics — Military Asset & Deployment Tracker

SINGLE SOURCE OF TRUTH FOR THE VERSION IS MILITARY_TRACKER_VERSION, defined
below with MILITARY_TRACKER_FEATURES. This header is prose and cannot be
trusted to match the code; it read 'v3.0.0 / April 4, 2026' through nine
releases before anyone looked at it. If you want to know what is deployed,
read MILITARY_TRACKER_VERSION, the boot log line it prints at import, or the
'version' field on /api/military-posture. Do not read this paragraph.

Current at time of writing: v3.10.0, September 19, 2026.

Tracks military asset movements across multiple actors and regions.
Feeds deployment scores into existing threat probability calculations.

ACTORS TRACKED:
  Global / NORTHCOM:
    - US (CENTCOM + SOUTHCOM + NORTHCOM — global actor)
  Tier 1 (Direct strike correlation):
    - Israel / IDF
  Tier 2 (Adversary / Active Theatre):
    - Iran / IRGC
    - Iraq (Active theatre — IRI militia attacks, ISIS, US withdrawal)
    - Russia
    - China / PLAN
    - Venezuela (post-Maduro transition, US DEA/military involvement)
    - Cuba (regime stability, Russian/Chinese naval visits)
    - Haiti (MSS gang control, de facto military actor, failed state)
  Tier 3 (Regional — Middle East):
    - Saudi Arabia
    - UAE
    - Jordan
    - Qatar
    - Kuwait
    - Egypt
    - Turkey
  Tier 3 (Regional — Europe):
    - Ukraine
    - Greenland / Denmark
    - Poland
  Tier 3 (Regional — Western Hemisphere):
    - Panama (Canal security, Chinese port presence)
    - Colombia (ELN/FARC dissidents, functioning state)
    - Mexico (Cartel military ops, inward-facing)
    - Brazil (Regional power, Amazon military presence)
  Tier 4 (Alliance):
    - NATO (Europe / Arctic expansion)

REGIONS:
  Primary: CENTCOM AOR (Persian Gulf, Red Sea, Eastern Med, Levant)
  Secondary: EUCOM (Europe, Arctic/Greenland, Black Sea, Ukraine)
  Tertiary: SOUTHCOM/NORTHCOM (Caribbean, Central/South America, Gulf of Mexico)
  Planned: INDOPACOM

REGIONAL GROUPINGS (for frontend display):
  - Global / NORTHCOM (US anchor)
  - Asia & The Pacific Theatre
  - European Theatre
  - Middle East & North Africa
  - Western Hemisphere

OUTPUTS:
  - Per-target military posture scores
  - Regional tension multipliers
  - Location-aware context scoring
  - Alert objects for dashboard integration
  - Standalone page data for military.html

CHANGELOG:
  The v3.1 - v3.10 changes are NOT listed here. They are recorded as flags in
  MILITARY_TRACKER_FEATURES, which is machine-readable, published in the scan
  payload, and therefore cannot silently drift out of date the way the entries
  below did. Read that dict, not this list.

  v3.0.0 - Western Hemisphere expansion:
           * Added 'global_northcom' theatre — US as standalone global actor
           * Moved 'us' theatre from 'middle_east' to 'global_northcom'
           * Added 'western_hemisphere' theatre (order 5)
           * Added 7 WHA actors: venezuela (Tier 2, post-Maduro transition),
             cuba (Tier 2), haiti (Tier 2, MSS gang = de facto military),
             panama (Tier 3), colombia (Tier 3), mexico (Tier 3), brazil (Tier 3)
           * Added WHA location multipliers: Panama Canal, Soto Cano,
             GTMO, NAS Key West, NAVBASE San Diego, SOUTHCOM HQ,
             Caribbean Sea, Gulf of Mexico, Miraflores/Caracas,
             Port-au-Prince, Bogota, Mexico City border zones
           * Added 'southcom' block to ASSET_TARGET_MAPPING
           * Added WHA GDELT English query block (wha_english_queries)
           * Added WHA Spanish-language GDELT query block (spanish_queries)
           * Added WHA RSS feeds to DEFENSE_RSS_FEEDS
           * Added WHA queries to fetch_all_newsapi_military()
           * Updated version strings throughout
  v2.5.0 - Iraq actor integration:
           * Added Iraq as Tier 2 active theatre actor (weight 0.7)
           * Comprehensive keyword coverage: IRI militias (Kata'ib Hezbollah,
             Harakat al-Nujaba, Asa'ib Ahl al-Haq, Islamic Resistance in Iraq),
             PMF/Hashd al-Shaabi, ISIS/ISIL Iraq, US withdrawal, Iraqi airspace
           * Added Arabic keywords for Iraqi militia and military coverage
           * Added Iraq-specific location multipliers: Al Asad (2.5x),
             Ain al-Assad, Erbil (2.0x), Taji, Balad, Baghdad Green Zone,
             Camp Victory, Iraqi airspace corridor
           * Updated ASSET_TARGET_MAPPING: existing Iraq bases now feed
             'iraq' target; added Taji, Balad, Baghdad Green Zone
           * Added Iraq RSS feeds: Iraqi News Agency, Rudaw, Kurdistan24
           * Added Iraq GDELT queries in English and Arabic
           * Added Iraq NewsAPI query
           * Added 'iraq' to REGIONAL_THEATRES middle_east actors
  v2.4.0 - Upstash Redis persistent cache:
           * Replaced /tmp file cache with Upstash Redis
           * Cache now survives Render deploys and cold starts
           * Same pattern as Iran and Lebanon modules
           * /tmp file used as local fallback only
  v2.3.0 - Multilingual keyword matching + new actors:
           * Added Greenland and Poland as Tier 3 European actors
           * Added multilingual keywords to Russia, Ukraine, Iran, Israel
             actors so GDELT non-English articles trigger score matches
           * Added Polish and Danish/Norwegian GDELT query blocks
           * Expanded Russian and Ukrainian GDELT queries
           * Added drone incursion and airspace violation keywords
             for Poland (border drone flyovers from Belarus/Russia)
           * Added Greenland sovereignty and Arctic militarization keywords
           * Added location multipliers for Poland border hotspots
           * Total GDELT queries now 120+ across 11 languages
  v2.2.0 - Background scan & stability fix:
           * Moved initial scan to background thread (prevents gunicorn
             worker timeout crashes on cold start)
           * Endpoint returns stale cache or empty skeleton while scan
             runs — never blocks workers
           * Removed manual _add_cors_headers() — Flask-CORS handles
             all CORS globally from app.py
           * Added _background_scan_running lock to prevent duplicate scans
           * Added graceful empty response when no cache exists yet
  v2.1.0 - Multilingual intelligence expansion:
           * Added GDELT queries in 8 languages: Hebrew, Russian, Arabic,
             Farsi, Turkish, Ukrainian, French, Chinese
           * Added 15 new RSS feeds: Jerusalem Post, Times of Israel, Ynet,
             Israel Hayom, Al Jazeera, Al Arabiya, MEE, TASS, Moscow Times,
             Daily Sabah, TRT World, Kyiv Independent, Ukrinform,
             Iran International, Tasnim
           * Added missing English GDELT queries for Israel/IDF, Egypt, Turkey
           * Expanded English GDELT queries from 25 to 44
           * Total GDELT queries now 92 across 9 languages
  v2.0.0 - Major rewrite:
           * Added base evacuation / drawdown asset category with tiered weights
           * Added location multipliers for hotspot scoring
           * Added context-aware scoring (adversary exercises during buildup)
           * Expanded actors: Ukraine, split Saudi/UAE/Jordan/Qatar/Kuwait
           * Added regional theatre groupings for frontend
           * Expanded GDELT and RSS queries for new coverage
           * Added EUCOM target mapping (Ukraine, Black Sea, Baltic)
  v1.0.1 - Added CORS headers to all endpoint responses
  v1.0.0 - Initial release

COPYRIGHT © 2025-2026 Asifah Analytics. All rights reserved.
"""

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
import math
import os
import threading

try:
    from telegram_signals import fetch_telegram_signals
    TELEGRAM_AVAILABLE = True
    print("[Military Tracker] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Military Tracker] ⚠️ Telegram signals not available")

# Military signal interpreter — analytical prose layer (v1.0.0)
# Optional: tracker still functions if interpreter not yet deployed.
try:
    from military_signal_interpreter import build_full_interpretation
    MIL_INTERPRETER_AVAILABLE = True
    print("[Military Tracker] ✅ Signal interpreter loaded")
except ImportError:
    MIL_INTERPRETER_AVAILABLE = False
    print("[Military Tracker] ⚠️ Signal interpreter not yet deployed (analytical prose disabled)")

# ========================================
# CONFIGURATION
# ========================================

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY')

# Upstash Redis (persistent cache across Render cold starts)
UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

# Local fallback cache (wiped on deploy, used when Redis unavailable)
MILITARY_CACHE_FILE = '/tmp/military_tracker_cache.json'
MILITARY_CACHE_TTL_HOURS = 4

# Background scan lock — prevents duplicate concurrent scans
_background_scan_running = False
_background_scan_lock = threading.Lock()

# ------------------------------------------------------------
# CROSS-WORKER SCHEDULER LOCK  [Jun 2026]
# gunicorn runs --workers 2; each worker imports this module and starts its own
# periodic scan thread. The _background_scan_running flag above is per-process,
# so it only stops a worker from overlapping ITSELF -- not a second worker from
# scanning in parallel. Without this lock both workers scan and every GDELT /
# Brave / RSS call fires twice (doubles quota burn + trips GDELT 429s faster).
# Atomic Upstash "SET ... NX EX" makes exactly ONE worker own the scan; the
# owner renews each cycle (TTL > cycle so ownership never lapses while alive);
# if the owner dies, the lock expires and another worker takes over.
# Fail-open: if Redis is unreachable we proceed (no worse than today).
# ------------------------------------------------------------
_SCHED_WORKER_ID = f"w{os.getpid()}"

def _acquire_scheduler_lock(name, ttl_seconds):
    """Return True if THIS worker owns the scheduler lock for `name`.
    Atomic claim via SET NX EX; renews the TTL if we already own it."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return True
    key = f"sched_lock:{name}"
    hdr = {"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}
    try:
        r = requests.post(UPSTASH_REDIS_URL, headers=hdr,
                          json=["SET", key, _SCHED_WORKER_ID, "NX", "EX", str(ttl_seconds)],
                          timeout=8)
        if r.ok and (r.json() or {}).get('result') == 'OK':
            return True
        g = requests.get(f"{UPSTASH_REDIS_URL}/get/{key}", headers=hdr, timeout=8)
        owner = (g.json() or {}).get('result') if g.ok else None
        if owner == _SCHED_WORKER_ID:
            requests.post(UPSTASH_REDIS_URL, headers=hdr,
                         json=["SET", key, _SCHED_WORKER_ID, "EX", str(ttl_seconds)],
                         timeout=8)
            return True
        return False
    except Exception as e:
        print(f"[SchedLock] {name}: lock check failed ({e}); proceeding (fail-open)")
        return True

# ========================================
# REGIONAL THEATRE GROUPINGS (for frontend)
# ========================================

REGIONAL_THEATRES = {
    'global_northcom': {
        'label': 'Global / NORTHCOM',
        'icon': '🌐',
        'order': 0,
        'actors': ['us'],
        'description': 'United States — global actor spanning CENTCOM, SOUTHCOM, NORTHCOM, EUCOM, INDOPACOM'
    },
    'asia_pacific': {
        'label': 'Asia & The Pacific Theatre',
        'icon': '🌏',
        'order': 1,
        'actors': ['china', 'taiwan', 'vietnam', 'north_korea', 'pakistan', 'afghanistan'],
        'description': 'INDOPACOM area — China/PLAN, Taiwan Strait, Korean Peninsula, South/Central Asia'
    },
    'europe': {
        'label': 'European Theatre',
        'icon': '🌍',
        'order': 2,
        'actors': ['nato', 'russia', 'denmark', 'turkey', 'greece', 'ukraine', 'greenland', 'poland', 'cyprus', 'azerbaijan', 'armenia', 'hungary', 'kazakhstan'],
        'description': 'EUCOM area — NATO, Russia, Arctic, Black Sea, Ukraine, Poland eastern flank, Greece/Aegean, Cyprus, Caucasus'
    },
    'middle_east': {
        'label': 'Middle East & North Africa',
        'icon': '🕌',
        'order': 3,
        'actors': ['israel', 'iran', 'iraq', 'bahrain', 'egypt', 'jordan', 'kuwait', 'oman', 'qatar', 'saudi_arabia', 'uae', 'algeria', 'libya', 'morocco', 'tunisia'],
        'description': 'CENTCOM area — Persian Gulf, Red Sea, Eastern Med, Levant, Iraq theatre. Libya cross-listed with Africa theater (AFRICOM AOR).'
    },
    # ──────────────────────────────────────────────────────────────────
    # AFRICA THEATER (May 22 2026 — new theater build)
    # AFRICOM AOR. Excludes North Africa (which sits in middle_east label
    # but operationally covers Egypt only). Libya is cross-listed here
    # AND in middle_east since it sits at the MENA/Africa boundary.
    # ──────────────────────────────────────────────────────────────────
    'africa': {
        'label': 'Africa Theatre',
        'icon': '🌍',
        'order': 4,
        'actors': ['nigeria', 'somalia', 'mali', 'niger', 'burkina_faso', 'drc',
                   'sudan', 'south_sudan', 'libya', 'ethiopia', 'kenya', 'djibouti',
                   'central_african_republic', 'chad', 'mozambique', 'madagascar',
                   'equatorial_guinea', 'guinea', 'wagner_africa'],
        'description': 'AFRICOM area — Sahel junta belt, Horn of Africa, Lake Chad Basin, Great Lakes (DRC/Rwanda), Sudan civil war, Wagner/Africa Corps footprint'
    },
    'western_hemisphere': {
        'label': 'Western Hemisphere',
        'icon': '🌎',
        'order': 5,
        'actors': ['venezuela', 'cuba', 'haiti', 'panama', 'colombia', 'mexico', 'brazil'],
        'description': 'SOUTHCOM area — Caribbean, Central America, South America, narco-military actors'
    }
}


# ========================================
# MILITARY ACTORS
# ========================================

MILITARY_ACTORS = {
    # ------------------------------------------------
    # GLOBAL / NORTHCOM — United States (multi-theatre anchor)
    # ------------------------------------------------
    'us': {
        'name': 'United States',
        'flag': '🇺🇸',
        'tier': 1,
        'theatre': 'global_northcom',
        'weight': 1.0,
        'feeds_into': ['strike_probability'],
        'keywords': [
            # CENTCOM / Middle East
            'centcom', 'us central command', 'pentagon deploys',
            'department of defense deployment', 'us forces middle east',
            'carrier strike group', 'uss ', 'us navy gulf', 'us navy middle east',
            'amphibious ready group', 'us destroyer', 'us cruiser',
            'us submarine mediterranean', 'us submarine gulf',
            'us submarine north atlantic', 'us submarine arctic', 'us attack submarine norway',
            'giuk gap', 'p-8 poseidon keflavik', 'p-8 iceland', 'keflavik deployment',
            'us navy norwegian sea', 'ice exercise', 'icex', 'us submarine under ice',
            'bomber task force', 'b-1 lancer', 'b-2 spirit', 'b-52 middle east',
            'f-35 deployment middle east', 'f-22 deployment', 'usaf deploys',
            'kc-135', 'kc-46', 'aerial refueling middle east',
            'mq-9 reaper', 'rq-4 global hawk', 'us isr assets',
            'us troops deployed middle east', 'us forces iraq',
            'us forces syria', 'us forces jordan',
            '82nd airborne', '101st airborne middle east',
            'marine expeditionary', 'us special operations',
            'patriot battery deployed', 'thaad deployment',
            'iron dome us', 'us air defense middle east',
            'pre-positioned stocks', 'ammunition shipment',
            'military sealift command', 'us logistics middle east',
            'us military buildup', 'us force posture', 'us surge middle east',
            'massive fleet', 'armada', 'combat power',
            'us military assets middle east', 'military assets flock',
            # Active war posture (v2.6.0)
            'us strikes iran', 'us attack iran', 'us retaliates iran',
            'pentagon iran strike', 'centcom strike iran',
            'us military action iran', 'us iran war',
            'us forces high alert', 'defcon', 'force protection elevated',
            'us embassy evacuation middle east', 'us citizens leave',
            'shelter in place embassy', 'us warships iran',
            'us carrier iran', 'us bomber iran',
            'b-2 iran', 'b-52 iran', 'tomahawk iran',
            # SOUTHCOM / Western Hemisphere (v3.0.0)
            'southcom', 'us southern command', 'us forces caribbean',
            'us forces latin america', 'us military venezuela',
            'us military cuba', 'us military haiti',
            'us military panama', 'us navy caribbean',
            'soto cano air base', 'joint task force bravo',
            'us drug enforcement', 'dea military operation',
            'us coast guard caribbean', 'us coast guard drug interdiction',
            'naval station guantanamo', 'gtmo', 'guantanamo bay',
            'nas key west', 'naval air station key west',
            'us navy san diego', 'navbase san diego',
            'naval base san diego', 'third fleet',
            'operation martillo', 'drug interdiction caribbean',
            'us troops central america', 'us forces honduras',
            'us special forces colombia', 'us military advisors colombia',
            'panama canal security', 'canal zone military',
            'us venezuela sanctions military', 'us venezuela naval',
            'us military haiti security mission',
            # ── US HOME PORTS + ASSET MOVEMENT (May 22 2026 — Naval Asset Visibility expansion) ──
            # Catches signals about where the US Navy actually lives/operates
            # when not in a hot zone — Fleet Week, port returns, commissioning ceremonies,
            # underway departures. Critical for movement persistence tracking.
            # East Coast home ports
            'naval station norfolk', 'norfolk naval', 'norfolk virginia naval',
            'naval station mayport', 'mayport florida', 'mayport naval',
            'naval submarine base kings bay', 'kings bay georgia',
            'naval academy annapolis', 'annapolis fleet week',
            'naval submarine base groton', 'groton connecticut', 'sub base groton',
            'portsmouth naval shipyard', 'portsmouth naval', 'kittery maine',
            'naval submarine base new london', 'new london submarine',
            'naval weapons station yorktown',
            # West Coast home ports
            'naval base kitsap', 'bremerton naval', 'puget sound naval shipyard',
            'naval base kitsap bangor', 'bangor submarine', 'bangor washington naval',
            'naval station everett', 'everett washington naval',
            'naval amphibious base coronado', 'coronado california naval',
            'naval base point loma', 'point loma',
            'naval base ventura', 'port hueneme',
            'naval air station lemoore', 'lemoore california',
            'naval air station fallon', 'fallon nevada',
            'naval air station north island', 'north island',
            # Pacific home ports
            'pearl harbor naval', 'joint base pearl harbor hickam', 'pearl harbor hickam',
            'naval base pearl harbor', 'naval station pearl harbor',
            'apra harbor', 'naval base guam apra', 'guam naval base',
            'naval base kitsap silverdale',
            # Gulf Coast home ports
            'naval station pascagoula', 'pascagoula mississippi naval',
            'naval air station jacksonville', 'nas jacksonville',
            'naval air station kingsville', 'kingsville texas naval',
            'naval air station corpus christi', 'corpus christi naval',
            # Carrier-specific homeport language
            'home port san diego', 'home port norfolk', 'home port mayport',
            'home port yokosuka', 'home port everett', 'home port bremerton',
            'homeported in', 'homeported at',
            # Movement language (catches news-pop transitions)
            'returns to port', 'returns to san diego', 'returns to norfolk',
            'returns to mayport', 'returns to yokosuka', 'returns to pearl harbor',
            'departs san diego', 'departs norfolk', 'departs mayport',
            'departs yokosuka', 'departs pearl harbor',
            'underway from', 'underway departure', 'sailed from',
            'commissioning ceremony', 'decommissioning ceremony',
            'change of command', 'change of homeport',
            'pier-side', 'pierside', 'tied up at',
            'fleet week new york', 'fleet week san francisco', 'fleet week los angeles',
            'fleet week port everglades', 'fleet week portland',
            'open ship', 'ship tours public',
            # Carrier strike group movement
            'csg deployment', 'csg departs', 'csg returns',
            'carrier strike group deploys', 'carrier strike group returns',
            'strike group sails',
            # ── IRAN KINETIC RE-HEATING (May 22 2026) ──
            # Catches the specific patterns of US force flow into CENTCOM AOR
            # as Iran posture re-escalates. Ben Gurion launch-hub language is
            # the unique signature — Israel air bases used as US strike staging.
            # Ben Gurion / Israel air bases as US launch hubs
            'ben gurion launch', 'ben gurion launch pad', 'ben gurion staging',
            'us bombers ben gurion', 'us aircraft ben gurion',
            'us bombers israel', 'us tankers israel', 'us aircraft israel staging',
            'israeli air bases us', 'israel air base us aircraft',
            'kc-46 nevatim', 'kc-46 ramat david', 'kc-135 israel',
            'b-2 israel', 'b-2 staging israel', 'b-2 nevatim',
            'b-21 raider israel', 'b-21 staging',
            'b-52 israel', 'b-1 israel',
            'f-35 israel deployment', 'f-22 israel deployment',
            'tanker bridge israel', 'aerial refueling bridge israel',
            'us strike package israel', 'us aircraft staging israel',
            # US troop surge / flow language (echoes Jan 2026 Operation Absolute Resolve)
            'troop deployment iran', 'troop deployment middle east',
            'us forces surge centcom', 'us forces surge middle east',
            'army flowing middle east', 'army surge centcom',
            'pentagon orders deployment', 'sec def orders deployment',
            'us military prepositioning iran', 'army prepositioning middle east',
            'rapid deployment iran', 'rapid deployment middle east',
            'us forces flow', 'forces flow centcom',
            # Aerial refueling / ISR bridge to CENTCOM
            'aerial refueling track', 'tanker bridge centcom',
            'kc-46 deployment middle east', 'kc-135 deployment middle east',
            'tanker squadron deploys', 'tanker squadron forward deploys',
            'rc-135 rivet joint iran', 'rc-135 deployment',
            'e-3 awacs middle east', 'awacs deployment',
            # Strike package + escalation language
            'b-2 deployment iran', 'b-21 deployment iran',
            'strike package iran', 'strike package centcom',
            'pre-strike posture', 'pre-strike positioning',
            'kinetic preparation iran', 'kinetic prep iran',
            'wartime alert centcom', 'wartime posture iran',
            # Saudi / Gulf air defense buildup
            'patriot saudi', 'thaad saudi deployment', 'patriot kuwait',
            'thaad uae deployment', 'patriot uae',
            # Diego Garcia bomber posture (key signal)
            'diego garcia bomber', 'diego garcia b-2',
            'diego garcia b-52', 'diego garcia b-1',
            'bomber forward deployed diego garcia',
            # ── US HOSPITAL SHIPS (May 22 2026) ──
            # USNS Mercy (T-AH-19, San Diego homeport) + USNS Comfort (T-AH-20,
            # Norfolk homeport). 1,000-bed hospital ships, primary HA/DR mission.
            # Deployment = US recognizing humanitarian crisis severity.
            # Co-occurrence with pandemic signals = high-fidelity analytical signal.
            'usns mercy', 'uss mercy', 'mercy hospital ship', 't-ah-19',
            'usns comfort', 'uss comfort', 'comfort hospital ship', 't-ah-20',
            'us hospital ship', 'us navy hospital ship',
            'hospital ship deployment', 'hospital ship deploys',
            'hospital ship arrives', 'hospital ship sails',
            'mercy deployed', 'comfort deployed', 'mercy sails', 'comfort sails',
            'mercy departs', 'comfort departs', 'mercy returns', 'comfort returns',
            'pacific partnership mercy', 'continuing promise comfort',
            'pacific partnership exercise', 'continuing promise exercise',
            # HA/DR (Humanitarian Assistance / Disaster Response) mission language
            'ha/dr deployment', 'humanitarian assistance disaster response',
            'us military humanitarian deployment', 'us navy disaster relief',
            'medical mission deployment', 'us navy medical mission',
            'medical relief ship', 'medical treatment facility ship',
            # Pandemic / disease surveillance signals (catches the convergence)
            'ebola outbreak', 'ebola surge', 'ebola cases rising',
            'ebola response military', 'sudan virus disease', 'sudan ebolavirus',
            'ebola drc', 'ebola uganda',
            'marburg outbreak', 'marburg virus', 'marburg cases',
            'lassa fever outbreak', 'mpox outbreak', 'mpox cases surge',
            'cholera outbreak africa', 'cholera surge',
            'who declares emergency', 'who pheic',
            'public health emergency international concern',
            'cdc deployment', 'cdc team africa', 'cdc disease response',
            'us pandemic response', 'us military disease response',
            'biosurveillance africa', 'biosurveillance deployment',
            'medical evacuation mass casualty',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=site:centcom.mil&hl=en&gl=US&ceid=US:en',
            'https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945',
        ]
    },

    # ------------------------------------------------
    # TIER 1 — Direct strike correlation
    # ------------------------------------------------
    'israel': {
        'name': 'Israel',
        'flag': '🇮🇱',
        'tier': 1,
        'theatre': 'middle_east',
        'weight': 0.9,
        'feeds_into': ['strike_probability', 'regional_tension'],
        'keywords': [
            # IDF mobilization & operations
            'idf mobilization', 'idf mobilisation', 'israel reservists called',
            'israel reserves mobilized', 'idf northern command',
            'idf southern command', 'idf central command',
            'idf ground operation', 'idf troops deployed',
            'israel military buildup', 'idf offensive',
            # Air Force
            'israeli air force exercise', 'iaf exercise', 'iaf drill',
            'f-35 israel', 'f-15 israel', 'israeli airstrike',
            'israel aerial refueling', 'israeli drone strike',
            'iaf strike iran', 'iaf long range strike',
            # Navy
            'israeli navy', 'israel submarine', 'israeli corvette',
            # -- Defense exports / security cooperation (Jul 2026: the Israel-shares-tech story) --
            'israel arms deal', 'israeli arms sale', 'israel defense export',
            'israel weapons export', 'israeli defense contract',
            'rafael contract', 'elbit contract', 'iai contract',
            'israel aerospace industries deal', 'elbit systems deal',
            'israel arms uae', 'israel weapons uae', 'israel trains uae',
            'israeli trainers gulf', 'israel gulf defense cooperation',
            'israel uae defense', 'israel uae military cooperation',
            'israel bahrain defense', 'israel morocco defense',
            'israel azerbaijan arms', 'israel india defense deal',
            'barak air defense sale', 'barak-8 export', 'david sling export',
            'iron dome sale', 'iron dome export', 'arrow 3 export', 'arrow-3 germany',
            'israeli air defense transfer', 'israel radar sale',
            'israel naval blockade', 'israel red sea',
            # Air defense systems
            'iron dome deployment', 'david sling', 'arrow battery',
            'israel air defense activation', 'iron dome intercept',
            'iron dome activated', 'iron dome overwhelmed', 'iron dome fails',
            'iron dome saturated', 'iron dome capacity',
            'david sling intercept', 'arrow intercept', 'arrow 3 intercept',
            'arrow missile defense', 'multi-layer defense',
            # Intelligence
            'mossad operation', 'shin bet alert', 'aman intelligence',
            'israel intelligence assessment',
            # Home Front Command / Pikud HaOref
            'home front command', 'pikud haoref', 'pikud ha-oref',
            'rocket alert', 'rocket siren', 'incoming rocket',
            'red alert israel', 'red alert app', 'tzeva adom',
            'missile alert israel', 'air raid siren israel',
            'rocket barrage israel', 'missile barrage israel',
            'rockets fired at israel', 'missiles fired at israel',
            'shelter instructions', 'bomb shelter israel',
            'home front command instructions',
            'multiple alerts', 'nationwide alert israel',
            # City-specific alerts (high location multiplier)
            'tel aviv siren', 'tel aviv rocket', 'tel aviv alert',
            'tel aviv missile', 'tel aviv hit', 'tel aviv impact',
            'jerusalem siren', 'jerusalem alert', 'jerusalem missile',
            'haifa siren', 'haifa alert', 'haifa rocket', 'haifa hit',
            'eilat siren', 'eilat missile', 'eilat alert',
            'beer sheva siren', 'beersheba alert', 'negev alert',
            'golan rockets', 'golan attack', 'golan shelling',
            # Airport / airspace
            'ben gurion airport closed', 'ben gurion divert',
            'ben gurion cancelled', 'ben gurion suspended',
            'israel airspace closed', 'israel flights cancelled',
            'israel flights suspended', 'ovda airport closed',
            'ramon airport closed',
            # Active Iran-Israel war (v2.7.2)
            'iran strikes israel', 'iran attack israel',
            'iran missile strike israel', 'iran retaliatory strike',
            'iran launches missiles', 'iran fires missiles',
            'iranian missile attack', 'iranian strike israel',
            'iran drone attack israel', 'shahed drone israel',
            'iran ballistic missile israel', 'iran cruise missile israel',
            'iranian ballistic missile tel aviv', 'iranian missile hits israel',
            'iran retaliates israel', 'iran retaliatory strike israel',
            'israel retaliates iran', 'israel strikes iran',
            'israel attack iran', 'idf strikes iran',
            'israel iran war', 'iran israel war',
            'iran israel conflict', 'iran israel escalation',
            'full scale war iran israel', 'regional war middle east',
            'multi front war israel', 'seven front war',
            # War damage & casualties
            'casualties israel', 'killed in israel', 'wounded israel',
            'dead in israel', 'injuries israel', 'israel death toll',
            'missile hits israel', 'missile impact israel',
            'debris falls israel', 'shrapnel israel', 'fragments israel',
            'direct hit israel', 'impact confirmed israel',
            'building hit israel', 'residential area hit israel',
            # US-Israel coordination
            'operation epic fury', 'us israel joint strike',
            'us israel coordinated', 'us defends israel',
            'patriot battery israel', 'thaad israel', 'thaad deployed israel',
            'us troops israel', 'centcom israel',
            # Evacuation & diplomatic
            'authorized departure israel', 'evacuate israel',
            'us citizens leave israel', 'us embassy israel alert',
            'leave israel immediately', 'commercial flights israel',
            'israel state of emergency', 'israel wartime government',
            'israel war cabinet',
            # Hebrew keywords
            'צה"ל', 'כיפת ברזל', 'חיל האוויר',
            'פיקוד צפון', 'פיקוד דרום', 'פיקוד מרכז',
            'מילואים', 'חזבאללה', 'חמאס',
            'חיל הים', 'תרגיל', 'גיוס',
            'כוננות', 'פריסה', 'סיור',
            'פיקוד העורף', 'צבע אדום', 'אזעקה',
            'התרעה', 'מרחב מוגן', 'מקלט',
            'יירוט', 'טיל בליסטי', 'רקטות',
            'שיגור', 'מטח רקטות', 'מטח טילים',
            'טיל חץ', 'שרביט דוד', 'כיפת ברזל נפלה',
            'מלחמה', 'מצב חירום', 'פינוי',
            'נפגעים', 'הרוגים', 'פצועים',
            'פגיעה ישירה', 'נפילה', 'רסיסים',
            'תל אביב אזעקה', 'חיפה אזעקה', 'ירושלים אזעקה',
            'נתב"ג סגור', 'שדה תעופה סגור',
            # Arabic keywords
            'صواريخ على إسرائيل', 'هجوم إيراني على إسرائيل',
            'القبة الحديدية', 'صافرات الإنذار إسرائيل',
            'قصف تل أبيب', 'قصف حيفا', 'قصف القدس',
            'حرب إسرائيل إيران', 'عملية إيبك فيوري',
            'إسرائيل تحت القصف', 'صاروخ باليستي إسرائيل',
            'الجبهة الداخلية', 'ملجأ', 'إنذار أحمر',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=Israel+Iran+missile+attack+war&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=Israel+iron+dome+intercept+siren+alert&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=Israel+ballistic+missile+casualties+tel+aviv&hl=en&gl=US&ceid=US:en',
        ]
    },

    # ------------------------------------------------
    # TIER 2 — Adversary / Active Theatre
    # ------------------------------------------------
    'iran': {
        'name': 'Iran',
        'flag': '🇮🇷',
        'tier': 2,
        'theatre': 'middle_east',
        'weight': 0.8,
        'feeds_into': ['reverse_threat', 'regional_tension'],
        'keywords': [
            'irgc navy', 'irgc naval', 'iranian warship', 'iranian frigate',
            'iranian destroyer', 'iranian submarine', 'iran fast attack craft',
            'bandar abbas naval', 'iran strait of hormuz', 'irgc boats',
            'iran missile test', 'iran ballistic missile', 'iran cruise missile',
            'iran missile launch', 'shahab missile', 'fateh missile',
            'emad missile', 'iran hypersonic', 'irgc aerospace force',
            'iranian air force', 'iriaf', 'iran drone', 'shahed drone',
            'iran uav', 'iran mohajer', 'iranian fighter jet',
            'irgc exercise', 'iran military exercise', 'iran war games',
            'irgc ground forces', 'basij mobilization',
            'great prophet exercise', 'iran military drill',
            'iran drills', 'iran naval drill', 'iran naval exercise',
            'iran weapons shipment', 'iran arms transfer',
            'irgc quds force', 'iran smuggling weapons',
            'iran threatens', 'iran retaliation', 'iran warns',
            'iranian bases within range', 'iran retaliatory strike',
            'iran nuclear weapon', 'iran enrichment',
            'iranian defense minister',
            # Farsi keywords (match GDELT Farsi articles)
            'سپاه پاسداران', 'رزمایش', 'نیروی دریایی',
            'موشک بالستیک', 'پهپاد', 'نیروی هوافضا',
            'تنگه هرمز', 'سپاه قدس',
            # Arabic keywords (match Arabic-language Iran coverage)
            'الحرس الثوري', 'صواريخ باليستية إيران',
            'القوات البحرية الإيرانية', 'مضيق هرمز',
            # Active war / strike keywords (v2.6.0)
            'iran strikes israel', 'iran attacks israel',
            'iran missile launch israel', 'iran retaliatory strike israel',
            'iran fires missiles at israel', 'iranian attack on israel',
            'irgc launches', 'irgc fires', 'irgc strike',
            'iran ballistic missile launch', 'iran massive strike',
            'iran second strike', 'iran retaliates',
            'iran nuclear sites', 'iran nuclear facilities strike',
            'natanz', 'fordow', 'isfahan nuclear',
            'iran air defense activated', 'iran intercept',
            'iran war footing', 'iran full mobilization',
            'iran declares war', 'iran state of war',
            'strait of hormuz closed', 'hormuz blockade',
            'iran oil embargo', 'iran shipping attack',
            'حمله به اسرائیل', 'شلیک موشک', 'جنگ ایران اسرائیل',
            'حمله موشکی', 'عملیات نظامی',
            # Ceasefire / compliance signals (April 7, 2026 US-Iran ceasefire)
            'iran ceasefire', 'us iran ceasefire', 'iran truce', 'iran deal',
            'iran compliance', 'iran violates ceasefire', 'ceasefire violation iran',
            'iran ceasefire holding', 'iran stands down', 'irgc stand down',
            'iran nuclear deal', 'iran agreement', 'iran negotiations',
            'iran hostage', 'iran prisoner', 'iran detainee release',
            'trump iran deal', 'us iran agreement', 'iran nuclear talks',
            'iran ceasefire collapse', 'iran breaks ceasefire', 'iran resumes',
            'pmf ceasefire', 'hezbollah ceasefire', 'proxy ceasefire',
            'آتش بس ایران', 'توافق ایران', 'مذاکرات ایران',
        ],
        'rss_feeds': []
    },

    # ------------------------------------------------
    # TIER 2 — Iraq (Active theatre: IRI militias, ISIS, US withdrawal)
    # v2.5.0
    # ------------------------------------------------
    'iraq': {
        'name': 'Iraq',
        'flag': '🇮🇶',
        'tier': 2,
        'theatre': 'middle_east',
        'weight': 0.7,
        'feeds_into': ['strike_probability', 'regional_tension'],
        'keywords': [
            # --- IRI / Iran-aligned militias (primary threat) ---
            'islamic resistance in iraq', 'islamic resistance iraq',
            'iri attack', 'iri drone', 'iri rocket',
            'kata\'ib hezbollah', 'kataib hezbollah', 'kata\'ib hizballah',
            'harakat al-nujaba', 'harakat al nujaba', 'nujaba movement',
            'asa\'ib ahl al-haq', 'asaib ahl al haq', 'aah militia',
            'kata\'ib sayyid al-shuhada', 'kataib sayyid',
            'badr organization', 'badr corps', 'badr militia',
            'iran-backed militia iraq', 'iran backed militia iraq',
            'iran-aligned militia iraq', 'iran aligned militia',
            'iran proxy iraq', 'iranian proxy attack iraq',
            'militia attack us base iraq', 'militia drone attack iraq',
            'militia rocket attack iraq', 'one-way attack drone iraq',
            'attack on coalition forces iraq',
            # --- PMF / Hashd al-Shaabi ---
            'popular mobilization forces', 'pmf iraq',
            'hashd al-shaabi', 'hashd al shaabi', 'al-hashd',
            'pmf militia', 'pmf checkpoint', 'pmf deployment',
            'popular mobilization', 'hashd forces',
            # --- ISIS / ISIL in Iraq ---
            'isis iraq', 'isil iraq', 'daesh iraq',
            'isis attack iraq', 'isis ambush iraq', 'isis resurgence iraq',
            'isis prison iraq', 'isis prisoners iraq', 'isis fighters iraq',
            'isis sleeper cell iraq', 'islamic state iraq',
            'isis ied iraq', 'isis suicide iraq',
            'counter-isis iraq', 'counter isis operation',
            'operation inherent resolve',
            # --- US forces in Iraq ---
            'us forces iraq', 'us troops iraq', 'coalition forces iraq',
            'us withdrawal iraq', 'us pullout iraq', 'us drawdown iraq',
            'us base iraq', 'american forces iraq',
            'operation inherent resolve', 'cjtf-oir',
            'us military iraq withdrawal', 'coalition withdrawal iraq',
            'us advisors iraq', 'us advisory mission iraq',
            # --- Iraqi military / government ---
            'iraqi military', 'iraqi armed forces', 'iraqi army',
            'iraqi air force', 'iraqi navy',
            'iraqi security forces', 'iraqi federal police',
            'iraqi counter-terrorism', 'icts iraq', 'isof iraq',
            'iraqi special operations',
            'iraq defense minister', 'iraq security',
            'maliki iraq', 'nouri al-maliki',
            # --- Key locations ---
            'al asad airbase', 'ain al-asad', 'ain al asad',
            'erbil base', 'erbil attack', 'erbil rocket',
            'camp victory iraq', 'taji base', 'balad air base',
            'baghdad green zone', 'green zone attack',
            'baghdad international airport', 'biap',
            'al-tanf iraq', 'qaim border crossing',
            # --- Iraqi airspace (critical for Iran strike corridor) ---
            'iraqi airspace', 'iraq airspace corridor',
            'iraq air corridor', 'overfly iraq',
            'iraq flight restriction', 'iraq no-fly',
            # --- Sectarian / political instability ---
            'iraq sectarian', 'iraq sectarian violence',
            'iraq political crisis', 'iraq government formation',
            'iraq parliament', 'kurdistan iraq',
            'kurdish peshmerga', 'peshmerga',
            'krg iraq', 'erbil sulaymaniyah',
            # Arabic keywords (match GDELT/Arabic coverage)
            'المقاومة الإسلامية في العراق',
            'كتائب حزب الله', 'حركة النجباء',
            'عصائب أهل الحق', 'الحشد الشعبي',
            'القوات المسلحة العراقية', 'الجيش العراقي',
            'داعش العراق', 'قوات التحالف العراق',
            'الانسحاب الأمريكي العراق',
            'قاعدة عين الأسد', 'أربيل هجوم',
            'المنطقة الخضراء', 'الأجواء العراقية',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=iraq+military+OR+militia+OR+ISIS&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=site:rudaw.net+military&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=site:kurdistan24.net+military&hl=en&gl=US&ceid=US:en',
        ]
    },

    'china': {
        'name': 'China',
        'flag': '🇨🇳',
        'tier': 2,
        'theatre': 'asia_pacific',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'plan gulf', 'chinese warship', 'chinese navy persian gulf',
            'pla navy gulf', 'china naval deployment middle east',
            'chinese carrier', 'chinese destroyer gulf',
            'chinese frigate gulf', 'china anti-piracy',
            'chinese submarine indian ocean',
            'djibouti base china', 'china djibouti',
            'china military base', 'china port visit oman',
            'china port visit pakistan', 'gwadar china navy',
            'china spy ship', 'china surveillance vessel',
            'china intelligence ship', 'yuan wang tracking ship',
            'china iran naval exercise', 'china russia naval exercise',
            'china military exercise middle east',
            'south china sea military', 'taiwan strait military',
            'pla exercise', 'chinese military exercise',
            'chinese naval gun', 'plan warship'
        ],
        'rss_feeds': []
    },

    'taiwan': {
        'name': 'Taiwan',
        'flag': '🇹🇼',
        'tier': 2,
        'theatre': 'asia_pacific',
        'weight': 0.8,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Strait activity
            'taiwan strait', 'taiwan strait incursion', 'pla taiwan strait',
            'median line violation', 'taiwan median line',
            'chinese warplanes taiwan', 'pla aircraft taiwan adiz',
            'taiwan adiz', 'taiwan air defense zone',
            # Naval/military
            'taiwan blockade', 'taiwan naval exercise',
            'pla navy taiwan', 'chinese carrier taiwan',
            'taiwan invasion', 'pla amphibious',
            'pla exercise taiwan', 'joint sword', 'joint sword exercise',
            'taiwan military exercise', 'han kuang',
            'taiwan strait crisis', 'taiwan contingency',
            # US/ally involvement
            'us warship taiwan strait', 'freedom of navigation taiwan',
            'us navy taiwan strait', 'seventh fleet taiwan',
            'japan taiwan defense', 'aukus taiwan',
            # Political/escalation
            'taiwan independence declaration', 'taiwan president china',
            'beijing taiwan threat', 'china taiwan war',
            'china invade taiwan', 'taiwan reunification force',
            'pelosi taiwan', 'us arms taiwan', 'taiwan arms sale',
            # Chinese language
            '台湾海峡', '解放军台湾', '台海演习',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=taiwan+strait+OR+pla+OR+china+military+taiwan&hl=en&gl=US&ceid=US:en',
        ]
    },

    'vietnam': {
        'name': 'Vietnam',
        'flag': '🇻🇳',
        'tier': 2,
        'theatre': 'asia_pacific',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # South China Sea / maritime sovereignty
            'south china sea vietnam', 'vietnam south china sea',
            'vanguard bank', 'vanguard bank standoff',
            'paracel islands', 'spratly vietnam', 'spratly islands vietnam',
            'vietnam china standoff', 'china survey vessel vietnam',
            'china coast guard vietnam', 'vietnam oil rig standoff',
            'hd-981', 'hd 981', 'haiyang dizhi',
            # Vietnamese forces / incidents
            'vietnam coast guard', 'vietnam navy', 'vietnam naval exercise',
            'vietnam maritime militia', 'vietnam fishing vessel china',
            'vietnam fishing boat rammed', 'cam ranh bay',
            # Partnership / external balancing
            'us vietnam defense', 'vietnam comprehensive strategic partnership',
            'vietnam philippines coast guard', 'vietnam india defense',
            'vietnam russia arms',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=vietnam+south+china+sea+OR+vanguard+bank+OR+vietnam+coast+guard&hl=en&gl=US&ceid=US:en',
        ]
    },

    'japan': {
        'name': 'Japan',
        'flag': '🇯🇵',
        'tier': 2,
        'theatre': 'asia_pacific',
        'weight': 0.8,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # ── Maritime presence / Taiwan Strait transit ──
            'jmsdf taiwan strait', 'japan warship taiwan strait',
            'japan destroyer taiwan strait', 'js ikazuchi', 'js ise',
            'japan maritime self-defense force', 'japan taiwan strait transit',
            'jmsdf destroyer', 'japan freedom of navigation',
            'jmsdf deployment', 'japan helicopter destroyer',

            # ── Senkaku / Diaoyu (China–Japan flashpoint) ──
            'senkaku islands', 'senkaku incursion', 'senkaku intrusion',
            'diaoyu islands japan', 'chinese vessels senkaku',
            'japan coast guard senkaku', 'jcg senkaku', 'jcg patrol',
            'japan coast guard china', 'china coast guard senkaku',
            'east china sea japan', 'japan east china sea standoff',

            # ── Okinawa / Ryukyu / Southwest islands ──
            'okinawa us base', 'okinawa military', 'futenma', 'henoko',
            'yonaguni deployment', 'miyako missile', 'ishigaki garrison',
            'southwest islands defense', 'ryukyu deployment',
            'japan southwest islands', 'okinawa marines',
            'japan amphibious rapid deployment brigade',

            # ── Strike capability / counter-strike ──
            'tomahawk japan', 'long-range strike japan',
            'japan counter-strike capability', 'japan counterstrike',
            'type 12 missile', 'japan hypersonic',
            'jsdf stand-off missile', 'japan strike posture',
            'japan stand-off defense', 'japan missile deployment',

            # ── JSDF deployments / scrambles ──
            'jsdf scramble', 'asdf intercept', 'japan air defense scramble',
            'japan air self-defense force', 'japan ground self-defense force',
            'self-defense force exercise', 'japan-us joint exercise',
            'us-japan exercise', 'jsdf deployment',

            # ── Taiwan defense rhetoric (constitutional) ──
            'article 9 japan', 'article 9 reinterpretation',
            'collective self-defense taiwan', 'japan taiwan defense',
            'potentially critical situation', 'existential threat taiwan',
            'takaichi taiwan', 'takaichi defense', 'japan taiwan contingency',
            'japan taiwan emergency',

            # ── Regional alliance posture ──
            'quad military exercise', 'aukus japan', 'japan-philippines defense',
            'japan-philippines security', 'japan-australia exercise',
            'us-japan-korea trilateral', 'japan reciprocal access agreement',
            'japan raa', 'japan-uk military', 'japan nato',

            # ── DPRK threat axis (Japan as missile target) ──
            'north korea missile japan', 'dprk missile japan',
            'j-alert', 'missile flies over japan', 'missile defense japan',
            'aegis ashore japan', 'sm-3 japan', 'japan missile shield',
            'kim missile japan',

            # ── Russia far east (Japan-Russia) ──
            'northern territories', 'kuril islands japan',
            'russia japan exercise', 'russian bombers hokkaido',
            'tsushima strait russia', 'russia japan tension',
            'russia far east japan',

            # ── Embassy / diplomatic incident category ──
            'japan embassy beijing', 'chinese embassy tokyo',
            'jgsdf officer embassy', 'diplomatic incident japan china',
            'japan china embassy incident',

            # ── Defense budget / posture ──
            'japan defense budget', 'japan rearmament', 'japan 2 percent gdp',
            'japan defense spending', 'japan national security strategy',
            'japan defense buildup', 'kishida defense', 'takaichi defense budget',

            # ── Eastern Theater Command pressure (Japan as target) ──
            'eastern theater command okinawa', 'pla eastern theater japan',
            'pla aircraft japan', 'chinese drone japan',
            'pla navy okinawa', 'pla east china sea',

            # ── Japanese language signals ──
            '自衛隊', '尖閣諸島', '台湾海峡', '反撃能力',
            '高市', '中国軍', '北朝鮮ミサイル', '南西諸島',
            '海上自衛隊', '航空自衛隊', '陸上自衛隊',
            '日米同盟', 'スクランブル',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=jsdf+OR+%22japan+self-defense%22+OR+japan+military&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=senkaku+OR+%22japan+china+military%22+OR+japan+taiwan+strait&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=okinawa+military+OR+japan+missile+OR+japan+strike+capability&hl=en&gl=US&ceid=US:en',
        ]
    },

    'north_korea': {
        'name': 'North Korea',
        'flag': '🇰🇵',
        # TIER BUMP (Jul 12 2026): 2 -> 1, weight 0.7 -> 0.9.
        # Tier here tracks KINETIC ACTIVITY, not importance -- which is why China
        # (0.6) and Russia (0.7) sit at tier 2 while Sudan and Wagner sit at tier 1.
        # The 0.7/tier-2 rating was calibrated when the DPRK was a SUPPLIER of
        # shells. It is now a COMBATANT: ~10-15k troops committed to Kursk, dead in
        # the thousands, and a state memorial whose walls carry 2,288 names. That is
        # the Sudan/Wagner band, so it gets the Sudan/Wagner weight. Only the US
        # carries 1.0.
        'tier': 1,
        'theatre': 'asia_pacific',
        'weight': 0.9,
        # ROLLUP FIX (Jul 12 2026): russia_proxy_pressure added.
        # This is the change with teeth. Wagner feeds russia_proxy_pressure. Sudan
        # feeds russia_proxy_pressure. The country that sent an army corps to fight
        # Russia's war did not -- so every DPRK combat signal was landing in
        # 'regional_tension' (i.e. read as a Korean Peninsula story) and the
        # Russia-proxy rollup was structurally blind to its largest proxy.
        'feeds_into': ['regional_tension', 'russia_proxy_pressure'],
        'keywords': [
            # Missile / launch events (broad)
            'north korea missile', 'dprk missile', 'north korea launches',
            'dprk launches', 'north korea fires', 'dprk fires',
            'north korea ballistic', 'dprk ballistic',
            'north korea icbm', 'dprk icbm', 'hwasong',
            'north korea projectile', 'dprk projectile',
            'north korea short-range', 'north korea medium-range',
            'north korea test', 'dprk test',
            # Nuclear
            'north korea nuclear', 'dprk nuclear',
            'north korea nuclear weapon', 'dprk nuclear warhead',
            'north korea nuclear test', 'north korea nuclear drill',
            'north korea nuclear posture', 'north korea nuclear arsenal',
            'punggye-ri', 'yongbyon', 'yongbyon reactor',
            'north korea enrichment', 'north korea plutonium',
            'north korea tactical nuclear', 'dprk tactical nuclear',
            'kim nuclear', 'kim warhead',
            # Kim Jong Un statements / orders (major signal source)
            'kim jong un', 'kim jong-un',
            'kim orders', 'kim inspects', 'kim oversees',
            'kim threatens', 'kim warns', 'kim vows',
            'kim declares', 'kim military',
            'north korean leader', 'pyongyang warns',
            'pyongyang threatens', 'pyongyang fires',
            'pyongyang launches', 'pyongyang test',
            'dprk state media', 'korean central news agency', 'kcna',
            'north korea threatens', 'north korea warns', 'north korea vows',
            'north korea soldiers', 'dprk soldiers', 'korean soldiers russia',
            # Military exercises / drills
            'north korea military exercise', 'north korea drill',
            'north korea war games', 'north korea combat drill',
            "korean people's army", 'kpa exercise',
            'north korea artillery', 'dprk artillery',
            'north korea tank', 'north korea troops',
            # Provocations / escalation
            'north korea provocation', 'dprk provocation',
            'north korea escalation', 'korean peninsula tension',
            'north korea aggression',
            # Drones / submarines
            'north korea drone', 'dprk drone', 'north korea uav',
            'north korea submarine', 'dprk submarine',
            'north korea submarine launch', 'north korea slbm',
            # DMZ / inter-Korean
            'dmz incident', 'korean dmz', 'inter-korean',
            'north korea south korea', 'north korea border',
            'nll violation', 'north korea nll',
            'north korea loudspeaker', 'north korea trash balloon',
            'north korea balloon', 'north korea mines dmz',
            # Troops in Russia
            'north korea troops russia', 'dprk soldiers ukraine',
            'north korea soldiers deployed', 'korean troops ukraine',
            # Sanctions / weapons exports
            'north korea weapons export', 'dprk weapons transfer',
            'north korea sanctions violation', 'north korea arms',
            'north korea russia weapons', 'dprk russia military',
            # ══ EXPEDITIONARY FOOTPRINT (Jul 12 2026) ══
            # The gap that mattered most: the DPRK's most under-watched export is
            # LABOR. Where its workers and engineers appear, tunnels appear --
            # Hezbollah's network in Lebanon, the Gaza tunnels, now Kursk
            # reconstruction. Labor presence x malign-actor co-location is a
            # military-infrastructure transfer signal, and we had ZERO sensors on it.
            'north korean workers', 'dprk workers', 'north korean laborers',
            'dprk laborers', 'north korean engineers', 'dprk engineers',
            'north korean overseas workers', 'dprk overseas labor',
            'north korea tunnel', 'dprk tunnel', 'north korean tunnel',
            'tunnel construction north korea', 'north korea underground facility',
            'north korean advisers', 'dprk advisers', 'north korea military advisers',
            'north korea hezbollah', 'dprk hezbollah',
            'north korea hamas', 'dprk hamas',
            'north korea syria', 'north korea africa', 'dprk africa',
            'north korean workers russia', 'dprk workers russia',
            'north korea reconstruction russia', 'north korea kursk rebuild',

            # ══ LEADERSHIP / PURGE WATCH ══
            # Pyongyangology. Who is in frame, who vanished, who speaks for Kim.
            'kim yo jong', 'kim yo-jong', 'kim ju ae', 'kim ju-ae',
            'choe son hui', 'choe son-hui', 'pak jong chon', 'ri pyong chol',
            'jo yong won', 'kim tok hun', 'kim jong sik',
            'north korea purge', 'dprk purge', 'north korea executed',
            'north korea execution', 'north korea official removed',
            'north korea demoted', 'north korea reshuffle',
            'north korea politburo', 'workers party plenum',
            'central military commission', 'north korea succession',
            'kim jong un daughter', 'north korea heir',
            '김여정', '김주애', '최선희', '노동당 전원회의',

            # ══ TEST LOCATION + TYPE GRANULARITY ══
            # Location is the AUDIENCE. A lofted ICBM is addressed to Washington;
            # an SRBM into the East Sea is addressed to Seoul and Tokyo; Sohae is
            # prestige. Punggye-ri tunnel 3 is the Black Swan.
            'sohae', 'sohae satellite launching station', 'tongchang-ri',
            'punggye-ri tunnel', 'punggye-ri reactivation',
            'seventh nuclear test', '7th nuclear test',
            'north korea satellite launch', 'dprk satellite',
            'north korea reconnaissance satellite', 'north korea spy satellite',
            'sinpo', 'north korea lofted', 'lofted trajectory',
            'north korea hypersonic', 'dprk hypersonic',
            'north korea cruise missile', 'north korea solid-fuel',

            # ══ LEVERAGE DECAY / SIDELINING TELLS ══
            # The inverted read: the DPRK escalates when its leverage DECAYS, not
            # when it peaks. A test is a RELEVANCE signal -- the way Pyongyang
            # forces itself back onto an agenda it has been left off. So the
            # dangerous condition is being negotiated AROUND, and these are the
            # words that show it happening.
            'north korea sidelined', 'pyongyang sidelined',
            'north korea excluded', 'north korea snubbed',
            'kim skips', 'kim absent', 'kim did not attend',
            'north korea russia rift', 'dprk russia tension',
            'north korea troops withdrawal', 'north korea troops return',
            'russia aid north korea', 'russia oil north korea',
            'north korea food aid russia', 'north korea missile technology russia',

            # ══ ILLICIT FLOWS ══
            # Where the commodity story actually lives. Sanctions severed the DPRK's
            # reserves from any market, so there is no price to track -- only flows.
            'north korea coal smuggling', 'dprk coal', 'ship-to-ship transfer',
            'north korea sanctions evasion', 'dprk sanctions evasion',
            'north korea oil cap', 'north korea illicit',
            'lazarus group', 'north korea crypto theft', 'dprk crypto',

            # ══ CHINA BORDER + FOOD SECURITY ══
            # Famine is not only a humanitarian sensor here -- it is a LEVERAGE
            # variable. A hungrier DPRK needs its patrons more.
            'yalu river', 'tumen river', 'north korea china border',
            'north korea defector', 'dprk defector', 'north korea china trade',
            'north korea famine', 'dprk famine', 'north korea food shortage',
            'north korea food crisis', 'north korea harvest',

            # ══ IRAN DYAD ══
            'north korea iran', 'dprk iran', 'north korea iran missile',

            # Korean language signals
            '북한 미사일', '북한 핵', '김정은', '조선인민군',
            '북한 도발', '북한 발사', '탄도미사일',
            '북한 노동자', '북한 기술자', '풍계리', '동창리',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=north+korea+OR+dprk+OR+kim+jong+un+military+missile&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=north+korea+nuclear+OR+dprk+launch+OR+pyongyang+threatens&hl=en&gl=US&ceid=US:en',
        ]
    },

    'pakistan': {
        'name': 'Pakistan',
        'flag': '🇵🇰',
        'tier': 2,
        'theatre': 'asia_pacific',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Nuclear / missiles
            'pakistan nuclear', 'pakistan nuclear weapon',
            'pakistan nuclear arsenal', 'pakistan nuclear doctrine',
            'pakistan missile test', 'pakistan launches missile',
            'shaheen missile', 'ghauri missile', 'nasr missile',
            'pakistan tactical nuclear', 'pakistan ballistic missile',
            'pakistan cruise missile', 'babur missile',
            # Pakistan military operations (domestic)
            'pakistan military operation', 'pakistan army operation',
            'pakistan air force strike', 'pakistan jets strike',
            'pakistan military offensive', 'ispr pakistan',
            'pakistan kills militants', 'pakistan kills terrorists',
            'pakistan security forces', 'pakistan fc',
            # TTP — major daily signal source
            'tehrik-i-taliban pakistan', 'tehrik-e-taliban',
            'tehrik-i-taliban', 'tehrik e taliban',
            'ttp attack', 'ttp kills', 'ttp militants',
            'ttp fighters', 'ttp ambush', 'ttp soldiers',
            'ttp north waziristan', 'ttp south waziristan',
            'ttp khyber', 'ttp kurram', 'ttp bajaur',
            'pakistan taliban attack', 'pakistan taliban kills',
            'militant attack pakistan', 'terrorist attack pakistan',
            # Balochistan insurgency
            'balochistan attack', 'baloch insurgent',
            'bla attack', 'balochistan liberation army',
            'blf attack', 'balochistan separatist',
            'dera bugti attack', 'turbat attack', 'gwadar attack',
            # Iran-Pakistan cross-border (key 2026 events)
            'iran pakistan border', 'iran strikes pakistan',
            'iran bombs pakistan', 'iran attack pakistan',
            'iran missile pakistan', 'iran drone pakistan',
            'iran balochistan strike', 'iran jaish al-adl',
            'jaish al-adl', 'jaish al adl',
            'irgc pakistan strike', 'iran retaliates pakistan',
            'pakistan retaliates iran', 'pakistan iran border',
            'pakistan iran tension', 'pakistan iran military',
            'pakistan closes iran border', 'pakistan iran standoff',
            'pakistan retaliates', 'pakistan retaliation',
            'iran fires missiles pakistan', 'iran fires pakistan',
            'iran missiles balochistan', 'iran balochistan',
            'pakistan iran border crossing', 'pakistan iran escalation',
            'pakistan iran incident', 'pakistan iran drone',
            'iran border tension pakistan', 'iran pakistan escalation',
            'iran fires missiles', 'pakistan-iran border', 'iran missiles into pakistan',
            # India-Pakistan
            'india pakistan border', 'line of control', 'loc incident',
            'loc ceasefire violation', 'india pakistan skirmish',
            'india pakistan military', 'india pakistan tension',
            'india pakistan standoff', 'kashmir military',
            'kashmir insurgency', 'kashmir line of control',
            'pulwama', 'balakot', 'india strikes pakistan',
            'pakistan strikes india', 'india pakistan aerial',
            # US/China
            'pakistan us military', 'china pakistan military',
            'cpec security', 'gwadar security', 'gwadar attack',
            # Urdu signals
            'پاکستان فوج', 'پاکستان میزائل', 'ٹی ٹی پی',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=pakistan+military+OR+TTP+attack+OR+pakistan+iran+border&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=pakistan+army+operation+OR+balochistan+attack+OR+iran+pakistan+strike&hl=en&gl=US&ceid=US:en',
        ]
    },

    'afghanistan': {
        'name': 'Afghanistan',
        'flag': '🇦🇫',
        'tier': 3,
        'theatre': 'asia_pacific',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Taliban daily activity — broad catch
            'taliban', 'islamic emirate', 'islamic emirate of afghanistan',
            'taliban attack', 'taliban offensive', 'taliban operation',
            'taliban military', 'taliban forces', 'taliban fighters',
            'taliban seize', 'taliban capture', 'taliban kill',
            'taliban execute', 'taliban bomb', 'taliban ied',
            'taliban ambush', 'taliban checkpoint',
            'haqqani network', 'haqqani',
            'sirajuddin haqqani', 'mullah baradar',
            # Taliban governance / crackdowns
            'islamic emirate crackdown', 'taliban crackdown',
            'taliban suppress', 'taliban arrest',
            # TTP — Tehrik-i-Taliban Pakistan (daily news)
            'tehrik-i-taliban', 'tehrik-e-taliban',
            'ttp attack', 'ttp militants', 'ttp fighters',
            'ttp kills', 'ttp soldiers', 'ttp ambush',
            'pakistan taliban attack', 'pakistan taliban kills',
            # ISIS-K / ISKP
            'isis-k', 'iskp', 'islamic state khorasan',
            'islamic state afghanistan', 'khorasan province isis',
            'isis-k attack', 'iskp attack', 'iskp bomb',
            'isis khorasan attack', 'isis afghanistan',
            # Pakistan cross-border strikes (critical — major 2026 events)
            'pakistan strikes afghanistan', 'pakistan bombs afghanistan',
            'pakistan airstrike afghanistan', 'pakistan jets afghanistan',
            'pakistan military afghanistan', 'pakistan shelling afghanistan',
            'pakistan kills afghanistan', 'pakistan operation afghanistan',
            'pakistan afghanistan strike', 'pakistan afghanistan bombing',
            'pakistan bombs khost', 'pakistan bombs paktika',
            'pakistan bombs paktia', 'pakistan bombs kunar',
            'pakistan bombs nangarhar', 'pakistan bombs bajaur',
            'pakistan bombs mohmand', 'pakistan kills civilians afghanistan',
            'durand line', 'torkham border', 'chaman border',
            'pak-afghan border', 'pakistan afghanistan border tension',
            'afghanistan condemns pakistan', 'kabul condemns islamabad',
            # Iran cross-border
            'iran afghanistan border', 'iran strikes afghanistan',
            'iran afghanistan tension', 'nimroz border',
            # NRF / resistance
            'national resistance front', 'nrf afghanistan',
            'panjshir resistance', 'anti-taliban resistance',
            'ahmad massoud', 'panjshir fighters',
            # Key provinces / cities (conflict hotspots)
            'kabul attack', 'kabul bomb', 'kabul explosion',
            'kandahar attack', 'kandahar bomb',
            'helmand attack', 'helmand military',
            'kunduz attack', 'kunduz military',
            'nangarhar attack', 'jalalabad attack',
            'khost attack', 'paktika attack',
            'badakhshan attack', 'baghlan attack',
            'herat attack', 'herat military',
            'farah attack', 'nimroz attack',
            # Regional spillover
            'afghanistan civil war', 'afghanistan collapse',
            'afghanistan drone strike', 'afghanistan airstrike',
            # Dari/Pashto signals
            'افغانستان طالبان', 'د افغانستان', 'طالبان',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=afghanistan+taliban+OR+TTP+OR+isis-k+OR+pakistan+strikes+afghanistan&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=pakistan+airstrike+afghanistan+OR+pakistan+bombs+afghanistan+OR+haqqani&hl=en&gl=US&ceid=US:en',
            'https://tolonews.com/rss.xml',
        ]
    },

    'russia': {
        'name': 'Russia',
        'flag': '🇷🇺',
        'tier': 2,
        'theatre': 'europe',
        'weight': 0.7,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'russian navy mediterranean',
            # -- Arctic / Northern Fleet subsurface (Jul 2026) --
            'northern fleet', 'russian submarine atlantic', 'russian submarine arctic',
            'russian submarine norwegian sea', 'russian sub greenland',
            'yasen class', 'yasen-m', 'severodvinsk submarine', 'kazan submarine',
            'borei class', 'borei-a', 'knyaz vladimir',
            'kola peninsula', 'gadzhiyevo', 'severomorsk',
            'russian navy giuk', 'bear island exercise', 'barents sea exercise',
            'russia bastion defense', 'kalibr arctic', 'russian warship mediterranean',
            'russian submarine mediterranean', 'russia med fleet',
            'tartus naval base', 'hmeimim air base', 'russia syria deployment',
            'russian forces syria', 'russian air force syria',
            # -- Transnistria / OGRF garrison (Jul 2026): Russia's westernmost
            # forward-deployed force. Same structural-blindness lesson as DPRK --
            # do not let the platform be blind to a Russian garrison because it
            # sits inside a country with no army of its own. These read as
            # RUSSIA posture, correctly, not Moldova posture.
            'russian troops transnistria', 'russian forces transnistria',
            'operational group of russian forces', 'ogrf transnistria',
            'cobasna ammunition', 'cobasna depot', 'colbasna',
            'russian peacekeepers moldova', 'russian peacekeepers transnistria',
            'transnistria military', 'tiraspol garrison', 'security zone dniester',
            'russian troops moldova', 'transnistria mobilization',
            'russian warship', 'russian destroyer', 'russian frigate',
            'russian submarine', 'russia black sea fleet',
            'russia naval exercise', 'russian aircraft carrier',
            'russian bomber patrol', 'tu-95 patrol', 'tu-160',
            'russian air force middle east', 'su-35 syria',
            'russia arms delivery', 'russia s-300', 'russia s-400',
            'russia weapons syria', 'russia iran military cooperation',
            'russian offensive ukraine', 'russia ukraine front',
            'russian forces ukraine', 'russia mobilization',
            'russian missile ukraine', 'russia drone ukraine',
            'russian artillery ukraine', 'wagner group',
            'russia nuclear posture', 'russia nuclear threat',
            'russia black sea', 'russian black sea fleet',
            'sevastopol naval base', 'crimea military',
            'russia arctic military', 'northern fleet',
            'russia arctic exercise',
            # Russian Arctic submarine / deterrence posture (v3.1.0)
            'borei class submarine', 'borei ssbn', 'russia ssbn patrol',
            'russia submarine arctic patrol', 'russia submarine kola',
            'severodvinsk submarine', 'yasen class submarine',
            'northern fleet submarine', 'russian submarine nato',
            'russian submarine norway', 'russian submarine atlantic',
            'russia submarine deployment arctic', 'kola peninsula submarine',
            'russian nuclear submarine', 'russia slbm patrol',
            'russia ballistic missile submarine', 'russia strategic submarine',
            'submarine exercise barents', 'barents sea exercise',
            'arctic underwater', 'russia underwater drone',
            # Kola Peninsula / Northern Fleet base
            'murmansk military', 'severomorsk', 'gadzhiyevo',
            'olenya airfield', 'russian arctic base',
            # Russian keywords (match GDELT Russian-language articles)
            'вооруженные силы', 'военная операция', 'ракетный удар',
            'черноморский флот', 'северный флот', 'мобилизация',
            'наступление', 'артиллерия', 'ПВО', 'учения',
            'ядерное оружие', 'стратегические силы',
            'крылатая ракета', 'баллистическая ракета',
            'военно-морской флот', 'подводная лодка',
            'бомбардировщик', 'истребитель',
            'дрон', 'беспилотник', 'БПЛА',
            'фронт', 'контрнаступление', 'оборона',
            # Active war keywords (v2.7.1)
            'russia launches missiles', 'russia fires missiles',
            'russian missile strike', 'russian drone strike',
            'russia attacks ukraine', 'russian offensive',
            'russia shahed', 'russian shahed drone',
            'russia escalation', 'russia nuclear warning',
            'putin warns', 'putin threatens',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=russia+military+OR+missile+OR+offensive+OR+ukraine+attack&hl=en&gl=US&ceid=US:en',
        ]
    },

    # ------------------------------------------------
    # TIER 3 — Regional actors (Middle East)
    # ------------------------------------------------
    'saudi_arabia': {
        'name': 'Saudi Arabia',
        'flag': '🇸🇦',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'saudi military', 'saudi air force', 'royal saudi navy',
            'saudi air defense', 'saudi patriot', 'saudi thaad',
            'saudi arabia military exercise', 'saudi naval exercise',
            'saudi yemen border', 'saudi military buildup',
            'saudi defense spending', 'saudi arms deal',
            'saudi intercept', 'saudi houthi',
            'us cargo planes saudi', 'saudi base',
            'prince sultan air base', 'king abdulaziz air base',
            'king fahd air base', 'eskan village',
            # War keywords (v2.7.0)
            'iran strike saudi', 'iranian missile saudi',
            'iranian attack saudi arabia', 'iran drone saudi',
            'saudi intercept missile', 'saudi air defense activated',
            'riyadh attack', 'riyadh missile', 'riyadh drone',
            'eastern province attack', 'dhahran attack',
            'aramco attack', 'saudi oil attack',
            'saudi embassy closed', 'saudi shelter in place',
            'us embassy saudi closed', 'saudi arabia war',
            'houthi attack saudi', 'houthi missile riyadh',
            'us embassy riyadh hit', 'us embassy riyadh drone',
            'us embassy riyadh attack', 'riyadh embassy strike',
            'iran strikes saudi arabia', 'ballistic missile riyadh',
            'riyadh struck', 'riyadh hit', 'jeddah attack',
            'saudi oil facility attack', 'ras tanura attack',
            'saudi port attack', 'jubail attack',
            'iran drone riyadh', 'iranian drone saudi',
            # Arabic keywords
            'القوات المسلحة السعودية', 'تدريب عسكري السعودية',
            'هجوم على السعودية', 'صاروخ إيراني السعودية',
            'الدفاع الجوي السعودي', 'قاعدة الأمير سلطان',
            'أرامكو هجوم', 'الرياض هجوم',
            # v2.7.3 — confirmed strike / active defense
            'ukraine technicians saudi', 'ukraine experts saudi arabia',
            'ukraine advisors ksa', 'ukraine technical team saudi',
            'ksa drone shoot down', 'saudi drone intercept confirmed',
            'saudi shoots down drone', 'saudi shot down iranian drone',
            'iran bombs saudi', 'iran bombed saudi arabia',
            'saudi struck iran', 'saudi under attack',
            'saudi hit confirmed', 'saudi arabia bombed',
            'saudi arabia war footing', 'saudi high alert',
            'riyadh sirens', 'riyadh incoming', 'riyadh hit confirmed',
            'ordered departure ksa', 'ordered departure saudi',
            'us embassy riyadh ordered departure',
            'saudi retaliates', 'saudi response iran',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=saudi+arabia+military+OR+missile+OR+attack+OR+defense&hl=en&gl=US&ceid=US:en',
        ]
    },

    'uae': {
        'name': 'United Arab Emirates',
        'flag': '🇦🇪',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'uae forces', 'uae military', 'uae air force',
            'uae naval', 'uae military exercise',
            'al dhafra air base', 'uae defense',
            'uae arms deal', 'uae military buildup',
            'uae evacuation', 'uae departure',
            'emirates military', 'uae drone',
            # Active conflict — Mar 2026
            'uae shoots down', 'uae shot down', 'uae intercepts drone',
            'uae intercepts missile', 'uae downs iranian drone',
            'uae air defense fires', 'uae air defense activated',
            'uae scrambles jets', 'uae scrambles fighters',
            'uae retaliates', 'uae responds firmly',
            'uae warns iran', 'uae threatens iran',
            'uae mobilization', 'uae deploys', 'uae deployed',
            'uae patriot', 'uae thaad', 'uae pantsir',
            'iran strike uae', 'iranian missile uae',
            'iranian attack uae', 'iran drone uae',
            'iranian drone abu dhabi', 'iranian drone dubai',
            'iran attacks emirates', 'iran bombards uae',
            'dubai attack', 'dubai missile', 'dubai drone',
            'abu dhabi attack', 'abu dhabi missile', 'abu dhabi drone',
            # -- Israel security cooperation, receiving side (Jul 2026) --
            'uae israel defense', 'uae israeli weapons', 'uae israeli training',
            'uae buys israeli', 'uae israeli air defense', 'uae barak',
            'edge group rafael', 'edge group elbit', 'uae israel exercise',
            'uae israel joint', 'emirati israeli defense', 'uae spyder',
            'us embassy dubai', 'us embassy dubai hit',
            'us embassy abu dhabi', 'uae shelter',
            'al dhafra attack', 'al dhafra missile', 'al dhafra struck',
            'jebel ali port attack', 'jebel ali struck', 'uae war',
            'houthi attack uae', 'houthi missile uae', 'houthi drone uae',
            'fujairah attack', 'fujairah port', 'fujairah struck',
            'fujairah missile', 'fujairah drone',
            'uae embassy attack', 'uae embassy struck',
            'iran strikes uae', 'ballistic missile dubai',
            'ballistic missile abu dhabi', 'iran drone dubai',
            'uae port struck', 'uae port attack',
            'uae airspace closed', 'uae flights cancelled',
            'dubai airport closed', 'abu dhabi airport closed',
            'emirates flights cancelled', 'etihad flights cancelled',
            'flydubai cancelled', 'uae siren', 'uae casualties',
            # Arabic keywords
            'القوات المسلحة الإماراتية',
            'هجوم على الإمارات', 'صاروخ إيراني الإمارات',
            'دبي هجوم', 'أبوظبي هجوم',
            'قاعدة الظفرة', 'السفارة الأمريكية دبي',
            'الإمارات تسقط طائرة', 'الإمارات دفاع جوي',
            'الإمارات إيران', 'الإمارات تعبئة',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=UAE+OR+dubai+OR+abu+dhabi+military+OR+missile+OR+attack+OR+iran+OR+intercept+OR+drone&hl=en&gl=US&ceid=US:en',
        ]
    },
    'jordan': {
        'name': 'Jordan',
        'flag': '🇯🇴',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'jordan military', 'jordanian armed forces',
            'muwaffaq salti', 'tower 22', 'jordan air base',
            'jordan border', 'jordan syria border',
            'f-15 jordan', 'us forces jordan',
            'jordan military exercise', 'jordan defense',
            'jordan intercept', 'jordan air defense',
            'eager lion exercise', 'jordan base',
            'us cargo planes jordan', 'strike eagles jordan',
            # War keywords (v2.7.0)
            'jordan intercept drone', 'jordan intercept missile',
            'jordan intercept ballistic', 'jordan shoots down',
            'jordanian airspace violation', 'jordan airspace',
            'jordan air defense activated', 'jordan scramble jets',
            'debris jordan', 'fragments jordan', 'shrapnel jordan',
            'iran missile jordan', 'iranian drone jordan',
            'jordan shelter', 'amman attack', 'amman missile',
            'us embassy jordan closed', 'jordan war',
            'jordan intercepted drones', 'jordan intercepted missiles',
            # Arabic keywords
            'القوات الأردنية', 'الجيش الأردني',
            'الأردن اعتراض صاروخ', 'الأردن دفاع جوي',
            'المجال الجوي الأردني', 'عمان هجوم',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=jordan+military+OR+intercept+OR+missile+OR+airspace&hl=en&gl=US&ceid=US:en',
        ]
    },

'qatar': {
        'name': 'Qatar',
        'flag': '🇶🇦',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.6,
        'feeds_into': ['strike_probability', 'regional_tension'],
        'keywords': [
            'al udeid air base', 'al udeid', 'qatar base',
            'centcom forward headquarters', 'centcom hq qatar',
            'qatar military', 'qatar defense',
            'qatar air base evacuation', 'al udeid evacuation',
            'qatar military exercise', 'us forces qatar',
            # War keywords (v2.7.0)
            'al udeid hit', 'al udeid attack', 'al udeid missile',
            'al udeid struck', 'iran missile qatar',
            'iranian attack qatar', 'iranian strike qatar',
            'qatar intercept missile', 'qatar air defense',
            'qatar airspace closed', 'qatar flights suspended',
            'qatar airways grounded', 'qatar flights grounded',
            'doha attack', 'doha missile', 'doha shelter',
            'qatar civil aviation suspended', 'qatar war',
            'قطر هجوم', 'قاعدة العديد', 'الدوحة صاروخ',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=qatar+OR+al+udeid+military+OR+missile+OR+attack+OR+flights&hl=en&gl=US&ceid=US:en',
        ]
    },

    'kuwait': {
        'name': 'Kuwait',
        'flag': '🇰🇼',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.6,
        'feeds_into': ['strike_probability', 'regional_tension'],
        'keywords': [
            'camp arifjan', 'kuwait military', 'kuwait base',
            'us forces kuwait', 'kuwait defense',
            'ali al salem air base', 'kuwait evacuation',
            'kuwait military exercise',
            # Active conflict — Mar 2026
            'kuwait mobilization', 'kuwait deploys', 'kuwait deployed',
            'kuwait army deployed', 'kuwait forces deployed',
            'kuwait iran', 'iran bombard kuwait', 'iran bombs kuwait',
            'iran attacks kuwait', 'iranian bombardment kuwait',
            'iranian strike kuwait', 'iranian missile kuwait',
            'iranian attack kuwait', 'iran drone kuwait',
            'kuwait embassy closed', 'us embassy kuwait closed',
            'us embassy kuwait evacuated', 'embassy closure kuwait',
            'kuwait retaliates', 'kuwait strikes iran',
            'kuwait scrambles jets', 'kuwait air force scramble',
            'kuwait shoots down', 'kuwait intercepts',
            'kuwait patriot', 'kuwait thaad', 'kuwait iron dome',
            'kuwait port attack', 'kuwait drone strike',
            'us soldiers killed kuwait', 'us troops killed kuwait',
            'kuwait intercept missile', 'kuwait air defense',
            'kuwait city attack', 'kuwait shrapnel',
            'kuwait warplanes crashed', 'kuwait war',
            'camp arifjan attack', 'ali al salem attack',
            'camp arifjan struck', 'ali al salem struck',
            'kuwait casualties', 'kuwait killed', 'kuwait wounded',
            'us embassy kuwait hit', 'us embassy kuwait drone',
            'us embassy kuwait attack', 'kuwait embassy strike',
            'kuwait troops dead', 'american soldiers kuwait',
            'soldiers died kuwait', 'troops died kuwait',
            'kuwait base struck', 'kuwait base hit',
            'iran strikes kuwait', 'ballistic missile kuwait',
            'cruise missile kuwait', 'kuwait siren', 'kuwait shelter',
            'kuwait airspace closed', 'kuwait flights cancelled',
            'kuwait airport closed', 'kuwait martial law',
            # Arabic keywords
            'الكويت هجوم', 'صاروخ إيراني الكويت',
            'معسكر عريفجان', 'قاعدة علي السالم',
            'السفارة الأمريكية الكويت',
            'الكويت تعبئة', 'الكويت حرب', 'الكويت قصف',
            'الكويت إيران', 'الكويت دفاع جوي',
            # v2.7.3 — confirmed strike / ordered departure
            'us embassy kuwait ordered departure',
            'ordered departure kuwait',
            'embassy kuwait shuttered', 'embassy kuwait closed war',
            'kuwait fighter pilots scramble',
            'kuwait jets intercept', 'kuwait air force scramble iran',
            'iran bombs kuwait', 'iran bombed kuwait',
            'iranian strike kuwait confirmed', 'kuwait struck iran',
            'kuwait under attack', 'kuwait hit', 'kuwait bombed',
            'kuwait war footing', 'kuwait high alert',
            'kuwait city sirens', 'kuwait incoming missile',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=kuwait+military+OR+arifjan+OR+ali+al+salem+OR+missile+OR+attack+OR+iran&hl=en&gl=US&ceid=US:en',
        ]
    },

    'bahrain': {
        'name': 'Bahrain',
        'flag': '🇧🇭',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.6,
        'feeds_into': ['strike_probability', 'regional_tension'],
        'keywords': [
            # US 5th Fleet / Naval Forces Central Command
            'us 5th fleet', 'fifth fleet', 'navcent', 'naval forces central command',
            'nsa bahrain', 'naval support activity bahrain',
            'us naval base bahrain', 'bahrain naval base',
            'juffair', 'mina salman',
            # Bahrain military
            'bahrain military', 'bahrain defense force', 'bdf',
            'bahrain air force', 'bahrain navy',
            'bahrain military exercise', 'bahrain defense',
            'bahrain base', 'bahrain deployment',
            'sheikh isa air base', 'bahrain airbase',
            # Regional role
            'bahrain iran tensions', 'bahrain security',
            'combined maritime forces bahrain', 'cmf bahrain',
            'international maritime security construct',
            'combined task force 150', 'ctf 150',
            'combined task force 152', 'ctf 152',
            'combined task force 153', 'ctf 153',
            'bahrain evacuation', 'bahrain departure',
            'bahrain threat', 'bahrain alert',
            # Bahrain defense / intercept (v2.7.2)
            'bahrain intercept missile', 'bahrain intercept drone',
            'bahrain air defense', 'bahrain air defense activated',
            'bahrain shoots down', 'bahrain shelter',
            'manama attack', 'manama missile', 'manama struck',
            'bahrain struck', 'bahrain hit', 'bahrain shrapnel',
            'iran attack bahrain', 'iranian missile bahrain',
            'iranian strike bahrain', 'iran drone bahrain',
            # Arabic keywords
            'قوة دفاع البحرين', 'الأسطول الخامس',
            'القاعدة البحرية البحرين',
        ],
        'rss_feeds': []
    },

    'egypt': {
        'name': 'Egypt',
        'flag': '🇪🇬',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'egyptian military', 'egypt military exercise',
            'egyptian navy', 'egypt suez canal military',
            'egypt sinai operation', 'egyptian air force',
            'egypt rafale', 'egypt military buildup',
            'egypt libya border', 'egypt gaza border',
            'egypt israel border troops', 'bright star exercise',
            # War keywords (v2.7.0)
            'suez canal closed', 'suez canal military',
            'suez canal disruption', 'egypt rafah crossing',
            'egypt gaza humanitarian', 'egypt border tensions',
            'egypt air defense', 'egypt intercept',
            'egypt airspace', 'cairo military alert',
            'egypt sinai buildup', 'egypt red sea military',
            'sharm el sheikh military', 'egypt war footing',
            'egypt intercept missile', 'egypt intercept drone',
            'egypt scramble jets', 'egyptian jets scramble',
            'egypt closes airspace', 'egypt airspace closed',
            'cairo alert', 'egypt military alert',
            'egypt mobilization', 'egypt deploys troops sinai',
            'suez canal attack', 'suez canal struck',
            'suez canal closed war', 'suez shipping disruption',
            'egypt red sea patrol', 'egypt naval deployment',
            # Arabic keywords
            'الجيش المصري', 'القوات المسلحة المصرية',
            'قناة السويس عسكري', 'مصر دفاع جوي',
            'سيناء عملية', 'معبر رفح',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=egypt+military+OR+suez+OR+sinai+OR+defense&hl=en&gl=US&ceid=US:en',
        ]
    },

    'oman': {
        'name': 'Oman',
        'flag': '🇴🇲',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'oman military', 'royal oman armed forces',
            'oman air force', 'oman navy', 'oman defense',
            'oman strait of hormuz', 'oman gulf',
            'muscat military', 'oman base',
            'oman us military', 'oman access agreement',
            'masirah island', 'thumrait air base',
            'duqm port', 'duqm naval base', 'port of duqm',
            'oman air defense', 'oman intercept',
            # War keywords (v2.7.0)
            'iran attack oman', 'iranian missile oman',
            'oman airspace', 'oman airspace violation',
            'oman strait closure', 'oman war',
            'oman intercept missile', 'oman shelter',
            'muscat attack', 'duqm attack',
            'salalah', 'salalah attack', 'salalah strike', 'salalah bombed',
            'salalah refinery', 'salalah oil', 'oman refinery attack',
            'oman oil refinery', 'iran bombs oman', 'iran bombed oman',
            'iranian strike oman', 'iranian missile oman', 'iran attack oman',
            'oman struck', 'oman under attack', 'oman hit', 'oman casualties',
            'oman killed', 'royal air force oman scramble',
            'صلالة هجوم', 'صلالة مصفاة', 'إيران تقصف عمان',
            'oman evacuation', 'oman embassy',
            # Arabic keywords
            'القوات المسلحة العمانية', 'سلطنة عمان عسكري',
            'ميناء الدقم', 'مسقط هجوم',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=oman+military+OR+muscat+OR+duqm+OR+salalah+OR+refinery+OR+iran+OR+strike&hl=en&gl=US&ceid=US:en',
        ]
    },

    'turkey': {
        'name': 'Turkey',
        'flag': '🇹🇷',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'turkish military syria', 'turkish forces syria',
            'operation claw', 'turkish navy', 'turkish air force',
            'turkish drone strike', 'bayraktar tb2', 'akinci drone',
            'incirlik air base', 'turkish military exercise',
            'turkish navy mediterranean', 'turkish naval exercise',
            'turkey northern iraq', 'turkey pkk operation',
            'turkish ground operation syria',
            'turkey nato', 'turkish military nato',
            # War keywords (v2.7.0)
            'incirlik attack', 'incirlik strike', 'incirlik base alert',
            'turkey iran tensions', 'iran attack turkey',
            'iranian missile turkey', 'turkish airspace violation',
            'turkey air defense', 'turkey intercept',
            'turkey bosphorus military', 'turkish straits closure',
            'turkey border alert', 'erdogan military',
            'turkey war', 'turkey nato article 5',
            # Turkish keywords
            'türk silahlı kuvvetleri', 'türk donanması',
            'hava kuvvetleri', 'askeri operasyon',
            'İncirlik üssü saldırı', 'hava savunma',
            'füze saldırısı', 'savaş', 'NATO madde 5',
            # Active war — intercepts & strikes (v2.7.1)
            'turkey intercepts missile', 'turkey intercepts ballistic',
            'turkey shoots down drone', 'turkey shoots down missile',
            'turkish intercept', 'turkey missile intercept',
            'incirlik high alert', 'incirlik closed',
            'iran strikes turkey', 'iran attacks turkey',
            'iranian missile hits turkey', 'iranian drone turkey',
            'turkey scrambles jets', 'turkish jets scramble',
            'ankara shelter', 'istanbul shelter',
            'turkey activates air defense', 'turkey nato article 5',
            'turkey invokes article 5', 'article 5 turkey',
            'debris falls turkey', 'shrapnel turkey',
            'missile intercepted over turkey',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=turkey+military+OR+incirlik+OR+erdogan+defense+OR+attack&hl=en&gl=US&ceid=US:en',
        ]
    },

    # ------------------------------------------------
    # TIER 3 — Regional actors (Europe)
    # ------------------------------------------------
    'ukraine': {
        'name': 'Ukraine',
        'flag': '🇺🇦',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'ukraine military', 'ukrainian armed forces',
            'ukraine offensive', 'ukraine counteroffensive',
            'ukraine front line', 'ukraine defense',
            'zaporizhzhia front', 'kherson front', 'bakhmut',
            'kursk incursion', 'ukraine kursk',
            'donetsk front', 'luhansk front',
            'ukraine f-16', 'ukraine patriot', 'ukraine air defense',
            'ukraine himars', 'ukraine storm shadow',
            'ukraine atacms', 'ukraine drone warfare',
            'ukraine long range strike', 'ukraine missile',
            'ukraine black sea', 'ukraine naval drone',
            'ukraine anti-ship', 'ukraine sea drone',
            'ukraine arms delivery', 'ukraine weapons package',
            'ukraine military aid', 'ukraine ammunition',
            'ukraine defense package',
            'ukraine mobilization', 'ukraine conscription',
            'ukraine reserves', 'ukraine recruitment',
            # Ukrainian keywords (match GDELT Ukrainian articles)
            'збройні сили', 'зброя', 'наступ', 'оборона',
            'фронт', 'мобілізація', 'протиповітряна оборона',
            'ракетний удар', 'артилерія', 'дрон', 'БПЛА',
            'контрнаступ', 'зенітна ракета',
            'постачання зброї', 'військова допомога',
            'морський дрон', 'безпілотник',
            # Russian keywords (many Ukraine war articles in Russian)
            'украина наступление', 'украина фронт',
            'украина оружие', 'украина мобилизация',
            'ВСУ', 'вооруженные силы украины'
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=ukraine+military+OR+missile+OR+offensive+OR+drone+attack&hl=en&gl=US&ceid=US:en',
        ]
    },

    'greenland': {
        'name': 'Greenland',
        'flag': '🇬🇱',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.4,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # English — sovereignty & acquisition
            'greenland sovereignty', 'greenland acquisition', 'greenland trump',
            'greenland independence', 'greenland autonomy', 'greenland referendum',
            'greenland self-rule', 'greenland self-determination',
            'greenland purchase', 'buy greenland', 'us greenland deal',
            'greenland strategic', 'greenland geopolitical',
            # English — military & Arctic
            'greenland military', 'greenland defense', 'greenland defence',
            'greenland nato', 'greenland arctic', 'greenland us military',
            'thule air base', 'pituffik space base',
            'greenland radar', 'greenland early warning',
            'greenland surveillance', 'greenland patrol',
            'arctic military exercise', 'arctic sovereignty',
            'arctic nato', 'arctic icebreaker',
            'us arctic strategy', 'arctic military buildup',
            # English — resources & China
            'greenland rare earth', 'greenland critical minerals',
            'greenland mining', 'greenland china', 'greenland mineral',
            'greenland lithium', 'greenland uranium',
            # English — Denmark relations
            'denmark greenland', 'danish armed forces greenland',
            'denmark military greenland', 'greenland denmark tensions',
            'múte egede', 'naalakkersuisut',
            # Danish keywords (match GDELT Danish articles)
            'grønland', 'grønlands selvstyre', 'grønland forsvar',
            'grønland suverænitet', 'grønland nato',
            'grønland militær', 'pituffik', 'thule',
            'arktisk forsvar', 'arktisk sikkerhed',
            'forsvaret grønland',
            # Greenlandic
            'kalaallit nunaat', 'namminersorlutik',
        ],
        'rss_feeds': []
    },

    'poland': {
        'name': 'Poland',
        'flag': '🇵🇱',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # English — military posture
            'poland military', 'polish armed forces', 'polish army',
            'poland defense spending', 'poland defence spending',
            'poland military buildup', 'poland military modernization',
            'poland nato', 'poland nato deployment',
            'poland eastern flank', 'nato poland',
            'us forces poland', 'us troops poland',
            'poland patriot', 'poland air defense',
            'poland himars', 'poland abrams', 'poland k2 tanks',
            'poland f-35', 'poland military procurement',
            # English — drone incursions & airspace violations
            'poland drone incursion', 'drone over poland',
            'drone crossed into poland', 'drone entered polish airspace',
            'poland airspace violation', 'airspace violation poland',
            'unidentified drone poland', 'mystery drone poland',
            'drone flyover poland', 'drone overflight poland',
            'poland border drone', 'drone from belarus',
            'drone from ukraine entered poland', 'drone from russia poland',
            'stray drone poland', 'wayward drone poland',
            'poland scramble jets', 'poland intercept drone',
            'poland shoot down drone', 'poland airspace incursion',
            'object entered polish airspace', 'missile entered poland',
            'projectile crossed into poland', 'poland airspace breach',
            'przewodów', 'przewodow missile',
            # English — border & Belarus
            'poland border', 'poland belarus border',
            'poland ukraine border', 'poland border crisis',
            'poland border troops', 'poland border security',
            'poland migration crisis', 'hybrid warfare poland',
            'belarus hybrid attack', 'lukashenko poland border',
            # English — exercises & bases
            'poland military exercise', 'steadfast defender poland',
            'dragon exercise poland', 'anakonda exercise',
            'rzeszów', 'rzeszow logistics', 'poland logistics hub',
            'redzikowo', 'aegis ashore poland',
            'poland missile defense', 'poland shield',
            'lask air base', 'poznań military',
            # Polish keywords (match GDELT Polish articles)
            'wojsko polskie', 'siły zbrojne',
            'dron nad polską', 'naruszenie przestrzeni powietrznej',
            'obrona powietrzna', 'ćwiczenia wojskowe',
            'granica polsko-białoruska', 'granica polsko-ukraińska',
            'modernizacja armii', 'zakupy wojskowe',
            'NATO w Polsce', 'flanka wschodnia',
            'incydent graniczny', 'obiekt w przestrzeni powietrznej',
            'bezzałogowiec', 'dron zwiadowczy',
        ],
        'rss_feeds': []
    },

    'cyprus': {
        'name': 'Cyprus',
        'flag': '🇨🇾',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'cyprus military',
            # -- Subsurface / GIUK watch (Jul 2026) --
            'submarine near greenland', 'submarine greenland waters', 'pituffik',
            'thule submarine', 'denmark strait submarine', 'greenland sea submarine',
            'russian sub denmark strait', 'sosus', 'undersea cable arctic', 'cyprus defense', 'cyprus defence',
            'cyprus base', 'cyprus british base',
            'akrotiri base', 'raf akrotiri', 'akrotiri attack',
            'akrotiri drone', 'akrotiri strike',
            'dhekelia base', 'sovereign base areas',
            'cyprus air base', 'cyprus nato',
            # War keywords (v2.7.0)
            'iran attack cyprus', 'iranian drone cyprus',
            'iranian strike cyprus', 'iran missile cyprus',
            'cyprus airspace closed', 'cyprus flights cancelled',
            'cyprus evacuation', 'us evacuate cyprus',
            'cyprus shelter', 'nicosia attack',
            'limassol military', 'larnaca military',
            'paphos air base', 'andreas papandreou air base',
            'cyprus intercept', 'cyprus air defense',
            'european forces cyprus', 'france cyprus',
            'uk forces cyprus', 'british forces cyprus',
            'greece deploy cyprus', 'cyprus war',
            'cyprus reinforcement', 'destroyer cyprus',
            # Greek keywords
            'κύπρος στρατιωτικό', 'ακρωτήρι βάση',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=cyprus+military+OR+akrotiri+OR+attack+OR+evacuation&hl=en&gl=US&ceid=US:en',
        ]
    },
    'greece': {
        'name': 'Greece',
        'flag': '🇬🇷',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Hellenic armed forces
            'greece military', 'greek armed forces', 'hellenic army',
            'hellenic navy', 'hellenic air force', 'greek defense', 'greek defence',
            'greek general staff', 'greece mobilization', 'greece mobilisation',
            # Aegean / Greece-Turkey dyad
            'greece turkey tensions', 'aegean dispute', 'aegean airspace',
            'aegean overflight', 'turkish overflight aegean', 'greek airspace violation',
            'greece turkey dogfight', 'greek f-16', 'greek rafale', 'greek mirage 2000',
            'casus belli aegean', 'imia islet', 'kastellorizo', 'greek islands militarization',
            # Evros land border
            'evros border', 'evros greece turkey', 'evros militarization',
            'greek border guards', 'evros migrants', 'greece migrants pushback',
            # Air defense / hardware
            'greek s-300', 's-300 crete', 'greek patriot', 'belharra frigate',
            'kimon frigate', 'greek navy frigate', 'greek submarine fleet',
            # Bases (US / NATO)
            'souda bay', 'souda bay crete', 'nsa souda bay', 'larissa air base',
            'andravida air base', 'stefanovikio', 'alexandroupoli port',
            # Cyprus / Eastern Med projection
            'greece deploy cyprus', 'greek jets cyprus', 'greece cyprus military',
            'greek f-16 cyprus', 'eastern mediterranean greece', 'greece eez',
            'greece libya maritime', 'greece egypt eez', 'greece france defense',
            'greece nato', 'greece israel defense',
            # Greek-language keywords
            'ελληνικός στρατός',
            'πολεμική αεροπορία',
            'αιγαίο', 'ελληνοτουρκικά',
            'εθνική άμυνα', 'ένοπλες δυνάμεις',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=greece+military+OR+aegean+OR+hellenic+OR+evros+OR+%22greece+turkey%22&hl=en&gl=US&ceid=US:en',
        ]
    },

  'azerbaijan': {
        'name': 'Azerbaijan',
        'flag': '🇦🇿',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'azerbaijan military', 'azerbaijani army', 'azerbaijani forces',
            'azerbaijan defense', 'azerbaijan defence',
            'azerbaijan mobilization', 'azerbaijan mobilisation',
            'aliyev military', 'azerbaijan drone', 'azerbaijan bayraktar',
            'azerbaijan tb2', 'azerbaijan harop', 'azerbaijan orbiter',
            'nakhchivan', 'nakhchivan attack', 'nakhchivan airport',
            'nakhchivan drone', 'nakhchivan missile',
            'azerbaijan iran', 'iran azerbaijan border',
            'iran baku', 'iran attack azerbaijan',
            'iranian drone azerbaijan', 'iranian missile azerbaijan',
            'azerbaijan israel', 'israel azerbaijan base',
            'baku tbilisi ceyhan', 'btc pipeline', 'btc pipeline attack',
            'shah deniz', 'socar', 'azerbaijan oil',
            'azerbaijan gas', 'sangachal terminal',
            'karabakh', 'nagorno-karabakh', 'lachin corridor',
            'zangezur corridor', 'azerbaijan armenia border',
            'azerbaijan airspace', 'azerbaijan air force',
            'azerbaijan navy', 'caspian flotilla',
            'ganja military', 'baku military',
            'Азербайджан военный', 'Баку армия',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=azerbaijan+military+OR+nakhchivan+OR+drone+OR+mobilization+OR+iran&hl=en&gl=US&ceid=US:en',
        ]
    },
    'hungary': {
        'name': 'Hungary',
        'flag': '🇭🇺',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.4,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # ── Democratic transition / internal ─────────────────
            'hungary military', 'hungarian army', 'hungarian defense',
            'hungary defence', 'hungary nato', 'hungary armed forces',
            'honved', 'hungarian honved',
            # ── Russian interference / hybrid ─────────────────────
            'russia hungary military', 'russian interference hungary',
            'hungary hybrid attack', 'hungary cyber attack',
            'hungary disinformation', 'fidesz military',
            # ── EU / NATO re-integration signals ──────────────────
            'hungary nato reintegration', 'hungary ukraine weapons',
            'hungary ukraine aid military', 'paks nuclear hungary',
            'rosatom hungary', 'hungary defense spending',
            # ── Regional / border ─────────────────────────────────
            'hungary border', 'hungary serbia border',
            'hungary ukraine border', 'hungary slovakia border',
            'budapest military', 'hungary airspace',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=hungary+military+OR+nato+OR+defense+OR+armed+forces&hl=en&gl=US&ceid=US:en',
        ]
    },

    'armenia': {
        'name': 'Armenia',
        'flag': '🇦🇲',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'armenia military', 'armenian army', 'armenian forces',
            'armenia defense', 'armenia defence',
            'armenia mobilization', 'armenia mobilisation',
            'pashinyan military', 'armenia border',
            'armenia azerbaijan border', 'syunik',
            'armenia iran border', 'armenia airspace',
            'armenia air defense', 'armenia pvo',
            'armenia russia base', 'gyumri base', 'russian base gyumri',
            'armenia CSTO', 'CSTO withdrawal', 'CSTO armenia',
            'armenia nato', 'armenia eu defense',
            'armenia french weapons', 'france armenia military',
            'india armenia weapons', 'india armenia defense',
            'armenia drone', 'armenia missile',
            'yerevan military', 'zvartnots',
            'armenia evacuation', 'armenia corridor iran',
            'lachin', 'artsakh military',
            'zangezur corridor', 'crossroads of peace',
            'armenia azerbaijan peace treaty', 'eu monitoring mission armenia',
            'Армения военный', 'Ереван армия',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=armenia+military+OR+yerevan+OR+defense+OR+CSTO+OR+border&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=zangezur+OR+armenia+azerbaijan+peace+OR+syunik&hl=en&gl=US&ceid=US:en',
            'https://www.azatutyun.am/api/zrqiteuuir',
        ]
    },

    'kazakhstan': {
        'name': 'Kazakhstan',
        'flag': '🇰🇿',
        'tier': 3,
        'theatre': 'europe',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'kazakhstan military', 'kazakh army', 'kazakhstan defense',
            'kazakhstan defence', 'kazakhstan mobilization',
            'baikonur', 'baikonur cosmodrome', 'russia baikonur',
            'kazakhstan csto', 'csto kazakhstan', 'csto exercise',
            'kazakhstan russia exercise', 'kazakhstan russia military',
            'kazakhstan china military', 'kazakhstan china exercise',
            'caspian flotilla', 'kazakhstan caspian',
            'kazakhstan border russia', 'kazakhstan border china',
            'kazakhstan unrest', 'kazakhstan protests military',
            'tokayev military', 'astana military', 'almaty unrest',
            'kazakhstan air defense', 'kazakhstan drone',
            'Казахстан военный', 'Казахстан армия', 'ОДКБ Казахстан',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=kazakhstan+military+OR+baikonur+OR+CSTO+OR+tokayev&hl=en&gl=US&ceid=US:en',
        ]
    },
  
    # ------------------------------------------------
    # TIER 4 — NATO / Alliance (Europe + Arctic expansion)
    # ------------------------------------------------
    'nato': {
        'name': 'NATO',
        'flag': '🏳️',
        'tier': 4,
        'theatre': 'europe',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'nato exercise', 'nato deployment', 'nato military exercise',
            'nato forces deployed', 'nato readiness', 'nato response force',
            'nato rapid reaction', 'allied command',
            'nato arctic', 'nato arctic exercise', 'thule air base',
            'pituffik space base', 'greenland military', 'greenland defense',
            'denmark military greenland', 'danish armed forces greenland',
            'arctic military exercise', 'cold response exercise',
            'nato northern flank', 'arctic patrol',
            'us greenland military', 'us arctic strategy',
            'icebreaker arctic', 'arctic surveillance',
            'nato baltic', 'nato baltic exercise', 'baltic air policing',
            'nato enhanced forward presence', 'nato eastern flank',
            'nato poland deployment', 'nato romania deployment',
            'nato mediterranean', 'standing nato maritime group',
            'snmg', 'nato sea guardian', 'nato med patrol',
            'nato defense spending', 'nato summit',
            'nato article 5', 'nato interoperability',
            'ramstein air base', 'shape nato', 'saceur',
            'nato ukraine', 'nato aid ukraine', 'ramstein format'
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=site:nato.int+news&hl=en&gl=US&ceid=US:en',
        ]
    },

    # ------------------------------------------------
    # DENMARK / ARCTIC COMMAND (v3.1.0)
    # Tier 4 — sovereignty signaling actor
    # Small kinetic footprint but analytically critical:
    # Danish Arktisk Kommando deployments and P-8 patrols
    # from Pituffik are direct proxies for Copenhagen's
    # seriousness in responding to U.S. pressure on Greenland.
    # ------------------------------------------------
    'denmark': {
        'name': 'Denmark',
        'flag': '🇩🇰',
        'tier': 4,
        'theatre': 'europe',
        'weight': 0.4,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Arctic Command / Greenland defense
            'arktisk kommando', 'arctic command denmark',
            'danish arctic command', 'danish armed forces greenland',
            'denmark military greenland', 'danish defence greenland',
            'danish frigate greenland', 'danish navy arctic',
            'denmark greenland sovereignty', 'denmark greenland defense',
            'danish patrol vessel greenland', 'denmark coast guard greenland',
            'sirius patrol', 'sirius dog sled patrol',
            # Pituffik / Thule
            'pituffik space base danish', 'thule air base danish',
            'denmark pituffik', 'denmark thule',
            'danish personnel pituffik', 'danish sovereignty pituffik',
            # P-8 / ISR patrols
            'denmark p-8 poseidon', 'danish maritime patrol',
            'danish air force arctic', 'danish isr greenland',
            # Sovereignty response language
            'denmark greenland us', 'denmark rejects us',
            'denmark sovereignty greenland', 'danish foreign minister greenland',
            'denmark nato greenland', 'lars lokke greenland',
            'denmark trump greenland', 'denmark greenland response',
            'frederik x greenland', 'denmark arctic strategy',
            'danish defence bill', 'denmark defence spending',
            'denmark military buildup arctic',
            # Danish keywords (GDELT Danish-language)
            'forsvaret grønland', 'arktisk kommando',
            'dansk suverænitet grønland', 'dansk forsvar arktis',
            'grønland forsvar styrkelse', 'dansk militær grønland',
            'grønland beredskab', 'forsvarsminister grønland',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=denmark+military+greenland+OR+arctic+command+OR+danish+defence+greenland&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=arktisk+kommando+OR+grønland+forsvar+OR+dansk+forsvar+arktis&hl=da&gl=DK&ceid=DK:da',
        ]
    },

    # ------------------------------------------------
    # WESTERN HEMISPHERE ACTORS (v3.0.0)
    # ------------------------------------------------

    'venezuela': {
        'name': 'Venezuela',
        'flag': '🇻🇪',
        'tier': 2,
        'theatre': 'western_hemisphere',
        'weight': 0.7,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Post-Maduro transition (v3.0.0 — regime change context)
            'venezuela maduro', 'nicolas maduro', 'maduro arrested', 'maduro captured',
            'maduro extradited', 'venezuela regime change', 'venezuela transition',
            'venezuela interim government', 'venezuela opposition government',
            'venezuela power vacuum', 'venezuela military faction',
            'chavismo collapse', 'psuv military', 'venezuela military split',
            'venezuela military defection', 'colectivos armed',
            # Armed forces / military posture
            'fanb venezuela', 'fuerzas armadas venezuela',
            'venezuela military exercise', 'venezuela army deploy',
            'venezuela navy caribbean', 'venezuela air force',
            'venezuela national guard', 'guardia nacional venezuela',
            # Narco-military nexus
            'cartel de los soles', 'tren de aragua', 'venezuela drug trafficking',
            'venezuela cocaine military', 'dea venezuela',
            'colombia venezuela border military', 'eln venezuela',
            'farc venezuela border', 'venezuela colombia smuggling',
            # US involvement
            'us military venezuela', 'us venezuela sanctions',
            'us venezuela naval operation', 'dea arrests venezuela',
            'us indictment venezuela military', 'us venezuela operation',
            'trump venezuela military', 'venezuela designated terrorist',
            # Cuba/Russia/China backing
            'cuba venezuela military', 'russian military venezuela',
            'russia venezuela arms', 'china venezuela military',
            'iranian military venezuela', 'hezbollah venezuela',
            # Crisis / instability signals
            'venezuela protests military', 'venezuela crackdown',
            'venezuela martial law', 'venezuela state of emergency',
            'venezuela hyperinflation military', 'venezuela fuel shortage military',
            'venezuela blackout military',
            # Spanish keywords
            'venezuela fuerzas armadas', 'ejército venezolano',
            'crisis venezuela militares', 'transición venezuela',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=venezuela+military+OR+maduro+OR+transition+OR+armed+forces&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=venezuela+crisis+OR+tren+de+aragua+OR+colectivos+OR+dea+venezuela&hl=en&gl=US&ceid=US:en',
        ]
    },

    'cuba': {
        'name': 'Cuba',
        'flag': '🇨🇺',
        'tier': 2,
        'theatre': 'western_hemisphere',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Regime stability
            'cuba military', 'cuban armed forces', 'far cuba',
            'fuerzas armadas revolucionarias', 'cuba national security',
            'cuba state security', 'cuba protests military',
            'cuba crackdown', 'cuba repression', 'cuba dissidents military',
            'cuba power outage instability', 'cuba economic collapse',
            'miguel diaz-canel', 'cuba raul castro',
            # Russian / Chinese military presence
            'russia cuba military', 'russian warship cuba', 'russian navy cuba',
            'russia signals intelligence cuba', 'russia cuba spy base',
            'russia cuba electronic surveillance', 'lourdes cuba russia',
            'china cuba military', 'china cuba spy base',
            'china signals intelligence cuba', 'chinese warship cuba',
            'iran cuba military', 'cuba venezuela military cooperation',
            # US-Cuba tensions
            'us cuba military', 'guantanamo bay military',
            'gtmo military', 'us cuba relations military',
            'cuba exile military', 'cuba embargo military',
            'us navy cuba', 'florida straits military',
            # Migration as instability signal
            'cuba mass exodus military', 'cuba coast guard',
            'cuba migration crisis', 'cuba boatlift',
            # Spanish keywords
            'cuba militares', 'fuerzas armadas cuba', 'crisis cuba',
            'apagón cuba', 'protestas cuba represión',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=cuba+military+OR+russia+cuba+OR+china+cuba+spy+OR+protests+crackdown&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=cuba+armed+forces+OR+guantanamo+military+OR+cuba+russia+base&hl=en&gl=US&ceid=US:en',
        ]
    },

    'haiti': {
        'name': 'Haiti',
        'flag': '🇭🇹',
        'tier': 2,
        'theatre': 'western_hemisphere',
        'weight': 0.6,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # MSS gang control — de facto military actor
            'mss haiti', 'viv ansanm haiti', 'gran grif haiti',
            'g9 haiti', 'g-9 gang haiti', 'barbeque haiti',
            'jimmy cherizier', 'haitian gang military',
            'haiti gang territory', 'haiti gang attack police',
            'haiti gang seize', 'haiti gang control',
            'haiti port-au-prince gang', 'cite soleil gang',
            'haiti gang weapons', 'haiti gang massacre',
            # International security mission
            'mss kenya haiti', 'kenyan police haiti',
            'multinational security support mission', 'mss mission haiti',
            'binuh haiti', 'un haiti security',
            'haiti security mission forces', 'kenya haiti mission',
            'haitian national police', 'pnh haiti',
            # State collapse / failed state signals
            'haiti prime minister security', 'haiti government collapse',
            'haiti presidential assassination', 'haiti state collapse',
            'haiti martial law', 'haiti emergency',
            'haiti coup', 'haiti political crisis military',
            # US / Caribbean military involvement
            'us military haiti', 'us coast guard haiti',
            'us embassy haiti security', 'us evacuation haiti',
            'us citizens haiti', 'ordered departure haiti',
            'caribbean community haiti military', 'caricom haiti',
            # Humanitarian-military overlap
            'haiti fuel shortage gangs', 'haiti airport gangs',
            'haiti hospital gangs', 'haiti hostage',
            # French/Creole keywords
            'haïti gangs armés', 'haïti sécurité militaire',
            'mission sécurité haïti', 'crise haïti',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=haiti+gang+OR+mss+mission+OR+kenya+haiti+OR+security+mission&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=haiti+military+OR+viv+ansanm+OR+g9+gang+OR+port-au-prince+security&hl=en&gl=US&ceid=US:en',
        ]
    },

    'panama': {
        'name': 'Panama',
        'flag': '🇵🇦',
        'tier': 3,
        'theatre': 'western_hemisphere',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Panama Canal — strategic chokepoint
            'panama canal military', 'canal zone security',
            'panama canal sovereignty', 'us panama canal',
            'trump panama canal', 'panama canal control',
            'panama canal chinese', 'hutchison whampoa panama',
            'china panama canal port', 'panama canal strategic',
            'canal operations disrupted', 'canal closure military',
            'canal transit warship', 'us warship panama canal',
            # Chinese port presence / influence
            'chinese port panama', 'china panama influence',
            'china panama military', 'pla navy panama',
            'china panama infrastructure', 'silk road panama',
            # US SOUTHCOM / regional posture
            'soto cano panama', 'us forces panama',
            'us military panama', 'panama security forces',
            'panama national police security', 'senan panama',
            # Darien Gap — migration-military nexus
            'darien gap military', 'darien gap colombia',
            'darien migration military', 'gulf of darien',
            'colombia panama border military',
            # Narco-trafficking
            'panama drug trafficking military', 'dea panama',
            'cartel panama', 'narco panama military',
            # Spanish keywords
            'canal de panama seguridad', 'fuerzas panama',
            'china canal panama', 'panama militares',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=panama+canal+military+OR+china+canal+OR+canal+sovereignty+OR+trump+panama&hl=en&gl=US&ceid=US:en',
        ]
    },

    'colombia': {
        'name': 'Colombia',
        'flag': '🇨🇴',
        'tier': 3,
        'theatre': 'western_hemisphere',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # ELN — primary active armed group
            'eln colombia', 'ejercito liberacion nacional colombia',
            'eln attack', 'eln bombing', 'eln pipeline',
            'eln ceasefire', 'eln negotiations military',
            'eln guerrilla colombia', 'eln front colombia',
            # FARC dissidents / FARC-EP
            'farc dissident colombia', 'farc-ep colombia',
            'farc disidencias', 'estado mayor central colombia',
            'ivan mordisco farc', 'farc attack colombia',
            'farc dissident attack military',
            # Colombian military operations
            'colombia military operation', 'colombia armed forces',
            'fuerzas militares colombia', 'ejercito colombia',
            'colombia air force strike', 'colombia military attack',
            'colombia special forces', 'colombia police military',
            # Narco-trafficking military nexus
            'colombia cocaine military', 'dea colombia',
            'clan del golfo colombia', 'autodefensas gaitanistas',
            'narco colombia military', 'colombia drug cartel military',
            # Venezuela-Colombia border
            'colombia venezuela border military', 'colombia venezuela tension',
            'petro maduro military', 'colombia venezuela migration military',
            # US involvement
            'us military colombia', 'us advisors colombia',
            'plan colombia military', 'colombia us drug war',
            # Spanish keywords
            'colombia militares eln', 'farc disidentes colombia',
            'operación militar colombia', 'colombia fuerzas armadas',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=colombia+eln+OR+farc+dissident+OR+military+operation+OR+cartel&hl=en&gl=US&ceid=US:en',
        ]
    },

    'mexico': {
        'name': 'Mexico',
        'flag': '🇲🇽',
        'tier': 3,
        'theatre': 'western_hemisphere',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Cartel military operations — primary signal
            'sinaloa cartel military', 'cjng military', 'jalisco cartel',
            'cartel military mexico', 'cartel ambush military',
            'cartel checkpoint mexico', 'cartel territorial control',
            'cartel drone attack', 'narco drone mexico',
            'narco roadblock military', 'narco convoy',
            'mexico cartel gunfight military', 'mexico massacre cartel',
            # Mexican military / state response
            'mexico military operation cartel', 'sedena mexico',
            'guardia nacional mexico cartel', 'marina mexico cartel',
            'mexico army cartel', 'mexico special forces cartel',
            'mexico military deployment', 'ejercito mexicano',
            'fuerzas armadas mexico', 'mexico army operation',
            # US-Mexico border military
            'us mexico border military', 'us troops mexico border',
            'us military mexico border', 'border patrol military',
            'national guard mexico border', 'us mexico border operation',
            'trump mexico military', 'designate cartel terrorist',
            'cartel terrorist designation', 'us strikes mexico',
            # Fentanyl / narco-trafficking
            'fentanyl mexico military', 'mexico fentanyl operation',
            'dea mexico cartel', 'us mexico drug military',
            # State capture signals
            'mexico police cartel corruption military',
            'mexico governor cartel', 'mexico state capture',
            # Spanish keywords
            'cartel mexico militar', 'operación militar cartel',
            'guardia nacional cartel', 'ejercito mexico cartel',
            'narcos drones mexico',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=mexico+cartel+military+OR+cjng+OR+sinaloa+cartel+military+OR+mexico+army&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=mexico+border+military+OR+us+mexico+military+OR+cartel+drone+attack&hl=en&gl=US&ceid=US:en',
        ]
    },

    'brazil': {
        'name': 'Brazil',
        'flag': '🇧🇷',
        'tier': 3,
        'theatre': 'western_hemisphere',
        'weight': 0.4,
        'feeds_into': ['regional_tension'],
        'keywords': [
            # Brazilian military posture
            'brazil military', 'exercito brasileiro', 'marinha do brasil',
            'forca aerea brasileira', 'brazil armed forces',
            'brazil military exercise', 'brazil navy exercise',
            'brazil air force exercise', 'brazil military deployment',
            # Amazon military operations
            'amazon military brazil', 'operacao verde brasil',
            'brazil army amazon', 'amazon deforestation military',
            'brazil amazon border military', 'brazil indigenous military',
            # Regional power / political instability
            'lula military brazil', 'brazil coup attempt military',
            'brazil bolsonaro military', 'brazil military politics',
            'brazil january 8 military', 'brazil democracy military',
            # Venezuela / regional
            'brazil venezuela military', 'brazil colombia military',
            'brazil suriname military', 'brazil guyana military',
            'brazil border military', 'brazil southcom',
            # Organized crime / narco
            'primeiro comando capital brazil', 'pcc brazil military',
            'faction war brazil military', 'brazil organized crime military',
            'rio de janeiro military', 'favela military brazil',
            'brazil drug trafficking military',
            # Chinese / strategic interest
            'china brazil military', 'brics military brazil',
            # Portuguese keywords
            'brasil militares', 'exercito brasil operacao',
            'marinha brasil', 'brasil fronteira militar',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=brazil+military+OR+amazon+military+OR+brazil+armed+forces+operation&hl=en&gl=US&ceid=US:en',
        ]
    },

    # ══════════════════════════════════════════════════════════════════
    # AFRICA THEATER ACTORS (May 22 2026 — new theater build)
    # AFRICOM AOR — Sahel junta belt, Horn of Africa, Lake Chad Basin,
    # Great Lakes, Sudan civil war. Libya cross-listed in middle_east.
    # AFRICOM US-side activity rolled into the existing 'us' actor.
    # ══════════════════════════════════════════════════════════════════

    'nigeria': {
        'name': 'Nigeria',
        'flag': '🇳🇬',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.7,
        'feeds_into': ['regional_stability'],
        'keywords': [
            'nigerian army', 'nigerian armed forces', 'nigerian air force',
            'nigerian military', 'nigerian troops', 'nigerian defense',
            'nigeria boko haram', 'nigeria iswap', 'lake chad basin',
            'nigeria military operation', 'operation hadin kai',
            'nigeria bandits military', 'nigeria military offensive',
            'nigeria security forces', 'borno state military',
            'nigeria multinational joint task force', 'mnjtf',
            # US military in Nigeria (recent activity)
            'us forces nigeria', 'us military nigeria', 'us troops nigeria',
            'us special forces nigeria', 'green berets nigeria',
            'africom nigeria', 'us africa command nigeria',
            'us nigeria security cooperation', 'us trained nigerian',
            'nigeria christian persecution', 'nigeria genocide',
            # Niger Delta militancy
            'niger delta avengers', 'niger delta militants', 'nigerian oil region military',
            # Lakurawa (new group, 2024-2025 emergence in NW)
            'lakurawa', 'lakurawa nigeria', 'lakurawa kebbi',
            'lakurawa sokoto', 'lakurawa borno',
            'lakurawa group operations',
            # ISWAP / Boko Haram specifics
            'iswap nigeria', 'iswap lake chad', 'iswap commander',
            'sambisa forest', 'boko haram sambisa',
            'baga nigeria attack', 'monguno', 'damasak nigeria',
            'rann nigeria military',
            'shekau successor', 'abu musab al-barnawi',
            # Bandit groups (NW Nigeria)
            'zamfara bandits', 'sokoto bandits', 'kaduna bandits',
            'katsina bandits', 'kebbi bandits',
            'turji nigeria', 'ado aleru', 'bello turji',
            'kachalla nigeria', 'bandit kingpin',
            # Plateau State / Middle Belt attacks
            'plateau attack', 'plateau state military', 'plateau massacre',
            'mangu plateau', 'jos military', 'bokkos attack',
            'middle belt nigeria', 'kaduna attack',
            'southern kaduna attacks',
            # Other groups
            'ipob nigeria', 'eastern security network', 'esn nigeria',
            'unknown gunmen biafra',
            'amotekun southwest',
            # Border ops with Niger
            'nigeria niger border closed military',
            'nigeria niger ecowas standoff',
            # ECOWAS standby force
            'ecowas standby force', 'ecowas military intervention',
            'tinubu military', 'ecowas chairmanship military',
            # JTF North-East / North-West
            'jtf north east', 'jtf north west', 'operation fasan yamma',
            'operation whirl punch', 'operation hadarin daji',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=nigeria+military+OR+nigerian+army+OR+nigeria+boko+haram&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=lakurawa+OR+iswap+OR+plateau+attack+nigeria&hl=en&gl=US&ceid=US:en',
        ]
    },

    'somalia': {
        'name': 'Somalia',
        'flag': '🇸🇴',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.8,
        'feeds_into': ['us_operations'],
        'keywords': [
            'somali national army', 'snа somalia', 'somalia military',
            'al-shabaab', 'al shabaab', 'shabaab somalia',
            'somalia us strike', 'us strike somalia', 'us drone strike somalia',
            'somalia mq-9', 'reaper somalia', 'us forces somalia',
            'us special operations somalia', 'jsoc somalia',
            'africom somalia strike', 'us africa command somalia',
            'atmis somalia', 'amisom', 'amisom somalia',
            'mogadishu attack', 'mogadishu military',
            'somalia federal forces', 'danab somalia',
            'puntland military', 'somaliland military',
            'al-shabaab attack', 'shabab car bomb',
            # AUSSOM replaces ATMIS (Jan 2025 transition)
            'aussom', 'aussom somalia', 'au transition mission somalia',
            'african union somalia mission',
            # ISIS-Somalia / Puntland operations
            'isis somalia', 'islamic state somalia', 'is somalia',
            'puntland isis offensive', 'almiskaad mountains',
            'cal-miskaad', 'cal miskaad', 'bari region operations',
            # Specific al-Shabaab cells / commanders
            'al-shabaab amniyat', 'amniyat somalia',
            'mahad karate', 'fuad shongole',
            'shabaab finance network', 'shabaab tax collection',
            # Major recent attack zones
            'mogadishu hotel attack', 'beach hotel mogadishu',
            'somalia ied', 'shabaab ied', 'mogadishu vbied',
            'baidoa attack', 'lower shabelle military',
            'middle shabelle ops', 'galmudug military',
            'hirshabelle military', 'jubaland military',
            # Turkish + Egyptian + UAE ties (regional power competition)
            'turkey somalia military', 'turkish drones somalia',
            'turkey somalia base', 'tika somalia',
            'egypt somalia military', 'egypt deploy somalia',
            'uae somalia military', 'gulf states somalia',
            # Maritime / piracy resurgence
            'somalia piracy', 'somalia maritime attack',
            'somali pirates 2024', 'somali pirates 2025', 'somali pirates 2026',
            'gulf of aden somalia', 'eunavfor atalanta',
            # Ethiopia-Somaliland MoU spillover
            'ethiopia somaliland mou military',
            'somalia ethiopia tension', 'somalia turkey mediation',
            # Hassan Sheikh Mohamud government posture
            'hassan sheikh mohamud military', 'somalia president military',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=somalia+military+OR+al+shabaab+OR+us+strike+somalia&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=aussom+OR+puntland+isis+OR+somalia+drone+strike&hl=en&gl=US&ceid=US:en',
        ]
    },

    'mali': {
        'name': 'Mali',
        'flag': '🇲🇱',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.7,
        'feeds_into': ['russia_proxy_pressure', 'sahel_instability'],
        'keywords': [
            'mali military junta', 'mali junta', 'malian armed forces',
            'mali wagner', 'wagner mali', 'africa corps mali',
            'mali russian mercenaries', 'mali russia military',
            'fama mali', 'forces armées maliennes',
            'mali ecowas military', 'mali sahel military',
            'goita mali', 'assimi goita',
            'mali french withdrawal', 'barkhane mali',
            'mali coup', 'mali insurgency', 'jihadist mali',
            'mali jnim', 'group support islam muslims',
            'gao mali', 'kidal mali', 'menaka mali',
            'mali iswap', 'mali isgs',
            'aes alliance sahel', 'alliance sahel states military',
            # Tinzaouaten — July 2024 Wagner+FAMa catastrophe
            'tinzaouaten', 'tinzaouaten ambush', 'tinzaouaten battle',
            'wagner tinzaouaten losses', 'cma tinzaouaten',
            'azawad tinzaouaten', 'fla tinzaouaten',
            # JNIM Bamako Sept 2024 attack
            'jnim bamako attack', 'bamako airport attack',
            'modibo keita airport', 'bamako presidential helicopter',
            'sept 2024 mali attack', 'september 17 bamako',
            # CMA / Azawad movement
            'cma azawad', 'coordination azawad movements',
            'fla azawad', 'permanent strategic framework',
            'tuareg insurgency mali', 'tuareg rebels',
            # JNIM leadership / structure
            'iyad ag ghaly', 'jnim emir', 'iyad ghaly',
            'amadou kouffa', 'kouffa katiba',
            'macina katiba', 'macina liberation front',
            # Specific Wagner / Africa Corps figures in Mali
            'wagner mali commander', 'wagner mali deaths',
            'andrey averyanov mali', 'african legion mali',
            'russia training mali', 'russia mali instructors',
            # ECOWAS exit + AES military pact
            'mali ecowas exit', 'aes military pact',
            'aes confederation military', 'sahel states military',
            'mali burkina niger military pact',
            # Specific cities / regions under JNIM pressure
            'mopti mali', 'segou mali military', 'sikasso mali',
            'koulikoro military', 'kayes military', 'timbuktu military',
            'farabougou', 'boni mali', 'bandiagara military',
            # ── Traditional / ethnic self-defense militias (warlord layer) ──
            'dozo hunters mali', 'dozo militia', 'donso hunters', 'dan na ambassagou',
            'dana ambassagou', 'dogon militia mali', 'fulani militia mali',
            'ogossagou massacre', 'ethnic militia mali', 'self-defense militia mali',
            'imghad tuareg militia', 'gatia mali', 'plateforme mali',
            'wagner auxiliary mali', 'wagner local proxies mali',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=mali+military+OR+wagner+mali+OR+mali+sahel&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=tinzaouaten+OR+jnim+bamako+OR+mali+jihadist&hl=en&gl=US&ceid=US:en',
        ]
    },

    'niger': {
        'name': 'Niger',
        'flag': '🇳🇪',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.7,
        'feeds_into': ['sahel_instability', 'us_operations'],
        'keywords': [
            'niger military junta', 'niger junta', 'niger coup',
            'niger armed forces', 'forces armées nigériennes',
            'cnsp niger', 'tchiani niger', 'general tchiani',
            'niger ecowas military', 'niger sahel military',
            'agadez niger', 'niamey military',
            # Niger Air Base 201 — major US drone hub (now expelled)
            'air base 201', 'niger air base 201', 'niger drone base',
            'niger 101 air base', 'niger drone base agadez',
            'us forces niger withdrawal', 'us military niger',
            'us withdraw niger', 'pentagon niger',
            'niger russia military', 'niger russian military',
            'niger wagner', 'wagner niger', 'africa corps niger',
            'niger uranium military', 'orano niger',
            'aes alliance niger',
            # Russian airbase deployment specifics
            'russian airbase niamey', 'russia airbase niger',
            'niger russia military deployment',
            'russia takes over base 201', 'russia base 201',
            'russia troops niger arrival',
            # JNIM Tillaberi + ISGS specific zones
            'tillaberi niger', 'tillaberi military',
            'tahoua niger military', 'maradi military',
            'diffa niger military', 'dosso military',
            'tongo tongo niger', 'inates niger', 'chinegodar',
            'niger boko haram', 'niger lake chad',
            'niger isgs', 'isgs niger', 'islamic state sahel niger',
            'three borders niger', 'three border area sahel',
            # AES + Mali/Burkina coordination
            'aes confederation niger', 'aes military summit',
            'niger mali burkina pact', 'aes joint force niger',
            # Coup leaders / military council
            'salifou mody', 'general mody niger',
            'cnsp leadership', 'niger council state',
            'niger junta consolidation',
            # CFA franc exit / French withdrawal aftermath
            'niger cfa franc exit', 'niger french withdrawal complete',
            'niger eu sanctions', 'niger usaid suspension military',
            # ── Community / ethnic self-defense + auxiliaries (warlord layer) ──
            'niger self-defense militia', 'niger community militia',
            'tuareg militia niger', 'fulani militia niger', 'ethnic militia niger',
            'niger vigilante group', 'wagner auxiliary niger',
            'niger local proxy forces', 'zarma militia', 'djerma self-defense',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=niger+military+OR+niger+coup+OR+niger+sahel&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=niger+russia+OR+aes+niger+OR+tillaberi&hl=en&gl=US&ceid=US:en',
        ]
    },

    'burkina_faso': {
        'name': 'Burkina Faso',
        'flag': '🇧🇫',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.6,
        'feeds_into': ['sahel_instability'],
        'keywords': [
            'burkina faso military', 'burkinabé military', 'burkinabe armed forces',
            'burkina faso junta', 'burkina junta',
            'ibrahim traore', 'traore burkina', 'captain traore',
            'burkina faso wagner', 'wagner burkina faso',
            'burkina faso russia military', 'africa corps burkina',
            'burkina faso jihadist', 'burkina jnim',
            'burkina ecowas military', 'burkina sahel',
            'ouagadougou military', 'aes burkina',
            'vdp burkina faso', 'volontaires defense patrie',
            # JNIM specific attack zones
            'djibo burkina', 'djibo siege', 'djibo military',
            'inata burkina', 'inata attack',
            'arbinda burkina', 'mansila burkina',
            'barsalogho', 'barsalogho massacre',
            'kongoussi', 'kaya burkina military',
            'fada n gourma', 'fada ngourma military',
            'gourma burkina', 'sahel region burkina',
            'soum province military', 'oudalan military',
            'seno province', 'yagha province',
            # Major massacres / events 2024-2026
            'solhan massacre', 'yirgou massacre', 'nouna massacre',
            'karma massacre', 'mansila massacre',
            # Russia partnership specifics
            'burkina faso africa corps deployment',
            'burkina russia military instructors',
            'burkina drone purchase', 'turkish drones burkina',
            'bayraktar burkina', 'tb2 burkina',
            # Traore government / coup defense
            'traore coup attempt', 'burkina coup plot',
            'burkina faso assassination plot', 'sankarist movement',
            # AES + regional integration
            'aes burkina deployment', 'aes joint force',
            'burkina mali joint operations',
            # ── Traditional / community self-defense (warlord layer) ──
            'koglweogo', 'koglweogo militia', 'burkina self-defense group',
            'dozo burkina', 'burkina ethnic militia', 'rugga fulani burkina',
            'vdp massacre', 'vdp recruitment burkina', 'vdp auxiliary',
            'karma massacre vdp', 'zaongo massacre', 'nadiagou',
            'wagner auxiliary burkina', 'burkina local proxy forces',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=burkina+faso+military+OR+burkina+junta&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=djibo+OR+jnim+burkina+OR+vdp+burkina&hl=en&gl=US&ceid=US:en',
        ]
    },

    'drc': {
        'name': 'DR Congo',
        'flag': '🇨🇩',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.7,
        'feeds_into': ['regional_stability'],
        'keywords': [
            'drc military', 'congo military', 'fardc',
            'forces armées rdc', 'congolese armed forces',
            'drc m23', 'm23 rebels', 'm23 congo',
            'drc rwanda military', 'rwanda backed m23',
            'drc rwanda border military',
            'eastern drc military', 'north kivu military', 'south kivu military',
            'goma military', 'bukavu military', 'beni military',
            'kinshasa military',
            'drc adf', 'allied democratic forces', 'adf drc',
            'monusco', 'un monusco drc', 'un peacekeepers drc',
            'east african community force drc', 'eacrf',
            'sadc mission drc', 'samidrc',
            'drc wagner', 'wagner drc', 'romanian mercenaries drc',
            'drc cobalt military',
            # Goma fall Jan 2025 (major)
            'goma fall m23', 'goma captured', 'm23 enters goma',
            'goma takeover', 'rdf goma', 'goma rwanda forces',
            'bukavu fall', 'm23 bukavu', 'south kivu offensive',
            # AFC (Alliance Fleuve Congo) — Corneille Nangaa political wing
            'afc alliance fleuve congo', 'corneille nangaa',
            'nangaa m23 alliance', 'afc m23 political',
            'afc/m23', 'congo river alliance',
            # Romanian mercenaries (RALF)
            'romanian mercenaries drc', 'horatiu potra',
            'ralf romania', 'asociatia ralf',
            'romanian special forces drc', 'romanian contractors goma',
            'romanian fighters surrender goma',
            # SADC withdrawal (Dec 2024 announcement)
            'samidrc withdrawal', 'sadc mission drc end',
            'south africa drc casualties', 'mozambique drc casualties',
            'tanzania drc mission', 'malawi drc mission end',
            # Specific FARDC operations / defeats
            'fardc desertions', 'fardc surrender', 'fardc defection',
            'sukola operations', 'sukola i', 'sukola ii',
            'rumangabo military camp', 'kibumba',
            'sake drc military', 'masisi territory',
            'rutshuru territory military', 'nyiragongo military',
            # Wazalendo militias (FARDC-allied)
            'wazalendo', 'wazalendo drc', 'patriotic resistance forces',
            'apcls', 'maï-maï drc', 'mai mai drc',
            # ── Ituri warlords + Ebola-zone overlap (convergence-critical) ──
            'codeco', 'codeco militia', 'codeco ituri', 'lendu militia',
            'zaire militia ituri', 'hema lendu conflict', 'ituri massacre',
            'adf drc', 'allied democratic forces', 'adf ituri', 'adf beni',
            'beni massacre', 'north kivu adf', 'islamic state central africa drc',
            # Ebola / health-emergency military overlap (Ituri/N.Kivu are Ebola zones)
            'drc ebola military', 'ebola quarantine drc military',
            'ituri ebola response military', 'ebola zone conflict drc',
            'health workers attacked drc', 'ebola response suspended conflict',
            # Mineral war / cobalt / coltan dimension
            'rubaya coltan', 'rubaya mines', 'm23 coltan',
            'm23 minerals tax', 'rwanda smuggling minerals',
            'cobalt drc military', 'coltan drc rebels',
            'drc supply chain conflict minerals',
            # M23 / RDF leadership
            'sultani makenga', 'm23 sultani',
            'rdf rwanda defence force', 'james kabarebe drc',
            'kagame drc military', 'rwanda denies drc',
            # Tshisekedi government posture
            'tshisekedi military', 'felix tshisekedi war',
            'drc emergency military', 'drc state of siege',
            # ADF + ISIS-CAP (Central Africa Province)
            'iscap drc', 'isis central africa province',
            'adf ituri', 'adf nord kivu attack', 'adf mwalika',
            'adf erengeti', 'adf oicha',
            # Ebola Bundibugyo PHEIC (May 15 2026) military context
            'drc ebola military', 'ebola quarantine drc military',
            'ituri ebola response military',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=drc+military+OR+m23+congo+OR+goma+military&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=afc+m23+OR+wazalendo+OR+drc+rwanda+war&hl=en&gl=US&ceid=US:en',
        ]
    },

    'sudan': {
        'name': 'Sudan',
        'flag': '🇸🇩',
        'tier': 1,
        'theatre': 'africa',
        'weight': 0.9,
        'feeds_into': ['humanitarian_cascade', 'russia_proxy_pressure'],
        'keywords': [
            'sudanese armed forces', 'saf sudan',
            'rapid support forces', 'rsf sudan',
            'sudan civil war', 'sudan war', 'sudan conflict',
            'burhan sudan', 'general burhan', 'al-burhan',
            'hemedti', 'hemeti', 'dagalo sudan', 'mohamed hamdan dagalo',
            'darfur military', 'darfur attack', 'el fasher',
            'el fashir', 'el-fasher', 'genocide darfur',
            'khartoum military', 'khartoum fighting', 'omdurman fighting',
            'port sudan military', 'port sudan attack',
            'sudan uae weapons', 'uae rsf', 'uae sudan weapons',
            'sudan iran weapons', 'iran sudan drones',
            'sudan russia military', 'wagner sudan',
            'sudan red sea military',
            'sudan mass killing', 'sudan ethnic cleansing',
            'sudan famine', 'sudan humanitarian crisis',
            # 2024-2026 specific RSF/SAF cities + offensives
            'sennar offensive', 'sennar rsf', 'sennar saf',
            'wad madani', 'wad madani rsf', 'gezira state military',
            'sinja sudan', 'singa offensive',
            'gedaref military', 'kassala military',
            'al-jazira state', 'al jazira sudan',
            'nuba mountains sudan', 'south kordofan military',
            'blue nile state military', 'damazin sudan',
            'al-fashir siege', 'el fasher siege', 'zamzam camp attack',
            'kadugli sudan', 'merowe dam military',
            'jebel moya', 'singa rsf',
            'tine sudan', 'kabkabiya', 'malha darfur',
            # RSF leadership / structure
            'abdul rahim dagalo', 'rsf advance', 'rsf paramilitary',
            'janjaweed', 'janjaweed sudan', 'rsf masalit',
            'masalit genocide', 'el geneina', 'el-geneina',
            'al-malit sudan', 'al malit',
            # SAF leadership / structure
            'malik agar', 'taqaddum sudan',
            'sudan armed forces general command',
            'shams al-din kabbashi', 'yasir al-atta',
            # Iran-Sudan-Houthi triangle (May 2026)
            'sudan houthi weapons', 'houthi sudan ties',
            'iran sudan iras', 'iran shahed sudan',
            'sudan iranian drones', 'mohajer-6 sudan',
            'irgc sudan', 'sudan iran proxy',
            # Russia naval base Port Sudan talks
            'russia port sudan base', 'russia naval base sudan',
            'russia red sea base', 'russia sudan logistics base',
            'putin sudan base', 'lavrov sudan',
            # UAE / Emirati support to RSF
            'uae chad sudan corridor', 'amdjarass chad',
            'uae rsf airlift', 'uae sudan weapons flights',
            'emirati drones rsf', 'uae shipped weapons sudan',
            # Egypt support to SAF
            'egypt saf', 'egypt sudan military aid',
            'egyptian air support sudan', 'egypt jet sudan',
            'egypt training sudan armed forces',
            # Ukraine drone operators rumored
            'ukraine drones sudan', 'gur sudan',
            'ukrainian special forces sudan',
            # Atrocities + war crimes
            'sudan war crimes', 'sudan icc',
            'darfur ethnic cleansing 2024', 'darfur masalit massacre',
            'sudan starvation weapon', 'ipc phase 5 sudan',
            'famine declared sudan', 'zamzam famine',
            # ── Jul 2026 refresh: Kordofan front is now the critical frontline ──
            'el obeid', 'el-obeid', 'el obeid siege', 'kordofan offensive',
            'north kordofan military', 'bara kordofan',
            # Chad-border offensive (Zaghawa villages, cross-border strikes)
            'um baru', 'tine karnoi', 'zaghawa villages',
            'rsf chad incursion', 'rsf cross-border chad',
            # Libya / Haftar tri-border (Jun 2025+)
            'haftar sudan', 'libya sudan border', 'tri-border sudan',
            'sudan libya egypt border', 'sahara supply lines sudan',
            # RSF parallel government + defection wave
            'rsf parallel government', 'tasis sudan', 'tasis alliance',
            'nyala government rsf', 'rsf defections', 'sudan shield forces',
            'abu aqla kaikal',
            # Drone-war escalation
            'port sudan drone', 'port sudan drone strike', 'rsf drone strike',
            'nyala airport strike', 'sudan drone attack',
            # Peace track (Boulos plan) — de-escalation watch
            'boulos sudan', 'sudan peace plan', 'sudan truce',
            'sudan ceasefire talks', 'quad sudan mediation',
            # Russia state-level plug (base + arms + mining)
            'sudan russia arms deal', 'russia sudan air defense',
            'russia sudan mining', 'port sudan agreement',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=sudan+military+OR+sudan+civil+war+OR+rsf+sudan&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=el+fasher+OR+wad+madani+OR+darfur+rsf&hl=en&gl=US&ceid=US:en',
        ]
    },

    # ── South Sudan (Jul 2026): lean coup/collapse-watch actor. Not a
    # two-army war like Sudan — an elite-fracture petro-state on the brink
    # (Machar detained, pipeline revenue collapsed, elections Dec 2026).
    # Also carries the Sudan-war coupling: SPLM-N/RSF operate from South
    # Sudanese territory into Blue Nile. Full rhetoric-tracker treatment
    # deferred to its own build (Cuba elite-fracture primitives). ──
    'south_sudan': {
        'name': 'South Sudan',
        'flag': '\U0001f1f8\U0001f1f8',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.6,
        'feeds_into': ['humanitarian_cascade', 'regional_tension'],
        'keywords': [
            # State forces + factions
            'sspdf', 'south sudan army', 'south sudan military',
            'splm-io', 'splm in opposition', 'white army south sudan',
            'white army nuer', 'south sudan clashes',
            # Kiir / Machar elite fracture
            'salva kiir', 'riek machar', 'machar house arrest',
            'machar treason trial', 'kiir machar', 'south sudan coup',
            # Flashpoints
            'nasir upper nile', 'nasir south sudan', 'ulang county',
            'upper nile clashes', 'malakal', 'jonglei violence',
            'murle pibor', 'juba military', 'juba south sudan',
            # External forces
            'unmiss', 'ugandan troops south sudan', 'updf juba',
            'uganda special forces juba',
            # Sudan-war coupling (the corridor)
            'splm-n south sudan', 'blue nile south sudan',
            'rsf south sudan border', 'sudan south sudan border clash',
            'abyei clashes', 'heglig',
            # Petro-state strain
            'south sudan oil pipeline', 'petrodar pipeline',
            'south sudan pipeline attack', 'south sudan oil force majeure',
            # Transition watch
            'south sudan elections', 'south sudan transition',
            'south sudan civil war',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=south+sudan+military+OR+kiir+machar+OR+white+army&hl=en&gl=US&ceid=US:en',
        ]
    },

    'algeria': {
        'name': 'Algeria',
        'flag': '🇩🇿',
        'tier': 2,
        'theatre': 'middle_east',
        'weight': 0.55,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'algerian military', 'algeria army', 'armee algerienne',
            'algerian peoples national army', 'anp algeria',
            'said chengriha', 'algeria chief of staff',
            'algeria defense', 'algeria military exercise',
            # Morocco rupture / border
            'algeria morocco border', 'algeria morocco tension',
            'algeria morocco war', 'algeria morocco military',
            'algeria closes airspace morocco', 'algeria morocco gas pipeline',
            # Western Sahara / Polisario
            'algeria polisario', 'algeria western sahara',
            'tindouf camps', 'polisario algeria support', 'sahrawi algeria',
            # Russia arms client / Wagner-adjacent
            'algeria russia arms', 'algeria russia weapons',
            'algeria su-57', 'algeria su-34', 'algeria russia military deal',
            'algeria wagner', 'algeria africa corps',
            # Sahel border / Mali
            'algeria mali border', 'algeria sahel', 'algeria niger border',
            'algeria mali tension', 'algeria counterterrorism sahel',
            'algeria azawad', 'algeria jnim',
            # Hydrocarbon / energy security
            'algeria gas military', 'sonatrach security', 'in amenas',
            'algeria hydrocarbon security', 'algeria europe gas',
            'algeria pipeline security',
            # Domestic / leadership
            'tebboune military', 'algeria air defense', 'algeria drone',
            'algeria mobilization', 'algeria france military tension',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=algeria+military+OR+algeria+morocco+OR+algeria+sahel&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=algeria+russia+arms+OR+algeria+western+sahara+OR+algeria+border&hl=en&gl=US&ceid=US:en',
        ]
    },

    'morocco': {
        'name': 'Morocco',
        'flag': '🇲🇦',
        'tier': 2,
        'theatre': 'middle_east',
        'weight': 0.5,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'moroccan military', 'morocco army', 'far morocco',
            'royal armed forces morocco', 'forces armees royales',
            'morocco defense', 'morocco military exercise',
            # Western Sahara / Polisario (core flashpoint)
            'western sahara', 'polisario', 'polisario front', 'sahrawi',
            'sadr western sahara', 'guerguerat', 'minurso',
            'western sahara ceasefire', 'morocco polisario clashes',
            'western sahara wall', 'berm western sahara',
            # Algeria rupture
            'morocco algeria border', 'morocco algeria tension',
            'morocco algeria military',
            # Israel / Abraham Accords defense ties
            'morocco israel military', 'morocco israel defense',
            'morocco israel drones', 'abraham accords morocco military',
            'morocco israel cooperation',
            # Drones / procurement
            'morocco bayraktar', 'morocco drones turkey', 'morocco harop',
            'morocco wing loong', 'morocco f-16', 'morocco abrams',
            # US / exercises
            'morocco us military', 'african lion exercise', 'morocco africom',
            # Spain / migration / Sahel
            'morocco spain ceuta', 'morocco melilla', 'morocco mauritania',
            'morocco sahel', 'morocco migration military',
            'mohammed vi military',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=morocco+military+OR+western+sahara+OR+polisario&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=morocco+algeria+OR+morocco+israel+defense+OR+african+lion&hl=en&gl=US&ceid=US:en',
        ]
    },

    'tunisia': {
        'name': 'Tunisia',
        'flag': '🇹🇳',
        'tier': 3,
        'theatre': 'middle_east',
        'weight': 0.4,
        'feeds_into': ['regional_tension'],
        'keywords': [
            'tunisian military', 'tunisia army', 'armee tunisienne',
            'tunisia armed forces', 'tunisia defense', 'tunisia national guard',
            # Libya border / spillover
            'tunisia libya border', 'ras jedir', 'tunisia libya security',
            'tunisia libya smuggling', 'dehiba crossing',
            # Jihadist / internal security
            'tunisia jihadist', 'tunisia ansar al-sharia', 'mount chaambi',
            'kasserine tunisia', 'tunisia counterterrorism', 'tunisia isis',
            # Migration / Mediterranean
            'tunisia migration', 'tunisia coast guard', 'sfax migration',
            'tunisia lampedusa', 'tunisia eu migration deal',
            'tunisia migrant boats',
            # Leadership / political
            'kais saied military', 'tunisia democratic backsliding',
            'tunisia coup', 'tunisia political crisis',
            # External / cooperation
            'tunisia us military', 'tunisia african lion',
            'tunisia algeria military', 'tunisia imf security',
            'tunisia russia', 'tunisia air defense',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=tunisia+military+OR+tunisia+libya+border+OR+tunisia+migration&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=tunisia+security+OR+kais+saied+OR+tunisia+jihadist&hl=en&gl=US&ceid=US:en',
        ]
    },

    'libya': {
        'name': 'Libya',
        'flag': '🇱🇾',
        'tier': 2,
        'theatre': 'africa',  # Primary theater = Africa (AFRICOM AOR)
        'cross_theatre': ['middle_east'],  # Also visible in ME framing
        'weight': 0.7,
        'feeds_into': ['russia_proxy_pressure'],
        'keywords': [
            'libyan military', 'libyan armed forces', 'lna libya',
            'libyan national army', 'haftar', 'khalifa haftar',
            'lna haftar', 'tobruk parliament',
            'gna libya', 'government national accord libya',
            'gnu libya', 'government national unity libya',
            'tripoli military', 'benghazi military', 'sirte military',
            'misrata military', 'libya wagner', 'wagner libya',
            'africa corps libya', 'russia libya military',
            'turkey libya military', 'libya turkey drones',
            'libya egypt military', 'libya uae military',
            'al-watiya air base', 'al watiya libya',
            'libya gaddafi', 'libya militias',
            'libya oil military', 'libya nlc military',
            # 2024 Tripoli clashes (Aug 2024)
            'tripoli clashes 2024', 'tripoli militia clashes',
            'gnu militia clashes', 'libyan capital fighting',
            'rada force tripoli', '444 brigade tripoli',
            'stability support apparatus libya', 'ssa libya',
            'dbeibeh tripoli', 'abdul hamid dbeibah',
            # Eastern Libya / Haftar family
            'saddam haftar', 'khaled haftar', 'belqasem haftar',
            'haftar family', 'haftar succession',
            'tobruk hor libya', 'house of representatives libya',
            'aguila saleh', 'libyan supreme court military',
            # Russia naval base / port access
            'russia libya port', 'russia tobruk port',
            'russia libya naval base', 'russia benghazi port',
            'russia libya logistics base',
            'russian ships libya', 'russian aircraft libya',
            'russia africa corps libya deployment',
            # Mediterranean migration / military dimension
            'libya migrant pushback', 'libyan coast guard',
            'frontex libya', 'libya migrant detention military',
            'libyan navy mediterranean',
            # Bashagha + competing PMs
            'fathi bashagha', 'bashagha libya military',
            'libya parallel government military',
            # Air strike events
            'haftar airstrike', 'libyan air strikes',
            'turkish drones libya 2024',
            # CIA Cooperation / U.S. interests
            'cia libya', 'us libya military cooperation',
            'us drone libya', 'us special operations libya',
            # Tribal / militia specifics
            'zintan brigade', 'misrata brigade',
            'awlad sulayman tribe', 'tuareg libya',
            'tebu libya', 'libya south military',
            # Mercenary withdrawal (or non-withdrawal)
            'wagner libya withdrawal', 'wagner libya remains',
            'syrian mercenaries libya',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=libya+military+OR+haftar+OR+libya+wagner&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=tripoli+clashes+OR+haftar+russia+OR+libya+migrant&hl=en&gl=US&ceid=US:en',
        ]
    },

    'ethiopia': {
        'name': 'Ethiopia',
        'flag': '🇪🇹',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.6,
        'feeds_into': ['regional_stability'],
        'keywords': [
            'ethiopian national defense forces', 'endf ethiopia',
            'ethiopian military', 'ethiopian air force',
            'ethiopia tigray military', 'tplf ethiopia',
            'ethiopia eritrea military', 'ethiopia somalia border',
            'amhara fano', 'fano militia ethiopia',
            'oromo liberation army ethiopia',
            'abiy ahmed military', 'addis ababa military',
            'ethiopia red sea', 'ethiopia somaliland port',
            'ethiopia drone strike',
            'ethiopia eritrea border', 'ethiopia sudan border',
            # Pretoria Agreement (Nov 2022) — status & implementation
            'pretoria agreement', 'pretoria agreement implementation',
            'cessation hostilities ethiopia', 'cohi ethiopia',
            'tigray disarmament', 'tplf disarmament',
            'tigray interim administration',
            # Amhara conflict (Fano vs ENDF, 2023-2026)
            'amhara conflict', 'amhara region war',
            'fano amhara military', 'fano militia attack',
            'gondar military', 'bahir dar military',
            'amhara federal forces', 'amhara crackdown',
            'amhara state of emergency',
            # Eritrea war risk
            'eritrea ethiopia war', 'eritrea ethiopia tension',
            'isaias afwerki ethiopia', 'eritrea military buildup',
            'eritrea border closure', 'eritrea war preparation',
            'tigray eritrea border',
            # Sea access ambitions / Red Sea / Somaliland MoU
            'ethiopia sea access', 'ethiopia red sea ambition',
            'ethiopia somaliland mou', 'berbera ethiopia',
            'ethiopia assab port', 'ethiopia eritrea assab',
            'ethiopia djibouti tension',
            # Oromia conflict (OLA / Shene)
            'ola ethiopia', 'oromo liberation army',
            'shene ola', 'ola shene', 'oromia conflict',
            'wollega military', 'east wollega military',
            'horro guduru', 'oromia crackdown',
            # GERD (Grand Ethiopian Renaissance Dam) military dimension
            'gerd military', 'gerd egypt military', 'gerd sudan',
            'nile dam military', 'blue nile military',
            # Abiy government posture / Ankober defense doctrine
            'abiy military doctrine', 'ethiopia naval force',
            'ethiopia state defence policy', 'ankober',
            # Drone strikes (TB2, etc.)
            'tb2 ethiopia', 'bayraktar ethiopia',
            'iranian drones ethiopia', 'mohajer ethiopia',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=ethiopia+military+OR+endf+OR+ethiopia+tigray&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=amhara+fano+OR+eritrea+ethiopia+OR+oromia+ola&hl=en&gl=US&ceid=US:en',
        ]
    },

    'kenya': {
        'name': 'Kenya',
        'flag': '🇰🇪',
        'tier': 3,
        'theatre': 'africa',
        'weight': 0.5,
        'feeds_into': ['us_operations'],
        'keywords': [
            'kenya defence forces', 'kdf kenya',
            'kenyan military', 'kenyan army',
            'kenya somalia military', 'kenya al-shabaab',
            'manda bay kenya', 'camp simba kenya',
            'manda bay attack', 'us forces kenya',
            'kenya us military', 'lamu kenya military',
            'kenya somalia border military',
            'kenya haiti deployment', 'kenya haiti mission',
            # KDF in DRC EACRF (East African Community Regional Force)
            'kdf drc', 'kenya drc deployment', 'kenya eacrf',
            'kenya goma deployment', 'kenya east africa force',
            'kdf eastern congo',
            # Haiti MSS (Multinational Security Support)
            'kenya mss haiti', 'kenya haiti police',
            'haiti mission kenya', 'mss mission haiti',
            'kenya haiti casualties', 'kenya haiti expansion',
            # KDF Somalia operations (cross-border)
            'kdf somalia raid', 'kenya cross border somalia',
            'kdf jubaland operations', 'kdf gedo region',
            'kenya kismayo military', 'kdf badhadhe',
            # Garissa / NE Kenya security
            'garissa attack', 'mandera attack', 'wajir attack',
            'lamu attack kenya', 'boni forest operations',
            'operation amani', 'operation linda boni',
            # US military ties (cooperation level)
            'kenya us defense agreement', 'kenya us cooperation',
            'us drone kenya', 'manda bay strike',
            # Internal political-military stress
            'gen-z protests military', 'ruto military deployment',
            'kenya gen z military response',
            # Ebola / health security military deployment
            'kenya ebola border military',
            'kenya screening drc border',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=kenya+military+OR+kdf+OR+manda+bay&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=kdf+drc+OR+kenya+haiti+OR+kdf+somalia&hl=en&gl=US&ceid=US:en',
        ]
    },

    'djibouti': {
        'name': 'Djibouti',
        'flag': '🇩🇯',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.7,
        'feeds_into': ['us_operations', 'great_power_competition'],
        'keywords': [
            'djibouti military', 'djiboutian armed forces',
            'camp lemonnier', 'camp lemonier',
            'us forces djibouti', 'us base djibouti',
            'us military djibouti', 'africom djibouti',
            'cjtf-hoa', 'combined joint task force horn africa',
            'djibouti china base', 'china djibouti base',
            'china military djibouti', 'plan djibouti',
            'french base djibouti', 'japanese base djibouti',
            'doraleh port djibouti',
            'bab el-mandeb djibouti',
            # China PLAN base expansion (2024-2026)
            'china djibouti base expansion', 'plan djibouti expansion',
            'china carrier djibouti', 'china naval base africa',
            'doraleh china', 'china djibouti pier',
            # US Camp Lemonnier expansion / drone ops
            'camp lemonnier expansion', 'us drone djibouti operations',
            'reaper djibouti', 'mq-9 djibouti',
            'special operations djibouti horn africa',
            # Bab el-Mandeb / Houthi response
            'djibouti red sea security', 'djibouti yemen response',
            'djibouti suez', 'djibouti shipping corridor',
            'djibouti naval coalition', 'djibouti operation prosperity',
            'djibouti aspides eu', 'eu aspides djibouti',
            # French Forces in Djibouti (FFDJ) — withdrawal posture
            'ffdj djibouti', 'french forces djibouti',
            'france djibouti reduction', 'france djibouti withdrawal',
            # Italian + Japanese + Indian rotation
            'italian base djibouti', 'jmsdf djibouti',
            'india djibouti deployment', 'india naval djibouti',
            # Strategic competition framing
            'china us competition djibouti',
            'doraleh container terminal', 'djibouti port debt',
            'djibouti china debt',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=djibouti+military+OR+camp+lemonnier+OR+horn+of+africa+us&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=china+djibouti+base+OR+bab+el+mandeb+djibouti&hl=en&gl=US&ceid=US:en',
        ]
    },

    'central_african_republic': {
        'name': 'Central African Republic',
        'flag': '🇨🇫',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.7,
        'feeds_into': ['russia_proxy_pressure', 'great_power_competition'],
        'keywords': [
            # National forces + government
            'car military', 'central african republic military',
            'faca central african', 'faca car', 'car armed forces',
            'touadera car', 'faustin-archange touadera', 'touadera',
            'bangui military', 'car presidential guard',
            # Wagner / Africa Corps — CAR is the ORIGINAL Wagner model state
            'car wagner', 'wagner car', 'wagner central african',
            'car russian mercenaries', 'africa corps car', 'wagner bangui',
            'wagner presidential guard car', 'russian instructors car',
            'wagner touadera bodyguard', 'wagner car withdrawal',
            'africa corps central african republic',
            # Wagner mining / finance nexus (the payment model)
            'ndassima gold mine', 'ndassima wagner', 'car gold wagner',
            'wagner diamonds car', 'midas resources car', 'lobaye invest',
            'wagner mining concessions car', 'car diamond smuggling russia',
            'bois rouge car', 'wagner timber car',
            # 2023 constitutional referendum (Wagner-engineered third term)
            'car constitutional referendum', 'touadera third term',
            'car 2023 referendum wagner', 'car term limits removed',
            # Armed groups / warlords — CPC coalition + constituents
            'car rebels', 'car civil war', 'car coalition patriots change',
            'coalition of patriots for change', 'cpc car', 'cpc rebels',
            'anti-balaka', 'anti balaka car', 'ex-seleka', 'seleka car',
            'upc car', 'union for peace central africa', 'ali darassa',
            '3r rebels car', 'return reclamation rehabilitation',
            'fprc car', 'mpc car', 'noureddine adam',
            'francois bozize', 'bozize rebels', 'car former president rebels',
            # Key regions / flashpoints
            'bria car', 'bambari car', 'bangassou car', 'bossangoa',
            'birao car', 'obo car', 'vakaga car', 'haut-mbomou',
            'car cameroon border', 'car chad border', 'car sudan border',
            'car drc border spillover',
            # Regional patron competition + UN
            'minusca', 'minusca car', 'un mission central african republic',
            'rwanda troops car', 'rwanda car deployment',
            'car sudan rsf spillover', 'car refugees sudan',
            # French / Western exit
            'france car withdrawal', 'car france rupture', 'car us sanctions wagner',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=central+african+republic+military+OR+car+wagner+OR+bangui&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=cpc+car+OR+anti-balaka+OR+ndassima+wagner&hl=en&gl=US&ceid=US:en',
        ]
    },

    'chad': {
        'name': 'Chad',
        'flag': '🇹🇩',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.6,
        'feeds_into': ['russia_proxy_pressure', 'sahel_instability'],
        'keywords': [
            # National forces + post-Deby transition
            'chad military', 'chadian army', 'ant chad', 'chad armed forces',
            'mahamat deby', 'mahamat idriss deby', 'deby chad', 'chad junta',
            'chad transitional council', 'chad presidential guard', 'dgssie chad',
            "n'djamena military", 'ndjamena military',
            # Russia / Wagner drift
            'chad russia military', 'chad wagner', 'wagner chad', 'russia chad ties',
            'chad russia cooperation', 'chad moscow visit',
            # US / France exit
            'us withdraws chad', 'us forces chad withdrawal', 'chad us military exit',
            'france chad withdrawal', 'chad france military rupture',
            'chad ends military agreement', 'chad french base',
            # Sudan-RSF spillover (the UAE weapons corridor)
            'chad sudan border', 'amdjarass chad', 'uae chad sudan corridor',
            'chad rsf weapons', 'chad sudan refugees', 'chad darfur refugees',
            'chad rsf support', 'chad wadai', 'adre crossing chad',
            # Boko Haram / Lake Chad
            'chad boko haram', 'lake chad basin', 'chad iswap',
            'chad multinational joint task force', 'mnjtf chad',
            # Rebel groups
            'fact chad', 'front change concorde tchad', 'chad rebels',
            'chad northern rebels', 'chad libya border rebels',
            'wagner chad rebels libya',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=chad+military+OR+mahamat+deby+OR+chad+russia&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=chad+sudan+border+OR+amdjarass+OR+fact+chad&hl=en&gl=US&ceid=US:en',
        ]
    },

    'mozambique': {
        'name': 'Mozambique',
        'flag': '🇲🇿',
        'tier': 2,
        'theatre': 'africa',
        'weight': 0.55,
        'feeds_into': ['russia_proxy_pressure', 'humanitarian_cascade'],
        'keywords': [
            # National forces + Cabo Delgado insurgency
            'mozambique military', 'mozambique armed forces', 'fadm mozambique',
            'cabo delgado', 'cabo delgado insurgency', 'mozambique isis',
            'islamic state mozambique', 'iscap mozambique', 'ansar al-sunna mozambique',
            'al-shabaab mozambique', 'mozambique jihadist', 'palma attack',
            'mocimboa da praia', 'macomia attack', 'mueda mozambique',
            # Foreign forces / Wagner history
            'wagner mozambique', 'wagner cabo delgado', 'russia mozambique',
            'rwanda mozambique deployment', 'rwanda troops cabo delgado',
            'samim mozambique', 'sadc mission mozambique', 'samim withdrawal',
            # TotalEnergies LNG (the strategic stake)
            'total lng mozambique', 'mozambique lng force majeure',
            'afungi lng', 'mozambique gas project security',
            # Post-election unrest (2024-2025)
            'mozambique election unrest', 'mozambique protests venancio mondlane',
            'mondlane mozambique', 'frelimo mozambique', 'mozambique post-election violence',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=cabo+delgado+OR+mozambique+insurgency&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=mozambique+lng+security+OR+iscap+mozambique&hl=en&gl=US&ceid=US:en',
        ]
    },

    'madagascar': {
        'name': 'Madagascar',
        'flag': '🇲🇬',
        'tier': 3,
        'theatre': 'africa',
        'weight': 0.4,
        'feeds_into': ['russia_proxy_pressure'],
        'keywords': [
            'madagascar military', 'madagascar armed forces', 'madagascar coup',
            'andry rajoelina', 'rajoelina madagascar', 'madagascar political crisis',
            # Russia influence (2018 election-interference precedent)
            'russia madagascar', 'wagner madagascar', 'russia madagascar election',
            'prigozhin madagascar', 'madagascar russia cooperation',
            'madagascar russia mining', 'madagascar chromite russia',
            # Instability drivers
            'madagascar dahalo', 'dahalo bandits', 'madagascar cattle raiders',
            'madagascar south famine', 'madagascar drought crisis',
            'antananarivo protest', 'madagascar unrest',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=madagascar+military+OR+madagascar+russia+OR+rajoelina&hl=en&gl=US&ceid=US:en',
        ]
    },

    'equatorial_guinea': {
        'name': 'Equatorial Guinea',
        'flag': '🇬🇶',
        'tier': 3,
        'theatre': 'africa',
        'weight': 0.4,
        'feeds_into': ['russia_proxy_pressure', 'great_power_competition'],
        'keywords': [
            'equatorial guinea military', 'equatorial guinea armed forces',
            'obiang equatorial guinea', 'teodoro obiang', 'teodorin obiang',
            'malabo military', 'equatorial guinea coup',
            # Russia / China base competition (the Atlantic-port story)
            'russia equatorial guinea', 'wagner equatorial guinea',
            'russia equatorial guinea security', 'russia malabo',
            'china equatorial guinea base', 'china atlantic base bata',
            'bata port china', 'us equatorial guinea base concern',
            'equatorial guinea russia security pact',
            # Regime security
            'equatorial guinea presidential guard', 'equatorial guinea mercenaries',
            'equatorial guinea coup plot',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=equatorial+guinea+military+OR+equatorial+guinea+russia+OR+china+bata&hl=en&gl=US&ceid=US:en',
        ]
    },

    'guinea': {
        'name': 'Guinea',
        'flag': '🇬🇳',
        'tier': 3,
        'theatre': 'africa',
        'weight': 0.4,
        'feeds_into': ['sahel_instability'],
        'keywords': [
            'guinea military', 'guinea junta', 'guinea coup', 'guinea armed forces',
            'mamadi doumbouya', 'doumbouya guinea', 'guinea cnrd',
            'conakry military', 'guinea transition', 'guinea special forces',
            # Russia / resource competition (bauxite / Simandou)
            'guinea russia military', 'russia guinea', 'guinea rusal',
            'guinea bauxite russia', 'simandou guinea', 'guinea china mining security',
            # Instability
            'guinea protest crackdown', 'guinea fndc', 'guinea opposition crackdown',
            'guinea coup plot', 'guinea junta consolidation',
            # NOTE: 'guinea' also matches Guinea-Bissau / Equatorial Guinea in feeds;
            # keyword pairs above are Conakry-Guinea specific to reduce bleed.
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=guinea+conakry+military+OR+doumbouya+OR+guinea+junta&hl=en&gl=US&ceid=US:en',
        ]
    },

    'wagner_africa': {
        'name': 'Wagner Group / Africa Corps',
        'flag': '🇷🇺',
        'tier': 1,
        'theatre': 'africa',
        'weight': 0.9,
        'feeds_into': ['russia_proxy_pressure', 'great_power_competition'],
        'keywords': [
            # Wagner / post-Prigozhin rebrand
            'wagner group africa', 'wagner africa',
            'africa corps', 'russia africa corps',
            'russian mercenaries africa', 'russia military africa',
            'russian military advisers africa',
            'gru africa', 'rosgvardiya africa',
            # Country footprint
            'wagner mali', 'wagner burkina faso', 'wagner niger',
            'wagner car', 'wagner sudan', 'wagner libya',
            'wagner madagascar', 'wagner mozambique',
            'africa corps mali', 'africa corps burkina',
            'africa corps libya', 'africa corps niger',
            'africa corps car', 'africa corps drc',
            # Operations / activity
            'wagner gold mining africa', 'wagner africa gold',
            'wagner massacres', 'wagner africa civilians',
            'wagner training african forces',
            'russia private military africa',
            'prigozhin africa legacy',
            # Specific commanders / leaders
            'andrey averyanov', 'gru general africa',
            'yevkurov africa', 'russia deputy defense africa',
            # Post-Prigozhin leadership transition
            'yunus-bek yevkurov', 'yevkurov africa tour',
            'pavel popov africa', 'russia africa envoy',
            'sergei surovikin africa',
            # Africa Corps formal command structure
            'gru unit 29155 africa', 'unit 29155',
            'gru direct command africa', 'russia mod africa corps',
            'russian regular military africa', 'russia regular troops africa',
            # 2024-2026 events
            'wagner tinzaouaten losses 2024',
            'wagner cme mali ambush', 'wagner mali casualties',
            'africa corps niger arrival',
            'africa corps burkina arrival',
            'africa corps niger 100 troops',
            'africa corps niger 1000 troops',
            # Russia State Duma rebrand statements
            'putin africa corps statement',
            'shoigu africa visit', 'belousov africa',
            'lavrov africa tour military',
            # Gold trafficking + finance network
            'wagner gold smuggling', 'sudan gold russia',
            'wagner uae gold', 'russia gold africa sanctions',
            'wagner finance africa',
            # AFRICOM counter-Wagner
            'africom counter wagner', 'us state department wagner',
            'us treasury wagner africa sanctions',
            'wagner sdgt designation',
            # Maghreb expansion (Algeria/Morocco tension)
            'wagner algeria', 'wagner morocco',
            'wagner sahara', 'wagner western sahara',
            # Equatorial Guinea / new theater rumors
            'wagner equatorial guinea', 'wagner gabon',
            'wagner togo', 'wagner ivory coast tension',
            # Port Sudan hub + Sudan state-level plug (Jul 2026)
            'africa corps sudan', 'africa corps port sudan',
            'russia port sudan logistics', 'tobruk africa corps',
            'africa corps supply route',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=wagner+africa+OR+africa+corps+OR+russia+mercenaries+africa&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=yevkurov+africa+OR+africa+corps+deployment&hl=en&gl=US&ceid=US:en',
        ]
    },

}


# ========================================
# ASSET CATEGORIES & WEIGHTS
# ========================================

ASSET_CATEGORIES = {
    'carrier_strike_group': {
        'label': 'Carrier Strike Group',
        'icon': '🚢',
        'weight': 5.0,
        'description': 'Aircraft carrier + escorts. Maximum power projection.',
        'keywords': [
            'carrier strike group', 'aircraft carrier', 'uss nimitz',
            'uss eisenhower', 'uss ford', 'uss lincoln', 'uss truman',
            'uss roosevelt', 'uss reagan', 'uss vinson', 'uss stennis',
            'uss washington', 'uss bush', 'csg deployed',
            # Named ships currently in news (v2.8.0)
            'uss carl vinson', 'uss ronald reagan', 'uss george washington',
            'uss harry truman', 'uss gerald ford', 'uss john c stennis',
            # Movement language
            'carrier transits', 'carrier arrives', 'carrier departs',
            'carrier redeployed', 'carrier repositioned', 'csg transiting',
            'strike group arrives', 'strike group departs', 'strike group redeployed',
            'carrier strike group pacific', 'carrier strike group persian gulf',
            'carrier strike group red sea', 'carrier strike group mediterranean'
        ]
    },
    'submarine': {
        'label': 'Submarine',
        'icon': '🔱',
        'weight': 4.5,
        'description': 'SSBN/SSGN/SSN. Stealth strike capability.',
        'keywords': [
            'submarine deployed', 'submarine gulf', 'submarine mediterranean',
            'ssbn', 'ssgn', 'ohio class', 'virginia class',
            'submarine transit suez', 'submarine indian ocean',
            'guided missile submarine', 'uss georgia', 'uss florida',
            'uss ohio', 'uss michigan'
        ]
    },
    'bomber_deployment': {
        'label': 'Strategic Bomber',
        'icon': '✈️',
        'weight': 4.0,
        'description': 'B-1/B-2/B-52 deployment signals deep strike readiness.',
        'keywords': [
            'bomber task force', 'b-1 lancer', 'b-1b',
            'b-2 spirit', 'b-2 bomber', 'b-52 stratofortress', 'b-52h',
            'bomber deployment diego garcia', 'bomber deployment middle east',
            'strategic bomber deployed', 'long-range strike',
            'b-2 stealth bomber', 'long-range mission'
        ]
    },
    'naval_movement': {
        'label': 'Naval Redeployment',
        'icon': '🔄',
        'weight': 3.5,
        'description': 'Significant naval asset movement — redeployment, transit, repositioning signal.',
        'keywords': [
            # Redeployment/repositioning language
            'navy redeployed', 'ships redeployed', 'fleet repositioned',
            'naval assets moved', 'warships repositioned', 'ships transiting',
            'destroyer redeployed', 'cruiser redeployed', 'frigate redeployed',
            # Fleet-to-fleet transitions (key strategic signal)
            'fifth fleet to seventh', 'persian gulf to pacific',
            'redeployed to pacific', 'shifted to pacific', 'moved to pacific',
            'redeployed from gulf', 'withdrawn from gulf', 'departing gulf',
            'transit strait of hormuz', 'transit suez canal',
            # Minesweepers + Hormuz mining threat (v2.9.1)
            'minesweeper', 'mine countermeasures', 'mcm vessel',
            'uss pioneer', 'uss chief', 'uss devastator', 'uss champion',
            'avenger class', 'mine warfare',
            # LCS minesweeping variant — Hormuz repositioning signal
            'uss tulsa', 'uss santa barbara', 'uss cincinnati',
            'littoral combat ship', 'lcs minesweeping', 'lcs mine',
            'independence class lcs', 'freedom class lcs',
            'hormuz mining', 'mining strait of hormuz', 'iran mining',
            'hormuz mine threat', 'mine threat gulf',
            'minesweeper malaysia', 'minesweeper singapore',
            'lcs repositioned', 'lcs redeployed', 'gulf lcs withdrawn',
            'logistical stop malaysia', 'port visit penang',
            # General movement signals
            'arrives fifth fleet', 'departs fifth fleet',
            'arrives sixth fleet', 'departs sixth fleet',
            'arrives seventh fleet', 'departs seventh fleet',
            'navcent arrival', 'navcent departure',
        ]
    },
    'amphibious_group': {
        'label': 'Amphibious Ready Group',
        'icon': '⚓',
        'weight': 3.5,
        'description': 'Marines + landing ships. Ground intervention capability.',
        'keywords': [
            'amphibious ready group', 'arg deployed', 'marine expeditionary unit',
            'meu deployed', 'amphibious assault ship', 'lhd deployed',
            'lpd deployed', 'dock landing ship'
            # Marine ground force deployment signals (v2.9.0)
            'marine ground troops', 'marines deploying', 'marines headed to',
            'marines en route', 'marines bound for', 'marines carrying',
            'warship carrying marines', 'ship carrying marines',
            'tracked off singapore', 'tracked off', 'spotted off',
            'transiting singapore', 'transiting malacca',
            'believed to be carrying', 'believed carrying troops',
            'heading to middle east', 'heading for middle east',
            'bound for middle east', 'en route middle east',
            'wasp class', 'america class', 'lha deployed',
            'lhd deployed', 'lha transiting', 'lhd transiting',
        ]
    },
    'fighter_surge': {
        'label': 'Fighter Aircraft Surge',
        'icon': '🛩️',
        'weight': 3.0,
        'description': 'Additional fighter squadron deployments.',
        'keywords': [
            'f-35 deployed', 'f-22 deployed', 'f-15 deployed', 'f-16 deployed',
            'fighter squadron deployed', 'additional aircraft',
            'air expeditionary wing', 'fighter surge', 'combat air patrol',
            'f-15e strike eagle', 'strike eagles deployed',
            'expeditionary fighter squadron', 'fighter wing deployed'
        ]
    },
    'air_defense': {
        'label': 'Air Defense System',
        'icon': '🛡️',
        'weight': 3.0,
        'description': 'Patriot/THAAD/Iron Dome deployment indicates threat preparation.',
        'keywords': [
            'patriot battery deployed', 'thaad deployed', 'thaad battery',
            'iron dome deployed', 'arrow battery', 'david sling deployed',
            'air defense deployment', 'sam battery', 'air defense activation',
            'patriot missile defense', 'air defense coordination',
            'mead-cdoc', 'air defense cell',
            # Israel active air defense (v2.7.2)
            'iron dome intercept', 'iron dome activated', 'iron dome overwhelmed',
            'arrow intercept', 'arrow 3 intercept', 'david sling intercept',
            'air defense activated', 'air defense fires',
            'missile intercepted', 'intercepted over israel',
            'multi-layer defense', 'ballistic missile intercept',
            'iran missile intercept', 'intercepts ballistic',
            'shoots down drone', 'shoots down missile',
            # Regional air defense / intercept (v2.7.2)
            'patriot intercept', 'patriot missile intercept',
            'thaad intercept', 'thaad engagement',
            'air defense intercept', 'air defense engagement',
            'intercepted missile', 'intercepted drone',
            'intercepted ballistic', 'intercepted cruise missile',
            'shot down drone', 'shot down missile',
            'air defense system activated', 'air defense response',
            'saudi air defense intercept', 'saudi intercept',
            'uae air defense intercept', 'uae intercept',
            'jordan intercept', 'jordan air defense',
            'qatar air defense', 'kuwait air defense',
            'bahrain air defense', 'oman air defense',
            'egypt air defense', 'turkey air defense',
            'intercepted over saudi', 'intercepted over uae',
            'intercepted over jordan', 'intercepted over qatar',
            'intercepted over bahrain', 'intercepted over kuwait',
        ]
    },
    'isr_assets': {
        'label': 'ISR / Surveillance',
        'icon': '👁️',
        'weight': 2.5,
        'description': 'Intelligence/Surveillance/Recon buildup precedes operations.',
        'keywords': [
            'mq-9 reaper', 'rq-4 global hawk', 'mq-4c triton',
            'p-8 poseidon', 'e-3 awacs', 'rc-135 rivet joint',
            'isr surge', 'surveillance aircraft', 'reconnaissance flight',
            'spy plane', 'intelligence aircraft', 'sigint aircraft',
            'rc-135w', 'electronic emissions', 'flight tracking military'
        ]
    },
    'ground_forces': {
        'label': 'Ground Forces',
        'icon': '🪖',
        'weight': 3.5,
        'description': 'Troop deployments and ground force movements.',
        'keywords': [
            'troops deployed', 'brigade deployed', 'division deployed',
            'battalion deployed', 'special forces deployed',
            'airborne deployed', 'infantry deployed',
            'reservists called up', 'mobilization order',
            'ground forces buildup',
            # Active war ground signals (v2.7.2)
            'soldiers killed', 'troops killed', 'service members killed',
            'casualties confirmed', 'killed in action',
            'wounded in action', 'soldiers wounded',
            'idf troops deployed', 'idf ground operation',
            'reservists mobilized', 'reserves called up',
            'home front command', 'shelter instructions',
        ]
    },
    'logistics': {
        'label': 'Logistics / Pre-positioning',
        'icon': '📦',
        'weight': 2.0,
        'description': 'Supply buildup often precedes major operations.',
        'keywords': [
            'pre-positioned stocks', 'ammunition shipment',
            'military sealift command', 'logistics buildup',
            'fuel pre-positioning', 'hospital ship deployed',
            'supply chain military', 'c-17 airlift surge',
            'c-5 galaxy deployment', 'military cargo',
            'cargo planes flowing', 'c-130 airlift',
            'airlift surge', 'logistics surge'
        ]
    },
    'missile_test': {
        'label': 'Missile Test / Launch',
        'icon': '🚀',
        'weight': 4.0,
        'description': 'Ballistic/cruise missile tests and live-fire launches.',
        'keywords': [
            'missile test', 'ballistic missile launch', 'cruise missile test',
            'missile exercise', 'rocket launch', 'weapons test',
            'hypersonic test', 'anti-ship missile test',
            'tomahawk launch', 'missile salvo',
            # Active missile fire (v2.7.2)
            'ballistic missile', 'cruise missile', 'missile barrage',
            'missile salvo', 'fires missiles', 'launches missiles',
            'rocket barrage', 'missile strike', 'missile attack',
            'iran fires missiles', 'iran launches missiles',
            'iran ballistic missile', 'iran cruise missile',
            'iranian missile attack', 'iranian ballistic missile',
            'houthi missile', 'hezbollah rockets',
            'missile hits', 'missile impact', 'missile struck',
        ]
    },
    'naval_exercise': {
        'label': 'Naval Exercise',
        'icon': '⚓',
        'weight': 2.0,
        'description': 'Multi-nation or large-scale naval drills.',
        'keywords': [
            'naval exercise', 'maritime exercise', 'naval drill',
            'freedom of navigation', 'multinational naval exercise',
            'combined maritime forces', 'naval war games'
        ]
    },
    'base_evacuation': {
        'label': 'Base Evacuation / Ordered Departure',
        'icon': '🚨',
        'weight': 5.0,
        'description': 'Evacuation of military bases or embassy drawdowns. Highest threat signal.',
        'keywords': [
            'base evacuation', 'military evacuation', 'evacuated base',
            'evacuation ordered', 'personnel evacuated',
            'troops evacuated', 'evacuated troops',
            'evacuation of base', 'base drawdown',
            'noncombatant evacuation', 'neo operation',
            'neo packet', 'neo preparation',
            'ordered departure', 'embassy ordered departure',
            'reduced footprint', 'nonessential personnel depart',
            'embassy drawdown', 'embassy evacuation',
            'partial evacuation', 'personnel relocated',
            'voluntary departure', 'authorized departure',
            'dependent evacuation', 'dependents evacuated',
            'family departure', 'family evacuation',
            'military families evacuate', 'military families depart',
            'families prepare departure', 'families leaving',
            'embassy closure', 'consulate evacuation',
            'potential departures', 'prepare for evacuation',
            # Active war evacuation signals (v2.7.2)
            'us citizens leave israel', 'leave israel immediately',
            'evacuate israel', 'evacuate cyprus',
            'us citizens leave', 'citizens urged to leave',
            'authorized departure israel', 'authorized departure',
            'commercial flights cancelled', 'airport closed',
            'ben gurion closed', 'ben gurion airport closed',
            'airspace closed', 'flights grounded',
            'shelter in place', 'seek shelter',
        ]
    },
    'military_posturing': {
        'label': 'Military Posturing / Threats',
        'icon': '⚠️',
        'weight': 2.5,
        'description': 'Explicit military threats, warnings, or posturing statements.',
        'keywords': [
            'military threat', 'threatens retaliation',
            'warns of military action', 'warns neighbors',
            'all options on the table', 'military options',
            'strike options', 'decisive military options',
            'regime change', 'regime overthrow',
            'hit very hard', 'overwhelming force',
            'bases within range', 'within our range',
            'will defend with full force', 'painful response',
            # Target under fire / victim-of-attack signals (v2.7.2)
            'struck by missile', 'hit by missile', 'hit by drone',
            'attacked by iran', 'iranian attack on', 'iranian strike on',
            'iranian missiles strike', 'iran attacks',
            'under attack', 'came under fire', 'shelling reported',
            'explosion reported', 'blast reported',
            'embassy hit', 'embassy struck', 'embassy attacked',
            'port struck', 'port attacked', 'oil facility attacked',
            'base hit', 'base struck', 'base attacked',
            'casualties reported', 'killed in attack',
            'wounded in attack', 'shrapnel', 'debris fell',
            'infrastructure hit', 'civilian casualties',
        ]
    },
    'drone_incursion': {
        'label': 'Drone Incursion / Airspace Violation',
        'icon': '🛸',
        'weight': 3.5,
        'description': 'Unidentified drone or object entering sovereign airspace. Border threat signal.',
        'keywords': [
            'drone incursion', 'drone entered airspace',
            'drone crossed border', 'airspace violation',
            'unidentified drone', 'mystery drone',
            'drone flyover', 'drone overflight',
            'stray drone', 'wayward drone',
            'object entered airspace', 'airspace breach',
            'scramble jets drone', 'intercept drone',
            'shoot down drone', 'drone shot down',
            'missile crossed border', 'projectile entered airspace',
            'border airspace incident',
            'drone from belarus', 'drone from russia',
            'uav crossed border', 'uav incursion',
            # Active war drone/airspace (v2.7.2)
            'shahed drone', 'iranian drone', 'iran drone attack',
            'drone swarm', 'drone strike', 'kamikaze drone',
            'one-way attack drone', 'uav attack',
            'airspace closed', 'airspace violation',
        ]
    },
    # ────────────────────────────────────────────────────────────────
    # HOSPITAL SHIP (May 22 2026 — humanitarian convergence signal)
    # USNS Mercy (T-AH-19, Pacific) + USNS Comfort (T-AH-20, Atlantic)
    # Hospital ship deployment is a high-fidelity strategic signal:
    #   - Indicates US recognition of severe humanitarian crisis
    #   - Co-occurrence with pandemic/disease signals = major convergence
    #   - 1,000-bed capacity, lengthy planning/sail times
    # Weight 3.5: more than logistics, less than carrier (significant but
    # not strike-related). Frontend should display as distinct asset class.
    # ────────────────────────────────────────────────────────────────
    'hospital_ship': {
        'label': 'Hospital Ship',
        'icon': '🏥',
        'weight': 3.5,
        'description': (
            'USNS Mercy / Comfort deployment — strategic humanitarian asset. '
            'Co-occurrence with pandemic/disease signals = major convergence indicator.'
        ),
        'keywords': [
            'usns mercy', 'uss mercy', 'mercy hospital ship', 't-ah-19',
            'usns comfort', 'uss comfort', 'comfort hospital ship', 't-ah-20',
            'us hospital ship', 'us navy hospital ship',
            'hospital ship deployment', 'hospital ship deploys',
            'hospital ship arrives', 'hospital ship sails',
            'hospital ship departs', 'hospital ship returns',
            'mercy deployed', 'comfort deployed', 'mercy sails', 'comfort sails',
            'mercy departs', 'comfort departs',
            'pacific partnership mercy', 'continuing promise comfort',
            'medical treatment facility ship',
            # HA/DR mission deployments that frequently use hospital ships
            'us navy disaster relief', 'us navy medical mission',
            'medical relief ship', 'medical mission deployment',
        ]
    }
}


# ========================================
# EVACUATION SUB-TYPE WEIGHTS
# ========================================

EVACUATION_SUBTYPE_WEIGHTS = {
    'military_evacuation': {
        'weight': 5.0,
        'keywords': ['base evacuation', 'military evacuation', 'evacuated base',
                     'evacuation ordered', 'personnel evacuated', 'troops evacuated',
                     'evacuated troops', 'base drawdown']
    },
    'neo_operation': {
        'weight': 4.5,
        'keywords': ['noncombatant evacuation', 'neo operation', 'neo packet',
                     'neo preparation']
    },
    'ordered_departure': {
        'weight': 4.0,
        'keywords': ['ordered departure', 'embassy ordered departure',
                     'reduced footprint', 'nonessential personnel',
                     'embassy drawdown', 'embassy evacuation',
                     'partial evacuation', 'personnel relocated',
                     'tankers vacate', 'vacate air base',
                     'urged to leave', 'citizens urged to leave',
                     'airport closed', 'flights cancelled',
                     'airspace closed', 'flights suspended',
                     'dubai airport closed', 'ben gurion closed',
                     'commercial flights cancelled']
    },
    'voluntary_departure': {
        'weight': 3.5,
        'keywords': ['voluntary departure', 'authorized departure',
                     'dependent evacuation', 'dependents evacuated',
                     'family departure', 'family evacuation',
                     'military families evacuate', 'military families depart',
                     'families prepare departure', 'families leaving',
                     'potential departures', 'prepare for evacuation']
    }
}


# ========================================
# LOCATION MULTIPLIERS
# ========================================

LOCATION_MULTIPLIERS = {
    'strait of hormuz': 3.0,
    'bab el-mandeb': 3.0,
    'suez canal': 2.5,
    'taiwan strait': 3.0,
    'persian gulf': 2.0,
    'arabian sea': 2.0,
    'red sea': 2.0,
    'gulf of oman': 2.5,
    'eastern mediterranean': 2.0,
    'black sea': 2.0,
    'sea of azov': 2.0,
    'al udeid': 2.5,
    'bahrain naval': 2.0,
    'camp arifjan': 1.5,
    'muwaffaq salti': 2.0,
    'tower 22': 2.5,
    'incirlik': 1.5,
    'diego garcia': 2.0,
    'tartus': 2.0,
    'hmeimim': 2.0,
    'zaporizhzhia': 2.0,
    'crimea': 2.0,
    'kursk': 2.0,
    'arctic': 1.5,
    'greenland': 1.5,
    'south china sea': 2.0,
    'baltic': 1.5,
    # Poland-specific hotspots (v2.3.0)
    'rzeszów': 2.0,
    'rzeszow': 2.0,
    'redzikowo': 2.0,
    'przewodów': 2.5,
    'przewodow': 2.5,
    'poland belarus border': 2.0,
    'polish airspace': 2.0,
    'suwalki gap': 2.5,
    'kaliningrad': 2.0,
    'lask air base': 1.5,
    # Iraq-specific hotspots (v2.5.0)
    'al asad': 2.5,
    'ain al-asad': 2.5,
    'ain al asad': 2.5,
    'erbil': 2.0,
    'taji': 2.0,
    'balad air base': 2.0,
    'baghdad green zone': 2.5,
    'green zone': 2.0,
    'camp victory': 2.0,
    'iraqi airspace': 2.5,
    'iraq airspace': 2.5,
    'anbar province': 2.0,
    'qaim': 2.0,
    'sinjar': 1.5,
    'kirkuk': 1.5,
    'mosul': 1.5,
    'basra': 1.5,
    'sulaymaniyah': 1.5,
    'diyala': 2.0,
    # Bahrain (v2.6.0)
    'bahrain naval base': 2.5,
    'juffair': 2.5,
    'nsa bahrain': 2.5,
    'fifth fleet': 2.5,
    '5th fleet': 2.5,
    'sixth fleet': 2.0,
    '6th fleet': 2.0,
    'seventh fleet': 2.0,
    '7th fleet': 2.0,
    'navcent': 2.5,
    'indopacom': 2.0,
    'minesweeper': 2.0,
    'mine countermeasures': 2.0,
    'hormuz mining': 3.5,       # Iran mining = major escalation signal
    'mining strait of hormuz': 3.5,
    'iran mining': 3.0,
    'mine threat gulf': 3.0,
    'uss tulsa': 2.5,           # Named LCS vessels — specific signal
    'uss santa barbara': 2.5,
    'uss cincinnati': 2.5,
    'littoral combat ship': 2.0,
    'lcs minesweeping': 2.5,
    'lcs redeployed': 2.5,
    'naval station rota': 2.0,
    'naval station norfolk': 1.5,
    'naval base guam': 2.0,
    'yokosuka': 2.0,
    # Indo-Pacific transit waypoints (v2.9.0)
    'singapore': 2.0,
    'strait of malacca': 2.5,
    'strait of singapore': 2.0,
    'south china sea': 2.0,
    'diego garcia': 2.5,
    'andaman sea': 1.5,
    'bay of bengal': 1.5,
    'indian ocean': 1.5,
    'horn of africa': 1.5,
    'djibouti': 2.0,
    'camp lemonnier': 2.5,
    'sheikh isa air base': 2.0,
    'mina salman': 2.0,
    # Kuwait (v2.7.0)
    'camp arifjan': 2.5,
    'ali al salem': 2.0,
    'kuwait port': 2.0,
    'kuwait city': 1.5,
    # Saudi Arabia (v2.7.0)
    'prince sultan air base': 2.5,
    'king abdulaziz air base': 2.0,
    'king fahd air base': 2.0,
    'riyadh': 2.0,
    'dhahran': 2.0,
    'eastern province': 2.0,
    'aramco': 2.5,
    # UAE (v2.7.0)
    'al dhafra': 2.5,
    'dubai': 1.5,
    'abu dhabi': 2.0,
    'jebel ali': 2.0,
    # Jordan (v2.7.0)
    'muwaffaq salti': 2.5,
    'tower 22': 2.5,
    'amman': 1.5,
    # Qatar (v2.7.0)
    'al udeid': 2.5,
    'doha': 1.5,
    # Oman (v2.7.0)
    'duqm': 2.0,
    'masirah': 2.0,
    'thumrait': 2.0,
    'muscat': 1.5,
    # Cyprus (v2.7.0)
    'akrotiri': 2.5,
    'dhekelia': 2.0,
    'larnaca': 1.5,
    'paphos air base': 2.0,
    'nicosia': 1.5,
    'limassol': 1.5,
    # Egypt (v2.7.0)
    'suez canal': 3.0,
    'sharm el sheikh': 1.5,
    'cairo': 1.5,
    # UAE ports (v2.7.1)
    'fujairah': 2.5,
    'ras tanura': 2.5,
    # Saudi ports (v2.7.1)
    'jubail': 2.0,
    'jeddah': 1.5,
    # Turkey (v2.7.1)
    'incirlik': 2.5,
    'ankara': 1.5,
    'istanbul': 1.5,
    # Israel (v2.7.2)
    'tel aviv': 2.5,
    'haifa': 2.5,
    'jerusalem': 2.0,
    'ben gurion': 3.0,
    'dimona': 3.0,
    'nevatim': 3.0,
    'ramon air base': 2.5,
    'hatzerim': 2.5,
    'ramat david': 2.5,
    'palmachim': 2.5,
    'eilat': 2.0,
    'negev': 1.5,
    'golan': 2.0,
    'iron dome': 2.0,
    'arrow': 2.0,
    # Western Hemisphere — chokepoints and bases (v3.0.0)
    'panama canal': 3.0,
    'canal zone': 2.5,
    'darien gap': 2.0,
    'soto cano': 2.5,
    'joint task force bravo': 2.5,
    'naval station guantanamo': 2.5,
    'guantanamo bay': 2.5,
    'gtmo': 2.5,
    'nas key west': 2.0,
    'key west naval': 2.0,
    'navbase san diego': 2.0,
    'naval base san diego': 2.0,
    'naval station san diego': 2.0,
    'third fleet': 2.0,
    'southcom': 2.0,
    'us southern command': 2.0,
    'florida straits': 2.0,
    'caribbean sea military': 1.5,
    'gulf of mexico military': 1.5,
    'miraflores palace': 2.5,
    'caracas military': 2.0,
    'maracaibo': 1.5,
    'havana military': 2.0,
    'santiago de cuba': 1.5,
    'port-au-prince': 2.0,
    'cite soleil': 2.5,
    'bogota military': 1.5,
    'cali cartel': 2.0,
    'medellin military': 2.0,
    'mexico city military': 1.5,
    'ciudad juarez': 2.0,
    'tijuana military': 1.5,
    'culiacan': 2.5,
    'sinaloa military': 2.0,
    'rio de janeiro military': 1.5,
    'brasilia military': 1.5,
    # ──────────────────────────────────────────────────────────────────
    # US HOME PORTS (May 22 2026 — Naval Asset Visibility expansion)
    # Lower multipliers (1.0-1.5) because these are routine/home locations;
    # a signal at home port = "asset is alive and accounted for" not
    # "asset is poised for combat." Used by frontend to plot ALL US Navy
    # positions on the deployment map, not just the hot zones.
    # ──────────────────────────────────────────────────────────────────
    # East Coast home ports
    'norfolk naval':            1.3,
    'naval station norfolk':    1.3,
    'mayport':                  1.2,
    'mayport naval':            1.2,
    'kings bay':                1.5,   # Sub base — strategic deterrent
    'naval submarine base kings bay': 1.5,
    'annapolis':                1.0,   # Mostly ceremonial / Fleet Week
    'fleet week':               1.2,   # Catches any Fleet Week city
    'groton':                   1.5,   # Sub base
    'sub base groton':          1.5,
    'naval submarine base groton': 1.5,
    'portsmouth naval':         1.2,
    'portsmouth naval shipyard': 1.2,
    'new london submarine':     1.5,
    # West Coast home ports
    'san diego':                1.5,   # Major fleet hub
    'naval station san diego':  1.5,
    'navbase san diego':        1.5,
    'bremerton':                1.3,
    'naval base kitsap':        1.3,
    'bangor':                   1.7,   # SSBN sub base — Trident
    'bangor submarine':         1.7,
    'everett':                  1.3,
    'naval station everett':    1.3,
    'coronado':                 1.5,
    'naval amphibious base coronado': 1.5,
    'point loma':               1.3,
    'naval base point loma':    1.3,
    'lemoore':                  1.3,
    'nas lemoore':              1.3,
    'nas fallon':               1.3,
    'north island':             1.3,
    'naval air station north island': 1.3,
    # Pacific home ports
    'pearl harbor':             2.0,   # INDOPACOM nexus
    'naval base pearl harbor':  2.0,
    'joint base pearl harbor hickam': 2.0,
    'apra harbor':              2.0,   # Guam
    'naval base guam apra':     2.0,
    # Gulf Coast home ports
    'pascagoula':               1.3,   # Shipbuilding + station
    'naval air station jacksonville': 1.3,
    'nas jacksonville':         1.3,
    'kingsville naval':         1.2,
    'corpus christi naval':     1.2,
    # Japan / Forward home ports
    'sasebo':                   2.2,   # Amphib hub Western Pacific
    'naval base sasebo':        2.2,
    # ──────────────────────────────────────────────────────────────────
    # IRAN KINETIC RE-HEATING — Additional hotspots (May 22 2026)
    # ──────────────────────────────────────────────────────────────────
    'nevatim air base':         3.0,   # Israeli AB used by US (joint exercises, Iran ops)
    'tel nof':                  2.5,   # Israeli AB
    'sde dov':                  2.0,
    'ovda':                     2.5,   # Israeli AB, Eilat region
    'ramat david air base':     2.5,
    'ben gurion launch':        3.5,   # Specific phrase = major signal
    'us bombers israel':        3.0,
    'tanker bridge':            2.5,
    'aerial refueling bridge':  2.5,
    'strike package iran':      3.5,
    'kinetic prep iran':        3.5,
    'pre-strike posture':       3.0,
    'pre-strike positioning':   3.0,
    'b-2 staging israel':       3.5,
    'b-21 deployment':          3.0,   # Newest stealth bomber
    'kc-46 nevatim':            3.0,
    # ──────────────────────────────────────────────────────────────────
    # AFRICA THEATER LOCATIONS (May 22 2026 — new theater build)
    # AFRICOM AOR — Sahel/Horn/Lake Chad/Great Lakes hotspots + key bases.
    # ──────────────────────────────────────────────────────────────────
    # AFRICOM HQ + major US bases
    'africom':                  2.0,
    'us africa command':        2.0,
    'africom hq':               2.0,
    'stuttgart africom':        1.5,
    'camp lemonnier':           2.5,   # Already in CENTCOM block, but key for Africa
    'cjtf-hoa':                 2.5,
    # Niger (former US drone hub — eviction is a major signal in itself)
    'air base 201':             2.5,
    'niger air base 201':       2.5,
    'agadez':                   2.0,
    'niger drone base':         2.5,
    'niamey':                   1.8,
    # Sahel hotspots
    'gao mali':                 2.0,
    'kidal mali':                2.0,
    'mopti mali':               2.0,
    'timbuktu military':        1.5,
    'bamako military':          1.5,
    'ouagadougou military':     1.5,
    # Nigeria / Lake Chad Basin
    'borno state':              2.0,
    'maiduguri':                2.0,
    'lake chad basin':          2.0,
    'sambisa forest':           2.0,
    'abuja military':           1.5,
    'lagos military':           1.5,
    # Horn of Africa
    'mogadishu':                2.5,
    'mogadishu attack':         2.5,
    'kismayo':                  1.8,
    'baidoa':                   1.5,
    'manda bay':                2.5,   # Kenya — US base attacked Jan 2020
    'camp simba':               2.0,
    'lamu kenya':               1.5,
    'doraleh port':             2.0,
    'addis ababa military':     1.5,
    'asmara':                   1.5,
    # Great Lakes / DRC
    'goma':                     2.5,
    'goma military':            2.5,
    'bukavu':                   2.0,
    'beni drc':                 2.0,
    'north kivu':               2.0,
    'south kivu':               2.0,
    'kinshasa military':        1.5,
    'kigali military':          1.5,   # Rwanda
    # Sudan civil war
    'khartoum military':        2.5,
    'khartoum fighting':        2.5,
    'omdurman':                 2.5,
    'port sudan':               2.0,
    'darfur':                   2.5,
    'el fasher':                3.0,   # Genocide-watch hotspot
    'el-fasher':                3.0,
    'el fashir':                3.0,
    'nyala':                    2.0,
    'el obeid':                 2.5,   # Critical frontline: RSF siege (2026)
    'el-obeid':                 2.5,
    'um baru':                  2.0,   # Chad-border offensive corridor
    # South Sudan (Jul 2026)
    'juba military':            2.0,
    'juba south sudan':         2.0,
    'nasir upper nile':         2.2,   # White Army / SSPDF flashpoint
    'malakal':                  2.0,
    # Libya
    'tripoli libya':            2.0,
    'benghazi':                 2.0,
    'sirte':                    2.0,
    'misrata':                  1.8,
    'al-watiya':                2.0,
    'al watiya':                2.0,
    'tobruk':                   1.8,
    # Central African Republic
    'bangui':                   1.8,
    'car bangui':               1.8,
    # Strategic waterways near Africa
    'mozambique channel':       1.5,
    'gulf of guinea':           1.5,
    'cabo delgado':             1.8,   # Mozambique ISIS-linked insurgency
    # Cross-region high-signal phrases
    'wagner africa':            2.5,
    'africa corps':             2.5,
    'russian mercenaries africa': 2.5,
}


# ========================================
# ASSET → TARGET MAPPING
# ========================================

ASSET_TARGET_MAPPING = {
    'centcom': {
        'Al Udeid Air Base': {
            'location': 'Qatar',
            'targets': ['iran', 'qatar'],
            'description': 'CENTCOM forward HQ. Primary air ops hub.'
        },
        'Al Dhafra Air Base': {
            'location': 'UAE',
            'targets': ['iran', 'uae'],
            'description': 'ISR and tanker hub. Iran-facing.'
        },
        'Bahrain Naval Base': {
            'location': 'Bahrain',
            'targets': ['bahrain', 'iran'],
            'description': 'US 5th Fleet HQ. Naval ops center.'
        },
        'NSA Bahrain (5th Fleet HQ)': {
            'location': 'Bahrain',
            'targets': ['bahrain', 'iran'],
            'description': 'US 5th Fleet / NAVCENT HQ. Primary naval command for Persian Gulf ops.'
        },
        'Sheikh Isa Air Base': {
            'location': 'Bahrain',
            'targets': ['bahrain', 'iran'],
            'description': 'Bahrain Air Force base. Coalition air ops.'
        },
        'Diego Garcia': {
            'location': 'British Indian Ocean Territory',
            'targets': ['iran'],
            'description': 'Bomber staging. Deep strike capability vs Iran.'
        },
        'Gulf of Oman': {
            'location': 'Maritime',
            'targets': ['iran'],
            'description': 'Naval presence near Strait of Hormuz.'
        },
        'Persian Gulf': {
            'location': 'Maritime',
            'targets': ['iran'],
            'description': 'Forward naval presence.'
        },
        'Strait of Hormuz': {
            'location': 'Maritime',
            'targets': ['iran'],
            'description': 'Critical oil chokepoint. Maximum tension zone.'
        },
        'Eastern Mediterranean': {
            'location': 'Maritime',
            'targets': ['lebanon', 'syria', 'hezbollah'],
            'description': 'Carrier ops, Tomahawk range to Levant.'
        },
        'Souda Bay': {
            'location': 'Greece (Crete)',
            'targets': ['lebanon', 'syria'],
            'description': 'Naval support hub for Eastern Med ops.'
        },
        'Akrotiri': {
            'location': 'Cyprus (UK)',
            'targets': ['syria', 'lebanon'],
            'description': 'RAF base. Strike and ISR platform.'
        },
        'Al Tanf': {
            'location': 'Syria',
            'targets': ['syria', 'iran', 'iraq'],
            'description': 'US garrison. Syria-Iraq border control.'
        },
        'Al Asad Air Base': {
            'location': 'Iraq (Anbar)',
            'targets': ['iraq', 'syria', 'iran'],
            'description': 'Major US base in western Iraq. Frequent IRI militia target.'
        },
        'Erbil': {
            'location': 'Iraq (Kurdistan)',
            'targets': ['iraq', 'syria', 'iran'],
            'description': 'US forces in northern Iraq / KRG. IRI militia target.'
        },
        # v2.5.0 — new Iraq base entries
        'Taji': {
            'location': 'Iraq (Baghdad)',
            'targets': ['iraq'],
            'description': 'Iraqi military base north of Baghdad. Former Coalition hub.'
        },
        'Balad Air Base': {
            'location': 'Iraq (Saladin)',
            'targets': ['iraq'],
            'description': 'Major Iraqi Air Force base. Former US Joint Base Balad.'
        },
        'Baghdad Green Zone': {
            'location': 'Iraq (Baghdad)',
            'targets': ['iraq'],
            'description': 'International Zone. US Embassy compound. IRI militia rocket target.'
        },
        'Camp Victory': {
            'location': 'Iraq (Baghdad)',
            'targets': ['iraq'],
            'description': 'Former US HQ complex near Baghdad airport.'
        },
        'Qaim Border Crossing': {
            'location': 'Iraq (Anbar)',
            'targets': ['iraq', 'syria'],
            'description': 'Iraq-Syria border. Key smuggling / militia transit corridor.'
        },
        'Muwaffaq Salti (Tower 22)': {
            'location': 'Jordan',
            'targets': ['jordan', 'syria', 'iran'],
            'description': 'US base near Jordan-Syria border. F-15E hub.'
        },
        'Camp Arifjan': {
            'location': 'Kuwait',
            'targets': ['kuwait', 'iran'],
            'description': 'US Army Central forward HQ.'
        },
        'Ali Al Salem Air Base': {
            'location': 'Kuwait',
            'targets': ['kuwait'],
            'description': 'US Air Force operations in Kuwait.'
        },
        'Red Sea': {
            'location': 'Maritime',
            'targets': ['houthis', 'yemen'],
            'description': 'Anti-Houthi naval operations.'
        },
        'Bab el-Mandeb': {
            'location': 'Maritime',
            'targets': ['houthis', 'yemen'],
            'description': 'Critical shipping chokepoint.'
        },
        'Camp Lemonnier': {
            'location': 'Djibouti',
            'targets': ['houthis', 'yemen'],
            'description': 'US Africa Command base. Drone and SOF ops.'
        },
        'Prince Sultan Air Base': {
            'location': 'Saudi Arabia',
            'targets': ['iran', 'saudi_arabia'],
            'description': 'US Air Force presence in Saudi Arabia.'
        },
        'King Abdulaziz Air Base': {
            'location': 'Saudi Arabia (Dhahran)',
            'targets': ['saudi_arabia', 'iran'],
            'description': 'Saudi/coalition air ops. Eastern Province.'
        },
        'Duqm Naval Base': {
            'location': 'Oman',
            'targets': ['oman', 'iran'],
            'description': 'UK/US naval logistics. Indian Ocean access.'
        },
        'Thumrait Air Base': {
            'location': 'Oman',
            'targets': ['oman', 'iran'],
            'description': 'Omani Air Force. Coalition staging.'
        },
        'Masirah Island': {
            'location': 'Oman',
            'targets': ['oman'],
            'description': 'Remote air base. Indian Ocean patrol.'
        },
    },
    'southcom': {
        'Soto Cano Air Base': {
            'location': 'Honduras',
            'targets': ['honduras', 'central_america'],
            'description': 'Joint Task Force Bravo. SOUTHCOM primary air hub for Central America.'
        },
        'Naval Station Guantanamo Bay': {
            'location': 'Cuba',
            'targets': ['cuba', 'caribbean'],
            'description': 'US naval installation on Cuba. Strategic Caribbean presence. Detention facility.'
        },
        'NAS Key West': {
            'location': 'Florida, USA',
            'targets': ['cuba', 'caribbean'],
            'description': 'Naval Air Station Key West. Drug interdiction and Caribbean surveillance hub.'
        },
        'NAVBASE San Diego': {
            'location': 'California, USA',
            'targets': ['pacific', 'western_hemisphere'],
            'description': 'Naval Base San Diego. Third Fleet HQ. Largest US Navy surface fleet homeport.'
        },
        'SOUTHCOM HQ': {
            'location': 'Doral, Florida',
            'targets': ['western_hemisphere'],
            'description': 'US Southern Command headquarters. Covers Central/South America and Caribbean.'
        },
        'Panama Canal': {
            'location': 'Panama',
            'targets': ['panama', 'western_hemisphere'],
            'description': 'Strategic maritime chokepoint. US/international transit rights. Chinese port presence at both ends.'
        },
        'Caribbean Sea': {
            'location': 'Maritime',
            'targets': ['cuba', 'haiti', 'caribbean'],
            'description': 'US Navy drug interdiction and Caribbean security patrols.'
        },
        'Gulf of Mexico': {
            'location': 'Maritime',
            'targets': ['mexico', 'western_hemisphere'],
            'description': 'US Coast Guard and Navy drug interdiction operations.'
        },
        'Manta (former)': {
            'location': 'Ecuador',
            'targets': ['colombia', 'western_hemisphere'],
            'description': 'Former US FOL. Regional ISR staging point for counter-narcotics.'
        },
        'Comalapa Air Base': {
            'location': 'El Salvador',
            'targets': ['central_america', 'western_hemisphere'],
            'description': 'US Forward Operating Location. Drug interdiction ISR platform.'
        },
        'Reina Beatrix (Aruba)': {
            'location': 'Aruba (Netherlands)',
            'targets': ['venezuela', 'caribbean'],
            'description': 'US/Dutch FOL. Venezuela-facing surveillance. Drug interdiction.'
        },
        'Hato Airport (Curacao)': {
            'location': 'Curacao (Netherlands)',
            'targets': ['venezuela', 'caribbean'],
            'description': 'US/Dutch Forward Operating Location. Venezuela monitoring and drug interdiction.'
        },
    },
    'eucom': {
        'Pituffik Space Base (Thule)': {
            'location': 'Greenland (Denmark)',
            'targets': ['greenland', 'arctic'],
            'description': 'US Space Force. Missile early warning. Arctic presence.'
        },
        'Keflavik': {
            'location': 'Iceland',
            'targets': ['arctic', 'north_atlantic'],
            'description': 'NATO Atlantic / Arctic surveillance.'
        },
        'Ramstein Air Base': {
            'location': 'Germany',
            'targets': ['europe', 'nato_general'],
            'description': 'USAFE HQ. European operations hub.'
        },
        'Rota Naval Station': {
            'location': 'Spain',
            'targets': ['mediterranean', 'nato_general'],
            'description': 'US destroyer forward base.'
        },
        'Sigonella': {
            'location': 'Italy (Sicily)',
            'targets': ['mediterranean', 'libya'],
            'description': 'ISR and maritime patrol hub.'
        },
        'Baltic Region': {
            'location': 'Baltic States',
            'targets': ['nato_eastern_flank'],
            'description': 'NATO enhanced forward presence.'
        },
        'Grafenwöhr': {
            'location': 'Germany',
            'targets': ['europe', 'ukraine_support'],
            'description': 'US Army training hub. Ukraine training ops.'
        },
        'Rzeszów': {
            'location': 'Poland',
            'targets': ['ukraine_support', 'poland'],
            'description': 'Key logistics hub for Ukraine aid. Near Ukrainian border.'
        },
        'Mihail Kogălniceanu': {
            'location': 'Romania',
            'targets': ['black_sea', 'nato_eastern_flank'],
            'description': 'US/NATO presence on Black Sea.'
        },
        'Deveselu': {
            'location': 'Romania',
            'targets': ['nato_eastern_flank'],
            'description': 'Aegis Ashore missile defense site.'
        },
        'Redzikowo': {
            'location': 'Poland',
            'targets': ['poland', 'nato_eastern_flank'],
            'description': 'Aegis Ashore missile defense site. NATO BMD.'
        },
        'Łask Air Base': {
            'location': 'Poland',
            'targets': ['poland', 'nato_eastern_flank'],
            'description': 'Polish Air Force base. NATO air policing.'
        },
        'Poznań': {
            'location': 'Poland',
            'targets': ['poland', 'nato_eastern_flank'],
            'description': 'US Army V Corps forward HQ.'
        },
        'Suwalki Gap': {
            'location': 'Poland/Lithuania border',
            'targets': ['poland', 'nato_eastern_flank'],
            'description': 'Critical NATO corridor between Kaliningrad and Belarus.'
        },
        'RAF Akrotiri': {
            'location': 'Cyprus (UK SBA)',
            'targets': ['cyprus', 'syria', 'lebanon'],
            'description': 'UK sovereign base. Strike and ISR. Iran drone target.'
        },
        'Dhekelia': {
            'location': 'Cyprus (UK SBA)',
            'targets': ['cyprus'],
            'description': 'UK sovereign base area. Eastern Cyprus.'
        },
        'Andreas Papandreou Air Base': {
            'location': 'Cyprus (Paphos)',
            'targets': ['cyprus'],
            'description': 'Cypriot/Greek Air Force. Eastern Med.'
        },
        'Souda Bay (NSA Crete)': {
            'location': 'Greece (Crete)',
            'targets': ['greece'],
            'description': 'US Navy / NATO naval support activity + air base. Eastern Med power projection.'
        },
        'Nakhchivan': {
            'location': 'Azerbaijan (exclave)',
            'targets': ['azerbaijan', 'iran'],
            'description': 'Azeri exclave bordering Iran/Turkey. Iranian drone strikes Mar 2026.'
        },
        'Ganja Air Base': {
            'location': 'Azerbaijan',
            'targets': ['azerbaijan'],
            'description': 'Azerbaijani Air Force. Second city military hub.'
        },
        'Gyumri (Russian 102nd Base)': {
            'location': 'Armenia',
            'targets': ['armenia', 'russia'],
            'description': 'Russian military base in Armenia. Status uncertain post-CSTO strain.'
        },
        'Erebuni Air Base': {
            'location': 'Armenia (Yerevan)',
            'targets': ['armenia'],
            'description': 'Armenian Air Force / former Russian aviation base near Yerevan.'
        },
    }
}


# ========================================
# ALERT THRESHOLDS
# ========================================

ALERT_THRESHOLDS = {
    'normal': {
        'min_score': 0,
        'label': 'Normal',
        'color': 'green',
        'icon': '🟢',
        'dashboard_banner': False
    },
    'elevated': {
        'min_score': 10,
        'label': 'Elevated',
        'color': 'yellow',
        'icon': '🟡',
        'dashboard_banner': True
    },
    'high': {
        'min_score': 25,
        'label': 'High',
        'color': 'orange',
        'icon': '🟠',
        'dashboard_banner': True
    },
    'surge': {
        'min_score': 50,
        'label': 'Surge',
        'color': 'red',
        'icon': '🔴',
        'dashboard_banner': True
    }
}

# ========================================
# WAR FOOTING FLOOR SCORES (v3.3) - Redis-backed with decay
# ========================================
# A floor is an ANALYST ASSERTION: "regardless of what this scan found,
# this actor is at war and cannot read as quiet." It is not measured.
#
# Because it is an assertion and not a measurement, it must expire.
# Every floor carries set_at + half_life_days and decays exponentially.
# When the decayed value falls below FLOOR_EXPIRY_THRESHOLD the floor
# stops applying entirely and the actor reads at its measured score.
#
# Floors live in Redis so they can be updated without a redeploy.
# The seed dict below is used ONLY to hydrate an empty Redis key.
#
# Deliberate design decision: floors are NEVER auto-refreshed from
# measured signal. Refreshing an assertion from the same data it exists
# to backstop is circular reasoning. A floor is renewed by a human.
# ========================================

MILITARY_TRACKER_VERSION = '3.13.0'

# Feature flags published in the scan result. These exist so "did my deploy
# land" is one field to read instead of an archaeology exercise on downstream
# numbers. Every one of these was shipped on Sep 7, 2026.
MILITARY_TRACKER_FEATURES = {
    'recency_gate':            True,
    'source_health':           True,
    'floors_redis_decay':      True,   # v3.3
    'floor_endpoints':         True,   # v3.3
    'article_dedupe':          True,   # v3.4
    'event_dedupe':            True,   # v3.4
    'signal_direction':        True,   # v3.5
    'match_text_hygiene':      True,   # v3.6
    'short_keyword_boundary':  True,   # v3.6
    'capability_fingerprint':  True,   # v3.7 - the join
    'loss_noun_cues':          True,   # v3.8 - "attack ON x", "launches AT x"
    'wartime_sustainment':     True,   # v3.9 - battle damage, munitions burn
    'roundup_guard':           True,   # v3.9 - digests are not events
    'financial_burn':          True,   # v3.10 - money is capability
    'neutral_sample':          True,   # v3.10 - read the 85%, stop guessing
    'dynamic_fp_source':       True,   # v3.10 - fingerprint source no longer hardcoded
    'rtl_normalization':       True,   # v3.11 - gershayim, alef forms, diacritics
    'script_detection':        True,   # v3.11 - neutral reasons name the script
    'multilingual_direction':  True,   # v3.11 - HE/AR/FA/RU direction cues
    'alliance_cues':           True,   # v3.11 - capability supplemented by pact
    'source_health_v2':        True,   # v3.12 - why a feed is dead, not just that it is
    'gateway_stats_exposed':   True,   # v3.13 - the breaker is visible at last
}

# Printed at module import so a deploy is verifiable from the boot log
# without waiting out a full scan cycle.
print(f"[Military Tracker] module loaded - version {MILITARY_TRACKER_VERSION} "
      f"({sum(1 for v in MILITARY_TRACKER_FEATURES.values() if v)} features active)")

WAR_FOOTING_FLOOR_REDIS_KEY = 'military:war_footing_floors'
WAR_FOOTING_FLOOR_TTL_SECONDS = 365 * 24 * 3600
DEFAULT_FLOOR_HALF_LIFE_DAYS = 30.0
FLOOR_EXPIRY_THRESHOLD = 3.0

WAR_FOOTING_FLOORS_SEED = {
    'israel':       {'score': 75, 'half_life_days': 30, 'note': 'Active war, mass barrages'},
    'iraq':         {'score': 40, 'half_life_days': 30, 'note': 'IRI militia ops, US bases hit'},
    'kuwait':       {'score': 35, 'half_life_days': 30, 'note': 'Iranian strikes confirmed; US Embassy ordered departure; USAF scrambled'},
    'saudi_arabia': {'score': 35, 'half_life_days': 30, 'note': 'Iranian strikes confirmed; drone shoot-downs; Ukraine technicians deployed'},
    'uae':          {'score': 25, 'half_life_days': 30, 'note': 'Struck; UAE air defense active; flights disrupted'},
    'jordan':       {'score': 25, 'half_life_days': 30, 'note': 'Missiles/drones transiting airspace; intercept operations'},
    'qatar':        {'score': 20, 'half_life_days': 30, 'note': 'Al Udeid on heightened alert; airspace affected'},
    'bahrain':      {'score': 20, 'half_life_days': 30, 'note': '5th Fleet HQ; heightened posture'},
    'turkey':       {'score': 15, 'half_life_days': 30, 'note': 'Incirlik on alert; border tensions'},
    'egypt':        {'score': 10, 'half_life_days': 30, 'note': 'Suez disruption risk; Sinai watch'},
    'oman':         {'score': 15, 'half_life_days': 30, 'note': 'Strait of Hormuz operations'},
    'cyprus':       {'score': 15, 'half_life_days': 30, 'note': 'Akrotiri on alert; evacuation staging'},
}

# Back-compat: some older call sites read WAR_FOOTING_FLOORS as a flat
# {country: score} dict. Keep that name alive as the UNDECAYED asserted
# values. Nothing in the scan path should use it - use get_effective_floors().
WAR_FOOTING_FLOORS = {k: v['score'] for k, v in WAR_FOOTING_FLOORS_SEED.items()}


def _floor_age_days(entry, now=None):
    """Days since this floor was asserted. Returns None if undatable."""
    now = now or datetime.now(timezone.utc)
    raw = entry.get('set_at')
    if not raw:
        return None
    try:
        txt = str(raw).replace('Z', '+00:00')
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    delta = (now - dt).total_seconds() / 86400.0
    return max(0.0, delta)

# ========================================
# DEFENSE MEDIA RSS FEEDS
# ========================================

DEFENSE_RSS_FEEDS = {
    'The War Zone': 'https://www.twz.com/feed',
    'Breaking Defense': 'https://breakingdefense.com/feed/',
    'Defense One': 'https://www.defenseone.com/rss/all/',
    'Naval News': 'https://www.navalnews.com/feed/',
    'Stars and Stripes': 'https://news.google.com/rss/search?q=site:stripes.com+military&hl=en&gl=US&ceid=US:en',
    'Military Times': 'https://www.militarytimes.com/arc/outboundfeeds/rss/?outputType=xml',
    'CENTCOM': 'https://news.google.com/rss/search?q=site:centcom.mil&hl=en&gl=US&ceid=US:en',
    'NATO News': 'https://news.google.com/rss/search?q=site:nato.int+news&hl=en&gl=US&ceid=US:en',
    'DVIDS': 'https://www.dvidshub.net/rss/news',
    'Jerusalem Post': 'https://www.jpost.com/rss/rssfeedsmilitary.aspx',
    'Times of Israel': 'https://news.google.com/rss/search?q=site:timesofisrael.com+military&hl=en&gl=US&ceid=US:en',
    'Ynet News': 'https://www.ynetnews.com/Integration/StoryRss3254.xml',
    'Israel Hayom': 'https://www.israelhayom.com/feed/',
    'Al Jazeera English': 'https://www.aljazeera.com/xml/rss/all.xml',
    'Al Arabiya English': 'https://english.alarabiya.net/tools/rss',
    'Middle East Eye': 'https://www.middleeasteye.net/rss',
    'TASS Defense': 'https://tass.com/rss/v2.xml',
    'Moscow Times': 'https://www.themoscowtimes.com/rss/news',
    'Daily Sabah': 'https://www.dailysabah.com/rssFeed/defense',
    'TRT World': 'https://www.trtworld.com/rss',
    'Kyiv Independent': 'https://kyivindependent.com/feed/',
    'Ukrinform': 'https://www.ukrinform.net/rss/block-lastnews',
    'Iran International': 'https://www.iranintl.com/en/feed',
    'Tasnim English': 'https://news.google.com/rss/search?q=site:tasnimnews.com+military&hl=en&gl=US&ceid=US:en',
    # v2.3.0 additions — Poland & Arctic
    'Defence24 Poland': 'https://defence24.com/rss',
    'Polish Press Agency': 'https://www.pap.pl/en/rss.xml',
    'Arctic Today': 'https://news.google.com/rss/search?q=site:arctictoday.com&hl=en&gl=US&ceid=US:en',
    'High North News': 'https://news.google.com/rss/search?q=site:highnorthnews.com+arctic&hl=en&gl=US&ceid=US:en',
    # v2.5.0 additions — Iraq
    'Iraq News (Google)': 'https://news.google.com/rss/search?q=iraq+military+OR+militia+OR+ISIS&hl=en&gl=US&ceid=US:en',
    'Rudaw English': 'https://news.google.com/rss/search?q=site:rudaw.net+military&hl=en&gl=US&ceid=US:en',
    'Kurdistan24': 'https://news.google.com/rss/search?q=site:kurdistan24.net+military&hl=en&gl=US&ceid=US:en',
    # v2.6.0 — Bahrain
    'Bahrain News (Google)': 'https://news.google.com/rss/search?q=bahrain+military+OR+fifth+fleet+OR+naval&hl=en&gl=US&ceid=US:en',
    # v2.8.0 — Naval movement tracking
    'USNI News': 'https://news.usni.org/feed',
    'USNI Fleet': 'https://news.google.com/rss/search?q=site:news.usni.org+fleet+OR+deployed+OR+carrier&hl=en&gl=US&ceid=US:en',
    'TWZ Naval': 'https://news.google.com/rss/search?q=site:twz.com+navy+OR+carrier+OR+fleet+OR+ship&hl=en&gl=US&ceid=US:en',
    'NavalNews Movements': 'https://news.google.com/rss/search?q=site:navalnews.com+deployed+OR+transit+OR+arrives+OR+departs&hl=en&gl=US&ceid=US:en',
    'USNI Proceedings': 'https://news.google.com/rss/search?q=site:usni.org+navy+deployment+OR+fleet+OR+carrier&hl=en&gl=US&ceid=US:en',
    # v2.7.0 — War footing: all Gulf + regional actors
    'Kuwait Military (Google)': 'https://news.google.com/rss/search?q=kuwait+military+OR+missile+OR+attack+OR+troops&hl=en&gl=US&ceid=US:en',
    'Saudi Military (Google)': 'https://news.google.com/rss/search?q=saudi+arabia+military+OR+missile+OR+attack+OR+defense&hl=en&gl=US&ceid=US:en',
    'UAE Military (Google)': 'https://news.google.com/rss/search?q=UAE+OR+dubai+OR+abu+dhabi+military+OR+missile+OR+attack&hl=en&gl=US&ceid=US:en',
    'Jordan Military (Google)': 'https://news.google.com/rss/search?q=jordan+military+OR+intercept+OR+missile+OR+airspace&hl=en&gl=US&ceid=US:en',
    'Qatar Military (Google)': 'https://news.google.com/rss/search?q=qatar+OR+al+udeid+military+OR+missile+OR+attack+OR+flights&hl=en&gl=US&ceid=US:en',
    'Oman Military (Google)': 'https://news.google.com/rss/search?q=oman+military+OR+muscat+OR+duqm+OR+strait+hormuz&hl=en&gl=US&ceid=US:en',
    'Egypt Military (Google)': 'https://news.google.com/rss/search?q=egypt+military+OR+suez+OR+sinai+OR+defense&hl=en&gl=US&ceid=US:en',
    'Turkey Military (Google)': 'https://news.google.com/rss/search?q=turkey+military+OR+incirlik+OR+erdogan+defense+OR+attack&hl=en&gl=US&ceid=US:en',
    'Cyprus Military (Google)': 'https://news.google.com/rss/search?q=cyprus+military+OR+akrotiri+OR+attack+OR+evacuation&hl=en&gl=US&ceid=US:en',
    # v3.0.0 additions — Western Hemisphere
    'Venezuela Military (Google)': 'https://news.google.com/rss/search?q=venezuela+military+OR+maduro+transition+OR+colectivos+armed&hl=en&gl=US&ceid=US:en',
    'Cuba Military (Google)': 'https://news.google.com/rss/search?q=cuba+military+OR+russia+cuba+OR+china+cuba+spy+base&hl=en&gl=US&ceid=US:en',
    'Haiti Security (Google)': 'https://news.google.com/rss/search?q=haiti+gang+mss+mission+OR+kenya+haiti+OR+viv+ansanm+security&hl=en&gl=US&ceid=US:en',
    'Panama Canal (Google)': 'https://news.google.com/rss/search?q=panama+canal+military+OR+china+panama+canal+OR+canal+sovereignty&hl=en&gl=US&ceid=US:en',
    'Colombia Military (Google)': 'https://news.google.com/rss/search?q=colombia+eln+military+OR+farc+dissident+OR+colombia+army+operation&hl=en&gl=US&ceid=US:en',
    'Mexico Cartel Military (Google)': 'https://news.google.com/rss/search?q=mexico+cartel+military+OR+cjng+attack+OR+sinaloa+cartel+army&hl=en&gl=US&ceid=US:en',
    'Brazil Military (Google)': 'https://news.google.com/rss/search?q=brazil+military+OR+amazon+military+OR+brazil+armed+forces&hl=en&gl=US&ceid=US:en',
    'SOUTHCOM (Google)': 'https://news.google.com/rss/search?q=southcom+military+OR+us+southern+command+OR+operation+martillo&hl=en&gl=US&ceid=US:en',
}

REDDIT_MILITARY_SUBREDDITS = [
    'CredibleDefense', 'LessCredibleDefence', 'geopolitics',
    'Military', 'WarCollege', 'navy', 'AirForce',
    'NCD', 'DefenseNews'
]

REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ========================================
# UPSTASH REDIS CACHE (v2.4.0)
# Persistent across Render deploys/cold starts
# Same pattern as Iran and Lebanon modules
# ========================================

# ========================================
# CROSS-TRACKER FINGERPRINT CONTRACT (v3.1.0 — May 2026)
# ========================================
# Writes per-country, per-theatre, per-chokepoint, and cross-actor
# military fingerprints to Upstash Redis so other systems (rhetoric
# trackers, GPI, country stability pages) can read live military
# context without re-scanning.
#
# Fingerprint key namespace:
#   military:{country}:posture            13h TTL
#   military:{country}:asset_distribution 13h TTL
#   military:theatre:{theatre_id}         13h TTL
#   military:chokepoint:{name}            13h TTL
#   military:evacuation:{country}         13h TTL  (only when active)
#   military:cross:{label}                13h TTL  (only when active)
#
# All fingerprints carry a 'scanned_at' timestamp + a 'source' string built
# from MILITARY_TRACKER_VERSION (v3.10; it was hardcoded to v3.1 until then)
# so consumers can age-out stale data.
#
# This is an ADDITIVE upgrade — does not change existing /api/military-posture
# response shape, scoring engine, or signal aggregation logic.

FINGERPRINT_TTL_SECONDS = 13 * 3600   # 13h — outlasts 12h scan refresh + 1h buffer

# ── ASSET POSITION TTL (May 22 2026 — Naval Asset Visibility expansion) ──
# Naval assets move slowly between news pops. A ship spotted in San Diego
# Monday may not appear in news again until Pacific Thursday. We keep
# asset-position fingerprints alive for a full week to trace movement
# across slow news cycles. Political/threat signals still expire at 13h.
ASSET_POSITION_TTL_SECONDS = 168 * 3600   # 7 days — captures multi-day asset movement
ASSET_MOVEMENT_HISTORY_TTL_SECONDS = 30 * 24 * 3600   # 30 days — for movement-trail Redis lists
ASSET_MOVEMENT_HISTORY_MAX_ENTRIES = 50   # Cap stored position history per named ship

# Chokepoint mapping — translates LOCATION_MULTIPLIERS hits into chokepoint
# fingerprints. Each chokepoint accumulates signal_count + score from any
# article where the matched_location resolves to one of its keywords.
#
# Reused values: 'hormuz', 'bab_el_mandeb', 'taiwan_strait', 'panama_canal',
# 'malacca', 'bosporus', 'gibraltar', 'suez', 'baltic', 'arctic', 'magellan'.
CHOKEPOINT_LOCATION_MAP = {
    'hormuz':         ['strait of hormuz', 'hormuz', 'persian gulf', 'bandar abbas',
                       'hormuz mining', 'mining strait of hormuz', 'hormuz mine threat',
                       'hormuz blockade', 'hormuz closed'],
    'bab_el_mandeb':  ['bab el-mandeb', 'bab al-mandab', 'bab al-mandeb', 'mandeb',
                       'red sea', 'gulf of aden', 'aden gulf'],
    'suez':           ['suez canal', 'suez', 'egyptian canal'],
    'taiwan_strait':  ['taiwan strait', 'taiwan straits', 'kinmen', 'matsu',
                       'taipei', 'penghu'],
    'south_china_sea':['south china sea', 'spratly', 'paracel', 'scarborough shoal',
                       'second thomas shoal', 'philippine sea'],
    'malacca':        ['malacca strait', 'strait of malacca', 'malacca'],
    'sunda_strait':   ['sunda strait', 'lombok strait', 'indonesian archipelago transit'],
    'bosporus':       ['bosporus', 'bosphorus', 'turkish straits', 'dardanelles'],
    'gibraltar':      ['gibraltar', 'strait of gibraltar', 'rock of gibraltar'],
    'sicily_strait':  ['strait of sicily', 'sicilian channel', 'pantelleria', 'lampedusa'],
    'panama_canal':   ['panama canal', 'miraflores', 'colon', 'gatun'],
    'magellan':       ['strait of magellan', 'magellan', 'punta arenas', 'tierra del fuego'],
    'baltic':         ['baltic sea', 'kaliningrad', 'gulf of finland', 'gotland'],
    'arctic':         ['arctic', 'svalbard', 'barents sea', 'beaufort sea',
                       'greenland sea', 'thule', 'pituffik'],
    'bering_strait':  ['bering strait', 'bering sea', 'diomede islands', 'chukchi sea'],
    'black_sea':      ['black sea', 'sevastopol', 'crimea naval', 'odesa naval', 'odessa naval'],
    'mediterranean':  ['eastern mediterranean', 'levantine', 'cyprus naval', 'haifa naval',
                       'sicily', 'aegean'],
    'caribbean':      ['caribbean sea', 'gulf of mexico', 'gtmo', 'guantanamo', 'cuba naval',
                       'florida straits', 'bahamas naval'],
}

# Reverse-lookup: location-keyword → chokepoint_id (built once at import time)
_LOCATION_TO_CHOKEPOINT = {}
for _cp_id, _kws in CHOKEPOINT_LOCATION_MAP.items():
    for _kw in _kws:
        _LOCATION_TO_CHOKEPOINT[_kw.lower()] = _cp_id

# ────────────────────────────────────────────────────────────────────
# CHOKEPOINT-SPECIFIC ALERT THRESHOLDS (v3.1.1 — May 2026)
# ────────────────────────────────────────────────────────────────────
# Why separate from the country-level ALERT_THRESHOLDS (10/25/50):
# A chokepoint is a different signal class than a country. Country
# scoring accumulates 20+ asset categories over a 7-day window and
# needs higher thresholds. Chokepoints have lower baseline noise but
# step-change criticality — a single "Iran mining Hormuz" signal is
# materially worse than 20 routine patrol reports.
#
# Bands match the bimodal real-world impact pattern:
#   open       → routine traffic, minor patrol activity
#   monitored  → elevated patrols, named-actor presence, normal exercises
#   contested  → active confrontations, mining threats, anti-ship signals,
#                  high transit risk
#   disrupted  → kinetic events, blockade signals, traffic rerouting,
#                  insurance war-risk listings
#
CHOKEPOINT_THRESHOLDS = {
    'open':       {'min_score': 0,    'label': 'Open',       'icon': '🟢'},
    'monitored':  {'min_score': 5,    'label': 'Monitored',  'icon': '🟡'},
    'contested':  {'min_score': 12,   'label': 'Contested',  'icon': '🟠'},
    'disrupted':  {'min_score': 25,   'label': 'Disrupted',  'icon': '🔴'},
}

# Critical-event multipliers — these signal types have outsized impact
# at chokepoints relative to country-level scoring. A Houthi anti-ship
# missile fired at a Bab el-Mandeb transit is materially worse than the
# same signal type at country-level. Multipliers stack with the existing
# weight (so a 4.0-weighted signal at 2.5x = 10.0 chokepoint contribution).
CHOKEPOINT_CRITICAL_KEYWORDS = {
    # Mining — THE signal that closes a strait. Extreme multiplier.
    'mining':              3.0,    # 'mining', 'mine threat', 'naval mine'
    'mine_threat':         3.0,
    'naval_mine':          3.0,

    # Direct kinetic events on commercial shipping
    'anti-ship missile':   2.5,
    'anti-ship attack':    2.5,
    'vessel struck':       3.0,
    'ship attacked':       2.5,
    'tanker attacked':     2.8,
    'tanker struck':       2.8,
    'commercial vessel hit': 2.8,

    # Blockade / closure signals
    'blockade':            2.5,
    'closed to traffic':   3.0,
    'closed to commercial': 3.0,
    'closed to shipping':  3.0,
    'transit closed':      3.0,
    'traffic suspended':   2.5,
    'transit suspended':   2.5,
    'shipping halt':       2.5,
    'strait closed':       3.0,

    # Rerouting tells (the "supply chain has already given up" signal)
    'cape of good hope':   2.0,    # rerouting from BAM/Suez
    'rerouting':           2.0,
    'avoiding':            1.8,    # 'shippers avoiding red sea'

    # Insurance war-risk premium (Lloyd's JWC signal)
    'war risk':            2.2,
    'jwc listed':          2.5,    # Lloyd's Joint War Committee
    'joint war committee': 2.5,
    'insurance premium':   1.8,

    # Convoy escort (sustained-but-managed escalation)
    'convoy escort':       1.8,
    'escorted transit':    1.8,
    'naval escort':        1.5,

    # Specific high-criticality events
    'seized vessel':       2.5,
    'vessel boarded':      2.2,
    'hijacked':            2.5,
    'detained vessel':     2.0,
}

# Chokepoint convergence pairs — when two chokepoints hit 'contested+'
# simultaneously, that's a coupled-disruption signal worth its own
# fingerprint. Same pattern as cross-actor amplifiers but for chokepoints.
#
# Each entry: chokepoint_pair → coupling rationale
CHOKEPOINT_CONVERGENCE_PAIRS = {
    'hormuz_bam':          {
        'chokepoints':  ['hormuz', 'bab_el_mandeb'],
        'min_level':    'contested',
        'rationale':    'Iran-coupled — IRGC at Hormuz + Houthi proxies at BAM. '
                        'Simultaneous contestation = supply-chain black swan.',
    },
    'bam_suez':            {
        'chokepoints':  ['bab_el_mandeb', 'suez'],
        'min_level':    'contested',
        'rationale':    'Mediterranean-Red Sea trade artery. Both contested = '
                        'Cape of Good Hope rerouting at scale.',
    },
    'taiwan_scs':          {
        'chokepoints':  ['taiwan_strait', 'south_china_sea'],
        'min_level':    'contested',
        'rationale':    'China-coupled maritime perimeter. Joint pressure = '
                        'INDOPACOM regional escalation.',
    },
    'bosporus_black_sea':  {
        'chokepoints':  ['bosporus', 'black_sea'],
        'min_level':    'contested',
        'rationale':    'Russia-Ukraine grain corridor + Turkish straits. '
                        'Joint disruption = NATO Article-V watch.',
    },
    'panama_magellan':     {
        'chokepoints':  ['panama_canal', 'magellan'],
        'min_level':    'contested',
        'rationale':    'Western Hemisphere maritime — only matters when '
                        'Panama disrupted (Magellan is the failover).',
    },
    'malacca_sunda':       {
        'chokepoints':  ['malacca', 'sunda_strait'],
        'min_level':    'contested',
        'rationale':    'Southeast Asian maritime — Indonesia archipelago '
                        'failover when Malacca contested.',
    },
}


def determine_chokepoint_alert(score):
    """Convert raw chokepoint score to chokepoint-specific alert level.
    Distinct from country-level determine_alert_level() — uses lower bands
    appropriate to the chokepoint signal class."""
    if score >= CHOKEPOINT_THRESHOLDS['disrupted']['min_score']:
        return 'disrupted'
    if score >= CHOKEPOINT_THRESHOLDS['contested']['min_score']:
        return 'contested'
    if score >= CHOKEPOINT_THRESHOLDS['monitored']['min_score']:
        return 'monitored'
    return 'open'


# Numeric rank for chokepoint level comparison (used in convergence detection)
CHOKEPOINT_LEVEL_RANK = {'open': 0, 'monitored': 1, 'contested': 2, 'disrupted': 3}


def _apply_chokepoint_critical_multiplier(signal):
    """Inspect a signal's article title/text for chokepoint critical-event keywords.
    Returns the multiplier to apply (1.0 if none match, else max matching multiplier).
    Multiple matches → uses highest single multiplier (not stacked) so we don't
    double-count e.g. 'tanker attacked' + 'anti-ship attack' on the same article."""
    text = ((signal.get('article_title') or '') + ' ' +
            (signal.get('asset_label') or '')).lower()
    max_mult = 1.0
    for kw, mult in CHOKEPOINT_CRITICAL_KEYWORDS.items():
        if kw in text and mult > max_mult:
            max_mult = mult
    return max_mult

# Cross-actor amplifier definitions — when these actor-pair combinations are
# both at elevated+ alert level, write a `military:cross:{label}` fingerprint
# so downstream consumers (rhetoric trackers, GPI) can detect correlated
# escalation across actors.
CROSS_AMPLIFIER_PAIRS = {
    'nato_us_active':       {'actors': ['us', 'nato'],            'min_level': 'elevated'},
    'china_taiwan_active':  {'actors': ['china', 'taiwan'],       'min_level': 'elevated'},
    'russia_ukraine_active':{'actors': ['russia', 'ukraine'],     'min_level': 'elevated'},
    'iran_proxy_active':    {'actors': ['iran'],                  'min_level': 'high',
                             'requires_evac_anywhere': True},
    'us_venezuela_active':  {'actors': ['us', 'venezuela'],       'min_level': 'elevated'},
    'us_cuba_active':       {'actors': ['us', 'cuba'],            'min_level': 'elevated'},
    'us_panama_active':     {'actors': ['us', 'panama'],          'min_level': 'elevated'},
    'us_greenland_active':  {'actors': ['us', 'greenland'],       'min_level': 'elevated'},
    'israel_uae_defense':   {'actors': ['israel', 'uae'],          'min_level': 'elevated'},
}

LEVEL_RANK = {'normal': 0, 'elevated': 1, 'high': 2, 'surge': 3}


def _redis_fp_set(key, payload, ttl_seconds=FINGERPRINT_TTL_SECONDS):
    """Write a fingerprint to Upstash Redis with TTL. Adds scanned_at + source.
    Returns True on success, False on any error (silent — never crashes scan)."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        if isinstance(payload, dict):
            payload = dict(payload)
            payload.setdefault('scanned_at', datetime.now(timezone.utc).isoformat())
            payload.setdefault(
                'source', f'military_tracker_v{MILITARY_TRACKER_VERSION}')
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_seconds)}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(payload, default=str),
            timeout=8,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Military Fingerprint] Redis write error ({key}): {str(e)[:120]}")
        return False


def _redis_fp_get(key):
    """Read a fingerprint. Returns dict on success, None on miss/error."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        body = resp.json()
        if body.get('result'):
            return json.loads(body['result'])
    except Exception:
        pass
    return None


def _floor_half_life(entry):
    """Half-life in days for one floor entry. 0 means do not decay.
    Missing/blank falls back to the default; junk falls back to the default."""
    raw = entry.get('half_life_days')
    if raw is None or raw == '':
        return DEFAULT_FLOOR_HALF_LIFE_DAYS
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_FLOOR_HALF_LIFE_DAYS


def _decayed_floor_value(entry, now=None):
    """Exponential half-life decay of an asserted floor.
    Returns (effective_score, age_days_or_None).
    An entry with no usable set_at does not decay - it is treated as
    freshly asserted rather than silently zeroed."""
    try:
        asserted = float(entry.get('score') or 0)
    except (TypeError, ValueError):
        asserted = 0.0
    if asserted <= 0:
        return 0.0, _floor_age_days(entry, now)

    age = _floor_age_days(entry, now)
    if age is None:
        return asserted, None

    half_life = _floor_half_life(entry)
    if half_life <= 0:
        # half_life_days = 0 means "permanent assertion, do not decay"
        return asserted, age

    return asserted * (0.5 ** (age / half_life)), age


def _seed_floor_entries():
    """Build a fresh Redis payload from the static seed.
    The original assertion dates are unknown, so the clock honestly starts
    at hydration time and the provenance note says so."""
    stamp = datetime.now(timezone.utc).isoformat()
    out = {}
    for country, cfg in WAR_FOOTING_FLOORS_SEED.items():
        out[country] = {
            'score': float(cfg['score']),
            'half_life_days': float(cfg.get('half_life_days', DEFAULT_FLOOR_HALF_LIFE_DAYS)),
            'note': cfg.get('note', ''),
            'set_at': stamp,
            'source': 'seed_hydration',
            'provenance': 'Seeded from static code defaults. Original assertion date is unknown, so the decay clock starts at hydration.',
        }
    return out


def load_war_footing_floors():
    """Read floors from Redis. Hydrate from the seed if the key is empty
    or Redis is unreachable. Always returns a dict of entries."""
    stored = _redis_fp_get(WAR_FOOTING_FLOOR_REDIS_KEY)
    if isinstance(stored, dict) and stored:
        clean = {k: v for k, v in stored.items() if isinstance(v, dict)}
        if clean:
            return clean
    seeded = _seed_floor_entries()
    ok = _redis_fp_set(WAR_FOOTING_FLOOR_REDIS_KEY, seeded, WAR_FOOTING_FLOOR_TTL_SECONDS)
    print(f"[Military Tracker] War footing floors hydrated from seed "
          f"({len(seeded)} entries, redis_write={ok})")
    return seeded


def get_effective_floors(now=None):
    """Returns (effective, ledger).
      effective : {country: decayed_score} for floors still above threshold
      ledger    : full audit trail for every floor, expired ones included
    """
    now = now or datetime.now(timezone.utc)
    entries = load_war_footing_floors()
    effective = {}
    ledger = {}
    for country, entry in entries.items():
        value, age = _decayed_floor_value(entry, now)
        expired = value < FLOOR_EXPIRY_THRESHOLD
        ledger[country] = {
            'asserted_score': round(float(entry.get('score') or 0), 2),
            'effective_score': round(value, 2),
            'age_days': None if age is None else round(age, 1),
            'half_life_days': _floor_half_life(entry),
            'set_at': entry.get('set_at'),
            'expired': expired,
            'note': entry.get('note', ''),
            'source': entry.get('source', ''),
        }
        if not expired:
            effective[country] = value
    return effective, ledger


def set_war_footing_floor(country, score, half_life_days=None, note='', source='manual'):
    """Assert or renew a single floor. Restamps set_at, restarting decay."""
    entries = load_war_footing_floors()
    key = (country or '').strip().lower().replace(' ', '_')
    if not key:
        return None
    try:
        score = float(score)
    except (TypeError, ValueError):
        return None

    if score <= 0:
        entries.pop(key, None)
    else:
        entries[key] = {
            'score': score,
            'half_life_days': _floor_half_life({'half_life_days': half_life_days}),
            'note': note or '',
            'set_at': datetime.now(timezone.utc).isoformat(),
            'source': source,
        }
    _redis_fp_set(WAR_FOOTING_FLOOR_REDIS_KEY, entries, WAR_FOOTING_FLOOR_TTL_SECONDS)
    return entries.get(key)


def _classify_signal_asset_class(signal):
    """Map a signal's asset_type to broad asset classes for fingerprint distribution.
    Returns one of: 'naval', 'air', 'missile', 'ground', 'cyber', 'evacuation', 'other'.
    """
    asset_type = (signal.get('asset_type') or '').lower()
    asset_label = (signal.get('asset_label') or '').lower()
    combined = asset_type + ' ' + asset_label

    # Order matters — most specific first
    if 'evac' in combined or 'neo' in combined or 'drawdown' in combined:
        return 'evacuation'
    if any(t in combined for t in ['carrier', 'naval', 'destroyer', 'frigate', 'submarine',
                                    'amphib', 'minesweep', 'lcs', 'flagship']):
        return 'naval'
    if any(t in combined for t in ['missile', 'ballistic', 'cruise', 'hypersonic',
                                    'thaad', 'patriot', 'iron dome', 'aegis', 'sm-6', 'sm-3']):
        return 'missile'
    if any(t in combined for t in ['air', 'aircraft', 'b-52', 'b-2', 'b-21', 'f-22', 'f-35',
                                    'f-16', 'aegis ashore', 'fighter', 'bomber', 'tanker']):
        return 'air'
    if any(t in combined for t in ['cyber', 'cybersec', 'malware', 'apt']):
        return 'cyber'
    if any(t in combined for t in ['ground', 'troop', 'brigade', 'division', 'battalion',
                                    'tank', 'armor', 'infantry', 'special forces', 'sof']):
        return 'ground'
    return 'other'


def _extract_chokepoint_signals(all_signals):
    """Aggregate signals by chokepoint based on each signal's matched location.
    Applies CHOKEPOINT_CRITICAL_KEYWORDS multipliers to weight signals appropriately
    for chokepoint scoring (mining, anti-ship, blockade, rerouting, etc.).
    Returns dict {chokepoint_id: {signal_count, weighted_score, top_signals[],
    critical_signal_count}}.

    NOTE: Signals carry the location metadata under 'hotspot_location' (the
    convention established by analyze_article_military()). Earlier versions
    of this function read 'matched_location' which silently produced zero
    matches — fixed in v3.2.1.
    """
    chokepoint_data = {}
    for sig in all_signals or []:
        loc = (sig.get('hotspot_location') or sig.get('matched_location') or '').lower()
        if not loc:
            continue
        cp_id = _LOCATION_TO_CHOKEPOINT.get(loc)
        if not cp_id:
            # Try substring match (multi-word locations sometimes don't exact-match)
            for kw, cp in _LOCATION_TO_CHOKEPOINT.items():
                if kw in loc:
                    cp_id = cp
                    break
        if not cp_id:
            continue

        # Apply chokepoint-specific critical-event multiplier
        base_weight = float(sig.get('weight', 0))
        cp_multiplier = _apply_chokepoint_critical_multiplier(sig)
        adjusted_weight = base_weight * cp_multiplier

        if cp_id not in chokepoint_data:
            chokepoint_data[cp_id] = {
                'signal_count':         0,
                'weighted_score':       0.0,
                'critical_signal_count': 0,    # signals that triggered a multiplier
                'top_signals':          [],
            }
        chokepoint_data[cp_id]['signal_count'] += 1
        chokepoint_data[cp_id]['weighted_score'] += adjusted_weight
        if cp_multiplier > 1.0:
            chokepoint_data[cp_id]['critical_signal_count'] += 1
        if len(chokepoint_data[cp_id]['top_signals']) < 5:
            chokepoint_data[cp_id]['top_signals'].append({
                'title':       sig.get('article_title', '')[:200],
                'url':         sig.get('article_url', ''),
                'source':      sig.get('source', ''),
                'actor':       sig.get('actor_name', ''),
                'base_weight': base_weight,
                'multiplier':  round(cp_multiplier, 2),
                'final_weight': round(adjusted_weight, 2),
            })
    return chokepoint_data


def _compute_asset_distribution_for_actor(actor_id, all_signals):
    """Per-actor asset class distribution based on its scored signals."""
    counts = {'naval': 0, 'air': 0, 'missile': 0, 'ground': 0,
              'cyber': 0, 'evacuation': 0, 'other': 0}
    weighted = {k: 0.0 for k in counts}
    for sig in all_signals or []:
        if sig.get('actor') != actor_id:
            continue
        cls = _classify_signal_asset_class(sig)
        counts[cls] += 1
        weighted[cls] += float(sig.get('weight', 0))
    return {'counts': counts, 'weighted': {k: round(v, 2) for k, v in weighted.items()}}


# ════════════════════════════════════════════════════════════════════════
# ASSET MOVEMENT HISTORY (May 22 2026)
# ────────────────────────────────────────────────────────────────────────
# Named US Navy ships (USS Nimitz, USS Ford, etc.) tend to surface
# in news at irregular intervals — Monday at San Diego, Thursday in the
# Pacific. To trace their movement, we:
#   (a) Write their current position as a 168h-TTL fingerprint so the
#       location persists even if news goes quiet for a week
#   (b) Append each new position to a per-ship Redis LIST capped at 50
#       entries with a 30-day TTL — provides movement-trail history
#
# Frontend can read these lists later to draw movement arrows on the
# naval-asset map, or surface "USS Nimitz: Pacific → Caribbean (3 days)"
# style signals in the so-what synthesis.
# ════════════════════════════════════════════════════════════════════════

# Named US Navy ships pattern: "uss <something>" + optional ship designation.
# Matches "USS Nimitz", "USS Gerald R. Ford", "USS Carl Vinson", etc.
import re as _re
_NAMED_SHIP_PATTERN = _re.compile(r'\b(uss\s+[a-z][a-z\.\s]{2,40}?)(?=\s+(?:carrier|csg|departed|departs|return|returns|enters?|exits?|left|arrived|arrives|in|near|at|off|conducts|will|to|patrol|deployed|deploys|transit|sail|sails|underway|home)|[\,\.\;])', _re.IGNORECASE)


def _extract_named_ships(text):
    """Extract named US Navy ships from signal text. Returns list of canonical names."""
    if not text:
        return []
    text_lower = text.lower()
    matches = _NAMED_SHIP_PATTERN.findall(text_lower)
    # Canonicalize: "uss nimitz" → "uss_nimitz" for Redis key
    canonical = []
    for m in matches:
        # Clean trailing whitespace + punctuation, collapse internal spaces
        clean = ' '.join(m.split()).strip(' .,;')
        if 4 <= len(clean) <= 50:  # Sanity bounds
            canonical.append(clean)
    return list(set(canonical))  # Dedupe


def _redis_list_lpush_trim(key, value, max_entries, ttl_seconds):
    """LPUSH a value to a Redis list, trim to max_entries, set TTL.
    Returns True on success.
    """
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        # LPUSH
        url = f"{UPSTASH_REDIS_URL}/lpush/{key}/{value}"
        resp = requests.post(
            url,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=4,
        )
        if resp.status_code != 200:
            return False
        # LTRIM 0 max-1 (keeps newest max_entries)
        url_trim = f"{UPSTASH_REDIS_URL}/ltrim/{key}/0/{max_entries - 1}"
        requests.post(
            url_trim,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=4,
        )
        # EXPIRE
        url_exp = f"{UPSTASH_REDIS_URL}/expire/{key}/{ttl_seconds}"
        requests.post(
            url_exp,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=4,
        )
        return True
    except Exception:
        return False


def _write_asset_movement_history(all_signals):
    """For each signal naming a specific US Navy ship AND with a hotspot location,
    write:
      (a) military:asset:{ship_id}:position fingerprint (168h TTL)
      (b) Append to military:asset:{ship_id}:positions Redis list (30d TTL, max 50)

    Returns (position_write_count, movement_append_count).
    """
    if not all_signals:
        return (0, 0)

    position_count = 0
    movement_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build a deduped map: ship_id → most recent (location, weight, signal)
    ship_latest = {}
    for sig in all_signals:
        text = (sig.get('article_title') or '') + ' ' + (sig.get('signal_text') or '')
        ships = _extract_named_ships(text)
        location = sig.get('hotspot_location')
        if not ships or not location:
            continue
        for ship in ships:
            ship_id = ship.replace(' ', '_').replace('.', '').lower()
            # Keep highest-weight signal per ship per scan
            current = ship_latest.get(ship_id)
            if not current or (sig.get('weight', 0) > current.get('weight', 0)):
                ship_latest[ship_id] = {
                    'ship_name':       ship.title(),
                    'location':        location,
                    'weight':          sig.get('weight', 0),
                    'asset_class':     sig.get('asset', ''),
                    'article_title':   sig.get('article_title', ''),
                    'article_url':     sig.get('article_url', ''),
                    'last_seen':       now_iso,
                }

    # Now write each ship's position + movement history
    for ship_id, data in ship_latest.items():
        # (a) Position fingerprint with extended TTL
        pos_key = f"military:asset:{ship_id}:position"
        if _redis_fp_set(pos_key, data, ttl_seconds=ASSET_POSITION_TTL_SECONDS):
            position_count += 1

        # (b) Movement-history Redis list (LPUSH + LTRIM + EXPIRE)
        history_key = f"military:asset:{ship_id}:positions"
        history_entry = json.dumps({
            'location':      data['location'],
            'asset_class':   data['asset_class'],
            'seen_at':       data['last_seen'],
            'article_title': data['article_title'][:150],
        })
        # URL-encode the JSON for Upstash REST API
        from urllib.parse import quote
        encoded = quote(history_entry, safe='')
        if _redis_list_lpush_trim(history_key, encoded,
                                  ASSET_MOVEMENT_HISTORY_MAX_ENTRIES,
                                  ASSET_MOVEMENT_HISTORY_TTL_SECONDS):
            movement_count += 1

    if position_count > 0 or movement_count > 0:
        print(f"[Military Fingerprints] Asset movement tracking: "
              f"{position_count} position fingerprints, "
              f"{movement_count} movement-history appends "
              f"across {len(ship_latest)} named ships")
    return (position_count, movement_count)


# ════════════════════════════════════════════════════════════════════════
# HUMANITARIAN-PANDEMIC CONVERGENCE DETECTOR (May 22 2026)
# ────────────────────────────────────────────────────────────────────────
# Detects when US hospital ship deployment co-occurs with pandemic/disease
# signals in the same theater or region. This is a high-fidelity analytical
# signal — the US committing a strategic 1,000-bed hospital ship indicates
# recognition of severe humanitarian crisis.
#
# Pattern: hospital_ship signal + pandemic_keyword signal within same scan +
#          overlapping geographic context = convergence fires.
#
# Writes a fingerprint: military:humanitarian_convergence:{region} with TTL
# matching general fingerprints. Interpreter reads this to surface the
# analytical signal in prose.
# ════════════════════════════════════════════════════════════════════════

# Keywords that indicate active pandemic/disease emergency (not just routine)
_PANDEMIC_KEYWORDS = [
    'ebola outbreak', 'ebola surge', 'ebola cases rising',
    'ebola sudan', 'ebola drc', 'ebola uganda', 'ebola response',
    'marburg outbreak', 'marburg virus', 'marburg cases',
    'lassa fever outbreak', 'mpox outbreak', 'mpox cases surge',
    'cholera outbreak africa', 'cholera surge',
    'who declares emergency', 'who pheic',
    'public health emergency international concern',
    'biosurveillance', 'cdc deployment',
]


def _detect_humanitarian_convergence(all_signals):
    """Scan all signals for hospital-ship + pandemic co-occurrence patterns.

    Returns a list of convergence dicts:
        [
          {
            'region':                'africa' | 'asia_pacific' | 'middle_east' | 'wha',
            'hospital_ship_signals': [signal_dict, ...],
            'pandemic_signals':      [signal_dict, ...],
            'severity':              'elevated' | 'high' | 'surge',
            'hospital_ship_name':    'USNS Mercy' | 'USNS Comfort' | 'Unknown',
            'rationale':             'Why this fires',
          },
          ...
        ]

    Fires only when BOTH signal types appear in the same scan. Severity scales
    with signal volume and weight.
    """
    if not all_signals:
        return []

    # Bucket 1: hospital-ship signals (any with asset == 'hospital_ship')
    hospital_signals = [s for s in all_signals
                        if s.get('asset') == 'hospital_ship']

    if not hospital_signals:
        return []  # No hospital ship activity — no convergence possible

    # Bucket 2: pandemic-relevant signals (text matches a pandemic keyword)
    pandemic_signals = []
    for sig in all_signals:
        text = ((sig.get('article_title') or '') + ' ' +
                (sig.get('signal_text') or '')).lower()
        if not text.strip():
            continue
        for kw in _PANDEMIC_KEYWORDS:
            if kw in text:
                # Tag the matching keyword on the signal for downstream prose
                sig_copy = dict(sig)
                sig_copy['_pandemic_keyword'] = kw
                pandemic_signals.append(sig_copy)
                break

    if not pandemic_signals:
        return []  # Hospital ship but no pandemic → not the convergence we're after

    # Convergence DETECTED. Now characterize it.
    # ── Identify which ship ──
    ship_text = ' '.join(((s.get('article_title') or '') + ' ' +
                          (s.get('signal_text') or '')).lower()
                         for s in hospital_signals)
    if 'mercy' in ship_text and 'comfort' not in ship_text:
        ship_name = 'USNS Mercy'
    elif 'comfort' in ship_text and 'mercy' not in ship_text:
        ship_name = 'USNS Comfort'
    elif 'mercy' in ship_text and 'comfort' in ship_text:
        ship_name = 'USNS Mercy + USNS Comfort'
    else:
        ship_name = 'US hospital ship (unspecified)'

    # ── Determine region from signal locations ──
    # Try to bucket by hotspot_location
    AFRICA_HOTSPOTS = ['mogadishu', 'goma', 'khartoum', 'el fasher', 'tripoli',
                       'lagos', 'abuja', 'addis ababa', 'kinshasa', 'bangui',
                       'manda bay', 'camp lemonnier', 'djibouti', 'cabo delgado',
                       'south sudan', 'uganda', 'kampala']
    region_votes = {}
    for sig in hospital_signals + pandemic_signals:
        loc = (sig.get('hotspot_location') or '').lower()
        text = ((sig.get('article_title') or '') + ' ' +
                (sig.get('signal_text') or '')).lower()
        for african_hp in AFRICA_HOTSPOTS:
            if african_hp in loc or african_hp in text:
                region_votes['africa'] = region_votes.get('africa', 0) + 1
                break
        else:
            # Check pandemic keyword for region hint
            for kw in ['ebola sudan', 'ebola drc', 'ebola uganda', 'cholera outbreak africa']:
                if kw in text:
                    region_votes['africa'] = region_votes.get('africa', 0) + 1
                    break

    region = max(region_votes, key=region_votes.get) if region_votes else 'unknown'

    # ── Severity scoring ──
    # surge: 2+ hospital signals AND 3+ pandemic signals
    # high:  1+ hospital AND 2+ pandemic
    # elevated: 1 hospital + 1 pandemic
    h_count = len(hospital_signals)
    p_count = len(pandemic_signals)
    total_weight = (sum(s.get('weight', 0) for s in hospital_signals) +
                    sum(s.get('weight', 0) for s in pandemic_signals))
    if h_count >= 2 and p_count >= 3:
        severity = 'surge'
    elif h_count >= 1 and p_count >= 2:
        severity = 'high'
    else:
        severity = 'elevated'

    # ── Build rationale ──
    pandemic_kw_summary = list(set(s.get('_pandemic_keyword', '') for s in pandemic_signals))
    rationale = (
        f"{ship_name} deployment co-occurs with {p_count} pandemic/disease signal(s) "
        f"in {region.replace('_', ' ').title()}. "
        f"Pandemic keywords detected: {', '.join(pandemic_kw_summary[:5])}. "
        f"US committing strategic humanitarian asset to active health emergency — "
        f"signals official recognition of crisis severity."
    )

    convergence = {
        'region':                region,
        'hospital_ship_name':    ship_name,
        'hospital_signal_count': h_count,
        'pandemic_signal_count': p_count,
        'total_signal_weight':   round(total_weight, 2),
        'severity':              severity,
        'pandemic_keywords':     pandemic_kw_summary,
        'rationale':             rationale,
        'top_hospital_signal':   hospital_signals[0] if hospital_signals else None,
        'top_pandemic_signal':   pandemic_signals[0] if pandemic_signals else None,
    }

    return [convergence]


def _write_military_fingerprints(scan_result, all_signals):
    """Write all fingerprint types to Redis based on the scan result.
    This is called once per successful _run_full_scan().

    Failure of any individual write does NOT abort the scan — fingerprints
    are best-effort metadata; the scan result itself is the source of truth.
    """
    written = {'posture': 0, 'asset_distribution': 0, 'theatre': 0,
               'chokepoint': 0, 'evacuation': 0, 'cross': 0}
    try:
        target_postures   = scan_result.get('target_postures', {}) or {}
        actor_summaries   = scan_result.get('actor_summaries', {}) or {}
        theatre_groupings = scan_result.get('theatre_groupings', {}) or {}
        evac_alerts       = scan_result.get('evacuation_alerts', []) or []

        # ── 1. Per-country posture fingerprints ──
        # Write for each target that has a posture entry, keyed by lowercase country id.
        for target_id, posture in target_postures.items():
            if not isinstance(posture, dict):
                continue
            payload = {
                'country':       target_id,
                'alert_level':   posture.get('alert_level', 'normal'),
                'alert_label':   posture.get('alert_label', 'Normal'),
                'score':         round(float(posture.get('score', 0)), 2),
                'show_banner':   posture.get('show_banner', False),
                'top_signals':   posture.get('top_signals', [])[:3],
                'tension_multi': posture.get('tension_multiplier', 1.0),
                'evac_active':   any(e.get('actor', '').lower() == target_id.lower() or
                                     target_id.lower() in (e.get('title', '') or '').lower()
                                     for e in evac_alerts),
            }
            if _redis_fp_set(f"military:{target_id}:posture", payload):
                written['posture'] += 1

        # ── 2. Per-actor asset-distribution fingerprints ──
        for actor_id in actor_summaries.keys():
            distribution = _compute_asset_distribution_for_actor(actor_id, all_signals)
            payload = {
                'country':      actor_id,
                'alert_level':  actor_summaries[actor_id].get('alert_level', 'normal'),
                'distribution': distribution,
                'signal_count': actor_summaries[actor_id].get('signal_count', 0),
            }
            if _redis_fp_set(f"military:{actor_id}:asset_distribution", payload):
                written['asset_distribution'] += 1

        # ── 3. Per-theatre fingerprints ──
        for theatre_id, theatre in theatre_groupings.items():
            if not isinstance(theatre, dict):
                continue
            actors_in_theatre = list(theatre.get('actors', {}).keys())
            active_actors = [a for a in actors_in_theatre
                             if (theatre.get('actors', {}).get(a, {}) or {})
                                .get('alert_level', 'normal') in ('elevated', 'high', 'surge')]
            payload = {
                'theatre':         theatre_id,
                'label':           theatre.get('label', ''),
                'alert_level':     theatre.get('alert_level', 'normal'),
                'total_score':     round(float(theatre.get('total_score', 0)), 2),
                'all_actors':      actors_in_theatre,
                'active_actors':   active_actors,
                'active_count':    len(active_actors),
            }
            if _redis_fp_set(f"military:theatre:{theatre_id}", payload):
                written['theatre'] += 1

        # ── 4. Chokepoint fingerprints ──
        chokepoint_data = _extract_chokepoint_signals(all_signals)
        chokepoint_levels = {}   # used for convergence detection in step 7
        for cp_id, cp_info in chokepoint_data.items():
            score = cp_info['weighted_score']
            cp_alert = determine_chokepoint_alert(score)    # chokepoint-specific bands
            chokepoint_levels[cp_id] = cp_alert
            payload = {
                'chokepoint':            cp_id,
                'alert_level':           cp_alert,
                'alert_label':           CHOKEPOINT_THRESHOLDS[cp_alert]['label'],
                'alert_icon':            CHOKEPOINT_THRESHOLDS[cp_alert]['icon'],
                'signal_count':          cp_info['signal_count'],
                'critical_signal_count': cp_info.get('critical_signal_count', 0),
                'score':                 round(score, 2),
                'top_signals':           cp_info['top_signals'],
            }
            if _redis_fp_set(f"military:chokepoint:{cp_id}", payload):
                written['chokepoint'] += 1

        # ── 5. Evacuation fingerprints (only when evac signal exists) ──
        # Group evac alerts by country/actor so a single country surface
        # gets one fingerprint listing all its evac signals.
        evac_by_country = {}
        for evac in evac_alerts:
            actor_name = (evac.get('actor') or '').lower().strip()
            if not actor_name:
                continue
            # Try to map actor_name → country_id (the actor field is a
            # display name like 'United States' — map it to actor_id like 'us')
            country_id = None
            for aid, asum in actor_summaries.items():
                if asum.get('name', '').lower() == actor_name or aid == actor_name:
                    country_id = aid
                    break
            if not country_id:
                # fallback — use the lowercase actor name itself
                country_id = actor_name.replace(' ', '_')
            evac_by_country.setdefault(country_id, []).append(evac)

        for country_id, country_evacs in evac_by_country.items():
            payload = {
                'country':       country_id,
                'active':        True,
                'evac_count':    len(country_evacs),
                'top_evac':      country_evacs[0] if country_evacs else None,
                'all_evacs':     country_evacs[:5],
                'subtypes':      list({e.get('subtype', 'unspecified') for e in country_evacs}),
            }
            if _redis_fp_set(f"military:evacuation:{country_id}", payload):
                written['evacuation'] += 1

        # ── 6. Cross-actor amplifier fingerprints ──
        for label, criteria in CROSS_AMPLIFIER_PAIRS.items():
            required_actors = criteria.get('actors', [])
            min_level = criteria.get('min_level', 'elevated')
            min_rank = LEVEL_RANK.get(min_level, 1)
            requires_evac = criteria.get('requires_evac_anywhere', False)

            # All required actors must be at min_level or higher
            all_active = True
            actor_levels = {}
            for required_id in required_actors:
                a = actor_summaries.get(required_id, {})
                lvl = a.get('alert_level', 'normal')
                actor_levels[required_id] = lvl
                if LEVEL_RANK.get(lvl, 0) < min_rank:
                    all_active = False
                    break

            if not all_active:
                continue

            if requires_evac and not evac_alerts:
                continue

            payload = {
                'label':         label,
                'active':        True,
                'level':         min(actor_levels.values(),
                                     key=lambda l: LEVEL_RANK.get(l, 0)),
                'actor_levels':  actor_levels,
                'evac_present':  bool(evac_alerts),
            }
            if _redis_fp_set(f"military:cross:{label}", payload):
                written['cross'] += 1

        # ── 7. Chokepoint convergence fingerprints ──
        # When two chokepoints in a defined pair both hit 'contested+' simultaneously,
        # write a convergence fingerprint. This is the "supply-chain black swan" signal.
        written['chokepoint_convergence'] = 0
        for label, criteria in CHOKEPOINT_CONVERGENCE_PAIRS.items():
            required_cps = criteria.get('chokepoints', [])
            min_level = criteria.get('min_level', 'contested')
            min_rank = CHOKEPOINT_LEVEL_RANK.get(min_level, 2)

            # Both chokepoints must be at min_level or higher
            all_active = True
            cp_levels_in_pair = {}
            for cp_id in required_cps:
                lvl = chokepoint_levels.get(cp_id, 'open')
                cp_levels_in_pair[cp_id] = lvl
                if CHOKEPOINT_LEVEL_RANK.get(lvl, 0) < min_rank:
                    all_active = False
                    break

            if not all_active:
                continue

            # Lowest of the two levels = the convergence level
            convergence_level = min(cp_levels_in_pair.values(),
                                     key=lambda l: CHOKEPOINT_LEVEL_RANK.get(l, 0))
            payload = {
                'label':              label,
                'active':             True,
                'level':              convergence_level,
                'chokepoint_levels':  cp_levels_in_pair,
                'rationale':          criteria.get('rationale', ''),
            }
            if _redis_fp_set(f"military:chokepoint_convergence:{label}", payload):
                written['chokepoint_convergence'] += 1

        # ── 8. Asset-position fingerprints + movement history ─────────
        # (May 22 2026 — Naval Asset Visibility expansion)
        # For each signal that names a specific ship (USS Nimitz, USS Ford, etc.)
        # and has a hotspot_location, write:
        #   (a) Position fingerprint with 168h TTL (catches ship across multiple
        #       news cycles even if news goes quiet for days)
        #   (b) Append to per-asset movement-history Redis list (30-day window,
        #       max 50 entries) so we can trace the ship's path over time
        written['asset_position'] = 0
        written['asset_movement'] = 0
        try:
            asset_position_count, movement_append_count = _write_asset_movement_history(all_signals)
            written['asset_position'] = asset_position_count
            written['asset_movement'] = movement_append_count
        except Exception as e:
            print(f"[Military Fingerprints] Asset movement write error: {str(e)[:200]}")

        # ── 9. Humanitarian-pandemic convergence (May 22 2026) ──
        # Detects US hospital ship + pandemic disease co-occurrence.
        # Fires only when both signals present — surfaces the convergence
        # to the interpreter prose layer for analytical voice.
        written['humanitarian_convergence'] = 0
        try:
            convergences = _detect_humanitarian_convergence(all_signals)
            for conv in convergences:
                region = conv.get('region', 'unknown')
                if _redis_fp_set(f"military:humanitarian_convergence:{region}", conv):
                    written['humanitarian_convergence'] += 1
                    print(f"[Military Fingerprints] ⚕️ Humanitarian convergence detected: "
                          f"{conv.get('hospital_ship_name')} + pandemic in {region} "
                          f"(severity: {conv.get('severity')})")
            # Also attach convergences to scan_result so interpreter can read them
            scan_result['humanitarian_convergences'] = convergences
        except Exception as e:
            print(f"[Military Fingerprints] Humanitarian convergence error: {str(e)[:200]}")

        total = sum(written.values())
        print(f"[Military Fingerprints] ✅ Wrote {total} fingerprints — "
              f"posture:{written['posture']} asset:{written['asset_distribution']} "
              f"theatre:{written['theatre']} chokepoint:{written['chokepoint']} "
              f"evac:{written['evacuation']} cross:{written['cross']} "
              f"convergence:{written['chokepoint_convergence']} "
              f"asset_position:{written.get('asset_position', 0)} "
              f"asset_movement:{written.get('asset_movement', 0)}")
        return written

    except Exception as e:
        print(f"[Military Fingerprints] Error during fingerprint write: {str(e)[:200]}")
        import traceback
        traceback.print_exc()
        return written


# ========================================
# REDIS PERSISTENT CACHE (existing)
# ========================================

MILITARY_REDIS_KEY = 'military_tracker_cache'


def load_military_cache():
    """Load cached military tracker data from Upstash Redis, fallback to /tmp"""
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{MILITARY_REDIS_KEY}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get("result"):
                cache = json.loads(data["result"])
                print(f"[Military Cache] Loaded from Redis (cached_at: {cache.get('cached_at', 'unknown')})")
                return cache
            print("[Military Cache] No existing cache in Redis")
        except Exception as e:
            print(f"[Military Cache] Redis load error: {e}")

    try:
        from pathlib import Path
        if Path(MILITARY_CACHE_FILE).exists():
            with open(MILITARY_CACHE_FILE, 'r') as f:
                cache = json.load(f)
                print("[Military Cache] Loaded from /tmp fallback")
                return cache
    except Exception as e:
        print(f"[Military Cache] /tmp load error: {e}")

    return {}


def save_military_cache(data):
    """Save military tracker data to Upstash Redis + /tmp fallback"""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()

    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            payload = json.dumps(data, default=str)
            resp = requests.post(
                f"{UPSTASH_REDIS_URL}/set/{MILITARY_REDIS_KEY}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                data=payload,
                timeout=10
            )
            if resp.status_code == 200:
                print("[Military Cache] ✅ Saved to Redis")
            else:
                print(f"[Military Cache] Redis save HTTP {resp.status_code}")
        except Exception as e:
            print(f"[Military Cache] Redis save error: {e}")

    try:
        with open(MILITARY_CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        print("[Military Cache] Saved /tmp fallback")
    except Exception as e:
        print(f"[Military Cache] /tmp save error: {e}")


def is_military_cache_fresh():
    """Check if military cache is still valid"""
    try:
        cache = load_military_cache()
        if not cache or 'cached_at' not in cache:
            return False
        cached_at = datetime.fromisoformat(cache['cached_at'])
        age = datetime.now(timezone.utc) - cached_at
        is_fresh = age.total_seconds() < (MILITARY_CACHE_TTL_HOURS * 3600)
        if is_fresh:
            age_min = age.total_seconds() / 60
            print(f"[Military Cache] Fresh ({age_min:.0f}min old)")
        return is_fresh
    except:
        return False


def _build_empty_skeleton():
    """Return a valid but empty military posture response."""
    actor_summaries = {}
    for actor_id, actor_data in MILITARY_ACTORS.items():
        actor_summaries[actor_id] = {
            'name': actor_data.get('name', actor_id),
            'flag': actor_data.get('flag', ''),
            'tier': actor_data.get('tier', 99),
            'theatre': actor_data.get('theatre', 'unknown'),
            'total_score': 0,
            'signal_count': 0,
            'top_signals': [],
            'alert_level': 'normal'
        }

    theatre_data = {}
    for theatre_id, theatre_info in REGIONAL_THEATRES.items():
        theatre_actors = {}
        for actor_id in theatre_info['actors']:
            if actor_id in actor_summaries:
                theatre_actors[actor_id] = actor_summaries[actor_id]
        theatre_data[theatre_id] = {
            'label': theatre_info['label'],
            'icon': theatre_info['icon'],
            'order': theatre_info['order'],
            'description': theatre_info['description'],
            'actors': theatre_actors,
            'total_score': 0,
            'alert_level': 'normal'
        }

    return {
        'success': True,
        'scan_time_seconds': 0,
        'days_analyzed': 7,
        'total_articles_scanned': 0,
        'total_signals_detected': 0,
        'active_actors': [],
        'active_actor_count': 0,
        'tension_multiplier': 1.0,
        'target_postures': {},
        'actor_summaries': actor_summaries,
        'theatre_groupings': theatre_data,
        'asset_distribution': {},
        'evacuation_alerts': [],
        'top_signals': [],
        'source_breakdown': {
            'defense_rss': 0,
            'gdelt': 0,
            'newsapi': 0,
            'reddit': 0
        },
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'cached': False,
        'scan_in_progress': True,
        'message': 'Initial scan in progress. Data will appear shortly.',
        # This payload is what /api/military-posture serves in the window
        # between a cold start and the first completed scan - which is exactly
        # when someone is checking whether a deploy landed. Reporting a frozen
        # '3.0.0' here would answer that question wrong at the only moment it
        # is being asked.
        'version': MILITARY_TRACKER_VERSION
    }


# ========================================
# DATA FETCHING — RSS FEEDS
# ========================================

# =====================================================================
# SOURCE HEALTH INSTRUMENTATION (v3.12, Sep 19 2026)
# =====================================================================
# The previous source_health was {name: 'ok' if count > 0 else 'ZERO'}. It
# told us a feed was dead and never why. Underneath it every fetcher threw
# its status code away:
#     fetch_brave_military    -> except Exception: return []
#     fetch_newsapi_military  -> except: return []
#     fetch_reddit_military   -> except Exception: continue
# so a 403, a spent quota, a soft block and a query matching nothing were
# indistinguishable from outside the function. The three feeds reporting ZERO
# on Sep 19 are exactly the three with silent catch-all handlers.
#
# This records the outcome of every attempt. It changes nothing about what is
# fetched or how anything is scored, and ships deliberately AHEAD of any
# attempt to revive a feed, so the corpus stays comparable across the change.

# Sources this tracker is supposed to have. A name listed here that never
# appears in _SOURCE_HEALTH is reported as 'not_attempted' rather than
# vanishing from the payload.
EXPECTED_SOURCES = ('defense_rss', 'gdelt', 'newsapi', 'reddit',
                    'telegram', 'brave', 'bluesky')

_SOURCE_HEALTH = {}


def _health_reset():
    """Clear per-scan health records. Called once at the top of a scan."""
    global _SOURCE_HEALTH
    _SOURCE_HEALTH = {}


def _health_note(source, configured=True, http_status=None, error=None,
                 articles=0, duration_ms=None, note=None, blocked=False):
    """Record one fetch attempt. Many attempts aggregate into one source."""
    rec = _SOURCE_HEALTH.setdefault(source, {
        'configured':    configured,
        'attempts':      0,
        'articles':      0,
        'http_statuses': {},
        'errors':        [],
        'notes':         [],
        'duration_ms':   0,
        'blocked':       False,
    })
    rec['configured'] = configured
    if blocked:
        rec['blocked'] = True
    rec['attempts'] += 1
    rec['articles'] += int(articles or 0)
    if http_status is not None:
        key = str(http_status)
        rec['http_statuses'][key] = rec['http_statuses'].get(key, 0) + 1
    if error and len(rec['errors']) < 3:
        rec['errors'].append(str(error)[:160])
    if note and note not in rec['notes']:
        rec['notes'].append(str(note)[:120])
    if duration_ms:
        rec['duration_ms'] += int(duration_ms)


def _health_status(rec):
    """One word for what happened. The point is that 'we could not reach it'
    and 'we reached it and asked the wrong question' stop looking the same."""
    if not rec.get('configured'):
        return 'not_configured'
    if rec.get('attempts', 0) == 0:
        # Never called. Brave sits behind a (gdelt + newsapi) < 10 gate, so a
        # healthy GDELT silently disables it and the old field said 'ZERO'.
        return 'not_attempted'
    if rec.get('blocked'):
        # v3.13 - the call was made and refused BEFORE the network, by our
        # own gateway's circuit breaker. Previously indistinguishable from
        # 'reached it, got nothing', which made 457 GDELT attempts on
        # Sep 19 completely unreadable from the payload.
        return 'blocked_by_gateway'
    statuses = rec.get('http_statuses') or {}
    if any(s in statuses for s in ('401', '403')):
        return 'auth_failed'
    if '402' in statuses:
        # Brave answers a spent plan with 402 Payment Required, not 429.
        # v3.12 filed that under the meaningless 'http_error'.
        return 'quota_exceeded'
    if '429' in statuses:
        return 'rate_limited'
    non_ok = [s for s in statuses if s not in ('200', 'None')]
    if non_ok:
        # A source still delivering articles is not broken. defense_rss
        # read 'http_error' in v3.12 while returning 695 articles, because
        # one feed out of dozens answered 202.
        return 'degraded' if rec.get('articles', 0) > 0 else 'http_error'
    if rec.get('errors'):
        return 'error'
    if rec.get('articles', 0) > 0:
        return 'ok'
    return 'reachable_but_empty'


def _health_report(expected=EXPECTED_SOURCES):
    """Per-source health for the scan payload."""
    out = {}
    for name in set(list(_SOURCE_HEALTH.keys()) + list(expected)):
        rec = _SOURCE_HEALTH.get(name) or {
            'configured': True, 'attempts': 0, 'articles': 0,
            'http_statuses': {}, 'errors': [], 'notes': [], 'duration_ms': 0,
            'blocked': False,
        }
        out[name] = {
            'status':        _health_status(rec),
            'blocked':       rec.get('blocked', False),
            'configured':    rec['configured'],
            'attempts':      rec['attempts'],
            'articles':      rec['articles'],
            'http_statuses': rec['http_statuses'],
            'duration_ms':   rec['duration_ms'],
            'error':         (rec['errors'][0] if rec['errors'] else None),
            'notes':         rec['notes'],
        }
    return out


def fetch_defense_rss(feed_name, feed_url, max_articles=15):
    """Fetch articles from a defense media RSS feed"""
    articles = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Military RSS] {feed_name}: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:max_articles]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            desc_elem = item.find('description')
            content_elem = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')

            if title_elem is None or link_elem is None:
                continue

            pub_date = ''
            if pubDate_elem is not None and pubDate_elem.text:
                try:
                    pub_date = parsedate_to_datetime(pubDate_elem.text).isoformat()
                except:
                    pub_date = datetime.now(timezone.utc).isoformat()

            description = ''
            if desc_elem is not None and desc_elem.text:
                description = desc_elem.text[:500]
            elif content_elem is not None and content_elem.text:
                description = content_elem.text[:500]

            articles.append({
                'title': title_elem.text or '',
                'description': description,
                'url': link_elem.text or '',
                'publishedAt': pub_date,
                'source': {'name': feed_name},
                'content': description,
                'feed_type': 'defense_rss'
            })

        print(f"[Military RSS] {feed_name}: ✓ {len(articles)} articles")
        return articles

    except ET.ParseError as e:
        print(f"[Military RSS] {feed_name}: XML parse error: {str(e)[:100]}")
        return []
    except Exception as e:
        print(f"[Military RSS] {feed_name}: Error: {str(e)[:100]}")
        return []


# ========================================
# DATA FETCHING -- NITTER (Twitter/X OSINT)
# ========================================

NITTER_MIRRORS = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

# Priority accounts for military tracker
# (account, weight, description)
NITTER_ACCOUNTS_MILITARY = [
    ("CENTCOM",          1.2, "US Central Command -- ME/South Asia ops"),
    ("INDOPACOM",        1.1, "US Indo-Pacific Command -- China/Taiwan/Korea"),
    ("EUCOM",            1.0, "US European Command -- Russia/Ukraine/NATO"),
    ("USNavy",           1.1, "US Navy -- CSG deployments, naval movements"),
    ("SecDef",           1.1, "Secretary of Defense -- policy, posture"),
    ("DeptofDefense",    1.0, "DoD -- official statements, deployments"),
    ("IDF",              1.1, "Israel Defense Forces -- strikes, posture"),
    ("AvichayAdraee",    1.0, "IDF Arabic spokesman -- ME escalation"),
    ("StateDept",        1.0, "State Dept -- diplomatic signals, ceasefire"),
    ("realDonaldTrump",  1.1, "Trump -- Iran ceasefire, military policy"),
    ("OSINTdefender",    0.9, "OSINT Defender -- incident reports"),
    ("ElintNews",        0.9, "ELINT News -- military incidents"),
    ("WarMonitors",      0.85,"War Monitors -- strike reports"),
    ("RALee85",          0.85,"Rob Lee -- Russia/Ukraine military analysis"),
]


def _fetch_nitter_account(username, weight=1.0, timeout=8):
    """Fetch RSS from a single Nitter account, trying mirrors in order."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AsifahAnalytics/1.0)"}
    for mirror in NITTER_MIRRORS:
        url = f"https://{mirror}/{username}/rss"
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                continue
            import xml.etree.ElementTree as _ET
            from email.utils import parsedate_to_datetime as _ptd
            root = _ET.fromstring(resp.content)
            posts = []
            for item in root.findall(".//item")[:20]:
                title_el   = item.find("title")
                link_el    = item.find("link")
                pubdate_el = item.find("pubDate")
                if title_el is None:
                    continue
                title = title_el.text or ""
                link  = link_el.text  if link_el  is not None else ""
                pub   = ""
                if pubdate_el is not None and pubdate_el.text:
                    try:
                        pub = _ptd(pubdate_el.text).isoformat()
                    except Exception:
                        pub = pubdate_el.text
                posts.append({
                    'title':       title,
                    'description': title,
                    'url':         link,
                    'publishedAt': pub,
                    'source':      {'name': f'Nitter @{username}'},
                    'content':     title,
                    'feed_type':   'nitter',
                    'weight':      weight,
                })
            if posts:
                print(f"[Military/Nitter] @{username}: {len(posts)} posts via {mirror}")
                return posts
        except Exception as e:
            print(f"[Military/Nitter] @{username} {mirror} failed: {str(e)[:60]}")
            continue
    print(f"[Military/Nitter] @{username}: all mirrors failed")
    return []


def fetch_nitter_military(days=7):
    """Fetch posts from all military OSINT Nitter accounts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen = set()
    for username, weight, desc in NITTER_ACCOUNTS_MILITARY:
        posts = _fetch_nitter_account(username, weight=weight)
        for p in posts:
            if p["url"] in seen:
                continue
            try:
                pub = datetime.fromisoformat(p["publishedAt"].replace("Z", "+00:00"))
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
            except Exception:
                pass
            seen.add(p["url"])
            all_posts.append(p)
        time.sleep(0.3)
    print(f"[Military/Nitter] Total: {len(all_posts)} posts from {len(NITTER_ACCOUNTS_MILITARY)} accounts")
    return all_posts


# ========================================
# DATA FETCHING — BlueSky (global-scope aggregator)
# ========================================
# Added May 6 2026. Replaces Nitter (which has been chronically failing).
# Pulls posts from accounts marked with '*' target scope across the regional
# bluesky_signals_* modules. These are the global-relevance accounts:
# POTUS, SecDef, SecState, INDOPACOM, OSINT Defender, WarTranslated, etc.
#
# Pattern: Option A — reuse existing per-theater modules rather than building
# a parallel military-specific account list. Each module already exposes its
# globally-relevant accounts via the '*' scope flag.

def fetch_bluesky_military_aggregated(days=7):
    """Aggregate BlueSky posts from global-scoped ('*') accounts across all
    regional bluesky_signals_* modules. Returns list of article dicts ready
    for downstream military signal analysis.
    Non-fatal: any module that fails to import is silently skipped."""
    all_posts = []
    seen_urls = set()

    # ── Asia module ──
    try:
        from bluesky_signals_asia import fetch_bluesky_for_target as fetch_asia
        # 'china' is just a target key — accounts marked '*' will return
        # regardless of which target we pass. Theatre-specific accounts
        # (PLA Primer, etc.) are still pulled but they're high-signal anyway.
        asia_posts = fetch_asia('china', days=days, max_posts_per_account=15)
        for p in asia_posts:
            url = p.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                p['feed_type'] = 'bluesky'
                all_posts.append(p)
    except Exception as e:
        print(f"[Military BlueSky] Asia module error (non-fatal): {str(e)[:100]}")

    # ── Middle East module ──
    try:
        from bluesky_signals_me import fetch_bluesky_for_target as fetch_me
        me_posts = fetch_me('iran', days=days, max_posts_per_account=15)
        for p in me_posts:
            url = p.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                p['feed_type'] = 'bluesky'
                all_posts.append(p)
    except Exception as e:
        print(f"[Military BlueSky] ME module error (non-fatal): {str(e)[:100]}")

    # ── Western Hemisphere module ──
    try:
        from bluesky_signals_wha import fetch_bluesky_for_target as fetch_wha
        wha_posts = fetch_wha('cuba', days=days, max_posts_per_account=15)
        for p in wha_posts:
            url = p.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                p['feed_type'] = 'bluesky'
                all_posts.append(p)
    except Exception as e:
        print(f"[Military BlueSky] WHA module error (non-fatal): {str(e)[:100]}")

    print(f"[Military BlueSky] Total aggregated posts: {len(all_posts)}")
    return all_posts


def fetch_all_defense_rss():
    """Fetch articles from all configured defense RSS feeds"""
    all_articles = []
    for feed_name, feed_url in DEFENSE_RSS_FEEDS.items():
        articles = fetch_defense_rss(feed_name, feed_url)
        all_articles.extend(articles)
        time.sleep(0.5)
    print(f"[Military RSS] Total defense RSS articles: {len(all_articles)}")
    return all_articles


# ========================================
# DATA FETCHING — GDELT
# ========================================

# ── Shared GDELT gateway (Jul 24 2026) ────────────────────────────────
# Standing rule: route every GDELT caller through the shared gateway
# (one serialised, paced lane per process with its own circuit breaker
# and response cache). Original direct call preserved as the fallback.
try:
    from gdelt_gateway import gdelt_fetch as _gw_gdelt_fetch
    try:
        from gdelt_gateway import gateway_stats as _gw_gdelt_stats
    except ImportError:
        _gw_gdelt_stats = None      # gateway older than v2.0
    _GDELT_GATEWAY = True
except ImportError:
    print("[Military GDELT] gdelt_gateway not available -- using direct GDELT calls")
    _GDELT_GATEWAY = False
    _gw_gdelt_stats = None


def fetch_gdelt_military(query, days=7, language='eng'):
    """Fetch military-related articles from GDELT"""
    if _GDELT_GATEWAY:
        # Adapt the gateway's canonical shape into this file's own dialect
        # (source is a DICT, publishedAt, content, feed_type='gdelt').
        _t0 = time.time()
        raw = _gw_gdelt_fetch(query, language=language, timespan=f'{days}d',
                              maxrecords=50, label=f'military/{language}')
        # v3.13 - ask the breaker what it did instead of inferring from an
        # empty list. An open circuit means this call never reached the
        # network at all, which is a gateway fault and not a GDELT outage.
        _gw_state = {}
        if _gw_gdelt_stats:
            try:
                _gw_state = _gw_gdelt_stats() or {}
            except Exception:
                _gw_state = {}
        _gw_blocked = bool(_gw_state.get('circuit_open'))
        _health_note('gdelt', articles=len(raw or []),
                     http_status=None if (_gw_blocked or not raw) else 200,
                     duration_ms=(time.time() - _t0) * 1000,
                     blocked=_gw_blocked,
                     note=('gateway circuit OPEN (%ss remaining) - request '
                           'never reached GDELT'
                           % _gw_state.get('circuit_remaining_sec', '?'))
                          if _gw_blocked else
                          'routed through shared GDELT gateway')
        return [{
            'title':       a.get('title', ''),
            'description': a.get('title', ''),
            'url':         a.get('url', ''),
            'publishedAt': a.get('published', ''),
            'source':      {'name': a.get('source') or 'GDELT'},
            'content':     a.get('title', ''),
            'feed_type':   'gdelt'
        } for a in raw]
    try:
        params = {
            'query': query,
            'mode': 'artlist',
            'maxrecords': 50,
            'timespan': f'{days}d',
            'format': 'json',
            'sourcelang': language
        }
        response = None
        for attempt in range(2):
            try:
                response = requests.get(GDELT_BASE_URL, params=params, timeout=60)
                if response.status_code == 200:
                    break
            except requests.Timeout:
                if attempt == 0:
                    time.sleep(2)
                    continue
                raise
        if not response or response.status_code != 200:
            _health_note('gdelt',
                         http_status=(response.status_code if response else None),
                         note='no response' if not response else None)
            return []

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            # 200 OK carrying HTML is GDELT's soft block. Neither an outage
            # nor a query problem, and it needs its own label.
            _health_note('gdelt', http_status=200,
                         note='HTTP 200 with non-JSON body (soft block)')
            return []
        articles = data.get('articles', [])

        standardized = []
        for article in articles:
            standardized.append({
                'title': article.get('title', ''),
                'description': article.get('title', ''),
                'url': article.get('url', ''),
                'publishedAt': article.get('seendate', ''),
                'source': {'name': article.get('domain', 'GDELT')},
                'content': article.get('title', ''),
                'feed_type': 'gdelt'
            })
        _health_note('gdelt', http_status=200, articles=len(standardized))
        return standardized

    except Exception as e:
        print(f"[Military GDELT] Error: {str(e)[:100]}")
        _health_note('gdelt', error=e)
        return []


def fetch_all_gdelt_military(days=7):
    """Fetch military articles from GDELT across multiple queries and languages."""

    english_queries = [
        # --- Naval movements (v2.8.0) ---
        'US navy ship redeployed pacific gulf',
        'carrier strike group transiting repositioned',
        'minesweeper navy middle east pacific',
        'fifth fleet seventh fleet naval movement',
        'navy warship departs arrives gulf',
        # --- CENTCOM / Middle East ---
        'military deployment middle east',
        'carrier strike group persian gulf',
        'military exercise middle east',
        'troops deployed middle east',
        'naval deployment mediterranean',
        'irgc military exercise',
        'iran strait hormuz drill',
        'chinese warship persian gulf',
        'russian navy mediterranean',
        'military base evacuation middle east',
        'embassy evacuation middle east',
        'voluntary departure military',
        'military families evacuation',
        'ordered departure embassy',
        'noncombatant evacuation operation',
        # --- Israel / IDF ---
        'IDF military operation',
        'Israel defense forces deployment',
        'Israel military buildup',
        'Israel reservists mobilization',
        'Iron Dome deployment',
        'Israeli airstrike',
        'Israel Hezbollah military',
        'IDF northern command',
        # --- Gulf States ---
        'jordan military base',
        'qatar al udeid',
        'saudi military exercise',
        'uae military',
        'kuwait camp arifjan',
        'egypt military exercise',
        'egypt sinai troops',
        # --- Turkey ---
        'turkish military operation syria',
        'turkey military exercise',
        'incirlik air base',
        # --- NATO / Europe ---
        'nato exercise arctic',
        'nato military deployment',
        'greenland military defense',
        'nato baltic deployment',
        # --- Ukraine / Russia war ---
        'ukraine military front',
        'russia ukraine offensive',
        'ukraine weapons delivery',
        'black sea military',
        'ukraine drone strike russia',
        'russia mobilization military',
        'crimea military attack',
        'ukraine front line advance',
        'russia missile strike ukraine',
        'ukraine air defense intercept',
        'kursk incursion ukraine',
        # --- Greenland / Arctic (v2.3.0) ---
        'greenland sovereignty dispute',
        'greenland trump acquisition',
        'arctic military buildup',
        'pituffik space base greenland',
        'greenland rare earth minerals',
        'greenland independence referendum',
        'denmark greenland military',
        'arctic nato exercise',
        'us arctic strategy',
        # --- Poland / Eastern Flank (v2.3.0) ---
        'poland military buildup',
        'poland defense spending',
        'poland nato eastern flank',
        'drone incursion poland',
        'drone entered polish airspace',
        'poland airspace violation',
        'poland belarus border crisis',
        'aegis ashore redzikowo poland',
        'us troops poland deployment',
        'poland scramble jets',
        'unidentified object polish airspace',
        'suwalki gap military',
        'poland military modernization',
        'poland F-35 purchase',
        'hybrid warfare poland border',
        # --- Iraq (v2.5.0) ---
        'Iraq militia attack US base',
        'Islamic Resistance Iraq drone',
        'Kataib Hezbollah attack',
        'Iraq ISIS resurgence',
        'US withdrawal Iraq',
        'US forces Iraq drawdown',
        'coalition forces Iraq attack',
        'PMF Popular Mobilization Iraq',
        'Al Asad airbase attack',
        'Erbil rocket attack',
        'Iraq airspace corridor Iran',
        'Iran proxy militia Iraq',
        'ISIS prisoners Iraq',
        'Operation Inherent Resolve Iraq',
        'Iraq sectarian violence',
        'Maliki Iraq government',
        'Peshmerga Kurdistan military',
        # v2.6.0 — Active Iran-Israel conflict + Bahrain
        'Iran missile strike Israel',
        'Iran attack Israel missiles',
        'Israel retaliates Iran',
        'Iran Israel war',
        'ballistic missile Israel intercept',
        'iron dome intercept barrage',
        'home front command rocket alert',
        'US military response Iran',
        'CENTCOM Iran strike',
        'Bahrain 5th Fleet alert',
        'Strait of Hormuz military',
        'regional war Middle East escalation',
        'Iran nuclear facilities strike',
        'airlines cancel Middle East war',
        # v2.7.2 — Israel active war GDELT queries
        'Israel Iran ballistic missile attack',
        'Israel iron dome intercept overwhelmed',
        'Israel home front command siren alert',
        'Israel Tel Aviv missile impact casualties',
        'Israel airspace closed war Iran',
        'Israel Ben Gurion airport closed missile',
        'Israel multi front war missile barrage',
        'Israel casualties missile strike dead wounded',
        'Israel bomb shelter siren red alert',
        'Israel war cabinet emergency session',
        # v2.7.0 — Gulf state + regional actor war queries
        'Kuwait Iranian missile attack',
        'Kuwait US soldiers killed',
        'Kuwait port drone strike',
        'Saudi Arabia Iranian missile Riyadh',
        'Saudi Aramco attack Iran',
        'Saudi air defense intercept',
        'UAE Dubai embassy attack',
        'UAE Abu Dhabi missile',
        'Al Dhafra air base attack',
        'Jordan intercept Iranian drone missile',
        'Jordan airspace ballistic missile',
        'Qatar Al Udeid missile hit',
        'Qatar flights suspended war',
        'Qatar airspace closed',
        'Oman Strait Hormuz military',
        'Oman Duqm naval base',
        'Egypt Suez Canal war disruption',
        'Egypt Sinai military buildup',
        'Turkey Incirlik base attack',
        'Turkey Iran border tensions',
        'Cyprus Akrotiri drone attack',
        'Cyprus evacuation Iran',
        'Cyprus flights cancelled war',
        'UK forces Cyprus reinforcement',
        # --- Sudan civil war + South Sudan (Jul 2026) ---
        'Sudan RSF SAF offensive',
        'El Obeid siege Kordofan',
        'Sudan drone strike Port Sudan',
        'South Sudan clashes White Army',
    ]

    hebrew_queries = [
        'צה"ל פריסה',
        'צה"ל תרגיל',
        'כיפת ברזל',
        'חיל האוויר תרגיל',
        'מילואים גיוס',
        'חזבאללה צפון',
        'פיקוד צפון כוננות',
        'חיל הים סיור',
        # v2.6.0 — Home Front Command / active war
        'פיקוד העורף התרעה',
        'צבע אדום טיל',
        'יירוט טיל בליסטי',
        'מטח רקטות איראן',
        'מלחמה איראן ישראל',
        # v2.7.2 — Israel active war Hebrew
        'פגיעה ישירה תל אביב',
        'נפגעים הרוגים פצועים טיל',
        'כיפת ברזל רווי נפילות',
        'נתב"ג סגור טיסות מבוטלות',
        'פינוי אזרחים מקלט',
    ]

    russian_queries = [
        'военная операция украина',
        'черноморский флот',
        'вооруженные силы учения',
        'ракетный удар украина',
        'мобилизация военная',
        'северный флот арктика',
        'военно-морской флот',
        'ПВО развертывание',
        'наступление фронт донецк',
        'наступление фронт запорожье',
        'артиллерия обстрел украина',
        'крылатая ракета удар',
        'баллистическая ракета удар',
        'дрон удар украина',
        'беспилотник атака',
        'БПЛА удар',
        'курск вторжение',
        'контрнаступление украина',
        'потери военные',
        'подкрепление войска',
        'фронт продвижение',
        'ядерная угроза',
        'мобилизация призыв',
    ]

    arabic_queries = [
        'الحرس الثوري تدريب',
        'قوات عسكرية الخليج',
        'تدريب عسكري السعودية',
        'القوات المسلحة الإماراتية',
        'الجيش المصري تدريب',
        'القوات الأردنية',
        'حزب الله عسكري',
        'صواريخ باليستية إيران',
        'القوات البحرية مضيق هرمز',
        'إخلاء قاعدة عسكرية',
        # v2.5.0 — Iraq Arabic queries
        'المقاومة الإسلامية العراق هجوم',
        'كتائب حزب الله هجوم قاعدة',
        'الحشد الشعبي عمليات',
        'داعش العراق هجوم',
        'الانسحاب الأمريكي العراق',
        'قاعدة عين الأسد هجوم',
        'القوات المسلحة العراقية',
        # v2.6.0 — Active conflict + Bahrain
        'حرب إيران إسرائيل',
        'هجوم صاروخي إيران إسرائيل',
        'الأسطول الخامس البحرين تأهب',
        'القوات الأمريكية تأهب قصوى',
        # v2.7.0 — Gulf state Arabic queries
        'الكويت هجوم صاروخي إيراني',
        'السعودية دفاع جوي اعتراض',
        'الإمارات دبي هجوم',
        'الأردن اعتراض صواريخ طائرات',
        'قطر العديد صاروخ',
        'عمان مضيق هرمز عسكري',
        'مصر قناة السويس حرب',
        'قبرص أكروتيري هجوم',
        # v2.7.2 — Israel war Arabic
        'إسرائيل صاروخ باليستي إيراني هجوم',
        'القبة الحديدية تل أبيب صاروخ',
        'إسرائيل حرب إيران قصف ضحايا',
        # --- Sudan civil war (Jul 2026) ---
        'الدعم السريع الجيش السوداني',
        'حصار الأبيض كردفان',
    ]

    farsi_queries = [
        'سپاه پاسداران رزمایش',
        'نیروی دریایی رزمایش',
        'موشک بالستیک آزمایش',
        'پهپاد نظامی',
        'نیروی هوافضا سپاه',
        'تنگه هرمز رزمایش',
        # v2.6.0 — Active conflict
        'حمله به اسرائیل موشک',
        'جنگ ایران اسرائیل',
        'عملیات نظامی سپاه',
    ]

    turkish_queries = [
        'türk silahlı kuvvetleri operasyon',
        'türk donanması tatbikat',
        'suriye askeri operasyon',
        'bayraktar insansız hava',
        'incirlik üssü',
        # v2.7.0 — War queries
        'İncirlik üssü saldırı',
        'Türkiye hava savunma',
        'İran saldırı Türkiye',
        'füze saldırısı Türkiye',
    ]

    ukrainian_queries = [
        'збройні сили україни',
        'фронт наступ',
        'мобілізація військова',
        'протиповітряна оборона',
        'зброя постачання',
        'ракетний удар росія',
        'дрон атака',
        'артилерія обстріл',
        'контрнаступ запоріжжя',
        'фронт донецьк',
        'фронт луганськ',
        'курськ операція',
        'морський дрон чорне море',
        'F-16 Україна',
        'Patriot ППО',
        'HIMARS удар',
        'Storm Shadow ракета',
        'мобілізація призов',
        'військова допомога',
    ]

    french_queries = [
        'forces armées méditerranée',
        'base militaire djibouti',
        'opération militaire sahel',
    ]

    chinese_queries = [
        '军事演习 南海',
        '解放军 海军',
        '中国 军舰',
    ]

    polish_queries = [
        'wojsko polskie ćwiczenia',
        'siły zbrojne modernizacja',
        'dron nad Polską',
        'naruszenie przestrzeni powietrznej',
        'obrona powietrzna Polska',
        'NATO flanka wschodnia',
        'granica polsko-białoruska wojsko',
        'granica polsko-ukraińska incydent',
        'zakupy wojskowe Polska',
        'Patriot Polska',
        'F-35 Polska',
        'Redzikowo tarcza',
        'Suwałki korytarz',
        'bezzałogowiec granica',
    ]

    danish_norwegian_queries = [
        'grønland forsvar',
        'grønland suverænitet',
        'arktisk militær',
        'Pituffik base',
        'grønland NATO',
        'Danmark forsvar grønland',
        'arktisk sikkerhed',
        'forsvaret Arktis',
        'militær øvelse Arktis',
        'Grønland selvstændighed',
    ]

    # v2.8.0 — Asia-Pacific dedicated query blocks
    asia_english_queries = [
        # Afghanistan / Taliban (daily signal)
        'Taliban attack Afghanistan',
        'Taliban military operation Afghanistan',
        'Taliban seize district Afghanistan',
        'TTP attack Pakistan soldiers',
        'TTP militants Pakistan border',
        'Pakistan airstrike Afghanistan',
        'Pakistan bombs Afghanistan TTP',
        'Pakistan strikes Khost Paktika',
        'Haqqani network attack',
        'ISIS-K attack Afghanistan',
        'ISKP bomb Afghanistan',
        'Pakistan Afghanistan border tension',
        'Iran strikes Pakistan Balochistan',
        'Iran Pakistan border military',
        'Jaish al-Adl Iran Pakistan',
        'Pakistan retaliates Iran',
        'Pakistan deploys troops Iran border',
        'Balochistan insurgent attack',
        'BLA attack Pakistan',
        'NRF resistance Afghanistan Taliban',
        # North Korea (provocations are constant)
        'North Korea missile launch',
        'North Korea ballistic missile',
        'DPRK missile test',
        'North Korea ICBM',
        'Kim Jong Un military order',
        'Kim Jong Un nuclear weapon',
        'Pyongyang ballistic missile',
        'North Korea nuclear test',
        'North Korea nuclear warhead',
        'North Korea provocation',
        'DPRK provocation South Korea',
        'North Korea artillery DMZ',
        'North Korea drone South Korea',
        'North Korea troops Russia Ukraine',
        'North Korea soldiers deployed Russia',
        'DPRK weapons Russia',
        'North Korea submarine launch',
        # Pakistan military
        'Pakistan military operation',
        'Pakistan ISPR militants killed',
        'Pakistan nuclear missile test',
        'India Pakistan line of control',
        'India Pakistan skirmish Kashmir',
        # South Korea / peninsula
        'South Korea North Korea border',
        'Korean peninsula military tension',
        'USFK military exercise',
        'Ulchi Freedom Shield Korea',
        # Taiwan / China
        'PLA Taiwan Strait military exercise',
        'China Taiwan invasion threat',
        'Taiwan ADIZ incursion PLA',
        'US Navy Taiwan Strait patrol',
        # India
        'India China LAC border clash',
        'India Pakistan line of control',
        'India missile test Agni',
        'India military exercise',
        # Japan — expanded May 6 2026 (Takaichi-era posture changes)
        'Japan JSDF scramble China',
        'Japan North Korea missile alert',
        'Japan defense budget rearmament',
        'Senkaku islands China Japan',
        'JMSDF Taiwan Strait transit',
        'Japan Taiwan defense Takaichi',
        'Japan Article 9 reinterpretation',
        'Japan counter-strike capability Tomahawk',
        'Okinawa PLA pressure',
        'Japan Philippines security cooperation',
        'JGSDF officer Chinese Embassy incident',
        'Japan long-range strike deployment',
        'Eastern Theater Command Japan',
        'Yonaguni Miyako Ishigaki garrison',
    ]

    japanese_queries = [
        '自衛隊 中国',
        '尖閣諸島 中国',
        '高市 台湾',
        '反撃能力 配備',
        '北朝鮮 ミサイル 日本',
        '南西諸島 防衛',
        '日米共同訓練',
    ]

    korean_queries = [
        '북한 미사일 발사',
        '북한 핵 실험',
        '김정은 군사',
        '북한 도발',
        '한미 연합훈련',
        '북한 탄도미사일',
        '조선인민군',
        '북한 남한 군사',
    ]

    urdu_queries = [
        'پاکستان فوج آپریشن',
        'ٹی ٹی پی حملہ',
        'پاکستان ایران سرحد',
        'بلوچستان حملہ',
        'پاکستان افغانستان سرحد',
        'پاکستان بھارت کنٹرول لائن',
    ]

    # v3.0.0 — Western Hemisphere dedicated query blocks
    wha_english_queries = [
        # Venezuela — post-Maduro transition
        'Venezuela military transition Maduro',
        'Venezuela regime change armed forces',
        'Venezuela military faction power vacuum',
        'colectivos Venezuela armed',
        'Venezuela DEA military operation',
        'Venezuela US military sanctions',
        'Tren de Aragua military Venezuela',
        'Venezuela Cuba military cooperation',
        'Russia military Venezuela Caribbean',
        'China military Venezuela',
        # Cuba
        'Cuba Russia spy base signals intelligence',
        'Russian warship Cuba Caribbean',
        'China Cuba military intelligence base',
        'Cuba protests military crackdown',
        'Cuba armed forces stability',
        'Guantanamo Bay military',
        'Cuba economic collapse military',
        # Haiti
        'Haiti gang MSS mission Viv Ansanm',
        'Haiti Kenyan security force mission',
        'Haiti G9 gang armed territory',
        'Haiti multinational security mission',
        'Haiti police overwhelmed gang',
        'Haiti port-au-prince gang control',
        'Haiti security forces deploy',
        'Haiti US embassy security',
        # Panama
        'Panama Canal military security',
        'Panama Canal China port Hutchison',
        'Trump Panama Canal sovereignty military',
        'US warship Panama Canal transit',
        'Panama Darien Gap military',
        # Colombia
        'Colombia ELN attack military',
        'Colombia FARC dissident operation',
        'Colombia military operation guerrilla',
        'Colombia US military advisors',
        'Colombia Venezuela border military',
        # Mexico
        'Mexico cartel military operation',
        'CJNG Sinaloa cartel ambush military',
        'Mexico army cartel operation',
        'US Mexico border military deployment',
        'Mexico cartel drone attack',
        'Trump Mexico cartel terrorist designation',
        'Mexico fentanyl military operation',
        # Brazil
        'Brazil Amazon military operation',
        'Brazil armed forces exercise',
        'Brazil navy military exercise',
        'Brazil Colombia Venezuela border military',
        # SOUTHCOM general
        'SOUTHCOM military exercise Caribbean',
        'US Southern Command deployment',
        'Operation Martillo drug interdiction',
        'US Coast Guard drug bust Caribbean',
        'Joint Task Force Bravo Honduras',
    ]

    spanish_queries = [
        # Venezuela
        'venezuela fuerzas armadas transicion',
        'venezuela militares faccion',
        'venezuela colectivos armados',
        'maduro detenido capturado',
        'venezuela crisis militar',
        'tren de aragua venezuela',
        # Cuba
        'cuba militares represion',
        'cuba fuerzas armadas crisis',
        'cuba protestas represion',
        'rusia base cuba inteligencia',
        # Haiti
        'haiti pandillas armadas',
        'haiti mision seguridad kenia',
        'haiti policia pandillas',
        # Panama
        'canal panama seguridad militar',
        'china canal panama control',
        'soberania canal panama',
        # Colombia
        'colombia eln ataque militar',
        'colombia farc disidencias operacion',
        'colombia ejercito operacion',
        'colombia venezuela frontera militar',
        # Mexico
        'mexico cartel operacion militar',
        'cjng jalisco cartel militar',
        'mexico ejercito cartel',
        'guardia nacional mexico cartel',
        'narco drones mexico',
        'frontera mexico militar estados unidos',
        # Brazil
        'brasil militares operacao',
        'exercito brasil amazonia operacao',
        'brasil fronteira militar',
    ]

    all_articles = []

    query_blocks = [
        (english_queries, 'eng', 'English'),
        (asia_english_queries, 'eng', 'Asia-English'),
        (wha_english_queries, 'eng', 'WHA-English'),
        (hebrew_queries, 'heb', 'Hebrew'),
        (russian_queries, 'rus', 'Russian'),
        (arabic_queries, 'ara', 'Arabic'),
        (farsi_queries, 'fas', 'Farsi'),
        (turkish_queries, 'tur', 'Turkish'),
        (ukrainian_queries, 'ukr', 'Ukrainian'),
        (french_queries, 'fra', 'French'),
        (chinese_queries, 'zho', 'Chinese'),
        (polish_queries, 'pol', 'Polish'),
        (danish_norwegian_queries, 'dan', 'Danish'),
        (korean_queries, 'kor', 'Korean'),
        (urdu_queries, 'urd', 'Urdu'),
        (spanish_queries, 'spa', 'Spanish'),
        (japanese_queries, 'jpn', 'Japanese'),
    ]

    for queries, lang_code, lang_name in query_blocks:
        block_count = 0
        for query in queries:
            articles = fetch_gdelt_military(query, days, language=lang_code)
            all_articles.extend(articles)
            block_count += len(articles)
            time.sleep(0.5)
        if block_count > 0:
            print(f"[Military GDELT] {lang_name} ({lang_code}): {block_count} articles from {len(queries)} queries")

    print(f"[Military GDELT] Total GDELT military articles: {len(all_articles)}")
    return all_articles


# ========================================
# DATA FETCHING — NewsAPI
# ========================================

def fetch_newsapi_military(query, days=7):
    """Fetch military articles from NewsAPI"""
    if not NEWSAPI_KEY:
        _health_note('newsapi', configured=False)
        return []
    _t0 = time.time()

    from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    url = "https://newsapi.org/v2/everything"
    params = {
        'q': query,
        'from': from_date,
        'sortBy': 'publishedAt',
        'language': 'en',
        'apiKey': NEWSAPI_KEY,
        'pageSize': 50
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])
            for a in articles:
                a['feed_type'] = 'newsapi'
            _health_note('newsapi', http_status=200, articles=len(articles),
                         duration_ms=(time.time() - _t0) * 1000)
            return articles
        # NewsAPI answers a plan restriction with 426 and a bad key with
        # 401; both looked exactly like 'no results' from outside.
        _health_note('newsapi', http_status=response.status_code,
                     error=(response.text or '')[:160],
                     duration_ms=(time.time() - _t0) * 1000)
        return []
    except Exception as e:
        _health_note('newsapi', error=e,
                     duration_ms=(time.time() - _t0) * 1000)
        return []


def fetch_all_newsapi_military(days=7):
    """Fetch military articles from NewsAPI across key queries"""
    queries = [
        'military deployment Middle East',
        'carrier strike group Gulf',
        'US troops deployed',
        'IRGC military exercise',
        'NATO exercise',
        'base evacuation Middle East',
        'military families departure Bahrain',
        'Ukraine military',
        'Russia offensive Ukraine',
        'Poland military NATO',
        'drone Poland airspace',
        'Greenland sovereignty Arctic',
        # v2.5.0 — Iraq
        'Iraq militia attack coalition base',
        'Iraq ISIS military operation',
        # v2.6.0 — War footing
        'Bahrain 5th Fleet military alert',
        'Iran Israel war missile strike',
        # v2.7.0 — Gulf + regional
        'Kuwait Iran attack US soldiers',
        'Saudi Arabia Iranian missile defense',
        'UAE Dubai embassy attack missile',
        'Jordan intercept Iranian missiles drones',
        'Qatar Al Udeid base missile attack',
        'Cyprus Akrotiri Iran drone attack',
        'Oman military Strait Hormuz',
        # v2.7.2 — Israel war
        'Israel Iran missile attack ballistic',
        'Israel iron dome intercept war siren',
        'Israel home front command alert casualties',
        'Israel Tel Aviv Haifa missile impact',
        # v3.0.0 — Western Hemisphere
        'Venezuela military transition Maduro regime',
        'Cuba Russia military base Caribbean',
        'Haiti gang MSS Kenya security mission',
        'Panama Canal China port military sovereignty',
        'Colombia ELN FARC military operation',
        'Mexico cartel military army operation',
        'SOUTHCOM US military Caribbean Latin America',
    ]

    all_articles = []
    for query in queries:
        articles = fetch_newsapi_military(query, days)
        all_articles.extend(articles)
        time.sleep(0.3)

    print(f"[Military NewsAPI] Total articles: {len(all_articles)}")
    return all_articles


# ========================================
# DATA FETCHING — Reddit
# ========================================

# ========================================
# DATA FETCHING — Brave Search (tertiary fallback)
# ========================================
# Added May 6 2026. Free tier: 2000 queries/month, 1 req/sec.
# Pattern: only fires when GDELT + NewsAPI combined return < 10 articles
# (i.e., both upstream sources failed or rate-limited). Same pattern as
# WHA backend.

BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY')
BRAVE_API_URL = 'https://api.search.brave.com/res/v1/news/search'


def fetch_brave_military(query, days=7):
    """Fetch military articles from Brave Search News API (tertiary fallback).
    Returns empty list if no API key configured or request fails."""
    if not BRAVE_API_KEY:
        _health_note('brave', configured=False)
        return []
    _t0 = time.time()
    headers = {
        'Accept':              'application/json',
        'Accept-Encoding':     'gzip',
        'X-Subscription-Token': BRAVE_API_KEY,
    }
    params = {
        'q':           query,
        'count':       20,
        'freshness':   'pw' if days <= 7 else 'pm',  # past week / past month
        'spellcheck':  'false',
    }
    try:
        response = requests.get(BRAVE_API_URL, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', []) or []
            articles = []
            for r in results:
                articles.append({
                    'title':       r.get('title', '')[:200],
                    'description': r.get('description', '')[:500],
                    'url':         r.get('url', ''),
                    'publishedAt': r.get('age', '') or r.get('page_age', ''),
                    'source':      {'name': (r.get('meta_url', {}) or {}).get('hostname', 'Brave')},
                    'content':     r.get('description', '')[:500],
                    'feed_type':   'brave',
                })
            _health_note('brave', http_status=200, articles=len(articles),
                         duration_ms=(time.time() - _t0) * 1000)
            return articles
        # Brave sends 401 for a bad token, 403 for a plan problem and 429
        # when the 2000/month free tier is spent. All three used to leave
        # here as an empty list with the status code discarded.
        _health_note('brave', http_status=response.status_code,
                     error=(response.text or '')[:160],
                     duration_ms=(time.time() - _t0) * 1000)
        return []
    except Exception as e:
        _health_note('brave', error=e,
                     duration_ms=(time.time() - _t0) * 1000)
        return []


def fetch_all_brave_military(days=7):
    """Fetch military articles from Brave Search across high-priority queries.
    Only fires as a tertiary fallback — keeps the query list short to respect
    the 2000/month free tier quota. Brave's strength is recency and de-Googling
    coverage gaps, not breadth."""
    if not BRAVE_API_KEY:
        return []
    queries = [
        # Highest-signal global military queries (mirror GDELT priorities)
        'military deployment escalation',
        'carrier strike group deployment',
        'PLA Taiwan Strait incursion',
        'JSDF scramble China',
        'Senkaku islands incursion',
        'Iran military strike',
        'Israel IDF operation',
        'North Korea missile launch',
        'Russia Ukraine military',
        'NATO eastern flank deployment',
    ]
    all_articles = []
    for query in queries:
        articles = fetch_brave_military(query, days)
        all_articles.extend(articles)
        time.sleep(1.0)  # Brave free tier: 1 req/sec hard limit
    print(f"[Military Brave] Total Brave military articles: {len(all_articles)}")
    return all_articles


def fetch_reddit_military(days=7):
    """Fetch military-related Reddit posts"""
    _t0 = time.time()
    all_posts = []
    keywords = ['deployment', 'military', 'carrier', 'strike group', 'NATO', 'CENTCOM',
                'evacuation', 'Ukraine']
    query = " OR ".join(keywords[:4])
    time_filter = "week" if days <= 7 else "month"

    for subreddit in REDDIT_MILITARY_SUBREDDITS[:5]:
        try:
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params = {
                "q": query,
                "restrict_sr": "true",
                "sort": "new",
                "t": time_filter,
                "limit": 15
            }
            headers = {"User-Agent": REDDIT_USER_AGENT}

            time.sleep(2)
            response = requests.get(url, params=params, headers=headers, timeout=10)

            if response.status_code != 200:
                # Reddit blocks datacenter IPs and generic user agents with
                # 403, and rate limits with 429. Both previously fell
                # through this `if` in silence and then out of the bare
                # `except ... continue` below, leaving zero trace.
                _health_note('reddit', http_status=response.status_code,
                             error=(response.text or '')[:160],
                             note=f'r/{subreddit}')
            if response.status_code == 200:
                _health_note('reddit', http_status=200)
                data = response.json()
                if "data" in data and "children" in data["data"]:
                    for post in data["data"]["children"]:
                        post_data = post.get("data", {})
                        all_posts.append({
                            'title': post_data.get('title', '')[:200],
                            'description': post_data.get('selftext', '')[:300],
                            'url': f"https://www.reddit.com{post_data.get('permalink', '')}",
                            'publishedAt': datetime.fromtimestamp(
                                post_data.get('created_utc', 0),
                                tz=timezone.utc
                            ).isoformat(),
                            'source': {'name': f'r/{subreddit}'},
                            'content': post_data.get('selftext', ''),
                            'feed_type': 'reddit'
                        })
        except Exception as e:
            _health_note('reddit', error=e, note=f'r/{subreddit}')
            continue

    _health_note('reddit', articles=len(all_posts),
                 duration_ms=(time.time() - _t0) * 1000)
    print(f"[Military Reddit] Total posts: {len(all_posts)}")
    return all_posts


# ========================================
# CORE ANALYSIS ENGINE
# ========================================

def get_location_multiplier(text):
    """Scan article text for hotspot locations and return the highest multiplier."""
    max_multiplier = 1.0
    matched_location = None

    for location, multiplier in LOCATION_MULTIPLIERS.items():
        if location in text:
            if multiplier > max_multiplier:
                max_multiplier = multiplier
                matched_location = location

    return max_multiplier, matched_location


def get_evacuation_subtype_weight(text):
    """For base_evacuation signals, determine the specific sub-type."""
    for subtype_id, subtype_data in sorted(
        EVACUATION_SUBTYPE_WEIGHTS.items(),
        key=lambda x: x[1]['weight'],
        reverse=True
    ):
        for kw in subtype_data['keywords']:
            if kw in text:
                return subtype_data['weight'], subtype_id

    return ASSET_CATEGORIES['base_evacuation']['weight'], 'unspecified'


# ════════════════════════════════════════════════════════════════════════
# RECENCY GATE (Sep 7 2026)
# ════════════════════════════════════════════════════════════════════════
# The scan declares days_analyzed=7 and then scored an eleven-year span.
# The Sep 7 payload carried a Rudaw article from 2015-04-28, another from
# 2021, the USS Nimitz homecoming from 2025-12-16 (twice, from two USNI
# feeds), and the Al Udeid evacuation stories from July. Every article
# already carries publishedAt. Nothing read it.
#
# ABSENCE-HONEST: an article whose date cannot be parsed is KEPT, not
# dropped. We do not infer a date we do not have. Those are counted
# separately so the payload says how much of the corpus is undated.
# ════════════════════════════════════════════════════════════════════════

_REL_AGE_PATTERN = _re.compile(
    r'(\d+)\s*(minute|min|hour|hr|day|week|month|year)s?\s*ago', _re.IGNORECASE)
_REL_UNIT_SECONDS = {
    'minute': 60, 'min': 60, 'hour': 3600, 'hr': 3600, 'day': 86400,
    'week': 604800, 'month': 2592000, 'year': 31536000,
}


def _parse_article_date(raw):
    """Parse the many publishedAt shapes this corpus carries.

    Handles ISO 8601 with or without offset, Brave relative strings
    ('27 minutes ago', '1 week ago'), GDELT compact stamps
    (20260904T163321Z), and RFC 822 RSS dates. Returns an aware datetime
    in UTC, or None when the value cannot be understood.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    now = datetime.now(timezone.utc)

    m = _REL_AGE_PATTERN.search(s)
    if m:
        try:
            n = int(m.group(1))
            secs = _REL_UNIT_SECONDS.get(m.group(2).lower())
            if secs:
                return now - timedelta(seconds=n * secs)
        except (TypeError, ValueError):
            return None

    if _re.fullmatch(r'\d{8}T\d{6}Z', s):
        try:
            return datetime.strptime(s, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    if _re.fullmatch(r'\d{14}', s):
        try:
            return datetime.strptime(s, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass

    for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S %Z',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    return None


def filter_articles_by_recency(articles, days):
    """Drop articles published outside the declared scan window.

    Returns (kept_articles, stats_dict). Undated articles are kept and
    counted; the stats dict is published in the payload so an operator can
    see how much of the corpus is undated rather than guessing.
    """
    if not articles:
        return [], {'kept': 0, 'dropped_stale': 0, 'undated_kept': 0,
                    'window_days': days, 'oldest_kept': None,
                    'oldest_dropped': None}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    kept, dropped, undated = [], 0, 0
    oldest_kept = None
    oldest_dropped = None

    for art in articles:
        dt = _parse_article_date(art.get('publishedAt'))
        if dt is None:
            undated += 1
            kept.append(art)
            continue
        if dt < cutoff:
            dropped += 1
            if oldest_dropped is None or dt < oldest_dropped:
                oldest_dropped = dt
            continue
        kept.append(art)
        if oldest_kept is None or dt < oldest_kept:
            oldest_kept = dt

    stats = {
        'kept':           len(kept),
        'dropped_stale':  dropped,
        'undated_kept':   undated,
        'window_days':    days,
        'oldest_kept':    oldest_kept.isoformat() if oldest_kept else None,
        'oldest_dropped': oldest_dropped.isoformat() if oldest_dropped else None,
    }
    return kept, stats


# ════════════════════════════════════════════════════════════════════════
# EVENT DEDUPLICATION (v3.4)
# ════════════════════════════════════════════════════════════════════════
# The tracker used to count coverage, not events. One Abraham Lincoln port
# call reported by five outlets scored five times. That inflates whichever
# actor gets the most press, which is not the same thing as the actor doing
# the most - the exact failure mode this platform exists to avoid.
#
# Two layers, applied in order:
#
#   LAYER 0 - Article dedupe. The same article arriving through more than
#             one feed (RSS + GDELT + Brave all catch the same Reuters wire)
#             is one article. Same URL, or same normalized title, = one.
#             No judgment involved; this is a straight double-count bug.
#
#   LAYER 1 - Event dedupe. Distinct articles describing the SAME event are
#             collapsed to one signal. Match rule: same actor + same asset
#             class + same named entity, within a rolling 72h window.
#             Requires a named entity - with nothing to anchor on we do NOT
#             merge, because a wrongly merged event is invisible signal loss
#             and that is the more dangerous error.
#
# Corroboration is preserved as a CONFIDENCE multiplier, not a count of
# events. Five independent outlets genuinely is more confirmed than one, so
# the surviving signal gets a logarithmic bonus that is capped and counts
# DISTINCT SOURCES, not articles - five reposts by one outlet is one source.
#   1 source  = x1.00      3 sources = x1.29      10 sources = x1.60 (cap)
#   2 sources = x1.18      5 sources = x1.42
# ════════════════════════════════════════════════════════════════════════

EVENT_DEDUPE_WINDOW_HOURS = 72
CORROBORATION_WEIGHT = 0.18
CORROBORATION_MAX_MULTIPLIER = 1.6

# Named assets recognizable WITHOUT a "USS" prefix. Used only to group
# duplicate reports of one event, never to score.
#
# Deliberately conservative. A false positive here MERGES two unrelated
# events and silently destroys signal, so bare surnames that are also
# people, places or companies ('ford', 'roosevelt', 'truman', 'lincoln',
# 'washington', 'bush', 'reagan') are listed only in their unambiguous
# multi-word or USS-prefixed forms.
NAMED_MILITARY_ASSETS = {
    'cvn_68_nimitz':          ['uss nimitz', 'nimitz carrier', 'nimitz strike group'],
    'cvn_69_eisenhower':      ['uss eisenhower', 'dwight d. eisenhower', 'dwight d eisenhower', 'ike carrier'],
    'cvn_70_vinson':          ['uss carl vinson', 'carl vinson'],
    'cvn_71_roosevelt':       ['uss theodore roosevelt', 'theodore roosevelt carrier', 'uss roosevelt'],
    'cvn_72_lincoln':         ['uss abraham lincoln', 'abraham lincoln carrier', 'abraham lincoln strike group', 'uss lincoln'],
    'cvn_73_washington':      ['uss george washington', 'george washington carrier'],
    'cvn_74_stennis':         ['uss john c. stennis', 'uss john c stennis', 'john c. stennis', 'uss stennis'],
    'cvn_75_truman':          ['uss harry s. truman', 'uss harry truman', 'harry s. truman', 'uss truman'],
    'cvn_76_reagan':          ['uss ronald reagan', 'ronald reagan carrier'],
    'cvn_77_bush':            ['uss george h.w. bush', 'uss george hw bush', 'uss george h. w. bush'],
    'cvn_78_ford':            ['uss gerald r. ford', 'uss gerald ford', 'gerald r. ford', 'gerald ford carrier'],
    'lhd_1_wasp':             ['uss wasp'],
    'lha_6_america':          ['uss america'],
    'lhd_3_kearsarge':        ['uss kearsarge'],
    'lhd_7_iwo_jima':         ['uss iwo jima'],
    'lha_7_tripoli':          ['uss tripoli'],
    'lhd_8_makin_island':     ['uss makin island', 'makin island'],
    'lhd_2_essex':            ['uss essex'],
    'lhd_4_boxer':            ['uss boxer'],
    'lhd_5_bataan':           ['uss bataan'],
    'ssgn_ohio':              ['uss ohio'],
    'ssgn_florida':           ['uss florida'],
    'ssgn_georgia':           ['uss georgia'],
    'ssgn_michigan':          ['uss michigan'],
    'cg_gettysburg':          ['uss gettysburg'],
    'ddg_carney':             ['uss carney'],
    'ddg_cole':               ['uss cole'],
    'ddg_laboon':             ['uss laboon'],
    'ddg_mason':              ['uss mason'],
    'ddg_thomas_hudner':      ['uss thomas hudner'],
    'ddg_gravely':            ['uss gravely'],
    'ddg_stockdale':          ['uss stockdale'],
    'ddg_spruance':           ['uss spruance'],
    'ddg_arleigh_burke':      ['uss arleigh burke'],
    'ddg_bulkeley':           ['uss bulkeley'],
}

# CONTEXTUAL aliases: bare ship names that are also people or places.
# The observed failure was literally "Abraham Lincoln departs Thailand"
# with no USS prefix, so these have to be matched - but only when the text
# also carries naval context, which keeps a Lincoln history piece or a
# story datelined Lincoln, Nebraska out of the carrier's cluster.
NAMED_ASSET_CONTEXTUAL_ALIASES = {
    'cvn_68_nimitz':     ['nimitz'],
    'cvn_69_eisenhower': ['eisenhower'],
    'cvn_71_roosevelt':  ['theodore roosevelt'],
    'cvn_72_lincoln':    ['abraham lincoln'],
    'cvn_73_washington': ['george washington'],
    'cvn_74_stennis':    ['stennis'],
    'cvn_75_truman':     ['harry s. truman', 'harry truman'],
    'cvn_76_reagan':     ['ronald reagan'],
    'cvn_78_ford':       ['gerald r. ford', 'gerald ford'],
    'lhd_8_makin_island':['makin island'],
}

NAVAL_CONTEXT_TERMS = (
    'carrier', 'strike group', 'csg', 'navy', 'naval', 'warship', 'flattop',
    'fleet', 'destroyer', 'amphibious', 'port call', 'underway', 'flight deck',
    'deploy', 'deployment', 'transit', 'transits', 'steaming', 'sortie',
    'sails', 'sailed', 'sailing', 'homeport', 'home port', 'shipyard',
    'escort', 'air wing', 'sixth fleet', 'fifth fleet', 'seventh fleet',
)

# Flat alias -> canonical id, longest alias first so 'uss abraham lincoln'
# wins over 'uss lincoln'.
_NAMED_ASSET_ALIASES = sorted(
    ((alias, asset_id)
     for asset_id, aliases in NAMED_MILITARY_ASSETS.items()
     for alias in aliases),
    key=lambda pair: -len(pair[0])
)

_NAMED_ASSET_CONTEXTUAL = sorted(
    ((alias, asset_id)
     for asset_id, aliases in NAMED_ASSET_CONTEXTUAL_ALIASES.items()
     for alias in aliases),
    key=lambda pair: -len(pair[0])
)


def _has_naval_context(low_text):
    return any(term in low_text for term in NAVAL_CONTEXT_TERMS)


def _extract_named_asset(text):
    """Return the canonical id of the first named asset in text, or None.

    Three tiers, most confident first:
      1. Unambiguous aliases ('uss abraham lincoln', 'carl vinson')
      2. Bare names ('abraham lincoln') ONLY with naval context in the text
      3. Generic USS-pattern fallback for ships not on the roster
    """
    if not text:
        return None
    low = text.lower()

    for alias, asset_id in _NAMED_ASSET_ALIASES:
        if alias in low:
            return asset_id

    if _has_naval_context(low):
        for alias, asset_id in _NAMED_ASSET_CONTEXTUAL:
            if alias in low:
                return asset_id

    try:
        generic = _extract_named_ships(low)
    except Exception:
        generic = []
    if generic:
        return 'uss_' + sorted(generic)[0].replace(' ', '_').replace('.', '')
    return None


def _normalize_title_key(title):
    """Collapse a headline to a comparison key: lowercase, alphanumerics
    only, stopwords dropped. Used ONLY for Layer 0 exact-article dedupe."""
    if not title:
        return ''
    low = ''.join(ch if ch.isalnum() else ' ' for ch in str(title).lower())
    drop = {'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for',
            'and', 'as', 'is', 'it', 'its', 'by', 'with', 'from'}
    words = [w for w in low.split() if w and w not in drop]
    return ' '.join(words)[:150]


def deduplicate_articles(articles):
    """LAYER 0. Collapse the same article arriving through multiple feeds.
    Returns (unique_articles, stats). Keeps the FIRST occurrence, and records
    every feed that carried it on the survivor as 'also_seen_in'."""
    seen_url = {}
    seen_title = {}
    unique = []
    dropped_url = 0
    dropped_title = 0

    for art in articles:
        url = (art.get('url') or '').strip().lower().split('#')[0].rstrip('/')
        tkey = _normalize_title_key(art.get('title'))
        feed = (art.get('source') or {}).get('name', 'Unknown') \
            if isinstance(art.get('source'), dict) else str(art.get('source') or 'Unknown')

        keeper = None
        if url and url in seen_url:
            keeper = seen_url[url]
            dropped_url += 1
        elif tkey and len(tkey) >= 25 and tkey in seen_title:
            keeper = seen_title[tkey]
            dropped_title += 1

        if keeper is not None:
            feeds = keeper.setdefault('also_seen_in', [])
            if feed not in feeds:
                feeds.append(feed)
            continue

        if url:
            seen_url[url] = art
        if tkey and len(tkey) >= 25:
            seen_title[tkey] = art
        unique.append(art)

    return unique, {
        'input': len(articles),
        'kept': len(unique),
        'dropped_same_url': dropped_url,
        'dropped_same_title': dropped_title,
        'dropped_total': dropped_url + dropped_title,
    }


def _corroboration_multiplier(distinct_sources):
    """Logarithmic, capped confidence bonus for independent corroboration."""
    n = max(1, int(distinct_sources))
    if n <= 1:
        return 1.0
    mult = 1.0 + CORROBORATION_WEIGHT * math.log2(n)
    return min(mult, CORROBORATION_MAX_MULTIPLIER)


def _signal_event_key(signal):
    """(actor, asset, named_entity) or None if the signal cannot be anchored
    to a named entity. None means DO NOT dedupe this signal."""
    text = f"{signal.get('article_title') or ''} {signal.get('keyword') or ''}"
    entity = _extract_named_asset(text)
    if not entity:
        return None
    return (signal.get('actor'), signal.get('asset'), entity)


def deduplicate_event_signals(signals):
    """LAYER 1. Collapse signals describing the same event into one.

    Same actor + asset + named entity inside a rolling 72h window = one
    event. The highest-weight signal survives and carries the corroboration
    bonus. Signals with no named entity pass through untouched.

    Returns (deduped_signals, stats).
    """
    window = timedelta(hours=EVENT_DEDUPE_WINDOW_HOURS)
    clusters = {}
    passthrough = []

    for sig in signals:
        key = _signal_event_key(sig)
        if key is None:
            passthrough.append(sig)
            continue
        when = _parse_article_date(sig.get('published'))
        clusters.setdefault(key, []).append((when, sig))

    deduped = list(passthrough)
    collapsed = 0
    events = 0
    biggest = None

    for key, entries in clusters.items():
        # Undated signals sort last so a dated signal anchors each cluster.
        dated = sorted((e for e in entries if e[0]), key=lambda e: e[0])
        undated = [e for e in entries if not e[0]]

        buckets = []
        for when, sig in dated:
            placed = False
            for b in buckets:
                if when - b['start'] <= window:
                    b['signals'].append(sig)
                    placed = True
                    break
            if not placed:
                buckets.append({'start': when, 'signals': [sig]})
        if undated:
            if buckets:
                buckets[0]['signals'].extend(s for _, s in undated)
            else:
                buckets.append({'start': None, 'signals': [s for _, s in undated]})

        for b in buckets:
            group = b['signals']
            events += 1
            winner = max(group, key=lambda s: s.get('weight', 0))
            sources = []
            for s in group:
                src = s.get('source') or 'Unknown'
                if src not in sources:
                    sources.append(src)

            merged = dict(winner)
            base = float(winner.get('weight') or 0)
            mult = _corroboration_multiplier(len(sources))
            merged['weight'] = round(base * mult, 2)
            merged['dedupe_event_key'] = f"{key[0]}|{key[1]}|{key[2]}"
            merged['report_count'] = len(group)
            merged['corroboration_count'] = len(sources)
            merged['corroborating_sources'] = sources[:12]
            merged['corroboration_multiplier'] = round(mult, 3)
            merged['pre_corroboration_weight'] = round(base, 2)
            merged['collapsed_titles'] = [
                s.get('article_title', '') for s in group
                if s.get('article_title') and s is not winner
            ][:8]
            deduped.append(merged)

            if len(group) > 1:
                collapsed += len(group) - 1
                if biggest is None or len(group) > biggest['report_count']:
                    biggest = {
                        'event_key': merged['dedupe_event_key'],
                        'report_count': len(group),
                        'corroboration_count': len(sources),
                        'title': merged.get('article_title', ''),
                        'raw_score_before': round(sum(float(s.get('weight') or 0) for s in group), 2),
                        'score_after': merged['weight'],
                    }

    return deduped, {
        'input_signals': len(signals),
        'output_signals': len(deduped),
        'unanchored_passthrough': len(passthrough),
        'anchored_signals': len(signals) - len(passthrough),
        'distinct_events': events,
        'duplicate_signals_collapsed': collapsed,
        'window_hours': EVENT_DEDUPE_WINDOW_HOURS,
        'largest_cluster': biggest,
    }


# ════════════════════════════════════════════════════════════════════════
# MATCH-TEXT HYGIENE (v3.6)
# ════════════════════════════════════════════════════════════════════════
# Keyword matching used to run against the raw title + description +
# content. For Google News RSS the description is HTML containing the
# encoded article link, so the text handed to the matcher looked like:
#
#   ...<a href="https://news.google.com/rss/articles/CBMiV0FVX3lxTE9q
#   TFNuTkwxWnVvZTFiT1l1ZzY5WXBtN3hyeWJrUWVNUXpKRmpGejlySU9ZcDMx
#   LTV6bDFONWhrODJZdnNhZlRILWFVcDV2SEY5WHdwQXVUSQ">...
#
# Lowercased, that blob contains the literal string "bdf" - which is
# Bahrain's keyword for the Bahrain Defence Force. That is why an article
# titled "New scheme introduced to attract Danish doctors and nurses to
# Greenland" scored as Bahraini military activity. The RSS fetcher also
# copies description into content, so every blob was matched twice.
#
# Two defences, because either alone is insufficient:
#   1. Strip markup, URLs and opaque tokens before matching.
#   2. Require word boundaries for short ASCII keywords, so a three-letter
#      acronym cannot hide inside a longer word.
# ════════════════════════════════════════════════════════════════════════

# Opaque token = a long unbroken run of letters/digits with no vowel
# rhythm a human word would have. Base64 ids, tracking hashes, encoded
# links. Anything this long and unbroken is not prose.
_OPAQUE_TOKEN_MIN_LEN = 22

_HTML_TAG_RE = _re.compile(r'<[^>]{1,400}>')
_HTML_ENTITY_RE = _re.compile(r'&(?:[a-z]{2,10}|#\d{1,5});')
_URL_RE = _re.compile(r'(?:https?://|www\.)\S+', _re.IGNORECASE)
_OPAQUE_TOKEN_RE = _re.compile(
    r'\b(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)'
    r'[A-Za-z0-9_-]{%d,}\b' % _OPAQUE_TOKEN_MIN_LEN
)
# Long alpha-only runs are also not words (base64 without digits).
_LONG_ALPHA_RUN_RE = _re.compile(r'\b[A-Za-z]{28,}\b')


def clean_match_text(raw):
    """Strip markup, links and machine tokens so keyword matching only ever
    sees human-readable prose. Returns lowercased, whitespace-collapsed text.

    Deliberately aggressive about URLs: no actor or asset keyword should
    ever legitimately be matched inside one, and the cost of leaving them
    in is a Danish healthcare story scoring as a Gulf military signal.
    """
    if not raw:
        return ''
    txt = str(raw)
    txt = _HTML_TAG_RE.sub(' ', txt)
    txt = _URL_RE.sub(' ', txt)
    txt = _HTML_ENTITY_RE.sub(' ', txt)
    txt = _OPAQUE_TOKEN_RE.sub(' ', txt)
    txt = _LONG_ALPHA_RUN_RE.sub(' ', txt)
    return ' '.join(txt.lower().split())


# ---- Word-boundary matching for short keywords -----------------------
# A short ASCII acronym as a bare substring is a liability: 'bdf', 'far',
# 'uss', 'gtmo'. Long keywords and non-Latin scripts keep plain substring
# matching, which is both cheaper and correct for them.
SHORT_KEYWORD_MAX_LEN = 5

_kw_pattern_cache = {}


def _keyword_needs_boundary(keyword):
    k = (keyword or '').strip()
    if not k or not k.isascii():
        return False
    if len(k) > SHORT_KEYWORD_MAX_LEN:
        return False
    # Multi-word short keywords are already self-limiting.
    return ' ' not in k


def _keyword_pattern(keyword):
    """Compiled word-boundary pattern for a short keyword, cached."""
    pat = _kw_pattern_cache.get(keyword)
    if pat is None:
        k = (keyword or '').strip()
        pat = _re.compile(r'(?<![a-z0-9])' + _re.escape(k) + r'(?![a-z0-9])')
        _kw_pattern_cache[keyword] = pat
    return pat


def kw_match(keyword, text):
    """True if keyword occurs in text.

    Short ASCII keywords must sit on word boundaries. Everything else is a
    plain substring test, unchanged from previous behaviour.

    Note the boundary class is [a-z0-9] rather than \\b: it lets 'uss'
    match "USS Nimitz", "the USS." and "(USS)" while still refusing
    "discuss" and a base64 run. It also means the old trailing-space hack
    in 'uss ' is no longer load-bearing.
    """
    if not keyword or not text:
        return False
    if _keyword_needs_boundary(keyword):
        return bool(_keyword_pattern(keyword).search(text))
    return keyword in text


# ════════════════════════════════════════════════════════════════════════
# SIGNAL DIRECTION (v3.5) - the tracker learns to subtract
# ════════════════════════════════════════════════════════════════════════
# Every signal in this tracker has been additive. "The US Navy has 11
# carriers and can usually deploy 4, and only 1 shipyard can fix them"
# scored 15.0 as power projection. "Navy not returning to damaged Bahrain
# base anytime soon" scored 0.6 as Military Activity. Both articles are
# about American capability being LOST, and both made America look
# stronger.
#
# That is the failure this module fixes. It answers, for each signal:
# is this capability being APPLIED, PULLED BACK, WORN DOWN, or SHOT AT?
#
#   projection   capability applied forward - deploys, surges, arrives,
#                strikes, scrambles, reinforces, goes to alert
#   withdrawal   capability pulled back - departs, returns home, draws
#                down, ends deployment, evacuates
#   degradation  capability structurally impaired - maintenance backlog,
#                shipyard capacity, readiness shortfall, munitions
#                depletion, manning gaps, budget shortfall, materiel
#                condition. Self-inflicted or systemic, not combat.
#   attrition    capability damaged or destroyed BY AN ADVERSARY - struck,
#                hit, shot down, sunk, casualties. Combat loss.
#   neutral      analysis, commentary, history. No directional content.
#
# THIS RELEASE IS ADDITIVE ONLY. Scores are untouched. Every signal gains
# a direction plus the exact cues that produced it, and the scan result
# gains a per-actor ledger. Look at the ledger, judge whether the calls
# are right, and only then decide whether direction should move numbers.
#
# Direction is resolved RELATIVE TO THE SIGNAL'S ACTOR. "Iran Strikes
# Kuwait" is projection for Iran and attrition for Kuwait, from the same
# sentence. That is done by locating the actor's own matched keyword in
# the text and reading what sits on either side of it.
# ════════════════════════════════════════════════════════════════════════

DIRECTION_CLASSES = ('projection', 'withdrawal', 'degradation', 'attrition', 'neutral')

# Directions that mean an actor's usable combat power went DOWN.
DIRECTION_NEGATIVE = ('withdrawal', 'degradation', 'attrition')

# How far either side of the actor keyword to read for subject/object.
DIRECTION_WINDOW_CHARS = 80

# ---- Structural capability loss. Not combat. -------------------------
DEGRADATION_CUES = (
    # maintenance and industrial base
    'maintenance backlog', 'maintenance delay', 'shipyard backlog',
    'only 1 shipyard', 'only one shipyard', 'depot backlog', 'dry dock',
    'drydock', 'in overhaul', 'undergoing repair', 'awaiting repair',
    'yard period', 'out of service', 'sidelined', 'inoperable',
    'industrial base', 'production shortfall', 'behind schedule',
    'delayed delivery', 'cost overrun',
    # readiness
    'readiness shortfall', 'readiness gap', 'readiness crisis',
    'not ready for', 'ready for action', 'unable to deploy',
    'cannot deploy', 'can usually deploy', 'can only deploy',
    'no longer able', 'not returning', 'anytime soon',
    'availability gap', 'carrier gap', 'presence gap',
    # materiel condition
    'rust', 'rusty', 'rusted', 'poor condition', 'disrepair',
    'deteriorat', 'worn out', 'wear and tear',
    "warship's condition", "ship's condition", 'materiel condition',
    'material condition', 'reveal warship', 'state of the ship',
    # people
    'recruiting shortfall', 'retention crisis', 'manning shortfall',
    'undermanned', 'short-handed', 'personnel shortage', 'crew fatigue',
    'sailor fatigue', 'morale', 'worst deployment', 'marathon deployment',
    'extended deployment', 'deployment extended', 'record deployment',
    'back-to-back deployment',
    # munitions and money
    'munitions shortage', 'magazine depletion', 'interceptor shortage',
    'running low on', 'stockpile depletion', 'depleted', 'exhausted its',
    'burn rate', 'expenditure rate',
    'budget cut', 'unfunded priorit', 'funding shortfall',
    'aging fleet', 'block obsolescence', 'end of service life',
    'overstretched', 'overextended', 'stretched thin', 'spread thin',

    # v3.9 - WARTIME SUSTAINMENT BURN.
    # Every degradation cue above this line is PEACETIME READINESS
    # JOURNALISM: shipyard backlogs, rusty hulls, "worst deployment ever".
    # That vocabulary produced 4 degradation signals on Sep 8 and ZERO on
    # Sep 19 -- on day 203 of a war running 6,000 combat sorties, which is
    # the single largest consumer of military capability there is.
    #
    # The tracker was not wrong about the corpus. It was blind to the
    # register. In wartime, capability loss is not reported as "the Navy
    # has a maintenance backlog." It is reported as a shrapnel-damaged
    # tanker getting patched up, interceptors expended faster than they
    # are built, a sortie rate nobody can hold, a deployment extended
    # because there is no relief.
    # battle damage and repair
    'battle damage', 'battle-damaged', 'battle damaged', 'combat damage',
    'shrapnel-damaged', 'shrapnel damage', 'damaged aircraft',
    'damaged jet', 'patched up', 'patched-up', 'field repair',
    'depot repair', 'depot-level', 'cannibaliz', 'salvaged',
    'written off', 'combat loss', 'combat losses', 'damage assessment',
    'out of action', 'non-mission capable', 'not mission capable',
    # munitions and interceptor burn
    'expended', 'rounds fired', 'missiles expended',
    'interceptors expended', 'interceptor inventory', 'magazine depth',
    'vls reload', 'at-sea reload', 'rearm', 'resupply run',
    'inventory drawdown', 'outpacing production', 'faster than we can',
    'cannot keep up with demand', 'production backlog',
    # tempo and sortie strain
    'sortie rate', 'sortie generation', 'flying hours', 'flight hours',
    'operational tempo', 'optempo', 'high tempo', 'unsustainable',
    'cannot sustain', 'sustainment strain', 'strain on the force',
    'straining', 'wear on the fleet',
    # deployment clock
    'extension of deployment', 'tour extended',
    'no relief', 'no replacement', 'gapped', 'back-to-back',
    'held over', 'stop-loss',
    # enablers
    'tanker availability', 'tanker shortage', 'refueling capacity',
    'isr gap', 'lift shortfall', 'spare parts', 'parts shortage',
    'deferred maintenance', 'maintenance deferred',
    # v3.11 - NON-COMBAT LOSS. 'Japan Air Self-Defense Force Recon Drone
    # Crashes into Sea of Japan' is an airframe gone with no adversary
    # involved, which is the exact distinction degradation was split from
    # attrition to carry. It read neutral.
    'crashes into', 'crashed into', 'crash landed', 'crashed near',
    'went down over', 'went down in', 'aircraft crash', 'drone crash',
    'jet crash', 'helicopter crash', 'non-combat loss', 'class a mishap',
    # SERVICE LIFE EXTENSION. 'US Air Force to extend service of B-1, B-2
    # bombers' is the thesis of this whole build in one headline: you
    # extend forty-year-old airframes because the replacements are not
    # arriving. It scored 4.0 and classified as nothing.
    'extend service', 'extend the service', 'service life extension',
    'life extension program', 'sustainment program', 'keep flying until',
    'beyond its planned', 'past its retirement',
    # FORCED HARDENING. 'Al Udeid Goes Underground After Iranian
    # Barrages' - a base that must bury itself has lost operating freedom
    # whether or not anything was destroyed. Placed in degradation so it
    # resolves at step 3, ahead of the barrage reading as force applied.
    'goes underground', 'went underground', 'hardened shelter',
    'forced dispersal', 'dispersal of aircraft',
)

# ---- Money as capability ---------------------------------------------
# v3.10. The Sep 19 corpus carried "US War on Iran Hits $43.6B Price Tag /
# CENTCOM estimates the war with Iran has cost..." and the tracker read it
# as attrition. Nobody shot down $43.6 billion. That is capability the
# United States consumed itself - munitions bought and fired, ops tempo
# funded, readiness deferred to pay for today. Structurally that is
# degradation, and it is the largest single capability-consumption datum
# in the corpus.
#
# The degradation table above reads METAL. This one reads MONEY.
FINANCIAL_BURN_CUES = (
    # cost of the war being fought
    'price tag', 'has cost', 'have cost', 'cost of the war',
    'war has cost', 'cost so far', 'total cost of', 'running cost',
    'costs taxpayers', 'cost to date', 'tab for', 'bill for the war',
    'spent so far', 'has spent', 'burned through', 'burn through',
    # emergency money, which is money that was not planned for
    'supplemental request', 'supplemental appropriation',
    'emergency appropriation', 'emergency funding', 'emergency supplemental',
    'reprogramming request', 'reprogrammed funds', 'drawdown authority',
    'above the budget request', 'over budget', 'cost growth',
    # replacing what was consumed
    'replenishment cost', 'replacement cost', 'cost to replace',
    'restock', 'restocking', 'rebuild the stockpile',
    'replenish stocks', 'replenish inventories',
)

# Money going the OTHER way. This is the hinge of the whole question -
# 'is the United States buying capability, or spending it?' - and the
# machine must not answer it backwards. An appropriation for new hulls is
# capability being BOUGHT; it is not degradation, whatever dollar figure
# sits next to it. When investment language is present the burn read is
# vetoed rather than reversed: buying is not yet its own direction class,
# and inventing one on a hunch would be worse than staying quiet.
FINANCIAL_INVESTMENT_CUES = (
    'contract award', 'awarded a contract', 'contract to build',
    'procurement of', 'procures', 'procurement budget',
    'orders new', 'buys new', 'purchase of new', 'acquisition of new',
    'shipbuilding budget', 'shipbuilding plan', 'multiyear procurement',
    'production increase', 'expand production', 'expanding production',
    'new production line', 'capacity expansion', 'invests in',
    'investment in', 'authorizes the purchase', 'budget request for new',
    'modernization program', 'recapitalization',
)

# ---- Force pulled back ----------------------------------------------
WITHDRAWAL_CUES = (
    'departs', 'departed', 'departure from', 'leaves port', 'left port',
    'returns home', 'returning home', 'return home', 'heads home',
    'sails home', 'homecoming', 'end of deployment', 'ends deployment',
    'concludes deployment', 'completed deployment', 'wraps up deployment',
    'drawdown', 'draw down', 'drawing down', 'withdraw', 'withdrawal of',
    'withdrew', 'pulls out', 'pulled out', 'pulling out', 'pull back',
    'pulled back', 'pulls back', 'exits the', 'exited the',
    'relieved on station', 'ordered home', 'recalled to',
    'reduce its presence', 'reducing its presence', 'scaling back',
    'evacuat', 'ordered departure', 'authorized departure', 'drew down',
    'disengag', 'ceases operations', 'shuts down base', 'closes base',
    'vacated', 'relocated away',
    # v3.10 - bare and plural-subject forms, same rule as PROJECTION_CUES.
    # withdrawal has read 0 signals on every scan of a war in which ships
    # demonstrably rotate home; singular-only vocabulary is a candidate
    # explanation and this tests it.
    'depart the', 'depart from', 'depart port', 'leave port',
    'head home', 'sail home', 'pull out of',
    # 'exit the' rejected in testing: it matched exiting an arms
    # control agreement, which is a policy move, not a force move.
    'end deployment', 'end its deployment', 'relieve on station',
    'rotate home', 'rotates home', 'rotated home',
)

# ---- Force applied ---------------------------------------------------
PROJECTION_CUES = (
    'deploys', 'deployed', 'deploying', 'deployment order', 'orders the',
    'surge', 'surged', 'surging', 'arrives', 'arrived', 'arriving',
    'reinforce', 'reinforcement', 'reinforcing', 'additional forces',
    'more troops', 'additional troops', 'additional aircraft',
    'buildup', 'build-up', 'massing', 'amassing', 'staging',
    'forward deploy', 'forward-deploy', 'repositioned to', 'moves toward',
    'moving toward', 'en route to', 'heading to', 'headed to',
    'bound for', 'sails for', 'sailing for', 'steaming toward',
    'ordered to the', 'dispatched to', 'sent to the',
    'scrambled', 'scramble', 'sortie', 'sorties', 'launched strikes',
    'conducts strikes', 'conducted strikes', 'carried out strikes',
    'intercept', 'intercepts', 'intercepted', 'interception',
    'repelled', 'repel', 'thwarted', 'engaged and destroyed',
    'air defense activated', 'air defences engaged',
    'high alert', 'heightened alert', 'on alert', 'alert status',
    'raised readiness', 'mobiliz', 'activated', 'call-up', 'called up',
    'extended stay', 'remains on station', 'stays on station',
    'exercise', 'drill', 'war game', 'wargame',
    # v3.8 - capability ENTERING SERVICE or under way. The corpus showed
    # "INS Drakon en route from Germany to Israel", "4 Tu-160M bombers
    # conducted launch maneuvers" and a new destroyer joining the fleet all
    # reading neutral. Force arriving is force projected.
    'en route', 'enroute', 'under way', 'underway to', 'maneuvers',
    'manoeuvres', 'launch maneuvers', 'sea trials', 'enters service',
    'entered service', 'joins the fleet', 'joined the fleet', 'inducted',
    'delivered to', 'handed over to', 'took delivery', 'christened',
    'nuclear response system', 'new destroyer', 'operational reality',
    # v3.9 - combined and allied operations. "Carrier USS Abraham Lincoln
    # Operates with Australians in the South China Sea" read neutral at
    # 10.0: a carrier conducting combined ops with an ally is force being
    # applied, and it is the most legible kind.
    'operates with', 'operating with', 'operations with',
    'combined operations', 'joint operations', 'combined exercise',
    'bilateral exercise', 'trilateral', 'interoperability',
    'steams with', 'sails with', 'escorted by', 'integrated with',
    'commissions', 'commissioned', 'joint exercise', 'joint drill',
    'military drill', 'live-fire', 'live fire', 'show of force',
    'freedom of navigation', 'fonop', 'overflight', 'patrols the',
    # v3.10 - BARE AND PLURAL-SUBJECT VERB FORMS.
    # 'USS Abraham Lincoln (CVN 72), USS Frank E. Petersen Jr. (DDG 121)
    # ARRIVE in Guam' does not match 'arrives', 'arrived' or 'arriving'.
    # A plural subject takes the bare verb, and every inflected cue in
    # this table was written for a singular one - so two ships arriving
    # scored nothing where one ship arriving scored. Added by rule rather
    # than by guess: a bare form goes in only where the inflected form is
    # already above it.
    'arrive in', 'arrive at', 'arrive off', 'deploy to', 'deploy for',
    'sail for', 'sail to', 'steam toward', 'steam towards',
    'conduct strikes', 'carry out strikes', 'operate with',
    'steam with', 'sail with', 'enter service', 'join the fleet',
    # v3.11 - GROUND WAR AND SAHEL. Read straight off the neutral sample:
    # 'Mi-24 Hind...conducting close air support for the forces of the
    # Malian army', 'Sudan's Army...claim to have taken 11 areas west of
    # El Obeid', 'US moves MQ-9 Reapers to South America'. The cue tables
    # were built for a naval and air war in the Gulf; the corpus has since
    # grown a Sahel ground war whose vocabulary is territory and air
    # support, not sortie rates.
    'close air support', 'air support for', 'air support to',
    # Bare 'captured' and 'seized' rejected in testing: 'captured on video'
    # and 'seized documents' are not territorial gains. Territory takes an
    # article or an object.
    'have taken', 'has taken', 'seized the', 'seized control',
    'seized territory', 'seized positions', 'captured the',
    'captured from', 'have captured', 'has captured',
    'recaptured', 'retook', 'overran', 'advance on',
    'advanced on', 'ground offensive', 'counteroffensive',
    # NB 'moves to' / 'moved to' deliberately absent: as contiguous
    # strings they match 'moves to condemn' and miss 'moves MQ-9 Reapers
    # to South America'. That shape is handled by PROJECTION_PATTERNS.
    # Rejected in testing, kept here as a record of what NOT to add:
    # 'head to' matched an admiral heading to a hearing, 'patrol the'
    # matched Border Patrol, and 'move toward' matched moving toward
    # a ceasefire. Generic motion verbs need a military object and
    # these have none, so the inflected forms above stand alone.
)

# Bare departure words. Ambiguous on their own - "strike leaves 3 dead"
# is not a withdrawal - so these count ONLY when the text carries no
# combat-loss vocabulary at all.
WITHDRAWAL_CUES_WEAK = (
    'leaves', 'leaving', 'left the', 'exits', 'exited', 'departing',
    'pulls away', 'moves away', 'heads out',
)

# Prepositions of direction. A loss verb separated from the actor by one
# of these is acting on something ELSE that is merely moving toward the
# actor: "destroyed two bombers racing TOWARD Al Udeid" does not mean
# Al Udeid was destroyed.
DIRECTIONAL_PREPOSITIONS = (
    'toward', 'towards', 'near', 'against', 'into', 'over ', 'at the',
    'heading to', 'racing to', 'bound for', 'en route',
)

# Weapons MOVING TOWARD something. This is the mirror image of the
# preposition guard below and must beat it: "destroyed two bombers racing
# toward Al Udeid" means Al Udeid was not hit, but "cruise missiles
# towards U.S. Navy vessels" means the vessels ARE the target. The
# difference is whether the noun travelling toward the actor is a weapon.
WEAPON_APPROACH_CUES = (
    'missiles toward', 'missiles towards', 'missile toward',
    'missile towards', 'rockets toward', 'rockets towards',
    'drones toward', 'drones towards', 'drone toward',
    'launched toward', 'launched towards', 'fired toward',
    'fired towards', 'inbound toward', 'inbound towards',
    'incoming missile', 'incoming drone', 'incoming rocket',
    'aimed at', 'directed at', 'bearing down on',
)

# Periodic roundups and position digests. These are inventories, not
# events. "USNI News Western Pacific Pulse: Sept. 18, 2026" classified as
# PROJECTION at 10.0 -- a weekly list of where ships are is not force
# being applied, and counting it as such inflates projection with the same
# article every week. Same family as "Where Are America's Aircraft
# Carriers Now?". Checked before everything except evacuation.
ROUNDUP_TITLE_CUES = (
    'pulse:', 'fleet tracker', 'fleet and marine tracker',
    'where are america', 'where are the aircraft carriers',
    'roundup', 'round-up', 'rundown', 'weekly digest', 'daily digest',
    'this week in', 'week in review', 'news wrap', 'in pictures',
    'by the numbers', 'explainer:', 'everything we know',
)

# Casualty vocabulary. Its presence means a bare departure word like
# "leaves" is almost certainly "leaves 3 dead", not a ship sailing home.
CASUALTY_WORDS = (
    'dead', 'death toll', 'fatalities', 'bodies', 'martyr', 'victims',
    'killed', 'wounded', 'injured', 'casualt',
)

# Kinetic vocabulary appearing in the SIGNAL'S OWN matched keyword. If the
# thing that made this a signal was "drone strike" or "missile attack",
# force was applied - and if the actor is not the victim, the actor
# applied it. Checked after withdrawal so "carrier strike group departs"
# still reads as a departure.
KINETIC_KEYWORD_TERMS = (
    'strike', 'airstrike', 'air strike', 'attack', 'launch', 'fired',
    'bombard', 'shelling', 'offensive', 'raid', 'incursion', 'shot down',
    'intercept', 'sortie', 'bombing',
)

# Formation names that merely CONTAIN a kinetic word. "Carrier Strike
# Group" is a unit, not an act of violence, and treating it as one turned
# every routine carrier mention into an attack.
KINETIC_KEYWORD_EXCLUSIONS = (
    'carrier strike group', 'strike group', 'strike package', 'strike wing',
    'strike fighter', 'strikemaster', 'strike eagle',
)

# Attribution tails. In "Iran fired missiles at Israel, IRGC says" the
# actor keyword sits AFTER the violence while being neither striker nor
# struck - it is the party doing the talking. One keyword occurrence
# cannot tell us which, so an attribution tail makes the signal neutral
# and says so, rather than guessing. In full article text the actor is
# normally named earlier too, and find() lands on that instead.
ATTRIBUTION_TAIL_CUES = (
    'says', 'said', 'confirmed', 'announced', 'reported', 'stated',
    'claims', 'claimed', 'told', 'tells', 'adds', 'noted',
)
ATTRIBUTION_TAIL_WINDOW = 24

# ---- Combat loss verbs, used with actor position ---------------------
LOSS_VERBS = (
    'hit', 'hits', 'struck', 'strikes', 'strike on', 'strike against',
    'targeted', 'targets', 'targeting', 'damaged', 'destroyed', 'destroys',
    'sank', 'sunk', 'sinks', 'shot down', 'shoot down', 'downed',
    'attacked', 'attacks', 'bombed', 'shelled', 'disabled', 'crippled',
    'casualties', 'killed', 'wounded', 'injured', 'wrecked',
    # 'fired' alone is too ambiguous (officers get fired); only the forms
    # that unambiguously name a weapon and a target.
    'fired at', 'fired on', 'fired ballistic', 'fired missiles',
    'missiles at', 'missile at', 'launched at', 'launched against',
    'rockets at', 'drones at',
    # v3.8 - NOUN + PREPOSITION constructions. The live corpus showed these
    # were the single largest miss: "Missile Launches AT Jordan", "Drone
    # Attack ON Kuwait", "cruise missiles STRIKING Ukrainian forces" all read
    # as neutral, so three countries being actively struck registered as
    # nothing. The verb forms were covered; the noun forms were not.
    'attack on', 'attacks on', 'attack against', 'attacks against',
    'attack upon', 'strikes on', 'strikes against', 'raid on',
    'raids on', 'assault on',
    'launches at', 'launches against', 'launch at',
    'shelling of', 'bombardment of', 'bombing of', 'siege on',
    'striking', 'hitting', 'targeting of', 'incursion into',
    'violation of', 'breach of',
    # Suppression and denial. Capability does not have to be destroyed to
    # be taken away - a strike group that cannot operate is a strike group
    # that is not projecting.
    # v3.11 - from the sample: 'During an ambush on Africa Corps and
    # Malian forces...lead to catastrophic losses', 'dozens of burning
    # vehicles and camps of Malian army'. Irregular-warfare loss language.
    'ambush on', 'ambush of', 'ambushed', 'ambushes',
    'heavy losses', 'catastrophic losses', 'sustained losses',
    'burning vehicles', 'burnt-out', 'wreckage of', 'overrun by',
    'suppress', 'suppressed', 'suppression of', 'pinned down',
    'jammed', 'jamming', 'blockade', 'blockaded', 'besieged', 'siege of',
    'cut off', 'forced to divert', 'forced to withdraw', 'driven off',
    'repulsed', 'denied access', 'grounded',
)

# Phrases meaning the thing just named RECEIVED the blow. These override
# the plain-verb reading, because "US bases come under attack" puts the
# verb after the actor while still making the actor the victim.
RECEIVING_CUES = (
    'come under', 'came under', 'comes under', 'under attack', 'under fire',
    'hit by', 'struck by', 'targeted by', 'attacked by', 'damaged by',
    'destroyed by', 'was hit', 'were hit', 'was struck', 'were struck',
    'was targeted', 'were targeted', 'was damaged', 'were damaged',
    'suffered', 'sustained damage', 'sustained casualties', 'took damage',
    'shot down by', 'downed by', 'lost a', 'lost two', 'lost three',
    'casualties confirmed', 'casualties reported',
)


# ---- RTL and non-Latin script normalisation (v3.11) -------------------
# Written because 13 of 40 signals in the Sep 19 neutral sample were Hebrew or
# Arabic, matched an actor, carried a weight, and were structurally unable to
# classify: the detection layer has spoken Hebrew, Arabic, Farsi and Russian
# since v2.3, and the direction layer added in v3.5 speaks only English.
#
# Normalisation has to happen before any of that vocabulary can fire:
#   Hebrew   - gershayim/geresh vs ASCII quotes in acronyms (צה״ל vs צה"ל),
#              and niqqud vowel points that split otherwise identical words.
#   Arabic   - four alef forms, two yeh forms, teh marbuta, tatweel padding
#              and harakat, any of which break a plain substring match.
#   Farsi    - uses ی U+06CC and ک U+06A9 where Arabic uses ي and ك, so the
#              same word in an Iranian and an Arab outlet is two strings.
#   Digits   - Arabic-Indic and Eastern Arabic numerals, so "צו 8" and its
#              equivalents compare against ASCII.
HEBREW_GERSHAYIM = '\u05f4'
HEBREW_GERESH = '\u05f3'

RTL_CHAR_MAP = {
    # Hebrew punctuation -> ASCII equivalents used by this file's keywords
    HEBREW_GERSHAYIM: '"',
    HEBREW_GERESH: "'",
    '\u05be': '-',          # maqaf
    # Arabic alef family -> bare alef
    '\u0622': '\u0627', '\u0623': '\u0627', '\u0625': '\u0627',
    '\u0671': '\u0627',
    # yeh family (incl. Farsi yeh) -> Arabic yeh
    '\u0649': '\u064a', '\u06cc': '\u064a', '\u06d0': '\u064a',
    # kaf family (incl. Farsi keheh) -> Arabic kaf
    '\u06a9': '\u0643', '\u06aa': '\u0643',
    # heh / teh marbuta
    '\u0629': '\u0647', '\u06c1': '\u0647', '\u06d5': '\u0647',
    # Farsi/Urdu variants
    '\u06be': '\u0647', '\u0624': '\u0648', '\u0626': '\u064a',
    # Arabic-Indic digits
    '\u0660': '0', '\u0661': '1', '\u0662': '2', '\u0663': '3',
    '\u0664': '4', '\u0665': '5', '\u0666': '6', '\u0667': '7',
    '\u0668': '8', '\u0669': '9',
    # Eastern Arabic (Farsi) digits
    '\u06f0': '0', '\u06f1': '1', '\u06f2': '2', '\u06f3': '3',
    '\u06f4': '4', '\u06f5': '5', '\u06f6': '6', '\u06f7': '7',
    '\u06f8': '8', '\u06f9': '9',
}

# Marks that carry no matching value and only fragment substrings: Hebrew
# niqqud and cantillation, Arabic harakat, and the tatweel used to stretch
# Arabic text for justification.
RTL_STRIP_RANGES = (
    (0x0591, 0x05c7),   # Hebrew points and accents
    (0x064b, 0x065f),   # Arabic harakat
    (0x0670, 0x0670),   # superscript alef
    (0x06d6, 0x06ed),   # Quranic marks
    (0x0640, 0x0640),   # tatweel
    (0x200b, 0x200f),   # zero-width and directional marks
    (0x202a, 0x202e),   # bidi embedding controls
)


def _rtl_normalize(text):
    """Fold script variants so one spelling matches all of them."""
    if not text:
        return ''
    out = []
    for ch in str(text):
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in RTL_STRIP_RANGES):
            continue
        out.append(RTL_CHAR_MAP.get(ch, ch))
    return ''.join(out)


# Script ranges used to report WHY a signal could not be classified. The
# threshold exists so one stray glyph in an English headline does not get the
# whole article labelled as foreign-language.
SCRIPT_RANGES = (
    ('hebrew',   ((0x0590, 0x05ff),)),
    ('arabic',   ((0x0600, 0x06ff), (0x0750, 0x077f), (0xfb50, 0xfdff),
                  (0xfe70, 0xfeff))),
    ('cyrillic', ((0x0400, 0x04ff), (0x0500, 0x052f))),
    ('cjk',      ((0x4e00, 0x9fff), (0x3040, 0x30ff))),
)
SCRIPT_MIN_CHARS = 4


def _text_scripts(text):
    """Non-Latin scripts present in text, above a noise threshold."""
    if not text:
        return []
    counts = {}
    for ch in str(text):
        cp = ord(ch)
        for name, ranges in SCRIPT_RANGES:
            if any(lo <= cp <= hi for lo, hi in ranges):
                counts[name] = counts.get(name, 0) + 1
                break
    return sorted(n for n, c in counts.items() if c >= SCRIPT_MIN_CHARS)


def _normalize_direction_text(text):
    """Lowercase and flatten typographic punctuation so cue phrases match.
    Curly quotes are why 'worst deployment' failed to match a headline
    that literally read Worst Deployment."""
    if not text:
        return ''
    out = _rtl_normalize(str(text)).lower()
    for bad, good in (
        ('\u2018', "'"), ('\u2019', "'"), ('\u201c', '"'), ('\u201d', '"'),
        ('\u2013', '-'), ('\u2014', '-'), ('\u00a0', ' '), ('\n', ' '),
        ('\t', ' '),
    ):
        out = out.replace(bad, good)
    return ' '.join(out.split())


def _strip_quotes(text):
    """Drop quote marks so 'worst deployment' still matches a headline
    written as \"worst\" deployment."""
    return (text or '').replace('"', '').replace("'", '')


def _distinct_cues(found):
    """Collapse matched cues that are substrings of other matched cues.

    The cue tables carry several forms of one concept on purpose - 'rust'
    and 'rusted', 'combat loss' and 'combat losses' - so that matching is
    robust. But a threshold that COUNTS cues then sees one rusty hull as
    two independent pieces of evidence, and the >= 2 test in the classifier
    is exactly such a threshold: it decides whether a struck actor is filed
    as degraded rather than attrited. Counting one concept twice flips that
    call on a single phrase.
    """
    out = []
    for c in found:
        if c in out:
            continue
        if any(c != o and c in o for o in found):
            continue
        out.append(c)
    return out


def _find_cues(text, cues):
    """Every cue present in text, in the order the cue table lists them.
    Matched against the text both as-is and with quote marks removed, so
    an embedded quotation cannot hide a cue phrase."""
    bare = _strip_quotes(text)
    return [c for c in cues if c in text or _strip_quotes(c) in bare]


def _actor_windows(text, actor_keyword):
    """Text immediately before and after the actor's matched keyword.
    Returns (before, after). Empty strings if the keyword is not locatable."""
    if not actor_keyword:
        return '', ''
    idx = text.find(actor_keyword)
    if idx < 0:
        return '', ''
    start = max(0, idx - DIRECTION_WINDOW_CHARS)
    end = idx + len(actor_keyword) + DIRECTION_WINDOW_CHARS
    return text[start:idx], text[idx + len(actor_keyword):end]


# =====================================================================
# MULTILINGUAL DIRECTION VOCABULARY (v3.11)
# =====================================================================
# The detection layer has matched Hebrew, Arabic, Farsi and Russian actor and
# asset keywords since v2.3. The direction layer, bolted on at v3.5, matched
# only English. The result was a signal class that could be created, weighted
# and counted but never classified: in the Sep 19 sample, 13 of the 40
# heaviest neutral signals were Hebrew or Arabic.
#
# These tables are defined after _normalize_direction_text so every entry can
# be folded through the same normaliser the article text goes through. Writing
# a cue with a gershayim and matching text with an ASCII quote would otherwise
# fail silently, which is exactly the failure being fixed.
#
# Voice matters and maps onto the existing logic. An ACTIVE strike verb makes
# the actor the striker and belongs in LOSS_VERBS, where a verb near the actor
# reads as force applied. A PASSIVE or receiving construction makes the actor
# the target and belongs in RECEIVING_CUES, which wins outright. Hebrew binyan
# and Arabic form carry that distinction cleanly, so the split is reliable in
# a way English phrasal verbs often are not.

# ---- Force applied or moved into place -------------------------------
PROJECTION_CUES_ML = (
    # Hebrew
    # NB 'תקף' alone is excluded: it also means 'valid / in force', and
    # 'ההסכם תקף' would otherwise read as an air strike.
    'תקיפה', 'תקיפות', 'תקפו', 'תקיפה אווירית', 'גל תקיפות',
    # תקף takes an object or a preposition when it means 'attacked';
    # standing alone it usually means 'valid'. These collocations keep
    # the verb and drop the adjective.
    'תקף את', 'תקף מטרות', 'תקף יעדים', 'תקף ב', 'תקפה את',
    'פשיטה', 'פשיטות', 'חיסול', 'חיסלו', 'סיכול ממוקד',
    'יירט', 'יירטו', 'יירוט', 'שיגר', 'שיגרו', 'שיגור',
    'הפציץ', 'הפצצה', 'הפצצות', 'תמרון', 'תמרון קרקעי', 'כניסה קרקעית',
    # 'חדרו' excluded: also 'his room'.
    'פעילות מבצעית', 'מבצע צבאי', 'השתלטו', 'כבשו', 'חדרו לשטח',
    'פריסה', 'נפרסו', 'תגבור', 'תגבורת', 'תגברו', 'הזעיק', 'הוזעקו',
    'כוננות גבוהה', 'כוננות ספיגה', 'גיוס מילואים', 'צו 8', 'צו שמונה',
    'הוצבו', 'תרגיל משותף', 'אימון משותף',
    # Arabic (written in normalised form: bare alef, arabic yeh/kaf, heh)
    'قصف', 'غاره', 'غارات', 'استهدف', 'استهداف', 'ضربه', 'ضربات',
    'هجوم', 'هجمات', 'اعترض', 'اعتراض', 'اطلاق نار', 'اطلاق صواريخ',
    'اطلقت صواريخ', 'توغل',
    # 'حشد' excluded: الحشد الشعبي (the PMF) would make every Iraq story a
    # force build-up. 'اطلاق' alone excluded: اطلاق سراح is a prisoner
    # release, not a launch.
    'نشر قوات', 'تعزيزات', 'حشد قوات', 'استنفار', 'عمليه عسكريه',
    'مناوره', 'تدريب مشترك', 'مناورات مشتركه',
    # Farsi
    # bare 'حمله' excluded: unambiguous in Farsi, an ordinary word in
    # Arabic, and both scripts normalise to the same string here.
    'حمله موشكي', 'حمله هوايي', 'شليك', 'رزمايش', 'عمليات نظامي',
    'استقرار نيرو',
    # Russian
    # 'наступление' alone is also 'the onset of' (winter). Needs its target.
    'нанесли удар', 'авиаудар', 'атаковали', 'наступление на',
    'перешли в наступление', 'развертывание', 'переброска', 'учения',
)

# ---- Force pulled back -----------------------------------------------
WITHDRAWAL_CUES_ML = (
    # Hebrew
    'נסיגה', 'נסוג', 'נסוגו', 'סיום המבצע', 'סיום הלחימה',
    'חזרו לבסיס', 'שבו לבסיס', 'שחרור מילואים', 'שוחררו ממילואים',
    'צמצום כוחות', 'הוצאת כוחות',
    # Arabic
    'انسحاب', 'انسحب', 'انسحبت', 'اخلاء', 'سحب قوات', 'تقليص القوات',
    # Farsi
    'عقب نشيني', 'عقبنشيني',
    # Russian
    'отвод войск', 'вывод войск', 'отступление', 'отошли',
)

# ---- Structural capability loss --------------------------------------
DEGRADATION_CUES_ML = (
    # Hebrew. שחיקה is the exact word Israeli defence reporting uses for
    # force erosion, and מילואים strain is where Israeli capability loss
    # shows up first - months before any of the materiel vocabulary.
    'שחיקה', 'שחיקת כוחות', 'עייפות קרב', 'מחסור', 'מחסור במלאי',
    # 'אזל' excluded: it sits inside באזל (Basel).
    'מחסור במיירטים', 'מלאי מתדלדל', 'אזלו', 'אזל המלאי',
    'כשירות נמוכה', 'ירידה בכשירות', 'מקורקע', 'מקורקעים',
    'הארכת שירות', 'עומס מבצעי', 'מילואים ממושכים',
    'שירות מילואים מוארך', 'בעיות תחזוקה', 'קיצוץ בתקציב',
    'קיצוץ תקציבי',
    # Arabic
    'نقص الذخيره', 'استنزاف', 'تاكل', 'نقص في الجاهزيه', 'تراجع الجاهزيه',
    # Farsi
    'كمبود', 'فرسودگي',
    # Russian
    'нехватка', 'истощение', 'износ',
)

# ---- Actor took the blow (passive / receiving voice) ------------------
RECEIVING_CUES_ML = (
    # Hebrew - nifal and pual forms put the actor on the receiving end
    'נפגע', 'נפגעו', 'נפגעים', 'הותקף', 'הותקפה', 'הותקפו',
    'ספגו', 'ספג פגיעה', 'נהרג', 'נהרגו', 'נפצע', 'נפצעו',
    'הופל', 'הופלה', 'הופלו', 'אבדות', 'נזק כבד', 'פגיעה ישירה',
    'ספגה מכה', 'נגרם נזק',
    # Arabic
    'اصيب', 'اصابه', 'تعرض ل', 'خسائر', 'قتلي', 'جرحي', 'دمار',
    'اسقطت', 'تم اسقاط',
    # Farsi
    'تلفات', 'خسارت',
    # Russian
    'потери', 'сбит', 'сбили', 'погибли', 'ранены', 'попадание',
)

# ---- Capability supplemented by alliance (v3.11) ---------------------
# Rachel's ask, and it is a different mechanism from everything above: a
# security agreement adds nothing to an order of battle on the day it is
# signed, yet it changes what forces an actor can call on. Israel-KSA and the
# Mecca Pact are the live examples.
#
# NOTE FOR THE ANALYST, deliberately not resolved in code: this is arguably
# not projection at all. It belongs with procurement on the BUYING side of
# "is the United States buying capability, or spending it?" - the same side
# FINANCIAL_INVESTMENT_CUES sits on. Routing it to projection here keeps the
# five existing classes intact and makes the signal visible, but it does
# inflate projection_share, which feeds the capability-rhetoric gap cell.
# Creating a sixth direction class is a doctrine decision, not a coding one.
ALLIANCE_CUES = (
    # English
    'defense pact', 'defence pact', 'security agreement', 'security pact',
    'mutual defense', 'mutual defence', 'defense treaty', 'defence treaty',
    'defense cooperation agreement', 'strategic partnership agreement',
    'mecca pact', 'collective defense', 'collective defence',
    'status of forces agreement', 'basing agreement', 'basing rights',
    'joint defense council', 'security guarantee', 'security guarantees',
    'defense accord', 'defense agreement', 'defence agreement',
    'military cooperation agreement', 'arms package', 'security assistance',
    # Hebrew
    'הסכם ביטחוני', 'ברית הגנה', 'הסכם הגנה', 'שיתוף פעולה ביטחוני',
    'הסכם אסטרטגי', 'ערבות ביטחונית', 'הסכם ביטחון',
    # Arabic
    'اتفاق امني', 'اتفاقيه امنيه', 'ميثاق مكه', 'تحالف دفاعي',
    'الدفاع المشترك', 'اتفاقيه دفاع مشترك', 'التعاون الدفاعي',
    'ضمانات امنيه', 'اتفاقيه عسكريه',
    # Farsi
    'پيمان دفاعي', 'توافق امنيتي',
    # Russian
    'оборонный пакт', 'соглашение о безопасности',
)


# ---- Gapped movement constructions (v3.11) ---------------------------
# Every other cue in this file is a contiguous substring, which cannot express
# "VERB ... to PLACE" when the payload sits in the middle. 'US moves MQ-9
# Reapers to South America' is force being projected, stated in the most
# ordinary headline shape in defence reporting, and it read neutral.
#
# The negative lookahead is what keeps this honest: 'moves to condemn' and
# 'moved to dismiss' put 'to' immediately after the verb and are political
# verbs, not movement. Requiring a payload of real length between the verb and
# 'to' separates a squadron being sent somewhere from a government moving to
# do something.
PROJECTION_PATTERNS = (
    re.compile(
        r'\b(?:moves?|moved|moving|sends?|sent|sending|transfers?|'
        r'transferred|transferring|shifts?|shifted|repositions?|'
        r'repositioned|relocates?|relocated|dispatch(?:es|ed)?|'
        r'redeploys?|redeployed|flies|flew|ferries|ferried)\b\s+'
        r'(?!to\b|toward|towards)[^.;:!?]{3,70}?\bto\b',
        re.IGNORECASE),
)


def _find_patterns(text, patterns):
    """Regex cues, reported like _find_cues so evidence reads the same."""
    hits = []
    for pat in patterns:
        m = pat.search(text or '')
        if m:
            hits.append(' '.join(m.group(0).split())[:60])
    return hits


def _norm_cue_table(cues):
    """Fold a cue table through the same normaliser article text goes through.

    Without this a cue written with a gershayim, a hamza-carrying alef or a
    Farsi yeh would never match normalised text, and would do so silently.
    """
    seen = []
    for c in cues:
        n = _normalize_direction_text(c)
        if n and n not in seen:
            seen.append(n)
    return tuple(seen)


ALLIANCE_CUES = _norm_cue_table(ALLIANCE_CUES)
PROJECTION_CUES = PROJECTION_CUES + _norm_cue_table(PROJECTION_CUES_ML)
WITHDRAWAL_CUES = WITHDRAWAL_CUES + _norm_cue_table(WITHDRAWAL_CUES_ML)
DEGRADATION_CUES = DEGRADATION_CUES + _norm_cue_table(DEGRADATION_CUES_ML)
RECEIVING_CUES = RECEIVING_CUES + _norm_cue_table(RECEIVING_CUES_ML)


def classify_signal_direction(text, actor_keyword, asset_id=None,
                              signal_keyword=''):
    """Direction of one signal, relative to that signal's own actor.

    text           full article text (title + description + content)
    actor_keyword  the actor keyword that matched, used to locate the
                   actor in the sentence and read subject vs object
    asset_id       asset category id, so evacuation short-circuits
    signal_keyword the asset keyword that matched, e.g. 'drone strike'

    Returns (direction, evidence_dict). Never raises; unknown reads
    'neutral', which is the honest answer when nothing matched.
    """
    text = _normalize_direction_text(text)
    actor_keyword = _normalize_direction_text(actor_keyword)
    signal_keyword = _normalize_direction_text(signal_keyword)

    before, after = _actor_windows(text, actor_keyword)
    positionless = not (before or after)
    if positionless:
        # Actor keyword not locatable (it matched in a field we were not
        # handed). Read the whole text rather than reading nothing.
        near = text
    else:
        near = f"{before} {after}"

    deg_cues = _find_cues(text, DEGRADATION_CUES)
    loss_anywhere = _find_cues(text, LOSS_VERBS)

    # v3.10 - financial burn counts as structural capability loss, but
    # only where the money is being CONSUMED. Procurement language vetoes
    # it: an appropriation for new hulls is capability bought, not spent.
    fin_burn = _find_cues(text, FINANCIAL_BURN_CUES)
    fin_invest = _find_cues(text, FINANCIAL_INVESTMENT_CUES)
    if fin_invest:
        fin_burn = []

    evidence = {
        'degradation_cues': deg_cues[:6],
        'withdrawal_cues': _find_cues(text, WITHDRAWAL_CUES)[:6],
        'projection_cues': _find_cues(text, PROJECTION_CUES)[:6],
        'loss_verbs_near_actor': _find_cues(near, LOSS_VERBS)[:6],
        'receiving_cues_near_actor': _find_cues(near, RECEIVING_CUES)[:6],
        'weapon_approach_near_actor': _find_cues(near, WEAPON_APPROACH_CUES)[:4],
        'actor_keyword_located': not positionless,
        'financial_burn_cues': fin_burn[:6],
    }
    # v3.11 - record the script so an unclassified signal can say whether
    # the vocabulary missed it or the alphabet did.
    _scripts = _text_scripts(text)
    if _scripts:
        evidence['scripts'] = _scripts
    if fin_invest:
        evidence['financial_investment_cues'] = fin_invest[:4]
        evidence['financial_burn_vetoed'] = (
            'cost language present but the text reads as procurement, so '
            'the spend is capability being bought rather than consumed')
    if positionless:
        evidence['positionless'] = ('actor keyword not found in text; '
                                    'subject/object not resolved')

    def _done(direction, secondary=None, **extra):
        evidence['direction_secondary'] = secondary
        evidence.update(extra)
        return direction, evidence

    # 1. Evacuation is unambiguous withdrawal whatever else is in the text.
    if asset_id == 'base_evacuation':
        return _done('withdrawal')

    # 1b. Periodic roundups are inventories, not events. Checked early so a
    #     digest that happens to mention a strike is not read as one.
    roundup = _find_cues(text, ROUNDUP_TITLE_CUES)
    if roundup:
        return _done('neutral', roundup_cues=roundup[:3],
                     neutral_reason='periodic roundup or position digest, '
                                    'not a discrete event')

    # 2. Did this actor TAKE a blow? Receiving language after the actor wins
    #    outright. A loss verb in FRONT of the actor also makes the actor the
    #    object, unless a preposition of direction sits between them - then
    #    the verb acted on something merely moving toward the actor.
    receiving_after = _find_cues(after, RECEIVING_CUES) if not positionless else []
    loss_before = _find_cues(before, LOSS_VERBS) if not positionless else []
    weapon_approach = _find_cues(before, WEAPON_APPROACH_CUES) if not positionless else []
    actor_is_object = bool(receiving_after)

    if not actor_is_object and weapon_approach:
        # A weapon travelling toward the actor makes the actor the target,
        # and beats the preposition guard below.
        actor_is_object = True
        evidence['weapon_approach'] = weapon_approach[:3]
    elif not actor_is_object and loss_before:
        # Take the tail after the loss verb that appears LATEST IN THE TEXT,
        # not last in the cue table. Getting this wrong reads the wrong
        # clause and flips the call.
        last_idx = -1
        last_verb = ''
        for verb in loss_before:
            idx = before.rfind(verb)
            if idx > last_idx:
                last_idx, last_verb = idx, verb
        tail = before[last_idx + len(last_verb):] if last_idx >= 0 else before
        if not any(p in tail for p in DIRECTIONAL_PREPOSITIONS):
            actor_is_object = True
        else:
            evidence['object_elsewhere'] = (
                'loss verb separated from actor by a preposition of direction')

    # An attribution tail means the actor is the SPEAKER, not a participant.
    if actor_is_object and not receiving_after:
        tail_probe = after[:ATTRIBUTION_TAIL_WINDOW]
        if any(f' {c}' in f' {tail_probe}' for c in ATTRIBUTION_TAIL_CUES):
            actor_is_object = False
            evidence['attribution_tail'] = (
                'actor keyword sits in an attribution clause, so striker vs '
                'struck cannot be resolved from this occurrence')
            return _done('neutral')

    if actor_is_object:
        reason = ('receiving language after actor' if receiving_after
                  else 'loss verb immediately before actor')
        # A base can be struck AND be out of action. Where the text is
        # dominated by sustained-unavailability language the standing state
        # is the more useful primary read; the strike survives as secondary.
        if len(_distinct_cues(deg_cues)) >= 2:
            return _done('degradation', 'attrition',
                         attrition_reason=reason,
                         degradation_reason=f'{len(_distinct_cues(deg_cues))} distinct '
                                            f'sustained-capability cues outweigh a '
                                            f'single strike reference')
        if fin_burn:
            # A war-cost story often trips a loss verb ('war HITS $43.6B')
            # and would otherwise be filed as a blow struck by an enemy.
            # Self-consumed capability is degradation; the strike
            # reference survives as the secondary read.
            return _done('degradation', 'attrition',
                         attrition_reason=reason,
                         degradation_reason='financial burn: capability '
                                            'consumed rather than destroyed')
        return _done('attrition', 'degradation' if deg_cues else None,
                     attrition_reason=reason)

    # 3. Structural capability loss. Ahead of projection because a readiness
    #    story is usually stuffed with deployment vocabulary.
    if deg_cues:
        return _done('degradation')
    if fin_burn:
        return _done('degradation',
                     degradation_reason='financial burn: capability funded '
                                        'and consumed, not destroyed')

    # 4. Actor is in a kinetic event and is NOT the victim, so it is the one
    #    applying force. This requires knowing WHERE the actor sits in the
    #    sentence. If the actor could not be located, we cannot tell the
    #    striker from the struck, and guessing would be worse than silence -
    #    so the signal reads neutral and says why.
    if _find_cues(near, LOSS_VERBS):
        if positionless:
            return _done('neutral',
                         unresolved_kinetic='combat vocabulary present but the '
                                            'actor could not be located, so '
                                            'striker vs struck is unresolved')
        return _done('projection',
                     projection_reason='loss verb near actor, actor not the object')

    # 5. Withdrawal before projection: "departs" and "arrives" often share a
    #    headline, and leaving is the more consequential of the two.
    if evidence['withdrawal_cues']:
        return _done('withdrawal')

    # 6. The keyword that CREATED this signal was itself kinetic. Formation
    #    names are stripped first so "carrier strike group" is not read as
    #    an act of violence.
    if not positionless:
        kw_probe = signal_keyword
        for excl in KINETIC_KEYWORD_EXCLUSIONS:
            kw_probe = kw_probe.replace(excl, ' ')
        kinetic = [t for t in KINETIC_KEYWORD_TERMS if t in kw_probe]
        if kinetic:
            return _done('projection', kinetic_keyword=kinetic[:3],
                         projection_reason='signal keyword is itself kinetic')

    if evidence['projection_cues']:
        return _done('projection')

    # 6a. v3.11 - 'moves X to Y' and friends.
    moved = _find_patterns(text, PROJECTION_PATTERNS)
    if moved:
        return _done('projection', movement_pattern=moved[:2],
                     projection_reason='force moved to a named place')

    # 6b. v3.11 - capability supplemented by alliance. Checked after every
    #     form of actual force so a pact mentioned in a strike story never
    #     outranks the strike.
    alliance = _find_cues(text, ALLIANCE_CUES)
    if alliance:
        return _done('projection', alliance_cues=alliance[:4],
                     capability_source='alliance',
                     projection_reason='security agreement or defence pact: '
                                       'capability supplemented by partner '
                                       'forces rather than applied')

    # 7. Bare departure words, trusted only when nothing in the text reads as
    #    combat or casualties ("strike leaves 3 dead" is not a withdrawal).
    if not loss_anywhere and not _find_cues(text, CASUALTY_WORDS):
        weak = _find_cues(text, WITHDRAWAL_CUES_WEAK)
        if weak:
            return _done('withdrawal', withdrawal_cues_weak=weak[:4])

    return _done('neutral')


# How many neutral signals to publish for inspection. The neutral bucket
# is ~85% of the corpus and is the reason classified_share sits under the
# abstention gate; it cannot be fixed while it is unreadable.
NEUTRAL_SAMPLE_SIZE = 40

MIL_CAPABILITY_FP_KEY = 'military:{actor}:capability_direction'
MIL_CAPABILITY_SUMMARY_KEY = 'military:capability_direction:summary'


def write_capability_fingerprints(ledger, total_signals=0):
    """Publish the signed capability read to Redis for cross-backend consumers.

    This is the MIL half of the capability-rhetoric join. The US rhetoric
    tracker reads military:us:capability_direction and sets it against
    measured rhetoric intensity. Neither sensor can see that on its own.

    Writes one fingerprint per actor carrying directional signal, plus a
    summary. Silent on failure: a Redis outage must never break a scan.
    """
    if not isinstance(ledger, dict):
        return 0

    per_actor = ledger.get('per_actor') or {}
    written = 0
    for actor_id, row in per_actor.items():
        if not isinstance(row, dict):
            continue
        projection = row.get('projection_score', 0)
        loss = row.get('loss_score', 0)
        if (projection + loss) <= 0:
            continue  # nothing directional to publish
        payload = {
            'actor':             actor_id,
            'actor_name':        row.get('actor_name', actor_id),
            'net_score':         row.get('net_score', 0),
            'projection_score':  projection,
            'loss_score':        loss,
            'projection_share':  row.get('projection_share'),
            'reading':           row.get('reading', ''),
            'by_direction': {
                d: {'count': row.get(d, {}).get('count', 0),
                    'score': row.get(d, {}).get('score', 0.0)}
                for d in DIRECTION_CLASSES if isinstance(row.get(d), dict)
            },
            'examples':          row.get('examples', {}),
            'classified_share':  ledger.get('classified_share'),
            'total_signals':     total_signals,
            'tracker_version':   MILITARY_TRACKER_VERSION,
        }
        if _redis_fp_set(MIL_CAPABILITY_FP_KEY.format(actor=actor_id), payload):
            written += 1

    _redis_fp_set(MIL_CAPABILITY_SUMMARY_KEY, {
        'totals':            ledger.get('totals'),
        'classified_share':  ledger.get('classified_share'),
        'most_degraded':     ledger.get('most_degraded'),
        'actors_published':  written,
        'total_signals':     total_signals,
        'tracker_version':   MILITARY_TRACKER_VERSION,
    })
    return written


def _neutral_reason(evidence):
    """Why one signal failed to classify, in a form that groups.

    Returns a short stable label rather than free text, so the counts are
    countable. 'no directional cue matched' means the vocabulary missed it
    and is fixable; 'actor not locatable' and 'attribution clause' mean the
    text genuinely does not say who did what, and no cue table will help.
    Telling those apart is the whole point of publishing this.
    """
    ev = evidence if isinstance(evidence, dict) else {}
    if ev.get('roundup_cues'):
        return 'periodic roundup, not a discrete event'
    if ev.get('attribution_tail'):
        return 'actor is the speaker, not a participant'
    if ev.get('unresolved_kinetic'):
        return 'combat language but actor not locatable'
    if ev.get('actor_keyword_located') is False:
        return 'actor keyword not found in text'
    if ev.get('financial_burn_vetoed'):
        return 'cost language read as procurement'
    # v3.11 - separate 'our phrasing missed it' from 'our alphabet did'.
    # Before this, both reported 'no directional cue matched', which would
    # have sent the next vocabulary pass writing English cues for a pile
    # that was a third unreadable.
    scripts = ev.get('scripts')
    if scripts:
        return 'no cue matched - text in %s' % '+'.join(scripts)
    return 'no directional cue matched'


def build_direction_ledger(signals):
    """Per-actor projection-vs-loss accounting over a list of signals.

    net_score = projection - (withdrawal + degradation + attrition).
    A negative net means this actor's week reads as capability going DOWN,
    however loud the headlines were.
    """
    per_actor = {}
    totals = {d: {'count': 0, 'score': 0.0} for d in DIRECTION_CLASSES}
    neutral_pool = []
    neutral_reasons = {}

    for sig in signals:
        actor = sig.get('actor') or 'unknown'
        direction = sig.get('direction') or 'neutral'
        if direction not in totals:
            direction = 'neutral'
        try:
            weight = float(sig.get('weight') or 0)
        except (TypeError, ValueError):
            weight = 0.0

        row = per_actor.setdefault(actor, {
            'actor': actor,
            'actor_name': sig.get('actor_name', actor),
            **{d: {'count': 0, 'score': 0.0} for d in DIRECTION_CLASSES},
            'total_score': 0.0,
            'total_count': 0,
            'examples': {},
        })
        row[direction]['count'] += 1
        row[direction]['score'] = round(row[direction]['score'] + weight, 2)
        row['total_score'] = round(row['total_score'] + weight, 2)
        row['total_count'] += 1

        totals[direction]['count'] += 1
        totals[direction]['score'] = round(totals[direction]['score'] + weight, 2)

        # v3.10 - keep the neutral bucket inspectable. Every signal that
        # failed to classify records WHY, so the next vocabulary pass is
        # driven by what the corpus actually contains instead of by a
        # guess about what it might contain.
        if direction == 'neutral':
            why = _neutral_reason(sig.get('direction_evidence'))
            neutral_reasons[why] = neutral_reasons.get(why, 0) + 1
            neutral_pool.append({
                'weight': round(weight, 2),
                'actor': actor,
                'asset': sig.get('asset', ''),
                'keyword': sig.get('keyword', ''),
                'title': (sig.get('article_title') or '')[:120],
                'source': sig.get('source', ''),
                'reason': why,
            })

        # Keep the heaviest example of each direction so the call is auditable.
        ex = row['examples'].get(direction)
        if ex is None or weight > ex.get('weight', 0):
            row['examples'][direction] = {
                'weight': round(weight, 2),
                'title': (sig.get('article_title') or '')[:110],
                'source': sig.get('source', ''),
                'cues': sig.get('direction_evidence', {}),
            }

    for actor, row in per_actor.items():
        projection = row['projection']['score']
        loss = sum(row[d]['score'] for d in DIRECTION_NEGATIVE)
        row['projection_score'] = round(projection, 2)
        row['loss_score'] = round(loss, 2)
        row['net_score'] = round(projection - loss, 2)
        denom = projection + loss
        row['projection_share'] = round(projection / denom, 3) if denom else None
        if denom == 0:
            row['reading'] = 'no directional signal this scan'
        elif row['net_score'] > 0:
            row['reading'] = 'capability reads as being applied'
        elif row['net_score'] < 0:
            row['reading'] = 'capability reads as being lost'
        else:
            row['reading'] = 'projection and loss in balance'

    neutral_pool.sort(key=lambda r: r['weight'], reverse=True)
    ranked = sorted(per_actor.values(), key=lambda r: r['net_score'])

    return {
        'note': ('Additive only in v3.5 - direction is recorded but does not '
                 'change any score. net_score = projection minus '
                 '(withdrawal + degradation + attrition).'),
        'totals': totals,
        'per_actor': per_actor,
        'most_degraded': [
            {'actor': r['actor'], 'net_score': r['net_score'],
             'projection': r['projection_score'], 'loss': r['loss_score'],
             'reading': r['reading']}
            for r in ranked if r['loss_score'] > 0
        ][:10],
        'classified_share': round(
            1 - (totals['neutral']['count'] / max(1, sum(t['count'] for t in totals.values()))), 3
        ),
        # v3.10 - the unread 85%, heaviest first, with a reason each.
        'neutral_sample': neutral_pool[:NEUTRAL_SAMPLE_SIZE],
        'neutral_reason_counts': dict(sorted(
            neutral_reasons.items(), key=lambda kv: kv[1], reverse=True)),
        'neutral_total': len(neutral_pool),
    }


def analyze_article_military(article):
    """Analyze a single article for military deployment signals."""
    # v3.6 - clean BEFORE matching. Raw RSS description is HTML carrying the
    # encoded article link, and keywords were matching inside those base64
    # blobs. The fetcher also copies description into content, so every blob
    # was matched twice.
    title = clean_match_text(article.get('title'))
    description = clean_match_text(article.get('description'))
    content = clean_match_text(article.get('content'))
    text = f"{title} {description} {content}"

    result = {
        'actors': set(),
        'asset_types': set(),
        'regions': set(),
        'targets': set(),
        'score': 0,
        'signals': [],
        'location_multiplier': 1.0,
        'hotspot_location': None
    }

    loc_multiplier, hotspot = get_location_multiplier(text)
    result['location_multiplier'] = loc_multiplier
    result['hotspot_location'] = hotspot

    for actor_id, actor_data in MILITARY_ACTORS.items():
        for keyword in actor_data['keywords']:
            if kw_match(keyword, text):
                result['actors'].add(actor_id)
                actor_weight = actor_data['weight']

                asset_matched = False
                for asset_id, asset_data in ASSET_CATEGORIES.items():
                    for asset_kw in asset_data['keywords']:
                        if kw_match(asset_kw, text):
                            result['asset_types'].add(asset_id)

                            if asset_id == 'base_evacuation':
                                asset_weight, evac_subtype = get_evacuation_subtype_weight(text)
                            else:
                                asset_weight = asset_data['weight']
                                evac_subtype = None

                            signal_score = asset_weight * actor_weight * loc_multiplier

                            signal_entry = {
                                'actor': actor_id,
                                'actor_name': actor_data['name'],
                                'actor_flag': actor_data['flag'],
                                'asset': asset_id,
                                'asset_label': asset_data['label'],
                                'asset_icon': asset_data['icon'],
                                'keyword': asset_kw,
                                'actor_keyword': keyword,
                                'weight': round(signal_score, 2),
                                'base_weight': asset_weight,
                                'location_multiplier': loc_multiplier,
                                'hotspot_location': hotspot,
                                'article_title': article.get('title', '')[:120],
                                'article_url': article.get('url', ''),
                                'source': article.get('source', {}).get('name', 'Unknown'),
                                'published': article.get('publishedAt', '')
                            }

                            if evac_subtype:
                                signal_entry['evacuation_subtype'] = evac_subtype

                            # v3.5 - direction, additive only (score untouched)
                            _dir, _dir_ev = classify_signal_direction(
                                text, keyword, asset_id, asset_kw)
                            signal_entry['direction'] = _dir
                            signal_entry['direction_evidence'] = _dir_ev

                            result['signals'].append(signal_entry)
                            result['score'] += signal_score
                            asset_matched = True
                            break

                    if asset_matched:
                        break

                if not asset_matched:
                    signal_score = actor_weight * 1.0 * loc_multiplier
                    result['signals'].append({
                        'actor': actor_id,
                        'actor_name': actor_data['name'],
                        'actor_flag': actor_data['flag'],
                        'asset': 'unspecified',
                        'asset_label': 'Military Activity',
                        'asset_icon': '⚠️',
                        'keyword': keyword,
                        'actor_keyword': keyword,
                        'weight': round(signal_score, 2),
                        'base_weight': 1.0,
                        'location_multiplier': loc_multiplier,
                        'hotspot_location': hotspot,
                        'article_title': article.get('title', '')[:120],
                        'article_url': article.get('url', ''),
                        'source': article.get('source', {}).get('name', 'Unknown'),
                        'published': article.get('publishedAt', ''),
                        **dict(zip(('direction', 'direction_evidence'),
                                   classify_signal_direction(text, keyword,
                                                             'unspecified', keyword)))
                    })
                    result['score'] += signal_score

                break

    for aor, bases in ASSET_TARGET_MAPPING.items():
        for base_name, base_data in bases.items():
            if kw_match(base_name.lower(), text):
                result['regions'].add(base_name)
                for target in base_data['targets']:
                    result['targets'].add(target)

    result['actors'] = list(result['actors'])
    result['asset_types'] = list(result['asset_types'])
    result['regions'] = list(result['regions'])
    result['targets'] = list(result['targets'])
    result['score'] = round(result['score'], 2)

    return result


def calculate_regional_tension_multiplier(active_actors):
    """Multiple militaries moving simultaneously = compounding tension."""
    count = len(active_actors)
    if count <= 1:
        return 1.0
    elif count == 2:
        return 1.15
    elif count == 3:
        return 1.3
    elif count == 4:
        return 1.45
    else:
        return 1.5 + (0.05 * (count - 5))


def determine_alert_level(score):
    """Convert raw score to alert level"""
    if score >= ALERT_THRESHOLDS['surge']['min_score']:
        return 'surge'
    elif score >= ALERT_THRESHOLDS['high']['min_score']:
        return 'high'
    elif score >= ALERT_THRESHOLDS['elevated']['min_score']:
        return 'elevated'
    else:
        return 'normal'


# ========================================
# MAIN SCAN FUNCTION
# ========================================

def scan_military_posture(days=7, force_refresh=False):
    """Main entry point."""

    if not force_refresh and is_military_cache_fresh():
        cache = load_military_cache()
        cache['cached'] = True
        print("[Military Tracker] Returning fresh cached data")
        return cache

    if not force_refresh:
        stale_cache = load_military_cache()
        if stale_cache and 'cached_at' in stale_cache:
            stale_cache['cached'] = True
            stale_cache['stale'] = True
            _trigger_background_scan(days)
            print("[Military Tracker] Returning stale cache, background refresh triggered")
            return stale_cache

        print("[Military Tracker] No cache found, returning skeleton. Periodic scan will populate.")
        return _build_empty_skeleton()

    return _run_full_scan(days)


def _trigger_background_scan(days=7):
    """Start a background scan if one isn't already running."""
    global _background_scan_running

    with _background_scan_lock:
        if _background_scan_running:
            print("[Military Tracker] Background scan already in progress, skipping")
            return
        _background_scan_running = True

    def _do_scan():
        global _background_scan_running
        try:
            print("[Military Tracker] Background scan starting...")
            _run_full_scan(days)
        except Exception as e:
            print(f"[Military Tracker] Background scan error: {e}")
        finally:
            with _background_scan_lock:
                _background_scan_running = False

    thread = threading.Thread(target=_do_scan, daemon=True)
    thread.start()


def _run_full_scan(days=7):
    """Execute the full scan pipeline."""

    print(f"[Military Tracker] Starting fresh scan ({days} days)...")
    scan_start = time.time()

    print("[Military Tracker] Phase 1: Fetching data...")
    _health_reset()

    rss_articles = fetch_all_defense_rss()
    _health_note('defense_rss', articles=len(rss_articles),
                 http_status=200 if rss_articles else None)
    gdelt_articles = fetch_all_gdelt_military(days)
    newsapi_articles = fetch_all_newsapi_military(days)
    reddit_posts = fetch_reddit_military(days)

    # Brave tertiary fallback — fires only when GDELT+NewsAPI underperformed.
    # Threshold: <10 combined articles signals upstream failure or rate limit.
    brave_articles = []
    if (len(gdelt_articles) + len(newsapi_articles)) < 10:
        print(f"[Military Tracker] Upstream sparse (GDELT={len(gdelt_articles)}, NewsAPI={len(newsapi_articles)}); firing Brave fallback")
        brave_articles = fetch_all_brave_military(days)
    else:
        print(f"[Military Tracker] Upstream healthy (GDELT={len(gdelt_articles)}, NewsAPI={len(newsapi_articles)}); skipping Brave")
        # Brave never ran. The old source_health reported that as 'ZERO',
        # which reads as broken when the truth is that nobody asked.
        _health_note('brave', configured=bool(BRAVE_API_KEY),
                     note=f'not attempted: gdelt={len(gdelt_articles)} + '
                          f'newsapi={len(newsapi_articles)} '
                          f'(fallback fires below 10)')
        _SOURCE_HEALTH['brave']['attempts'] = 0

    telegram_articles = []
    if not TELEGRAM_AVAILABLE:
        _health_note('telegram', configured=False,
                     note='module import failed at startup')
    if TELEGRAM_AVAILABLE:
        _tg_t0 = time.time()
        try:
            telegram_msgs = fetch_telegram_signals(hours_back=days*24, include_extended=True)
            if telegram_msgs:
                for msg in telegram_msgs:
                    telegram_articles.append({
                        'title': msg.get('title', '')[:200],
                        'description': msg.get('title', '')[:500],
                        'url': msg.get('url', ''),
                        'publishedAt': msg.get('published', ''),
                        'source': {'name': msg.get('source', 'Telegram')},
                        'content': msg.get('title', '')[:500],
                        'feed_type': 'telegram'
                    })
                print(f"[Military Tracker] Telegram: {len(telegram_articles)} messages")
            _health_note('telegram', articles=len(telegram_articles),
                         duration_ms=(time.time() - _tg_t0) * 1000)
        except Exception as e:
            print(f"[Military Tracker] Telegram error: {str(e)[:100]}")
            _health_note('telegram', error=e,
                         duration_ms=(time.time() - _tg_t0) * 1000)

    # ─────────────────────────────────────────────────────────────
    # Nitter OSINT accounts — DEPRECATED May 6 2026
    # Nitter has been chronically failing across all theaters.
    # Migrating to BlueSky aggregator below. Code preserved (commented)
    # for emergency rollback if BlueSky migration has issues.
    # ─────────────────────────────────────────────────────────────
    # nitter_articles = []
    # try:
    #     nitter_posts = fetch_nitter_military(days=days)
    #     for p in nitter_posts:
    #         nitter_articles.append({
    #             'title':       p.get('title', '')[:200],
    #             'description': p.get('title', '')[:500],
    #             'url':         p.get('url', ''),
    #             'publishedAt': p.get('publishedAt', ''),
    #             'source':      p.get('source', {'name': 'Nitter'}),
    #             'content':     p.get('title', '')[:500],
    #             'feed_type':   'nitter',
    #         })
    #     print(f"[Military Tracker] Nitter: {len(nitter_articles)} posts")
    # except Exception as e:
    #     print(f"[Military Tracker] Nitter error: {str(e)[:100]}")
    nitter_articles = []  # legacy — kept for downstream concatenation compat

    # ─────────────────────────────────────────────────────────────
    # BlueSky OSINT — global '*'-scoped accounts from regional modules
    # Aggregates POTUS, SecDef, INDOPACOM, OSINT Defender, WarTranslated,
    # State Dept, etc. — accounts marked with '*' target scope across the
    # bluesky_signals_asia, bluesky_signals_me, bluesky_signals_wha modules.
    # Theatre-specific accounts (e.g. NK News for DPRK) are pulled by
    # the rhetoric trackers, not here.
    # ─────────────────────────────────────────────────────────────
    bluesky_articles = []
    _bs_t0 = time.time()
    try:
        bluesky_articles = fetch_bluesky_military_aggregated(days=days)
        _health_note('bluesky', articles=len(bluesky_articles),
                     duration_ms=(time.time() - _bs_t0) * 1000)
        print(f"[Military Tracker] BlueSky: {len(bluesky_articles)} posts from global-scoped accounts")
    except Exception as e:
        print(f"[Military Tracker] BlueSky error (non-fatal): {str(e)[:100]}")
        _health_note('bluesky', error=e,
                     duration_ms=(time.time() - _bs_t0) * 1000)

    all_articles = rss_articles + gdelt_articles + newsapi_articles + reddit_posts + telegram_articles + nitter_articles + bluesky_articles + brave_articles

    # One line per unhealthy source, so a dead feed is visible in the boot
    # log without anyone having to inspect a payload.
    for _hname, _hrec in sorted(_health_report().items()):
        if _hrec['status'] != 'ok':
            print(f"[Military Tracker HEALTH] {_hname}: {_hrec['status']} "
                  f"(articles={_hrec['articles']}, attempts={_hrec['attempts']}, "
                  f"http={_hrec['http_statuses'] or '-'})")

    _pre_filter_count = len(all_articles)
    all_articles, recency_stats = filter_articles_by_recency(all_articles, days)
    print(f"[Military Tracker] Recency gate ({days}d): {_pre_filter_count} -> "
          f"{recency_stats['kept']} kept, {recency_stats['dropped_stale']} stale dropped, "
          f"{recency_stats['undated_kept']} undated kept")
    if recency_stats['oldest_dropped']:
        print(f"[Military Tracker]    Oldest dropped: {recency_stats['oldest_dropped']}")

    # v3.4 - LAYER 0: collapse the same article arriving through several feeds
    _pre_dedupe_count = len(all_articles)
    all_articles, article_dedupe_stats = deduplicate_articles(all_articles)
    print(f"[Military Tracker] Article dedupe: {_pre_dedupe_count} -> "
          f"{article_dedupe_stats['kept']} unique "
          f"({article_dedupe_stats['dropped_same_url']} same URL, "
          f"{article_dedupe_stats['dropped_same_title']} same title)")

    print(f"[Military Tracker] Total articles to analyze: {len(all_articles)}")

    print("[Military Tracker] Phase 2: Analyzing articles...")

    all_signals = []
    per_target_scores = {}
    per_actor_scores = {}
    active_actors = set()
    asset_type_counts = {}
    evacuation_signals = []

    # v3.4 - Two passes. Collect every signal first, dedupe events, THEN score.
    # Scoring inside the collection loop is what let one port call reported by
    # five outlets count five times.
    #
    # Targets ride ON the signal dict (not a side table keyed by id()), because
    # dedupe returns NEW dict objects for merged signals and any id()-based
    # lookup would silently lose their target attribution.
    raw_signals = []

    for article in all_articles:
        analysis = analyze_article_military(article)
        if analysis['signals']:
            for signal in analysis['signals']:
                signal['targets'] = list(analysis['targets'])
                raw_signals.append(signal)

    _raw_signal_score = round(sum(float(s.get('weight') or 0) for s in raw_signals), 2)

    # LAYER 1: collapse distinct reports of the same event into one signal.
    all_signals, event_dedupe_stats = deduplicate_event_signals(raw_signals)

    _deduped_signal_score = round(sum(float(s.get('weight') or 0) for s in all_signals), 2)
    event_dedupe_stats['raw_signal_score'] = _raw_signal_score
    event_dedupe_stats['deduped_signal_score'] = _deduped_signal_score
    event_dedupe_stats['score_removed'] = round(_raw_signal_score - _deduped_signal_score, 2)

    print(f"[Military Tracker] Event dedupe: {event_dedupe_stats['input_signals']} signals -> "
          f"{event_dedupe_stats['output_signals']} "
          f"({event_dedupe_stats['duplicate_signals_collapsed']} duplicates collapsed across "
          f"{event_dedupe_stats['distinct_events']} distinct events; "
          f"{event_dedupe_stats['unanchored_passthrough']} unanchored passed through)")
    print(f"[Military Tracker]    Score: {_raw_signal_score} -> {_deduped_signal_score} "
          f"(removed {event_dedupe_stats['score_removed']} of double-counted signal)")
    if event_dedupe_stats['largest_cluster']:
        _lc = event_dedupe_stats['largest_cluster']
        print(f"[Military Tracker]    Largest cluster: {_lc['event_key']} - "
              f"{_lc['report_count']} reports from {_lc['corroboration_count']} sources, "
              f"{_lc['raw_score_before']} -> {_lc['score_after']}")

    # v3.5 - direction ledger. Additive: no score is changed by this.
    direction_ledger = build_direction_ledger(all_signals)
    _dt = direction_ledger['totals']
    print(f"[Military Tracker] Direction: "
          f"projection {_dt['projection']['count']} ({_dt['projection']['score']}) | "
          f"withdrawal {_dt['withdrawal']['count']} ({_dt['withdrawal']['score']}) | "
          f"degradation {_dt['degradation']['count']} ({_dt['degradation']['score']}) | "
          f"attrition {_dt['attrition']['count']} ({_dt['attrition']['score']}) | "
          f"neutral {_dt['neutral']['count']} ({_dt['neutral']['score']})")
    for _row in direction_ledger['most_degraded'][:5]:
        print(f"[Military Tracker]    Net capability {_row['actor']}: "
              f"projection {_row['projection']} - loss {_row['loss']} = "
              f"{_row['net_score']} ({_row['reading']})")

    # v3.10 - why the neutral bucket is the size it is. classified_share
    # sits under the 0.30 abstention gate because ~85% of signals read
    # neutral; this line says how much of that is fixable vocabulary and
    # how much is text that genuinely does not resolve who did what.
    print(f"[Military Tracker] Classified share: "
          f"{direction_ledger.get('classified_share')} "
          f"(gate 0.30) | neutral {direction_ledger.get('neutral_total', 0)}")
    for _why, _n in list(
            (direction_ledger.get('neutral_reason_counts') or {}).items())[:6]:
        print(f"[Military Tracker]    neutral x{_n}: {_why}")

    # v3.7 - publish the signed capability read for the rhetoric tracker.
    _fp_written = write_capability_fingerprints(direction_ledger, len(all_signals))
    print(f"[Military Tracker] Capability fingerprints published: {_fp_written} actors "
          f"(key {MIL_CAPABILITY_FP_KEY.format(actor='<actor>')})")

    for signal in all_signals:
        active_actors.add(signal['actor'])

        for target in signal.get('targets') or []:
            per_target_scores[target] = per_target_scores.get(target, 0) + signal['weight']

        actor = signal['actor']
        per_actor_scores[actor] = per_actor_scores.get(actor, 0) + signal['weight']

        asset = signal['asset']
        asset_type_counts[asset] = asset_type_counts.get(asset, 0) + 1

        if asset == 'base_evacuation':
            evacuation_signals.append(signal)

    # v3.3 - Apply DECAYED war footing floors (Redis-backed, half-life decay)
    print("[Military Tracker] Applying war footing floors (decayed)...")
    war_footing_effective, war_footing_ledger = get_effective_floors()

    for actor_id, entry in sorted(war_footing_ledger.items()):
        age_txt = 'undated' if entry['age_days'] is None else f"{entry['age_days']:.0f}d old"
        if entry['expired']:
            print(f"[Military Tracker]   Floor EXPIRED: {actor_id} "
                  f"asserted {entry['asserted_score']:.0f} -> "
                  f"{entry['effective_score']:.1f} ({age_txt}, "
                  f"half-life {entry['half_life_days']:.0f}d) - no longer applied")
        else:
            print(f"[Military Tracker]   Floor active:  {actor_id} "
                  f"asserted {entry['asserted_score']:.0f} -> "
                  f"effective {entry['effective_score']:.1f} ({age_txt})")

    for actor_id, floor_score in war_footing_effective.items():
        current = per_actor_scores.get(actor_id, 0)
        if current < floor_score:
            print(f"[Military Tracker]   Floor raised {actor_id}: "
                  f"measured {current:.1f} -> floor {floor_score:.1f}")
            per_actor_scores[actor_id] = float(floor_score)
        # Only an actor whose floor still stands is force-activated.
        active_actors.add(actor_id)

    for actor_id, floor_score in war_footing_effective.items():
        current = per_target_scores.get(actor_id, 0)
        if current < floor_score:
            per_target_scores[actor_id] = float(floor_score)

    tension_multiplier = calculate_regional_tension_multiplier(active_actors)

    print(f"[Military Tracker] Active actors: {len(active_actors)} → Tension multiplier: {tension_multiplier}x")

    for target in per_target_scores:
        per_target_scores[target] = round(per_target_scores[target] * tension_multiplier, 2)

    target_postures = {}

    for target, score in per_target_scores.items():
        alert_level = determine_alert_level(score)
        threshold = ALERT_THRESHOLDS[alert_level]
        relevant_signals = sorted(all_signals, key=lambda x: x['weight'], reverse=True)

        target_postures[target] = {
            'score': score,
            'alert_level': alert_level,
            'alert_label': threshold['label'],
            'alert_color': threshold['color'],
            'alert_icon': threshold['icon'],
            'show_banner': threshold['dashboard_banner'],
            'top_signals': relevant_signals[:5],
            'tension_multiplier': tension_multiplier
        }

    actor_summaries = {}

    for actor_id, score in per_actor_scores.items():
        actor_data = MILITARY_ACTORS.get(actor_id, {})
        actor_signals = [s for s in all_signals if s['actor'] == actor_id]
        actor_signals.sort(key=lambda x: x['weight'], reverse=True)

        actor_summaries[actor_id] = {
            'name': actor_data.get('name', actor_id),
            'flag': actor_data.get('flag', ''),
            'tier': actor_data.get('tier', 99),
            'theatre': actor_data.get('theatre', 'unknown'),
            'total_score': round(score, 2),
            'signal_count': len(actor_signals),
            'top_signals': actor_signals[:5],
            'alert_level': determine_alert_level(score)
        }

    for actor_id, actor_data in MILITARY_ACTORS.items():
        if actor_id not in actor_summaries:
            actor_summaries[actor_id] = {
                'name': actor_data.get('name', actor_id),
                'flag': actor_data.get('flag', ''),
                'tier': actor_data.get('tier', 99),
                'theatre': actor_data.get('theatre', 'unknown'),
                'total_score': 0,
                'signal_count': 0,
                'top_signals': [],
                'alert_level': 'normal'
            }

    theatre_data = {}

    for theatre_id, theatre_info in REGIONAL_THEATRES.items():
        theatre_actors = {}
        theatre_total_score = 0

        for actor_id in theatre_info['actors']:
            if actor_id in actor_summaries:
                theatre_actors[actor_id] = actor_summaries[actor_id]
                theatre_total_score += actor_summaries[actor_id]['total_score']

        theatre_data[theatre_id] = {
            'label': theatre_info['label'],
            'icon': theatre_info['icon'],
            'order': theatre_info['order'],
            'description': theatre_info['description'],
            'actors': theatre_actors,
            'total_score': round(theatre_total_score, 2),
            'alert_level': determine_alert_level(theatre_total_score)
        }

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success': True,
        'scan_time_seconds': scan_time,
        'days_analyzed': days,
        'total_articles_scanned': len(all_articles),
        'total_signals_detected': len(all_signals),
        'deduplication': {
            'articles': article_dedupe_stats,
            'events': event_dedupe_stats,
        },
        'direction_ledger': direction_ledger,
        'active_actors': list(active_actors),
        'active_actor_count': len(active_actors),
        'tension_multiplier': tension_multiplier,
        'war_footing_floors': {
            'effective': {k: round(v, 2) for k, v in war_footing_effective.items()},
            'ledger': war_footing_ledger,
            'active_count': len(war_footing_effective),
            'expired_count': sum(1 for e in war_footing_ledger.values() if e['expired']),
            'default_half_life_days': DEFAULT_FLOOR_HALF_LIFE_DAYS,
            'expiry_threshold': FLOOR_EXPIRY_THRESHOLD,
            'redis_key': WAR_FOOTING_FLOOR_REDIS_KEY,
        },
        'target_postures': target_postures,
        'actor_summaries': actor_summaries,
        'theatre_groupings': theatre_data,
        'asset_distribution': asset_type_counts,
        'evacuation_alerts': [
            {
                'subtype': s.get('evacuation_subtype', 'unspecified'),
                'actor': s.get('actor_name', ''),
                'title': s.get('article_title', ''),
                'url': s.get('article_url', ''),
                'weight': s.get('weight', 0),
                'source': s.get('source', '')
            }
            for s in evacuation_signals
        ],
        'top_signals': sorted(all_signals, key=lambda x: x['weight'], reverse=True)[:25],
        'source_breakdown': {
            'defense_rss': len(rss_articles),
            'gdelt': len(gdelt_articles),
            'newsapi': len(newsapi_articles),
            'reddit': len(reddit_posts),
            'telegram': len(telegram_articles),
            'nitter': len(nitter_articles),
            'brave': len(brave_articles),
            'bluesky': len(bluesky_articles)
        },
        # Sep 7 2026: brave and bluesky were concatenated into all_articles
        # but never reported. The Sep 7 payload showed 3,313 articles scanned
        # against a source_breakdown summing to 3,090 -- 223 articles from
        # two working sources, uncredited and invisible.
        # v3.12 - was {name: 'ok' if count > 0 else 'ZERO'}, which reported
        # that a feed was dead and never why. Now carries status, http
        # codes, attempt count and the first error per source, so a 403, a
        # spent quota, a soft block, a query matching nothing and a
        # fallback that never fired are five different answers.
        'source_health': _health_report(),
        # v3.13 - the breaker, visible. gateway_stats() has existed since
        # July and nothing has ever called it; a high circuit_skips with a
        # low calls count means the gateway locked itself out, which is
        # the opposite diagnosis from 'GDELT is down'.
        'gdelt_gateway': (_gw_gdelt_stats() if _gw_gdelt_stats else
                          {'note': 'gdelt_gateway < v2.0 or not installed'}),
        # Kept under its old shape for any UI still reading it.
        'source_health_legacy': {
            name: ('ok' if count > 0 else 'ZERO')
            for name, count in (
                ('defense_rss', len(rss_articles)),
                ('gdelt',       len(gdelt_articles)),
                ('newsapi',     len(newsapi_articles)),
                ('reddit',      len(reddit_posts)),
                ('telegram',    len(telegram_articles)),
                ('nitter',      len(nitter_articles)),
                ('brave',       len(brave_articles)),
                ('bluesky',     len(bluesky_articles)),
            )
        },
        'recency_filter': recency_stats,
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'cached': False,
        'version': MILITARY_TRACKER_VERSION,
        'features': MILITARY_TRACKER_FEATURES
    }

    # ── Compute chokepoint postures + convergences for scan_result + interpreter ──
    # (These mirror what _write_military_fingerprints derives, but exposed in
    # the scan_result so frontend + interpreter can read without Redis hops.)
    chokepoint_data = _extract_chokepoint_signals(all_signals)
    chokepoint_postures = {}
    chokepoint_levels = {}
    for cp_id, cp_info in chokepoint_data.items():
        cp_alert = determine_chokepoint_alert(cp_info['weighted_score'])
        chokepoint_levels[cp_id] = cp_alert
        chokepoint_postures[cp_id] = {
            'chokepoint':            cp_id,
            'alert_level':           cp_alert,
            'alert_label':           CHOKEPOINT_THRESHOLDS[cp_alert]['label'],
            'alert_icon':            CHOKEPOINT_THRESHOLDS[cp_alert]['icon'],
            'signal_count':          cp_info['signal_count'],
            'critical_signal_count': cp_info.get('critical_signal_count', 0),
            'score':                 round(cp_info['weighted_score'], 2),
            'top_signals':           cp_info['top_signals'],
        }

    # Compute chokepoint convergences (mirror writer logic)
    chokepoint_convergences = {}
    for label, criteria in CHOKEPOINT_CONVERGENCE_PAIRS.items():
        required_cps = criteria.get('chokepoints', [])
        min_level = criteria.get('min_level', 'contested')
        min_rank = CHOKEPOINT_LEVEL_RANK.get(min_level, 2)
        all_active = True
        cp_levels_in_pair = {}
        for cp_id in required_cps:
            lvl = chokepoint_levels.get(cp_id, 'open')
            cp_levels_in_pair[cp_id] = lvl
            if CHOKEPOINT_LEVEL_RANK.get(lvl, 0) < min_rank:
                all_active = False
                break
        if all_active:
            convergence_level = min(cp_levels_in_pair.values(),
                                     key=lambda l: CHOKEPOINT_LEVEL_RANK.get(l, 0))
            chokepoint_convergences[label] = {
                'label':              label,
                'active':             True,
                'level':              convergence_level,
                'chokepoint_levels':  cp_levels_in_pair,
                'rationale':          criteria.get('rationale', ''),
            }

    result['chokepoint_postures']       = chokepoint_postures
    result['chokepoint_convergences']   = chokepoint_convergences

    # ── Run analytical interpreter (v3.2.0 — adds prose layer) ──
    if MIL_INTERPRETER_AVAILABLE:
        try:
            interpretation = build_full_interpretation(result)
            result['interpretation'] = interpretation
            print(f"[Military Tracker] ✅ Interpreter generated "
                  f"{len(interpretation.get('theater_prose', {}))} theater "
                  f"+ {len(interpretation.get('chokepoint_prose', {}))} chokepoint "
                  f"+ {len(interpretation.get('convergence_prose', {}))} convergence prose blocks")
        except Exception as interp_err:
            print(f"[Military Tracker] Interpreter error (non-critical): {str(interp_err)[:200]}")
            result['interpretation'] = None
    else:
        result['interpretation'] = None

    save_military_cache(result)

    # Write cross-tracker fingerprints (v3.1.0 — for downstream consumers:
    # rhetoric trackers, GPI, country stability pages reading via Redis)
    try:
        _write_military_fingerprints(result, all_signals)
    except Exception as fp_err:
        # Fingerprint writes are non-critical — don't fail the scan
        print(f"[Military Tracker] Fingerprint write error (non-critical): {str(fp_err)[:200]}")

    print(f"[Military Tracker] ✅ Scan complete in {scan_time}s")
    print(f"[Military Tracker]    Signals: {len(all_signals)}, Actors: {len(active_actors)}, Targets: {len(target_postures)}")
    print(f"[Military Tracker]    Evacuation alerts: {len(evacuation_signals)}")

    return result


# ========================================
# DASHBOARD INTEGRATION HELPER
# ========================================

def get_military_posture(target):
    """Quick lookup for a specific target's military posture."""
    try:
        data = scan_military_posture()

        posture = data.get('target_postures', {}).get(target, {})

        if not posture:
            return {
                'alert_level': 'normal',
                'alert_label': 'Normal',
                'alert_color': 'green',
                'military_bonus': 0,
                'show_banner': False,
                'banner_text': '',
                'detail_url': '/military.html',
                'top_signals': []
            }

        bonus_map = {
            'normal': 0,
            'elevated': 5,
            'high': 10,
            'surge': 15
        }

        alert_level = posture.get('alert_level', 'normal')
        military_bonus = bonus_map.get(alert_level, 0)

        banner_text = ''
        top_signals = posture.get('top_signals', [])

        evac_alerts = data.get('evacuation_alerts', [])
        if evac_alerts and posture.get('show_banner'):
            top_evac = evac_alerts[0]
            banner_text = (
                f"🚨 BASE EVACUATION: {top_evac.get('title', '')[:80]}"
            )
        elif top_signals and posture.get('show_banner'):
            top = top_signals[0]
            banner_text = (
                f"{ALERT_THRESHOLDS[alert_level]['icon']} "
                f"MILITARY POSTURE: {top.get('actor_flag', '')} "
                f"{top.get('asset_label', 'Activity')} detected — "
                f"{top.get('article_title', '')[:80]}"
            )

        return {
            'alert_level': alert_level,
            'alert_label': posture.get('alert_label', 'Normal'),
            'alert_color': posture.get('alert_color', 'green'),
            'military_bonus': military_bonus,
            'show_banner': posture.get('show_banner', False),
            'banner_text': banner_text,
            'detail_url': '/military.html',
            'top_signals': top_signals[:3],
            'tension_multiplier': data.get('tension_multiplier', 1.0),
            'active_actors': data.get('active_actors', []),
            'evacuation_alerts': evac_alerts[:3]
        }

    except Exception as e:
        print(f"[Military Posture] Error for {target}: {str(e)[:200]}")
        return {
            'alert_level': 'normal',
            'military_bonus': 0,
            'show_banner': False,
            'banner_text': '',
            'detail_url': '/military.html',
            'top_signals': [],
            'error': str(e)[:100]
        }


# ========================================
# FLASK ENDPOINT REGISTRATION
# ========================================

def register_military_endpoints(app, start_background=True):
    """
    Register military tracker endpoints with the Flask app.

    Parameters:
        app: Flask app instance
        start_background: If True (default), spawn a periodic scan thread
                          that refreshes the military cache every 12 hours.
                          Set to False on read-only backends that share
                          Redis with a primary scanner (prevents duplicate
                          scans on backup/read replicas).
    """

    @app.route('/api/military-posture', methods=['GET', 'OPTIONS'])
    def api_military_posture():
        """Full military posture assessment for military.html"""
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            days = int(flask_request.args.get('days', 7))
            refresh = flask_request.args.get('refresh', 'false').lower() == 'true'

            if refresh:
                _trigger_background_scan(days)
            result = scan_military_posture(days=days, force_refresh=False)
            return app.response_class(
                response=json.dumps(result, default=str),
                status=200,
                mimetype='application/json'
            )

        except Exception as e:
            print(f"[Military API] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return app.response_class(
                response=json.dumps({
                    'success': False,
                    'error': str(e)[:200]
                }),
                status=500,
                mimetype='application/json'
            )

    @app.route('/api/military-posture/<target>', methods=['GET', 'OPTIONS'])
    def api_military_posture_target(target):
        """Quick posture check for a specific target."""
        from flask import request as flask_request

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            posture = get_military_posture(target)
            return app.response_class(
                response=json.dumps(posture, default=str),
                status=200,
                mimetype='application/json'
            )

        except Exception as e:
            return app.response_class(
                response=json.dumps({
                    'success': False,
                    'error': str(e)[:200]
                }),
                status=500,
                mimetype='application/json'
            )

    # ============================================================
    # FINGERPRINT ENDPOINTS (v3.1.0 — cross-tracker contract)
    # Read live military fingerprints written to Upstash Redis
    # by _write_military_fingerprints() during the most recent scan.
    # ============================================================

    @app.route('/api/military-fingerprint/<country>', methods=['GET', 'OPTIONS'])
    def api_military_fingerprint_country(country):
        """Per-country military posture fingerprint (incl. asset distribution)."""
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            country = (country or '').lower().strip()
            posture = _redis_fp_get(f"military:{country}:posture")
            assets  = _redis_fp_get(f"military:{country}:asset_distribution")
            evac    = _redis_fp_get(f"military:evacuation:{country}")
            return jsonify({
                'country':            country,
                'posture':            posture,
                'asset_distribution': assets,
                'evacuation':         evac,
                'has_data':           bool(posture or assets or evac),
            })
        except Exception as e:
            return jsonify({'country': country, 'error': str(e)[:200]}), 500

    @app.route('/api/military-fingerprint/theatre/<theatre_id>', methods=['GET', 'OPTIONS'])
    def api_military_fingerprint_theatre(theatre_id):
        """Per-theatre fingerprint (theatre = global_northcom, asia_pacific,
        europe, middle_east, western_hemisphere)."""
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            theatre_id = (theatre_id or '').lower().strip()
            data = _redis_fp_get(f"military:theatre:{theatre_id}")
            return jsonify({
                'theatre':  theatre_id,
                'data':     data,
                'has_data': bool(data),
            })
        except Exception as e:
            return jsonify({'theatre': theatre_id, 'error': str(e)[:200]}), 500

    @app.route('/api/military-fingerprint/chokepoint/<chokepoint_id>', methods=['GET', 'OPTIONS'])
    def api_military_fingerprint_chokepoint(chokepoint_id):
        """Per-chokepoint fingerprint (hormuz, bab_el_mandeb, taiwan_strait, etc.)."""
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            chokepoint_id = (chokepoint_id or '').lower().strip()
            data = _redis_fp_get(f"military:chokepoint:{chokepoint_id}")
            return jsonify({
                'chokepoint': chokepoint_id,
                'data':       data,
                'has_data':   bool(data),
            })
        except Exception as e:
            return jsonify({'chokepoint': chokepoint_id, 'error': str(e)[:200]}), 500

    @app.route('/api/military-fingerprint/cross/<label>', methods=['GET', 'OPTIONS'])
    def api_military_fingerprint_cross(label):
        """Cross-actor amplifier fingerprint (nato_us_active, china_taiwan_active, etc.)."""
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            label = (label or '').lower().strip()
            data = _redis_fp_get(f"military:cross:{label}")
            return jsonify({
                'label':    label,
                'data':     data,
                'has_data': bool(data),
            })
        except Exception as e:
            return jsonify({'label': label, 'error': str(e)[:200]}), 500

    @app.route('/api/military-fingerprint/chokepoint-convergence/<label>',
               methods=['GET', 'OPTIONS'])
    def api_military_fingerprint_cp_convergence(label):
        """Chokepoint convergence fingerprint (hormuz_bam, bam_suez, taiwan_scs, etc.).
        Active when both chokepoints in the pair are simultaneously at 'contested+'."""
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            label = (label or '').lower().strip()
            data = _redis_fp_get(f"military:chokepoint_convergence:{label}")
            return jsonify({
                'label':    label,
                'data':     data,
                'has_data': bool(data),
            })
        except Exception as e:
            return jsonify({'label': label, 'error': str(e)[:200]}), 500

    @app.route('/api/military/asset/<ship_id>/movement', methods=['GET', 'OPTIONS'])
    def api_military_asset_movement(ship_id):
        """Return movement history for a named US Navy ship.

        ship_id should be canonical (lowercase, underscores), e.g.:
            /api/military/asset/uss_nimitz/movement
            /api/military/asset/uss_gerald_r_ford/movement

        Returns:
            current_position: latest position fingerprint (or null)
            movement_history: list of recent positions (newest first), up to 50 entries
                              spanning up to 30 days
        """
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            ship_id = (ship_id or '').lower().strip().replace(' ', '_').replace('.', '')

            # Current position (single fingerprint with 168h TTL)
            position = _redis_fp_get(f"military:asset:{ship_id}:position")

            # Movement history (Redis list)
            history = []
            if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
                try:
                    url = f"{UPSTASH_REDIS_URL}/lrange/military:asset:{ship_id}:positions/0/49"
                    resp = requests.get(
                        url,
                        headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        result = resp.json().get('result', [])
                        from urllib.parse import unquote
                        for entry in result or []:
                            try:
                                decoded = unquote(entry) if isinstance(entry, str) else entry
                                parsed = json.loads(decoded)
                                history.append(parsed)
                            except (json.JSONDecodeError, TypeError):
                                continue
                except Exception as e:
                    print(f"[Military API] Movement history read error for {ship_id}: {str(e)[:100]}")

            return jsonify({
                'ship_id':           ship_id,
                'current_position':  position,
                'movement_history':  history,
                'history_count':     len(history),
                'has_data':          position is not None or len(history) > 0,
            })
        except Exception as e:
            return jsonify({'ship_id': ship_id, 'error': str(e)[:200]}), 500

    @app.route('/api/military-interpretation', methods=['GET', 'OPTIONS'])
    def api_military_interpretation():
        """Analytical prose layer (v3.2.0+). Returns:
            executive_summary, theater_prose (5 regions),
            chokepoint_prose (contested+ only), convergence_prose (active only),
            evacuation_prose (single block), top_signals (canonical schema).

        Reads from the cached scan_result['interpretation'] — no live re-derivation.
        Frontend (military.html) + GPI consume this for FSO-grade prose."""
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            cache = load_military_cache() or {}
            interp = cache.get('interpretation')
            if not interp:
                return jsonify({
                    'available':            False,
                    'reason':               ('Interpreter prose not available — either '
                                              'interpreter module not deployed or scan '
                                              'predates v3.2.0. Force-refresh to populate.'),
                    'last_scan_version':    cache.get('version', 'unknown'),
                    'last_updated':         cache.get('last_updated'),
                })
            return jsonify({
                'available':              True,
                'interpretation':         interp,
                'last_updated':           cache.get('last_updated'),
                'tracker_version':        cache.get('version', 'unknown'),
            })
        except Exception as e:
            return jsonify({'available': False, 'error': str(e)[:200]}), 500

    @app.route('/api/military-fingerprint-debug', methods=['GET'])
    def api_military_fingerprint_debug():
        """Diagnostic — list which fingerprint keys are currently in Redis."""
        from flask import jsonify

        # Probe well-known fingerprint keys
        countries_to_check = list(MILITARY_ACTORS.keys())
        theatres_to_check = list(REGIONAL_THEATRES.keys())
        chokepoints_to_check = list(CHOKEPOINT_LOCATION_MAP.keys())
        cross_to_check = list(CROSS_AMPLIFIER_PAIRS.keys())
        convergence_to_check = list(CHOKEPOINT_CONVERGENCE_PAIRS.keys())

        debug = {
            'version':              MILITARY_TRACKER_VERSION,
            'gdelt_gateway':        (_gw_gdelt_stats() if _gw_gdelt_stats
                                     else {'note': 'stats unavailable'}),
            'fingerprint_ttl_hours': FINGERPRINT_TTL_SECONDS / 3600,
            'redis_configured':     bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'chokepoint_thresholds': CHOKEPOINT_THRESHOLDS,
            'interpreter_available': MIL_INTERPRETER_AVAILABLE,
            'fingerprints_present': {
                'posture':                [],
                'asset_distribution':     [],
                'theatre':                [],
                'chokepoint':             [],
                'evacuation':             [],
                'cross':                  [],
                'chokepoint_convergence': [],
            },
            'fingerprints_missing': {
                'posture':                [],
                'asset_distribution':     [],
                'theatre':                [],
                'chokepoint':             [],
                'evacuation':             [],
                'cross':                  [],
                'chokepoint_convergence': [],
            },
        }

        for cid in countries_to_check:
            for ftype, prefix in [('posture', 'military:{}:posture'),
                                   ('asset_distribution', 'military:{}:asset_distribution'),
                                   ('evacuation', 'military:evacuation:{}')]:
                if _redis_fp_get(prefix.format(cid)):
                    debug['fingerprints_present'][ftype].append(cid)
                else:
                    debug['fingerprints_missing'][ftype].append(cid)

        for tid in theatres_to_check:
            if _redis_fp_get(f"military:theatre:{tid}"):
                debug['fingerprints_present']['theatre'].append(tid)
            else:
                debug['fingerprints_missing']['theatre'].append(tid)

        for cpid in chokepoints_to_check:
            if _redis_fp_get(f"military:chokepoint:{cpid}"):
                debug['fingerprints_present']['chokepoint'].append(cpid)
            else:
                debug['fingerprints_missing']['chokepoint'].append(cpid)

        for label in cross_to_check:
            if _redis_fp_get(f"military:cross:{label}"):
                debug['fingerprints_present']['cross'].append(label)
            else:
                debug['fingerprints_missing']['cross'].append(label)

        for label in convergence_to_check:
            if _redis_fp_get(f"military:chokepoint_convergence:{label}"):
                debug['fingerprints_present']['chokepoint_convergence'].append(label)
            else:
                debug['fingerprints_missing']['chokepoint_convergence'].append(label)

        # Summary counts
        debug['summary'] = {
            ftype: {
                'present_count': len(debug['fingerprints_present'][ftype]),
                'missing_count': len(debug['fingerprints_missing'][ftype]),
            }
            for ftype in debug['fingerprints_present']
        }

        return jsonify(debug)

    # ============================================================
    # WAR FOOTING FLOOR ENDPOINTS (v3.3)
    # Read and renew analyst floor assertions without a redeploy.
    # GET is open. POST mutates shared Redis state, so it is gated on
    # the ASIFAH_ADMIN_TOKEN env var and FAILS CLOSED if that is unset.
    # ============================================================

    @app.route('/api/military/floors', methods=['GET', 'OPTIONS'])
    def api_military_floors():
        """Current war footing floors with decay ledger.

        Every floor is an analyst assertion, not a measurement. This shows
        what was asserted, how old the assertion is, what it has decayed to,
        and whether it still applies.
        """
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            effective, ledger = get_effective_floors()
            for country_id, entry in ledger.items():
                entry['country'] = country_id
            rows = sorted(
                ledger.values(),
                key=lambda e: (e['expired'], -e['effective_score'])
            )
            return jsonify({
                'success':                 True,
                'effective':               {k: round(v, 2) for k, v in effective.items()},
                'ledger':                  ledger,
                'rows':                    rows,
                'active_count':            len(effective),
                'expired_count':           sum(1 for e in ledger.values() if e['expired']),
                'default_half_life_days':  DEFAULT_FLOOR_HALF_LIFE_DAYS,
                'expiry_threshold':        FLOOR_EXPIRY_THRESHOLD,
                'redis_key':               WAR_FOOTING_FLOOR_REDIS_KEY,
                'write_enabled':           bool(os.environ.get('ASIFAH_ADMIN_TOKEN')),
                'note':                    ('A floor is an analyst assertion that decays. '
                                            'It is never auto-refreshed from measured signal, '
                                            'because refreshing an assertion from the data it '
                                            'backstops is circular. Renew it deliberately.'),
                'read_at':                 datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/military/floors/<country>', methods=['POST', 'OPTIONS'])
    def api_military_set_floor(country):
        """Assert or renew a war footing floor. Restarts that floor's decay clock.

        Header:  X-Asifah-Admin: <ASIFAH_ADMIN_TOKEN>
        Body:    {"score": 40, "half_life_days": 30, "note": "why"}

        score = 0 deletes the floor.
        half_life_days = 0 means do not decay (use sparingly).
        """
        from flask import request as flask_request, jsonify

        if flask_request.method == 'OPTIONS':
            return '', 200

        admin_token = os.environ.get('ASIFAH_ADMIN_TOKEN')
        if not admin_token:
            return jsonify({
                'success': False,
                'error':   ('Floor writes are disabled: ASIFAH_ADMIN_TOKEN is not set '
                            'on this instance. Set it in Render env vars to enable.'),
            }), 503

        supplied = (flask_request.headers.get('X-Asifah-Admin')
                    or flask_request.args.get('token') or '')
        if supplied != admin_token:
            return jsonify({'success': False, 'error': 'Unauthorized.'}), 401

        try:
            body = flask_request.get_json(silent=True) or {}
            if 'score' not in body:
                return jsonify({'success': False,
                                'error': 'Body must include "score".'}), 400

            key = (country or '').strip().lower().replace(' ', '_')
            if not key:
                return jsonify({'success': False,
                                'error': 'Country is required.'}), 400

            try:
                score = float(body.get('score'))
            except (TypeError, ValueError):
                return jsonify({'success': False,
                                'error': f'score must be a number, got '
                                         f'{body.get("score")!r}.'}), 400

            half_life = body.get('half_life_days')
            if half_life is not None and half_life != '':
                try:
                    half_life = float(half_life)
                except (TypeError, ValueError):
                    return jsonify({'success': False,
                                    'error': f'half_life_days must be a number, got '
                                             f'{body.get("half_life_days")!r}.'}), 400
                if half_life < 0:
                    return jsonify({'success': False,
                                    'error': 'half_life_days cannot be negative. '
                                             'Use 0 for a non-decaying floor.'}), 400
            else:
                half_life = None

            note = str(body.get('note') or '')[:300]
            entry = set_war_footing_floor(key, score, half_life, note, source='api')

            effective, ledger = get_effective_floors()
            return jsonify({
                'success':       True,
                'country':       key,
                'action':        'deleted' if score <= 0 else 'set',
                'entry':         entry,
                'ledger_entry':  ledger.get(key),
                'active_count':  len(effective),
                'reminder':      ('This floor now reads as freshly asserted. It will decay '
                                  'from here and stop applying below '
                                  f'{FLOOR_EXPIRY_THRESHOLD}.'),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    print("[Military Tracker] ✅ Endpoints registered: /api/military-posture, /api/military-posture/<target>")
    print("[Military Tracker] ✅ Floor endpoints registered: "
          "GET /api/military/floors, POST /api/military/floors/<country>")
    print("[Military Tracker] ✅ Fingerprint endpoints registered: "
          "/api/military-fingerprint/<country>, "
          "/api/military-fingerprint/theatre/<id>, "
          "/api/military-fingerprint/chokepoint/<id>, "
          "/api/military-fingerprint/chokepoint-convergence/<label>, "
          "/api/military-fingerprint/cross/<label>, "
          "/api/military-fingerprint-debug")
    print("[Military Tracker] ✅ Interpretation endpoint registered: "
          "/api/military-interpretation")

    # PERIODIC BACKGROUND SCAN (every 12 hours)
    # start_background=False → skip the scan thread entirely
    # (used by read-only backends that share Redis with a primary scanner)
    if not start_background:
        print("[Military Tracker] ℹ️ Background scan disabled on this instance (read-only via Redis)")
        return

    def _periodic_scan():
        time.sleep(10)
        while True:
            try:
                # Cross-worker guard: only the lock-owning worker scans. TTL (13h)
                # outlasts the 12h sleep so ownership persists between cycles; a
                # non-owner re-checks hourly so it can take over if the owner dies.
                if not _acquire_scheduler_lock('military', 46800):
                    time.sleep(3600)
                    continue
                print("[Military Tracker] Periodic scan starting (lock owner)...")
                _trigger_background_scan(days=7)
                time.sleep(60)
                while _background_scan_running:
                    time.sleep(30)
                print("[Military Tracker] Periodic scan complete. Sleeping 12 hours.")
                time.sleep(43200)  # 12 hours (was 14400 / 4 hours)
            except Exception as e:
                print(f"[Military Tracker] Periodic scan error: {e}")
                time.sleep(3600)

    periodic_thread = threading.Thread(target=_periodic_scan, daemon=True)
    periodic_thread.start()
