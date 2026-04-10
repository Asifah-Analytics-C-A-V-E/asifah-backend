"""
Telegram Signal Source for Asifah Analytics
v1.1.0 — April 4, 2026

Bridges Telethon (async) with Flask (sync) to pull messages
from monitored Telegram channels across theatres:
- Lebanon / Hezbollah
- Yemen / Houthi / Red Sea
- Syria / HTS / SDF / Druze
- Extended OSINT / Regional

Usage:
    from telegram_signals import fetch_telegram_signals
    messages = fetch_telegram_signals(hours_back=24)
"""

import os
import asyncio
import base64
from datetime import datetime, timezone, timedelta

try:
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetHistoryRequest
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


# ========================================
# CHANNEL GROUPS
# ========================================

LEBANON_CHANNELS = [
    # Palestinian / Resistance axis breaking news
    'QudsN',                # Quds News Network — 722K subs, resistance-axis Arabic breaking news
    # Israeli/IDF sources
    'avichay_adraee',       # IDF Arabic spokesperson — evacuation warningsLEBANON_CHANNELS = [
    # Israeli/IDF sources
    'avichay_adraee',       # IDF Arabic spokesperson — evacuation warnings
    'idfonline',            # IDF English spokesperson
    'AbuAliExpress',        # Abu Ali Express — bilingual Hebrew/Arabic OSINT
    'kann_news',            # Kann News — Hebrew breaking alerts
    'channel14news',        # Channel 14 — right-leaning, fast on military
    # Lebanese sources — existing
    'ManarNewsEN',          # Al-Manar English (FIXED: was almanar_tv)
    'almanarnews',          # Al-Manar Arabic (FIXED: was almanar_tv)
    'almayadeenenglish',    # Al-Mayadeen English (FIXED: was almayadeen_net)
    'LBCI_Lebanon',         # LBCI — Lebanese broadcast news
    'MTVLebanonNews',       # MTV Lebanon — Christian perspective
    'nayaforiraq',          # Naya For Iraq — Iraq/Levant coverage
    # Lebanese sources — Arabic breaking news (NEW v1.2.0)
    'lebanonkhabar',        # Lebanon Khabar — Arabic breaking news, WhatsApp mirror source
    'Lebanon_24',           # Lebanon24 — major Arabic news channel, 2M+ followers
    'LebUpdate',            # Lebanese News and Updates — EN/AR mix, 75K subs, fast OSINT
    'lebanonnews2',         # Lebanon News 2 — Arabic, ground reporters across Lebanon
    'UNIFIL_Lebanon',       # UNIFIL official — bilingual, key for 1701 enforcement signals
    'almanarnews',          # Al-Manar Arabic (duplicate guard handled by dedup logic)
]

YEMEN_CHANNELS = [
    # Houthi / Ansar Allah
    'YemenMonitor',         # Yemen Monitor — conflict tracking
    'QudsN',                # Quds News Network -- covers Houthi/Yemen ops
    'almayadeenenglish',    # Al-Mayadeen -- Houthi resistance axis
    # Israeli/IDF — watching IDF actions against Houthis
    'avichay_adraee',       # IDF Arabic spokesperson
    'idfonline',            # IDF English
    'AbuAliExpress',        # Abu Ali Express — bilingual OSINT
    'kann_news',            # Kan News — Hebrew
    # Red Sea / Maritime OSINT
    'OSINTdefender',        # OSINT Defender — Red Sea attacks
    'WarMonitors',          # War Monitor — Houthi strikes
    'ClashReport',          # Clash Report — maritime incidents
    'C_Military1',          # C_Military1 — Houthi military activity
    # Horn of Africa
    'AJEnglish',            # Al Jazeera English — Somalia/Somaliland
    # US/CENTCOM
    'CentcomOfficial',      # CENTCOM — Red Sea operations
    # Arabic regional
    'almayadeenenglish',    # Al-Mayadeen — axis of resistance
    'ManarNewsEN',          # Al-Manar EN — Houthi operations
    'IranIntl_En',          # Iran International EN — Iran-Houthi nexus
    'rodast_omiddana',      # Omid Dana — Farsi political commentary
]


