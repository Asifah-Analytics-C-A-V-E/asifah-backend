"""
egypt_stability.py -- Asifah Analytics (ME backend)
================================================================================
EGYPT STABILITY INDEX  v1.0.0  (Nov 1 2026)

WHAT THIS MEASURES
  CONDITIONS, not statements. Six dimensions of the Egyptian state's load:
    1. macro_fx        the pound, reserves, IMF programme, Gulf money, debt
    2. food_bread      wheat, the baladi bread subsidy, staple prices
    3. energy_grid     gas balance, Israeli gas, LNG, load-shedding, fuel prices
    4. external_rev    Suez Canal, tourism, remittances (the hard-currency lungs)
    5. security        Sinai, the borders (Gaza, Sudan, Libya), Red Sea threats
    6. social          protest, strikes, price anger -- STRUCTURALLY UNDER-SENSED
  What actors SAY lives in rhetoric_tracker_egypt.py. This module is the
  ground the rhetoric stands on; the two never double-count each other.

DOCTRINE (each one a mistake this module refuses to make)
  * Quiet is not calm in Egypt. The press environment suppresses dissent
    coverage, so the SOCIAL dimension never reads "calm". With no signal it
    reads "no signal through restricted media" and is EXCLUDED from the
    composite rather than counted as stable. (Rachel ruling, Nov 1 2026.)
  * Talk is not policy. "Egypt may devalue" is MOOTED, listed, not scored.
  * Relief is information. An IMF disbursement, a renewed Gulf deposit or a
    restarted gas flow is reported, and lowers a dimension; it never raises one.
  * The calendar amplifies, never fires. The summer power-demand peak and the
    Ramadan food window scale ACTIVE stress only; zero stays zero.
  * Absence is named. A failed market fetch is "unread", never a guessed
    number (the Israel module's hardcoded fallback rate is NOT copied here).
    A thin corpus is "Not Sensed", never "Quiet".
  * Commodity "pressure" is news-signal pressure on commodities Egypt touches
    (weighted volume/severity of reporting), NOT a price and NOT Egyptian
    stress. It is shown as context and never scored here.

INDEPENDENT INSTRUMENTS READ (proxy, never clone -- all ME-backend Redis)
  food_price_pulse_bundle        WFP measured domestic staple prices (EGY)
  worldbank:structural:latest    World Bank structural stressors (EGY)
  corridor:<id>:latest           corridor state (Europe backend writes)
  Markets (Yahoo Finance):       USD/EGP (EGP=X), EGX30 (^CASE30)

ENDPOINTS (register_egypt_stability_endpoints(app))
  GET /api/egypt/stability            cached payload; ?refresh=true (or
                                      ?force=true) starts a background rescan
                                      and returns the cache meanwhile
  GET /api/egypt/stability/trends     history for the trendline (?days=30)
  GET /api/egypt/stability/debug      config + cache freshness + source health

REDIS
  egypt:stability:latest       payload (12h TTL; refreshed every 6h)
  egypt:stability:history      {date: snapshot} (120 days)
  egypt:stability:fingerprint  compact dimension levels for the rhetoric
                               tracker, the ME BLUF and the GPI (13h TTL)

No Claude calls anywhere in this module.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta, date

import requests

MODULE_VERSION = '1.0.0'

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    feedparser = None
    FEEDPARSER_AVAILABLE = False
    print('[Egypt Stability] feedparser unavailable -- RSS disabled')

# GDELT only through the shared gateway; no direct fallback (one platform clock).
try:
    from gdelt_gateway import gdelt_fetch_probed as _gw_fetch_probed
    _GDELT_GATEWAY = True
except ImportError:
    _gw_fetch_probed = None
    _GDELT_GATEWAY = False
    print('[Egypt Stability] gdelt_gateway unavailable -- GDELT disabled this process')
try:
    from gdelt_trickle import register_queries as _trickle_register
except ImportError:
    _trickle_register = None
try:
    from newsapi_gateway import newsapi_fetch_probed as _newsapi_gw
except Exception:
    _newsapi_gw = None

# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))

REDIS_KEY_LATEST = 'egypt:stability:latest'
REDIS_KEY_HISTORY = 'egypt:stability:history'
REDIS_KEY_FINGERPRINT = 'egypt:stability:fingerprint'
CACHE_TTL_HOURS = 12
REFRESH_HOURS = 6
FINGERPRINT_TTL_HOURS = 13
HISTORY_TTL_DAYS = 120
INITIAL_SCAN_DELAY_SECONDS = 150
CACHE_FILE = '/tmp/egypt_stability_cache.json'

MIN_CORPUS_SENSED = 40        # fewer Egypt articles than this -> whole scan Not Sensed
MIN_LANE_TOPIC = 3            # fewer on-topic articles -> that dimension "thin"
RSS_MAX_AGE_DAYS = 8

HTTP_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
}

# ============================================================
# DATED ANCHORS (static -- every entry carries as_of + source)
# ============================================================
# The page shows these as background, never as live readings. Review every
# 45 days; the payload flags them as due once STATIC_REVIEWED ages past that.
STATIC_REVIEWED = '2026-11-01'
STATIC_REVIEW_DAYS = 45

STATIC_ANCHORS = [
    {'id': 'imf_eff', 'dimension': 'macro_fx',
     'label': 'IMF Extended Fund Facility',
     'value': '$8bn, 48 months; expires 15 Dec 2026. 7th review completed 30 Jul 2026 '
              '(~$1.8bn incl. RSF). Final EFF review + 3rd RSF review planned Q4 2026 (~$2.3bn).',
     'as_of': '2026-10-01', 'source': 'IMF via Ahram Online / Rio Times',
     'url': 'https://www.riotimesonline.com/egypt-economy-2026-imf-pound-inflation/'},
    {'id': 'cbe_rates', 'dimension': 'macro_fx',
     'label': 'Central Bank of Egypt policy rates',
     'value': 'Overnight deposit 19% / lending 20%, held 24 Sep 2026 (fifth straight hold; '
              'last move a 100bp cut, Feb 2026).',
     'as_of': '2026-09-24', 'source': 'CBE via Rio Times',
     'url': 'https://www.riotimesonline.com/egypt-economy-2026-imf-pound-inflation/'},
    {'id': 'inflation', 'dimension': 'macro_fx',
     'label': 'Urban headline inflation',
     'value': '14.5% y/y in Aug 2026 (core 14.9%; food 6.3%). CBE target 7% +/-2 by H2 2027.',
     'as_of': '2026-09-10', 'source': 'CAPMAS / CBE',
     'url': 'https://www.riotimesonline.com/egypt-economy-2026-imf-pound-inflation/'},
    {'id': 'reserves', 'dimension': 'macro_fx',
     'label': 'Net international reserves',
     'value': 'Record $57.2bn end-Aug 2026 (gold $19.1bn rising; FX component $37.6bn falling).',
     'as_of': '2026-08-31', 'source': 'CBE',
     'url': 'https://www.riotimesonline.com/egypt-economy-2026-imf-pound-inflation/'},
    {'id': 'gulf_deposits', 'dimension': 'macro_fx',
     'label': 'Gulf deposits at the CBE',
     'value': 'About $5.3bn falling due Oct 2026; renewal under negotiation (outcome not '
              'confirmed in our sources as of this date).',
     'as_of': '2026-10-19', 'source': 'Bloomberg via New Lines',
     'url': 'https://newlinesmag.com/running-notes/egypts-parliament-votes-on-sending-military-support-to-saudi-arabia/'},
    {'id': 'suez_revenue', 'dimension': 'external_rev',
     'label': 'Suez Canal revenue',
     'value': '$4.67bn in FY2025/26 (+23%); Aug 2026 $567m (+57% y/y). Still under half of '
              '2023 ($10.25bn). The rebound rides Saudi crude rerouted via Yanbu while Hormuz is shut.',
     'as_of': '2026-09-20', 'source': 'SCA via Rio Times',
     'url': 'https://www.riotimesonline.com/egypt-economy-2026-imf-pound-inflation/'},
    {'id': 'israeli_gas', 'dimension': 'energy_grid',
     'label': 'Israeli pipeline gas',
     'value': '2019 deal up to ~1 bcf/d; expanded $35bn Leviathan deal approved by Israel '
              'Dec 2025. Flows halted when the Iran war began (28 Feb 2026), resumed early '
              'April 2026. Egypt runs a ~2 bcf/d gas gap, closed with LNG via FSRUs.',
     'as_of': '2026-04-07', 'source': 'Ahram Online (17 Mar 2026) / The National (7 Apr 2026)',
     'url': 'https://www.thenationalnews.com/business/energy/2026/04/07/israeli-gas-exports-resume-but-egypt-is-counting-cost-of-energy-crunch-fuelled-by-war'},
    {'id': 'wheat_dependence', 'dimension': 'food_bread',
     'label': 'Wheat import dependence',
     'value': "World's #1 wheat importer; ~83% Black Sea (Russia ~66%, Ukraine ~17%), EU/France "
              "~14% the substitution margin. Baladi bread subsidy covers ~70M people. "
              "Mostakbal Misr (military-linked) replaced GASC as state buyer in late 2024.",
     'as_of': '2026-07', 'source': "Rachel's COUNTRY_COMMODITY_EXPOSURE note (corridor_dependence)",
     'url': ''},
    {'id': 'saudi_defence', 'dimension': 'security',
     'label': 'Authorisation to defend Saudi Arabia',
     'value': 'Parliament authorised the President on 26 Oct 2026 to support and defend Saudi '
              'Arabia against Houthi attacks. Sisi has said Egypt will defend Saudi territory '
              'and will not attack Yemen; Houthi officials have warned Cairo directly.',
     'as_of': '2026-10-26', 'source': 'Al Jazeera / Ahram Online',
     'url': 'https://www.aljazeera.com/news/2026/10/26/egyptian-parliament-authorises-military-aid-for-saudi-arabia'},
]

# Leadership -- only what was verified; review with the anchors.
LEADERSHIP_REVIEWED = '2026-11-01'
LEADERSHIP = [
    {'name': 'Abdel Fattah el-Sisi', 'title': 'President (in office since 2014; current term to 2030)',
     'icon': '\U0001F3DB️', 'status': 'IN OFFICE', 'verified': True},
    {'name': 'Mostafa Madbouly', 'title': 'Prime Minister (since 2018; retained in the Feb 2026 reshuffle)',
     'icon': '\U0001F4BC', 'status': 'IN OFFICE', 'verified': True},
    {'name': 'Gen. Ashraf Mansour', 'title': 'Minister of Defence (appointed Feb 2026)',
     'icon': '\U0001F396️', 'status': 'IN OFFICE', 'verified': True},
]

# Calendar: amplifiers only. Dates for Ramadan are approximate (moon sighting).
CALENDAR = {
    'imf_eff_expiry': '2026-12-15',
    'ramadan_windows': [('2027-02-07', '2027-03-09')],   # approximate
    'power_peak_months': (6, 7, 8, 9),                   # Jun-Sep demand peak
}
_ENERGY_PEAK_MULT = 1.25
_RAMADAN_FOOD_MULT = 1.15

# ============================================================
# COUNTRY GATE + LANES
# ============================================================
_EGYPT_GATE = re.compile(
    r"\b(egypt|egyptian|egyptians|cairo|sisi|el-sisi|al-sisi|madbouly|suez|sinai|"
    r"alexandria|rafah crossing|egp|cbe|egx|mostakbal misr|gasc)\b|"
    r"(مصر|المصري|القاهرة|"
    r"السيسي|مدبولي|السويس|"
    r"سيناء|الجنيه)", re.I)

_HEDGE_RX = re.compile(
    r"\b(could|may|might|consider(?:s|ing)?|mulls?|weighs?|plans? to|proposed?|"
    r"seeks?|calls? for|urged?|threatens? to|warns? of|fears?|risk of|forecasts?|"
    r"expected to|likely to|outlook|projected|ahead of|what if)\b|"
    r"(قد |من المتوقع|يدرس|محتمل)", re.I)

# Commentary is not an event (same lesson as the US tracker v1.4.1).
_COMMENTARY_RX = re.compile(
    r"^\s*(opinion|analysis|explainer|editorial|comment|podcast|explained)\b|"
    r"\b(what to know|what we know|op-ed|cheat sheet|q&a)\b", re.I)

# Each lane: topic_rx (is this article ABOUT the lane?) and patterns
# (direction, weight, regex). Weight 3 = event-grade, 2 = clear stress,
# 1 = soft. Relief patterns lower the lane; they never raise it.
LANES = {
    'macro_fx': {
        'label': 'Macro & currency', 'icon': '\U0001F4B1', 'weight': 0.25,
        'topic_rx': (r"\b(pound|egp|devalu\w*|exchange rate|imf|inflation|reserves?|"
                     r"eurobond|sukuk|debt|deposit|central bank|cbe|fitch|moody'?s|s&p|"
                     r"budget deficit|interest rates?)\b|"
                     r"(الجنيه|الدولار|"
                     r"صندوق النقد|التضخم|"
                     r"البنك المركزي)"),
        'patterns': [
            ('stress', 3, r"\b(devalu(?:e|es|ed|ation)|pound (?:plunges?|crashes|collapses|tumbles|slumps)|"
                          r"record low against the dollar|free[- ]float(?:s|ed)?)\b"),
            ('stress', 3, r"\b(default(?:s|ed)?|missed (?:a )?payment|debt restructuring|"
                          r"downgrade[sd]? egypt|cuts? egypt'?s? (?:credit )?rating)\b"),
            ('stress', 2, r"\b(black market|parallel (?:market|rate)|dollar shortage|fx shortage|"
                          r"imf (?:delays?|postpones?|suspends?|withholds?)|review (?:delayed|stalled))\b"),
            ('stress', 2, r"\b(inflation (?:jumps|surges|soars|accelerates|rises)|price hikes?)\b"),
            ('stress', 1, r"\b(pound (?:weakens|slips|falls|eases)|reserves (?:fall|drop|decline))\b"),
            ('stress', 2, r"(خفض قيمة الجنيه|"
                          r"تعويم|السوق السوداء|"
                          r"أزمة الدولار)"),
            ('relief', 2, r"\b(imf (?:approves|disburses|completes|releases)|completes? (?:the )?(?:\w+ )?review|"
                          r"deposits? (?:renewed|rolled over|extended)|rolls? over (?:\$[\d.]+ ?(?:bn|billion) )?deposits?|"
                          r"upgrade[sd]? egypt|raises? egypt'?s? (?:credit )?rating|record reserves|reserves (?:rise|climb|hit record))\b"),
            ('relief', 1, r"\b(inflation (?:eases|slows|falls|cools)|pound (?:strengthens|gains|rallies))\b"),
        ],
    },
    'food_bread': {
        'label': 'Food & bread', 'icon': '\U0001F35E', 'weight': 0.20,
        'topic_rx': (r"\b(wheat|bread|baladi|flour|subsid\w*|ration cards?|tender|"
                     r"mostakbal misr|gasc|food prices?|sugar|rice|cooking oil)\b|"
                     r"(القمح|الخبز|الدقيق|"
                     r"الدعم|بطاقات التموين|"
                     r"مستقبل مصر)"),
        'patterns': [
            ('stress', 3, r"\b(bread (?:price|subsidy) (?:hike|rise|increase|raised|cut)|raises? (?:the )?(?:price of )?subsidi[sz]ed bread|"
                          r"bread queues?|bread riots?|flour shortage|wheat shortage)\b"),
            ('stress', 2, r"\b(cancels? (?:a |its )?(?:wheat )?tender|tender (?:cancelled|scrapped|fails?)|"
                          r"delayed payments?|unpaid (?:wheat )?cargoes|broken (?:wheat )?deals?|"
                          r"wheat reserves? (?:fall|drop|low))\b"),
            ('stress', 2, r"\b(food (?:prices|inflation) (?:jump|surge|soar|spike)|sugar (?:shortage|crisis)|"
                          r"rice (?:shortage|crisis)|ration (?:cut|reduced))\b"),
            ('stress', 2, r"(رفع سعر الخبز|أزمة الخبز|"
                          r"نقص القمح|نقص الدقيق|"
                          r"طوابير الخبز)"),
            ('relief', 1, r"\b(buys? (?:\d[\d,.]* ?(?:k|kt|tonnes|tons|mt) of )?wheat|wheat purchases?|procures?|"
                          r"record (?:wheat )?harvest|strategic reserves? (?:sufficient|cover|enough))\b"),
        ],
    },
    'energy_grid': {
        'label': 'Energy & grid', 'icon': '⚡', 'weight': 0.15,
        'topic_rx': (r"\b(gas|lng|electricity|power cuts?|blackouts?|load[- ]shedding|outages?|"
                     r"fuel prices?|petrol|diesel|leviathan|tamar|zohr|fsru|grid)\b|"
                     r"(الكهرباء|انقطاع|"
                     r"تخفيف الأحمال|الغاز|"
                     r"الوقود|البنزين)"),
        'patterns': [
            ('stress', 3, r"\b(israel (?:halts?|suspends?|stops?|cuts?) (?:gas )?(?:exports?|supplies|flows?)|"
                          r"(?:gas )?(?:exports?|supplies|flows?) to egypt (?:halted|suspended|stopped|cut)|"
                          r"leviathan (?:shut|halt|closed))\b"),
            ('stress', 3, r"\b(load[- ]shedding|rolling (?:power )?cuts|nationwide (?:blackout|outage))\b"),
            ('stress', 2, r"\b(power cuts?|blackouts?|outages?|fertili[sz]er plants? (?:halt|shut|stop))\b"),
            ('stress', 2, r"\b(fuel prices? (?:hike|rise|raised|increase)|raises? fuel prices|petrol price (?:hike|rise)|"
                          r"gas shortage|lng (?:shortfall|delay))\b"),
            ('stress', 2, r"(تخفيف الأحمال|انقطاع الكهرباء|"
                          r"رفع أسعار الوقود|وقف الغاز)"),
            ('relief', 2, r"\b((?:gas )?(?:exports?|flows?|supplies) (?:to egypt )?(?:resume|resumed|restored|restart)|"
                          r"leviathan (?:resumes?|restarts?)|new gas discovery|lng cargoes? (?:arrive|secured))\b"),
        ],
    },
    'external_rev': {
        'label': 'Suez & external revenue', 'icon': '\U0001F6A2', 'weight': 0.15,
        'topic_rx': (r"\b(suez|canal|transits?|red sea|bab el-mandeb|shipping|tourism|tourists?|"
                     r"remittances?|yanbu|petroline|container lines?)\b|"
                     r"(قناة السويس|البحر الأحمر|"
                     r"السياحة|تحويلات)"),
        'patterns': [
            ('stress', 3, r"\b(suez (?:canal )?(?:closed|blocked|shut)|bab el-mandeb (?:closed|closure|blocked)|"
                          r"(?:ship|vessel|tanker) (?:attacked|struck|hit) (?:in|near) the red sea)\b"),
            ('stress', 2, r"\b(suez (?:canal )?revenues? (?:fall|drop|plunge|slump|decline)|transits? (?:fall|drop|plunge)|"
                          r"(?:reroute|divert)\w* (?:around|via) the cape|avoid(?:s|ing)? the red sea|"
                          r"tourists? (?:cancel|flee)|travel warnings?)\b"),
            ('stress', 2, r"\b(houthis? (?:threaten|warn)\w* (?:egypt|cairo|suez)|yanbu (?:attacked|struck|hit)|"
                          r"petroline (?:attacked|struck|hit))\b"),
            ('stress', 2, r"(تراجع إيرادات قناة السويس|"
                          r"إغلاق باب المندب)"),
            ('relief', 2, r"\b(suez (?:canal )?revenues? (?:rise|jump|climb|surge|rebound|record)|"
                          r"transits? (?:rise|recover|rebound)|return(?:s|ing)? to the (?:suez|red sea)|"
                          r"tourism (?:record|rebound|rises|surges)|remittances? (?:rise|record|jump))\b"),
        ],
    },
    'security': {
        'label': 'Security & borders', 'icon': '\U0001F6E1️', 'weight': 0.15,
        'topic_rx': (r"\b(sinai|militants?|attack|terror\w*|border|rafah|gaza|sudan|libya|"
                     r"drone|missile|soldiers?|army|troops|houthi\w*|isis|wilayat)\b|"
                     r"(سيناء|هجوم|إرهاب|الحدود|"
                     r"رفح|مسيرة)"),
        'patterns': [
            ('stress', 3, r"\b((?:militants?|gunmen|terrorists?) (?:kill|attack|ambush)\w*|"
                          r"(?:egyptian )?soldiers? killed|attack on (?:egyptian )?(?:troops|checkpoint|army)|"
                          r"bomb(?:ing)? in (?:cairo|sinai|alexandria|el-arish))\b"),
            ('stress', 3, r"\b(drone (?:hits?|struck|crashes|lands) (?:in )?(?:taba|nuweiba|sinai|egypt)|"
                          r"missile (?:hits?|lands|struck) (?:in )?(?:egypt|sinai|taba))\b"),
            ('stress', 2, r"\b(border (?:clash|incident|shooting)|(?:israeli|idf) (?:fire|troops) (?:at|on) the egypt\w* border|"
                          r"philadelphi|rafah crossing (?:closed|shut)|sudan(?:ese)? (?:refugees?|fighting) (?:at|near) the border|"
                          r"rsf (?:near|at|approach\w*) (?:the )?egypt\w* border)\b"),
            ('stress', 2, r"(هجوم إرهابي|استشهاد|"
                          r"مسيرة (?:سقطت|في) (?:طابا|سيناء))"),
            ('stress', 1, r"\b(security alert|heightened security|state of emergency)\b"),
        ],
    },
    'social': {
        'label': 'Social & political', 'icon': '\U0001F465', 'weight': 0.10,
        'under_sensed': True,
        'topic_rx': (r"\b(protests?|protesters?|demonstrat\w*|strikes?|arrests?|detain\w*|crackdown|"
                     r"dissent|activists?|riot\w*|unrest|sit-in|workers)\b|"
                     r"(احتجاج|مظاهرات|اعتصام|"
                     r"إضراب|اعتقال)"),
        'patterns': [
            ('stress', 3, r"\b(protests? (?:erupt|spread|across)|riots?|clashes with (?:police|security forces)|"
                          r"protesters? killed)\b"),
            ('stress', 2, r"\b(protests? (?:over|against) (?:prices|bread|fuel|electricity|cost of living)|"
                          r"workers? (?:strike|walk out|sit-in)|mass arrests?|crackdown on)\b"),
            ('stress', 2, r"(مظاهرات|احتجاجات|"
                          r"إضراب العمال|اعتصام)"),
            ('stress', 1, r"\b(arrest(?:s|ed)? (?:of )?(?:activists?|journalists?)|detained (?:activists?|journalists?))\b"),
        ],
    },
}

for _lane in LANES.values():
    _lane['_topic'] = re.compile(_lane['topic_rx'], re.I)
    _lane['_pats'] = [(d, w, re.compile(rx, re.I)) for d, w, rx in _lane['patterns']]

LEVEL_WORDS = ['calm', 'watch', 'strained', 'acute']
LEVEL_COLORS = {'calm': '#38bdf8', 'watch': '#f59e0b', 'strained': '#f97316',
                'acute': '#dc2626', 'not_sensed': '#6b7280', 'under_sensed': '#6b7280'}


def _lane_level(score):
    if score >= 60:
        return 'acute'
    if score >= 35:
        return 'strained'
    if score >= 15:
        return 'watch'
    return 'calm'


# ============================================================
# SOURCES
# ============================================================
def _gn(q, lang='en'):
    from urllib.parse import quote_plus
    if lang == 'ar':
        return f'https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&hl=ar&gl=EG&ceid=EG:ar'
    return f'https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&hl=en-US&gl=US&ceid=US:en'


RSS_FEEDS = {
    'ahram_en':    {'url': 'https://english.ahram.org.eg/rss/ahram.aspx', 'name': 'Ahram Online', 'language': 'en', 'weight': 1.0},
    'gn_economy':  {'url': _gn('Egypt (pound OR IMF OR inflation OR reserves OR deposits)'), 'name': 'Google News', 'language': 'en', 'weight': 0.9},
    'gn_food':     {'url': _gn('Egypt (wheat OR bread OR subsidy OR "Mostakbal Misr")'), 'name': 'Google News', 'language': 'en', 'weight': 0.9},
    'gn_energy':   {'url': _gn('Egypt (gas OR LNG OR electricity OR "power cuts" OR fuel)'), 'name': 'Google News', 'language': 'en', 'weight': 0.9},
    'gn_suez':     {'url': _gn('"Suez Canal" (revenue OR transits OR shipping OR Houthi)'), 'name': 'Google News', 'language': 'en', 'weight': 0.9},
    'gn_security': {'url': _gn('Egypt (Sinai OR border OR Rafah OR militants OR drone)'), 'name': 'Google News', 'language': 'en', 'weight': 0.9},
    'gn_social':   {'url': _gn('Egypt (protest OR strike OR arrests OR crackdown)'), 'name': 'Google News', 'language': 'en', 'weight': 0.9},
    'gn_ar_econ':  {'url': _gn('مصر الجنيه الدولار صندوق النقد', 'ar'), 'name': 'Google News AR', 'language': 'ar', 'weight': 0.9},
    'gn_ar_bread': {'url': _gn('مصر الخبز القمح الدعم', 'ar'), 'name': 'Google News AR', 'language': 'ar', 'weight': 0.9},
    'gn_ar_power': {'url': _gn('مصر انقطاع الكهرباء الغاز', 'ar'), 'name': 'Google News AR', 'language': 'ar', 'weight': 0.9},
    'gn_ar_suez':  {'url': _gn('قناة السويس إيرادات', 'ar'), 'name': 'Google News AR', 'language': 'ar', 'weight': 0.9},
    'gn_ar_sinai': {'url': _gn('سيناء الحدود مصر هجوم', 'ar'), 'name': 'Google News AR', 'language': 'ar', 'weight': 0.9},
}

GDELT_QUERIES = [
    ('Egypt (pound OR IMF OR inflation OR devaluation)', 'eng'),
    ('Egypt (wheat OR bread OR subsidy)', 'eng'),
    ('Egypt (gas OR electricity OR blackout OR LNG)', 'eng'),
    ('"Suez Canal" (revenue OR transits OR Houthi)', 'eng'),
    ('Egypt (Sinai OR border OR protest)', 'eng'),
    ('مصر', 'ara'),
]

# Two NewsAPI queries -- the gateway budget is shared by every ME tracker.
NEWSAPI_QUERIES = [
    'Egypt (pound OR IMF OR wheat OR bread OR "Suez Canal")',
    'Egypt (gas OR electricity OR blackout OR Sinai OR protest)',
]

_SOURCE_HEALTH = {}


def _reset_health():
    _SOURCE_HEALTH.clear()
    _SOURCE_HEALTH.update({
        'rss': {'feeds': 0, 'feeds_ok': 0, 'articles': 0, 'failed': []},
        'gdelt': {'queries': 0, 'sensed': 0, 'articles': 0, 'not_sensed': {}},
        'newsapi': {'queries': 0, 'sensed': 0, 'articles': 0, 'not_sensed': {}},
    })


def _rss_entry_too_old(entry):
    st = entry.get('published_parsed') or entry.get('updated_parsed')
    if not st:
        return False
    try:
        dt = datetime(*st[:6], tzinfo=timezone.utc)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - dt) > timedelta(days=RSS_MAX_AGE_DAYS)


def fetch_rss(feed_id, cfg, max_articles=40):
    h = _SOURCE_HEALTH['rss']
    h['feeds'] += 1
    if not FEEDPARSER_AVAILABLE:
        h['failed'].append(feed_id)
        return []
    out = []
    try:
        feed = feedparser.parse(cfg['url'], agent=HTTP_HEADERS['User-Agent'])
        for e in (feed.entries or [])[:max_articles]:
            if _rss_entry_too_old(e):
                continue
            out.append({
                'title': (e.get('title') or '').strip(),
                'description': re.sub(r'<[^>]+>', ' ', e.get('summary', '') or '')[:400],
                'url': e.get('link', ''),
                'published': e.get('published', '') or e.get('updated', ''),
                'source': cfg['name'], 'feed_id': feed_id, 'feed_type': 'rss',
                'language': cfg.get('language', 'en'),
            })
        if out:
            h['feeds_ok'] += 1
        else:
            h['failed'].append(feed_id)
    except Exception as e:
        h['failed'].append(feed_id)
        print(f'[Egypt Stability] RSS {feed_id} error: {str(e)[:100]}')
    h['articles'] += len(out)
    return out


def fetch_gdelt(query, language, days=7):
    h = _SOURCE_HEALTH['gdelt']
    if not _GDELT_GATEWAY:
        h['not_sensed']['no_gateway'] = h['not_sensed'].get('no_gateway', 0) + 1
        return []
    h['queries'] += 1
    q = f'{query} sourcelang:english' if language == 'eng' else query
    try:
        raw, probe = _gw_fetch_probed(q, language=language, timespan=f'{days}d',
                                      maxrecords=50, label='egypt_stab/' + language)
    except Exception as e:
        h['not_sensed']['exception'] = h['not_sensed'].get('exception', 0) + 1
        print(f'[Egypt Stability] GDELT error: {str(e)[:100]}')
        return []
    if (probe or {}).get('sensed'):
        h['sensed'] += 1
    else:
        r = (probe or {}).get('reason') or 'unknown'
        h['not_sensed'][r] = h['not_sensed'].get(r, 0) + 1
    out = []
    for it in raw or []:
        out.append({'title': it.get('title', ''), 'description': '', 'url': it.get('url', ''),
                    'published': it.get('published', '') or it.get('seendate', ''),
                    'source': it.get('source') or it.get('domain') or 'GDELT',
                    'feed_id': 'gdelt', 'feed_type': 'gdelt',
                    'language': 'ar' if language == 'ara' else 'en'})
    h['articles'] += len(out)
    return out


def fetch_newsapi(query, days=7, have=None):
    h = _SOURCE_HEALTH['newsapi']
    if _newsapi_gw is None:
        h['not_sensed']['no_gateway'] = h['not_sensed'].get('no_gateway', 0) + 1
        return []
    h['queries'] += 1
    try:
        raw, probe = _newsapi_gw(query, days=days, page_size=30,
                                 label='egypt_stab/' + query.split()[1].strip('(').lower(), have=have)
    except Exception as e:
        raw, probe = [], {'sensed': False, 'reason': 'exception:' + type(e).__name__}
    if (probe or {}).get('sensed'):
        h['sensed'] += 1
    else:
        r = (probe or {}).get('reason') or 'unknown'
        h['not_sensed'][r] = h['not_sensed'].get(r, 0) + 1
    out = []
    for it in raw or []:
        out.append({'title': it.get('title', '') or '', 'description': it.get('description', '') or '',
                    'url': it.get('url', ''), 'published': it.get('publishedAt', ''),
                    'source': (it.get('source') or {}).get('name', 'NewsAPI'),
                    'feed_id': 'newsapi', 'feed_type': 'newsapi', 'language': 'en'})
    h['articles'] += len(out)
    return out


def gather_articles(days=7):
    _reset_health()
    arts = []
    for fid, cfg in RSS_FEEDS.items():
        arts.extend(fetch_rss(fid, cfg))
    if _trickle_register and _GDELT_GATEWAY:
        try:
            _trickle_register('egypt_stability', [
                {'query': (f'{q} sourcelang:english' if l == 'eng' else q), 'language': l,
                 'timespan': f'{days}d', 'maxrecords': 50} for q, l in GDELT_QUERIES])
        except Exception as e:
            print(f'[Egypt Stability] trickle registration failed (non-fatal): {str(e)[:80]}')
    for q, l in GDELT_QUERIES:
        arts.extend(fetch_gdelt(q, l, days))
    have = len(arts)
    for q in NEWSAPI_QUERIES:
        arts.extend(fetch_newsapi(q, days, have=have))
    return _dedupe(arts)


def _norm_title(t):
    t = re.sub(r'\s+-\s+[^-]{2,60}$', '', t or '')      # drop " - Publisher"
    return re.sub(r'[^\w؀-ۿ]+', ' ', t.lower()).strip()


def _dedupe(arts):
    seen_u, seen_t, out = set(), set(), []
    for a in arts:
        u = (a.get('url') or '').split('?')[0]
        t = _norm_title(a.get('title'))
        if not t:
            continue
        if (u and u in seen_u) or t in seen_t:
            continue
        if u:
            seen_u.add(u)
        seen_t.add(t)
        out.append(a)
    return out


# ============================================================
# MARKETS (Yahoo) -- absence-honest, no invented fallback values
# ============================================================
def _yahoo_series(symbol, rng='1mo'):
    """(meta, [(iso, close)]) or (None, reason). Tries query1 then query2."""
    last = 'no response'
    for host in ('query1', 'query2'):
        try:
            r = requests.get(f'https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}',
                             params={'interval': '1d', 'range': rng}, headers=HTTP_HEADERS, timeout=10)
            if r.status_code != 200:
                last = f'HTTP {r.status_code}'
                continue
            res = ((r.json() or {}).get('chart') or {}).get('result') or []
            if not res:
                last = 'empty result'
                continue
            res = res[0]
            ts = res.get('timestamp') or []
            closes = ((res.get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
            series = [(datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(), round(float(c), 4))
                      for t, c in zip(ts, closes) if c is not None]
            if not series:
                last = 'no closes'
                continue
            return res.get('meta') or {}, series
        except Exception as e:
            last = type(e).__name__
    return None, last


def fetch_market(symbol, label, unit):
    meta, series = _yahoo_series(symbol)
    if meta is None:
        return {'symbol': symbol, 'label': label, 'sensed': False, 'reason': series,
                'source': 'Yahoo Finance'}
    price = meta.get('regularMarketPrice') or series[-1][1]
    first = series[0][1]
    prev = series[-2][1] if len(series) >= 2 else None
    return {
        'symbol': symbol, 'label': label, 'unit': unit, 'sensed': True,
        'value': round(float(price), 4),
        'change_1d_pct': round((series[-1][1] - prev) / prev * 100, 2) if prev else None,
        'change_30d_pct': round((series[-1][1] - first) / first * 100, 2) if first else None,
        'sparkline': [{'date': d, 'value': v} for d, v in series],
        'as_of': series[-1][0], 'source': 'Yahoo Finance',
    }


def market_stress(fx, egx):
    """0-100 stress from the pound (USD/EGP up = pound weaker) and EGX30."""
    parts, notes = [], []
    if fx.get('sensed'):
        c30 = fx.get('change_30d_pct') or 0.0
        c1 = fx.get('change_1d_pct') or 0.0
        s = 0
        if c30 >= 15:
            s = 80
        elif c30 >= 7:
            s = 50
        elif c30 >= 3:
            s = 25
        if c1 >= 5:                          # one-day step = devaluation-grade move
            s = max(s, 75)
            notes.append(f'pound fell {c1:.1f}% in one session (devaluation-grade move)')
        elif c30 >= 3:
            notes.append(f'pound {c30:.1f}% weaker over 30 days')
        elif c30 <= -3:
            notes.append(f'pound {abs(c30):.1f}% stronger over 30 days')
        parts.append(s)
    if egx.get('sensed'):
        e30 = egx.get('change_30d_pct') or 0.0
        s = 0
        if e30 <= -15:
            s = 60
        elif e30 <= -8:
            s = 35
        elif e30 <= -4:
            s = 15
        if e30 <= -4:
            notes.append(f'EGX30 down {abs(e30):.1f}% over 30 days')
        parts.append(s)
    if not parts:
        return None, ['markets unread this cycle']
    return max(parts), notes


# ============================================================
# CROSS-INSTRUMENT READS (Redis, read-only)
# ============================================================
def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(f'{UPSTASH_REDIS_URL}/get/{key}',
                         headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'}, timeout=8)
        if r.status_code != 200:
            return None
        raw = (r.json() or {}).get('result')
        if raw is None:
            return None
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        print(f'[Egypt Stability] Redis GET error ({key}): {str(e)[:100]}')
        return None


def _redis_set(key, value, ttl_seconds):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(f'{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_seconds)}',
                          headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                          data=json.dumps(value, default=str), timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f'[Egypt Stability] Redis SET error ({key}): {str(e)[:100]}')
        return False


_BAND_SCORE = {'normal': 0, 'watch': 20, 'elevated': 45, 'high': 70}


def read_food_pulse():
    """WFP measured domestic staple prices for Egypt."""
    bundle = _redis_get('food_price_pulse_bundle')
    if not isinstance(bundle, dict):
        return {'sensed': False, 'reason': 'food price pulse bundle not in Redis',
                'source': 'WFP VAM via HDX'}
    c = (bundle.get('countries') or {}).get('EGY')
    if not isinstance(c, dict):
        return {'sensed': False, 'reason': 'Egypt not in the latest WFP bundle',
                'source': 'WFP VAM via HDX'}
    band = c.get('band') or 'normal'
    staples = {k: {'band': v.get('band'), 'yoy_pct': v.get('yoy_pct'), 'mom_pct': v.get('mom_pct'),
                   'latest_month': v.get('latest_month')}
               for k, v in (c.get('staples') or {}).items()}
    return {'sensed': band != 'stale', 'band': band, 'score': _BAND_SCORE.get(band, 0),
            'anomalous_staples': c.get('anomalous_staples') or [], 'staples': staples,
            'data_as_of': c.get('data_as_of'), 'source': 'WFP VAM via HDX',
            'reason': None if band != 'stale' else 'WFP data stale'}


def read_structural():
    """World Bank structural stressors for Egypt (context; not scored here)."""
    p = _redis_get('worldbank:structural:latest')
    if not isinstance(p, dict):
        return {'sensed': False, 'reason': 'World Bank structural feed not in Redis'}
    rec = (p.get('by_country') or {}).get('EGY')
    if not isinstance(rec, dict):
        return {'sensed': True, 'stress_severity': 0, 'stressed': [], 'extreme': [],
                'note': 'Egypt below the structural-stress floor', 'generated_at': p.get('generated_at')}
    ind = rec.get('indicators') or {}
    return {'sensed': True, 'stress_severity': rec.get('stress_severity', 0),
            'stressed': rec.get('stressed') or [], 'extreme': rec.get('extreme') or [],
            'indicators': {k: {'value': v.get('value'), 'unit': v.get('unit'), 'year': v.get('year')}
                           for k, v in ind.items() if isinstance(v, dict)},
            'generated_at': p.get('generated_at'), 'source': 'World Bank WDI'}


CORRIDORS = [('black_sea_grain_corridor', 'Black Sea grain corridor', 'food_bread'),
             ('red_sea', 'Red Sea / Bab el-Mandeb', 'external_rev'),
             ('suez_canal', 'Suez Canal', 'external_rev')]


def read_corridors():
    out = []
    for cid, label, dim in CORRIDORS:
        rec = _redis_get(f'corridor:{cid}:latest')
        st = str(rec.get('live_state')).lower() if isinstance(rec, dict) and rec.get('live_state') else 'unknown'
        out.append({'id': cid, 'label': label, 'dimension': dim, 'state': st,
                    'sensed': st != 'unknown',
                    'note': None if st != 'unknown' else 'no corridor sensor record -- unread, not open'})
    return out


# ============================================================
# CLASSIFY + SCORE
# ============================================================
def _text(a):
    return f"{a.get('title') or ''} . {a.get('description') or ''}"


def _is_commentary(a):
    return bool(_COMMENTARY_RX.search(a.get('title') or ''))


def classify(articles):
    """Assign each Egypt-gated article to every lane whose topic it touches,
    and record pattern hits (stress / relief / mooted)."""
    lanes = {k: {'topic': [], 'hits': []} for k in LANES}
    egypt = []
    skipped_commentary = 0
    for a in articles:
        txt = _text(a)
        if not _EGYPT_GATE.search(txt):
            continue
        egypt.append(a)
        if _is_commentary(a):
            skipped_commentary += 1
            continue
        title = a.get('title') or ''
        for lid, lane in LANES.items():
            if not lane['_topic'].search(txt):
                continue
            lanes[lid]['topic'].append(a)
            best = None
            for direction, w, rx in lane['_pats']:
                m = rx.search(title) or rx.search(txt)
                if not m:
                    continue
                src = title if rx.search(title) else txt
                m2 = rx.search(src)
                hedged = direction == 'stress' and bool(_HEDGE_RX.search(src[max(0, m2.start() - 45):m2.start()]))
                cand = {'direction': 'mooted' if hedged else direction, 'weight': w,
                        'pattern': m2.group(0)[:60]}
                if best is None or (cand['direction'] == 'stress' and best['direction'] != 'stress') \
                        or (cand['direction'] == best['direction'] and w > best['weight']):
                    best = cand
            if best:
                lanes[lid]['hits'].append({**best, 'title': title[:200], 'url': a.get('url'),
                                           'source': a.get('source'), 'published': a.get('published'),
                                           'language': a.get('language')})
    return egypt, lanes, skipped_commentary


def _calendar_state(today=None):
    today = today or datetime.now(timezone.utc).date()
    exp = date.fromisoformat(CALENDAR['imf_eff_expiry'])
    ramadan = None
    for s, e in CALENDAR['ramadan_windows']:
        sd, ed = date.fromisoformat(s), date.fromisoformat(e)
        if sd <= today <= ed:
            ramadan = {'start': s, 'end': e, 'approximate': True}
    return {
        'today': today.isoformat(),
        'imf_eff_expiry': CALENDAR['imf_eff_expiry'],
        'days_to_imf_expiry': (exp - today).days,
        'imf_window_open': 0 <= (exp - today).days <= 60,
        'energy_peak': today.month in CALENDAR['power_peak_months'],
        'ramadan': ramadan,
    }


def score_lane(lid, data, cal, extra=None):
    lane = LANES[lid]
    topic_n = len(data['topic'])
    hits = data['hits']
    stress = [h for h in hits if h['direction'] == 'stress']
    relief = [h for h in hits if h['direction'] == 'relief']
    mooted = [h for h in hits if h['direction'] == 'mooted']
    stress_pts = sum(h['weight'] for h in stress)
    relief_pts = sum(h['weight'] for h in relief)
    # 3 event-grade stories ~ strained; diminishing beyond that.
    news = min(100.0, 12.0 * stress_pts) if stress_pts else 0.0
    # Corroboration: one story alone can put a dimension on WATCH, never
    # higher. Strained/acute need two or more independent stress reports.
    if len(stress) == 1:
        news = min(news, 34.0)
    if news and relief_pts:
        news = max(0.0, news - min(news * 0.3, 6.0 * relief_pts))
    mult, mult_note = 1.0, None
    if lid == 'energy_grid' and cal.get('energy_peak') and news:
        mult, mult_note = _ENERGY_PEAK_MULT, 'summer power-demand peak (Jun-Sep) amplifies active stress'
    if lid == 'food_bread' and cal.get('ramadan') and news:
        mult, mult_note = _RAMADAN_FOOD_MULT, 'Ramadan demand window (approximate dates) amplifies active stress'
    news = min(100.0, news * mult)

    instruments = []
    score = news
    if extra:
        for inst in extra:
            instruments.append(inst)
            if inst.get('sensed') and inst.get('score') is not None:
                score = max(score, float(inst['score']))
    score = round(score)

    under = bool(lane.get('under_sensed'))
    if under and not stress:
        level, sensed = 'under_sensed', False
        state_note = ('No signal through restricted media. Egypt\'s press environment '
                      'suppresses dissent coverage, so absence here is a property of the '
                      'sources, not a reading of calm.')
    elif topic_n < MIN_LANE_TOPIC and not stress and not relief \
            and not any(i.get('sensed') for i in instruments):
        level, sensed = 'not_sensed', False
        state_note = f'Thin coverage ({topic_n} on-topic articles) -- not sensed this cycle.'
    else:
        level, sensed = _lane_level(score), True
        state_note = None
    ev = sorted(stress, key=lambda h: -h['weight'])[:5] + relief[:2] + mooted[:2]
    return {
        'id': lid, 'label': lane['label'], 'icon': lane['icon'], 'weight': lane['weight'],
        'sensed': sensed, 'level': level, 'color': LEVEL_COLORS.get(level, '#6b7280'),
        'score': score if sensed else None, 'news_score': round(news),
        'topic_articles': topic_n, 'stress_count': len(stress), 'relief_count': len(relief),
        'mooted_count': len(mooted), 'calendar_multiplier': mult, 'calendar_note': mult_note,
        'instruments': instruments, 'evidence': ev, 'note': state_note,
        'under_sensed': under,
    }


_STAB_BANDS = [(75, 'Stable', '#38bdf8'), (60, 'Pressured', '#f59e0b'),
               (45, 'Strained', '#f97316'), (30, 'Fragile', '#ef4444'), (0, 'Critical', '#dc2626')]


def composite(dims):
    """Stability 0-100 (higher = more stable). Unsensed dimensions are
    EXCLUDED and the weights renormalised -- never counted as calm."""
    used = [d for d in dims.values() if d['sensed'] and d['score'] is not None]
    excluded = [d['id'] for d in dims.values() if not d['sensed']]
    if not used:
        return {'score': None, 'label': 'Not Sensed', 'color': '#6b7280', 'level': None,
                'excluded': excluded, 'coverage_weight': 0.0}
    wsum = sum(d['weight'] for d in used)
    stress = sum(d['score'] * d['weight'] for d in used) / wsum
    # The worst dimension pulls the composite: a state is as stable as its
    # most stressed load-bearing wall, not the average of its walls.
    worst = max(d['score'] for d in used)
    stress = 0.7 * stress + 0.3 * worst
    score = round(100 - stress)
    label, color = next((lbl, col) for floor, lbl, col in _STAB_BANDS if score >= floor)
    level = {'Stable': 1, 'Pressured': 2, 'Strained': 3, 'Fragile': 4, 'Critical': 5}[label]
    return {'score': score, 'label': label, 'color': color, 'level': level,
            'excluded': excluded, 'coverage_weight': round(wsum, 2),
            'driver': max(used, key=lambda d: d['score'] * d['weight'])['id']}


# ============================================================
# SO WHAT
# ============================================================
_DIM_SO_WHAT = {
    'macro_fx': ("The pound is the transmission belt: a weaker pound raises the cost of every "
                 "imported calorie and every LNG cargo at once."),
    'food_bread': ("Egypt's failure mode is fiscal before it is hunger: a wheat shock lands on "
                   "the subsidy bill and the FX position first, and on the street only if the "
                   "state passes the cost through."),
    'energy_grid': ("Gas is Egypt's quiet hinge to Israel: when Israeli flows stop, Cairo buys "
                    "LNG in dollars, and fertilizer plants are the first load shed."),
    'external_rev': ("Suez is coupled to the Saudi bypass: with Hormuz shut, Saudi crude leaves "
                     "via Yanbu and the canal, so a hit on the Petroline or Yanbu would cut "
                     "Riyadh's exports and Egypt's canal take together."),
    'security': ("Every border is live at once -- Gaza/Rafah, Sudan, Libya -- and the Saudi "
                 "defence authorisation adds a Red Sea exposure the Houthis have named."),
    'social': ("Absence of reported protest is not evidence of calm in Egypt; it is the "
               "expected output of the media environment."),
}


def build_so_what(dims, comp, cal, market_notes, structural):
    lines = []
    active = sorted([d for d in dims.values() if d['sensed'] and d['level'] in ('strained', 'acute')],
                    key=lambda d: -(d['score'] or 0))
    watch = [d for d in dims.values() if d['sensed'] and d['level'] == 'watch']
    if comp['score'] is None:
        head = 'Egypt not sensed this cycle -- too few articles to read conditions.'
    elif active:
        names = ', '.join(d['label'].lower() for d in active[:2])
        head = f"Egypt reads {comp['label'].upper()} ({comp['score']}/100): {names} under strain."
    elif watch:
        head = (f"Egypt reads {comp['label'].upper()} ({comp['score']}/100): "
                f"{', '.join(d['label'].lower() for d in watch[:3])} on watch; nothing acute.")
    else:
        head = f"Egypt reads {comp['label'].upper()} ({comp['score']}/100): no sensed dimension above watch."
    for d in (active or watch)[:2]:
        if _DIM_SO_WHAT.get(d['id']):
            lines.append(_DIM_SO_WHAT[d['id']])
    if cal.get('imf_window_open') or 0 <= cal.get('days_to_imf_expiry', -1) <= 60:
        lines.append(f"The IMF programme expires {cal['imf_eff_expiry']} "
                     f"({cal['days_to_imf_expiry']} days): the final review is the next hard date "
                     f"for the pound, and what follows the programme is not yet announced.")
    if structural.get('sensed') and 'water_stress' in (structural.get('extreme') or []):
        lines.append("The World Bank's extreme flag on Egypt is WATER, not money -- the Nile/GERD "
                     "question is the structural stressor, and it sits on the southern flank.")
    if market_notes:
        lines.append('Markets: ' + '; '.join(market_notes) + '.')
    unsensed = [d['label'] for d in dims.values() if not d['sensed']]
    if unsensed:
        lines.append('Not counted (unsensed, not calm): ' + ', '.join(unsensed) + '.')
    return {'headline': head, 'lines': lines}


# ============================================================
# SCAN
# ============================================================
_scan_lock = threading.Lock()
_scan_running = {'active': False, 'started': None}


def scan_egypt_stability(days=7):
    t0 = time.time()
    now = datetime.now(timezone.utc)
    cal = _calendar_state()
    articles = gather_articles(days)
    egypt, lanes, skipped = classify(articles)
    fx = fetch_market('EGP=X', 'USD/EGP (pounds per dollar)', 'EGP')
    egx = fetch_market('^CASE30', 'EGX30 index', 'pts')
    m_score, m_notes = market_stress(fx, egx)
    food = read_food_pulse()
    structural = read_structural()
    corridors = read_corridors()

    corpus_ok = len(egypt) >= MIN_CORPUS_SENSED
    extra = {
        'macro_fx': [{'id': 'markets', 'label': 'Markets (pound + EGX30)', 'sensed': m_score is not None,
                      'score': m_score, 'note': '; '.join(m_notes)}],
        'food_bread': [{'id': 'wfp_prices', 'label': 'WFP measured staple prices',
                        'sensed': food.get('sensed', False), 'score': food.get('score'),
                        'note': (f"band {food.get('band')} (data as of {food.get('data_as_of')})"
                                 if food.get('sensed') else food.get('reason'))}],
    }
    for c in corridors:
        if c['sensed'] and c['state'] in ('impaired', 'blocked'):
            extra.setdefault(c['dimension'], []).append(
                {'id': 'corridor_' + c['id'], 'label': c['label'], 'sensed': True,
                 'score': 55 if c['state'] == 'impaired' else 80, 'note': f"corridor reads {c['state'].upper()}"})

    dims = {}
    for lid in LANES:
        dims[lid] = score_lane(lid, lanes[lid], cal, extra.get(lid))
        if not corpus_ok and not any(i.get('sensed') for i in dims[lid]['instruments']):
            dims[lid].update(sensed=False, score=None, level='not_sensed',
                             color=LEVEL_COLORS['not_sensed'],
                             note=f'Whole scan thin ({len(egypt)} Egypt articles) -- not sensed.')
    comp = composite(dims)
    so_what = build_so_what(dims, comp, cal, m_notes, structural)

    reviewed = date.fromisoformat(STATIC_REVIEWED)
    static_age = (now.date() - reviewed).days
    lang_counts = {}
    for a in egypt:
        lang_counts[a.get('language', 'en')] = lang_counts.get(a.get('language', 'en'), 0) + 1

    payload = {
        'success': True, 'country': 'egypt', 'version': MODULE_VERSION,
        'scanned_at': now.isoformat(), 'scan_seconds': round(time.time() - t0, 1),
        'sensed': comp['score'] is not None,
        'stability': comp,
        'so_what': so_what,
        'dimensions': dims,
        'markets': {'fx': fx, 'egx30': egx, 'stress': m_score, 'notes': m_notes},
        'instruments': {'food_pulse': food, 'structural': structural, 'corridors': corridors},
        'calendar': cal,
        'static_anchors': STATIC_ANCHORS,
        'static_reviewed': STATIC_REVIEWED,
        'static_review_due': static_age > STATIC_REVIEW_DAYS,
        'leadership': LEADERSHIP, 'leadership_reviewed': LEADERSHIP_REVIEWED,
        'coverage': {
            'articles_total': len(articles), 'articles_egypt': len(egypt),
            'by_language': lang_counts, 'skipped_commentary': skipped,
            'min_corpus_sensed': MIN_CORPUS_SENSED, 'sources': dict(_SOURCE_HEALTH),
        },
        'articles': [{k: a.get(k) for k in ('title', 'url', 'source', 'published', 'language', 'feed_type')}
                     for a in egypt[:80]],
        'doctrine': ('Conditions, not predictions. Unsensed dimensions are excluded, never '
                     'counted as calm. Social signal is structurally under-sensed in Egypt.'),
    }
    _persist(payload)
    print(f"[Egypt Stability] scan done: {len(egypt)}/{len(articles)} Egypt articles, "
          f"stability={comp['score']} ({comp['label']}), {payload['scan_seconds']}s")
    return payload


def _persist(payload):
    _redis_set(REDIS_KEY_LATEST, payload, CACHE_TTL_HOURS * 3600)
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(payload, f, default=str)
    except Exception:
        pass
    dims = payload['dimensions']
    fp = {
        'country': 'egypt', 'version': MODULE_VERSION, 'written_at': payload['scanned_at'],
        'stability_score': payload['stability']['score'], 'stability_label': payload['stability']['label'],
        'stability_level': payload['stability']['level'],
        'dimensions': {k: {'level': v['level'], 'score': v['score'], 'sensed': v['sensed']} for k, v in dims.items()},
        'days_to_imf_expiry': payload['calendar']['days_to_imf_expiry'],
        'fx_change_30d_pct': (payload['markets']['fx'] or {}).get('change_30d_pct'),
    }
    _redis_set(REDIS_KEY_FINGERPRINT, fp, FINGERPRINT_TTL_HOURS * 3600)
    hist = _redis_get(REDIS_KEY_HISTORY)
    hist = hist if isinstance(hist, dict) else {}
    hist[payload['scanned_at'][:10]] = {
        'stability': payload['stability']['score'],
        'dims': {k: v['score'] for k, v in dims.items()},
        'usd_egp': (payload['markets']['fx'] or {}).get('value'),
        'egx30': (payload['markets']['egx30'] or {}).get('value'),
        'method': 'v1.0',
    }
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=HISTORY_TTL_DAYS)).isoformat()
    hist = {k: v for k, v in hist.items() if k >= cutoff}
    _redis_set(REDIS_KEY_HISTORY, hist, HISTORY_TTL_DAYS * 86400)


def load_cache():
    c = _redis_get(REDIS_KEY_LATEST)
    if c:
        return c
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _age_hours(payload):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(payload['scanned_at'])).total_seconds() / 3600
    except Exception:
        return None


def _run_scan_guarded():
    with _scan_lock:
        if _scan_running['active']:
            return False
        _scan_running.update(active=True, started=datetime.now(timezone.utc).isoformat())
    try:
        scan_egypt_stability()
    except Exception as e:
        print(f'[Egypt Stability] scan error: {e}')
        traceback.print_exc()
    finally:
        _scan_running['active'] = False
    return True


def _background_loop():
    time.sleep(INITIAL_SCAN_DELAY_SECONDS)
    try:
        from instance_lock import own_this_job as _own
    except ImportError:
        def _own(_name):
            return True
    while True:
        try:
            if _own('egypt_stability_scan'):
                c = load_cache()
                age = _age_hours(c) if c else None
                if age is None or age >= REFRESH_HOURS:
                    _run_scan_guarded()
            else:
                print('[Egypt Stability] another instance owns the scan; standing by')
        except Exception as e:
            print(f'[Egypt Stability] loop error: {e}')
        time.sleep(30 * 60)


# ============================================================
# FLASK
# ============================================================
def register_egypt_stability_endpoints(app, start_background=True):
    from flask import jsonify, request

    @app.route('/api/egypt/stability', methods=['GET', 'OPTIONS'])
    def api_egypt_stability():
        if request.method == 'OPTIONS':
            return ('', 204)
        force = (request.args.get('refresh', '') or request.args.get('force', '')).lower() in ('true', '1', 'yes')
        cached = load_cache()
        if force:
            started = False
            if not _scan_running['active']:
                threading.Thread(target=_run_scan_guarded, daemon=True).start()
                started = True
            if cached:
                cached = dict(cached)
                cached['from_cache'] = True
                cached['rescan'] = 'started' if started else 'already_running'
                return jsonify(cached)
            return jsonify({'success': True, 'sensed': False, 'warming': True,
                            'rescan': 'started' if started else 'already_running',
                            'note': 'First scan running (about 1-2 minutes). Reload shortly.'}), 202
        if cached:
            cached = dict(cached)
            cached['from_cache'] = True
            age = _age_hours(cached)
            cached['cache_age_hours'] = round(age, 2) if age is not None else None
            if age is not None and age >= CACHE_TTL_HOURS:
                cached['stale'] = True
            return jsonify(cached)
        if not _scan_running['active']:
            threading.Thread(target=_run_scan_guarded, daemon=True).start()
        return jsonify({'success': True, 'sensed': False, 'warming': True,
                        'note': 'No cached scan yet; first scan started. Reload in 1-2 minutes.'}), 202

    @app.route('/api/egypt/stability/trends', methods=['GET'])
    def api_egypt_stability_trends():
        try:
            days = max(1, min(int(request.args.get('days', 30)), HISTORY_TTL_DAYS))
        except ValueError:
            days = 30
        hist = _redis_get(REDIS_KEY_HISTORY)
        hist = hist if isinstance(hist, dict) else {}
        keys = sorted(hist)[-days:]
        return jsonify({'success': bool(keys), 'days_collected': len(keys),
                        'dates': keys, 'points': [hist[k] for k in keys]})

    @app.route('/api/egypt/stability/debug', methods=['GET'])
    def api_egypt_stability_debug():
        c = load_cache()
        return jsonify({
            'version': MODULE_VERSION, 'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'feedparser': FEEDPARSER_AVAILABLE, 'gdelt_gateway': _GDELT_GATEWAY,
            'newsapi_gateway': _newsapi_gw is not None, 'rss_feeds': len(RSS_FEEDS),
            'gdelt_queries': len(GDELT_QUERIES), 'newsapi_queries': len(NEWSAPI_QUERIES),
            'lanes': list(LANES), 'cache_present': bool(c),
            'cache_age_hours': round(_age_hours(c), 2) if c and _age_hours(c) is not None else None,
            'scan_running': _scan_running, 'static_reviewed': STATIC_REVIEWED,
            'last_coverage': (c or {}).get('coverage'),
        })

    print('[Egypt Stability] Routes registered: /api/egypt/stability, /trends, /debug')
    if start_background:
        threading.Thread(target=_background_loop, daemon=True, name='EgyptStabilityBG').start()
        print(f'[Egypt Stability] background loop started (first check in {INITIAL_SCAN_DELAY_SECONDS}s)')
