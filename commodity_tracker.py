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


# ========================================
# CONFIGURATION
# ========================================

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY')

# Upstash Redis (persistent cache across Render cold starts)
UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

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
        'top_producers':  ['usa', 'russia', 'qatar', 'iran', 'china', 'turkmenistan', 'azerbaijan'],
        'top_consumers':  ['eu', 'china', 'japan', 'korea'],
    },
    'nickel': {
        'name': 'Nickel',
        'icon': '⚙️',
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
        'top_producers':  ['saudi_arabia', 'russia', 'iran', 'iraq', 'usa', 'uae', 'azerbaijan', 'kazakhstan'],
        'top_consumers':  ['china', 'usa', 'india', 'eu'],
    },
    'potash': {
        'name': 'Potash',
        'icon': '🌱',
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
    'potash': [
        'potash', 'belaruskali', 'uralkali', 'nutrien',
        'mosaic potash', 'k+s potash', 'potash corp',
        'potash sanctions', 'potash export', 'potash production',
        'fertilizer prices', 'fertilizer sanctions',
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
}
# ========================================
# COUNTRY EXPOSURE MATRIX (Phase 1)
# ========================================
# Which commodities does each country touch, and in what role?
# role: 'producer' | 'consumer' | 'transit' | 'sanctions_target' | 'mediator'
# weight: 0.5 (minor) → 1.5 (dominant role)

COUNTRY_COMMODITY_EXPOSURE = {
    'argentina': {
        'lithium':      {'role': 'producer',          'weight': 1.0, 'rank': 5,
                         'note': "Lithium Triangle anchor (with Chile + Bolivia); ~18,000 MT/yr 2024 (doubled YoY); Salar del Hombre Muerto + Cauchari-Olaroz; Milei RIGI investment regime (2024) provides legal stability for large mining investments — structural pricing variable. Lithium Argentina (TSX:LAR) + Ganfeng JV; Rio Tinto Fénix."},
        'soybeans':     {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "~14% global production; export tax politics under Milei (reduced retentions = supply boost); crusher capacity dominant in Rosario; Paraná river logistics; major China supplier alongside Brazil."},
        'corn':         {'role': 'producer',          'weight': 1.0,
                         'note': "Top-5 corn producer; export tax variable; Rosario hub + Paraná river logistics; competitive with Brazil for Asian buyers."},
    },
    'australia': {
        'lithium':      {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 lithium producer (~88,000 MT/yr, ~38% global); spodumene hard-rock mining dominant. Greenbushes (Talison) is the largest hard-rock lithium mine globally; Pilbara Minerals + Liontown Kathleen Valley + Mineral Resources operations. China is dominant import destination. Production guidance + ASX:PLS, ASX:MIN, ASX:LTR earnings = global lithium price discovery."},
        'gold':         {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 gold producer (~290 tonnes/yr, ~9% global); Newmont Boddington + Cadia + Northern Star Kalgoorlie Super Pit; primary Western alternative to Chinese gold supply alongside Russia."},
        'rare_earths':  {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "Lynas Rare Earths Mt. Weld (Western Australia) is the only major non-Chinese heavy rare earth producer + refiner globally. Strategic diversification anchor for US/Japan/EU critical minerals strategy. Lynas Malaysia processing facility + planned Texas (US) plant. ASX:LYC."},
        'uranium':      {'role': 'producer',          'weight': 1.0, 'rank': 3,
                         'note': "World's #3 uranium producer (~10% global); Olympic Dam (BHP), Beverley + Honeymoon ISR mines; uranium export ban to non-NPT signatories; major supplier to USA + Japan + South Korea + India (under bilateral safeguards agreement)."},
    },
    'belarus': {
        'potash':       {'role': 'producer',         'weight': 1.2, 'rank': 3,
                         'note': 'Belaruskali, sanctioned 2021, rebuilt via Russian ports + China rail'},
        'oil':          {'role': 'transit',           'weight': 0.8,
                         'note': 'Druzhba pipeline, Mozyr/Naftan refineries (Russian crude)'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': '100% Russian gas dependency'},
    },
    'brazil': {
        'soybeans':     {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 soybean producer (~40% global, ~155 Mt/yr 2024-25); Mato Grosso + Paraná dominant; CONAB official forecasts; safrinha (second-crop) Mato Grosso corn rotated with soy. Single largest agri-supply story of the past decade — Brazil overtook USA in 2013. Dominant China supplier (~75% of Brazilian soy exports go to China); Paranaguá + Santos ports; US-China trade war beneficiary structurally."},
        'corn':         {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': "~12% global production; safrinha (Mato Grosso second harvest, ~75% of total Brazilian corn) creates a structural global supply variable distinct from US harvest cycles. Paranaguá + Santos export terminals. Major destination shift toward China + MENA in last decade."},
        'potash':       {'role': 'consumer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 potash consumer (~13M tonnes, ~17% global); the demand-side anchor of all global agri-commodity flow. Brazil's soy/corn export economy depends entirely on potash imports — when Belarus got sanctioned in 2021, Brazil was the primary impact zone. ~85% imported (Russia + Belarus + Canada). Soybean farmers' input cost lever."},
    },
    'canada': {
        'potash':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World's #1 potash producer (~14M tonnes/yr, ~36% global); Saskatchewan basin (largest known reserves globally); Nutrien (TSE:NTR — formed from PotashCorp + Agrium 2018 merger); Mosaic Esterhazy K3 mine. Canpotex consortium handles offshore exports. Brazil + USA + China are largest customers. Ukraine war + Belarus sanctions made Canada the structural Western-aligned potash anchor."},
        'uranium':      {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 uranium producer (~13% global); Cameco (TSE:CCO) operates McArthur River + Cigar Lake — among the world's highest-grade uranium deposits. Saskatchewan basin. Canada also leads CANDU heavy-water reactor IP. Major supplier to USA + EU + Japan + Korea. Western strategic alternative to Russian + Kazakh + Chinese supply chains."},
        'oil':          {'role': 'producer',          'weight': 1.0,
                         'note': "World's #4-5 oil producer (~5.9M bpd); Alberta oil sands (Athabasca) dominant; Suncor + Cenovus + CNRL operate. Largest oil exporter to USA via pipelines (Enbridge Mainline + Trans Mountain TMX expansion 2024). Heavy crude discount to WTI (WCS spread) drives Alberta fiscal politics."},
    },
    'chile': {
        'copper':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': 'World #1 copper producer (~24% global supply, ~5.3M tonnes/yr); Codelco state-owned + BHP Escondida + Antofagasta + Anglo American Sur; Chuquicamata is the largest open-pit mine on Earth. Antofagasta region is the world\'s most concentrated copper-mining infrastructure. Strategic anchor for the global energy transition (EVs + grid + electrification all copper-hungry).'},
        'lithium':      {'role': 'producer',          'weight': 1.4, 'rank': 2,
                         'note': 'World #2 lithium producer (~23% global supply); Salar de Atacama is the highest-grade lithium brine deposit globally. SQM + Albemarle dominant. Lithium Triangle anchor (Chile/Argentina/Bolivia ~58% of global reserves). Boric administration\'s 2023 National Lithium Strategy moved sector toward state-private partnerships — domestic political volatility is structural commodity-pricing variable.'},
        'silver':       {'role': 'producer',          'weight': 1.0, 'rank': 6,
                         'note': '~50 Moz/yr (~5% global); by-product of copper mining at Escondida, Collahuasi, Pelambres; Chile silver flows track copper extraction tempo, not standalone silver-mine economics.'},
        'gold':         {'role': 'producer',          'weight': 0.7,
                         'note': 'Modest gold production (~40 tonnes/yr); often co-mined with copper at Maricunga/El Indio/Andacollo belts; not a pricing-mover but a stability-of-mining-sector signal.'},
    },
    'china': {
        'rare_earths':  {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': '60%+ of global production, 85% of refining; export controls leverage'},
        'wheat': {
            'producer': {'weight': 1.5, 'rank': 1,
                         'note': "World's #1 wheat producer (~140 Mt/yr, ~18% global); primarily domestic consumption (low export) — food security strategic priority. State stockpiles + minimum procurement prices. Sinograin + COFCO state buyers. Henan + Shandong + Anhui dominant provinces."},
            'consumer': {'weight': 1.5, 'rank': 1,
                         'note': "World's #1 wheat consumer (~151 Mt/yr); largest net importer despite #1 producer status. Net imports ~7-12 Mt/yr depending on crop year — primarily Australian + Canadian + US + Russian wheat. China's import tariff-rate quota (TRQ) policy is structural global wheat pricing variable."},
        },
        'corn': {
            'producer': {'weight': 1.3, 'rank': 2,
                         'note': "World's #2 corn producer (~22% global, ~280 Mt/yr); Northeast (Heilongjiang/Jilin/Liaoning) + North China Plain dominant; primarily domestic feed + ethanol. Sinograin state stockpiling drives planting."},
            'consumer': {'weight': 1.5, 'rank': 2,
                         'note': "World's #2 corn consumer; largest net importer (animal feed + ethanol; net imports ~15-25 Mt/yr). Major US + Brazilian + Ukrainian corn buyer; trade war pressure point. China's annual import quota allocations move global corn prices."},
        },
        'lithium': {
            'producer': {'weight': 1.2, 'rank': 3,
                         'note': "World's #3 lithium producer (~17% global, ~41,000 MT/yr); Tianqi Lithium + Ganfeng Lithium dominant; Sichuan deposits + Jiangxi spodumene + Qinghai/Tibet brine. Recent investments in African + South American lithium assets (Bolivia, DRC, Mali). Tianqi is also ~25% owner of Australian Greenbushes mine (via SQM JV)."},
            'consumer': {'weight': 1.5, 'rank': 1,
                         'note': "World's #1 lithium consumer; refines ~70%+ of global lithium; manufactures ~70% of EV batteries. CATL + BYD + Gotion + EVE Energy + Sunwoda dominant cell makers. Whether lithium is mined in Australia, Chile, Argentina, or Zimbabwe, most flows to China for processing first. China is the global lithium throat."},
        },
        'potash':       {'role': 'consumer',          'weight': 1.4,
                         'note': '~20% of global consumption; structural deficit; helping Belarus bypass sanctions'},
        'soybeans':     {'role': 'consumer',          'weight': 1.5,
                         'note': '~60% of global imports; trade war pressure point'},
        'copper':       {'role': 'consumer',          'weight': 1.5,
                         'note': "World's #1 copper consumer (~10.2M tonnes, ~40% global) — recent figures lower than the popular '~50%' narrative; industrial demand bellwether driven by EV manufacturing + grid expansion + electronics + renewable energy. Net importer despite ~9% domestic production."},
        'oil':          {'role': 'consumer',          'weight': 1.4,
                         'note': 'World #1 importer; Iran/Russia discount buyer'},
        'gold':         {'role': 'consumer',          'weight': 1.2,
                         'note': 'Central bank reserve diversification; Shanghai Gold Exchange'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': 'Power of Siberia pipeline; LNG imports'},
        'cobalt':       {'role': 'consumer',          'weight': 1.5, 'rank': 1,
                         'note': '~73% of global cobalt refining; CMOC dominates DRC mining; Huayou vertically integrated; ~87% of cobalt consumption goes to lithium-ion batteries'},
        'nickel':       {'role': 'consumer',          'weight': 1.4,
                         'note': 'World #1 nickel consumer; stainless steel + EV batteries; Tsingshan/Huayou Indonesia investments dominate processing'},
        'silver': {
            'producer': {'weight': 1.2, 'rank': 2,
                         'note': "World's #2 silver producer (~109 Moz, ~13% global); often by-product of zinc/lead mining; Henan + Inner Mongolia + Yunnan provinces."},
            'consumer': {'weight': 1.4,
                         'note': "World's #1 silver consumer; solar PV manufacturing demand is the single largest silver demand growth vector globally — ~50% of new solar capacity uses Chinese silver paste. Industrial electronics + EV electronics also significant. China consumed > Mexico produced in 2024."},
        },
        'semiconductors': {'role': 'consumer',        'weight': 1.5, 'rank': 1,
                         'note': "World's largest semiconductor consumer (~50% of global imports for assembly + domestic use); aspirant producer pushed to legacy nodes by US export controls. SMIC, YMTC, CXMT struggle to advance beyond ~7nm without ASML EUV access. China responds with self-reliance push, REE export controls (retaliatory), and Taiwan unification rhetoric — semiconductors are THE structural reason cross-strait stakes are global. Watch SMIC node announcements, US entity list updates, ASML China revenue reports."},
    },
    'drc': {
        'cobalt':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': 'World #1 cobalt producer (~72% of global supply, ~247kt projected 2026); CMOC, Glencore dominate; export quotas since Feb 2025; Lobito Corridor diversifies routes from China-controlled infrastructure'},
        'copper':       {'role': 'producer',          'weight': 1.3,
                         'note': 'Major copper producer (Katanga belt); cobalt is largely a copper-mining by-product; Lubumbashi industrial center'},
    },
    'egypt': {
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
        'wheat':        {'role': 'consumer',          'weight': 1.3, 'rank': 3,
                         'note': "EU-27 collective wheat consumer (~108 Mt/yr, ~13% global). EU is also #2 wheat producer (~134 Mt/yr including UK historically) — typically net exporter, but consumption + production both at bloc-level due to Common Agricultural Policy. CAP determines planting incentives + subsidies. Russia-Ukraine war disrupted EU as residual Black Sea supplier."},
        'copper':       {'role': 'consumer',          'weight': 1.3, 'rank': 2,
                         'note': "EU-27 collective copper consumer (~4.1M tonnes/yr, ~16% global). Driven by automotive (especially EV transition), grid electrification mandates, building wiring codes (CPR fire safety). Germany #1 individual member-state consumer; Italy + France follow. Aurubis (Germany) largest copper smelter."},
        'natural_gas':  {'role': 'consumer',          'weight': 1.4,
                         'note': "EU-27 collective gas consumer (~330 bcm/yr post-2022 reduction from ~410 bcm pre-war). EU REPowerEU directives + 90% storage mandate drive winter procurement signals. Norway (~31% of imports) + USA LNG (~17%) + Algeria + Qatar + Azerbaijan now primary suppliers (Russia <10% by 2025). TTF Dutch hub = EU benchmark price."},
        'corn':         {'role': 'consumer',          'weight': 0.9,
                         'note': "EU-27 corn consumer (~75-80 Mt/yr); animal feed primary use. Imports from Ukraine + Brazil + Argentina; domestic production heavily concentrated in France + Romania + Hungary."},
        'soybeans':     {'role': 'consumer',          'weight': 1.0,
                         'note': "EU-27 collective soybean consumer (~15 Mt/yr); animal feed; ~95% imported (~half from Brazil); EU deforestation regulation (EUDR) creating supply chain compliance pressure; Brazilian soybean traceability is structural cost variable."},
        'nickel':       {'role': 'consumer',          'weight': 1.0,
                         'note': "EU-27 collective nickel consumer (stainless steel + battery sector); German + Italian stainless + Polish + Hungarian battery cell capacity build-out. Major Indonesian + Philippine supply dependency."},
        'rare_earths':  {'role': 'consumer',          'weight': 1.0,
                         'note': "EU Critical Raw Materials Act (2023) explicitly targets reducing China REE dependency. EU consumes ~25% of global REEs for automotive (EV magnets) + wind turbines + electronics. Lynas + MP Materials + Solvay (France) are diversification anchors. Watch: CRMA strategic project announcements, EU-Greenland REE agreements."},
        'semiconductors': {'role': 'consumer',        'weight': 1.0,
                         'note': "EU-27 collective semiconductor consumer ($45B+ market); automotive (~37% of EU chip demand) + industrial sectors. EU Chips Act (€43B, 2023) targets 20% global market share by 2030 via TSMC Dresden + Intel Magdeburg + GlobalFoundries Dresden expansion. Watch: ASML export-license decisions, EU Chips Act milestone announcements."},
    },
    'france': {
        'uranium':      {'role': 'consumer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 uranium consumer; ~70% of French electricity from nuclear (~56 reactors operated by EDF). Orano (formerly Areva) provides full fuel cycle: La Hague reprocessing + Tricastin enrichment + Melox MOX fabrication. Niger uranium supply traditionally critical (~20% of French imports historically) — disrupted by 2023 Niger coup; pivot to Kazakhstan + Canada + Australia accelerated. Macron's 2022 nuclear renaissance announcement (6 new EPR2 reactors) raises uranium demand trajectory. Watch: Niger uranium status, Orano-Kazatomprom contracts, EDF reactor availability."},
        'wheat':        {'role': 'producer',          'weight': 1.0,
                         'note': "Largest individual EU wheat producer (~35-37 Mt/yr, ~26% of EU total). Major Egypt + Algeria + sub-Saharan Africa supplier. CAP-driven; Brittany + Beauce + Picardy regions. Listed separately from EU bloc only because French wheat exports have a distinct national identity in MENA markets (vs. generic 'EU' supply)."},
    },
    'india': {
        'wheat': {
            'producer': {'weight': 1.3, 'rank': 2,
                         'note': "World's #2 wheat producer (~115 Mt/yr); Punjab + Haryana + Uttar Pradesh dominant; FCI (Food Corporation of India) state procurement at MSP (Minimum Support Price). India is structurally export-restricted — May 2022 + 2023 export bans (in response to Ukraine war disruption) directly tightened global Black Sea-replacement supply. Watch: FCI procurement levels, MSP announcements, export-ban policy."},
            'consumer': {'weight': 1.3, 'rank': 2,
                         'note': "World's #2 wheat consumer (~110 Mt/yr); roti + paratha + bread + biscuit demand for 1.45B population. PDS (Public Distribution System) covers ~800M people via subsidized wheat — a structural political stability lever (BJP's PMGKAY extensions are election-cycle policy). Domestic stocks + buffer norms drive periodic export-ban toggles."},
        },
        'oil':          {'role': 'consumer',          'weight': 1.4, 'rank': 3,
                         'note': "World's #3 oil consumer (~5.6M bpd, ~5.5% global); fastest-growing oil demand globally — accounts for ~25% of all global oil demand growth 2024-25. ~85% imported. Russian Urals crude (post-G7 price cap) ~35-40% of imports — discount-driven; Saudi + Iraq + UAE primary alternatives. Reliance Jamnagar + IOC refineries. Modi-era refining capacity expansion for re-export to Europe. Watch: Urals discount to Brent, Russian payment routing, India-Saudi long-term contracts."},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': "Growing LNG importer (~33 Mt/yr, ~7% global); Petronet LNG + GAIL infrastructure; Qatar long-term + USA LNG + spot purchases. National Gas Grid + city gas distribution buildout under PNGRB. Coal-to-gas substitution policy lever; LNG import sensitive to TTF + JKM spot pricing."},
        'gold':         {'role': 'consumer',          'weight': 1.4, 'rank': 2,
                         'note': "World's #2 gold consumer (~750-800 tonnes/yr, ~22% global retail demand); cultural-economic anchor (jewelry + savings + dowry). Wedding + festival demand cycle (Diwali + Akshaya Tritiya) is global gold pricing variable. Gold import duty + GST adjustments are political stability levers (rural sentiment). RBI also major central-bank gold buyer (~840 tonnes reserves; +57 tonnes 2024)."},
        'silver':       {'role': 'consumer',          'weight': 1.2, 'rank': 2,
                         'note': "World's #2 silver consumer (~6,000 tonnes/yr, ~16% global); silver follows gold pattern in Indian cultural-economic life — jewelry + ETF (Tata, Nippon, ICICI silver ETFs launched 2022-24). Industrial demand growing for solar PV manufacturing (Adani + Reliance giga-factories). Silver import duty changes mirror gold policy."},
        'potash':       {'role': 'consumer',          'weight': 1.2, 'rank': 3,
                         'note': "World's #3 potash consumer (~6 Mt/yr); 100% imported — IPL (Indian Potash Limited) state-aligned buyer; Canada (Canpotex) + Russia + Belarus primary suppliers. Subsidized fertilizer pricing → fiscal exposure to global MOP price moves. 2021 Belarus sanctions tested supply diversification."},
        'corn':         {'role': 'consumer',          'weight': 0.9,
                         'note': "Growing corn consumer (~30 Mt/yr); rapid expansion of poultry + ethanol blending (E20 mandate by 2025). Domestic production primary; minor net importer. Watch: ethanol blending policy, MSP announcements."},
    },
    'indonesia': {
        'nickel':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': 'World #1 nickel producer (~800K tons/yr); Sulawesi/Morowali Industrial Park + Weda Bay; HPAL processing dominant; Chinese capital deeply embedded (Tsingshan, Huayou); 2020 ore export ban transformed market'},
        'cobalt':       {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': '~15% of global cobalt (HPAL nickel by-product); rapid growth via Pomalaa, Morowali; expected 20% global share by 2030'},
        'wheat':        {'role': 'consumer',          'weight': 1.3, 'rank': 2,
                         'note': "World's #2 wheat importer (~11.7 Mt/yr); BULOG state buyer; instant noodle culture (Indomie etc.) drives structural demand; ~280M population; primarily Australian + Canadian + Russian wheat. Domestic wheat production zero — fully import-dependent. Watch: Bulog tender results, Indonesian rupiah USD reserves, ASEAN food security policy."},
    },
    'israel': {
        # ── Producer side (existing, kept) ──
        'potash':       {'role': 'producer',          'weight': 1.0, 'rank': 6,
                         'note': 'ICL (Israel Chemicals); Dead Sea production'},
        'natural_gas':  {'role': 'producer',          'weight': 0.8,
                         'note': 'Leviathan + Tamar fields; exports to Egypt/Jordan'},
        # ── Consumer side (Phase 3 expansion, May 2026) ──
        # Israel is a small consumer market deeply tied to global supply chains.
        # Mediterranean shipping, Eilat pipeline, and Black Sea grain corridor
        # are all single-points-of-failure for Israeli food/fuel security.
        'wheat':        {'role': 'consumer',          'weight': 1.3,
                         'note': '~80% of consumption imported (Black Sea + US); bread = coalition stress lever'},
        'corn':         {'role': 'consumer',          'weight': 0.9,
                         'note': 'Animal feed dependency; Ukraine + US imports; livestock cost driver'},
        'soybeans':     {'role': 'consumer',          'weight': 0.7,
                         'note': 'Food + feed imports; soy-oil + animal protein supply chain'},
        'oil':          {'role': 'consumer',          'weight': 1.2,
                         'note': 'Net importer; Eilat-Ashkelon pipeline + Mediterranean tankers; Hormuz/Suez vulnerable'},
    },
    'iran': {
        # ── Producer side (war-degraded but structural) ──
        'oil':          {'role': 'producer',          'weight': 1.5, 'rank': 6,
                         'note': 'World #6 oil producer pre-strike (~3.2M bpd OPEC); also primary control of Strait of Hormuz transit (~20% of global oil). Kharg Island terminal struck Feb 2026; export capacity severely degraded. Hormuz closure remains active leverage even when production stalled.'},
        'natural_gas':  {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': 'World #3 natural gas reserves (~33.99 trillion cubic meters); South Pars field shared with Qatar; sanctions-constrained export capacity; pipeline-only delivery to Türkiye + Iraq + Armenia; LNG export ambitions blocked by tech restrictions.'},
        'uranium':      {'role': 'producer',          'weight': 1.3,
                         'note': 'Domestic enrichment program (Natanz, Fordow); pre-strike enriched to 60%; not market commodity but strategic signaling vector. Tracker watches IAEA + nuclear language.'},
        # ── Consumer side ──
        'wheat':        {'role': 'consumer',          'weight': 1.4,
                         'note': '~25-30% of consumption imported (~5-7M tonnes/yr); subsidized bread is the central political stability lever — wheat shortage = regime risk (1979 Revolution echo). Russian wheat primary import source; sanctions complicate payment routing.'},
        'gold':         {'role': 'consumer',          'weight': 1.2,
                         'note': 'Iran-Russia-China gold barter as sanctions evasion; Tehran Gold Exchange + bazaar physical demand surging during currency crisis; central bank reserves obscured but estimated ~$15-30B'},
    },
    'japan': {
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
                         'note': 'World #1 uranium producer (~40% of global supply); Kazatomprom dominates ISR mining; 14 JVs hedge across Cameco/Orano/Rosatom/CGN; SMR demand wave 2025-2030 critical'},
        'wheat':        {'role': 'producer',          'weight': 1.0,
                         'note': "Top-10 wheat producer (~14 Mt/yr); largest wheat exporter in Central Asia. Costanai + Akmola + North Kazakhstan oblasts. Major supplier to Iran + Türkiye + Afghanistan + Tajikistan + Uzbekistan. Russian transit politics affect export routing — Kazakhstan's wheat partly competes with, partly complements Russian Black Sea wheat in Central Asian markets."},
        'oil':          {'role': 'producer',          'weight': 1.3, 'rank': 8,
                         'note': 'Tengiz, Karachaganak, Kashagan supergiants; CPC pipeline to Novorossiysk (Russia exposure); KazTransOil to China; Aktau Caspian port'},
        'natural_gas':  {'role': 'producer',          'weight': 0.7,
                         'note': 'Net producer/consumer balance; primarily domestic + neighbor exports'},
        'silver':       {'role': 'producer',          'weight': 0.8,
                         'note': '~12.6 Moz (~1.5% global); by-product of base-metal mining; strategic position between Russia/China for export routing'},
    },
    'mexico': {
        'silver':       {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': 'World #1 silver producer (~6,120 MT, ~22% global); Zacatecas/Durango/Chihuahua; Fresnillo (largest primary silver mine); Peñoles/Fresnillo PLC dominant; ancient mining tradition'},
        'oil':          {'role': 'producer',          'weight': 0.9,
                         'note': "World's #11-12 oil producer (~1.9M bpd); Pemex state monopoly (heavy debt burden ~$100B+); Cantarell + Ku-Maloob-Zaap legacy fields declining; Sheinbaum administration (2024-) energy nationalist stance. Heavy crude exports to USA + Spain + India. Watch: Pemex debt sustainability, Cantarell production decline, US-Mexico USMCA energy provisions."},
        'corn':         {'role': 'consumer',          'weight': 1.0,
                         'note': "World's #5 corn consumer (~45 Mt/yr); largest individual-country corn importer (~17 Mt/yr from USA via USMCA); white-corn for tortillas politically sensitive (AMLO/Sheinbaum GMO restriction → US trade dispute). Animal feed + tortilla industry dual demand. Watch: USMCA agriculture dispute outcomes, peso USD exchange rate."},
        'copper':       {'role': 'consumer',          'weight': 0.7,
                         'note': "Major Latin American manufacturing hub (Northern Mexico maquiladoras + automotive + electronics); USMCA supply chain integration with USA. Net copper importer despite minor domestic production at Buenavista (Grupo México). Tesla Monterrey + new EV manufacturing builds out copper demand."},
    },
    'netherlands': {
        'semiconductors': {'role': 'producer',        'weight': 1.5, 'rank': 4,
                         'note': "Holds the single most concentrated leverage point in semiconductor manufacturing: ASML's EUV lithography monopoly. ASML (Veldhoven) is the only company in the world that produces extreme ultraviolet lithography systems required for sub-7nm chip manufacturing — meaning every leading-edge fab on Earth (TSMC, Samsung, Intel, SK Hynix) depends on ASML. Dutch government export-control decisions on EUV (and increasingly DUV) shipments to China constitute the most consequential single-country technology policy in the world. Also home to NXP (automotive chips). Watch: ASML quarterly bookings, Dutch trade ministry export-license announcements, EU Chips Act milestones."},
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
        'silver':       {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': 'World #3 silver producer (~107 Moz/~13% global); largest silver reserves globally per USGS; Antamina, Cerro de Pasco, Yanacocha; Buenaventura + Hochschild dominant. Andean mining region — political stability of Peru directly affects global silver supply.'},
        'copper':       {'role': 'producer',          'weight': 1.3,
                         'note': 'Major copper producer; Antamina, Toromocho; high-altitude Andean mining'},
    },
    'philippines': {
        'nickel':       {'role': 'producer',          'weight': 1.4, 'rank': 2,
                         'note': 'World #2 nickel producer (~420K tons/yr); Surigao region dominant; periodically exceeds Indonesia during Indonesian export bans; key Chinese feedstock'},
    },
    'russia': {
        'oil':          {'role': 'producer',          'weight': 1.5, 'rank': 2,
                         'note': 'World #2 producer; Urals crude; G7 price cap; shadow fleet'},
        'natural_gas':  {'role': 'producer',          'weight': 1.5, 'rank': 2,
                         'note': 'Gazprom, Novatek; Nord Stream; Yamal LNG; European market loss'},
        'wheat': {
            'producer': {'weight': 1.5, 'rank': 1,
                         'note': "World's #1 wheat exporter (~50-55 Mt/yr exports of ~85 Mt production); Black Sea grain corridor leverage; primary supplier to Egypt + Türkiye + Iran + Bangladesh + Indonesia; floating export taxes are structural pricing variable. 2024-25 record harvest pushed global prices down."},
            'consumer': {'weight': 1.0,
                         'note': "Major domestic wheat consumer (~40 Mt/yr, ~5% global); bread is politically subsidized; Russian Federation grain trading is partly state-controlled (United Grain Company)."},
        },
        'potash':       {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': 'Uralkali; partially sanctioned'},
        'uranium':      {'role': 'producer',          'weight': 1.0, 'rank': 5,
                         'note': 'Rosatom; HALEU enrichment dominance; Tenex sanctions risk'},
        'gold':         {'role': 'producer',          'weight': 1.1,
                         'note': 'BRICS+ gold reserves; sanctions evasion vehicle'},
        'cobalt':       {'role': 'producer',          'weight': 1.0, 'rank': 3,
                         'note': 'World #3 cobalt producer; Norilsk Nickel by-product; geopolitical risk reducing global prominence'},
        'nickel':       {'role': 'producer',          'weight': 1.2, 'rank': 3,
                         'note': 'World #3 nickel producer (~270K tons/yr); Norilsk Nickel/Nornickel dominant; Arctic Norilsk + Kun-Manie + Krasnoyarsk Krai operations'},
        'silver':       {'role': 'producer',          'weight': 1.0, 'rank': 4,
                         'note': '~39.8 Moz (~5% global); Polymetal International + Norilsk Nickel by-product; sanctions complicate Western supply'},
    },
    'saudi_arabia': {
        'oil':          {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': 'Saudi Aramco; world #1 producer (~10M bpd capacity); OPEC institutional anchor; Ras Tanura export terminal; East-West Pipeline bypasses Hormuz'},
        'natural_gas':  {'role': 'producer',          'weight': 0.9,
                         'note': 'Jafurah unconventional field (largest in ME); Master Gas System; primarily domestic power + petrochemicals'},
        'gold':         {'role': 'consumer',          'weight': 0.9,
                         'note': 'SAMA central bank reserves; significant retail demand; Vision 2030 mineral resources strategy'},
        'wheat':        {'role': 'consumer',          'weight': 1.0,
                         'note': "Major wheat importer (~3.5 Mt/yr, ~85% imported); SAGO (Saudi Grains Organization) state procurement; bread subsidies for ~36M population (citizens + expat workforce); domestic wheat phased out 2016 due to water scarcity. Russian + Australian + Canadian primary suppliers. Watch: SAGO tender results, Vision 2030 food security strategy, Red Sea shipping (Houthi BAM attacks)."},
    },
    'south_korea': {
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
    },
    'taiwan': {
        'semiconductors': {'role': 'producer',        'weight': 1.5, 'rank': 1,
                         'note': "World #1 semiconductor producer and the platform's most concentrated single-country chokepoint. TSMC alone manufactures ~60% of global foundry output and ~90% of leading-edge (sub-7nm) chips — including all advanced AI accelerators (Nvidia, AMD), Apple silicon, and high-end mobile SoCs. Fab 18 (Tainan) is the most strategically valuable industrial facility on Earth. UMC #4 globally for mature nodes. Taiwan's semiconductor dominance is THE structural reason for US/Japan/EU shared interest in cross-strait stability — and the central asymmetric risk in any PLA blockade scenario. Watch: TSMC capacity announcements, Arizona/Kumamoto/Dresden fab progress, US export-control updates, Taiwan defense budget."},
        'oil':          {'role': 'consumer',          'weight': 1.4,
                         'note': '~99% of oil imported; CPC Corporation + Formosa Petrochemical; Middle East dependency creates compound Hormuz exposure. Strategic petroleum reserve ~140 days. Blockade vulnerability is the asymmetric risk that PLA planners explicitly reference.'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.4,
                         'note': '~99% LNG imports; Yongan + Taichung + Taoyuan terminals; ~10-14 days strategic reserve. Australia + Qatar primary suppliers. LNG terminal vulnerability + short reserve timeline = energy security single-point-of-failure during conflict scenarios.'},
        'wheat':        {'role': 'consumer',          'weight': 1.0,
                         'note': '~95% imported, primarily from US + Australia + Canada; food security exposure during blockade scenarios. Limited strategic grain reserve.'},
        'corn':         {'role': 'consumer',          'weight': 0.9,
                         'note': 'Animal feed import dependency; livestock sector cost driver; US + Brazil primary sources.'},
        'rare_earths':  {'role': 'consumer',          'weight': 1.3,
                         'note': 'Semiconductor manufacturing critical input — heavy rare earths for chip polishing, magnets, and specialty alloys. China holds export-control leverage; Taiwan diversification efforts via Lynas Australia + recycling. Compound risk: REE export ban + cross-strait pressure simultaneously.'},
    },
    'turkey': {
        'wheat':        {'role': 'transit',           'weight': 1.0,
                         'note': "Bosphorus + Dardanelles + Black Sea grain corridor mediator. Türkiye's straits are the chokepoint through which all Russian + Ukrainian + Romanian + Bulgarian wheat exports must pass — Türkiye's UN-brokered July 2022 grain corridor agreement (with UN + Russia + Ukraine) was foundational. Türkiye is also a major wheat-flour re-exporter (~5-6 Mt/yr to MENA + sub-Saharan Africa, including Egypt + Iraq + Sudan + Yemen). Domestic wheat production ~20 Mt + imports ~10 Mt; Turkish Grain Board (TMO) state procurement. Watch: Montreux Convention enforcement, Turkish Straits transit, TMO tender results."},
        'oil':          {'role': 'transit',           'weight': 1.2,
                         'note': "Turkish Straits + BTC pipeline + Ceyhan terminal: ~3% of global seaborne oil transits Bosphorus/Dardanelles; Baku-Tbilisi-Ceyhan pipeline (Azerbaijan crude) terminates at Ceyhan; Kirkuk-Ceyhan pipeline (Iraqi crude, currently halted) terminates similarly. Türkiye is also major refined-product importer (~1M bpd consumption). Erdoğan administration uses transit position as diplomatic leverage. Watch: BTC volume data, Kirkuk-Ceyhan restart negotiations, Russian oil tanker transit through Bosphorus."},
        'natural_gas':  {'role': 'transit',           'weight': 1.1,
                         'note': "TurkStream (Russian gas to Türkiye + Southeast Europe) + TANAP (Caspian gas via Azerbaijan) + Iraqi pipeline + LNG import terminals. Türkiye positioned itself as European gas hub during 2022-24 sanctions period — Russian gas re-flow + LNG re-export. Erdoğan-proposed 'gas hub' concept structurally controversial within EU. Watch: TurkStream throughput, BOTAŞ tender results, EU 'gas hub' diplomatic friction."},
        'gold':         {'role': 'consumer',          'weight': 1.0,
                         'note': "Major retail + jewelry gold market (~250-300 tonnes/yr); Istanbul Grand Bazaar tradition + Erdoğan-era inflation hedge (Turkish lira lost ~80% since 2018, driving aggressive household + central-bank gold accumulation). TCMB (central bank) bought ~75 tonnes 2024 alone. Gold smuggling via Iran corridor concern. Watch: TCMB monthly gold reserves, USD/TRY exchange rate, retail gold demand."},
    },
    'turkmenistan': {
        'natural_gas':  {'role': 'producer',          'weight': 1.0, 'rank': 4,
                         'note': "World #4 natural gas reserves (~27.4 TCM); Galkynysh world's #2 onshore field; primarily exports to China via Central Asia-China pipeline; Russia/Iran transit constrained; isolated state — gas is the entire economy."},
        'oil':          {'role': 'producer',          'weight': 0.6,
                         'note': 'Modest oil production; primarily domestic + Caspian shipping; Turkmenbashi port modernization 2018'},
    },
    'uae': {
        'oil':          {'role': 'producer',          'weight': 1.4, 'rank': 7,
                         'note': 'ADNOC; ~3M bpd capacity; Fujairah terminal + Habshan-Fujairah pipeline bypass Hormuz; left OPEC May 1 2026 over quota disputes; Fujairah struck during Iran war (2026)'},
        'natural_gas':  {'role': 'consumer',          'weight': 0.9,
                         'note': 'Dolphin Pipeline imports from Qatar; net importer despite domestic production; LNG terminal at Jebel Ali'},
        'gold':         {'role': 'transit',           'weight': 1.0,
                         'note': 'Dubai DMCC + Gold Souk; major global gold re-export hub; Africa→Asia routing; sanctions evasion concerns'},
        'wheat':        {'role': 'consumer',          'weight': 0.9,
                         'note': "Major wheat importer (~1.7 Mt/yr); ~95% imported (~10M population, half citizen + half expat workforce); bread + pasta + bakery products for Western expat-heavy diet. Strategic stockpile policy (~6 months reserves). Russian + Australian + Canadian primary suppliers; UAE re-exports milled flour to MENA + Africa."},
    },
    'ukraine': {
        'wheat':        {'role': 'producer',          'weight': 1.4, 'rank': 5,
                         'note': 'Pre-war top-5 wheat exporter; corridor disruption signal'},
        'corn':         {'role': 'producer',          'weight': 1.4,
                         'note': 'Major corn exporter; Odesa port dependency'},
        'sunflower_oil': {'role': 'producer',         'weight': 1.0,
                         'note': '~50% of global sunflower oil; tracked under wheat/corn for Phase 1'},
    },
    'usa': {
        'semiconductors': {'role': 'producer',        'weight': 1.5, 'rank': 5,
                         'note': "World's dominant semiconductor designer + emerging manufacturer + export-control authority. Design dominance: Nvidia (~80% AI accelerator market), AMD, Intel, Qualcomm, Broadcom, Apple silicon. Manufacturing reshoring: Intel (Ohio, Oregon, Arizona), TSMC Arizona, Samsung Austin/Taylor TX, Micron Idaho/NY — backed by ~$52B CHIPS and Science Act subsidies. Most consequential lever: US Foreign Direct Product Rule + Entity List authorities give Washington effective veto over global chip flows touching any US technology. Watch: CHIPS Act fab milestones, Commerce Department BIS rule updates, Nvidia China revenue (H20/B20 product lines), TSMC Arizona yield reports."},
        'oil': {
            'producer': {'weight': 1.5, 'rank': 1,
                         'note': "World's #1 oil producer post-shale revolution (~13M bpd, ~22% global); Permian basin dominant. Strategic Petroleum Reserve. Sanctions weapon (against Iran, Russia, Venezuela)."},
            'consumer': {'weight': 1.5, 'rank': 1,
                         'note': "World's #1 oil consumer (~19M bpd, ~19% global); ~40% imported despite #1 producer status — driven by industrial scale + transportation network + petrochemical feedstock. Strategic Petroleum Reserve insurance against import disruption."},
        },
        'natural_gas':  {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': "World #1 natural gas producer; world's #1 LNG exporter post-2023. Henry Hub benchmark. Cheniere + Sabine Pass + Freeport LNG. Energy security weapon for European allies."},
        'wheat':        {'role': 'producer',          'weight': 1.2,
                         'note': 'Major wheat exporter; USDA WASDE reports drive global price discovery; Mississippi River + Gulf export infrastructure.'},
        'corn': {
            'producer': {'weight': 1.5, 'rank': 1,
                         'note': "World's #1 corn producer (~30% global, ~380 Mt/yr); Iowa/Illinois/Nebraska Corn Belt. USDA WASDE reports drive global price discovery. Mississippi River barge → New Orleans Gulf export infrastructure."},
            'consumer': {'weight': 1.4,
                         'note': "World's #1 corn consumer; ~40% goes to ethanol (Renewable Fuel Standard mandate), ~36% to animal feed, ~24% to exports. Ethanol mandate intersects with food-vs-fuel debates. Major net exporter."},
        },
        'soybeans':     {'role': 'producer',          'weight': 1.4,
                         'note': "Major soybean exporter; trade war pressure point with China; Mississippi + Gulf export."},
        'gold':         {'role': 'consumer',          'weight': 1.0,
                         'note': "Federal Reserve gold reserves (~8,133 tonnes — world's largest); COMEX dominance; sanctions enforcement infrastructure."},
        'silver':       {'role': 'consumer',          'weight': 1.0, 'rank': 3,
                         'note': "World's #3 silver consumer (~14% global); industrial demand (electronics + photovoltaics + brazing alloys + medical) + ETF demand (SLV + PSLV + SIVR). COMEX silver futures = global price discovery. Sprott Physical Silver Trust accumulation periodically squeezes physical market."},
        'copper':       {'role': 'consumer',          'weight': 1.2, 'rank': 3,
                         'note': "World's #3 copper consumer (~3.3M tonnes/yr, ~13% global); construction + electrical wiring + EV adoption + grid modernization + defense electronics. ~40% imported (Chile + Peru primary suppliers). IRA infrastructure spending + EV transition + grid electrification all copper-hungry. Net importer despite domestic Freeport-McMoRan + Rio Tinto + BHP operations."},
        'rare_earths':  {'role': 'producer',          'weight': 1.0,
                         'note': "MP Materials Mountain Pass (the only operating US REE mine) + new processing investments; CHIPS-era industrial policy push for diversification from China dependency."},
        'uranium':      {'role': 'consumer',          'weight': 1.1,
                         'note': "World's largest civilian uranium consumer (~93 reactors); Russian HALEU dependency major concern; Centrus Energy + Urenco USA + DOE strategic uranium reserve."},
    },
}
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

    for article in all_articles:
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
        ROLE_PRIORITY = {'producer': 5, 'consumer': 4, 'transit': 3,
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
        'version':                '1.1.0',
    }

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
    consumer_items = []
    transit_items  = []
    for cid, role_name, role_data in _iter_country_exposures(target):
        rank = role_data.get('rank')
        label = cid.replace('_', ' ')
        if rank and role_name == 'producer':
            label = f"{label} (#{rank} globally)"
        if role_name == 'producer':
            producer_items.append(label)
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

    # Consumer sentence
    if consumer_items:
        if not producer_items:
            parts.append(f"{target_name} is a major consumer of {_natural_join(consumer_items)}.")
        else:
            parts.append(f"It is also a major consumer of {_natural_join(consumer_items)}.")

    # Transit sentence
    if transit_items:
        connector = "It is also" if (producer_items or consumer_items) else f"{target_name} is"
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

        return {
            'success':              True,
            'country':              target,
            'commodity_pressure':   country.get('total_score', 0),
            'alert_level':          country.get('alert_level', 'normal'),
            'commodity_summaries':  commodity_summaries,
            'top_signals':          country.get('top_signals', [])[:8],
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
# FLASK ENDPOINT REGISTRATION
# ========================================

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

    @app.route('/api/commodity-debug', methods=['GET'])
    def api_commodity_debug():
        """Diagnostic — config snapshot + cache freshness."""
        from flask import jsonify
        return jsonify({
            'version':                '1.0.0',
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
        })

    print("[Commodity Tracker] ✅ Endpoints registered:")
    print("  GET  /api/commodity-pressure")
    print("  GET  /api/commodity-pressure/<target>")
    print("  GET  /api/commodity-prices")
    print("  GET  /api/commodity-debug")

    # PERIODIC BACKGROUND SCAN (every 12 hours)
    if not start_background:
        print("[Commodity Tracker] ℹ️ Background scan disabled on this instance")
        return

    def _periodic_scan():
        time.sleep(15)  # initial delay so app finishes booting
        while True:
            try:
                print("[Commodity Tracker] Periodic scan starting...")
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