SYRIA_CHANNELS = [
    # Palestinian / Resistance axis breaking news
    'QudsN',                # Quds News Network — resistance-axis, covers Syria/Lebanon/Gaza nexus
    # Syria-specific OSINT
    'syrianinfowar',        # Syrian Information War — OSINT, conflict tracking
    # Syria News Now username invalid — removed
    # Kurdish / SDF coverage
    'kurdistan24english',   # Kurdistan 24 English — SDF/Kurdish affairs
    # HTS / Islamist monitoring
    'ManarNewsEN',          # Al-Manar — covers Syria/resistance axis
    'almayadeenenglish',    # Al-Mayadeen — HTS/Syria coverage
    # Israeli strikes in Syria
    'avichay_adraee',       # IDF Arabic — Israeli strike announcements
    'idfonline',            # IDF English
    'AbuAliExpress',        # Abu Ali Express — Israel/Syria OSINT
    # Druze / Suwayda watch
    'OSINTdefender',        # Covers southern Syria Israeli activity
    # Broader OSINT
    'WarMonitors',          # War Monitor — Syria factional clashes
    'ClashReport',          # Clash Report — Syria incidents
    'IntelSlava',           # Intel Slava — multilingual ME OSINT
    'C_Military1',          # C_Military1 — Syria military activity
    # Turkish/SNA watch
    'AJEnglish',            # Al Jazeera — Turkey/Syria coverage
    'IranIntl_En',          # Iran International — Iran proxies in Syria
]

IRAQ_CHANNELS = [
    # Palestinian / Resistance axis breaking news
    'QudsN',                # Quds News Network — resistance-axis, covers Iraq/PMF nexus
    # Iraqi state / official
    'IraqiNewsAgency',      # INA -- Iraqi News Agency (may need handle verification)
    # PMF / Hashd al-Shaabi
    # SabreenNews, kataibmedia, alwahdapress -- handles unverified, removed
    'almanarnews',          # Al-Manar Arabic -- militia/resistance axis coverage
    'nayaforiraq',          # Naya For Iraq — Iraq/Levant, covers PMF activity
    # Kurdish / KRG
    'kurdistan24english',   # Kurdistan 24 English — KRG, Peshmerga, Kirkuk tensions
    'BasNewsKurdish',       # Bas News -- Kurdish perspective (handle needs verification)
    # Shafaq_News -- handle unverified, removed
    # Iran nexus — IRGC/Quds Force direction of Iraqi militias
    'IranIntl_En',          # Iran International EN — Iran-PMF nexus
    'ManarNewsEN',          # Al-Manar EN — axis of resistance, Iraq ops
    'almayadeenenglish',    # Al-Mayadeen — resistance axis framing
    # CENTCOM / US forces in Iraq
    'CentcomOfficial',      # CENTCOM — US force protection, Iraq ops
    'OSINTdefender',        # OSINT Defender — US base strikes, drone attacks
    'WarMonitors',          # War Monitor — Iraqi militia strikes
    'ClashReport',          # Clash Report — Iraq incident tracking
]

ASIA_PACIFIC_CHANNELS = [
    'IntelSlava',           # Intel Slava — multilingual conflict OSINT
    'RALee85',              # Robert Lee — DPRK analyst
    'PakistanMilitary',     # Pakistan military updates
]

