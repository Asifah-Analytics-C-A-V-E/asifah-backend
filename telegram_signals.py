"""
Telegram Signal Source for Asifah Analytics
v2.1.0 — September 21, 2026  (entity cache — the FloodWait fix)

Bridges Telethon (async) with Flask (sync) to pull messages
from monitored Telegram channels across theatres:
- Lebanon / Hezbollah
- Yemen / Houthi / Red Sea
- Syria / HTS / SDF / Druze
- Iraq / PMF / KRG
- Israel / IDF / Home Front
- Iran / IRGC / proxy network
- Libya / GNU-LNA / Africa Corps (Wagner)
- Extended OSINT / Regional

v2.1.0 CHANGES — ENTITY CACHE
-----------------------------
THE PROBLEM. Every sweep called client.get_entity(handle) for every channel.
With a handle string, that is a ResolveUsernameRequest — Telegram's most
tightly rate-limited call. The session is decoded fresh from
TELEGRAM_SESSION_BASE64 on each cold start, so Telethon's own entity cache
was thrown away on every deploy/restart. Result: ~199 resolutions per sweep
and an 11-hour FloodWait that silenced every theatre at once.

THE FIX. A handle only needs resolving ONCE. The answer (channel id +
access_hash) is stable for this account, so it is cached:
    L1  in-process dict              — free, dies on restart
    L2  Upstash  telegram:entity:*   — survives restarts, 30-day TTL
and the fetch uses InputPeerChannel(id, access_hash) directly. Steady state:
~0 resolutions per sweep.

GUARDRAILS.
  - FloodWaitError is caught, logged with its length, and remembered (in
    process AND in Upstash) so no worker keeps knocking. Cached channels
    keep fetching during a resolve-FloodWait; only NEW resolutions stop.
    A FloodWait on history itself stands the whole sweep down.
  - RESOLVE BUDGET (TELEGRAM_RESOLVE_BUDGET, default 30 per rolling HOUR,
    shared by every theatre fetch in the process) paces the first fill, so
    a cold cache warms over a few scans instead of tripping a FloodWait in
    one. Per-hour, not per-call: seven theatre fetches per scan would
    otherwise each get their own allowance.
  - Dead handles (username not occupied / invalid) are negatively cached
    for 7 days instead of being re-resolved every sweep.
  - A cached entry that stops working (channel went private, hash rejected)
    is dropped and re-resolved on a later sweep.
  - 'idfonline' removed everywhere (reported 404 since v2.0.0 — it was
    costing a resolution every sweep to learn nothing).
  - get_telegram_status() now reports 'entity_cache' counters, so
    "resolved" trending to zero is visible, not assumed.

v2.0.0 CHANGES
--------------
1. SOURCE TIER + LANGUAGE METADATA (CHANNEL_META).
   Every emitted message now carries `source_tier`, `source_lang`, and
   `channel`. Alignment is DISCLOSED, never excluded — an aligned channel
   is a primary instrument for rhetoric measurement and a weak input for
   event confirmation, and consumers cannot tell those apart without the
   tier field. Tiers:
       official     government / military official account
       wire         news agency
       mainstream   established outlet or named journalist
       aggregator   OSINT aggregation, mixed sourcing
       aligned      openly aligned with a party to the conflict
       state        state media of a party to the conflict
       unverified   not yet assessed — DO NOT weight until reviewed
2. 20 new channels added (3 of the submitted 22 were already present:
   AbuAliExpress, ClashReport, WarMonitors).
3. Duplicate handles removed from within lists (dedup already happened at
   fetch time, so this is hygiene, not a behaviour change).
4. `limit` now scales with hours_back — a 50-message cap silently truncated
   24h windows on high-volume channels like ClashReport.
5. New helpers: get_channel_meta(), channels_needing_verification(),
   get_language_coverage().

BACKWARD COMPATIBILITY: every existing export keeps its name, signature and
return shape. app.py:1177 and military_tracker.py:158 need no changes.

Usage:
    from telegram_signals import fetch_telegram_signals
    messages = fetch_telegram_signals(hours_back=24)
"""

import os
import json
import time
import asyncio
import base64
import threading
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:          # the cache degrades to in-process only
    requests = None

try:
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetHistoryRequest
    from telethon.tl.types import InputPeerChannel, InputPeerUser
    from telethon.errors import (FloodWaitError, UsernameNotOccupiedError,
                                 UsernameInvalidError)
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    print("[Telegram] ⚠️ telethon not installed — Telegram signals disabled")


# ========================================
# CONFIGURATION
# ========================================

