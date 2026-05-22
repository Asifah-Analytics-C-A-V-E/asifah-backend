"""
Asifah Analytics — Military Asset & Deployment Tracker v3.0.0
April 4, 2026

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
        'actors': ['china', 'taiwan', 'north_korea', 'pakistan', 'afghanistan'],
        'description': 'INDOPACOM area — China/PLAN, Taiwan Strait, Korean Peninsula, South/Central Asia'
    },
    'europe': {
        'label': 'European Theatre',
        'icon': '🌍',
        'order': 2,
        'actors': ['nato', 'russia', 'denmark', 'turkey', 'ukraine', 'greenland', 'poland', 'cyprus', 'azerbaijan', 'armenia', 'hungary'],
        'description': 'EUCOM area — NATO, Russia, Arctic, Black Sea, Ukraine, Poland eastern flank, Cyprus, Caucasus'
    },
    'middle_east': {
        'label': 'Middle East & North Africa',
        'icon': '🕌',
        'order': 3,
        'actors': ['israel', 'iran', 'iraq', 'bahrain', 'egypt', 'jordan', 'kuwait', 'oman', 'qatar', 'saudi_arabia', 'uae', 'libya'],
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
                   'sudan', 'libya', 'ethiopia', 'kenya', 'djibouti',
                   'central_african_republic', 'wagner_africa'],
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
            'ebola response military', 'ebola sudan', 'ebola drc', 'ebola uganda',
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
            'חץ', 'שלט דוד', 'כיפת ברזל נפלה',
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
        'tier': 2,
        'theatre': 'asia_pacific',
        'weight': 0.7,
        'feeds_into': ['regional_tension'],
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
            # Korean language signals
            '북한 미사일', '북한 핵', '김정은', '조선인민군',
            '북한 도발', '북한 발사', '탄도미사일',
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
            'russian navy mediterranean', 'russian warship mediterranean',
            'russian submarine mediterranean', 'russia med fleet',
            'tartus naval base', 'hmeimim air base', 'russia syria deployment',
            'russian forces syria', 'russian air force syria',
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
            'cyprus military', 'cyprus defense', 'cyprus defence',
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
            'Армения военный', 'Ереван армия',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=armenia+military+OR+yerevan+OR+defense+OR+CSTO+OR+border&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=nigeria+military+OR+nigerian+army+OR+nigeria+boko+haram&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=somalia+military+OR+al+shabaab+OR+us+strike+somalia&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=mali+military+OR+wagner+mali+OR+mali+sahel&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=niger+military+OR+niger+coup+OR+niger+sahel&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=burkina+faso+military+OR+burkina+junta&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=drc+military+OR+m23+congo+OR+goma+military&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=sudan+military+OR+sudan+civil+war+OR+rsf+sudan&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=libya+military+OR+haftar+OR+libya+wagner&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=ethiopia+military+OR+endf+OR+ethiopia+tigray&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=kenya+military+OR+kdf+OR+manda+bay&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=djibouti+military+OR+camp+lemonnier+OR+horn+of+africa+us&hl=en&gl=US&ceid=US:en',
        ]
    },

    'central_african_republic': {
        'name': 'Central African Republic',
        'flag': '🇨🇫',
        'tier': 3,
        'theatre': 'africa',
        'weight': 0.5,
        'feeds_into': ['russia_proxy_pressure'],
        'keywords': [
            'car military', 'central african republic military',
            'faca central african', 'far',
            'car wagner', 'wagner car', 'wagner central african',
            'car russian mercenaries', 'africa corps car',
            'bangui military', 'touadera car',
            'car rebels', 'car civil war',
            'car coalition patriots change',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=central+african+republic+military+OR+car+wagner&hl=en&gl=US&ceid=US:en',
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
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=wagner+africa+OR+africa+corps+OR+russia+mercenaries+africa&hl=en&gl=US&ceid=US:en',
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
# WAR FOOTING FLOOR SCORES (v2.7.3)
# Countries confirmed struck by Iran — minimum score floor regardless of scan hits
# Update manually as situation evolves
# ========================================

WAR_FOOTING_FLOORS = {
    'israel':       75,   # Active war, mass barrages
    'iraq':         40,   # IRI militia ops, US bases hit
    'kuwait':       35,   # Iranian strikes confirmed; US Embassy ordered departure; USAF scrambled
    'saudi_arabia': 35,   # Iranian strikes confirmed; drone shoot-downs; Ukraine technicians deployed
    'uae':          25,   # Struck; UAE air defense active; flights disrupted
    'jordan':       25,   # Missiles/drones transiting airspace; intercept operations
    'qatar':        20,   # Al Udeid on heightened alert; airspace affected
    'bahrain':      20,   # 5th Fleet HQ; heightened posture
    'turkey':       15,   # Incirlik on alert; border tensions
    'egypt':        10,   # Suez disruption risk; Sinai watch
    'oman':         15,   # Strait of Hormuz operations
    'cyprus':       15,   # Akrotiri on alert; evacuation staging
}

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
# All fingerprints carry a 'scanned_at' timestamp + 'source': 'military_tracker_v3.1'
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
            payload.setdefault('source', 'military_tracker_v3.1')
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
        'version': '3.0.0'
    }


# ========================================
# DATA FETCHING — RSS FEEDS
# ========================================

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

def fetch_gdelt_military(query, days=7, language='eng'):
    """Fetch military-related articles from GDELT"""
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
            return []

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
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
        return standardized

    except Exception as e:
        print(f"[Military GDELT] Error: {str(e)[:100]}")
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
        return []

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
            return articles
        return []
    except:
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
        return []
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
            return articles
        return []
    except Exception:
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

            if response.status_code == 200:
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
        except Exception:
            continue

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


def analyze_article_military(article):
    """Analyze a single article for military deployment signals."""
    title = (article.get('title') or '').lower()
    description = (article.get('description') or '').lower()
    content = (article.get('content') or '').lower()
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
            if keyword in text:
                result['actors'].add(actor_id)
                actor_weight = actor_data['weight']

                asset_matched = False
                for asset_id, asset_data in ASSET_CATEGORIES.items():
                    for asset_kw in asset_data['keywords']:
                        if asset_kw in text:
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
                        'published': article.get('publishedAt', '')
                    })
                    result['score'] += signal_score

                break

    for aor, bases in ASSET_TARGET_MAPPING.items():
        for base_name, base_data in bases.items():
            if base_name.lower() in text:
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

    rss_articles = fetch_all_defense_rss()
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

    telegram_articles = []
    if TELEGRAM_AVAILABLE:
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
        except Exception as e:
            print(f"[Military Tracker] Telegram error: {str(e)[:100]}")

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
    try:
        bluesky_articles = fetch_bluesky_military_aggregated(days=days)
        print(f"[Military Tracker] BlueSky: {len(bluesky_articles)} posts from global-scoped accounts")
    except Exception as e:
        print(f"[Military Tracker] BlueSky error (non-fatal): {str(e)[:100]}")

    all_articles = rss_articles + gdelt_articles + newsapi_articles + reddit_posts + telegram_articles + nitter_articles + bluesky_articles + brave_articles

    print(f"[Military Tracker] Total articles to analyze: {len(all_articles)}")

    print("[Military Tracker] Phase 2: Analyzing articles...")

    all_signals = []
    per_target_scores = {}
    per_actor_scores = {}
    active_actors = set()
    asset_type_counts = {}
    evacuation_signals = []

    for article in all_articles:
        analysis = analyze_article_military(article)

        if analysis['signals']:
            for signal in analysis['signals']:
                all_signals.append(signal)
                active_actors.add(signal['actor'])

                for target in analysis['targets']:
                    per_target_scores[target] = per_target_scores.get(target, 0) + signal['weight']

                actor = signal['actor']
                per_actor_scores[actor] = per_actor_scores.get(actor, 0) + signal['weight']

                asset = signal['asset']
                asset_type_counts[asset] = asset_type_counts.get(asset, 0) + 1

                if asset == 'base_evacuation':
                    evacuation_signals.append(signal)

    # v2.7.3 — Apply war footing floor scores for confirmed-struck actors
    print("[Military Tracker] Applying war footing floors...")
    for actor_id, floor_score in WAR_FOOTING_FLOORS.items():
        current = per_actor_scores.get(actor_id, 0)
        if current < floor_score:
            print(f"[Military Tracker]   Floor applied: {actor_id} {current:.1f} → {floor_score}")
            per_actor_scores[actor_id] = float(floor_score)
        active_actors.add(actor_id)

    for actor_id, floor_score in WAR_FOOTING_FLOORS.items():
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
        'active_actors': list(active_actors),
        'active_actor_count': len(active_actors),
        'tension_multiplier': tension_multiplier,
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
            'nitter': len(nitter_articles)
        },
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'cached': False,
        'version': '3.2.1'
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
            'version':              '3.2.1',
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

    print("[Military Tracker] ✅ Endpoints registered: /api/military-posture, /api/military-posture/<target>")
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
                print("[Military Tracker] Periodic scan starting...")
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
