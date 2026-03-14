"""
Telegram Signal Source for Lebanon Security Situation Scanner
v1.0.0 — March 2026

Bridges Telethon (async) with Flask (sync) to pull messages
from monitored Telegram channels and feed them into the
security situation keyword scanner.

Channels monitored:
- @AvichayAdraee — IDF Arabic spokesperson (evacuation warnings)
- @IDFSpokesperson — IDF English spokesperson
- @Lebanon_News — Lebanese news aggregator
- @AlManarTV — Hezbollah-affiliated media
- @C_Military1 — Conflict/military OSINT

Usage:
    from telegram_signals import fetch_telegram_signals
    messages = fetch_telegram_signals(hours_back=24)
    # Returns list of dicts with 'title', 'url', 'published', 'query' keys
    # Compatible with scan_security_situation() article format
"""

import os
import asyncio
import base64
from datetime import datetime, timezone, timedelta

# Telethon import with graceful fallback
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

TELEGRAM_API_ID = os.environ.get('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.environ.get('TELEGRAM_API_HASH')
TELEGRAM_PHONE = os.environ.get('TELEGRAM_PHONE')
SESSION_NAME = 'asifah_session'

# Channels to monitor for Lebanon security situation
LEBANON_CHANNELS = [
    # Israeli/IDF sources (Hebrew + Arabic)
    'avichay_adraee',      # IDF Arabic spokesperson — evacuation warnings
    'idfonline',           # IDF English spokesperson
    'AbuAliExpress',       # Abu Ali Express — bilingual Hebrew/Arabic OSINT
    'kann_news',           # Kann News — Hebrew breaking alerts
    'channel14news',       # Channel 14 — right-leaning, fast on military
    # Lebanese sources (Arabic)
    'almanar_tv',          # Hezbollah-affiliated media (Al Manar)
    'almayadeen_net',      # Al-Mayadeen — pro-resistance axis
    'LBCI_Lebanon',        # LBCI — Lebanese news
    'MTVLebanonNews',      # MTV Lebanon — Christian perspective
    'nayaforiraq',         # Naya For Iraq — Iraq/Levant coverage
]

# Yemen / Red Sea / Horn of Africa channels
YEMEN_CHANNELS = [
    # Houthi / Ansar Allah
    'YemenMonitor',        # Yemen Monitor — conflict tracking
    'ansarallah_en',       # Ansar Allah English channel
    'almasirah_net',       # Al-Masirah TV — Houthi-affiliated media
    # Israeli sources — IDF actions against Houthis
    'avichay_adraee',      # IDF Arabic spokesperson (already in Lebanon)
    'idfonline',           # IDF English (already in Lebanon)
    'yair_altime',         # Yair Altman — Israeli military journalist
    'keshet12news',        # Channel 12 — Hebrew breaking
    'n12news',             # N12 — Hebrew
    'N12chat',             # N12 live breaking
    'kann_news',           # Kan News — Hebrew
    'glzradio',            # Galatz IDF radio
    # Red Sea / Maritime OSINT
    'OSINTdefender',       # OSINT Defender — covers Red Sea attacks
    'WarMonitors',         # War Monitor — covers Houthi strikes
    'ClashReport',         # Clash Report — maritime incidents
    'C_Military1',         # C_Military1 — Houthi military activity
    'IntelSky',            # Intel Sky — aggregator
    # Horn of Africa / Somaliland watch
    'AJEnglish',           # Al Jazeera English — Somalia/Somaliland coverage
    # US/CENTCOM
    'CentcomOfficial',     # CENTCOM — Red Sea operations
    # Arabic regional
    'almayadeen_net',      # Al-Mayadeen — axis of resistance coverage
    'almanar_tv',          # Al-Manar — covers Houthi operations
    'iranintl',            # Iran International — Iran-Houthi nexus
]

# Asia-Pacific channels — Taiwan Strait, Korean Peninsula, South/Central Asia
ASIA_PACIFIC_CHANNELS = [
    # Taiwan/China strait monitoring
    'IntelSlava',          # Intel Slava — multilingual conflict OSINT
    # Korean Peninsula
    'RALee85',             # Robert Lee — DPRK analyst
    # South/Central Asia
    'PakistanMilitary',    # Pakistan military updates
]

# Extended channels — regional OSINT + Iranian sources + Israel-specific
EXTENDED_CHANNELS = [
    # Regional conflict monitoring (English/multilingual)
    'C_Military1',         # Conflict/military OSINT
    'IntelSky',            # Intel Sky — very active aggregator
    'ClashReport',         # Clash Report — conflict monitoring
    'WarMonitors',         # War Monitor — multilingual
    'OSINTdefender',       # OSINT Defender — English, high signal
    'war_in_ukraine',      # Ukraine war updates
    'UkrWarReport',        # Ukraine military reporting
    # Iranian sources
    'IranIntl_En',         # Iran International — English
    'iranintl',            # Iran International — Farsi
    'manoto1',             # Manoto — Farsi opposition media
    'rodast_omiddana',     # Omid Dana — Farsi political commentary
    # Israel-specific
    'ynet_news',           # Ynet English breaking news
    'TimesofIsrael',       # Times of Israel
    'Aborached',           # Israeli security commentary
    'glzradio',            # IDF radio — Galatz
    'keshet12news',        # Keshet 12 News — Hebrew
    'n12news',             # Channel 12 News — Hebrew
    'N12chat',             # Channel 12 live chat/breaking — Hebrew
    # CENTCOM
    'CentcomOfficial',     # CENTCOM official
]


def _telegram_available():
    """Check if Telegram integration is fully configured."""
    if not TELETHON_AVAILABLE:
        return False
    if not all([TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE]):
        print("[Telegram] ⚠️ Missing environment variables (TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE)")
        return False
    return True


def _ensure_session_file():
    """Decode session file from base64 env var if needed."""
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
    
    print("[Telegram] ⚠️ No session file and no TELEGRAM_SESSION_BASE64 env var")
    return False


async def _async_fetch_messages(channels, hours_back=24):
    """
    Async function to fetch messages from Telegram channels.
    Returns list of messages in the format expected by scan_security_situation().
    """
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

        print(f"[Telegram] ✅ Connected, fetching from {len(channels)} channels...")

        for channel in channels:
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
                        # Convert to article format compatible with security scanner
                        messages.append({
                            'title': msg.message[:200],  # Use first 200 chars as "title"
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
        print(f"[Telegram] ✅ Total: {len(messages)} messages from {len(channels)} channels")

    except Exception as e:
        print(f"[Telegram] ❌ Connection error: {str(e)[:200]}")
        try:
            await client.disconnect()
        except:
            pass

    return messages


def fetch_telegram_signals(hours_back=24, include_extended=True):
    """
    Synchronous wrapper to fetch Telegram messages.
    Returns list of article-format dicts compatible with scan_security_situation().
    
    Args:
        hours_back: How many hours back to fetch (default 24)
        include_extended: Whether to include extended channel list
    
    Returns:
        List of dicts with keys: title, url, published, query, source, views, forwards
    """
    if not _telegram_available():
        print("[Telegram] Signals unavailable — skipping")
        return []

    channels = LEBANON_CHANNELS.copy()
    if include_extended:
        channels.extend(EXTENDED_CHANNELS)
        channels.extend(ASIA_PACIFIC_CHANNELS)

    # Bridge async to sync
    try:
        # Check if there's already an event loop running
        try:
            loop = asyncio.get_running_loop()
            print("[Telegram] ⚠️ Event loop already running — using thread")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _async_fetch_messages(channels, hours_back))
                return future.result(timeout=120)
        except RuntimeError:
            # No running loop — create a new one explicitly for thread safety
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_async_fetch_messages(channels, hours_back))
            finally:
                loop.close()
    except Exception as e:
        print(f"[Telegram] ❌ fetch_telegram_signals error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_yemen(hours_back=24):
    """
    Fetch Telegram signals specifically for Yemen/Houthi/Red Sea theatre.
    Pulls from YEMEN_CHANNELS — includes Houthi media, Israeli sources
    watching IDF actions against Houthis, Red Sea OSINT, and Horn of Africa.

    Returns list of article-format dicts compatible with rhetoric_tracker_yemen.py
    """
    if not _telegram_available():
        print("[Telegram/Yemen] Signals unavailable — skipping")
        return []

    channels = YEMEN_CHANNELS.copy()

    try:
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
    except Exception as e:
        print(f"[Telegram/Yemen] ❌ fetch error: {str(e)[:200]}")
        return []


def get_telegram_status():
    """Return status info for health check / debugging."""
    return {
        'telethon_installed': TELETHON_AVAILABLE,
        'api_configured': bool(TELEGRAM_API_ID and TELEGRAM_API_HASH),
        'phone_configured': bool(TELEGRAM_PHONE),
        'session_available': os.path.exists(f'{SESSION_NAME}.session') or bool(os.environ.get('TELEGRAM_SESSION_BASE64')),
        'channels_lebanon': LEBANON_CHANNELS,
        'channels_yemen': YEMEN_CHANNELS,
        'channels_extended': EXTENDED_CHANNELS,
        'ready': _telegram_available() and (os.path.exists(f'{SESSION_NAME}.session') or bool(os.environ.get('TELEGRAM_SESSION_BASE64')))
    }
