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
    'AvichayAdraee',       # IDF Arabic spokesperson — evacuation warnings
    'IDFSpokesperson',     # IDF English spokesperson
    'yaborached',          # Yair Altman — Hebrew, breaks IDF ops early
    'AbuAliExpress',       # Abu Ali Express — bilingual Hebrew/Arabic OSINT
    'kann_news',           # Kann News — Hebrew breaking alerts
    'channel14news',       # Channel 14 — right-leaning, fast on military
    'iaborached',          # i24 Hebrew news
    # Lebanese sources (Arabic)
    'AlManarTV',           # Hezbollah-affiliated media (Al Manar)
    'AlMayadeenNews',      # Al-Mayadeen — pro-resistance axis
    'LBCILebanon',         # LBCI — Lebanese news
    'MTVLebanonNews',      # MTV Lebanon — Christian perspective
    'Lebanon_News',        # Lebanese news aggregator
]

# Extended channels — regional OSINT + Iranian sources
EXTENDED_CHANNELS = [
    # Regional conflict monitoring (English/multilingual)
    'C_Military1',         # Conflict/military OSINT
    'Intel_Sky',           # Intel Sky — very active aggregator
    'ClashReport',         # Clash Report — conflict monitoring
    'WarMonitors',         # War Monitor — multilingual
    # Iranian sources
    'TassimNewsEN',        # Tasnim News Agency — English
    'preaborached',        # Press TV English
    # Lebanese military/political
    'maaborached',         # Lebanese military updates
    'GLZRadio',            # IDF radio — Galatz
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

    # Bridge async to sync
    try:
        # Check if there's already an event loop running
        try:
            loop = asyncio.get_running_loop()
            # We're inside an async context — shouldn't happen in Flask but handle it
            print("[Telegram] ⚠️ Event loop already running — using thread")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _async_fetch_messages(channels, hours_back))
                return future.result(timeout=60)
        except RuntimeError:
            # No running loop — normal case for Flask
            return asyncio.run(_async_fetch_messages(channels, hours_back))
    except Exception as e:
        print(f"[Telegram] ❌ fetch_telegram_signals error: {str(e)[:200]}")
        return []


def get_telegram_status():
    """Return status info for health check / debugging."""
    return {
        'telethon_installed': TELETHON_AVAILABLE,
        'api_configured': bool(TELEGRAM_API_ID and TELEGRAM_API_HASH),
        'phone_configured': bool(TELEGRAM_PHONE),
        'session_available': os.path.exists(f'{SESSION_NAME}.session') or bool(os.environ.get('TELEGRAM_SESSION_BASE64')),
        'channels': LEBANON_CHANNELS,
        'ready': _telegram_available() and (os.path.exists(f'{SESSION_NAME}.session') or bool(os.environ.get('TELEGRAM_SESSION_BASE64')))
    }
