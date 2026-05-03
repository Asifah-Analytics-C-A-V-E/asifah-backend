"""
========================================
BLUESKY — Middle East Signal Monitor (v1.0.0)
========================================
ME companion to bluesky_signals_wha.py and bluesky_signals_asia.py.

Bluesky's public AppView API (https://public.api.bsky.app) requires NO auth
and exposes a stable JSON endpoint at:
    /xrpc/app.bsky.feed.getAuthorFeed?actor={handle}&limit={N}

Returns the same article dict shape as RSS/GDELT/Telegram ingestion so the
ME backend's existing scoring pipeline works unchanged.

ARCHITECTURAL NOTE: Bluesky's ME presence is much thinner than WHA's. Most
regional governments, IDF, and militia accounts are X-native, not Bluesky-
native. govmirrors.com mirrors a subset of these to Bluesky. Native Bluesky
ME presence is mostly journalists, OSINT analysts, and a few diaspora voices.

Targets supported (ME backend tracker keys):
    lebanon, israel, iran, yemen, iraq, syria, oman
    Use ['*'] for accounts that are global (US executive, all-ME scope).

Conservative initial list — verified handles from WHA/Asia modules + handful
of additions. Handles that 404 in production should be commented out, not
silently dropped, so the next session can decide whether to find replacements.
"""

import requests
import time
from datetime import datetime, timezone, timedelta

# Public AppView — no auth required for read-only
BLUESKY_API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"

# Timeout for individual account fetches (seconds)
BLUESKY_TIMEOUT = 8

# ────────────────────────────────────────────────────────────────
# MIDDLE EAST ACCOUNT DIRECTORY
# ────────────────────────────────────────────────────────────────
# (handle, weight, targets[], description)
#
# handle:  Bluesky handle WITHOUT the @ prefix
#          e.g. "state-department.bsky.social"
#          govmirrors: "potus.govmirrors.com" (mirror of @POTUS)
#
# weight:  1.2 = head of state direct (Trump, Netanyahu, Iranian Supreme Leader)
#          1.1 = senior cabinet (SecState, SecDef, FMs)
#          1.0 = institutional / military command (CENTCOM, State Dept, IDF)
#          0.9 = analytical / OSINT / regional specialist
#          0.85 = partner/allied accounts, journalists
#
# targets: list of ME tracker keys this account is relevant to.
#          ME targets: lebanon, israel, iran, yemen, iraq, syria, oman
#          Use ['*'] for all ME targets (global USG / regional scope).
# ────────────────────────────────────────────────────────────────
BLUESKY_ACCOUNTS_ME = [
    # ── US Government — native Bluesky (global scope) ───────────
    ('state-department.bsky.social',    1.0, ['*'],
        'US State Department (official) — travel advisories, ME policy'),

    # ── US Government — govmirrors.com (X / Truth Social sourced) ──
    # Trump Truth Social mirroring is critical for ME — his posts on
    # Iran negotiations, Hormuz, Gaza, Lebanon are primary US signals.
    ('potus.govmirrors.com',            1.2, ['*'],
        'POTUS (X mirror) — White House executive statements'),
    ('realdonaldtrump.govmirrors.com',  1.2, ['*'],
        'Trump Truth Social (X mirror) — Iran/Israel/Lebanon/Hormuz statements; PRIMARY US signal source'),
    ('secdef.govmirrors.com',           1.1, ['*'],
        'US SecDef (X mirror) — CENTCOM posture, deployment signals to ME'),
    ('secrubio.govmirrors.com',         1.15, ['*'],
        'SecState Rubio (X mirror) — Iran hawkish line, Israel relations'),
    ('statedept.govmirrors.com',        0.9, ['*'],
        'StateDept (X mirror) — redundant with native, kept as backup'),

    # ── Regional Combatant Commands ─────────────────────────────
    ('centcom.govmirrors.com',          1.05, ['*'],
        'US CENTCOM (X mirror) — ME military posture, Red Sea, Iraq, Syria'),

    # ── Israeli Government / IDF (X mirrors) ────────────────────
    # Most likely valid based on naming conventions; comment out on 404
    ('idf.govmirrors.com',              1.1, ['israel', 'lebanon', 'iran', 'syria', 'yemen'],
        'IDF official (X mirror) — Israeli military operations across ME'),
    ('netanyahu.govmirrors.com',        1.2, ['israel', 'iran', 'lebanon', 'syria'],
        'Netanyahu (X mirror) — Israeli PM strategic statements'),
    ('israelmfa.govmirrors.com',        1.0, ['israel', 'iran', 'lebanon'],
        'Israel MFA (X mirror) — Israeli foreign ministry'),

    # ── OSINT aggregators (global, high signal) ─────────────────
    ('osintdefender.bsky.social',       0.9, ['*'],
        'OSINT Defender — global conflict monitoring, ME strikes/operations'),
    ('wartranslated.bsky.social',       0.8, ['*'],
        'WarTranslated — global military translation, often ME content'),

    # ── ME / Iran analytical accounts ──────────────────────────
    # Conservative additions; expand once we see what works in production.
    # NOTE: Native Bluesky ME presence is sparse — these are best-guesses
    # based on common naming patterns. 404s will appear in logs.
    ('iranintl.bsky.social',            0.95, ['iran', 'lebanon', 'iraq', 'syria'],
        'Iran International — Persian-language opposition outlet'),

    # ── Lebanese / Levant analytical ────────────────────────────
    # If you find native Bluesky handles for L'Orient Today, Naharnet,
    # Almanar, etc., add them here. Conservative seed list:
    ('almonitor.bsky.social',           0.85, ['*'],
        'Al-Monitor — ME policy analysis (if native Bluesky exists)'),
]