ISRAEL_CHANNELS = [
    # Tzeva Adom / Alert channels — real-time rocket/missile alerts
    'tzevaadom_en',         # Tzeva Adom English -- every Pikud HaOref alert in real time
    'pikudHaoref',          # Pikud HaOref official channel
    # IDF / Military
    'idfonline',            # IDF English spokesperson — official strike/ops announcements
    'avichay_adraee',       # IDF Arabic spokesperson — Arabic-language ops
    'Yair_Altman_channel14',  # Yair Altman — Channel 14, best Hebrew OSINT northern front + IDF
    'idfofficial',            # IDF Official English — primary IDF announcements channel
    'osintisraelgroup',       # OSINT Israel — aggregates 50+ Hebrew/Arabic channels in English
    'AbuAliExpress',        # Abu Ali Express — bilingual Hebrew/Arabic OSINT
    'kann_news',            # Kan News — Hebrew breaking, fast on military
    'channel14news',        # Channel 14 — right-leaning, fast on military ops
    # Israeli political — War Cabinet, annexation rhetoric
    'IsraelHayomHeb',       # Israel Hayom Hebrew -- settler/annexation signals
    # Threat actors — inbound signals
    'ManarNewsEN',          # Al-Manar English — Hezbollah ops against Israel
    'almayadeenenglish',    # Al-Mayadeen — resistance axis ops
    'QudsN',                # Quds News Network — Hamas/resistance signals
    'WarMonitors',          # War Monitor — strike tracking both directions
    'ClashReport',          # Clash Report — incident tracking
    'OSINTdefender',        # OSINT Defender — multi-threat tracking
    'IntelSlava',           # Intel Slava — multilingual ME OSINT
    # West Bank / Palestinian civil signals
    'AJEnglish',            # Al Jazeera — West Bank, settler violence coverage
    'IranIntl_En',          # Iran International — Iran-Israel nexus
]

IRAN_CHANNELS = [
    # Supreme Leader / Iranian government official
    'khamenei_ir',          # Khamenei official — supreme leader statements, fatwa language
    'IRIranArmy',           # Iranian Army official — conventional military statements
    # IRGC-affiliated / state media
    'tasnimnews_en',        # Tasnim News English — IRGC-affiliated, operation announcements
    'FarsNewsAgency',       # Fars News English — IRGC-affiliated, proxy coordination signals
    'PressTV',              # Press TV — Iranian state English, regime framing
    'QudsN',                # Quds News Network — resistance-axis, Iran-directed ops
    # Proxy network — Hezbollah
    'ManarNewsEN',          # Al-Manar English — Hezbollah operations, Iran-Hezbollah nexus
    'almanarnews',          # Al-Manar Arabic — direct Hezbollah/Iran statements
    'almayadeenenglish',    # Al-Mayadeen — axis of resistance framing
    # Proxy network — Houthi / Yemen
    'YemenMonitor',         # Yemen Monitor — Houthi operations
    'WarMonitors',          # War Monitor — Houthi/PMF strikes
    # Proxy network — Iraq PMF
    # SabreenNews, kataibmedia -- handles unverified, removed
    'almanarnews',          # Al-Manar Arabic -- IRGC proxy statements
    'nayaforiraq',          # Naya For Iraq — Iraq/Iran nexus
    # OSINT — Iran operations
    'OSINTdefender',        # OSINT Defender — Iran strikes, Operation True Promise tracking
    'ClashReport',          # Clash Report — Iran missile/drone operations
    'IntelSlava',           # Intel Slava — multilingual, Iran war coverage
    'AbuAliExpress',        # Abu Ali Express — Israeli perspective on Iran ops
    # Persian / domestic Iran signals
    'rodast_omiddana',      # Omid Dana — Farsi political commentary, domestic pressure signals
    'IranIntl_En',          # Iran International English — opposition/protest signals
    'EnglishAlam',          # Al-Alam English — Iran state, softer narrative framing
    'resistance_news',      # Resistance News Network — English, anti-war amplification
    # CENTCOM / US response
    'CentcomOfficial',      # CENTCOM — US strikes on Iran, force posture
    'kann_news',            # Kan News Hebrew — Israeli perspective on Iran
    'IranianDiplomacy',     # Iranian diplomacy narratives, soft power framing
    # ── NEW: Persian-language state/IRGC sources ──
    'farsna',               # Fars News Persian — IRGC-affiliated, Persian domestic signals (distinct from FarsNewsAgency EN)
    'iribnews',             # IRIB News — Islamic Republic Broadcasting, official state TV
    'mashreghnews',         # Mashregh News — IRGC-affiliated hardline outlet, operational signals
    'mashreghnews_channel', # Mashregh News secondary channel — broader coverage
    'snntv',                # SNN TV — Students News Network, Basij-linked, domestic mobilization signals
    'TasminNews',           # Tasmin News Persian — IRGC-affiliated Persian (complements tasnimnews_en EN)
    'roozplus_ir',          # Rooz Plus — reformist/news aggregator, domestic mood and dissent signals
    'khabar_fouri',         # Khabar Fouri — Persian breaking news, high-speed domestic signal
    # ── NEW: IRGC official and operational ──
    'Sepah_Pasdaran',       # IRGC official Telegram — direct Sepah/Pasdaran announcements
    'BisimchiMedia',        # Bisimchi Media — frontline IRGC/resistance axis operational coverage
    'sepah_cyberi_iran',    # IRGC Cyber Army — cyber operations, electronic warfare signals
    'qods_com',             # Qods (Jerusalem) — IRGC Quds Force affiliated outlet
    # ── NEW: Supreme National Security Council mouthpiece ──
    'nour_news',            # Nour News — SNSC mouthpiece, highest-level regime signaling
    # ── NEW: OSINT ──
    'GeoPWatch',            # Geopolitics Watch — OSINT, Iran regional operations tracking
]

