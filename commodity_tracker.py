"""
Asifah Analytics — Cross-Cutting Commodity Tracker v1.0.0
April 29, 2026

Tracks 11 strategic commodities and their country-level pressure signals.
Mirrors military_tracker.py architecture.

COMMODITIES TRACKED (Phase 1):
  Tier 1 (Strategic / Chokepoint):
    - Oil (Brent + WTI futures)
    - Natural Gas (Henry Hub + LNG)
    - Wheat (CBOT)
    - Potash (no spot price — production volume + sanctions cycle)
  Tier 2 (Strategic Minerals + Agri):
    - Corn (CBOT)
    - Soybeans (CBOT)
    - Uranium (URA ETF + Sprott proxy)
    - Rare Earth Elements (MP Materials, REMX ETF)
    - Lithium (LIT ETF, ALB stock)
    - Gold (futures)
  Tier 3 (Industrial):
    - Copper (HG futures)

COUNTRY EXPOSURE — Phase 1:
  Belarus, Russia, China, Israel, Ukraine
  (Phase 2: KZ, CA, AU, SA, UAE, IR, US, BR, DRC, GL, NE, KZ, CL, PE)

DATA SOURCES:
  - Yahoo Finance (yfinance) — sparklines for 10/11 commodities
  - GDELT (English + Russian + Chinese + Arabic) — news signals
  - Defense/Industry RSS — USGS, USDA, IEA public, Argus public
  - Reddit — r/commodities, r/Mining, r/uranium, r/RareEarthMetals,
    r/agriculture, r/wallstreetbets (futures coverage)
  - Brave Search (fallback when GDELT/NewsAPI rate limit)

ARCHITECTURE NOTES:
  - Mirrors military_tracker.py exactly (Redis cache, /tmp fallback,
    background scan daemon, register_*_endpoints pattern)
  - Read-aware: country pages call /api/commodity-pressure/<target>
    same shape as /api/military-posture/<target>
  - yfinance is the only new dependency (~50MB pandas/numpy transitive)
  - Honest UI: commodities WITHOUT public spot prices (potash) get
    production volume + policy event signals instead of fake sparklines

CHANGELOG:
  v1.0.0 - Initial release. 11 commodities, 5 country mappings,
           full backend wiring matching military_tracker pattern.
  v1.6.0 - Jul 18 2026 Africa expansion: graphite + gum_arabic commodity
           types (potash-pattern, no spot price); 7 new countries (Mali,
           Burkina Faso, Niger, Sudan, CAR, Mozambique, Madagascar);
           graphite worldwide sweep (CN/BR/US/KR/EU); gum_arabic to
           Nigeria; Guinea notes refreshed post-election; keyword nets
           extended (gold/diamonds/lithium/natural_gas/coal); 8 African
           commodity-jawboning leaders added to KNOWN_SPEAKERS.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
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
import os
import threading

# Yahoo Finance for sparklines
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
    print("[Commodity Tracker] ✅ yfinance available")
except ImportError:
    YFINANCE_AVAILABLE = False
    print("[Commodity Tracker] ⚠️ yfinance not available — sparklines disabled")


# ── v1.2.0 (May 24 2026) — Analytical prose layer wiring ───────
# The commodity_signal_interpreter wraps scan_result into an
# 'interpretation' block (executive summary + butterfly convergences
# + regional prose) consumed by commodities.html. The interpreter is
# a soft dependency — if absent, the rest of the tracker still works.
try:
    from commodity_signal_interpreter import build_full_commodity_interpretation
    COMM_INTERPRETER_AVAILABLE = True
    print("[Commodity Tracker] ✅ Commodity signal interpreter available")
except ImportError as e:
    COMM_INTERPRETER_AVAILABLE = False
    print(f"[Commodity Tracker] ⚠️ Commodity interpreter not available: {e}")

# The convergence_registry is needed to walk the registry and surface
# which convergences are currently ACTIVE (commodity above threshold).
# Soft dependency — if registry is missing, we emit empty list.
try:
    from convergence_registry import (
        CONVERGENCE_REGISTRY,
        alert_meets_threshold,
        format_headline,
    )
    CONVERGENCE_REGISTRY_AVAILABLE = True
    print(f"[Commodity Tracker] ✅ Convergence registry available "
          f"({len(CONVERGENCE_REGISTRY)} entries)")
except ImportError as e:
    CONVERGENCE_REGISTRY_AVAILABLE = False
    CONVERGENCE_REGISTRY = []
    print(f"[Commodity Tracker] ⚠️ Convergence registry not available: {e}")


# ========================================
# CONFIGURATION
# ========================================

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY')

# Upstash Redis (persistent cache across Render cold starts)
UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

# ------------------------------------------------------------
# CROSS-WORKER SCHEDULER LOCK  [Jun 2026]
# gunicorn runs --workers 2, and each worker imports this module and starts
# its own periodic-scan thread. The in-process running-flags do NOT cross
# processes, so without this guard BOTH workers scan -- every GDELT / NewsAPI /
# Brave / RSS call fires twice (doubles quota burn + trips GDELT 429s faster).
# This atomic Upstash "SET ... NX EX" makes exactly ONE worker own the scan;
# the owner renews each cycle (TTL > cycle so ownership never lapses while it
# is alive); if the owner dies, the lock expires and another worker takes over.
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

# Local fallback cache
COMMODITY_CACHE_FILE = '/tmp/commodity_tracker_cache.json'
COMMODITY_CACHE_TTL_HOURS = 4

# Sparkline cache (separate, refreshed more frequently)
SPARKLINE_CACHE_TTL_HOURS = 1     # Prices update faster than news
SPARKLINE_REDIS_KEY = 'commodity_sparkline_bundle'

# Background scan lock
_background_scan_running = False
_background_scan_lock = threading.Lock()


# ========================================
# COMMODITY DEFINITIONS
# ========================================
# Each commodity has:
#   tier:           1 (chokepoint), 2 (strategic), 3 (industrial)
#   category:       'energy', 'agricultural', 'strategic_mineral', 'precious'
#   icon:           emoji for UI
#   yahoo_ticker:   primary Yahoo Finance ticker for sparkline
#   yahoo_proxies:  alternate tickers if primary fails (failover)
#   keywords:       news keyword set
#   chokepoints:    geographic/logistical chokepoints
#   has_spot_price: True if a public ticker tracks it; False = production-volume
#                   + policy events instead (e.g. potash)

COMMODITY_TYPES = {
    'cobalt': {
        'name': 'Cobalt',
        'icon': '🔷',
        'tier': 1,
        'category': 'strategic_mineral',
        'has_spot_price': True,
        'yahoo_ticker': 'BATT',          # Amplify Lithium & Battery Tech ETF (cobalt-exposed)
        'yahoo_proxies': ['GLNCY', 'CMCLF'],  # Glencore + CMOC Group (DRC dominant)
        'unit': 'USD (BATT ETF)',
        'description': 'Cobalt is a critical battery metal essential for EV cathodes (NMC chemistry). DRC produces ~72% of global supply; China refines ~73%. Tracked via battery-metals ETF + Glencore/CMOC equity proxies. LME cobalt futures available but illiquid.',
        'chokepoints': [
            'drc cobalt belt', 'kolwezi', 'lubumbashi', 'tenke fungurume',
            'mutanda', 'kisanfu', 'lobito corridor', 'glencore cobalt',
            'cmoc cobalt', 'huayou cobalt', 'sulawesi indonesia',
            'morowali industrial park', 'weda bay',
        ],
        'top_producers':  ['drc', 'indonesia', 'russia', 'australia', 'canada', 'philippines'],
        'top_consumers':  ['china', 'korea', 'japan', 'usa', 'eu'],
    },
    'copper': {
        'name': 'Copper',
        'icon': '🟫',
        # v1.4.1 (May 17, 2026): cascade_via metadata -- copper oxide processing
        # (solvent extraction) requires sulfuric acid; Chile imports ~20% of its
        # processing acid; Africa imports 90% of sulfur. Hormuz closure -> sulfur
        # scarcity -> copper processing risk. Source: Reuters/Andy Home Apr 17 2026.
        'cascade_via': ['sulfur'],
        'cascade_upstream_chokepoints': ['strait_of_hormuz'],
        'tier': 3,
        'category': 'industrial',
        'has_spot_price': True,
        'yahoo_ticker': 'HG=F',
        'yahoo_proxies': ['CPER', 'FCX'],   # Copper ETF + Freeport-McMoRan
        'unit': 'USD/lb',
        'description': 'COMEX copper futures. Bellwether for global industrial demand. China consumes ~50%.',
        'chokepoints': [
            'antofagasta chile', 'escondida', 'chuquicamata',
            'lubumbashi drc', 'glencore', 'panama copper',
        ],
        'top_producers':  ['chile', 'peru', 'china', 'drc', 'usa', 'australia'],
        'top_consumers':  ['china', 'eu', 'usa', 'japan', 'korea'],
    },
    'corn': {
        'name': 'Corn',
        'icon': '🌽',
        'tier': 2,
        'category': 'agricultural',
        'has_spot_price': True,
        'yahoo_ticker': 'ZC=F',
        'yahoo_proxies': ['CORN'],
        'unit': 'USD/bushel',
        'description': 'CBOT corn futures. Animal feed + ethanol + food.',
        'chokepoints': [
            'mississippi river', 'panama canal', 'brazil port santos',
            'paranaguá', 'odesa port',
        ],
        'top_producers':  ['usa', 'china', 'brazil', 'argentina', 'ukraine'],
        'top_consumers':  ['china', 'usa', 'eu', 'mexico', 'japan'],
    },
    'gold': {
        'name': 'Gold',
        'icon': '🥇',
        'tier': 2,
        'category': 'precious',
        'has_spot_price': True,
        'yahoo_ticker': 'GC=F',
        'yahoo_proxies': ['GLD', 'IAU'],
        'unit': 'USD/oz',
        'description': 'COMEX gold futures. Sanctions-evasion vehicle and BRICS+ reserve diversification signal.',
        'chokepoints': [
            'london bullion market', 'shanghai gold exchange',
            'comex', 'switzerland refining',
        ],
        'top_producers':  ['china', 'russia', 'australia', 'usa', 'canada', 'south_africa'],
        'top_consumers':  ['china', 'india', 'usa', 'eu', 'central banks'],
    },
    'graphite': {
        'name': 'Graphite',
        'icon': '⚫',
        'tier': 2,
        'category': 'industrial',
        'has_spot_price': False,    # NO PUBLIC SPOT PRICE (flake/spherical priced by grade, opaque)
        'yahoo_ticker': None,
        'yahoo_proxies': ['NVX'],   # Novonix (NASDAQ, synthetic anode) as soft sentiment proxy
        'unit': 'production volume + export-control cycle',
        'description': 'Natural graphite is the dominant lithium-ion battery ANODE material (~95g+ per kWh) with the most concentrated processing chain of any battery input: China produces ~77% of natural graphite and refines 90%+ of anode-grade spherical graphite. Beijing imposed export PERMITS on graphite products Dec 1 2023 (dual-use framing) -- an ACTIVE regime lever, exercised alongside gallium/germanium controls. Non-China supply: Mozambique (Balama, world largest natural graphite mine, Syrah Resources) + Madagascar (Molo + legacy flake) + Brazil + Tanzania. US is 100% NET IMPORT RELIANT (USGS critical mineral); IRA/DOE financing the ex-China anode chain (Syrah Vidalia LA, Anovion, Novonix). No public spot price -- tracked via export-control events, mine uptime (Balama force-majeure cycles), offtake announcements, USGS volumes.',
        'chokepoints': [
            'china export permits', 'balama', 'spherical graphite',
            'anode processing', 'heilongjiang', 'nacala corridor',
        ],
        'top_producers':  ['china', 'mozambique', 'madagascar', 'brazil'],
        'top_consumers':  ['china', 'usa', 'south_korea', 'japan', 'eu'],
    },
    'gum_arabic': {
        'name': 'Gum Arabic',
        'icon': '🌿',
        'tier': 3,
        'category': 'agricultural',
        'has_spot_price': False,    # NO PUBLIC SPOT PRICE (trade-house negotiated)
        'yahoo_ticker': None,
        'yahoo_proxies': [],
        'unit': 'export flow + conflict-corridor signals',
        'description': 'Gum arabic (acacia gum, food additive E414) is the most geographically concentrated soft commodity on Earth: Sudan supplies ~66-80% of world exports from the Kordofan/Darfur gum belt, with Chad + Nigeria the only material alternates. Irreplaceable emulsifier/stabilizer for soft drinks (Coca-Cola, PepsiCo), confectionery, pharma, and cosmetics -- buyers historically maintain strategic stockpiles precisely because of Sudanese instability (a US sanctions CARVE-OUT existed for it for decades). The 2023- war moved the trade into smuggling corridors via Chad, Egypt, and South Sudan, with RSF taxation of the gum belt. Belgium-diamonds-class structural role: tiny market, absolute concentration. No spot price -- tracked via export-corridor events, gum-belt control changes, buyer inventory reporting.',
        'chokepoints': [
            'kordofan', 'port sudan', 'el obeid',
            'gum belt', 'chad border corridor',
        ],
        'top_producers':  ['sudan', 'nigeria'],
        'top_consumers':  ['usa', 'eu'],
    },

    'fishmeal': {
        'name': 'Fishmeal',
        'icon': '\U0001F41F',
        'tier': 3,
        'category': 'agricultural',
        'has_spot_price': False,    # NO PUBLIC SPOT PRICE (trade-house negotiated)
        'yahoo_ticker': None,
        'yahoo_proxies': [],
        'unit': 'quota cycle + biomass survey',
        'description': 'Fishmeal is the top global protein input to aquaculture (farmed salmon/shrimp) and animal feed, and its supply is extraordinarily concentrated in ONE fishery: the Peruvian anchoveta of the Humboldt Current, the largest single-species fishery on Earth. No public spot price -- tracked via Peru IMARPE biomass surveys and PRODUCE quota announcements. The signal event is a SEASON CANCELLATION (e.g. the 2023 first-season closure), which spikes global fishmeal prices and ripples protein-feed costs into farmed-salmon, poultry, and aquaculture worldwide. FOOD-SECURITY frame: this is the trackable core of the viral \'guano collapse\' narrative -- the real leading indicator is the anchoveta quota, not seabird populations (guano is an ecological proxy under phosphate, not a supply source). El Nino warm-water anomalies are the recurring disruption vector.',
        'chokepoints': [
            'anchoveta', 'imarpe', 'humboldt current', 'peru fishing quota',
            'anchoveta season', 'el nino anchoveta', 'peru fishmeal',
        ],
        'top_producers':  ['peru'],
        'top_consumers':  ['china', 'norway', 'chile'],
    },
    'lithium': {
        'name': 'Lithium',
        'icon': '🔋',
        'tier': 2,
        'category': 'strategic_mineral',
        'has_spot_price': True,
        'yahoo_ticker': 'LIT',           # Global X Lithium & Battery Tech ETF
        'yahoo_proxies': ['ALB', 'SQM'],  # Albemarle + SQM (Chile)
        'unit': 'USD (LIT ETF)',
        'description': 'Global X Lithium ETF. Albemarle (ALB) and SQM (Chile) as concentrated producer proxies. Spot lithium carbonate price tracked via news.',
        'chokepoints': [
            'salar de atacama', 'salar de uyuni', 'lithium triangle',
            'greenbushes', 'kwinana', 'jiangxi china',
        ],
        'top_producers':  ['australia', 'chile', 'china', 'argentina'],
        'top_consumers':  ['china', 'korea', 'japan', 'eu', 'usa'],
    },
    'natural_gas': {
        'name': 'Natural Gas',
        'icon': '⛽',
        'tier': 1,
        'category': 'energy',
        'has_spot_price': True,
        'yahoo_ticker': 'NG=F',          # Henry Hub
        'yahoo_proxies': ['UNG'],         # Natural gas ETF
        'unit': 'USD/MMBtu',
        'description': 'Henry Hub futures + TTF/JKM news context for European/Asian spot.',
        'chokepoints': [
            'turkstream', 'nord stream', 'yamal', 'tanap',
            'qatar lng', 'sakhalin', 'arctic lng', 'galkynysh',
            'central asia china pipeline', 'tapi pipeline',
        ],
        'top_producers':  ['usa', 'russia', 'qatar', 'iran', 'china', 'turkmenistan', 'azerbaijan', 'algeria'],
        'top_consumers':  ['eu', 'china', 'japan', 'korea'],
    },
    'nickel': {
        'name': 'Nickel',
        'icon': '⚙️',
        # v1.4.1: cascade_via -- nickel HPAL (high-pressure acid leach) for
        # battery-grade nickel sulfate requires substantial sulfuric acid.
        # Indonesia (world's #1 nickel producer) imports >5M MT sulfur/yr from
        # Gulf; sulfur prices +80% there since Iran war. S&P Global Mar 17 2026.
        'cascade_via': ['sulfur'],
        'cascade_upstream_chokepoints': ['strait_of_hormuz'],
        'tier': 2,
        'category': 'industrial',
        'has_spot_price': True,
        'yahoo_ticker': 'JJN',           # iPath Nickel ETN
        'yahoo_proxies': ['VALE', 'BHP'],  # Vale + BHP (major nickel producers)
        'unit': 'USD (JJN ETN)',
        'description': 'iPath Nickel ETN tracks LME nickel futures. Vale (Brazil) and BHP (Australia/Indonesia) as integrated producer proxies. Indonesia dominates ~50% of global mined supply via HPAL/RKEF processing.',
        'chokepoints': [
            'sulawesi indonesia', 'morowali industrial park', 'weda bay',
            'norilsk russia', 'norilsk nickel', 'sorowako',
            'voiseys bay canada', 'goro new caledonia',
            'philippines nickel', 'surigao',
        ],
        'top_producers':  ['indonesia', 'philippines', 'russia', 'australia', 'canada', 'new_caledonia'],
        'top_consumers':  ['china', 'eu', 'japan', 'korea', 'usa'],
    },
    'oil': {
        'name': 'Oil',
        'icon': '🛢️',
        'tier': 1,
        'category': 'energy',
        'has_spot_price': True,
        'yahoo_ticker': 'BZ=F',         # Brent crude
        'yahoo_proxies': ['CL=F'],       # WTI fallback
        'unit': 'USD/barrel',
        'description': 'Brent crude futures. Global benchmark. WTI as fallback.',
        'chokepoints': [
            'strait of hormuz', 'bab el-mandeb', 'suez canal',
            'fujairah', 'ras tanura', 'novorossiysk', 'primorsk',
            'kozmino', 'jubail', 'hormuz blockade',
            'baku-tbilisi-ceyhan', 'btc pipeline', 'sangachal terminal',
            'caspian sea', 'ceyhan terminal', 'cpc pipeline', 'tengiz',
        ],
        'top_producers':  ['saudi_arabia', 'russia', 'iran', 'iraq', 'usa', 'uae', 'azerbaijan', 'kazakhstan', 'algeria', 'libya'],
        'top_consumers':  ['china', 'usa', 'india', 'eu'],
    },
    'nitrogen': {
        'name': 'Nitrogen (Urea / Ammonia)',
        'icon': '💨',
        # Nitrogen fertilizer (urea, ammonia, ammonium nitrate, UAN) is made via
        # Haber-Bosch from natural gas -- so nitrogen prices track gas. European
        # ammonia plants idle when gas spikes (2022 precedent); Russia/China/Gulf
        # dominate export supply. Largest fertilizer nutrient by global volume.
        'cascade_via': ['natural_gas'],
        'cascade_upstream_chokepoints': ['strait_of_hormuz'],
        'tier': 1,
        'category': 'agricultural',
        'has_spot_price': False,    # no clean public spot; tracked via urea/ammonia benchmarks + stocks
        'yahoo_ticker': None,
        'yahoo_proxies': ['CF', 'NTR', 'YARIY'],   # CF Industries + Nutrien + Yara as soft proxies
        'unit': 'production volume + gas-cost cycle',
        'description': 'No single public spot price. Tracked via urea/ammonia benchmark reporting, gas-driven European plant idling, and export-policy events (Russia/China quotas, Egypt/Qatar/Trinidad flows). CF Industries/Yara/Nutrien equity as soft sentiment proxy.',
        'chokepoints': [
            'black sea ammonia', 'togliatti-odesa pipeline', 'yuzhny port',
            'baltic urea', 'egypt urea', 'qatar ammonia', 'trinidad ammonia',
        ],
        'top_producers':  ['china', 'russia', 'india', 'usa', 'egypt', 'qatar', 'trinidad', 'indonesia'],
        'top_consumers':  ['india', 'china', 'usa', 'brazil'],
    },
    'potash': {
        'name': 'Potash',
        'icon': '🌱',
        # v1.4.1: cascade_via -- potash is one fertilizer input; phosphate
        # fertilizers (the other major class) require sulfuric acid to dissolve
        # phosphate rock. Sulfur scarcity -> phosphate fertilizer crunch ->
        # global food security pressure (Egypt, Ethiopia at risk per WFP).
        'cascade_via': ['sulfur'],
        'cascade_upstream_chokepoints': ['strait_of_hormuz'],
        'tier': 1,
        'category': 'agricultural',
        'has_spot_price': False,    # NO PUBLIC SPOT PRICE
        'yahoo_ticker': None,
        'yahoo_proxies': ['NTR', 'MOS'],   # Nutrien + Mosaic stocks as soft proxies
        'unit': 'production volume + sanctions cycle',
        'description': 'No public spot price. Tracked via production volume (USGS), sanctions events, Belaruskali/Uralkali export news. Nutrien/Mosaic stock prices as soft proxy for market sentiment.',
        'chokepoints': [
            'klaipeda port', 'saskatchewan', 'belaruskali',
            'uralkali', 'soligorsk', 'st petersburg port',
        ],
        'top_producers':  ['canada', 'russia', 'belarus', 'china', 'germany', 'israel', 'jordan'],
        'top_consumers':  ['china', 'brazil', 'india', 'usa'],
    },
    'rare_earths': {
        'name': 'Rare Earths',
        'icon': '⚗️',
        'tier': 2,
        'category': 'strategic_mineral',
        'has_spot_price': True,
        'yahoo_ticker': 'MP',            # MP Materials (US REE producer)
        'yahoo_proxies': ['REMX', 'LYC.AX'],  # VanEck REMX ETF + Lynas Australia
        'unit': 'USD (MP Materials)',
        'description': 'MP Materials (Mountain Pass mine, USA). REMX ETF as broader proxy. China dominates ~60% of production and ~85% of refining.',
        'chokepoints': [
            'baotou china', 'mountain pass usa', 'kvanefjeld greenland',
            'lynas malaysia', 'mt weld australia',
        ],
        'top_producers':  ['china', 'usa', 'australia', 'myanmar', 'greenland'],
        'top_consumers':  ['china', 'japan', 'usa', 'eu'],
    },
    'semiconductors': {
        'name': 'Semiconductors',
        'icon': '💎',
        'tier': 1,
        'category': 'strategic_chokepoint',
        'has_spot_price': True,
        'yahoo_ticker': 'TSM',           # TSMC ADR — ~60% of global foundry, ~90% of leading-edge nodes
        'yahoo_proxies': ['SOXX', 'SMH'], # iShares Semiconductor ETF + VanEck Semiconductor ETF
        'unit': 'USD (TSM ADR)',
        'description': 'TSMC ADR (TSM) as primary proxy — TSMC manufactures ~60% of global foundry output and ~90% of leading-edge (sub-7nm) chips. SOXX/SMH ETFs track broader industry. Semiconductors are THE strategic chokepoint of 21st-century geopolitics: concentrated manufacturing + concentrated equipment supply (ASML EUV monopoly) + concentrated design (US-led) creates triple-leverage geometry. Taiwan blockade scenarios, China export controls, CHIPS Act reshoring, and ASML restrictions all live here.',
        'chokepoints': [
            'tsmc fab 18', 'tsmc arizona', 'tsmc kumamoto japan',
            'samsung pyeongtaek', 'samsung austin texas',
            'sk hynix icheon', 'sk hynix wuxi china',
            'asml veldhoven netherlands', 'asml euv lithography',
            'applied materials santa clara', 'kla corporation',
            'lam research', 'tokyo electron',
            'smic shanghai', 'ymtc wuhan', 'cxmt hefei',
            'micron boise idaho', 'intel hillsboro oregon',
            'globalfoundries malta new york',
            'nvidia design', 'amd design', 'arm holdings cambridge',
            'imec leuven belgium',  # research consortium
        ],
        'top_producers':  ['taiwan', 'south_korea', 'japan', 'usa', 'netherlands', 'china'],
        'top_consumers':  ['china', 'usa', 'eu', 'japan', 'south_korea', 'taiwan'],

        # ════════════════════════════════════════════════════════════════
        # CAVE BREADCRUMBS (May 7 2026) — annotations for future investment
        # overlay. NOT consumed by Asifah; reserved for CAVE schema work.
        # See: conversation thread May 7 2026 (Rachel + Peter, Path A decision).
        # When CAVE work begins, these may migrate to a separate
        # commodity_investment_overlay.py file rather than living inline here.
        # ════════════════════════════════════════════════════════════════
        'decomposition_hint': {
            'future_sub_categories': [
                'foundry',     # leading-edge logic (TSM, Samsung Foundry)
                'memory',      # DRAM/NAND (Micron, SK Hynix, Samsung)
                'equipment',   # ASML, AMAT, LRCX, KLAC, TEL — picks-and-shovels
                'design',      # NVDA, AMD, AVGO, QCOM — AI accelerator scarcity
                'materials',   # Shin-Etsu, SUMCO, JSR — wafers + photoresist
                'legacy',      # UMC, GlobalFoundries, SMIC — mature node cyclical
            ],
            'rationale': (
                'Unified in v1 for geopolitical signal concentration: TSM as '
                'foundry-weighted proxy captures the strategic chokepoint '
                '(~60% global foundry, ~90% leading-edge) where Asifah\'s lens '
                'matters most. CAVE will need to split into sub-markets that '
                'move differently and represent different theses: foundry tracks '
                'AI capex cycle, memory is cyclical-commodity-like, equipment is '
                'picks-and-shovels for capex booms. Country exposure entries will '
                'also need re-splitting (Taiwan = foundry #1, Korea = memory #1, '
                'Netherlands = equipment #1).'
            ),
            'decided_at':  '2026-05-07',
            'decided_by':  'Rachel + Peter (Path A — ship unified, decompose later)',
        },
        'market_impact': {
            # Heuristic only — directionality may be commodity-specific.
            # CAVE will replace with calibrated betas + asymmetric exposure
            # (e.g. NVDA benefits from AI demand surge, but TSM benefits from
            # ANY semiconductor demand — different beta profiles).
            'price_up':   {'producers': 'benefit', 'consumers': 'hurt'},
            'price_down': {'producers': 'hurt',    'consumers': 'benefit'},
        },
        'market_proxies': {
            # Tradable instruments associated with this commodity.
            # CAVE bridge from signal → trade. Note that exposure type varies:
            # ETFs are diversified semi exposure; individual equities have
            # specific theses (TSM = foundry/Taiwan-risk; NVDA = AI accelerator;
            # ASML = EUV monopoly; 005930.KS = Samsung memory).
            'etfs':     ['SOXX', 'SMH'],
            'equities': [
                'TSM',         # TSMC ADR — foundry/Taiwan risk
                'NVDA',        # AI accelerator design
                'AMD',         # AI accelerator design
                'AVGO',        # broad design + networking
                'ASML',        # EUV equipment monopoly (Netherlands)
                '005930.KS',   # Samsung Electronics — memory + foundry (Korea)
                'MU',          # Micron — memory (US)
                'INTC',        # Intel — IDM + foundry reshoring (US)
            ],
            'futures':  None,  # no liquid semiconductor futures market
        },
    },
    'silicon': {
        'name': 'Silicon',
        'icon': '🟦',
        'tier': 1,
        'category': 'strategic_mineral',
        'has_spot_price': True,
        'yahoo_ticker': 'GSM',                       # Ferroglobe -- largest listed Western silicon-metal/ferrosilicon producer
        'yahoo_proxies': ['DQ', 'WCH.DE', 'TAN'],    # Daqo (CN polysilicon) + Wacker Chemie (DE) + Invesco Solar ETF
        'unit': 'USD (GSM equity proxy)',
        'description': 'Silicon (metallurgical + ferrosilicon + polysilicon) -- the chip-and-solar backbone. Cascade: quartz/silica -> metallurgical silicon (~98-99%, carbothermic reduction) -> polysilicon (Siemens process, 6N-9N+) -> wafers -> chips/solar cells. China ~80% of global silicon materials (USGS 2024) and >80% of polysilicon. Crucible chokepoint: Spruce Pine NC (Sibelco/Unimin + The Quartz Corp) supplies ~80%+ of the ultra-high-purity quartz used to melt silicon -- the Helene-flood 2024 single-point-of-failure. No liquid Western silicon futures; tracked via Ferroglobe (GSM) + Daqo/Wacker (polysilicon) + solar ETF; Chinese industrial-silicon futures trade on the Guangzhou Futures Exchange. Added to the 2025 U.S. Critical Minerals List (esp. ferroalloys); CHIPS Act demand surge; Commerce Section 232 polysilicon probe.',
        'chokepoints': [
            'spruce pine quartz', 'high-purity quartz', 'hpq crucible',
            'sibelco iota', 'the quartz corp', 'drag norway quartz',
            'xinjiang polysilicon', 'guangzhou silicon futures',
            'wacker burghausen', 'hemlock michigan', 'daqo xinjiang',
        ],
        'top_producers':  ['china', 'russia', 'brazil', 'norway', 'usa', 'france', 'malaysia'],
        'top_consumers':  ['china', 'usa', 'eu', 'japan', 'korea', 'taiwan'],
    },
    'silver': {
        'name': 'Silver',
        'icon': '🪙',
        'tier': 2,
        'category': 'precious',
        'has_spot_price': True,
        'yahoo_ticker': 'SI=F',          # COMEX silver futures
        'yahoo_proxies': ['SLV', 'PSLV'],  # iShares Silver Trust + Sprott Physical Silver
        'unit': 'USD/oz',
        'description': 'COMEX silver futures. Mexico is world #1 producer (~6,120 MT). Industrial/photovoltaic demand + precious-metal monetary properties. China #2 producer + dominant in solar manufacturing.',
        'chokepoints': [
            'fresnillo mexico', 'saucito mexico', 'antamina peru',
            'uchucchacua peru', 'cannington australia',
            'comex silver', 'shanghai silver', 'london bullion',
        ],
        'top_producers':  ['mexico', 'china', 'peru', 'russia', 'poland', 'chile', 'australia'],
        'top_consumers':  ['china', 'india', 'usa', 'eu', 'japan'],
    },
    'soybeans': {
        'name': 'Soybeans',
        'icon': '🫘',
        'tier': 2,
        'category': 'agricultural',
        'has_spot_price': True,
        'yahoo_ticker': 'ZS=F',
        'yahoo_proxies': ['SOYB'],
        'unit': 'USD/bushel',
        'description': 'CBOT soybeans. China is the dominant consumer (~60%).',
        'chokepoints': [
            'panama canal', 'brazil port santos', 'mississippi river',
            'us gulf', 'paranaguá',
        ],
        'top_producers':  ['brazil', 'usa', 'argentina', 'china', 'india'],
        'top_consumers':  ['china', 'eu', 'mexico', 'japan'],
    },
    'sugar': {
        'name': 'Sugar',
        'icon': '🌾',
        'tier': 2,
        'category': 'agricultural',
        'has_spot_price': True,
        'yahoo_ticker': 'SB=F',         # NY #11 raw sugar futures (global benchmark)
        'yahoo_proxies': ['CANE'],       # Teucrium Sugar ETF
        'unit': 'USD/lb',
        'description': 'NY #11 raw sugar futures. Brazil dominates exports (~36 MMT/yr, ~50% global trade); India is the world\'s #1 consumer + policy price-setter via export quota toggles; Thailand is ASEAN supply anchor; Cuba is the canonical historic-reversal case (former #1 producer ~150 years, now net importer post-2024 collapse).',
        'chokepoints': [
            'brazil port santos', 'paranaguá', 'recife',
            'kandla port', 'mumbai port',
            'bangkok port', 'laem chabang',
            'mariel port',
        ],
        'top_producers':  ['brazil', 'india', 'thailand', 'china', 'eu', 'usa', 'mexico', 'australia'],
        'top_consumers':  ['india', 'china', 'eu', 'usa', 'brazil', 'indonesia'],
    },
    'rice': {
        'name': 'Rice',
        'icon': '🍚',
        'tier': 2,
        'category': 'agricultural',
        'has_spot_price': True,
        'yahoo_ticker': 'ZR=F',         # CBOT rough rice futures (global benchmark)
        'yahoo_proxies': [],
        'unit': 'USD/cwt',
        'description': 'CBOT rough rice futures. Staple calorie for roughly half the world, concentrated in Asia. India is the leading exporter and the dominant policy price-setter (its mid-2023 non-basmati export ban pushed global prices to multi-year highs); Thailand and Vietnam are the next-largest exporters; China is the largest producer and consumer. Top importers - Philippines, Indonesia, Nigeria, West Africa, the Gulf - are highly exposed to export-ban shocks, which makes rice a recurring food-security and political-stability trigger. Watch: India export-policy toggles, monsoon and El Nino effects on Asian harvests, Philippines and Indonesia import tenders, FAO rice price index.',
        'chokepoints': [
            'kandla port', 'kakinada port', 'mundra port',
            'bangkok port', 'laem chabang',
            'ho chi minh port', 'cai mep',
            'manila port', 'tanjung priok',
        ],
        'top_producers':  ['china', 'india', 'indonesia', 'vietnam', 'thailand', 'bangladesh', 'usa'],
        'top_consumers':  ['china', 'india', 'indonesia', 'philippines', 'nigeria', 'iran', 'iraq', 'saudi_arabia'],
    },
    'coffee': {
        'name': 'Coffee',
        'icon': '☕',
        'tier': 2,
        'category': 'agricultural',
        'has_spot_price': True,
        'yahoo_ticker': 'KC=F',         # ICE Arabica coffee futures (global benchmark)
        'yahoo_proxies': ['JO'],         # iPath Coffee ETN
        'unit': 'USD/lb',
        'description': 'ICE Arabica coffee futures. Brazil is the largest producer (Arabica); Vietnam is the next-largest overall and the leading robusta producer; Indonesia is a major producer. This is an export-earnings and climate-shock commodity rather than an instability signal - prices swing hard on Brazilian frost and drought and on Vietnamese Central Highlands dry spells, and coffee is a major export-revenue driver for producer economies. Watch: Brazil weather (frost and drought), Vietnam Central Highlands rainfall, ICE certified-stock levels, robusta-to-arabica spread.',
        'chokepoints': [
            'santos port', 'port of santos',
            'ho chi minh port', 'cai mep',
            'panama canal',
        ],
        'top_producers':  ['brazil', 'vietnam', 'colombia', 'indonesia', 'ethiopia', 'honduras'],
        'top_consumers':  ['eu', 'usa', 'brazil', 'japan'],
    },
    # ============================================================
    # SULFUR (commodity #17 -- May 17, 2026)
    # The "king of chemicals" -- byproduct of Gulf oil+gas refining
    # that powers copper processing, nickel HPAL, fertilizer
    # (phosphate + ammonium sulfate), batteries, semiconductors.
    # CASCADE COMMODITY: not consumed directly by humans, but its
    # scarcity propagates upstream through 5 downstream sectors
    # simultaneously. Iran war 2026 + Strait of Hormuz closure
    # (Feb 28) trapped ~45% of global sulfur trade. China announced
    # sulfur export ban; Turkey announced ban; India considering.
    # Sulfuric acid prices: +30% globally, +80% Indonesia.
    # Source: Reuters/Andy Home Apr 17 2026; S&P Global Mar 17 2026;
    # FP Apr 17 2026; UPI May 10 2026.
    # ============================================================
    'sulfur': {
        'name': 'Sulfur / Sulfuric Acid',
        'icon': '⚗️',
        'tier': 2,
        'category': 'industrial_chemical',
        'has_spot_price': False,         # No clean public spot price; trade through opaque B2B contracts
        'yahoo_ticker': None,
        'yahoo_proxies': ['MOS'],         # The Mosaic Company (sulfur-intensive fertilizer producer)
        'unit': 'USD/MT (CFR Asia spot, indicative)',
        'description': 'King of chemicals. Sulfur is a byproduct of oil + natural gas refining (Gulf states produce ~45% of global trade). Converted to sulfuric acid for: (1) fertilizers (66% of demand -- phosphate + ammonium sulfate), (2) copper oxide processing (solvent extraction), (3) nickel HPAL battery-grade processing, (4) lithium refining, (5) cobalt refining, (6) semiconductor wafer cleaning. CASCADE COMMODITY: its scarcity propagates upstream from Hormuz closure into 5 seemingly unrelated downstream sectors. Iran war 2026 + Hormuz closure trapped Gulf supply; China announced export ban (largest sulfuric acid producer protecting domestic); Turkey banned exports; India considering. Sulfuric acid prices up 30% globally, 80% Indonesia. Ivanhoe Mines founder: "if disruption >3 weeks, copper oxide operations will close."',
        'chokepoints': [
            'strait of hormuz', 'persian gulf shipping',
            'ras laffan qatar', 'jubail saudi arabia',
            'ruwais uae', 'bandar abbas iran',
            'nantong port china', 'shanghai port china',
        ],
        'top_producers':  ['iran', 'qatar', 'saudi_arabia', 'uae', 'china', 'usa', 'canada', 'russia', 'kazakhstan'],
        'top_consumers':  ['china', 'morocco', 'indonesia', 'chile', 'usa', 'india', 'brazil'],
        # Cascade metadata: which downstream commodities are affected when sulfur is constrained
        'cascade_downstream': [
            'potash',          # phosphate fertilizer production requires sulfuric acid
            'copper',          # copper oxide solvent extraction needs sulfuric acid
            'nickel',          # nickel HPAL for EV battery chemicals
            'lithium',         # lithium refining (cathode active materials)
            'cobalt',          # cobalt refining
            'semiconductors',  # wafer cleaning
        ],
        # Upstream chokepoint: when this is constrained, sulfur is constrained
        'cascade_upstream': ['oil', 'natural_gas'],  # because sulfur is byproduct of refining
    },
    'uranium': {
        'name': 'Uranium',
        'icon': '☢️',
        'tier': 2,
        'category': 'strategic_mineral',
        'has_spot_price': True,
        'yahoo_ticker': 'URA',           # Global X Uranium ETF (best public proxy)
        'yahoo_proxies': ['SRUUF', 'CCJ'],  # Sprott Physical Uranium Trust + Cameco
        'unit': 'USD (URA ETF price)',
        'description': 'Global X Uranium ETF. Spot price (UxC) is paywalled; URA tracks the equity exposure. Sprott (SRUUF) and Cameco (CCJ) as proxies.',
        'chokepoints': [
            'kazatomprom', 'cameco', 'orano', 'rosatom',
            'niger uranium', 'arlit niger',
        ],
        'top_producers':  ['kazakhstan', 'canada', 'australia', 'niger', 'russia', 'namibia'],
        'top_consumers':  ['usa', 'france', 'china', 'russia', 'korea', 'japan'],
    },
    'wheat': {
        'name': 'Wheat',
        'icon': '🌾',
        'tier': 1,
        'category': 'agricultural',
        'has_spot_price': True,
        'yahoo_ticker': 'ZW=F',          # CBOT wheat
        'yahoo_proxies': ['WEAT'],        # Teucrium Wheat ETF
        'unit': 'USD/bushel',
        'description': 'CBOT wheat futures. Russia + Ukraine = ~25% of global exports.',
        'chokepoints': [
            'black sea grain corridor', 'odesa port', 'mykolaiv port',
            'novorossiysk', 'bosphorus',
        ],
        'top_producers':  ['russia', 'eu', 'china', 'india', 'usa', 'ukraine', 'canada', 'australia'],
        'top_consumers':  ['china', 'india', 'eu', 'egypt', 'turkey'],
    },
    'pgm': {
        'name': 'Platinum-Group Metals',
        'icon': '⚪',
        'tier': 1,
        'category': 'industrial',
        'has_spot_price': True,
        'yahoo_ticker': 'PPLT',          # abrdn Physical Platinum Shares ETF
        'yahoo_proxies': ['PALL', 'SBSW', 'AAL.L'],  # Palladium ETF + Sibanye-Stillwater + Anglo American
        'unit': 'USD (PPLT ETF)',
        'description': 'Platinum-group metals (platinum, palladium, rhodium, iridium, ruthenium, osmium). South Africa = ~70% global platinum and ~40% palladium; Russia (Norilsk) = ~40% palladium and the swing producer. Demand driven by autocatalysts (gasoline=palladium, diesel=platinum), hydrogen fuel cells (PEM electrolyzers + FCEVs), semiconductor catalysts. Bushveld Complex (Limpopo, SA) is the planetary spigot. Strategic asymmetry: Western alternatives to South African + Russian supply are minimal — North American Palladium (Ontario) + Stillwater (Montana) cover <10%.',
        'chokepoints': [
            'bushveld complex', 'rustenburg', 'mogalakwena', 'limpopo platinum',
            'amplats', 'anglo american platinum', 'sibanye-stillwater',
            'impala platinum', 'implats', 'lonmin', 'marikana',
            'norilsk russia', 'nornickel palladium', 'stillwater montana',
            'north american palladium', 'lac des iles',
        ],
        'top_producers':  ['south_africa', 'russia', 'zimbabwe', 'canada', 'usa'],
        'top_consumers':  ['china', 'eu', 'usa', 'japan', 'korea'],
    },
    'chromium': {
        'name': 'Chromium / Ferrochrome',
        'icon': '🔩',
        'tier': 2,
        'category': 'industrial',
        'has_spot_price': False,
        'yahoo_ticker': None,
        'yahoo_proxies': ['GLEN.L', 'ENOR.OL'],  # Glencore + Eramet (ferroalloys)
        'unit': 'USD/MT ferrochrome (proxy)',
        'description': 'Chromium is the irreplaceable alloying element for stainless steel (no substitute exists). South Africa holds ~70% of global chromium production (Bushveld); Kazakhstan + Turkey + India also material. China dominates ferrochrome smelting via electricity-intensive submerged-arc furnaces. Western strategic exposure: chromium is on US/EU critical minerals lists but receives less attention than cobalt/REEs despite tighter supply concentration. SA ferrochrome industry has been hollowed out by China since 2010 (electricity cost arbitrage); SA ore now exported raw to China. Watch: South African Eskom load-shedding (kills SA smelting), Kazakhstan rail/port logistics, Glencore/Tharisa output guidance.',
        'chokepoints': [
            'bushveld chromium', 'rustenburg chrome', 'tharisa',
            'kazakhstan chromium', 'donskoy gok', 'eramet gabon',
            'sukinda india', 'tata steel chrome',
        ],
        'top_producers':  ['south_africa', 'kazakhstan', 'turkey', 'india', 'finland', 'zimbabwe'],
        'top_consumers':  ['china', 'india', 'eu', 'usa', 'korea', 'japan'],
    },
    'manganese': {
        'name': 'Manganese',
        'icon': '🟪',
        'tier': 2,
        'category': 'industrial',
        'has_spot_price': False,
        'yahoo_ticker': None,
        'yahoo_proxies': ['ERA.PA', 'S32.AX', 'GLEN.L'],  # Eramet (Moanda Gabon) + South32 + Glencore
        'unit': 'USD/MTU (manganese ore proxy)',
        'description': 'Manganese is the irreplaceable steel-additive (90% of demand) plus rapidly-growing EV battery cathode material (LFP and NMC chemistries both contain manganese). South Africa + Gabon = ~50% of global supply. Eramet Moanda mine (Gabon) is one of the largest and highest-grade. South32 GEMCO (Australia) was the Western anchor — but partially knocked offline by Cyclone Megan March 2024, recovery ongoing. Battery-grade high-purity manganese sulfate (HPMSM) supply chain is ~95% Chinese-processed regardless of origin. China dominates downstream just as it does with cobalt + REE. EV battery demand projected to drive ~30% of manganese demand by 2030.',
        'chokepoints': [
            'kalahari manganese field', 'hotazel', 'south32 hotazel',
            'mamatwan', 'wessels mine', 'tshipi manganese',
            'moanda gabon', 'eramet moanda', 'comilog',
            'gemco groote eylandt', 'cyclone megan',
            'bootu creek', 'element 25',
        ],
        'top_producers':  ['south_africa', 'gabon', 'australia', 'brazil', 'china', 'ghana'],
        'top_consumers':  ['china', 'india', 'japan', 'korea', 'usa', 'eu'],
    },
    'phosphate': {
        'name': 'Phosphate Rock',
        'icon': '🪨',
        'tier': 1,
        'category': 'agricultural',
        'has_spot_price': False,
        'yahoo_ticker': 'MOS',           # Mosaic Co
        'yahoo_proxies': ['NTR.TO', 'OCP-MA'],  # Nutrien + OCP Maroc (where listed)
        'unit': 'USD/MT phosphate rock (proxy)',
        'description': 'Phosphate is the irreplaceable second pillar of global fertilizer (N-P-K: nitrogen, phosphate, potassium). Morocco/Western Sahara reserves = ~70% of global proven reserves — the most geographically concentrated fertilizer input on Earth. OCP Group (Moroccan state-owned, sovereign-controlled) operates Khouribga + Bou Craa mines and is the swing producer for global phosphate trade. NOTE ON SOVEREIGNTY: OCP operates phosphate mines in both Morocco proper and Western Sahara (Bou Craa). Western Sahara political status remains contested; certain EU court rulings have held that contracts requiring Western Sahara provenance be treated separately. The platform reports OCP combined output under Morocco as the operating entity, mirroring official US State Department neutral posture, while noting source provenance distinctions some buyers apply. The other top-5 producers (China, USA Florida + North Carolina, Russia, Jordan) have a fraction of Moroccan reserves. CASCADE LINK: phosphate requires sulfuric acid for processing into DAP/MAP fertilizers — Hormuz sulfur cascade flows directly into phosphate prices. Watch: OCP guidance, Moroccan-EU disputes over Western Sahara provenance, China DAP/MAP export taxes, India phosphate import tenders. \u26A0\uFE0F GUANO SUB-SIGNAL (ecological indicator, NOT material supply): Peruvian seabird guano is the pre-industrial renewable phosphate source, but at modern scale it is a rounding error (single-digit-thousands of tonnes vs. ~50M tonnes/yr of mined rock). Viral framing treats guano-colony collapse as a fertilizer crisis; the platform does NOT. Guano seabird decline is a real ECOLOGICAL proxy for anchoveta stress in the Humboldt Current -- so it reads as a leading indicator for Peru FISHMEAL (food/feed), not for phosphate supply. See peru.fishmeal.',
        'chokepoints': [
            'khouribga', 'bou craa', 'youssoufia', 'gantour',
            'ocp group', 'ocp maroc', 'phosboucraa',
            'jorf lasfar', 'safi morocco',
            'aqaba potash', 'arab potash',
            'mosaic florida', 'central florida phosphate',
            'kola peninsula russia', 'phosagro',
            'guano', 'peruvian guano', 'seabird collapse', 'anchoveta',  # ecological sub-signal (-> fishmeal, not supply)
        ],
        'top_producers':  ['morocco', 'china', 'usa', 'russia', 'jordan', 'tunisia', 'saudi_arabia'],
        'top_consumers':  ['india', 'brazil', 'china', 'usa', 'eu'],
    },
    'diamonds': {
        'name': 'Diamonds (Rough)',
        'icon': '💎',
        'tier': 2,
        'category': 'precious',
        'has_spot_price': False,
        'yahoo_ticker': None,
        'yahoo_proxies': ['AAL.L', 'PDL.AX', 'LUC.TO'],  # Anglo American (De Beers parent), Petra, Lucara
        'unit': 'USD/carat (rough, proxy)',
                'description': (
            'Rough diamonds: ~$15-20B annual global production by value. '
            'Botswana + Russia + Canada + Australia (Argyle closed 2020) + Angola + Namibia + DRC + South Africa + Sierra Leone are the producer set. '
            'The four downstream trade/cutting/retail hubs: Antwerp (Belgium, ~84% of world rough trade), Mumbai/Surat (India, ~90% world cutting+polishing by volume), Ramat Gan (Israel, ~50% of US polished imports), and Dubai (UAE, rising third hub). '
            'G7 SANCTIONS REGIME (active since Jan 1 2024): G7 imposed direct ban on Russian diamonds, then ban on Russian diamonds via third countries from March 1 2024. '
            'Verification system requires certification-of-origin via designated "nodes": Antwerp (Belgium) operational since March 1 2024 as the FIRST cert node; Botswana cert node under construction with G7 technical team (joint statement Nov 27 2024). '
            'This makes Belgium + Botswana de facto sanctions-enforcement actors — foreign-policy weight, not just commercial.'
        ),
        'chokepoints': [
            'jwaneng', 'orapa', 'debswana', 'okavango diamond company',
            'antwerp diamond hub', 'awdc', 'gia certification',
            'de beers', 'anglo american de beers',
            'alrosa', 'mirny diamonds', 'siberian diamonds',
            'catoca angola', 'endiama',
            'namdeb', 'oranjemund', 'debmarine',
            'mwadui tanzania', 'venetia mine', 'cullinan mine',
            'kimberley process', 'kimberley certification',
            'g7 diamond ban', 'g7 russian diamonds',
        ],
        'top_producers':  ['botswana', 'russia', 'canada', 'angola', 'south_africa', 'namibia', 'drc', 'zimbabwe'],
        'top_consumers':  ['usa', 'india', 'china', 'eu', 'uae', 'hong_kong'],
    },
    'bauxite': {
        'name': 'Bauxite',
        'icon': '🟫',
        'tier': 2,
        'category': 'industrial',
        'has_spot_price': False,
        'yahoo_ticker': None,
        'yahoo_proxies': ['AA', 'RIO', 'NHYDY'],  # Alcoa + Rio Tinto + Norsk Hydro (alumina/aluminum)
        'unit': 'USD/MT bauxite (proxy)',
        'description': 'Bauxite is the primary aluminum precursor (~4-6 tonnes bauxite → 2 tonnes alumina → 1 tonne aluminum). Guinea = ~25% of global production and the single most important non-Chinese supplier; China is the #1 importer and ~55% of its bauxite comes from Guinea via the Boké region. Australia + Brazil + Indonesia + India also material. CMA-style supply shock risk: Guinea has experienced multiple coups (2008, 2021) — Sept 2021 Doumbouya coup briefly disrupted bauxite shipments and spiked alumina prices ~10% in a week. Chinese Belt-and-Road heavy infrastructure footprint in Guinea (Boké railway, Conakry port) — same playbook as DRC cobalt. Simandou iron ore megaproject (separate commodity but same political risk profile) coming online 2026 reshapes Guinea geopolitically. Watch: Doumbouya transition timeline, CBG/SMB/EGA output, Conakry port disruptions, Chinese SOE Guinea presence.',
        'chokepoints': [
            'boké region', 'cbg guinea', 'sangaredi',
            'smb winning', 'emirates global aluminium', 'ega guinea',
            'conakry port', 'kamsar port',
            'weipa queensland', 'gove arnhem',
            'porto trombetas brazil', 'mineracao rio do norte',
            'orin bauxite', 'huntly western australia',
        ],
        'top_producers':  ['australia', 'guinea', 'china', 'brazil', 'indonesia', 'india'],
        'top_consumers':  ['china', 'india', 'usa', 'eu', 'russia', 'uae'],
    },

    'iron_ore': {
        'name': 'Iron Ore',
        'icon': '🧲',
        'tier': 1,
        'category': 'industrial',
        'has_spot_price': False,
        'yahoo_ticker': None,
        'yahoo_proxies': ['VALE', 'RIO', 'BHP'],
        'unit': 'USD/MT (62% Fe CFR China)',
        'description': 'Primary steelmaking input. Australia is the #1 exporter (Pilbara: Rio Tinto, BHP, Fortescue); Brazil #2 (Vale, Carajas high-grade, ~336 Mt 2025). China is the dominant importer/consumer (~70% of seaborne trade) -- the China steel/property cycle sets the price. data_as_of 2026-06.',
        'chokepoints': [
            'port hedland', 'dampier', 'pilbara', 'carajas', 'ponta da madeira',
            'simandou guinea', 'tubarao port', 'china steel mills',
        ],
        'top_producers':  ['australia', 'brazil', 'china', 'india', 'russia', 'south_africa', 'ukraine', 'guinea'],
        'top_consumers':  ['china', 'japan', 'south_korea', 'eu', 'india'],
    },
    'coal': {
        'name': 'Coal',
        'icon': '🪨',
        'tier': 1,
        'category': 'energy',
        'has_spot_price': False,
        'yahoo_ticker': None,
        'yahoo_proxies': ['BTU', 'ARCH', 'GLNCY'],
        'unit': 'USD/MT (Newcastle thermal)',
        'description': 'Thermal (power) + metallurgical (steelmaking) coal. China produces ~52% of global output and is the swing consumer; Indonesia is the #1 thermal EXPORTER, Australia the top metallurgical exporter. Top six (China, India, Indonesia, USA, Australia, Russia) = ~87% of supply. data_as_of 2026-06.',
        'chokepoints': [
            'newcastle port', 'richards bay', 'kalimantan', 'bowen basin',
            'hunter valley', 'powder river basin', 'qinhuangdao',
        ],
        'top_producers':  ['china', 'india', 'indonesia', 'usa', 'australia', 'russia', 'south_africa'],
        'top_consumers':  ['china', 'india', 'japan', 'south_korea', 'eu'],
    },
    'tantalum': {
        'name': 'Tantalum',
        'icon': '🔩',
        'tier': 2,
        'category': 'strategic_mineral',
        'has_spot_price': False,
        'yahoo_ticker': None,
        'yahoo_proxies': [],
        'unit': 'USD/kg Ta2O5',
        'description': 'Capacitor + superalloy metal (coltan). The DRC + Rwanda dominate mined supply (~2/3 of global), much of it artisanal with conflict-mineral (3TG) traceability exposure; Brazil + China round out supply. Critical for electronics + defense. data_as_of 2026-06.',
        'chokepoints': [
            'coltan', 'kivu drc', 'rwanda processing', 'great lakes region',
            '3tg conflict minerals', 'pilbara tantalum',
        ],
        'top_producers':  ['drc', 'rwanda', 'brazil', 'china', 'nigeria'],
        'top_consumers':  ['china', 'usa', 'japan', 'eu'],
    },
    'sunflower_oil': {
        'name': 'Sunflower Oil',
        'icon': '🌻',
        'tier': 2,
        'category': 'agricultural',
        'has_spot_price': False,
        'yahoo_ticker': None,
        'yahoo_proxies': [],
        'unit': 'USD/MT',
        'description': 'Major vegetable/cooking oil. Ukraine + Russia together supply the majority of world sunflower-oil exports -- Black Sea logistics + the war directly gate global supply; Argentina is the #3 exporter. India + the EU are the largest importers. data_as_of 2026-06.',
        'chokepoints': [
            'black sea', 'odesa port', 'rosario argentina', 'novorossiysk',
            'india edible oil imports',
        ],
        'top_producers':  ['ukraine', 'russia', 'argentina'],
        'top_consumers':  ['india', 'eu', 'china', 'turkey', 'egypt'],
    },
}
# ========================================
# COMMODITY KEYWORD SETS
# ========================================
# Used for matching news articles to commodities.
# Each commodity has English + (where relevant) multilingual keywords.

COMMODITY_KEYWORDS = {
    'cobalt': [
        # Producers / state actors
        'cobalt', 'cobalt prices', 'cobalt market', 'cobalt sulphate',
        'cobalt hydroxide', 'cobalt metal', 'cobalt concentrate',
        'drc cobalt', 'congo cobalt', 'congolese cobalt',
        'indonesia cobalt', 'indonesian cobalt',
        # Companies
        'glencore cobalt', 'cmoc cobalt', 'china molybdenum',
        'huayou cobalt', 'jinchuan cobalt', 'umicore cobalt',
        'tenke fungurume', 'kisanfu', 'mutanda',
        'gecamines', 'ivanhoe mines',
        # Geographic / logistical
        'kolwezi', 'lubumbashi', 'katanga cobalt', 'lobito corridor',
        'sulawesi cobalt', 'morowali', 'weda bay',
        # Market events
        'cobalt export ban', 'drc cobalt quota', 'cobalt sanctions',
        'cobalt artisanal mining', 'cobalt child labor',
        'cobalt refining china', 'lme cobalt',
        'battery metal', 'nmc battery', 'nca battery',
        'foreign entity of concern', 'feoc cobalt', 'ira critical minerals',
        # French (DRC)
        'cobalt rdc', 'cobalt congolais', 'mines de cobalt',
        # Chinese
        '钴', '钴价', '钴矿', '钴精矿',
    ],
    'copper': [
        'copper', 'copper prices', 'copper futures',
        'comex copper', 'lme copper', 'doctor copper',
        'antofagasta copper', 'escondida', 'chuquicamata',
        'codelco', 'freeport-mcmoran', 'glencore copper',
        'first quantum', 'cobre panama', 'panama copper',
        'lubumbashi', 'katanga copper', 'drc copper',
        'china copper imports', 'copper smelter',
        'copper concentrate', 'copper cathode',
        # Spanish
        'cobre', 'cobre chile', 'cobre perú',
        # Chinese
        '铜', '铜价', '铜进口',
    ],
    'corn': [
        'corn', 'maize', 'corn prices', 'corn futures', 'cbot corn',
        'corn harvest', 'corn ethanol', 'corn export',
        'ukrainian corn', 'us corn', 'brazil corn safrinha',
        'argentina corn', 'corn yields', 'corn drought',
        'usda corn', 'wasde corn',
        # Spanish
        'maíz', 'cosecha de maíz',
        # Chinese
        '玉米',
    ],
    'gold': [
        'gold', 'gold prices', 'gold futures', 'comex gold',
        'gold reserves', 'central bank gold', 'gold buying',
        'china gold reserves', 'russian gold', 'gold sanctions',
        'london bullion', 'shanghai gold exchange',
        'gold etf', 'gold etfs', 'gold imports',
        'world gold council', 'gold demand', 'gold supply',
        'brics gold', 'gold standard', 'gold-backed currency',
        # Russian
        'золото', 'золотовалютные резервы',
        # Chinese
        '黄金', '黄金储备', '黄金价格',
        # Arabic
        'الذهب', 'أسعار الذهب',
            # Sahel / Sudan war-gold (Jul 2026 Africa expansion)
        'loulo-gounkoto', 'loulo gounkoto', 'barrick mali', 'mali gold',
        'sudan gold', 'rsf gold', 'darfur gold', 'jebel amer',
        'burkina faso gold', 'sopamib', 'nordgold', 'ndassima',
        'artisanal gold sahel', 'gold smuggling uae',
    ],
    'graphite': [
        'graphite', 'natural graphite', 'flake graphite', 'spherical graphite',
        'graphite anode', 'anode material', 'battery anode',
        'china graphite exports', 'graphite export controls', 'graphite export permits',
        'syrah resources', 'balama graphite', 'balama mine',
        'molo graphite', 'nextsource', 'novonix', 'anovion', 'vidalia anode',
        'graphite mining', 'anode-grade graphite', 'synthetic graphite',
    ],
    'gum_arabic': [
        'gum arabic', 'acacia gum', 'acacia senegal', 'e414',
        'gum arabic exports', 'sudan gum arabic', 'gum belt',
        'kordofan gum', 'hashab', 'talha gum',
        'gum arabic supply', 'gum arabic shortage', 'gum arabic smuggling',
    ],
    'fishmeal': [
        'fishmeal', 'fish meal', 'anchoveta', 'anchovy peru',
        'peru fishing quota', 'anchoveta quota', 'anchoveta season',
        'imarpe', 'peru fishing ban', 'fishing season cancelled peru',
        'fishmeal price', 'aquaculture feed', 'fish feed shortage',
        'humboldt current', 'el nino fishing peru', 'peru produce quota',
        # guano ecological proxy (rolls into fishmeal read, NOT phosphate supply)
        'guano', 'peruvian guano', 'guano birds', 'seabird collapse',
        'guano islands', 'cormorant collapse', 'boobies peru',
    ],
    'lithium': [
        'lithium', 'lithium prices', 'lithium carbonate', 'lithium hydroxide',
        'spodumene', 'salar de atacama', 'salar de uyuni',
        'sqm lithium', 'albemarle', 'tianqi lithium',
        'ganfeng lithium', 'pilbara lithium', 'greenbushes',
        'lithium triangle', 'lithium argentina', 'lithium chile',
        'lithium bolivia', 'lithium battery', 'ev battery lithium',
        'lithium mining', 'lithium refinery', 'lithium tariff',
        'china lithium', 'australian lithium',
        # Spanish
        'litio', 'litio chile', 'litio argentina', 'litio bolivia',
        # Chinese
        '锂', '碳酸锂', '锂电池',
            # Mali lithium (Jul 2026 Africa expansion)
        'goulamina', 'mali lithium', 'bougouni lithium', 'kodal',
    ],
    'natural_gas': [
        'natural gas', 'lng', 'liquefied natural gas',
        'henry hub', 'ttf gas', 'jkm price', 'gas prices',
        'nord stream', 'turkstream', 'yamal lng',
        'qatar lng', 'us lng exports', 'european gas',
        'gas pipeline', 'gas storage europe', 'gas crisis',
        'gazprom', 'novatek', 'qatargas', 'shell lng',
        'sakhalin', 'arctic lng',
        'galkynysh', 'central asia china pipeline', 'tapi pipeline',
        'turkmenistan gas', 'turkmen gas',
        # Russian
        'природный газ', 'газпром', 'газопровод', 'спг',
        # Chinese
        '天然气', '液化天然气',
            # Mozambique Rovuma (Jul 2026 Africa expansion)
        'rovuma', 'mozambique lng', 'cabo delgado lng', 'coral sul',
        'coral norte', 'afungi', 'totalenergies mozambique',
    ],
    'nickel': [
        # Producers / state actors
        'nickel', 'nickel prices', 'nickel futures', 'lme nickel',
        'nickel pig iron', 'npi', 'ferronickel', 'nickel sulphate',
        'class 1 nickel', 'class 2 nickel', 'high pressure acid leach', 'hpal',
        # Companies
        'norilsk nickel', 'nornickel', 'vale nickel',
        'bhp nickel', 'sumitomo metal mining', 'tsingshan',
        'huayou nickel', 'eramet', 'glencore nickel',
        # Geographic / logistical
        'indonesia nickel', 'indonesian nickel', 'sulawesi nickel',
        'morowali industrial park', 'weda bay nickel', 'sorowako',
        'philippines nickel', 'surigao', 'palawan nickel',
        'norilsk russia', 'kun-manie', 'voiseys bay',
        'goro new caledonia', 'koniambo new caledonia',
        # Market events
        'nickel export ban', 'indonesia nickel ban', 'nickel sanctions',
        'nickel mining moratorium', 'nickel laterite',
        'ev battery nickel', 'cathode nickel', 'tesla nickel',
        'foreign entity of concern nickel',
        # Russian
        'никель', 'норильский никель',
        # Chinese
        '镍', '镍价', '镍矿', '不锈钢',
        # Indonesian
        'nikel indonesia', 'tambang nikel',
    ],
    'oil': [
        # Producers / state actors
        'crude oil', 'oil prices', 'oil futures', 'brent crude', 'wti',
        'opec', 'opec+', 'opec plus', 'saudi oil', 'aramco',
        'russian oil', 'urals crude', 'iranian oil',
        'venezuelan oil', 'pdvsa', 'oil sanctions',
        'oil embargo', 'oil price cap', 'g7 price cap',
        # Companies / refining
        'rosneft', 'lukoil', 'gazprom neft', 'cnpc oil',
        'chevron oil', 'exxonmobil', 'totalenergies',
        'refinery attack', 'oil tanker attack', 'shadow fleet',
        # Geographic / logistical
        'fujairah terminal', 'ras tanura', 'novorossiysk',
        'kozmino terminal', 'primorsk port',
        'cpc pipeline', 'tengiz oil', 'kashagan', 'karachaganak',
        # Russian
        'нефть', 'цена на нефть', 'нефтепровод', 'нефтяные санкции',
        # Arabic
        'النفط', 'أسعار النفط', 'أرامكو', 'أوبك',
        # Farsi
        'نفت', 'صادرات نفت ایران', 'تحریم نفت',
        # Chinese
        '原油', '石油价格', '石油进口',
    ],
    'nitrogen': [
        'nitrogen fertilizer', 'nitrogen fertiliser', 'nitrogenous fertilizer',
        'urea', 'urea prices', 'urea exports', 'granular urea', 'prilled urea',
        'urea tender', 'india urea', 'urea subsidy', 'egyptian urea', 'iran urea',
        'ammonia', 'ammonia prices', 'anhydrous ammonia', 'green ammonia', 'ammonia exports',
        'ammonium nitrate', 'calcium ammonium nitrate', 'ammonium sulphate',
        'uan fertilizer', 'uan solution', 'nitrate fertilizer',
        'haber-bosch', 'haber bosch',
        'cf industries', 'yara', 'nutrien nitrogen', 'oci nitrogen', 'eurochem nitrogen',
        'togliattiazot', 'qafco', 'phosagro nitrogen',
    ],
    'potash': [
        'potash', 'belaruskali', 'uralkali', 'nutrien',
        'mosaic potash', 'k+s potash', 'potash corp',
        'potash sanctions', 'potash export', 'potash production',
        'fertilizer prices', 'fertilizer sanctions',
        'fertilizer', 'fertiliser',
        'fertilizer crisis', 'fertiliser crisis', 'fertilizer supply',
        'fertilizer exports', 'fertiliser exports', 'fertilizer access',
        'potassium chloride', 'mop fertilizer',
        'potash klaipeda', 'belarusian potash',
        'canpotex', 'soligorsk', 'jansen project',
        'potash shortage', 'potash mining',
        'belarus exports', 'belarus rail china',
        'icl potash', 'arab potash company', 'dead sea potash',
        # Russian
        'калий', 'калийные удобрения', 'беларуськалий',
        'уралкалий', 'хлористый калий',
        # Chinese
        '钾肥', '氯化钾',
    ],
    'rare_earths': [
        'rare earth', 'rare earths', 'rare earth elements',
        'neodymium', 'dysprosium', 'praseodymium', 'terbium',
        'mp materials', 'mountain pass', 'lynas rare earths',
        'china rare earth', 'baotou', 'china export controls',
        'rare earth magnets', 'permanent magnets',
        'rare earth processing', 'rare earth refining',
        'kvanefjeld', 'tanbreez',
        'gallium germanium', 'antimony export ban',
        # Chinese
        '稀土', '稀土出口', '稀土磁铁', '包头',
    ],
    'semiconductors': [
        # Core terms
        'semiconductor', 'semiconductors', 'chip', 'chips', 'silicon',
        'integrated circuit', 'wafer', 'foundry', 'fabless',
        # Process / nodes
        'leading edge', 'leading-edge', '3nm', '5nm', '7nm', '2nm',
        'advanced node', 'mature node', 'legacy node',
        'EUV lithography', 'EUV', 'extreme ultraviolet',
        'DUV', 'photolithography',
        # Companies — foundries / IDMs
        'TSMC', 'taiwan semiconductor', 'tsm stock',
        'samsung electronics', 'samsung foundry',
        'SK hynix', 'sk hynix memory',
        'micron technology', 'intel foundry', 'intel fab',
        'globalfoundries', 'umc', 'united microelectronics',
        'smic', 'semiconductor manufacturing international',
        'ymtc', 'cxmt', 'hua hong',
        # Companies — equipment / EDA / fabless
        'asml', 'asml euv', 'asml lithography',
        'applied materials', 'lam research', 'kla corporation',
        'tokyo electron', 'screen holdings', 'advantest',
        'nvidia', 'amd chips', 'qualcomm', 'broadcom',
        'arm holdings', 'cadence design', 'synopsys',
        # Geopolitical / policy
        'CHIPS act', 'chips and science act', 'tech war',
        'export controls', 'chip export ban', 'semiconductor sanctions',
        'entity list', 'foreign direct product rule',
        'taiwan strait chips', 'taiwan semiconductor risk',
        'chip4 alliance', 'semiconductor reshoring',
        'tech sovereignty', 'chip independence',
        # Memory / specialty
        'DRAM', 'NAND', 'HBM', 'high bandwidth memory',
        'GAAFET', 'gate all around',
        # Chinese
        '半导体', '芯片', '台积电', '中芯国际', '光刻机', '芯片出口',
        # Japanese
        '半導体', 'チップ', 'TSMC熊本', 'ラピダス',
        # Korean
        '반도체', '삼성전자', 'SK하이닉스',
    ],
    'silicon': [
        # Core material / grades
        'silicon', 'silicon metal', 'metallurgical silicon', 'ferrosilicon',
        'polysilicon', 'polysilicon prices', 'silicon wafer', 'silicon ingot',
        'solar-grade silicon', 'semiconductor-grade silicon', 'silicon carbide',
        # Feedstock / high-purity quartz
        'silica', 'silica sand', 'quartz', 'high-purity quartz', 'hpq',
        'quartz crucible', 'spruce pine', 'the quartz corp', 'sibelco iota',
        # Companies
        'ferroglobe', 'daqo', 'daqo new energy', 'wacker chemie', 'wacker polysilicon',
        'hemlock semiconductor', 'rec silicon', 'oci polysilicon', 'tongwei', 'gcl',
        # Geographic / chokepoint
        'xinjiang polysilicon', 'guangzhou silicon futures', 'drag norway',
        # Market / policy events
        'polysilicon dumping', 'silicon export', 'section 232 polysilicon',
        'chips act silicon', 'silicon critical mineral', 'forced labor polysilicon',
        'uflpa polysilicon',
        # Chinese
        '硅', '多晶硅', '工业硅', '硅片', '光伏',
    ],
    'silver': [
        # Producers / state actors
        'silver', 'silver prices', 'silver futures', 'comex silver',
        'silver ounces', 'silver metric tons', 'silver supply',
        'silver demand', 'silver imports', 'silver exports',
        # Companies
        'fresnillo silver', 'pan american silver', 'first majestic',
        'wheaton precious', 'hochschild mining', 'polymetal silver',
        'kghm polska miedz', 'industrias peñoles',
        # Geographic
        'mexico silver', 'mexican silver', 'zacatecas silver',
        'durango silver', 'chihuahua silver', 'fresnillo',
        'peru silver', 'antamina silver', 'uchucchacua',
        'china silver', 'poland silver', 'kazakhstan silver',
        'cannington australia', 'broken hill',
        # Market context
        'silver photovoltaic', 'solar silver demand', 'silver solar',
        'silver electronics', 'silver industrial demand',
        'silver bullion', 'silver etf', 'slv etf',
        'london silver fix', 'shanghai silver',
        # Spanish
        'plata', 'plata mexicana', 'plata peruana',
        # Chinese
        '白银', '银价', '白银市场',
        # Russian
        'серебро', 'серебряные руды',
    ],
    'soybeans': [
        'soybeans', 'soybean prices', 'soybean futures',
        'cbot soybeans', 'soybean meal', 'soybean oil',
        'china soybean imports', 'brazil soybean', 'us soybean',
        'argentina soybean', 'soybean tariff', 'trade war soybean',
        'soybean crush', 'soybean rust',
        # Portuguese (Brazil)
        'soja', 'safra de soja',
        # Chinese
        '大豆', '中美大豆',
    ],
    'rice': [
        # Core market terms
        'rice', 'rice prices', 'rice futures', 'rough rice', 'milled rice',
        'white rice', 'paddy rice', 'rice exports', 'rice imports',
        'rice harvest', 'global rice stocks', 'rice shortage', 'rice surplus',
        # Producer / exporter specific
        'india rice', 'indian rice', 'basmati', 'non-basmati rice',
        'thailand rice', 'thai rice', 'vietnam rice', 'vietnamese rice',
        'china rice', 'pakistan rice', 'myanmar rice', 'cambodia rice',
        # Importer / food security
        'philippines rice', 'indonesia rice', 'bulog rice', 'nigeria rice',
        'rice import tender', 'rice food security',
        # Policy + trade
        'india rice export ban', 'rice export ban', 'rice export restriction',
        'india rice export', 'rice tariff', 'usda rice',
        'fao rice price', 'el nino rice',
    ],
    'coffee': [
        # Core market terms
        'coffee', 'coffee prices', 'coffee futures', 'arabica', 'robusta',
        'arabica coffee', 'robusta coffee', 'ice coffee futures',
        'coffee exports', 'coffee harvest', 'coffee stocks', 'coffee shortage',
        # Producer specific
        'brazil coffee', 'brazilian coffee', 'minas gerais coffee',
        'vietnam coffee', 'vietnamese coffee', 'central highlands coffee',
        'colombia coffee', 'colombian coffee', 'indonesia coffee',
        'ethiopia coffee', 'honduras coffee', 'uganda coffee',
        # Weather / climate drivers
        'brazil frost', 'brazil coffee frost', 'brazil coffee drought',
        'vietnam coffee drought', 'coffee crop damage',
        # Trade
        'coffee export', 'ice certified stocks coffee', 'robusta arabica spread',
    ],
    'sugar': [
        # Core market terms
        'sugar', 'sugar prices', 'sugar futures', 'raw sugar', 'refined sugar',
        'ny11', 'ny no. 11', 'ice sugar', 'london white sugar',
        'sugar exports', 'sugar imports', 'sugar harvest', 'sugar mill',
        'sugar surplus', 'sugar deficit', 'global sugar stocks',
        # Producer-specific
        'brazil sugar', 'brazilian sugar', 'centre-south brazil',
        'india sugar', 'indian sugar', 'uttar pradesh sugar', 'maharashtra sugar',
        'thailand sugar', 'thai sugar',
        'china sugar', 'china sugar imports', 'sugar syrup imports china',
        'eu sugar', 'european sugar', 'sugar beet eu',
        'mexico sugar', 'mexican sugar', 'usmca sugar',
        'cuba sugar', 'cuban sugar', 'cuban sugar harvest',
        'australia sugar', 'australian sugar',
        'guatemala sugar', 'philippines sugar',
        # Policy + trade
        'india sugar export quota', 'india sugar export ban',
        'usda sugar', 'usda sugar report',
        'sugar tariff rate quota', 'us sugar trq',
        'sugar ethanol mix', 'sugar ethanol parity',
        'safra cana', 'cana de açúcar',
        # Companies
        'cosan', 'raízen', 'são martinho', 'tereos', 'südzucker',
        'wilmar sugar', 'mitr phol',
        # Spanish + Portuguese + Hindi keywords
        'azúcar', 'caña de azúcar', 'açúcar',           # ES + PT
        'zafra cubana',                                  # ES (Cuban harvest)
        'गन्ना', 'चीनी',                                 # Hindi (sugarcane, sugar)
        # Chinese
        '糖', '白糖', '蔗糖',
    ],
    'uranium': [
        'uranium', 'uranium prices', 'yellowcake',
        'kazatomprom', 'cameco', 'orano', 'rosatom uranium',
        'sprott physical uranium', 'uranium etf',
        'uranium enrichment', 'enriched uranium',
        'natural uranium', 'uranium oxide',
        'kazakhstan uranium', 'niger uranium', 'arlit',
        'uranium mining', 'uranium sanctions',
        'haleu', 'low-enriched uranium', 'high-assay',
        'small modular reactor', 'smr uranium',
        'cameco kazatomprom', 'kazakhstan nuclear',
        # French (Niger / Orano)
        "uranium nigérien", 'orano niger',
        # Russian
        'уран', 'росатом',
        # Chinese
        '铀', '核燃料',
    ],
    'wheat': [
        'wheat', 'wheat prices', 'wheat futures', 'cbot wheat',
        'black sea grain', 'grain corridor', 'grain deal',
        'russian wheat exports', 'ukrainian wheat',
        'wheat shortage', 'wheat tariff', 'wheat ban',
        'india wheat ban', 'bread prices', 'flour shortage',
        'usda wheat report', 'wasde wheat', 'wheat harvest',
        'wheat smuggling', 'odesa port wheat',
        # Russian
        'пшеница', 'экспорт пшеницы', 'зерновой коридор',
        # Arabic
        'القمح', 'أسعار القمح',
        # Chinese
        '小麦', '小麦进口',
    ],
    'pgm': [
        'platinum', 'palladium', 'rhodium', 'iridium', 'ruthenium',
        'platinum group metals', 'pgm', 'pgms',
        'platinum prices', 'palladium prices', 'rhodium prices',
        'autocatalyst', 'auto catalyst', 'catalytic converter',
        'hydrogen fuel cell', 'pem electrolyzer',
        'anglo american platinum', 'amplats', 'impala platinum', 'implats',
        'sibanye-stillwater', 'sibanye stillwater', 'lonmin', 'marikana',
        'bushveld complex', 'rustenburg', 'mogalakwena',
        'norilsk palladium', 'nornickel', 'stillwater montana',
        'eskom load shedding', 'south africa power crisis',
        # Russian (Norilsk)
        'палладий', 'платина', 'норильский никель',
        # Chinese
        '铂', '钯', '铂金',
    ],
    'chromium': [
        'chromium', 'chrome', 'ferrochrome', 'ferro chrome',
        'stainless steel', 'chrome ore', 'chromite',
        'chromium prices', 'ferrochrome prices',
        'bushveld chrome', 'rustenburg chrome', 'tharisa',
        'kazakhstan chromium', 'donskoy gok', 'eramet',
        'sukinda', 'glencore chrome',
        'china ferrochrome', 'south africa ferrochrome',
        'chrome export ban',
        # Chinese
        '铬', '铬铁',
        # Russian
        'хром', 'ферросплавы',
    ],
    'manganese': [
        'manganese', 'manganese ore', 'mn ore',
        'ferromanganese', 'ferro manganese', 'silicomanganese',
        'manganese sulfate', 'hpmsm', 'high purity manganese sulfate',
        'manganese prices', 'manganese cathode',
        'kalahari manganese', 'hotazel', 'mamatwan', 'wessels',
        'tshipi manganese', 'south32 hotazel',
        'moanda gabon', 'eramet moanda', 'comilog',
        'gemco', 'groote eylandt', 'cyclone megan',
        'bootu creek', 'element 25',
        'lfp battery', 'nmc cathode', 'manganese-rich cathode',
        # Chinese
        '锰', '锰矿', '硫酸锰',
        # French (Gabon)
        'manganèse', 'comilog gabon',
    ],
    'phosphate': [
        'phosphate', 'phosphate rock', 'phosphate fertilizer',
        'phosphoric acid', 'dap', 'map', 'tsp', 'ssp',
        'diammonium phosphate', 'monoammonium phosphate',
        'phosphate prices', 'phosphate export',
        'ocp group', 'ocp maroc', 'office cherifien des phosphates',
        'khouribga', 'bou craa', 'youssoufia', 'gantour',
        'phosboucraa', 'jorf lasfar', 'safi morocco',
        'mosaic', 'central florida phosphate', 'mosaic fertilizer',
        'phosagro', 'kola peninsula',
        'arab potash', 'aqaba phosphate', 'jordan phosphate',
        'china dap export', 'india phosphate tender',
        'western sahara phosphate', 'western sahara mining',
        # French (Morocco)
        'phosphates marocains', 'phosphate maroc', 'ocp groupe',
        # Arabic
        'الفوسفات', 'فوسفات المغرب',
        # Chinese
        '磷酸盐', '磷肥',
    ],
    'diamonds': [
        'diamond', 'diamonds', 'rough diamonds', 'rough diamond',
        'polished diamonds', 'diamond prices', 'diamond market',
        'de beers', 'debeers', 'anglo american de beers',
        'alrosa', 'mirny', 'russian diamonds',
        'debswana', 'okavango diamond company', 'odc',
        'jwaneng', 'orapa', 'cullinan mine', 'venetia mine',
        'catoca angola', 'endiama',
        'namdeb', 'oranjemund', 'debmarine',
        'antwerp diamond', 'awdc', 'diamond bourse',
        'kimberley process', 'kimberley certification',
        'g7 diamond ban', 'g7 russian diamonds',
        'diamond sanctions', 'diamond seizure',
        'lab grown diamond', 'lab-grown diamonds', 'synthetic diamond',
        'botswana cert', 'botswana certification node',
        'de beers sale', 'de beers acquisition', 'okavango bid',
        # Russian
        'алмазы', 'алроса', 'якутские алмазы',
        # French (DRC, francophone Africa)
        'diamants', 'diamants bruts',
            # CAR conflict-diamond node (Jul 2026 Africa expansion)
        'central african republic diamonds', 'car diamonds', 'diamville',
        'kimberley process car', 'bangui diamonds',
    ],
    'sulfur': [
        'sulfur', 'sulphur', 'sulfur prices', 'sulphur prices',
        'sulfuric acid', 'sulphuric acid', 'molten sulfur', 'molten sulphur',
        'recovered sulfur', 'frasch sulfur', 'sour gas sulfur',
        'sulfur supply', 'sulphur supply', 'sulfur export', 'sulphur export',
        'sulfur production', 'sulphur production', 'sulfur output', 'sulphur output',
        'sulfur fertilizer', 'sulphur fertiliser',
    ],
    'bauxite': [
        'bauxite', 'alumina', 'aluminum ore', 'aluminium ore',
        'bauxite prices', 'alumina prices',
        'boké', 'boke region', 'cbg guinea', 'sangaredi',
        'smb winning', 'emirates global aluminium', 'ega guinea',
        'conakry port', 'kamsar port', 'guinea bauxite',
        'weipa', 'gove arnhem', 'australian bauxite',
        'porto trombetas', 'mineracao rio do norte', 'mrn',
        'simandou', 'rio tinto simandou',
        'guinea coup', 'doumbouya', 'conakry transition',
        'indonesia bauxite ban', 'indonesian alumina',
        # French (Guinea)
        'bauxite guinéenne', 'bauxite de boké',
        # Chinese
        '铝土矿', '氧化铝',
    ],

    'iron_ore': [
        'iron ore', 'iron ore prices', '62% fe', 'iron ore futures',
        'pilbara', 'port hedland', 'rio tinto iron ore', 'bhp iron ore',
        'fortescue', 'vale iron ore', 'carajas', 'simandou', 'iron ore exports',
        'iron ore imports', 'seaborne iron ore', 'pellet feed', 'magnetite',
        'hematite', 'dalian iron ore', 'china steel mills', 'iron ore cfr china',
        'kumba iron ore', 'kryvyi rih',
    ],
    'coal': [
        'coal', 'thermal coal', 'coking coal', 'metallurgical coal', 'met coal',
        'newcastle coal', 'coal prices', 'coal exports', 'coal imports',
        'kalimantan coal', 'bowen basin', 'richards bay coal',
        'powder river basin', 'coal mine', 'coal-fired power', 'qinhuangdao',
        'coal futures', 'thermal coal demand', 'coking coal benchmark',
        'indonesia coal', 'australia coal exports', 'china coal', 'coal india',
            # Mozambique coking coal (Jul 2026 Africa expansion)
        'moatize', 'mozambique coal', 'nacala corridor',
    ],
    'tantalum': [
        'tantalum', 'coltan', 'tantalite', 'ta2o5', 'tantalum capacitor',
        'conflict minerals', '3tg', 'coltan drc', 'rwanda coltan',
        'tantalum supply', 'tantalum prices', 'columbite-tantalite',
        'kivu mining', 'artisanal coltan',
    ],
    'sunflower_oil': [
        'sunflower oil', 'sunflower seed', 'sunflower oil exports',
        'sunflower oil prices', 'black sea sunflower', 'ukraine sunflower',
        'russia sunflower oil', 'argentina sunflower', 'edible oil imports',
        'vegetable oil', 'sunflower oil india', 'sunoil', 'sunflowerseed oil',
    ],
}
# ========================================
# COUNTRY EXPOSURE MATRIX (Phase 1)
# ========================================
# Which commodities does each country touch, and in what role?
# role: 'producer' | 'consumer' | 'producer_consumer' | 'transit' |
#       'sanctions_target' | 'mediator' | 'historic_reversal'
# weight: 0.5 (minor) → 1.5 (dominant role)
#
# REGIME_FLAGS (optional list, added May 17 2026 — sub-consumer-floor framework):
# Each entry may include an optional 'regime_flags' list to flag structural
# market-regime transitions distinct from cyclical movement. These are discrete
# event flags consumed by future regime-aware logic (CAVE phase 2, butterfly
# Phase 7+). NOT continuous variables — set when the country crosses a structural
# threshold; cleared only when conditions sustainably reverse.
#
# Recognized flags (extensible — add new ones as they emerge):
#   'sub_consumer_floor'   — Country production fell BELOW its own consumption
#                            for first time in N years (default N=5). Implies
#                            country becomes inelastic importer + export-policy
#                            risk. CANONICAL: India sugar 2024/25 (first time
#                            below ~31 MMT consumption in 8 years).
#   'export_ban_active'    — Government has imposed export restrictions on the
#                            commodity. Implies global supply tightening + price
#                            volatility expansion.
#   'stocks_critical'      — Stock-to-use ratio below historical floor.
#   'price_floor_breached' — Government intervention triggered (subsidy spike,
#                            buffer-stock release, MSP adjustment).
#   'belt_and_road_anchor' — Commodity-producing country with major Chinese
#                            Belt-and-Road resource-leverage stake (e.g., SDIC
#                            owns 28% of Jordan's Arab Potash Co; CCP-linked
#                            entities control ~80% of DRC cobalt; Chinese SOE
#                            footprint in Guinea bauxite via Boké rail/port).
#                            Implies political optionality risk — terms can be
#                            renegotiated under stress. Phase 1A: added for
#                            Africa + Jordan country entries (May 23 2026).
#   'g7_diamond_certification_node' — Country hosts (or is positioned to host)
#                            a G7 diamond certification node enforcing the
#                            Russian diamond import ban. CANONICAL HOSTS:
#                            Belgium (Antwerp / AWDC — operational since
#                            Mar 1 2024, the FIRST and currently primary node)
#                            and Botswana (joint statement with G7 technical
#                            team Nov 27 2024, under construction). Implies
#                            the country has de facto sanctions-enforcement
#                            weight beyond pure commerce.
#   'wagner_resource_collateral' — Country where Russian-linked PMC (Wagner
#                            successor "Africa Corps") receives mining
#                            concessions or gold as compensation. Implies
#                            conflict-financing channel + sanctions-evasion
#                            convergence exposure. Phase 2 — placeholder for
#                            when Sudan/Mali/CAR gold tracking is added.
#
# Example usage:
#   'sugar': {'role': 'producer_consumer', 'weight': 1.5, 'rank': 2,
#             'regime_flags': ['sub_consumer_floor'],  # ← new optional field
#             'note': "..."}
#
# Consumers of regime_flags (planned):
#   - CAVE phase 2 — constraint-regime portfolio biases
#   - Butterfly reader — cross-theater regime amplification
#   - Stability page UI — regime-shift badges on commodity tiles

COUNTRY_COMMODITY_EXPOSURE = {
    'afghanistan': {
        'wheat':        {'role': 'importer', 'weight': 1.4, 'data_as_of': '2026-06',
                         'note': "Afghanistan imports the bulk of its wheat and flour (Kazakhstan the dominant supplier, Pakistan secondary) -- domestic production chronically short and drought-exposed. STABILITY LINK: with a collapsed formal economy and an aid architecture under Taliban-era constraint, wheat/flour price shocks transmit directly into acute food insecurity -- the platform's tightest commodity-to-humanitarian coupling. Watch: Kazakh export policy and rail tariffs, Pakistan border-crossing closures (Torkham/Chaman), Black Sea wheat moves repricing Central Asian supply, WFP pipeline funding."},
        'oil':          {'role': 'importer', 'weight': 0.8,
                         'note': "Near-total refined-fuel import dependence (Iran, Turkmenistan, Uzbekistan, Russia via traders). Fuel prices set transport and food-distribution costs economy-wide. Watch: Iranian fuel-export policy toward Kabul (doubles as a friction lever), Amu Darya basin crude extraction (Chinese XCAP contract) as an embryonic domestic supply story."},
        'copper':       {'role': 'producer', 'weight': 0.5, 'data_as_of': '2026-06',
                         'note': "Mes Aynak (Logar) -- one of the world's largest undeveloped copper deposits, under Chinese MCC lease since 2008 and finally moving toward development under the Emirate. POTENTIAL not production: weight reflects trajectory. STRATEGIC ROLE: extraction is the China wheel's primary economic vector into Kabul. Watch: MCC mobilization milestones, rail/power infrastructure commitments, Taliban revenue-sharing announcements."},
        'lithium':      {'role': 'producer', 'weight': 0.3,
                         'note': "Large claimed lithium potential (Ghazni pegmatites and salt-lake brines) -- the 'Saudi Arabia of lithium' framing remains narrative rather than bankable production. Weight reflects headline sensitivity, not output: lithium announcements move the China-engagement and sanctions-workaround stories. Watch: Chinese exploration MOUs, any offtake framework, security incidents around survey teams."},
        'gold':         {'role': 'producer', 'weight': 0.3,
                         'note': "Artisanal and small-scale gold (Badakhshan, Takhar) provides local revenue streams, some under Taliban licensing and some smuggled through Central Asian routes. A shadow-economy indicator more than a market mover. Watch: Emirate mining-license announcements, smuggling interdiction reporting on the Tajik border."},
    },
    'algeria': {
        'phosphate':    {'role': 'producer', 'weight': 0.6, 'data_as_of': '2026-06',
                         'note': "Large phosphate reserves (Bled El Hadba / Tebessa megaproject with Chinese partners) positioning Algeria as an emerging North African phosphate exporter. Pre-ramp; weight reflects potential."},
        'natural_gas':  {'role': 'producer',          'weight': 1.4,
                         'note': "Africa's largest natural gas producer and a top-tier EU pipeline supplier — strategically elevated since 2022 as Europe diversified off Russian gas. Sonatrach (state-owned) exports via Medgaz (to Almeria, Spain) and the Trans-Mediterranean / Enrico Mattei line (through Tunisia to Mazara del Vallo, Italy); incremental-volume deals made Algeria one of Italy's top pipeline suppliers. The GME line to Spain via Morocco was closed in October 2021 over the Western Sahara dispute, rerouting volumes through Medgaz. Ageing fields (Hassi R'Mel), heavy domestic subsidy demand, and rising internal consumption cap export headroom. STABILITY LINK: hydrocarbon revenue underwrites the great majority of the state budget, so price or volume shocks transmit directly to fiscal and social-subsidy stability. Watch: Sonatrach contract announcements, Medgaz / TransMed throughput, Italy-Algeria volume deals, Hassi R'Mel decline rates, domestic-demand-versus-export tension."},
        'oil':          {'role': 'producer',          'weight': 1.0,
                         'note': "OPEC member (~1M bpd crude); Saharan Blend light sweet, Sonatrach-operated (Hassi Messaoud). Smaller and far steadier than Libya's volatile output, but bound to the same OPEC+ quota cadence and the same fiscal-dependency profile as the gas complex. Watch: OPEC+ quota decisions, Saharan Blend differentials, Sonatrach upstream investment."},
    },
    'angola': {
        'oil':          {'role': 'producer',          'weight': 1.2, 'rank': 7,
                         'note': "Africa's #2 oil producer (~1.1M bpd 2025, post-Cabinda recovery); OPEC member until withdrawal Jan 2024 (cited quota disputes). Sonangol state oil company + TotalEnergies + ExxonMobil + Chevron + Eni majors. Block 17 (Total) + Block 15 (ExxonMobil) deepwater workhorses. PETROLEUM-AS-LEVERAGE: Angola left OPEC partly over US sanctions/Chinese debt dynamic. Lobito Corridor terminus at Lobito port = the Atlantic export endpoint for DRC + Zambia copper/cobalt — strategically positions Angola in US-China critical-minerals competition. Watch: Sonangol production guidance, Lobito throughput, Cabinda separatist tensions."},
        'diamonds':     {'role': 'producer',          'weight': 1.3, 'rank': 4,
                         'note': "World's #4 rough diamond producer by value (~$1.5B annual); Catoca mine (Saurimo, Lunda Sul) is one of the world's largest. Endiama (state diamond company) + Sodiam (sole diamond marketer). Angola in active talks with Botswana for joint De Beers acquisition (May 2025 ministerial meeting in Gaborone). G7 diamond technical team has indicated future certification node expansion to Angola alongside Namibia. Watch: Endiama production data, De Beers ownership negotiations, Catoca expansion projects."},
        'copper':       {'role': 'transit',           'weight': 0.9,
                         'note': "Angola is the Atlantic-coast TERMINUS of the Lobito Corridor — DRC + Zambia copper exports flow by rail to Lobito port, bypassing Chinese-controlled East African infrastructure (Tanzania-Zambia Railway). US Development Finance Corp + EU + G7 funded Lobito rebuild $2.5B 2023-2026. STRATEGIC ROLE: Angola is not a major copper producer itself but its port + rail capacity is the West's primary counter-positioning lever against Chinese resource leverage in Central Africa."},
        'natural_gas':  {'role': 'producer',          'weight': 0.7,
                         'note': "Angola LNG (Soyo) plant operational; Eni-led Quiluma + Maboqueiro gas project FID 2023; first non-associated gas Angolan project. ~5.2M tpa LNG capacity. Atlantic Basin supplier, EU + Asia destinations. Less material than Mozambique/Nigeria LNG but growing."},
    },
    'argentina': {
        'wheat':        {'role': 'producer', 'weight': 1.2, 'data_as_of': '2026-06',
                         'note': "Top-10 wheat exporter; Pampas crop, Rosario the export hub. Milei-era export-tax (retenciones) changes move farmer selling + global supply. Watch: retenciones policy, peso/FX, Pampas weather."},
        'natural_gas':  {'role': 'producer', 'weight': 0.9, 'data_as_of': '2026-06',
                         'note': "Vaca Muerta (Neuquen) -- one of the world's largest shale plays, ramping hard (YPF + majors); Argentina pivoting from importer toward planned LNG exports. Watch: pipeline build-out, LNG export FID."},
        'gold':         {'role': 'producer', 'weight': 0.6, 'data_as_of': '2026-06',
                         'note': "Mid-tier gold/silver producer (San Juan, Santa Cruz; Veladero) in the Andes precious-metals belt."},
        'sunflower_oil': {'role': 'producer', 'weight': 0.8, 'data_as_of': '2026-06',
                         'note': "The #3 global sunflower-oil exporter (after Ukraine + Russia); Pampas crop, Rosario crush + export. A non-Black-Sea supply alternative when the war tightens flows."},
        'lithium':      {'role': 'producer',          'weight': 1.0, 'rank': 5,
                         'note': "Lithium Triangle anchor (with Chile + Bolivia); ~18,000 MT/yr 2024 (doubled YoY); Salar del Hombre Muerto + Cauchari-Olaroz; Milei RIGI investment regime (2024) provides legal stability for large mining investments — structural pricing variable. Lithium Argentina (TSX:LAR) + Ganfeng JV; Rio Tinto Fénix."},
        'soybeans':     {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "~14% global production; export tax politics under Milei (reduced retentions = supply boost); crusher capacity dominant in Rosario; Paraná river logistics; major China supplier alongside Brazil."},
        'corn':         {'role': 'producer',          'weight': 1.0,
                         'note': "Top-5 corn producer; export tax variable; Rosario hub + Paraná river logistics; competitive with Brazil for Asian buyers."},
    },
    'australia': {
        'natural_gas':  {'role': 'producer', 'weight': 1.3, 'data_as_of': '2026-06',
                         'note': "Top-3 LNG exporter (NWS, Gorgon, Wheatstone, Ichthys, Gladstone); swing supplier to Japan/Korea/China. East-coast domestic-reservation politics recurring. Watch: LNG outages (move JKM), domestic-gas policy."},
        'wheat':        {'role': 'producer', 'weight': 1.1, 'data_as_of': '2026-06',
                         'note': "Top-5 wheat exporter; the southern-hemisphere harvest (Nov-Jan) is key counter-seasonal supply to Asia/MENA. Watch: El Nino/La Nina drought swing, east vs west crop."},
        'iron_ore':     {'role': 'producer', 'weight': 1.5, 'rank': 1, 'data_as_of': '2026-06',
                         'note': "World's #1 iron ore exporter (Pilbara -- Rio Tinto, BHP, Fortescue); China's single most important supplier. The China steel/property cycle sets the price. Watch: China steel output, Pilbara cyclones, Simandou competition."},
        'coal':         {'role': 'producer', 'weight': 1.2, 'data_as_of': '2026-06',
                         'note': "World's top metallurgical (coking) coal exporter + major thermal; Bowen Basin + Hunter Valley -- a steel-input chokepoint for Asian mills. Watch: Queensland weather, China import policy, met-coal benchmark."},
        'copper':       {'role': 'producer', 'weight': 0.7, 'data_as_of': '2026-06',
                         'note': "Mid-tier copper producer (Olympic Dam, which is also uranium); growing on electrification demand."},
        'lithium':      {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 lithium producer (~88,000 MT/yr, ~38% global); spodumene hard-rock mining dominant. Greenbushes (Talison) is the largest hard-rock lithium mine globally; Pilbara Minerals + Liontown Kathleen Valley + Mineral Resources operations. China is dominant import destination. Production guidance + ASX:PLS, ASX:MIN, ASX:LTR earnings = global lithium price discovery."},
        'gold':         {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 gold producer (~290 tonnes/yr, ~9% global); Newmont Boddington + Cadia + Northern Star Kalgoorlie Super Pit; primary Western alternative to Chinese gold supply alongside Russia."},
        'rare_earths':  {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "Lynas Rare Earths Mt. Weld (Western Australia) is the only major non-Chinese heavy rare earth producer + refiner globally. Strategic diversification anchor for US/Japan/EU critical minerals strategy. Lynas Malaysia processing facility + planned Texas (US) plant. ASX:LYC."},
        'uranium':      {'role': 'producer',          'weight': 1.0, 'rank': 3,
                         'note': "World's #3 uranium producer (~10% global); Olympic Dam (BHP), Beverley + Honeymoon ISR mines; uranium export ban to non-NPT signatories; major supplier to USA + Japan + South Korea + India (under bilateral safeguards agreement)."},
        'bauxite':      {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "🥇 World's #1 bauxite producer (~100 Mt/yr, ~28% global). Weipa (Rio Tinto, Cape York Peninsula) + Gove (Rio Tinto, Arnhem Land) + Huntly + Willowdale (South32, Western Australia) operations. Australia + Guinea together = ~50% of global mined bauxite. Major supplier to Chinese alumina refineries; structural Western counterweight to Guinea's coup-prone supply. Rio Tinto + South32 + Alcoa primary operators. Watch: Rio Tinto Pacific Aluminium segment, ASX:RIO + ASX:S32 quarterly reports."},
        'manganese':    {'role': 'producer',          'weight': 1.0, 'rank': 3,
                         'note': "World's #3 manganese producer historically; GEMCO (South32 Groote Eylandt Mining Company, Northern Territory) was one of the world's largest single manganese operations. CYCLONE MEGAN (March 2024) caused severe damage to GEMCO infrastructure including the haul road and wharf — partial recovery ongoing through 2025-2026. Bootu Creek + Element 25 (Butcherbird, WA) are secondary operations. Australian outage redirected global manganese flow toward South Africa + Gabon. Watch: South32 GEMCO recovery timeline (ASX:S32), Element 25 production ramp."},
    },
    'azerbaijan': {
        'oil':          {'role': 'producer',          'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Caspian crude anchor (~600-700k bpd; the BP-operated Azeri-Chirag-Gunashli mega-complex, on a gradual decline). The Baku-Tbilisi-Ceyhan (BTC) pipeline is the strategically pivotal asset -- the only major westbound Caspian crude artery that bypasses BOTH Russia and Iran, delivering Azeri light crude to Ceyhan on Turkey's Mediterranean coast. SOCAR is the state operator. STRATEGIC LINKAGE: Azerbaijan supplies on the order of ~40% of Israel's crude (BTC -> Ceyhan -> tanker) -- a quiet but consequential energy-security tie. Watch: BP ACG production guidance, BTC throughput, SOCAR export statistics, Ceyhan loadings."},
        'natural_gas':  {'role': 'producer',          'weight': 1.2, 'data_as_of': '2026-06',
                         'note': "Shah Deniz (BP-operated) feeds the Southern Gas Corridor -- SCP -> TANAP (Turkey) -> TAP (Greece-Albania-Italy) -- the EU's flagship non-Russian gas diversification route. The July 2022 EU-Azerbaijan MoU aims to roughly DOUBLE SGC deliveries toward ~20 bcm/yr by 2027, making Azerbaijan a strategically outsized (if volumetrically modest) European supplier. Also a Middle Corridor / Trans-Caspian transit node for Turkmen and Kazakh volumes. Watch: Shah Deniz Stage 2/3 ramp, TAP expansion, EU-Azerbaijan SGC volume commitments, SOCAR gas export data."},
    },
    'belarus': {
        'potash':       {'role': 'producer',         'weight': 1.2, 'rank': 3,
                         'note': 'Belaruskali, sanctioned 2021, rebuilt via Russian ports + China rail'},
        'oil':          {'role': 'transit',           'weight': 0.8,
                         'note': 'Druzhba pipeline, Mozyr/Naftan refineries (Russian crude)'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': '100% Russian gas dependency'},
    },
    'belgium': {
        'diamonds':     {'role': 'mediator',          'weight': 1.5, 'rank': 1,
                         'regime_flags': ['g7_diamond_certification_node'],
                         'note': "🥇 ANTWERP — the global diamond trade and sanctions-enforcement nerve center. Antwerp World Diamond Centre (AWDC) historically processes ~84% of the world's rough diamonds by value (~$50B annual trade). Belgium is NOT a producer; it imports rough (primarily from Botswana + Russia historically + Canada + DRC), grades + sorts + distributes via four diamond exchanges in Antwerp. G7 SANCTIONS REGIME: Belgium hosts the FIRST operational G7 diamond certification node (operational since March 1, 2024) enforcing the Russian-diamond import ban into G7 jurisdictions. Belgian customs/AWDC seized millions in suspected Russian-origin stones in Feb 2024, proving both that the node operates and that the bypass is being attempted. ~30,000 Belgian jobs depend on the diamond sector. STRATEGIC ROLE: Belgium is the canonical Mediator — not producer, not consumer in scale, but the regulator, certifier, taxer, and sanctions enforcer. Watch: AWDC monthly trade statistics, Belgian customs seizure announcements, G7 diamond technical-team statements, Antwerp diamond-bourse activity levels."},
        'semiconductors': {'role': 'producer',        'weight': 1.0,
                         'note': "imec (Interuniversity Microelectronics Centre, Leuven) is one of the world's most important semiconductor research consortiums — co-develops next-generation node technology with ASML, TSMC, Samsung, Intel, Applied Materials, Nvidia. Belgian semiconductor IP and process know-how punches well above Belgium's economic weight. Critical node in the EU Chips Act implementation. Watch: imec roadmap announcements, EU Chips Act milestone funding."},
        'natural_gas':  {'role': 'transit',           'weight': 0.8,
                         'note': "Zeebrugge LNG terminal + Interconnector pipeline to UK = major gateway for EU LNG imports. Fluxys operates the trunk gas system. Post-Nord Stream, Belgium's LNG terminal capacity is meaningfully important for EU energy security — Northwest European LNG hub competing with Rotterdam (Netherlands)."},
    },
    'botswana': {
        'diamonds':     {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'regime_flags': ['g7_diamond_certification_node'],
                         'note': "🥇 World's #1 rough diamond producer BY VALUE (~$3-3.5B annual exports) and #2 by volume after Russia. Debswana (50/50 JV between Government of Botswana + De Beers) operates Jwaneng (highest-value diamond mine on Earth by US$/carat) + Orapa + Letlhakane + Damtshaa. Okavango Diamond Company (state-owned, ODC) marketing 25% of production, rising to 50% over next decade per June 2023 De Beers-Botswana agreement. STRATEGIC SOVEREIGN POSITIONING: Botswana owns 15% of De Beers directly; in talks with Angola for joint majority acquisition (May 2025) as Anglo American divests De Beers at $4.9B valuation. G7 SANCTIONS-REGIME ROLE: Botswana cert node under construction with G7 technical team (joint statement Nov 27 2024) — makes Botswana a de facto enforcer of the G7 Russian-diamond ban, foreign-policy weight beyond commerce. FISCAL EXPOSURE: Diamonds = ~75% of Botswana exports, ~30% of GDP — lab-grown diamond market share growth (~50% of US engagement-ring market) is an existential variable. Watch: ODC tender results, De Beers ownership negotiations, G7 cert node operational readiness, Botswana credit rating actions."},
        'copper':       {'role': 'producer',          'weight': 0.5,
                         'note': "Khoemacau Mining (Northwest Copper Belt) acquired by MMG (China Minmetals) 2023 for $1.88B — meaningful but secondary to diamonds in Botswana's economic picture. Cupric Canyon ZF site also developing. Adds Chinese SOE footprint to Botswana otherwise dominated by Western-aligned mining capital."},
    },
    'brazil': {
        'oil':          {'role': 'producer', 'weight': 1.2, 'data_as_of': '2026-06',
                         'note': "Top-10 crude producer (~3.7 Mb/d, OPEC+ aligned); Petrobras pre-salt (Santos/Campos) the growth engine and a rising export to China. Watch: pre-salt ramp, Petrobras dividend/capex policy, Equatorial Margin exploration."},
        'iron_ore':     {'role': 'producer', 'weight': 1.4, 'rank': 2, 'data_as_of': '2026-06',
                         'note': "World's #2 iron ore exporter (Vale, ~336 Mt 2025; Carajas high-grade + Minas Gerais). Carajas premium ore is prized for low-emission steel; tailings-dam regulation (post-Brumadinho) constrains. Watch: Vale guidance, China demand, dam-safety rulings."},
        'gold':         {'role': 'producer', 'weight': 0.7, 'data_as_of': '2026-06',
                         'note': "Growing gold producer (Amazon + Minas Gerais) alongside a large illegal garimpo sector with traceability + deforestation concerns."},
        'tantalum':     {'role': 'producer', 'weight': 0.6, 'data_as_of': '2026-06',
                         'note': "A significant non-Africa tantalum source (Pitinga / Amazonas); part of Brazil's broader strategic-minerals base."},
        'silicon':      {'role': 'producer', 'weight': 1.0,
                         'note': "Largest single source of U.S. silicon-metal imports (~38%); cheap hydropower underwrites carbothermic smelting (Ferbasa, Minasligas). Emerging downstream solar-glass / high-purity-silica ambition (Homerun, Bahia). Western-aligned counterweight to Chinese silicon-metal supply."},
        'coffee':       {'role': 'producer',          'weight': 1.4, 'rank': 1,
                         'note': "World's #1 coffee producer and exporter (Arabica-dominant; Minas Gerais, Sao Paulo, Espirito Santo). Brazilian frost and drought are the single biggest global coffee price drivers - the 2021 frost and subsequent droughts drove multi-year price spikes. Watch: Minas Gerais frost/drought, CONAB crop estimates, ICE arabica certified stocks, real (BRL) moves affecting export economics."},
        'nitrogen':     {'role': 'consumer', 'weight': 1.4, 'rank': 2,
                         'note': "Among the world's largest fertilizer importers -- buys the bulk of its nitrogen (urea + ammonia) abroad to feed soy / corn / sugarcane. Heavy reliance on Russian + Middle East + North African supply makes Brazil acutely exposed to nitrogen export disruptions. Watch: Brazilian urea import volumes / origins, port arrivals (Paranagua / Santos), planting-season demand."},
        'soybeans':     {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 soybean producer (~40% global, ~155 Mt/yr 2024-25); Mato Grosso + Paraná dominant; CONAB official forecasts; safrinha (second-crop) Mato Grosso corn rotated with soy. Single largest agri-supply story of the past decade — Brazil overtook USA in 2013. Dominant China supplier (~75% of Brazilian soy exports go to China); Paranaguá + Santos ports; US-China trade war beneficiary structurally."},
        'corn':         {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "~12% global production; safrinha (Mato Grosso second harvest, ~75% of total Brazilian corn) creates a structural global supply variable distinct from US harvest cycles. Paranaguá + Santos export terminals. Major destination shift toward China + MENA in last decade."},
        'potash':       {'role': 'consumer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 potash consumer (~13M tonnes, ~17% global); the demand-side anchor of all global agri-commodity flow. Brazil's soy/corn export economy depends entirely on potash imports — when Belarus got sanctioned in 2021, Brazil was the primary impact zone. ~85% imported (Russia + Belarus + Canada). Soybean farmers' input cost lever."},
        'phosphate':    {'role': 'consumer',          'weight': 1.2, 'rank': 2,
                         'note': "World's #2 phosphate consumer (~10-12 Mt/yr); demand-side anchor alongside potash for Brazil's massive soy/corn export economy. Mosaic Brazil + Vale Fertilizantes (sold to Mosaic 2018) primary fertilizer distributors. Brazilian fertilizer prices = key input cost variable for global soy supply. Russian + Moroccan + US imports dominant. Watch: Mosaic Brazil quarterly results, Brazilian Real exchange rate impact on fertilizer affordability."},
        'sugar':        {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "🌾 World #1 sugar producer (~44.7 MMT 2025/26 record forecast) AND #1 exporter (~36 MMT/yr, ~50% of global sugar trade). Centre-south region (São Paulo + Minas Gerais + Mato Grosso) dominant; Santos + Paranaguá primary export ports. Cosan/Raízen + São Martinho top mills. STRUCTURAL FLEXIBILITY: ~50% of cane allocated to sugar vs ethanol depending on price economics (the sugar/ethanol mix toggles seasonally — when ethanol prices are high relative to sugar, mills divert toward fuel and global sugar prices spike). Brazil is the de facto global sugar price floor + the variable-supply marginal producer. Watch: Conab cane forecasts, UNICA biweekly reports, sugar/ethanol parity ratio (ANP), Santos port loadout volumes."},
        'manganese':    {'role': 'producer',          'weight': 1.0, 'rank': 4,
                         'note': "World's #4 manganese producer (~2-3 Mt/yr). Vale Mineração + Buritirama Mineração operations in Pará + Minas Gerais. Steel-grade ore primarily; also growing battery-grade interest. Less concentrated geologically than South Africa Kalahari but stable supply. Watch: Vale quarterly base metals segment, port logistics through Itaqui + Santos."},
        'bauxite':      {'role': 'producer',          'weight': 1.1, 'rank': 4,
                         'note': "World's #4 bauxite producer (~30 Mt/yr); Porto Trombetas (Mineração Rio do Norte, MRN — Vale+BHP+Rio Tinto+South32+Hydro JV) in Pará is the largest operation. Norsk Hydro Paragominas + Alunorte alumina refinery (Barcarena). Brazilian bauxite + alumina industry is significant Atlantic-basin counterweight to Guinea + Australia. Watch: MRN production, Norsk Hydro Brazil segment results."},
            'graphite':     {'role': 'producer',          'weight': 0.9, 'rank': 3,
                         'note': "World #3 natural graphite producer (Minas Gerais flake district; Nacional de Grafite among the largest ex-China producers) -- a quiet but material leg of the non-China anode diversification story. Watch: expansion announcements, Western offtake deals, energy-cost competitiveness."},
},
    'canada': {
        'gold':         {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Top-5 global gold producer (Quebec + Ontario; Canadian Malartic, Detour). Stable Western-aligned ounces; gold at all-time highs in 2025-26 on central-bank buying + geopolitics."},
        'natural_gas':  {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Top-5 gas producer (WCSB, Montney); LNG Canada (Kitimat) opened Pacific-basin exports beyond the US pipeline market. Watch: LNG Canada ramp, AECO-Henry Hub spread."},
        'wheat':        {'role': 'producer', 'weight': 1.1, 'data_as_of': '2026-06',
                         'note': "Top-5 wheat exporter; high-protein spring wheat + durum from the Prairies -- a reliable Western counterweight. Watch: Prairie drought, rail to Vancouver/Thunder Bay."},
        'nickel':       {'role': 'producer', 'weight': 0.7, 'data_as_of': '2026-06',
                         'note': "Sudbury / Voisey's Bay (Vale, Glencore): class-1 nickel + cobalt byproduct, an IRA-compliant Western source for EV supply chains."},
        'silicon':      {'role': 'producer', 'weight': 0.8,
                         'note': "Silicon-metal producer (Quebec -- Ferroglobe Becancour) on cheap hydropower; ~28% of U.S. silicon-metal imports and a near-shore, allied alternative to Chinese supply. Added silicon metal to its own critical-minerals list in 2024."},
        'potash':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 potash producer (~14M tonnes/yr, ~36% global); Saskatchewan basin (largest known reserves globally); Nutrien (TSE:NTR — formed from PotashCorp + Agrium 2018 merger); Mosaic Esterhazy K3 mine. Canpotex consortium handles offshore exports. Brazil + USA + China are largest customers. Ukraine war + Belarus sanctions made Canada the structural Western-aligned potash anchor."},
        'uranium':      {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 uranium producer (~13% global); Cameco (TSE:CCO) operates McArthur River + Cigar Lake — among the world's highest-grade uranium deposits. Saskatchewan basin. Canada also leads CANDU heavy-water reactor IP. Major supplier to USA + EU + Japan + Korea. Western strategic alternative to Russian + Kazakh + Chinese supply chains."},
        'oil':          {'role': 'producer',          'weight': 1.0,
                         'note': "World's #4-5 oil producer (~5.9M bpd); Alberta oil sands (Athabasca) dominant; Suncor + Cenovus + CNRL operate. Largest oil exporter to USA via pipelines (Enbridge Mainline + Trans Mountain TMX expansion 2024). Heavy crude discount to WTI (WCS spread) drives Alberta fiscal politics."},
        'pgm':          {'role': 'producer',          'weight': 0.7,
                         'note': "North American Palladium / Impala Canada (Lac des Iles mine, Ontario) is one of the few non-South-African / non-Russian primary palladium producers globally. Small in global terms (~5-7% palladium, <1% platinum) but strategically critical as Western supply diversification. Watch: Impala Platinum (JSE:IMP) Canada segment, Generation Mining + Marathon Palladium development progress."},
        'diamonds':     {'role': 'producer',          'weight': 0.9,
                         'note': "World's #4-5 diamond producer (~$1.5-2B annual); Northwest Territories (Diavik, Ekati, Gahcho Kué) + Quebec (Stornoway Renard). Argyle (Australia) closure 2020 + Russian sanctions raised Canadian rough's market premium. Rio Tinto Diavik + De Beers Snap Lake (closed) + Mountain Province Diamonds. G7-aligned supply, no certification concerns. Watch: Rio Tinto Diavik wind-down (mine closure expected 2026), Mountain Province (TSX:MPVD) results."},
    },
    'chile': {
        'copper':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'regime_flags': ['sulfur_dependency'],
                         'note': 'World #1 copper producer (~24% global supply, ~5.3M tonnes/yr); Codelco state-owned + BHP Escondida + Antofagasta + Anglo American Sur; Chuquicamata is the largest open-pit mine on Earth. Antofagasta region is the world\'s most concentrated copper-mining infrastructure. Strategic anchor for the global energy transition (EVs + grid + electrification all copper-hungry). SULFUR DEPENDENCY (May 17 2026): ~20% of Chilean copper processing uses imported sulfuric acid; Hormuz closure + China sulfur export ban (May 2026) creates structural risk to copper oxide solvent-extraction operations. Ivanhoe Mines founder warned >3 week disruption = mine closures. Cascade exposure: chile copper risk is amplified by sulfur upstream signal, not visible in copper-only telemetry.'},
        'lithium':      {'role': 'producer',          'weight': 1.4, 'rank': 2,
                         'note': "World's #2 lithium producer (~28% global supply); Salar de Atacama brine operations dominate. SQM + Albemarle operate under quota system; Boric government partial nationalization (April 2023) pushed Codelco into majority stake on new projects. Lithium Triangle anchor (with Argentina + Bolivia). The April 2023 nationalization announcement structurally elevated political risk for Chilean lithium beyond what Argentina/Australia carry."},
        'silver':       {'role': 'producer',          'weight': 1.0,
                         'note': 'Major silver producer (~1,400 MT/yr); silver is largely a by-product of copper + gold operations; Antofagasta region.'},
        'gold':         {'role': 'producer',          'weight': 0.9,
                         'note': 'Significant gold producer (~30-35 tonnes/yr); Maricunga + El Indio belt; Yamana + Kinross operations.'},
        'sulfur':       {'role': 'consumer',          'weight': 1.3,
                         'regime_flags': ['cascade_exposure_active'],
                         'note': 'Chile imports ~20-30% of sulfur for copper-oxide processing (solvent extraction-electrowinning, SX-EW). China sulfur export ban (May 2026) + Hormuz closure trapped Gulf supply; Chilean sulfur import prices doubled. CASCADE EXPOSURE: this is the FIRST visible cascade-transmission belt — Hormuz disruption -> sulfur scarcity -> Chilean copper output risk. Ivanhoe Mines founder warned >3 week disruption would close copper oxide operations. Watch: Chilean copper-oxide vs. concentrate output mix, ENAP sulfur import data, Cochilco sector reports.'},
    },
    'china': {
        'lithium':      {'role': 'consumer', 'weight': 1.4, 'data_as_of': '2026-06',
                         'note': "Heart of the lithium chain: dominant refiner (~60%+ of global processing) plus a top-3 mined producer (Jiangxi, Qinghai). Controls the midstream the battery world depends on; CATL/BYD anchor demand. Watch: refining utilization, lepidolite cost curve, export-control posture."},
        'wheat':        {'role': 'producer_consumer', 'weight': 1.3, 'data_as_of': '2026-06',
                         'note': "World's #1 wheat PRODUCER (~140M t, ~17%) but consumes nearly all of it; a swing IMPORTER whose buying moves the world price. State reserves vast and opaque. Watch: Sinograin buying, import-quota use, harvest quality."},
        'uranium':      {'role': 'consumer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Fastest-growing reactor fleet on Earth; a major and rising uranium importer locking up long-term supply (Kazakhstan, Africa, Russia). Demand-side pressure on the uranium market."},
        'silver':       {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Top-3 silver producer (largely lead/zinc byproduct) AND the swing source of industrial silver demand via dominant solar-PV manufacturing. Both ends of the silver balance."},
        'iron_ore':     {'role': 'consumer', 'weight': 1.5, 'rank': 1, 'data_as_of': '2026-06',
                         'note': "The demand center of gravity: ~70% of seaborne iron ore (steel + property/infrastructure). Domestic ore is low-grade; China imports from Australia + Brazil. The China steel cycle IS the iron-ore price. Watch: steel output, property stimulus, Dalian port stocks."},
        'coal':         {'role': 'producer_consumer', 'weight': 1.5, 'rank': 1, 'data_as_of': '2026-06',
                         'note': "Both #1 producer (~52% of global, ~4.78 Bt) and #1 consumer; domestic output is a strategic energy-security lever and import demand swings the seaborne market. Watch: domestic output mandates, hydro/weather, import policy toward Australia."},
        'silicon':      {'role': 'producer', 'weight': 1.5, 'rank': 1,
                         'note': "China dominates the entire silicon chain -- ~80% of global silicon materials (USGS 2024) and >80% of polysilicon. Xinjiang concentration carries UFLPA / forced-labor exposure; the Guangzhou Futures Exchange runs industrial-silicon futures. Overproduction is cratering global polysilicon prices and undermining Western producers; subject of a U.S. Commerce Section 232 probe. Command-node of the chip-and-solar feedstock."},
        'rice':         {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 rice producer and consumer; broadly self-sufficient via hybrid-rice yields and large Sinograin state reserves, so China acts as a price-stabilizer more than an import-dependency story - but stockpiling policy and occasional large import/export swings still move regional flows. Watch: Sinograin reserve actions, hybrid-rice acreage, customs import data (periodic buys from Vietnam/Thailand), domestic minimum purchase prices."},
        'nitrogen':     {'role': 'producer_consumer', 'weight': 1.5, 'rank': 1,
                         'note': "World's #1 nitrogen fertilizer producer AND consumer (urea + ammonia). Coal-based ammonia (unlike the gas-based West) insulates China from gas-price shocks but is emissions-heavy. Periodic urea EXPORT QUOTAS / customs-inspection holds (2021, 2023-24) to protect domestic supply are a top global price signal -- when China holds back urea, world prices spike. Watch: customs urea-export inspection policy, domestic urea price controls, coal feedstock cost."},
        'rare_earths':  {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 rare earth producer + processor (~60% mining, ~85% refining of magnetic + heavy rare earths). Bayan Obo (Inner Mongolia) is the largest single REE deposit globally; Sichuan ionic clay heavy-REE mines. Export controls (Dec 2023 onward, expanded April 2025) on gallium + germanium + graphite + dysprosium + terbium are the canonical 'critical minerals weaponization' case study. Watch: MOFCOM export-license announcements, China REE quota adjustments."},
        'potash':       {'role': 'consumer',          'weight': 1.4, 'rank': 1,
                         'note': "World's #1 potash consumer (~17M tonnes/yr); Qinghai-Lop Nur domestic production covers ~50%, balance imported from Canada (Canpotex) + Russia (Uralkali) + Belarus (Belaruskali). State-controlled buyer pricing dynamic — China's annual potash contract negotiation sets the global benchmark. Domestic Salt Lake Industry Co (SH:000792). Major fertilizer-security strategic concern under Belt-and-Road food-security framing."},
        'soybeans':     {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 soybean consumer (~115 Mt/yr, ~60% of global trade). Brazil (~75%) + USA (~20%) + Argentina primary suppliers. Pig feed + cooking oil dominant uses. STRUCTURAL: US-China trade war soybean tariffs (2018-) accelerated Chinese diversification toward Brazil — Brazil's structural rise as #1 soybean exporter is partially a Chinese policy outcome. COFCO state buyer + crushing capacity. Watch: COFCO contract decisions, USDA FAS China reports, soybean-meal-pork crush margin."},
        'copper':       {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 copper consumer (~14-15M tonnes/yr, ~55% of global demand). Power grid + EV + appliances + construction all major drivers. China dominates downstream smelting/refining (~50% global smelter capacity). State Grid Corporation of China + State Power Investment Corporation are the largest individual copper buyers globally. Watch: SHFE copper inventory, Yangshan port concentrate imports, China property-sector stimulus signals."},
        'oil':          {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #2 oil consumer (~15-16M bpd); world's #1 crude oil importer. CNPC + Sinopec + CNOOC majors. STRATEGIC PETROLEUM RESERVE expansion ongoing — China is the canonical 'discount-crude buyer' (sanctioned Russian + Iranian + Venezuelan crude flows preferentially to Chinese teapot refiners). Refined product export quotas are policy lever. Watch: customs crude import data, teapot refinery activity, SPR fill rate."},
        'gold':         {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 gold producer (~370 tonnes/yr, ~10% global) AND #1 consumer (~1,000 tonnes/yr jewelry + investment + central bank). PBOC has bought gold for 23+ consecutive months (2022-2024); central bank reserves disclosure historically opaque (suspected actual holdings 2-3x reported). DEDOLLARIZATION SIGNAL: PBOC gold buying is the canonical visible indicator of Chinese strategic reserve diversification away from USD. Shanghai Gold Exchange (SGE) competing with London + COMEX for global benchmark status. Watch: PBOC monthly gold reserve disclosures, SGE volumes, premium-to-London spread."},
        'natural_gas':  {'role': 'consumer',          'weight': 1.4, 'rank': 1,
                         'note': "World's #1 LNG importer (overtook Japan 2021); ~80 MMT/yr. Pipeline imports also major: Power of Siberia 1 (Russia, operational); Power of Siberia 2 (negotiated since 2014, partial agreement 2024); Central Asia pipelines (Turkmenistan dominant). Sanctioned Russian gas finds Chinese demand. Watch: customs LNG import data, Power of Siberia flow rates, Yamal LNG Chinese cargo share."},
        'cobalt':       {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 cobalt consumer + refiner (~73% global refining). CMOC + Huayou + Jinchuan + GEM Co dominate refining; CCP-linked entities control ~80% of DRC mining (15 of 19 best deposits per public reporting). Battery cathode (NMC chemistry) dominant use. STRATEGIC VULNERABILITY: US-DRC Strategic Partnership (2025) + Orion Critical Mineral Consortium MOU with Glencore (Feb 2026) threaten Chinese cobalt processing position. Watch: CMOC + Huayou earnings, China customs cobalt import data, DRC ownership renegotiation signals."},
        'nickel':       {'role': 'consumer',          'weight': 1.4, 'rank': 1,
                         'note': "World's #1 nickel consumer (~1.6 Mt/yr); stainless steel + EV battery cathode (NMC). Tsingshan Holding Group is the world's largest stainless+nickel producer and operates Indonesian HPAL projects via Morowali + Weda Bay. Chinese-Indonesian nickel processing dominance is the canonical case study in Belt-and-Road resource leverage. Watch: Tsingshan production guidance, Indonesia HPAL output, SHFE nickel inventory."},
        'semiconductors': {'role': 'consumer',        'weight': 1.5, 'rank': 1,
                         'note': "World's #1 semiconductor consumer (~$200B+ chip imports annually — larger than oil imports). SMIC (foundry) + YMTC (memory) + CXMT (DRAM) building indigenous capacity; chokepoint exposure at ASML EUV + Tokyo Electron + Applied Materials equipment. US export controls (Oct 2022, Oct 2023 expansions) + Dutch DUV restrictions cut off advanced node access. Huawei + HiSilicon are the strategic-priority customers. Watch: SMIC + YMTC capacity build-out, US BIS Entity List additions, ASML Chinese sales."},
        'sugar':        {'role': 'consumer',          'weight': 1.0,
                         'note': "World's #4 sugar consumer (~15 MMT/yr); state stockpiling via SinoSugar + Cofco Sugar; Brazil + Thailand + India primary import suppliers. Strategic food-security commodity under Belt-and-Road framing. Watch: COFCO Sugar tender activity, Guangxi/Yunnan domestic harvest reports."},
        'chromium':     {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 ferrochrome consumer + producer-by-smelting (NOT by mining — China smelts ~50% of global ferrochrome, primarily from imported South African ore via electricity-cost arbitrage). Stainless-steel industry (Tsingshan + Baosteel + TISCO) is the dominant downstream demand. South African ferrochrome industry was structurally hollowed out by Chinese smelter expansion since 2010. Watch: Chinese ferrochrome smelter operating rates, SA chrome-ore export volumes, Tsingshan stainless production."},
        'manganese':    {'role': 'consumer',          'weight': 1.4, 'rank': 1,
                         'note': "World's #1 manganese consumer + processor (~70% of global HPMSM = high-purity battery-grade manganese sulfate is Chinese-processed regardless of where ore originates). Steel-grade ferromanganese also dominated by Chinese smelters. Tsingshan, CITIC Dameng, South Manganese Group major operators. STRATEGIC: similar to cobalt + nickel — Chinese midstream processing dominance is the persistent supply-chain leverage point even as Western producers reshore mining. Watch: South Manganese Group output, HPMSM export prices, Chinese EV battery cathode mix."},
        'phosphate':    {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 phosphate producer (~90 Mt/yr rock + significant DAP/MAP processing). Yunnan + Guizhou + Hubei provinces dominant. STRUCTURAL: China imposed phosphate export quotas/taxes starting 2021 to prioritize domestic agricultural use — reduced global DAP/MAP availability and structurally elevated Indian + Brazilian + Southeast Asian phosphate prices. Yuntianhua + Hubei Yihua + Wengfu Group major operators. Watch: MOFCOM phosphate export quota announcements, China customs DAP/MAP export data, OCP-China phosphate trade flow."},
        'bauxite':      {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 bauxite importer (~140 Mt/yr) AND world's #1 alumina + aluminum producer (~57% global aluminum, ~55% global alumina). Domestic bauxite resources insufficient quality — ~55% of bauxite imported from Guinea (Boké region via Chinese-funded rail + port), ~20% Australia, ~10% Indonesia (when not banned). Chalco + Chinalco + Hongqiao + Weiqiao major operators. STRATEGIC VULNERABILITY: Guinea coup risk + Indonesia export-policy whiplash + Australian relations cycle expose Chinese aluminum smelter feedstock to political volatility. Watch: Chinese bauxite import customs data, Guinea Boké throughput, Indonesia bauxite export-policy announcements."},
            'graphite':     {'role': 'producer',          'weight': 1.4, 'rank': 1,
                         'regime_flags': ['export_controls_active'],
                         'note': "🥇 ~77% of world natural graphite production AND 90%+ of anode-grade spherical graphite processing -- the single most concentrated node in the battery supply chain. Export PERMITS imposed Dec 1 2023 under dual-use rules (alongside gallium/germanium) and exercised as an active statecraft lever in US-China tech friction. Every ex-China anode project (Syrah/Vidalia, Novonix, Anovion, Korean/Japanese anode makers) is priced against Beijing's permit posture. Watch: MOFCOM permit-approval tempo, spherical-graphite export volumes, additions to the dual-use control list."},
},
    'cuba': {
        'oil':          {'role': 'consumer',          'weight': 1.4,
                         'note': "🚨 ACUTE IMPORT DEPENDENCY: Cuba imports ~75-80% of oil consumption (~100,000 bpd). Venezuela primary supplier under PetroCaribe + Petrocaribe-successor framework; Russia + Mexico (modest) secondary. POST-MADURO TRANSITION (Jan 3 2026): With Maduro captured + Rodriguez interim government in Caracas, the Venezuela-Cuba oil-for-services barter framework is the most exposed bilateral arrangement on the continent. Cuba sent ~22,000 medical professionals to Venezuela in exchange for ~70,000-90,000 bpd discounted oil shipments — that arrangement's future is now contingent on US-Rodriguez negotiations. CRITICAL ANALYTICAL SIGNAL: If Rodriguez govt redirects Venezuelan crude toward US refiners (Trump's 'oil is beginning to flow' Apr 2026 framing), Cuban energy security collapses within weeks-to-months. Watch: PDVSA shipments to Cienfuegos + Matanzas, Cubapetróleo (CUPET) inventory levels, Cienfuegos refinery utilization (Russian Soviet-era 65k bpd capacity), Russian Rosneft cargo continuity, blackout duration data from Havana."},
        'wheat':        {'role': 'consumer',          'weight': 1.2,
                         'note': "🌾 Cuba imports ~75-85% of wheat consumption (~800k-1MMT annually). State-monopoly procurement via Alimport (Empresa Cubana Importadora de Alimentos). Russia + EU (France) + Canada + Argentina primary suppliers. Bread + pasta rations are central to Cuba's libreta (ration book) system — politically sensitive food security commodity. POST-MADURO CASCADE: Reduced Venezuelan oil flow → less hard currency for wheat imports → ration shortfalls → social-stability risk. 2021 protests catalyzed by food shortages; 2024-2025 ongoing US embassy reporting on libreta gaps. Watch: Alimport tender activity, Mariel + Havana port grain arrivals, daily libreta-bread availability reports."},
        'corn':         {'role': 'consumer',          'weight': 0.9,
                         'note': "🌽 Cuba imports ~80% of corn consumption (~700-900k tonnes annually). White corn + yellow corn (animal feed) dual demand. Argentina + Brazil + Mexico primary suppliers post-US embargo restrictions. Animal feed import dependency → livestock + poultry sector capacity → meat/egg availability variable. Watch: Alimport corn tender activity, Cuban Agriculture Ministry production reports."},
        'soybeans':     {'role': 'consumer',          'weight': 0.7,
                         'note': "🌱 Cuba imports near-100% of soybean consumption (~300-500k tonnes annually) primarily as soybean meal for animal feed (poultry + pork sector). USA (under specific cash-only OFAC exemptions for agricultural exports) + Brazil + Argentina primary suppliers. Watch: USDA FAS reports on Cuba soybean imports, USA-Cuba ag-trade license activity."},
        'potash':       {'role': 'consumer',          'weight': 0.6,
                         'note': "🌾 Cuba imports ~95% of potash + phosphate fertilizers; sugarcane + tobacco + vegetable cultivation depend on imported inputs. Sugarcane sector (historically central to Cuban economy) collapsed from ~8 MMT (1990) to <1 MMT (2023) partly due to fertilizer access constraints. Russia + Canada + Brazil intermediaries primary fertilizer routes. Watch: Cuban sugar harvest output as proxy for fertilizer-input adequacy."},
        'sugar':        {'role': 'producer',          'weight': 0.6,
                         'regime_flags': ['historic_reversal_event'],
                         'note': "🌾🔄 STRUCTURAL DECLINE STORY: Cuba was historically the WORLD'S #1 sugar exporter (~8 MMT/yr in 1989 USSR-era) — sugar was the Cuban economy. Production collapsed to <1 MMT/yr (2023) over 30+ years due to (1) loss of USSR-bloc preferential markets 1991, (2) fertilizer/input constraints from US embargo, (3) hurricane damage, (4) infrastructure decay. Cuba is now a NET SUGAR IMPORTER in some years — one of the most striking commodity-historical reversals in Latin America. SIGNAL: Cuban sugar production data is the proxy indicator for whether Cuba's agricultural production capacity is recovering or continuing to deteriorate. Watch: AZCUBA (state sugar enterprise) annual harvest reports, Cuban sugar mill (centrales) operational count vs. historical baseline."},
        'natural_gas':  {'role': 'consumer',          'weight': 0.4,
                         'note': "Limited LNG infrastructure (Mariel port LNG terminal under development with Chinese cooperation, repeatedly delayed). Most Cuban electricity generation runs on heavy fuel oil + crude (Venezuelan-supplied) — natural gas import buildout is the proposed long-term energy-diversification pathway but execution stalled. Watch: Mariel LNG terminal construction status, Russian + Chinese energy-cooperation announcements."},
        'gold':         {'role': 'consumer',          'weight': 0.3,
                         'note': "Central bank gold reserves opaque; not a structural commodity actor. Possible role as sanctions-evasion settlement vehicle (Iran + Russia + Venezuela parallels) but documentation thin. Worth tracking for future intelligence but not currently a material data point."},
    },
    'drc': {
        'cobalt':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'regime_flags': ['belt_and_road_anchor', 'export_ban_active'],
                         'note': 'World #1 cobalt producer (~72% of global supply, ~247kt projected 2026); CMOC + Glencore + Eurasian Resources Group dominate. CCP-linked entities control ~80% of Congolese cobalt mining (15 of 19 best deposits per public reporting). US-DRC Strategic Partnership (signed 2025) + Orion Critical Mineral Consortium MOU with Glencore (Feb 2026) signal Western re-entry; Project Vault channels DRC minerals into US strategic stockpiles. June 2025 US-brokered DRC-Rwanda peace deal explicitly tied to mineral access. DRC imposed cobalt export quota Feb 2025 (lifted Oct 2025, quotas remain). Lobito Corridor (DRC→Zambia→Angola rail) diversifies routes from Chinese-controlled infrastructure. Watch: Glencore-Orion offtake terms, CMOC/Tenke output, Lobito throughput, Kinshasa-Beijing renegotiation signals.'},
        'copper':       {'role': 'producer',          'weight': 1.3, 'rank': 4,
                         'regime_flags': ['belt_and_road_anchor'],
                         'note': "Major copper producer (~2.4 Mt/yr, ~10% global, world #4); Katanga copper belt (Kolwezi + Lubumbashi). Cobalt is largely a copper-mining by-product geologically. DRC sold $1.8B copper to US in 2025 (6x increase YoY per Africa Report Feb 2026). Lobito Corridor opens Atlantic export route bypassing East African ports historically controlled by Chinese SOE rail."},
        'gold':         {'role': 'producer',          'weight': 0.9,
                         'note': "Eastern Congo (Ituri + South Kivu + North Kivu) is one of Africa's largest artisanal gold sources; significant volumes smuggled through Uganda/Rwanda/Burundi to UAE refiners. M23 + ADF + FDLR + other armed groups extract conflict-financing rents. Russia-linked PMC (Africa Corps/Wagner successor) reported activity in Ituri concessions. June 2025 DRC-Rwanda peace deal directly targets the conflict-gold-corridor problem. Watch: UAE gold import data, Kinshasa-Kigali tensions, M23 controlled territory."},
        'lithium':      {'role': 'producer',          'weight': 0.8,
                         'note': "Manono project (Tanganyika province) is one of the largest undeveloped hard-rock lithium deposits globally — comparable to Australia's Greenbushes. Chinese (Zijin Mining) + Australian (AVZ Minerals) ownership dispute has stalled development since 2023; political settlement remains uncertain. When/if Manono comes online, materially shifts non-Australian lithium supply picture. Watch: Manono ownership settlement, KoBold Metals (US, Gates-backed) prospecting, Zijin-AVZ arbitration outcomes."},
        'tantalum':     {'role': 'producer',          'weight': 1.0,
                         'note': "DRC produces ~40% of global tantalum (coltan = columbite-tantalite ore). Tantalum is critical for capacitors in smartphones/laptops/aerospace/medical implants. Eastern Congo coltan is the canonical 'conflict mineral' — Dodd-Frank Section 1502 disclosure regime, OECD due diligence guidance, EU Conflict Minerals Regulation all aimed at this supply chain. M23 controls coltan-rich Rubaya area. Watch: ITRI iTSCi traceability data, Apple/Intel supply chain disclosures, M23 territorial control updates."},
        'diamonds':     {'role': 'producer',          'weight': 0.6,
                         'note': "DRC is a meaningful diamond producer (~15-20 Mcarats/yr) but historically conflict-adjacent supply (Kasai region); Kimberley Process participant. Société Anonyme MIBA + small-scale artisanal sector. Less material than DRC's cobalt/copper/coltan story but adds to the Africa-diamonds picture and the broader conflict-minerals frame. Watch: MIBA production data, Kimberley Process annual statistics."},
    },
    'egypt': {
        'gold':         {'role': 'producer', 'weight': 0.8, 'data_as_of': '2026-06',
                         'note': "Sukari (Eastern Desert) is a top-tier African gold mine (~450k oz/yr); AngloGold Ashanti acquired operator Centamin (2025), and Egypt signed Eastern Desert exploration deals (incl. Barrick). Gold+silver output rose ~14% to ~$1.54B in 2024-25; the central bank is accumulating. Watch: EMRA bid-round results, AngloGold Sukari guidance."},
        'phosphate':    {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Among the larger phosphate-rock producers/reserve holders (Abu Tartour, Red Sea, Nile Valley); exports rock + growing downstream DAP/MAP (with Hormuz sulfur-cascade exposure). Part of the Vision 2030 mining push. Watch: rock exports, DAP capacity, sulfur input costs."},
        'silicon':      {'role': 'producer', 'weight': 0.7,
                         'note': "EMERGING PRODUCER with strategic ambition: ~20 billion tonnes of silica resources (among the world's largest). Vision 2030 targets lifting mining to ~5-6% of GDP, and 2025 ministerial policy elevated silica sand to a strategic industrial mineral -- with an explicit climb from raw-sand export toward metallurgical silicon, polysilicon, and solar feedstock (EMRA reconstituted as an economic authority). Low-cost energy + IFC backing. Output is nascent; the weight reflects ambition + reserve base, not current tonnage. Watch: EMRA tenders, silica-to-solar value-add projects, Chinese polysilicon JVs."},
        'rice':         {'role': 'producer',          'weight': 0.9,
                         'note': "Nile Delta producer that also imports in drought years; rice shares the politically charged subsidized-staple space with baladi bread. Water scarcity (GERD/Nile constraints) periodically forces cultivation-area restrictions, tightening domestic supply and occasionally banning exports. Watch: cultivation-area decrees, GASC tenders, Nile water-allocation news, subsidy-reform signals."},
        'nitrogen':     {'role': 'producer', 'weight': 1.3,
                         'note': "Major urea / ammonia EXPORTER (gas-based; MOPCO, EBIC, Abu Qir) and a Mediterranean swing supplier to Europe. GAS-CASCADE EXPOSURE: when domestic gas is diverted to power / cooling in summer, Egyptian nitrogen plants curtail -- tightening European urea supply. Watch: Egyptian gas allocation to fertilizer plants, summer curtailment notices, EGAS pricing."},
        'wheat':        {'role': 'consumer',          'weight': 1.4, 'rank': 1,
                         'note': "World's #1 wheat importer (~12.7 Mt 2025-26, ahead of Indonesia + Algeria). Population ~108M (projected 124M by 2030); ~50% of wheat needs imported. Bread subsidy program (`baladi` bread for ~70M citizens) is the central political stability lever — Mubarak fell in part over bread prices. Russia (~66%) + Ukraine (~17%) + EU/France (~14%) primary suppliers. Mostakbal Misr (military-linked) replaced GASC as state buyer in late 2024 — adds opacity to global wheat tender pricing. Watch: GASC/Mostakbal tender results, Russian wheat export taxes, Black Sea grain corridor status, Egyptian pound USD reserve adequacy."},
        'corn':         {'role': 'consumer',          'weight': 1.0,
                         'note': "~9.5 Mt imported 2025-26 (up 9% YoY on poultry sector demand); Brazil + Ukraine + Argentina primary suppliers; domestic production only covers ~30% of feed demand. Yellow corn for poultry feed = 70% of feed mix. Population growth driver."},
        'natural_gas':  {'role': 'producer',          'weight': 0.9,
                         'note': "Eastern Mediterranean producer (Zohr field, Tamar/Leviathan re-imports from Israel via EMG pipeline); LNG export terminals at Idku + Damietta; recent shift to net importer status during demand peaks. Strategic energy hub for East Med; mediator role between Israeli + Cypriot + Greek + Turkish maritime claims."},
        'oil':          {'role': 'transit',           'weight': 1.0,
                         'note': "Suez Canal + SUMED pipeline transit: ~12% of global seaborne oil + ~8% of LNG passes through. Suez closure scenarios (e.g., 2021 Ever Given grounding, 2023-25 Houthi Red Sea attacks shifting flows) directly impact Brent-Dubai spread. Egypt extracts strategic rents from chokepoint position; Suez Canal Authority + government revenue ~$8-10B/yr. Watch: Houthi BAM attack tempo, Egyptian foreign reserves, IMF program status."},
    },
    'eu': {
        # ─────────────────────────────────────────────────────────────────────
        # EU BLOC ENTRY — see programming note at top of COUNTRY_COMMODITY_EXPOSURE
        # When France, Germany, Italy, Poland, Spain, etc. are added as individual
        # country pages, those entries should INHERIT eu's commodity exposures and
        # override only where genuinely national (France nuclear/uranium is the
        # canonical example — already split out below).
        # ─────────────────────────────────────────────────────────────────────
        'wheat':        {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 wheat producer (~135-140 Mt/yr); France, Germany, Poland, Romania, Bulgaria are top member-state producers. Major exporter to MENA + Sub-Saharan Africa. CAP (Common Agricultural Policy) subsidy framework + variable export refunds. Black Sea disruption (Ukraine war) made EU the marginal Mediterranean wheat supplier."},
        'copper':       {'role': 'consumer',          'weight': 1.2,
                         'note': "Major EU industrial consumer; Germany + Italy + Spain manufacturing demand. Aurubis (largest EU smelter), Boliden (Sweden). Net importer despite some Polish + Iberian production. Energy transition (grid + EV) is structural EU demand driver."},
        'natural_gas':  {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #2 LNG importer (overtook Japan 2022 post-Ukraine war); ~140 BCM/yr LNG imports. USA + Qatar + Algeria + Norway primary pipeline + LNG suppliers. Russia-dependency reduced from ~40% (2021) to ~10% (2024) via REPowerEU. Gas-storage targets + carbon-tax framework structural. Watch: AGSI gas storage levels, TTF benchmark price, Norwegian pipeline flow."},
        'corn':         {'role': 'consumer',          'weight': 1.0,
                         'note': "Major importer + producer (~70 Mt/yr produced, +imports). Animal feed primary use. Ukraine + Brazil primary import suppliers. Spain + Italy + Netherlands largest importers."},
        'soybeans':     {'role': 'consumer',          'weight': 1.3, 'rank': 3,
                         'note': "Major importer (~30 Mt/yr); near-zero domestic production. Brazil + USA + Argentina primary suppliers. Animal feed (poultry + pork) crusher demand. Spain + Netherlands + Germany ports dominant. EU Deforestation Regulation (EUDR, 2024) reshapes Brazilian soy supply chain compliance requirements."},
        'nickel':       {'role': 'consumer',          'weight': 1.1,
                         'note': "Major nickel consumer for stainless steel + EV battery cathode; Northvolt (Sweden), Verkor (France), ACC (FR/DE) battery plants under construction with class-1 nickel demand."},
        'rare_earths':  {'role': 'consumer',          'weight': 1.3, 'rank': 3,
                         'note': "Critical Raw Materials Act (CRMA, 2024) targets 40% domestic processing + 25% recycling by 2030 + max 65% single-country reliance. Lynas Malaysia-processed REE + Solvay La Rochelle (France) recycling. China-dependency reduction the strategic objective."},
        'semiconductors': {'role': 'producer',        'weight': 1.0,
                         'note': "EU Chips Act (€43B, 2023) targets 20% global semiconductor production by 2030 (current ~9%). Intel Magdeburg + TSMC Dresden + Wolfspeed Saarland + STMicroelectronics-GlobalFoundries Crolles. Trailing-edge + automotive chips dominant; leading-edge (sub-7nm) presence minimal apart from ASML (Netherlands)."},
        'sugar':        {'role': 'producer',          'weight': 1.0,
                         'note': "🌾 EU sugar producer ~16-17 MMT/yr from sugar beet (France + Germany + Poland + UK); historically self-sufficient + small net exporter. EU sugar quota system ended Sept 2017 — production now market-based, EU competitiveness vs Brazilian cane sugar tightened. CAP support for beet farmers + ACP-EPA preferential cane imports from African/Caribbean/Pacific countries. Watch: EU Sugar Observatory, beet harvest forecasts, ACP-Pacific cane import volumes."},
        'phosphate':    {'role': 'consumer',          'weight': 1.0,
                         'note': "Major phosphate fertilizer consumer (~5-7 Mt/yr DAP/MAP equivalent); near-zero domestic phosphate rock production (some Finnish + minor Belgian sources). Morocco (OCP) + Russia (Phosagro pre-sanctions) + Tunisia primary suppliers. EU Critical Raw Materials Act (2024) added phosphate rock as strategic material. NOTE on Western Sahara: certain EU court rulings (most recently 2024) have held that contracts requiring Western Sahara provenance be treated separately from Moroccan-proper sourcing — the EU is the jurisdiction where OCP's combined Morocco/Western-Sahara output is most actively litigated. Watch: Yara + ICL Group phosphate trade flows, EU Critical Raw Materials Act implementation."},
            'graphite':     {'role': 'consumer',          'weight': 0.9,
                         'note': "Natural graphite is on the EU Critical Raw Materials Act strategic list with 2030 extraction/processing/diversification targets -- the bloc's battery buildout is exposed to the same Chinese permit gate as the US, with fewer domestic alternatives moving. Watch: CRMA strategic-project designations, EU-China trade-defense actions touching anode materials."},
},
    'france': {
        'uranium':      {'role': 'consumer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 uranium consumer; ~70% of French electricity from nuclear (~56 reactors operated by EDF). Orano (formerly Areva) provides full fuel cycle: La Hague reprocessing + Tricastin enrichment + Melox MOX fabrication. Niger uranium supply traditionally critical (~20% of French imports historically) — disrupted by 2023 Niger coup; pivot to Kazakhstan + Canada + Australia accelerated. Macron's 2022 nuclear renaissance announcement (6 new EPR2 reactors) raises uranium demand trajectory. Watch: Niger uranium status, Orano-Kazatomprom contracts, EDF reactor availability."},
        'wheat':        {'role': 'producer',          'weight': 1.0,
                         'note': "Largest individual EU wheat producer (~35-37 Mt/yr, ~26% of EU total). Major Egypt + Algeria + sub-Saharan Africa supplier. CAP-driven; Brittany + Beauce + Picardy regions. Listed separately from EU bloc only because French wheat exports have a distinct national identity in MENA markets (vs. generic 'EU' supply)."},
    },
    'germany': {
        'semiconductors': {'role': 'component_producer', 'weight': 1.4, 'rank': 2,
                         'note': "EUV CHOKEPOINT INPUT: Carl Zeiss SMT (optics) + Trumpf (high-power CO2 lasers) are the near-sole suppliers of the optical and light-source subsystems inside every ASML EUV lithography machine -- no Zeiss/Trumpf, no leading-edge chips anywhere on Earth. Plus 'Silicon Saxony' around Dresden (GlobalFoundries, Infineon, Bosch) and the TSMC-led ESMC fab under construction (~2027). Component-producer sitting on a genuine global chokepoint."},
        'natural_gas':  {'role': 'consumer',           'weight': 1.4, 'rank': 1,
                         'note': "Europe's largest natural-gas consumer; the post-2022 loss of Russian pipeline gas forced a scramble to Norwegian pipeline supply plus new LNG import terminals (Wilhelmshaven, Brunsbuttel). Gas price and availability gate the entire German industrial base -- chemicals, steel, glass. Watch: Norwegian flow rates, LNG terminal throughput, industrial-curtailment signals."},
        'silicon':      {'role': 'producer',           'weight': 1.2,
                         'note': "Wacker Chemie (Burghausen) is the West's leading hyperpure-polysilicon producer -- nearly half the world's microchips use Wacker polysilicon -- and Siltronic is a top-tier silicon-wafer maker. Both are margin-squeezed by Chinese polysilicon oversupply. Germany is the non-China anchor of the upstream chip-feedstock chain. Watch: Wacker capacity adds, Siltronic strategic review, EU anti-dumping posture."},
        'nitrogen':     {'role': 'producer_consumer',  'weight': 1.2,
                         'note': "BASF's Ludwigshafen complex (the world's largest integrated chemical site) is a major ammonia/nitrogen producer and a textbook GAS-CASCADE node: when European gas spiked in 2022, BASF curtailed ammonia and bought on world markets, tightening global nitrogen supply. Watch: BASF ammonia run-rates, European gas spreads."},
        'potash':       {'role': 'producer',           'weight': 1.1,
                         'note': "K+S AG (Kassel) is one of the world's leading potash and salt producers -- German mines (Werra, Zielitz) plus the Bethune mine in Canada -- a Western fertilizer anchor alongside Canada, Belarus, and Russia. Potash processing is energy-intensive, so German power costs feed directly into output economics."},
        'copper':       {'role': 'consumer',           'weight': 0.9,
                         'note': "Aurubis (Hamburg) is Europe's largest copper smelter and recycler -- a processing node converting concentrate and scrap into refined copper for German industry. Exposure runs to concentrate supply (treatment/refining charges) and energy costs, not mine ownership."},
    },
    'greece': {
        'oil':          {'role': 'transit',           'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "FLOW, NOT STOCK: Greece produces almost no crude but owns the world's LARGEST merchant fleet by deadweight tonnage -- Greek shipowners control a very large share of the global crude- and product-tanker fleet -- so Greek exposure is to FREIGHT RATES and chokepoint reroutes, not wellhead output. A Red Sea (Bab-el-Mandeb) or Hormuz disruption forcing Cape-of-Good-Hope reroutes hits Greek owners' economics directly. Plus domestic refining/bunkering (HELLENiQ Energy [ex-Hellenic Petroleum], Motor Oil Hellas at Corinth) and Aegean bunker hubs. Watch: Baltic Dirty/Clean tanker indices, Greek-owned fleet-share data, Red Sea/Hormuz reroute signals, HELLENiQ/Motor Oil refining runs."},
        'natural_gas':  {'role': 'transit',           'weight': 0.8, 'data_as_of': '2026-06',
                         'note': "Emerging South-East Europe gas gateway: the Trans Adriatic Pipeline (TAP) lands Azeri Shah Deniz gas en route to Italy; the Revithoussa LNG terminal and the new Alexandroupoli FSRU (offshore northern Greece) import LNG for onward flow into the Balkans; and the Greece-Bulgaria IGB interconnector links the network northward. Greece's role is corridor / regasification, not production. Watch: Alexandroupoli FSRU throughput, Revithoussa send-out, TAP flows, IGB utilization."},
    },
    'greenland': {
        'rare_earths':  {'role': 'producer', 'weight': 1.2, 'data_as_of': '2026-07',
                         'regime_flags': ['critical_minerals_contested', 'us_strategic_interest'],
                         'note': "POTENTIAL, NOT PRODUCTION -- but the geology is world-class: Kvanefjeld (Kuannersuit) and Tanbreez in the south are among the largest undeveloped rare-earth deposits on Earth. Kvanefjeld is FROZEN by the 2021 uranium-mining ban (the deposit is uranium-bearing; Chinese-linked Shenghe Resources holds a stake in operator Energy Transition Minerals), while Tanbreez advances under US-aligned Critical Metals Corp -- making Greenland the physical square where the US, China, and the EU critical-minerals contest actually lands. Renewed US acquisition/security pressure keeps strategic attention pinned. STABILITY LINK: mining politics IS Greenlandic politics -- the 2021 election turned on Kvanefjeld, and every REE headline re-energizes the independence-vs-Denmark debate and the US-Denmark alliance friction. Watch: Tanbreez permitting/offtake milestones, uranium-ban politics in Inatsisartut, US/Denmark security statements, Chinese stake movements, EU Critical Raw Materials Act engagement."},
        'gold':         {'role': 'producer', 'weight': 0.3, 'data_as_of': '2026-07',
                         'note': "Nalunaq (Amaroq Minerals) restarted -- small output, but Greenland's only active metals mine and the symbolic reopening of the mining economy after a decade dormant. A sentiment bellwether for whether extraction in Greenland is investable at all. Watch: Amaroq production ramp, new exploration-license tempo, Greenland government royalty/permitting posture."},
    },
    'guinea': {
        'bauxite':      {'role': 'producer',          'weight': 1.5, 'rank': 2,
                         'regime_flags': ['belt_and_road_anchor'],
                         'note': "🥇 World's #2 bauxite producer (~25% of global supply, ~110 Mt/yr) and the SINGLE most important non-Chinese supplier — China imports ~55% of its bauxite from Guinea via Boké region. SMB Winning Consortium (Société Minière de Boké, Chinese+Singaporean+Guinean JV) is the largest operator; CBG (Compagnie des Bauxites de Guinée, Alcoa+Rio Tinto+Halco JV) the Western-aligned alternative; EGA Guinea (Emirates Global Aluminium) is third major. BELT-AND-ROAD HEAVY FOOTPRINT: Chinese-funded Boké-Conakry railway + Kamsar port + Conakry container port — same resource-leverage playbook as DRC cobalt. POLITICAL SETTLEMENT: Doumbouya's Sept 2021 coup briefly disrupted bauxite shipments and spiked alumina ~10% in a week; the transition RESOLVED via the Dec 2025 election -- Doumbouya sworn in Jan 2026, AU sanctions lifted, with a 14-year constitutional runway. Single-leader supply concentration is now the risk shape (one man, ~25% of world bauxite, ~55% of China's imports). Watch: SMB/CBG/EGA output, Conakry port throughput, mining-code fiscal renegotiations, Conakry street stability."},
        'iron_ore':     {'role': 'producer',          'weight': 1.2,
                         'note': "SIMANDOU MEGAPROJECT — world's largest high-grade iron ore deposit -- IN PRODUCTION since late 2025 (first ore shipped) and the centerpiece of Doumbouya's 'Simandou 2040' program (Simandou Mountains, southeast Guinea). Rio Tinto (Simandou South blocks 3-4) + SMB Winning Consortium / WCS (blocks 1-2) developing in parallel; total potential ~120 Mt/yr at high-grade (~65% Fe). First production scheduled late 2025/2026, ramp to full capacity 2027-2028. RESHAPES GLOBAL IRON ORE: when fully online, materially undercuts Australian (Pilbara) + Brazilian (Vale Carajás) dominance and reduces China's exposure to Australian supply concentration. Trans-Guinea Railway (650km) + Morebaya deepwater port being built simultaneously. Watch: first commercial shipments, railway commissioning, Rio Tinto guidance, China-Conakry political alignment."},
        'gold':         {'role': 'producer',          'weight': 0.8,
                         'note': "Guinea is Africa's #4 gold producer (~85 t/yr); AngloGold Ashanti + Société Anonyme de Guinée + Russian Nordgold + Chinese SOE Hyperdynamics. Artisanal sector substantial. Russian gold-mining presence (Nordgold, Severnaya Aurora) gives Moscow indirect leverage. Watch: AngloGold output guidance, Russian-affiliated mine status post-coup."},
        'diamonds':     {'role': 'producer',          'weight': 0.4,
                         'note': "Modest diamond producer (Banankoro region); historically conflict-adjacent supply. Not material to global supply but Kimberley Process participant."},
    },
    # ============================================================
    # HUNGARY (added May 17, 2026)
    # Russia-axis-DEPENDENT country undergoing AXIS REVERSAL after
    # April 2026 Tisza landslide defeated Orban/Fidesz. Druzhba oil
    # pipeline transit + Russian gas dependency are the structural
    # leverage points. The May 2026 $82M cash + 9kg gold return to
    # Ukraine + EU loan veto lift mark concrete reversal symptoms.
    # Source: AP/Spike May 6 2026; Bloomberg April 2026 election cov.
    # ============================================================
    'hungary': {
        'oil':          {'role': 'transit',           'weight': 1.0,
                         'regime_flags': ['axis_reversal_in_progress', 'druzhba_pipeline_critical'],
                         'note': "Druzhba pipeline transit -- Russian crude flows Russia -> Ukraine -> Hungary -> Slovakia -> Czechia. MOL Group (Hungarian state-anchored) operates Szazhalombatta + Tisza refineries (Russian Urals crude optimized). Pre-Tisza election: Orban government blocked the 90B EUR EU loan to Ukraine specifically over Druzhba interruption (Russian drone strike damage). Post-Tisza election (April 2026 landslide): Druzhba flows resumed + Hungary lifted EU loan veto. Watch: MOL refinery loadout, Druzhba flow telemetry, EU sanctions exemption status."},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'regime_flags': ['axis_reversal_in_progress'],
                         'note': "Heavily dependent on Russian gas (Gazprom via TurkStream + Hungarian state long-term contract signed under Orban 2021). Hungary was one of the few EU members to maintain direct Gazprom contracts through Ukraine war + post-2022 sanctions cycles. Tisza government policy on Russian gas TBD; expected gradual diversification toward LNG (Krk Croatia + Polish Baltic Pipe). Watch: MVM Hungary statements on gas contracts, TurkStream flow data, Hungarian energy minister appointments."},
        'gold':         {'role': 'transit',           'weight': 0.4,
                         'regime_flags': ['historic_reversal_event'],
                         'note': "Not a structural gold actor, but the canonical AXIS REVERSAL event: March 5 2026 Hungarian counter-terrorism authorities (under Orban) seized 80M USD + 9kg gold shipment between Ukrainian state banks (Oschadbank) transiting Hungary by armored car. Orban claimed money-laundering investigation. Ukraine called it political blackmail re: Druzhba pipeline + Tisza party funding accusations. May 6 2026: Tisza government RETURNED full shipment. Tiny in commodity terms but ANALYTICALLY foundational -- the first documented Asifah-trackable axis-reversal event in Europe."},
        'wheat':        {'role': 'producer',          'weight': 0.6,
                         'note': "Modest EU wheat producer (~5 Mt/yr); Great Hungarian Plain agriculture. Part of CAP system. Net exporter regionally. Not a global pricing-mover but a stability-of-agriculture signal for Central Europe."},
        'uranium':      {'role': 'consumer',          'weight': 0.7,
                         'regime_flags': ['axis_reversal_in_progress'],
                         'note': "Paks Nuclear Power Plant (Russian VVER reactors) supplies ~45% of Hungarian electricity. Rosatom contracted to build Paks II expansion (2014 deal under Orban). Post-Tisza election, Paks II Rosatom contract status under review. Watch: Paks II construction milestones, Rosatom financing arrangements, EU nuclear-sector sanctions exposure."},
    },
    'india': {
        'coal':         {'role': 'producer_consumer', 'weight': 1.2, 'data_as_of': '2026-06',
                         'note': "World's #2 coal producer (~1 Bt, ~12%) AND a huge importer -- Coal India dominates domestic output but power demand still pulls thermal imports (Indonesia, Australia). Watch: Coal India output, monsoon hydro, import parity."},
        'rice':         {'role': 'producer',          'weight': 1.4, 'rank': 1,
                         'note': "World's #1 rice exporter (~40% of global trade). India's export-policy toggles are the single biggest swing factor in world rice prices - the mid-2023 non-basmati white-rice export ban (eased in stages through 2024) sent global prices to multi-year highs and rerouted flows to Africa and Southeast Asia. Basmati (premium, Gulf/Iran-bound) and non-basmati (bulk, Africa/Asia) are distinct markets. Watch: DGFT export notifications, minimum export prices, monsoon performance, FCI buffer-stock levels."},
        'nitrogen':     {'role': 'consumer', 'weight': 1.5, 'rank': 1,
                         'note': "World's #1 urea importer and a top consumer (~700M farmers; heavily subsidized via Nutrient Based Subsidy + urea price control). India's periodic urea import TENDERS (IPL/RCF/MMTC) set the global benchmark price. STRATEGIC EXPOSURE: heavy reliance on imported finished urea + feedstock means gas-driven price spikes flow straight into the fertilizer subsidy bill. Watch: India urea tender results + volumes, NBS subsidy adjustments, domestic plant gas allocation."},
        'wheat': {
            'producer': {'weight': 1.3, 'rank': 2,
                         'note': "World's #2 wheat producer (~115 Mt/yr); Punjab + Haryana + Uttar Pradesh dominant; FCI (Food Corporation of India) state procurement at MSP (Minimum Support Price). India is structurally export-restricted — May 2022 + 2023 export bans (in response to Ukraine war disruption) directly tightened global Black Sea-replacement supply. Watch: FCI procurement levels, MSP announcements, export-ban policy."},
            'consumer': {'weight': 1.3, 'rank': 2,
                         'note': "World's #2 wheat consumer (~106 Mt/yr); roti-chapati staple food. Demand structurally inelastic. PDS (Public Distribution System) provides subsidized wheat to ~800M citizens — politically central food-security commodity."},
        },
        'oil':          {'role': 'consumer',          'weight': 1.3, 'rank': 3,
                         'note': "World's #3 oil consumer (~5M bpd); ~85% imported. Russian crude (post-sanctions discount) became dominant supplier 2022-2025 (~35-40% of Indian crude). IOCL + BPCL + HPCL + Reliance + Nayara refining majors. Modi government balancing US-sanctioned-Russian-crude purchases against Western pressure. Watch: Indian customs crude import data, Reliance Jamnagar mix, US sanctions enforcement signals."},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': "Major LNG importer (~24 MMT/yr); Petronet LNG + GAIL + Adani-TotalEnergies operations. Qatar + USA + UAE primary suppliers. Strategic Petroleum Reserve + LNG diversification policies under Modi. Watch: Petronet (NS:PETRONET) contract renewals, US LNG export licenses to India."},
        'gold':         {'role': 'consumer',          'weight': 1.5, 'rank': 2,
                         'note': "World's #1 gold importer (~800-900 t/yr depending on rupee strength + wedding season + festival demand). Cultural + investment + wedding-jewelry demand. Modi May 2026 verbal intervention asking Indians to stop buying gold for a year = canonical defensive jawboning signal (FX-pressure absorption). Reserve Bank of India + private retail combine for world-leading demand. Watch: India Bullion + Jewellers Association statements, monthly gold import data, RBI gold-reserves disclosures, festival/wedding-season-adjusted demand."},
        'silver':       {'role': 'consumer',          'weight': 0.9,
                         'note': "Major silver consumer (~6,000 MT/yr) for jewelry + industrial + investment; price tracks gold-silver ratio + INR volatility."},
        'potash':       {'role': 'consumer',          'weight': 1.0,
                         'note': "Major potash consumer (~6-7 Mt/yr); ~100% imported. Russia + Belarus + Canada primary suppliers. Subsidized via NBS (Nutrient Based Subsidy) framework. Fertilizer-cost politics central to Indian agricultural politics."},
        'corn':         {'role': 'producer',          'weight': 1.0,
                         'note': "Major producer (~35 Mt/yr); growing animal feed + ethanol blending program demand. Modi government 20% ethanol blending mandate (E20, 2025 target) elevates corn demand structurally. Net exporter historically, becoming structurally balanced/importer."},
        'sugar':        {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'regime_flags': ['sub_consumer_floor'],
                         'note': "🌾 World #1 sugar producer (~30 MMT 2024/25, surpassing Brazil in volume in some years) AND #1 consumer (~31 MMT/yr) — making India the WORLD'S ONLY MAJOR PRODUCER WHERE PRODUCTION FELL BELOW CONSUMPTION in 2024/25 (first time in 8+ years). Maharashtra + Uttar Pradesh + Karnataka dominant cane regions. State-level cane pricing + FRP (Fair and Remunerative Price) politics. Modi government's 2025/26 ethanol blending mandate (E20, 20% ethanol) diverted ~3-4 MMT of sugar to ethanol — directly tightening global supply. STRUCTURAL REGIME: when India's production falls below consumption, India becomes the inelastic importer and export-policy variable for global sugar prices. Watch: ISMA cane harvest reports, government ethanol-diversion announcements, ISO export quota decisions, monsoon rainfall (Maharashtra cane is rain-fed)."},
        'chromium':     {'role': 'producer',          'weight': 0.9,
                         'note': "World's #4 chromium producer (~3-4 Mt/yr); Sukinda Valley (Odisha) is the dominant chromite belt. Tata Steel + IMFA + Balasore Alloys major operators. India is both producer + consumer (domestic stainless-steel demand growing) + significant ferrochrome exporter. Watch: Tata Steel ferro alloys segment, IMFA quarterly production."},
        'manganese':    {'role': 'consumer',          'weight': 1.0,
                         'note': "Major manganese consumer (~2 Mt/yr) for steel sector; India's steel-production growth (target 300 Mt by 2030 per National Steel Policy) is structural manganese demand driver. MOIL Ltd (state-owned) is largest domestic producer. South African + Gabonese imports balance demand. Watch: MOIL Ltd production, Indian steel-output data."},
        'phosphate':    {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': "🥇 World's #1 phosphate consumer (~10-12 Mt/yr DAP/MAP equivalent). India is ~90% reliant on imports for phosphate raw materials — single most concentrated fertilizer dependency on Earth. Morocco (OCP) + Jordan (JPMC) + Russia (Phosagro pre-sanctions) + Saudi (Ma'aden) + China (until 2021 export quotas) primary suppliers. India phosphate tender outcomes (IPL, Coromandel, IFFCO) set global DAP benchmark. Modi government subsidizes via NBS (Nutrient Based Subsidy). STRATEGIC EXPOSURE: India's phosphate import dependency = single largest fertilizer-cost variable for ~700M Indian farmers. Hormuz sulfur cascade flows into Indian DAP prices via processing. Watch: India phosphate tender results (IPL/Coromandel), Modi government NBS rate adjustments, OCP-India trade flow."},
        'bauxite':      {'role': 'producer',          'weight': 0.9,
                         'note': "World's #6 bauxite producer (~20-22 Mt/yr); Odisha + Andhra Pradesh + Gujarat. NALCO (National Aluminium Company) + Hindalco (Aditya Birla) + Vedanta dominant operators. India's aluminum sector is growing (~4 Mt/yr aluminum production); domestic bauxite mostly supports domestic aluminum vs export. Watch: NALCO production guidance, Hindalco (NS:HINDALCO) earnings, Vedanta Lanjigarh refinery status."},
        'diamonds':     {'role': 'producer_consumer', 'weight': 1.5, 'rank': 1,
                         'note': "🥇 SURAT — the world's diamond-cutting capital. India cuts + polishes ~90% of the world's rough diamonds BY VOLUME (and ~80% by value); Surat's Gujarat-based cutting industry employs ~1M workers across ~5,000 units. Mumbai (Bharat Diamond Bourse) + Surat (cutting) + Mumbai SEEPZ (jewelry) form India's downstream diamond cluster. India is the second-largest diamond consumer (after USA) and a meaningful jewelry market. GJEPC (Gem & Jewellery Export Promotion Council) regulates exports. STRATEGIC: India was historically the largest buyer of Russian Alrosa rough — G7 sanctions on Russian diamonds caught Indian cutters in the middle, with multiple voluntary halts to Russian-origin rough since March 2024. Surat industry is materially affected by both lab-grown diamond growth AND the Russian-sanctions enforcement framework. Watch: GJEPC monthly export statistics, Surat industry layoff/shutdown reports, lab-grown vs natural mix data."},
        'uranium':      {'role': 'consumer',          'weight': 0.8,
                         'note': "Growing uranium consumer (~22 reactors, target 70+ by 2032). NPCIL + Indian Atomic Energy Commission operate. Domestic uranium (UCIL Jaduguda) insufficient; imports from Kazakhstan + Russia + France + Canada (under bilateral safeguards agreements). Civil nuclear cooperation with US (123 Agreement 2008) + France + Russia. Watch: NPCIL reactor commissioning, IAEA safeguards inspections, US-India 123 Agreement reauthorization."},
    },
    'indonesia': {
        'copper':       {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Grasberg (Papua; Freeport + MIND ID) is one of the world's largest copper-gold mines; new domestic smelters (Gresik) under the concentrate-export ban keep value onshore. Watch: Grasberg permitting, smelter ramp, export-ban enforcement."},
        'gold':         {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Grasberg is also a top-tier gold mine (~140 t/yr national total); copper-gold coupled -- a major byproduct-gold source."},
        'coal':         {'role': 'producer', 'weight': 1.3, 'rank': 2, 'data_as_of': '2026-06',
                         'note': "World's #1 thermal coal EXPORTER (~9% of global production; Kalimantan); swing supplier to China/India power. Domestic Market Obligation (DMO) + royalty shifts ripple through Asian power costs. Watch: DMO rules, China/India import demand, royalties."},
        'natural_gas':  {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Long-standing LNG exporter (Bontang, Tangguh); output maturing as domestic demand rises, but still a notable Pacific-basin supplier."},
        'oil':          {'role': 'consumer', 'weight': 0.9, 'data_as_of': '2026-06',
                         'note': "Net oil IMPORTER now (production declined; Pertamina); fuel subsidies are a fiscal/political pressure point. A demand-side Southeast Asian barrel."},
        'rice':         {'role': 'consumer',          'weight': 1.2,
                         'note': "One of the world's largest rice consumers and a recurring major importer; rice prices are directly politically sensitive. Bulog (state logistics agency) manages reserves and import tenders; El Nino harvest shortfalls trigger large import programs. Watch: Bulog import tenders, domestic retail rice prices, El Nino/harvest outlook, Bapanas food-agency policy."},
        'coffee':       {'role': 'producer',          'weight': 0.9, 'rank': 4,
                         'note': "Major coffee producer - robusta from Sumatra (Lampung) plus specialty arabica (Gayo, Java); a meaningful export-earner though smaller than Brazil/Vietnam. Rising domestic consumption is tightening the exportable surplus. Watch: Sumatra harvest/weather, robusta export volumes, domestic-consumption growth."},
        'nickel':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 nickel producer (~50% global mine + smelter). Sulawesi (Morowali + Weda Bay) integrated nickel parks operated primarily by Chinese capital (Tsingshan + Huayou + GEM Co). Class-1 battery-grade nickel via HPAL (high-pressure acid leach) — environmentally controversial + sulfur-acid intensive. STRATEGIC: 2020 nickel ore export ban forced downstream processing onshore — successful resource-leverage playbook (Jokowi-Prabowo). Indonesia + Philippines = ~60% global supply. Watch: Indonesian Ministry of Energy + Mineral Resources statements, IMIP/IWIP output, Tsingshan production."},
        'cobalt':       {'role': 'producer',          'weight': 1.0,
                         'note': "Indonesia is the world's #2 cobalt producer (~20% global, rising) — cobalt is largely a by-product of HPAL nickel processing in Sulawesi. Strategic challenge to DRC's cobalt dominance + provides Chinese cobalt supply chain diversification away from DRC concentration risk. Watch: HPAL output, Tsingshan-Huayou cobalt segment data."},
        'wheat':        {'role': 'consumer',          'weight': 1.1, 'rank': 2,
                         'note': "World's #2 wheat importer (~11-12 Mt/yr); Indomie noodles + bread sectors central. Russia + Ukraine + Australia + USA primary suppliers. Indonesian rupiah volatility = key affordability variable."},
        'bauxite':      {'role': 'producer',          'weight': 1.0, 'rank': 5,
                         'note': "World's #5 bauxite producer historically (~20 Mt/yr peak); 2023 BAUXITE EXPORT BAN (extending the 2020 nickel-ore export ban playbook) forced downstream alumina/aluminum processing onshore. Pattern repeated: resource-leverage to capture value-added industry. Inalum (state aluminum company) + Antam + private Chinese-funded refineries. China imports significantly reduced post-ban; Guinea + Australia backfilled. Watch: Indonesian alumina refinery commissioning, Inalum production, Antam (IDX:ANTM) earnings."},
    },
    'israel': {
        'potash':       {'role': 'producer',          'weight': 1.0,
                         'note': "ICL Group (Dead Sea Works) operates potash + bromine + magnesium extraction; ~7-9% global potash output. Tel Aviv-listed (ICL) + NYSE. Major Israel-Jordan transboundary resource (Dead Sea shared)."},
        'natural_gas':  {'role': 'producer',          'weight': 1.1, 'rank': 5,
                         'note': "Eastern Mediterranean producer; Tamar + Leviathan + Karish offshore fields supply domestic demand + exports to Egypt + Jordan via EMG pipeline. Chevron + NewMed Energy + Delek consortium. STRATEGIC: Israel's gas exports to Egypt (which re-exports as LNG to EU) make Israel an indirect EU gas-security actor post-Ukraine. Watch: Leviathan/Tamar production, Egypt LNG terminal arrivals, Karish operational status."},
        'wheat':        {'role': 'consumer',          'weight': 1.0,
                         'note': "~95% imported (~1.5 Mt/yr); Russia + Ukraine + USA primary suppliers. Bread subsidies (under Likud-era policies) politically sensitive."},
        'corn':         {'role': 'consumer',          'weight': 0.8,
                         'note': "Major feed corn importer; poultry + dairy sector demand."},
        'soybeans':     {'role': 'consumer',          'weight': 0.7,
                         'note': "~100% imported for animal feed."},
        'oil':          {'role': 'consumer',          'weight': 1.2,
                         'note': "~99% imported; pre-war: ~50% Azeri (BTC pipeline + Ceyhan), ~30% Kazakh (CPC). Post-Iran-war (March 2026): exposure to disrupted regional supply chains; Strategic Petroleum Reserve coverage ~30 days. Watch: Eilat + Ashkelon refinery utilization, Azeri SOCAR cargo flow."},
        'diamonds':     {'role': 'producer_consumer', 'weight': 1.4, 'rank': 2,
                         'note': "🥇 RAMAT GAN — one of the world's four major diamond hubs (alongside Antwerp, Mumbai/Surat, Dubai). Israel Diamond Exchange (IDE/Bursa, Ramat Gan) operates the world's largest single diamond trading floor. Israel imports ~$5B/yr rough diamonds, exports ~$7-10B/yr polished — making it one of the top global polished-diamond exporters despite zero domestic production. ~50% of polished diamonds purchased in the USA (the world's largest diamond consumer market) come from Israel. ~20,000 directly employed; diamond exports have historically been ~12-30% of Israeli goods exports. UAE-Israel diamond trade ~tripled post-2020 Abraham Accords (Dubai Diamond Exchange synergy). STRATEGIC: Israeli polishing industry is G7-sanctions-aware (zero Russian-origin rough since March 2024). Watch: IDE monthly trading reports, MID House of Diamond exports, GJEPC India-Israel rough-polish flow, US Customs precious-stones import data from Israel."},
    },
    'iran': {
        'rice':         {'role': 'consumer',          'weight': 0.9,
                         'note': "Significant importer (domestic Caspian-province output covers part of demand); procurement is complicated by sanctions and FX access, with India (basmati) the historic key supplier paid partly via rupee/barter mechanisms. Rice sits with wheat in the subsidized, stability-sensitive staple basket. Watch: India-Iran basmati payment mechanisms, FX allocation for staple imports, Caspian harvest, subsidy policy."},
        'nitrogen':     {'role': 'producer', 'weight': 1.3,
                         'note': "Significant urea / ammonia exporter on the back of cheap subsidized gas (Pardis, Kermanshah, Lordegan petrochemical complexes). Sanctioned but flows continue via discounted regional + Asian buyers. HORMUZ / GAS LINK: Iranian nitrogen exports transit the Gulf; South Pars gas (shared with Qatar) is the feedstock. Watch: Iranian petrochemical urea export volumes, sanctions-evasion routing, South Pars output."},
        'sulfur':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'regime_flags': ['cascade_exposure_active'],
                         'note': "Iran is a major Gulf sulfur producer (sulfur is a refining + sour-gas-processing by-product); production trapped onshore by Hormuz closure + sanctions evasion complications. The Iran 2026 war + Hormuz closure is the upstream chokepoint for the global sulfur cascade. Watch: Iranian refinery + South Pars sour-gas output, Bandar Abbas + Imam Khomeini Port sulfur stockpiles."},
        'oil':          {'role': 'sanctions_target',  'weight': 1.5, 'rank': 1,
                         'note': "🚨 ACTIVE WAR ZONE (March 2026): Kharg Island oil terminal struck March 14 2026; Iran's primary export terminal degraded. Pre-war: ~3.4M bpd production, ~1.5M bpd exports (largely to Chinese teapot refiners via sanctioned-tanker shadow fleet). Post-Kharg: exports severely curtailed. STRATEGIC HORMUZ POSITION: Iran controls northern Hormuz coast — has demonstrated mining capability (1980s + recent threats 2024-2026). Watch: Iranian crude export tanker tracking (TankerTrackers, Kpler), Kharg Island reconstruction status, US Treasury OFAC Iran-targeted SDN list expansions."},
        'natural_gas':  {'role': 'producer',          'weight': 1.2,
                         'note': "World's #3 natural gas reserves; South Pars (shared with Qatar North Field) is the world's largest single gas field. Domestic consumption dominant; LNG export development blocked by sanctions. STRATEGIC: Iran has the gas to be a major LNG exporter but cannot monetize at scale due to sanctions + war. Russian-Iran-axis cooperation on gas-condensate processing growing."},
        'uranium':      {'role': 'producer',          'weight': 0.7,
                         'note': "Iranian uranium enrichment program (Natanz + Fordow) is the canonical nuclear-proliferation flashpoint. Production capacity exists but UN/IAEA sanctions framework precludes commercial export. Watch: IAEA monthly enrichment-level reports, Natanz/Fordow site activity."},
        'wheat':        {'role': 'consumer',          'weight': 1.1,
                         'note': "Major wheat importer (~5-7 Mt/yr); Russia + EU primary suppliers. Bread subsidies (Tehran-bakery network) politically central. War + sanctions = compounded import-financing difficulty."},
        'gold':         {'role': 'producer',          'weight': 0.9,
                         'regime_flags': ['sanctions_evasion_active'],
                         'note': "Iran has used GOLD-FOR-OIL settlement extensively as US-dollar-sanctions workaround. Tehran Bourse gold trading + Iranian central bank (CBI) gold reserves opaque. Iran-China + Iran-Russia + Iran-Turkey gold flow tracked via UAE intermediary refiners. Sanctions-evasion architecture canonical case study. Watch: UAE gold import data from Iran, Tehran Bourse gold-coin premium, CBI reserve disclosures (rare)."},
    },
    'japan': {
        'silicon':      {'role': 'producer', 'weight': 1.2,
                         'note': "WAFER CHOKEPOINT: Shin-Etsu + SUMCO together make ~50%+ of the world's finished silicon wafers -- the step between polysilicon and chips. Mitsubishi Chemical is the only meaningful synthetic high-purity-quartz backstop to Spruce Pine (and costlier). Producer at the highest-value link of the chain."},
        'lithium':      {'role': 'consumer',          'weight': 1.0,
                         'note': "World #3 lithium consumer; Panasonic (Tesla 4680 cells + ENERGY Storage); battery materials + electrolyte + separator IP dominant globally (Toray, Sumitomo Chemical, Asahi Kasei). Toyota's solid-state battery push raises specialty lithium demand. ~95% imported (Australia + Chile primary)."},
        'cobalt':       {'role': 'consumer',          'weight': 1.0,
                         'note': "Major cobalt consumer for battery cathode + specialty alloy industry; Sumitomo Metal Mining + Panasonic + Toyota Tsusho. Sumitomo Metal Mining's Pomalaa nickel project (Indonesia) + Madagascar Ambatovy mine vertically integrate cobalt access. Watch: Sumitomo Metal Mining (TSE:5713) earnings, Indonesian HPAL output."},
        'nickel':       {'role': 'consumer',          'weight': 1.0,
                         'note': "Major nickel consumer (~150K tonnes/yr); stainless steel + EV battery cathode; Sumitomo Metal Mining + Nippon Yakin Kogyo. Sumitomo's Sulawesi (Indonesia) nickel mining + Madagascar Ambatovy operations. Class-1 battery-grade nickel from Indonesia HPAL is critical for Japanese EV battery industry."},
        'semiconductors': {'role': 'producer',        'weight': 1.4, 'rank': 3,
                         'note': "World #3 semiconductor producer with critical equipment + materials dominance. Tokyo Electron (TEL) #2 globally for fab equipment after Applied Materials; Screen Holdings + Advantest dominant in cleaning/test. JSR + Shin-Etsu + SUMCO control ~60-70% of high-purity silicon wafers and EUV photoresist. TSMC Kumamoto fab (JASM) operational since 2024 — Japan's reshoring linchpin. Rapidus (Hokkaido) targeting 2nm by 2027 with IBM/imec partnership. Chip4 alliance member; G7 export-control coordinator. Watch: Rapidus milestones, TEL/SEH earnings, METI semiconductor subsidy announcements."},
        'oil':          {'role': 'consumer',          'weight': 1.3,
                         'note': '~99% oil imported; Middle East dependency (~90% from Gulf); Hormuz exposure; strategic petroleum reserve ~240 days (largest IEA-mandate stockpile). ENEOS + Idemitsu refineries.'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.3,
                         'note': 'World #2 LNG importer (post-Fukushima nuclear shutdown); ~95% imported. Australia + Qatar + Malaysia + USA primary suppliers; Sakhalin-2 (Russia) sanctions-complicated. LNG vulnerability central to Japan-US alliance energy security framing.'},
        'rare_earths':  {'role': 'consumer',          'weight': 1.3,
                         'note': 'Major REE consumer for electronics + magnets + EVs. 2010 China export embargo (Senkaku dispute) catalyzed Lynas Australia partnership and recycling/substitution R&D. Still ~60% China-dependent for heavy rare earths. JOGMEC strategic stockpile.'},
        'wheat':        {'role': 'consumer',          'weight': 1.0,
                         'note': '~90% imported, primarily US + Canada + Australia; managed via MAFF state trading; food security strategy.'},
        'uranium':      {'role': 'consumer',          'weight': 1.0,
                         'note': '100% uranium imported; nuclear restart program post-Fukushima; Australia + Kazakhstan primary suppliers; TEPCO + Kansai Electric major buyers.'},
    },
    'jordan': {
        'potash':       {'role': 'producer',          'weight': 1.3, 'rank': 4,
                         'regime_flags': ['belt_and_road_anchor'],
                         'note': "World's #8 potash producer (~2.5 Mt/yr); Arab Potash Company (APC, Amman Stock Exchange) operates the ONLY potash production in the Arab World — Dead Sea solar evaporation extraction at Safi/Ghor al-Mazra'a. BELT-AND-ROAD ANCHOR: China's State Development and Investment Group (SDIC) is APC's LARGEST shareholder since 2017 (~28% stake acquired for ~$500M). China is APC's #1 export market AND Jordan's #2 trade partner ($5.8B bilateral 2023). Jordan-China Belt-and-Road MOU signed for joint infrastructure; Arab-Chinese Cooperation Forum (June 2026) is the upcoming strategic milestone. STRATEGIC ANALYTICAL ANGLE: Jordan-potash is structurally identical to DRC-cobalt and Guinea-bauxite — Chinese state capital acquires controlling stake in a developing country's flagship resource company in exchange for Belt-and-Road infrastructure. Same playbook, different commodity. Watch: APC quarterly production data, SDIC Jordan presence, Aqaba port potash loadout, Arab-Chinese Cooperation Forum outcomes."},
        'phosphate':    {'role': 'producer',          'weight': 1.1, 'rank': 5,
                         'note': "World's #5 phosphate producer (~10 Mt/yr); Jordan Phosphate Mines Company (JPMC, Amman) operates Eshidiya + El-Abiad mines. Aqaba port export terminal. Less geographically critical than Moroccan phosphate but materially supplies India + Indonesia + Southeast Asia. JPMC has Chinese + Indonesian joint-venture downstream phosphate-processing investments. Watch: JPMC quarterly output, Aqaba phosphate shipments, India-Jordan tender results."},
        'oil':          {'role': 'consumer',          'weight': 1.1,
                         'note': "~95% oil imported; Iraq strategic pipeline talks ongoing (Basra-Aqaba pipeline FID delayed multiple times due to security + financing). Currently sources from Saudi Arabia + Iraq + UAE. Aqaba refinery + Zarqa refinery operate. Jordan Petroleum Refinery Co (JPRC). Bread-fuel-water subsidies are King Abdullah's three-pillar stability lever."},
        'wheat':        {'role': 'consumer',          'weight': 1.2,
                         'note': "~95% wheat imported (~1.0-1.2 Mt/yr); Russia + Romania + Ukraine + Australia + USA primary suppliers. Bread subsidy program (similar to Egyptian baladi) is politically critical — King Abdullah's reform efforts to reduce bread subsidy have repeatedly triggered protests (2018, 2023). Strategic Wheat Reserve maintained at ~6 months by Ministry of Industry, Trade and Supply. Watch: Jordan Grain Co tender results, Aqaba grain arrival data."},
    },
    'lebanon': {
        # ── Consumer side (acute import dependency) ──
        'wheat':        {'role': 'consumer',          'weight': 1.5,
                         'note': 'Critical import dependency: ~60-67% of wheat from Ukraine alone, ~80-90% combined Black Sea (UA+RU). National wheat reserves ~1 month — never rebuilt after 2020 Beirut port explosion destroyed national grain silos. 2022 Ukraine war caused immediate rationing and price spike. Active humanitarian crisis (1M+ displaced, 1.24M IPC Phase 3+ projected through Aug 2026) compounds wheat-import vulnerability — any Black Sea disruption is materially worse during humanitarian crisis. Watch: Black Sea grain corridor status, Russian wheat export taxes, Lebanese Mills Association statements.'},
        'oil':          {'role': 'consumer',          'weight': 1.3,
                         'note': 'Zero domestic refining capacity since post-2020 economic collapse; ~100% reliant on refined fuel imports (diesel/gasoline) for power generation, transport, and household generators. National grid produces only ~3-6 hours/day; private generators run the country. Fuel subsidy collapse (2021) means import disruption translates immediately to street-level cost-of-living crisis.'},
        'natural_gas':  {'role': 'consumer',          'weight': 0.9,
                         'note': 'Power generation increasingly LNG-dependent; offshore Mediterranean exploration (Block 8/9, Qana field) ongoing under TotalEnergies/ENI/QatarEnergy consortium following 2022 US-brokered maritime border agreement with Israel — no commercial finds confirmed yet, but represents long-term upside if Qana proves productive. Currently 100% importer despite aspirational producer status.'},
        'corn':         {'role': 'consumer',          'weight': 0.8,
                         'note': 'Animal feed import dependency mirrors Israel + Egypt patterns; livestock + poultry sector cost-driver; Black Sea corridor (Ukraine + Russia) primary source. Compounds wheat vulnerability — Lebanese household food costs amplified at every link of food supply chain.'},
    },
    'kazakhstan': {
        'uranium':      {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "🥇 World's #1 uranium producer (~43% global, ~21,000 tonnes U/yr). KAZATOMPROM (state-controlled, KASE-listed) is the world's largest uranium mining company. ISR (in-situ recovery) mining dominant — lower cost than Australian/Canadian conventional. Major supplier to France (Orano), USA, China (CGNPC + CNNC), Japan, India, EU. Strategic balancing actor between Russian + Chinese + Western nuclear-fuel customers. Watch: Kazatomprom production guidance, IAEA inspection reports, Russia-Kazakhstan uranium-transit-via-Russia disruption potential."},
        'wheat':        {'role': 'producer',          'weight': 1.1,
                         'note': "Major wheat exporter (~10-15 Mt/yr export); Northern Kazakhstan steppe agriculture. Central Asian wheat-staple supplier (Tajikistan + Afghanistan + Uzbekistan dependent). Russia + China trade routes."},
        'oil':          {'role': 'producer',          'weight': 1.2,
                         'note': "~1.8-2.0M bpd; Tengiz (Chevron-operated, TCO consortium) + Kashagan (NCOC consortium) + Karachaganak primary fields. CPC pipeline (Tengiz-Novorossiysk) exports through Russian Black Sea — vulnerability point. KazMunaiGas state firm. Watch: CPC pipeline operational status, Tengiz expansion (FGP) progress."},
        'natural_gas':  {'role': 'producer',          'weight': 0.9,
                         'note': "Major associated-gas + Karachaganak gas-condensate output; Central Asia pipeline network supplies China. Strategic Central Asia gas-corridor actor."},
        'silver':       {'role': 'producer',          'weight': 0.8,
                         'note': "Significant silver producer (by-product of polymetallic mining); Kazzinc + Kazakhmys + KAZ Minerals primary operators."},
        'chromium':     {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 chromium producer (~15-18% global). Eurasian Resources Group (ERG) operates Donskoy GOK (Aktyubinsk Oblast) — one of the world's largest chrome ore mines. Vertically integrated into Kazchrome ferrochrome smelters (Aksu + Aktobe). KAZAKHSTAN-CHINA RAILWAY route exports significant volumes to Chinese stainless-steel sector. ERG is privately held (post-2013 ENRC delisting); financial transparency limited. Watch: ERG Donskoy output, Kazchrome smelter operational rates, Kazakhstan-China cross-border rail throughput."},
    },
    'libya': {
        'natural_gas':  {'role': 'producer', 'weight': 0.7, 'data_as_of': '2026-06',
                         'note': "Gas exporter to Italy via the Greenstream pipeline (Mellitah); output hostage to political fragmentation + field security. Watch: NOC stability, Greenstream flows."},
        'oil':          {'role': 'producer',          'weight': 1.2,
                         'note': "OPEC member with ~1.2M bpd capacity when stable, but output is chronically disrupted by the East-West institutional split (NOC / Tripoli versus LNA / Haftar-controlled eastern fields and terminals). Recurring blockades and force-majeure declarations at El Sharara (largest field) and El Feel, plus the eastern-crescent terminals (Es Sider, Ras Lanuf, Zueitina, Brega), make Libyan supply one of the most disruption-prone signals in the oil complex — a textbook conflict-to-supply-shock convergence pattern. Light sweet Es Sider crude competes with Mediterranean and West African grades into Europe. CONVERGENCE LINK: Libyan production-halt announcements have historically preceded short-cycle Brent risk-premium moves and frequently track the LNA / GNU political cycle rather than market fundamentals. Watch: NOC force-majeure notices, El Sharara / Es Sider status, LNA-NOC revenue-distribution disputes, eastern-terminal loadings (Kpler / tanker tracking)."},
    },
    'malaysia': {
        'semiconductors': {'role': 'producer',           'weight': 1.3, 'rank': 3,
                         'note': "Penang -- the 'Silicon Valley of the East' -- is a global center of gravity for semiconductor back-end (assembly, packaging, test), handling on the order of ~13% of the world's chip packaging (Intel, AMD, Infineon, Bosch). Malaysia owns the back-end of the chip chain the way Taiwan owns the front-end. Watch: Penang capex, US-China packaging-tariff spillover, flood/grid disruption to the cluster."},
        'rare_earths':  {'role': 'processor',          'weight': 1.1,
                         'note': "Lynas Malaysia (Kuantan) is the only commercial-scale rare-earth separation plant outside China -- ~13-15% of ex-China oxide capacity (~8,500-9,000 t/yr), processing Australian Mt Weld concentrate and serving as the West's main alternative for heavy REEs (dysprosium, terbium). Its March 2026 license renewal carries a hard condition: the radioactive cracking-and-leaching front end must leave Kuantan for Kalgoorlie (WA) by 2031, while Malaysia keeps the high-value separation/refining. Watch: WLP-residue compliance, 2031 relocation progress, NdPr ramp toward 12,000 t/yr."},
        'silicon':      {'role': 'producer',           'weight': 1.0,
                         'note': "Major non-China polysilicon: OCI's Malaysian plant (the former Tokuyama Bintulu site) supplies solar- and electronic-grade polysilicon prized precisely because it sits outside Xinjiang -- the 'UFLPA-clean' feedstock that U.S. and European solar buyers seek. Sarawak hydropower-fed. Watch: OCI Malaysia expansion, U.S. solar polysilicon sourcing rules."},
        'natural_gas':  {'role': 'producer',           'weight': 1.1,
                         'note': "Petronas's Bintulu LNG complex (Sarawak) makes Malaysia one of the world's larger LNG exporters, supplying Japan, Korea, China, and Taiwan. State champion Petronas underwrites a large share of federal revenue. Watch: Petronas LNG cargoes, Sarawak gas-rights friction with the federal government."},
        'oil':          {'role': 'producer',           'weight': 0.9,
                         'note': "Petronas-operated offshore crude (Malay, Sarawak, and Sabah basins) plus the Pengerang refining/petrochemical complex; a modest but steady regional producer. Oil and gas rents are central to the federal budget and to Petronas's outsized national role."},
    },
    'mexico': {
        'gold':         {'role': 'producer', 'weight': 0.8, 'data_as_of': '2026-06',
                         'note': "Top-10 gold producer (Sonora, Zacatecas; often silver-coupled) -- Newmont Penasquito a major operation. New mining-law restrictions (concessions, water) cloud the outlook. Watch: 2023+ mining-law implementation, Penasquito labor."},
        'silver':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': 'World #1 silver producer (~6,120 MT, ~22% global); Zacatecas/Durango/Chihuahua; Fresnillo (largest primary silver mine); Peñoles/Fresnillo PLC dominant; ancient mining tradition'},
        'oil':          {'role': 'producer',          'weight': 0.9,
                         'note': "World's #11-12 oil producer (~1.9M bpd); Pemex state monopoly (heavy debt burden ~$100B+); Cantarell + Ku-Maloob-Zaap legacy fields declining; Sheinbaum administration (2024-) energy nationalist stance. Heavy crude exports to USA + Spain + India. Watch: Pemex debt sustainability, Cantarell production decline, US-Mexico USMCA energy provisions."},
        'corn':         {'role': 'consumer',          'weight': 1.0,
                         'note': "World's #5 corn consumer (~45 Mt/yr); largest individual-country corn importer (~17 Mt/yr from USA via USMCA); white-corn for tortillas politically sensitive (AMLO/Sheinbaum GMO restriction → US trade dispute). Animal feed + tortilla industry dual demand. Watch: USMCA agriculture dispute outcomes, peso USD exchange rate."},
        'copper':       {'role': 'consumer',          'weight': 0.7,
                         'note': "Major Latin American manufacturing hub (Northern Mexico maquiladoras + automotive + electronics); USMCA supply chain integration with USA. Net copper importer despite minor domestic production at Buenavista (Grupo México). Tesla Monterrey + new EV manufacturing builds out copper demand."},
        'sugar':        {'role': 'producer',          'weight': 1.1,
                         'note': "🌾 Mexico sugar producer ~5.1 MMT/yr (2025/26 forecast, ~50% of which exports to USA via USMCA-privileged quota). Veracruz + Jalisco + San Luis Potosí dominant cane regions. Sheinbaum administration energy/water policy intersects with sugar — drought + cane water allocation politics. The US-Mexico sugar dispute (recurring AD/CVD investigations + suspension agreements since 2014) is the canonical case study in managed trade. Mexico is the SINGLE LARGEST source of US sugar imports under USMCA. Watch: CONADESUCA harvest reports, USMCA sugar dispute filings, peso USD exchange rate (affects competitiveness vs Brazil)."},
    },
    'morocco': {
        'phosphate':    {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "🥇 World's #1 phosphate producer AND ~70% of global proven reserves — the most geographically concentrated fertilizer input on Earth. OCP Group (Office Chérifien des Phosphates, Moroccan state-owned, sovereign-controlled) is the planetary spigot for phosphate trade and the largest single supplier of phosphate fertilizers (DAP/MAP/TSP). Operations: Khouribga + Gantour + Youssoufia (Morocco proper) + Bou Craa via Phosboucraa subsidiary (Western Sahara). Downstream processing at Jorf Lasfar + Safi (Atlantic coast). NOTE ON SOVEREIGNTY: Western Sahara political status remains contested under UN MINURSO mandate; certain EU court rulings (most recently 2024) have held that contracts requiring Western Sahara provenance be treated separately from Moroccan-proper sourcing. The platform reports OCP combined output under Morocco as the operating entity, mirroring US State Department neutral posture, while noting source-provenance distinctions some buyers (notably the EU under specific rulings) apply. CASCADE EXPOSURE: phosphate processing into DAP/MAP requires sulfuric acid — Hormuz sulfur cascade flows directly into Moroccan phosphate prices and OCP margins. Watch: OCP quarterly results, Moroccan-EU phosphate dispute rulings, Bou Craa output disclosures (or absence thereof), India + Brazil DAP tender results, China DAP/MAP export-tax announcements."},
        'natural_gas':  {'role': 'consumer',          'weight': 0.7,
                         'note': "Morocco is a net importer; Algeria GME pipeline closed October 2021 over diplomatic dispute (Western Sahara recognition). Spanish LNG re-export via reversed-flow GME pipeline + new LNG terminal at Jorf Lasfar under construction. Strategic energy-security pivot away from Algerian dependency. Watch: Jorf Lasfar LNG terminal commissioning, Algeria-Morocco GME pipeline status."},
        'gold':         {'role': 'consumer',          'weight': 0.5,
                         'note': "Modest gold consumer (jewelry + private holdings); Bank Al-Maghrib gold reserves ~22 tonnes. Not a major producer or pricing-mover but worth tracking for North African MENA gold-flow context."},
    },
    'netherlands': {
        'oil':          {'role': 'transit', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Rotterdam (ARA hub) is Europe's largest oil port + refining/storage/blending complex and the #2 destination for US crude exports (~10% in 2024) -- a pure transit/processing chokepoint for European product flows. Watch: ARA refining margins, Russian-product import bans, US crude arbitrage."},
        'natural_gas':  {'role': 'transit', 'weight': 0.9, 'data_as_of': '2026-06',
                         'note': "TTF -- the European gas benchmark -- is Dutch; Rotterdam Gate LNG is a key import gateway. Groningen production has ended, flipping the Netherlands from producer to transit/trading hub. Watch: TTF spreads, Gate LNG throughput."},
        'semiconductors': {'role': 'producer',        'weight': 1.5, 'rank': 4,
                         'note': "Holds the single most concentrated leverage point in semiconductor manufacturing: ASML's EUV lithography monopoly. ASML (Veldhoven) is the only company in the world that produces extreme ultraviolet lithography systems required for sub-7nm chip manufacturing — meaning every leading-edge fab on Earth (TSMC, Samsung, Intel, SK Hynix) depends on ASML. Dutch government export-control decisions on EUV (and increasingly DUV) shipments to China constitute the most consequential single-country technology policy in the world. Also home to NXP (automotive chips). Watch: ASML quarterly bookings, Dutch trade ministry export-license announcements, EU Chips Act milestones."},
    },
    'norway': {
        'natural_gas':  {'role': 'producer',           'weight': 1.5, 'rank': 1,
                         'note': "Since 2022 Norway is the EU's single largest natural-gas supplier -- ~30% of EU gas (~109-122 bcm/yr), having replaced Russia's Gazprom -- delivered mostly through ~8,800 km of subsea pipelines, with Equinor marketing about two-thirds. The flip side is acute physical exposure: the remote offshore pipeline grid is a hard-to-attribute sabotage target (post-Nord Stream). Watch: Equinor maintenance/outage notices (they move European TTF within minutes), subsea-infrastructure security incidents."},
        'oil':          {'role': 'producer',           'weight': 1.2,
                         'note': "Western Europe's largest oil producer (~2 mb/d, ~2% of global supply); Equinor-operated North Sea fields anchored by Johan Sverdrup, the region's largest. Crude and gas together are ~57% of Norway's export value. A stable, Western-aligned barrel feeding the Government Pension Fund Global."},
        'silicon':      {'role': 'producer',           'weight': 1.0,
                         'note': "Dual silicon role: Elkem is a major silicon-metal and silicones producer on cheap hydropower, and The Quartz Corp's Drag operation (northern Norway) is one of only two large-scale high-purity-quartz sources on Earth alongside Spruce Pine, NC -- the crucible feedstock the entire wafer industry depends on. A quiet Western chokepoint backstop."},
        'rare_earths':  {'role': 'producer',           'weight': 0.6,
                         'note': "EMERGING: the Fen Complex (Telemark) is described as Europe's largest rare-earth deposit, under development by Rare Earths Norway as a potential non-China REE source for European magnets. Pre-production; the weight reflects strategic potential, not current output. Watch: Fen financing and permitting milestones."},
        'nickel':       {'role': 'consumer',           'weight': 0.6,
                         'note': "Glencore's Nikkelverk refinery (Kristiansand) is one of the world's largest nickel/cobalt/copper refineries -- a processing node turning imported matte into high-purity class-1 nickel and cobalt for European battery and alloy supply. Exposure is to matte feed and energy, not mining."},
    },
    'nigeria': {
        'rice':         {'role': 'consumer',          'weight': 1.0,
                         'note': "Large consumer and importer pursuing an aggressive (and porous) domestic self-sufficiency push; the 2019-2020 land-border closure aimed at curbing smuggled rice spiked domestic prices. Food security is a live stability variable. Watch: CBN FX-access policy for rice imports, border-policy shifts, paddy output (Kebbi/Anchor Borrowers Programme), local milled-rice prices."},
        'oil':          {'role': 'producer',          'weight': 1.3, 'rank': 9,
                         'note': "Africa's #1 oil producer (~1.4-1.7M bpd, well below ~2.5M bpd capacity due to theft + pipeline sabotage). OPEC member; Bonny Light + Forcados light sweet grades historically competitive with Brent. NNPC (Nigerian National Petroleum Co) state operator + Shell + Chevron + ExxonMobil + TotalEnergies + Eni majors. STRUCTURAL LOSSES: ~250-400k bpd lost to oil theft/illegal bunkering in Niger Delta — among highest theft rates globally. Tinubu administration (2023-) fuel subsidy removal + naira devaluation reshaped domestic oil economics. Dangote Refinery (Lekki, 650k bpd, world's largest single-train) operational from 2024 — transforms West Africa from gasoline-importer to potential exporter. Watch: NNPC monthly stats, Dangote utilization rates, Niger Delta militia activity, Tinubu fuel-subsidy politics."},
        'natural_gas':  {'role': 'producer',          'weight': 1.1,
                         'note': "Africa's #1 LNG exporter; Nigeria LNG (NLNG) Bonny Island plant operates 6 trains (~22 MMTPA capacity), Train 7 under construction (~30 MMTPA total). Eni + Shell + TotalEnergies + NNPC ownership. Major EU + India + Japan + South Korea supplier. Trans-Saharan Gas Pipeline Nigeria-Niger-Algeria-Europe revived as discussion item post-Ukraine war. Watch: NLNG Train 7 commissioning, Niger Delta gas-flaring data, EU LNG tender results."},
        'gold':         {'role': 'producer',          'weight': 0.4,
                         'note': "Modest gold producer (~1 tonne/yr formal sector); large artisanal sector (Zamfara state in particular) operates outside Kimberley-style traceability. Bandit-controlled gold mining in Zamfara/Kaduna funds insecurity in Nigeria's northwest. Watch: CBN gold-reserves disclosures, Zamfara security operations, artisanal mining concession reform."},
            'gum_arabic':   {'role': 'producer',          'weight': 0.8,
                         'note': "Alternate-supplier tier (with Chad) behind Sudan's ~70-80% dominance -- Nigerian gum (Borno/Yobe belt) gains structural weight precisely when Sudan's war chokes the primary channel, though the producing belt overlaps Boko Haram/ISWAP territory. Watch: export-volume responses to Sudan disruptions, northeast security radius around the gum belt."},
},
    'panama': {
        'oil':          {'role': 'transit',           'weight': 1.2,
                         'note': "Panama Canal transit: ~6% of global seaborne trade by value, ~3% of crude oil + significant LNG, soybean, corn, copper concentrate flow. 2023-25 drought reduced daily transit slots from ~36 to ~24, raising auction prices to record ~$4M per slot. Trans-Panama Pipeline (Petroterminal) bypasses canal for crude. Watch: Gatun Lake water levels, ACP slot auctions, Trump-era canal sovereignty rhetoric (Mulino administration response)."},
        'soybeans':     {'role': 'transit',           'weight': 1.1,
                         'note': "Major Panama Canal transit chokepoint for US-China + South American agricultural commodity flow. Brazilian + US soy headed to China increasingly diverts via Cape of Good Hope when canal slots tighten. Drought-driven slot reduction is structural global agri-cost variable."},
        'corn':         {'role': 'transit',           'weight': 0.9,
                         'note': "Panama Canal transit for US Midwest corn exports to Asia. Drought + slot auction pricing affects WASDE-tracked freight differentials. Mississippi River → Gulf → Panama Canal → Asia is the canonical US corn export route."},
        'copper':       {'role': 'producer',          'weight': 0.8,
                         'note': "Cobre Panamá (First Quantum Minerals, FQM) was Panama's only major copper mine and ~1.5% of global supply at peak — closed November 2023 by Supreme Court ruling after massive nationwide protests over contract terms. Mulino administration (2024-) seeking restart pathway. Mine closure removed ~350K tonnes/yr from global market — structural copper price variable. Watch: Cobre Panama restart negotiations, FQM (TSE:FM) earnings."},
        'natural_gas':  {'role': 'transit',           'weight': 1.0,
                         'note': "Panama Canal LNG transit: USA Gulf LNG carriers transit to Asia (~9% of global LNG flow at canal capacity). Ever-tightening slot auctions during drought directly affect JKM-Henry Hub spread. Cape of Good Hope reroute adds 14-18 days transit + freight costs."},
    },
    'peru': {
        'gold':         {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Top-7 global gold producer (Yanacocha, Cajamarca) plus a large illegal-mining sector in Madre de Dios. Watch: illegal-mining crackdowns, social-license conflicts."},
        'natural_gas':  {'role': 'producer', 'weight': 0.6, 'data_as_of': '2026-06',
                         'note': "Camisea gas (Cusco) + Peru LNG (Pampa Melchorita) -- a modest Pacific LNG exporter, mostly domestic/regional."},
        'silver':       {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': 'World #3 silver producer; Andean polymetallic mining'},
        'copper':       {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 copper producer (~12% global, ~2.4M tonnes/yr); Antamina (BHP+Glencore+Teck+Mitsubishi), Cerro Verde (Freeport), Las Bambas (MMG/Chinese), Antapaccay (Glencore). Political risk: Castillo impeachment (Dec 2022) + Boluarte unrest + ongoing community protests vs Chinese-operated Las Bambas. Strategic alternative to Chilean copper concentration."},
        'fishmeal':     {'role': 'producer',          'weight': 1.1, 'rank': 1, 'data_as_of': '2026-07',
                         'note': "\U0001F947 World's largest fishmeal exporter -- the Peruvian anchoveta (Humboldt Current) is the planet's biggest single-species fishery and the top global input to aquaculture + animal feed. FOOD-SECURITY frame, NOT fertilizer: when IMARPE biomass surveys trigger a season CANCELLATION (as in the 2023 first-season closure), global fishmeal prices spike and protein-feed costs ripple into farmed-salmon/poultry/aquaculture worldwide. This is the trackable leading indicator behind the viral 'guano collapse' framing -- the real signal is the quota, filed under food/feed, not the birds. Watch: IMARPE anchoveta biomass surveys, PRODUCE quota announcements/cancellations, El Nino warm-water anomalies, fishing-fleet protests. See also Chile (same Humboldt anchoveta fishery, secondary scale) when built."},
    },
    'philippines': {
        'semiconductors': {'role': 'component_producer', 'weight': 1.1,
                         'note': "Long-established assembly, test, and packaging (OSAT) hub - semiconductors and electronics are the country's top merchandise export (Laguna, Cavite, Clark corridors). Like Vietnam, exposure is downstream component/assembly rather than leading-edge fabrication, and it is a beneficiary of China+1 diversification. Watch: SEIPI export figures, US/Japan/Taiwan OSAT capacity additions, CHIPS-adjacent investment announcements."},
        'rice':         {'role': 'consumer',          'weight': 1.2,
                         'note': "Among the world's largest rice importers; food security is acutely political. The 2019 Rice Tariffication Law shifted from an NFA import monopoly to private tariff-based imports, with Vietnam the dominant supplier; the Marcos administration imposed retail price ceilings in 2023 amid spikes. Watch: import volumes from Vietnam/Thailand, retail price ceilings, NFA buffer stock, tariff-rate adjustments."},
        'nickel':       {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 nickel producer (~12% global); Nickel Asia + Global Ferronickel + Dinapigue Mining. Surigao + Palawan mines. Philippines-Indonesia together = ~60% global nickel. Marcos Jr. administration considering Indonesian-style export ban for downstream processing investment. Watch: DENR mining-policy announcements, Nickel Asia (NAC.PS) earnings, Marcos Jr. industry plans."},
    },
    'poland': {
        'silver':       {'role': 'producer', 'weight': 1.2, 'rank': 2, 'data_as_of': '2026-07',
                         'note': "Top-tier global silver producer via KGHM Polska Miedz -- one of the world's largest silver miners (Glogow/Lubin copper-silver ores), routinely #1-2 in refined silver output alongside Mexico. Silver is dual-natured: industrial (photovoltaics, electronics) + monetary hedge, so Polish output matters to both cycles. STABILITY LINK: KGHM is state-controlled and a fiscal pillar; strikes or energy-cost shocks at Polish smelters move global silver supply. Watch: KGHM production reports, Polish energy prices (smelting cost base), zloty moves, EU industrial-policy shifts."},
        'copper':       {'role': 'producer', 'weight': 0.8, 'data_as_of': '2026-07',
                         'note': "KGHM is Europe's largest copper producer (~top-10 global) from the Legnica-Glogow belt, plus international assets (Sierra Gorda, Chile). Copper is the electrification bellwether, and Poland is the EU's only major primary producer -- strategic weight in EU critical-raw-materials autonomy debates. Watch: KGHM output/strikes, EU CRMA sourcing rules, energy costs."},
        'wheat':        {'role': 'transit', 'weight': 0.9, 'data_as_of': '2026-07',
                         'note': "FLOW, NOT STOCK: Poland is the primary overland corridor for Ukrainian grain (rail transshipment + Baltic ports Gdansk/Gdynia) since Black Sea disruption -- and the epicenter of the EU-Ukraine grain-glut political conflict (farmer blockades, import bans, border protests). A Polish border closure is a food-corridor event with Ukraine-solidarity and EU-cohesion spillovers. STABILITY LINK: farmer protests are a live domestic-politics pressure valve. Watch: border-crossing status (Dorohusk/Medyka), Polish farmer-union actions, EU import-quota decisions, Baltic port grain volumes."},
    },
    'russia': {
        'wheat':        {'role': 'producer', 'weight': 1.5, 'rank': 1, 'data_as_of': '2026-06',
                         'note': "World's #1 wheat EXPORTER (~45M t in 2024-25); Black Sea (Novorossiysk) the gateway. Russian export taxes/quotas + Black Sea security move global wheat directly. Watch: export-quota/tax changes, Black Sea shipping risk, harvest size."},
        'corn':         {'role': 'producer', 'weight': 0.7, 'data_as_of': '2026-06',
                         'note': "Secondary Black Sea grain exporter; southern Russia. Part of the same export complex as wheat, smaller volume."},
        'iron_ore':     {'role': 'producer', 'weight': 0.7, 'data_as_of': '2026-06',
                         'note': "~6th-largest producer (~86 Mt 2025; Belgorod -- Lebedinsky + Stoilensky GOKs). Exports collapsed post-2022 under EU import bans; now feeds domestic steel + redirected flows."},
        'coal':         {'role': 'producer', 'weight': 0.9, 'data_as_of': '2026-06',
                         'note': "~5th-6th coal producer/exporter (~4.6% of global); sanctions rerouted volumes from Europe to China/India at discounts. Watch: Pacific-port rail capacity, discount to benchmark."},
        'sunflower_oil': {'role': 'producer', 'weight': 1.2, 'data_as_of': '2026-06',
                         'note': "Now rivals/leads Ukraine as the top sunflower-oil exporter; southern Russia crush + Black Sea ports. A major edible-oil supply swing alongside the war."},
        'silicon':      {'role': 'producer', 'weight': 0.9,
                         'note': "Major ferrosilicon producer -- historically ~37% of U.S. ferrosilicon imports before sanctions rerouted volumes toward China and Asia. RusAl / Bratsk complex. Sanctions exposure makes Russian silicon flow a swing variable for Western steel + aluminum feedstock."},
        'nitrogen':     {'role': 'producer', 'weight': 1.5, 'rank': 1,
                         'note': "World's #1 nitrogen-fertilizer exporter (urea, ammonia, ammonium nitrate); cheap domestic gas = structural cost advantage. EuroChem, Acron, Uralchem, Togliattiazot. CHOKEPOINT: the Togliatti-Odesa ammonia pipeline + Yuzhny / Black Sea terminals (war-disrupted) are a recurring grain-deal bargaining chip. Sanctions carve-outs explicitly protect food + fertilizer flows. Watch: Black Sea ammonia corridor status, EU sanctions-exemption debates, export tax / quota changes."},
        'oil':          {'role': 'producer',          'weight': 1.5, 'rank': 2,
                         'note': "World's #2 oil producer (~10-11M bpd); Urals crude (medium sour) historic European staple. Post-2022 sanctions + G7 price cap ($60/bbl Russian crude): exports redirected to China + India + Türkiye via shadow fleet (~600+ tankers). Discount-to-Brent (Urals-Brent spread) is the live measure of sanctions effectiveness. Rosneft + Lukoil + Gazprom Neft majors. Druzhba pipeline transit to EU (Hungary/Slovakia carve-outs). Watch: Urals-Brent spread, shadow fleet tracking (S&P Platts, Kpler), refinery utilization in India/China for Russian crude."},
        'natural_gas':  {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 natural gas reserves; ~70% of pre-war EU pipeline gas + LNG dependency materially severed by 2022-2024 REPowerEU pivot. Yamal LNG (Novatek) still flowing despite sanctions via Asian + EU + LNG-aware Western buyers; Sakhalin-2 sanctioned-but-operational. Power of Siberia (China) + Power of Siberia 2 (negotiated since 2014, partial agreement 2024) realign Russian gas eastward. Gazprom domestic + export operator. Watch: Yamal LNG cargo tracking, Power of Siberia volumes, EU LNG-import-from-Russia status."},
        'potash':       {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 potash producer (~17% global); Uralkali (sanctions-affected) + Eurochem operations in Perm Krai. Major Brazilian + Chinese supplier. Sanctions disrupted European customer flows; redirected to BRICS + Belt-and-Road customers."},
        'uranium':      {'role': 'producer',          'weight': 1.2, 'rank': 4,
                         'note': "World's #4 uranium producer + #1 enrichment provider (~40% global SWU capacity via Rosatom). USA banned Russian-enriched uranium imports May 2024 (with waivers through 2027) — major US nuclear-fuel transition challenge. Rosatom also constructs reactors globally (Hungary Paks II, Egypt El Dabaa, Turkey Akkuyu, India Kudankulam, Bangladesh Rooppur). Watch: Rosatom contract progression, US Rosatom-replacement HALEU progress."},
        'gold':         {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "World's #3 gold producer (~310 tonnes/yr); Polyus + Polymetal majors. Sanctions disrupted London Bullion Market access — Russian gold redirects to UAE refiners + BRICS markets. Central Bank of Russia gold reserves significant component of de-dollarization strategy."},
        'cobalt':       {'role': 'producer',          'weight': 0.5,
                         'note': "Norilsk Nickel cobalt by-product; modest globally but adds to non-Chinese non-DRC supply diversification narrative for Russian-aligned customers."},
        'nickel':       {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "World's #3 nickel producer; Norilsk Nickel (Nornickel) operates Norilsk + Kola peninsula deposits. Class-1 battery-grade nickel + palladium primary. Sanctions exposure limited because Western buyers struggle to replace high-purity Russian Class-1 nickel + palladium feedstock. Watch: Nornickel (MCX:GMKN) operational disclosures, EU sanctions extension on Russian nickel."},
        'silver':       {'role': 'producer',          'weight': 0.7,
                         'note': "Polymetal + Polyus silver production; Russian + Kazakhstan polymetallic operations."},
        'pgm':          {'role': 'producer',          'weight': 1.4, 'rank': 2,
                         'note': "World's #2 PGM producer + the planetary palladium SWING producer — Norilsk Nickel (Nornickel) is the world's largest single palladium producer (~40% of global supply) and a major platinum + rhodium producer. Norilsk + Kola Peninsula geology unique. STRATEGIC: Western alternatives to Russian palladium are minimal — Stillwater Montana + North American Palladium together cover <10% of global supply. Russian palladium has remained largely un-sanctioned despite Ukraine war because Western auto + semiconductor industries depend on it. Sanctions exposure managed via LBMA Good Delivery listing decisions. Watch: Nornickel (MCX:GMKN) production, LBMA Russian-refiner listing status, US automotive palladium-substitution efforts."},
        'phosphate':    {'role': 'producer',          'weight': 1.2, 'rank': 4,
                         'note': "World's #4 phosphate producer; PhosAgro (MCX:PHOR) operates Kola Peninsula mines (Khibiny, Kovdor) + Volkhov + Cherepovets DAP/MAP processing. Russia is ~10-12% global phosphate output. SANCTIONS: PhosAgro is one of the few major Russian commodity exporters that has remained largely unsanctioned (G7 specifically carved out fertilizers to avoid global-south famine consequences). Belarus + Russia + Morocco combined effectively control global non-Chinese phosphate supply. Watch: PhosAgro production, EU fertilizer sanctions framework, US-Russia fertilizer trade flows."},
        'diamonds':     {'role': 'sanctions_target',  'weight': 1.4, 'rank': 2,
                         'regime_flags': ['sanctions_evasion_active'],
                         'note': "World's #2 rough diamond producer + historically #1 by volume (Alrosa, MCX:ALRS); Mirny + Udachny + Aikhal + Nyurba mines (Sakha Republic/Yakutia). Pre-2022: Russia was the world's largest rough diamond exporter at ~$3.8B/yr by value. G7 SANCTIONS REGIME (Jan 1 2024 onward): direct ban + third-country routing ban (March 1 2024) materially disrupt Alrosa's primary export markets. Belgian customs seized millions in suspected Russian-origin stones Feb 2024 — proof bypass active. SANCTIONS EVASION ARCHITECTURE: Russian rough increasingly routes via UAE (DMCC) + India (Surat cutters) + Hong Kong for re-export as 'mixed-origin' polished. The G7 Botswana certification node + EU Antwerp node are designed to break this routing. Watch: Alrosa quarterly stockpile reports, UAE diamond import data, Belgian Federal Police seizure announcements, GJEPC India Russian-rough boycott compliance."},
        'bauxite':      {'role': 'producer',          'weight': 0.7,
                         'note': "Russia produces ~5-6 Mt/yr bauxite (Severouralsk + North Onega operations, Rusal-controlled) — domestic aluminum smelter feed plus partial export. Insufficient for Rusal's needs; complement with Guinea + Jamaica imports. Sanctions complicate Rusal's Guinean operations financing. Watch: Rusal (MCX:RUAL) production, Guinea bauxite-to-Russia flow."},
    },
    'qatar': {
        'nitrogen':     {'role': 'producer', 'weight': 1.2,
                         'note': "Gulf ammonia / urea producer (QAFCO at Mesaieed -- among the world's largest single urea sites), gas-based off the North Field. Hormuz transit exposure on exports. Watch: QAFCO output + expansion, North Field gas allocation, Asia / India urea contract flows."},
        'natural_gas':  {'role': 'producer',         'weight': 1.5, 'rank': 1,
                         'note': "World's #2 LNG exporter (~80 MMT/yr, behind USA briefly); North Field (shared with Iran's South Pars) is the world's largest single gas field. QatarEnergy state operator; ConocoPhillips + ExxonMobil + Shell + TotalEnergies + Eni JV partners. North Field Expansion (NFE) program brings capacity to 142 MMTPA by 2027. Strategic supplier to EU (post-Ukraine) + Asia. Watch: NFE construction milestones, Qatar-EU long-term contract signings, North Field operational status."},
        'sulfur':       {'role': 'producer',          'weight': 1.4,
                         'regime_flags': ['cascade_exposure_active'],
                         'note': "Qatar is a major Gulf sulfur producer (sour-gas processing by-product at North Field + Ras Laffan); ~5 Mt/yr exports. Hormuz closure exposure: Qatar's gas + sulfur exports transit the Strait. Cascade chain: Hormuz closure → Gulf sulfur trapped → Chinese + Indonesian + Chilean copper/nickel/phosphate processing disruption."},
        'oil':          {'role': 'producer',          'weight': 0.7,
                         'note': "Condensate + NGL heavyweight (~0.6M bpd condensate off North Field gas streams) rather than a crude major. Qatar LEFT OPEC in Jan 2019 -- an early tell of the gas-first strategy and independence from Saudi-led quota politics. All liquids transit Hormuz. Watch: condensate export volumes, QatarEnergy liquids guidance, any OPEC-relations signaling."},
        'wheat':        {'role': 'consumer',          'weight': 0.7,
                         'note': "Near-total food import dependence -- and the 2017-2021 GCC blockade is the defining precedent: Saudi/UAE/Bahrain closure of Qatar's only land border forced a food-security revolution (airlifted dairy herds, Baladna, strategic reserves, Iran/Turkey supply corridors). Food-supply signals double as GCC-cohesion signals. Watch: strategic-reserve announcements, Hamad Port food-corridor volumes, any land-border friction with KSA."},
    },
    'saudi_arabia': {
        'phosphate':    {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "Ma'aden (Wa'ad Al Shamal, Al Jalamid) has made Saudi a top-tier phosphate-fertilizer EXPORTER (DAP/MAP) within a decade -- vertically integrated with domestic rock + ammonia + sulfur, a rising challenger to Morocco's OCP. Watch: Ma'aden Phosphate 3 ramp, DAP tenders."},
        'sulfur':       {'role': 'producer', 'weight': 1.2, 'data_as_of': '2026-06',
                         'note': "Massive sulfur producer as an oil/gas-processing byproduct (Aramco); feeds its own phosphate chain plus global export -- a structural sulfur source. Watch: Aramco gas-program sulfur output, phosphate self-consumption."},
        'rice':         {'role': 'consumer',          'weight': 0.9,
                         'note': "Near-100% import-dependent (negligible domestic production); rice is a dietary staple sourced heavily as Indian/Pakistani basmati, with strategic food reserves held via SAGO/GFSA. Highly exposed to any Indian export restriction. Watch: SAGO procurement tenders, India basmati export-policy, strategic reserve levels, Red Sea shipping disruptions affecting import routes."},
        'oil':          {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 oil exporter, #2 producer (~10M bpd). Saudi Aramco (largest IPO in history, 2019) is the world's most profitable company. Ghawar field + Khurais + Safaniya operations. OPEC+ swing producer — Saudi Aramco production decisions + voluntary cut announcements move global oil prices materially. Strategic Saudi-Russia coordination via OPEC+ central. HORMUZ BYPASS: East-West Petroline (~5M bpd capacity) to Yanbu on the Red Sea is the kingdom's strategic escape valve -- and the anchor of the west-west-west posture (Red Sea pipelines + rail toward Turkey) and the IMEC corridor, positioning KSA as the counter-BRI hub. PRECEDENT: Abqaiq/Khurais drone-missile attack (Sep 2019) briefly halved Saudi output -- the single-point-vulnerability benchmark. Watch: Saudi Aramco production guidance, OPEC+ ministerials, voluntary-cut extensions, Petroline/Yanbu throughput expansion, IMEC milestone announcements."},
        'natural_gas':  {'role': 'producer',          'weight': 0.9,
                         'note': 'Jafurah unconventional field (largest in ME); Master Gas System; primarily domestic power + petrochemicals'},
        'gold':         {'role': 'consumer',          'weight': 0.9,
                         'note': 'SAMA central bank reserves; significant retail demand; Vision 2030 mineral resources strategy'},
        'wheat':        {'role': 'consumer',          'weight': 1.0,
                         'note': "Major wheat importer (~3.5 Mt/yr, ~85% imported); SAGO (Saudi Grains Organization) state procurement; bread subsidies for ~36M population (citizens + expat workforce); domestic wheat phased out 2016 due to water scarcity. Russian + Australian + Canadian primary suppliers. Watch: SAGO tender results, Vision 2030 food security strategy, Red Sea shipping (Houthi BAM attacks)."},
    },
    'south_africa': {
        'iron_ore':     {'role': 'producer', 'weight': 0.8, 'data_as_of': '2026-06',
                         'note': "Kumba Iron Ore (Anglo American; Sishen/Kolomela) -- a notable seaborne supplier via the Saldanha rail-port line. Watch: Transnet rail performance, China demand."},
        'pgm':          {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "🥇 World's #1 platinum producer (~70% of global supply) and #2 palladium producer (~40% global, behind Russia). Bushveld Complex (Limpopo + North West provinces) is THE planetary spigot for PGMs — geologic concentration unmatched anywhere on Earth. Operators: Anglo American Platinum (Amplats), Impala Platinum (Implats), Sibanye-Stillwater, Northam, Lonmin (historical, post-Marikana). Eskom load-shedding is the existential operational risk — PGM mining + smelting are electricity-intensive; SA grid instability has materially impacted output 2022-2025. CRITICAL FOR: autocatalysts (gasoline+diesel), hydrogen fuel cells (PEM electrolyzers), semiconductor catalysts, jewelry. Strategic Western alternative supply is minimal — Stillwater Montana + North American Palladium together cover <10%. Watch: Amplats/Implats/Sibanye-Stillwater earnings, Eskom load-shedding stages, Marikana memorial-anniversary labor actions."},
        'chromium':     {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "🥇 World's #1 chromium producer (~70% global). Bushveld Complex Lower Group seams. Chrome ore + ferrochrome industry hollowed out since 2010 by Chinese electricity-cost arbitrage — SA chrome ore now largely exported raw to China for smelting. Glencore + Tharisa + Samancor Chrome major operators. Eskom load-shedding kills SA ferrochrome smelting profitability. Critical for stainless steel (no substitute). Watch: SA ferrochrome industry capacity, Tharisa output, Glencore SA chrome segment results, Eskom load-shedding."},
        'manganese':    {'role': 'producer',          'weight': 1.4, 'rank': 1,
                         'note': "🥇 World's #1 manganese producer (~36% global). Kalahari Manganese Field (Northern Cape) is the largest land-based manganese resource. South32 (Hotazel JV), Tshipi Borwa, Wessels, Mamatwan operations. Critical for both steel (90% of demand) AND rapidly-growing EV battery cathode market (LFP + NMC manganese-rich chemistries). High-purity manganese sulfate (HPMSM, battery-grade) is ~95% Chinese-processed regardless of where the ore originates. Watch: South32 manganese segment results, Northern Cape rail logistics (Sishen-Saldanha + Port Elizabeth)."},
        'gold':         {'role': 'producer',          'weight': 1.0,
                         'note': "Historic gold dominance (Witwatersrand was once the world's #1 gold-producing region) but production has declined ~85% since 1970 peak as accessible reefs depleted and mining costs escalated. Currently ~90-100 tonnes/yr (~10th globally), behind Ghana as Africa's leader since 2018. AngloGold Ashanti (now Denver HQ post-2023 redomicile), Gold Fields, Harmony Gold + Sibanye-Stillwater operate. Witwatersrand reefs remain world's largest historical resource. Watch: AngloGold/Gold Fields production guidance, deep-level mining safety incidents."},
        'diamonds':     {'role': 'producer',          'weight': 0.9,
                         'note': "Historic diamond producer (Kimberley, Cullinan); De Beers' original geographic base — Anglo American + De Beers still operate Venetia (Limpopo) + Voorspoed mines. Modern production secondary to Botswana but historically + symbolically central. Sale of De Beers (Anglo American divestment, $4.9B valuation) materially affects SA mining sector future."},
        'coal':         {'role': 'producer',          'weight': 1.1,
                         'note': "World's #6-7 coal producer (~230 Mt/yr); Mpumalanga coalfields. Eskom-dependency domestically; Richards Bay Coal Terminal exports to India + Pakistan + Europe. Just-Energy-Transition Partnership (JETP) committed by G7 + Germany ($8.5B) for SA coal-phaseout pathway, but progress contested. Watch: Eskom load-shedding stages, Transnet rail performance to RBCT, JETP implementation milestones."},
        'oil':          {'role': 'consumer',          'weight': 0.9,
                         'note': "~70% imported; Saudi Arabia + Nigeria + Angola primary suppliers. Sasol synthetic-fuel (coal-to-liquid Secunda + Sasolburg) covers ~25-30% of domestic liquid fuels — unique strategic asset. Refining sector contracted significantly 2020-2024 (multiple refinery shutdowns: Engen Durban, Sapref). Watch: Sasol earnings, refinery utilization, fuel-import volumes."},
    },
    'south_korea': {
        'silicon':      {'role': 'consumer', 'weight': 1.2,
                         'note': "Dual role: OCI is a major polysilicon producer, while Samsung + SK Hynix fabs make Korea one of the largest silicon demand sinks on Earth. Exposure runs both up (polysilicon supply) and down (advanced-node demand for wafers + HPQ crucibles)."},
        'lithium':      {'role': 'consumer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 lithium consumer; LG Energy Solution + Samsung SDI + SK On are the world's #2 battery cell manufacturing trio (combined ~20-25% global EV battery market share). Heavy supplier of cells to Western automakers (Hyundai, Kia, GM, Ford, VW). ~95% imported lithium hydroxide + carbonate. Watch: Korean battery cell production data, LG ES (KS:373220) earnings, IRA Section 30D compliance."},
        'cobalt':       {'role': 'consumer',          'weight': 1.2, 'rank': 2,
                         'note': "World's #2 cobalt consumer; NMC battery chemistry cobalt-heavy; LG Chem + POSCO Future M cathode manufacturing dominant. Vertical integration via Indonesia HPAL JVs (POSCO + Sumitomo + Tsingshan) + DRC investments. Korean cathode tech exports to Western automakers fundamental to non-China battery supply chain."},
        'nickel':       {'role': 'consumer',          'weight': 0.9,
                         'note': "Major nickel consumer; stainless steel (POSCO) + EV battery cathode; Indonesian HPAL nickel critical for class-1 battery-grade material. POSCO + Posco-CNGR JV + LG-Huayou nickel sulfate facilities."},
        'semiconductors': {'role': 'producer',        'weight': 1.5, 'rank': 2,
                         'note': 'World #2 semiconductor producer; Samsung Electronics (memory leadership: ~40% DRAM, ~35% NAND globally; foundry #2 chasing TSMC) + SK Hynix (HBM dominance ~50%, critical for AI accelerators). Pyeongtaek megafab + Hwaseong campus. Also operates fabs in Wuxi/Xi\'an China — caught between US export controls and Chinese market access. Chip4 alliance member.'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': 'World #3 LNG importer; KOGAS imports primarily from Qatar/Australia/USA; near-total import dependency for energy; Hormuz/Suez chokepoint exposure'},
        'oil':          {'role': 'consumer',          'weight': 1.2,
                         'note': '~99% imported; Middle East dependency; SK Energy + GS Caltex refineries; major refined product exporter'},
        'uranium':      {'role': 'consumer',          'weight': 0.9,
                         'note': 'Major nuclear power user (~26 reactors, ~30% of electricity); KEPCO domestic build + UAE Barakah export contract; nuclear fuel imports'},
            'graphite':     {'role': 'consumer',          'weight': 1.0,
                         'note': "Anode-manufacturing heavyweight (POSCO Future M) with deep exposure to Chinese spherical-graphite permits -- Seoul's battery chain is the canary for Beijing's graphite-control enforcement. Watch: POSCO Future M sourcing announcements, Korea-China permit friction, IRA-compliant sourcing shifts."},
},
    'taiwan': {
        'silicon':      {'role': 'consumer', 'weight': 1.5, 'rank': 1,
                         'note': "Demand center of gravity: TSMC's fabs consume the wafers, HPQ crucibles, and polysilicon-derived silicon at the leading edge -- the strategic prize of the entire chain. Cross-strait disruption transmits directly to global chip + silicon-feedstock supply."},
        'semiconductors': {'role': 'producer',        'weight': 1.5, 'rank': 1,
                         'note': "🥇 World's #1 semiconductor producer; TSMC (Hsinchu + Tainan + Kaohsiung megafabs) holds ~55% global foundry market share + ~90%+ leading-edge (3nm/5nm) production. UMC + Vanguard secondary foundries. TSMC Arizona (US) + Kumamoto (Japan) + Dresden (Germany) overseas fabs come online 2024-2026 but Taiwan retains structural concentration. SILICON SHIELD doctrine: Taiwan's semiconductor concentration is its primary deterrent against Chinese kinetic action. Watch: TSMC quarterly results, capex guidance, overseas-fab capacity additions, US export-controls Entity List China chip-design firm additions."},
        'oil':          {'role': 'consumer',          'weight': 1.2,
                         'note': '~99% imported; CPC Corp Taiwan; Hormuz exposure; strategic stockpile ~90 days'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': 'World #6 LNG importer; CPC + private utilities; Qatar + Australia + USA primary'},
        'wheat':        {'role': 'consumer',          'weight': 0.8,
                         'note': '~95% imported; Taiwan Flour Mills Association procurement; USA primary supplier'},
        'corn':         {'role': 'consumer',          'weight': 0.7,
                         'note': 'Animal feed import dependency'},
        'rare_earths':  {'role': 'consumer',          'weight': 1.0,
                         'note': 'Critical for TSMC + UMC semiconductor manufacturing chain; permanent magnets + EV demand'},
    },
    'thailand': {
        'rice':         {'role': 'producer',          'weight': 1.2, 'rank': 2,
                         'note': "Perennial top-three rice exporter; Hom Mali jasmine is the premium signature grade. Competitiveness is sensitive to baht strength (vs India/Vietnam) and to central-plains drought/El Nino. Like Vietnam, gains share whenever India restricts exports. Watch: Thai Rice Exporters Association quotes, baht moves, reservoir/drought levels, jasmine premium vs Vietnamese fragrant rice."},
        'sugar':        {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "🌾 World #2 sugar exporter (~7-8 MMT/yr export, ~10 MMT total production 2024/25). Central + Northeast Thailand cane regions. Mitr Phol + Thai Roong Ruang Sugar + Khon Kaen Sugar major mill operators. Indonesia + China + South Korea + Japan + Philippines + Bangladesh primary import customers. Thailand's sugar exports are the structural marginal global supply variable alongside Brazil — when Indian exports tighten (sub-consumer-floor regime), Thai availability becomes the global supply backstop. CANE-WATER REGIME: ~70% of Thai cane is rain-fed; El Niño + La Niña cycles directly affect annual output volatility. Watch: Office of the Cane and Sugar Board (OCSB) reports, monsoon rainfall, Mitr Phol export quotas, USDA FAS Thailand sugar reports."},
        'natural_gas':  {'role': 'consumer',          'weight': 0.9,
                         'note': 'Major LNG importer; PTT Energy domestic gas + LNG imports; power generation primary use'},
        'rare_earths':  {'role': 'consumer',          'weight': 0.6,
                         'note': 'Growing rare earth processing (BSC Rare Earths, Thai-Lanthanide-China JV); strategic Southeast Asian processing investment'},
    },
    'turkey': {
        'wheat':        {'role': 'consumer',          'weight': 1.2,
                         'note': 'Major wheat importer (~6-7 Mt/yr); Russia + Ukraine + Romania primary; bread subsidies (Erdogan-era populism) politically sensitive'},
        'oil':          {'role': 'transit',           'weight': 1.0,
                         'note': "BTC pipeline (Baku-Tbilisi-Ceyhan) + Kurdistan-Turkey pipeline (closed 2023 over dispute) + Bosphorus tanker transit. Turkish straits = ~3M bpd Russian + Caspian crude transit chokepoint. Watch: Ceyhan terminal throughput, Bosphorus tanker queue, Iraq-Turkey pipeline restart negotiations."},
        'natural_gas':  {'role': 'transit',           'weight': 1.2,
                         'note': "TurkStream pipeline (Russian gas via Black Sea to Turkey + Southern Europe) + TANAP (Azeri SGC corridor) make Turkey EU's southeastern gas-supply gatekeeper. Strategic Erdogan position: balancing Russian sanctions compliance vs. cheap Russian gas. Watch: TurkStream flow data, BOTAS contract renewals, Caspian-EU SGC volumes."},
        'gold':         {'role': 'consumer',          'weight': 1.1,
                         'note': "Turkey is among the world's largest gold importers + jewelry-trading hubs. Istanbul Gold Refinery + Nadir Metal Refining + Turkish Mint operations. Turkish gold dealers facilitate Russian + Iranian + Venezuelan sanctions-evasion gold flows (UAE-Türkiye-Iran-Russia gold arbitrage). Lira-volatility = retail-demand variable. Watch: Borsa Istanbul gold trading volumes, CBRT gold-reserves disclosures, US Treasury 311 sanctions actions on Turkish dealers."},
        'chromium':     {'role': 'producer',          'weight': 1.0, 'rank': 3,
                         'note': "World's #3 chromium producer (~8-10% global). Eti Krom + Yıldırım Group operations in Elazig + Antalya. Turkey is both producer + exporter (raw ore + ferrochrome). Strategic Western-aligned supplier (NATO member) for chrome ore — alternative to South African + Kazakh routes. Watch: Eti Krom production, Yıldırım Group exports, Turkish stainless-steel sector demand."},
    },
    'turkmenistan': {
        'natural_gas':  {'role': 'producer',          'weight': 1.0,
                         'note': "Major Central Asia gas producer; Galkynysh field (world's #2 single gas field after South Pars/North Field). Almost entirely sold to China via Central Asia-China pipeline. Turkmengaz state operator. Strategic Chinese-Central-Asia dependency anchor."},
        'oil':          {'role': 'producer',          'weight': 0.5,
                         'note': 'Modest oil producer; sanctions-light status; opaque state-controlled economy'},
    },
    'uae': {
        'oil':          {'role': 'producer',          'weight': 1.4, 'rank': 6,
                         'note': "Major Gulf oil producer (~4M bpd); ADNOC (Abu Dhabi National Oil Company) operates onshore + offshore. OPEC member (departure rumored mid-2024-2025). Habshan-Fujairah pipeline allows partial bypass of Hormuz. Strategic balance vs. Saudi Arabia within OPEC+. Watch: ADNOC production guidance, Habshan-Fujairah throughput, ADNOC IPO actions."},
        'natural_gas':  {'role': 'producer',          'weight': 0.9,
                         'note': 'Major LNG exporter via Das Island (ADNOC LNG); shifting to net importer status during peak summer cooling demand'},
        'gold':         {'role': 'mediator',          'weight': 1.5, 'rank': 1,
                         'regime_flags': ['sanctions_evasion_active'],
                         'note': "DUBAI is the world's largest gold trading hub by physical-flow volume (~$100B+ annual physical gold trade). DMCC (Dubai Multi Commodities Centre) + Dubai Gold and Commodities Exchange operate. Strategic UAE position: ~40% of Russian gold post-2022 sanctions routes through Dubai refiners; substantial Venezuelan + Iranian + African artisanal gold flows. UAE is the canonical Mediator for global sanctions-affected gold — not because UAE makes policy, but because UAE infrastructure (refineries, banks, free zones) is the path of least resistance. Watch: UAE gold-import customs data, DMCC refiner registrations, FATF UAE inspections, OFAC actions on UAE intermediaries."},
        'wheat':        {'role': 'consumer',          'weight': 0.8,
                         'note': '~100% imported; Russia + Ukraine + Australia primary; Jebel Ali strategic stockpile'},
        'diamonds':     {'role': 'mediator',          'weight': 1.3, 'rank': 3,
                         'regime_flags': ['sanctions_evasion_active'],
                         'note': "🥇 DUBAI DIAMOND EXCHANGE (DDE) — the world's third-largest diamond trading hub behind Antwerp + Mumbai/Surat. ~$30-40B annual diamond trade through DMCC. STRATEGIC ROLE POST-G7-SANCTIONS: UAE has become the primary routing alternative for Russian-origin rough diamonds since March 2024 — Russian rough increasingly mixes with African + Indian-cut polished at DMCC for re-export as 'mixed-origin', complicating G7 enforcement. UAE-Israel diamond trade tripled post-2020 Abraham Accords (DMCC-IDE Ramat Gan partnership). Watch: DMCC monthly diamond trade volumes, UAE-Russia diamond customs data, US OFAC + EU sanctions enforcement actions on DMCC intermediaries."},
    },
    'ukraine': {
        'iron_ore':     {'role': 'producer', 'weight': 0.8, 'data_as_of': '2026-06',
                         'note': "Historically a top-5 iron-ore exporter (Kryvyi Rih); output + Black Sea export logistics constrained by the war. A swing European supply variable."},
        'wheat':        {'role': 'producer',          'weight': 1.3, 'rank': 5,
                         'note': "Pre-war: World's #5 wheat exporter (~25 Mt/yr export). Post-2022 war: production reduced ~30% + export logistics severely complicated. Black Sea Grain Initiative (2022-23, lapsed July 2023) + Ukraine Solidarity Lanes via Danube ports + Polish/Romanian rail backfill. Odesa + Mykolaiv ports under intermittent Russian attack. Compound Lebanon + Egypt + Yemen + Sub-Saharan Africa food-security implications. Watch: Ukrainian Agrarian Council reports, Odesa port operational status, Danube port (Reni, Izmail) throughput."},
        'corn':         {'role': 'producer',          'weight': 1.2, 'rank': 4,
                         'note': "Pre-war: World's #4 corn exporter (~25-30 Mt/yr); post-war: degraded but ongoing. EU + China + MENA + Sub-Saharan Africa primary destinations. Same Black Sea logistics constraints as wheat."},
        'sunflower_oil':{'role': 'producer',          'weight': 1.4, 'rank': 1,
                         'note': "World's #1 sunflower oil producer + exporter (~50% global pre-war); war degraded but partially restored. India + EU primary buyers. Major global cooking oil market mover."},
    },
    'usa': {
        'oil':          {'role': 'producer', 'weight': 1.5, 'rank': 1, 'data_as_of': '2026-06',
                         'note': "World's #1 crude producer -- record ~13.6 Mb/d in 2025 (~16% of global), Permian Basin the engine -- and the #1 petroleum exporter. SPR drawn down to ~349M bbl during the 2026 Iran conflict. Light-sweet shale; still imports heavy grades. Watch: Permian rig count, SPR levels, WTI vs ~$61-62 breakeven."},
        'corn':         {'role': 'producer', 'weight': 1.5, 'rank': 1, 'data_as_of': '2026-06',
                         'note': "World's #1 corn producer and exporter; the Midwest Corn Belt sets the global price. Mississippi -> Gulf -> Panama Canal is the canonical Asia export artery; ~1/3 of the crop goes to ethanol. Watch: USDA WASDE, Corn Belt drought, Gulf basis, China purchases."},
        'lithium':      {'role': 'consumer', 'weight': 0.8, 'data_as_of': '2026-06',
                         'note': "Import-reliant (>50%, mostly Chile) but building domestic supply (Thacker Pass NV, Salton Sea brine); a demand sink for EV/battery buildout still dependent on Chinese refining. Emerging producer."},
        'coal':         {'role': 'producer', 'weight': 1.0, 'data_as_of': '2026-06',
                         'note': "~#4 coal producer (~533M short tons in 2025, +4%); Powder River Basin + Appalachia. Shifted from declining domestic burn toward exports and reviving data-center power demand. Watch: export-terminal throughput, data-center load."},
        'silicon':      {'role': 'producer', 'weight': 1.4,
                         'note': "FEEDSTOCK CHOKEPOINT: Spruce Pine, NC (Sibelco/Unimin + The Quartz Corp) supplies ~80%+ of the world's ultra-high-purity quartz used to make the crucibles that melt silicon -- a single-point-of-failure exposed when Hurricane Helene idled it in 2024. Also a polysilicon producer (Hemlock) and the demand surge: CHIPS Act fabs (TSMC AZ, Intel, Micron). Silicon added to the 2025 U.S. Critical Minerals List. Watch: Spruce Pine operating status, Section 232 polysilicon action."},
        'nitrogen':     {'role': 'producer_consumer', 'weight': 1.3, 'rank': 3,
                         'note': "Major nitrogen producer AND consumer -- cheap shale gas underpins large domestic urea / ammonia / UAN output (CF Industries, Nutrien, Koch), yet the Corn Belt still imports to balance. Gulf Coast ammonia capacity is gas-price sensitive. Watch: CF Industries guidance, Henry Hub gas, Corn Belt application-season demand, tariff actions on imported UAN."},
        'semiconductors': {'role': 'producer',        'weight': 1.5, 'rank': 5,
                         'note': "US semiconductor sector ~10% global manufacturing but dominates leading-edge design (Nvidia, AMD, Qualcomm, Intel, Apple Silicon) + equipment (Applied Materials, Lam Research, KLA). CHIPS and Science Act ($52B, 2022) funds Intel Ohio + TSMC Arizona + Samsung Texas + Micron NY fab builds. Trump 2024-2026 administration tariff + national-security framework reshapes export-controls + tariffs on Chinese semi imports. Watch: CHIPS Act funding milestones, BIS Entity List Chinese chip-design firm additions, Intel Foundry + TSMC Arizona ramp."},
        'natural_gas':  {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "🥇 World's #1 natural gas producer + #1 LNG exporter (overtook Qatar 2022). Cheniere Energy + Sempra + Freeport + Cameron LNG + Venture Global operate Gulf Coast LNG terminals. Permian + Marcellus + Haynesville shale basins. Trump 2024-2026 administration paused new LNG export license approvals (since lifted). Strategic supplier to EU post-Ukraine. Watch: EIA weekly natural gas storage, US LNG export feedgas demand, FERC LNG project approvals."},
        'wheat':        {'role': 'producer',          'weight': 1.2,
                         'note': "World's #4 wheat producer (~50 Mt/yr); Kansas + North Dakota + Montana + Washington. Hard Red Winter + Hard Red Spring + Soft White export grades. USDA WASDE reports = global benchmark. Egypt + Indonesia + Mexico + Japan primary export destinations."},
        'soybeans':     {'role': 'producer',          'weight': 1.4, 'rank': 2,
                         'note': "World's #2 soybean producer (~110-115 Mt/yr); Illinois + Iowa + Indiana + Minnesota + Nebraska + Missouri dominant. China primary historical export destination (pre-2018 trade war ~60% of US exports went to China; now ~50%). USDA + CME futures benchmark. Watch: WASDE reports, US-China trade tariff status, Mississippi River barge logistics."},
        'gold':         {'role': 'producer',          'weight': 1.0,
                         'note': "World's #4-5 gold producer (~170 tonnes/yr); Nevada Carlin Trend (Newmont + Barrick JV NGM) + Alaska Pogo + Donlin operations. US Treasury Fort Knox + West Point + Denver Mint hold ~8,133 tonnes (world's largest sovereign reserves). Watch: Newmont (NEM) earnings, NGM operational data."},
        'silver':       {'role': 'producer',          'weight': 0.9,
                         'note': 'Major silver producer; Coeur Mining + Hecla Mining + Pan American Silver operations; Nevada + Idaho primary'},
        'copper':       {'role': 'consumer',          'weight': 1.0,
                         'note': "Major copper consumer; Freeport-McMoRan operates Arizona + New Mexico mines; Resolution Copper (Arizona) advancing through permitting. Net importer despite domestic production. Energy transition + grid modernization structural demand driver."},
        'rare_earths':  {'role': 'producer',          'weight': 0.9,
                         'note': "MP Materials Mountain Pass (California) is the only operating REE mine in the Western Hemisphere; processes ~15% of global REE. DoD investments + USA Rare Earth (Round Top, Texas) under development. Critical Minerals Mineral Security Partnership (MSP) framework anchors Western coordination."},
        'uranium':      {'role': 'consumer',          'weight': 1.3, 'rank': 1,
                         'note': "World's #1 uranium consumer (~94 nuclear reactors, ~20% of electricity). US Strategic Uranium Reserve (~1M lbs U3O8) modest. Domestic production minimal (<2% global); ~50% imports from Kazakhstan + Russia (until May 2024 ban + waivers) + Canada + Australia. Rosatom-substitution HALEU buildout via Centrus + URENCO USA. Watch: NEI quarterly reports, DOE LEU/HALEU procurement, Kazatomprom US contracts."},
        'sugar':        {'role': 'producer',          'weight': 1.0,
                         'note': "🌾 USA sugar producer ~8 MMT/yr (cane: Florida + Louisiana; beet: Minnesota + Idaho + ND + MI); largest individual-country sugar-beet consumer. USDA TRQ + price-support program + Mexico (USMCA quota) suspension agreement create unique managed-market regime. American Sugar Refining + ASR Group + Florida Crystals dominate. NOT a free market — US sugar prices structurally elevated above world price by program design. Watch: USDA WASDE Sugar tables, ITC Mexico-sugar reviews, US Sugar Program reauthorization."},
        'pgm':          {'role': 'producer',          'weight': 0.7,
                         'note': "Sibanye-Stillwater Stillwater + East Boulder mines (Montana) are the ONLY primary platinum + palladium producers in the USA. Critical-Minerals-List + Defense Production Act-eligible. Strategic Western alternative to Russian palladium + South African platinum but cover <10% of global supply combined. Watch: Sibanye-Stillwater (NYSE:SBSW) US segment results, DoD palladium-stockpile actions, US Geological Survey strategic-mineral assessments."},
        'phosphate':    {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "World's #3 phosphate producer (~22 Mt/yr); Mosaic + Nutrien operations in Florida (Central Florida phosphate district) + North Carolina (Aurora). USA is largely self-sufficient + modest exporter. Major DAP/MAP producer for domestic + Latin American + Asian markets. Florida phosphate-mining environmental compliance + radioactive byproduct (phosphogypsum) regulation are ongoing operational variables. Watch: Mosaic (NYSE:MOS) results, Nutrien Phosphate segment, USGS phosphate production reports."},
        'diamonds':     {'role': 'consumer',          'weight': 1.4, 'rank': 1,
                         'note': "🥇 World's #1 DIAMOND CONSUMER MARKET (~$26-30B annual retail diamond + diamond-jewelry sales, ~50% of global retail value). LAB-GROWN DIAMOND DISPLACEMENT: lab-grown share of US engagement-ring market climbed to ~50% by 2025 — the steepest natural-vs-synthetic substitution shift in jewelry history. Direct existential pressure on Botswana + Russian + Canadian rough producer economies. G7 SANCTIONS ENFORCEMENT: US implements the G7 Russian-diamond ban via OFAC + Customs/Border Protection; Belgian Antwerp cert node serves as primary verification path; secondary Botswana node coming online. Tiffany + Signet + Jared + retail jewelry sector primary commercial actors. Watch: Signet Jewelers (NYSE:SIG) earnings, GIA grading volume, lab-grown vs natural mix data, OFAC Russian-diamond seizure announcements."},
            'graphite':     {'role': 'consumer',          'weight': 1.1,
                         'note': "100% NET IMPORT RELIANT on natural graphite (USGS critical mineral) while building the largest ex-China anode demand base (EV/battery plants). IRA + DOE/DFC financing anchors the alternative chain: Syrah Vidalia (LA), Anovion, Novonix -- all priced against Chinese export-permit posture and Mozambican/Malagasy mine uptime. Watch: DOE loan actions, Section 301/tariff moves on Chinese anode material, domestic synthetic-graphite capacity milestones."},
},
    'venezuela': {
        'oil':          {'role': 'sanctions_target',  'weight': 1.5, 'rank': 1,
                         'note': "🚨 CRITICAL HEADLINE: Venezuela holds world's LARGEST proven oil reserves (~303 billion barrels per OPEC) — but ~95% is extra-heavy crude from Orinoco Belt, expensive to refine, requires specialized facilities (Gulf Coast US, China CNPC Maoming). Production collapsed from ~3.2M bpd (2008 peak) to ~700-900k bpd (2024) via mismanagement + sanctions + PDVSA brain drain. POST-MADURO TRANSITION (Jan 3 2026): US captured Maduro; Delcy Rodriguez interim govt; Trump quoted Apr 2026 'the oil is beginning to flow' — signaling US oil major re-entry under transactional alignment. Chevron OFAC license expansions expected. STRATEGIC ANALYTICAL QUESTION: Was the January 2026 US raid timed to secure Venezuelan crude redundancy ahead of potential Hormuz disruption? Watch: PDVSA monthly export volumes (Reuters/Bloomberg shipping data), Chevron + Repsol + ENI license expansions, Russian Rosneft cargo continuity post-Rodriguez, Chinese CNPC Maoming refinery feedstock mix, Jose terminal tanker traffic. [VERIFY: Peter's pushback noted — reserve QUALITY (Orinoco extra-heavy ~8.5° API) materially constrains how much of 303B 'proven' reserves are economically extractable at current price decks vs. Saudi/Permian light sweet]."},
        'natural_gas':  {'role': 'producer',          'weight': 0.6,
                         'note': "Venezuela has ~5.5 trillion cubic meters of natural gas reserves (world top-10) but historically flared 40-60% as associated gas with crude production — minimal LNG export infrastructure. Cardon IV offshore (Eni/Repsol) + Mariscal Sucre offshore projects historically stalled. Cross-border Caribbean Gas Pipeline to Trinidad/Tobago Atlantic LNG envisioned but blocked under Maduro sanctions. Rodriguez interim govt may revive — Trinidad's Dragon Field development depends on Venezuelan gas. Watch: Trinidad-Venezuela Dragon gas deal status, Eni Cardon IV restart signals, Chevron natural gas license additions."},
        'gold':         {'role': 'sanctions_target',  'weight': 1.3,
                         'note': "🥇 Venezuela's Orinoco Mining Arc (Arco Minero del Orinoco) — military-administered gold mining region with extensive ELN guerrilla involvement, Wagner/Russian operational presence reported (pre-Maduro-capture), illicit gold flows to UAE/Türkiye/Russia as sanctions evasion since 2017. BCV (central bank) sold ~73 tonnes of reserves 2014-2020 for hard currency. Under Rodriguez interim: status of mining concessions to Russia (Rusoro Mining lawsuits) + Iran (Comafi Bank gold transit) + Türkiye (Sardes Kiymetli Madenler) is the key signal for whether legacy adversary access continues or unwinds. Watch: BCV gold reserve disclosures, Orinoco mining concession announcements, UAE/Türkiye gold import flows from VE, US OFAC actions on VE gold."},
        'wheat':        {'role': 'consumer',          'weight': 0.8,
                         'note': "Venezuela imports ~90% of wheat consumption (~1.5-2 MMT/yr). Pre-crisis: Canada + US dominant; under Maduro-era sanctions, Russia + Argentina backfilled. Bread is subsidized + politically sensitive (food riots 2017-2019). Rodriguez interim govt has signaled openness to US food imports as part of broader normalization — watch USDA FAS Venezuela post for shifts in supplier mix."},
        'corn':         {'role': 'consumer',          'weight': 0.7,
                         'note': "Venezuela imports ~70% of corn consumption (white maize is national staple for arepas). Brazil + Argentina + Mexico primary suppliers. Local production collapsed alongside broader agricultural sector. Stability variable: arepas-without-corn is the canonical Caracas-protest-trigger pattern."},
    },
    'vietnam': {
        'semiconductors': {'role': 'component_producer', 'weight': 1.2, 'rank': 3,
                         'note': "Fast-rising assembly, test, and packaging (OSAT) hub - the leading 'China+1' beneficiary as electronics supply chains diversify out of China. Samsung's largest global smartphone-manufacturing base (Bac Ninh, Thai Nguyen); Intel's largest assembly-test site (Ho Chi Minh City); Amkor packaging (Bac Ninh); ongoing Apple-supplier migration. Vietnam fabricates little leading-edge silicon itself - its exposure is downstream component/assembly, structurally different from a Taiwan or Korea fab shock. National semiconductor strategy (2024) targets design + packaging scale-up. Watch: Samsung + Intel + Amkor capex, US-Vietnam semiconductor cooperation announcements, FDI inflow data, power-supply reliability (a real constraint on OSAT expansion)."},
        'rare_earths':  {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "Holds among the world's largest rare-earth reserves (US Geological Survey has ranked Vietnam #2 globally, ~22 million tonnes), but current mined output is tiny - the gap between reserves and production is the whole story. Positioned as the leading hoped-for non-China REE alternative; Vietnam-US, Vietnam-Japan (JOGMEC), and Vietnam-Korea processing/offtake deals are the signals to watch. Nui Phao (Masan) is the flagship mine-to-processing complex. Watch: REE processing-plant announcements, Western offtake/financing deals, export-policy signaling, China export-control moves (which raise Vietnam's strategic value)."},
        'oil':          {'role': 'producer',          'weight': 0.9,
                         'note': "Modest offshore producer via PetroVietnam (~200-300k bpd). Strategic salience is less volume than location: several producing and prospective blocks sit in or near waters contested by China's nine-dash-line claim. The Vanguard Bank area (Block 06-1, Nam Con Son basin) has seen repeated China Coast Guard / survey-vessel standoffs that pressured Vietnam to suspend operations. Watch: Vanguard Bank / Block 06-1 standoff reports, PetroVietnam partner activity (Rosneft, Zarubezhneft, legacy ExxonMobil), China survey-vessel incursions near Vietnamese blocks."},
        'natural_gas':  {'role': 'producer',          'weight': 0.8,
                         'note': "Offshore gas producer; the Block B - O Mon project (Phu Quoc basin) and the long-stalled Blue Whale / Ca Voi Xanh field (originally ExxonMobil) are the major developments. As with oil, some gas acreage sits in South China Sea waters subject to Chinese pressure, tying energy development directly to the maritime-sovereignty dispute. Watch: Block B - O Mon final-investment / first-gas milestones, Ca Voi Xanh operator status, China interference near gas blocks."},
        'rice':         {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "Among the world's top-three rice exporters (~7-8 MMT/yr), centered on the Mekong Delta. A direct beneficiary when India restricts exports - Vietnamese export prices spiked to multi-year highs during the 2023-24 India ban. Structural vulnerability: Mekong Delta salinity intrusion, upstream Chinese and Lao dam operations, and climate stress on the delta. Watch: Vietnam Food Association export-price quotes, Mekong Delta salinity/drought reports, India export-policy spillover, Philippines import tenders (Vietnam's largest customer)."},
        'coffee':       {'role': 'producer',          'weight': 1.1, 'rank': 2,
                         'note': "World's #2 coffee producer overall and the #1 robusta producer, concentrated in the Central Highlands (Dak Lak). A major export-earnings driver. Robusta prices hit record highs in 2024 on Vietnamese drought - Vietnamese weather is now a top global robusta price signal. Watch: Central Highlands rainfall/drought, VICOFA export figures, robusta-arabica spread, aging-tree replanting and productivity trends."},
    },

    # ────────────────────────────────────────────────────────────
    # AFRICA EXPANSION — Jul 18 2026 (Sahel gold belt, Sudan war
    # economy, Niger uranium, CAR mercenary-finance node, Mozambique
    # gas/graphite, Madagascar graphite/nickel)
    # ────────────────────────────────────────────────────────────
    'mali': {
        'gold':         {'role': 'producer',          'weight': 1.4,
                         'regime_flags': ['resource_nationalization_active'],
                         'note': "Africa's #2-3 gold producer (~65t/yr industrial + large artisanal), and ground zero of the continent's state-vs-miner confrontation. Junta seized ~3t of gold stock from Barrick's Loulo-Gounkoto complex (Jan 2025), jailed executives, and placed the mine -- ~14% of Barrick's global output -- under provisional state administration (2025); Barrick pursues ICSID arbitration. 2023 mining code raises state + local stakes to up to 35% and enabled sweeping back-tax campaigns (Resolute CEO detained Nov 2024, ~$160M settlement; B2Gold Fekola + Allied + Hummingbird renegotiated). Wagner/Africa Corps compensated partly via gold concessions and artisanal-site control (Intahaka). JNIM taxes artisanal production across contested zones -- gold funds the state, the Russians, AND the insurgency simultaneously. Watch: Loulo-Gounkoto output under state administration, Barrick arbitration milestones, new Africa Corps concession grants, junta back-tax targets."},
        'lithium':      {'role': 'producer',          'weight': 1.0,
                         'regime_flags': ['belt_and_road_anchor'],
                         'note': "Goulamina (Ganfeng Lithium, Chinese-controlled) shipped first spodumene concentrate Dec 2024 -- Mali's entry into the battery chain and a Belt-and-Road resource anchor mirroring Guinea's bauxite playbook. Bougouni (Kodal/Hainan JV) follows. Junta applies the same rising-state-stake mining code to lithium as to gold. Watch: Goulamina ramp volumes, Bamako-Ganfeng fiscal renegotiation signals, export routing via Senegal/Cote d'Ivoire corridors."},
    },

    'burkina_faso': {
        'gold':         {'role': 'producer',          'weight': 1.3,
                         'regime_flags': ['resource_nationalization_active'],
                         'note': "Africa's #4-5 gold producer (~55-60t/yr, declining with insecurity) under the continent's most aggressive resource-nationalist junta. Traore created state miner SOPAMIB (2024), which took over the Boungou + Wahgnion mines, and the 2024 mining code raises free-carried state interest with local-ownership mandates -- Western operators (Endeavour, IAMGOLD orbit) divesting while Russian-linked Nordgold stays. JNIM controls or contests wide territory and TAXES artisanal gold sites -- an estimated third of artisanal output is smuggled (Togo/UAE routes), making gold a shared revenue base of state, coup-proofing patronage, and insurgency alike. Watch: SOPAMIB portfolio expansion, further mine seizures/nationalizations, Nordgold footprint, artisanal-corridor interdictions."},
    },

    'niger': {
        'uranium':      {'role': 'producer',          'weight': 1.4, 'rank': 7,
                         'regime_flags': ['resource_nationalization_active'],
                         'note': "World #7 uranium producer (~4-5% of global output) and historically ~15-25% of EU supply -- the live case of resource nationalization as geopolitics. Post-coup junta blocked exports (2023), stripped Orano of operational control of SOMAIR (Dec 2024), then moved to NATIONALIZE it outright (Jun 2025); Orano pursues international arbitration while ~1,000+ tonnes of yellowcake sit stranded at Arlit. Imouraren mega-deposit permit revoked from Orano (Jun 2024); GoviEx Madaouela permit also revoked. Rosatom courtship ongoing; reporting has flagged Iranian interest in Nigerien uranium (unconfirmed, tracked as rumor-tier). France's fuel chain diversified to Kazakhstan/Canada but the EU-exposure precedent is set. Watch: SOMAIR arbitration, Arlit stockpile movements, Rosatom entry signals, any export-corridor reopening (Benin transit feud)."},
        'oil':          {'role': 'producer',          'weight': 0.9,
                         'regime_flags': ['belt_and_road_anchor'],
                         'note': "Small producer (~90-110k bpd target) whose significance is the PIPELINE: CNPC's Agadem project exports via the ~2,000km Niger-Benin pipeline (first liftings May 2024) -- pure Belt-and-Road petro-politics. Flow repeatedly interrupted by junta-Benin border feuding and rebel sabotage (Patriotic Liberation Front attacks); junta has detained/expelled Chinese oil executives in fiscal renegotiation pressure plays (2025). Watch: pipeline uptime, CNPC-Niamey friction, Benin transit politics, Agadem output guidance."},
    },

    'sudan': {
        'gold':         {'role': 'producer',          'weight': 1.3,
                         'regime_flags': ['conflict_finance_node'],
                         'note': "Africa's #3 gold producer (~64t official pre-war; true output far higher) and the FINANCING SPINE of Africa's largest war. RSF controls Darfur artisanal fields (Jebel Amer legacy) and smuggling exits; SAF controls Port Sudan refining and formal export channels -- gold bankrolls BOTH sides. An estimated 50-80% of production is smuggled, overwhelmingly to the UAE (Dubai refining hub), with documented Russian channels (Wagner-legacy Meroe Gold / M-Invest structures) tying Sudanese gold to Moscow's sanction-evasion economy -- and to the Port Sudan naval-base negotiation. Belgium-diamonds-class structural role: not a top-5 producer, but a top-tier conflict-finance and sanctions-evasion node. Watch: UAE gold import statistics, Port Sudan export policy shifts, RSF consolidation of Darfur fields, Russian refinery/concession signals."},
        'gum_arabic':   {'role': 'producer',          'weight': 1.2, 'rank': 1,
                         'regime_flags': ['conflict_finance_node'],
                         'note': "🥇 ~66-80% OF WORLD SUPPLY -- the most concentrated soft commodity on Earth, from the Kordofan/Darfur gum belt. Irreplaceable emulsifier (E414) for Coca-Cola, PepsiCo, confectionery, pharma; so strategically odd that US sanctions carved it out for decades. The war rerouted the trade into smuggling corridors (Chad, Egypt, South Sudan) with RSF taxation of the belt; buyers drew down strategic stockpiles in 2023-24 and the supply chain now prices Sudanese territorial control directly. Watch: export-corridor shifts, Kordofan front movements, buyer inventory disclosures, substitute-gum R&D announcements (the demand-destruction tail risk)."},
    },

    'car': {
        'gold':         {'role': 'producer',          'weight': 1.0,
                         'regime_flags': ['conflict_finance_node'],
                         'note': "Globally small producer whose significance is WHO it finances: the Ndassima mine (Wagner-linked Midas Ressources, assessed $1B+ in gold) is the material base of Russia's Africa Corps presence -- the concession-for-security model in its purest form. US Treasury has repeatedly designated Wagner-linked CAR entities. Artisanal production elsewhere feeds smuggling via Cameroon and the Sudan war economy's tri-border zone. Structural-role qualification (mercenary-finance node), not volume. Watch: Ndassima output/expansion signals, sanctions designations, concession transfers under the Wagner-to-Africa-Corps handover, Vakaga corridor traffic."},
        'diamonds':     {'role': 'producer',          'weight': 1.0,
                         'regime_flags': ['conflict_finance_node'],
                         'note': "THE live conflict-diamond case: under partial Kimberley Process embargo since 2013 (compliant 'green zones' only), with Wagner-linked Diamville (US-sanctioned) documented routing stones to the UAE. Smuggling via Cameroon and Sudan chains persists at scale. Like Belgium in reverse -- a certification-REGIME pressure point rather than a volume producer: what happens to CAR stones tests whether the KP means anything. Watch: KP review decisions on CAR zones, Diamville-successor entities, UAE rough-import anomalies, artisanal-zone control shifts."},
    },

    'mozambique': {
        'natural_gas':  {'role': 'producer',          'weight': 1.3,
                         'regime_flags': ['conflict_supply_coupling'],
                         'note': "Rovuma Basin holds ~100+ tcf -- a top-10 global gas endowment -- and the platform's TEXTBOOK conflict-commodity coupling. Eni's Coral Sul FLNG has exported since 2022 (insurgent-proof by being offshore) with Coral Norte advancing; TotalEnergies' $20B Mozambique LNG (Afungi) has sat under force majeure since the 2021 Palma attack, with restart preparation under Rwandan force protection -- every N380 corridor ambush reprices the timeline. ExxonMobil's larger Rovuma LNG train is sequenced behind Total's restart confidence. LNG receipts are the state's entire projected fiscal transformation, which makes the insurgency's implicit hostage-taking of the timeline a sovereign-credit variable. Watch: Total force-majeure status, Afungi-perimeter incidents, Coral Norte milestones, ExxonMobil FID signals."},
        'graphite':     {'role': 'producer',          'weight': 1.2, 'rank': 2,
                         'regime_flags': ['conflict_supply_coupling'],
                         'note': "🥈 World's #2 natural graphite producer, anchored by Balama (Syrah Resources) -- the largest natural graphite mine on Earth and the West's principal ex-China anode bet (Syrah's Vidalia LA plant, US DOE/DFC financing, Tesla offtake). Production is chronically interruptible: farmer-protest force majeure (Dec 2024), Cabo Delgado insurgency proximity, and post-election unrest have all halted output -- each stoppage tightens an anode chain China already gates with export permits. Watch: Balama uptime/restart declarations, Syrah offtake + US-support announcements, Nacala/Pemba logistics, protest cycles in Cabo Delgado province."},
        'coal':         {'role': 'producer',          'weight': 0.9,
                         'note': "Africa's leading coking-coal exporter via the Moatize complex (post-Vale ownership) and the Nacala rail corridor -- a metallurgical-coal supply thread to Indian and Asian steelmakers. Cyclone exposure and corridor unrest (2024-25 protest roadblocks) are the recurring disruption vectors. Watch: Nacala throughput, Moatize ownership/output guidance, coking-coal benchmark spreads."},
    },

    'madagascar': {
        'graphite':     {'role': 'producer',          'weight': 1.1,
                         'note': "Top-5 world natural graphite producer -- historic flake-graphite district plus the modern Molo mine (NextSource Materials, producing since 2023) feeding the ex-China anode chain. The Oct 2025 military transition adds permitting/political risk to an otherwise structural position: the Jan 2026 lifting of a 16-year mining-permit freeze signals a revenue-hungry transitional government reopening the sector. Watch: Molo ramp + offtakes, permit-regime decisions under the transition, Toamasina export logistics."},
        'nickel':       {'role': 'producer',          'weight': 0.9,
                         'note': "Ambatovy (Sumitomo-led) is one of the world's largest lateritic nickel-cobalt operations -- top-10-tier producer of class-1 nickel with cobalt byproduct feeding battery chains -- but chronically financially distressed (debt restructuring 2024) amid the Indonesian-supply nickel price collapse. A solvency failure would be a meaningful class-1 supply event AND a Malagasy fiscal/employment shock in an already fragile transition. Watch: Ambatovy solvency/output guidance, Sumitomo commitment signals, nickel-price threshold behavior."},
    },
}
# ============================================================================
# LEADER COMMODITY INTERVENTIONS — v1.0
# ============================================================================
# Detects verbal interventions ("jawboning") by senior officials about
# commodities — a price-moving signal class invisible to fundamentals trackers.
#
# Example: PM Modi's May 2026 call for Indians to stop buying gold for a year
# is not a gold supply/demand event — it's a defensive FX-pressure absorption
# signal. Bloomberg sees the price tick. We see the causal taxonomy.
#
# Architecture:
#   - KNOWN_SPEAKERS:                 name → {role, country, weight} lookup
#   - LEADER_INTERVENTION_KEYWORDS:   per-commodity trigger phrases (en/hi/ur)
#   - INTERVENTION_DIRECTION_LEXICON: phrase → direction enum
#   - INTERVENTION_RATIONALE_LEXICON: phrase → rationale enum
#
# Downstream consumers:
#   - get_commodity_pressure(target) injects 'leader_interventions' field
#   - india-stability.html / commodities.html render the panel
#   - Future: rhetoric trackers read 'leader_intervention' fingerprints to
#     classify offensive vs defensive statecraft (Feature B, backlog)
#
# Schema reserves 'classification_hint' + 'upstream_stressor_hint' fields for
# the future rhetoric-tracker interpretation layer (defensive statecraft
# attribution, butterfly-effect mapping to upstream theater stressors).
# ============================================================================

# ── KNOWN_SPEAKERS ───────────────────────────────────────────────────────────
# Senior officials whose statements move commodity markets. Add aliases freely.
# weight: 1.0 = standard; 1.3 = high-impact speaker (head of state of major
# economy, Fed/ECB/PBOC governor, OPEC SecGen-tier).
KNOWN_SPEAKERS = {
    # India
    'narendra modi':        {'role': 'head_of_state',         'country': 'india',     'weight': 1.3, 'aliases': ['pm modi', 'prime minister modi', 'modi ji']},
    'nirmala sitharaman':   {'role': 'finance_minister',      'country': 'india',     'weight': 1.2, 'aliases': ['sitharaman', 'finance minister sitharaman']},
    'shaktikanta das':      {'role': 'central_bank_governor', 'country': 'india',     'weight': 1.2, 'aliases': ['rbi governor', 'governor das']},
    'piyush goyal':         {'role': 'trade_minister',        'country': 'india',     'weight': 1.0, 'aliases': ['goyal']},
    'hardeep puri':         {'role': 'energy_minister',       'country': 'india',     'weight': 1.0, 'aliases': ['puri']},
    # USA
    'donald trump':         {'role': 'head_of_state',         'country': 'usa',       'weight': 1.3, 'aliases': ['president trump', 'trump']},
    'jerome powell':        {'role': 'central_bank_governor', 'country': 'usa',       'weight': 1.3, 'aliases': ['fed chair powell', 'powell']},
    'scott bessent':        {'role': 'finance_minister',      'country': 'usa',       'weight': 1.2, 'aliases': ['treasury secretary bessent', 'bessent']},
    'chris wright':         {'role': 'energy_minister',       'country': 'usa',       'weight': 1.1, 'aliases': ['energy secretary wright']},
    # China
    'xi jinping':           {'role': 'head_of_state',         'country': 'china',     'weight': 1.3, 'aliases': ['president xi', 'xi']},
    'li qiang':             {'role': 'head_of_state',         'country': 'china',     'weight': 1.1, 'aliases': ['premier li']},
    'pan gongsheng':        {'role': 'central_bank_governor', 'country': 'china',     'weight': 1.2, 'aliases': ['pboc governor', 'pan']},
    # Russia
    'vladimir putin':       {'role': 'head_of_state',         'country': 'russia',    'weight': 1.3, 'aliases': ['president putin', 'putin']},
    'elvira nabiullina':    {'role': 'central_bank_governor', 'country': 'russia',    'weight': 1.2, 'aliases': ['nabiullina', 'cbr governor']},
    'alexander novak':      {'role': 'energy_minister',       'country': 'russia',    'weight': 1.1, 'aliases': ['novak']},
    # Iran
    'masoud pezeshkian':    {'role': 'head_of_state',         'country': 'iran',      'weight': 1.2, 'aliases': ['president pezeshkian', 'pezeshkian']},
    'ali khamenei':         {'role': 'head_of_state',         'country': 'iran',      'weight': 1.3, 'aliases': ['supreme leader khamenei', 'khamenei', 'ayatollah khamenei']},
    # Saudi Arabia / OPEC
    'mohammed bin salman':  {'role': 'head_of_state',         'country': 'saudi_arabia', 'weight': 1.3, 'aliases': ['mbs', 'crown prince', 'mohammed bin salman']},
    'abdulaziz bin salman': {'role': 'energy_minister',       'country': 'saudi_arabia', 'weight': 1.2, 'aliases': ['prince abdulaziz']},
    # Mexico
    'claudia sheinbaum':    {'role': 'head_of_state',         'country': 'mexico',    'weight': 1.2, 'aliases': ['president sheinbaum', 'sheinbaum']},
    # Brazil
    'lula da silva':        {'role': 'head_of_state',         'country': 'brazil',    'weight': 1.2, 'aliases': ['president lula', 'lula']},
    # Turkey
    'recep tayyip erdogan': {'role': 'head_of_state',         'country': 'turkey',    'weight': 1.2, 'aliases': ['president erdogan', 'erdogan', 'erdoğan']},
    # Eurozone
    'christine lagarde':    {'role': 'central_bank_governor', 'country': 'eu',        'weight': 1.3, 'aliases': ['ecb president lagarde', 'lagarde']},
    # UK
    'andrew bailey':        {'role': 'central_bank_governor', 'country': 'uk',        'weight': 1.2, 'aliases': ['boe governor bailey']},
    # Japan
    'kazuo ueda':           {'role': 'central_bank_governor', 'country': 'japan',     'weight': 1.2, 'aliases': ['boj governor ueda']},
    # United Nations (mediator-class -- normative/brokering voice on food, grain, fertilizer)
    'antonio guterres':     {'role': 'un_secretary_general',  'country': 'un',        'weight': 1.2, 'aliases': ['guterres', 'un secretary-general', 'un secretary general', 'secretary-general guterres', 'un chief']},
    # ── Africa commodity-jawboning tier (added Jul 18 2026) ──
    # These leaders personally announce mine seizures, export bans, and
    # concession transfers -- their statements ARE the supply events.
    'felix tshisekedi':     {'role': 'head_of_state',         'country': 'drc',          'weight': 1.3, 'aliases': ['tshisekedi', 'president tshisekedi']},
    'ibrahim traore':       {'role': 'head_of_state',         'country': 'burkina_faso', 'weight': 1.2, 'aliases': ['traore', 'captain traore', 'capitaine traore']},
    'assimi goita':         {'role': 'head_of_state',         'country': 'mali',         'weight': 1.2, 'aliases': ['goita', 'colonel goita', 'general goita']},
    'abdourahamane tchiani': {'role': 'head_of_state',        'country': 'niger',        'weight': 1.2, 'aliases': ['tchiani', 'tiani', 'general tchiani']},
    'mamadi doumbouya':     {'role': 'head_of_state',         'country': 'guinea',       'weight': 1.2, 'aliases': ['doumbouya', 'mamady doumbouya', 'general doumbouya']},
    'abdel fattah al-burhan': {'role': 'head_of_state',       'country': 'sudan',        'weight': 1.1, 'aliases': ['burhan', 'al-burhan', 'general burhan']},
    'mohamed hamdan dagalo': {'role': 'militia_commander',    'country': 'sudan',        'weight': 1.1, 'aliases': ['hemedti', 'hemeti', 'dagalo', 'hemedti dagalo']},
    'bola tinubu':          {'role': 'head_of_state',         'country': 'nigeria',      'weight': 1.2, 'aliases': ['tinubu', 'president tinubu']},
}

# ── LEADER_INTERVENTION_KEYWORDS ─────────────────────────────────────────────
# Phrases that, when paired with a known speaker AND a commodity reference,
# elevate an article to an "intervention" signal. en/hi/ur coverage for India;
# en-only for other countries in v1.
LEADER_INTERVENTION_KEYWORDS = {
    'en': [
        # Demand-side calls
        'urged', 'urges', 'urge citizens', 'urge consumers', 'appeal', 'appealed',
        'called on', 'calls on', 'asked citizens', 'asked indians', 'ask the public',
        'avoid buying', 'stop buying', 'cut consumption', 'reduce consumption',
        'curb demand', 'restrain demand', 'pause buying',
        # Supply-side calls
        'release reserves', 'tap reserves', 'release from spr', 'draw down reserves',
        'export ban', 'export restriction', 'export curb', 'export tax',
        'import duty', 'raise duty', 'cut duty', 'tariff', 'levy',
        # Reserve / sovereign accumulation
        'build reserves', 'accumulate reserves', 'diversify reserves',
        'central bank gold', 'sovereign stockpile', 'strategic stockpile',
        # Threats / signals
        'will retaliate', 'will respond', 'weaponize', 'leverage',
        # Defensive statecraft markers (Feature B foothold)
        'protect forex', 'defend the rupee', 'defend currency', 'forex reserves',
        'balance of payments', 'current account', 'import bill',
    ],
    'hi': [
        # Hindi — common policy / exhortation language
        'अपील', 'आह्वान', 'आग्रह', 'अनुरोध',                      # appeal/call/urge
        'न खरीदें', 'मत खरीदें', 'खरीदारी रोकें', 'खरीद बंद',        # don't buy / stop buying
        'सोना न खरीदें', 'सोने की खरीद',                              # gold-specific
        'विदेशी मुद्रा भंडार', 'फॉरेक्स',                              # forex reserves
        'आयात शुल्क', 'निर्यात प्रतिबंध',                            # import duty / export ban
        'भंडार जारी',                                                # release reserves
    ],
    'ur': [
        # Urdu — used for Pakistan + cross-border India coverage
        'اپیل', 'مطالبہ', 'درخواست',                                # appeal/call/request
        'خریداری بند', 'نہ خریدیں', 'خریدنے سے گریز',                # don't buy / avoid buying
        'زر مبادلہ ذخائر', 'فاریکس',                                 # forex reserves
        'درآمدی ڈیوٹی', 'برآمدی پابندی',                             # import duty / export ban
        'ذخائر جاری',                                                # release reserves
    ],
}

# ── INTERVENTION_DIRECTION_LEXICON ───────────────────────────────────────────
# Trigger phrases mapped to the direction enum.
INTERVENTION_DIRECTION_LEXICON = {
    'suppress_demand':  [
        'avoid buying', 'stop buying', 'do not buy', "don't buy", 'pause buying',
        'cut consumption', 'reduce consumption', 'curb demand', 'restrain demand',
        'न खरीदें', 'मत खरीदें', 'खरीदारी रोकें',
        'نہ خریدیں', 'خریداری بند',
    ],
    'boost_demand':     [
        'encourage buying', 'incentivize purchase', 'buy local', 'buy domestic',
        'support purchases', 'buy indian', 'buy american', 'buy chinese',
    ],
    'restrict_supply':  [
        'export ban', 'export restriction', 'export curb', 'export tax',
        'production cut', 'output cut', 'cap exports', 'halt exports',
        'निर्यात प्रतिबंध', 'برآمدی پابندی',
    ],
    'boost_supply':     [
        'release reserves', 'tap reserves', 'release from spr', 'draw down reserves',
        'increase production', 'lift export ban', 'lift restriction',
        # Mediator / corridor language (keep supply flowing) -- only ever reached
        # after a KNOWN_SPEAKER gate, e.g. the UN Secretary-General on grain.
        'keep grain flowing', 'let the grain flow', 'grain corridor', 'grain deal',
        'grain initiative', 'safe passage', 'resume exports', 'restore exports',
        'allow exports', 'keep exports flowing', 'unblock exports',
        'fertilizer must reach', 'keep fertilizer flowing',
        'भंडार जारी', 'ذخائر جاری',
    ],
    'build_reserves':   [
        'build reserves', 'accumulate reserves', 'diversify reserves',
        'central bank purchases', 'central bank buying', 'sovereign stockpile',
        'strategic stockpile', 'build strategic',
    ],
    'draw_reserves':    [
        'sell reserves', 'reserve sale', 'liquidate reserves', 'reserves drawdown',
    ],
    'threaten_ban':     [
        'may ban', 'considering ban', 'could ban', 'threaten to ban', 'may impose ban',
    ],
    'threaten_sanctions': [
        'will sanction', 'sanctions if', 'consider sanctions', 'threaten sanctions',
        'secondary sanctions',
    ],
}

# ── INTERVENTION_RATIONALE_LEXICON ───────────────────────────────────────────
# Stated reasoning maps to rationale enum. Order matters — first match wins,
# so list more specific rationales before more generic ones.
INTERVENTION_RATIONALE_LEXICON = {
    'fx_defense':         [
        'forex reserves', 'foreign exchange reserves', 'protect forex', 'defend the rupee',
        'defend currency', 'balance of payments', 'current account', 'import bill',
        'विदेशी मुद्रा भंडार', 'فاریکس', 'زر مبادلہ ذخائر',
    ],
    'inflation':          [
        'inflation', 'cpi', 'cost of living', 'price stability', 'price rise',
        'महंगाई', 'مہنگائی',
    ],
    'food_security':      [
        'food security', 'food prices', 'food inflation', 'grain stocks', 'wheat shortage',
        'food crisis', 'global food crisis', 'famine', 'hunger', 'starvation',
        'acute food insecurity', 'food insecurity',
        'खाद्य सुरक्षा',
    ],
    'energy_security':    [
        'energy security', 'fuel prices', 'gasoline prices', 'pump prices', 'oil security',
        'crude prices',
    ],
    'sanctions_response': [
        'sanctions', 'sanctioned', 'in response to sanctions', 'retaliation', 'countersanctions',
    ],
    'strategic_stockpile': [
        'strategic reserve', 'strategic petroleum reserve', 'spr', 'national stockpile',
    ],
    'election_politics':  [
        'election', 'voters', 'electorate', 'campaign',
    ],
    'climate_policy':     [
        'climate', 'emissions', 'net zero', 'decarbonization', 'green transition',
    ],
    'industrial_policy':  [
        'industrial policy', 'made in china', 'make in india', 'reshoring',
        'self-reliance', 'atmanirbhar',
    ],
}

# Backlog (Feature B — Rhetoric tracker interpretation layer):
#   - ECONOMIC_ABSORPTION_SIGNATURES: classify defensive vs offensive statecraft
#   - upstream_stressor attribution (link to cross-theater fingerprints)
#   - Historical analog database (UK '67, India '91, Turkey '21, Egypt 2010s)
#   - Escalation ladder progression detection (jawboning → duty → controls → IMF)

# ========================================
# RSS FEEDS — Commodity-specific sources
# ========================================

COMMODITY_RSS_FEEDS = {
    # General commodity / market news
    'Reuters Commodities': 'https://news.google.com/rss/search?q=site:reuters.com+commodity+OR+oil+OR+wheat+OR+gold&hl=en&gl=US&ceid=US:en',
    'Bloomberg Markets': 'https://news.google.com/rss/search?q=site:bloomberg.com+commodity+OR+commodities&hl=en&gl=US&ceid=US:en',
    'FT Commodities': 'https://news.google.com/rss/search?q=site:ft.com+commodities&hl=en&gl=US&ceid=US:en',
    # Energy-specific
    'Oil Price News': 'https://news.google.com/rss/search?q=oil+price+OR+brent+OR+WTI+OR+OPEC&hl=en&gl=US&ceid=US:en',
    'IEA News': 'https://news.google.com/rss/search?q=site:iea.org+OR+international+energy+agency&hl=en&gl=US&ceid=US:en',
    'Natural Gas Intel': 'https://news.google.com/rss/search?q=natural+gas+OR+LNG+OR+henry+hub+OR+TTF&hl=en&gl=US&ceid=US:en',
    # Agriculture
    'USDA Wheat Reports': 'https://news.google.com/rss/search?q=USDA+wheat+OR+WASDE+OR+grain+stocks&hl=en&gl=US&ceid=US:en',
    'AgriCensus': 'https://news.google.com/rss/search?q=wheat+exports+OR+corn+exports+OR+soybean+exports&hl=en&gl=US&ceid=US:en',
    'Rice (USDA/Reuters)': 'https://news.google.com/rss/search?q=rice+export+OR+rice+prices+OR+basmati+OR+india+rice+ban&hl=en&gl=US&ceid=US:en',
    'Coffee (ICE/Reuters)': 'https://news.google.com/rss/search?q=coffee+prices+OR+arabica+OR+robusta+OR+brazil+coffee+OR+vietnam+coffee&hl=en&gl=US&ceid=US:en',
    # Food security / FAO (Stage 1a — June 2026)
    # FAO is the canonical food-commodity authority. These feed BOTH the commodity
    # news layer AND the cascade detector's article scan (fertilizer->food chain).
    # Pattern mirrors mining.com (Google News RSS, site: + keyword targeting).
    'FAO Food Price Index': 'https://news.google.com/rss/search?q=site:fao.org+food+price+index+OR+FFPI&hl=en&gl=US&ceid=US:en',
    'FAO GIEWS Early Warning': 'https://news.google.com/rss/search?q=FAO+GIEWS+OR+food+price+anomaly+OR+%22food+security%22+early+warning&hl=en&gl=US&ceid=US:en',
    'FAO Newsroom': 'https://news.google.com/rss/search?q=site:fao.org%2Fnewsroom+OR+FAO+warns+OR+FAO+food+prices&hl=en&gl=US&ceid=US:en',
    'Global Food Security': 'https://news.google.com/rss/search?q=food+security+crisis+OR+IPC+phase+OR+famine+OR+food+access+OR+crop+yield+forecast&hl=en&gl=US&ceid=US:en',
    # Strategic minerals
    'USGS Mineral News': 'https://news.google.com/rss/search?q=USGS+mineral+OR+rare+earth+OR+lithium+OR+uranium&hl=en&gl=US&ceid=US:en',
    'Mining.com': 'https://news.google.com/rss/search?q=site:mining.com+OR+mining+production&hl=en&gl=US&ceid=US:en',
    'Mining Journal': 'https://news.google.com/rss/search?q=mining+journal+OR+mineral+production&hl=en&gl=US&ceid=US:en',
    # Potash-specific (Peter's signal)
    'Potash News': 'https://news.google.com/rss/search?q=potash+OR+belaruskali+OR+uralkali+OR+nutrien&hl=en&gl=US&ceid=US:en',
    'Fertilizer News': 'https://news.google.com/rss/search?q=fertilizer+prices+OR+fertilizer+sanctions+OR+MOP+fertilizer&hl=en&gl=US&ceid=US:en',
    # Uranium
    'Uranium News': 'https://news.google.com/rss/search?q=uranium+OR+yellowcake+OR+kazatomprom+OR+cameco&hl=en&gl=US&ceid=US:en',
    'Nuclear Fuel News': 'https://news.google.com/rss/search?q=enriched+uranium+OR+HALEU+OR+rosatom+OR+urenco&hl=en&gl=US&ceid=US:en',
    # Rare earths
    'Rare Earth News': 'https://news.google.com/rss/search?q=rare+earth+OR+neodymium+OR+MP+materials+OR+lynas&hl=en&gl=US&ceid=US:en',
    'China REE': 'https://news.google.com/rss/search?q=china+rare+earth+OR+baotou+OR+REE+export&hl=en&gl=US&ceid=US:en',
    # Lithium
    'Lithium News': 'https://news.google.com/rss/search?q=lithium+OR+lithium+carbonate+OR+albemarle+OR+SQM&hl=en&gl=US&ceid=US:en',
    # Gold
    'Gold Markets': 'https://news.google.com/rss/search?q=gold+price+OR+gold+reserves+OR+central+bank+gold&hl=en&gl=US&ceid=US:en',
    # Copper
    'Copper News': 'https://news.google.com/rss/search?q=copper+OR+copper+prices+OR+codelco+OR+escondida&hl=en&gl=US&ceid=US:en',
    # Cobalt (NEW)
    'Cobalt News': 'https://news.google.com/rss/search?q=cobalt+OR+drc+cobalt+OR+glencore+cobalt+OR+CMOC&hl=en&gl=US&ceid=US:en',
    'Battery Metals News': 'https://news.google.com/rss/search?q=battery+metals+OR+nmc+battery+OR+lfp+battery+OR+cobalt+lithium&hl=en&gl=US&ceid=US:en',
    # Nickel (NEW)
    'Nickel News': 'https://news.google.com/rss/search?q=nickel+OR+indonesia+nickel+OR+norilsk+nickel+OR+LME+nickel&hl=en&gl=US&ceid=US:en',
    'Indonesia Mining': 'https://news.google.com/rss/search?q=indonesia+mining+OR+morowali+OR+sulawesi+nickel+OR+weda+bay&hl=en&gl=US&ceid=US:en',
    # Silver (NEW)
    'Silver News': 'https://news.google.com/rss/search?q=silver+OR+silver+prices+OR+fresnillo+OR+pan+american+silver&hl=en&gl=US&ceid=US:en',
    'Precious Metals': 'https://news.google.com/rss/search?q=precious+metals+OR+gold+silver+OR+silver+demand+OR+silver+solar&hl=en&gl=US&ceid=US:en',

    # ---- Broad multi-commodity sources (scan ALL commodities; each article is
    #      attributed to a commodity downstream by _match_commodity_in_text) ----
    'Yahoo Finance Commodities': 'https://news.google.com/rss/search?q=site:finance.yahoo.com+sugar+OR+commodity+OR+futures+OR+manganese+OR+platinum+OR+nickel&hl=en&gl=US&ceid=US:en',
    'Barchart Commodities': 'https://news.google.com/rss/search?q=site:barchart.com+sugar+OR+commodity+OR+futures+OR+prices+OR+grain+OR+metals&hl=en&gl=US&ceid=US:en',

    # ---- Dedicated feeds for previously-uncovered commodities ----
    'Sugar Markets': 'https://news.google.com/rss/search?q=sugar+prices+OR+raw+sugar+OR+sugar+futures+OR+ICE+sugar+OR+brazil+sugar+OR+india+sugar&hl=en&gl=US&ceid=US:en',
    'Manganese News': 'https://news.google.com/rss/search?q=manganese+OR+ferromanganese+OR+manganese+ore+OR+silicomanganese+OR+south32+manganese+OR+eramet+manganese&hl=en&gl=US&ceid=US:en',
    'Semiconductor Supply': 'https://news.google.com/rss/search?q=semiconductor+OR+chip+shortage+OR+TSMC+OR+foundry+OR+wafer+OR+chip+export&hl=en&gl=US&ceid=US:en',
    'Chromium & Ferrochrome': 'https://news.google.com/rss/search?q=chromium+OR+ferrochrome+OR+chrome+ore+OR+chromite+OR+ferrochrome+prices&hl=en&gl=US&ceid=US:en',
    'Diamond Markets': 'https://news.google.com/rss/search?q=diamond+prices+OR+de+beers+OR+alrosa+OR+rough+diamond+OR+kimberley+process&hl=en&gl=US&ceid=US:en',
    'Bauxite & Alumina': 'https://news.google.com/rss/search?q=bauxite+OR+alumina+OR+guinea+bauxite+OR+bauxite+prices+OR+alumina+prices&hl=en&gl=US&ceid=US:en',
    'Sulfur Markets': 'https://news.google.com/rss/search?q=sulfur+OR+sulphur+OR+sulfuric+acid+OR+molten+sulphur+OR+sulphur+prices&hl=en&gl=US&ceid=US:en',
    'Nitrogen Fertilizer': 'https://news.google.com/rss/search?q=urea+prices+OR+ammonia+prices+OR+nitrogen+fertilizer+OR+ammonium+nitrate+OR+CF+industries+OR+yara+nitrogen&hl=en&gl=US&ceid=US:en',
    'Phosphate News': 'https://news.google.com/rss/search?q=phosphate+OR+DAP+fertilizer+OR+MAP+fertilizer+OR+phosphate+rock+OR+OCP+morocco+OR+phosphoric+acid&hl=en&gl=US&ceid=US:en',
}
# ========================================
# REDDIT SUBREDDITS
# ========================================

COMMODITY_REDDIT_SUBREDDITS = [
    'commodities',
    'Commodities',
    'Mining',
    'uranium',
    'RareEarthMetals',
    'agriculture',
    'wheat',
    'farming',
    'wallstreetbets',     # Surprisingly active for futures
    'EnergyAndPower',
    'oil',
    'naturalgas',
    # NEW: cobalt / nickel / silver
    'BatteryMetals',
    'electricvehicles',   # battery-metals discussion
    'Wallstreetsilver',
    'silverbugs',
    'PreciousMetals',
]

REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ========================================
# ALERT THRESHOLDS
# ========================================

ALERT_THRESHOLDS = {
    'normal':   {'min_score': 0,  'label': 'Normal',    'color': 'green',  'icon': '🟢', 'banner': False},
    'elevated': {'min_score': 8,  'label': 'Elevated',  'color': 'yellow', 'icon': '🟡', 'banner': True},
    'high':     {'min_score': 20, 'label': 'High',      'color': 'orange', 'icon': '🟠', 'banner': True},
    'surge':    {'min_score': 40, 'label': 'Surge',     'color': 'red',    'icon': '🔴', 'banner': True},
}


# ========================================
# REDIS CACHE (mirrors military_tracker pattern)
# ========================================

COMMODITY_REDIS_KEY = 'commodity_tracker_cache'


def load_commodity_cache():
    """Load cached commodity tracker data from Upstash Redis, fallback to /tmp"""
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{COMMODITY_REDIS_KEY}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get("result"):
                cache = json.loads(data["result"])
                print(f"[Commodity Cache] Loaded from Redis (cached_at: {cache.get('cached_at', 'unknown')})")
                return cache
            print("[Commodity Cache] No existing cache in Redis")
        except Exception as e:
            print(f"[Commodity Cache] Redis load error: {e}")

    try:
        from pathlib import Path
        if Path(COMMODITY_CACHE_FILE).exists():
            with open(COMMODITY_CACHE_FILE, 'r') as f:
                cache = json.load(f)
                print("[Commodity Cache] Loaded from /tmp fallback")
                return cache
    except Exception as e:
        print(f"[Commodity Cache] /tmp load error: {e}")

    return {}


def save_commodity_cache(data):
    """Save commodity tracker data to Upstash Redis + /tmp fallback"""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()

    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            payload = json.dumps(data, default=str)
            resp = requests.post(
                f"{UPSTASH_REDIS_URL}/set/{COMMODITY_REDIS_KEY}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                data=payload,
                timeout=10
            )
            if resp.status_code == 200:
                print("[Commodity Cache] ✅ Saved to Redis")
            else:
                print(f"[Commodity Cache] Redis save HTTP {resp.status_code}")
        except Exception as e:
            print(f"[Commodity Cache] Redis save error: {e}")

    try:
        with open(COMMODITY_CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        print("[Commodity Cache] Saved /tmp fallback")
    except Exception as e:
        print(f"[Commodity Cache] /tmp save error: {e}")


def is_commodity_cache_fresh():
    """Check if commodity cache is still valid"""
    try:
        cache = load_commodity_cache()
        if not cache or 'cached_at' not in cache:
            return False
        cached_at = datetime.fromisoformat(cache['cached_at'])
        age = datetime.now(timezone.utc) - cached_at
        is_fresh = age.total_seconds() < (COMMODITY_CACHE_TTL_HOURS * 3600)
        if is_fresh:
            age_min = age.total_seconds() / 60
            print(f"[Commodity Cache] Fresh ({age_min:.0f}min old)")
        return is_fresh
    except:
        return False


def load_sparkline_cache():
    """Load sparkline cache (separate from main cache, refreshed hourly)."""
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{SPARKLINE_REDIS_KEY}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get("result"):
                return json.loads(data["result"])
        except Exception as e:
            print(f"[Sparkline Cache] Redis load error: {e}")
    return {}


def save_sparkline_cache(data):
    """Save sparkline cache to Redis."""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            payload = json.dumps(data, default=str)
            resp = requests.post(
                f"{UPSTASH_REDIS_URL}/set/{SPARKLINE_REDIS_KEY}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                data=payload,
                timeout=10
            )
            if resp.status_code == 200:
                print("[Sparkline Cache] ✅ Saved to Redis")
        except Exception as e:
            print(f"[Sparkline Cache] Redis save error: {e}")


def is_sparkline_cache_fresh():
    """Sparklines have shorter TTL (1hr) since prices move."""
    try:
        cache = load_sparkline_cache()
        if not cache or 'cached_at' not in cache:
            return False
        cached_at = datetime.fromisoformat(cache['cached_at'])
        age = datetime.now(timezone.utc) - cached_at
        return age.total_seconds() < (SPARKLINE_CACHE_TTL_HOURS * 3600)
    except:
        return False


# ========================================
# YAHOO FINANCE — Sparkline Fetcher
# ========================================

def _fetch_yahoo_sparkline(ticker, period='1mo'):
    """
    Fetch 30-day OHLC for a single ticker via yfinance.

    Returns a dict:
        {
            'ticker':       'BZ=F',
            'price':        72.40,
            'change_1d':    0.85,
            'change_pct_1d': 1.18,
            'change_30d':   -2.10,
            'change_pct_30d': -2.81,
            'spark':        [70.1, 70.4, 71.2, ...],     # 30 closing prices
            'currency':     'USD',
            'last_updated': iso8601,
        }
    or None on failure.
    """
    if not YFINANCE_AVAILABLE:
        return None

    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist is None or hist.empty:
            return None

        closes = hist['Close'].dropna().tolist()
        if not closes or len(closes) < 2:
            return None

        # Round closes for compact JSON payload
        closes_rounded = [round(float(c), 2) for c in closes]
        latest = closes_rounded[-1]
        previous = closes_rounded[-2] if len(closes_rounded) >= 2 else latest
        first = closes_rounded[0]

        change_1d  = round(latest - previous, 2)
        change_pct = round(((latest - previous) / previous) * 100, 2) if previous else 0.0
        change_30d = round(latest - first, 2)
        change_30d_pct = round(((latest - first) / first) * 100, 2) if first else 0.0

        return {
            'ticker':         ticker,
            'price':          latest,
            'change_1d':      change_1d,
            'change_pct_1d':  change_pct,
            'change_30d':     change_30d,
            'change_pct_30d': change_30d_pct,
            'spark':          closes_rounded,
            'point_count':    len(closes_rounded),
            'currency':       'USD',
            'last_updated':   datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"[Sparkline] {ticker} fetch error: {str(e)[:120]}")
        return None


def _fetch_with_failover(commodity_id, commodity_data):
    """
    Try the primary yahoo_ticker, then fall back through yahoo_proxies.
    Returns the first successful sparkline result, or None.
    """
    if not commodity_data.get('has_spot_price'):
        # Potash: production-volume-only, no sparkline
        return None

    primary = commodity_data.get('yahoo_ticker')
    proxies = commodity_data.get('yahoo_proxies', []) or []

    candidates = []
    if primary:
        candidates.append(primary)
    candidates.extend(proxies)

    for ticker in candidates:
        spark = _fetch_yahoo_sparkline(ticker)
        if spark:
            spark['source_ticker_used'] = ticker
            spark['fallback_used'] = (ticker != primary)
            return spark
        print(f"[Sparkline] {commodity_id}: {ticker} returned no data, trying next...")

    print(f"[Sparkline] {commodity_id}: ALL tickers failed (tried {len(candidates)})")
    return None


def fetch_all_sparklines(force=False):
    """
    Fetch sparklines for all commodities with public spot prices.
    Uses 1hr cache. Set force=True to bypass.
    Returns dict keyed by commodity_id.
    """
    if not force and is_sparkline_cache_fresh():
        cache = load_sparkline_cache()
        if cache.get('sparklines'):
            return cache['sparklines']

    print("[Sparkline] Refreshing all commodity sparklines...")
    results = {}
    for commodity_id, commodity_data in COMMODITY_TYPES.items():
        spark = _fetch_with_failover(commodity_id, commodity_data)
        results[commodity_id] = spark   # may be None for potash, or on failure
        time.sleep(0.3)                  # polite pause between Yahoo calls

    save_sparkline_cache({'sparklines': results})

    success_count = sum(1 for v in results.values() if v is not None)
    print(f"[Sparkline] ✅ {success_count}/{len(COMMODITY_TYPES)} commodities have live prices")
    return results


# ========================================
# RSS FETCHER (mirrors military pattern)
# ========================================

def fetch_commodity_rss(feed_name, feed_url, max_articles=15):
    """Fetch articles from a single commodity-relevant RSS feed."""
    articles = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Commodity RSS] {feed_name}: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:max_articles]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            desc_elem = item.find('description')

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

            articles.append({
                'title':       title_elem.text or '',
                'description': description,
                'url':         link_elem.text or '',
                'publishedAt': pub_date,
                'source':      {'name': feed_name},
                'content':     description,
                'feed_type':   'commodity_rss',
            })

        print(f"[Commodity RSS] {feed_name}: ✓ {len(articles)} articles")
        return articles

    except ET.ParseError as e:
        print(f"[Commodity RSS] {feed_name}: XML parse error: {str(e)[:100]}")
        return []
    except Exception as e:
        print(f"[Commodity RSS] {feed_name}: Error: {str(e)[:100]}")
        return []


def fetch_all_commodity_rss():
    """Aggregate from all configured commodity RSS feeds."""
    all_articles = []
    for feed_name, feed_url in COMMODITY_RSS_FEEDS.items():
        articles = fetch_commodity_rss(feed_name, feed_url)
        all_articles.extend(articles)
        time.sleep(0.4)
    print(f"[Commodity RSS] Total: {len(all_articles)} articles")
    return all_articles


# ========================================
# GDELT FETCHER (multilingual)
# ========================================

def fetch_gdelt_commodity(query, days=7, language='eng'):
    """Fetch commodity-relevant articles from GDELT."""
    try:
        params = {
            'query':      query,
            'mode':       'artlist',
            'maxrecords': 50,
            'timespan':   f'{days}d',
            'format':     'json',
            'sourcelang': language,
        }
        response = None
        for attempt in range(2):
            try:
                response = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 15))
                if response.status_code == 200:
                    break
                if response.status_code == 429:
                    print(f"[Commodity GDELT] 429 rate limit -- skipping: {query[:50]}")
                    return []
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

        return [{
            'title':       a.get('title', ''),
            'description': a.get('title', ''),
            'url':         a.get('url', ''),
            'publishedAt': a.get('seendate', ''),
            'source':      {'name': a.get('domain', 'GDELT')},
            'content':     a.get('title', ''),
            'feed_type':   'gdelt',
        } for a in articles]

    except Exception as e:
        print(f"[Commodity GDELT] Error: {str(e)[:100]}")
        return []


def fetch_all_gdelt_commodity(days=7):
    """Fetch commodity articles across English + multilingual queries."""
    english_queries = [
        # General commodity / market
        'commodity prices market',
        'fertilizer prices sanctions',
        'critical minerals supply chain',
        # Oil
        'oil prices brent OPEC sanctions',
        'russian oil exports shadow fleet',
        'iran oil exports china',
        'saudi arabia oil production OPEC',
        # Natural gas / LNG
        'LNG exports natural gas TTF',
        'european gas supply russia',
        'qatar lng us lng exports',
        # Wheat / corn / soybeans
        'wheat prices black sea grain',
        'russian wheat exports global',
        'ukraine grain corridor odesa',
        'corn exports brazil ukraine',
        'soybean china trade tariff',
        # Potash (Peter's signal)
        'potash exports belaruskali sanctions',
        'belarus potash russian ports china rail',
        'potash production canada nutrien',
        'fertilizer market mosaic potash',
        # Uranium
        'uranium prices kazatomprom enrichment',
        'rosatom uranium tenex sanctions',
        'niger uranium orano arlit',
        'cameco uranium production',
        # Rare earths
        'china rare earth export controls',
        'mp materials mountain pass rare earth',
        'lynas rare earth australia',
        'neodymium dysprosium magnet',
        # Lithium
        'lithium prices battery EV',
        'albemarle SQM lithium chile',
        'china lithium ganfeng tianqi',
        # Gold
        'gold prices central bank reserves',
        'russia gold reserves brics',
        'china gold buying shanghai',
        # Copper
        'copper prices china demand',
        'codelco escondida copper production',
        'first quantum cobre panama copper',
        # Cobalt (NEW)
        'cobalt prices DRC congo supply',
        'cmoc cobalt tenke fungurume kisanfu',
        'glencore cobalt mutanda mining',
        'indonesia cobalt sulawesi morowali',
        'cobalt export ban quota battery',
        # Nickel (NEW)
        'nickel prices indonesia LME',
        'norilsk nickel russia production',
        'philippines nickel surigao mining',
        'nickel battery EV stainless steel',
        'tsingshan huayou nickel china',
        # Silver (NEW)
        'silver prices comex demand',
        'mexico silver fresnillo zacatecas',
        'peru silver antamina mining',
        'silver solar photovoltaic demand',
        'china silver imports refining',
    ]

    russian_queries = [
        'нефть санкции цена',
        'газ европейский экспорт',
        'пшеница экспорт черное море',
        'калий беларуськалий уралкалий',
        'уран росатом тенекс',
        'золото резервы брикс',
        'никель норильский',
        'серебро добыча',
        'кобальт россия',
    ]

    chinese_queries = [
        '原油价格 制裁',
        '稀土出口 限制',
        '锂矿 电池',
        '钾肥 进口',
        '黄金储备 中国',
        '小麦 进口',
        '大豆 美国',
        '钴 电池 刚果',
        '镍 印尼 不锈钢',
        '白银 价格 太阳能',
    ]

    arabic_queries = [
        'أسعار النفط أوبك',
        'صادرات القمح روسيا',
        'الذهب احتياطيات',
    ]

    spanish_queries = [
        'cobre chile producción',
        'litio chile argentina',
        'soja brasil exportación',
        'maíz argentina cosecha',
    ]

    portuguese_queries = [
        'soja brasil exportação china',
        'milho safrinha brasil',
    ]

    all_articles = []
    blocks = [
        (english_queries,    'eng', 'English'),
        (russian_queries,    'rus', 'Russian'),
        (chinese_queries,    'zho', 'Chinese'),
        (arabic_queries,     'ara', 'Arabic'),
        (spanish_queries,    'spa', 'Spanish'),
        (portuguese_queries, 'por', 'Portuguese'),
    ]

    for queries, lang_code, lang_name in blocks:
        block_count = 0
        for query in queries:
            articles = fetch_gdelt_commodity(query, days, language=lang_code)
            all_articles.extend(articles)
            block_count += len(articles)
            time.sleep(0.5)
        if block_count > 0:
            print(f"[Commodity GDELT] {lang_name} ({lang_code}): {block_count} articles")

    print(f"[Commodity GDELT] Total: {len(all_articles)} articles")
    return all_articles


# ========================================
# NewsAPI FETCHER
# ========================================

def fetch_newsapi_commodity(query, days=7):
    """Fetch a single commodity-relevant query from NewsAPI."""
    if not NEWSAPI_KEY:
        return []

    from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    url = "https://newsapi.org/v2/everything"
    params = {
        'q':         query,
        'from':      from_date,
        'sortBy':    'publishedAt',
        'language':  'en',
        'apiKey':    NEWSAPI_KEY,
        'pageSize':  50,
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


def fetch_all_newsapi_commodity(days=7):
    """Aggregate NewsAPI commodity coverage."""
    queries = [
        'oil prices brent OR WTI OR OPEC',
        'natural gas LNG OR henry hub OR TTF',
        'wheat exports OR grain corridor OR black sea',
        'corn exports OR soybean trade',
        'potash OR belaruskali OR fertilizer sanctions',
        'uranium OR kazatomprom OR rosatom enrichment',
        'rare earth OR mp materials OR neodymium',
        'lithium prices OR albemarle OR EV battery',
        'gold prices OR central bank reserves',
        'copper prices OR codelco OR china demand',
    ]
    all_articles = []
    for q in queries:
        articles = fetch_newsapi_commodity(q, days)
        all_articles.extend(articles)
        time.sleep(0.3)
    print(f"[Commodity NewsAPI] Total: {len(all_articles)} articles")
    return all_articles


# ========================================
# BRAVE SEARCH FALLBACK
# ========================================

def fetch_brave_commodity(query, count=20):
    """
    Brave Search fallback when GDELT/NewsAPI are insufficient.
    Free tier: 2000 queries/month, 1 req/sec — use sparingly.
    """
    if not BRAVE_API_KEY:
        return []
    try:
        resp = requests.get(
            'https://api.search.brave.com/res/v1/news/search',
            headers={
                'Accept': 'application/json',
                'X-Subscription-Token': BRAVE_API_KEY,
            },
            params={'q': query, 'count': count},
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[Commodity Brave] HTTP {resp.status_code}")
            return []
        data = resp.json()
        results = data.get('results', [])
        return [{
            'title':       r.get('title', ''),
            'description': r.get('description', '')[:500],
            'url':         r.get('url', ''),
            'publishedAt': r.get('age', ''),
            'source':      {'name': r.get('meta_url', {}).get('hostname', 'Brave')},
            'content':     r.get('description', ''),
            'feed_type':   'brave',
        } for r in results]
    except Exception as e:
        print(f"[Commodity Brave] Error: {str(e)[:100]}")
        return []


def fetch_all_brave_commodity():
    """
    Brave fallback — only fires for a small set of high-priority queries
    to conserve free-tier quota. Used when GDELT yields <40 articles.
    """
    if not BRAVE_API_KEY:
        return []
    queries = [
        'potash sanctions belarus 2026',
        'uranium prices haleu 2026',
        'rare earth export ban china 2026',
        'wheat global supply russia ukraine',
    ]
    all_articles = []
    for q in queries:
        articles = fetch_brave_commodity(q)
        all_articles.extend(articles)
        time.sleep(1.1)   # respect 1 req/sec free tier limit
    print(f"[Commodity Brave] Fallback: {len(all_articles)} articles")
    return all_articles


# ========================================
# REDDIT FETCHER
# ========================================

def fetch_reddit_commodity(days=7):
    """Fetch commodity discussions from Reddit subreddits."""
    all_posts = []
    keywords = ['oil', 'gas', 'wheat', 'potash', 'uranium', 'lithium', 'gold', 'copper']
    query = " OR ".join(keywords)
    time_filter = "week" if days <= 7 else "month"

    for subreddit in COMMODITY_REDDIT_SUBREDDITS[:8]:
        try:
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params = {
                "q":           query,
                "restrict_sr": "true",
                "sort":        "new",
                "t":           time_filter,
                "limit":       15,
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
                            'title':       post_data.get('title', '')[:200],
                            'description': post_data.get('selftext', '')[:300],
                            'url':         f"https://www.reddit.com{post_data.get('permalink', '')}",
                            'publishedAt': datetime.fromtimestamp(
                                post_data.get('created_utc', 0),
                                tz=timezone.utc,
                            ).isoformat(),
                            'source':      {'name': f'r/{subreddit}'},
                            'content':     post_data.get('selftext', ''),
                            'feed_type':   'reddit',
                        })
        except Exception:
            continue

    print(f"[Commodity Reddit] Total: {len(all_posts)} posts")
    return all_posts


# ========================================
# SCHEMA HELPERS — backward-compat for dict-of-roles migration (May 2026)
# ========================================
# COUNTRY_COMMODITY_EXPOSURE supports two entry shapes:
#
#   Old (single-role, original):
#     'china': {
#         'rare_earths': {'role': 'producer', 'weight': 1.5, 'rank': 1, 'note': '...'}
#     }
#
#   New (multi-role, dict-of-roles — for countries that are BOTH producer
#   and consumer of the same commodity, e.g. China wheat, India wheat,
#   USA oil):
#     'china': {
#         'wheat': {
#             'producer': {'weight': 1.5, 'rank': 1, 'note': '...'},
#             'consumer': {'weight': 1.4, 'rank': 1, 'note': '...'}
#         }
#     }
#
# These helpers normalize both shapes so existing analytical code works
# without modification. Always use these to read the registry — never index
# COUNTRY_COMMODITY_EXPOSURE[country][commodity] directly downstream.

def _is_multi_role_entry(entry):
    """
    Returns True if `entry` is a new-style dict-of-roles (no top-level 'role'
    key, but has 'producer'/'consumer'/'transit'/'sanctions_target'/'mediator'
    keys instead). Returns False for old-style single-role entries.
    """
    if not isinstance(entry, dict):
        return False
    if 'role' in entry:
        return False  # old-style: has 'role' at top level
    role_keys = {'producer', 'consumer', 'transit', 'sanctions_target', 'mediator'}
    return any(k in entry for k in role_keys)


def _iter_country_exposures(country_id):
    """
    Yield (commodity_id, role_name, role_data_dict) tuples for a country.
    Handles both old-style single-role and new-style dict-of-roles entries.

    role_data_dict always has the shape:
      {'role': str, 'weight': float, 'rank': int|None, 'note': str}

    For old-style entries this is the original dict (already has 'role').
    For new-style entries this is constructed from the inner role dict
    with 'role' injected.
    """
    profile = COUNTRY_COMMODITY_EXPOSURE.get(country_id, {})
    for commodity_id, entry in profile.items():
        if _is_multi_role_entry(entry):
            # New-style: yield once per role
            for role_name, role_data in entry.items():
                if not isinstance(role_data, dict):
                    continue
                normalized = dict(role_data)
                normalized['role'] = role_name
                yield commodity_id, role_name, normalized
        else:
            # Old-style: single yield with whatever role is recorded
            if isinstance(entry, dict) and 'role' in entry:
                yield commodity_id, entry['role'], entry


def _country_has_commodity(country_id, commodity_id):
    """
    Returns True if a country has ANY exposure (any role) to a commodity.
    Used by article-attribution to decide which countries get a signal.
    """
    profile = COUNTRY_COMMODITY_EXPOSURE.get(country_id, {})
    return commodity_id in profile


def _country_commodity_exposures(country_id, commodity_id):
    """
    Returns a list of (role_name, role_data_dict) tuples for a single
    (country, commodity) pair. Empty list if no exposure exists.
    Old-style entries return a 1-element list; new-style return N-element list.
    """
    profile = COUNTRY_COMMODITY_EXPOSURE.get(country_id, {})
    entry = profile.get(commodity_id)
    if entry is None:
        return []
    if _is_multi_role_entry(entry):
        result = []
        for role_name, role_data in entry.items():
            if not isinstance(role_data, dict):
                continue
            normalized = dict(role_data)
            normalized['role'] = role_name
            result.append((role_name, normalized))
        return result
    if isinstance(entry, dict) and 'role' in entry:
        return [(entry['role'], entry)]
    return []


def _country_commodity_max_weight(country_id, commodity_id):
    """
    Returns the maximum weight across all roles for a (country, commodity)
    pair. Used by signal-scoring to apply the strongest exposure weight.
    Returns 1.0 if no exposure exists (defensive default).
    """
    exposures = _country_commodity_exposures(country_id, commodity_id)
    if not exposures:
        return 1.0
    weights = [e[1].get('weight', 1.0) for e in exposures]
    return max(weights) if weights else 1.0


# ========================================
# CROSS-TRACKER FINGERPRINTS (May 2026)
# ========================================
# This module emits per-(country, commodity) supply-risk fingerprints to Redis
# so that downstream consumers (rhetoric trackers, regional BLUFs, GPI) can
# read country-specific commodity pressure without re-querying the full
# /api/commodity-pressure endpoint.
#
# CONSUMER CONTRACT — for any downstream tracker:
#
#   from commodity_tracker import read_country_supply_risk, read_all_supply_risks_for_country
#
#   # Read a single country/commodity pair:
#   risk = read_country_supply_risk('peru', 'copper')
#   # Returns dict (see schema below) or None if no current pressure
#
#   # Read all commodity pressures for a single country:
#   risks = read_all_supply_risks_for_country('peru')
#   # Returns dict {commodity_id: risk_dict} or {} if no pressure
#
# REDIS KEY PATTERN:  commodity:{commodity_id}:{country_id}_supply_risk
#   examples:  commodity:copper:peru_supply_risk
#              commodity:lithium:chile_supply_risk
#              commodity:cobalt:drc_supply_risk
#
# VALUE SCHEMA (JSON):
#   {
#     'country':                'peru',
#     'commodity':              'copper',
#     'role':                   'producer',           # primary role (or composite)
#     'roles':                  ['producer'],         # list of all roles for this country/commodity
#     'is_multi_role':          False,
#     'rank':                   2,                    # global rank for primary role (or None)
#     'max_weight':             1.3,                  # max weight across all roles
#     'alert_level':            'elevated',           # normal | elevated | high | surge
#     'signal_count':           7,
#     'country_weighted_score': 12.3,                 # signals × country_weight
#     'top_signal': {                                 # the single highest-weight signal
#         'title':      'Las Bambas community blockade enters week 3',
#         'url':        'https://...',
#         'source':     'Reuters',
#         'weight':     1.4,
#         'language':   'es',
#         'published':  '2026-05-08T14:00:00Z',
#     },
#     'top_signals_brief': [...],                     # top 3 signals (lighter shape)
#     'fingerprint_written_at': '2026-05-09T15:30:00Z',
#     'ttl_hours':              13,
#   }
#
# WRITE BEHAVIOR:
#   • Fingerprints are written ONLY for (country, commodity) pairs with
#     signal_count > 0 — empty fingerprints are NOT written. This keeps Redis
#     clean (we'd otherwise have 32 × 15 = 480 keys, most empty).
#   • TTL is 13 hours = 12-hour standard refresh + 1-hour buffer. This ensures
#     fingerprints never expire mid-cycle if a refresh is delayed.
#   • Writes happen at the end of _run_full_scan(), inside the per-country
#     breakdown loop, after country_summaries[cid] is populated.
#   • If Upstash Redis is not configured (no env vars), writes silently no-op.
#
# READ BEHAVIOR:
#   • read_country_supply_risk(country, commodity) returns the dict or None
#   • read_all_supply_risks_for_country(country) iterates the country's
#     registered commodities and returns a {commodity_id: dict} map
#   • Both readers handle Redis-down gracefully (return None / empty dict)

SUPPLY_RISK_FINGERPRINT_TTL_HOURS = 13   # 12h refresh + 1h buffer


def _supply_risk_redis_key(country_id, commodity_id):
    """Build the canonical Redis key for a (country, commodity) supply-risk fingerprint."""
    return f"commodity:{commodity_id}:{country_id}_supply_risk"


def _write_supply_risk_fingerprint(country_id, commodity_id, breakdown_entry):
    """
    Emit a per-(country, commodity) supply-risk fingerprint to Upstash Redis.

    Called from _run_full_scan() after country_summaries are built. Skips
    write entirely if signal_count == 0 (no current pressure to report).

    Args:
        country_id: e.g. 'peru'
        commodity_id: e.g. 'copper'
        breakdown_entry: the dict from country_summaries[country_id]['commodity_signals'][commodity_id]
                        — contains role, weight, rank, signal_count, top_signals, roles[], etc.

    Returns:
        True if the fingerprint was written, False if skipped or failed.
    """
    if not breakdown_entry:
        return False
    signal_count = breakdown_entry.get('signal_count', 0)
    if signal_count == 0:
        return False  # nothing to report — skip write to keep Redis clean

    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False  # silently no-op if Redis isn't configured

    # Compute country-weighted score (signal weight × country exposure weight)
    role_exposures = _country_commodity_exposures(country_id, commodity_id)
    if not role_exposures:
        return False
    max_weight = max(e[1].get('weight', 1.0) for e in role_exposures)
    role_names = [e[0] for e in role_exposures]
    is_multi_role = len(role_names) > 1

    # Country-weighted score = sum of (signal weight × max country exposure weight)
    top_signals = breakdown_entry.get('top_signals', []) or []
    country_weighted_score = round(
        sum(s.get('weight', 1.0) * max_weight for s in top_signals),
        2
    )

    # Determine alert level for this country/commodity pair
    alert_level = determine_alert_level(country_weighted_score)

    # Build top_signal (the single highest-weight) and top_signals_brief (top 3, lighter)
    top_signal = None
    if top_signals:
        s0 = top_signals[0]
        top_signal = {
            'title':      s0.get('article_title') or s0.get('title'),
            'url':        s0.get('article_url') or s0.get('url'),
            'source':     s0.get('source'),
            'weight':     s0.get('weight'),
            'language':   s0.get('language'),
            'published':  s0.get('published'),
        }
    top_signals_brief = []
    for s in top_signals[:3]:
        top_signals_brief.append({
            'title':  s.get('article_title') or s.get('title'),
            'url':    s.get('article_url') or s.get('url'),
            'source': s.get('source'),
            'weight': s.get('weight'),
        })

    fingerprint = {
        'country':                country_id,
        'commodity':              commodity_id,
        'role':                   breakdown_entry.get('role'),
        'roles':                  role_names,
        'is_multi_role':          is_multi_role,
        'rank':                   breakdown_entry.get('rank'),
        'max_weight':             max_weight,
        'alert_level':            alert_level,
        'signal_count':           signal_count,
        'country_weighted_score': country_weighted_score,
        'top_signal':             top_signal,
        'top_signals_brief':      top_signals_brief,
        'fingerprint_written_at': datetime.now(timezone.utc).isoformat(),
        'ttl_hours':              SUPPLY_RISK_FINGERPRINT_TTL_HOURS,
    }

    key = _supply_risk_redis_key(country_id, commodity_id)
    ttl_seconds = SUPPLY_RISK_FINGERPRINT_TTL_HOURS * 3600

    try:
        url = f"{UPSTASH_REDIS_URL}/setex/{key}/{ttl_seconds}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(fingerprint, default=str),
            timeout=5
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Commodity Fingerprint] Write error ({key}): {str(e)[:120]}")
        return False


def read_country_supply_risk(country_id, commodity_id):
    """
    Read a single (country, commodity) supply-risk fingerprint from Redis.

    Returns:
        dict (see schema in module header) or None if no fingerprint exists,
        Redis is unavailable, or a network error occurs.

    Usage:
        from commodity_tracker import read_country_supply_risk
        risk = read_country_supply_risk('peru', 'copper')
        if risk:
            alert = risk['alert_level']
            top_headline = risk['top_signal']['title'] if risk.get('top_signal') else None
    """
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    key = _supply_risk_redis_key(country_id, commodity_id)
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        raw = body.get('result')
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        print(f"[Commodity Fingerprint] Read error ({key}): {str(e)[:120]}")
        return None


def read_all_supply_risks_for_country(country_id):
    """
    Read all supply-risk fingerprints for a country across its registered commodities.

    Returns:
        dict {commodity_id: risk_dict} — only commodities with active fingerprints
        included. Empty dict if no pressure or country not in registry.

    Usage:
        from commodity_tracker import read_all_supply_risks_for_country
        risks = read_all_supply_risks_for_country('peru')
        # {'copper': {...}, 'silver': {...}} — assuming both have active pressure
    """
    profile = COUNTRY_COMMODITY_EXPOSURE.get(country_id)
    if not profile:
        return {}
    risks = {}
    for commodity_id in profile.keys():
        risk = read_country_supply_risk(country_id, commodity_id)
        if risk:
            risks[commodity_id] = risk
    return risks


# ============================================================================
# LEADER COMMODITY INTERVENTIONS — Detection + Fingerprint I/O
# ============================================================================
# Implementation of the v1.0 detection layer described in the
# LEADER_COMMODITY_INTERVENTIONS module block above.
#
# Pipeline:
#   article → _match_speaker → _match_commodity_in_text → _classify_direction
#           → _classify_rationale → _score_intensity → intervention record
#
# Each detected intervention is buffered per-country during the main scan, then
# the top-N most recent are written to a single per-country Redis fingerprint
# at key 'commodity:leader_interventions:{country_id}' with 12h TTL.
# ============================================================================

LEADER_INTERVENTION_TTL_HOURS = 12   # match supply-risk fingerprint cadence
LEADER_INTERVENTION_MAX_PER_COUNTRY = 10   # cap fingerprint size


def _leader_intervention_redis_key(country_id):
    """Canonical Redis key for the per-country leader intervention fingerprint."""
    return f"commodity:leader_interventions:{country_id}"


def _match_speaker(text):
    """
    Scan article text for a known speaker (canonical name OR alias).
    Case-insensitive. First match wins. Returns (canonical_name, speaker_dict)
    or (None, None) if no match.
    """
    if not text:
        return (None, None)
    text_lower = text.lower()
    for canonical, info in KNOWN_SPEAKERS.items():
        if canonical in text_lower:
            return (canonical, info)
        for alias in info.get('aliases', []):
            if alias.lower() in text_lower:
                return (canonical, info)
    return (None, None)


def _match_commodity_in_text(text):
    """
    Identify which commodity an article is about by scanning COMMODITY_KEYWORDS.
    First match wins. Returns commodity_id or None.

    Note: we deliberately reuse the existing keyword set so interventions stay
    consistent with the broader commodity tracker's understanding of what
    counts as "about gold" / "about oil" / etc.
    """
    if not text:
        return None
    text_lower = text.lower()
    for commodity_id, keyword_set in COMMODITY_KEYWORDS.items():
        # COMMODITY_KEYWORDS is a flat list per commodity (mixed languages)
        for kw in keyword_set:
            if kw.lower() in text_lower:
                return commodity_id
    return None


def _classify_intervention_direction(text):
    """
    Map article text to a direction enum by scanning INTERVENTION_DIRECTION_LEXICON.
    First match wins. Returns direction string or None.
    """
    if not text:
        return None
    text_lower = text.lower()
    for direction, phrases in INTERVENTION_DIRECTION_LEXICON.items():
        for phrase in phrases:
            if phrase.lower() in text_lower:
                return direction
    return None


def _classify_intervention_rationale(text):
    """
    Map article text to a rationale enum by scanning INTERVENTION_RATIONALE_LEXICON.
    First match wins. Returns rationale string or None.
    """
    if not text:
        return None
    text_lower = text.lower()
    for rationale, phrases in INTERVENTION_RATIONALE_LEXICON.items():
        for phrase in phrases:
            if phrase.lower() in text_lower:
                return rationale
    return None


def _score_intervention_intensity(text, direction, rationale):
    """
    Heuristic intensity scoring:
      - 'strong'   = formal exhortation, repeated language, or explicit ask
      - 'moderate' = clear request, single mention
      - 'mild'     = mused / hinted / softer language

    Signals used:
      - 'strong' verbs: "urged", "called on", "demanded", "announced"
      - softeners: "considering", "may", "could", "weighing"
      - presence of a clear rationale = +1 intensity rung
    """
    if not text:
        return 'mild'
    text_lower = text.lower()

    strong_markers = [
        'urged', 'urges', 'called on', 'calls on', 'demanded', 'demands',
        'announced', 'directed', 'ordered', 'declared', 'asked citizens',
        'asked indians', 'appeal to citizens',
    ]
    softener_markers = [
        'considering', 'weighing', 'may ', 'could ', 'might ', 'mused',
        'hinted', 'suggested',
    ]

    has_strong = any(m in text_lower for m in strong_markers)
    has_softener = any(m in text_lower for m in softener_markers)

    if has_strong and not has_softener:
        return 'strong'
    if has_softener and not has_strong:
        return 'mild'
    # Promote intensity by one rung if rationale is explicitly stated
    if rationale and not has_softener:
        return 'strong' if has_strong else 'moderate'
    return 'moderate'


def _get_24h_price_reaction(commodity_id):
    """
    Read the cached 24h price change for a commodity from the sparkline bundle.
    Returns float (pct) or None if not available.

    Leverages the existing sparkline cache — no new yfinance call required.
    """
    try:
        bundle = load_sparkline_cache()
        if not bundle:
            return None
        entry = bundle.get(commodity_id) or {}
        return entry.get('change_pct_1d')
    except Exception:
        return None


def detect_leader_intervention(article):
    """
    Main entrypoint: analyze a single article for a leader commodity intervention.

    Args:
        article: dict with at minimum 'title' and optionally 'description',
                 'url', 'source', 'published', 'language'.

    Returns:
        A structured intervention record (dict) if detected, else None.

    The record includes two reserved fields for Feature B (rhetoric-tracker
    interpretation layer): 'classification_hint' and 'upstream_stressor_hint'.
    Both are None at v1.0 — the rhetoric tracker will populate them later.
    """
    if not article:
        return None

    # Combine title + description for richer matching (description may be empty)
    title = (article.get('title') or '').strip()
    description = (article.get('description') or '').strip()
    if not title:
        return None
    text = f"{title} {description}"

    # Speaker check is the hard gate — if no known speaker is named, it's not
    # an intervention by our definition (we're tracking attributed statements,
    # not anonymous policy moves).
    speaker_name, speaker_info = _match_speaker(text)
    if not speaker_info:
        return None

    # Commodity check — must reference at least one tracked commodity
    commodity_id = _match_commodity_in_text(text)
    if not commodity_id:
        return None

    # Direction check — must have at least one directional phrase
    direction = _classify_intervention_direction(text)
    if not direction:
        return None

    # Rationale is optional but adds analytical value
    rationale = _classify_intervention_rationale(text)
    intensity = _score_intervention_intensity(text, direction, rationale)
    price_reaction = _get_24h_price_reaction(commodity_id)

    # Build the intervention record
    intervention = {
        # Core identification
        'date':                    article.get('published') or datetime.now(timezone.utc).isoformat(),
        'country':                 speaker_info.get('country'),
        'speaker':                 speaker_name.title(),
        'speaker_canonical':       speaker_name,
        'role':                    speaker_info.get('role'),
        'speaker_weight':          speaker_info.get('weight', 1.0),

        # Commodity + classification
        'commodity':               commodity_id,
        'direction':               direction,
        'rationale':               rationale,        # may be None
        'intensity':               intensity,
        'verbal_only':             True,             # v1.0 default; future patches may detect formal-action backing

        # Source provenance — normalize the {'name': '...'} dict shape used
        # throughout this codebase (NewsAPI native shape; mirrored by RSS/GDELT/
        # Brave/Reddit ingesters at lines 915/985/1194/1264). See pattern at
        # line ~1333 in analyze_article_commodity().
        'source_url':              article.get('url'),
        'source_title':            (
            article.get('source', {}).get('name', 'Unknown')
            if isinstance(article.get('source'), dict)
            else (article.get('source') or 'Unknown')
        ),
        'language':                article.get('language', 'en'),
        'quote_short':             title[:180],

        # Market reaction (best-effort)
        'price_reaction_pct_24h':  price_reaction,

        # Stable identity for downstream deduplication / fingerprint refs.
        # Falls back to detected_at if published is missing/empty so we never
        # produce a fingerprint_id with a trailing underscore (would cause
        # same-day same-direction collisions on subsequent calls).
        'fingerprint_id':          (
            f"{speaker_info.get('country')}_{commodity_id}_{direction}_"
            f"{((article.get('published') or datetime.now(timezone.utc).isoformat())[:10].replace('-', '_'))}"
        ),

        # Feature B reservations (populated by future rhetoric-tracker layer)
        'classification_hint':     None,   # 'offensive' | 'defensive' | None
        'upstream_stressor_hint':  None,   # cross-theater fingerprint reference

        # Audit
        'detected_at':             datetime.now(timezone.utc).isoformat(),
    }
    return intervention


def _write_leader_intervention_fingerprint(country_id, interventions):
    """
    Write the per-country leader intervention fingerprint to Upstash Redis.

    Stores up to LEADER_INTERVENTION_MAX_PER_COUNTRY most-recent interventions
    for the country, with a 12h TTL. Skips entirely if Redis isn't configured
    or if there are zero interventions to report.
    """
    if not interventions:
        return False
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False

    # Sort by date desc, cap at MAX_PER_COUNTRY
    sorted_interventions = sorted(
        interventions,
        key=lambda i: i.get('date') or '',
        reverse=True
    )[:LEADER_INTERVENTION_MAX_PER_COUNTRY]

    payload = {
        'country':                  country_id,
        'intervention_count':       len(sorted_interventions),
        'interventions':            sorted_interventions,
        'fingerprint_written_at':   datetime.now(timezone.utc).isoformat(),
        'ttl_hours':                LEADER_INTERVENTION_TTL_HOURS,
    }

    key = _leader_intervention_redis_key(country_id)
    ttl_seconds = LEADER_INTERVENTION_TTL_HOURS * 3600

    try:
        url = f"{UPSTASH_REDIS_URL}/setex/{key}/{ttl_seconds}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(payload, default=str),
            timeout=5
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Leader Interventions] Write error ({key}): {str(e)[:120]}")
        return False


def read_leader_interventions(country_id):
    """
    Read the per-country leader intervention fingerprint from Upstash Redis.

    Returns the payload dict (with 'interventions' list) or None if not present
    or if Redis isn't configured. Mirrors read_country_supply_risk() pattern.

    This is the read-side function that downstream consumers (India rhetoric
    tracker, regional BLUFs, get_commodity_pressure(), etc.) will call.
    """
    if not country_id:
        return None
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None

    key = _leader_intervention_redis_key(country_id)
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5
        )
        if resp.status_code != 200:
            return None
        result = resp.json().get('result')
        if not result:
            return None
        return json.loads(result)
    except Exception as e:
        print(f"[Leader Interventions] Read error ({key}): {str(e)[:120]}")
        return None


# ========================================
# ARTICLE ANALYZER
# ========================================

def analyze_article_commodity(article):
    """
    Analyze a single article for commodity signals.

    Returns:
        {
            'commodities':    [list of commodity_ids matched],
            'countries':      [list of country_ids matched (via exposure mapping)],
            'score':          numeric weight,
            'signals':        [list of structured signal dicts],
        }
    """
    title       = (article.get('title') or '').lower()
    description = (article.get('description') or '').lower()
    content     = (article.get('content') or '').lower()
    text        = f"{title} {description} {content}"

    result = {
        'commodities': set(),
        'countries':   set(),
        'score':       0,
        'signals':     [],
    }

    for commodity_id, keywords in COMMODITY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                result['commodities'].add(commodity_id)
                commodity_data = COMMODITY_TYPES.get(commodity_id, {})

                # Tier-based weight: tier 1 = 1.0, tier 2 = 0.7, tier 3 = 0.5
                tier = commodity_data.get('tier', 3)
                tier_weight = {1: 1.0, 2: 0.7, 3: 0.5}.get(tier, 0.5)

                signal_score = tier_weight

                # Country attribution: any country exposed to this commodity gets the signal.
                # Uses _country_has_commodity() helper to handle both old-style
                # (single role) and new-style (dict-of-roles) registry entries.
                # Note: per-country score weighting happens in _run_full_scan(); we just
                # record the country list here.
                for country_id in COUNTRY_COMMODITY_EXPOSURE.keys():
                    if _country_has_commodity(country_id, commodity_id):
                        result['countries'].add(country_id)

                # Build signal entry
                signal_entry = {
                    'commodity':         commodity_id,
                    'commodity_name':    commodity_data.get('name', commodity_id),
                    'commodity_icon':    commodity_data.get('icon', '📊'),
                    'commodity_tier':    tier,
                    'category':          commodity_data.get('category', 'unknown'),
                    'matched_keyword':   kw,
                    'weight':            round(signal_score, 2),
                    'article_title':     article.get('title', '')[:200],
                    'article_url':       article.get('url', ''),
                    'source':            article.get('source', {}).get('name', 'Unknown'),
                    'published':         article.get('publishedAt', ''),
                    'feed_type':         article.get('feed_type', 'unknown'),
                }
                result['signals'].append(signal_entry)
                result['score'] += signal_score
                break   # one keyword match per commodity per article

    result['commodities'] = list(result['commodities'])
    result['countries']   = list(result['countries'])
    result['score']       = round(result['score'], 2)
    return result


def determine_alert_level(score):
    """Convert raw country-commodity score to alert level."""
    if score >= ALERT_THRESHOLDS['surge']['min_score']:
        return 'surge'
    elif score >= ALERT_THRESHOLDS['high']['min_score']:
        return 'high'
    elif score >= ALERT_THRESHOLDS['elevated']['min_score']:
        return 'elevated'
    return 'normal'


def _domestic_price_stress(commodity_id):
    """Per-commodity domestic staple-price-stress indicator.

    STUB -- returns None. Awaiting the WFP domestic staple-price basket feed.
    Platform discipline (see FFPI section below): never fabricate a placeholder
    stress value. Returns None until a real WFP-measured domestic-price source
    is wired in. The commodity-summary schema already treats None as 'no data'
    (see _build_empty_skeleton, which sets this field to None), and the frontend
    handles None. When the WFP feed lands, compute the real reading here.
    """
    return None


# ========================================
# CONVERGENCE TRIGGER GATE (v1.3.0 -- Jun 2026)
# A convergence's anchor commodity being globally hot is NOT enough to fire
# it. The registry also declares a coupled trigger signal that must be live
# in its regional BLUF (e.g. 'humanitarian_lebanon' in the ME BLUF). These
# helpers read the BLUF's published top_signals[] to confirm that trigger.
# ========================================

# trigger_region -> regional BLUF Redis cache key.
# ME confirmed ('rhetoric:me:regional_bluf'); others follow the same convention.
_BLUF_CACHE_KEYS = {
    'me':     'rhetoric:me:regional_bluf',
    'asia':   'rhetoric:asia:regional_bluf',
    'europe': 'rhetoric:europe:regional_bluf',
    'wha':    'rhetoric:wha:regional_bluf',
    'africa': 'rhetoric:africa:regional_bluf',
}


def _load_bluf_top_signals(region):
    """Fetch a regional BLUF's published top_signals[] from Redis.
    Returns a list, or None if Redis is unreachable / key missing (so callers
    can tell 'no signals' apart from 'could not check')."""
    key = _BLUF_CACHE_KEYS.get(region)
    if not key or not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        raw = resp.json().get('result')
        if not raw:
            return None
        data = json.loads(raw)
        return data.get('top_signals', []) if isinstance(data, dict) else None
    except Exception as e:
        print(f"[Commodity Tracker] BLUF read error ({region}): {str(e)[:120]}")
        return None


def _level_at_least(actual, minimum):
    """Numeric level comparison, tolerant of None / non-numeric inputs.
    If we cannot compare, do not block on level."""
    try:
        return float(actual) >= float(minimum)
    except (TypeError, ValueError):
        return True


def _trigger_signal_state(category, min_level, region_signals):
    """Three-state gate for a convergence's coupled trigger signal:
        'present' -- category found in the BLUF (and >= min_level if given)
        'absent'  -- BLUF readable, category not present at the required level
        'unknown' -- BLUF unreadable (Redis miss/cold); don't fake, don't hide
    region_signals is the prefetched top_signals[] list (or None)."""
    if not category:
        return 'present'                  # entry declares no trigger
    if region_signals is None:
        return 'unknown'                  # could not read the BLUF
    for s in region_signals:
        if isinstance(s, dict) and s.get('category') == category:
            if min_level in (None, '') or _level_at_least(s.get('level'), min_level):
                return 'present'
            return 'absent'               # found, but below required level
    return 'absent'

# ========================================
# SCAN ORCHESTRATOR
# ========================================

def _build_empty_skeleton():
    """Return a valid but empty scan response."""
    commodity_summaries = {}
    for cid, cdata in COMMODITY_TYPES.items():
        commodity_summaries[cid] = {
            'name':           cdata.get('name', cid),
            'icon':           cdata.get('icon', '📊'),
            'tier':           cdata.get('tier', 3),
            'category':       cdata.get('category', 'unknown'),
            'has_spot_price': cdata.get('has_spot_price', False),
            'unit':           cdata.get('unit', ''),
            'description':    cdata.get('description', ''),
            'top_producers':  cdata.get('top_producers', []),
            'top_consumers':  cdata.get('top_consumers', []),
            'chokepoints':    cdata.get('chokepoints', []),
            'sparkline':      None,
            'total_score':    0,
            'signal_count':   0,
            'domestic_price_stress': None,
            'top_signals':    [],
            'alert_level':    'normal',
        }

    country_summaries = {}
    for cid in COUNTRY_COMMODITY_EXPOSURE.keys():
        country_summaries[cid] = {
            'country':           cid,
            'total_score':       0,
            'alert_level':       'normal',
            'commodity_signals': {},
            'top_signals':       [],
        }

    return {
        'success':                  True,
        'scan_time_seconds':        0,
        'days_analyzed':            7,
        'total_articles_scanned':   0,
        'total_signals_detected':   0,
        'commodity_summaries':      commodity_summaries,
        'country_summaries':        country_summaries,
        'top_signals':              [],
        'source_breakdown':         {
            'rss': 0, 'gdelt': 0, 'newsapi': 0, 'reddit': 0, 'brave': 0,
        },
        'last_updated':             datetime.now(timezone.utc).isoformat(),
        'cached':                   False,
        'scan_in_progress':         True,
        'message':                  'Initial scan in progress. Data will appear shortly.',
        'version':                  '1.0.0',
    }


def scan_commodity_pressure(days=7, force_refresh=False):
    """Main entry point — returns full commodity intelligence bundle."""
    if not force_refresh and is_commodity_cache_fresh():
        cache = load_commodity_cache()
        cache['cached'] = True
        print("[Commodity Tracker] Returning fresh cached data")
        return cache

    if not force_refresh:
        stale = load_commodity_cache()
        if stale and 'cached_at' in stale:
            stale['cached'] = True
            stale['stale']  = True
            _trigger_background_scan(days)
            print("[Commodity Tracker] Returning stale cache, background refresh triggered")
            return stale

        print("[Commodity Tracker] No cache found, returning skeleton. Periodic scan will populate.")
        return _build_empty_skeleton()

    return _run_full_scan(days)


def _trigger_background_scan(days=7):
    """Start a background scan if one isn't already running."""
    global _background_scan_running
    with _background_scan_lock:
        if _background_scan_running:
            print("[Commodity Tracker] Background scan already in progress, skipping")
            return
        _background_scan_running = True

    def _do_scan():
        global _background_scan_running
        try:
            print("[Commodity Tracker] Background scan starting...")
            _run_full_scan(days)
        except Exception as e:
            print(f"[Commodity Tracker] Background scan error: {e}")
        finally:
            with _background_scan_lock:
                _background_scan_running = False

    thread = threading.Thread(target=_do_scan, daemon=True)
    thread.start()


def _run_full_scan(days=7):
    """Execute the full scan pipeline."""
    print(f"[Commodity Tracker] Starting fresh scan ({days} days)...")
    scan_start = time.time()

    # Phase 1: fetch all signal sources in parallel-ish sequence
    print("[Commodity Tracker] Phase 1: Fetching data...")
    rss_articles     = fetch_all_commodity_rss()
    gdelt_articles   = fetch_all_gdelt_commodity(days)
    newsapi_articles = fetch_all_newsapi_commodity(days)
    reddit_posts     = fetch_reddit_commodity(days)

    # Brave fallback only fires if GDELT yielded thin results
    brave_articles = []
    if len(gdelt_articles) < 40 and BRAVE_API_KEY:
        print("[Commodity Tracker] GDELT thin — firing Brave fallback...")
        brave_articles = fetch_all_brave_commodity()

    all_articles = (
        rss_articles + gdelt_articles + newsapi_articles
        + reddit_posts + brave_articles
    )
    print(f"[Commodity Tracker] Total articles: {len(all_articles)}")

    # Phase 2: fetch sparklines (cheap, 11 Yahoo calls, cached separately)
    print("[Commodity Tracker] Phase 2: Fetching sparklines...")
    sparklines = fetch_all_sparklines(force=force_refresh if False else False)
    # Note: sparklines have their own 1hr TTL; main scan respects that

    # Phase 3: analyze articles
    print("[Commodity Tracker] Phase 3: Analyzing articles...")
    all_signals = []
    per_commodity_signals = {cid: [] for cid in COMMODITY_TYPES.keys()}
    per_country_signals   = {cid: [] for cid in COUNTRY_COMMODITY_EXPOSURE.keys()}
    per_commodity_score   = {cid: 0  for cid in COMMODITY_TYPES.keys()}
    per_country_score     = {cid: 0  for cid in COUNTRY_COMMODITY_EXPOSURE.keys()}
    # Leader intervention buckets — one list per country; populated alongside
    # the main signal analysis. See LEADER_COMMODITY_INTERVENTIONS module.
    intervention_buckets  = {}   # country_id → list of intervention records

    for article in all_articles:
        # Leader intervention check — runs on every article regardless of
        # whether the commodity-signal analyzer matched. An intervention can
        # be valid even when the article isn't otherwise pressure-scored.
        intervention = detect_leader_intervention(article)
        if intervention:
            ic = intervention.get('country')
            if ic:
                intervention_buckets.setdefault(ic, []).append(intervention)

        analysis = analyze_article_commodity(article)
        if not analysis['signals']:
            continue
        for sig in analysis['signals']:
            all_signals.append(sig)
            cid = sig['commodity']
            if cid in per_commodity_signals:
                per_commodity_signals[cid].append(sig)
                per_commodity_score[cid] += sig['weight']
            for country_id in analysis['countries']:
                if country_id in per_country_signals:
                    # Country signal score weighted by its strongest exposure to this commodity.
                    # For multi-role entries (e.g. China wheat as both #1 producer + #1 consumer),
                    # we use the maximum weight across all roles. Each role gets its own
                    # weighted_sig entry attached to per_country_signals so the country's
                    # commodity tile can show all roles separately.
                    role_exposures = _country_commodity_exposures(country_id, cid)
                    if not role_exposures:
                        continue
                    country_weight = max(e[1].get('weight', 1.0) for e in role_exposures)
                    # Composite role label for display: "producer + consumer" if multi-role
                    role_labels = [r[0] for r in role_exposures]
                    composite_role = ' + '.join(role_labels) if len(role_labels) > 1 else role_labels[0]
                    # Combine notes if multi-role (joined with newline for prose readability)
                    notes = [r[1].get('note', '') for r in role_exposures if r[1].get('note')]
                    composite_note = '\n'.join(notes)
                    weighted_sig = dict(sig)
                    weighted_sig['country_weight'] = country_weight
                    weighted_sig['country_role']   = composite_role
                    weighted_sig['country_note']   = composite_note
                    per_country_signals[country_id].append(weighted_sig)
                    per_country_score[country_id] += sig['weight'] * country_weight

    # Phase 4: build commodity summaries
    commodity_summaries = {}
    for cid, cdata in COMMODITY_TYPES.items():
        sigs = sorted(per_commodity_signals[cid], key=lambda s: s['weight'], reverse=True)
        score = round(per_commodity_score[cid], 2)
        commodity_summaries[cid] = {
            'name':           cdata.get('name', cid),
            'icon':           cdata.get('icon', '📊'),
            'tier':           cdata.get('tier', 3),
            'category':       cdata.get('category', 'unknown'),
            'has_spot_price': cdata.get('has_spot_price', False),
            'unit':           cdata.get('unit', ''),
            'description':    cdata.get('description', ''),
            'top_producers':  cdata.get('top_producers', []),
            'top_consumers':  cdata.get('top_consumers', []),
            'chokepoints':    cdata.get('chokepoints', []),
            'sparkline':      sparklines.get(cid),
            'total_score':    score,
            'signal_count':   len(sigs),
            'top_signals':    sigs[:8],
            'alert_level':    determine_alert_level(score),
            'domestic_price_stress': _domestic_price_stress(cid),
        }

    # Phase 5: build country summaries
    country_summaries = {}
    for cid in COUNTRY_COMMODITY_EXPOSURE.keys():
        sigs = sorted(per_country_signals[cid], key=lambda s: s['weight'], reverse=True)
        score = round(per_country_score[cid], 2)

        # Per-commodity breakdown for this country.
        # New schema: a country may have multiple roles for the same commodity
        # (e.g., China wheat as both producer #1 and consumer #1). The breakdown
        # dict surfaces a "primary" role for legacy frontend display (the
        # exposure matrix renders one cell per commodity), AND a 'roles' list
        # for stability pages that want to show all roles as separate tiles.
        # Primary role selection: producer wins over consumer wins over transit
        # wins over sanctions_target wins over mediator (descending strategic
        # weight). Highest individual weight breaks ties.
        commodity_breakdown = {}
        ROLE_PRIORITY = {'producer': 5, 'component_producer': 4.5, 'consumer': 4, 'transit': 3,
                         'sanctions_target': 2, 'mediator': 1}
        for commodity_id in COUNTRY_COMMODITY_EXPOSURE[cid].keys():
            commodity_sigs = [s for s in sigs if s['commodity'] == commodity_id]
            role_exposures = _country_commodity_exposures(cid, commodity_id)
            if not role_exposures:
                continue
            # Sort roles by priority (then by weight) to identify the primary role
            sorted_roles = sorted(
                role_exposures,
                key=lambda x: (ROLE_PRIORITY.get(x[0], 0), x[1].get('weight', 0)),
                reverse=True
            )
            primary_role_name, primary_role_data = sorted_roles[0]
            # Build the legacy-shape entry for backward compat with frontend
            commodity_breakdown[commodity_id] = {
                'role':         primary_role_name,
                'weight':       primary_role_data.get('weight'),
                'rank':         primary_role_data.get('rank'),
                'note':         primary_role_data.get('note'),
                'signal_count': len(commodity_sigs),
                'top_signals':  commodity_sigs[:3],
                # New schema additions: list of all roles for this commodity
                'roles':        [
                    {
                        'role':   role_name,
                        'weight': role_data.get('weight'),
                        'rank':   role_data.get('rank'),
                        'note':   role_data.get('note'),
                    }
                    for role_name, role_data in sorted_roles
                ],
                'is_multi_role': len(sorted_roles) > 1,
            }

        country_summaries[cid] = {
            'country':            cid,
            'total_score':        score,
            'alert_level':        determine_alert_level(score),
            'commodity_signals':  commodity_breakdown,
            'top_signals':        sigs[:10],
        }

        # ── Cross-tracker fingerprint writes ──
        # For each (country, commodity) pair where signals exist, emit a Redis
        # fingerprint that downstream consumers (rhetoric trackers, regional
        # BLUFs, GPI) can read. Skips empty pairs to keep Redis clean.
        # See module header above _write_supply_risk_fingerprint for full contract.
        for commodity_id, breakdown_entry in commodity_breakdown.items():
            _write_supply_risk_fingerprint(cid, commodity_id, breakdown_entry)

        # ── Leader intervention fingerprint write ──
        # Writes the per-country jawboning fingerprint (top-N most-recent
        # interventions, 12h TTL). Skips entirely if zero interventions detected
        # for this country during the scan.
        country_interventions = intervention_buckets.get(cid, [])
        if country_interventions:
            _write_leader_intervention_fingerprint(cid, country_interventions)

    # Also write interventions for ANY country with detections, even if that
    # country isn't in COUNTRY_COMMODITY_EXPOSURE (e.g. Saudi Arabia, Turkey —
    # speakers are listed in KNOWN_SPEAKERS but full exposure maps may not
    # exist yet). This ensures we never silently drop jawboning signal.
    for unmapped_country, interventions in intervention_buckets.items():
        if unmapped_country not in COUNTRY_COMMODITY_EXPOSURE and interventions:
            _write_leader_intervention_fingerprint(unmapped_country, interventions)

    total_interventions = sum(len(v) for v in intervention_buckets.values())
    if total_interventions:
        print(f"[Commodity Tracker] Leader interventions detected: {total_interventions} "
              f"across {len(intervention_buckets)} countries")

    scan_time = round(time.time() - scan_start, 1)

    # ── PAGE-LEVEL top_signals: round-robin across commodities ──
    # Bug fix May 2 2026: previous logic was sort-by-weight which let one
    # commodity (typically oil) monopolize the top 30. This caused
    # commodities.html bottom feed to show "no signals" for any non-oil
    # commodity even though those commodities had 18-53 signals each.
    # Now: take top N from each commodity, then sort by weight within tier.
    PER_COMMODITY_QUOTA = 5   # each commodity gets up to 5 slots
    diversified_signals = []
    for commodity_id, summary in commodity_summaries.items():
        commodity_top = sorted(
            summary.get('top_signals', []),
            key=lambda s: s.get('weight', 0),
            reverse=True
        )[:PER_COMMODITY_QUOTA]
        diversified_signals.extend(commodity_top)
    # Final sort: by tier (1 first), then by weight within tier
    diversified_signals.sort(
        key=lambda s: (s.get('commodity_tier', 3), -s.get('weight', 0))
    )

    result = {
        'success':                True,
        'scan_time_seconds':      scan_time,
        'days_analyzed':          days,
        'total_articles_scanned': len(all_articles),
        'total_signals_detected': len(all_signals),
        'commodity_summaries':    commodity_summaries,
        'country_summaries':      country_summaries,
        'top_signals':            diversified_signals,
        'source_breakdown': {
            'rss':     len(rss_articles),
            'gdelt':   len(gdelt_articles),
            'newsapi': len(newsapi_articles),
            'reddit':  len(reddit_posts),
            'brave':   len(brave_articles),
        },
        'last_updated':           datetime.now(timezone.utc).isoformat(),
        'cached':                 False,
        'version':                '1.2.0',
    }

    # ── v1.2.0 (May 24 2026) — Active convergence detection ─────
    # Walk the convergence_registry. For each entry, check whether the
    # anchor commodity's alert_level meets the entry's threshold. If so,
    # this convergence is "active" and gets surfaced in the interpreter.
    active_convergences = []
    if CONVERGENCE_REGISTRY_AVAILABLE:
        try:
            # Pre-fetch each regional BLUF's published signals ONCE (a walk may
            # reference several regions; avoid a Redis hit per registry entry).
            _trigger_regions = {
                e.get('trigger_region') for e in CONVERGENCE_REGISTRY
                if e.get('commodity') and e.get('trigger_signal_category')
            }
            bluf_signals_by_region = {
                r: _load_bluf_top_signals(r) for r in _trigger_regions if r
            }

            for entry in CONVERGENCE_REGISTRY:
                anchor_commodity = entry.get('commodity')
                threshold = entry.get('commodity_threshold', 'elevated')

                # Skip non-commodity-driven convergences (commodity=None) —
                # these are regime/diplomatic-axis entries that don't fire
                # off commodity pressure. Future work: wire those via the
                # rhetoric trackers' regime signals.
                if not anchor_commodity:
                    continue

                summary = commodity_summaries.get(anchor_commodity, {})
                actual_level = summary.get('alert_level', 'normal')

                # Gate 1: the anchor commodity must meet the entry's threshold.
                if not alert_meets_threshold(actual_level, threshold):
                    continue

                # Gate 2 (v1.3.0): the coupled trigger signal must actually be
                # live in its regional BLUF. A globally-hot commodity is NOT
                # enough — global wheat at 'elevated' does not by itself mean
                # Lebanon's humanitarian crisis is active. We confirm the
                # trigger ('humanitarian_lebanon' in the ME BLUF) before firing.
                trig_cat = entry.get('trigger_signal_category')
                trig_status = _trigger_signal_state(
                    trig_cat,
                    entry.get('trigger_signal_min_level'),
                    bluf_signals_by_region.get(entry.get('trigger_region')),
                )
                # Commodity hot but coupled trigger confirmed ABSENT -> skip.
                if trig_cat and trig_status == 'absent':
                    continue
                # 'present' -> confirmed firing. 'unknown' (BLUF unreadable) ->
                # surface but flag, so prose can hedge instead of overclaiming.
                trigger_confirmed = (not trig_cat) or (trig_status == 'present')

                # Build a flattened entry the interpreter expects
                headline = format_headline(entry, actual_level) \
                    if entry.get('headline_template') else ''
                active_convergences.append({
                    'id':          entry.get('id'),
                    'commodity':   anchor_commodity,
                    'country':     entry.get('country'),
                    'priority':    entry.get('priority', 0),
                    'icon':        entry.get('icon', '\u26a1'),
                    'color':       entry.get('color', '#f59e0b'),
                    'headline':    headline,
                    'detail':      entry.get('detail', ''),
                    'regions':     entry.get('regions', []),
                    'alert_level': actual_level,
                    'signals':     summary.get('signal_count', 0),
                    'trigger_category':  trig_cat,
                    'trigger_confirmed': trigger_confirmed,
                })
            print(f"[Commodity Tracker] ✅ {len(active_convergences)} active "
                  f"convergence(s) detected from {len(CONVERGENCE_REGISTRY)} "
                  f"registry entries")
        except Exception as conv_err:
            print(f"[Commodity Tracker] Convergence walk error "
                  f"(non-critical): {str(conv_err)[:200]}")
            active_convergences = []
    result['active_convergences'] = active_convergences

    # ── v1.2.0 (May 24 2026) — Analytical prose interpreter ────
    # Mirror of military_tracker.py line 6537 pattern. Builds the
    # executive summary + butterfly + regional prose blocks. Soft-fails
    # so per-commodity / country-exposure data remains authoritative
    # even if interpreter throws.
    if COMM_INTERPRETER_AVAILABLE:
        try:
            interpretation = build_full_commodity_interpretation(result)
            result['interpretation'] = interpretation
            print(f"[Commodity Tracker] ✅ Interpreter generated "
                  f"{len(interpretation.get('butterfly_prose', {}))} butterfly "
                  f"+ {len(interpretation.get('regional_prose', {}))} regional prose blocks")
        except Exception as interp_err:
            print(f"[Commodity Tracker] Interpreter error "
                  f"(non-critical): {str(interp_err)[:200]}")
            result['interpretation'] = None
    else:
        result['interpretation'] = None

    save_commodity_cache(result)
    print(f"[Commodity Tracker] ✅ Scan complete in {scan_time}s")
    print(f"[Commodity Tracker]    Articles: {len(all_articles)}, Signals: {len(all_signals)}")
    print(f"[Commodity Tracker]    Sparklines: {sum(1 for s in sparklines.values() if s)}/{len(COMMODITY_TYPES)}")
    return result


# ========================================
# DASHBOARD INTEGRATION HELPER
# ========================================

# ============================================
# COUNTRY EXPOSURE PROFILE + PROSE BUILDER (Phase 4 Gold Standard)
# ============================================
# Generates the canonical "always-shown" commodity exposure data for any country.
# Returns static profile data (role, rank, note) + plain-English prose summary.
# Independent of live signal data — describes what each country IS, not what's
# happening this week.

def _natural_join(items):
    """Build a comma-separated list with 'and' before the last item."""
    items = [i for i in items if i]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f'{items[0]} and {items[1]}'
    return ', '.join(items[:-1]) + f', and {items[-1]}'


def _build_country_prose(target):
    """
    Generate a plain-English commodity exposure paragraph for a country.
    Reads from COUNTRY_COMMODITY_EXPOSURE — single source of truth.

    Returns a 2-4 sentence summary suitable for a stability page header.
    Falls back to a generic message if country not in registry.

    Schema migration (May 2026): now uses _iter_country_exposures() so
    multi-role entries (e.g. China wheat as both producer + consumer)
    surface in BOTH role buckets in the resulting prose.
    """
    profile = COUNTRY_COMMODITY_EXPOSURE.get(target)
    if not profile:
        return f"{target.title()} commodity exposure profile is not yet registered in the tracker."

    # Bucket commodities by role. Uses _iter_country_exposures() so
    # multi-role entries (e.g. China wheat as both producer + consumer)
    # appear in both buckets.
    producer_items = []
    component_items = []
    consumer_items = []
    transit_items  = []
    for cid, role_name, role_data in _iter_country_exposures(target):
        rank = role_data.get('rank')
        label = cid.replace('_', ' ')
        if rank and role_name in ('producer', 'component_producer'):
            label = f"{label} (#{rank} globally)"
        if role_name == 'producer':
            producer_items.append(label)
        elif role_name == 'component_producer':
            component_items.append(label)
        elif role_name == 'consumer':
            consumer_items.append(label)
        elif role_name == 'transit':
            transit_items.append(label)

    parts = []
    target_name = target.replace('_', ' ').title()

    # Producer sentence
    if producer_items:
        if len(producer_items) == 1:
            parts.append(f"{target_name} is a producer of {producer_items[0]}.")
        else:
            parts.append(f"{target_name} is a producer of {_natural_join(producer_items)}.")

    # Component-producer sentence (assembly / test / packaging nodes)
    if component_items:
        connector = "It is also" if producer_items else f"{target_name} is"
        parts.append(f"{connector} a component / assembly producer of {_natural_join(component_items)}.")

    # Consumer sentence
    if consumer_items:
        if not (producer_items or component_items):
            parts.append(f"{target_name} is a major consumer of {_natural_join(consumer_items)}.")
        else:
            parts.append(f"It is also a major consumer of {_natural_join(consumer_items)}.")

    # Transit sentence
    if transit_items:
        connector = "It is also" if (producer_items or component_items or consumer_items) else f"{target_name} is"
        parts.append(f"{connector} a critical transit point for {_natural_join(transit_items)}.")

    # Country-specific strategic appendix (the "why this matters" sentence)
    appendix = _country_strategic_appendix(target, profile)
    if appendix:
        parts.append(appendix)

    return ' '.join(parts)


def _country_strategic_appendix(target, profile):
    """
    Country-specific strategic context line. Hand-tuned per country for
    the unique geopolitical narrative each commodity profile implies.
    Returns empty string if no special context applies.
    """
    appendices = {
        'iran': (
            "Iran's primary commodity leverage is the Strait of Hormuz, through which "
            "approximately 20% of global oil transit passes. Its wheat dependency creates "
            "domestic stability risk (1979 Revolution echo); its gold trade is the primary "
            "sanctions evasion vehicle."
        ),
        'lebanon': (
            "Lebanon's commodity vulnerability is structural — zero domestic refining capacity, "
            "destroyed national grain silos (2020 Beirut port), and acute Black Sea import "
            "dependency. Any combined wheat + fuel disruption translates directly to "
            "street-level crisis. Mediterranean offshore exploration represents long-term "
            "upside but no commercial production yet."
        ),
        'israel': (
            "Israel is structurally tied to global supply chains — Mediterranean shipping, "
            "Black Sea grain, and the Eilat-Ashkelon pipeline are single-points-of-failure for "
            "food and fuel security. Domestic natural gas production (Leviathan/Tamar) provides "
            "energy autonomy; consumer-side wheat and oil exposure remains the coalition stress lever."
        ),
        'ukraine': (
            "Ukraine's pre-war agricultural exports anchored the Black Sea grain corridor — "
            "wartime disruption directly impacts MENA food security (Egypt, Lebanon, Yemen). "
            "Recovery of corridor capacity is the single largest commodity-flow signal in Europe."
        ),
        'russia': (
            "Russia's commodity profile is structural global leverage — #1 wheat exporter, "
            "#2 oil and gas producer, and a vehicle for sanctions-evading gold trade. "
            "Western sanctions reroute (not replace) these flows."
        ),
        'china': (
            "China's commodity profile is dual-natured — dominant rare earth + cobalt refining "
            "creates supply leverage, while soybean and oil consumption creates demand-side "
            "vulnerability. Trade war pressure points cut both ways."
        ),
        'belarus': (
            "Belarus's potash production (Belaruskali) was sanctioned in 2021 but rebuilt routing "
            "via Russian ports + China rail. Druzhba pipeline transit and Russian gas dependency "
            "lock Belarus into the Russian commodity ecosystem."
        ),
        'chile': (
            "Chile is the structural anchor of the global energy-transition supply chain — "
            "#1 copper producer (~24% global) and #2 lithium producer (~23% global), with the "
            "Salar de Atacama representing the highest-grade lithium brine deposit on Earth. "
            "Domestic political volatility (Boric-era constitutional process, mining royalty "
            "reform, 2023 National Lithium Strategy) translates directly into global EV and "
            "grid-electrification pricing. Watch: SQM/Codelco production guidance, Antofagasta "
            "labor disputes, lithium nationalization rhetoric."
        ),
        'peru': (
            "Peru's commodity profile is concentrated mining vulnerability — #3 silver producer "
            "with the world's largest silver reserves per USGS, plus major copper output from "
            "Antamina and Toromocho. The structural risk is political: presidential instability "
            "(multiple presidents since 2022), Las Bambas mining-region community blockades, "
            "and VRAEM-zone insecurity all translate directly into supply disruption signals. "
            "Mining accounts for ~60% of Peruvian export earnings — instability there is "
            "instability in the global silver and copper price discovery."
        ),
    }
    return appendices.get(target, '')

def get_commodity_pressure(target):
    """
    Quick lookup for a country stability page. Returns the country's
    commodity exposure summary, ready to drop into a stability page card.

    Phase 4 Gold Standard contract:
      - ALWAYS returns the static exposure profile (one tile per registered commodity)
      - ALWAYS returns the prose paragraph
      - When live signal data is available, tiles upgrade with alert badges + sparklines
      - When no live signal data, tiles show 'normal' alert + structural exposure data only

    Mirrors get_military_posture(target) signature.
    """
    target = (target or '').lower().strip()
    try:
        # ── Static exposure profile (always available) ──
        profile = COUNTRY_COMMODITY_EXPOSURE.get(target)
        if not profile:
            return {
                'success':              True,
                'country':              target,
                'commodity_pressure':   None,
                'message':              f'No commodity exposure mapping for {target}. Country not yet registered.',
                'commodity_summaries':  [],
                'top_signals':          [],
                'alert_level':          'normal',
                'prose':                _build_country_prose(target),
            }

        # ── Live signal data (best-effort; fall back to static profile if scan fails) ──
        try:
            data = scan_commodity_pressure()
        except Exception as scan_err:
            print(f"[Commodity Pressure] Live scan failed for {target}, falling back to static profile: {scan_err}")
            data = {'country_summaries': {}, 'commodity_summaries': {}, 'last_updated': None}

        country = data.get('country_summaries', {}).get(target, {}) or {}
        country_signals = country.get('commodity_signals', {}) or {}

        # ── Build commodity_summaries: ONE TILE PER (commodity, role) pair ──
        # If a country has multiple roles for the same commodity (e.g. China
        # wheat producer + consumer), each role becomes its own tile. This is
        # Option α from the schema migration design — full analytical fidelity
        # on stability pages.
        # If live signal data exists for that commodity, the tile inherits the
        # commodity-level live data (signals are commodity-scoped, not
        # role-scoped). Otherwise fall back to static.
        commodity_summaries = []
        for commodity_id in profile.keys():
            full_summary = data.get('commodity_summaries', {}).get(commodity_id, {}) or {}
            live_breakdown = country_signals.get(commodity_id, {}) or {}
            role_exposures = _country_commodity_exposures(target, commodity_id)

            for role_name, role_data in role_exposures:
                # Static fields (always from registry)
                tile = {
                    'commodity':            commodity_id,
                    'name':                 full_summary.get('name', commodity_id.replace('_', ' ').title()),
                    'icon':                 full_summary.get('icon', '📊'),
                    'tier':                 full_summary.get('tier'),
                    'category':             full_summary.get('category'),
                    'role':                 role_name,
                    'rank':                 role_data.get('rank'),
                    'note':                 role_data.get('note'),
                    'has_spot_price':       full_summary.get('has_spot_price'),
                    'unit':                 full_summary.get('unit'),
                    'sparkline':            full_summary.get('sparkline'),
                    # Live signal fields (commodity-scoped, shared across roles)
                    'signal_count':         live_breakdown.get('signal_count', 0),
                    'top_signals':          live_breakdown.get('top_signals', []),
                    'global_alert_level':   full_summary.get('alert_level', 'normal'),
                    'global_signal_count':  full_summary.get('signal_count', 0),
                    'global_total_score':   full_summary.get('total_score', 0),
                    # Schema-migration metadata: True if this country has
                    # multiple roles for this commodity (rendered as separate
                    # tiles, but UI may want to group them visually)
                    'is_multi_role_commodity': len(role_exposures) > 1,
                    'role_count_for_commodity': len(role_exposures),
                }
                commodity_summaries.append(tile)

        # Sort: producers (with rank) first by rank, then transit, then consumers
        def _sort_key(t):
            role_priority = {'producer': 0, 'transit': 1, 'consumer': 2}.get(t.get('role'), 3)
            rank = t.get('rank') or 999
            return (role_priority, rank)
        commodity_summaries.sort(key=_sort_key)

        # ── Leader interventions (jawboning) — read from Redis fingerprint ──
        # Best-effort: if read fails or fingerprint is absent, we return an
        # empty list rather than failing the whole response.
        leader_interventions_payload = read_leader_interventions(target) or {}
        leader_interventions_list = leader_interventions_payload.get('interventions', [])

        return {
            'success':              True,
            'country':              target,
            'commodity_pressure':   country.get('total_score', 0),
            'alert_level':          country.get('alert_level', 'normal'),
            'commodity_summaries':  commodity_summaries,
            'top_signals':          country.get('top_signals', [])[:8],
            'leader_interventions': leader_interventions_list,
            'leader_intervention_count': len(leader_interventions_list),
            'detail_url':           '/commodities.html',
            'last_updated':         data.get('last_updated'),
            'prose':                _build_country_prose(target),
            'profile_count':        len(profile),
            'has_live_data':        bool(country),
        }

    except Exception as e:
        print(f"[Commodity Pressure] Error for {target}: {str(e)[:200]}")
        # Even on error, try to return the static profile for graceful degradation
        try:
            return {
                'success':            False,
                'country':            target,
                'commodity_pressure': 0,
                'alert_level':        'normal',
                'commodity_summaries': [],
                'top_signals':        [],
                'error':              str(e)[:120],
                'prose':              _build_country_prose(target),
            }
        except Exception:
            return {
                'success':            False,
                'country':            target,
                'commodity_pressure': 0,
                'alert_level':        'normal',
                'commodity_summaries': [],
                'top_signals':        [],
                'error':              str(e)[:120],
            }


# ========================================
# FAO FOOD PRICE INDEX (FFPI) — Stage 1b
# ========================================
# Real, dynamically-fetched FAO Food Price Index (current 2014-2016=100 base).
# Source: https://www.fao.org/worldfoodsituation/foodpricesindex/en
# Layered fetch (mirrors Nigeria NGX pattern):
#   (1) Parse live FAO page  ->  (2) Redis last-known-good  ->  (3) Unavailable
# NEVER returns a hardcoded placeholder number. FFPI is monthly (1st Thursday),
# so a 12h Redis TTL is comfortably fresh and survives FAO outages.
#
# NOTE: We deliberately do NOT use fileadmin/.../Food_price_indices_data.csv —
# that legacy file is still on the OLD 2002-2004=100 base and would not match
# the published current-base values.

FFPI_REDIS_KEY      = 'ffpi_cache'
FFPI_CACHE_TTL_HOURS = 12
FFPI_SOURCE_URL     = 'https://www.fao.org/worldfoodsituation/foodpricesindex/en'

# Sub-index display metadata (canonical order + icons)
FFPI_SUBINDICES = [
    ('cereal',        'Cereals',        '🌾'),
    ('vegetable_oil', 'Vegetable Oils', '🫒'),
    ('dairy',         'Dairy',          '🥛'),
    ('meat',          'Meat',           '🥩'),
    ('sugar',         'Sugar',          '🍬'),
]


def _ffpi_strip_html(html):
    """Strip tags + decode entities + collapse whitespace so prose regexes match cleanly.

    FAO's markup is inconsistent: the Cereal line sometimes separates 'Index' and
    'averaged' with a &nbsp; entity, which is literal text (not whitespace) and was
    silently breaking the cereal sub-index parse. Decoding entities + normalizing the
    non-breaking space char fixes it for all five sub-indices.
    """
    import html as _htmlmod  # aliased — the 'html' parameter shadows the module name
    text = re.sub(r'<[^>]+>', ' ', html or '')
    text = _htmlmod.unescape(text)     # &nbsp; &amp; &#160; -> real characters
    text = text.replace('\xa0', ' ')   # non-breaking space -> normal space
    text = re.sub(r'\s+', ' ', text)
    return text


def _parse_ffpi_page(html):
    """
    Parse the FAO FFPI page prose into a structured dict.
    Returns None if the headline FFPI value can't be found (treat as fetch miss).
    Validated against live FAO text (Feb 2026 release).
    """
    text = _ffpi_strip_html(html)
    if not text:
        return None

    # Headline FFPI value + month, e.g. "FFPI) averaged 125.3 points in February 2026"
    m = re.search(r'FFPI\)\s*averaged\s+([\d.]+)\s+points\s+in\s+([A-Z][a-z]+\s+\d{4})', text)
    if not m:
        return None

    out = {
        'ffpi':   float(m.group(1)),
        'month':  m.group(2),
        'base':   '2014-2016=100',
        'subindices': {},
    }

    # Month-on-month change immediately following the headline value
    tail = text[m.end():m.end() + 90]
    mom = re.search(r'(up|down)\s+([\d.]+)\s+points\s+\(([\d.]+)\s+percent\)', tail)
    if mom:
        sign = 1.0 if mom.group(1) == 'up' else -1.0
        out['mom_points']  = round(sign * float(mom.group(2)), 1)
        out['mom_percent'] = round(sign * float(mom.group(3)), 1)
        out['direction']   = mom.group(1)

    # Five sub-indices, e.g. "FAO Cereal Price Index averaged 108.6 points in February"
    for key, label, _icon in FFPI_SUBINDICES:
        # 'cereal' -> 'Cereal', 'vegetable_oil' -> 'Vegetable Oil'
        grp = ' '.join(w.capitalize() for w in key.split('_'))
        sm = re.search(rf'FAO\s+{re.escape(grp)}\s+Price\s+Index\s*averaged\s+([\d.]+)\s+points', text)
        if sm:
            out['subindices'][key] = float(sm.group(1))

    # Release date, e.g. "Release date: 06/03/2026"
    rd = re.search(r'Release date:\s*(\d{2}/\d{2}/\d{4})', text)
    if rd:
        out['release_date'] = rd.group(1)

    return out


def _ffpi_redis_get():
    """Read last-known-good FFPI bundle from Redis (with freshness flag)."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{FFPI_REDIS_KEY}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
    except Exception as e:
        print(f"[FFPI] Redis load error: {e}")
    return None


def _ffpi_redis_set(bundle):
    """Persist FFPI bundle to Redis as last-known-good."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return
    try:
        requests.post(
            f"{UPSTASH_REDIS_URL}/set/{FFPI_REDIS_KEY}",
            headers={
                "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                "Content-Type": "application/json",
            },
            data=json.dumps(bundle, default=str),
            timeout=10,
        )
        print("[FFPI] ✅ Saved to Redis")
    except Exception as e:
        print(f"[FFPI] Redis save error: {e}")


def _ffpi_is_fresh(bundle):
    """True if a cached bundle is within TTL."""
    try:
        ts = datetime.fromisoformat(bundle['fetched_at'])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < (FFPI_CACHE_TTL_HOURS * 3600)
    except Exception:
        return False


def get_ffpi(force=False):
    """
    Layered FFPI fetch:
      (1) Redis fresh-cache hit (unless force)
      (2) Live FAO page parse  -> cache + return
      (3) Redis stale last-known-good (flagged stale)
      (4) Unavailable honest state (status='unavailable', value=None)
    """
    # (1) Fresh cache
    cached = _ffpi_redis_get()
    if cached and not force and _ffpi_is_fresh(cached):
        cached['status'] = 'cached'
        return cached

    # (2) Live fetch + parse
    try:
        resp = requests.get(
            FFPI_SOURCE_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AsifahAnalytics/1.0)"},
            timeout=15,
        )
        if resp.status_code == 200:
            parsed = _parse_ffpi_page(resp.text)
            if parsed and parsed.get('ffpi'):
                parsed['status']      = 'live'
                parsed['source']      = 'FAO Food Price Index'
                parsed['source_url']  = FFPI_SOURCE_URL
                parsed['fetched_at']  = datetime.now(timezone.utc).isoformat()
                _ffpi_redis_set(parsed)
                print(f"[FFPI] ✅ Live: {parsed['ffpi']} ({parsed.get('month')})")
                return parsed
            print("[FFPI] Live fetch parsed no headline value — falling back")
        else:
            print(f"[FFPI] Live fetch HTTP {resp.status_code} — falling back")
    except Exception as e:
        print(f"[FFPI] Live fetch error: {e} — falling back")

    # (3) Stale last-known-good
    if cached and cached.get('ffpi'):
        cached['status'] = 'stale'
        print(f"[FFPI] Serving STALE cache ({cached.get('month')})")
        return cached

    # (4) Honest unavailable
    return {
        'status':     'unavailable',
        'ffpi':       None,
        'source':     'FAO Food Price Index',
        'source_url': FFPI_SOURCE_URL,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
    }


# ========================================
# FLASK ENDPOINT REGISTRATION
# ========================================

# ============================================================
# COMMODITY -> GPI ECONOMIC AXIS (BLUF emitter)  [Jun 2026]
# ------------------------------------------------------------
# Emits a BLUF-shaped payload at /api/commodity-pressure/bluf that GPI
# consumes via REGIONAL_BLUF_ENDPOINTS as the 'global_commodity' pseudo-
# region. Signals are tagged pressure_type='economic' so GPI routes them
# into the economic axis with ZERO GPI-side changes (same pattern as the
# cascade + humanitarian pseudo-regions).
#
# Two gates keep the axis meaningful, not just loud:
#   1. THRESHOLD  -- only 'high'/'surge' commodities surface.
#   2. RELEVANCE  -- a surge must be corroborated by >=1 commodity-SPECIFIC
#      signal: a multi-word matched phrase ('sugar futures', 'crude oil') or
#      a non-contamination-prone single token ('bauxite', 'urea'). A surge
#      driven ONLY by a bare common word ('sugar' -> a celebrity, 'gold' -> a
#      medal) is treated as keyword contamination and dropped. This gate lives
#      at the BLUF layer only; raw commodity scores/cards are untouched.
# ============================================================

# Bare single-word commodity names that collide with everyday English / names.
# A surge driven ONLY by these (no specific phrase) is likely contamination.
_CONTAMINATION_PRONE_BARE = {
    'sugar', 'gold', 'silver', 'copper', 'diamond', 'diamonds',
    'nickel', 'oil', 'corn', 'tin', 'lead', 'platinum',
    'rice',   # Jul 18 2026: bare 'rice' substring-matches "p(rice)s" -- e.g. a
              # gasoline "prices" headline bled into the rice driver. The specific
              # compounds ('rice prices', 'rice futures', ...) still detect rice.
}

def _is_hard_commodity_signal(sig):
    """True if the signal is genuinely about the commodity: matched keyword is
    a multi-word phrase (inherently specific) OR a single jargon token that is
    not a contamination-prone common word."""
    kw = (sig.get('matched_keyword') or '').strip().lower()
    if not kw:
        return False
    if ' ' in kw:
        return True
    return kw not in _CONTAMINATION_PRONE_BARE

_COMMODITY_BLUF_LEVEL = {'surge': 5, 'high': 4, 'elevated': 3, 'normal': 0}
_COMMODITY_BLUF_COLOR = {5: '#dc2626', 4: '#f97316', 3: '#f59e0b', 0: '#6b7280'}

_COUNTRY_LABEL_OVERRIDES = {'usa': 'USA', 'uae': 'UAE', 'eu': 'EU', 'uk': 'UK', 'drc': 'DRC'}
def _commodity_country_label(cid):
    c = str(cid).strip().lower()
    return _COUNTRY_LABEL_OVERRIDES.get(c, c.replace('_', ' ').title())

def build_commodity_economic_bluf(bundle=None):
    """Build a GPI-consumable BLUF from current commodity pressure.

    Surfaces only high/surge commodities whose surge passes the relevance gate,
    each anchored with a plain-language So-What naming the exposed importers.
    All signals tagged pressure_type='economic'.
    """
    if bundle is None:
        bundle = scan_commodity_pressure(days=7, force_refresh=False)
    summaries = (bundle or {}).get('commodity_summaries', {}) or {}

    signals = []
    for cid, summ in summaries.items():
        alert = summ.get('alert_level', 'normal')
        if alert not in ('high', 'surge'):
            continue                                   # gate 1: threshold
        top_sigs = summ.get('top_signals', []) or []
        hard = [s for s in top_sigs if _is_hard_commodity_signal(s)]
        if not hard:
            continue                                   # gate 2: relevance (drop contamination)

        level = _COMMODITY_BLUF_LEVEL.get(alert, 0)
        color = _COMMODITY_BLUF_COLOR.get(level, '#6b7280')
        name  = summ.get('name', cid)
        icon  = summ.get('icon', '\U0001F4C8')
        driver = (hard[0].get('article_title') or '').strip()
        consumers = [_commodity_country_label(c) for c in (summ.get('top_consumers') or [])[:3]]
        cons_txt = ', '.join(consumers) if consumers else 'import-dependent economies'

        short_text = (f"{icon} {name} news-signal pressure {alert.upper()} "
                      f"-- exposed importers: {cons_txt}")[:150]
        long_parts = []
        if driver:
            long_parts.append(f"Driver: {driver}.")
        long_parts.append(
            f"{name} news-signal pressure ({alert}) reflects weighted volume/severity "
            f"of matched commodity reporting -- not price.")
        long_parts.append(
            "SO WHAT: supply stress here transmits to import-dependent economies"
            + (f" -- most exposed: {cons_txt}." if consumers else "."))
        long_text = ' '.join(long_parts)

        signals.append({
            'category':          f'commodity_{cid}',
            'commodity':         cid,
            'theatre':           'global_commodity',
            'region':            'global_commodity',
            'level':             level,
            'pressure_type':     'economic',           # routes into GPI economic axis
            'icon':              icon,
            'color':             color,
            'short_text':        short_text,
            'long_text':         long_text,
            'priority':          level * 3,
            'exposed_consumers': consumers,
            'score':             summ.get('total_score'),
        })

    signals.sort(key=lambda s: -s['level'])
    max_level = signals[0]['level'] if signals else 0
    posture_label = {5: 'Surge', 4: 'High'}.get(max_level, 'Monitoring')
    posture_color = _COMMODITY_BLUF_COLOR.get(max_level, '#6b7280')

    return {
        'region':        'global_commodity',
        'max_level':     max_level,
        'peak_level':    max_level,
        'posture_label': posture_label,
        'posture_color': posture_color,
        'top_signals':   signals[:5],
        'signals':       signals,
        'updated_at':    datetime.now(timezone.utc).isoformat(),
        'disclaimer':    ('Economic CONVERGENCE/EXPOSURE indicator built from news-signal '
                          'pressure (weighted reporting volume/severity), NOT a price forecast. '
                          'Surfaces only commodities with a supply-relevant driver and '
                          'import-dependent exposure.'),
        'meta': {
            'commodities_surfaced': [s['commodity'] for s in signals],
            'emitter_version':      'commodity_economic_bluf v1.0.0',
            'gate':                 'high/surge + specific-phrase relevance',
        },
    }


def register_commodity_endpoints(app, start_background=True):
    """
    Register commodity tracker endpoints with the Flask app.

    Endpoints:
      GET  /api/commodity-pressure              full bundle (commodities + countries)
      GET  /api/commodity-pressure/<target>     per-country summary (for stability pages)
      GET  /api/commodity-prices                sparklines only (lightweight)

    Parameters:
        app: Flask app instance
        start_background: If True (default), spawn a periodic scan thread
                          that refreshes the cache every 12 hours.
                          Set to False on read-only backends sharing Redis.
    """

    @app.route('/api/commodity-pressure', methods=['GET', 'OPTIONS'])
    def api_commodity_pressure():
        """Full commodity intelligence bundle for commodities.html."""
        from flask import request as flask_request

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            days    = int(flask_request.args.get('days', 7))
            refresh = flask_request.args.get('refresh', 'false').lower() == 'true'

            if refresh:
                _trigger_background_scan(days)
            result = scan_commodity_pressure(days=days, force_refresh=False)
            return app.response_class(
                response=json.dumps(result, default=str),
                status=200,
                mimetype='application/json',
            )
        except Exception as e:
            print(f"[Commodity API] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return app.response_class(
                response=json.dumps({'success': False, 'error': str(e)[:200]}),
                status=500,
                mimetype='application/json',
            )

    @app.route('/api/commodity-pressure/<target>', methods=['GET', 'OPTIONS'])
    def api_commodity_pressure_target(target):
        """Quick commodity-pressure check for a specific country."""
        from flask import request as flask_request

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            pressure = get_commodity_pressure(target)
            return app.response_class(
                response=json.dumps(pressure, default=str),
                status=200,
                mimetype='application/json',
            )
        except Exception as e:
            return app.response_class(
                response=json.dumps({'success': False, 'error': str(e)[:200]}),
                status=500,
                mimetype='application/json',
            )

    @app.route('/api/commodity-pressure/bluf', methods=['GET', 'OPTIONS'])
    def api_commodity_pressure_bluf():
        """BLUF-shaped payload consumed by GPI as the 'global_commodity'
        economic pseudo-region. Built from cached commodity pressure; gated to
        high/surge commodities with a real supply-relevant driver + exposure."""
        from flask import request as flask_request
        if flask_request.method == 'OPTIONS':
            return '', 200
        try:
            bluf = build_commodity_economic_bluf()
            return app.response_class(
                response=json.dumps(bluf, default=str),
                status=200, mimetype='application/json')
        except Exception as e:
            print(f"[Commodity BLUF] Error: {str(e)}")
            return app.response_class(
                response=json.dumps({
                    'region': 'global_commodity', 'max_level': 0,
                    'posture_label': 'Monitoring', 'top_signals': [], 'signals': [],
                    'error': str(e)[:200],
                }),
                status=200, mimetype='application/json')   # 200 so GPI treats as baseline

    @app.route('/api/commodity-prices', methods=['GET', 'OPTIONS'])
    def api_commodity_prices():
        """Lightweight: just sparklines + current prices, no news context."""
        from flask import request as flask_request

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            force = flask_request.args.get('force', 'false').lower() == 'true'
            sparklines = fetch_all_sparklines(force=force)
            payload = {
                'success':       True,
                'sparklines':    sparklines,
                'commodity_meta': {
                    cid: {
                        'name':           c.get('name'),
                        'icon':           c.get('icon'),
                        'tier':           c.get('tier'),
                        'category':       c.get('category'),
                        'has_spot_price': c.get('has_spot_price'),
                        'unit':           c.get('unit'),
                    } for cid, c in COMMODITY_TYPES.items()
                },
                'last_updated':  datetime.now(timezone.utc).isoformat(),
            }
            return app.response_class(
                response=json.dumps(payload, default=str),
                status=200,
                mimetype='application/json',
            )
        except Exception as e:
            return app.response_class(
                response=json.dumps({'success': False, 'error': str(e)[:200]}),
                status=500,
                mimetype='application/json',
            )

    @app.route('/api/food-price-index', methods=['GET', 'OPTIONS'])
    def api_food_price_index():
        """FAO Food Price Index (FFPI) — headline + 5 sub-indices. Stage 1b."""
        from flask import request as flask_request

        if flask_request.method == 'OPTIONS':
            return '', 200

        try:
            force = flask_request.args.get('force', 'false').lower() == 'true'
            ffpi = get_ffpi(force=force)
            # Attach display metadata for the sub-indices (icons + labels + order)
            ffpi['subindex_meta'] = [
                {'key': k, 'label': lbl, 'icon': ic} for k, lbl, ic in FFPI_SUBINDICES
            ]
            payload = {'success': True, 'ffpi': ffpi}
            return app.response_class(
                response=json.dumps(payload, default=str),
                status=200,
                mimetype='application/json',
            )
        except Exception as e:
            return app.response_class(
                response=json.dumps({'success': False, 'error': str(e)[:200]}),
                status=500,
                mimetype='application/json',
            )

    @app.route('/api/commodity-debug', methods=['GET'])
    def api_commodity_debug():
        """Diagnostic — config snapshot + cache freshness."""
        from flask import jsonify
        return jsonify({
            'version':                '1.1.0',
            'commodity_count':        len(COMMODITY_TYPES),
            'commodities':            list(COMMODITY_TYPES.keys()),
            'country_exposure_count': len(COUNTRY_COMMODITY_EXPOSURE),
            'countries_mapped':       list(COUNTRY_COMMODITY_EXPOSURE.keys()),
            'rss_feeds':              len(COMMODITY_RSS_FEEDS),
            'reddit_subs':            len(COMMODITY_REDDIT_SUBREDDITS),
            'yfinance_available':     YFINANCE_AVAILABLE,
            'newsapi_configured':     bool(NEWSAPI_KEY),
            'brave_configured':       bool(BRAVE_API_KEY),
            'redis_configured':       bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'main_cache_fresh':       is_commodity_cache_fresh(),
            'sparkline_cache_fresh':  is_sparkline_cache_fresh(),
            'main_cache_ttl_hours':   COMMODITY_CACHE_TTL_HOURS,
            'sparkline_cache_ttl_hours': SPARKLINE_CACHE_TTL_HOURS,
            # Leader Interventions module (v1.0)
            'leader_interventions_enabled':        True,
            'known_speakers_count':                len(KNOWN_SPEAKERS),
            'known_speakers_countries':            sorted(list({s.get('country') for s in KNOWN_SPEAKERS.values()})),
            'intervention_keyword_languages':      list(LEADER_INTERVENTION_KEYWORDS.keys()),
            'intervention_direction_enum_count':   len(INTERVENTION_DIRECTION_LEXICON),
            'intervention_rationale_enum_count':   len(INTERVENTION_RATIONALE_LEXICON),
            'intervention_fingerprint_ttl_hours':  LEADER_INTERVENTION_TTL_HOURS,
        })

    @app.route('/api/commodity-fingerprint/<country>/<commodity>', methods=['GET'])
    def api_commodity_fingerprint_single(country, commodity):
        """
        Read a single (country, commodity) supply-risk fingerprint from Redis.
        Returns null if no current pressure or no fingerprint exists.
        Useful for debugging the cross-tracker fingerprint contract.
        """
        from flask import jsonify
        country = country.lower().strip()
        commodity = commodity.lower().strip()
        risk = read_country_supply_risk(country, commodity)
        return jsonify({
            'country': country,
            'commodity': commodity,
            'fingerprint': risk,
            'has_pressure': risk is not None,
        })

    @app.route('/api/commodity-fingerprint/<country>', methods=['GET'])
    def api_commodity_fingerprint_country(country):
        """
        Read all supply-risk fingerprints for a country.
        Returns an object with one entry per commodity that currently has
        pressure (signal_count > 0). Empty if no pressure.
        """
        from flask import jsonify
        country = country.lower().strip()
        risks = read_all_supply_risks_for_country(country)
        registry = COUNTRY_COMMODITY_EXPOSURE.get(country, {})
        return jsonify({
            'country': country,
            'registered_commodities': list(registry.keys()),
            'commodities_with_pressure': list(risks.keys()),
            'fingerprints': risks,
            'pressure_count': len(risks),
        })

    # ========================================================================
    # LEADER COMMODITY INTERVENTIONS — Endpoints
    # ========================================================================
    # /api/leader-interventions/<country>       → all interventions for 1 country
    # /api/leader-interventions/commodity/<id>  → cross-country, 1 commodity
    # /api/leader-interventions                 → global feed, all interventions

    @app.route('/api/leader-interventions/<country>', methods=['GET', 'OPTIONS'])
    def api_leader_interventions_country(country):
        """
        Return all current leader interventions for a single country.
        Reads the per-country fingerprint from Redis (12h TTL).
        """
        from flask import request as flask_request, jsonify
        if flask_request.method == 'OPTIONS':
            return '', 200
        country = (country or '').lower().strip()
        payload = read_leader_interventions(country) or {}
        interventions = payload.get('interventions', [])
        return jsonify({
            'success':            True,
            'country':            country,
            'intervention_count': len(interventions),
            'interventions':      interventions,
            'fingerprint_meta':   {
                'written_at':  payload.get('fingerprint_written_at'),
                'ttl_hours':   payload.get('ttl_hours'),
            },
            'last_updated':       datetime.now(timezone.utc).isoformat(),
        })

    @app.route('/api/leader-interventions/commodity/<commodity>', methods=['GET', 'OPTIONS'])
    def api_leader_interventions_commodity(commodity):
        """
        Cross-country view: all current leader interventions affecting one
        commodity. Iterates known speakers' countries, reads each fingerprint,
        filters to records where intervention['commodity'] matches.
        """
        from flask import request as flask_request, jsonify
        if flask_request.method == 'OPTIONS':
            return '', 200
        commodity = (commodity or '').lower().strip()
        if commodity not in COMMODITY_TYPES:
            return jsonify({
                'success': False,
                'error':   f"Unknown commodity '{commodity}'. Known: {list(COMMODITY_TYPES.keys())}",
            }), 400

        # Collect candidate countries — every country that has a known speaker
        # OR a registered commodity exposure. Union is intentional so we don't
        # miss speakers from countries without a full exposure map yet.
        candidate_countries = set(COUNTRY_COMMODITY_EXPOSURE.keys())
        for spk in KNOWN_SPEAKERS.values():
            c = spk.get('country')
            if c:
                candidate_countries.add(c)

        matching = []
        for c in candidate_countries:
            payload = read_leader_interventions(c) or {}
            for iv in payload.get('interventions', []):
                if iv.get('commodity') == commodity:
                    matching.append(iv)

        # Sort newest first
        matching.sort(key=lambda i: i.get('date') or '', reverse=True)

        return jsonify({
            'success':            True,
            'commodity':          commodity,
            'commodity_name':     COMMODITY_TYPES.get(commodity, {}).get('name', commodity),
            'commodity_icon':     COMMODITY_TYPES.get(commodity, {}).get('icon', '📊'),
            'intervention_count': len(matching),
            'interventions':      matching,
            'countries_with_intervention': sorted(list({i.get('country') for i in matching if i.get('country')})),
            'last_updated':       datetime.now(timezone.utc).isoformat(),
        })

    @app.route('/api/leader-interventions', methods=['GET', 'OPTIONS'])
    def api_leader_interventions_global():
        """
        Global feed: every current intervention across every country, newest
        first. Convenience endpoint for commodities.html's global panel and
        future GPI consumption.
        """
        from flask import request as flask_request, jsonify
        if flask_request.method == 'OPTIONS':
            return '', 200

        candidate_countries = set(COUNTRY_COMMODITY_EXPOSURE.keys())
        for spk in KNOWN_SPEAKERS.values():
            c = spk.get('country')
            if c:
                candidate_countries.add(c)

        all_interventions = []
        countries_with_data = []
        for c in candidate_countries:
            payload = read_leader_interventions(c) or {}
            ivs = payload.get('interventions', [])
            if ivs:
                countries_with_data.append(c)
                all_interventions.extend(ivs)

        all_interventions.sort(key=lambda i: i.get('date') or '', reverse=True)

        # Aggregate stats
        by_commodity = {}
        by_country   = {}
        by_direction = {}
        for iv in all_interventions:
            by_commodity[iv.get('commodity')] = by_commodity.get(iv.get('commodity'), 0) + 1
            by_country[iv.get('country')]     = by_country.get(iv.get('country'), 0) + 1
            by_direction[iv.get('direction')] = by_direction.get(iv.get('direction'), 0) + 1

        return jsonify({
            'success':                  True,
            'intervention_count':       len(all_interventions),
            'interventions':            all_interventions,
            'countries_with_intervention': sorted(countries_with_data),
            'breakdown_by_commodity':   by_commodity,
            'breakdown_by_country':     by_country,
            'breakdown_by_direction':   by_direction,
            'last_updated':             datetime.now(timezone.utc).isoformat(),
        })

    print("[Commodity Tracker] ✅ Endpoints registered:")
    print("  GET  /api/commodity-pressure")
    print("  GET  /api/commodity-pressure/<target>")
    print("  GET  /api/commodity-prices")
    print("  GET  /api/commodity-debug")
    print("  GET  /api/commodity-fingerprint/<country>")
    print("  GET  /api/commodity-fingerprint/<country>/<commodity>")
    print("  GET  /api/leader-interventions")
    print("  GET  /api/leader-interventions/<country>")
    print("  GET  /api/leader-interventions/commodity/<commodity>")

    # PERIODIC BACKGROUND SCAN (every 12 hours)
    if not start_background:
        print("[Commodity Tracker] ℹ️ Background scan disabled on this instance")
        return

    def _periodic_scan():
        time.sleep(15)  # initial delay so app finishes booting
        while True:
            try:
                # Cross-worker guard: only the lock-owning worker scans. TTL (13h)
                # outlasts the 12h sleep so ownership persists between cycles; a
                # non-owner re-checks hourly so it can take over if the owner dies.
                if not _acquire_scheduler_lock('commodity', 46800):
                    time.sleep(3600)
                    continue
                print("[Commodity Tracker] Periodic scan starting (lock owner)...")
                _trigger_background_scan(days=7)
                time.sleep(60)
                while _background_scan_running:
                    time.sleep(30)
                print("[Commodity Tracker] Periodic scan complete. Sleeping 12 hours.")
                time.sleep(43200)  # 12 hours
            except Exception as e:
                print(f"[Commodity Tracker] Periodic scan error: {e}")
                time.sleep(3600)

    periodic_thread = threading.Thread(
        target=_periodic_scan,
        name='commodity-tracker-periodic',
        daemon=True,
    )
    periodic_thread.start()