TELEGRAM_API_ID   = os.environ.get('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.environ.get('TELEGRAM_API_HASH')
TELEGRAM_PHONE    = os.environ.get('TELEGRAM_PHONE')
SESSION_NAME      = 'asifah_session'

VERSION = '2.1.0'

# Per-channel message cap. Scales with the requested window so a 24h pull on
# a high-volume channel is not silently truncated at 50.
MSGS_PER_HOUR    = 4
MSG_LIMIT_MIN    = 50
MSG_LIMIT_MAX    = 200

# ---- v2.1.0 entity cache ----
ENTITY_TTL_SEC      = 30 * 24 * 3600   # id + access_hash are stable; refresh monthly
DEAD_TTL_SEC        = 7 * 24 * 3600    # a handle that does not exist, re-checked weekly
RESOLVE_BUDGET      = int(os.environ.get('TELEGRAM_RESOLVE_BUDGET', '30'))  # per rolling hour, whole process
RESOLVE_SPACING_SEC = 1.0              # breathe between live resolutions
FLOOD_KEY           = 'telegram:floodwait_until'

UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_URL')
               or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                 or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
REDIS_OK = bool(UPSTASH_URL and UPSTASH_TOKEN and requests is not None)


# ========================================
# CHANNEL METADATA  (tier + language)
# ========================================
# tier: official | wire | mainstream | aggregator | aligned | state | unverified
# lang: list of ISO-ish codes — en, he, ar, fa, ru, tr, ku
#
# 'aligned' and 'state' are NOT pejorative and NOT grounds for exclusion.
# Al-Mayadeen shifting register on Yemen is the closest open-source read on
# axis messaging available. The tier exists so a rhetoric tracker can treat
# that as signal while a stability sensor treats it as one input among many.
#
# 'unverified' means Claude could not establish ownership/output and Rachel
# has not yet reviewed it. These fetch normally but MUST NOT be weighted as
# corroboration until assessed. See channels_needing_verification().

CHANNEL_META = {
    # ---------- Official government / military ----------
    'idfofficial':        {'tier': 'official',   'lang': ['en'],       'note': 'IDF English official'},
    'avichay_adraee':     {'tier': 'official',   'lang': ['ar'],       'note': 'IDF Arabic spokesperson — evacuation warnings'},
    'pikudHaoref':        {'tier': 'official',   'lang': ['he'],       'note': 'Home Front Command official'},
    'tzevaadom_en':       {'tier': 'official',   'lang': ['en'],       'note': 'Tzeva Adom alert relay'},
    'CentcomOfficial':    {'tier': 'official',   'lang': ['en'],       'note': 'US CENTCOM'},
    'UNIFIL_Lebanon':     {'tier': 'official',   'lang': ['en', 'ar'], 'note': 'UNIFIL — 1701 enforcement signals'},
    'khamenei_ir':        {'tier': 'official',   'lang': ['fa', 'en'], 'note': 'Supreme Leader office'},
    'IRIranArmy':         {'tier': 'official',   'lang': ['fa'],       'note': 'Artesh — conventional military'},
    'Sepah_Pasdaran':     {'tier': 'official',   'lang': ['fa'],       'note': 'IRGC official'},
    'LANANews':           {'tier': 'official',   'lang': ['ar'],       'note': 'Libyan News Agency (candidate handle)'},

    # ---------- Wire services ----------
    'AJEnglish':          {'tier': 'wire',       'lang': ['en'],       'note': 'Al Jazeera English'},
    'anadoluagency':      {'tier': 'wire',       'lang': ['en', 'tr'], 'note': 'Anadolu — Turkish state newswire'},
    'IraqiNewsAgency':    {'tier': 'wire',       'lang': ['ar'],       'note': 'INA (handle needs verification)'},

    # ---------- Mainstream outlets / named journalists ----------
    'kann_news':          {'tier': 'mainstream', 'lang': ['he'],       'note': 'Kan — public broadcaster, Hebrew'},
    'channel14news':      {'tier': 'mainstream', 'lang': ['he'],       'note': 'Channel 14 — right-leaning, fast on military'},
    'IsraelHayomHeb':     {'tier': 'mainstream', 'lang': ['he'],       'note': 'Israel Hayom — settler/annexation signals'},
    'Yair_Altman_channel14': {'tier': 'mainstream', 'lang': ['he'],    'note': 'Yair Altman — northern front reporting'},
    'amitsegal':          {'tier': 'mainstream', 'lang': ['he'],       'note': 'NEW v2.0.0 — Amit Segal, political correspondent. Well-sourced and openly positioned; read as elite Israeli political signal, not neutral wire'},
    'LBCI_Lebanon':       {'tier': 'mainstream', 'lang': ['ar'],       'note': 'LBCI Lebanese broadcast'},
    'MTVLebanonNews':     {'tier': 'mainstream', 'lang': ['ar'],       'note': 'MTV Lebanon — Christian perspective'},
    'Lebanon_24':         {'tier': 'mainstream', 'lang': ['ar'],       'note': 'Lebanon24 — major Arabic news'},
    'lebanonkhabar':      {'tier': 'mainstream', 'lang': ['ar'],       'note': 'Lebanon Khabar — Arabic breaking'},
    'lebanonnews2':       {'tier': 'mainstream', 'lang': ['ar'],       'note': 'Lebanon News 2 — ground reporters'},
    'LebUpdate':          {'tier': 'mainstream', 'lang': ['en', 'ar'], 'note': 'Lebanese News and Updates'},
    'kurdistan24english': {'tier': 'mainstream', 'lang': ['en'],       'note': 'Kurdistan 24 — KRG/SDF'},
    'BasNewsKurdish':     {'tier': 'mainstream', 'lang': ['ku'],       'note': 'Bas News (handle needs verification)'},
    'YemenMonitor':       {'tier': 'mainstream', 'lang': ['ar', 'en'], 'note': 'Yemen Monitor'},
    'LibyaObserver':      {'tier': 'mainstream', 'lang': ['en'],       'note': 'Tripoli/GNU-leaning (candidate)'},
    'LibyaHerald':        {'tier': 'mainstream', 'lang': ['en'],       'note': 'Libya Herald (candidate)'},
    'AddressLibya':       {'tier': 'mainstream', 'lang': ['en', 'ar'], 'note': 'Address Libya (candidate)'},
    'libya218':           {'tier': 'mainstream', 'lang': ['ar'],       'note': '218 News (candidate)'},
    'RALee85':            {'tier': 'mainstream', 'lang': ['en'],       'note': 'Rob Lee — analyst'},

    # ---------- OSINT aggregators ----------
    'AbuAliExpress':      {'tier': 'aggregator', 'lang': ['he', 'ar'], 'note': 'Translates Arabic media into Hebrew — high value, Israeli vantage'},
    'osintisraelgroup':   {'tier': 'aggregator', 'lang': ['en'],       'note': 'Aggregates 50+ HE/AR channels into English'},
    'OSINTdefender':      {'tier': 'aggregator', 'lang': ['en'],       'note': 'RUMINT anchor'},
    'WarMonitors':        {'tier': 'aggregator', 'lang': ['en'],       'note': 'RUMINT anchor'},
    'ClashReport':        {'tier': 'aggregator', 'lang': ['en', 'tr'], 'note': 'RUMINT anchor — fast, Turkish-linked, accuracy varies'},
    'C_Military1':        {'tier': 'aggregator', 'lang': ['en'],       'note': 'Military activity aggregator'},
    'GeoPWatch':          {'tier': 'aggregator', 'lang': ['en'],       'note': 'Geopolitics Watch'},
    'rageintel':          {'tier': 'aggregator', 'lang': ['en'],       'note': 'High-volume kinetic OSINT'},
    'syrianinfowar':      {'tier': 'aggregator', 'lang': ['en', 'ar'], 'note': 'Syria conflict OSINT'},
    'nayaforiraq':        {'tier': 'aggregator', 'lang': ['ar'],       'note': 'Iraq/Levant coverage'},
    'PakistanMilitary':   {'tier': 'aggregator', 'lang': ['en'],       'note': 'Pakistan military updates'},

    # ---------- Openly aligned (a party to the conflict, or its bloc) ----------
    'QudsN':              {'tier': 'aligned',    'lang': ['ar', 'en'], 'note': 'Quds News Network — resistance axis'},
    'ManarNewsEN':        {'tier': 'aligned',    'lang': ['en'],       'note': 'Al-Manar EN — Hezbollah'},
    'almanarnews':        {'tier': 'aligned',    'lang': ['ar'],       'note': 'Al-Manar AR — Hezbollah, direct statements'},
    'almayadeenenglish':  {'tier': 'aligned',    'lang': ['en'],       'note': 'Al-Mayadeen EN — Iran axis'},
    'almayadeen':         {'tier': 'aligned',    'lang': ['ar'],       'note': 'NEW v2.0.0 — Al-Mayadeen Arabic, Beirut. Primary axis-messaging instrument; register shifts here are the signal'},
    'almasirah':          {'tier': 'aligned',    'lang': ['ar'],       'note': 'Al-Masirah — Houthi flagship (candidate)'},
    'almasirahnet':       {'tier': 'aligned',    'lang': ['ar'],       'note': 'Al-Masirah mirror (candidate)'},
    'ansarollah_ye':      {'tier': 'aligned',    'lang': ['ar'],       'note': 'Ansar Allah media — Saree statements (candidate)'},
    'sabayemen':          {'tier': 'aligned',    'lang': ['ar'],       'note': 'SABA — Houthi-controlled (candidate)'},
    'resistance_news':    {'tier': 'aligned',    'lang': ['en'],       'note': 'Resistance News Network'},
    'BisimchiMedia':      {'tier': 'aligned',    'lang': ['fa'],       'note': 'Frontline IRGC/axis operational'},
    'qods_com':           {'tier': 'aligned',    'lang': ['fa'],       'note': 'Quds Force affiliated'},
    'IntelSlava':         {'tier': 'aligned',    'lang': ['ru', 'en'], 'note': 'Russian-aligned multilingual OSINT'},
    'rybar_force':        {'tier': 'aligned',    'lang': ['ru'],       'note': 'Rybar — Russian milblogger (candidate)'},
    'grey_zone':          {'tier': 'aligned',    'lang': ['ru'],       'note': 'Wagner-linked (candidate, may be banned)'},
    'afrinz_ru':          {'tier': 'aligned',    'lang': ['ru'],       'note': 'African Initiative — Russian info-op agency (candidate)'},
    'almarsadlibya':      {'tier': 'aligned',    'lang': ['ar'],       'note': 'Al-Marsad — eastern/LNA-leaning (candidate)'},
    'LibyaAlAhrar':       {'tier': 'aligned',    'lang': ['ar'],       'note': 'Libya Al-Ahrar (candidate)'},
    'Middle_East_Spectator': {'tier': 'aligned', 'lang': ['en'],       'note': 'NEW v2.0.0 — pro-Russia/Iran framing aggregator'},
    'DDGeopolitics':      {'tier': 'aligned',    'lang': ['en'],       'note': 'NEW v2.0.0 — pro-Russia leaning geopolitics aggregator'},
    'SabrenNewss':        {'tier': 'aligned',    'lang': ['ar'],       'note': 'NEW v2.0.0 — appears to be Sabereen News, Iraqi PMF/axis. A prior handle spelling was removed from this file as unverified; treat as candidate'},

    # ---------- State media of a party ----------
    'PressTV':            {'tier': 'state',      'lang': ['en'],       'note': 'Iranian state English'},
    'tasnimnews_en':      {'tier': 'state',      'lang': ['en'],       'note': 'Tasnim EN — IRGC-affiliated'},
    'TasminNews':         {'tier': 'state',      'lang': ['fa'],       'note': 'Tasnim FA — IRGC-affiliated'},
    'FarsNewsAgency':     {'tier': 'state',      'lang': ['en'],       'note': 'Fars EN — IRGC-affiliated'},
    'farsna':             {'tier': 'state',      'lang': ['fa'],       'note': 'Fars FA — IRGC-affiliated'},
    'iribnews':           {'tier': 'state',      'lang': ['fa'],       'note': 'IRIB — state broadcaster'},
    'mashreghnews':       {'tier': 'state',      'lang': ['fa'],       'note': 'Mashregh — IRGC-affiliated hardline'},
    'mashreghnews_channel': {'tier': 'state',    'lang': ['fa'],       'note': 'Mashregh secondary'},
    'snntv':              {'tier': 'state',      'lang': ['fa'],       'note': 'SNN — Basij-linked, mobilization signals'},
    'nour_news':          {'tier': 'state',      'lang': ['fa'],       'note': 'Nour News — SNSC mouthpiece, highest-level signalling'},
    'EnglishAlam':        {'tier': 'state',      'lang': ['en'],       'note': 'Al-Alam EN — Iran state'},
    'IranianDiplomacy':   {'tier': 'state',      'lang': ['en'],       'note': 'Iran soft-power framing'},
    'sepah_cyberi_iran':  {'tier': 'state',      'lang': ['fa'],       'note': 'IRGC Cyber — EW/cyber signals'},
    'IraninArabic':       {'tier': 'state',      'lang': ['ar'],       'note': 'NEW v2.0.0 — Iranian Arabic-language output. Iran addressing the Arab world in Arabic: audience-targeting signal distinct from Farsi domestic messaging'},
    'IranIntl_En':        {'tier': 'state',      'lang': ['en'],       'note': 'Iran International — Saudi-funded, opposition-leaning. Aligned AGAINST Tehran; not a neutral counterweight'},
    'trtworld':           {'tier': 'state',      'lang': ['en'],       'note': 'TRT — Turkish state'},
    'roozplus_ir':        {'tier': 'state',      'lang': ['fa'],       'note': 'Rooz Plus — reformist aggregator, domestic mood'},
    'khabar_fouri':       {'tier': 'state',      'lang': ['fa'],       'note': 'Khabar Fouri — Persian breaking'},
    'rodast_omiddana':    {'tier': 'aligned',    'lang': ['fa'],       'note': 'Omid Dana — Farsi political commentary'},

    # ---------- UNVERIFIED — fetch, but DO NOT weight until assessed ----------
    # Language below is Rachel's own grouping from submission. Ownership,
    # output and reliability are NOT established. Claude did not guess.
    'saledesk1':            {'tier': 'unverified', 'lang': ['he'], 'note': 'NEW v2.0.0 — submitted as Israeli/Hebrew. Ownership unestablished'},
    'yediotnews25':         {'tier': 'unverified', 'lang': ['he'], 'note': 'NEW v2.0.0 — name suggests Yediot association; official status NOT confirmed'},
    'arabworld301news':     {'tier': 'unverified', 'lang': ['he'], 'note': 'NEW v2.0.0 — submitted as Hebrew; name suggests Arab-world coverage from an Israeli vantage. Unconfirmed'},
    'TheBigBadShadow':      {'tier': 'unverified', 'lang': ['he'], 'note': 'NEW v2.0.0 — submitted as Israeli/Hebrew. Unestablished'},
    'alexmehacarmel':       {'tier': 'unverified', 'lang': ['he'], 'note': 'NEW v2.0.0 — submitted as Israeli/Hebrew. Unestablished'},
    'danielamran3':         {'tier': 'unverified', 'lang': ['he'], 'note': 'NEW v2.0.0 — submitted as Israeli/Hebrew. Unestablished'},
    'myGplanet':            {'tier': 'unverified', 'lang': ['he'], 'note': 'NEW v2.0.0 — submitted as Israeli/Hebrew. Unestablished'},
    'ramreports':           {'tier': 'unverified', 'lang': ['he'], 'note': 'NEW v2.0.0 — submitted as Israeli/Hebrew. Unestablished'},
    'S0nia10':              {'tier': 'unverified', 'lang': ['ar'], 'note': 'NEW v2.0.0 — submitted as Arabic/Farsi. Unestablished'},
    'bombing156':           {'tier': 'unverified', 'lang': ['ar'], 'note': 'NEW v2.0.0 — submitted as Arabic/Farsi. Unestablished'},
    'StateMediaTeamsForums':{'tier': 'unverified', 'lang': ['ar'], 'note': 'NEW v2.0.0 — submitted as Arabic/Farsi. Name implies state-media aggregation; unestablished'},
    'Waffairsblog':         {'tier': 'unverified', 'lang': ['en'], 'note': 'NEW v2.0.0 — submitted as conflict/geopolitical. Unestablished'},
    'ourwardstoday':        {'tier': 'unverified', 'lang': ['en'], 'note': 'NEW v2.0.0 — submitted as conflict/geopolitical. Unestablished'},
    'TheLeaflet':           {'tier': 'unverified', 'lang': ['en'], 'note': 'NEW v2.0.0 — submitted as conflict/geopolitical. Unestablished'},
}

DEFAULT_META = {'tier': 'unverified', 'lang': ['en'], 'note': 'No metadata entry'}


def get_channel_meta(handle):
    """Tier/language for a handle. Case-insensitive (Telegram handles are)."""
    if handle in CHANNEL_META:
        return CHANNEL_META[handle]
    low = handle.lower()
    for k, v in CHANNEL_META.items():
        if k.lower() == low:
            return v
    return DEFAULT_META


def channels_needing_verification():
    """Handles that must NOT be treated as corroboration until reviewed."""
    return sorted(k for k, v in CHANNEL_META.items() if v['tier'] == 'unverified')


def get_language_coverage():
    """Channel counts by language and by tier — for the absence-honest read."""
    langs, tiers = {}, {}
    for v in CHANNEL_META.values():
        tiers[v['tier']] = tiers.get(v['tier'], 0) + 1
        for lg in v['lang']:
            langs[lg] = langs.get(lg, 0) + 1
    return {'by_language': dict(sorted(langs.items(), key=lambda x: -x[1])),
            'by_tier': dict(sorted(tiers.items(), key=lambda x: -x[1])),
            'total_channels': len(CHANNEL_META)}


# ========================================
# CHANNEL GROUPS
# ========================================

LEBANON_CHANNELS = [
    # Palestinian / Resistance axis breaking news
    'QudsN',
    # Israeli/IDF sources
    'idfofficial',
    'avichay_adraee',
    'AbuAliExpress',
    'kann_news',
    'channel14news',
    'amitsegal',            # NEW v2.0.0 — Hebrew elite political signal on the northern front
    'ramreports',           # NEW v2.0.0 — unverified
    'alexmehacarmel',       # NEW v2.0.0 — unverified
    'danielamran3',         # NEW v2.0.0 — unverified
    'arabworld301news',     # NEW v2.0.0 — unverified
    # Lebanese sources
    'ManarNewsEN',
    'almanarnews',
    'almayadeenenglish',
    'almayadeen',           # NEW v2.0.0 — Arabic original, not the EN edition
    'LBCI_Lebanon',
    'MTVLebanonNews',
    'nayaforiraq',
    'lebanonkhabar',
    'Lebanon_24',
    'LebUpdate',
    'lebanonnews2',
    'UNIFIL_Lebanon',
]


YEMEN_CHANNELS = [
    # Houthi / Ansar Allah
    'YemenMonitor',
    'QudsN',
    'almayadeenenglish',
    'almayadeen',           # NEW v2.0.0
    # Israeli/IDF — watching IDF actions against Houthis
    'avichay_adraee',
    'idfofficial',
    'AbuAliExpress',
    'kann_news',
    # Red Sea / Maritime OSINT
    'OSINTdefender',
    'WarMonitors',
    'ClashReport',
    'C_Military1',
    # Horn of Africa
    'AJEnglish',
    # US/CENTCOM
    'CentcomOfficial',
    # Arabic regional
    'ManarNewsEN',
    'IranIntl_En',
    'IraninArabic',         # NEW v2.0.0 — Iran addressing the Arab world on Yemen
    'rodast_omiddana',
    # Houthi PRIMARY Arabic sources
    # ⚠️ VERIFY HANDLES — Houthi channels are deplatformed frequently.
    'almasirah',
    'almasirahnet',
    'ansarollah_ye',
    'sabayemen',
]

SYRIA_CHANNELS = [
    'QudsN',
    'syrianinfowar',
    'kurdistan24english',
    'ManarNewsEN',
    'almayadeenenglish',
    'almayadeen',           # NEW v2.0.0
    # Israeli strikes in Syria
    'avichay_adraee',
    'idfofficial',
    'AbuAliExpress',
    'amitsegal',            # NEW v2.0.0
    # Druze / Suwayda watch
    'OSINTdefender',
    # Broader OSINT
    'WarMonitors',
    'ClashReport',
    'IntelSlava',
    'C_Military1',
    'Middle_East_Spectator',  # NEW v2.0.0 — aligned framing, useful as counter-vantage
    # Turkish/SNA watch
    'AJEnglish',
    'IranIntl_En',
]

IRAQ_CHANNELS = [
    'QudsN',
    # Iraqi state / official
    'IraqiNewsAgency',
    # PMF / Hashd al-Shaabi
    'almanarnews',
    'nayaforiraq',
    'SabrenNewss',          # NEW v2.0.0 — PMF/axis Arabic; replaces the unverified spelling removed earlier
    'StateMediaTeamsForums',  # NEW v2.0.0 — unverified
    # Kurdish / KRG
    'kurdistan24english',
    'BasNewsKurdish',
    # Iran nexus
    'IranIntl_En',
    'IraninArabic',         # NEW v2.0.0
    'ManarNewsEN',
    'almayadeenenglish',
    'almayadeen',           # NEW v2.0.0
    # CENTCOM / US forces in Iraq
    'CentcomOfficial',
    'OSINTdefender',
    'WarMonitors',
    'ClashReport',
]

LIBYA_CHANNELS = [
    # Proven multi-theatre OSINT
    'OSINTdefender',
    'WarMonitors',
    'ClashReport',
    'IntelSlava',
    'C_Military1',
    'AJEnglish',
    'GeoPWatch',
    'rageintel',
    'DDGeopolitics',        # NEW v2.0.0 — Russia-leaning, tracks Africa Corps framing

    # CLUSTER A: Libyan media — GNU/west + LNA/east
    # ⚠️ VERIFY HANDLES — Libyan outlet channels migrate.
    'LibyaObserver',
    'LibyaHerald',
    'AddressLibya',
    'LibyaAlAhrar',
    'libya218',
    'LANANews',
    'almarsadlibya',

    # CLUSTER B: Africa Corps / Wagner / Russia-in-Africa
    # ⚠️ VERIFY HANDLES — these migrate and are deplatformed often.
    'rybar_force',
    'grey_zone',
    'afrinz_ru',

    # CLUSTER C: Foreign-patron state media
    'trtworld',
    'anadoluagency',
]


ASIA_PACIFIC_CHANNELS = [
    'IntelSlava',
    'RALee85',
    'PakistanMilitary',
]

ISRAEL_CHANNELS = [
    # Alert channels — real-time rocket/missile alerts
    'tzevaadom_en',
    'pikudHaoref',
    # IDF / Military
    'idfofficial',
    'avichay_adraee',
    'Yair_Altman_channel14',
    'osintisraelgroup',
    'AbuAliExpress',
    'kann_news',
    'channel14news',
    # Israeli political
    'IsraelHayomHeb',
    'amitsegal',            # NEW v2.0.0 — coalition/War Cabinet signal, Hebrew
    # NEW v2.0.0 — Hebrew channels pending verification
    'saledesk1',
    'yediotnews25',
    'arabworld301news',
    'TheBigBadShadow',
    'alexmehacarmel',
    'danielamran3',
    'myGplanet',
    'ramreports',
    # Threat actors — inbound signals
    'ManarNewsEN',
    'almayadeenenglish',
    'almayadeen',           # NEW v2.0.0
    'QudsN',
    'SabrenNewss',          # NEW v2.0.0
    'WarMonitors',
    'ClashReport',
    'OSINTdefender',
    'IntelSlava',
    # West Bank / Palestinian civil signals
    'AJEnglish',
    'IranIntl_En',
    'rageintel',
]

IRAN_CHANNELS = [
    # Supreme Leader / Iranian government official
    'khamenei_ir',
    'IRIranArmy',
    # IRGC-affiliated / state media
    'tasnimnews_en',
    'FarsNewsAgency',
    'PressTV',
    'QudsN',
    'IraninArabic',         # NEW v2.0.0 — Iran's Arabic-language voice; audience-targeting signal
    # Proxy network — Hezbollah
    'ManarNewsEN',
    'almanarnews',
    'almayadeenenglish',
    'almayadeen',           # NEW v2.0.0
    # Proxy network — Houthi / Yemen
    'YemenMonitor',
    'WarMonitors',
    # Proxy network — Iraq PMF
    'nayaforiraq',
    'SabrenNewss',          # NEW v2.0.0
    # OSINT — Iran operations
    'OSINTdefender',
    'ClashReport',
    'IntelSlava',
    'Middle_East_Spectator',  # NEW v2.0.0
    # Israeli vantage on Iran — the fastest reporting on strikes inside Iran
    'AbuAliExpress',
    'kann_news',
    'amitsegal',            # NEW v2.0.0
    'ramreports',           # NEW v2.0.0 — unverified
    # Persian / domestic Iran signals
    'rodast_omiddana',
    'IranIntl_En',
    'EnglishAlam',
    'resistance_news',
    # CENTCOM / US response
    'CentcomOfficial',
    'IranianDiplomacy',
    # Persian-language state/IRGC sources
    'farsna',
    'iribnews',
    'mashreghnews',
    'mashreghnews_channel',
    'snntv',
    'TasminNews',
    'roozplus_ir',
    'khabar_fouri',
    # IRGC official and operational
    'Sepah_Pasdaran',
    'BisimchiMedia',
    'sepah_cyberi_iran',
    'qods_com',
    # Supreme National Security Council mouthpiece
    'nour_news',
    # OSINT
    'GeoPWatch',
    'rageintel',
]

EXTENDED_CHANNELS = [
    # Palestinian / Resistance axis breaking news
    'QudsN',
    # General conflict OSINT
    'C_Military1',
    'ClashReport',
    'WarMonitors',
    'OSINTdefender',
    # NEW v2.0.0 — global conflict / geopolitical
    'Waffairsblog',
    'ourwardstoday',
    'Middle_East_Spectator',
    'TheLeaflet',
    'DDGeopolitics',
    # Iranian sources
    'IranIntl_En',
    'IraninArabic',
    'rodast_omiddana',
    # Israeli sources
    'AbuAliExpress',
    'kann_news',
    'channel14news',
    'amitsegal',
    # Regional
    'almayadeenenglish',
    'almayadeen',
    'ManarNewsEN',
    'nayaforiraq',
    'S0nia10',
    'bombing156',
    # CENTCOM
    'CentcomOfficial',
    'rageintel',
]


# ========================================
# HELPERS
# ========================================

def _telegram_available():
    if not TELETHON_AVAILABLE:
        return False
    if not all([TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE]):
        print("[Telegram] ⚠️ Missing env vars (TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE)")
        return False
    return True


def _ensure_session_file():
    session_path = f'{SESSION_NAME}.session'
    if os.path.exists(session_path):
        return True
    session_b64 = os.environ.get('TELEGRAM_SESSION_BASE64')
    if session_b64:
        try:
            session_data = base64.b64decode(session_b64)
            with open(session_path, 'wb') as f:
                f.write(session_data)
            print(f"[Telegram] ✅ Session file decoded ({len(session_data)} bytes)")
            return True
        except Exception as e:
            print(f"[Telegram] ❌ Session decode error: {str(e)[:100]}")
            return False
    print("[Telegram] ⚠️ No session file and no TELEGRAM_SESSION_BASE64")
    return False


# ========================================
# ENTITY CACHE  (v2.1.0)
# ========================================
# L1 in-process, L2 Upstash. Values are small dicts:
#     {'type': 'channel'|'user', 'id': int, 'hash': int, 'at': epoch}
# or  {'dead': True, 'reason': str, 'at': epoch}   (negative cache)

_entity_l1 = {}
_ec_lock = threading.Lock()
_ec_stats = {
    'l1_hits': 0, 'redis_hits': 0, 'resolved': 0, 'dead_skipped': 0,
    'budget_skipped': 0, 'flood_skipped': 0, 'flood_waits': 0,
    'last_flood_seconds': 0, 'stale_dropped': 0, 'last_sweep': {},
}
_flood_until_local = 0.0
_resolve_times = []   # epoch of each live resolution in the last hour


def _budget_take():
    """Spend one resolution from the rolling-hour budget. False = none left."""
    now = time.time()
    with _ec_lock:
        _resolve_times[:] = [t for t in _resolve_times if now - t < 3600]
        if len(_resolve_times) >= RESOLVE_BUDGET:
            return False
        _resolve_times.append(now)
        return True


def _redis(cmd):
    """One Upstash REST command -> 'result' or None. Same shape as the gateways."""
    if not REDIS_OK:
        return None
    try:
        r = requests.post(UPSTASH_URL, headers={
            'Authorization': 'Bearer %s' % UPSTASH_TOKEN}, json=cmd, timeout=5)
        if r.ok:
            return (r.json() or {}).get('result')
    except Exception as e:
        print(f"[Telegram] entity cache redis error: {str(e)[:80]}")
    return None


def _ec_key(handle):
    return 'telegram:entity:' + handle.lower()


def _ec_bump(field, n=1):
    with _ec_lock:
        _ec_stats[field] = _ec_stats.get(field, 0) + n


def _ec_get(handle):
    """Cached record for a handle, or None. Never touches Telegram."""
    key = handle.lower()
    rec = _entity_l1.get(key)
    if rec:
        _ec_bump('l1_hits')
        return rec
    raw = _redis(['GET', _ec_key(handle)])
    if raw:
        try:
            rec = json.loads(raw)
            _entity_l1[key] = rec
            _ec_bump('redis_hits')
            return rec
        except Exception:
            pass
    return None


def _ec_put(handle, rec, ttl):
    _entity_l1[handle.lower()] = rec
    _redis(['SET', _ec_key(handle), json.dumps(rec), 'EX', int(ttl)])


def _ec_drop(handle):
    _entity_l1.pop(handle.lower(), None)
    _redis(['DEL', _ec_key(handle)])
    _ec_bump('stale_dropped')


def _record_from_peer(peer):
    """Turn a Telethon InputPeer into a cacheable record (or None)."""
    if isinstance(peer, InputPeerChannel):
        return {'type': 'channel', 'id': peer.channel_id,
                'hash': peer.access_hash, 'at': int(time.time())}
    if isinstance(peer, InputPeerUser):
        return {'type': 'user', 'id': peer.user_id,
                'hash': peer.access_hash, 'at': int(time.time())}
    return None


def _peer_from_record(rec):
    if rec.get('type') == 'channel':
        return InputPeerChannel(int(rec['id']), int(rec['hash']))
    if rec.get('type') == 'user':
        return InputPeerUser(int(rec['id']), int(rec['hash']))
    return None


def _flood_remaining():
    """Seconds left on a known ResolveUsername FloodWait (any worker's)."""
    global _flood_until_local
    now = time.time()
    if _flood_until_local > now:
        return int(_flood_until_local - now)
    raw = _redis(['GET', FLOOD_KEY])
    try:
        until = float(raw) if raw else 0.0
    except (TypeError, ValueError):
        until = 0.0
    if until > now:
        _flood_until_local = until
        return int(until - now)
    return 0


def _flood_set(seconds):
    global _flood_until_local
    until = time.time() + int(seconds)
    _flood_until_local = until
    _redis(['SET', FLOOD_KEY, str(until), 'EX', max(int(seconds), 1)])
    with _ec_lock:
        _ec_stats['flood_waits'] += 1
        _ec_stats['last_flood_seconds'] = int(seconds)


def get_entity_cache_stats():
    with _ec_lock:
        s = dict(_ec_stats)
    s['l1_size'] = len(_entity_l1)
    s['redis_ok'] = REDIS_OK
    s['resolve_budget_per_hour'] = RESOLVE_BUDGET
    now = time.time()
    s['resolve_budget_left'] = max(0, RESOLVE_BUDGET - len(
        [t for t in _resolve_times if now - t < 3600]))
    s['flood_wait_remaining_sec'] = _flood_remaining()
    return s


def _msg_limit(hours_back):
    """Scale the per-channel cap to the window (was a flat 50)."""
    return max(MSG_LIMIT_MIN, min(MSG_LIMIT_MAX, int(hours_back) * MSGS_PER_HOUR))


async def _async_fetch_messages(channels, hours_back=24):
    if not _ensure_session_file():
        return []

    messages = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    limit = _msg_limit(hours_back)

    try:
        client = TelegramClient(SESSION_NAME, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            print("[Telegram] ❌ Session not authorized — need to re-authenticate locally")
            await client.disconnect()
            return []

        # Deduplicate channels while preserving order (case-insensitive:
        # Telegram handles are not case-sensitive, so 'WarMonitors' and
        # 'warmonitors' are the same channel and must not be fetched twice).
        seen = set()
        unique_channels = []
        for ch in channels:
            key = ch.lower()
            if key not in seen:
                seen.add(key)
                unique_channels.append(ch)

        tier_counts = {}
        for ch in unique_channels:
            t = get_channel_meta(ch)['tier']
            tier_counts[t] = tier_counts.get(t, 0) + 1
        print(f"[Telegram] ✅ Connected, fetching from {len(unique_channels)} channels "
              f"(limit {limit}/channel) — tiers: {tier_counts}")

        # v2.1.0 -- per-sweep resolution accounting
        sweep = {'cached': 0, 'resolved': 0, 'dead': 0, 'budget_skipped': 0,
                 'flood_skipped': 0, 'fetched': 0}
        flood_left = _flood_remaining()
        if flood_left:
            print(f"[Telegram] ⏸ ResolveUsername FloodWait active ({flood_left}s left) "
                  f"— cached channels only this sweep")

        for channel in unique_channels:
            meta = get_channel_meta(channel)
            try:
                # ---- v2.1.0: cache first, resolve only when we must ----
                rec = _ec_get(channel)
                if rec and rec.get('dead'):
                    sweep['dead'] += 1
                    _ec_bump('dead_skipped')
                    continue
                entity = _peer_from_record(rec) if rec else None
                if entity is not None:
                    sweep['cached'] += 1
                else:
                    if flood_left:
                        sweep['flood_skipped'] += 1
                        _ec_bump('flood_skipped')
                        continue
                    if not _budget_take():
                        sweep['budget_skipped'] += 1
                        _ec_bump('budget_skipped')
                        continue
                    try:
                        entity = await client.get_input_entity(channel)
                    except FloodWaitError as fw:
                        _flood_set(fw.seconds)
                        flood_left = int(fw.seconds)
                        sweep['flood_skipped'] += 1
                        print(f"[Telegram] ⛔ FloodWait {fw.seconds}s on resolving @{channel} "
                              f"— no more resolutions until it clears; cached channels continue")
                        continue
                    except (UsernameNotOccupiedError, UsernameInvalidError, ValueError) as dead:
                        _ec_put(channel, {'dead': True, 'reason': type(dead).__name__,
                                          'at': int(time.time())}, DEAD_TTL_SEC)
                        sweep['dead'] += 1
                        print(f"[Telegram] @{channel}: handle does not resolve "
                              f"({type(dead).__name__}) — skipped for 7 days")
                        continue
                    sweep['resolved'] += 1
                    _ec_bump('resolved')
                    new_rec = _record_from_peer(entity)
                    if new_rec:
                        _ec_put(channel, new_rec, ENTITY_TTL_SEC)
                    await asyncio.sleep(RESOLVE_SPACING_SEC)

                history = await client(GetHistoryRequest(
                    peer=entity,
                    limit=limit,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0
                ))

                channel_count = 0
                for msg in history.messages:
                    if msg.date and msg.date.replace(tzinfo=timezone.utc) > since and msg.message:
                        messages.append({
                            'title': msg.message[:500],
                            'body': msg.message,
                            'url': f'https://t.me/{channel}/{msg.id}',
                            'published': msg.date.replace(tzinfo=timezone.utc).isoformat(),
                            'query': f'telegram_{channel}',
                            'source': f'Telegram @{channel}',
                            'views': getattr(msg, 'views', 0) or 0,
                            'forwards': getattr(msg, 'forwards', 0) or 0,
                            # --- v2.0.0 provenance fields (additive) ---
                            'channel': channel,
                            'source_tier': meta['tier'],
                            'source_lang': meta['lang'],
                        })
                        channel_count += 1

                sweep['fetched'] += 1
                print(f"[Telegram] @{channel}: {channel_count} messages "
                      f"[{meta['tier']}/{'+'.join(meta['lang'])}] (last {hours_back}h)")

            except FloodWaitError as fw:
                # A FloodWait on history itself: stop the whole sweep, do not
                # keep knocking channel after channel.
                _flood_set(fw.seconds)
                print(f"[Telegram] ⛔ FloodWait {fw.seconds}s fetching @{channel} "
                      f"— standing the sweep down")
                break
            except Exception as e:
                # A cached peer that no longer works (channel went private,
                # access_hash rejected) is dropped so a later sweep re-resolves.
                if rec and not rec.get('dead'):
                    _ec_drop(channel)
                    print(f"[Telegram] @{channel}: cached entity rejected — dropped for re-resolve")
                print(f"[Telegram] @{channel} error: {str(e)[:100]}")
                continue

        await client.disconnect()
        with _ec_lock:
            _ec_stats['last_sweep'] = dict(sweep, at=datetime.now(timezone.utc).isoformat())
        print(f"[Telegram] ✅ Total: {len(messages)} messages from {len(unique_channels)} channels "
              f"| entities: {sweep['cached']} cached, {sweep['resolved']} resolved, "
              f"{sweep['dead']} dead, {sweep['budget_skipped']} deferred (budget), "
              f"{sweep['flood_skipped']} deferred (FloodWait)")

    except Exception as e:
        print(f"[Telegram] ❌ Connection error: {str(e)[:200]}")
        try:
            await client.disconnect()
        except Exception:
            pass

    return messages


def _run_async(channels, hours_back):
    """Bridge async to sync, handling existing event loops."""
    try:
        asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, _async_fetch_messages(channels, hours_back))
            return future.result(timeout=120)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_async_fetch_messages(channels, hours_back))
        finally:
            loop.close()