def fetch_bluesky_account(handle, weight=1.0, limit=20, timeout=BLUESKY_TIMEOUT):
    """
    Fetch recent posts from a single Bluesky account.

    Uses the public AppView API — no authentication required.
    Returns list of article dicts matching the ME backend schema.

    On 404 (handle doesn't exist) → logs and returns []
    On 429 (rate limit) → logs and returns []
    On network/parse error → logs and returns []
    """
    headers = {
        'User-Agent': 'AsifahAnalytics-ME/1.0 (+https://asifahanalytics.com)',
        'Accept': 'application/json',
    }
    params = {'actor': handle, 'limit': limit}

    try:
        resp = requests.get(BLUESKY_API, headers=headers, params=params, timeout=timeout)

        if resp.status_code == 404:
            # 404 means handle doesn't exist. Log once — we won't retry.
            print(f'[Bluesky ME] @{handle}: handle not found (404) — consider removing from list')
            return []
        if resp.status_code == 429:
            print(f'[Bluesky ME] @{handle}: rate-limited (429) — backing off')
            return []
        if resp.status_code != 200:
            print(f'[Bluesky ME] @{handle}: HTTP {resp.status_code}')
            return []

        data = resp.json()
        feed = data.get('feed', [])
        articles = []

        for item in feed:
            post = item.get('post', {})
            record = post.get('record', {})
            author = post.get('author', {})

            text = record.get('text', '') or ''
            if not text.strip():
                continue

            # Bluesky timestamps are ISO-8601 UTC
            pub = record.get('createdAt') or post.get('indexedAt') or ''

            # Construct canonical post URL from DID + rkey
            post_uri = post.get('uri', '')
            rkey = post_uri.rsplit('/', 1)[-1] if post_uri else ''
            url = f'https://bsky.app/profile/{handle}/post/{rkey}' if rkey else f'https://bsky.app/profile/{handle}'

            # Description = first 400 chars of text (Bluesky is short-form)
            desc = text[:400]

            articles.append({
                'title':       text[:200],
                'description': desc,
                'url':         url,
                'publishedAt': pub,
                'source':      {'name': f'Bluesky @{handle}'},
                'content':     text[:500],
                'language':    'en',
                'feed_type':   'bluesky',
                'source_weight_override': weight,
                '_bluesky_author':  author.get('displayName', handle),
            })

        if articles:
            print(f'[Bluesky ME] @{handle}: {len(articles)} posts')
        return articles

    except requests.exceptions.Timeout:
        print(f'[Bluesky ME] @{handle}: timeout after {timeout}s')
        return []
    except Exception as e:
        print(f'[Bluesky ME] @{handle}: {str(e)[:80]}')
        return []


def fetch_bluesky_for_target(target, days=7, max_posts_per_account=20):
    """
    Fetch Bluesky posts relevant to a specific ME target.

    Filters by:
      - target key (account must have '*' or target in its targets list)
      - recency (post must be within last {days} days)
      - deduplication (URL-based)

    Returns list of article dicts ready for downstream scoring.

    For Israel/Iran/Lebanon: govmirrors-based US executive content is
    primary, plus IDF/Netanyahu mirrors when active.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen_urls = set()
    accounts_queried = 0

    for handle, weight, targets, desc in BLUESKY_ACCOUNTS_ME:
        # Skip accounts not relevant to this target
        if '*' not in targets and target not in targets:
            continue

        accounts_queried += 1
        posts = fetch_bluesky_account(handle, weight=weight, limit=max_posts_per_account)

        for p in posts:
            if p['url'] in seen_urls:
                continue

            # Recency filter
            try:
                pub_str = p['publishedAt'].replace('Z', '+00:00')
                pub = datetime.fromisoformat(pub_str)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
            except Exception:
                # If date parsing fails, keep the post (better than losing signal)
                pass

            seen_urls.add(p['url'])
            all_posts.append(p)

        # Light politeness delay — Bluesky public API is fast but we
        # don't want to look abusive
        time.sleep(0.2)

    print(f'[Bluesky ME] {target}: {len(all_posts)} posts from {accounts_queried} accounts queried')
    return all_posts
