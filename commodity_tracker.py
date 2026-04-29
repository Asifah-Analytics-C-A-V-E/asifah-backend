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
    'oil': {
        'name': 'Oil (Crude)',
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
            'kozmino', 'jubail', 'hormuz blockade'
        ],
        'top_producers':  ['saudi_arabia', 'russia', 'iran', 'iraq', 'usa', 'uae'],
        'top_consumers':  ['china', 'usa', 'india', 'eu'],
    },
    'natural_gas': {
        'name': 'Natural Gas / LNG',
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
            'qatar lng', 'sakhalin', 'arctic lng',
        ],
        'top_producers':  ['usa', 'russia', 'qatar', 'iran', 'china'],
        'top_consumers':  ['eu', 'china', 'japan', 'korea'],
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
    'corn': {
        'name': 'Corn (Maize)',
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
    'potash': {
        'name': 'Potash (KCl)',
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
    'rare_earths': {
        'name': 'Rare Earth Elements',
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
}


# ========================================
# COMMODITY KEYWORD SETS
# ========================================
# Used for matching news articles to commodities.
# Each commodity has English + (where relevant) multilingual keywords.

COMMODITY_KEYWORDS = {
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
        # Russian
        'нефть', 'цена на нефть', 'нефтепровод', 'нефтяные санкции',
        # Arabic
        'النفط', 'أسعار النفط', 'أرامكو', 'أوبك',
        # Farsi
        'نفت', 'صادرات نفت ایران', 'تحریم نفت',
        # Chinese
        '原油', '石油价格', '石油进口',
    ],
    'natural_gas': [
        'natural gas', 'lng', 'liquefied natural gas',
        'henry hub', 'ttf gas', 'jkm price', 'gas prices',
        'nord stream', 'turkstream', 'yamal lng',
        'qatar lng', 'us lng exports', 'european gas',
        'gas pipeline', 'gas storage europe', 'gas crisis',
        'gazprom', 'novatek', 'qatargas', 'shell lng',
        'sakhalin', 'arctic lng',
        # Russian
        'природный газ', 'газпром', 'газопровод', 'спг',
        # Chinese
        '天然气', '液化天然气',
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
    'uranium': [
        'uranium', 'uranium prices', 'yellowcake',
        'kazatomprom', 'cameco', 'orano', 'rosatom uranium',
        'sprott physical uranium', 'uranium etf',
        'uranium enrichment', 'enriched uranium',
        'natural uranium', 'uranium oxide',
        'kazakhstan uranium', 'niger uranium', 'arlit',
        'uranium mining', 'uranium sanctions',
        'haleu', 'low-enriched uranium', 'high-assay',
        'tenex russia', 'urenco',
        'small modular reactor', 'smr fuel',
        # Russian
        'уран', 'росатом уран', 'тенекс',
        # French (Niger)
        "uranium nigérien", 'orano niger',
    ],
    'rare_earths': [
        'rare earth', 'rare earths', 'rare earth elements',
        'ree', 'neodymium', 'dysprosium', 'samarium',
        'praseodymium', 'terbium', 'cerium', 'lanthanum',
        'mp materials', 'mountain pass', 'lynas',
        'remx etf', 'china rare earth', 'baotou',
        'rare earth export ban', 'rare earth sanctions',
        'rare earth processing', 'rare earth refining',
        'kvanefjeld greenland', 'tanbreez',
        'shenghe resources', 'china northern rare earth',
        'permanent magnet', 'ndfeb magnet',
        # Chinese
        '稀土', '稀土出口', '稀土禁令',
    ],
    'lithium': [
        'lithium', 'lithium prices', 'lithium carbonate',
        'lithium hydroxide', 'spodumene',
        'albemarle', 'sqm lithium', 'tianqi lithium',
        'ganfeng lithium', 'lithium triangle',
        'salar de atacama', 'salar de uyuni',
        'greenbushes mine', 'lithium battery',
        'lithium ev', 'lithium australia', 'lithium chile',
        'lithium argentina', 'lithium bolivia',
        'lithium mining', 'lit etf',
        # Spanish
        'litio', 'litio chile', 'litio argentina',
        # Chinese
        '锂', '碳酸锂', '锂矿',
    ],
    'gold': [
        'gold', 'gold prices', 'gold futures', 'gold spot',
        'comex gold', 'lbma gold', 'shanghai gold exchange',
        'central bank gold buying', 'gold reserves',
        'russian gold', 'china gold reserves',
        'india gold imports', 'gold smuggling',
        'gold sanctions', 'sanctions evasion gold',
        'brics gold', 'gold-backed', 'goldman gold',
        'gold etf gld', 'iau gold',
        # Russian
        'золото', 'золотовалютные резервы',
        # Chinese
        '黄金', '黄金储备', '黄金价格',
        # Arabic
        'الذهب', 'أسعار الذهب',
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
}


# ========================================
# COUNTRY EXPOSURE MATRIX (Phase 1)
# ========================================
# Which commodities does each country touch, and in what role?
# role: 'producer' | 'consumer' | 'transit' | 'sanctions_target' | 'mediator'
# weight: 0.5 (minor) → 1.5 (dominant role)

COUNTRY_COMMODITY_EXPOSURE = {
    'belarus': {
        'potash':       {'role': 'producer',         'weight': 1.4, 'rank': 3,
                         'note': 'Belaruskali, sanctioned 2021, rebuilt via Russian ports + China rail'},
        'oil':          {'role': 'transit',           'weight': 0.8,
                         'note': 'Druzhba pipeline, Mozyr/Naftan refineries (Russian crude)'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': '100% Russian gas dependency'},
    },
    'russia': {
        'oil':          {'role': 'producer',          'weight': 1.5, 'rank': 2,
                         'note': 'World #2 producer; Urals crude; G7 price cap; shadow fleet'},
        'natural_gas':  {'role': 'producer',          'weight': 1.5, 'rank': 2,
                         'note': 'Gazprom, Novatek; Nord Stream; Yamal LNG; European market loss'},
        'wheat':        {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': 'World #1 wheat exporter; Black Sea grain corridor leverage'},
        'potash':       {'role': 'producer',          'weight': 1.3, 'rank': 2,
                         'note': 'Uralkali; partially sanctioned'},
        'uranium':      {'role': 'producer',          'weight': 1.0, 'rank': 5,
                         'note': 'Rosatom; HALEU enrichment dominance; Tenex sanctions risk'},
        'gold':         {'role': 'producer',          'weight': 1.1,
                         'note': 'BRICS+ gold reserves; sanctions evasion vehicle'},
    },
    'china': {
        'rare_earths':  {'role': 'producer',          'weight': 1.5, 'rank': 1,
                         'note': '60%+ of global production, 85% of refining; export controls leverage'},
        'lithium':      {'role': 'consumer',          'weight': 1.5,
                         'note': 'World #1 lithium consumer (EV batteries); also major producer via Tianqi/Ganfeng + dominant downstream battery industry'},
        'potash':       {'role': 'consumer',          'weight': 1.4,
                         'note': '~20% of global consumption; structural deficit; helping Belarus bypass sanctions'},
        'soybeans':     {'role': 'consumer',          'weight': 1.5,
                         'note': '~60% of global imports; trade war pressure point'},
        'copper':       {'role': 'consumer',          'weight': 1.5,
                         'note': '~50% of global consumption; industrial demand bellwether'},
        'oil':          {'role': 'consumer',          'weight': 1.4,
                         'note': 'World #1 importer; Iran/Russia discount buyer'},
        'gold':         {'role': 'consumer',          'weight': 1.2,
                         'note': 'Central bank reserve diversification; Shanghai Gold Exchange'},
        'natural_gas':  {'role': 'consumer',          'weight': 1.0,
                         'note': 'Power of Siberia pipeline; LNG imports'},
    },
    'israel': {
        'potash':       {'role': 'producer',          'weight': 1.0, 'rank': 6,
                         'note': 'ICL (Israel Chemicals); Dead Sea production'},
        'natural_gas':  {'role': 'producer',          'weight': 0.8,
                         'note': 'Leviathan + Tamar fields; exports to Egypt/Jordan'},
    },
    'ukraine': {
        'wheat':        {'role': 'producer',          'weight': 1.4, 'rank': 5,
                         'note': 'Pre-war top-5 wheat exporter; corridor disruption signal'},
        'corn':         {'role': 'producer',          'weight': 1.4,
                         'note': 'Major corn exporter; Odesa port dependency'},
        'sunflower_oil': {'role': 'producer',         'weight': 1.0,
                         'note': '~50% of global sunflower oil; tracked under wheat/corn for Phase 1'},
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
    ]

    russian_queries = [
        'нефть санкции цена',
        'газ европейский экспорт',
        'пшеница экспорт черное море',
        'калий беларуськалий уралкалий',
        'уран росатом тенекс',
        'золото резервы брикс',
    ]

    chinese_queries = [
        '原油价格 制裁',
        '稀土出口 限制',
        '锂矿 电池',
        '钾肥 进口',
        '黄金储备 中国',
        '小麦 进口',
        '大豆 美国',
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
                # Note: per-country score weighting happens in _run_full_scan(); we just
                # record the country list here.
                for country_id, exposures in COUNTRY_COMMODITY_EXPOSURE.items():
                    if commodity_id in exposures:
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
                    # Country signal score weighted by its exposure to this commodity
                    exposure = COUNTRY_COMMODITY_EXPOSURE[country_id].get(cid, {})
                    country_weight = exposure.get('weight', 1.0)
                    weighted_sig = dict(sig)
                    weighted_sig['country_weight'] = country_weight
                    weighted_sig['country_role']   = exposure.get('role', 'unknown')
                    weighted_sig['country_note']   = exposure.get('note', '')
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

        # Per-commodity breakdown for this country
        commodity_breakdown = {}
        for commodity_id, exposure in COUNTRY_COMMODITY_EXPOSURE[cid].items():
            commodity_sigs = [s for s in sigs if s['commodity'] == commodity_id]
            commodity_breakdown[commodity_id] = {
                'role':         exposure.get('role'),
                'weight':       exposure.get('weight'),
                'rank':         exposure.get('rank'),
                'note':         exposure.get('note'),
                'signal_count': len(commodity_sigs),
                'top_signals':  commodity_sigs[:3],
            }

        country_summaries[cid] = {
            'country':            cid,
            'total_score':        score,
            'alert_level':        determine_alert_level(score),
            'commodity_signals':  commodity_breakdown,
            'top_signals':        sigs[:10],
        }

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success':                True,
        'scan_time_seconds':      scan_time,
        'days_analyzed':          days,
        'total_articles_scanned': len(all_articles),
        'total_signals_detected': len(all_signals),
        'commodity_summaries':    commodity_summaries,
        'country_summaries':      country_summaries,
        'top_signals':            sorted(all_signals, key=lambda s: s['weight'], reverse=True)[:30],
        'source_breakdown': {
            'rss':     len(rss_articles),
            'gdelt':   len(gdelt_articles),
            'newsapi': len(newsapi_articles),
            'reddit':  len(reddit_posts),
            'brave':   len(brave_articles),
        },
        'last_updated':           datetime.now(timezone.utc).isoformat(),
        'cached':                 False,
        'version':                '1.0.0',
    }

    save_commodity_cache(result)
    print(f"[Commodity Tracker] ✅ Scan complete in {scan_time}s")
    print(f"[Commodity Tracker]    Articles: {len(all_articles)}, Signals: {len(all_signals)}")
    print(f"[Commodity Tracker]    Sparklines: {sum(1 for s in sparklines.values() if s)}/{len(COMMODITY_TYPES)}")
    return result


# ========================================
# DASHBOARD INTEGRATION HELPER
# ========================================

def get_commodity_pressure(target):
    """
    Quick lookup for a country stability page. Returns the country's
    commodity exposure summary, ready to drop into a stability page card.

    Mirrors get_military_posture(target) signature.
    """
    try:
        if target not in COUNTRY_COMMODITY_EXPOSURE:
            return {
                'success':              True,
                'country':              target,
                'commodity_pressure':   None,
                'message':              f'No commodity exposure mapping for {target} (Phase 1 covers: belarus, russia, china, israel, ukraine).',
                'commodity_summaries':  [],
                'top_signals':          [],
                'alert_level':          'normal',
            }

        data = scan_commodity_pressure()
        country = data.get('country_summaries', {}).get(target, {})
        if not country:
            return {
                'success':              True,
                'country':              target,
                'commodity_pressure':   0,
                'alert_level':          'normal',
                'commodity_summaries':  [],
                'top_signals':          [],
                'message':              'Awaiting first scan.',
            }

        # Build a compact list of this country's commodity exposures with sparklines attached
        commodity_summaries = []
        for commodity_id, breakdown in country.get('commodity_signals', {}).items():
            full_summary = data.get('commodity_summaries', {}).get(commodity_id, {})
            commodity_summaries.append({
                'commodity':       commodity_id,
                'name':            full_summary.get('name'),
                'icon':            full_summary.get('icon'),
                'tier':            full_summary.get('tier'),
                'category':        full_summary.get('category'),
                'role':            breakdown.get('role'),
                'rank':            breakdown.get('rank'),
                'note':            breakdown.get('note'),
                'has_spot_price':  full_summary.get('has_spot_price'),
                'unit':            full_summary.get('unit'),
                'sparkline':       full_summary.get('sparkline'),
                'signal_count':    breakdown.get('signal_count'),
                'top_signals':     breakdown.get('top_signals', []),
            })

        return {
            'success':              True,
            'country':              target,
            'commodity_pressure':   country.get('total_score', 0),
            'alert_level':          country.get('alert_level', 'normal'),
            'commodity_summaries':  commodity_summaries,
            'top_signals':          country.get('top_signals', [])[:8],
            'detail_url':           '/commodities.html',
            'last_updated':         data.get('last_updated'),
        }

    except Exception as e:
        print(f"[Commodity Pressure] Error for {target}: {str(e)[:200]}")
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