# ========================================
# PUBLIC FETCH FUNCTIONS
# ========================================

def fetch_telegram_signals(hours_back=24, include_extended=True):
    """Lebanon-focused fetch. Also used as general fallback."""
    if not _telegram_available():
        return []
    channels = LEBANON_CHANNELS.copy()
    if include_extended:
        channels.extend(EXTENDED_CHANNELS)
        channels.extend(ASIA_PACIFIC_CHANNELS)
    try:
        return _run_async(channels, hours_back)
    except Exception as e:
        print(f"[Telegram] ❌ fetch_telegram_signals error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_yemen(hours_back=24):
    """Yemen / Houthi / Red Sea theatre fetch."""
    if not _telegram_available():
        return []
    try:
        return _run_async(YEMEN_CHANNELS.copy(), hours_back)
    except Exception as e:
        print(f"[Telegram/Yemen] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_syria(hours_back=24):
    """Syria / HTS / SDF / Druze / Israeli strikes theatre fetch."""
    if not _telegram_available():
        return []
    try:
        return _run_async(SYRIA_CHANNELS.copy(), hours_back)
    except Exception as e:
        print(f"[Telegram/Syria] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_iraq(hours_back=24):
    """Iraq theatre fetch — PMF/Hashd, KRG, ISF, Iran-Iraq nexus, CENTCOM."""
    if not _telegram_available():
        return []
    try:
        return _run_async(IRAQ_CHANNELS.copy(), hours_back)
    except Exception as e:
        print(f"[Telegram/Iraq] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_israel(hours_back=24):
    """
    Israel fetch — Tzeva Adom alerts, IDF ops, War Cabinet,
    inbound threat actors (Hezbollah/Hamas/Houthi/Iran),
    West Bank/annexation signals, US coordination.
    """
    if not _telegram_available():
        return []
    try:
        return _run_async(ISRAEL_CHANNELS.copy(), hours_back)
    except Exception as e:
        print(f"[Telegram/Israel] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_iran(hours_back=24):
    """
    Iran command node fetch — Supreme Leader, IRGC, state media,
    proxy network (Hezbollah/Houthi/PMF), domestic pressure signals,
    and Israeli/US response channels.
    Primary purpose: detect when Iran is activating or directing proxies.
    """
    if not _telegram_available():
        return []
    try:
        return _run_async(IRAN_CHANNELS.copy(), hours_back)
    except Exception as e:
        print(f"[Telegram/Iran] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_libya(hours_back=24):
    """
    Libya theatre fetch — GNU/Tripoli vs LNA/Haftar, Africa Corps (Wagner),
    Fezzan/south (Tebu-Tuareg-Arab + Sudan spillover), oil/NOC, migration,
    and the Russia-in-Africa node signals.
    """
    if not _telegram_available():
        return []
    try:
        return _run_async(LIBYA_CHANNELS.copy(), hours_back)
    except Exception as e:
        print(f"[Telegram/Libya] ❌ fetch error: {str(e)[:200]}")
        return []


# ========================================
# HEALTH CHECK
# ========================================

def get_telegram_status():
    return {
        'version': VERSION,
        'telethon_installed': TELETHON_AVAILABLE,
        'api_configured': bool(TELEGRAM_API_ID and TELEGRAM_API_HASH),
        'phone_configured': bool(TELEGRAM_PHONE),
        'session_available': os.path.exists(f'{SESSION_NAME}.session') or bool(os.environ.get('TELEGRAM_SESSION_BASE64')),
        'channels_lebanon': LEBANON_CHANNELS,
        'channels_yemen': YEMEN_CHANNELS,
        'channels_syria': SYRIA_CHANNELS,
        'channels_iraq': IRAQ_CHANNELS,
        'channels_iran': IRAN_CHANNELS,
        'channels_israel': ISRAEL_CHANNELS,
        'channels_libya': LIBYA_CHANNELS,
        'channels_extended': EXTENDED_CHANNELS,
        # --- v2.0.0 ---
        'coverage': get_language_coverage(),
        'needs_verification': channels_needing_verification(),
        # --- v2.1.0 ---
        'entity_cache': get_entity_cache_stats(),
        'ready': _telegram_available() and (
            os.path.exists(f'{SESSION_NAME}.session') or
            bool(os.environ.get('TELEGRAM_SESSION_BASE64'))
        )
    }
