"""
rhetoric_tracker_egypt.py -- Asifah Analytics (ME backend)
================================================================================
EGYPT RHETORIC & PRESSURE TRACKER  v1.0.0  (Nov 1 2026)

THE HUB QUESTION
  "Which of Egypt's six fronts is moving, and which global market does it touch?"
  Egypt is a crossroads tracker -- the inverse of Syria's transition tracker.
  It does not ask "is Egypt about to break?" (egypt_stability.py reads the
  conditions). It asks where the pressure on Cairo is coming FROM this week,
  and what that pressure is coupled to outside Egypt.

THE SIX FRONTS (vectors; Rachel ruling Nov 1 2026)
  1. gulf_defence    Mecca Pact orbit: the 26 Oct authorisation to defend Saudi
                     Arabia; Houthi warnings to Cairo.          -> touches CRUDE
  2. suez_red_sea    Canal transits/revenue, Bab el-Mandeb, the Yanbu bypass.
                                                               -> touches FREIGHT
  3. bread_balance   Wheat, the bread subsidy, the IMF, Gulf deposits, the pound.
                                                               -> touches WHEAT
  4. southern_flank  Sudan's war (Egypt backs the SAF), refugees, Halaib, the
                     Nile and GERD.                          -> touches WATER/GOLD
  5. eastern_flank   Gaza, Rafah, Sinai, the 1979 treaty -- AND Israeli gas.
                                                           -> touches GAS/FERTILIZER
  6. western_flank   Libya: Haftar's east, the border.        -> touches LIBYAN CRUDE

ACTORS ARE SPEAKERS, FRONTS ARE TOPICS
  An article is attributed to whoever is talking (presidency, military,
  Houthis, Israel...) and to every front it is about. A Houthi warning to Cairo
  is a houthis-actor statement on the gulf_defence front.

DOCTRINE (each one a mistake this tracker refuses to make)
  * Commentary is not an event (explainers, op-eds, "what to know" skipped).
  * Talk is not action: hedged phrasing ("could", "may", "warns of") cannot
    lift a front above L1.
  * A claim is not a confirmation: a sentence that attributes an attack to
    the attacker ("Houthis say they struck...") is a CLAIM and is capped at L3
    unless Egyptian or neutral confirmation is present (Saudi v2.3.0 lesson).
  * Corroboration: L3 and L4 need two or more distinct sources; a single
    source caps one rung lower.
  * L5 is never asserted from keywords (L5 assertion rule). Ceiling here: L4.
  * Neighbour lenses (Sudan, Libya, Saudi, Yemen trackers; Egypt stability)
    are READ, never re-scanned -- proxy, not clone. A lens can lift a front to
    L2 at most on its own: context, not an event in Egypt.
  * Quiet is not calm: a thin corpus reads Not Sensed; an unread lens says so.

OUTPUT
  Redis rhetoric:egypt:latest        payload (ME BLUF reads this; 12h TTL)
        rhetoric:egypt:history       LPUSH snapshots (direction arrows)
        rhetoric:egypt:fingerprint   front levels for the Saudi tracker and the
                                     Mecca Pact card (13h TTL)
  GET /api/rhetoric/egypt            cached; ?refresh=true starts a rescan
  GET /api/rhetoric/egypt/debug

No Claude calls anywhere in this module.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta

import requests

MODULE_VERSION = '1.0.1'   # Nov 1 2026: Gaza aid != Egyptian bread stress; 'Study|' is commentary; Saudi lens lanes

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    feedparser = None
    FEEDPARSER_AVAILABLE = False
    print('[Egypt Rhetoric] feedparser unavailable -- RSS disabled')
try:
    from gdelt_gateway import gdelt_fetch_probed as _gw_fetch_probed
    _GDELT_GATEWAY = True
except ImportError:
    _gw_fetch_probed = None
    _GDELT_GATEWAY = False
    print('[Egypt Rhetoric] gdelt_gateway unavailable -- GDELT disabled this process')
try:
    from gdelt_trickle import register_queries as _trickle_register
except ImportError:
    _trickle_register = None
try:
    from newsapi_gateway import newsapi_fetch_probed as _newsapi_gw
except Exception:
    _newsapi_gw = None

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))

REDIS_KEY_LATEST = 'rhetoric:egypt:latest'
REDIS_KEY_HISTORY = 'rhetoric:egypt:history'
REDIS_KEY_FINGERPRINT = 'rhetoric:egypt:fingerprint'
CACHE_TTL_HOURS = 12
REFRESH_HOURS = 6
FINGERPRINT_TTL_HOURS = 13
INITIAL_SCAN_DELAY_SECONDS = 210      # after egypt_stability's first scan
CACHE_FILE = '/tmp/egypt_rhetoric_cache.json'
WINDOW_DAYS = 7
RSS_MAX_AGE_DAYS = 8
MIN_CORPUS_SENSED = 40
MIN_FRONT_TOPIC = 3
L_CEILING = 4

HTTP_HEADERS = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                               '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')}

# The PLATFORM ladder words and colours (severity_canon.PLATFORM_LEVELS /
# asifah-standard-shell.js ASIFAH_LADDER) -- not a private ladder. On the
# kinetic axis L4 means "armed incident", which is what this tracker's L4 rung
# requires; L5+ is never asserted from keywords here.
LEVEL_LABELS = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning', 3: 'Confrontation', 4: 'Coercion',
                5: 'Active Conflict', 6: 'Red Line Breached'}
LEVEL_COLORS = {0: '#6b7280', 1: '#3b82f6', 2: '#f59e0b', 3: '#f97316', 4: '#ef4444',
                5: '#dc2626', 6: '#991b1b'}

# ============================================================
# COUNTRY GATE
# ============================================================
_EGYPT_GATE = re.compile(
    r"\b(egypt|egyptian|egyptians|cairo|sisi|el-sisi|al-sisi|madbouly|suez|sinai|"
    r"alexandria|rafah crossing|mostakbal misr|abdelatty)\b|"
    r"(مصر|المصري|القاهرة|"
    r"السيسي|مدبولي|السويس|"
    r"سيناء)", re.I)

_HEDGE_RX = re.compile(
    r"\b(could|may|might|would|consider(?:s|ing)?|mulls?|weighs?|plans? to|proposed?|"
    r"seeks?|calls? for|urged?|warns? of|fears?|risk of|forecasts?|expected to|"
    r"likely to|ready to|prepared to|if asked|if requested|threatens? to|vows? to)\b|"
    r"(قد |مستعد|محتمل|يدرس)", re.I)

_COMMENTARY_RX = re.compile(
    r"^\s*(opinion|analysis|explainer|editorial|comment|podcast|explained|interview|study|research)\b|"
    r"\b(what to know|what we know|op-ed|cheat sheet|q&a|why it matters)\b", re.I)

# Claim attribution (Saudi v2.3.0 lesson): attacker says it struck -> claim.
_CLAIM_VERB_RX = re.compile(r"\b(say|says|said|claim|claims|claimed|announce[sd]?|"
                            r"boast(?:s|ed)?|according to)\b|(أعلن|يعلن|زعم)", re.I)
_CLAIMANT_RX = re.compile(r"\b(houthis?|ansar\s?allah|ansarullah|saree|al-bukhaiti|rsf|hemedti|"
                          r"rapid support forces)\b|(الحوثي|أنصار الله|"
                          r"الدعم السريع)", re.I)
_CONFIRMS_RX = re.compile(r"\b(egyptian (?:army|military|armed forces|spokesman|authorities|officials?) "
                          r"(?:said|says|confirmed)|military spokesman confirmed|"
                          r"suez canal authority (?:said|confirmed)|ukmto|reuters witnesses)\b|"
                          r"(المتحدث العسكري)", re.I)

# v1.0.1 (Nov 1 2026). First live scan read bread_balance at L4 "Coercion" from
# "Egypt sends 280 aid trucks to tackle Gaza bread shortage" -- Egypt was the
# SENDER, the shortage was Gaza's. Gaza-locus stories are routed to the
# eastern flank (where Gaza lives) and never climb the bread ladder.
_GAZA_LOCUS = re.compile(r"\b(gaza|gazans?|palestin\w*|west bank|unrwa)\b|(\u063a\u0632\u0629|\u0641\u0644\u0633\u0637\u064a\u0646)", re.I)
_LOCUS_EXCLUDED_FRONTS = {'bread_balance': _GAZA_LOCUS}

# ============================================================
# ACTORS (speakers)
# ============================================================
def _rx(*parts):
    return re.compile('|'.join(parts), re.I)


ACTORS = {
    'egypt_presidency': {
        'name': 'Presidency & Cabinet', 'flag': '\U0001F1EA\U0001F1EC', 'icon': '\U0001F3DB️',
        'role': 'Sisi, the presidency spokesman, PM Madbouly', 'side': 'egypt', 'mode': 'actor',
        'rx': _rx(r"\b(sisi|el-sisi|al-sisi|egyptian president|presidential spokesman|madbouly|egyptian (?:cabinet|prime minister))\b",
                  r"(السيسي|الرئاسة|مدبولي|رئيس الوزراء)"),
    },
    'egypt_military': {
        'name': 'Armed Forces & Defence', 'flag': '\U0001F1EA\U0001F1EC', 'icon': '\U0001F396️',
        'role': 'Defence Minister, military spokesman, National Defense Council', 'side': 'egypt', 'mode': 'actor',
        'rx': _rx(r"\b(egyptian (?:army|military|armed forces|air force|navy|troops|forces|defen[cs]e minist(?:er|ry))|"
                  r"military spokesman|national defen[cs]e council|ashraf mansour)\b",
                  r"(القوات المسلحة|المتحدث العسكري|"
                  r"وزير الدفاع|مجلس الدفاع الوطني)"),
    },
    'egypt_parliament': {
        'name': 'Parliament', 'flag': '\U0001F1EA\U0001F1EC', 'icon': '⚖️',
        'role': 'House of Representatives (the 2/3 vote for deployments abroad)', 'side': 'egypt', 'mode': 'actor',
        'rx': _rx(r"\b(egyptian (?:parliament|lawmakers|mps)|house of representatives|egypt'?s parliament)\b",
                  r"(مجلس النواب|البرلمان المصري)"),
    },
    'egypt_mfa': {
        'name': 'Foreign Ministry', 'flag': '\U0001F1EA\U0001F1EC', 'icon': '\U0001F91D',
        'role': 'Diplomacy: Gaza, Sudan, GERD, Libya, the Gulf', 'side': 'egypt', 'mode': 'actor',
        'rx': _rx(r"\b(egyptian foreign (?:minister|ministry)|egypt'?s foreign minister|abdelatty|egyptian diplomat)\b",
                  r"(وزير الخارجية|الخارجية المصرية|عبد العاطي)"),
    },
    'egypt_economic': {
        'name': 'Economic Institutions', 'flag': '\U0001F1EA\U0001F1EC', 'icon': '\U0001F4B1',
        'role': 'CBE, Finance, Supply, Petroleum, the Suez Canal Authority', 'side': 'egypt', 'mode': 'actor',
        'rx': _rx(r"\b(central bank of egypt|cbe|egypt'?s finance minist(?:er|ry)|supply minist(?:er|ry)|"
                  r"petroleum minist(?:er|ry)|suez canal authority|sca chairman|mostakbal misr|egas)\b",
                  r"(البنك المركزي|وزير المالية|"
                  r"وزير التموين|وزير البترول|"
                  r"هيئة قناة السويس)"),
    },
    'houthis': {
        'name': 'Houthis (on Egypt)', 'flag': '\U0001F1FE\U0001F1EA', 'icon': '\U0001F3AF',
        'role': 'Warnings to Cairo over the Saudi defence vote; Red Sea', 'side': 'external', 'mode': 'actor',
        'rx': _rx(r"\b(houthis?|ansar\s?allah|ansarullah|saree|al-bukhaiti|sanaa)\b",
                  r"(الحوثي|أنصار الله|صنعاء)"),
    },
    'israel': {
        'name': 'Israel (on Egypt)', 'flag': '\U0001F1EE\U0001F1F1', 'icon': '\U0001F6E1️',
        'role': 'Rafah/Philadelphi, Sinai troop levels, the gas pipeline', 'side': 'external', 'mode': 'tape',
        'rx': _rx(r"\b(israel|israeli|idf|netanyahu|leviathan|tamar)\b",
                  r"(إسرائيل|الاحتلال)"),
    },
    'gulf_patrons': {
        'name': 'Gulf patrons', 'flag': '\U0001F1F8\U0001F1E6', 'icon': '\U0001F4B0',
        'role': 'Saudi Arabia, UAE, Qatar, Kuwait: deposits, investment, the pact', 'side': 'external', 'mode': 'tape',
        'rx': _rx(r"\b(saudi|riyadh|mbs|bin salman|uae|emirati|abu dhabi|qatar|doha|kuwait|mecca pact)\b",
                  r"(السعودية|الرياض|الإمارات|قطر|الكويت)"),
    },
    'sudan_parties': {
        'name': 'Sudan (SAF / RSF)', 'flag': '\U0001F1F8\U0001F1E9', 'icon': '⚔️',
        'role': 'Burhan (Egypt-backed) and Hemedti', 'side': 'external', 'mode': 'tape',
        'rx': _rx(r"\b(sudan|sudanese|burhan|saf|rsf|hemedti|rapid support forces|port sudan|khartoum)\b",
                  r"(السودان|البرهان|حميدتي|الدعم السريع)"),
    },
    'ethiopia': {
        'name': 'Ethiopia (GERD)', 'flag': '\U0001F1EA\U0001F1F9', 'icon': '\U0001F30A',
        'role': 'The Grand Ethiopian Renaissance Dam and the Nile', 'side': 'external', 'mode': 'tape',
        'rx': _rx(r"\b(ethiopia|ethiopian|abiy|gerd|renaissance dam|addis ababa)\b",
                  r"(إثيوبيا|سد النهضة|آبي)"),
    },
    'libya_parties': {
        'name': 'Libya (east and west)', 'flag': '\U0001F1F1\U0001F1FE', 'icon': '\U0001F3DC️',
        'role': 'Haftar / LNA (Egypt-backed), Dbeibah / Tripoli', 'side': 'external', 'mode': 'tape',
        'rx': _rx(r"\b(libya|libyan|haftar|lna|tripoli|benghazi|dbeibah|tobruk)\b",
                  r"(ليبيا|حفتر|طرابلس|بنغازي)"),
    },
    'western_lenders': {
        'name': 'IMF & Western partners', 'flag': '\U0001F30D', 'icon': '\U0001F3E6',
        'role': 'IMF, US, EU: the programme, aid, the 15 Dec EFF expiry', 'side': 'external', 'mode': 'tape',
        'rx': _rx(r"\b(imf|international monetary fund|georgieva|world bank|european union|eu |washington|state department|pentagon)\b",
                  r"(صندوق النقد|الاتحاد الأوروبي)"),
    },
}

# ============================================================
# FRONTS (vectors) -- topic + escalation ladder
# ============================================================
# Ladder entries: (level, regex). L1 is "on-topic coverage exists"; the ladder
# starts at L2. Relief entries record de-escalation and never raise a front.
FRONTS = {
    'gulf_defence': {
        'label': 'Gulf defence', 'icon': '\U0001F6E1️', 'market': 'crude (the Petroline / Yanbu bypass)',
        'topic': _rx(r"\b(saudi|riyadh|mecca pact|houthis?|yemen|defend(?:ing)? (?:the )?(?:kingdom|saudi)|gulf security)\b",
                     r"(السعودية|الحوثي|اليمن|أمن الخليج)"),
        'ladder': [
            (2, _rx(r"\b(authori[sz](?:es|ed|ation)|pledge[sd]?|military support|defend saudi|support (?:to|for) saudi|solidarity with (?:the )?kingdom)\b",
                    r"(تفويض|دعم السعودية|الدفاع عن المملكة)")),
            (3, _rx(r"\b(houthis? (?:warn|threaten)\w*|warns? (?:egypt|cairo)|egyptian (?:troops|forces|jets|air defen[cs]e|warships?) (?:deploy|arrive|sent|dispatched)\w*|"
                    r"deploy\w* (?:to|in) saudi|send\w* (?:troops|forces|jets) (?:to|into) saudi|national security threat)\b",
                    r"(تهديد|يحذر مصر|نشر قوات)")),
            (4, _rx(r"\b(egyptian (?:soldiers?|troops|pilots?|personnel) (?:killed|wounded|injured)|"
                    r"(?:struck|hit|target\w*) egyptian (?:forces|troops|air defen[cs]es?|positions?|ships?|warships?)|"
                    r"(?:houthi|drone|missile) (?:attack|strike)\w* (?:on|at) (?:an? )?egyptian|"
                    r"egyptian (?:jets|forces|air defen[cs]es?) (?:intercept|shoot down|shot down|strike|struck))\w*\b")),
        ],
        'relief': _rx(r"\b(de-escalat\w*|truce|ceasefire|talks with (?:the )?houthis|mediation)\b"),
    },
    'suez_red_sea': {
        'label': 'Suez & Red Sea', 'icon': '\U0001F6A2', 'market': 'container and tanker freight; war-risk insurance',
        'topic': _rx(r"\b(suez|canal|red sea|bab el-mandeb|bab al-mandab|shipping|tankers?|yanbu|petroline|transits?)\b",
                     r"(السويس|البحر الأحمر|باب المندب|الملاحة)"),
        'ladder': [
            (2, _rx(r"\b(revenues? (?:fall|drop|decline|slump)|divert\w*|reroute\w*|cape of good hope|war[- ]risk (?:premium|insurance))\b",
                    r"(تراجع الإيرادات|تحويل السفن)")),
            (3, _rx(r"\b(declar\w* (?:a )?(?:closure|blockade)|clos(?:e|es|ure) (?:of )?(?:the )?bab el-mandeb|threat\w* to shipping|"
                    r"insurers? (?:pull|suspend)\w*|shipping lines? (?:suspend|halt)\w*)\b",
                    r"(إغلاق باب المندب|حظر الملاحة)")),
            (4, _rx(r"\b((?:ship|vessel|tanker|bulk carrier) (?:attacked|struck|hit|seized|sunk|ablaze)|"
                    r"canal (?:blocked|closed|shut)|yanbu (?:attacked|struck|hit)|petroline (?:attacked|struck|hit))\b",
                    r"(استهداف سفينة|إغلاق القناة)")),
        ],
        'relief': _rx(r"\b(revenues? (?:rise|jump|rebound|record)|return(?:s|ing)? to the (?:suez|red sea)|transits? (?:rise|recover))\b"),
    },
    'bread_balance': {
        'label': 'Bread & balance sheet', 'icon': '\U0001F35E', 'market': "wheat (Egypt is the world's #1 importer)",
        'topic': _rx(r"\b(wheat|bread|subsid\w*|imf|pound|devalu\w*|deposits?|inflation|mostakbal misr|gasc|fuel prices?|eurobond)\b",
                     r"(القمح|الخبز|الدعم|صندوق النقد|الجنيه|الوقود)"),
        'ladder': [
            (2, _rx(r"\b(imf (?:delays?|postpones?)|review (?:delayed|stalled)|subsidy (?:reform|cuts?)|tender (?:cancelled|scrapped)|"
                    r"delayed (?:wheat )?payments?|black market)\b",
                    r"(تأجيل المراجعة|السوق السوداء)")),
            (3, _rx(r"\b(raises? (?:the price of )?(?:subsidi[sz]ed )?bread|bread price (?:hike|rise|increase)|raises? fuel prices|"
                    r"fuel price (?:hike|rise|increase)|devalu(?:es|ed|ation)|pound (?:plunges?|crashes)|imf (?:suspends?|halts?))\b",
                    r"(رفع سعر الخبز|رفع أسعار الوقود|تعويم الجنيه)")),
            (4, _rx(r"\b(bread (?:queues?|shortages?|riots?)|protests? over (?:bread|prices|fuel)|flour shortage|missed (?:a )?(?:debt )?payment|default)\b",
                    r"(طوابير الخبز|نقص الدقيق|احتجاجات الخبز)")),
        ],
        'relief': _rx(r"\b(imf (?:approves|disburses|completes|releases)|deposits? (?:renewed|rolled over|extended)|"
                      r"rolls? over|buys? (?:[\d,.]+ ?(?:k|kt|tonnes|tons) of )?wheat|inflation (?:eases|slows))\b"),
    },
    'southern_flank': {
        'label': 'Sudan & the Nile', 'icon': '\U0001F30A', 'market': 'Nile water; Sudan gold and refugee flows',
        'topic': _rx(r"\b(sudan|sudanese|rsf|saf|burhan|hemedti|halaib|nile|gerd|renaissance dam|ethiopia|aswan|wadi halfa|argeen)\b",
                     r"(السودان|النيل|سد النهضة|حلايب|إثيوبيا)"),
        'ladder': [
            (2, _rx(r"\b(refugees? (?:flee|cross|arriv)\w*|water security|nile (?:dispute|talks)|gerd (?:talks|filling|turbines?))\b",
                    r"(الأمن المائي|اللاجئين السودانيين)")),
            (3, _rx(r"\b(red line|existential (?:threat|issue)|all options|unilateral (?:filling|action)|border (?:closed|closure)|"
                    r"accus\w* egypt|egyptian (?:jets|drones|aircraft) in sudan)\b",
                    r"(خط أحمر|كل الخيارات|تهديد وجودي)")),
            (4, _rx(r"\b((?:egyptian|egypt'?s) (?:air ?strikes?|drone strikes?|strike) (?:in|on) sudan|"
                    r"(?:shelling|fire|clash\w*) (?:at|on|near) the egypt\w* border|rsf (?:attack|strike)\w* (?:on|near) egypt\w*)\b")),
        ],
        'relief': _rx(r"\b(agreement on (?:the )?(?:nile|gerd|filling)|ceasefire in sudan|humanitarian truce|refugees? return)\b"),
    },
    'eastern_flank': {
        'label': 'Gaza, Sinai & Israeli gas', 'icon': '⚡', 'market': 'East Med gas, LNG and fertilizer',
        'topic': _rx(r"\b(gaza|rafah|sinai|philadelphi|camp david|peace treaty|israel\w*|leviathan|tamar|gas (?:exports?|supplies|flows?))\b",
                     r"(غزة|رفح|سيناء|إسرائيل|معاهدة السلام|الغاز)"),
        'ladder': [
            (2, _rx(r"\b(gas (?:flows?|exports?|supplies) (?:reduced|cut|fall)|sinai (?:troop|military) (?:build-?up|presence)|"
                    r"treaty (?:strain|violation)|displacement (?:into|to) sinai|crossing (?:closed|shut))\b",
                    r"(انخفاض إمدادات الغاز|التهجير إلى سيناء)")),
            (3, _rx(r"\b((?:halts?|suspends?|stops?) (?:gas )?(?:exports?|supplies|flows?) to egypt|recall\w* (?:its )?ambassador|"
                    r"summon\w* (?:the )?(?:israeli )?ambassador|downgrade\w* (?:diplomatic )?relations|freeze\w* the (?:gas )?deal)\b",
                    r"(وقف ضخ الغاز|استدعاء السفير|تجميد)")),
            (4, _rx(r"\b(egyptian (?:soldiers?|border guards?|officers?) (?:killed|shot|wounded)|exchange of fire|"
                    r"(?:israeli|idf) (?:strike|fire)\w* (?:on|at|near) the egypt\w* border|shooting at the border)\b",
                    r"(استشهاد جندي مصري|تبادل إطلاق النار)")),
        ],
        'relief': _rx(r"\b((?:gas )?(?:exports?|flows?|supplies) (?:resume|resumed|restored)|rafah (?:reopen|reopened)|aid (?:enters|entering) gaza)\b"),
    },
    'western_flank': {
        'label': 'Libya', 'icon': '\U0001F3DC️', 'market': 'Libyan crude (force majeure risk)',
        'topic': _rx(r"\b(libya|libyan|haftar|lna|tripoli|benghazi|salloum|sirte|jufra|tobruk)\b",
                     r"(ليبيا|حفتر|سرت|السلوم)"),
        'ladder': [
            (2, _rx(r"\b(egypt\w* (?:backs?|support\w*) haftar|border security|smuggling|militants? (?:cross|infiltrat)\w*|oil (?:blockade|shutdown|force majeure))\b",
                    r"(تأمين الحدود|تهريب)")),
            (3, _rx(r"\b(sirte[- ]jufra|red line|direct intervention|egyptian (?:troops|forces) (?:mass|deploy)\w* (?:on|at|near) the (?:libyan )?border)\b",
                    r"(خط أحمر|سرت-الجفرة|تدخل مباشر)")),
            (4, _rx(r"\b(egyptian (?:air ?strikes?|strikes?) (?:in|on) libya|clash\w* (?:on|at) the (?:egypt|libya)\w* border)\b")),
        ],
        'relief': _rx(r"\b(unified government|elections? (?:agreed|scheduled)|oil (?:output|exports?) (?:resume|restored))\b"),
    },
}

# ============================================================
# SOURCES
# ============================================================
def _gn(q, lang='en'):
    from urllib.parse import quote_plus
    if lang == 'ar':
        return f'https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&hl=ar&gl=EG&ceid=EG:ar'
    return f'https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&hl=en-US&gl=US&ceid=US:en'


RSS_FEEDS = {
    'ahram_en':  {'url': 'https://english.ahram.org.eg/rss/ahram.aspx', 'name': 'Ahram Online', 'language': 'en'},
    'gn_gulf':   {'url': _gn('Egypt (Saudi OR Houthi OR "Mecca pact") (defend OR troops OR support)'), 'name': 'Google News', 'language': 'en'},
    'gn_suez':   {'url': _gn('"Suez Canal" OR "Red Sea" Egypt (shipping OR Houthi OR revenue)'), 'name': 'Google News', 'language': 'en'},
    'gn_bread':  {'url': _gn('Egypt (IMF OR wheat OR bread OR pound OR deposits)'), 'name': 'Google News', 'language': 'en'},
    'gn_south':  {'url': _gn('Egypt (Sudan OR GERD OR Nile OR Ethiopia)'), 'name': 'Google News', 'language': 'en'},
    'gn_east':   {'url': _gn('Egypt (Israel OR Gaza OR Rafah OR Sinai OR Leviathan)'), 'name': 'Google News', 'language': 'en'},
    'gn_west':   {'url': _gn('Egypt (Libya OR Haftar)'), 'name': 'Google News', 'language': 'en'},
    'gn_ar_gulf':  {'url': _gn('مصر السعودية الحوثي', 'ar'), 'name': 'Google News AR', 'language': 'ar'},
    'gn_ar_south': {'url': _gn('مصر السودان سد النهضة', 'ar'), 'name': 'Google News AR', 'language': 'ar'},
    'gn_ar_east':  {'url': _gn('مصر إسرائيل رفح الغاز', 'ar'), 'name': 'Google News AR', 'language': 'ar'},
    'gn_ar_pres':  {'url': _gn('السيسي', 'ar'), 'name': 'Google News AR', 'language': 'ar'},
    'gn_ar_libya': {'url': _gn('مصر ليبيا حفتر', 'ar'), 'name': 'Google News AR', 'language': 'ar'},
}

GDELT_QUERIES = [
    ('Egypt (Saudi OR Houthi OR "Mecca pact")', 'eng'),
    ('"Suez Canal" OR ("Red Sea" Egypt)', 'eng'),
    ('Egypt (Sudan OR GERD OR Nile)', 'eng'),
    ('Egypt (Israel OR Rafah OR Sinai OR gas)', 'eng'),
    ('Egypt (Libya OR Haftar)', 'eng'),
    ('مصر السيسي', 'ara'),
]

NEWSAPI_QUERIES = [
    'Egypt (Saudi OR Houthi OR Sudan OR Libya OR Israel)',
    'Egypt (IMF OR wheat OR "Suez Canal" OR GERD)',
]

_SOURCE_HEALTH = {}


def _reset_health():
    _SOURCE_HEALTH.clear()
    _SOURCE_HEALTH.update({
        'rss': {'feeds': 0, 'feeds_ok': 0, 'articles': 0, 'failed': []},
        'gdelt': {'queries': 0, 'sensed': 0, 'articles': 0, 'not_sensed': {}},
        'newsapi': {'queries': 0, 'sensed': 0, 'articles': 0, 'not_sensed': {}},
    })


def _rss_too_old(e):
    st = e.get('published_parsed') or e.get('updated_parsed')
    if not st:
        return False
    try:
        return (datetime.now(timezone.utc) - datetime(*st[:6], tzinfo=timezone.utc)) > timedelta(days=RSS_MAX_AGE_DAYS)
    except Exception:
        return False


def fetch_rss(fid, cfg, max_articles=40):
    h = _SOURCE_HEALTH['rss']
    h['feeds'] += 1
    if not FEEDPARSER_AVAILABLE:
        h['failed'].append(fid)
        return []
    out = []
    try:
        feed = feedparser.parse(cfg['url'], agent=HTTP_HEADERS['User-Agent'])
        for e in (feed.entries or [])[:max_articles]:
            if _rss_too_old(e):
                continue
            out.append({'title': (e.get('title') or '').strip(),
                        'description': re.sub(r'<[^>]+>', ' ', e.get('summary', '') or '')[:400],
                        'url': e.get('link', ''), 'published': e.get('published', '') or e.get('updated', ''),
                        'source': cfg['name'], 'feed_id': fid, 'feed_type': 'rss',
                        'language': cfg.get('language', 'en')})
        if out:
            h['feeds_ok'] += 1
        else:
            h['failed'].append(fid)
    except Exception as e:
        h['failed'].append(fid)
        print(f'[Egypt Rhetoric] RSS {fid} error: {str(e)[:100]}')
    h['articles'] += len(out)
    return out


def fetch_gdelt(query, language, days=WINDOW_DAYS):
    h = _SOURCE_HEALTH['gdelt']
    if not _GDELT_GATEWAY:
        h['not_sensed']['no_gateway'] = h['not_sensed'].get('no_gateway', 0) + 1
        return []
    h['queries'] += 1
    q = f'{query} sourcelang:english' if language == 'eng' else query
    try:
        raw, probe = _gw_fetch_probed(q, language=language, timespan=f'{days}d', maxrecords=50,
                                      label='egypt_rhet/' + language)
    except Exception as e:
        h['not_sensed']['exception'] = h['not_sensed'].get('exception', 0) + 1
        print(f'[Egypt Rhetoric] GDELT error: {str(e)[:100]}')
        return []
    if (probe or {}).get('sensed'):
        h['sensed'] += 1
    else:
        r = (probe or {}).get('reason') or 'unknown'
        h['not_sensed'][r] = h['not_sensed'].get(r, 0) + 1
    out = [{'title': it.get('title', ''), 'description': '', 'url': it.get('url', ''),
            'published': it.get('published', '') or it.get('seendate', ''),
            'source': it.get('source') or it.get('domain') or 'GDELT', 'feed_id': 'gdelt',
            'feed_type': 'gdelt', 'language': 'ar' if language == 'ara' else 'en'} for it in (raw or [])]
    h['articles'] += len(out)
    return out


def fetch_newsapi(query, days=WINDOW_DAYS, have=None):
    h = _SOURCE_HEALTH['newsapi']
    if _newsapi_gw is None:
        h['not_sensed']['no_gateway'] = h['not_sensed'].get('no_gateway', 0) + 1
        return []
    h['queries'] += 1
    try:
        raw, probe = _newsapi_gw(query, days=days, page_size=30, label='egypt_rhet/' + str(h['queries']), have=have)
    except Exception as e:
        raw, probe = [], {'sensed': False, 'reason': 'exception:' + type(e).__name__}
    if (probe or {}).get('sensed'):
        h['sensed'] += 1
    else:
        r = (probe or {}).get('reason') or 'unknown'
        h['not_sensed'][r] = h['not_sensed'].get(r, 0) + 1
    out = [{'title': it.get('title', '') or '', 'description': it.get('description', '') or '',
            'url': it.get('url', ''), 'published': it.get('publishedAt', ''),
            'source': (it.get('source') or {}).get('name', 'NewsAPI'), 'feed_id': 'newsapi',
            'feed_type': 'newsapi', 'language': 'en'} for it in (raw or [])]
    h['articles'] += len(out)
    return out


def _norm_title(t):
    t = re.sub(r'\s+-\s+[^-]{2,60}$', '', t or '')
    return re.sub(r'[^\w؀-ۿ]+', ' ', t.lower()).strip()


def _source_key(a):
    """Publisher identity for corroboration ('Ahram Online', 'Reuters'...)."""
    t = a.get('title') or ''
    m = re.search(r'\s-\s([^-]{2,60})$', t)
    if m and a.get('feed_type') == 'rss':
        return m.group(1).strip().lower()
    return (a.get('source') or a.get('feed_id') or '?').strip().lower()


def gather_articles(days=WINDOW_DAYS):
    _reset_health()
    arts = []
    for fid, cfg in RSS_FEEDS.items():
        arts.extend(fetch_rss(fid, cfg))
    if _trickle_register and _GDELT_GATEWAY:
        try:
            _trickle_register('egypt_rhetoric', [
                {'query': (f'{q} sourcelang:english' if l == 'eng' else q), 'language': l,
                 'timespan': f'{days}d', 'maxrecords': 50} for q, l in GDELT_QUERIES])
        except Exception as e:
            print(f'[Egypt Rhetoric] trickle registration failed (non-fatal): {str(e)[:80]}')
    for q, l in GDELT_QUERIES:
        arts.extend(fetch_gdelt(q, l, days))
    have = len(arts)
    for q in NEWSAPI_QUERIES:
        arts.extend(fetch_newsapi(q, days, have=have))
    seen_u, seen_t, out = set(), set(), []
    for a in arts:
        u = (a.get('url') or '').split('?')[0]
        t = _norm_title(a.get('title'))
        if not t or (u and u in seen_u) or t in seen_t:
            continue
        if u:
            seen_u.add(u)
        seen_t.add(t)
        out.append(a)
    return out


# ============================================================
# REDIS
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
        print(f'[Egypt Rhetoric] Redis GET error ({key}): {str(e)[:100]}')
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
        print(f'[Egypt Rhetoric] Redis SET error ({key}): {str(e)[:100]}')
        return False


def _redis_lpush_trim(key, value, max_len=336):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        hdr = {'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'}
        r = requests.post(f'{UPSTASH_REDIS_URL}/lpush/{key}', headers=hdr,
                          data=json.dumps(value, default=str), timeout=8)
        if r.status_code != 200:
            return False
        requests.post(f'{UPSTASH_REDIS_URL}/ltrim/{key}/0/{max_len - 1}', headers=hdr, timeout=8)
        return True
    except Exception as e:
        print(f'[Egypt Rhetoric] Redis LPUSH error ({key}): {str(e)[:100]}')
        return False


# ============================================================
# NEIGHBOUR LENSES (read, never re-scan)
# ============================================================
# Redis first (same Upstash across backends), then the public endpoint. Each
# lens reports where it was read from, or that it was not read.
LENS_SOURCES = {
    'sudan': {'keys': ['rhetoric:sudan:latest', 'sudan_rhetoric_cache'],
              'url': 'https://asifah-africa-backend.onrender.com/api/rhetoric/sudan'},
    'libya': {'keys': ['rhetoric:libya:latest', 'libya_rhetoric_cache'],
              'url': 'https://asifah-backend.onrender.com/api/rhetoric/libya'},
    'saudi': {'keys': ['rhetoric:saudi_arabia:latest'],
              'url': 'https://asifah-backend.onrender.com/api/rhetoric/saudi_arabia'},
    'yemen': {'keys': ['yemen_rhetoric_cache', 'rhetoric:yemen:latest'], 'url': None},
    'stability': {'keys': ['egypt:stability:fingerprint'], 'url': None},
}


def _http_json(url, timeout=12):
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def read_lens(name):
    src = LENS_SOURCES[name]
    for k in src['keys']:
        v = _redis_get(k)
        if isinstance(v, dict) and v:
            return v, 'redis:' + k
    if src.get('url'):
        v = _http_json(src['url'])
        if isinstance(v, dict) and v and v.get('success', True) is not False:
            return v, 'http'
    return None, None


def _int(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _scan_age_hours(d):
    for f in ('scanned_at', 'scan_date', 'timestamp', 'cached_at', 'written_at'):
        v = d.get(f) if isinstance(d, dict) else None
        if v:
            try:
                return round((datetime.now(timezone.utc) - datetime.fromisoformat(str(v).replace('Z', '+00:00'))).total_seconds() / 3600, 1)
            except Exception:
                continue
    return None


def build_lenses():
    """Front -> [lens dict]. Each lens: name, read, level (0-3 context), text, age_h."""
    lenses = {f: [] for f in FRONTS}

    sd, how = read_lens('sudan')
    if sd:
        vl = sd.get('vector_levels') or {}
        pat = (sd.get('patron_subtags') or {}).get('egypt')
        lvl = _int(sd.get('theatre_escalation_level') or sd.get('theatre_level'))
        egypt_named = _int(vl.get('saf_patron')) or (pat or 0)
        txt = (f"Sudan tracker reads L{lvl} ({sd.get('theatre_label') or ''}); SAF-patron vector L{_int(vl.get('saf_patron'))}"
               f", Egypt patron subtag {pat if pat is not None else 'n/a'}, southern spillover L{_int(vl.get('spillover_south'))}.")
        lenses['southern_flank'].append({'name': 'Sudan tracker', 'read': how, 'age_h': _scan_age_hours(sd),
                                         'level': min(2, 2 if egypt_named else (1 if lvl >= 3 else 0)), 'text': txt,
                                         'theatre_level': lvl})
    else:
        lenses['southern_flank'].append({'name': 'Sudan tracker', 'read': None, 'level': 0,
                                         'text': 'Sudan tracker not read this cycle -- unread, not quiet.'})

    ly, how = read_lens('libya')
    if ly:
        act = (ly.get('actors') or {}).get('egypt_uae_libya') or {}
        lvl = _int(ly.get('theatre_level') or ly.get('theatre_escalation_level'))
        oil = ly.get('oil_pulse_status')
        silent = bool(act.get('silence_alert'))
        txt = (f"Libya tracker reads L{lvl} ({ly.get('theatre_label') or ly.get('theatre_escalation_label') or ''}); "
               f"Egypt+UAE actor L{_int(act.get('escalation_level'))} with {_int(act.get('statement_count'))} statements"
               f"{' (silence alert)' if silent else ''}; oil pulse: {oil or 'unread'}.")
        lenses['western_flank'].append({'name': 'Libya tracker', 'read': how, 'age_h': _scan_age_hours(ly),
                                        'level': min(2, max(_int(act.get('escalation_level')), 1 if oil in ('force_majeure', 'blockade') else 0)),
                                        'text': txt, 'theatre_level': lvl, 'egypt_silent': silent, 'oil_pulse': oil})
    else:
        lenses['western_flank'].append({'name': 'Libya tracker', 'read': None, 'level': 0,
                                        'text': 'Libya tracker not read this cycle -- unread, not quiet.'})

    sa, how = read_lens('saudi')
    if sa:
        eg = (sa.get('actors') or {}).get('egypt_support') or {}
        mp = sa.get('mecca_pact') or {}
        lanes = mp.get('lanes') or {}
        # Saudi v2.3.0 nests the counts: {'stories': n, 'lanes': {'defence': n, ...}}
        if isinstance(lanes.get('lanes'), dict):
            lanes = lanes['lanes']

        def _n(v):
            if isinstance(v, dict):
                return v.get('count', v.get('stories', len(v)))
            if isinstance(v, (list, tuple)):
                return len(v)
            return v
        lane_txt = ', '.join(f"{k} {_n(v)}" for k, v in lanes.items()) if lanes else 'lanes unread'
        txt = (f"Saudi tracker: egypt_support actor L{_int(eg.get('escalation_level'))} "
               f"({_int(eg.get('statement_count'))} statements); Mecca Pact lanes: {lane_txt}.")
        lenses['gulf_defence'].append({'name': 'Saudi tracker', 'read': how, 'age_h': _scan_age_hours(sa),
                                       'level': min(2, _int(eg.get('escalation_level'))), 'text': txt,
                                       'pact_note': mp.get('note') or mp.get('reading')})
    else:
        lenses['gulf_defence'].append({'name': 'Saudi tracker', 'read': None, 'level': 0,
                                       'text': 'Saudi tracker not read this cycle -- unread, not quiet.'})

    ym, how = read_lens('yemen')
    if ym:
        sc = _int(ym.get('theatre_score'))
        lenses['suez_red_sea'].append({'name': 'Yemen / Houthi tracker', 'read': how, 'age_h': _scan_age_hours(ym),
                                       'level': 1 if sc >= 40 else 0,
                                       'text': f"Yemen tracker theatre score {sc}/100 (Houthi posture; Red Sea threat context)."})
    else:
        lenses['suez_red_sea'].append({'name': 'Yemen / Houthi tracker', 'read': None, 'level': 0,
                                       'text': 'Yemen tracker not read this cycle -- unread, not quiet.'})

    st, how = read_lens('stability')
    if st:
        dims = st.get('dimensions') or {}

        def _d(k):
            return (dims.get(k) or {}).get('level') or 'unread'
        lenses['bread_balance'].append({
            'name': 'Egypt stability (conditions)', 'read': how, 'age_h': _scan_age_hours(st),
            'level': 1 if _d('macro_fx') in ('strained', 'acute') or _d('food_bread') in ('strained', 'acute') else 0,
            'text': (f"Conditions: macro {_d('macro_fx')}, food {_d('food_bread')}, energy {_d('energy_grid')}; "
                     f"stability {st.get('stability_score')}/100 ({st.get('stability_label')}); "
                     f"IMF programme expires in {st.get('days_to_imf_expiry')} days."),
            'days_to_imf_expiry': st.get('days_to_imf_expiry')})
        lenses['suez_red_sea'].append({'name': 'Egypt stability (conditions)', 'read': how, 'level': 0,
                                       'text': f"External revenue dimension reads {_d('external_rev')}."})
    else:
        lenses['bread_balance'].append({'name': 'Egypt stability (conditions)', 'read': None, 'level': 0,
                                        'text': 'Egypt stability fingerprint not read -- unread, not quiet.'})
    return lenses


# ============================================================
# CLASSIFICATION
# ============================================================
def _text(a):
    return f"{a.get('title') or ''} . {a.get('description') or ''}"


_SENT_SPLIT = re.compile(r'(?<=[.!?؟])\s+|\s+[—–]\s+|\s+-\s+(?=[A-Z])')


def _ladder_hit(front, text):
    """Highest ladder rung matched -> (level, phrase, hedged, claim). Level 0 if none."""
    best = (0, None, False, False)
    for sent in _SENT_SPLIT.split(text):
        for lvl, rx in front['ladder']:
            m = rx.search(sent)
            if not m:
                continue
            hedged = bool(_HEDGE_RX.search(sent[max(0, m.start() - 50):m.start()]))
            claim = bool(_CLAIM_VERB_RX.search(sent) and _CLAIMANT_RX.search(sent)) and not _CONFIRMS_RX.search(sent)
            eff = 1 if hedged else lvl
            if eff > best[0]:
                best = (eff, m.group(0)[:60], hedged, claim)
    return best


def classify(articles):
    egypt, skipped = [], 0
    fronts = {k: {'topic': [], 'hits': [], 'relief': [], 'mooted': []} for k in FRONTS}
    actors = {k: {'articles': [], 'max_level': 0, 'phrases': []} for k in ACTORS}
    for a in articles:
        txt = _text(a)
        if not _EGYPT_GATE.search(txt):
            continue
        egypt.append(a)
        if _COMMENTARY_RX.search(a.get('title') or ''):
            skipped += 1
            continue
        art_level = 0
        for fid, f in FRONTS.items():
            if not f['topic'].search(txt):
                continue
            ex = _LOCUS_EXCLUDED_FRONTS.get(fid)
            if ex is not None and ex.search(txt):
                continue
            fronts[fid]['topic'].append(a)
            lvl, phrase, hedged, claim = _ladder_hit(f, txt)
            if hedged and phrase:
                fronts[fid]['mooted'].append({'title': a.get('title'), 'url': a.get('url'), 'source': a.get('source'),
                                              'phrase': phrase})
            elif lvl >= 2:
                if claim:
                    lvl = min(lvl, 3)
                fronts[fid]['hits'].append({'level': lvl, 'phrase': phrase, 'claim': claim,
                                            'title': (a.get('title') or '')[:200], 'url': a.get('url'),
                                            'source': a.get('source'), 'source_key': _source_key(a),
                                            'published': a.get('published'), 'language': a.get('language')})
                art_level = max(art_level, lvl)
            if f['relief'].search(txt):
                fronts[fid]['relief'].append({'title': (a.get('title') or '')[:200], 'url': a.get('url'),
                                              'source': a.get('source')})
        for aid, act in ACTORS.items():
            if act['rx'].search(txt):
                actors[aid]['articles'].append(a)
                actors[aid]['max_level'] = max(actors[aid]['max_level'], art_level or 1)
    return egypt, fronts, actors, skipped


def score_front(fid, data, lenses, corpus_ok):
    f = FRONTS[fid]
    topic_n = len(data['topic'])
    hits = data['hits']
    by_level = {}
    for h in hits:
        lvl = h['level']
        if h['claim']:
            lvl = min(lvl, 3)
        by_level.setdefault(lvl, []).append(h)
    level, basis = 0, None
    for lvl in sorted(by_level, reverse=True):
        srcs = {h['source_key'] for h in by_level[lvl]}
        if lvl >= 3 and len(srcs) < 2:
            cand = lvl - 1
            if cand > level:
                level, basis = cand, f'single-source L{lvl} report held at L{cand} until corroborated'
            continue
        if lvl > level:
            level, basis = lvl, f'{len(by_level[lvl])} report(s) from {len(srcs)} source(s)'
        break
    if level == 0 and topic_n >= MIN_FRONT_TOPIC:
        level, basis = 1, f'{topic_n} on-topic articles, no escalation phrase'
    lens_level = max([l.get('level', 0) for l in lenses] or [0])
    if lens_level > level:
        level, basis = min(2, lens_level), 'neighbour lens (context, not an event in Egypt)'
    level = min(level, L_CEILING)
    sensed = corpus_ok or any(l.get('read') for l in lenses)
    if not sensed:
        level, basis = 0, 'not sensed'
    relief_n = len(data['relief'])
    score = min(100, sum(h['level'] * 6 for h in hits) + topic_n) if sensed else 0
    claims = [h for h in hits if h['claim']]
    ev = sorted(hits, key=lambda h: -h['level'])[:4]
    return {
        'id': fid, 'label': f['label'], 'icon': f['icon'], 'market': f['market'],
        'level': level, 'label_word': LEVEL_LABELS[level], 'color': LEVEL_COLORS[level],
        'sensed': sensed, 'basis': basis, 'score': score,
        'topic_articles': topic_n, 'escalation_reports': len(hits), 'relief_reports': relief_n,
        'mooted_reports': len(data['mooted']), 'claims': len(claims),
        'evidence': ev, 'relief': data['relief'][:2], 'mooted': data['mooted'][:2], 'lenses': lenses,
    }


def build_actor_summaries(actors, ceiling=L_CEILING):
    """Actor level = the highest rung its own reports reached, capped at the
    corroborated theatre level -- one actor's uncorroborated story cannot read
    hotter than the fronts it spoke on."""
    out = {}
    for aid, a in actors.items():
        cfg = ACTORS[aid]
        arts = sorted(a['articles'], key=lambda x: x.get('published') or '', reverse=True)
        lvl = min(a['max_level'], L_CEILING, max(ceiling, 1)) if arts else 0
        out[aid] = {
            'name': cfg['name'], 'flag': cfg['flag'], 'icon': cfg['icon'], 'role': cfg['role'],
            'side': cfg['side'], 'mode': cfg['mode'], 'statement_count': len(arts),
            'escalation_level': lvl, 'escalation_label': LEVEL_LABELS[lvl], 'escalation_color': LEVEL_COLORS[lvl],
            'top_articles': [{k: x.get(k) for k in ('title', 'url', 'source', 'published', 'language')} for x in arts[:5]],
        }
    return out


# ============================================================
# SIGNALS + INTERPRETATION
# ============================================================
_PT = {'gulf_defence': 'diplomatic', 'suez_red_sea': 'economic', 'bread_balance': 'economic',
       'southern_flank': 'diplomatic', 'eastern_flank': 'diplomatic', 'western_flank': 'diplomatic'}

_FRONT_SO_WHAT = {
    'gulf_defence': ("Cairo is defending its own canal revenue as much as Riyadh: Saudi crude rides "
                     "the Petroline to Yanbu and then Suez while Hormuz is shut. Sisi has ruled out "
                     "attacking Yemen, so the posture reads defensive -- a shield on Saudi soil, not a front."),
    'suez_red_sea': ("Every Red Sea incident is priced twice in Egypt: once in canal revenue, once in "
                     "the dollars that revenue would have brought the pound."),
    'bread_balance': ("The failure mode is fiscal first, street second: a shock lands on the subsidy "
                      "bill and the pound before it reaches the bakery queue."),
    'southern_flank': ("Egypt is the SAF's patron and the Nile's downstream state; Sudan's war and the "
                       "GERD question meet on the same border."),
    'eastern_flank': ("The treaty relationship is not only Rafah and Sinai -- it is the gas that keeps "
                      "Egypt's grid and fertilizer plants running."),
    'western_flank': ("Egypt backs Haftar's east; a Libyan oil shutdown or border incident reaches "
                      "Cairo through security and through the oil price."),
}


def build_signals(fronts):
    sigs = []
    for fid, fr in fronts.items():
        if not fr['sensed'] or fr['level'] < 2:
            continue
        lvl = fr['level']
        pt = 'kinetic' if (lvl >= 4 and fid != 'bread_balance') else _PT[fid]
        top = fr['evidence'][0] if fr['evidence'] else None
        lens_only = fr['basis'] and fr['basis'].startswith('neighbour lens')
        lead = (top['title'] if top else (fr['lenses'][0]['text'] if fr['lenses'] else ''))
        sigs.append({
            'category': f'egypt_{fid}', 'country': 'egypt', 'theatre': 'egypt', 'region': 'me',
            'level': lvl, 'priority': lvl * 3, 'pressure_type': pt,
            'icon': fr['icon'], 'color': fr['color'],
            'short_text': f"\U0001F1EA\U0001F1EC Egypt {fr['label']}: {LEVEL_LABELS[lvl]}"
                          + (' (neighbour context)' if lens_only else '') + f" -- {lead}"[:150],
            'long_text': (f"{fr['label']} front at L{lvl} ({fr['basis']}). "
                          + (f"Includes {fr['claims']} claim(s) not confirmed by Egypt. " if fr['claims'] else '')
                          + f"Market touched: {fr['market']}. {_FRONT_SO_WHAT[fid]}"),
            'claim_only': bool(fr['claims'] and fr['claims'] == fr['escalation_reports']),
        })
    sigs.sort(key=lambda s: -s['level'])
    return sigs


def build_interpretation(fronts, theatre_level, lenses_flat, corpus_ok):
    moving = sorted([f for f in fronts.values() if f['sensed'] and f['level'] >= 2], key=lambda f: -f['level'])
    if not corpus_ok and not moving:
        head = 'Egypt rhetoric not sensed this cycle -- too few articles to read the fronts.'
    elif moving:
        names = ', '.join(f"{f['label'].lower()} (L{f['level']})" for f in moving[:3])
        markets = '; '.join(f"{f['label']} -> {f['market']}" for f in moving[:3])
        head = f"Egypt's moving fronts: {names}. Markets touched: {markets}."
    else:
        head = "No Egyptian front above rhetoric this cycle; the crossroads is quiet on what was sensed."
    lines = [_FRONT_SO_WHAT[f['id']] for f in moving[:2]]
    gd = fronts.get('gulf_defence') or {}
    if gd.get('sensed'):
        lines.append("Mecca Pact lens: Egypt's commitment is authorised, defensive, and conditioned on "
                     "a Saudi request -- watch for the move from authorisation to deployment.")
    unread = [l['name'] for l in lenses_flat if not l.get('read')]
    if unread:
        lines.append('Not read this cycle (unread, not quiet): ' + ', '.join(sorted(set(unread))) + '.')
    watch = []
    for f in moving[:3]:
        if f['id'] == 'gulf_defence':
            watch.append('Egyptian deployment to Saudi Arabia confirmed by Cairo (not by Houthi claim)')
        elif f['id'] == 'suez_red_sea':
            watch.append('Canal transit and revenue figures from the SCA; any strike near Yanbu')
        elif f['id'] == 'bread_balance':
            watch.append('The final IMF review before 15 Dec; any bread or fuel price decision')
        elif f['id'] == 'southern_flank':
            watch.append('Fighting near the Egyptian border; GERD statements')
        elif f['id'] == 'eastern_flank':
            watch.append('Israeli gas flows to Egypt; Rafah status')
        elif f['id'] == 'western_flank':
            watch.append('Libyan oil force majeure; Egyptian statements on Haftar')
    return {
        'hub_question': "Which of Egypt's six fronts is moving, and which global market does it touch?",
        'so_what': {'factor': head, 'lines': lines, 'level': theatre_level},
        'watch': watch,
        'disclaimer': 'Convergence indicator, not a probability of action.',
    }


# ============================================================
# SCAN
# ============================================================
_scan_lock = threading.Lock()
_scan_running = {'active': False, 'started': None}


def scan_egypt_rhetoric(days=WINDOW_DAYS):
    t0 = time.time()
    now = datetime.now(timezone.utc)
    articles = gather_articles(days)
    egypt, fr_raw, act_raw, skipped = classify(articles)
    corpus_ok = len(egypt) >= MIN_CORPUS_SENSED
    lenses = build_lenses()
    fronts = {fid: score_front(fid, fr_raw[fid], lenses.get(fid, []), corpus_ok) for fid in FRONTS}
    theatre_level = max([f['level'] for f in fronts.values()] or [0]) if (corpus_ok or any(f['sensed'] for f in fronts.values())) else 0
    actors = build_actor_summaries(act_raw, theatre_level)
    sensed = corpus_ok or any(f['sensed'] and f['level'] >= 2 for f in fronts.values())
    score = min(100, round(sum(f['score'] for f in fronts.values()) / 3)) if sensed else 0
    signals = build_signals(fronts)
    lenses_flat = [l for ls in lenses.values() for l in ls]
    interp = build_interpretation(fronts, theatre_level, lenses_flat, corpus_ok)
    lang = {}
    for a in egypt:
        lang[a.get('language', 'en')] = lang.get(a.get('language', 'en'), 0) + 1
    payload = {
        'success': True, 'country': 'egypt', 'theatre': 'Egypt', 'flag': '\U0001F1EA\U0001F1EC',
        'version': MODULE_VERSION, 'scanned_at': now.isoformat(), 'timestamp': now.isoformat(),
        'scan_seconds': round(time.time() - t0, 1), 'window_days': days,
        'sensed': sensed,
        'theatre_level': theatre_level, 'theatre_escalation_level': theatre_level,
        'theatre_label': LEVEL_LABELS[theatre_level] if sensed else 'Not Sensed',
        'theatre_color': LEVEL_COLORS[theatre_level], 'theatre_score': score, 'rhetoric_score': score,
        'vector_levels': {fid: f['level'] for fid, f in fronts.items()},
        'fronts': fronts, 'actors': actors, 'top_signals': signals,
        'interpretation': interp,
        'total_articles': len(egypt), 'articles_classified': len(egypt),
        'coverage': {'articles_total': len(articles), 'articles_egypt': len(egypt), 'by_language': lang,
                     'skipped_commentary': skipped, 'min_corpus_sensed': MIN_CORPUS_SENSED,
                     'sources': dict(_SOURCE_HEALTH)},
        'articles': [{k: a.get(k) for k in ('title', 'url', 'source', 'published', 'language', 'feed_type')}
                     for a in egypt[:100]],
        'silence_anomalies': [], 'crosstheater_coordination': [],
        'disclaimer': 'This composite is a CONVERGENCE indicator, NOT a probability of action.',
    }
    _persist(payload)
    print(f"[Egypt Rhetoric] scan done: {len(egypt)}/{len(articles)} Egypt articles, theatre L{theatre_level}, "
          f"fronts {payload['vector_levels']}, {payload['scan_seconds']}s")
    return payload


def _persist(payload):
    _redis_set(REDIS_KEY_LATEST, payload, CACHE_TTL_HOURS * 3600)
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(payload, f, default=str)
    except Exception:
        pass
    _redis_lpush_trim(REDIS_KEY_HISTORY, {'scanned_at': payload['scanned_at'],
                                          'theatre_level': payload['theatre_level'],
                                          'theatre_score': payload['theatre_score'],
                                          'vector_levels': payload['vector_levels']})
    gd = payload['fronts'].get('gulf_defence', {})
    _redis_set(REDIS_KEY_FINGERPRINT, {
        'country': 'egypt', 'version': MODULE_VERSION, 'written_at': payload['scanned_at'],
        'theatre_level': payload['theatre_level'], 'front_levels': payload['vector_levels'],
        'gulf_defence': {'level': gd.get('level'), 'basis': gd.get('basis'), 'claims': gd.get('claims')},
        'sensed': payload['sensed'],
    }, FINGERPRINT_TTL_HOURS * 3600)


def load_cache():
    c = _redis_get(REDIS_KEY_LATEST)
    if c:
        return c
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _age_hours(p):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(p['scanned_at'])).total_seconds() / 3600
    except Exception:
        return None


def _run_scan_guarded():
    with _scan_lock:
        if _scan_running['active']:
            return False
        _scan_running.update(active=True, started=datetime.now(timezone.utc).isoformat())
    try:
        scan_egypt_rhetoric()
    except Exception as e:
        print(f'[Egypt Rhetoric] scan error: {e}')
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
            if _own('egypt_rhetoric_scan'):
                c = load_cache()
                age = _age_hours(c) if c else None
                if age is None or age >= REFRESH_HOURS:
                    _run_scan_guarded()
        except Exception as e:
            print(f'[Egypt Rhetoric] loop error: {e}')
        time.sleep(30 * 60)


def register_egypt_rhetoric_endpoints(app, start_background=True):
    from flask import jsonify, request

    @app.route('/api/rhetoric/egypt', methods=['GET', 'OPTIONS'])
    def api_egypt_rhetoric():
        if request.method == 'OPTIONS':
            return ('', 204)
        force = (request.args.get('refresh', '') or request.args.get('force', '')).lower() in ('true', '1', 'yes')
        cached = load_cache()
        if force or not cached:
            started = False
            if not _scan_running['active']:
                threading.Thread(target=_run_scan_guarded, daemon=True).start()
                started = True
            if not cached:
                return jsonify({'success': True, 'sensed': False, 'warming': True,
                                'rescan': 'started' if started else 'already_running',
                                'note': 'First scan running (about 1-2 minutes). Reload shortly.'}), 202
            cached = dict(cached)
            cached['rescan'] = 'started' if started else 'already_running'
        cached = dict(cached)
        cached['from_cache'] = True
        age = _age_hours(cached)
        cached['cache_age_hours'] = round(age, 2) if age is not None else None
        if age is not None and age >= CACHE_TTL_HOURS:
            cached['stale'] = True
        return jsonify(cached)

    @app.route('/api/rhetoric/egypt/debug', methods=['GET'])
    def api_egypt_rhetoric_debug():
        c = load_cache()
        return jsonify({'version': MODULE_VERSION, 'actors': list(ACTORS), 'fronts': list(FRONTS),
                        'rss_feeds': len(RSS_FEEDS), 'gdelt_queries': len(GDELT_QUERIES),
                        'newsapi_queries': len(NEWSAPI_QUERIES), 'feedparser': FEEDPARSER_AVAILABLE,
                        'gdelt_gateway': _GDELT_GATEWAY, 'newsapi_gateway': _newsapi_gw is not None,
                        'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
                        'cache_present': bool(c), 'scan_running': _scan_running,
                        'cache_age_hours': round(_age_hours(c), 2) if c and _age_hours(c) is not None else None,
                        'last_coverage': (c or {}).get('coverage')})

    print('[Egypt Rhetoric] Routes registered: /api/rhetoric/egypt, /debug')
    if start_background:
        threading.Thread(target=_background_loop, daemon=True, name='EgyptRhetoricBG').start()
        print(f'[Egypt Rhetoric] background loop started (first check in {INITIAL_SCAN_DELAY_SECONDS}s)')