EXTENDED_CHANNELS = [
    # Palestinian / Resistance axis breaking news
    'QudsN',                # Quds News Network — broad resistance-axis coverage
    # General conflict OSINT
    'C_Military1',
    'ClashReport',
    'WarMonitors',
    'OSINTdefender',
    # Iranian sources
    'IranIntl_En',          # Iran International English
    'rodast_omiddana',      # Omid Dana — Farsi commentary
    # Israeli sources (working ones only)
    'AbuAliExpress',        # Most reliable Israeli OSINT channel
    'kann_news',            # Kan News — Hebrew
    'channel14news',        # Channel 14
    # Regional
    'almayadeenenglish',
    'ManarNewsEN',
    'nayaforiraq',
    # CENTCOM
    'CentcomOfficial',
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


async def _async_fetch_messages(channels, hours_back=24):
    if not _ensure_session_file():
        return []

    messages = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    try:
        client = TelegramClient(SESSION_NAME, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            print("[Telegram] ❌ Session not authorized — need to re-authenticate locally")
            await client.disconnect()
            return []

        # Deduplicate channels while preserving order
        seen = set()
        unique_channels = []
        for ch in channels:
            if ch not in seen:
                seen.add(ch)
                unique_channels.append(ch)

        print(f"[Telegram] ✅ Connected, fetching from {len(unique_channels)} channels...")

        for channel in unique_channels:
            try:
                entity = await client.get_entity(channel)
                history = await client(GetHistoryRequest(
                    peer=entity,
                    limit=50,
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
                        })
                        channel_count += 1

                print(f"[Telegram] @{channel}: {channel_count} messages (last {hours_back}h)")

            except Exception as e:
                print(f"[Telegram] @{channel} error: {str(e)[:100]}")
                continue

        await client.disconnect()
        print(f"[Telegram] ✅ Total: {len(messages)} messages from {len(unique_channels)} channels")

    except Exception as e:
        print(f"[Telegram] ❌ Connection error: {str(e)[:200]}")
        try:
            await client.disconnect()
        except:
            pass

    return messages


def _run_async(channels, hours_back):
    """Bridge async to sync, handling existing event loops."""
    try:
        loop = asyncio.get_running_loop()
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


# ========================================
# HEALTH CHECK
# ========================================

def get_telegram_status():
    return {
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
        'channels_extended': EXTENDED_CHANNELS,
        'ready': _telegram_available() and (
            os.path.exists(f'{SESSION_NAME}.session') or
            bool(os.environ.get('TELEGRAM_SESSION_BASE64'))
        )
    }
